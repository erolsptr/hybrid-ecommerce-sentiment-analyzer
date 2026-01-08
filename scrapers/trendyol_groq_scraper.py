import time
import re
import os
import json
from dotenv import load_dotenv
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
import concurrent.futures

# Groq Kütüphanesi
from groq import Groq

load_dotenv()

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