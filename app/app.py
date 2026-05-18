import json
import hashlib
import logging
import os
import sqlite3
import uuid
from functools import wraps
from flask import Flask, render_template, jsonify, request, session, redirect, url_for, Response
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
LOGS_DIR = os.getenv('LOGS_DIR', '').strip() or os.path.join(BASE_DIR, 'logs')
STAFF_ACTIVITY_LOG_FILE = os.path.join(LOGS_DIR, 'staff_activity.log')
DEFAULT_SECRET_KEY = 'change-this-secret-in-production'

load_dotenv(ENV_FILE)

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.secret_key = os.getenv('FLASK_SECRET_KEY', DEFAULT_SECRET_KEY)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024
df = None
DF_CACHE = {}
DF_CACHE_META = {}
CURRENT_YEAR_NUMERIC = None
RESULT_STATUS_OPTIONS = ['', 'สอบตก', 'ขาดสอบ', 'ขาดสิทธิ์', 'สอบได้', 'สอบซ่อม', 'สอบซ่อมได้']
RESULT_STATUS_SET = set(RESULT_STATUS_OPTIONS)
RESULTS_DATA_DIR = os.getenv('RESULTS_DATA_DIR', '').strip() or os.getenv('PARIYAT_DATA_DIR', '').strip() or os.path.join(BASE_DIR, 'data')
RESULTS_FILE = os.path.join(RESULTS_DATA_DIR, 'exam_results.json')
STAFF_ACCOUNTS_FILE = os.path.join(RESULTS_DATA_DIR, 'staff_accounts.json')
BALI_SUMMARY_FILE = os.path.join(RESULTS_DATA_DIR, 'bali_summary_2569.json')
API_SNAPSHOT_MAX_AGE_HOURS = int(os.getenv('API_SNAPSHOT_MAX_AGE_HOURS', '24') or 24)
try:
    API_SNAPSHOT_LOCK_MAX_YEAR = int((os.getenv('API_SNAPSHOT_LOCK_MAX_YEAR') or '').strip() or 0) or None
except ValueError:
    API_SNAPSHOT_LOCK_MAX_YEAR = None
ANALYTICS_DB_FILE = os.path.join(RESULTS_DATA_DIR, 'analytics.sqlite3')
VISITOR_COOKIE_NAME = 'ps_vid'
VISITOR_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365 * 5
VISITOR_COUNTER_CACHE = {'ts': None, 'date': None, 'data': None}

bali_summary_data = None
LOGIN_ATTEMPTS_FILE = os.path.join(RESULTS_DATA_DIR, 'login_attempts.json')
BACKUPS_DIR = os.getenv('BACKUPS_DIR', '').strip() or os.path.join(BASE_DIR, 'backups')
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
CLASS_NAME_ORDER = [LEVEL_ID_MAP[level_id] for level_id in LEVEL_ID_MAP]
CLASS_NAME_ORDER_INDEX = {class_name: index for index, class_name in enumerate(CLASS_NAME_ORDER)}

DEPARTMENT_LEVELS = {
    'tham': {
        'name': 'แผนกธรรม',
        'subsections': {
            'tham': {
                'name': 'นักธรรม',
                'levels': ['5001', '5002', '5003']
            },
            'tham_studies': {
                'name': 'ธรรมศึกษา',
                'levels': ['5004', '5005', '5006']
            }
        }
    },
    'bali': {
        'name': 'แผนกบาลี',
        'subsections': {
            'bali': {
                'name': 'บาลี',
                'levels': ['5015', '5016', '5017', '5018', '5019', '5020', '5021', '5022']
            },
            'bali_studies': {
                'name': 'บาลีศึกษา',
                'levels': ['5007', '5008', '5009', '5010', '5011', '5012', '5013', '5014']
            }
        }
    }
}


@app.route('/@vite/client')
def vite_client_stub():
    return Response('', status=204, mimetype='application/javascript')


def get_bangkok_now():
    timezone = pytz.timezone('Asia/Bangkok')
    return datetime.now(timezone)


def get_today_date_key():
    return get_bangkok_now().date().isoformat()


