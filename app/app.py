import os
from flask import Flask, render_template, jsonify, request
import pandas as pd
from datetime import datetime
import pytz
import requests

# --- การตั้งค่า Path (เหมือนเดิม) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'app', 'static')

app = Flask(__name__, 
            template_folder=TEMPLATE_DIR,
            static_folder=STATIC_DIR)

df = None

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
    ดาวน์โหลดข้อมูลทั้งหมดจาก API และเตรียมข้อมูลสำหรับการแสดงผลแบบหลายศูนย์สอบ
    """
    global df
    API_URL = "https://app.pariyat.com/pages/postx/name_json.php"
    PARAMS = {'user': 'dh', 'pass': 'dhahiw8425'}
    
    # --- *** กรุณาแก้ไขชื่อคอลัมน์สำหรับ "ศูนย์สอบ" ตรงนี้ ถ้าจำเป็น *** ---
    CENTER_COLUMN_NAME = 'center_name'  # <--- **สมมติว่าชื่อคอลัมน์คือ 'center_name'**
    
    print("--- [INFO] Attempting to load data from API... ---")
    try:
        response = requests.get(API_URL, params=PARAMS, timeout=60)
        response.raise_for_status()
        json_data = response.json()
        
        if json_data.get('status') == 'success' and 'data' in json_data:
            raw_df = pd.DataFrame(json_data['data'])
            print(f"--- [INFO] Found {len(raw_df)} total records from API.")

            # เราจะไม่กรองข้อมูลทิ้ง แต่จะนำข้อมูลศูนย์สอบมาใช้
            raw_df['class_name'] = raw_df['level_id'].astype(str).map(LEVEL_ID_MAP).fillna('ไม่พบชื่อชั้นเรียน')
            
            raw_df = raw_df.rename(columns={
                'id': 'sequence', 
                'fullname': 'full_name',
                'age': 'age_pansa',
                'status': 'reg_status',
                CENTER_COLUMN_NAME: 'center_name' # นำคอลัมน์ center_name เข้ามาในระบบ
            })
            
            required_columns = ['sequence', 'full_name', 'age_pansa', 'reg_status', 'class_name', 'center_name']
            for col in required_columns:
                if col not in raw_df.columns:
                    raw_df[col] = '' # สร้างคอลัมน์ว่างถ้าไม่มีอยู่
            
            df = raw_df[required_columns].astype(str)
            print(f"--- [SUCCESS] Data processed. Final records: {len(df)}")
        else:
            df = pd.DataFrame()
            print(f"--- [CRITICAL ERROR] API returned status: {json_data.get('status')}")

    except requests.exceptions.RequestException as e:
        df = pd.DataFrame()
        print(f"--- [CRITICAL ERROR] Failed to connect to API: {e}")

def get_data_timestamp():
    # (ฟังก์ชันนี้เหมือนเดิม)
    bangkok_tz = pytz.timezone("Asia/Bangkok")
    return datetime.now(bangkok_tz).strftime('%d/%m/%Y %H:%M:%S')

def get_current_buddhist_year():
    # (ฟังก์ชันนี้เหมือนเดิม)
    today = datetime.now()
    buddhist_year = today.year + 543
    if today < datetime(today.year, 6, 1):
        buddhist_year -= 1
    thai_digits = str.maketrans('0123456789', '๐๑๒๓๔๕๖๗๘๙')
    return str(buddhist_year).translate(thai_digits)

@app.route('/')
def index():
    # (ฟังก์ชันนี้เหมือนเดิม)
    current_year = get_current_buddhist_year()
    return render_template('index.html', current_buddhist_year=current_year)

@app.route('/get_data_info')
def get_data_info():
    # (ฟังก์ชันนี้เหมือนเดิม)
    return jsonify({'timestamp': get_data_timestamp(), 'count': len(df) if df is not None else 0})

@app.route('/search')
def search():
    """
    API สำหรับการค้นหาที่รองรับทั้งชื่อบุคคลและชื่อศูนย์สอบ
    """
    query = request.args.get('q', '')
    if df is None or df.empty or query == '': return jsonify([])
    
    # ทำให้ค้นหาได้ทั้งชื่อคนและชื่อวัด
    results_df = df[
        df['full_name'].str.contains(query, case=False, na=False) | 
        df['center_name'].str.contains(query, case=False, na=False)
    ]

    if results_df.empty: return jsonify([])

    grouped = results_df.groupby('full_name')
    
    final_results = []
    for name, group in grouped:
        person_data = {
            'name': name, 'age_pansa': group['age_pansa'].iloc[0],
            'registrations': [
                {
                    'class_name': row['class_name'], 
                    'reg_status': row['reg_status'], 
                    'sequence': row['sequence'],
                    'center_name': row['center_name'] # ส่งข้อมูล center_name ไปด้วย
                }
                for _, row in group.iterrows()
            ]
        }
        final_results.append(person_data)
        
    return jsonify(final_results)

load_data_from_api()

if __name__ == '__main__':
    app.run(debug=True)