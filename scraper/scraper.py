import requests
from bs4 import BeautifulSoup
import csv
# from tqdm import tqdm # เราจะไม่ใช้ tqdm แล้ว

# --- ค่าตั้งต้น (เหมือนเดิม) ---
INPUT_LINKS_FILE = "class_links.txt"
OUTPUT_CSV_FILE = "../data/pariyat_applicants_data.csv"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def find_class_name(soup):
    raw_text = ""
    tag = soup.find('h1', class_='post-title')
    if tag:
        raw_text = tag.text.strip()
    elif (tag := soup.find('h3')) and tag.find('span', class_='alternate'):
        clone = tag
        if clone.span:
            clone.span.decompose()
        raw_text = clone.text.strip()
    elif tag := soup.find('div', class_='content_header'):
        raw_text = tag.text.strip()
    if raw_text:
        return raw_text.replace("รายชื่อผู้", "").replace("ขอเข้าสอบ", "").strip()
    return "ไม่พบชื่อชั้นเรียน"

def scrape_applicant_data_from_url(class_url):
    try:
        response = requests.get(class_url, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        class_name = find_class_name(soup)
        if class_name == "ไม่พบชื่อชั้นเรียน":
            print(f"!!! คำเตือน: ไม่พบแท็กชื่อชั้นเรียนใน URL -> {class_url}")
        applicants = []
        table = soup.find('table', class_='tbl_bordered') or soup.find('table')
        if not table: return []
        for row in table.find('tbody').find_all('tr'):
            cells = [cell.text.strip() for cell in row.find_all('td')]
            if len(cells) >= 6:
                sequence, full_name, age_pansa, id_card_status, cert_id, reg_status = cells[:6]
                applicants.append({'sequence': sequence, 'full_name': full_name, 'age_pansa': age_pansa, 'id_card_status': id_card_status, 'cert_id': cert_id, 'reg_status': reg_status, 'class_name': class_name})
        return applicants
    except requests.exceptions.RequestException:
        # ไม่ต้องแสดง Error ถ้าเข้าลิงก์ไม่ได้ เพื่อให้ Log สะอาด
        return []

# --- จุดแก้ไขสำคัญอยู่ที่ main() ---
def main():
    try:
        with open(INPUT_LINKS_FILE, 'r', encoding='utf-8') as f:
            class_links = [line.strip() for line in f if line.strip()]
        print(f"พบทั้งหมด {len(class_links)} ลิงก์จากไฟล์ {INPUT_LINKS_FILE}")
    except FileNotFoundError:
        print(f"!!! ไม่พบไฟล์ {INPUT_LINKS_FILE} !!!")
        return

    all_applicants_data = []
    total_links = len(class_links)
    
    print("\nกำลังเริ่มดึงข้อมูล...")
    
    # --- เปลี่ยนจากการใช้ tqdm มาเป็น for loop ธรรมดาพร้อม enumerate ---
    for i, link in enumerate(class_links, 1):
        # พิมพ์รายงานความคืบหน้าออกมาเป็นข้อความ
        print(f"[{i}/{total_links}] กำลังประมวลผล: {link}")
        
        applicants_on_page = scrape_applicant_data_from_url(link)
        if applicants_on_page:
            all_applicants_data.extend(applicants_on_page)
            
    if not all_applicants_data:
        print("ไม่พบข้อมูลผู้สมัครเลย")
        return
        
    print(f"\nดึงข้อมูลสำเร็จทั้งหมด {len(all_applicants_data)} รายการ")
    print(f"กำลังบันทึกข้อมูลลงในไฟล์ {OUTPUT_CSV_FILE}...")
    
    fieldnames = ['sequence', 'full_name', 'age_pansa', 'id_card_status', 'cert_id', 'reg_status', 'class_name']
    try:
        with open(OUTPUT_CSV_FILE, 'w', newline='', encoding='utf-8-sig') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_applicants_data)
        print(f"บันทึกข้อมูลเรียบร้อย! เช็คไฟล์ได้ที่โฟลเดอร์ data")
    except IOError as e:
        print(f"เกิดข้อผิดพลาดในการเขียนไฟล์: {e}")

if __name__ == "__main__":
    main()