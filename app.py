from flask import Flask, request, render_template, redirect, url_for
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
import json
import os
import random

# --- MODÜLLER ---
import veritabani
from scrapers.trendyol_scraper import analyze_aspects_with_finetuned_model
from scrapers.trendyol_gemini_scraper import cek as trendyol_cek 
from scrapers.trendyol_gemini_scraper import analyze_batch_with_gemini 
from scrapers.n11_scraper import cek as n11_cek
from scrapers.veri_toplayici import topla as veri_toplayici_cek

app = Flask(__name__)

# Veritabanını başlat
veritabani.veritabani_baslat()

YORUM_LIMITI_ANALIZ = 500
YORUM_LIMITI_TOPLA = 500
JSON_DOSYA_YOLU = "yorumlar.json"
ETIKET_DOSYA_YOLU = "etiketler.json"

# --- CORE FONKSİYONLAR (AYNEN KORUNDU) ---

def ana_yorum_cekici(url, motor_tipi):
    # 1. Cache Kontrolü
    kayitli_analiz = veritabani.analiz_getir(url)
    if kayitli_analiz:
        print(f"🚀 Veritabanından getirildi: {kayitli_analiz.get('baslik', 'Bilinmeyen')}")
        return kayitli_analiz

    # 2. Scraper Seçimi
    site_tipi = ""
    scraper_fonksiyonu = None
    if "trendyol.com" in url:
        site_tipi = "trendyol"; scraper_fonksiyonu = trendyol_cek
    elif "n11.com" in url:
        site_tipi = "n11"; scraper_fonksiyonu = n11_cek
    elif "hepsiburada.com" in url:
        return [{"hata": "Hepsiburada bakımda. Trendyol veya N11 deneyin."}]
    else:
        return [{"hata": "Desteklenmeyen site."}]
    
    print(f"Selenium WebDriver başlatılıyor ({motor_tipi} - {site_tipi})...")
    chrome_options = Options()
    chrome_options.add_argument("--disable-gpu"); chrome_options.add_argument("window-size=1920,1080")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    try:
        ham_veri_paketi = scraper_fonksiyonu(driver, url, YORUM_LIMITI_ANALIZ)
        if isinstance(ham_veri_paketi, dict) and "hata" in ham_veri_paketi: return ham_veri_paketi
        
        urun_basligi = ham_veri_paketi.get('baslik', 'Bilinmeyen Ürün')
        yorumlar = ham_veri_paketi.get('yorumlar', [])
        if not yorumlar: return {"hata": "Yorum bulunamadı."}

        analiz_sonucu = {}
        if motor_tipi == 'hibrit':
            print(f"HİBRİT MOD: {len(yorumlar)} yorum işleniyor...")
            gemini_listesi = []
            for veri in yorumlar:
                try:
                    bert_sonucu = analyze_aspects_with_finetuned_model(veri['yorum'])
                    ipucu = f" (YZ Notu: {bert_sonucu})" if bert_sonucu else ""
                    gemini_listesi.append({'puan': veri['puan'], 'yorum': f"{veri['yorum']}{ipucu}"})
                except: gemini_listesi.append(veri)
            analiz_sonucu = analyze_batch_with_gemini(gemini_listesi)

        elif motor_tipi == 'gemini':
            print(f"GEMINI MODU: {len(yorumlar)} yorum işleniyor...")
            analiz_sonucu = analyze_batch_with_gemini(yorumlar)
        else: 
            analiz_sonucu = {"ham_yorumlar": yorumlar}

        if (motor_tipi != 'bert') and (not analiz_sonucu or not analiz_sonucu.get("konu_analizleri")):
             print("⚠️ Analiz başarısız, ham veri dönülüyor.")
             return list(yorumlar)

        analiz_sonucu["baslik"] = urun_basligi
        analiz_sonucu["analiz_edilen_yorum_sayisi"] = len(yorumlar)
        
        if motor_tipi != 'bert':
            veritabani.analiz_kaydet(url, urun_basligi, motor_tipi, analiz_sonucu)
        return analiz_sonucu
    finally:
        print("Driver kapatılıyor."); driver.quit()

def sadece_veri_cek(url):
    chrome_options = Options(); chrome_options.add_argument("--disable-gpu")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    try: return veri_toplayici_cek(driver, url, YORUM_LIMITI_TOPLA)
    finally: driver.quit()

