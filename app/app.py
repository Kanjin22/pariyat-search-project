import os
from flask import Flask, render_template, jsonify, request
import pandas as pd
from datetime import datetime
import pytz
import requests # เราจะใช้ requests ที่นี่โดยตรง!

# --- ไม่ต้องมี Path ไปหาไฟล์ CSV อีกแล้ว ---

app = Flask(__name__)
df = None # DataFrame ของเราจะถูกสร้างจาก API

# --- จุดสำคัญที่ 1: สร้าง "พจนานุกรม" แปลงรหัสเป็นชื่อชั้นเรียน ---
LEVEL_ID_MAP = {
    '5001': 'น.ธ.ตรี', '5002': 'น.ธ.โท', '5003': 'น.ธ.เอก',
    '5004': 'ธ.ศ.ตรี', '5005': 'ธ.ศ.โท', '5006': 'ธ.ศ.เอก',
    '5007': 'บ.ศ.๑-๒', '5008': 'บ.ศ.๓', '5009': 'บ.ศ.๔', '5010': 'บ.ศ.๕', 
    '5011': 'บ.ศ.๖', '5012': 'บ.ศ.๗', '5013': 'บ.ศ.๘', '5014': 'บ.ศ.๙',
    '5015': 'ป.๑-๒', '5016': 'ป.ธ.๓', '5017': 'ป.ธ.๔', '5018': 'ป.ธ.๕', 
    '5019': 'ป.ธ.๖', '5020': 'ป.ธ.๗', '5021': 'ป.ธ.๘', '5022': 'ป.ธ.๙'
}

def load_data_from_api():
    """
    ฟังก์ชันใหม่! ดาวน์โหลดข้อมูลทั้งหมดจาก API แล้วแปลงเป็น DataFrame
    """
    global df
    API_URL = "https://app.pariyat.com/pages/postx/name_json.php"
    PARAMS = {'user': 'dh', 'pass': 'dhahiw8425'}
    
    print("--- [INFO] Attempting to load data from API... ---")
    try:
        response = requests.get(API_URL, params=PARAMS, timeout=60) # เพิ่ม timeout
        response.raise_for_status() # ตรวจสอบว่า request สำเร็จหรือไม่
        
        json_data = response.json()
        
        if json_data.get('status') == 'success' and 'data' in json_data:
            # สร้าง DataFrame จากข้อมูลที่ได้รับ
            raw_df = pd.DataFrame(json_data['data'])
            
            # --- แปลงข้อมูลและสร้างคอลัมน์ใหม่ ---
            # ใช้พจนานุกรมเพื่อสร้างคอลัมน์ 'class_name'
            raw_df['class_name'] = raw_df['level_id'].astype(str).map(LEVEL_ID_MAP).fillna('ไม่พบชื่อชั้นเรียน')
            
            # เปลี่ยนชื่อคอลัมน์จาก API ให้ตรงกับที่เราใช้ (ถ้าจำเป็น)
            # สมมติว่า API ให้คอลัมน์ชื่อ 'fullname', 'age', 'status'
            raw_df = raw_df.rename(columns={
                'id': 'sequence', # สมมติว่า 'id' คือลำดับ
                'fullname': 'full_name',
                'age': 'age_pansa',
                'status': 'reg_status'
            })
            
            # เลือกเฉพาะคอลัมน์ที่เราต้องการ เพื่อให้โครงสร้างเหมือนเดิม
            # ตรวจสอบก่อนว่ามีคอลัมน์ครบหรือไม่
            required_columns = ['sequence', 'full_name', 'age_pansa', 'reg_status', 'class_name']
            # สร้างคอลัมน์ที่ขาดหายไป (ถ้ามี) แล้วเติมค่าว่าง
            for col in required_columns:
                if col not in raw_df.columns:
                    raw_df[col] = ''
            
            df = raw_df[required_columns].astype(str)
            print(f"--- [SUCCESS] Data loaded from API. Total records: {len(df)}")
        else:
            df = pd.DataFrame()
            print(f"--- [CRITICAL ERROR] API returned status: {json_data.get('status')}")

    except requests.exceptions.RequestException as e:
        df = pd.DataFrame()
        print(f"--- [CRITICAL ERROR] Failed to connect to API: {e}")

# (ฟังก์ชันที่เหลือเหมือนเดิม แต่ get_data_timestamp จะเปลี่ยนเล็กน้อย)

def get_data_timestamp():
    """
    แสดงเวลาปัจจุบันที่เซิร์ฟเวอร์โหลดข้อมูล (เพราะข้อมูลสดใหม่เสมอ)
    """
    bangkok_tz = pytz.timezone("Asia/Bangkok")
    return datetime.now(bangkok_tz).strftime('%d/%m/%Y %H:%M:%S')

# (ฟังก์ชันที่เหลือทำงานได้เหมือนเดิมเป๊ะๆ เพราะเราจัดโครงสร้าง df ให้เหมือนเดิมแล้ว!)

@app.route('/')
def index():
    # (โค้ดนี้ไม่ต้องแก้เลย)
    current_year = "๒๕๖๗" # อาจจะ Hardcode หรือคำนวณเหมือนเดิมก็ได้
    return render_template('index.html', current_buddhist_year=current_year)

@app.route('/get_data_info')
def get_data_info():
    # (โค้ดนี้ไม่ต้องแก้เลย)
    return jsonify({'timestamp': get_data_timestamp(), 'count': len(df) if df is not None else 0})

@app.route('/search')
def search():
    # (โค้ดนี้ไม่ต้องแก้เลย!)
    query = request.args.get('q', '')
    if df is None or df.empty or query == '': return jsonify([])
    results_df = df[df['full_name'].str.contains(query, case=False, na=False)]
    if results_df.empty: return jsonify([])
    grouped = results_df.groupby('full_name')
    final_results = []
    for name, group in grouped:
        person_data = {
            'name': name, 'age_pansa': group['age_pansa'].iloc[0],
            'registrations': [
                {'class_name': row['class_name'], 'reg_status': row['reg_status'], 'sequence': row['sequence']}
                for _, row in group.iterrows()
            ]
        }
        final_results.append(person_data)
    return jsonify(final_results)

# --- จุดสำคัญสุดท้าย: เรียกใช้ฟังก์ชันใหม่เมื่อเซิร์ฟเวอร์เริ่มทำงาน ---
load_data_from_api()

if __name__ == '__main__':
    app.run(debug=True)