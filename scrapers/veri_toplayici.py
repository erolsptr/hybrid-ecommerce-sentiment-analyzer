import time
import re
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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

def topla(driver, url, limit):
    print("Trendyol Veri Toplayıcı başlatıldı...")
    
    cekilen_veriler = []
    cekilen_yorum_metinleri = set()

    try:
        driver.get(url)
        time.sleep(2)
        try:
            cerez_butonu = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler")))
            cerez_butonu.click(); print("Çerez banner'ı kapatıldı."); time.sleep(1)
        except (NoSuchElementException, TimeoutException): print("Çerez banner'ı bulunamadı.")
        try:
            anladim_butonu = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CLASS_NAME, "onboarding__default-renderer-primary-button")))
            anladim_butonu.click(); print("'Anladım' butonuna tıklandı."); time.sleep(1)
        except (NoSuchElementException, TimeoutException): print("Konum pop-up'ı çıkmadı.")

        if "/yorumlar" not in driver.current_url:
            try:
                degerlendirmeler_butonu = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CLASS_NAME, "reviews-summary-reviews-detail")))
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", degerlendirmeler_butonu)
                time.sleep(1); degerlendirmeler_butonu.click(); print("Değerlendirmeler sayfasına geçildi."); time.sleep(3)
            except (NoSuchElementException, TimeoutException):
                return [{"hata": "Değerlendirmeler butonu bulunamadı veya tıklanamadı."}]
        
        print("Akıllı kaydırma başladı...")
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
        
        print(f"Trendyol'dan toplam {len(cekilen_veriler)} adet yorum çekildi.")
        return cekilen_veriler[:limit]

    except Exception as e:
        print(f"Trendyol scraper'da bir hata oluştu: {e}")
        return [{"hata": f"Bir hata oluştu: {e}"}]