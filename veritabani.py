import sqlite3
import json
from datetime import datetime

DB_ADI = "analizler.db"

def veritabani_baslat():
    """Veritabanı tablosunu oluşturur (Eğer yoksa)"""
    conn = sqlite3.connect(DB_ADI)
    cursor = conn.cursor()
    # DİKKAT: url sütunundan UNIQUE ifadesini kaldırdık.
    # Artık aynı url'den birden fazla kayıt olabilir (farklı motorlar için)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analiz_gecmisi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT, 
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
        
        sonuc_str = json.dumps(sonuc_json, ensure_ascii=False)
        tarih = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Sadece o URL ve o MOTOR tipindeki eski kaydı sil (Update mantığı)
        cursor.execute("DELETE FROM analiz_gecmisi WHERE url = ? AND motor = ?", (url, motor))
        
        cursor.execute('''
            INSERT INTO analiz_gecmisi (url, baslik, motor, analiz_sonucu, tarih)
            VALUES (?, ?, ?, ?, ?)
        ''', (url, baslik, motor, sonuc_str, tarih))
        
        conn.commit()
        conn.close()
        print(f"✅ Veritabanına kaydedildi ({motor}): {baslik}")
    except Exception as e:
        print(f"❌ Veritabanı kayıt hatası: {e}")

def analiz_getir(url, motor):
    """Verilen URL ve MOTOR tipi için kayıt varsa getirir"""
    conn = sqlite3.connect(DB_ADI)
    cursor = conn.cursor()
    # Sorguya motor şartını da ekledik
    cursor.execute("SELECT baslik, analiz_sonucu, motor, tarih FROM analiz_gecmisi WHERE url = ? AND motor = ?", (url, motor))
    veri = cursor.fetchone()
    conn.close()
    
    if veri:
        baslik, sonuc_str, motor_db, tarih = veri
        sonuc_json = json.loads(sonuc_str)
        return {
            "baslik": baslik,
            "analiz_sonucu": sonuc_json,
            "motor": motor_db,
            "tarih": tarih,
            "kaynaktan_geldi": True
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
def analiz_getir_id_ile(id):
    """ID'si verilen analizi getirir (Karşılaştırma için)"""
    conn = sqlite3.connect(DB_ADI)
    cursor = conn.cursor()
    cursor.execute("SELECT baslik, analiz_sonucu, motor, tarih, url FROM analiz_gecmisi WHERE id = ?", (id,))
    veri = cursor.fetchone()
    conn.close()
    
    if veri:
        baslik, sonuc_str, motor, tarih, url = veri
        sonuc_json = json.loads(sonuc_str)
        return {
            "id": id,
            "baslik": baslik,
            "analiz_sonucu": sonuc_json,
            "motor": motor,
            "tarih": tarih,
            "url": url
        }
    return None