def ensure_analytics_db():
    os.makedirs(RESULTS_DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(ANALYTICS_DB_FILE, timeout=10)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('CREATE TABLE IF NOT EXISTS totals (key TEXT PRIMARY KEY, value INTEGER NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS all_seen (visitor_id TEXT PRIMARY KEY, first_seen TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS daily_seen (date TEXT NOT NULL, visitor_id TEXT NOT NULL, PRIMARY KEY(date, visitor_id))')
        conn.execute('CREATE TABLE IF NOT EXISTS daily_stats (date TEXT PRIMARY KEY, pageviews INTEGER NOT NULL, unique_visitors INTEGER NOT NULL)')
        conn.execute("INSERT OR IGNORE INTO totals(key, value) VALUES ('total_pageviews', 0)")
        conn.execute("INSERT OR IGNORE INTO totals(key, value) VALUES ('total_unique_visitors', 0)")
        conn.commit()
    finally:
        conn.close()


def should_count_request(response):
    if request.method != 'GET':
        return False
    if response.status_code != 200:
        return False
    if not (response.mimetype or '').startswith('text/html'):
        return False
    path = request.path or ''
    if path.startswith('/static') or path.startswith('/api') or path.startswith('/@vite') or path.startswith('/staff') or path.startswith('/manage-results'):
        return False
    agent = (request.headers.get('User-Agent') or '').lower()
    bot_keywords = ['bot', 'spider', 'crawl', 'slackbot', 'facebookexternalhit', 'whatsapp', 'telegrambot', 'preview']
    if any(keyword in agent for keyword in bot_keywords):
        return False
    return True


def record_visit(visitor_id):
    ensure_analytics_db()
    today = get_today_date_key()
    now_iso = get_bangkok_now().isoformat()

    conn = sqlite3.connect(ANALYTICS_DB_FILE, timeout=10)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        cur = conn.cursor()
        cur.execute('BEGIN IMMEDIATE')
        cur.execute("UPDATE totals SET value = value + 1 WHERE key = 'total_pageviews'")
        cur.execute(
            "INSERT INTO daily_stats(date, pageviews, unique_visitors) VALUES (?, 1, 0) "
            "ON CONFLICT(date) DO UPDATE SET pageviews = pageviews + 1",
            (today,)
        )
        cur.execute("INSERT OR IGNORE INTO daily_seen(date, visitor_id) VALUES (?, ?)", (today, visitor_id))
        if cur.rowcount == 1:
            cur.execute("UPDATE daily_stats SET unique_visitors = unique_visitors + 1 WHERE date = ?", (today,))
        cur.execute("INSERT OR IGNORE INTO all_seen(visitor_id, first_seen) VALUES (?, ?)", (visitor_id, now_iso))
        if cur.rowcount == 1:
            cur.execute("UPDATE totals SET value = value + 1 WHERE key = 'total_unique_visitors'")
        conn.commit()
    finally:
        conn.close()
    VISITOR_COUNTER_CACHE['ts'] = None


def get_visitor_counts():
    today = get_today_date_key()
    cache_ts = VISITOR_COUNTER_CACHE.get('ts')
    if cache_ts and VISITOR_COUNTER_CACHE.get('date') == today:
        age_seconds = (get_bangkok_now() - cache_ts).total_seconds()
        if age_seconds < 30 and isinstance(VISITOR_COUNTER_CACHE.get('data'), dict):
            return VISITOR_COUNTER_CACHE['data']

    ensure_analytics_db()
    conn = sqlite3.connect(ANALYTICS_DB_FILE, timeout=10)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        cur = conn.cursor()
        cur.execute("SELECT value FROM totals WHERE key = 'total_unique_visitors'")
        total_unique = int((cur.fetchone() or [0])[0] or 0)
        cur.execute("SELECT value FROM totals WHERE key = 'total_pageviews'")
        total_pageviews = int((cur.fetchone() or [0])[0] or 0)
        cur.execute("SELECT unique_visitors FROM daily_stats WHERE date = ?", (today,))
        row = cur.fetchone()
        today_unique = int(row[0] or 0) if row else 0
    finally:
        conn.close()

    data = {
        'visitors_today': today_unique,
        'total_unique_visitors': total_unique,
        'total_pageviews': total_pageviews
    }
    VISITOR_COUNTER_CACHE['ts'] = get_bangkok_now()
    VISITOR_COUNTER_CACHE['date'] = today
    VISITOR_COUNTER_CACHE['data'] = data
    return data


@app.after_request
def track_visitors(response):
    visitor_id = request.cookies.get(VISITOR_COOKIE_NAME)
    new_visitor_id = None
    if not visitor_id:
        new_visitor_id = uuid.uuid4().hex
        visitor_id = new_visitor_id

    if visitor_id and should_count_request(response):
        try:
            record_visit(visitor_id)
        except Exception:
            logging.exception('visitor analytics error')

    if new_visitor_id:
        response.set_cookie(
            VISITOR_COOKIE_NAME,
            new_visitor_id,
            max_age=VISITOR_COOKIE_MAX_AGE_SECONDS,
            samesite='Lax'
        )
    return response


def to_thai_digits(text):
    if text is None or pd.isna(text): return ''
    text = str(text)
    thai_digits = str.maketrans('0123456789', '๐๑๒๓๔๕๖๗๘๙')
    return text.translate(thai_digits)


def normalize_name_key(value):
    if value is None or pd.isna(value):
        return ''
    text = str(value).strip()
    if not text:
        return ''
    text = text.replace('_', ' ').replace('-', ' ')
    text = text.replace('(', ' ').replace(')', ' ')
    text = pd.Series([text]).str.replace(r'[\s\u200b\u200c\u200d\ufeff]+', '', regex=True).iloc[0]
    return text


def strip_thai_title_prefix(value):
    text = normalize_name_key(value)
    if not text:
        return ''
    prefixes = [
        'พระครูสังฆรักษ์',
        'พระครูปลัด',
        'พระครู',
        'พระมหา',
        'พระอธิการ',
        'พระปลัด',
        'พระใบฎีกา',
        'พระ',
        'สามเณร',
        'นาย',
        'นาง',
        'นางสาว',
    ]
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if text.startswith(prefix):
                text = text[len(prefix):]
                changed = True
                break
    return text


def build_base_name_key_from_display_name(display_name):
    text = str(display_name or '').strip()
    if not text:
        return ''
    match = pd.Series([text]).str.extract(r'\(([^)]+)\)')[0].iloc[0]
    if isinstance(match, str) and match.strip():
        last_name = match.strip()
        without_parentheses = pd.Series([text]).str.replace(r'\s*\([^)]*\)\s*', ' ', regex=True).iloc[0].strip()
        first_token = without_parentheses.split()[0] if without_parentheses.split() else ''
        first_name = strip_thai_title_prefix(first_token)
        return normalize_name_key(f'{first_name}{last_name}')
    parts = [part for part in text.split() if part]
    if len(parts) < 2:
        return ''
    first_name = strip_thai_title_prefix(parts[0])
    last_name = parts[-1]
    return normalize_name_key(f'{first_name}{last_name}')


def extract_last_name_from_display_name(display_name):
    text = str(display_name or '').strip()
    if not text:
        return ''
    match = pd.Series([text]).str.extract(r'\(([^)]+)\)')[0].iloc[0]
    if isinstance(match, str) and match.strip():
        return match.strip()
    parts = [part for part in text.split() if part]
    return parts[-1] if len(parts) >= 2 else ''


def build_result_key(row):
    id_card = str(row.get('id_card', '') or '').strip()
    class_name = str(row.get('class_name', '') or '').strip()
    if id_card and id_card.lower() not in {'none', 'nan', 'null'}:
        return f'cid={id_card}|class={class_name}'
    base_key = build_base_name_key_from_display_name(row.get('display_name', ''))
    sequence = str(row.get('sequence', '') or '').strip()
    if base_key:
        return f'name={base_key}|class={class_name}|seq={sequence}'
    return str(row.get('registration_key', '') or '').strip()


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


def get_runtime_current_year_numeric():
    try:
        return int(get_current_buddhist_year(numeric=True))
    except Exception:
        return int(CURRENT_YEAR_NUMERIC)


def normalize_year_value(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def get_selected_year():
    year_value = request.args.get('year')
    parsed = normalize_year_value(year_value)
    return parsed or CURRENT_YEAR_NUMERIC


def get_exam_results_file(year):
    return os.path.join(RESULTS_DATA_DIR, f'exam_results_{int(year)}.json')


def get_exam_names_file(year):
    return os.path.join(RESULTS_DATA_DIR, f'exam_names_{int(year)}.json')


def get_manual_registrations_file(year):
    return os.path.join(RESULTS_DATA_DIR, f'manual_registrations_{int(year)}.json')


def get_api_snapshot_file(year):
    return os.path.join(RESULTS_DATA_DIR, f'api_snapshot_{int(year)}.json')


def is_snapshot_fresh(snapshot_meta):
    if not isinstance(snapshot_meta, dict):
        return False
    if API_SNAPSHOT_MAX_AGE_HOURS <= 0:
        return False
    fetched_at = snapshot_meta.get('fetched_at')
    if not isinstance(fetched_at, str) or not fetched_at.strip():
        return False
    try:
        fetched_dt = datetime.fromisoformat(fetched_at)
    except ValueError:
        return False
    age = datetime.now() - fetched_dt
    return age.total_seconds() <= (API_SNAPSHOT_MAX_AGE_HOURS * 3600)


def load_api_snapshot(year):
    snapshot_file = get_api_snapshot_file(year)
    if not os.path.exists(snapshot_file):
        return None
    try:
        with open(snapshot_file, 'r', encoding='utf-8') as fp:
            snapshot = json.load(fp)
        if isinstance(snapshot, dict) and isinstance(snapshot.get('data'), list):
            return snapshot
    except (OSError, json.JSONDecodeError):
        pass
    return None


def save_api_snapshot(year, api_rows):
    if not isinstance(api_rows, list):
        return False
    os.makedirs(RESULTS_DATA_DIR, exist_ok=True)
    snapshot_file = get_api_snapshot_file(year)
    payload = {
        'year': int(year),
        'fetched_at': datetime.now().isoformat(),
        'data': api_rows
    }
    with open(snapshot_file, 'w', encoding='utf-8') as fp:
        json.dump(payload, fp, ensure_ascii=False)
    return True


def ensure_year_result_file(year):
    year_file = get_exam_results_file(year)
    if os.path.exists(year_file):
        return year_file
    if int(year) == int(CURRENT_YEAR_NUMERIC) and os.path.exists(RESULTS_FILE):
        try:
            import shutil
            shutil.copy2(RESULTS_FILE, year_file)
            return year_file
        except Exception:
            return RESULTS_FILE
    return year_file


def list_available_years():
    years = set()
    years.add(int(CURRENT_YEAR_NUMERIC))
    if CURRENT_YEAR_NUMERIC and int(CURRENT_YEAR_NUMERIC) > 1:
        years.add(int(CURRENT_YEAR_NUMERIC) - 1)
    if os.path.exists(RESULTS_DATA_DIR):
        for filename in os.listdir(RESULTS_DATA_DIR):
            if filename.startswith('exam_results_') and filename.endswith('.json'):
                year_part = filename[len('exam_results_'):-len('.json')]
                year_value = normalize_year_value(year_part)
                if year_value:
                    years.add(year_value)
    return sorted(years)


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


def get_statistics(level_ids=None, year=None):
    stats = {}
    year_value = normalize_year_value(year) or CURRENT_YEAR_NUMERIC
    base_df = get_df_for_year(year_value) if int(year_value) != int(CURRENT_YEAR_NUMERIC) else df
    filtered_df = base_df
    
    if level_ids and base_df is not None and not base_df.empty:
        class_names = []
        for level_id in level_ids:
            class_name = LEVEL_ID_MAP.get(str(level_id), '')
            if class_name:
                class_names.append(class_name)
        if class_names:
            filtered_df = base_df[base_df['class_name'].isin(class_names)]
    
    if filtered_df is not None and not filtered_df.empty:
        stats['total_registrations'] = len(filtered_df)
        stats['unique_people'] = filtered_df['display_name'].nunique()
        
        if level_ids is None and base_df is not None and not base_df.empty:
            tham_class_names = []
            bali_class_names = []
            for subsection in DEPARTMENT_LEVELS.get('tham', {}).get('subsections', {}).values():
                for level_id in subsection.get('levels', []):
                    class_name = LEVEL_ID_MAP.get(str(level_id), '')
                    if class_name:
                        tham_class_names.append(class_name)
            for subsection in DEPARTMENT_LEVELS.get('bali', {}).get('subsections', {}).values():
                for level_id in subsection.get('levels', []):
                    class_name = LEVEL_ID_MAP.get(str(level_id), '')
                    if class_name:
                        bali_class_names.append(class_name)
            tham_class_names = sorted(set(tham_class_names))
            bali_class_names = sorted(set(bali_class_names))

            tham_people = set(base_df[base_df['class_name'].isin(tham_class_names)]['display_name'].tolist())
            bali_people = set(base_df[base_df['class_name'].isin(bali_class_names)]['display_name'].tolist())
            stats['people_both_departments'] = len(tham_people & bali_people)
            stats['people_only_tham'] = len(tham_people - bali_people)
            stats['people_only_bali'] = len(bali_people - tham_people)

        if 'exam_result_status' in filtered_df.columns:
            status_order = ['สอบได้', 'สอบซ่อมได้', 'สอบซ่อม', 'สอบตก', 'ขาดสอบ', 'ขาดสิทธิ์', 'ยังไม่บันทึกผล']
            status_series = filtered_df['exam_result_status'].fillna('').astype(str)
            display_status_series = status_series.replace({'': 'ยังไม่บันทึกผล'})
            status_counts = display_status_series.value_counts().to_dict()
            ordered_status_counts = {}
            for status_name in status_order:
                if status_name in status_counts:
                    ordered_status_counts[status_name] = int(status_counts[status_name])
            for status_name, count in status_counts.items():
                if status_name not in ordered_status_counts:
                    ordered_status_counts[status_name] = int(count)
            stats['by_status'] = ordered_status_counts
        
        class_counts = filtered_df['class_name'].value_counts().to_dict()
        ordered_classes = order_class_names(list(class_counts.keys()))
        stats['by_class'] = {class_name: int(class_counts[class_name]) for class_name in ordered_classes if class_name in class_counts}

        summary_rows = []
        total_sent = 0
        total_active = 0
        total_pass = 0
        for class_name in ordered_classes:
            class_df = filtered_df[filtered_df['class_name'] == class_name]
            sent_count = len(class_df)
            active_count = len(class_df[~class_df['exam_result_status'].isin(PASS_SUMMARY_ABSENT_STATUSES)])
            pass_count = len(class_df[class_df['exam_result_status'].isin(PASS_SUMMARY_PASS_STATUSES)])
            fail_count = max(int(active_count) - int(pass_count), 0)
            pass_rate = (pass_count / sent_count * 100) if sent_count > 0 else None
            summary_rows.append({
                'class_name': class_name,
                'sent': int(sent_count),
                'active': int(active_count),
                'fail': int(fail_count),
                'pass': int(pass_count),
                'pass_rate': pass_rate
            })
            total_sent += sent_count
            total_active += active_count
            total_pass += pass_count

        stats['pass_summary'] = {
            'rows': summary_rows,
            'total': {
                'sent': int(total_sent),
                'active': int(total_active),
                'fail': max(int(total_active) - int(total_pass), 0),
                'pass': int(total_pass),
                'pass_rate': (total_pass / total_sent * 100) if total_sent > 0 else None
            }
        }
    
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


def static_asset_url(filename):
    file_path = os.path.join(STATIC_DIR, filename)
    version = int(os.path.getmtime(file_path)) if os.path.exists(file_path) else int(datetime.now().timestamp())
    return url_for('static', filename=filename, v=version)


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
    group_descriptions = {}
    if isinstance(bali_summary_data, dict):
        group_descriptions = bali_summary_data.get('group_descriptions') or {}
    return {
        'staff_logged_in': is_staff_logged_in(),
        'security_hardened': is_security_hardened(),
        'is_admin': is_admin,
        'static_asset_url': static_asset_url,
        'group_descriptions': group_descriptions,
        'to_thai_digits': to_thai_digits,
        'visitor_counter': get_visitor_counts()
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


def get_class_sort_key(class_name):
    return (CLASS_NAME_ORDER_INDEX.get(class_name, len(CLASS_NAME_ORDER)), class_name)


def order_class_names(class_names):
    return sorted(class_names, key=get_class_sort_key)


def normalize_summary_class_name(class_name):
    return str(class_name or '').replace(' ', '').strip()


PASS_SUMMARY_GROUP_ORDER = ['กลุ่ม ๑', 'กลุ่ม ๒', 'กลุ่ม ๓', 'กลุ่ม ๔', 'กลุ่ม ๕', 'กลุ่ม ๖', 'กลุ่ม ๗', 'ไม่ระบุ']
PASS_SUMMARY_ABSENT_STATUSES = {'ขาดสอบ', 'ขาดสิทธิ์'}
PASS_SUMMARY_PASS_STATUSES = {'สอบได้', 'สอบซ่อมได้'}
PASS_SUMMARY_GROUP_MAP = {
    'None': 'ไม่ระบุ',
    '': 'ไม่ระบุ',
    'ไม่ระบุ': 'ไม่ระบุ',
    'พระภิกษุ/สามเณรวัดสาขา': 'กลุ่ม ๓',
    'พระภิกษุประจำหน่วยงาน': 'กลุ่ม ๒',
    'เจ้าหน้าที่ภายในองค์กร': 'กลุ่ม ๖',
    'สามเณรปริยัติสามัญ': 'กลุ่ม ๔',
    'พระนิสิตปัจจุบันสถาบันธรรมชัย': 'กลุ่ม ๔',
    'สามเณรเปรียญธรรม': 'กลุ่ม ๑',
    'พระมหาเปรียญธรรม': 'กลุ่ม ๑',
    'สาธุชนทั่วไป': 'กลุ่ม ๗'
}


def normalize_pass_summary_group(group_name):
    group_text = str(group_name or '').strip()
    if group_text in {'กลุ่ม ๑', 'กลุ่ม ๒', 'กลุ่ม ๓', 'กลุ่ม ๔', 'กลุ่ม ๕', 'กลุ่ม ๖', 'กลุ่ม ๗'}:
        return group_text
    return PASS_SUMMARY_GROUP_MAP.get(group_text, 'ไม่ระบุ')


def build_pass_summary(summary_df, class_name):
    if summary_df is None or summary_df.empty or not class_name:
        return None

    group_rows = {}
    total_sent = 0
    total_active = 0
    total_pass = 0

    for group_name in PASS_SUMMARY_GROUP_ORDER:
        group_df = summary_df[summary_df['summary_group'] == group_name]
        sent_count = len(group_df)
        active_count = len(group_df[~group_df['exam_result_status'].isin(PASS_SUMMARY_ABSENT_STATUSES)])
        pass_count = len(group_df[group_df['exam_result_status'].isin(PASS_SUMMARY_PASS_STATUSES)])
        fail_count = max(int(active_count) - int(pass_count), 0)

        group_rows[group_name] = {
            'ส่งสอบ': int(sent_count),
            'คงสอบ': int(active_count),
            'สอบตก': int(fail_count),
            'สอบได้': int(pass_count)
        }
        total_sent += sent_count
        total_active += active_count
        total_pass += pass_count

    return {
        'class_name': class_name,
        'class_data': {
            'groups': group_rows,
            'total': {
                'ส่งสอบ': int(total_sent),
                'คงสอบ': int(total_active),
                'สอบตก': max(int(total_active) - int(total_pass), 0),
                'สอบได้': int(total_pass)
            }
        }
    }


def load_exam_results():
    year = CURRENT_YEAR_NUMERIC
    try:
        year = get_selected_year()
    except RuntimeError:
        pass
    return load_exam_results_for_year(year)


def load_exam_results_for_year(year):
    result_file = ensure_year_result_file(year)
    if not os.path.exists(result_file):
        return {}
    try:
        with open(result_file, 'r', encoding='utf-8') as fp:
            loaded_data = json.load(fp)
        if isinstance(loaded_data, dict):
            return loaded_data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def load_exam_names_for_year(year):
    names_file = get_exam_names_file(year)
    if not os.path.exists(names_file):
        return {}
    try:
        with open(names_file, 'r', encoding='utf-8') as fp:
            loaded_data = json.load(fp)
        if isinstance(loaded_data, dict):
            return loaded_data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_exam_names_for_year(year, names_map):
    os.makedirs(RESULTS_DATA_DIR, exist_ok=True)
    names_file = get_exam_names_file(year)
    with open(names_file, 'w', encoding='utf-8') as fp:
        json.dump(names_map, fp, ensure_ascii=False, indent=2)


def load_manual_registrations_for_year(year):
    manual_file = get_manual_registrations_file(year)
    if not os.path.exists(manual_file):
        return {}
    try:
        with open(manual_file, 'r', encoding='utf-8') as fp:
            loaded_data = json.load(fp)
        if isinstance(loaded_data, dict):
            return loaded_data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_manual_registrations_for_year(year, manual_map):
    os.makedirs(RESULTS_DATA_DIR, exist_ok=True)
    manual_file = get_manual_registrations_file(year)
    with open(manual_file, 'w', encoding='utf-8') as fp:
        json.dump(manual_map, fp, ensure_ascii=False, indent=2)


def save_exam_results(result_map):
    year = CURRENT_YEAR_NUMERIC
    try:
        year = get_selected_year()
    except RuntimeError:
        pass
    save_exam_results_for_year(year, result_map)


def save_exam_results_for_year(year, result_map):
    os.makedirs(RESULTS_DATA_DIR, exist_ok=True)
    result_file = get_exam_results_file(year)
    with open(result_file, 'w', encoding='utf-8') as fp:
        json.dump(result_map, fp, ensure_ascii=False, indent=2)


def get_pending_exam_results_file(year):
    return os.path.join(RESULTS_DATA_DIR, f'pending_exam_results_{int(year)}.json')


def load_pending_exam_results_for_year(year):
    pending_file = get_pending_exam_results_file(year)
    if not os.path.exists(pending_file):
        return {'version': 1, 'items': {}}
    try:
        with open(pending_file, 'r', encoding='utf-8') as fp:
            payload = json.load(fp)
        if isinstance(payload, dict) and isinstance(payload.get('items'), dict):
            payload.setdefault('version', 1)
            return payload
    except (OSError, json.JSONDecodeError):
        pass
    return {'version': 1, 'items': {}}


def write_json_atomic(file_path, payload):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    temp_path = f'{file_path}.tmp'
    with open(temp_path, 'w', encoding='utf-8') as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    os.replace(temp_path, file_path)


def save_pending_exam_results_for_year(year, payload):
    pending_file = get_pending_exam_results_file(year)
    write_json_atomic(pending_file, payload)


def apply_exam_results(dataframe, year=None):
    if dataframe is None or dataframe.empty:
        return dataframe
    year_value = year or CURRENT_YEAR_NUMERIC
    result_map = load_exam_results_for_year(year_value)
    if 'result_key' in dataframe.columns:
        dataframe['exam_result_status'] = dataframe['result_key'].map(result_map).fillna(
            dataframe['registration_key'].map(result_map)
        ).fillna('')
    else:
        dataframe['exam_result_status'] = dataframe['registration_key'].map(result_map).fillna('')
    target_mask = dataframe['class_name'].astype(str).str.startswith('ป.') | dataframe['class_name'].astype(str).str.startswith('บ.ศ')
    dataframe.loc[target_mask & (dataframe['exam_result_status'] == ''), 'exam_result_status'] = 'สอบตก'
    return dataframe


def load_bali_summary():
    global bali_summary_data
    if os.path.exists(BALI_SUMMARY_FILE):
        try:
            with open(BALI_SUMMARY_FILE, 'r', encoding='utf-8') as f:
                bali_summary_data = json.load(f)
            print(f"--- [SUCCESS] Bali summary loaded: {BALI_SUMMARY_FILE}")
        except Exception as e:
            bali_summary_data = None
            print(f"--- [ERROR] Failed to load Bali summary: {e}")
    else:
        bali_summary_data = None


def build_processed_df_from_api_rows(api_rows, target_year_numeric, store_global):
    global df
    raw_df = pd.DataFrame(api_rows)
    raw_df['display_name'] = raw_df.apply(format_display_name, axis=1)
    raw_df['monk_year_num'] = pd.to_numeric(raw_df['monk_year'], errors='coerce').fillna(0).astype(int)
    raw_df['monk_month_num'] = pd.to_numeric(raw_df.get('monk_month', ''), errors='coerce').fillna(0).astype(int)
    raw_df['monk_day_num'] = pd.to_numeric(raw_df.get('monk_day', ''), errors='coerce').fillna(0).astype(int)
    raw_df['ordain_after_num'] = pd.to_numeric(raw_df['ordain_after'], errors='coerce').fillna(0).astype(int)
    raw_df['dob_year_num'] = pd.to_numeric(raw_df.get('dob_year', ''), errors='coerce').fillna(0).astype(int)
    raw_df['dob_month_num'] = pd.to_numeric(raw_df.get('dob_month', ''), errors='coerce').fillna(0).astype(int)
    raw_df['dob_day_num'] = pd.to_numeric(raw_df.get('dob_day', ''), errors='coerce').fillna(0).astype(int)
    raw_df['api_age_num'] = pd.to_numeric(raw_df.get('age', ''), errors='coerce').fillna(0).astype(int)
    academic_year_numeric = target_year_numeric - 1

    def build_date_sort_key(year_value, month_value, day_value):
        if year_value <= 0:
            return "99999999"
        month_value = month_value if 1 <= month_value <= 12 else 99
        day_value = day_value if 1 <= day_value <= 31 else 99
        return f"{year_value:04d}{month_value:02d}{day_value:02d}"

    def calculate_age_num(row):
        if row['dob_year_num'] <= 0:
            return row['api_age_num']
        birth_year = row['dob_year_num']
        birth_month = row['dob_month_num'] if 1 <= row['dob_month_num'] <= 12 else 1
        birth_day = row['dob_day_num'] if 1 <= row['dob_day_num'] <= 31 else 1
        ref_year = academic_year_numeric
        ref_month = 10
        ref_day = 10
        age_years = ref_year - birth_year
        if (ref_month, ref_day) < (birth_month, birth_day):
            age_years -= 1
        if age_years < 0:
            age_years = 0
        return age_years

    def calculate_pansa_num(row):
        if row['monk_year_num'] <= 0:
            return 0
        pansa = academic_year_numeric - row['monk_year_num'] + 1
        if row['ordain_after_num'] == 1:
            pansa -= 1
        if pansa < 0:
            pansa = 0
        return pansa

    raw_df['pansa_num'] = raw_df.apply(calculate_pansa_num, axis=1)
    raw_df['age_num'] = raw_df.apply(calculate_age_num, axis=1)

    def calculate_age_pansa(row):
        age_text = to_thai_digits(row['age_num']) if row['age_num'] > 0 else ''
        if row['monk_year_num'] > 0:
            return f"{age_text}/{to_thai_digits(row['pansa_num'])}" if age_text else to_thai_digits(row['pansa_num'])
        return age_text

    raw_df['age_thai'] = raw_df['age_num'].apply(lambda value: to_thai_digits(value) if value > 0 else '-')
    raw_df['pansa_thai'] = raw_df.apply(
        lambda row: to_thai_digits(row['pansa_num']) if row['monk_year_num'] > 0 else '-',
        axis=1
    )
    raw_df['ordain_sort_key'] = raw_df.apply(
        lambda row: build_date_sort_key(row['monk_year_num'], row['monk_month_num'], row['monk_day_num']),
        axis=1
    )
    raw_df['birth_sort_key'] = raw_df.apply(
        lambda row: build_date_sort_key(row['dob_year_num'], row['dob_month_num'], row['dob_day_num']),
        axis=1
    )

    raw_df['age_pansa'] = raw_df.apply(calculate_age_pansa, axis=1)
    raw_df['cert_nugdham_text'] = raw_df.apply(lambda r: extract_latest_cert(r.get('last_nugdham_id_list'), r.get('last_nugdham_id')), axis=1)
    raw_df['cert_pali_text'] = raw_df.apply(lambda r: extract_latest_cert(r.get('last_pali_id_list'), r.get('last_pali_id')), axis=1)
    raw_df['class_name'] = raw_df['level_id'].astype(str).map(LEVEL_ID_MAP).fillna('ไม่พบชื่อชั้นเรียน')
    raw_df['sequence'] = raw_df.groupby('class_name').cumcount() + 1
    raw_df['sequence_thai'] = raw_df['sequence'].apply(to_thai_digits)
    raw_df = raw_df.rename(columns={'status': 'reg_status', 'bureau': 'school_name', 'postx_type': 'group_name', 'card_id': 'id_card', 'mobile': 'tel'})
    raw_df['registration_key'] = raw_df.apply(build_registration_key, axis=1)
    raw_df['result_key'] = raw_df.apply(build_result_key, axis=1)
    required_columns = ['sequence_thai', 'display_name', 'age_num', 'pansa_num', 'monk_year_num', 'monk_month_num', 'monk_day_num', 'ordain_after_num', 'dob_year_num', 'dob_month_num', 'dob_day_num', 'age_thai', 'pansa_thai', 'age_pansa', 'ordain_sort_key', 'birth_sort_key', 'reg_status', 'class_name', 'school_name', 'group_name', 'cert_nugdham_text', 'cert_pali_text', 'id_card', 'tel', 'registration_key', 'result_key']
    for col in required_columns:
        if col not in raw_df.columns:
            raw_df[col] = ''
    result_df = raw_df[required_columns].astype(str)

    manual_map = load_manual_registrations_for_year(target_year_numeric)
    if isinstance(manual_map, dict) and manual_map:
        manual_rows = []
        for manual_key, manual_item in manual_map.items():
            if not isinstance(manual_item, dict):
                continue
            manual_class = str(manual_item.get('class_name') or '').strip()
            manual_name = str(manual_item.get('display_name') or '').strip()
            if not manual_class or not manual_name:
                continue
            manual_rows.append({
                'sequence_thai': to_thai_digits(manual_item.get('sequence') or ''),
                'display_name': manual_name,
                'age_num': str(manual_item.get('age_num') or ''),
                'pansa_num': str(manual_item.get('pansa_num') or ''),
                'monk_year_num': str(manual_item.get('monk_year_num') or ''),
                'monk_month_num': str(manual_item.get('monk_month_num') or ''),
                'monk_day_num': str(manual_item.get('monk_day_num') or ''),
                'ordain_after_num': str(manual_item.get('ordain_after_num') or ''),
                'dob_year_num': str(manual_item.get('dob_year_num') or ''),
                'dob_month_num': str(manual_item.get('dob_month_num') or ''),
                'dob_day_num': str(manual_item.get('dob_day_num') or ''),
                'age_thai': str(manual_item.get('age_thai') or '-'),
                'pansa_thai': str(manual_item.get('pansa_thai') or '-'),
                'age_pansa': str(manual_item.get('age_pansa') or '-'),
                'ordain_sort_key': str(manual_item.get('ordain_sort_key') or ''),
                'birth_sort_key': str(manual_item.get('birth_sort_key') or ''),
                'reg_status': str(manual_item.get('reg_status') or ''),
                'class_name': manual_class,
                'school_name': str(manual_item.get('school_name') or ''),
                'group_name': str(manual_item.get('group_name') or ''),
                'cert_nugdham_text': str(manual_item.get('cert_nugdham_text') or ''),
                'cert_pali_text': str(manual_item.get('cert_pali_text') or ''),
                'id_card': str(manual_item.get('id_card') or ''),
                'tel': str(manual_item.get('tel') or ''),
                'registration_key': str(manual_key),
                'result_key': str(manual_key)
            })
        if manual_rows:
            manual_df = pd.DataFrame(manual_rows)
            for col in required_columns:
                if col not in manual_df.columns:
                    manual_df[col] = ''
            manual_df = manual_df[required_columns].astype(str)
            result_df = pd.concat([result_df, manual_df], ignore_index=True)

    result_df = apply_exam_results(result_df, year=target_year_numeric)
    if store_global:
        df = result_df
    return result_df


def load_data_from_api(year=None, store_global=True, force_refresh=False):
    global df
    API_URL = os.getenv('PARIYAT_API_URL', "https://app.pariyat.com/pages/postx/name_json.php")
    API_USER = (os.getenv('PARIYAT_API_USER') or '').strip()
    API_PASS = (os.getenv('PARIYAT_API_PASS') or '').strip()
    target_year_numeric = int(year or CURRENT_YEAR_NUMERIC)
    PARAMS = {'user': API_USER, 'pass': API_PASS, 'filter_year': target_year_numeric}
    runtime_current_year = get_runtime_current_year_numeric()
    snapshot_lock_max_year = API_SNAPSHOT_LOCK_MAX_YEAR
    locked_year = (snapshot_lock_max_year is not None and target_year_numeric <= snapshot_lock_max_year) or (target_year_numeric < runtime_current_year)
    
    try:
        snapshot = None
        if locked_year or not force_refresh:
            snapshot = load_api_snapshot(target_year_numeric)
            if snapshot:
                if locked_year or is_snapshot_fresh(snapshot):
                    result_df = build_processed_df_from_api_rows(snapshot.get('data') or [], target_year_numeric, store_global)
                    print(f"--- [SUCCESS] Data loaded from snapshot (fresh). Final records: {len(result_df)}")
                    return result_df

        if locked_year and snapshot:
            raise RuntimeError('Snapshot is locked for this year; not refreshing from API')

        if not API_USER or not API_PASS:
            raise RuntimeError('Missing PARIYAT_API_USER or PARIYAT_API_PASS')

        response = requests.get(API_URL, params=PARAMS, timeout=60)
        json_data = response.json()
        
        if json_data.get('status') == 'success' and 'data' in json_data:
            api_rows = json_data.get('data') or []
            save_api_snapshot(target_year_numeric, api_rows)
            result_df = build_processed_df_from_api_rows(api_rows, target_year_numeric, store_global)
            print(f"--- [SUCCESS] Data processed. Final records: {len(result_df)}")
            return result_df
    except Exception as e:
        if store_global:
            df = pd.DataFrame()
        print(f"--- [CRITICAL ERROR] API Exception: {e}")

    snapshot = load_api_snapshot(target_year_numeric)
    if snapshot and isinstance(snapshot.get('data'), list):
        result_df = build_processed_df_from_api_rows(snapshot.get('data') or [], target_year_numeric, store_global)
        print(f"--- [SUCCESS] Data loaded from snapshot (fallback). Final records: {len(result_df)}")
        return result_df
    return pd.DataFrame()


def get_df_for_year(year):
    year_value = normalize_year_value(year) or CURRENT_YEAR_NUMERIC
    if year_value in DF_CACHE:
        if (API_SNAPSHOT_LOCK_MAX_YEAR is not None and int(year_value) <= int(API_SNAPSHOT_LOCK_MAX_YEAR)) or int(year_value) < int(get_runtime_current_year_numeric()):
            return DF_CACHE[year_value]
        cache_meta = DF_CACHE_META.get(year_value) or {}
        if API_SNAPSHOT_MAX_AGE_HOURS <= 0:
            return DF_CACHE[year_value]
        loaded_at = cache_meta.get('loaded_at')
        if isinstance(loaded_at, str) and loaded_at.strip():
            try:
                loaded_dt = datetime.fromisoformat(loaded_at)
                age = datetime.now() - loaded_dt
                if age.total_seconds() <= (API_SNAPSHOT_MAX_AGE_HOURS * 3600):
                    return DF_CACHE[year_value]
            except ValueError:
                pass
    loaded_df = load_data_from_api(year_value, store_global=False)
    DF_CACHE[year_value] = loaded_df
    DF_CACHE_META[year_value] = {'loaded_at': datetime.now().isoformat()}
    return loaded_df


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


@app.route('/get_classes')
@staff_login_required(api=True)
def get_classes():
    selected_year = get_selected_year()
    year_df = get_df_for_year(selected_year)
    if year_df is None or year_df.empty:
        return jsonify([])
    available_classes = order_class_names(year_df['class_name'].unique().tolist())
    return jsonify(available_classes)


@app.route('/search_exam_results')
@staff_login_required(api=True)
def search_exam_results():
    query = request.args.get('q', '').strip()
    class_filter = request.args.get('class', '').strip()
    selected_year = get_selected_year()
    
    year_df = get_df_for_year(selected_year)
    if year_df is None or year_df.empty:
        return jsonify([])

    names_map = load_exam_names_for_year(selected_year)
    results_df = year_df.copy()
    
    if query:
        results_df = results_df[results_df['display_name'].str.contains(query, case=False, na=False)]
    
    if class_filter:
        results_df = results_df[results_df['class_name'] == class_filter]
    
    if results_df.empty:
        return jsonify([])

    results_df = results_df.assign(
        pansa_sort=pd.to_numeric(results_df.get('pansa_num', ''), errors='coerce').fillna(0).astype(int),
        age_sort=pd.to_numeric(results_df.get('age_num', ''), errors='coerce').fillna(0).astype(int),
        has_pansa=lambda df_: pd.to_numeric(df_.get('pansa_num', ''), errors='coerce').fillna(0).astype(int) > 0,
        ordain_key=results_df['ordain_sort_key'].replace('', '99999999'),
        birth_key=results_df['birth_sort_key'].replace('', '99999999'),
        class_order=results_df['class_name'].map(lambda value: CLASS_NAME_ORDER_INDEX.get(value, len(CLASS_NAME_ORDER)))
    )
    ordering_df = results_df.groupby('display_name', sort=False).agg(
        has_pansa=('has_pansa', 'max'),
        pansa_sort=('pansa_sort', 'max'),
        ordain_key=('ordain_key', 'min'),
        age_sort=('age_sort', 'max'),
        birth_key=('birth_key', 'min')
    ).reset_index()
    ordering_df = ordering_df.sort_values(
        by=['has_pansa', 'pansa_sort', 'ordain_key', 'age_sort', 'birth_key', 'display_name'],
        ascending=[False, False, True, False, True, True]
    )
    grouped = results_df.groupby('display_name', sort=False)
    final_results = []
    for name in ordering_df['display_name'].tolist():
        group = grouped.get_group(name)
        first_row = group.iloc[0]
        exam_name = ''
        for _, row in group.iterrows():
            lookup_key = row.get('result_key') or row.get('registration_key')
            exam_name = names_map.get(str(lookup_key or ''), '') or exam_name
            if exam_name:
                break
        sorted_group = group.sort_values(by=['class_order', 'sequence_thai'], ascending=[True, True])
        person_data = {
            'name': name,
            'exam_name': exam_name,
            'age_pansa': first_row['age_pansa'],
            'school_name': to_thai_digits(first_row['school_name']),
            'group_name': to_thai_digits(first_row['group_name']),
            'registrations': [
                {
                    'registration_key': row['registration_key'],
                    'class_name': row['class_name'],
                    'reg_status': row['reg_status'],
                    'sequence': row['sequence_thai'],
                    'exam_result_status': row.get('exam_result_status', ''),
                    'exam_name': names_map.get(str((row.get('result_key') or row.get('registration_key')) or ''), '')
                }
                for _, row in sorted_group.iterrows()
            ]
        }
        final_results.append(person_data)
    return jsonify(final_results)


@app.route('/update_exam_result', methods=['POST'])
@staff_login_required(api=True)
def update_exam_result():
    payload = request.get_json(silent=True) or {}
    registration_key = (payload.get('registration_key') or '').strip()
    exam_result_status = (payload.get('exam_result_status') or '').strip()
    year_value = normalize_year_value(payload.get('year') or request.args.get('year')) or CURRENT_YEAR_NUMERIC

    if not registration_key:
        return jsonify({'success': False, 'message': 'ไม่พบรหัสรายการสมัครสอบ'}), 400
    if exam_result_status not in RESULT_STATUS_SET:
        return jsonify({'success': False, 'message': 'สถานะผลสอบไม่ถูกต้อง'}), 400

    store_key = registration_key
    year_df = get_df_for_year(year_value)
    if year_df is not None and not year_df.empty and 'result_key' in year_df.columns:
        matched_rows = year_df.loc[year_df['registration_key'] == registration_key]
        if not matched_rows.empty:
            candidate = str(matched_rows.iloc[0].get('result_key') or '').strip()
            if candidate:
                store_key = candidate

    result_map = load_exam_results_for_year(year_value)
    if exam_result_status:
        result_map[store_key] = exam_result_status
    else:
        result_map.pop(store_key, None)
        result_map.pop(registration_key, None)
    save_exam_results_for_year(year_value, result_map)

    if year_value in DF_CACHE and DF_CACHE[year_value] is not None and not DF_CACHE[year_value].empty and 'exam_result_status' in DF_CACHE[year_value].columns:
        DF_CACHE[year_value].loc[DF_CACHE[year_value]['registration_key'] == registration_key, 'exam_result_status'] = exam_result_status
    if int(year_value) == int(CURRENT_YEAR_NUMERIC) and df is not None and not df.empty and 'exam_result_status' in df.columns:
        df.loc[df['registration_key'] == registration_key, 'exam_result_status'] = exam_result_status

    write_staff_log(
        action='update_exam_result',
        outcome='success',
        username=session.get('staff_username', ''),
        detail=f"year={year_value} registration_key={registration_key} store_key={store_key} status={exam_result_status or 'cleared'}"
    )
    return jsonify({'success': True, 'message': 'บันทึกผลการสอบเรียบร้อยแล้ว'})


@app.route('/')
def index():
    current_year_thai = get_current_buddhist_year(numeric=False)
    return render_template(
        'index.html', 
        current_buddhist_year=current_year_thai
    )


@app.route('/pass-list')
def pass_list():
    current_year_thai = get_current_buddhist_year(numeric=False)
    current_year_numeric = CURRENT_YEAR_NUMERIC
    
    selected_year = normalize_year_value(request.args.get('year')) or current_year_numeric
    selected_level = request.args.get('level', '')
    selected_school = request.args.get('school', '')
    selected_group = request.args.get('group', '')
    selected_status = request.args.get('status', '')
    sort_by = request.args.get('sort_by', 'ordination')
    
    pass_results = []
    available_levels = []
    available_schools = []
    available_groups = []
    available_statuses = [status for status in RESULT_STATUS_OPTIONS if status]
    pass_summary = None
    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)
    
    year_df = get_df_for_year(selected_year)
    if year_df is not None and not year_df.empty:
        names_map = load_exam_names_for_year(selected_year)
        summary_df = year_df.copy()
        summary_df = summary_df.assign(
            summary_group=summary_df['group_name'].map(normalize_pass_summary_group)
        )

        if selected_level:
            summary_df = summary_df[summary_df['class_name'] == selected_level]
        
        if selected_school:
            summary_df = summary_df[summary_df['school_name'] == selected_school]
        
        if selected_group:
            summary_df = summary_df[summary_df['group_name'] == selected_group]

        if selected_level:
            pass_summary = build_pass_summary(summary_df, selected_level)

        pass_df = summary_df.copy()
        
        if selected_status:
            pass_df = pass_df[pass_df['exam_result_status'] == selected_status]
        
        if sort_by == 'name':
            pass_df = pass_df.sort_values(by='display_name', ascending=True)
        elif sort_by == 'ordination':
            pass_df = pass_df.assign(
                pansa_num=pd.to_numeric(pass_df.get('pansa_num', ''), errors='coerce').fillna(0).astype(int),
                age_num=pd.to_numeric(pass_df.get('age_num', ''), errors='coerce').fillna(0).astype(int),
                has_pansa=lambda df_: df_['pansa_num'] > 0,
                ordain_sort_key=pass_df['ordain_sort_key'].replace('', '99999999'),
                birth_sort_key=pass_df['birth_sort_key'].replace('', '99999999')
            ).sort_values(
                by=['has_pansa', 'pansa_num', 'ordain_sort_key', 'age_num', 'birth_sort_key', 'display_name'],
                ascending=[False, False, True, False, True, True]
            ).drop(columns=['has_pansa', 'age_num', 'ordain_sort_key', 'birth_sort_key'])
        elif sort_by == 'class_name':
            pass_df = pass_df.assign(
                class_order=pass_df['class_name'].map(
                    lambda class_name: CLASS_NAME_ORDER_INDEX.get(class_name, len(CLASS_NAME_ORDER))
                )
            ).sort_values(by=['class_order', 'display_name'], ascending=[True, True]).drop(columns=['class_order'])
        elif sort_by == 'school_name':
            pass_df = pass_df.sort_values(by='school_name', ascending=True)
        elif sort_by == 'group_name':
            pass_df = pass_df.sort_values(by='group_name', ascending=True)
        elif sort_by == 'status':
            pass_df = pass_df.sort_values(by='exam_result_status', ascending=True)
        else:
            pass_df = pass_df.sort_values(by='sequence_thai', ascending=True)
        
        available_levels = order_class_names(year_df['class_name'].unique().tolist())
        available_schools = sorted(year_df['school_name'].unique().tolist())
        available_groups = sorted(year_df['group_name'].unique().tolist())
        
        for _, row in pass_df.iterrows():
            lookup_key = row.get('result_key') or row.get('registration_key')
            exam_name = names_map.get(str(lookup_key or ''), '')
            pass_results.append({
                'name': row['display_name'],
                'exam_name': exam_name,
                'class_name': row['class_name'],
                'sequence': row['sequence_thai'],
                'age': row.get('age_thai', '-'),
                'pansa': row.get('pansa_thai', '-'),
                'school_name': to_thai_digits(row['school_name']),
                'group_name': to_thai_digits(row['group_name']),
                'result_status': row['exam_result_status']
            })
    
    return render_template(
        'pass_list.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=current_year_numeric,
        selected_year=selected_year,
        selected_level=selected_level,
        selected_school=selected_school,
        selected_group=selected_group,
        selected_status=selected_status,
        sort_by=sort_by,
        pass_results=pass_results,
        pass_summary=pass_summary,
        available_years=available_years,
        available_levels=available_levels,
        available_schools=available_schools,
        available_groups=available_groups,
        available_statuses=available_statuses
    )


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
        staff_accounts=accounts
    )


@app.route('/staff/statistics')
def staff_statistics():
    current_year_thai = get_current_buddhist_year(numeric=False)
    selected_year = get_selected_year()
    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)
    stats = get_statistics(year=selected_year)
    return render_template(
        'statistics.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=selected_year,
        available_years=available_years,
        statistics=stats,
        department_levels=DEPARTMENT_LEVELS
    )


