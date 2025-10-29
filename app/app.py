import os
from flask import Flask, render_template, jsonify, request
import pandas as pd
from datetime import datetime

# --- การหา Path ที่ถูกต้องสำหรับ Render.com ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(PROJECT_ROOT, 'data', 'pariyat_applicants_data.csv')

app = Flask(__name__)
df = None

def get_current_buddhist_year():
    """
    คำนวณปี พ.ศ. ปัจจุบัน โดยจะเปลี่ยนปีในวันที่ 1 มิถุนายนของทุกปี
    และแปลงเป็นเลขไทย
    """
    today = datetime.now()
    buddhist_year = today.year + 543
    
    # ถ้าปัจจุบันยังไม่ถึงวันที่ 1 มิ.ย. ให้ใช้ปี พ.ศ. ของปีที่แล้ว
    if today < datetime(today.year, 6, 1):
        buddhist_year -= 1
        
    # ฟังก์ชันแปลงเลขเลขอารบิกเป็นเลขไทย
    thai_digits = str.maketrans('0123456789', '๐๑๒๓๔๕๖๗๘๙')
    return str(buddhist_year).translate(thai_digits)

# (ฟังก์ชัน load_data และ get_data_timestamp เหมือนเดิม)
def load_data():
    global df
    try:
        df = pd.read_csv(DATA_FILE)
        df = df.astype(str)
    except FileNotFoundError:
        df = pd.DataFrame()

def get_data_timestamp():
    try:
        timestamp = os.path.getmtime(DATA_FILE)
        return datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y %H:%M:%S')
    except FileNotFoundError:
        return "ยังไม่มีข้อมูล"

# --- จุดแก้ไขสำคัญ: ส่งค่าปี พ.ศ. ไปยังหน้าเว็บ ---
@app.route('/')
def index():
    """หน้าแรกของเว็บ"""
    current_year = get_current_buddhist_year()
    return render_template('index.html', current_buddhist_year=current_year)

@app.route('/get_data_info')
def get_data_info():
    return jsonify({
        'timestamp': get_data_timestamp(),
        'count': len(df) if df is not None else 0
    })

# (ฟังก์ชัน search เหมือนเดิม)
@app.route('/search')
def search():
    query = request.args.get('q', '')
    if df is None or df.empty or query == '':
        return jsonify([])

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

# โหลดข้อมูลครั้งแรกเมื่อเซิร์ฟเวอร์เริ่มทำงาน
load_data()

# ส่วนนี้สำหรับการรันบน PC เท่านั้น
if __name__ == '__main__':
    app.run(debug=True)