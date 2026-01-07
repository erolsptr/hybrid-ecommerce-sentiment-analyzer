from flask import Flask, request, render_template_string, redirect, url_for
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
import json
import os
import random

# --- IMPORTLAR ---
# BERT Analiz Fonksiyonunu (analyze_aspects...) buraya dahil ediyoruz
from scrapers.trendyol_scraper import cek as trendyol_bert_cek, analyze_aspects_with_finetuned_model
from scrapers.trendyol_gemini_scraper import cek as trendyol_gemini_cek
from scrapers.trendyol_gemini_scraper import analyze_batch_with_gemini 
from scrapers.n11_scraper import cek as n11_cek
from scrapers.veri_toplayici import topla as veri_toplayici_cek
from scrapers.hibrit_scraper import cek as hibrit_cek

app = Flask(__name__)
YORUM_LIMITI_ANALIZ = 500
YORUM_LIMITI_TOPLA = 500
JSON_DOSYA_YOLU = "yorumlar.json"
ETIKET_DOSYA_YOLU = "etiketler.json"

def ana_yorum_cekici(url, motor_tipi):
    motor = None
    site_tipi = ""
    
    if "trendyol.com" in url:
        site_tipi = "trendyol"
        if motor_tipi == 'gemini': motor = trendyol_gemini_cek
        elif motor_tipi == 'hibrit': motor = hibrit_cek
        else: motor = trendyol_bert_cek
        
    elif "n11.com" in url:
        site_tipi = "n11"
        pass
        
    elif "hepsiburada.com" in url:
        return [{"hata": "Hepsiburada şu an bakımda. Lütfen Trendyol veya N11 deneyin."}]
    
    if not site_tipi: return {"hata": "Desteklenmeyen site. (Sadece Trendyol ve N11)"}
    
    print(f"Selenium WebDriver başlatılıyor ({motor_tipi} motoru - {site_tipi})...")
    chrome_options = Options();
    # chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu"); chrome_options.add_argument("window-size=1920,1080")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    try:
        # --- TRENDYOL İŞLEYİŞİ ---
        if site_tipi == "trendyol":
            sonuclar = motor(driver, url, YORUM_LIMITI_ANALIZ)
            return sonuclar
            
        # --- N11 İŞLEYİŞİ (GÜNCELLENDİ: BERT ENTEGRASYONU) ---
        elif site_tipi == "n11":
            # 1. Ham Verileri Çek
            ham_veriler = n11_cek(driver, url, YORUM_LIMITI_ANALIZ)
            
            if not ham_veriler or (isinstance(ham_veriler, list) and ham_veriler and "hata" in ham_veriler[0]):
                return ham_veriler
            
            # 2. HİBRİT MOD (BERT + GEMINI)
            if motor_tipi == 'hibrit':
                print(f"N11 verileri ({len(ham_veriler)} adet) için HİBRİT süreç başlıyor...")
                
                # ADIM 2.1: BERT ile Ön Analiz
                print("Adım 1/2: BERT Modeli yorumları tarıyor...")
                gemini_icin_hazirlanan_veriler = []
                
                for veri in ham_veriler:
                    try:
                        # Kendi eğittiğimiz BERT modelini çağırıyoruz
                        bert_sonucu = analyze_aspects_with_finetuned_model(veri['yorum'])
                        
                        # BERT sonuçlarını Gemini'ye "İpucu" olarak metne ekliyoruz
                        ipucu_metni = ""
                        if bert_sonucu:
                            ipucu_metni = f" (Yapay Zeka Notu: Bu yorumda şu özellikler tespit edildi: {bert_sonucu})"
                        
                        yeni_yorum_metni = f"{veri['yorum']}{ipucu_metni}"
                        
                        # Gemini'ye gidecek listeye ekle
                        gemini_icin_hazirlanan_veriler.append({
                            'puan': veri['puan'], 
                            'yorum': yeni_yorum_metni
                        })
                    except Exception as e:
                        print(f"BERT analizi hatası (yorum atlandı): {e}")
                        gemini_icin_hazirlanan_veriler.append(veri) # Hata olursa ham halini ekle

                # ADIM 2.2: Gemini ile Final Analiz
                print("Adım 2/2: Zenginleştirilmiş veriler Gemini'ye gönderiliyor...")
                analiz_sonucu = analyze_batch_with_gemini(gemini_icin_hazirlanan_veriler)
                
                if not analiz_sonucu or not analiz_sonucu.get("konu_analizleri"):
                    return ham_veriler 
                
                analiz_sonucu["analiz_edilen_yorum_sayisi"] = len(ham_veriler)
                return analiz_sonucu

            # 3. SADECE GEMINI MODU
            elif motor_tipi == 'gemini':
                print(f"N11 verileri ({len(ham_veriler)} adet) Gemini ile analiz ediliyor...")
                analiz_sonucu = analyze_batch_with_gemini(ham_veriler)
                if not analiz_sonucu or not analiz_sonucu.get("konu_analizleri"): return ham_veriler
                analiz_sonucu["analiz_edilen_yorum_sayisi"] = len(ham_veriler)
                return analiz_sonucu
            
            # 4. SADECE BERT MODU (Veya Ham Liste)
            else:
                return ham_veriler

    finally:
        print("Selenium WebDriver kapatılıyor."); driver.quit()