@app.route('/staff/statistics/tham')
def staff_statistics_tham():
    current_year_thai = get_current_buddhist_year(numeric=False)
    selected_year = get_selected_year()
    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)
    level_ids = []
    for subsection in DEPARTMENT_LEVELS.get('tham', {}).get('subsections', {}).values():
        level_ids.extend(subsection.get('levels', []) or [])
    stats = get_statistics(level_ids=level_ids, year=selected_year)
    return render_template(
        'statistics_department.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=selected_year,
        available_years=available_years,
        statistics=stats,
        department_key='tham',
        department=DEPARTMENT_LEVELS['tham']
    )


@app.route('/staff/statistics/tham/<subsection>')
def staff_statistics_tham_subsection(subsection):
    current_year_thai = get_current_buddhist_year(numeric=False)
    selected_year = get_selected_year()
    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)
    if subsection not in DEPARTMENT_LEVELS['tham']['subsections']:
        return redirect(url_for('staff_statistics_tham'))
    
    subsection_data = DEPARTMENT_LEVELS['tham']['subsections'][subsection]
    stats = get_statistics(subsection_data['levels'], year=selected_year)
    
    return render_template(
        'statistics_subsection.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=selected_year,
        available_years=available_years,
        department_key='tham',
        department=DEPARTMENT_LEVELS['tham'],
        subsection_key=subsection,
        subsection=subsection_data,
        statistics=stats
    )


