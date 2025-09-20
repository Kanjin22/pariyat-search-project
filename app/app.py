import os
import subprocess
import sys
from flask import Flask, render_template, jsonify, request
import pandas as pd
from datetime import datetime

# --- จุดแก้ไขสำคัญ: ปรับปรุงการหา Path ---
# เราจะหา Path ของโฟลเดอร์โปรเจกต์หลัก ไม่ใช่แค่โฟลเดอร์ app
# __file__ คือ path ของไฟล์ app.py นี้
# os.path.dirname(__file__) คือ path ของโฟลเดอร์ 'app'
# os.path.dirname(os.path.dirname(__file__)) คือ path ของโฟลเดอร์โปรเจกต์หลัก
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(PROJECT_ROOT, 'data', 'pariyat_applicants_data.csv')

app = Flask(__name__)
df = None

def load_data():
    """อ่านข้อมูลจาก CSV มาเก็บใน DataFrame ของ Pandas พร้อม Debug Log"""
    global df
    print("--- [DEBUG] Attempting to load data ---")
    print(f"--- [DEBUG] Project Root Path: {PROJECT_ROOT}")
    print(f"--- [DEBUG] Attempting to read CSV from: {DATA_FILE}")
    
    try:
        df = pd.read_csv(DATA_FILE)
        df = df.astype(str)
        print(f"--- [SUCCESS] Data loaded successfully. Total records: {len(df)}")
    except FileNotFoundError:
        df = pd.DataFrame()
        print(f"--- [CRITICAL ERROR] FileNotFoundError! Could not find CSV at path: {DATA_FILE}")
    except Exception as e:
        df = pd.DataFrame()
        print(f"--- [CRITICAL ERROR] An unexpected error occurred while loading data: {e}")


def get_data_timestamp():
    """ดึงเวลาล่าสุดที่มีการแก้ไขไฟล์ CSV"""
    try:
        timestamp = os.path.getmtime(DATA_FILE)
        return datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y %H:%M:%S')
    except FileNotFoundError:
        return "ยังไม่มีข้อมูล"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_data_info')
def get_data_info():
    return jsonify({
        'timestamp': get_data_timestamp(),
        'count': len(df) if df is not None else 0
    })

@app.route('/search')
def search():
    query = request.args.get('q', '')
    if df is None or df.empty or query == '':
        return jsonify([])

    results_df = df[df['full_name'].str.contains(query, case=False, na=False)]
    
    if results_df.empty:
        return jsonify([])

    grouped = results_df.groupby('full_name')
    
    final_results = []
    for name, group in grouped:
        person_data = {
            'name': name,
            'age_pansa': group['age_pansa'].iloc[0],
            'registrations': []
        }
        for index, row in group.iterrows():
            person_data['registrations'].append({
                'class_name': row['class_name'],
                'reg_status': row['reg_status'],
                'sequence': row['sequence']
            })
        final_results.append(person_data)
        
    return jsonify(final_results)

# --- โค้ดส่วนปุ่มอัปเดตจะไม่มีในเวอร์ชันออนไลน์ ---

# --- เริ่มการทำงานของเว็บ ---
# โค้ดส่วนนี้จะถูกเรียกใช้โดย Gunicorn บนเซิร์ฟเวอร์
load_data()

# ส่วน if __name__ == '__main__': จะใช้สำหรับการรันบนเครื่อง PC ของเราเท่านั้น
if __name__ == '__main__':
    app.run(debug=True)