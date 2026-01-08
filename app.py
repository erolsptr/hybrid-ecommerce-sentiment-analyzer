from flask import Flask, request, render_template, redirect, url_for
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
import json
import os
import random

# --- MODÜLLER ---
import veritabani  # Veritabanı yönetim modülü

# BERT Analizi için (Yerel Model):
from scrapers.trendyol_scraper import analyze_aspects_with_finetuned_model

# --- DEĞİŞİKLİK: GEMINI YERİNE GROQ (LLAMA) IMPORTLARI ---
# Artık trendyol_gemini_scraper yerine trendyol_groq_scraper kullanıyoruz.
from scrapers.trendyol_groq_scraper import cek as trendyol_cek 
from scrapers.trendyol_groq_scraper import analyze_batch_with_groq as analyze_batch_ai 

# Diğer Scraper'lar
from scrapers.n11_scraper import cek as n11_cek
from scrapers.veri_toplayici import topla as veri_toplayici_cek

app = Flask(__name__)

# Uygulama başlarken veritabanını hazırla (Tablo yoksa oluşturur)
veritabani.veritabani_baslat()

YORUM_LIMITI_ANALIZ = 500
YORUM_LIMITI_TOPLA = 500
JSON_DOSYA_YOLU = "yorumlar.json"
ETIKET_DOSYA_YOLU = "etiketler.json"

def ana_yorum_cekici(url, motor_tipi):
    # 1. ADIM: ÖNCE VERİTABANINA BAK (CACHE - ÖNBELLEK)
    # Eğer bu link daha önce analiz edildiyse, tekrar bekleme yapma, direkt getir.
    kayitli_analiz = veritabani.analiz_getir(url)
    if kayitli_analiz:
        print(f"🚀 Veritabanından getirildi: {kayitli_analiz.get('baslik', 'Bilinmeyen')}")
        return kayitli_analiz

    # 2. ADIM: KAYIT YOKSA SCRAPING BAŞLAT
    site_tipi = ""
    scraper_fonksiyonu = None
    
    if "trendyol.com" in url:
        site_tipi = "trendyol"
        scraper_fonksiyonu = trendyol_cek
    elif "n11.com" in url:
        site_tipi = "n11"
        scraper_fonksiyonu = n11_cek
    elif "hepsiburada.com" in url:
        return [{"hata": "Hepsiburada şu an bakımda. Lütfen Trendyol veya N11 deneyin."}]
    else:
        return [{"hata": "Desteklenmeyen site. Sadece Trendyol ve N11 linkleri çalışır."}]
    
    print(f"Selenium WebDriver başlatılıyor ({motor_tipi} motoru - {site_tipi})...")
    chrome_options = Options()
    # chrome_options.add_argument("--headless") # Tarayıcıyı gizlemek istersen yorumu kaldır
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("window-size=1920,1080")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    try:
        # A) Ham Veriyi Çek (Başlık + Yorumlar Listesi)
        ham_veri_paketi = scraper_fonksiyonu(driver, url, YORUM_LIMITI_ANALIZ)
        
        # Hata kontrolü (Scraper hata sözlüğü döndürdüyse)
        if isinstance(ham_veri_paketi, dict) and "hata" in ham_veri_paketi:
            return ham_veri_paketi
        
        # Verileri ayrıştır
        urun_basligi = ham_veri_paketi.get('baslik', 'Bilinmeyen Ürün')
        yorumlar = ham_veri_paketi.get('yorumlar', [])
        
        if not yorumlar: 
            return {"hata": "Yorum bulunamadı veya çekilemedi."}

        # B) Analiz Süreci (Seçilen Motora Göre)
        analiz_sonucu = {}

        # --- HIBRIT MOD (BERT + LLAMA) ---
        if motor_tipi == 'hibrit':
            print(f"HİBRİT MOD: {len(yorumlar)} yorum işleniyor...")
            
            # Adım 1: BERT ile Ön Analiz
            print("   -> Adım 1/2: BERT Modeli tarıyor...")
            gemini_icin_hazirlanan_veriler = []
            bert_tespitleri = []
            toplam_bert_tespiti = 0
            
            for veri in yorumlar:
                try:
                    bert_sonucu = analyze_aspects_with_finetuned_model(veri['yorum'])
                    
                    ipucu_metni = ""
                    if bert_sonucu:
                        # BERT bulgularını metne "İpucu" olarak ekliyoruz
                        ipucu_metni = f" (Yapay Zeka Notu: Bu yorumda şu özellikler tespit edildi: {bert_sonucu})"
                        
                        # BERT sonuçlarını görsel kanıt için sakla
                        veri['bert_analizi'] = bert_sonucu 
                        bert_tespitleri.append(veri)
                        toplam_bert_tespiti += len(bert_sonucu)
                    
                    gemini_icin_hazirlanan_veriler.append({
                        'puan': veri['puan'], 
                        'yorum': f"{veri['yorum']}{ipucu_metni}"
                    })
                except:
                    gemini_icin_hazirlanan_veriler.append(veri)

            # Adım 2: Groq (Llama 3) ile Final Analiz
            print("   -> Adım 2/2: Llama 3 (Groq) modeline gönderiliyor...")
            analiz_sonucu = analyze_batch_ai(gemini_icin_hazirlanan_veriler)
            
            # BERT İstatistiklerini rapora ekle
            if analiz_sonucu:
                analiz_sonucu["bert_istatistik"] = {
                    "toplam_tespit": toplam_bert_tespiti,
                    "detay": bert_tespitleri
                }

        # --- LLAMA MODU (SADECE GROQ) ---
        elif motor_tipi == 'llama': # Eski 'gemini' seçeneği
            print(f"LLAMA MODU: {len(yorumlar)} yorum işleniyor...")
            analiz_sonucu = analyze_batch_ai(yorumlar)
        
        # --- BERT VEYA HAM MOD ---
        else: 
            # Analiz yok, sadece listeleme
            analiz_sonucu = {"ham_yorumlar": yorumlar}

        # C) Sonuç Kontrolü ve Kaydetme
        # Eğer Yapay Zeka boş döndüyse (Hata olduysa), ham veriyi göster
        if (motor_tipi != 'bert') and (not analiz_sonucu or not analiz_sonucu.get("konu_analizleri")):
             print("⚠️ Analiz başarısız oldu, ham veriler gösterilecek.")
             # Hatalı analizi kaydetmiyoruz, sadece listeyi dönüyoruz
             return list(yorumlar)

        # Başlığı ve sayıyı sonuca ekle
        analiz_sonucu["baslik"] = urun_basligi
        analiz_sonucu["analiz_edilen_yorum_sayisi"] = len(yorumlar)
        
        # Veritabanına Kaydet (BERT modu hariç)
        if motor_tipi != 'bert':
            veritabani.analiz_kaydet(url, urun_basligi, motor_tipi, analiz_sonucu)
        
        return analiz_sonucu

    finally:
        print("Selenium WebDriver kapatılıyor."); driver.quit()

