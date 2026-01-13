from flask import Flask, request, render_template, redirect, url_for
from selenium import webdriver
from selenium.webdriver.chrome.service import Service 
from selenium.webdriver.chrome.options import Options
import json
import os
import random

# --- KELİME BULUTU İÇİN GEREKLİLER ---
from wordcloud import WordCloud
import matplotlib
matplotlib.use('Agg') # macOS ve Sunucu hatalarını önlemek için arka plan modu
import matplotlib.pyplot as plt
import io
import base64

# --- MODÜLLER ---
import veritabani
from scrapers.trendyol_scraper import analyze_aspects_with_finetuned_model
from scrapers.trendyol_groq_scraper import cek as trendyol_cek 
from scrapers.trendyol_groq_scraper import analyze_batch_with_groq as analyze_batch_ai, urune_soru_sor
from scrapers.trendyol_groq_scraper import iki_urunu_kiyasla
from scrapers.n11_scraper import cek as n11_cek
from scrapers.hepsiburada_scraper import cek as hepsiburada_cek
from scrapers.veri_toplayici import topla as veri_toplayici_cek

app = Flask(__name__)
veritabani.veritabani_baslat()

YORUM_LIMITI_ANALIZ = 500
YORUM_LIMITI_TOPLA = 500
JSON_DOSYA_YOLU = "yorumlar.json"
ETIKET_DOSYA_YOLU = "etiketler.json"

def kelime_bulutu_olustur(yorumlar_listesi):
    """
    Yorum listesinden Kelime Bulutu oluşturur ve base64 string olarak döner.
    """
    try:
        # 1. Tüm yorumları tek bir metin haline getir
        tum_metin = " ".join([str(y.get('yorum', '')) for y in yorumlar_listesi]).lower()
        
        # 2. Gereksiz kelimeleri temizle (Stopwords)
        stopwords = set(["bir", "bu", "şu", "ile", "ve", "veya", "ama", "fakat", "lakin", "de", "da", "ki", "için", "çok", "daha", "en", "kadar", "gibi", "diye", "ben", "sen", "o", "biz", "siz", "onlar", "ürün", "urunu", "aldım", "geldi", "yok", "var", "bi", "sey", "şey", "gayet", "sanki", "zaten", "bence", "falan", "filan", "yani", "güzel", "iyi", "kötü", "tavsiye", "ederim", "teşekkürler", "teşekkür", "ederiz", "elime", "ulaştı", "hızlı", "kargo", "paketleme", "sağlam"])
        
        # 3. Bulutu Oluştur
        wordcloud = WordCloud(
            width=800, height=400,
            background_color='white',
            stopwords=stopwords,
            colormap='viridis',
            min_font_size=10
        ).generate(tum_metin)
        
        # 4. Resmi Belleğe Kaydet
        img = io.BytesIO()
        plt.figure(figsize=(10, 5))
        plt.imshow(wordcloud, interpolation='bilinear')
        plt.axis("off")
        plt.tight_layout(pad=0)
        plt.savefig(img, format='png')
        plt.close()
        img.seek(0)
        
        # 5. Base64'e Çevir (HTML'de göstermek için)
        plot_url = base64.b64encode(img.getvalue()).decode('utf8')
        return plot_url
        
    except Exception as e:
        print(f"Kelime bulutu hatası: {e}")
        return None

