import time
import re
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def parse_rating_from_style(style_text):
    """
    Örn: style="--rating: 80;" stringinden 80'i alıp 5 üzerinden puana çevirir.
    80 -> 4 Puan, 100 -> 5 Puan.
    """
    if not style_text: return 5
    match = re.search(r'--rating:\s*([0-9]+)', style_text)
    if match:
        rating_value = int(match.group(1))
        return int(rating_value / 20) # 100/20 = 5, 80/20 = 4
    return 5

def cek(driver, url, limit):
    print("N11 Scraper (Vue.js / Infinite Scroll) başlatıldı...")
    cekilen_veriler = []
    
    try:
        driver.get(url)
        # Sayfanın yüklenmesini bekle
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        # Çerez / Popup Kapatma
        try:
            # N11'in "Tamam" veya "Kabul Et" butonu (Genelde class'ı btn-approve veya benzeri)
            cerez = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.CLASS_NAME, "btn-approve")))
            cerez.click()
            print("Çerez kapatıldı.")
        except: pass

        # --- ADIM 1: Yorumlar Sayfasına/Kısmına Git ---
        print("Değerlendirmeler bağlantısı aranıyor...")
        try:
            # Senin verdiğin ID: all-review-for-product
            yorum_linki = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "all-review-for-product"))
            )
            # Tıklamadan önce kaydır
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", yorum_linki)
            time.sleep(1)
            yorum_linki.click()
            print("Değerlendirmeler bağlantısına tıklandı.")
            
            # Yeni sayfaya geçebilir veya aşağı kayabilir. 
            # Yorumların yüklendiğini anlamak için yorum metnini içeren bir class bekleyelim.
            # Senin verdiğin class: card-detail__contents
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "card-detail__contents"))
            )
            print("Yorumlar görünür oldu.")
            
        except Exception as e:
            print(f"Yorumlara geçişte sorun (Belki zaten yorum sayfasındayızdır): {e}")

        # --- ADIM 2: Infinite Scroll (Sonsuz Kaydırma) ---
        print(f"Akıllı kaydırma başladı (Hedef: {limit} yorum)...")
        last_height = driver.execute_script("return document.body.scrollHeight")
        
        # Yorumları toplamak için bir döngü
        # N11'de DOM sürekli güncellendiği için önce kaydırıp yükletiyoruz, sonra topluyoruz.
        
        while True:
            # Mevcut yorum sayısını kontrol et (Hızlı bir kontrol)
            yorum_sayisi = len(driver.find_elements(By.CLASS_NAME, "card-detail__contents"))
            if yorum_sayisi >= limit:
                print("Yeterli yorum yüklendi.")
                break
            
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2) # Yükleme için bekle
            
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                print("Sayfa sonuna ulaşıldı (Daha fazla yüklenmiyor).")
                break
            last_height = new_height
            print(f"Yüklenen tahmini yorum sayısı: {yorum_sayisi}...")

        # --- ADIM 3: Verileri Ayrıştırma (Parsing) ---
        print("Veriler analiz ediliyor...")
        
        # Yorum kartlarını bulma stratejisi:
        # Metin class'ı: card-detail__contents
        # Puan class'ı: stars (style="--rating: 100;")
        # Bu ikisi genellikle aynı "li" veya "div" kapsayıcısının içindedir.
        
        # Tüm yorum kapsayıcılarını bulalım (Genel bir kapsayıcı arıyoruz)
        # Metni barındıran en yakın "li" etiketini bulmak mantıklı (N11 genelde liste kullanır)
        yorum_metinleri_elementleri = driver.find_elements(By.CLASS_NAME, "card-detail__contents")
        
        for metin_elem in yorum_metinleri_elementleri:
            if len(cekilen_veriler) >= limit: break
            
            try:
                yorum_metni = metin_elem.text.strip()
                if not yorum_metni: continue

                # Puanı bulmak için metin elementinin yukarısına (parent/ancestor) çıkıp 
                # oradan "stars" sınıfını arayacağız.
                # XPath: Bu elementin atalarından (ancestor) içinde 'stars' classı olan bir div bul.
                
                try:
                    # Metin elementinin bulunduğu kartın (kapsayıcının) içindeki yıldız elementini bul
                    # XPath açıklaması: Şu anki metin elementinin (self) ebeveynlerinden (ancestor::li veya div)
                    # gidip, onun altındaki (descendant) .stars sınıfını bul.
                    star_elem = metin_elem.find_element(By.XPATH, "./preceding::div[contains(@class, 'stars')][1] | ./ancestor::li//div[contains(@class, 'stars')]")
                    
                    style_attr = star_elem.get_attribute("style") # örn: --rating: 100;
                    puan = parse_rating_from_style(style_attr)
                except NoSuchElementException:
                    puan = 5 # Bulunamazsa varsayılan
                
                # Mükerrer kontrolü
                if not any(v['yorum'] == yorum_metni for v in cekilen_veriler):
                    cekilen_veriler.append({'puan': puan, 'yorum': yorum_metni})

            except Exception as e:
                continue

        print(f"N11'den toplam {len(cekilen_veriler)} yorum çekildi.")
        return cekilen_veriler

    except Exception as e:
        print(f"N11 Scraper Hatası: {e}")
        return [{"hata": f"N11 işlem hatası: {e}"}]