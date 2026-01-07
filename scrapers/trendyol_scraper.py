import time
import re
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException

import nltk
from nltk.corpus import stopwords
from transformers import pipeline
import os

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

print("Trendyol Scraper için eğittiğimiz model yükleniyor...")
try:
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    nltk_resources = ["punkt", "stopwords", "averaged_perceptron_tagger", "universal_tagset"]
    for resource in nltk_resources:
        try:
            if resource in ["punkt", "stopwords"]: nltk.data.find(f"corpora/{resource}")
            else: nltk.data.find(f"taggers/{resource}")
        except LookupError: nltk.download(resource)

    yerel_model_yolu = "./yeni_modelim/best"
    
    sentiment_analyzer = pipeline(
        "sentiment-analysis", 
        model=yerel_model_yolu,
        model_kwargs={"id2label": {0: "negative", 1: "neutral", 2: "positive"}}
    )
    
    print("Modelimiz başarıyla yüklendi!")
    MODELS_LOADED = True
except Exception as e:
    print(f"Model yüklenirken bir hata oluştu: {e}")
    MODELS_LOADED = False

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

def find_true_aspects(text):
    stop_words = set(stopwords.words('turkish'))
    stop_words.update(["ürün", "ürünü", "şey", "fiyat", "teşekkür", "bence", "gibi", "bir", "cok", "çok", "daha", "kadar", "göre", "aldım", "gerçekten", "tek", "gece", "artık", "gün", "tam", "şekilde", "için"])
    aspects = []
    try:
        tokens = nltk.word_tokenize(text.lower(), language='turkish')
        tagged_words = nltk.pos_tag(tokens, tagset='universal')
        for word, tag in tagged_words:
            if tag == 'NOUN' and word.isalpha() and len(word) > 3 and word not in stop_words:
                aspects.append(word)
    except Exception:
        pass
    return list(dict.fromkeys(aspects))

def analyze_aspects_with_finetuned_model(text):
    if not MODELS_LOADED: return {"hata": "Model yüklenemedi."}
    
    aspects = find_true_aspects(text)
    if not aspects: return {}
    
    analysis_results = {}
    sentences = nltk.sent_tokenize(text, language='turkish')
    
    for aspect in aspects:
        for sentence in sentences:
            if aspect in sentence.lower():
                try:
                    result = sentiment_analyzer(sentence)[0]
                    
                    if result['label'] == 'positive': label = "Pozitif"
                    elif result['label'] == 'neutral': label = "Nötr"
                    else: label = "Negatif"
                    
                    analysis_results[aspect] = label
                except Exception as e:
                    print(f"'{aspect}' analizi sırasında hata: {e}")
                    continue
    return analysis_results

def cek(driver, url, limit):
    print("Trendyol Scraper (Kendi Modelimizle) başlatıldı...")
    cekilen_veriler = []; cekilen_yorum_metinleri = set()

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
                print("Değerlendirmeler butonu bekleniyor...")
                degerlendirmeler_butonu = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CLASS_NAME, "reviews-summary-reviews-detail")))
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", degerlendirmeler_butonu)
                time.sleep(1); degerlendirmeler_butonu.click(); print("Değerlendirmeler sayfasına geçildi."); time.sleep(3)
            except (NoSuchElementException, TimeoutException):
                return [{"puan": 0, "yorum": "Değerlendirmeler butonu bulunamadı veya tıklanamadı."}]
        
        print("Akıllı kaydırma başladı...")
        son_kart_sayisi = 0
        while True:
            kart_elementleri = driver.find_elements(By.CSS_SELECTOR, ".review, .review-card")
            if len(kart_elementleri) >= limit or (len(kart_elementleri) == son_kart_sayisi and len(kart_elementleri) > 0): break
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
                
                ozellikler = analyze_aspects_with_finetuned_model(yorum_metni)
                
                if yorum_metni:
                    cekilen_veriler.append({ 'puan': puan, 'yorum': yorum_metni, 'ozellikler': ozellikler })
                    cekilen_yorum_metinleri.add(yorum_metni)
            except Exception as e:
                print(f"Bir kart işlenirken hata: {e}")
                continue
        
        print(f"Trendyol'dan toplam {len(cekilen_veriler)} adet veri çekildi ve kendi modelimizle analiz edildi.")
        return cekilen_veriler[:limit]

    except Exception as e:
        print(f"Trendyol scraper'da bir hata oluştu: {e}")
        return [{"puan": 0, "yorum": f"Hata: {e}"}]