def ana_yorum_cekici(url, motor_tipi):
    # 1. ADIM: TAM EŞLEŞME KONTROLÜ (URL + Motor)
    # Eğer aynısı varsa direkt getir.
    kayitli_analiz = veritabani.analiz_getir(url, motor_tipi)
    if kayitli_analiz:
        print(f"🚀 Veritabanından getirildi ({motor_tipi}): {kayitli_analiz.get('baslik', 'Bilinmeyen')}")
        return kayitli_analiz

    # 2. ADIM: VERİ TEKRAR KULLANIMI
    # Eğer bu URL için başka bir motorla (örn: Llama) yapılmış analiz varsa, yorumları oradan getir.
    eski_kayit = veritabani.analiz_getir_genel(url)
    yorumlar = []
    urun_basligi = "Bilinmeyen Ürün"
    veri_kaynagi = "scraper" 

    if eski_kayit and "analiz_sonucu" in eski_kayit:
        ham_veri = eski_kayit["analiz_sonucu"]
        # Ham yorumları bulmaya çalış
        if "ham_yorumlar" in ham_veri and ham_veri["ham_yorumlar"]:
            yorumlar = ham_veri["ham_yorumlar"]
            urun_basligi = eski_kayit.get("baslik", "Ürün")
            veri_kaynagi = "veritabani"
            print(f"♻️ Eski analizden {len(yorumlar)} yorum bulundu. Scraper çalışmayacak!")
        # Eski versiyon uyumluluğu (Eğer ham_yorumlar anahtarı yoksa ama yorumlar varsa)
        elif "yorumlar" in ham_veri and ham_veri["yorumlar"]:
            yorumlar = ham_veri["yorumlar"]
            urun_basligi = eski_kayit.get("baslik", "Ürün")
            veri_kaynagi = "veritabani"
            print(f"♻️ Eski analizden {len(yorumlar)} yorum bulundu (V1). Scraper çalışmayacak!")
    
    # 3. ADIM: EĞER VERİTABANINDA YOKSA SCRAPER ÇALIŞTIR
    if veri_kaynagi == "scraper":
        site_tipi = ""; scraper_fonksiyonu = None
        if "trendyol.com" in url: site_tipi = "trendyol"; scraper_fonksiyonu = trendyol_cek
        elif "n11.com" in url: site_tipi = "n11"; scraper_fonksiyonu = n11_cek
        elif "hepsiburada.com" in url: site_tipi = "hepsiburada"; scraper_fonksiyonu = hepsiburada_cek
        else: return [{"hata": "Desteklenmeyen site."}]
        
        print(f"Selenium WebDriver başlatılıyor ({motor_tipi} motoru - {site_tipi})...")
        chrome_options = Options()
        chrome_options.add_argument("--disable-gpu"); chrome_options.add_argument("window-size=1920,1080")
        chrome_options.add_argument("--no-sandbox"); chrome_options.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(service=Service(), options=chrome_options)
        
        try:
            ham_veri_paketi = scraper_fonksiyonu(driver, url, YORUM_LIMITI_ANALIZ)
            if isinstance(ham_veri_paketi, dict) and "hata" in ham_veri_paketi: return ham_veri_paketi
            urun_basligi = ham_veri_paketi.get('baslik', 'Bilinmeyen Ürün')
            yorumlar = ham_veri_paketi.get('yorumlar', [])
        finally:
            print("Driver kapatılıyor."); driver.quit()

    if not yorumlar: return {"hata": "Yorum bulunamadı."}

    # 4. ADIM: ANALİZ SÜRECİ
    analiz_sonucu = {}

    if motor_tipi == 'hibrit':
        print(f"HİBRİT MOD: {len(yorumlar)} yorum işleniyor...")
        gemini_icin_hazirlanan_veriler = []
        bert_tespitleri = []
        toplam_bert = 0
        for veri in yorumlar:
            try:
                bert_sonucu = analyze_aspects_with_finetuned_model(veri['yorum'])
                ipucu_metni = ""
                if bert_sonucu:
                    ipucu_metni = f" (Yapay Zeka Notu: Bu yorumda şu özellikler tespit edildi: {bert_sonucu})"
                    # Ham veriyi güncelle ki kaydettiğimizde BERT sonucu da kalsın
                    veri['bert_analizi'] = bert_sonucu
                    veri['ozellikler'] = bert_sonucu 
                    bert_tespitleri.append(veri)
                    toplam_bert += len(bert_sonucu)
                gemini_icin_hazirlanan_veriler.append({'puan': veri['puan'], 'yorum': f"{veri['yorum']}{ipucu_metni}"})
            except: gemini_icin_hazirlanan_veriler.append(veri)

        analiz_sonucu = analyze_batch_ai(gemini_icin_hazirlanan_veriler)
        if analiz_sonucu:
            analiz_sonucu["bert_istatistik"] = {"toplam_tespit": toplam_bert, "detay": bert_tespitleri}

    elif motor_tipi == 'llama':
        print(f"LLAMA MODU: {len(yorumlar)} yorum işleniyor...")
        analiz_sonucu = analyze_batch_ai(yorumlar)
    
    else: 
        # BERT Modu
        print(f"BERT MODU: {len(yorumlar)} yorum yerel modelle taranıyor...")
        islenmis_yorumlar = []
        for veri in yorumlar:
            try:
                bert_sonucu = analyze_aspects_with_finetuned_model(veri['yorum'])
                veri['ozellikler'] = bert_sonucu 
                islenmis_yorumlar.append(veri)
            except:
                islenmis_yorumlar.append(veri)
        
        # BERT modunda özet yoktur, sadece zenginleştirilmiş ham yorumlar vardır
        analiz_sonucu = {"ham_yorumlar": islenmis_yorumlar}

    # Kontrol: Eğer analiz boşsa ve BERT modu değilse hata ver
    if (motor_tipi != 'bert') and (not analiz_sonucu or not analiz_sonucu.get("konu_analizleri")):
            print("⚠️ Analiz başarısız oldu, ham veriler gösterilecek.")
            return list(yorumlar)

    # Paketleme
    analiz_sonucu["baslik"] = urun_basligi
    analiz_sonucu["analiz_edilen_yorum_sayisi"] = len(yorumlar)
    # HAM YORUMLARI SAKLA
    analiz_sonucu["ham_yorumlar"] = yorumlar 
    
    # 5. ADIM: KAYDETME 
    # BERT, Llama, Hibrit fark etmez, hepsi kaydedilir.
    veritabani.analiz_kaydet(url, urun_basligi, motor_tipi, analiz_sonucu)
    
    return analiz_sonucu