def verileri_kaydet(yeni_veriler):
    mevcut = []
    if os.path.exists(JSON_DOSYA_YOLU):
        with open(JSON_DOSYA_YOLU, 'r', encoding='utf-8') as f:
            try: mevcut = json.load(f)
            except: pass
    mevcut_yorumlar = {v['yorum'] for v in mevcut}
    eklenen = 0
    for v in yeni_veriler:
        if v['yorum'] not in mevcut_yorumlar:
            mevcut.append(v); eklenen += 1
    with open(JSON_DOSYA_YOLU, 'w', encoding='utf-8') as f: json.dump(mevcut, f, ensure_ascii=False, indent=2)
    return eklenen, len(mevcut)

def etiketleri_oku():
    if not os.path.exists(ETIKET_DOSYA_YOLU): return []
    with open(ETIKET_DOSYA_YOLU, 'r', encoding='utf-8') as f: return json.load(f)

def etiket_kaydet(yeni):
    etiketler = etiketleri_oku(); etiketler.append(yeni)
    with open(ETIKET_DOSYA_YOLU, 'w', encoding='utf-8') as f: json.dump(etiketler, f, ensure_ascii=False, indent=2)

# --- ROTALAR (ARTIK HTML STRING YOK, TEMPLATE VAR) ---

@app.route('/')
def ana_sayfa():
    return render_template('index.html')

@app.route('/analiz')
def analiz_sayfasi():
    return render_template('index.html')

@app.route('/analiz-et', methods=['POST'])
def analiz_et():
    url = request.form['url']
    motor_tipi = request.form.get('motor', 'bert')
    sonuclar = ana_yorum_cekici(url, motor_tipi)
    
    # Hata Yönetimi
    if isinstance(sonuclar, dict) and "hata" in sonuclar:
        return render_template('result.html', hata=sonuclar['hata'])
    if isinstance(sonuclar, list) and sonuclar and "hata" in sonuclar[0]:
        return render_template('result.html', hata=sonuclar[0]['hata'])
    
    # Veritabanı Unpacking (Kutudan Çıkarma)
    if isinstance(sonuclar, dict) and sonuclar.get("kaynaktan_geldi") and "analiz_sonucu" in sonuclar:
        sonuclar.update(sonuclar["analiz_sonucu"])
        
    return render_template('result.html', sonuclar=sonuclar, motor=motor_tipi)

@app.route('/gecmis')
def gecmis_sayfasi():
    gecmis_verisi = veritabani.gecmisi_listele()
    return render_template('history.html', gecmis=gecmis_verisi)

@app.route('/topla', methods=['GET', 'POST'])
def topla_sayfasi():
    mesaj = None
    if request.method == 'POST':
        url = request.form['url']
        ham_veri = sadece_veri_cek(url)
        # Veri formatını kontrol et (Dict mi List mi?)
        veriler = ham_veri.get('yorumlar', []) if isinstance(ham_veri, dict) else ham_veri
        
        if not veriler or (isinstance(veriler, list) and veriler and "hata" in veriler[0]):
            mesaj = {"tur": "hata", "icerik": "Veri çekilemedi."}
        else:
            eklenen, toplam = verileri_kaydet(veriler)
            mesaj = {"tur": "basari", "icerik": f"{eklenen} yeni yorum eklendi. Toplam: {toplam}"}
            
    return render_template('collect.html', mesaj=mesaj)

@app.route('/etiketle', methods=['GET', 'POST'])
def etiketle_sayfasi():
    if not os.path.exists(JSON_DOSYA_YOLU):
        return render_template('label.html', hata="Önce veri toplayın.")
        
    with open(JSON_DOSYA_YOLU, 'r', encoding='utf-8') as f: tum_yorumlar = json.load(f)
    mevcut_etiketler = etiketleri_oku()
    etiketli_metinler = {e['yorum_metni'] for e in mevcut_etiketler}
    
    if request.method == 'POST':
        yeni = {
            "yorum_metni": request.form.get('yorum_metni'),
            "etiketler": [{"konu": k, "duygu": d} for k, d in zip(request.form.getlist('konu'), request.form.getlist('duygu')) if k]
        }
        etiket_kaydet(yeni)
        return redirect(url_for('etiketle_sayfasi'))
        
    etiketlenmemis = [y for y in tum_yorumlar if y['yorum'] not in etiketli_metinler]
    if not etiketlenmemis:
        return render_template('label.html', bitti=True, sayi=len(mevcut_etiketler))
        
    gosterilecek = random.choice(etiketlenmemis)
    istatistik = f"({len(mevcut_etiketler) + 1} / {len(tum_yorumlar)})"
    
    return render_template('label.html', yorum=gosterilecek, istatistik=istatistik)

if __name__ == '__main__':
    app.run(debug=True, port=5001)