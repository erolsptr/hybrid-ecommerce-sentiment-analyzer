import time
import re
import os
import json
from dotenv import load_dotenv
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
import concurrent.futures
import random

# Groq Kütüphanesi
from groq import Groq

load_dotenv()

keys_string = os.getenv("GROQ_API_KEY")
# Virgülle ayrılmış birden fazla key varsa listeye çevir, yoksa tek elemanlı liste yap
API_KEY_POOL = keys_string.split(",") if keys_string else []

def get_random_client():
    """Havuzdan rastgele bir key seçip Groq istemcisi oluşturur."""
    if not API_KEY_POOL:
        print("HATA: Groq API Key bulunamadı.")
        return None
    
    # Rastgele bir key seç
    selected_key = random.choice(API_KEY_POOL).strip()
    return Groq(api_key=selected_key)
# API Key'i al
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

# --- GÜNCELLEME: Model İsmi Değiştirildi ---
# Eski (Kapanan): llama3-70b-8192
# Yeni (Aktif): llama-3.3-70b-versatile
MODEL_NAME = "llama-3.3-70b-versatile" 
BATCH_SIZE = 75

def parse_style_padding_to_rating(style_text):
    if not style_text: return 5
    match = re.search(r'padding-inline-end:\s*([0-9.]+)px', style_text)
    if match:
        padding = float(match.group(1))
        if padding > 60: return 1
        if padding > 45: return 2
        if padding > 30: return 3
        if padding > 15: return 4
    return 5

def call_groq_api(partial_comments):
    """Groq API çağrısı yapar."""
    tum_yorumlar_metni = "\n---\n".join([f"Puan: {y['puan']}, Yorum: {y['yorum']}" for y in partial_comments])
    
    prompt = f"""
    Sen bir e-ticaret yorum analistisin. Aşağıdaki Türkçe yorumları analiz et.
    
    KURALLAR:
    1. Analizlerini SADECE şu ana kategoriler altında topla:
       - "Kargo ve Teslimat"
       - "Paketleme"
       - "Ürün Kalitesi ve Malzeme"
       - "Fiyat/Performans"
       - "Kurulum ve Montaj"
       - "Ses ve Gürültü"
       - "Kullanım Kolaylığı"
       - "Tasarım ve Boyut"
       - "Satıcı ve İade Süreçleri"
       - "Dayanıklılık ve Arıza"
       - "Performans ve İşlevsellik"
    
    2. Eğer bir yorum bu kategorilerden hiçbirine girmiyorsa "Diğer" altına al.
    3. Cevabı SADECE ve SADECE aşağıdaki JSON formatında ver. Başka hiçbir açıklama yazma.

    YORUMLAR:
    {tum_yorumlar_metni}

    JSON CEVABI:
    {{
      "konu_analizleri": [
        {{
          "konu": "Kategori Adı",
          "pozitif_yorumlar": ["Yorum..."],
          "negatif_yorumlar": ["Yorum..."],
          "notr_yorumlar": []
        }}
      ]
    }}
    """
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "Sen sadece JSON döndüren bir asistansın. JSON dışında tek kelime bile etme."
                },
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            model=MODEL_NAME,
            temperature=0, 
            response_format={"type": "json_object"} 
        )
        
        json_response_text = chat_completion.choices[0].message.content
        return json.loads(json_response_text)

    except Exception as e:
        print(f"Groq API Hatası: {e}")
        return {"konu_analizleri": []}

def merge_results(results_list):
    final_dict = {"konu_analizleri": []}
    topic_map = {} 

    for result in results_list:
        if not result or "konu_analizleri" not in result: continue
        
        for item in result["konu_analizleri"]:
            konu_adi = item.get("konu", "Diğer").strip()
            
            if konu_adi in topic_map:
                existing_index = topic_map[konu_adi]
                existing_item = final_dict["konu_analizleri"][existing_index]
                existing_item["pozitif_yorumlar"].extend(item.get("pozitif_yorumlar", []))
                existing_item["negatif_yorumlar"].extend(item.get("negatif_yorumlar", []))
                existing_item.setdefault("notr_yorumlar", []).extend(item.get("notr_yorumlar", []))
            else:
                final_dict["konu_analizleri"].append(item)
                topic_map[konu_adi] = len(final_dict["konu_analizleri"]) - 1
    return final_dict

