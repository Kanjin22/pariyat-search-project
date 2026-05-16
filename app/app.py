import json
import logging
import os
from functools import wraps
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
import pandas as pd
from datetime import datetime, timedelta
import pytz
import requests
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'app', 'static')
ENV_FILE = os.path.join(BASE_DIR, '.env')
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
STAFF_ACTIVITY_LOG_FILE = os.path.join(LOGS_DIR, 'staff_activity.log')
DEFAULT_SECRET_KEY = 'change-this-secret-in-production'

load_dotenv(ENV_FILE)

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.secret_key = os.getenv('FLASK_SECRET_KEY', DEFAULT_SECRET_KEY)
df = None
RESULT_STATUS_OPTIONS = ['', 'ขาดสอบ', 'ขาดสิทธิ์', 'สอบได้', 'สอบซ่อม', 'สอบซ่อมได้']
RESULT_STATUS_SET = set(RESULT_STATUS_OPTIONS)
RESULTS_DATA_DIR = os.path.join(BASE_DIR, 'data')
RESULTS_FILE = os.path.join(RESULTS_DATA_DIR, 'exam_results.json')
STAFF_ACCOUNTS_FILE = os.path.join(RESULTS_DATA_DIR, 'staff_accounts.json')
LOGIN_ATTEMPTS_FILE = os.path.join(RESULTS_DATA_DIR, 'login_attempts.json')
BACKUPS_DIR = os.path.join(BASE_DIR, 'backups')
STAFF_USERNAME = os.getenv('STAFF_USERNAME', '').strip()
STAFF_PASSWORD = os.getenv('STAFF_PASSWORD', '')
STAFF_PASSWORD_HASH = os.getenv('STAFF_PASSWORD_HASH', '').strip()
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
LEVEL_ID_MAP = {
    '5001': 'น.ธ.ตรี', '5002': 'น.ธ.โท', '5003': 'น.ธ.เอก', '5004': 'ธ.ศ.ตรี',
    '5005': 'ธ.ศ.โท', '5006': 'ธ.ศ.เอก', '5007': 'บ.ศ.๑-๒', '5008': 'บ.ศ.๓',
    '5009': 'บ.ศ.๔', '5010': 'บ.ศ.๕', '5011': 'บ.ศ.๖', '5012': 'บ.ศ.๗',
    '5013': 'บ.ศ.๘', '5014': 'บ.ศ.๙', '5015': 'ป.๑-๒', '5016': 'ป.ธ.๓',
    '5017': 'ป.ธ.๔', '5018': 'ป.ธ.๕', '5019': 'ป.ธ.๖', '5020': 'ป.ธ.๗',
    '5021': 'ป.ธ.๘', '5022': 'ป.ธ.๙'
}


def to_thai_digits(text):
    if text is None or pd.isna(text): return ''
    text = str(text)
    thai_digits = str.maketrans('0123456789', '๐๑๒๓๔๕๖๗๘๙')
    return text.translate(thai_digits)


def validate_thai_id(pid):
    if not isinstance(pid, str) or not pid.isdigit() or len(pid) != 13:
        return False
    total = sum(int(digit) * (13 - i) for i, digit in enumerate(pid[:12]))
    check_digit = (11 - (total % 11)) % 10
    return int(pid[12]) == check_digit


def extract_latest_cert(id_list_string, latest_id):
    if not id_list_string or not latest_id or not isinstance(id_list_string, str): return ''
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


