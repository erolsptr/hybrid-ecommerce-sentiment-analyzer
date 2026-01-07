import time
import json
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def veriyi_js_objesinden_cek(driver, cekilen_veriler, limit):
    print("Sayfa kaynağındaki JavaScript objesi (Sayfa 1 için) aranıyor...")
    try:
        hermes_obj = driver.execute_script("return window.HERMES.YORUMLAR;")
        state_key = list(hermes_obj.keys())[0]
        veri = hermes_obj[state_key]['STATE']
        yorumlar_listesi = veri.get("data", {}).get("userReviews", {}).get("data", {}).get("approvedUserContent", {}).get("approvedUserContentList", [])
        
        if not yorumlar_listesi: return 0

        bu_sayfadan_cekilen_sayisi = 0
        for yorum in yorumlar_listesi:
            yorum_metni = yorum.get("review", {}).get("content")
            puan = yorum.get("star")

            if yorum_metni and puan:
                is_duplicate = any(item['yorum'] == yorum_metni for item in cekilen_veriler)
                if not is_duplicate:
                    cekilen_veriler.append({ 'puan': puan, 'yorum': yorum_metni })
                    bu_sayfadan_cekilen_sayisi += 1
                if len(cekilen_veriler) >= limit: break
        return bu_sayfadan_cekilen_sayisi
    except Exception:
        return 0

def veriyi_html_den_cek(driver, cekilen_veriler, limit):
    print("Sayfa HTML'i (Sayfa 2+ için) analiz ediliyor...")
    try:
        # --- YENİ ADIM: Yorumların yüklenmesini tetiklemek için kaydır ---
        print("Yorumların yüklenmesi için sayfa kaydırılıyor...")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(2)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        # Güvenilir hedefleri kullan
        kart_selector = "div[class*='hermes-ReviewCard-module-']"
        kart_elementleri = driver.find_elements(By.CSS_SELECTOR, kart_selector)
        
        bu_sayfadan_cekilen_sayisi = 0

        for kart in kart_elementleri:
            try:
                metin_selector = "span[style='text-align:start']"
                metin_elementleri = kart.find_elements(By.CSS_SELECTOR, metin_selector)
                if not metin_elementleri or not metin_elementleri[0].text.strip():
                    continue

                yorum_metni = metin_elementleri[0].text
                dolu_yildizlar = kart.find_elements(By.CLASS_NAME, "star")
                puan = len(dolu_yildizlar)

                if puan > 0 and yorum_metni:
                    is_duplicate = any(item['yorum'] == yorum_metni for item in cekilen_veriler)
                    if not is_duplicate:
                        cekilen_veriler.append({ 'puan': puan, 'yorum': yorum_metni })
                        bu_sayfadan_cekilen_sayisi += 1
                    if len(cekilen_veriler) >= limit: break
            except (StaleElementReferenceException, NoSuchElementException):
                continue
        return bu_sayfadan_cekilen_sayisi
    except Exception:
        return 0


def cek(driver, url, limit):
    print("Hepsiburada Scraper Motoru v17.1 (Düzeltilmiş Hibrit) başlatıldı...")
    cekilen_veriler = []
    
    try:
        driver.get(url)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        try:
            cerez_kabul_butonu = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler")))
            cerez_kabul_butonu.click(); print("Çerez banner'ı kapatıldı."); time.sleep(1)
        except (NoSuchElementException, TimeoutException):
            print("Çerez banner'ı bulunamadı veya zaten kapalı.")

        if "-yorumlari" not in driver.current_url:
            try:
                degerlendirmeler_butonu = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CLASS_NAME, "yPPu6UogPlaotjhx1Qki")))
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", degerlendirmeler_butonu)
                time.sleep(1); degerlendirmeler_butonu.click(); print("Değerlendirmeler sayfasına geçildi.")
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "hermes-voltran-comments")))
            except (NoSuchElementException, TimeoutException):
                return []

        suanki_sayfa_no = 1
        
        while len(cekilen_veriler) < limit:
            print(f"\n--- Sayfa {suanki_sayfa_no} işleniyor ---")
            
            if suanki_sayfa_no == 1:
                bu_sayfadan_cekilen_sayisi = veriyi_js_objesinden_cek(driver, cekilen_veriler, limit)
            else:
                bu_sayfadan_cekilen_sayisi = veriyi_html_den_cek(driver, cekilen_veriler, limit)
            
            print(f"Sayfa {suanki_sayfa_no} tamamlandı. Bu sayfadan {bu_sayfadan_cekilen_sayisi} metinli yorum çekildi.")

            if len(cekilen_veriler) >= limit or (bu_sayfadan_cekilen_sayisi == 0 and suanki_sayfa_no > 1):
                break
            
            hedef_sayfa_no = suanki_sayfa_no + 1
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                xpath_selector = f"//span[contains(@class, 'hermes-PageHolder-module-mgMeakg82BKyETORtkiQ') and text()='{hedef_sayfa_no}']"
                sonraki_sayfa_butonu = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, xpath_selector)))
                sonraki_sayfa_butonu.click()
                print(f"Sayfa {hedef_sayfa_no}'a geçildi. Yeni sayfanın yüklenmesi bekleniyor...")
                time.sleep(5)
                suanki_sayfa_no = hedef_sayfa_no
            except (NoSuchElementException, TimeoutException):
                print(f"Sayfa {hedef_sayfa_no} butonu bulunamadı. Son sayfa."); break
        
        print(f"Hepsiburada'dan toplam {len(cekilen_veriler)} adet metinli yorum çekildi.")

    except Exception as e:
        print(f"Hepsiburada scraper'da bir hata oluştu: {e}")
        return [{"puan": 0, "yorum": f"Hata: {e}"}]

    return cekilen_veriler