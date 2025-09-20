import requests

# --- ใส่ URL ที่มีปัญหา 1 URL ลงไปที่นี่ ---
URL_TO_DEBUG = "https://app.pariyat.com/pages/postx/namelist.php?lid=5015"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

print(f"กำลังเริ่มชันสูตร URL: {URL_TO_DEBUG}")

try:
    response = requests.get(URL_TO_DEBUG, headers=HEADERS)
    response.raise_for_status()
    
    # --- หัวใจสำคัญ: บันทึกทุกสิ่งที่เห็นลงในไฟล์ ---
    with open("debug_page.html", "wb") as f: # ใช้ "wb" เพื่อป้องกันปัญหาเรื่องการเข้ารหัสตัวอักษร
        f.write(response.content)
        
    print("\n✅ ชันสูตรสำเร็จ!")
    print("ได้สร้างไฟล์ชื่อ 'debug_page.html' ไว้ในโฟลเดอร์ scraper แล้ว")
    print("\n--- สิ่งที่ต้องทำต่อไป ---")
    print("1. เปิดไฟล์ 'debug_page.html' ด้วยเบราว์เซอร์ Chrome")
    print("2. มองหา 'ชื่อชั้นเรียน' บนหน้าที่เปิดขึ้นมา")
    print("3. คลิกขวาที่ชื่อชั้นเรียนนั้น แล้วเลือก 'Inspect'")
    print("4. ช่วยคัดลอกบรรทัดโค้ด HTML ที่ถูกไฮไลท์สีฟ้าส่งมาให้ผมดูด้วยครับ")

except requests.exceptions.RequestException as e:
    print(f"เกิดข้อผิดพลาดในการเชื่อมต่อ: {e}")