import os
import requests
from dotenv import load_dotenv

# .env dosyasındaki şifreyi yükle
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")
MODEL = "gemini-flash-latest"

def test_et():
    print(f"📡 API Bağlantısı Test Ediliyor...")
    print(f"🔑 Kullanılan Key: {API_KEY[:5]}...{API_KEY[-5:] if API_KEY else 'YOK'}")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"
    
    # Çok basit, tek cümlelik bir test isteği
    payload = {
        "contents": [{
            "parts": [{"text": "Merhaba, sadece bağlantıyı test ediyorum. Cevap verme."}]
        }]
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        
        print(f"\n📊 Durum Kodu: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ BAŞARILI! Engel kalkmış, projeyi çalıştırabilirsin.")
            print("Cevap:", response.json()['candidates'][0]['content']['parts'][0]['text'])
        elif response.status_code == 429:
            print("⏳ BAŞARISIZ. Engel hala devam ediyor (429 Too Many Requests).")
            print("Biraz daha beklemelisin.")
        else:
            print(f"❌ BAŞKA BİR HATA: {response.text}")
            
    except Exception as e:
        print(f"Bağlantı Hatası: {e}")

if __name__ == "__main__":
    test_et()