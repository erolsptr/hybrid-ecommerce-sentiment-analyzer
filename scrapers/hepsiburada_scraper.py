import time
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def safe_click(driver, element):
    """Tıklama işlemini garantiye alır (Header engelini aşar)."""
    try:
        # Önce elemente kaydır ve biraz yukarı pay bırak (Sticky header için)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        time.sleep(0.5)
        element.click()
        return True
    except:
        try:
            # Standart tıklama yemezse Javascript ile tıkla
            driver.execute_script("arguments[0].click();", element)
            return True
        except:
            return False

def cek(driver, url, limit):
    print("Hepsiburada Scraper (v4.0 - Strict Text Only) başlatıldı...")
    cekilen_veriler = []
    urun_basligi = "Bilinmeyen Hepsiburada Ürünü"
    
    try:
        driver.get(url)
        # Sayfanın yüklenmesini bekle
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        # 1. Çerezleri Kapat
        try:
            cerez = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler")))
            cerez.click()
        except: pass

        # 2. Ürün Başlığını Çek
        try:
            # Ürün sayfasındaki başlık (h1)
            baslik_elementi = driver.find_element(By.CSS_SELECTOR, "h1[data-test-id='title']")
            urun_basligi = baslik_elementi.text.strip().replace("\n", " ")
            print(f"Ürün Başlığı: {urun_basligi}")
        except:
            # Eğer yorumlar sayfasındaysak başlık farklı yerde olabilir
            try:
                baslik_elementi = driver.find_element(By.CSS_SELECTOR, "span[itemprop='name']")
                urun_basligi = baslik_elementi.text.strip()
            except: pass

        # 3. Yorumlar Sekmesine Git (Eğer linkte -yorumlari yoksa)
        if "-yorumlari" not in driver.current_url:
            print("Yorumlar sekmesi aranıyor...")
            try:
                # 'Değerlendirme' yazan linki bul
                yorum_linki = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//a[contains(@href, '-yorumlari')]"))
                )
                safe_click(driver, yorum_linki)
                time.sleep(3)
            except Exception as e:
                print("Yorum butonuna tıklanamadı (Belki zaten sayfadayız).")

        # 4. Yorumların Yüklenmesini Bekle (KRİTİK ADIM)
        print("Yorumlar yükleniyor...")
        try:
            # En az bir tane 'text-align: start' stilinde (metin içeren) span bekle
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//span[contains(@style, 'text-align') and contains(@style, 'start')]"))
            )
        except:
            print("Uyarı: Metin içeren yorum bulunamadı veya sayfa boş.")

        # 5. Yorum Toplama Döngüsü
        sayfa_no = 1
        
        while len(cekilen_veriler) < limit:
            print(f"--- Sayfa {sayfa_no} Taranıyor ---")
            
            # Sayfayı yavaşça aşağı kaydır (Lazy Load tetiklemek için)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 3);")
            time.sleep(0.5)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 1.5);")
            time.sleep(0.5)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
            
            # Kartları Bul (Senin verdiğin sınıf ismini kapsayan geniş seçici)
            kartlar = driver.find_elements(By.CSS_SELECTOR, "div[class*='hermes-ReviewCard-module']")
            
            bu_sayfadan_alinan = 0
            
            for kart in kartlar:
                if len(cekilen_veriler) >= limit: break
                
                try:
                    # Sadece METİN içeren yorumları al
                    # Senin verdiğin: <span style="text-align: start;">
                    try:
                        metin_elementi = kart.find_element(By.CSS_SELECTOR, "span[style*='text-align: start'], span[style*='text-align:start']")
                        yorum_metni = metin_elementi.text.strip()
                    except NoSuchElementException:
                        # Metin yoksa (sadece yıldızsa) bu kartı atla
                        continue
                    
                    if not yorum_metni: continue

                    # Puanı Çek (Yıldız sayısı)
                    # Senin verdiğin: <div class="star">...</div>
                    yildizlar = kart.find_elements(By.CLASS_NAME, "star")
                    puan = len(yildizlar)
                    if puan == 0: puan = 5 # Güvenlik

                    # Mükerrer kontrolü
                    if not any(v['yorum'] == yorum_metni for v in cekilen_veriler):
                        cekilen_veriler.append({'puan': puan, 'yorum': yorum_metni})
                        bu_sayfadan_alinan += 1

                except StaleElementReferenceException: continue
                except Exception: continue

            print(f"Sayfa {sayfa_no} Bitti: {bu_sayfadan_alinan} yeni metinli yorum alındı.")

            # --- KESİN DURMA KURALI ---
            # Eğer bu sayfayı taradık ama hiç metinli yorum bulamadıysak,
            # demek ki yorumlar bitti (Sadece puanlamalar kaldı). DUR.
            if bu_sayfadan_alinan == 0:
                print("⛔ Bu sayfada metinli yorum yok. İşlem sonlandırılıyor.")
                break

            if len(cekilen_veriler) >= limit: 
                print("Hedef limite ulaşıldı.")
                break
            
            # Sonraki Sayfaya Geçiş
            hedef_sayfa = sayfa_no + 1
            try:
                # Sayfa numarası butonunu bul (Örn: 2, 3)
                # Senin verdiğin: class="hermes-PageHolder-module..."
                xpath_pagination = f"//span[contains(@class, 'hermes-PageHolder') and text()='{hedef_sayfa}']"
                
                sonraki_sayfa_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, xpath_pagination))
                )
                
                # Butona tıkla
                if safe_click(driver, sonraki_sayfa_btn):
                    print(f"Sayfa {hedef_sayfa}'ye geçiliyor...")
                    time.sleep(3) # Sayfanın yüklenmesi için bekle
                    sayfa_no += 1
                else:
                    print("Sonraki sayfa butonuna tıklanamadı.")
                    break
                
            except TimeoutException:
                print("Sonraki sayfa butonu bulunamadı (Son sayfa).")
                break
            except Exception as e:
                print(f"Sayfa geçiş hatası: {e}")
                break
                
        print(f"Hepsiburada'dan toplam {len(cekilen_veriler)} yorum çekildi.")
        
        return {
            "baslik": urun_basligi,
            "yorumlar": cekilen_veriler
        }

    except Exception as e:
        print(f"Hepsiburada Hata: {e}")
        return {"baslik": urun_basligi, "yorumlar": [], "hata": str(e)}