def analyze_batch_with_groq(yorum_listesi):
    if not GROQ_API_KEY: return {"hata": "Groq API Anahtarı eksik."}

    batches = []
    for i in range(0, len(yorum_listesi), BATCH_SIZE):
        batches.append(yorum_listesi[i:i + BATCH_SIZE])

    print(f"Toplam {len(yorum_listesi)} yorum, {len(batches)} paralel paket halinde GROQ ile işlenecek...")
    
    all_results = []
    
    # GROQ ÇOK HIZLI OLDUĞU İÇİN PARALEL GÖNDEREBİLİRİZ
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_to_batch = {executor.submit(call_groq_api, batch): i for i, batch in enumerate(batches)}
        
        for future in concurrent.futures.as_completed(future_to_batch):
            batch_index = future_to_batch[future]
            try:
                data = future.result()
                if data and "konu_analizleri" in data and data["konu_analizleri"]:
                    all_results.append(data)
                    print(f"   -> Groq Paketi {batch_index + 1} Tamamlandı ✅")
                else:
                    print(f"   -> Groq Paketi {batch_index + 1} Boş Döndü ⚠️")
            except Exception as e:
                print(f"   -> Groq Paketi {batch_index + 1} Hata ❌: {e}")

    return merge_results(all_results)

# --- SCRAPER KISMI ---
def cek(driver, url, limit):
    print("Trendyol GROQ Scraper (Llama 3.3) başlatıldı...")
    cekilen_veriler = []
    cekilen_yorum_metinleri = set()
    urun_basligi = "Bilinmeyen Trendyol Ürünü"

    try:
        driver.get(url)
        time.sleep(3)
        try: driver.find_element(By.ID, "onetrust-accept-btn-handler").click(); time.sleep(1)
        except: pass
        try: driver.find_element(By.CLASS_NAME, "onboarding__default-renderer-primary-button").click(); time.sleep(1)
        except: pass

        baslik_bulundu = False
        try:
            baslik_elementi = driver.find_element(By.CLASS_NAME, "product-title")
            urun_basligi = baslik_elementi.text.strip()
            baslik_bulundu = True
        except: pass
        
        if not baslik_bulundu:
            try:
                baslik_elementi = driver.find_element(By.CLASS_NAME, "info-title-text")
                urun_basligi = baslik_elementi.text.strip()
                baslik_bulundu = True
            except: pass
            
        if not baslik_bulundu:
            try:
                marka = driver.find_element(By.CLASS_NAME, "pr-new-br").text
                ad = driver.find_element(By.CLASS_NAME, "pr-nm").text
                urun_basligi = f"{marka} {ad}"
            except: print("Başlık çekilemedi.")

        if "/yorumlar" not in driver.current_url:
            try:
                btn = driver.find_element(By.CLASS_NAME, "reviews-summary-reviews-detail")
                driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                time.sleep(1); btn.click(); time.sleep(3)
            except NoSuchElementException: return {"hata": "Değerlendirmeler butonu bulunamadı."}
        
        print(f"Akıllı kaydırma başladı (Hedef: {limit} yorum)...")
        son_sayi = 0
        while len(cekilen_yorum_metinleri) < limit:
            karts = driver.find_elements(By.CSS_SELECTOR, ".review, .review-card")
            if len(karts) == son_sayi and len(karts) > 0: break
            son_sayi = len(karts)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);"); time.sleep(2)
        
        karts = driver.find_elements(By.CSS_SELECTOR, ".review, .review-card")
        for kart in karts:
            try:
                metin_el = kart.find_elements(By.CLASS_NAME, "review-comment")
                if not metin_el: continue
                metin = metin_el[0].text
                if not metin or metin in cekilen_yorum_metinleri: continue
                try: 
                    more = kart.find_elements(By.CLASS_NAME, "read-more")
                    if more: driver.execute_script("arguments[0].click();", more[0]); metin = kart.find_element(By.CLASS_NAME, "review-comment").text
                except: pass
                style = kart.find_element(By.CLASS_NAME, "star-rating-full-star").get_attribute('style')
                puan = parse_style_padding_to_rating(style)
                cekilen_veriler.append({'puan': puan, 'yorum': metin})
                cekilen_yorum_metinleri.add(metin)
            except: continue
            
        print(f"Trendyol'dan toplam {len(cekilen_veriler)} yorum çekildi.")
        
        return {
            "baslik": urun_basligi,
            "yorumlar": cekilen_veriler
        }

    except Exception as e:
        print(f"Hata: {e}")
        return {"baslik": urun_basligi, "yorumlar": [], "hata": str(e)}
    # ... (Mevcut kodların en altına ekle) ...

