from flask import Flask, request, render_template_string, redirect, url_for
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
import json
import os
import random

# --- MODÜLLER ---
import veritabani  # Veritabanı modülü
# BERT Analizi için:
from scrapers.trendyol_scraper import analyze_aspects_with_finetuned_model
# Veri Çekme (Fetching) işlemleri için güncel scraper'lar:
from scrapers.trendyol_gemini_scraper import cek as trendyol_cek 
from scrapers.trendyol_gemini_scraper import analyze_batch_with_gemini 
from scrapers.n11_scraper import cek as n11_cek
from scrapers.veri_toplayici import topla as veri_toplayici_cek

app = Flask(__name__)

# Uygulama başlarken veritabanını hazırla
veritabani.veritabani_baslat()

YORUM_LIMITI_ANALIZ = 500
YORUM_LIMITI_TOPLA = 500
JSON_DOSYA_YOLU = "yorumlar.json"
ETIKET_DOSYA_YOLU = "etiketler.json"

def ana_yorum_cekici(url, motor_tipi):
    # 1. ADIM: ÖNCE VERİTABANINA BAK (CACHE)
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
        return {"hata": "Desteklenmeyen site. Sadece Trendyol ve N11."}
    
    print(f"Selenium WebDriver başlatılıyor ({motor_tipi} motoru - {site_tipi})...")
    chrome_options = Options()
    # chrome_options.add_argument("--headless") # İstersen açabilirsin
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("window-size=1920,1080")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    try:
        # A) Ham Veriyi Çek (Başlık + Yorumlar Sözlüğü Geliyor)
        ham_veri_paketi = scraper_fonksiyonu(driver, url, YORUM_LIMITI_ANALIZ)
        
        # Hata kontrolü
        if isinstance(ham_veri_paketi, dict) and "hata" in ham_veri_paketi:
            return ham_veri_paketi
        
        # Verileri ayrıştır (Artık sözlükten alıyoruz)
        urun_basligi = ham_veri_paketi.get('baslik', 'Bilinmeyen Ürün')
        yorumlar = ham_veri_paketi.get('yorumlar', [])
        
        if not yorumlar: 
            return {"hata": "Yorum bulunamadı veya çekilemedi."}

        # B) Analiz Süreci (Seçilen Motora Göre)
        analiz_sonucu = {}

        if motor_tipi == 'hibrit':
            print(f"HİBRİT MOD: {len(yorumlar)} yorum işleniyor...")
            gemini_listesi = []
            for veri in yorumlar:
                try:
                    bert_sonucu = analyze_aspects_with_finetuned_model(veri['yorum'])
                    ipucu_metni = ""
                    if bert_sonucu:
                        ipucu_metni = f" (Yapay Zeka Notu: Bu yorumda şu özellikler tespit edildi: {bert_sonucu})"
                    
                    gemini_listesi.append({
                        'puan': veri['puan'], 
                        'yorum': f"{veri['yorum']}{ipucu_metni}"
                    })
                except:
                    gemini_listesi.append(veri)

            analiz_sonucu = analyze_batch_with_gemini(gemini_listesi)

        elif motor_tipi == 'gemini':
            print(f"GEMINI MODU: {len(yorumlar)} yorum işleniyor...")
            analiz_sonucu = analyze_batch_with_gemini(yorumlar)
        
        else: 
            # BERT veya Ham Mod (Analiz yok, sadece listeleme)
            analiz_sonucu = {"ham_yorumlar": yorumlar}

        # C) Sonuç Kontrolü ve Kaydetme
        # Eğer Gemini boş döndüyse (Hata olduysa), ham veriyi göster
        if (motor_tipi != 'bert') and (not analiz_sonucu or not analiz_sonucu.get("konu_analizleri")):
             print("⚠️ Analiz başarısız oldu, ham veriler gösterilecek.")
             # Kaydetmeden dönüyoruz
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

@app.route('/')
def ana_sayfa():
    return redirect(url_for('analiz_sayfasi'))