def get_staff_logger():
    os.makedirs(LOGS_DIR, exist_ok=True)
    logger = logging.getLogger('staff_activity')
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(STAFF_ACTIVITY_LOG_FILE, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger


def get_client_ip():
    forwarded_for = request.headers.get('X-Forwarded-For', '')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.remote_addr or '-'


def write_staff_log(action, outcome, username='', detail=''):
    safe_detail = str(detail or '').replace('\n', ' ').strip()
    log_message = (
        f"action={action} | outcome={outcome} | username={username or '-'} "
        f"| ip={get_client_ip()} | detail={safe_detail or '-'}"
    )
    get_staff_logger().info(log_message)


def load_staff_accounts():
    if not os.path.exists(STAFF_ACCOUNTS_FILE):
        return []
    try:
        with open(STAFF_ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
            accounts = json.load(f)
            if isinstance(accounts, list):
                return accounts
    except (OSError, json.JSONDecodeError):
        pass
    return []


def save_staff_accounts(accounts):
    os.makedirs(RESULTS_DATA_DIR, exist_ok=True)
    with open(STAFF_ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)


def find_staff_account(username):
    accounts = load_staff_accounts()
    for account in accounts:
        if account.get('username') == username:
            return account
    return None


def add_staff_account(username, password, full_name='', role='staff'):
    accounts = load_staff_accounts()
    if find_staff_account(username):
        return False, 'Username already exists'
    new_account = {
        'username': username,
        'password_hash': generate_password_hash(password),
        'full_name': full_name or username,
        'role': role,
        'created_at': datetime.now().isoformat(),
        'active': True
    }
    accounts.append(new_account)
    save_staff_accounts(accounts)
    return True, 'Account created successfully'


def update_staff_account(username, password=None, full_name=None, active=None, role=None):
    accounts = load_staff_accounts()
    for i, account in enumerate(accounts):
        if account['username'] == username:
            if password is not None:
                accounts[i]['password_hash'] = generate_password_hash(password)
            if full_name is not None:
                accounts[i]['full_name'] = full_name
            if active is not None:
                accounts[i]['active'] = active
            if role is not None:
                accounts[i]['role'] = role
            accounts[i]['updated_at'] = datetime.now().isoformat()
            save_staff_accounts(accounts)
            return True, 'Account updated successfully'
    return False, 'Account not found'


def load_login_attempts():
    if not os.path.exists(LOGIN_ATTEMPTS_FILE):
        return {}
    try:
        with open(LOGIN_ATTEMPTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_login_attempts(attempts):
    os.makedirs(RESULTS_DATA_DIR, exist_ok=True)
    with open(LOGIN_ATTEMPTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(attempts, f, ensure_ascii=False, indent=2)


def is_account_locked(username):
    attempts = load_login_attempts()
    user_attempts = attempts.get(username, {})
    if not user_attempts:
        return False
    if user_attempts.get('locked_until'):
        try:
            locked_until = datetime.fromisoformat(user_attempts['locked_until'])
            if datetime.now() < locked_until:
                return True
            else:
                del attempts[username]
                save_login_attempts(attempts)
        except:
            pass
    return False


def record_login_attempt(username, success):
    attempts = load_login_attempts()
    user_attempts = attempts.get(username, {'count': 0, 'locked_until': None})
    
    if success:
        if username in attempts:
            del attempts[username]
            save_login_attempts(attempts)
    else:
        user_attempts['count'] = user_attempts.get('count', 0) + 1
        if user_attempts['count'] >= MAX_LOGIN_ATTEMPTS:
            locked_until = datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)
            user_attempts['locked_until'] = locked_until.isoformat()
        attempts[username] = user_attempts
        save_login_attempts(attempts)


def is_admin(username):
    account = find_staff_account(username)
    if account:
        return account.get('role') == 'admin'
    if username == STAFF_USERNAME:
        return True
    return False


def admin_required(api=False):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(*args, **kwargs):
            if not is_staff_logged_in():
                write_staff_log(action='access_denied', outcome='blocked', username=session.get('staff_username', ''), detail=request.path)
                if api:
                    return jsonify({'success': False, 'message': 'กรุณาเข้าสู่ระบบเจ้าหน้าที่'}), 401
                return redirect(url_for('staff_login', next=request.path))
            if not is_admin(session.get('staff_username')):
                write_staff_log(action='access_denied', outcome='blocked', username=session.get('staff_username', ''), detail=request.path)
                if api:
                    return jsonify({'success': False, 'message': 'คุณไม่มีสิทธิ์เข้าถึงส่วนนี้'}), 403
                return redirect(url_for('manage_results'))
            return view_func(*args, **kwargs)
        return wrapped_view
    return decorator


def create_backup():
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    files_to_backup = [
        (RESULTS_FILE, f'exam_results_{timestamp}.json'),
        (STAFF_ACCOUNTS_FILE, f'staff_accounts_{timestamp}.json')
    ]
    
    for source, dest_name in files_to_backup:
        if os.path.exists(source):
            dest_path = os.path.join(BACKUPS_DIR, dest_name)
            import shutil
            shutil.copy2(source, dest_path)
    
    return True


def get_statistics():
    stats = {}
    if df is not None and not df.empty:
        stats['total_registrations'] = len(df)
        stats['unique_people'] = df['display_name'].nunique()
        
        if 'exam_result_status' in df.columns:
            status_counts = df['exam_result_status'].value_counts().to_dict()
            stats['by_status'] = {k: v for k, v in status_counts.items() if k}
        
        stats['by_class'] = df['class_name'].value_counts().to_dict()
    
    return stats


def delete_staff_account(username):
    if username == session.get('staff_username'):
        return False, 'Cannot delete your own account'
    accounts = load_staff_accounts()
    new_accounts = [acc for acc in accounts if acc['username'] != username]
    if len(new_accounts) == len(accounts):
        return False, 'Account not found'
    save_staff_accounts(new_accounts)
    return True, 'Account deleted successfully'


def migrate_env_staff_to_json():
    if STAFF_USERNAME and (STAFF_PASSWORD_HASH or STAFF_PASSWORD):
        if not find_staff_account(STAFF_USERNAME):
            password_hash = STAFF_PASSWORD_HASH
            if not password_hash and STAFF_PASSWORD:
                password_hash = generate_password_hash(STAFF_PASSWORD)
            if password_hash:
                accounts = load_staff_accounts()
                accounts.append({
                    'username': STAFF_USERNAME,
                    'password_hash': password_hash,
                    'full_name': STAFF_USERNAME,
                    'role': 'admin',
                    'created_at': datetime.now().isoformat(),
                    'active': True
                })
                save_staff_accounts(accounts)
                return True
    return False


def is_staff_auth_configured():
    accounts = load_staff_accounts()
    if accounts:
        return True
    return bool(STAFF_USERNAME and (STAFF_PASSWORD_HASH or STAFF_PASSWORD))


def is_security_hardened():
    accounts = load_staff_accounts()
    return bool(app.secret_key and app.secret_key != DEFAULT_SECRET_KEY and (len(accounts) > 0 or STAFF_PASSWORD_HASH))


def get_login_notice():
    accounts = load_staff_accounts()
    if not accounts and not is_staff_auth_configured():
        return 'ยังไม่ได้ตั้งค่าเจ้าหน้าที่'
    if not accounts and STAFF_PASSWORD:
        return 'กำลังใช้ STAFF_PASSWORD แบบข้อความตรง แนะนำให้เพิ่มเจ้าหน้าที่ในระบบแทน'
    if app.secret_key == DEFAULT_SECRET_KEY:
        return 'กำลังใช้ secret key ค่าเริ่มต้น ควรเปลี่ยน FLASK_SECRET_KEY ในไฟล์ .env'
    return ''


def is_safe_redirect_url(target):
    return isinstance(target, str) and target.startswith('/') and not target.startswith('//')


def is_staff_logged_in():
    return session.get('staff_logged_in') is True


def verify_staff_password(username, password):
    accounts = load_staff_accounts()
    for account in accounts:
        if account.get('username') == username and account.get('active', True):
            return check_password_hash(account.get('password_hash', ''), password)
    if username == STAFF_USERNAME:
        if STAFF_PASSWORD_HASH:
            return check_password_hash(STAFF_PASSWORD_HASH, password)
        if STAFF_PASSWORD:
            return password == STAFF_PASSWORD
    return False


def staff_login_required(api=False):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(*args, **kwargs):
            if is_staff_logged_in():
                return view_func(*args, **kwargs)
            write_staff_log(action='access_denied', outcome='blocked', username=session.get('staff_username', ''), detail=request.path)
            if api:
                return jsonify({'success': False, 'message': 'กรุณาเข้าสู่ระบบเจ้าหน้าที่'}), 401
            return redirect(url_for('staff_login', next=request.path))
        return wrapped_view
    return decorator


@app.context_processor
def inject_auth_state():
    return {
        'staff_logged_in': is_staff_logged_in(),
        'security_hardened': is_security_hardened()
    }


def build_registration_key(row):
    key_parts = [
        row.get('display_name', ''),
        row.get('class_name', ''),
        row.get('school_name', ''),
        row.get('group_name', ''),
        row.get('id_card', ''),
        str(row.get('sequence', ''))
    ]
    return "|".join(str(part or '').strip() for part in key_parts)


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


def load_exam_results():
    if not os.path.exists(RESULTS_FILE):
        return {}
    try:
        with open(RESULTS_FILE, 'r', encoding='utf-8') as result_file:
            loaded_data = json.load(result_file)
        if isinstance(loaded_data, dict):
            return loaded_data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_exam_results(result_map):
    os.makedirs(RESULTS_DATA_DIR, exist_ok=True)
    with open(RESULTS_FILE, 'w', encoding='utf-8') as result_file:
        json.dump(result_map, result_file, ensure_ascii=False, indent=2)


def apply_exam_results(dataframe):
    if dataframe is None or dataframe.empty:
        return dataframe
    result_map = load_exam_results()
    dataframe['exam_result_status'] = dataframe['registration_key'].map(result_map).fillna('')
    return dataframe


def load_data_from_api():
    global df
    API_URL = "https://app.pariyat.com/pages/postx/name_json.php"
    current_year_numeric = get_current_buddhist_year(numeric=True)
    PARAMS = {'user': 'dh', 'pass': 'dhahiw8425', 'filter_year': current_year_numeric}
    
    try:
        response = requests.get(API_URL, params=PARAMS, timeout=60)
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
            raw_df['cert_nugdham_text'] = raw_df.apply(lambda r: extract_latest_cert(r.get('last_nugdham_id_list'), r.get('last_nugdham_id')), axis=1)
            raw_df['cert_pali_text'] = raw_df.apply(lambda r: extract_latest_cert(r.get('last_pali_id_list'), r.get('last_pali_id')), axis=1)
            raw_df['class_name'] = raw_df['level_id'].astype(str).map(LEVEL_ID_MAP).fillna('ไม่พบชื่อชั้นเรียน')
            raw_df['sequence'] = raw_df.groupby('class_name').cumcount() + 1
            raw_df['sequence_thai'] = raw_df['sequence'].apply(to_thai_digits)
            raw_df = raw_df.rename(columns={'status': 'reg_status', 'bureau': 'school_name', 'postx_type': 'group_name', 'card_id': 'id_card', 'mobile': 'tel'})
            raw_df['registration_key'] = raw_df.apply(build_registration_key, axis=1)
            required_columns = ['sequence_thai', 'display_name', 'age_pansa', 'reg_status', 'class_name', 'school_name', 'group_name', 'cert_nugdham_text', 'cert_pali_text', 'id_card', 'tel', 'registration_key']
            for col in required_columns:
                if col not in raw_df.columns: raw_df[col] = ''
            df = raw_df[required_columns].astype(str)
            df = apply_exam_results(df)
            print(f"--- [SUCCESS] Data processed. Final records: {len(df)}")
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
        id_card_raw = first_row.get('id_card', '')
        id_status_text = '(ไม่มีข้อมูล)'
        if id_card_raw and pd.notna(id_card_raw) and str(id_card_raw).lower() not in ['none', 'nan', 'null', '']:
            id_status_text = '✅ ถูกต้อง' if validate_thai_id(id_card_raw) else '❌ ไม่ถูกต้อง (หรือเป็น Passport)'
        
        tel_raw = first_row.get('tel')
        tel_masked_text = ''
        tel_cleaned = ''  
        
        if tel_raw and pd.notna(tel_raw) and str(tel_raw).lower() not in ['none', 'nan', 'null', '']:
            tel_cleaned = ''.join(filter(str.isdigit, str(tel_raw)))
            if len(tel_cleaned) >= 4:
                tel_masked_text = f"xxx-xxx-{to_thai_digits(tel_cleaned[-4:])}"
            elif len(tel_cleaned) > 0:
                tel_masked_text = to_thai_digits(tel_cleaned)
        
        person_data = {
            'name': name, 'age_pansa': first_row['age_pansa'],
            'school_name': to_thai_digits(first_row['school_name']),
            'group_name': to_thai_digits(first_row['group_name']),
            'id_status_text': id_status_text,
            'tel_masked_text': tel_masked_text,
            'tel_cleaned': tel_cleaned,
            'registrations': [
                {'class_name': row['class_name'], 'reg_status': row['reg_status'],
                 'sequence': row['sequence_thai'],
                 'cert_nugdham': to_thai_digits(row['cert_nugdham_text']),
                 'cert_pali': to_thai_digits(row['cert_pali_text'])}
                for _, row in group.iterrows()
            ]
        }
        final_results.append(person_data)
    return jsonify(final_results)


@app.route('/search_exam_results')
@staff_login_required(api=True)
def search_exam_results():
    query = request.args.get('q', '').strip()
    if df is None or df.empty or query == '':
        return jsonify([])

    results_df = df[df['display_name'].str.contains(query, case=False, na=False)]
    if results_df.empty:
        return jsonify([])

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
                    'registration_key': row['registration_key'],
                    'class_name': row['class_name'],
                    'reg_status': row['reg_status'],
                    'sequence': row['sequence_thai'],
                    'exam_result_status': row.get('exam_result_status', '')
                }
                for _, row in group.iterrows()
            ]
        }
        final_results.append(person_data)
    return jsonify(final_results)