# --- YARDIMCI FONKSİYONLAR ---

def sadece_veri_cek(url):
    print("Veri toplama modu...")
    chrome_options = Options()
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("window-size=1920,1080")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    try:
        sonuclar = veri_toplayici_cek(driver, url, YORUM_LIMITI_TOPLA)
        return sonuclar
    finally:
        driver.quit()

def verileri_kaydet(yeni_veriler):
    mevcut_veriler = []
    if os.path.exists(JSON_DOSYA_YOLU):
        with open(JSON_DOSYA_YOLU, 'r', encoding='utf-8') as f:
            try: mevcut_veriler = json.load(f)
            except json.JSONDecodeError: pass
    mevcut_yorumlar = {v['yorum'] for v in mevcut_veriler}
    eklenen_sayisi = 0
    for veri in yeni_veriler:
        if 'yorum' in veri and veri['yorum'] not in mevcut_yorumlar:
            mevcut_veriler.append(veri); eklenen_sayisi += 1
    with open(JSON_DOSYA_YOLU, 'w', encoding='utf-8') as f:
        json.dump(mevcut_veriler, f, ensure_ascii=False, indent=2)
    return eklenen_sayisi, len(mevcut_veriler)

def etiketleri_oku():
    if not os.path.exists(ETIKET_DOSYA_YOLU): return []
    with open(ETIKET_DOSYA_YOLU, 'r', encoding='utf-8') as f:
        try: return json.load(f)
        except json.JSONDecodeError: return []

def etiket_kaydet(yeni_etiket):
    etiketler = etiketleri_oku()
    etiketler.append(yeni_etiket)
    with open(ETIKET_DOSYA_YOLU, 'w', encoding='utf-8') as f:
        json.dump(etiketler, f, ensure_ascii=False, indent=2)

# --- ROTALAR (ROUTES) ---

@app.route('/')
def ana_sayfa():
    return render_template('index.html')

@app.route('/analiz')
def analiz_sayfasi():
    return render_template('index.html')

@app.route('/analiz-et', methods=['POST'])
def analiz_et():
    url = request.form['url']
    # Varsayılan motor 'bert', ama formdan 'llama' veya 'hibrit' gelebilir
    motor_tipi = request.form.get('motor', 'bert')
    
    sonuclar = ana_yorum_cekici(url, motor_tipi)
    
    # Hata Yönetimi
    if isinstance(sonuclar, dict) and "hata" in sonuclar:
        return render_template('result.html', hata=sonuclar['hata'])
    if isinstance(sonuclar, list) and sonuclar and "hata" in sonuclar[0]:
        return render_template('result.html', hata=sonuclar[0]['hata'])
    
    # --- VERİTABANI UNPACKING ---
    # Veritabanından gelen veri {'baslik': '...', 'analiz_sonucu': {...}} yapısındadır.
    # Bunu şablona uygun hale getirmek için iç içe yapıyı düzeltiyoruz.
    if isinstance(sonuclar, dict) and sonuclar.get("kaynaktan_geldi") and "analiz_sonucu" in sonuclar:
        # Analiz sonucunun içini ana sözlüğe kopyala
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
        # Sadece veri çek, analiz yapma
        ham_veri = sadece_veri_cek(url)
        
        # Gelen veri sözlük mü liste mi kontrol et
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
    # Mac kullanıcıları için Port 5001 (AirPlay çakışmasını önlemek için)
    app.run(debug=True, port=5001)