@app.route('/staff/statistics/bali')
def staff_statistics_bali():
    current_year_thai = get_current_buddhist_year(numeric=False)
    selected_year = get_selected_year()
    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)
    level_ids = []
    for subsection in DEPARTMENT_LEVELS.get('bali', {}).get('subsections', {}).values():
        level_ids.extend(subsection.get('levels', []) or [])
    stats = get_statistics(level_ids=level_ids, year=selected_year)
    return render_template(
        'statistics_department.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=selected_year,
        available_years=available_years,
        statistics=stats,
        department_key='bali',
        department=DEPARTMENT_LEVELS['bali']
    )


@app.route('/staff/statistics/bali/<subsection>')
def staff_statistics_bali_subsection(subsection):
    current_year_thai = get_current_buddhist_year(numeric=False)
    selected_year = get_selected_year()
    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)
    if subsection not in DEPARTMENT_LEVELS['bali']['subsections']:
        return redirect(url_for('staff_statistics_bali'))
    
    subsection_data = DEPARTMENT_LEVELS['bali']['subsections'][subsection]
    stats = get_statistics(subsection_data['levels'], year=selected_year)
    
    return render_template(
        'statistics_subsection.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=selected_year,
        available_years=available_years,
        department_key='bali',
        department=DEPARTMENT_LEVELS['bali'],
        subsection_key=subsection,
        subsection=subsection_data,
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
def api_get_statistics():
    selected_year = get_selected_year()
    return jsonify({'success': True, 'statistics': get_statistics(year=selected_year)})


@app.route('/api/statistics/<department>/<subsection>', methods=['GET'])
def api_get_department_statistics(department, subsection):
    if department not in DEPARTMENT_LEVELS:
        return jsonify({'success': False, 'message': 'Invalid department'}), 400
    if subsection not in DEPARTMENT_LEVELS[department]['subsections']:
        return jsonify({'success': False, 'message': 'Invalid subsection'}), 400
    
    level_ids = DEPARTMENT_LEVELS[department]['subsections'][subsection]['levels']
    selected_year = get_selected_year()
    return jsonify({'success': True, 'statistics': get_statistics(level_ids, year=selected_year)})


@app.route('/staff/summary/bali')
def staff_bali_summary():
    current_year_thai = get_current_buddhist_year(numeric=False)
    selected_year = get_selected_year()
    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)
    class_names = []
    for subsection in DEPARTMENT_LEVELS.get('bali', {}).get('subsections', {}).values():
        for level_id in subsection.get('levels', []):
            class_name = LEVEL_ID_MAP.get(str(level_id), '')
            if class_name:
                class_names.append(class_name)
    class_names = order_class_names(sorted(set(class_names)))

    summary = None
    year_df = get_df_for_year(selected_year)
    if year_df is not None and not year_df.empty and class_names:
        summary_df = year_df.copy()
        summary_df = summary_df.assign(
            summary_group=summary_df['group_name'].map(normalize_pass_summary_group)
        )
        summary_df = summary_df[summary_df['class_name'].isin(class_names)]

        classes_data = {}
        for class_name in class_names:
            class_df = summary_df[summary_df['class_name'] == class_name]
            group_rows = {}
            total_sent = 0
            total_active = 0
            total_pass = 0
            for group_name in PASS_SUMMARY_GROUP_ORDER:
                group_df = class_df[class_df['summary_group'] == group_name]
                sent_count = len(group_df)
                active_count = len(group_df[~group_df['exam_result_status'].isin(PASS_SUMMARY_ABSENT_STATUSES)])
                pass_count = len(group_df[group_df['exam_result_status'].isin(PASS_SUMMARY_PASS_STATUSES)])
                group_rows[group_name] = {
                    'ส่งสอบ': int(sent_count),
                    'คงสอบ': int(active_count),
                    'สอบได้': int(pass_count)
                }
                total_sent += sent_count
                total_active += active_count
                total_pass += pass_count

            classes_data[class_name] = {
                'groups': group_rows,
                'total': {
                    'ส่งสอบ': int(total_sent),
                    'คงสอบ': int(total_active),
                    'สอบได้': int(total_pass)
                }
            }

        grand_total = {}
        total_sent = 0
        total_active = 0
        total_pass = 0
        for group_name in PASS_SUMMARY_GROUP_ORDER:
            group_df = summary_df[summary_df['summary_group'] == group_name]
            sent_count = len(group_df)
            active_count = len(group_df[~group_df['exam_result_status'].isin(PASS_SUMMARY_ABSENT_STATUSES)])
            pass_count = len(group_df[group_df['exam_result_status'].isin(PASS_SUMMARY_PASS_STATUSES)])
            grand_total[group_name] = {
                'ส่งสอบ': int(sent_count),
                'คงสอบ': int(active_count),
                'สอบได้': int(pass_count)
            }
            total_sent += sent_count
            total_active += active_count
            total_pass += pass_count

        grand_total['total'] = {
            'ส่งสอบ': int(total_sent),
            'คงสอบ': int(total_active),
            'สอบได้': int(total_pass)
        }

        group_descriptions = {}
        if isinstance(bali_summary_data, dict):
            group_descriptions = bali_summary_data.get('group_descriptions') or {}

        summary = {
            'group_descriptions': group_descriptions,
            'classes': classes_data,
            'grand_total': grand_total
        }

    return render_template(
        'bali_summary.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=selected_year,
        available_years=available_years,
        summary=summary
    )