@app.route('/update_exam_result', methods=['POST'])
@staff_login_required(api=True)
def update_exam_result():
    global df
    payload = request.get_json(silent=True) or {}
    registration_key = (payload.get('registration_key') or '').strip()
    exam_result_status = (payload.get('exam_result_status') or '').strip()

    if not registration_key:
        return jsonify({'success': False, 'message': 'ไม่พบรหัสรายการสมัครสอบ'}), 400
    if exam_result_status not in RESULT_STATUS_SET:
        return jsonify({'success': False, 'message': 'สถานะผลสอบไม่ถูกต้อง'}), 400

    result_map = load_exam_results()
    if exam_result_status:
        result_map[registration_key] = exam_result_status
    else:
        result_map.pop(registration_key, None)
    save_exam_results(result_map)

    if df is not None and not df.empty and 'exam_result_status' in df.columns:
        df.loc[df['registration_key'] == registration_key, 'exam_result_status'] = exam_result_status

    write_staff_log(
        action='update_exam_result',
        outcome='success',
        username=session.get('staff_username', ''),
        detail=f"registration_key={registration_key} status={exam_result_status or 'cleared'}"
    )
    return jsonify({'success': True, 'message': 'บันทึกผลการสอบเรียบร้อยแล้ว'})


@app.route('/')
def index():
    current_year_thai = get_current_buddhist_year(numeric=False)
    return render_template('index.html', current_buddhist_year=current_year_thai)