# ... (Üstteki kodlar aynı kalsın) ...

def veriyi_ozetle(ham_veri):
    """
    Veri paketini istatistiklere ve ÖRNEK YORUMLARA dönüştürür.
    Böylece AI, detay sorulara cevap verebilir.
    """
    if not ham_veri: return {}
    
    # Konu bazlı sayıları ve örnekleri çıkar
    konu_ozeti = {}
    konular = ham_veri.get('konu_analizleri', [])
    
    for k in konular:
        konu_adi = k.get('konu', 'Diğer')
        p_list = k.get('pozitif_yorumlar', [])
        n_list = k.get('negatif_yorumlar', [])
        
        p_sayisi = len(p_list)
        n_sayisi = len(n_list)
        
        # Sadece yorum olan konuları al
        if p_sayisi + n_sayisi > 0:
            # --- GELİŞTİRME: İlk 3 yorumu örnek olarak alıp metne ekliyoruz ---
            # Metinleri kısaltarak alalım ki token patlamasın (ilk 100 karakter)
            p_ornekler = ", ".join([f"'{y[:100]}...'" for y in p_list[:3]])
            n_ornekler = ", ".join([f"'{y[:100]}...'" for y in n_list[:3]])
            
            detay_metni = f"{p_sayisi} Pozitif (Örnekler: {p_ornekler}), {n_sayisi} Negatif (Örnekler: {n_ornekler})"
            konu_ozeti[konu_adi] = detay_metni
            
    return {
        "urun_adi": ham_veri.get('baslik', 'Bilinmeyen Ürün'),
        "toplam_yorum": ham_veri.get('analiz_edilen_yorum_sayisi', 0),
        "konu_detaylari": konu_ozeti
    }

def iki_urunu_kiyasla(urun1_baslik, urun1_veri, urun2_baslik, urun2_veri):
    """İki ürünün ÖZET verilerini Llama'ya gönderip kıyaslama ister."""
    
    client = get_random_client()
    if not client: return "API Hatası: Anahtar bulunamadı."

    # --- KRİTİK ADIM: Veriyi küçültüyoruz ---
    ozet1 = veriyi_ozetle(urun1_veri)
    ozet2 = veriyi_ozetle(urun2_veri)
    # ----------------------------------------

    prompt = f"""
    Sen uzman bir alışveriş asistanısın. Aşağıda iki ürünün istatistiksel analiz verileri var.
    Yorum metinlerini okumadan, sadece bu sayılara bakarak objektif bir karşılaştırma yap.
    
    ÜRÜN 1: {json.dumps(ozet1, ensure_ascii=False)}
    
    ÜRÜN 2: {json.dumps(ozet2, ensure_ascii=False)}
    
    GÖREV:
    1. Hangi ürünün hangi konuda (Kargo, Kalite, Fiyat vb.) daha üstün olduğunu belirle.
    2. Negatif oranlarına dikkat et.
    3. Sonuç olarak birini öner.
    
    ÇIKTI FORMATI (HTML):
    <div class="analysis-result">
        <h3>🚀 Karşılaştırma Sonucu</h3>
        <p>Genel bir giriş cümlesi...</p>
        
        <div class="row">
            <div class="col-md-6">
                <h5 class="text-success">{urun1_baslik} Avantajları</h5>
                <ul>
                    <li>Madde 1...</li>
                </ul>
            </div>
            <div class="col-md-6">
                <h5 class="text-primary">{urun2_baslik} Avantajları</h5>
                <ul>
                    <li>Madde 1...</li>
                </ul>
            </div>
        </div>
        
        <hr>
        <div class="alert alert-info">
            <strong>🏆 Kazanan ve Öneri:</strong> Kimi neden seçmeli?
        </div>
    </div>
    """
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL_NAME, # Llama 3.3
            temperature=0.7
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"Karşılaştırma yapılamadı: {str(e)}"

