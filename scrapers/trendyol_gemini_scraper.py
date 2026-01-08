import time
import re
import os
from dotenv import load_dotenv
import concurrent.futures 

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
import requests
import json

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
MODEL_NAME = "gemini-3-flash-preview" 

BATCH_SIZE = 100

def parse_style_padding_to_rating(style_text):
    if not style_text or 'padding-inline-end' not in style_text: return 5
    match = re.search(r'padding-inline-end:\s*([0-9.]+)px', style_text)
    if match:
        padding = float(match.group(1))
        if padding > 60: return 1
        if padding > 45: return 2
        if padding > 30: return 3
        if padding > 15: return 4
    return 5

def call_gemini_api(partial_comments):
    tum_yorumlar_metni = "\n---\n".join([f"Puan: {y['puan']}, Yorum: {y['yorum']}" for y in partial_comments])
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GOOGLE_API_KEY}"

    prompt = f"""
    Sen bir e-ticaret yorum analistisin. Aşağıdaki yorumları analiz et.
    
    KURALLAR:
    1. Analizlerini KESİNLİKLE sadece şu ana kategoriler altında topla:
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
    3. Cevabı SADECE aşağıdaki JSON formatında ver.

    YORUMLAR:
    {tum_yorumlar_metni}

    JSON CEVABI:
    {{
      "konu_analizleri": [
        {{
          "konu": "Kategori Adı",
          "pozitif_yorumlar": ["Yorum metni..."],
          "negatif_yorumlar": ["Yorum metni..."],
          "notr_yorumlar": []
        }}
      ]
    }}
    """
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(api_url, json=payload, timeout=120)
            response.raise_for_status() 
            
            result = response.json()
            if 'candidates' not in result or not result['candidates']:
                return {"konu_analizleri": []}
                
            json_response_text = result['candidates'][0]['content']['parts'][0]['text'].strip()
            json_response_text = json_response_text.replace("```json", "").replace("```", "")
            return json.loads(json_response_text)

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                wait_time = 15 + (attempt * 15) 
                print(f"⚠️ API Kotası (429). {wait_time}sn bekleniyor... (Deneme {attempt+1}/{max_retries})")
                time.sleep(wait_time)
            else:
                return {"konu_analizleri": []}
        except Exception as e:
            return {"konu_analizleri": []}
    
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

def analyze_batch_with_gemini(yorum_listesi):
    if not GOOGLE_API_KEY: return {"hata": "API Anahtarı eksik."}

    batches = []
    for i in range(0, len(yorum_listesi), BATCH_SIZE):
        batches.append(yorum_listesi[i:i + BATCH_SIZE])

    print(f"Toplam {len(yorum_listesi)} yorum, {len(batches)} paralel paket halinde işlenecek...")
    all_results = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_to_batch = {executor.submit(call_gemini_api, batch): i for i, batch in enumerate(batches)}
        
        for future in concurrent.futures.as_completed(future_to_batch):
            batch_index = future_to_batch[future]
            try:
                data = future.result()
                if data:
                    all_results.append(data)
                    print(f"   -> Paket {batch_index + 1} tamamlandı ✅")
            except Exception as e:
                print(f"   -> Paket {batch_index + 1} HATA ALDI ❌: {e}")

    print("Tüm paralel işlemler tamamlandı, sonuçlar birleştiriliyor...")
    return merge_results(all_results)

def cek(driver, url, limit):
    print("Trendyol Scraper (Başlık + Yorum v2) başlatıldı...")
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

        # --- GÜNCELLENEN BAŞLIK ÇEKME ALANI ---
        baslik_bulundu = False
        # 1. Deneme: Ürün Sayfası Başlığı
        try:
            baslik_elementi = driver.find_element(By.CLASS_NAME, "product-title")
            urun_basligi = baslik_elementi.text.strip()
            print(f"Ürün Başlığı (Ana Sayfa): {urun_basligi}")
            baslik_bulundu = True
        except: pass
        
        # 2. Deneme: Yorumlar Sayfası Başlığı (Senin verdiğin selector)
        if not baslik_bulundu:
            try:
                baslik_elementi = driver.find_element(By.CLASS_NAME, "info-title-text")
                urun_basligi = baslik_elementi.text.strip()
                print(f"Ürün Başlığı (Yorum Sayfası): {urun_basligi}")
                baslik_bulundu = True
            except: pass
            
        # 3. Deneme: Eski Yöntemler (Fallback)
        if not baslik_bulundu:
            try:
                marka = driver.find_element(By.CLASS_NAME, "pr-new-br").text
                ad = driver.find_element(By.CLASS_NAME, "pr-nm").text
                urun_basligi = f"{marka} {ad}"
            except:
                print("Başlık çekilemedi.")
        # --------------------------------------

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