@app.route('/staff/login', methods=['GET', 'POST'])
def staff_login():
    if is_staff_logged_in():
        return redirect(url_for('manage_results'))

    migrate_env_staff_to_json()

    error_message = ''
    next_url = request.args.get('next', '')
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        next_url = request.form.get('next', '')

        if not is_staff_auth_configured():
            error_message = 'ระบบยังไม่ได้ตั้งค่าบัญชีเจ้าหน้าที่'
            write_staff_log(action='login', outcome='blocked', username=username, detail='missing_staff_config')
        elif is_account_locked(username):
            error_message = f'บัญชีถูกล็อกชั่วคราว โปรดลองอีกครั้งใน {LOCKOUT_MINUTES} นาที'
            write_staff_log(action='login', outcome='blocked', username=username, detail='account_locked')
        elif verify_staff_password(username, password):
            record_login_attempt(username, True)
            session['staff_logged_in'] = True
            session['staff_username'] = username
            write_staff_log(action='login', outcome='success', username=username, detail='staff_login')
            create_backup()
            if is_safe_redirect_url(next_url):
                return redirect(next_url)
            return redirect(url_for('manage_results'))
        else:
            record_login_attempt(username, False)
            error_message = 'ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง'
            write_staff_log(action='login', outcome='failed', username=username, detail='invalid_credentials')

    return render_template(
        'login.html',
        current_buddhist_year=get_current_buddhist_year(numeric=False),
        error_message=error_message,
        next_url=next_url if is_safe_redirect_url(next_url) else '',
        login_notice=get_login_notice()
    )