def build_school_summary(department_key, selected_year):
    class_names = []
    for subsection in DEPARTMENT_LEVELS.get(department_key, {}).get('subsections', {}).values():
        for level_id in subsection.get('levels', []):
            class_name = LEVEL_ID_MAP.get(str(level_id), '')
            if class_name:
                class_names.append(class_name)
    class_names = order_class_names(sorted(set(class_names)))

    year_df = get_df_for_year(selected_year)
    if year_df is None or year_df.empty or not class_names:
        return None

    summary_df = year_df.copy()
    summary_df = summary_df[summary_df['class_name'].isin(class_names)]

    def normalize_school_name(value):
        name = (str(value) if value is not None else '').strip()
        return name if name else 'ไม่ระบุหน่วยงาน'

    summary_df = summary_df.assign(
        school_name_norm=summary_df['school_name'].apply(normalize_school_name)
    )

    classes_data = {}
    for class_name in class_names:
        class_df = summary_df[summary_df['class_name'] == class_name]
        unit_rows_list = []
        for school_name in sorted(class_df['school_name_norm'].unique().tolist()):
            unit_df = class_df[class_df['school_name_norm'] == school_name]
            sent_count = len(unit_df)
            active_count = len(unit_df[~unit_df['exam_result_status'].isin(PASS_SUMMARY_ABSENT_STATUSES)])
            pass_count = len(unit_df[unit_df['exam_result_status'].isin(PASS_SUMMARY_PASS_STATUSES)])
            unit_rows_list.append({
                'name': school_name,
                'ส่งสอบ': int(sent_count),
                'คงสอบ': int(active_count),
                'สอบได้': int(pass_count)
            })
        unit_rows_list = sorted(unit_rows_list, key=lambda row: (-row.get('ส่งสอบ', 0), row.get('name', '')))

        total_sent = sum(row['ส่งสอบ'] for row in unit_rows_list)
        total_active = sum(row['คงสอบ'] for row in unit_rows_list)
        total_pass = sum(row['สอบได้'] for row in unit_rows_list)

        classes_data[class_name] = {
            'units': unit_rows_list,
            'total': {
                'ส่งสอบ': int(total_sent),
                'คงสอบ': int(total_active),
                'สอบได้': int(total_pass)
            }
        }

    grand_unit_rows = {}
    for school_name in sorted(summary_df['school_name_norm'].unique().tolist()):
        unit_df = summary_df[summary_df['school_name_norm'] == school_name]
        sent_count = len(unit_df)
        active_count = len(unit_df[~unit_df['exam_result_status'].isin(PASS_SUMMARY_ABSENT_STATUSES)])
        pass_count = len(unit_df[unit_df['exam_result_status'].isin(PASS_SUMMARY_PASS_STATUSES)])
        grand_unit_rows[school_name] = {
            'name': school_name,
            'ส่งสอบ': int(sent_count),
            'คงสอบ': int(active_count),
            'สอบได้': int(pass_count)
        }
    grand_units_list = sorted(grand_unit_rows.values(), key=lambda row: (-row.get('ส่งสอบ', 0), row.get('name', '')))

    total_sent = sum(row['ส่งสอบ'] for row in grand_units_list)
    total_active = sum(row['คงสอบ'] for row in grand_units_list)
    total_pass = sum(row['สอบได้'] for row in grand_units_list)

    return {
        'classes': classes_data,
        'grand_total': {
            'units': grand_units_list,
            'total': {
                'ส่งสอบ': int(total_sent),
                'คงสอบ': int(total_active),
                'สอบได้': int(total_pass)
            }
        }
    }


