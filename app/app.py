import os
from flask import Flask, render_template, jsonify, request
import pandas as pd
from datetime import datetime
import pytz

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(PROJECT_ROOT, 'data', 'pariyat_applicants_data.csv')
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, 'templates')

app = Flask(__name__, template_folder=TEMPLATE_DIR) 
df = None

def get_current_buddhist_year():
    today = datetime.now()
    buddhist_year = today.year + 543
    if today < datetime(today.year, 6, 1):
        buddhist_year -= 1
    thai_digits = str.maketrans('0123456789', '๐๑๒๓๔๕๖๗๘๙')
    return str(buddhist_year).translate(thai_digits)

def load_data():
    global df
    try:
        df = pd.read_csv(DATA_FILE)
        df = df.astype(str)
    except FileNotFoundError:
        df = pd.DataFrame()

def get_data_timestamp():
    """ดึงเวลาล่าสุดของไฟล์ และแปลงเป็นเวลาไทย (UTC+7)"""
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

@app.route('/get_data_info')
def get_data_info():
    return jsonify({
        'timestamp': get_data_timestamp(),
        'count': len(df) if df is not None else 0
    })

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