@app.route('/staff/manage')
@admin_required()
def staff_manage():
    current_year_thai = get_current_buddhist_year(numeric=False)
    accounts = load_staff_accounts()
    return render_template(
        'manage_staff.html',
        current_buddhist_year=current_year_thai,
        staff_accounts=accounts,
        is_admin=is_admin(session.get('staff_username', ''))
    )


@app.route('/staff/statistics')
@staff_login_required()
def staff_statistics():
    current_year_thai = get_current_buddhist_year(numeric=False)
    stats = get_statistics()
    return render_template(
        'statistics.html',
        current_buddhist_year=current_year_thai,
        statistics=stats
    )


@app.route('/staff/activity')
@admin_required()
def staff_activity():
    current_year_thai = get_current_buddhist_year(numeric=False)
    log_entries = []
    if os.path.exists(STAFF_ACTIVITY_LOG_FILE):
        with open(STAFF_ACTIVITY_LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            for line in reversed(lines[-200:]):
                line = line.strip()
                if not line:
                    continue
                entry = {'raw': line}
                try:
                    parts = line.split(' | ')
                    for part in parts:
                        if '=' in part:
                            key, value = part.split('=', 1)
                            entry[key.strip()] = value.strip()
                except:
                    pass
                log_entries.append(entry)
    return render_template(
        'activity_log.html',
        current_buddhist_year=current_year_thai,
        log_entries=log_entries
    )


@app.route('/api/staff', methods=['GET'])
@admin_required(api=True)
def api_get_staff():
    accounts = load_staff_accounts()
    return jsonify({'success': True, 'accounts': accounts})


@app.route('/api/staff', methods=['POST'])
@admin_required(api=True)
def api_add_staff():
    payload = request.get_json(silent=True) or {}
    username = (payload.get('username') or '').strip()
    password = payload.get('password') or ''
    full_name = (payload.get('full_name') or '').strip()
    role = payload.get('role', 'staff')

    if not username or not password:
        return jsonify({'success': False, 'message': 'กรุณากรอกชื่อผู้ใช้และรหัสผ่าน'}), 400

    success, message = add_staff_account(username, password, full_name, role)
    if success:
        write_staff_log(
            action='add_staff',
            outcome='success',
            username=session.get('staff_username', ''),
            detail=f'added_username={username} role={role}'
        )
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'message': message}), 400