@app.route('/staff/summary/bali/schools')
def staff_bali_school_summary():
    current_year_thai = get_current_buddhist_year(numeric=False)
    selected_year = get_selected_year()
    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)

    summary = build_school_summary('bali', selected_year)

    return render_template(
        'bali_school_summary.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=selected_year,
        available_years=available_years,
        summary=summary
    )


@app.route('/staff/summary/tham')
def staff_tham_summary():
    current_year_thai = get_current_buddhist_year(numeric=False)
    selected_year = get_selected_year()
    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)

    class_names = []
    for subsection in DEPARTMENT_LEVELS.get('tham', {}).get('subsections', {}).values():
        for level_id in subsection.get('levels', []):
            class_name = LEVEL_ID_MAP.get(str(level_id), '')
            if class_name:
                class_names.append(class_name)
    class_names = order_class_names(sorted(set(class_names)))

    summary = None
    year_df = get_df_for_year(selected_year)
    if year_df is not None and not year_df.empty and class_names:
        summary_df = year_df.copy()
        summary_df = summary_df.assign(
            summary_group=summary_df['group_name'].map(normalize_pass_summary_group)
        )
        summary_df = summary_df[summary_df['class_name'].isin(class_names)]

        classes_data = {}
        for class_name in class_names:
            class_df = summary_df[summary_df['class_name'] == class_name]
            group_rows = {}
            total_sent = 0
            total_active = 0
            total_pass = 0
            for group_name in PASS_SUMMARY_GROUP_ORDER:
                group_df = class_df[class_df['summary_group'] == group_name]
                sent_count = len(group_df)
                active_count = len(group_df[~group_df['exam_result_status'].isin(PASS_SUMMARY_ABSENT_STATUSES)])
                pass_count = len(group_df[group_df['exam_result_status'].isin(PASS_SUMMARY_PASS_STATUSES)])
                group_rows[group_name] = {
                    'ส่งสอบ': int(sent_count),
                    'คงสอบ': int(active_count),
                    'สอบได้': int(pass_count)
                }
                total_sent += sent_count
                total_active += active_count
                total_pass += pass_count

            classes_data[class_name] = {
                'groups': group_rows,
                'total': {
                    'ส่งสอบ': int(total_sent),
                    'คงสอบ': int(total_active),
                    'สอบได้': int(total_pass)
                }
            }

        grand_total = {}
        total_sent = 0
        total_active = 0
        total_pass = 0
        for group_name in PASS_SUMMARY_GROUP_ORDER:
            group_df = summary_df[summary_df['summary_group'] == group_name]
            sent_count = len(group_df)
            active_count = len(group_df[~group_df['exam_result_status'].isin(PASS_SUMMARY_ABSENT_STATUSES)])
            pass_count = len(group_df[group_df['exam_result_status'].isin(PASS_SUMMARY_PASS_STATUSES)])
            grand_total[group_name] = {
                'ส่งสอบ': int(sent_count),
                'คงสอบ': int(active_count),
                'สอบได้': int(pass_count)
            }
            total_sent += sent_count
            total_active += active_count
            total_pass += pass_count

        grand_total['total'] = {
            'ส่งสอบ': int(total_sent),
            'คงสอบ': int(total_active),
            'สอบได้': int(total_pass)
        }

        group_descriptions = {}
        if isinstance(bali_summary_data, dict):
            group_descriptions = bali_summary_data.get('group_descriptions') or {}

        summary = {
            'group_descriptions': group_descriptions,
            'classes': classes_data,
            'grand_total': grand_total
        }

    return render_template(
        'tham_summary.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=selected_year,
        available_years=available_years,
        summary=summary
    )


@app.route('/staff/summary/tham/schools')
def staff_tham_school_summary():
    current_year_thai = get_current_buddhist_year(numeric=False)
    selected_year = get_selected_year()
    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)

    summary = build_school_summary('tham', selected_year)

    return render_template(
        'tham_school_summary.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=selected_year,
        available_years=available_years,
        summary=summary
    )


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
    selected_year = get_selected_year()
    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)
    status_options = [status for status in RESULT_STATUS_OPTIONS if status]
    return render_template(
        'manage_results.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=selected_year,
        available_years=available_years,
        result_status_options=status_options
    )


EXCEL_IMPORT_STATUS_MAP = {
    '': 'สอบตก',
    'ผ่าน': 'สอบได้',
    'ไม่ผ่าน': 'สอบตก',
    'สอบตก': 'สอบตก',
    'ขาดสอบ': 'ขาดสอบ',
    'ขาดสิทธิ์': 'ขาดสิทธิ์',
    'สอบได้': 'สอบได้',
    'สอบซ่อม': 'สอบซ่อม',
    'สอบซ่อมได้': 'สอบซ่อมได้',
}


def excel_normalize_text(value):
    if value is None:
        return ''
    if pd.isna(value):
        return ''
    return str(value).strip()


def excel_build_display_name(row):
    first_name = excel_normalize_text(row.get('ชื่อ'))
    pali_name = excel_normalize_text(row.get('ฉายา'))
    last_name = excel_normalize_text(row.get('นามสกุล'))

    if first_name and pali_name and last_name:
        return f'{first_name} {pali_name} ({last_name})'
    if first_name and last_name:
        return f'{first_name} {last_name}'
    if first_name and pali_name:
        return f'{first_name} {pali_name}'
    if first_name:
        return first_name

    fallback_columns = [
        'ชื่อ-ฉายา (สกุล)',
        'ชื่อ-ฉายา(สกุล)',
        'ชื่อ-ฉายา',
        'ชื่อฉายา',
        'ชื่อ-นามสกุล',
        'display_name',
        'ชื่อ',
    ]
    for col in fallback_columns:
        if col in row.index:
            value = excel_normalize_text(row.get(col))
            if value:
                return value
    if len(row.index) == 1:
        value = excel_normalize_text(row.iloc[0])
        if value:
            return value
    return ''


def excel_resolve_sheet_status(row):
    if 'ผลการสอบ' in row.index:
        return excel_normalize_text(row.get('ผลการสอบ'))

    if 'ผลสอบ' in row.index or 'ผลสอบซ่อม' in row.index:
        result_1 = excel_normalize_text(row.get('ผลสอบ'))
        result_2 = excel_normalize_text(row.get('ผลสอบซ่อม'))

        if result_1 == 'สอบซ่อม' and result_2 == 'ผ่าน':
            return 'สอบซ่อมได้'
        if result_1 == 'สอบซ่อม':
            return 'สอบซ่อม'
        if result_1:
            return result_1
        if result_2 == 'ผ่าน':
            return 'สอบได้'
        return result_2

    result_1 = excel_normalize_text(row.get('ผลสอบ 1'))
    result_2 = excel_normalize_text(row.get('ผลสอบ 2'))

    if result_1 == 'สอบซ่อม' and result_2 == 'ผ่าน':
        return 'สอบซ่อมได้'
    if result_1 == 'สอบซ่อม':
        return 'สอบซ่อม'
    if result_1:
        return result_1
    if result_2 == 'ผ่าน':
        return 'สอบได้'
    return result_2


