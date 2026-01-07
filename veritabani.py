import sqlite3
import json
from datetime import datetime

DB_ADI = "analizler.db"

def veritabani_baslat():
    """Veritabanı tablosunu oluşturur (Eğer yoksa)"""
    conn = sqlite3.connect(DB_ADI)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analiz_gecmisi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            baslik TEXT,
            motor TEXT,
            analiz_sonucu TEXT,
            tarih DATETIME
        )
    ''')
    conn.commit()
    conn.close()

def analiz_kaydet(url, baslik, motor, sonuc_json):
    """Yeni bir analizi veritabanına kaydeder"""
    try:
        conn = sqlite3.connect(DB_ADI)
        cursor = conn.cursor()
        
        # JSON verisini string'e çeviriyoruz ki veritabanına metin olarak sığsın
        sonuc_str = json.dumps(sonuc_json, ensure_ascii=False)
        tarih = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Eğer bu URL daha önce varsa, eskisini silip yenisini yazalım (Update mantığı)
        cursor.execute("DELETE FROM analiz_gecmisi WHERE url = ?", (url,))
        
        cursor.execute('''
            INSERT INTO analiz_gecmisi (url, baslik, motor, analiz_sonucu, tarih)
            VALUES (?, ?, ?, ?, ?)
        ''', (url, baslik, motor, sonuc_str, tarih))
        
        conn.commit()
        conn.close()
        print(f"✅ Veritabanına kaydedildi: {baslik}")
    except Exception as e:
        print(f"❌ Veritabanı kayıt hatası: {e}")

def analiz_getir(url):
    """Verilen URL veritabanında varsa sonucunu döndürür"""
    conn = sqlite3.connect(DB_ADI)
    cursor = conn.cursor()
    cursor.execute("SELECT baslik, analiz_sonucu, motor, tarih FROM analiz_gecmisi WHERE url = ?", (url,))
    veri = cursor.fetchone()
    conn.close()
    
    if veri:
        # Veritabanından gelen string'i tekrar JSON (sözlük) formatına çevir
        baslik, sonuc_str, motor, tarih = veri
        sonuc_json = json.loads(sonuc_str)
        return {
            "baslik": baslik,
            "analiz_sonucu": sonuc_json,
            "motor": motor,
            "tarih": tarih,
            "kaynaktan_geldi": True # Bu bayrak sayesinde front-end'de "Veritabanından Yüklendi" diyebiliriz
        }
    return None

def gecmisi_listele():
    """Tüm analiz geçmişini listeler (Tarihe göre yeniden eskiye)"""
    conn = sqlite3.connect(DB_ADI)
    cursor = conn.cursor()
    cursor.execute("SELECT id, baslik, url, motor, tarih FROM analiz_gecmisi ORDER BY tarih DESC")
    veriler = cursor.fetchall()
    conn.close()
    
    liste = []
    for v in veriler:
        liste.append({
            "id": v[0],
            "baslik": v[1],
            "url": v[2],
            "motor": v[3],
            "tarih": v[4]
        })
    return liste