@app.route('/api/staff/<username>', methods=['PUT'])
@admin_required(api=True)
def api_update_staff(username):
    payload = request.get_json(silent=True) or {}
    password = payload.get('password')
    full_name = payload.get('full_name')
    active = payload.get('active')
    role = payload.get('role')

    success, message = update_staff_account(username, password, full_name, active, role)
    if success:
        write_staff_log(
            action='update_staff',
            outcome='success',
            username=session.get('staff_username', ''),
            detail=f'updated_username={username}'
        )
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'message': message}), 400


@app.route('/api/staff/<username>', methods=['DELETE'])
@admin_required(api=True)
def api_delete_staff(username):
    success, message = delete_staff_account(username)
    if success:
        write_staff_log(
            action='delete_staff',
            outcome='success',
            username=session.get('staff_username', ''),
            detail=f'deleted_username={username}'
        )
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'message': message}), 400


@app.route('/api/statistics', methods=['GET'])
@staff_login_required(api=True)
def api_get_statistics():
    return jsonify({'success': True, 'statistics': get_statistics()})


@app.route('/api/backup', methods=['POST'])
@admin_required(api=True)
def api_create_backup():
    try:
        create_backup()
        write_staff_log(
            action='create_backup',
            outcome='success',
            username=session.get('staff_username', ''),
            detail='manual_backup'
        )
        return jsonify({'success': True, 'message': 'สำรองข้อมูลสำเร็จ'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/staff/logout', methods=['POST'])
def staff_logout():
    write_staff_log(action='logout', outcome='success', username=session.get('staff_username', ''), detail='staff_logout')
    session.clear()
    return redirect(url_for('index'))


@app.route('/manage-results')
@staff_login_required()
def manage_results():
    current_year_thai = get_current_buddhist_year(numeric=False)
    status_options = [status for status in RESULT_STATUS_OPTIONS if status]
    return render_template(
        'manage_results.html',
        current_buddhist_year=current_year_thai,
        result_status_options=status_options
    )


@app.route('/get_data_info')
def get_data_info():
    return jsonify({'timestamp': get_data_timestamp(), 'count': len(df) if df is not None else 0})


def get_data_timestamp():
    bangkok_tz = pytz.timezone("Asia/Bangkok")
    return datetime.now(bangkok_tz).strftime('%d/%m/%Y %H:%M:%S')


load_data_from_api()

if __name__ == '__main__':
    app.run(debug=True)
