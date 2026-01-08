import time
import re
from transformers import pipeline
import os

print("Trendyol Scraper (BERT - Strict Mode) başlatılıyor...")

try:
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    yerel_model_yolu = "./yeni_modelim/best"
    
    if os.path.exists(yerel_model_yolu):
        print("✅ Eğitilmiş yerel model bulundu.")
        model_source = yerel_model_yolu
    else:
        print("⚠️ Varsayılan 'savasy/bert' modeli kullanılıyor.")
        model_source = "savasy/bert-base-turkish-sentiment-cased"

    sentiment_analyzer = pipeline(
        "sentiment-analysis", 
        model=model_source,
        truncation=True
    )
    MODELS_LOADED = True
except Exception as e:
    print(f"Model yüklenirken hata: {e}")
    MODELS_LOADED = False

def find_true_aspects(text):
    text = text.lower()
    
    # E-Ticaret Whitelist
    valid_aspects = [
        "kargo", "paket", "paketleme", "teslimat", "satıcı", "mağaza", "hız",
        "kalite", "malzeme", "kumaş", "dikiş", "beden", "kalıp", "renk", "boyut", "ebat",
        "ses", "gürültü", "tiz", "mikrofon", "şarj", "pil", "batarya", "kablo", # "bas" çıkarıldı
        "ekran", "görüntü", "kamera", "fotoğraf", "video", "hafıza", "işlemci", "donanım",
        "kurulum", "montaj", "parça", "vida", "kutu", "ambalaj", "kapak", "kılıf",
        "tat", "lezzet", "koku", "tazelik", "kıvam", 
        "etki", "performans", "işlev", "çekim", "güç", "motor", "soğutma", "ısıtma",
        "doku", "yumuşaklık", "rahatlık", "konfor", "tasarım", "görünüm", "duruş", "şık",
        "fiyat", "değer"
    ]
    
    found_aspects = []
    
    for aspect in valid_aspects:
        pattern = r'\b' + aspect + r'[a-zçğıöşü]*'
        if re.search(pattern, text):
            found_aspects.append(aspect)
            
    return found_aspects

def check_negation(sentence, keyword):
    """'Sorun yok', 'Kırık değil' gibi durumları kontrol eder."""
    negators = ["yok", "değil", "olmadı", "yaşamadım", "çıkmadı", "gelmedi", "etmedi", "yapmadı"]
    sentence = sentence.lower()
    if keyword in sentence:
        parts = sentence.split(keyword)
        if len(parts) > 1:
            after_part = parts[1]
            # Kelimeden sonraki kısımda olumsuzluk eki var mı?
            for neg in negators:
                if neg in after_part: return True
    return False

def split_into_segments(text):
    """Metni bağlaçlara göre daha agresif böler."""
    sentences = re.split(r'[.!?]+', text)
    segments = []
    # Bağlaç listesi
    conjunctions = [" ama ", " fakat ", " lakin ", " ancak ", " rağmen ", " oysa ", " yalnız ", " ve "]
    
    for sent in sentences:
        temp_segments = [sent]
        for conj in conjunctions:
            new_temp = []
            for seg in temp_segments:
                if conj in seg.lower():
                    new_temp.extend(re.split(conj, seg, flags=re.IGNORECASE))
                else:
                    new_temp.append(seg)
            temp_segments = new_temp
        segments.extend(temp_segments)
    
    return [s.strip() for s in segments if s.strip()]

def analyze_aspects_with_finetuned_model(text):
    if not MODELS_LOADED: return {}
    
    aspects = find_true_aspects(text)
    if not aspects: return {} 
    
    analysis_results = {}
    segments = split_into_segments(text)
    
    for aspect in aspects:
        # İlgili segmenti bul
        relevant_segment = next((s for s in segments if aspect in s.lower()), text)
        
        try:
            # 1. BERT Analizi
            result = sentiment_analyzer(relevant_segment[:512])[0]
            label_raw = result['label']
            
            if label_raw in ['positive', 'LABEL_2', 'POS']: duygu = "Pozitif"
            elif label_raw in ['neutral', 'LABEL_1', 'NEU']: duygu = "Nötr"
            else: duygu = "Negatif"
            
            # 2. Heuristics (Kural Bazlı Düzeltmeler)
            
            # Negatif Kelime Listesi (Genişletilmiş)
            # "keşke", "özensiz", "ezilmiş" gibi kelimeler eklendi.
            neg_keywords = [
                "kırık", "bozuk", "kötü", "berbat", "rezalet", "iade", "sorun", "yavaş", 
                "beğenmedim", "defolu", "çizik", "leke", "ince", "naylon", "sentetik", 
                "özensiz", "ezilmiş", "yırtık", "parçalanmış", "eksik", "fiyasko", 
                "değiştirin", "pişman", "keşke", "eksi", "lanet", "maalesef"
            ]
            
            found_neg = next((k for k in neg_keywords if k in relevant_segment.lower()), None)
            
            if found_neg:
                # "Sorun yok" kontrolü
                is_negated = check_negation(relevant_segment, found_neg)
                if is_negated: 
                    duygu = "Pozitif"
                else: 
                    # --- DÜZELTME: Negatif kelime varsa ve olumsuzlanmıyorsa, sonuç KESİN Negatiftir.
                    # BERT pozitif dese bile (örneğin cümledeki "güzel" kelimesine kanıp) biz Negatif yaparız.
                    duygu = "Negatif"
            
            # --- DÜZELTME: "Pozitif Zorlama" (Positive Override) Kaldırıldı ---
            # Eskiden burada "Eğer harika kelimesi varsa Negatifi Pozitif yap" diyen kod vardı.
            # Onu sildik. Çünkü "Ürün harika ama kargo kırık" cümlesinde kargo negatiftir.
            # "Harika" kelimesi kargoyu kurtarmamalı.

            clean_aspect = aspect.capitalize()
            analysis_results[clean_aspect] = duygu
            
        except Exception:
            continue
            
    return analysis_results

def cek(driver, url, limit):
    return []