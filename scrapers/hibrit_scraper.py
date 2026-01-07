import time
import re
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
import requests
import json
import os

from .trendyol_scraper import analyze_aspects_with_finetuned_model, parse_style_padding_to_rating
from .trendyol_gemini_scraper import analyze_batch_with_gemini

def cek(driver, url, limit):
    print("Hibrit (BERT + Gemini) Scraper Motoru v3 (Düzeltilmiş) başlatıldı...")
    
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

                # --- YAZIM HATASI DÜZELTİLDİ ---
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
        
        print(f"Trendyol'dan toplam {len(cekilen_veriler)} adet veri çekildi. Hibrit analiz başlıyor...")
        if not cekilen_veriler:
            return {"hata": "Analiz edilecek yorum bulunamadı."}

        print("Adım 2.1: BERT (eğitilmiş model) ile her yorum için ön analiz yapılıyor...")
        for veri in cekilen_veriler:
            bert_analizi = analyze_aspects_with_finetuned_model(veri['yorum'])
            veri['bert_on_analiz'] = bert_analizi
        print("BERT ön analizi tamamlandı.")

        print("Adım 2.2: Ön analiz sonuçları Gemini'ye gönderiliyor...")
        
        # BERT analiz sonuçlarını da içeren bir "yorum listesi" oluştur
        gemini_girdisi_listesi = []
        for y in cekilen_veriler:
            # Gemini'ye gönderilecek metni daha zengin hale getiriyoruz
            gonderilecek_yorum = f"Yorum: {y['yorum']} (İpucu: Bu yorumdaki potansiyel konular ve duyguları bir ast analist şöyle buldu: {y['bert_on_analiz']})"
            gemini_girdisi_listesi.append({'puan': y['puan'], 'yorum': gonderilecek_yorum})
            
        final_summary = analyze_batch_with_gemini(gemini_girdisi_listesi)
        
        final_summary["analiz_edilen_yorum_sayisi"] = len(cekilen_veriler)
        return final_summary

    except Exception as e:
        print(f"Hibrit scraper'da bir hata oluştu: {e}")
        return {"hata": f"Bir hata oluştu: {e}"}