# ... (Mevcut kodların en altına ekle) ...

def urune_soru_sor(urun_adi, analiz_verisi, soru):
    """
    Kullanıcının sorusunu cevaplarken hem istatistikleri hem de
    soruyla ilgili spesifik yorumları tarar (Mini-RAG).
    """
    client = get_random_client()
    if not client: return "Hata: API anahtarı bulunamadı."

    ozet_veri = veriyi_ozetle(analiz_verisi)
    ham_yorumlar = analiz_verisi.get('ham_yorumlar', [])
    ilgili_yorumlar = []
    
    if ham_yorumlar:
        # --- DÜZELTME 1: Harf Sınırı ---
        # > 3 yerine >= 3 yaptık. Artık "Ses", "Pil", "Hız" kelimeleri aranacak.
        anahtar_kelimeler = [k.lower() for k in soru.split() if len(k) >= 3]
        
        # Eğer soru çok kısaysa (örn: "pil?") ve hiç kelime kalmadıysa, soruyu olduğu gibi al
        if not anahtar_kelimeler and soru:
            anahtar_kelimeler = [soru.lower()]

        for yorum_obj in ham_yorumlar:
            yorum_metni = yorum_obj.get('yorum', '') if isinstance(yorum_obj, dict) else str(yorum_obj)
            yorum_metni_kucuk = yorum_metni.lower()
            
            if any(k in yorum_metni_kucuk for k in anahtar_kelimeler):
                ilgili_yorumlar.append(f"- {yorum_metni}")
    
    # --- DÜZELTME 2: Limit Artırımı ---
    # 15 az geliyordu, 50 yapalım. Llama 3.1 8b'nin hafızası (context window) geniştir, kaldırır.
    limit = 50
    if len(ilgili_yorumlar) > limit:
        # Rastgele 50 tane seç ki hep aynıları gelmesin
        import random
        ilgili_yorumlar = random.sample(ilgili_yorumlar, limit)
        
    ilgili_yorumlar_metni = "\n".join(ilgili_yorumlar) if ilgili_yorumlar else "Bu konuyla ilgili özel bir yorum bulunamadı."

    prompt = f"""
    Sen samimi, yardımsever ve profesyonel bir alışveriş asistanısın.
    Aşağıda bu ürünle ilgili istatistikler ve kullanıcı yorumlarından örnekler var.
    
    ÜRÜN: {urun_adi}
    
    VERİ KAYNAKLARI:
    1. GENEL İSTATİSTİKLER:
    {json.dumps(ozet_veri, ensure_ascii=False)}
    
    2. SORUYLA EŞLEŞEN YORUMLAR (Kanıtlar):
    {ilgili_yorumlar_metni}
    
    KULLANICI SORUSU: {soru}
    
    GÖREV:
    Kullanıcının sorusuna, elindeki verileri inceleyerek cevap ver.
    
    KURALLAR:
    1. ASLA "Kullanıcının sorduğu soru şudur" veya "Analiz edelim" gibi robotik girişler yapma.
    2. Direkt konuya gir: "Sizin için yorumları inceledim ve..." veya "Bu konuda kullanıcılar genellikle..." gibi başla.
    3. Cevabın sohbet havasında olsun ama verilere dayalı olsun.
    4. Eğer yorumlarda bilgi yoksa dürüstçe "Yorumlarda bu detaya değinilmemiş" de.
    """
        
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            temperature=0.5
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"Üzgünüm, şu an cevap veremiyorum. Hata: {str(e)}"