def sadece_veri_cek(url):
    print("Sadece veri toplama modunda çalışılıyor...")
    print("Selenium WebDriver başlatılıyor...")
    chrome_options = Options();
    # chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu"); chrome_options.add_argument("window-size=1920,1080")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    try:
        sonuclar = veri_toplayici_cek(driver, url, YORUM_LIMITI_TOPLA)
        return sonuclar
    finally:
        print("Selenium WebDriver kapatılıyor."); driver.quit()

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
    return render_template_string("""
    <!DOCTYPE html> <html lang="tr"> <head> <meta charset="UTF-8"> <title>Yorum Analiz Motoru</title> 
    <style> body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 0; background-color: #f8f9fa; display: flex; justify-content: center; align-items: center; min-height: 100vh; } .container { max-width: 800px; width: 100%; margin: auto; background-color: #fff; padding: 2.5rem; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.1); text-align: center; } h1 { color: #333; margin-bottom: 0.5rem; } p { color: #666; margin-bottom: 2rem; } input[type='text'] { width: 95%; padding: 12px; margin-bottom: 1.5rem; border: 1px solid #ccc; border-radius: 8px; font-size: 1rem; } .button-group { display: flex; flex-wrap: wrap; gap: 1rem; } button { flex-grow: 1; padding: 14px 20px; color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 1rem; font-weight: bold; transition: all 0.2s; } button:hover { transform: translateY(-2px); box-shadow: 0 4px 8px rgba(0,0,0,0.15); } .btn-bert { background-color: #3490dc; } .btn-gemini { background-color: #38c172; } .btn-hibrit { background-color: #9561e2; background-image: linear-gradient(45deg, #9561e2, #6f42c1); } #loader { display: none; text-align: center; margin-top: 2rem; } .spinner { border: 4px solid #f3f3f3; border-top: 4px solid #3490dc; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: auto; } #loader-text { margin-top: 1rem; color: #555; font-weight: 500; } @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } } </style> 
    <script>
        function showLoader() {
            document.getElementById('form-container').style.display = 'none';
            document.getElementById('loader').style.display = 'block';
            const loaderText = document.getElementById('loader-text');
            const messages = ["Analiz başlatılıyor...", "Ürün sayfasına bağlanılıyor...", "Yorumlar bulunuyor ve çekiliyor...", "Bu işlem yorum sayısına göre biraz zaman alabilir...", "BERT Modeli yorumları ön analizden geçiriyor...", "Gemini sonuçları doğruluyor ve özetliyor...", "Rapor hazırlanıyor..."];
            let i = 0;
            loaderText.innerText = messages[i];
            const interval = setInterval(() => { i = (i + 1) % messages.length; loaderText.innerText = messages[i]; }, 4000);
        }
    </script>
    </head> <body> <div class="container"> 
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
    if isinstance(analiz_sonuclari, dict) and "hata" in analiz_sonuclari: return f"<h1>Hata</h1><p>{analiz_sonuclari['hata']}</p><a href='/analiz'>Geri Dön</a>"
    if isinstance(analiz_sonuclari, list) and analiz_sonuclari and isinstance(analiz_sonuclari[0], dict) and "hata" in analiz_sonuclari[0]: return f"<h1>Hata</h1><p>{analiz_sonuclari[0]['hata']}</p><a href='/analiz'>Geri Dön</a>"
    
    html_template = """
    <!DOCTYPE html> <html lang="tr"> <head> <meta charset="UTF-8"> <title>Analiz Raporu</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style> body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8f9fa; color: #212529; }} .container {{ max-width: 900px; margin: 2rem auto; }} h1, h2 {{ text-align: center; }} a {{ color: #007bff; text-decoration: none; }} .card {{ background-color: #fff; border-radius: 12px; box-shadow: 0 8px 16px rgba(0,0,0,0.05); padding: 1.5rem; margin-bottom: 2rem; }} .score-box {{ text-align: center; }} .score {{ font-size: 4rem; font-weight: 700; color: #007bff; }} .score-text {{ font-size: 1.1rem; color: #6c757d; margin-top: 0.5rem; }} .summary-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }} .summary-box h3 {{ margin-top: 0; font-size: 1.25rem; }} .summary-box ul {{ padding-left: 20px; margin: 0; }} .summary-box li {{ margin-bottom: 0.5rem; }} .pros {{ border-top: 5px solid #28a745; }} .cons {{ border-top: 5px solid #dc3545; }} .details-list ul {{ list-style: none; padding: 0; }} .details-list li {{ border-bottom: 1px solid #eee; padding: 1rem 0; }} .details-list li:last-child {{ border-bottom: none; }} .konu-baslik {{ font-weight: bold; font-size: 1.1rem; }} .pozitif {{ color: #28a745; }} .negatif {{ color: #dc3545; }} .notr {{ color: #6c757d; }} .detay-buton {{ cursor: pointer; color: #007bff; font-size: 0.8rem; margin-left: 10px; user-select: none; font-weight: 500; }} .detay-yorumlar {{ display: none; margin-top: 1rem; padding-top: 1rem; border-top: 1px dashed #ddd; }} .detay-yorumlar p {{ font-size: 0.9rem; margin: 8px 0; padding: 8px; border-radius: 4px; }} .detay-yorumlar .pozitif {{ background-color: #f0fff4; border-left: 3px solid #28a745; }} .detay-yorumlar .negatif {{ background-color: #fff5f5; border-left: 3px solid #dc3545; }} .yorum-karti {{ border: 1px solid #ddd; border-radius: 8px; padding: 1.5rem; margin-top: 1.5rem; }} .ozellik-listesi {{ margin-left: 20px; border-left: 2px solid #ccc; padding-left: 15px; margin-top: 1rem; }}</style>
    <script> function toggleDetails(id) {{ var element = document.getElementById(id); element.style.display = (element.style.display === "none") ? "block" : "none"; }} </script>
    </head> <body> <div class="container">
        <h1>Ürün Analiz Raporu</h1>
        <h3>Kullanılan Motor: {motor_tipi_gosterim}</h3>
        {icerik}
        <a href='/analiz' style='display:block; text-align:center; margin-top:2rem;'>Yeni Bir Analiz Yap</a>
    </div> {chart_script} </body> </html>
    """

    icerik_html = ""
    chart_script_html = ""

    if motor_tipi == 'gemini' or motor_tipi == 'hibrit':
        konu_analizleri = analiz_sonuclari.get('konu_analizleri', [])
        
        filtrelenmis_analizler = []
        for analiz in konu_analizleri:
            p_sayisi = len(analiz.get('pozitif_yorumlar', []))
            n_sayisi = len(analiz.get('negatif_yorumlar', []))
            nt_sayisi = len(analiz.get('notr_yorumlar', []))
            if (p_sayisi + n_sayisi + nt_sayisi) > 0:
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
        bert_html = ""
        for veri in analiz_sonuclari:
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
        chart_script=chart_script_html
    ))

@app.route('/topla', methods=['GET', 'POST'])
def topla_sayfasi():
    if request.method == 'POST':
        url = request.form['url']
        if not url: return "Lütfen bir URL girin."
        cekilen_veriler = sadece_veri_cek(url)
        if isinstance(cekilen_veriler, list) and cekilen_veriler and "hata" in cekilen_veriler[0]:
            return f"<h1>Hata</h1><p>{cekilen_veriler[0]['hata']}</p><a href='/topla'>Geri Dön</a>"
        eklenen, toplam = verileri_kaydet(cekilen_veriler)
        return f"<h1>Veri Toplama Başarılı!</h1><p>{eklenen} yeni yorum 'yorumlar.json' dosyasına eklendi.</p><p>Dosyadaki toplam benzersiz yorum sayısı: {toplam}</p><a href='/topla'>Yeni Bir Üründen Daha Yorum Topla</a><br><br><a href='/'>Ana Sayfaya Dön</a>"
    return render_template_string("""
    <!DOCTYPE html> <html lang="tr"> <head> <meta charset="UTF-8"> <title>Eğitim Verisi Toplama Aracı</title> <style> body { font-family: sans-serif; margin: 40px; background-color: #f8f9fa;} .container { max-width: 800px; margin: auto; background-color: #fff; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); } input { width: 95%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; } button { width: 100%; margin-top: 1rem; padding: 10px; background-color: #38c172; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1rem;} a{text-decoration: none; color: #3490dc;} </style> </head> <body> <div class="container"><h1>Eğitim Verisi Toplama Aracı</h1> <p>Lütfen yorumlarını toplamak istediğiniz Trendyol ürün linkini yapıştırın.</p> <form action="/topla" method="post"> <input type="text" name="url" size="80" required> <button type="submit">Yorumları Topla ve Kaydet</button> </form><br><a href="/">Ana Sayfaya Dön</a></div> </body> </html>
    """)
@app.route('/etiketle', methods=['GET', 'POST'])
def etiketle_sayfasi():
    if not os.path.exists(JSON_DOSYA_YOLU): return "Etiketlenecek yorum bulunamadı. Lütfen önce '/topla' sayfasından veri toplayın."
    with open(JSON_DOSYA_YOLU, 'r', encoding='utf-8') as f: tum_yorumlar = json.load(f)
    mevcut_etiketler = etiketleri_oku()
    etiketlenmis_yorum_metinleri = {e['yorum_metni'] for e in mevcut_etiketler}
    if request.method == 'POST':
        yorum_metni = request.form.get('yorum_metni'); konular = request.form.getlist('konu'); duygular = request.form.getlist('duygu')
        yeni_etiket = { "yorum_metni": yorum_metni, "etiketler": [{"konu": konu, "duygu": duygu} for konu, duygu in zip(konular, duygular) if konu] }
        etiket_kaydet(yeni_etiket)
        return redirect(url_for('etiketle_sayfasi'))
    etiketlenmemis_yorumlar = [y for y in tum_yorumlar if y['yorum'] not in etiketlenmis_yorum_metinleri]
    if not etiketlenmemis_yorumlar: return f"<h1>Tebrikler!</h1><p>Tüm yorumları etiketlediniz. Toplam {len(mevcut_etiketler)} adet etiketli yorumunuz var.</p><a href='/'>Ana Sayfaya Dön</a>"
    gosterilecek_yorum = random.choice(etiketlenmemis_yorumlar)
    html = f"""
    <!DOCTYPE html><html lang="tr"><head><meta charset="UTF-8"><title>Veri Etiketleme Aracı</title>
    <style> body {{ font-family: sans-serif; display: flex; justify-content: center; padding-top: 2rem; background-color: #f4f4f4; }} .container {{ width: 800px; background: #fff; padding: 2rem; box-shadow: 0 0 10px rgba(0,0,0,0.1); border-radius: 8px; }} .yorum-kutusu {{ border: 2px solid #eee; padding: 1rem; border-radius: 5px; margin-bottom: 1.5rem; background: #fafafa; }} .etiket-satiri {{ display: flex; gap: 10px; margin-bottom: 10px; }} input[type='text'] {{ flex-grow: 1; padding: 8px; }} select {{ padding: 8px; }} .buton-grup {{ margin-top: 1.5rem; }} button {{ padding: 10px 15px; border: none; border-radius: 5px; cursor: pointer; }} .btn-ekle {{ background-color: #28a745; color: white; }} .btn-kaydet {{ background-color: #007bff; color: white; width: 100%; font-size: 1.2rem; }} .progress {{ margin-top: 1rem; font-size: 0.9rem; color: #555; }} a{{text-decoration: none; color: #3490dc;}}</style>
    </head><body>
    <div class="container">
        <h3>Etiketlenecek Yorum: ({len(mevcut_etiketler) + 1}/{len(tum_yorumlar)})</h3>
        <div class="yorum-kutusu"><p><b>Puan: {gosterilecek_yorum['puan']} Yıldız</b></p><p><i>{gosterilecek_yorum['yorum']}</i></p></div>
        <form method="post"> <input type="hidden" name="yorum_metni" value="{gosterilecek_yorum['yorum']}"> <h4>Etiketler:</h4><div id="etiket-alani"> <div class="etiket-satiri"><input type="text" name="konu" placeholder="Konu / Özellik (örn: kamera)"><select name="duygu"><option value="Pozitif">Pozitif</option><option value="Negatif">Negatif</option><option value="Nötr">Nötr</option></select></div>
        </div><div class="buton-grup"><button type="button" class="btn-ekle" onclick="yeniEtiketSatiriEkle()">+ Yeni Konu Ekle</button><button type="submit" class="btn-kaydet">Kaydet ve Sonrakine Geç</button></div> </form>
        <p><a href="/">Ana Sayfaya Dön</a></p>
    </div>
    <script> function yeniEtiketSatiriEkle() {{ const etiketAlani = document.getElementById('etiket-alani'); const yeniSatir = document.createElement('div'); yeniSatir.className = 'etiket-satiri'; yeniSatir.innerHTML = `<input type="text" name="konu" placeholder="Konu / Özellik"><select name="duygu"><option value="Pozitif">Pozitif</option><option value="Negatif">Negatif</option><option value="Nötr">Nötr</option></select>`; etiketAlani.appendChild(yeniSatir); }} </script>
    </body></html>
    """
    return render_template_string(html)

if __name__ == '__main__':
    app.run(debug=True, port=5001)