@app.route('/gecmis')
def gecmis_sayfasi():
    gecmis = veritabani.gecmisi_listele()
    
    html = """<!DOCTYPE html><html lang="tr"><head><meta charset="UTF-8"><title>Analiz Geçmişi</title>
    <style>body{font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; padding:2rem; background:#f8f9fa;} 
    .container{max-width:1000px; margin:auto; background:#fff; padding:2rem; border-radius:12px; box-shadow:0 8px 24px rgba(0,0,0,0.1);}
    table{width:100%; border-collapse:collapse; margin-top:1rem;} 
    th,td{border-bottom:1px solid #eee; padding:12px; text-align:left;} 
    th{background-color:#f8f9fa; color:#555;} 
    tr:hover{background-color:#f1f1f1;} 
    .btn{padding:8px 16px; background:#3490dc; color:white; text-decoration:none; border-radius:6px; font-weight:500; border:none; cursor:pointer;}
    .btn:hover{background:#2779bd;}
    h1{color:#333;}
    .back-link{display:inline-block; margin-top:20px; color:#666; text-decoration:none;}
    </style>
    </head><body><div class="container">
    <h1>📜 Geçmiş Analizler</h1>
    <table><tr><th>Tarih</th><th>Ürün</th><th>Motor</th><th>İşlem</th></tr>"""
    
    if not gecmis:
        html += "<tr><td colspan='4' style='text-align:center;'>Henüz kaydedilmiş bir analiz yok.</td></tr>"
    
    for g in gecmis:
        form = f"""<form action='/analiz-et' method='post' style='display:inline;'>
        <input type='hidden' name='url' value='{g['url']}'>
        <input type='hidden' name='motor' value='{g['motor']}'>
        <button type='submit' class='btn'>Raporu Aç</button></form>"""
        
        tarih_str = g['tarih']
        html += f"<tr><td>{tarih_str}</td><td><b>{g['baslik']}</b></td><td>{g['motor'].upper()}</td><td>{form}</td></tr>"
    
    html += "</table><br><a href='/analiz' class='back-link'>← Ana Sayfaya Dön</a></div></body></html>"
    return render_template_string(html)

@app.route('/analiz')
def analiz_sayfasi():
    return render_template_string("""
    <!DOCTYPE html> <html lang="tr"> <head> <meta charset="UTF-8"> <title>Yorum Analiz Motoru</title> 
    <style> body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 0; background-color: #f8f9fa; display: flex; justify-content: center; align-items: center; min-height: 100vh; } .container { max-width: 800px; width: 100%; margin: auto; background-color: #fff; padding: 2.5rem; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.1); text-align: center; position:relative; } h1 { color: #333; margin-bottom: 0.5rem; } p { color: #666; margin-bottom: 2rem; } input[type='text'] { width: 95%; padding: 12px; margin-bottom: 1.5rem; border: 1px solid #ccc; border-radius: 8px; font-size: 1rem; } .button-group { display: flex; flex-wrap: wrap; gap: 1rem; } button { flex-grow: 1; padding: 14px 20px; color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 1rem; font-weight: bold; transition: all 0.2s; } button:hover { transform: translateY(-2px); box-shadow: 0 4px 8px rgba(0,0,0,0.15); } .btn-bert { background-color: #3490dc; } .btn-gemini { background-color: #38c172; } .btn-hibrit { background-color: #9561e2; background-image: linear-gradient(45deg, #9561e2, #6f42c1); } #loader { display: none; text-align: center; margin-top: 2rem; } .spinner { border: 4px solid #f3f3f3; border-top: 4px solid #3490dc; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: auto; } #loader-text { margin-top: 1rem; color: #555; font-weight: 500; } @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } } .history-btn { position: absolute; top: 20px; right: 20px; text-decoration: none; color: #555; font-weight: 600; padding: 8px 12px; background: #eee; border-radius: 20px; font-size: 0.9rem; transition: background 0.2s; } .history-btn:hover { background: #e2e6ea; } </style> 
    <script>
        function showLoader() {
            document.getElementById('form-container').style.display = 'none';
            document.getElementById('loader').style.display = 'block';
            const loaderText = document.getElementById('loader-text');
            const messages = ["Analiz başlatılıyor...", "Veritabanı kontrol ediliyor...", "Ürün sayfasına bağlanılıyor...", "Yorumlar toplanıyor...", "Yapay zeka (BERT/Gemini) motoru devrede...", "Rapor hazırlanıyor..."];
            let i = 0;
            loaderText.innerText = messages[i];
            const interval = setInterval(() => { i = (i + 1) % messages.length; loaderText.innerText = messages[i]; }, 3500);
        }
    </script>
    </head> <body> 
    <div class="container"> 
        <a href="/gecmis" class="history-btn">📜 Geçmiş Analizler</a>
        <h1>Yorum Analiz Motoru</h1> 
        <p>Trendyol veya N11 ürün linklerini analiz edebilirsiniz.</p> 
        <div id="form-container">
            <form action="/analiz-et" method="post" onsubmit="showLoader()"> 
                <input type="text" name="url" size="80" required placeholder="Trendyol veya N11 ürün linkini yapıştırın..."> 
                <div class="button-group"> 
                    <button type="submit" name="motor" value="gemini" class="btn-gemini">✨ Gemini ile Hızlı Özetle</button> 
                    <button type="submit" name="motor" value="bert" class="btn-bert">⚙️ Kendi Modelimizle İncele</button> 
                    <button type="submit" name="motor" value="hibrit" class="btn-hibrit">🚀 Hibrit (BERT + Gemini)</button>
                </div> 
            </form> 
        </div>
        <div id="loader"> <div class="spinner"></div> <p id="loader-text">Analiz başlatılıyor...</p> </div>
    </div> </body> </html>
    """)

