import time
import re
import os  
from dotenv import load_dotenv 

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
import requests
import json

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
MODEL_NAME = "gemini-flash-latest" 
BATCH_SIZE = 40

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
    """Belirli bir yorum grubu için API çağrısı yapar."""
    tum_yorumlar_metni = "\n---\n".join([f"Puan: {y['puan']}, Yorum: {y['yorum']}" for y in partial_comments])
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GOOGLE_API_KEY}"

    prompt = f"""
    Sen bir e-ticaret yorum analistisin. Aşağıdaki yorumları analiz et.
    
    KURALLAR:
    1. Analizlerini KESİNLİKLE sadece şu ana kategoriler altında topla (Başka kategori uydurma):
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
    3. Konuları eşleştirirken akıllı davran: "Kırık geldi", "bozuldu", "çalışmıyor" -> "Dayanıklılık ve Arıza"; "Geç geldi" -> "Kargo ve Teslimat".
    4. Cevabı SADECE aşağıdaki JSON formatında ver.

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
    try:
        response = requests.post(api_url, json=payload, timeout=120)
        response.raise_for_status()
        result = response.json()
        if 'candidates' not in result or not result['candidates']:
            return {"konu_analizleri": []}
            
        json_response_text = result['candidates'][0]['content']['parts'][0]['text'].strip()
        json_response_text = json_response_text.replace("```json", "").replace("```", "")
        return json.loads(json_response_text)
    except Exception as e:
        print(f"Gemini API parçalı istek hatası: {e}")
        return {"konu_analizleri": []}

def merge_results(results_list):
    """Birden fazla API cevabını tek bir JSON yapısında birleştirir."""
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
    if not GOOGLE_API_KEY or " " in GOOGLE_API_KEY:
        print("KRİTİK HATA: Google API Anahtarı bulunamadı! .env dosyasını kontrol edin.")
        return {"hata": "API Anahtarı eksik."}

    print(f"Toplam {len(yorum_listesi)} yorum analiz edilecek. {BATCH_SIZE}'arlı paketler halinde gönderiliyor...")
    
    all_results = []
    for i in range(0, len(yorum_listesi), BATCH_SIZE):
        batch = yorum_listesi[i:i + BATCH_SIZE]
        print(f"   -> Paket işleniyor: {i} - {i + len(batch)} arası...")
        batch_result = call_gemini_api(batch)
        all_results.append(batch_result)
        time.sleep(1.5) 

    print("Tüm paketler tamamlandı, sonuçlar birleştiriliyor...")
    return merge_results(all_results)

def cek(driver, url, limit):
    print("Trendyol GEMINI Scraper (Detaylı Analiz - Secure Key) başlatıldı...")
    
    cekilen_veriler = []
    cekilen_yorum_metinleri = set()

    try:
        driver.get(url)
        time.sleep(3)
        try:
            cerez_kabul_butonu = driver.find_element(By.ID, "onetrust-accept-btn-handler")
            driver.execute_script("arguments[0].click();", cerez_kabul_butonu); print("Çerez banner'ı kapatıldı."); time.sleep(1)
        except Exception: print("Çerez banner'ı bulunamadı.")
        try:
            anladim_butonu = driver.find_element(By.CLASS_NAME, "onboarding__default-renderer-primary-button")
            anladim_butonu.click(); print("'Anladım' butonuna tıklandı."); time.sleep(1)
        except Exception: print("Konum pop-up'ı çıkmadı.")
        if "/yorumlar" not in driver.current_url:
            try:
                degerlendirmeler_butonu = driver.find_element(By.CLASS_NAME, "reviews-summary-reviews-detail")
                driver.execute_script("arguments[0].scrollIntoView(true);", degerlendirmeler_butonu)
                time.sleep(1); degerlendirmeler_butonu.click(); print("Değerlendirmeler sayfasına geçildi."); time.sleep(3)
            except NoSuchElementException: return {"hata": "Değerlendirmeler butonu bulunamadı."}
        
        print(f"Akıllı kaydırma başladı (Hedef: {limit} yorum)...")
        son_kart_sayisi = 0
        while len(cekilen_yorum_metinleri) < limit:
            kart_elementleri = driver.find_elements(By.CSS_SELECTOR, ".review, .review-card")
            if len(kart_elementleri) == son_kart_sayisi and len(kart_elementleri) > 0:
                print("Sayfanın sonuna ulaşıldı."); break
            son_kart_sayisi = len(kart_elementleri)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);"); time.sleep(2)
        
        kart_elementleri = driver.find_elements(By.CSS_SELECTOR, ".review, .review-card")
        
        for kart in kart_elementleri:
            try:
                yorum_metni_elementi = kart.find_elements(By.CLASS_NAME, "review-comment")
                if not yorum_metni_elementi: continue
                yorum_metni = yorum_metni_elementi[0].text
                if not yorum_metni or yorum_metni in cekilen_yorum_metinleri: continue
                devamini_oku_buton = kart.find_elements(By.CLASS_NAME, "read-more")
                if devamini_oku_buton:
                    driver.execute_script("arguments[0].click();", devamini_oku_buton[0]); time.sleep(0.5)
                    yorum_metni = kart.find_element(By.CLASS_NAME, "review-comment").text
                star_div = kart.find_element(By.CLASS_NAME, "star-rating-full-star")
                style_attributu = star_div.get_attribute('style')
                puan = parse_style_padding_to_rating(style_attributu)
                if yorum_metni:
                    cekilen_veriler.append({'puan': puan, 'yorum': yorum_metni})
                    cekilen_yorum_metinleri.add(yorum_metni)
            except Exception:
                continue
        
        print(f"Trendyol'dan toplam {len(cekilen_veriler)} adet veri çekildi. Şimdi toplu analiz başlıyor...")
        if not cekilen_veriler:
            return {"hata": "Analiz edilecek yorum bulunamadı."}

        final_summary = analyze_batch_with_gemini(cekilen_veriler)
        final_summary["analiz_edilen_yorum_sayisi"] = len(cekilen_veriler)
        return final_summary

    except Exception as e:
        print(f"Trendyol Gemini scraper'da bir hata oluştu: {e}")
        return {"hata": f"Bir hata oluştu: {e}"}