def excel_build_name_candidates(row):
    first_name = excel_normalize_text(row.get('ชื่อ'))
    pali_name = excel_normalize_text(row.get('ฉายา'))
    last_name = excel_normalize_text(row.get('นามสกุล'))

    candidates = []
    if first_name and pali_name and last_name:
        candidates.append(f'{first_name} {pali_name} ({last_name})')
    if first_name and pali_name:
        candidates.append(f'{first_name} {pali_name}')
    if first_name and last_name:
        candidates.append(f'{first_name} {last_name}')
        candidates.append(f'{first_name} ({last_name})')
    if first_name:
        candidates.append(first_name)

    seen = {}
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen[candidate] = True
    return list(seen.keys())


def excel_build_base_name_key_from_row(row):
    first_name_raw = excel_normalize_text(row.get('ชื่อ'))
    last_name = excel_normalize_text(row.get('นามสกุล'))
    if not first_name_raw or not last_name:
        return ''
    first_name = strip_thai_title_prefix(first_name_raw)
    return normalize_name_key(f'{first_name}{last_name}')


def get_excel_import_preview_file(token):
    return os.path.join(RESULTS_DATA_DIR, 'import_previews', f'{token}.json')


def save_excel_import_preview(token, payload):
    preview_file = get_excel_import_preview_file(token)
    write_json_atomic(preview_file, payload)


def load_excel_import_preview(token):
    preview_file = get_excel_import_preview_file(token)
    if not os.path.exists(preview_file):
        return None
    try:
        with open(preview_file, 'r', encoding='utf-8') as fp:
            payload = json.load(fp)
        return payload if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def delete_excel_import_preview(token):
    preview_file = get_excel_import_preview_file(token)
    try:
        if os.path.exists(preview_file):
            os.remove(preview_file)
    except OSError:
        pass


@app.route('/manage-results/import-excel', methods=['GET'])
@staff_login_required()
def staff_import_excel():
    current_year_thai = get_current_buddhist_year(numeric=False)
    available_years = list_available_years()
    year_value = normalize_year_value(request.args.get('year')) or get_selected_year()
    if year_value not in available_years:
        available_years.append(year_value)
        available_years = sorted(available_years)
    fixed_status_options = ['สอบได้', 'สอบตก', 'ขาดสอบ', 'ขาดสิทธิ์', 'สอบซ่อม', 'สอบซ่อมได้']
    return render_template(
        'import_excel.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=year_value,
        available_years=available_years,
        available_classes=CLASS_NAME_ORDER,
        default_sheet='',
        fixed_status_options=fixed_status_options,
        selected_import_mode='normal',
        selected_fixed_status='สอบได้'
    )


@app.route('/manage-results/import-excel/preview', methods=['POST'])
@staff_login_required()
def staff_import_excel_preview():
    year_value = normalize_year_value(request.form.get('year')) or get_selected_year()
    class_name = str(request.form.get('class_name') or '').strip()
    sheet_name = str(request.form.get('sheet_name') or '').strip()
    import_mode = str(request.form.get('import_mode') or 'normal').strip() or 'normal'
    fixed_status = str(request.form.get('fixed_status') or 'สอบได้').strip() or 'สอบได้'
    current_year_thai = get_current_buddhist_year(numeric=False)
    available_years = list_available_years()
    if year_value not in available_years:
        available_years.append(year_value)
        available_years = sorted(available_years)
    fixed_status_options = ['สอบได้', 'สอบตก', 'ขาดสอบ', 'ขาดสิทธิ์', 'สอบซ่อม', 'สอบซ่อมได้']

    def render_error(message):
        return render_template(
            'import_excel.html',
            current_buddhist_year=current_year_thai,
            current_year_numeric=CURRENT_YEAR_NUMERIC,
            selected_year=year_value,
            available_years=available_years,
            available_classes=CLASS_NAME_ORDER,
            selected_class=class_name,
            selected_sheet=sheet_name,
            default_sheet='',
            fixed_status_options=fixed_status_options,
            selected_import_mode=import_mode,
            selected_fixed_status=fixed_status,
            error_message=message
        )

    uploaded = request.files.get('excel_file')
    if not uploaded or not getattr(uploaded, 'filename', ''):
        return render_error('กรุณาเลือกไฟล์ Excel'), 400
    filename = str(uploaded.filename)
    if not filename.lower().endswith('.xlsx'):
        return render_error('รองรับเฉพาะไฟล์ .xlsx'), 400
    if class_name not in CLASS_NAME_ORDER:
        return render_error('ชั้นเรียนไม่ถูกต้อง'), 400
    if not sheet_name:
        return render_error('กรุณาระบุชื่อชีทในไฟล์'), 400
    if import_mode not in {'normal', 'list_only'}:
        return render_error('โหมดไฟล์ไม่ถูกต้อง'), 400
    if import_mode == 'list_only' and fixed_status not in fixed_status_options:
        return render_error('สถานะที่เลือกไม่ถูกต้อง'), 400

    token = uuid.uuid4().hex
    temp_dir = os.path.join(RESULTS_DATA_DIR, 'tmp_uploads')
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f'{token}.xlsx')
    uploaded.save(temp_path)

    try:
        excel_df = pd.read_excel(temp_path, sheet_name=sheet_name).fillna('')
    except Exception as e:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return render_error(f'อ่านไฟล์ไม่สำเร็จ: {e}'), 400

    try:
        os.remove(temp_path)
    except OSError:
        pass

    if excel_df is None or excel_df.empty:
        return render_error('ชีทนี้ไม่มีข้อมูล'), 400

    excel_df['display_name'] = excel_df.apply(excel_build_display_name, axis=1)
    if import_mode == 'list_only':
        excel_df['resolved_result'] = fixed_status
    else:
        excel_df['resolved_result'] = excel_df.apply(excel_resolve_sheet_status, axis=1)

    unknown_statuses = sorted(
        {
            excel_normalize_text(value)
            for value in excel_df['resolved_result'].tolist()
            if excel_normalize_text(value) not in EXCEL_IMPORT_STATUS_MAP
        }
    )
    if unknown_statuses:
        return render_error(f'พบค่าผลการสอบที่ไม่รู้จัก: {unknown_statuses}'), 400

    app_df = get_df_for_year(year_value)
    key_column = 'result_key' if 'result_key' in app_df.columns else 'registration_key'
    class_df = app_df[app_df['class_name'] == class_name][['display_name', key_column]].copy()
    duplicate_names = class_df[class_df.duplicated('display_name', keep=False)]['display_name'].tolist()
    if duplicate_names:
        return render_error(f'พบชื่อซ้ำในข้อมูลระบบของชั้น {class_name}: {sorted(set(duplicate_names))}'), 400

    registration_map = dict(zip(class_df['display_name'], class_df[key_column]))
    normalized_registration_map = {}
    base_registration_map = {}
    last_name_map = {}
    for _, class_row in class_df.iterrows():
        normalized_name = normalize_name_key(class_row['display_name'])
        if normalized_name and normalized_name not in normalized_registration_map:
            normalized_registration_map[normalized_name] = class_row[key_column]
        base_name_key = build_base_name_key_from_display_name(class_row['display_name'])
        if base_name_key:
            if base_name_key in base_registration_map and base_registration_map[base_name_key] != class_row[key_column]:
                base_registration_map[base_name_key] = ''
            elif base_name_key not in base_registration_map:
                base_registration_map[base_name_key] = class_row[key_column]
        last_name_key = normalize_name_key(extract_last_name_from_display_name(class_row['display_name']))
        if last_name_key:
            if last_name_key in last_name_map and last_name_map[last_name_key] != class_row[key_column]:
                last_name_map[last_name_key] = ''
            elif last_name_key not in last_name_map:
                last_name_map[last_name_key] = class_row[key_column]

    updates = []
    status_summary = {}
    pending_items = {}
    pending_names = []

    for idx, row in excel_df.iterrows():
        display_name = str(row.get('display_name') or '').strip()
        if not display_name:
            continue

        match_key = registration_map.get(display_name, '')
        if not match_key:
            for candidate_name in excel_build_name_candidates(row):
                match_key = registration_map.get(candidate_name, '')
                if match_key:
                    break
                normalized_candidate = normalize_name_key(candidate_name)
                match_key = normalized_registration_map.get(normalized_candidate, '')
                if match_key:
                    break
        if not match_key:
            base_key = excel_build_base_name_key_from_row(row)
            if base_key:
                candidate_key = base_registration_map.get(base_key, '')
                if candidate_key:
                    match_key = candidate_key
        if not match_key:
            last_name_key = normalize_name_key(excel_normalize_text(row.get('นามสกุล')))
            if last_name_key:
                candidate_key = last_name_map.get(last_name_key, '')
                if candidate_key:
                    match_key = candidate_key

        source_status = excel_normalize_text(row.get('resolved_result'))
        mapped_status = EXCEL_IMPORT_STATUS_MAP.get(source_status, '')

        if match_key:
            updates.append({'key': match_key, 'status': mapped_status, 'display_name': display_name})
            status_summary[mapped_status] = status_summary.get(mapped_status, 0) + 1
        else:
            name_key = normalize_name_key(display_name)
            pending_key = f'{class_name}|{name_key or display_name}|{sheet_name}|{idx}'
            pending_items[pending_key] = {
                'class_name': class_name,
                'display_name': display_name,
                'display_name_key': name_key,
                'base_name_key': excel_build_base_name_key_from_row(row),
                'exam_result_status': mapped_status,
                'source_status': source_status,
                'sheet': sheet_name,
                'workbook': filename,
                'imported_at': datetime.utcnow().isoformat(timespec='seconds') + 'Z'
            }
            pending_names.append(display_name)

    preview_payload = {
        'token': token,
        'year': int(year_value),
        'class_name': class_name,
        'sheet_name': sheet_name,
        'filename': filename,
        'import_mode': import_mode,
        'fixed_status': fixed_status if import_mode == 'list_only' else '',
        'total_rows': int(len(excel_df)),
        'matched_rows': int(len(updates)),
        'pending_rows': int(len(pending_items)),
        'status_summary': status_summary,
        'pending_names': pending_names[:200],
        'updates': updates,
        'pending_items': pending_items,
        'created_at': datetime.utcnow().isoformat(timespec='seconds') + 'Z'
    }
    save_excel_import_preview(token, preview_payload)
    write_staff_log(
        action='import_excel_preview',
        outcome='success',
        username=session.get('staff_username', ''),
        detail=f'year={year_value}|class={class_name}|sheet={sheet_name}|matched={len(updates)}|pending={len(pending_items)}'
    )

    current_year_thai = get_current_buddhist_year(numeric=False)
    available_years = list_available_years()
    if year_value not in available_years:
        available_years.append(year_value)
        available_years = sorted(available_years)
    return render_template(
        'import_excel_preview.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=year_value,
        available_years=available_years,
        preview=preview_payload
    )


