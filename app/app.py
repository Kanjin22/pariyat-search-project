import os
import subprocess
import sys
from flask import Flask, render_template, jsonify, request
import pandas as pd
from datetime import datetime

# --- ค่าตั้งต้น ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(PROJECT_ROOT, '..', 'data', 'pariyat_applicants_data.csv')
SCRAPER_SCRIPT = os.path.join(PROJECT_ROOT, '..', 'scraper', 'scraper.py')
SCRAPER_DIR = os.path.join(PROJECT_ROOT, '..', 'scraper')

app = Flask(__name__)
df = None

def load_data():
    global df
    try:
        df = pd.read_csv(DATA_FILE)
        df = df.astype(str)
        print(f"โหลดข้อมูลสำเร็จ {len(df)} รายการ")
    except FileNotFoundError:
        df = pd.DataFrame()
        print("ไม่พบไฟล์ข้อมูล CSV")

def get_data_timestamp():
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
    if df is None or query == '':
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
                'sequence': row['sequence']  # <-- เพิ่มข้อมูล sequence
            })
        final_results.append(person_data)
        
    return jsonify(final_results)


if __name__ == '__main__':
    load_data()
    app.run(debug=True)