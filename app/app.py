import os
from flask import Flask, render_template, jsonify, request
import pandas as pd
from datetime import datetime
import pytz
import requests

# --- การตั้งค่า Path, Flask App, LEVEL_ID_MAP ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'app', 'static')
app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
df = None
LEVEL_ID_MAP = {
    '5001': 'น.ธ.ตรี', '5002': 'น.ธ.โท', '5003': 'น.ธ.เอก', '5004': 'ธ.ศ.ตรี',
    '5005': 'ธ.ศ.โท', '5006': 'ธ.ศ.เอก', '5007': 'บ.ศ.๑-๒', '5008': 'บ.ศ.๓',
    '5009': 'บ.ศ.๔', '5010': 'บ.ศ.๕', '5011': 'บ.ศ.๖', '5012': 'บ.ศ.๗',
    '5013': 'บ.ศ.๘', '5014': 'บ.ศ.๙', '5015': 'ป.๑-๒', '5016': 'ป.ธ.๓',
    '5017': 'ป.ธ.๔', '5018': 'ป.ธ.๕', '5019': 'ป.ธ.๖', '5020': 'ป.ธ.๗',
    '5021': 'ป.ธ.๘', '5022': 'ป.ธ.๙'
}


# --- ฟังก์ชันผู้ช่วย ---
def to_thai_digits(text):
    if text is None or pd.isna(text): return ''
    text = str(text)
    thai_digits = str.maketrans('0123456789', '๐๑๒๓๔๕๖๗๘๙')
    return text.translate(thai_digits)


def extract_latest_cert(id_list_string, latest_id):
    """ฟังก์ชันนักสืบ: ค้นหาข้อความเต็มของประกาศนียบัตรล่าสุดจาก ID ที่กำหนด"""
    if not id_list_string or not latest_id or not isinstance(id_list_string, str):
        return ''
    history_list = id_list_string.split(',')
    search_key = f"{latest_id}:"
    for entry in history_list:
        clean_entry = entry.strip()
        if clean_entry.startswith(search_key):
            return clean_entry.split(':', 1)[1].strip()
    return ''


def get_current_buddhist_year(numeric=False):
    today = datetime.now()
    buddhist_year = today.year + 543
    if today >= datetime(today.year, 6, 1):
        buddhist_year += 1
    if numeric:
        return buddhist_year
    return to_thai_digits(str(buddhist_year))


def format_display_name(row):
    prefix = row.get('prefix_title', '') or ''
    fname = row.get('firstname', '') or ''
    lname = row.get('lastname', '') or ''
    pname = row.get('paliname', '') or ''
    full_first_name = f"{prefix}{fname}"
    if pname:
        display_name = " ".join(part for part in [full_first_name, pname] if part)
        if lname: display_name += f" ({lname})"
        return display_name
    else:
        return " ".join(part for part in [full_first_name, lname] if part)


def load_data_from_api():
    """Final Version: โหลดข้อมูล, กรองปี, คำนวณพรรษา, ประกอบชื่อ, และแกะข้อมูลประกาศนียบัตร"""
    global df
    API_URL = "https://app.pariyat.com/pages/postx/name_json.php"
    current_year_numeric = get_current_buddhist_year(numeric=True)
    PARAMS = {'user': 'dh', 'pass': 'dhahiw8425', 'filter_year': current_year_numeric}
    
    print(f"--- [INFO] Loading data for year {current_year_numeric}... ---")
    try:
        response = requests.get(API_URL, params=PARAMS, timeout=60)
        response.raise_for_status()
        json_data = response.json()
        
        if json_data.get('status') == 'success' and 'data' in json_data:
            raw_df = pd.DataFrame(json_data['data'])
            
            raw_df['display_name'] = raw_df.apply(format_display_name, axis=1)

            raw_df['monk_year_num'] = pd.to_numeric(raw_df['monk_year'], errors='coerce').fillna(0).astype(int)
            raw_df['ordain_after_num'] = pd.to_numeric(raw_df['ordain_after'], errors='coerce').fillna(0).astype(int)

            def calculate_pansa(row):
                if row['monk_year_num'] > 0:
                    pansa = current_year_numeric - row['monk_year_num']
                    if row['ordain_after_num'] == 1: pansa -= 1
                    if pansa < 0: pansa = 0
                    return f"{to_thai_digits(row['age'])}/{to_thai_digits(pansa)}"
                else: return to_thai_digits(row['age'])

            raw_df['age_pansa'] = raw_df.apply(calculate_pansa, axis=1)

            raw_df['cert_nugdham_text'] = raw_df.apply(lambda row: extract_latest_cert(row.get('last_nugdham_id_list'), row.get('last_nugdham_id')), axis=1)
            raw_df['cert_pali_text'] = raw_df.apply(lambda row: extract_latest_cert(row.get('last_pali_id_list'), row.get('last_pali_id')), axis=1)
            
            raw_df['class_name'] = raw_df['level_id'].astype(str).map(LEVEL_ID_MAP).fillna('ไม่พบชื่อชั้นเรียน')
            raw_df['sequence'] = raw_df.groupby('class_name').cumcount() + 1
            raw_df['sequence_thai'] = raw_df['sequence'].apply(to_thai_digits)
            
            raw_df = raw_df.rename(columns={'status': 'reg_status', 'bureau': 'school_name', 'postx_type': 'group_name'})
            
            required_columns = ['sequence_thai', 'display_name', 'age_pansa', 'reg_status', 'class_name', 'school_name', 'group_name', 'cert_nugdham_text', 'cert_pali_text']
            
            for col in required_columns:
                if col not in raw_df.columns: raw_df[col] = ''
            
            df = raw_df[required_columns].astype(str)
            print(f"--- [SUCCESS] Data processed. Final records: {len(df)}")
        else:
            df = pd.DataFrame()
            print(f"--- [CRITICAL ERROR] API Status: {json_data.get('status')}")
    except Exception as e:
        df = pd.DataFrame()
        print(f"--- [CRITICAL ERROR] API Exception: {e}")


@app.route('/search')
def search():
    query = request.args.get('q', '')
    if df is None or df.empty or query == '': return jsonify([])
    results_df = df[df['display_name'].str.contains(query, case=False, na=False)]
    if results_df.empty: return jsonify([])
    grouped = results_df.groupby('display_name')
    
    final_results = []
    for name, group in grouped:
        first_row = group.iloc[0]
        person_data = {
            'name': name,
            'age_pansa': first_row['age_pansa'],
            'school_name': to_thai_digits(first_row['school_name']),
            'group_name': to_thai_digits(first_row['group_name']),
            'registrations': [
                {
                    'class_name': row['class_name'], 'reg_status': row['reg_status'],
                    'sequence': row['sequence_thai'],
                    'cert_nugdham': to_thai_digits(row['cert_nugdham_text']),
                    'cert_pali': to_thai_digits(row['cert_pali_text'])
                }
                for _, row in group.iterrows()
            ]
        }
        final_results.append(person_data)
        
    return jsonify(final_results)


@app.route('/')
def index():
    current_year_thai = get_current_buddhist_year(numeric=False)
    return render_template('index.html', current_buddhist_year=current_year_thai)


@app.route('/get_data_info')
def get_data_info():
    return jsonify({'timestamp': get_data_timestamp(), 'count': len(df) if df is not None else 0})


def get_data_timestamp():
    bangkok_tz = pytz.timezone("Asia/Bangkok")
    return datetime.now(bangkok_tz).strftime('%d/%m/%Y %H:%M:%S')


load_data_from_api()

if __name__ == '__main__':
    app.run(debug=True)