@app.route('/manage-results/import-excel/confirm', methods=['POST'])
@staff_login_required()
def staff_import_excel_confirm():
    global df
    token = str(request.form.get('token') or '').strip()
    preview = load_excel_import_preview(token)
    if not preview:
        return jsonify({'success': False, 'message': 'ไม่พบข้อมูลพรีวิว หรือพรีวิวหมดอายุ'}), 400

    year_value = int(preview.get('year') or get_selected_year())
    updates = preview.get('updates') or []
    pending_items = preview.get('pending_items') or {}

    result_map = load_exam_results_for_year(year_value)
    names_map = load_exam_names_for_year(year_value)

    updated_count = 0
    for item in updates:
        if not isinstance(item, dict):
            continue
        key = str(item.get('key') or '').strip()
        status_value = str(item.get('status') or '').strip()
        display_name = str(item.get('display_name') or '').strip()
        if not key:
            continue
        result_map[key] = status_value
        if display_name:
            names_map[key] = display_name
        updated_count += 1

    write_json_atomic(get_exam_results_file(year_value), result_map)
    write_json_atomic(get_exam_names_file(year_value), names_map)

    pending_payload = load_pending_exam_results_for_year(year_value)
    pending_payload.setdefault('version', 1)
    pending_payload.setdefault('items', {})
    pending_payload['items'].update(pending_items if isinstance(pending_items, dict) else {})
    save_pending_exam_results_for_year(year_value, pending_payload)

    if int(year_value) in DF_CACHE and isinstance(DF_CACHE[int(year_value)], pd.DataFrame):
        DF_CACHE[int(year_value)] = apply_exam_results(DF_CACHE[int(year_value)].copy(), year=year_value)
    if int(year_value) == int(CURRENT_YEAR_NUMERIC) and isinstance(df, pd.DataFrame):
        df = apply_exam_results(df.copy(), year=year_value)

    delete_excel_import_preview(token)
    write_staff_log(
        action='import_excel_confirm',
        outcome='success',
        username=session.get('staff_username', ''),
        detail=f'year={year_value}|class={preview.get("class_name")}|sheet={preview.get("sheet_name")}|updated={updated_count}|pending={len(pending_items)}'
    )
    return redirect(url_for('manage_results', year=year_value))


def build_manual_registration_key(display_name, class_name):
    digest = hashlib.sha1(f'{display_name}|{class_name}'.encode('utf-8')).hexdigest()[:16]
    return f'manual={digest}|class={class_name}'


@app.route('/manage-results/manual-add', methods=['GET', 'POST'])
@staff_login_required()
def staff_manual_add():
    current_year_thai = get_current_buddhist_year(numeric=False)
    available_years = list_available_years()
    fixed_year = normalize_year_value(request.values.get('year')) or get_selected_year()
    if fixed_year not in available_years:
        available_years.append(fixed_year)
        available_years = sorted(available_years)

    class_name = str(request.values.get('class_name') or '').strip() or 'น.ธ.ตรี'
    if class_name not in CLASS_NAME_ORDER:
        class_name = 'น.ธ.ตรี'

    names_text = str(request.values.get('names') or '').replace('\r\n', '\n')
    success_message = ''
    error_message = ''
    added_names = []
    skipped_names = []
    manual_entries = []

    def normalize_optional_text(value):
        cleaned = str(value or '').strip()
        return cleaned if cleaned else None

    def invalidate_year_cache(year_value):
        DF_CACHE.pop(int(year_value), None)
        DF_CACHE_META.pop(int(year_value), None)
        if int(year_value) == int(CURRENT_YEAR_NUMERIC):
            global df
            df = None

    def build_display_name_key_map(year_value, target_class):
        year_df = get_df_for_year(year_value)
        if year_df is None or year_df.empty:
            return {}
        key_column = 'result_key' if 'result_key' in year_df.columns else 'registration_key'
        class_df = year_df[year_df['class_name'] == target_class][['display_name', key_column]].copy()
        class_df[key_column] = class_df[key_column].astype(str)
        return dict(zip(class_df['display_name'].astype(str), class_df[key_column]))

    manual_map = load_manual_registrations_for_year(fixed_year)
    if not isinstance(manual_map, dict):
        manual_map = {}

    for _, entry in manual_map.items():
        if isinstance(entry, dict):
            if 'school_name' not in entry or entry.get('school_name') == '':
                entry['school_name'] = None
            if 'group_name' not in entry or entry.get('group_name') == '':
                entry['group_name'] = None

    if request.method == 'POST':
        action = str(request.form.get('action') or '').strip() or 'add'

        if action == 'delete':
            delete_key = str(request.form.get('manual_key') or '').strip()
            if not delete_key or delete_key not in manual_map:
                error_message = 'ไม่พบรายการที่ต้องการลบ'
            else:
                manual_map.pop(delete_key, None)
                write_json_atomic(get_manual_registrations_file(fixed_year), manual_map)

                result_map = load_exam_results_for_year(fixed_year)
                if isinstance(result_map, dict) and delete_key in result_map:
                    result_map.pop(delete_key, None)
                    write_json_atomic(get_exam_results_file(fixed_year), result_map)

                names_map = load_exam_names_for_year(fixed_year)
                if isinstance(names_map, dict) and delete_key in names_map:
                    names_map.pop(delete_key, None)
                    write_json_atomic(get_exam_names_file(fixed_year), names_map)

                invalidate_year_cache(fixed_year)
                write_staff_log(
                    action='manual_delete',
                    outcome='success',
                    username=session.get('staff_username', ''),
                    detail=f'year={fixed_year}|key={delete_key}'
                )
                success_message = 'ลบรายการสำเร็จ'

        elif action == 'update':
            old_key = str(request.form.get('manual_key') or '').strip()
            new_display_name = str(request.form.get('display_name') or '').strip()
            new_class_name = str(request.form.get('new_class_name') or '').strip() or class_name
            new_school_name = normalize_optional_text(request.form.get('school_name'))
            new_group_name = normalize_optional_text(request.form.get('group_name'))

            if not old_key or old_key not in manual_map:
                error_message = 'ไม่พบรายการที่ต้องการแก้ไข'
            elif not new_display_name:
                error_message = 'กรุณากรอกชื่อให้ถูกต้อง'
            elif new_class_name not in CLASS_NAME_ORDER:
                error_message = 'ชั้นเรียนไม่ถูกต้อง'
            else:
                display_name_key_map = build_display_name_key_map(fixed_year, new_class_name)
                existing_key = str(display_name_key_map.get(new_display_name) or '')
                if existing_key and existing_key != old_key:
                    error_message = 'มีชื่อซ้ำอยู่แล้วในข้อมูลของชั้นนี้'
                else:
                    new_key = build_manual_registration_key(new_display_name, new_class_name)
                    if new_key in manual_map and new_key != old_key:
                        error_message = 'รายการนี้มีอยู่แล้ว (key ซ้ำ)'
                    else:
                        entry = manual_map.get(old_key) if isinstance(manual_map.get(old_key), dict) else {}
                        if not isinstance(entry, dict):
                            entry = {}

                        entry['display_name'] = new_display_name
                        entry['class_name'] = new_class_name
                        entry['sequence'] = str(entry.get('sequence') or '')
                        entry['school_name'] = new_school_name
                        entry['group_name'] = new_group_name
                        entry['reg_status'] = 'manual'

                        if new_key != old_key:
                            manual_map.pop(old_key, None)
                            manual_map[new_key] = entry

                            result_map = load_exam_results_for_year(fixed_year)
                            if isinstance(result_map, dict) and old_key in result_map:
                                result_map[new_key] = result_map.pop(old_key)
                                write_json_atomic(get_exam_results_file(fixed_year), result_map)

                            names_map = load_exam_names_for_year(fixed_year)
                            if isinstance(names_map, dict) and old_key in names_map:
                                names_map[new_key] = names_map.pop(old_key)
                                write_json_atomic(get_exam_names_file(fixed_year), names_map)
                        else:
                            manual_map[old_key] = entry

                        write_json_atomic(get_manual_registrations_file(fixed_year), manual_map)
                        invalidate_year_cache(fixed_year)
                        write_staff_log(
                            action='manual_update',
                            outcome='success',
                            username=session.get('staff_username', ''),
                            detail=f'year={fixed_year}|old_key={old_key}|new_key={new_key}|class={new_class_name}'
                        )
                        success_message = 'บันทึกการแก้ไขสำเร็จ'

        else:
            raw_names = [line.strip() for line in names_text.split('\n')]
            deduped = []
            seen = set()
            for name in raw_names:
                if not name:
                    continue
                if name in seen:
                    continue
                seen.add(name)
                deduped.append(name)

            if not deduped:
                error_message = 'กรุณากรอกรายชื่ออย่างน้อย 1 รายชื่อ (ขึ้นบรรทัดใหม่ 1 คน)'
            else:
                display_name_key_map = build_display_name_key_map(fixed_year, class_name)

                for display_name in deduped:
                    existing_key = str(display_name_key_map.get(display_name) or '')
                    if existing_key:
                        skipped_names.append(display_name)
                        continue

                    key = build_manual_registration_key(display_name, class_name)
                    if key in manual_map:
                        skipped_names.append(display_name)
                        continue

                    manual_map[key] = {
                        'display_name': display_name,
                        'class_name': class_name,
                        'sequence': '',
                        'school_name': None,
                        'group_name': None,
                        'reg_status': 'manual'
                    }
                    added_names.append(display_name)

                if added_names:
                    write_json_atomic(get_manual_registrations_file(fixed_year), manual_map)
                    invalidate_year_cache(fixed_year)
                    write_staff_log(
                        action='manual_add',
                        outcome='success',
                        username=session.get('staff_username', ''),
                        detail=f'year={fixed_year}|class={class_name}|added={len(added_names)}|skipped={len(skipped_names)}'
                    )

                success_message = f'เพิ่มรายชื่อสำเร็จ {len(added_names)} รายชื่อ'

    for manual_key, manual_item in manual_map.items():
        if not isinstance(manual_item, dict):
            continue
        entry_class = str(manual_item.get('class_name') or '').strip()
        if entry_class != class_name:
            continue
        manual_entries.append({
            'key': str(manual_key),
            'display_name': str(manual_item.get('display_name') or '').strip(),
            'class_name': entry_class,
            'school_name': manual_item.get('school_name'),
            'group_name': manual_item.get('group_name')
        })
    manual_entries = sorted(manual_entries, key=lambda item: item.get('display_name') or '')

    return render_template(
        'manual_add.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=fixed_year,
        available_years=available_years,
        available_classes=CLASS_NAME_ORDER,
        selected_class=class_name,
        names_text=names_text,
        success_message=success_message,
        error_message=error_message,
        added_names=added_names,
        skipped_names=skipped_names,
        manual_entries=manual_entries
    )


@app.route('/get_data_info')
def get_data_info():
    return jsonify({'timestamp': get_data_timestamp(), 'count': len(df) if df is not None else 0})


def get_data_timestamp():
    bangkok_tz = pytz.timezone("Asia/Bangkok")
    return datetime.now(bangkok_tz).strftime('%d/%m/%Y %H:%M:%S')


CURRENT_YEAR_NUMERIC = get_current_buddhist_year(numeric=True)
df = load_data_from_api(CURRENT_YEAR_NUMERIC, store_global=True)
DF_CACHE[CURRENT_YEAR_NUMERIC] = df
load_bali_summary()

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(debug=debug_mode)
