import time
import re
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def parse_rating_from_style(style_text):
    if not style_text: return 5
    match = re.search(r'--rating:\s*([0-9]+)', style_text)
    if match:
        rating_value = int(match.group(1))
        return int(rating_value / 20) 
    return 5

def cek(driver, url, limit):
    print("N11 Scraper (Vue.js / Infinite Scroll) başlatıldı...")
    cekilen_veriler = []
    urun_basligi = "Bilinmeyen N11 Ürünü" 
    
    try:
        driver.get(url)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        # --- GÜNCELLENEN BAŞLIK ÇEKME ALANI ---
        baslik_bulundu = False
        # 1. Deneme: Ürün Sayfası (h1.title)
        try:
            baslik_elementi = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "h1.title"))
            )
            urun_basligi = baslik_elementi.text.strip()
            print(f"Ürün Başlığı (Ana Sayfa): {urun_basligi}")
            baslik_bulundu = True
        except: pass

        # 2. Deneme: Yorum Sayfası (product-card-details-title)
        if not baslik_bulundu:
            try:
                baslik_elementi = driver.find_element(By.CLASS_NAME, "product-card-details-title")
                urun_basligi = baslik_elementi.text.strip()
                print(f"Ürün Başlığı (Yorum Sayfası): {urun_basligi}")
                baslik_bulundu = True
            except: 
                print("Ürün başlığı çekilemedi.")
        # -------------------------------------

        # Çerez / Popup Kapatma
        try:
            cerez = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.CLASS_NAME, "btn-approve")))
            cerez.click()
            print("Çerez kapatıldı.")
        except: pass

        # --- ADIM 1: Yorumlar Sayfasına Git ---
        print("Değerlendirmeler bağlantısı aranıyor...")
        try:
            yorum_linki = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "all-review-for-product"))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", yorum_linki)
            time.sleep(1)
            yorum_linki.click()
            print("Değerlendirmeler bağlantısına tıklandı.")
            
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "card-detail__contents"))
            )
            print("Yorumlar görünür oldu.")
            
        except Exception as e:
            print(f"Yorumlara geçişte sorun: {e}")

        # --- ADIM 2: Infinite Scroll ---
        print(f"Akıllı kaydırma başladı (Hedef: {limit} yorum)...")
        last_height = driver.execute_script("return document.body.scrollHeight")
        
        while True:
            yorum_sayisi = len(driver.find_elements(By.CLASS_NAME, "card-detail__contents"))
            if yorum_sayisi >= limit:
                print("Yeterli yorum yüklendi.")
                break
            
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                print("Sayfa sonuna ulaşıldı.")
                break
            last_height = new_height
            print(f"Yüklenen tahmini yorum sayısı: {yorum_sayisi}...")

        # --- ADIM 3: Verileri Ayrıştırma ---
        print("Veriler analiz ediliyor...")
        yorum_metinleri_elementleri = driver.find_elements(By.CLASS_NAME, "card-detail__contents")
        
        for metin_elem in yorum_metinleri_elementleri:
            if len(cekilen_veriler) >= limit: break
            try:
                yorum_metni = metin_elem.text.strip()
                if not yorum_metni: continue

                try:
                    star_elem = metin_elem.find_element(By.XPATH, "./preceding::div[contains(@class, 'stars')][1] | ./ancestor::li//div[contains(@class, 'stars')]")
                    style_attr = star_elem.get_attribute("style") 
                    puan = parse_rating_from_style(style_attr)
                except NoSuchElementException:
                    puan = 5 
                
                if not any(v['yorum'] == yorum_metni for v in cekilen_veriler):
                    cekilen_veriler.append({'puan': puan, 'yorum': yorum_metni})

            except Exception:
                continue

        print(f"N11'den toplam {len(cekilen_veriler)} yorum çekildi.")
        
        return {
            "baslik": urun_basligi,
            "yorumlar": cekilen_veriler
        }

    except Exception as e:
        print(f"N11 Scraper Hatası: {e}")
        return {"baslik": urun_basligi, "yorumlar": [], "hata": str(e)}