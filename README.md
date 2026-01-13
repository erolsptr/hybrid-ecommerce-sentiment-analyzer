# 🧠 ReviewSense AI - Hibrit Yorum Analiz Asistanı

ReviewSense AI, e-ticaret (Trendyol, N11, Hepsiburada) ürün yorumlarını yapay zeka ile analiz eden, görselleştiren ve kullanıcı sorularını yanıtlayan gelişmiş bir karar destek sistemidir.

![ReviewSense Logo](static/images/logo.png)

## 🚀 Öne Çıkan Özellikler

*   **Çoklu Platform Desteği:** Trendyol, N11 ve Hepsiburada uyumlu.
*   **Hibrit Zeka Motoru:** 
    *   **Yerel BERT Modeli:** Yorumlardaki özellik ve duyguları anında tespit eder (Hız & Maliyet optimizasyonu).
    *   **Llama 3.3 (Groq):** Derinlemesine anlamlandırma ve özetleme yapar.
*   **Canlı Ürün Asistanı (Chat):** Rapor sonucunda yapay zekaya "Şarjı ne kadar gidiyor?" gibi sorular sorabilirsiniz.
*   **Akıllı Hafıza (Cache):** Analiz edilen ürünler SQLite veritabanında saklanır, tekrar sorgulandığında saniyesinde açılır.
*   **Ürün Karşılaştırma (Versus):** İki farklı ürünü yan yana koyup, yapay zeka destekli kıyaslama raporu sunar.
*   **Görselleştirme:** Detaylı duygu grafikleri, radar (performans) grafiği ve kelime bulutu.
*   **Modern Arayüz:** Responsive, kullanıcı dostu ve şık tasarım.

## 🛠️ Kurulum

1.  **Gerekli Kütüphaneleri Yükleyin:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Ortam Değişkenlerini Ayarlayın:**
    Ana dizinde `.env` dosyası oluşturun ve Groq API anahtarınızı ekleyin:
    ```
    GROQ_API_KEY=gsk_...
    ```

3.  **Uygulamayı Başlatın:**
    ```bash
    python app.py
    ```
    Tarayıcıda `http://127.0.0.1:5001` adresine gidin.

---
*Bu proje, Yapay Zeka ve Veri Madenciliği alanında bir Bitirme Projesi olarak geliştirilmiştir.*