def sadece_veri_cek(url):
    print("Veri toplama modu...")
    chrome_options = Options()
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(service=Service(), options=chrome_options)
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

@app.route('/')
def ana_sayfa():
    return redirect(url_for('analiz_sayfasi'))

@app.route('/analiz')
def analiz_sayfasi():
    return render_template('index.html')

@app.route('/analiz-et', methods=['POST'])
def analiz_et():
    url = request.form['url']
    motor_tipi = request.form.get('motor', 'bert')
    
    # 1. Veriyi Çek/Analiz Et
    sonuclar = ana_yorum_cekici(url, motor_tipi)
    
    # 2. Hata Kontrolü
    if isinstance(sonuclar, dict) and "hata" in sonuclar: 
        return render_template('result.html', hata=sonuclar['hata'])
    if isinstance(sonuclar, list) and sonuclar and "hata" in sonuclar[0]: 
        return render_template('result.html', hata=sonuclar[0]['hata'])
    
    # 3. Veritabanı Unpacking (Kutudan Çıkarma)
    if isinstance(sonuclar, dict) and sonuclar.get("kaynaktan_geldi") and "analiz_sonucu" in sonuclar:
        sonuclar.update(sonuclar["analiz_sonucu"])
        
    # 4. Kelime Bulutu Oluşturma
    kelime_bulutu = None
    ham_yorumlar = []
    
    # Yorum listesini bul 
    if isinstance(sonuclar, list):
        ham_yorumlar = sonuclar
    elif isinstance(sonuclar, dict):
        ham_yorumlar = sonuclar.get('ham_yorumlar', sonuclar.get('yorumlar', []))
    
    if ham_yorumlar:
        print("☁️ Kelime bulutu oluşturuluyor...")
        kelime_bulutu = kelime_bulutu_olustur(ham_yorumlar)
        
    return render_template('result.html', sonuclar=sonuclar, motor=motor_tipi, kelime_bulutu=kelime_bulutu)

@app.route('/gecmis')
def gecmis_sayfasi():
    gecmis_verisi = veritabani.gecmisi_listele()
    return render_template('history.html', gecmis=gecmis_verisi)

@app.route('/sil/<int:id>', methods=['POST'])
def sil_analiz(id):
    veritabani.analiz_sil(id)
    return redirect(url_for('gecmis_sayfasi'))

