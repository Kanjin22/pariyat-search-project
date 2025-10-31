import os
from flask import Flask, render_template, jsonify, request
import pandas as pd
from datetime import datetime
import pytz

# --- จุดแก้ไขที่ 1: กำหนด Path แบบสัมบูรณ์ที่ทนทานที่สุด ---
# สร้าง Path ไปยังโฟลเดอร์โปรเจกต์หลัก (อยู่เหนือโฟลเดอร์ 'app' ไป 1 ระดับ)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# สร้าง Path ไปยังโฟลเดอร์ย่อยต่างๆ โดยอิงจาก BASE_DIR
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'app', 'static') # Static ยังคงอยู่ที่เดิม
DATA_FILE = os.path.join(BASE_DIR, 'data', 'pariyat_applicants_data.csv')

# --- จุดแก้ไขที่ 2: ตั้งค่า Flask ให้รู้จัก Path ใหม่ทั้งหมด ---
app = Flask(__name__, 
            template_folder=TEMPLATE_DIR,
            static_folder=STATIC_DIR)

df = None

def get_current_buddhist_year():
    # (ฟังก์ชันนี้สมบูรณ์แบบอยู่แล้ว ไม่ต้องแก้ไข)
    today = datetime.now()
    buddhist_year = today.year + 543
    if today < datetime(today.year, 6, 1):
        buddhist_year -= 1
    thai_digits = str.maketrans('0123456789', '๐๑๒๓๔๕๖๗๘๙')
    return str(buddhist_year).translate(thai_digits)

def load_data():
    global df
    print(f"--- [INFO] Attempting to load data from: {DATA_FILE}")
    try:
        df = pd.read_csv(DATA_FILE)
        df = df.astype(str)
        print(f"--- [SUCCESS] Data loaded successfully. Records: {len(df)}")
    except FileNotFoundError:
        df = pd.DataFrame()
        print(f"--- [CRITICAL ERROR] FileNotFoundError! Could not find: {DATA_FILE}")
    except Exception as e:
        df = pd.DataFrame()
        print(f"--- [CRITICAL ERROR] An unexpected error occurred: {e}")

def get_data_timestamp():
    try:
        utc_timestamp = os.path.getmtime(DATA_FILE)
        utc_datetime = datetime.fromtimestamp(utc_timestamp, tz=pytz.utc)
        bangkok_tz = pytz.timezone("Asia/Bangkok")
        bangkok_datetime = utc_datetime.astimezone(bangkok_tz)
        return bangkok_datetime.strftime('%d/%m/%Y %H:%M:%S')
    except FileNotFoundError:
        return "ยังไม่มีข้อมูล"

@app.route('/')
def index():
    current_year = get_current_buddhist_year()
    return render_template('index.html', current_buddhist_year=current_year)

# (ฟังก์ชัน /get_data_info และ /search เหมือนเดิม ไม่ต้องแก้ไข)
@app.route('/get_data_info')
def get_data_info():
    return jsonify({'timestamp': get_data_timestamp(), 'count': len(df) if df is not None else 0})

@app.route('/search')
def search():
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

load_data()

if __name__ == '__main__':
    app.run(debug=True)