@app.route('/analiz-et', methods=['POST'])
def analiz_et():
    url = request.form['url']; motor_tipi = request.form.get('motor', 'bert')
    analiz_sonuclari = ana_yorum_cekici(url, motor_tipi)
    
    if isinstance(analiz_sonuclari, dict) and "hata" in analiz_sonuclari: 
        return f"<h1>Hata</h1><p>{analiz_sonuclari['hata']}</p><a href='/analiz'>Geri Dön</a>"
    
    # --- VERİTABANI UNPACKING İŞLEMİ ---
    kaynaktan_geldi = analiz_sonuclari.get("kaynaktan_geldi", False)
    
    # Eğer veritabanından geldiyse, asıl veri 'analiz_sonucu' içindedir.
    if kaynaktan_geldi and "analiz_sonucu" in analiz_sonuclari:
        ic_veri = analiz_sonuclari["analiz_sonucu"]
        # Ana sözlüğü güncelle
        analiz_sonuclari.update(ic_veri)
    
    html_template = """
    <!DOCTYPE html> <html lang="tr"> <head> <meta charset="UTF-8"> <title>Analiz Raporu</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style> body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8f9fa; color: #212529; }} .container {{ max-width: 900px; margin: 2rem auto; }} h1, h2 {{ text-align: center; }} a {{ color: #007bff; text-decoration: none; }} .card {{ background-color: #fff; border-radius: 12px; box-shadow: 0 8px 16px rgba(0,0,0,0.05); padding: 1.5rem; margin-bottom: 2rem; }} .score-box {{ text-align: center; }} .score {{ font-size: 4rem; font-weight: 700; color: #007bff; }} .score-text {{ font-size: 1.1rem; color: #6c757d; margin-top: 0.5rem; }} .summary-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }} .summary-box h3 {{ margin-top: 0; font-size: 1.25rem; }} .summary-box ul {{ padding-left: 20px; margin: 0; }} .summary-box li {{ margin-bottom: 0.5rem; }} .pros {{ border-top: 5px solid #28a745; }} .cons {{ border-top: 5px solid #dc3545; }} .details-list ul {{ list-style: none; padding: 0; }} .details-list li {{ border-bottom: 1px solid #eee; padding: 1rem 0; }} .details-list li:last-child {{ border-bottom: none; }} .konu-baslik {{ font-weight: bold; font-size: 1.1rem; }} .pozitif {{ color: #28a745; }} .negatif {{ color: #dc3545; }} .notr {{ color: #6c757d; }} .detay-buton {{ cursor: pointer; color: #007bff; font-size: 0.8rem; margin-left: 10px; user-select: none; font-weight: 500; }} .detay-yorumlar {{ display: none; margin-top: 1rem; padding-top: 1rem; border-top: 1px dashed #ddd; }} .detay-yorumlar p {{ font-size: 0.9rem; margin: 8px 0; padding: 8px; border-radius: 4px; }} .detay-yorumlar .pozitif {{ background-color: #f0fff4; border-left: 3px solid #28a745; }} .detay-yorumlar .negatif {{ background-color: #fff5f5; border-left: 3px solid #dc3545; }} .yorum-karti {{ border: 1px solid #ddd; border-radius: 8px; padding: 1.5rem; margin-top: 1.5rem; }} .ozellik-listesi {{ margin-left: 20px; border-left: 2px solid #ccc; padding-left: 15px; margin-top: 1rem; }} .source-badge {{ display: inline-block; background: #e2e8f0; color: #4a5568; padding: 4px 12px; border-radius: 99px; font-size: 0.85rem; font-weight: 600; margin-bottom: 1rem; }} </style>
    <script> function toggleDetails(id) {{ var element = document.getElementById(id); element.style.display = (element.style.display === "none") ? "block" : "none"; }} </script>
    </head> <body> <div class="container">
        <h1>Ürün Analiz Raporu</h1>
        {baslik_html}
        {kaynak_html}
        <h3>Kullanılan Motor: {motor_tipi_gosterim}</h3>
        {icerik}
        <a href='/analiz' style='display:block; text-align:center; margin-top:2rem;'>Yeni Bir Analiz Yap</a>
    </div> {chart_script} </body> </html>
    """

    kaynak_html = "<div class='source-badge'>⚡ Veritabanından Yüklendi</div>" if kaynaktan_geldi else ""
    urun_basligi = analiz_sonuclari.get("baslik", "")
    baslik_html = f"<h2>{urun_basligi}</h2>" if urun_basligi else ""

    icerik_html = ""
    chart_script_html = ""

    if motor_tipi == 'gemini' or motor_tipi == 'hibrit':
        konu_analizleri = analiz_sonuclari.get('konu_analizleri', [])
        filtrelenmis_analizler = []
        for analiz in konu_analizleri:
            if (len(analiz.get('pozitif_yorumlar', [])) + len(analiz.get('negatif_yorumlar', [])) + len(analiz.get('notr_yorumlar', []))) > 0:
                filtrelenmis_analizler.append(analiz)
        konu_analizleri = filtrelenmis_analizler
        
        toplam_pozitif = sum(len(a.get('pozitif_yorumlar', [])) for a in konu_analizleri)
        toplam_bahsedilme = toplam_pozitif + sum(len(a.get('negatif_yorumlar', [])) for a in konu_analizleri)
        genel_skor = round((toplam_pozitif / toplam_bahsedilme) * 100) if toplam_bahsedilme > 0 else 50

        artilar = sorted([a for a in konu_analizleri if len(a.get('pozitif_yorumlar',[])) > len(a.get('negatif_yorumlar',[]))], key=lambda x: len(x.get('pozitif_yorumlar', [])), reverse=True)
        eksiler = sorted([a for a in konu_analizleri if len(a.get('negatif_yorumlar',[])) > len(a.get('pozitif_yorumlar',[]))], key=lambda x: len(x.get('negatif_yorumlar', [])), reverse=True)
        
        artilar_list_html = "".join([f"<li>{item['konu']}</li>" for item in artilar[:3]]) or "<li>-</li>"
        eksiler_list_html = "".join([f"<li>{item['konu']}</li>" for item in eksiler[:3]]) or "<li>-</li>"
        
        detayli_analiz_html = ""
        for i, analiz in enumerate(konu_analizleri):
            detayli_analiz_html += f"""
            <li>
                <span class='konu-baslik'>{analiz.get('konu', 'Bilinmeyen')}:</span> 
                <span class='pozitif'>{len(analiz.get('pozitif_yorumlar', []))} P</span>, 
                <span class='negatif'>{len(analiz.get('negatif_yorumlar', []))} N</span>
                <span class='detay-buton' onclick="toggleDetails('details-{i}')">Kanıt Yorumları Göster</span>
                <div class='detay-yorumlar' id='details-{i}'>
                    {''.join([f"<p class='pozitif'>- {yorum}</p>" for yorum in analiz.get('pozitif_yorumlar', [])])}
                    {''.join([f"<p class='negatif'>- {yorum}</p>" for yorum in analiz.get('negatif_yorumlar', [])])}
                </div>
            </li>
            """
            
        icerik_html = f"""
            <div class="card score-box">
                <div class="score">{genel_skor}<span>/100</span></div>
                <div class="score-text">Genel Özellik Memnuniyeti ({analiz_sonuclari.get('analiz_edilen_yorum_sayisi', 0)} yoruma göre)</div>
            </div>
            <div class="card summary-grid">
                <div class="summary-box pros"><h3>✅ Beğenilen Yönler (Top 3)</h3><ul>{artilar_list_html}</ul></div>
                <div class="summary-box cons"><h3>❌ Şikayet Edilen Yönler (Top 3)</h3><ul>{eksiler_list_html}</ul></div>
            </div>
            <div class="card"><h2>Özellik Analizi Grafiği</h2><canvas id="aspectChart"></canvas></div>
            <div class="card details-list"><h2>Detaylı Analiz</h2><ul>{detayli_analiz_html}</ul></div>
        """
        
        chart_labels = [f"'{a['konu']}'" for a in konu_analizleri[:7]]
        chart_data_pos = [len(a.get('pozitif_yorumlar', [])) for a in konu_analizleri[:7]]
        chart_data_neg = [len(a.get('negatif_yorumlar', [])) for a in konu_analizleri[:7]]
        
        chart_script_html = f"""
        <script>
            const ctx = document.getElementById('aspectChart');
            new Chart(ctx, {{
                type: 'bar', data: {{ labels: [{', '.join(chart_labels)}],
                datasets: [{{ label: 'Pozitif', data: {chart_data_pos}, backgroundColor: 'rgba(40, 167, 69, 0.7)' }}, {{ label: 'Negatif', data: {chart_data_neg}, backgroundColor: 'rgba(220, 53, 69, 0.7)' }}]
                }}, options: {{ indexAxis: 'y', scales: {{ x: {{ stacked: true }}, y: {{ stacked: true }} }}, responsive: true, plugins: {{ legend: {{ position: 'top' }} }} }}
            }});
        </script>
        """
    else:
        # BERT Modu veya Ham Veri
        ham_data = analiz_sonuclari
        if isinstance(ham_data, dict):
            yorumlar_listesi = ham_data.get('ham_yorumlar', ham_data.get('yorumlar', []))
        else:
            yorumlar_listesi = ham_data 

        bert_html = ""
        for veri in yorumlar_listesi:
            bert_html += f"<div class='yorum-karti'>"
            bert_html += f"<p><b>Kullanıcı Puanı: {veri.get('puan', 'N/A')} Yıldız</b></p>"
            bert_html += f"<p><i>\"{veri.get('yorum', 'N/A')}\"</i></p>"
            if 'ozellikler' in veri and veri['ozellikler']:
                bert_html += "<b>Özellik Bazlı Analiz:</b><div class='ozellik-listesi'>"
                for ozellik, duygu in veri['ozellikler'].items():
                    renk_class = "pozitif" if duygu == "Pozitif" else "negatif"
                    bert_html += f"<p class='{renk_class}'>- <b>{ozellik}:</b> {duygu}</p>"
                bert_html += "</div>"
            bert_html += "</div>"
        icerik_html = bert_html
    
    return render_template_string(html_template.format(
        motor_tipi_gosterim=motor_tipi.upper(),
        icerik=icerik_html,
        chart_script=chart_script_html,
        baslik_html=baslik_html,
        kaynak_html=kaynak_html
    ))

if __name__ == '__main__':
    app.run(debug=True, port=5001)