@app.route('/karsilastir', methods=['POST'])
def karsilastir():
    ids = request.form.getlist('urun_id')
    
    if len(ids) != 2:
        return "Lütfen karşılaştırmak için tam olarak 2 ürün seçin."
    
    # Veritabanından verileri çek
    u1 = veritabani.analiz_getir_id_ile(ids[0])
    u2 = veritabani.analiz_getir_id_ile(ids[1])
    
    if not u1 or not u2:
        return "Ürün verilerine ulaşılamadı."
    
    # Veritabanı verisini aç (unpack)
    if "analiz_sonucu" in u1: u1.update(u1["analiz_sonucu"])
    if "analiz_sonucu" in u2: u2.update(u2["analiz_sonucu"])
    
    # Yapay Zeka Karşılaştırması Yap
    print("🤖 Llama 3.3 Karşılaştırma yapıyor...")
    kiyaslama_metni = iki_urunu_kiyasla(
        u1.get('baslik', 'Ürün 1'), u1,
        u2.get('baslik', 'Ürün 2'), u2
    )
    
    return render_template('compare.html', u1=u1, u2=u2, ai_comment=kiyaslama_metni)

@app.route('/sor', methods=['POST'])
def soru_sor():
    data = request.json
    url = data.get('url'); soru = data.get('soru'); motor = data.get('motor', 'hibrit')
    if not url or not soru: return json.dumps({"cevap": "Hata: Eksik bilgi."})
    
    # 1. Önce tam eşleşme (Motor + URL) ara
    kayit = veritabani.analiz_getir(url, motor)
    
    # 2. Yoksa genel kayıt ara (Herhangi bir motorla yapılmış mı?)
    if not kayit:
        print("Soru için tam eşleşme bulunamadı, genel kayıt aranıyor...")
        kayit = veritabani.analiz_getir_genel(url)

    if not kayit: return json.dumps({"cevap": "Hata: Önce analiz yapmalısınız."})
    
    # Veritabanı verisini aç
    if "analiz_sonucu" in kayit: kayit.update(kayit["analiz_sonucu"])
    
    cevap = urune_soru_sor(kayit.get('baslik', 'Ürün'), kayit, soru)
    return json.dumps({"cevap": cevap}, ensure_ascii=False)

@app.route('/topla', methods=['GET', 'POST'])
def topla_sayfasi():
    mesaj = None
    if request.method == 'POST':
        url = request.form['url']
        ham_veri = sadece_veri_cek(url)
        veriler = ham_veri.get('yorumlar', []) if isinstance(ham_veri, dict) else ham_veri
        if not veriler or (isinstance(veriler, list) and veriler and "hata" in veriler[0]):
            mesaj = {"tur": "hata", "icerik": "Veri çekilemedi."}
        else:
            eklenen, toplam = verileri_kaydet(veriler)
            mesaj = {"tur": "basari", "icerik": f"{eklenen} yeni eklendi. Toplam: {toplam}"}
    return render_template('collect.html', mesaj=mesaj)

@app.route('/etiketle', methods=['GET', 'POST'])
def etiketle_sayfasi():
    if not os.path.exists(JSON_DOSYA_YOLU): return render_template('label.html', hata="Önce veri toplayın.")
    with open(JSON_DOSYA_YOLU, 'r', encoding='utf-8') as f: tum_yorumlar = json.load(f)
    mevcut_etiketler = etiketleri_oku()
    etiketli_metinler = {e['yorum_metni'] for e in mevcut_etiketler}
    if request.method == 'POST':
        yeni = {"yorum_metni": request.form.get('yorum_metni'), "etiketler": [{"konu": k, "duygu": d} for k, d in zip(request.form.getlist('konu'), request.form.getlist('duygu')) if k]}
        etiket_kaydet(yeni)
        return redirect(url_for('etiketle_sayfasi'))
    etiketlenmemis = [y for y in tum_yorumlar if y['yorum'] not in etiketli_metinler]
    if not etiketlenmemis: return render_template('label.html', bitti=True, sayi=len(mevcut_etiketler))
    return render_template('label.html', yorum=random.choice(etiketlenmemis), istatistik=f"({len(mevcut_etiketler) + 1} / {len(tum_yorumlar)})")

if __name__ == '__main__':
    app.run(debug=True, port=5001)
    