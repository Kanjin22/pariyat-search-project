import json
import hashlib
import logging
import os
import re
import sqlite3
import uuid
from functools import wraps
from flask import Flask, render_template, jsonify, request, session, redirect, url_for, Response
import pandas as pd
from datetime import datetime, timedelta, timezone
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
RESULT_STATUS_OPTIONS = ['', 'สอบตก', 'ขาดสอบ', 'ขาดสิทธิ์', 'สอบได้', 'สอบซ่อม (รวมสอบซ่อมได้)', 'สอบซ่อม', 'สอบซ่อมได้']
RESULT_STATUS_SET = set(RESULT_STATUS_OPTIONS)
RESULTS_DATA_DIR = os.getenv('RESULTS_DATA_DIR', '').strip() or os.getenv('PARIYAT_DATA_DIR', '').strip() or os.path.join(BASE_DIR, 'data')
RESULTS_FILE = os.path.join(RESULTS_DATA_DIR, 'exam_results.json')
STAFF_ACCOUNTS_FILE = os.path.join(RESULTS_DATA_DIR, 'staff_accounts.json')
BALI_SUMMARY_FILE = os.path.join(RESULTS_DATA_DIR, 'bali_summary_2569.json')
LEGACY_CERTIFICATE_SUMMARY_FILE = os.getenv('LEGACY_CERTIFICATE_SUMMARY_FILE', '').strip() or os.path.join(RESULTS_DATA_DIR, 'legacy_certificates_summary.json')
LEGACY_CERTIFICATE_NDJSON_FILE = os.getenv('LEGACY_CERTIFICATE_NDJSON_FILE', '').strip() or os.path.join(RESULTS_DATA_DIR, 'legacy_certificates.ndjson')
COMMITTED_LEGACY_CERTIFICATE_SUMMARY_FILE = os.path.join(BASE_DIR, 'app', 'data', 'legacy_certificates_summary.json')
LEGACY_CERTIFICATE_BASELINE_FILE = os.getenv('LEGACY_CERTIFICATE_BASELINE_FILE', '').strip()
LEGACY_CERTIFICATE_OVERRIDES_FILE = os.path.join(RESULTS_DATA_DIR, 'legacy_certificate_overrides.json')
LEGACY_CERTIFICATE_DELETIONS_FILE = os.path.join(RESULTS_DATA_DIR, 'legacy_certificate_deletions.json')
COMMITTED_CERTIFICATE_SNAPSHOT_ALL_FILE = os.path.join(BASE_DIR, 'app', 'data', 'certificate_snapshot_all.json')
COMMITTED_PUBLIC_CERTIFICATE_BOOTSTRAP_FILE = os.path.join(BASE_DIR, 'app', 'data', 'public_certificates_bootstrap.json')
API_SNAPSHOT_MAX_AGE_HOURS = int(os.getenv('API_SNAPSHOT_MAX_AGE_HOURS', '24') or 24)
try:
    API_SNAPSHOT_LOCK_MAX_YEAR = int((os.getenv('API_SNAPSHOT_LOCK_MAX_YEAR') or '').strip() or 0) or None
except ValueError:
    API_SNAPSHOT_LOCK_MAX_YEAR = None
DATA_SOURCE_SETTINGS_FILE = os.path.join(RESULTS_DATA_DIR, 'data_source_settings.json')
ANALYTICS_DB_FILE = os.path.join(RESULTS_DATA_DIR, 'analytics.sqlite3')
VISITOR_COOKIE_NAME = 'ps_vid'
VISITOR_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365 * 5
VISITOR_COUNTER_CACHE = {'ts': None, 'date': None, 'data': None}
CERTIFICATE_API_URL = (os.getenv('PARIYAT_CERT_API_URL') or '').strip() or 'https://app.pariyat.com/pages/postx/license_json.php'
CERTIFICATE_API_USER = (os.getenv('PARIYAT_CERT_API_USER') or os.getenv('PARIYAT_API_USER') or '').strip()
CERTIFICATE_API_PASS = (os.getenv('PARIYAT_CERT_API_PASS') or os.getenv('PARIYAT_API_PASS') or '').strip()
PUBLIC_CERTIFICATE_CACHE_TTL_SECONDS = int(os.getenv('PUBLIC_CERTIFICATE_CACHE_TTL_SECONDS', '300') or 300)
PUBLIC_CERTIFICATE_CACHE = {
    'built_at': None,
    'legacy_source': '',
    'legacy_mtime': None,
    'years': (),
    'rows': [],
    'meta': {}
}
CURRENT_CERTIFICATE_YEAR_CACHE = {}
LEGACY_CERTIFICATE_EDIT_CACHE_TTL_SECONDS = int(os.getenv('LEGACY_CERTIFICATE_EDIT_CACHE_TTL_SECONDS', '30') or 30)
LEGACY_CERTIFICATE_EDIT_CACHE = {
    'built_at': None,
    'baseline_file': '',
    'baseline_mtime': None,
    'overrides_mtime': None,
    'deletions_mtime': None,
    'rows': [],
    'search_texts': [],
}

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
CLASS_NAME_LEVEL_ID_MAP = {class_name: level_id for level_id, class_name in LEVEL_ID_MAP.items()}
CERTIFICATE_YEAR_OVERRIDES = {
    '313': '2549',
    '1198': '2531',
    '5426': '2554',
    '8590': '2565',
    '9307': '2558',
    '9672': '2567',
    '11524': '2561',
    '11922': '2552',
    '12393': '2560',
}


def is_running_on_render():
    for key in ('RENDER', 'RENDER_SERVICE_ID', 'RENDER_EXTERNAL_URL', 'RENDER_REGION'):
        if str(os.getenv(key) or '').strip():
            return True
    return False

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

THAM_LEVEL_TYPES = {'นักธรรม', 'ธรรมศึกษา'}
BALI_LEVEL_TYPES = {'บาลี', 'บาลีศึกษา'}

MODE_OVERVIEW = 'overview'
MODE_THAM = 'tham'
MODE_BALI = 'bali'
VALID_MODES = {MODE_OVERVIEW, MODE_THAM, MODE_BALI}


def get_mode_value(raw_value):
    mode = str(raw_value or '').strip().lower()
    return mode if mode in VALID_MODES else MODE_OVERVIEW


def get_current_mode():
    return get_mode_value(request.args.get('mode'))


def get_department_class_names(department_key):
    key = str(department_key or '').strip().lower()
    if key not in DEPARTMENT_LEVELS:
        return []
    levels = []
    for subsection in (DEPARTMENT_LEVELS[key].get('subsections') or {}).values():
        levels.extend(subsection.get('levels') or [])
    class_names = [LEVEL_ID_MAP.get(str(level_id), '') for level_id in levels]
    return [value for value in class_names if value]


def filter_df_by_mode(base_df, mode):
    if base_df is None or base_df.empty:
        return base_df
    mode_value = get_mode_value(mode)
    if mode_value == MODE_THAM:
        class_names = get_department_class_names('tham')
        return base_df[base_df['class_name'].isin(class_names)]
    if mode_value == MODE_BALI:
        class_names = get_department_class_names('bali')
        return base_df[base_df['class_name'].isin(class_names)]
    return base_df


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


def to_arabic_digits(text):
    if text is None or pd.isna(text):
        return ''
    text = str(text)
    arabic_digits = str.maketrans('๐๑๒๓๔๕๖๗๘๙', '0123456789')
    return text.translate(arabic_digits)


CERTIFICATE_TEXT_SPACE_RE = re.compile(r'[\s\u200b\u200c\u200d\ufeff]+')
NAME_KEY_SPACE_RE = re.compile(r'[\s\u200b\u200c\u200d\ufeff]+')
DISPLAY_NAME_PAREN_CONTENT_RE = re.compile(r'\(([^)]+)\)')
DISPLAY_NAME_PAREN_BLOCK_RE = re.compile(r'\s*\([^)]*\)\s*')


def normalize_certificate_text(value):
    text = to_arabic_digits(value)
    text = str(text or '').strip()
    text = CERTIFICATE_TEXT_SPACE_RE.sub(' ', text)
    text = text.replace(' /', '/').replace('/ ', '/')
    return text


def is_meaningful_certificate_no(value):
    text = normalize_certificate_text(value)
    if not text:
        return False
    invalid_markers = [
        'รอผลสอบ',
        'ไม่มีข้อมูล',
        'ไม่มีเลขที่',
    ]
    if any(marker in text for marker in invalid_markers):
        return False
    if text in {'ไม่มี', '-'}:
        return False
    return True


def normalize_certificate_year(value, source_record_id=''):
    year_text = to_arabic_digits(value)
    year_text = str(year_text or '').strip()
    override_value = str(CERTIFICATE_YEAR_OVERRIDES.get(str(source_record_id or '').strip()) or '').strip()
    return override_value or year_text


def normalize_public_certificate_record(item):
    if not isinstance(item, dict):
        return {}
    display_name = str(item.get('display_name') or item.get('fullname') or '').strip()
    certificate_no = normalize_certificate_text(item.get('certificate_no') or item.get('license'))
    if not is_meaningful_certificate_no(certificate_no):
        return {}
    subject = str(item.get('subject') or item.get('level_type') or '').strip()
    level = str(item.get('level') or '').strip()
    source_record_id = str(item.get('source_record_id') or item.get('license_id') or item.get('id') or '').strip()
    year = normalize_certificate_year(item.get('year'), source_record_id=source_record_id)
    parsed_year = ''
    try:
        parsed_year = str(parse_certificate_number_pattern(certificate_no).get('year') or '').strip()
    except Exception:
        parsed_year = ''
    if parsed_year.isdigit() and 2400 <= int(parsed_year) <= 2700:
        year_text = str(year or '').strip()
        if not year_text:
            year = parsed_year
        elif year_text.isdigit():
            year_int = int(year_text)
            if year_int < 2400 or year_int > 2700:
                year = parsed_year
    province = str(item.get('province') or '').strip()
    school = str(item.get('school') or item.get('sumnugrean') or '').strip()
    temple = str(item.get('temple') or item.get('sumnugrean') or item.get('school') or '').strip()
    source = str(item.get('source') or 'legacy').strip() or 'legacy'
    person_id = str(item.get('person_id') or item.get('source_person_id') or '').strip()
    level_id = str(item.get('level_id') or '').strip()
    name_normalized = build_base_name_key_from_display_name(display_name) or normalize_name_key(display_name)
    search_text = ' '.join(
        part for part in [
            display_name,
            name_normalized,
            certificate_no,
            subject,
            level,
            year,
            province,
            school,
            temple,
        ] if part
    ).lower()
    return {
        'id_std': str(item.get('id_std') or '').strip(),
        'display_name': display_name,
        'certificate_no': certificate_no,
        'certificate_no_normalized': certificate_no.lower(),
        'subject': subject,
        'level_type': str(item.get('level_type') or subject).strip(),
        'level_id': level_id,
        'level': level,
        'year': year,
        'province': province,
        'school': school,
        'temple': temple,
        'person_id': person_id,
        'source': source,
        'source_record_id': source_record_id,
        'name_normalized': name_normalized,
        'search_text': search_text,
        'license_text': str(item.get('license_text') or '').strip(),
        'scraped_at': str(item.get('scraped_at') or '').strip(),
        'updated_at': str(item.get('updated_at') or '').strip(),
        'merged_from': item.get('merged_from') if isinstance(item.get('merged_from'), list) else [],
    }


def build_public_certificate_row(id_std, display_name, certificate, scraped_at):
    return normalize_public_certificate_record({
        'id_std': id_std,
        'display_name': display_name,
        'certificate_no': certificate.get('certificate_no'),
        'subject': certificate.get('subject'),
        'level': certificate.get('level'),
        'year': certificate.get('year'),
        'province': certificate.get('province'),
        'school': certificate.get('school'),
        'temple': certificate.get('temple'),
        'scraped_at': scraped_at,
        'source': 'legacy',
        'source_record_id': f'{id_std}|{certificate.get("certificate_no") or ""}',
    })


def get_public_certificate_source_file():
    if os.path.exists(LEGACY_CERTIFICATE_SUMMARY_FILE):
        return LEGACY_CERTIFICATE_SUMMARY_FILE
    if os.path.exists(LEGACY_CERTIFICATE_NDJSON_FILE):
        return LEGACY_CERTIFICATE_NDJSON_FILE
    if os.path.exists(COMMITTED_LEGACY_CERTIFICATE_SUMMARY_FILE):
        return COMMITTED_LEGACY_CERTIFICATE_SUMMARY_FILE
    return ''


def get_certificate_snapshot_file(year=None):
    year_value = str(year or '').strip().lower()
    if year_value in {'', 'all', '*'}:
        return os.path.join(RESULTS_DATA_DIR, 'certificate_snapshot_all.json')
    return os.path.join(RESULTS_DATA_DIR, f'certificate_snapshot_{int(year)}.json')


def get_certificate_snapshot_read_file(year=None):
    snapshot_file = get_certificate_snapshot_file(year)
    year_value = str(year or '').strip().lower()
    if os.path.exists(snapshot_file):
        return snapshot_file
    if year_value in {'', 'all', '*'} and os.path.exists(COMMITTED_CERTIFICATE_SNAPSHOT_ALL_FILE):
        return COMMITTED_CERTIFICATE_SNAPSHOT_ALL_FILE
    return snapshot_file


def load_certificate_snapshot(year):
    snapshot_file = get_certificate_snapshot_read_file(year)
    if not os.path.exists(snapshot_file):
        return None
    try:
        with open(snapshot_file, 'r', encoding='utf-8') as fp:
            payload = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict) and isinstance(payload.get('data'), list):
        return payload
    return None


def save_certificate_snapshot(year, api_rows):
    os.makedirs(RESULTS_DATA_DIR, exist_ok=True)
    year_value = str(year or '').strip().lower()
    payload = {
        'year': 'all' if year_value in {'', 'all', '*'} else int(year),
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'data': api_rows if isinstance(api_rows, list) else [],
    }
    with open(get_certificate_snapshot_file(year), 'w', encoding='utf-8') as fp:
        json.dump(payload, fp, ensure_ascii=False)


def build_current_public_certificate_row(item):
    display_name = str(item.get('fullname') or '').strip()
    if not display_name:
        prefix = str(item.get('prefix_title') or '').strip()
        first_name = str(item.get('firstname') or '').strip()
        pali_name = str(item.get('paliname') or '').strip()
        last_name = str(item.get('lastname') or '').strip()
        first_section = ''.join(part for part in [prefix, first_name] if part)
        if pali_name:
            display_name = " ".join(part for part in [first_section, pali_name] if part)
            if last_name:
                display_name += f' ({last_name})'
        else:
            display_name = " ".join(part for part in [first_section, last_name] if part)
    return normalize_public_certificate_record({
        'display_name': display_name,
        'certificate_no': item.get('license'),
        'subject': item.get('level_type'),
        'level_type': item.get('level_type'),
        'level_id': item.get('level_id'),
        'level': item.get('level'),
        'year': item.get('year'),
        'province': item.get('province'),
        'school': item.get('sumnugrean') or item.get('school'),
        'temple': item.get('school'),
        'person_id': item.get('person_id'),
        'source': 'current_api',
        'source_record_id': item.get('license_id') or item.get('id'),
        'license_text': item.get('license_text'),
        'updated_at': item.get('updated_at'),
    })


def load_legacy_public_certificate_rows():
    baseline_file = get_legacy_certificate_baseline_source_file()
    if baseline_file:
        applied_rows, _texts, _source_file, baseline_mtime = load_legacy_certificate_rows_cached(include_deleted=False)
        rows = []
        for item in applied_rows:
            year_text = str(item.get('year') or '').strip()
            if year_text.isdigit() and int(year_text) >= 2567:
                continue
            normalized = normalize_public_certificate_record({
                **item,
                'source': 'legacy',
                'source_record_id': str(item.get('legacy_id') or '').strip(),
            })
            if normalized.get('display_name') and normalized.get('certificate_no'):
                rows.append(normalized)

        rows.sort(
            key=lambda row: (
                row.get('display_name', ''),
                row.get('year', ''),
                row.get('subject', ''),
                row.get('level', ''),
                row.get('certificate_no', ''),
            )
        )
        person_count = len({row.get('display_name', '') for row in rows if row.get('display_name')})
        stamp_mtime = baseline_mtime
        try:
            overrides_mtime = os.path.getmtime(LEGACY_CERTIFICATE_OVERRIDES_FILE) if os.path.exists(LEGACY_CERTIFICATE_OVERRIDES_FILE) else None
        except OSError:
            overrides_mtime = None
        try:
            deletions_mtime = os.path.getmtime(LEGACY_CERTIFICATE_DELETIONS_FILE) if os.path.exists(LEGACY_CERTIFICATE_DELETIONS_FILE) else None
        except OSError:
            deletions_mtime = None
        for candidate in [overrides_mtime, deletions_mtime]:
            if candidate is not None and (stamp_mtime is None or candidate > stamp_mtime):
                stamp_mtime = candidate
        timestamp = datetime.fromtimestamp(stamp_mtime).strftime('%d/%m/%Y %H:%M') if stamp_mtime else '-'
        meta = {
            'timestamp': timestamp,
            'certificate_count': len(rows),
            'person_count': person_count,
            'source': ', '.join(part for part in [
                os.path.basename(baseline_file),
                'legacy_overrides' if overrides_mtime else '',
                'legacy_deletions' if deletions_mtime else '',
            ] if part),
        }
        return rows, meta

    source_file = get_public_certificate_source_file()
    if not source_file:
        return [], {'timestamp': '-', 'certificate_count': 0, 'person_count': 0, 'source': ''}

    try:
        mtime = os.path.getmtime(source_file)
    except OSError:
        return [], {'timestamp': '-', 'certificate_count': 0, 'person_count': 0, 'source': ''}

    rows = []
    if source_file.endswith('.json'):
        try:
            with open(source_file, 'r', encoding='utf-8') as fp:
                payload = json.load(fp)
        except (OSError, json.JSONDecodeError):
            payload = []
        if isinstance(payload, list):
            for item in payload:
                row = normalize_public_certificate_record({**item, 'source': 'legacy'})
                if row.get('display_name') and row.get('certificate_no'):
                    rows.append(row)
    else:
        try:
            with open(source_file, 'r', encoding='utf-8') as fp:
                for line in fp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    display_name = str((payload.get('student') or {}).get('display_name') or '').strip()
                    id_std = str(payload.get('id_std') or '').strip()
                    scraped_at = str(payload.get('scraped_at') or '').strip()
                    certificates = payload.get('certificates') or []
                    for certificate in certificates:
                        row = build_public_certificate_row(id_std, display_name, certificate, scraped_at)
                        if row.get('display_name') and row.get('certificate_no'):
                            rows.append(row)
        except OSError:
            rows = []

    rows.sort(
        key=lambda item: (
            item.get('display_name', ''),
            item.get('year', ''),
            item.get('subject', ''),
            item.get('level', ''),
            item.get('certificate_no', ''),
        )
    )
    person_count = len({row.get('display_name', '') for row in rows if row.get('display_name')})
    timestamp = datetime.fromtimestamp(mtime).strftime('%d/%m/%Y %H:%M')
    meta = {
        'timestamp': timestamp,
        'certificate_count': len(rows),
        'person_count': person_count,
        'source': os.path.basename(source_file),
    }
    return rows, meta


def invalidate_public_certificate_cache():
    PUBLIC_CERTIFICATE_CACHE['built_at'] = None
    PUBLIC_CERTIFICATE_CACHE['legacy_source'] = ''
    PUBLIC_CERTIFICATE_CACHE['legacy_mtime'] = None
    PUBLIC_CERTIFICATE_CACHE['years'] = ()
    PUBLIC_CERTIFICATE_CACHE['rows'] = []
    PUBLIC_CERTIFICATE_CACHE['meta'] = {}


def invalidate_legacy_certificate_edit_cache():
    LEGACY_CERTIFICATE_EDIT_CACHE['built_at'] = None
    LEGACY_CERTIFICATE_EDIT_CACHE['baseline_file'] = ''
    LEGACY_CERTIFICATE_EDIT_CACHE['baseline_mtime'] = None
    LEGACY_CERTIFICATE_EDIT_CACHE['overrides_mtime'] = None
    LEGACY_CERTIFICATE_EDIT_CACHE['deletions_mtime'] = None
    LEGACY_CERTIFICATE_EDIT_CACHE['rows'] = []
    LEGACY_CERTIFICATE_EDIT_CACHE['search_texts'] = []


def get_legacy_certificate_baseline_source_file():
    baseline_env = str(LEGACY_CERTIFICATE_BASELINE_FILE or '').strip()
    if baseline_env and os.path.exists(baseline_env):
        return baseline_env
    if os.path.exists(LEGACY_CERTIFICATE_SUMMARY_FILE):
        return LEGACY_CERTIFICATE_SUMMARY_FILE
    if os.path.exists(COMMITTED_LEGACY_CERTIFICATE_SUMMARY_FILE):
        return COMMITTED_LEGACY_CERTIFICATE_SUMMARY_FILE
    return ''


def load_legacy_certificate_overrides():
    if not os.path.exists(LEGACY_CERTIFICATE_OVERRIDES_FILE):
        return {}
    try:
        with open(LEGACY_CERTIFICATE_OVERRIDES_FILE, 'r', encoding='utf-8') as fp:
            payload = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def save_legacy_certificate_overrides(payload):
    write_json_atomic(LEGACY_CERTIFICATE_OVERRIDES_FILE, payload if isinstance(payload, dict) else {})


def load_legacy_certificate_deletions():
    if not os.path.exists(LEGACY_CERTIFICATE_DELETIONS_FILE):
        return {}
    try:
        with open(LEGACY_CERTIFICATE_DELETIONS_FILE, 'r', encoding='utf-8') as fp:
            payload = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def save_legacy_certificate_deletions(payload):
    write_json_atomic(LEGACY_CERTIFICATE_DELETIONS_FILE, payload if isinstance(payload, dict) else {})


def build_legacy_certificate_id(index):
    return f'legacy:{int(index)}'


def merge_legacy_certificate_row(baseline_row, override_row):
    if not isinstance(baseline_row, dict):
        return {}
    merged = dict(baseline_row)
    if isinstance(override_row, dict):
        fields = override_row.get('fields') if isinstance(override_row.get('fields'), dict) else {}
        merged.update(fields)
    return merged


def is_legacy_certificate_deleted(legacy_id, deletions_map):
    deletion = deletions_map.get(legacy_id) if isinstance(deletions_map, dict) else None
    if not isinstance(deletion, dict):
        return False
    return deletion.get('deleted') is True


def legacy_certificate_row_fingerprint(baseline_row, override_row=None, deletion_row=None):
    payload = {
        'baseline': baseline_row if isinstance(baseline_row, dict) else {},
        'override': override_row if isinstance(override_row, dict) else {},
        'deletion': deletion_row if isinstance(deletion_row, dict) else {},
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(encoded.encode('utf-8')).hexdigest()


def load_legacy_certificate_baseline_rows(baseline_file):
    if not baseline_file:
        return []
    try:
        with open(baseline_file, 'r', encoding='utf-8') as fp:
            payload = json.load(fp)
    except (OSError, json.JSONDecodeError):
        payload = []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def load_legacy_certificate_rows_cached(include_deleted=False):
    baseline_file = get_legacy_certificate_baseline_source_file()
    try:
        baseline_mtime = os.path.getmtime(baseline_file) if baseline_file else None
    except OSError:
        baseline_mtime = None
    try:
        overrides_mtime = os.path.getmtime(LEGACY_CERTIFICATE_OVERRIDES_FILE) if os.path.exists(LEGACY_CERTIFICATE_OVERRIDES_FILE) else None
    except OSError:
        overrides_mtime = None
    try:
        deletions_mtime = os.path.getmtime(LEGACY_CERTIFICATE_DELETIONS_FILE) if os.path.exists(LEGACY_CERTIFICATE_DELETIONS_FILE) else None
    except OSError:
        deletions_mtime = None

    built_at = LEGACY_CERTIFICATE_EDIT_CACHE.get('built_at')
    if (
        isinstance(built_at, datetime)
        and LEGACY_CERTIFICATE_EDIT_CACHE.get('baseline_file') == baseline_file
        and LEGACY_CERTIFICATE_EDIT_CACHE.get('baseline_mtime') == baseline_mtime
        and LEGACY_CERTIFICATE_EDIT_CACHE.get('overrides_mtime') == overrides_mtime
        and LEGACY_CERTIFICATE_EDIT_CACHE.get('deletions_mtime') == deletions_mtime
        and (datetime.now(timezone.utc) - built_at).total_seconds() <= LEGACY_CERTIFICATE_EDIT_CACHE_TTL_SECONDS
    ):
        rows = LEGACY_CERTIFICATE_EDIT_CACHE.get('rows', [])
        texts = LEGACY_CERTIFICATE_EDIT_CACHE.get('search_texts', [])
        if not include_deleted:
            filtered_rows = []
            filtered_texts = []
            for idx, row in enumerate(rows):
                if row.get('deleted') is True:
                    continue
                filtered_rows.append(row)
                filtered_texts.append(texts[idx] if idx < len(texts) else '')
            return filtered_rows, filtered_texts, baseline_file, baseline_mtime
        return rows, texts, baseline_file, baseline_mtime

    baseline_rows = load_legacy_certificate_baseline_rows(baseline_file)
    overrides_map = load_legacy_certificate_overrides()
    deletions_map = load_legacy_certificate_deletions()

    rows = []
    search_texts = []
    for idx, baseline_row in enumerate(baseline_rows):
        legacy_id = build_legacy_certificate_id(idx)
        override_row = overrides_map.get(legacy_id) if isinstance(overrides_map, dict) else None
        deletion_row = deletions_map.get(legacy_id) if isinstance(deletions_map, dict) else None
        merged = merge_legacy_certificate_row(baseline_row, override_row)
        deleted = is_legacy_certificate_deleted(legacy_id, deletions_map)

        display_name = str(merged.get('display_name') or '').strip()
        id_std = str(merged.get('id_std') or '').strip()
        certificate_no = str(merged.get('certificate_no') or '').strip()
        subject = str(merged.get('subject') or '').strip()
        level = str(merged.get('level') or '').strip()
        year = str(merged.get('year') or '').strip()
        province = str(merged.get('province') or '').strip()
        school = str(merged.get('school') or '').strip()
        temple = str(merged.get('temple') or '').strip()

        row_payload = dict(merged)
        row_payload['legacy_id'] = legacy_id
        row_payload['deleted'] = deleted
        row_payload['fingerprint'] = legacy_certificate_row_fingerprint(baseline_row, override_row=override_row, deletion_row=deletion_row)
        rows.append(row_payload)
        search_texts.append(
            ' '.join(part for part in [
                display_name,
                normalize_name_key(display_name),
                id_std,
                certificate_no,
                normalize_certificate_text(certificate_no),
                subject,
                level,
                year,
                province,
                school,
                temple,
            ] if part).lower()
        )

    LEGACY_CERTIFICATE_EDIT_CACHE['built_at'] = datetime.now(timezone.utc)
    LEGACY_CERTIFICATE_EDIT_CACHE['baseline_file'] = baseline_file
    LEGACY_CERTIFICATE_EDIT_CACHE['baseline_mtime'] = baseline_mtime
    LEGACY_CERTIFICATE_EDIT_CACHE['overrides_mtime'] = overrides_mtime
    LEGACY_CERTIFICATE_EDIT_CACHE['deletions_mtime'] = deletions_mtime
    LEGACY_CERTIFICATE_EDIT_CACHE['rows'] = rows
    LEGACY_CERTIFICATE_EDIT_CACHE['search_texts'] = search_texts

    if not include_deleted:
        filtered_rows = []
        filtered_texts = []
        for idx, row in enumerate(rows):
            if row.get('deleted') is True:
                continue
            filtered_rows.append(row)
            filtered_texts.append(search_texts[idx] if idx < len(search_texts) else '')
        return filtered_rows, filtered_texts, baseline_file, baseline_mtime
    return rows, search_texts, baseline_file, baseline_mtime


def load_current_public_certificate_rows_for_year(year=None, force_refresh=False):
    year_filter = normalize_year_value(year)
    snapshot_key = int(year_filter) if year_filter else 'all'
    snapshot_file = get_certificate_snapshot_read_file(snapshot_key)
    snapshot_mtime = os.path.getmtime(snapshot_file) if os.path.exists(snapshot_file) else None
    cached = CURRENT_CERTIFICATE_YEAR_CACHE.get(snapshot_key)
    if cached and cached.get('snapshot_mtime') == snapshot_mtime and not force_refresh:
        return cached.get('rows', []), cached.get('meta', {})

    snapshot = load_certificate_snapshot(snapshot_key)
    api_rows = []
    source_label = ''
    error_message = ''

    if not force_refresh and snapshot and is_snapshot_fresh(snapshot):
        api_rows = snapshot.get('data') or []
        source_label = 'current_api_snapshot' if year_filter else 'current_api_snapshot_all'
    else:
        if CERTIFICATE_API_URL and CERTIFICATE_API_USER and CERTIFICATE_API_PASS:
            try:
                params = {
                    'user': CERTIFICATE_API_USER,
                    'pass': CERTIFICATE_API_PASS,
                }
                if year_filter:
                    params['filter_year'] = int(year_filter)
                response = requests.get(CERTIFICATE_API_URL, params=params, timeout=120)
                response.raise_for_status()
                payload = response.json()
                if payload.get('status') != 'success' or not isinstance(payload.get('data'), list):
                    raise RuntimeError('Invalid certificate API payload')
                api_rows = payload.get('data') or []
                save_certificate_snapshot(snapshot_key, api_rows)
                snapshot_mtime = os.path.getmtime(snapshot_file) if os.path.exists(snapshot_file) else None
                source_label = 'current_api_live' if year_filter else 'current_api_live_all'
            except Exception as exc:
                error_message = str(exc)
        if not api_rows and snapshot:
            api_rows = snapshot.get('data') or []
            source_label = 'current_api_snapshot_fallback' if year_filter else 'current_api_snapshot_fallback_all'

    rows = []
    for item in api_rows:
        row = build_current_public_certificate_row(item)
        if row.get('display_name') and row.get('certificate_no'):
            rows.append(row)
    rows.sort(
        key=lambda item: (
            item.get('display_name', ''),
            item.get('year', ''),
            item.get('subject', ''),
            item.get('level', ''),
            item.get('certificate_no', ''),
        )
    )
    meta = {
        'year': str(year_filter or ''),
        'certificate_count': len(rows),
        'person_count': len({row.get('display_name', '') for row in rows if row.get('display_name')}),
        'source': source_label,
        'error': error_message,
    }
    CURRENT_CERTIFICATE_YEAR_CACHE[snapshot_key] = {
        'snapshot_mtime': snapshot_mtime,
        'rows': rows,
        'meta': meta,
    }
    return rows, meta


def get_public_certificate_source_priority(source_name):
    source_text = str(source_name or '').strip().lower()
    if source_text == 'current_api':
        return 2
    if source_text == 'legacy':
        return 1
    return 0


def get_public_certificate_year_key(row):
    cert_text = str(row.get('certificate_no') or '').strip()
    year_text = str(row.get('year') or '').strip()
    if cert_text:
        try:
            info = parse_certificate_number_pattern(cert_text)
        except Exception:
            info = {}
        parsed_year = str(info.get('year') or '').strip()
        if parsed_year:
            return parsed_year
        parsed_year_two = str(info.get('year_two') or '').strip()
        if parsed_year_two:
            return f'yy:{parsed_year_two.zfill(2)}'
    normalized = normalize_year_value(year_text)
    if normalized is not None:
        return str(normalized)
    return str(year_text or '')


def build_public_certificate_merge_key(row):
    cert_key = str(row.get('certificate_no_normalized') or '').strip()
    level_id = str(row.get('level_id') or '').strip()
    year_text = get_public_certificate_year_key(row)
    person_id = str(row.get('person_id') or '').strip()
    if cert_key:
        return '|'.join(str(part or '') for part in [
            'cert',
            cert_key,
            year_text,
            level_id,
            person_id or str(row.get('name_normalized') or '').strip(),
        ])
    source = str(row.get('source') or '').strip()
    source_record_id = str(row.get('source_record_id') or '').strip()
    if source and source_record_id:
        return '|'.join(str(part or '') for part in ['source', source, source_record_id])
    return '|'.join(str(part or '') for part in [
        'fallback',
        source,
        str(row.get('display_name') or '').strip(),
        year_text,
        str(row.get('level') or '').strip(),
        str(row.get('school') or '').strip(),
    ])


def merge_public_certificate_rows(rows):
    merged = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get('display_name') or not row.get('certificate_no'):
            continue
        merge_key = build_public_certificate_merge_key(row)
        if merge_key not in merged:
            merged_row = dict(row)
            merged_row['merged_from'] = [{
                'source': row.get('source', ''),
                'source_record_id': row.get('source_record_id', ''),
            }]
            merged[merge_key] = merged_row
            continue

        current_row = merged[merge_key]
        current_priority = get_public_certificate_source_priority(current_row.get('source'))
        new_priority = get_public_certificate_source_priority(row.get('source'))
        preferred_row = row if new_priority > current_priority else current_row
        fallback_row = current_row if preferred_row is row else row
        merged_row = dict(current_row)
        for field_name in [
            'display_name',
            'certificate_no',
            'certificate_no_normalized',
            'subject',
            'level_type',
            'level_id',
            'level',
            'year',
            'province',
            'school',
            'temple',
            'person_id',
            'source',
            'source_record_id',
            'name_normalized',
            'search_text',
            'license_text',
            'scraped_at',
            'updated_at',
        ]:
            preferred_value = preferred_row.get(field_name)
            fallback_value = fallback_row.get(field_name)
            merged_row[field_name] = preferred_value or fallback_value or merged_row.get(field_name, '')
        merged_sources = list(current_row.get('merged_from') or [])
        new_source_entry = {
            'source': row.get('source', ''),
            'source_record_id': row.get('source_record_id', ''),
        }
        if new_source_entry not in merged_sources:
            merged_sources.append(new_source_entry)
        merged_row['merged_from'] = merged_sources
        merged[merge_key] = merged_row
    return list(merged.values())


def dedupe_public_certificate_rows(rows):
    deduped = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get('display_name') or not row.get('certificate_no'):
            continue
        display_name = str(row.get('display_name') or '').strip()
        identity = display_name
        cert_key = str(row.get('certificate_no_normalized') or '').strip().lower()
        if not cert_key:
            cert_key = normalize_certificate_text(row.get('certificate_no')).lower()
        year_text = get_public_certificate_year_key(row)
        dedupe_key = '|'.join(['dedupe', identity, cert_key, year_text])

        if dedupe_key not in deduped:
            deduped[dedupe_key] = dict(row)
            continue

        current_row = deduped[dedupe_key]
        current_priority = get_public_certificate_source_priority(current_row.get('source'))
        new_priority = get_public_certificate_source_priority(row.get('source'))
        preferred_row = row if new_priority > current_priority else current_row
        fallback_row = current_row if preferred_row is row else row
        merged_row = dict(current_row)
        for field_name in [
            'display_name',
            'certificate_no',
            'certificate_no_normalized',
            'subject',
            'level_type',
            'level_id',
            'level',
            'year',
            'province',
            'school',
            'temple',
            'person_id',
            'source',
            'source_record_id',
            'name_normalized',
            'search_text',
            'license_text',
            'scraped_at',
            'updated_at',
        ]:
            preferred_value = preferred_row.get(field_name)
            fallback_value = fallback_row.get(field_name)
            merged_row[field_name] = preferred_value or fallback_value or merged_row.get(field_name, '')
        merged_sources = list(current_row.get('merged_from') or [])
        new_sources = list(row.get('merged_from') or [])
        for entry in new_sources:
            if entry not in merged_sources:
                merged_sources.append(entry)
        new_source_entry = {
            'source': row.get('source', ''),
            'source_record_id': row.get('source_record_id', ''),
        }
        if new_source_entry not in merged_sources:
            merged_sources.append(new_source_entry)
        merged_row['merged_from'] = merged_sources
        deduped[dedupe_key] = merged_row
    return list(deduped.values())


def load_public_certificate_rows():
    legacy_source_file = get_public_certificate_source_file()
    legacy_mtime = os.path.getmtime(legacy_source_file) if legacy_source_file and os.path.exists(legacy_source_file) else None
    cache_built_at = PUBLIC_CERTIFICATE_CACHE.get('built_at')
    if (
        isinstance(cache_built_at, datetime)
        and PUBLIC_CERTIFICATE_CACHE.get('legacy_source') == legacy_source_file
        and PUBLIC_CERTIFICATE_CACHE.get('legacy_mtime') == legacy_mtime
        and (datetime.now(timezone.utc) - cache_built_at).total_seconds() <= PUBLIC_CERTIFICATE_CACHE_TTL_SECONDS
    ):
        return PUBLIC_CERTIFICATE_CACHE.get('rows', []), PUBLIC_CERTIFICATE_CACHE.get('meta', {})

    disable_bootstrap = str(os.getenv('PUBLIC_CERTIFICATE_DISABLE_BOOTSTRAP') or '').strip().lower() in {'1', 'true', 'yes'}
    force_bootstrap = str(os.getenv('PUBLIC_CERTIFICATE_FORCE_BOOTSTRAP') or '').strip().lower() in {'1', 'true', 'yes'}
    regular_legacy_available = bool(legacy_source_file and os.path.exists(legacy_source_file))
    snapshot_read_file = get_certificate_snapshot_read_file('all')
    regular_current_snapshot_available = bool(snapshot_read_file and os.path.exists(snapshot_read_file))
    legacy_edits_available = os.path.exists(LEGACY_CERTIFICATE_OVERRIDES_FILE) or os.path.exists(LEGACY_CERTIFICATE_DELETIONS_FILE)

    should_use_bootstrap = (
        not disable_bootstrap
        and os.path.exists(COMMITTED_PUBLIC_CERTIFICATE_BOOTSTRAP_FILE)
        and not legacy_edits_available
        and (
            force_bootstrap
            or is_running_on_render()
            or (not regular_legacy_available and not regular_current_snapshot_available)
        )
    )

    if should_use_bootstrap:
        try:
            with open(COMMITTED_PUBLIC_CERTIFICATE_BOOTSTRAP_FILE, 'r', encoding='utf-8') as fp:
                payload = json.load(fp)
            bootstrap_rows = payload.get('rows') if isinstance(payload, dict) else None
            bootstrap_meta = payload.get('meta') if isinstance(payload, dict) else None
            if isinstance(bootstrap_rows, list) and isinstance(bootstrap_meta, dict):
                deduped_rows = dedupe_public_certificate_rows(bootstrap_rows)
                deduped_rows.sort(
                    key=lambda item: (
                        item.get('display_name', ''),
                        item.get('year', ''),
                        item.get('subject', ''),
                        item.get('level', ''),
                        item.get('certificate_no', ''),
                    )
                )
                bootstrap_meta = dict(bootstrap_meta)
                bootstrap_meta['certificate_count'] = len(deduped_rows)
                bootstrap_meta['person_count'] = len({row.get('display_name', '') for row in deduped_rows if row.get('display_name')})
                PUBLIC_CERTIFICATE_CACHE['built_at'] = datetime.now(timezone.utc)
                PUBLIC_CERTIFICATE_CACHE['legacy_source'] = legacy_source_file
                PUBLIC_CERTIFICATE_CACHE['legacy_mtime'] = legacy_mtime
                PUBLIC_CERTIFICATE_CACHE['years'] = ()
                PUBLIC_CERTIFICATE_CACHE['rows'] = deduped_rows
                PUBLIC_CERTIFICATE_CACHE['meta'] = bootstrap_meta
                return deduped_rows, bootstrap_meta
        except (OSError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
            pass

    legacy_rows, legacy_meta = load_legacy_public_certificate_rows()
    current_rows, current_meta = load_current_public_certificate_rows_for_year(None)

    rows = dedupe_public_certificate_rows(merge_public_certificate_rows(legacy_rows + current_rows))
    rows.sort(
        key=lambda item: (
            item.get('display_name', ''),
            item.get('year', ''),
            item.get('subject', ''),
            item.get('level', ''),
            item.get('certificate_no', ''),
        )
    )
    person_count = len({row.get('display_name', '') for row in rows if row.get('display_name')})
    timestamp_candidates = [legacy_meta.get('timestamp', '-')]
    if current_meta.get('certificate_count'):
        timestamp_candidates.append('API ทั้งหมด')
    meta = {
        'timestamp': ' | '.join(candidate for candidate in timestamp_candidates if candidate and candidate != '-').strip() or '-',
        'certificate_count': len(rows),
        'person_count': person_count,
        'source': ', '.join(sorted(set(
            [legacy_meta.get('source', ''), str(current_meta.get('source') or '').strip()]
        ))).strip(', '),
    }
    PUBLIC_CERTIFICATE_CACHE['built_at'] = datetime.now(timezone.utc)
    PUBLIC_CERTIFICATE_CACHE['legacy_source'] = legacy_source_file
    PUBLIC_CERTIFICATE_CACHE['legacy_mtime'] = legacy_mtime
    PUBLIC_CERTIFICATE_CACHE['years'] = ()
    PUBLIC_CERTIFICATE_CACHE['rows'] = rows
    PUBLIC_CERTIFICATE_CACHE['meta'] = meta
    return rows, meta


def build_public_certificate_year_options(rows):
    values = []
    for row in rows:
        year_text = str(row.get('year') or '').strip()
        if not year_text or year_text == '0':
            continue
        if year_text.isdigit():
            values.append(int(year_text))
    return [str(value) for value in sorted(set(values), reverse=True)]


def filter_public_certificate_rows(rows, query='', year=''):
    query_text = str(query or '').strip().lower()
    year_text = str(year or '').strip()
    filtered_rows = rows
    if year_text:
        filtered_rows = [row for row in filtered_rows if str(row.get('year') or '').strip() == year_text]
    if query_text:
        query_normalized = normalize_certificate_text(query_text).lower()
        filtered_rows = [
            row for row in filtered_rows
            if query_text in str(row.get('search_text') or '')
            or (query_normalized and query_normalized in str(row.get('search_text') or ''))
        ]
    return filtered_rows


def search_public_certificate_groups(rows, query='', year='', limit=50):
    query_text = str(query or '').strip().lower()
    query_normalized = normalize_certificate_text(query_text).lower() if query_text else ''
    year_text = str(year or '').strip()
    results = []
    current_name = None
    current_payload = None

    def flush_current():
        nonlocal current_payload
        if not current_payload:
            return
        certificates = sorted(
            current_payload['certificates'],
            key=lambda item: (
                str(item.get('year') or ''),
                str(item.get('subject') or ''),
                str(item.get('level') or ''),
                str(item.get('certificate_no') or ''),
            ),
            reverse=True
        )
        results.append({
            'name': current_payload['name'],
            'certificate_count': len(certificates),
            'certificates': certificates,
        })
        current_payload = None

    for row in rows:
        if year_text and str(row.get('year') or '').strip() != year_text:
            continue
        search_text = str(row.get('search_text') or '')
        if query_text:
            if query_text not in search_text and (not query_normalized or query_normalized not in search_text):
                continue
        display_name = str(row.get('display_name') or '').strip()
        if not display_name:
            continue
        if current_name != display_name:
            if current_payload is not None:
                flush_current()
                if len(results) >= int(limit or 50):
                    break
            current_name = display_name
            current_payload = {'name': display_name, 'certificates': []}
        current_payload['certificates'].append({
            'certificate_no': row.get('certificate_no', ''),
            'subject': row.get('subject', ''),
            'level': row.get('level', ''),
            'year': row.get('year', ''),
            'province': row.get('province', ''),
            'school': row.get('school', ''),
            'temple': row.get('temple', ''),
        })

    if current_payload is not None and len(results) < int(limit or 50):
        flush_current()

    return results[: int(limit or 50)]


def group_public_certificate_rows(rows):
    grouped = {}
    for row in rows:
        display_name = str(row.get('display_name') or '').strip()
        if not display_name:
            continue
        entry = grouped.setdefault(display_name, {'name': display_name, 'certificates': []})
        entry['certificates'].append({
            'certificate_no': row.get('certificate_no', ''),
            'subject': row.get('subject', ''),
            'level': row.get('level', ''),
            'year': row.get('year', ''),
            'province': row.get('province', ''),
            'school': row.get('school', ''),
            'temple': row.get('temple', ''),
        })

    results = []
    for name, payload in grouped.items():
        certificates = sorted(
            payload['certificates'],
            key=lambda item: (
                str(item.get('year') or ''),
                str(item.get('subject') or ''),
                str(item.get('level') or ''),
                str(item.get('certificate_no') or ''),
            ),
            reverse=True
        )
        results.append({
            'name': name,
            'certificate_count': len(certificates),
            'certificates': certificates,
        })
    results.sort(key=lambda item: item['name'])
    return results


CERTIFICATE_VERDICT_PASS = 'pass'
CERTIFICATE_VERDICT_REVIEW = 'review'
CERTIFICATE_VERDICT_FAIL = 'fail'


def get_certificate_department_for_class_name(class_name):
    class_name_text = str(class_name or '').strip()
    if class_name_text in set(get_department_class_names('tham')):
        return 'tham'
    if class_name_text in set(get_department_class_names('bali')):
        return 'bali'
    return ''


def parse_certificate_number_pattern(cert_no):
    text = normalize_certificate_text(cert_no)
    info = {
        'text': text,
        'pattern': 'unknown',
        'province': '',
        'area_digit': '',
        'type_digit': '',
        'education_digit': '',
        'year': '',
        'year_two': '',
        'sequence': '',
    }
    if not text:
        return info
    tham_post_match = re.match(r'^([^\d\s/]{2})\s*([1-6])([1-6])(\d{2})/(\d{4,5})$', text)
    if tham_post_match:
        info.update({
            'pattern': 'tham_post_2543',
            'province': tham_post_match.group(1),
            'area_digit': tham_post_match.group(2),
            'type_digit': tham_post_match.group(3),
            'year_two': tham_post_match.group(4),
            'sequence': tham_post_match.group(5),
            'year': f"25{tham_post_match.group(4)}",
        })
        return info
    tham_studies_post_match = re.match(r'^([^\d\s/]{2})\s*([1-6])([4-6])([1-3])(\d{2})/(\d{4,5})$', text)
    if tham_studies_post_match:
        info.update({
            'pattern': 'tham_post_2543_tham_studies_variant',
            'province': tham_studies_post_match.group(1),
            'area_digit': tham_studies_post_match.group(2),
            'type_digit': tham_studies_post_match.group(3),
            'education_digit': tham_studies_post_match.group(4),
            'year_two': tham_studies_post_match.group(5),
            'sequence': tham_studies_post_match.group(6),
            'year': f"25{tham_studies_post_match.group(5)}",
        })
        return info
    generic_match = re.match(r'^([^\d\s/]{2})\s*(\d{1,6})/(\d{4})$', text)
    if generic_match:
        info.update({
            'pattern': 'generic_slash_year',
            'province': generic_match.group(1),
            'sequence': generic_match.group(2),
            'year': generic_match.group(3),
        })
    return info


def build_certificate_verification_context(row, selected_year):
    class_name = str(row.get('class_name') or '').strip()
    expected_year = get_expected_certificate_year_for_class_name(class_name, selected_year)
    department = get_certificate_department_for_class_name(class_name)
    expected_type_digit = get_tham_certificate_type_digit_from_class_name(class_name) if department == 'tham' else ''
    try:
        expected_year_int = int(expected_year) if expected_year else 0
    except ValueError:
        expected_year_int = 0
    return {
        'class_name': class_name,
        'department': department,
        'expected_year': expected_year,
        'expected_year_two': expected_year[-2:] if expected_year else '',
        'expected_type_digit': expected_type_digit,
        'level_id': str(row.get('level_id') or CLASS_NAME_LEVEL_ID_MAP.get(class_name) or '').strip(),
        'uses_tham_post_2543_policy': department == 'tham' and expected_year_int >= 2543,
    }


def build_certificate_candidate_key(row):
    return '|'.join([
        str(row.get('source') or '').strip(),
        str(row.get('source_record_id') or '').strip(),
        str(row.get('certificate_no') or '').strip(),
        str(row.get('person_id') or '').strip(),
        str(row.get('level_id') or '').strip(),
    ])


def build_certificate_verification_lookup(rows, year):
    candidates_by_person_id = {}
    candidates_by_name_key = {}
    for row in rows:
        level_id = str(row.get('level_id') or '').strip()
        if not level_id:
            continue
        person_id = str(row.get('person_id') or '').strip()
        name_key = str(row.get('name_normalized') or '').strip()
        if person_id:
            candidates_by_person_id.setdefault(person_id, []).append(row)
        if name_key:
            candidates_by_name_key.setdefault(name_key, []).append(row)
    return {
        'candidates_by_person_id': candidates_by_person_id,
        'candidates_by_name_key': candidates_by_name_key,
    }


def get_expected_certificate_year_for_class_name(class_name, selected_year):
    class_name_text = str(class_name or '').strip()
    year_value = normalize_year_value(selected_year)
    if not class_name_text or not year_value:
        return ''
    year_int = int(year_value)
    if class_name_text in set(get_department_class_names('tham')):
        return str(year_int - 1)
    if class_name_text in set(get_department_class_names('bali')):
        return str(year_int)
    return str(year_int)


def get_certificate_identity_strength(exam_row, cert_row):
    person_id = str(exam_row.get('person_id') or '').strip()
    cert_person_id = str(cert_row.get('person_id') or '').strip()
    if person_id and cert_person_id:
        return 'person_id' if person_id == cert_person_id else 'mismatch'
    exam_name_key = build_base_name_key_from_display_name(str(exam_row.get('display_name') or '').strip()) or normalize_name_key(
        str(exam_row.get('display_name') or '').strip()
    )
    cert_name_key = str(cert_row.get('name_normalized') or '').strip()
    if exam_name_key and cert_name_key:
        return 'name' if exam_name_key == cert_name_key else 'mismatch'
    return 'none'


def get_candidate_certificate_rows(exam_row, verification_lookup):
    candidates = []
    seen = set()
    person_id = str(exam_row.get('person_id') or '').strip()
    display_name = str(exam_row.get('display_name') or '').strip()
    name_key = build_base_name_key_from_display_name(display_name) or normalize_name_key(display_name)
    for candidate in verification_lookup.get('candidates_by_person_id', {}).get(person_id, []):
        candidate_key = build_certificate_candidate_key(candidate)
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        candidates.append(candidate)
    for candidate in verification_lookup.get('candidates_by_name_key', {}).get(name_key, []):
        candidate_key = build_certificate_candidate_key(candidate)
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        candidates.append(candidate)
    return candidates


def evaluate_certificate_candidate(exam_row, cert_row, selected_year):
    """
    Decision table:
    - Placeholder/identity mismatch/level mismatch => fail
    - ธรรมตั้งแต่ 2543: ต้องเป็น format tham_post_2543 + type/year ตรง => pass
    - บาลีทุกยุค และธรรมก่อน 2543: ใช้ generic_slash_year + year ตรง => pass
    - ข้อมูลที่คน/ชั้นตรง แต่เลขหรือปีไม่เข้า policy => review
    """
    context = build_certificate_verification_context(exam_row, selected_year)
    level_id = context.get('level_id', '')
    if not level_id:
        return {'verdict': CERTIFICATE_VERDICT_FAIL, 'reason': 'missing_level'}
    if not is_meaningful_certificate_no(cert_row.get('certificate_no')):
        return {'verdict': CERTIFICATE_VERDICT_FAIL, 'reason': 'placeholder_certificate_no'}

    cert_level_id = str(cert_row.get('level_id') or '').strip()
    if not cert_level_id or cert_level_id != level_id:
        return {'verdict': CERTIFICATE_VERDICT_FAIL, 'reason': 'level_mismatch'}

    identity_strength = get_certificate_identity_strength(exam_row, cert_row)
    if identity_strength in {'mismatch', 'none'}:
        return {'verdict': CERTIFICATE_VERDICT_FAIL, 'reason': f'identity_{identity_strength}'}

    expected_year = str(context.get('expected_year') or '').strip()
    expected_year_two = str(context.get('expected_year_two') or '').strip()
    cert_year = str(cert_row.get('year') or '').strip()
    pattern_info = parse_certificate_number_pattern(cert_row.get('certificate_no'))
    parsed_year = str(pattern_info.get('year') or '').strip()
    parsed_year_two = str(pattern_info.get('year_two') or '').strip()

    row_year_matches = bool(expected_year) and cert_year == expected_year
    row_year_conflicts = bool(expected_year and cert_year and cert_year != expected_year)
    parsed_year_matches = bool(expected_year and parsed_year and parsed_year == expected_year)
    parsed_year_two_matches = bool(expected_year_two and parsed_year_two and parsed_year_two == expected_year_two)
    parsed_year_conflicts = bool(
        expected_year and (
            (parsed_year and parsed_year != expected_year) or
            (parsed_year_two and parsed_year_two != expected_year_two)
        )
    )

    if context.get('uses_tham_post_2543_policy'):
        type_digit_matches = str(pattern_info.get('type_digit') or '').strip() == str(context.get('expected_type_digit') or '').strip()
        if (
            pattern_info.get('pattern') in {'tham_post_2543', 'tham_post_2543_tham_studies_variant'}
            and type_digit_matches
            and (row_year_matches or parsed_year_two_matches)
            and not row_year_conflicts
            and not parsed_year_conflicts
        ):
            return {'verdict': CERTIFICATE_VERDICT_PASS, 'reason': f'tham_post_2543_{identity_strength}'}
        if identity_strength in {'person_id', 'name'}:
            return {'verdict': CERTIFICATE_VERDICT_REVIEW, 'reason': 'tham_post_2543_review'}
        return {'verdict': CERTIFICATE_VERDICT_FAIL, 'reason': 'tham_post_2543_fail'}

    if context.get('department') in {'bali', 'tham'}:
        if (
            pattern_info.get('pattern') == 'generic_slash_year'
            and (row_year_matches or parsed_year_matches)
            and not row_year_conflicts
            and not parsed_year_conflicts
        ):
            return {'verdict': CERTIFICATE_VERDICT_PASS, 'reason': f'generic_slash_year_{identity_strength}'}
        if identity_strength in {'person_id', 'name'} and (row_year_matches or parsed_year_matches):
            return {'verdict': CERTIFICATE_VERDICT_REVIEW, 'reason': 'generic_year_review'}
        if identity_strength in {'person_id', 'name'}:
            return {'verdict': CERTIFICATE_VERDICT_REVIEW, 'reason': 'generic_identity_review'}

    return {'verdict': CERTIFICATE_VERDICT_FAIL, 'reason': 'no_matching_policy'}


def get_certificate_verification_decision(row, verification_lookup, selected_year=''):
    best_decision = {'verdict': CERTIFICATE_VERDICT_FAIL, 'reason': 'no_candidate'}
    verdict_priority = {
        CERTIFICATE_VERDICT_PASS: 3,
        CERTIFICATE_VERDICT_REVIEW: 2,
        CERTIFICATE_VERDICT_FAIL: 1,
    }
    for candidate in get_candidate_certificate_rows(row, verification_lookup):
        decision = evaluate_certificate_candidate(row, candidate, selected_year)
        if verdict_priority[decision['verdict']] > verdict_priority[best_decision['verdict']]:
            best_decision = decision
        if decision['verdict'] == CERTIFICATE_VERDICT_PASS:
            return decision
    return best_decision


def row_has_verified_certificate_from_layer(row, verification_lookup, selected_year=''):
    decision = get_certificate_verification_decision(row, verification_lookup, selected_year)
    return decision.get('verdict') == CERTIFICATE_VERDICT_PASS


def cert_matches_bali_year(cert_text, expected_year):
    text = normalize_certificate_text(cert_text)
    if not text:
        return False
    expected = str(int(expected_year))
    return re.search(r'/' + re.escape(expected) + r'(?!\d)', text) is not None


def cert_matches_tham_year(cert_text, expected_year_two_digits):
    text = normalize_certificate_text(cert_text)
    if not text:
        return False
    expected_year = str(expected_year_two_digits).zfill(2)
    match = re.search(r'(\d{4})\s*/\s*(\d{4,5})', text)
    prefix = str(match.group(1) if match else '').strip()
    if len(prefix) != 4 or not prefix.isdigit():
        return False
    year_two = prefix[2:4]
    return year_two == expected_year


def get_tham_certificate_type_digit_from_class_name(class_name):
    text = str(class_name or '').strip()
    mapping = {
        'น.ธ.ตรี': '1',
        'น.ธ.โท': '2',
        'น.ธ.เอก': '3',
        'ธ.ศ.ตรี': '4',
        'ธ.ศ.โท': '5',
        'ธ.ศ.เอก': '6',
    }
    return mapping.get(text, '')


def cert_matches_tham_year_and_type(cert_text, expected_year_two_digits, expected_type_digit):
    text = normalize_certificate_text(cert_text)
    if not text:
        return False
    expected_year = str(expected_year_two_digits).zfill(2)
    expected_type = str(expected_type_digit or '').strip()
    match = re.search(r'(\d{4})\s*/\s*(\d{4,5})', text)
    prefix = str(match.group(1) if match else '').strip()
    if len(prefix) != 4 or not prefix.isdigit():
        return False
    type_digit = prefix[1:2]
    year_two = prefix[2:4]
    if expected_type and type_digit != expected_type:
        return False
    return year_two == expected_year


def get_expected_certificate_years(selected_year_value):
    year_int = int(normalize_year_value(selected_year_value) or CURRENT_YEAR_NUMERIC)
    expected_bali_year = year_int
    expected_tham_year_two = str(year_int - 1)[-2:]
    return expected_bali_year, expected_tham_year_two


def normalize_name_key(value):
    if value is None or pd.isna(value):
        return ''
    text = str(value).strip()
    if not text:
        return ''
    text = text.replace('_', ' ').replace('-', ' ')
    text = text.replace('(', ' ').replace(')', ' ')
    text = NAME_KEY_SPACE_RE.sub('', text)
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
    match = DISPLAY_NAME_PAREN_CONTENT_RE.search(text)
    if match and (match.group(1) or '').strip():
        last_name = match.group(1).strip()
        without_parentheses = DISPLAY_NAME_PAREN_BLOCK_RE.sub(' ', text).strip()
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
    match = DISPLAY_NAME_PAREN_CONTENT_RE.search(text)
    if match and (match.group(1) or '').strip():
        return match.group(1).strip()
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


def load_data_source_settings():
    if not os.path.exists(DATA_SOURCE_SETTINGS_FILE):
        return {}
    try:
        with open(DATA_SOURCE_SETTINGS_FILE, 'r', encoding='utf-8') as fp:
            settings = json.load(fp)
        if isinstance(settings, dict):
            return settings
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_data_source_settings(settings):
    if not isinstance(settings, dict):
        return False
    os.makedirs(RESULTS_DATA_DIR, exist_ok=True)
    with open(DATA_SOURCE_SETTINGS_FILE, 'w', encoding='utf-8') as fp:
        json.dump(settings, fp, ensure_ascii=False)
    return True


def get_effective_snapshot_lock_max_year():
    settings = load_data_source_settings()
    override_value = settings.get('snapshot_lock_max_year')
    override_year = normalize_year_value(override_value)
    if override_year:
        return int(override_year)
    return API_SNAPSHOT_LOCK_MAX_YEAR


def get_snapshot_lock_status(year):
    year_value = normalize_year_value(year) or CURRENT_YEAR_NUMERIC
    runtime_current_year = int(get_runtime_current_year_numeric())
    lock_max_year = get_effective_snapshot_lock_max_year()
    settings = load_data_source_settings()
    override_year = normalize_year_value(settings.get('snapshot_lock_max_year'))
    locked = False
    reason = ''
    if int(year_value) < runtime_current_year:
        locked = True
        reason = 'past_year'
    if lock_max_year is not None and int(year_value) <= int(lock_max_year):
        locked = True
        reason = 'override' if override_year else 'lock_max_year'
    return {
        'locked': locked,
        'reason': reason,
        'year': int(year_value),
        'runtime_current_year': runtime_current_year,
        'lock_max_year': int(lock_max_year) if lock_max_year is not None else None,
        'override_lock_max_year': int(override_year) if override_year else None
    }


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
    now_dt = datetime.now(fetched_dt.tzinfo) if fetched_dt.tzinfo else datetime.now()
    age = now_dt - fetched_dt
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
    return year_file


def list_available_years():
    years = set()
    years.add(int(CURRENT_YEAR_NUMERIC))
    if CURRENT_YEAR_NUMERIC and int(CURRENT_YEAR_NUMERIC) > 1:
        years.add(int(CURRENT_YEAR_NUMERIC) - 1)
    try:
        current_year_int = int(CURRENT_YEAR_NUMERIC)
        next_year_int = current_year_int + 1
        next_exam_file = get_exam_results_file(next_year_int)
        next_snapshot_file = get_api_snapshot_file(next_year_int)
        today = datetime.now()
        should_include_next_year = int(today.month) < 6
        if not should_include_next_year:
            should_include_next_year = os.path.exists(next_exam_file) or os.path.exists(next_snapshot_file)
        if should_include_next_year:
            years.add(next_year_int)
    except Exception:
        pass
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
        totals = {
            'sent': 0,
            'absent': 0,
            'disqualified': 0,
            'active': 0,
            'pass_main': 0,
            'remedial': 0,
            'remedial_pass': 0,
            'total_pass': 0,
            'fail': 0
        }
        for class_name in ordered_classes:
            class_df = filtered_df[filtered_df['class_name'] == class_name]
            status_series = class_df['exam_result_status'].fillna('').astype(str)
            sent_count = int(len(class_df))
            absent_count = int((status_series == 'ขาดสอบ').sum())
            disqualified_count = int((status_series == 'ขาดสิทธิ์').sum())
            active_count = int(sent_count - absent_count - disqualified_count)
            pass_count = int((status_series == 'สอบได้').sum())
            remedial_pass_count = int((status_series == 'สอบซ่อมได้').sum())
            remedial_count = int(status_series.isin({'สอบซ่อม', 'สอบซ่อมได้'}).sum())
            total_pass_count = int(pass_count + remedial_pass_count)
            fail_count = max(int(active_count) - int(total_pass_count), 0)
            pass_rate = (total_pass_count / sent_count * 100) if sent_count > 0 else None
            summary_rows.append({
                'class_name': class_name,
                'sent': sent_count,
                'absent': absent_count,
                'disqualified': disqualified_count,
                'active': active_count,
                'pass_main': pass_count,
                'total_pass': total_pass_count,
                'remedial': remedial_count,
                'remedial_pass': remedial_pass_count,
                'pass': total_pass_count,
                'fail': fail_count,
                'pass_rate': pass_rate
            })
            totals['sent'] += sent_count
            totals['absent'] += absent_count
            totals['disqualified'] += disqualified_count
            totals['active'] += active_count
            totals['pass_main'] += pass_count
            totals['remedial'] += remedial_count
            totals['remedial_pass'] += remedial_pass_count
            totals['total_pass'] += total_pass_count
            totals['fail'] += fail_count

        stats['pass_summary'] = {
            'rows': summary_rows,
            'total': {
                'sent': int(totals['sent']),
                'absent': int(totals['absent']),
                'disqualified': int(totals['disqualified']),
                'active': int(totals['active']),
                'remedial': int(totals['remedial']),
                'remedial_pass': int(totals['remedial_pass']),
                'pass_main': int(totals['pass_main']),
                'total_pass': int(totals['total_pass']),
                'pass': int(totals['total_pass']),
                'fail': int(totals['fail']),
                'pass_rate': (totals['total_pass'] / totals['sent'] * 100) if totals['sent'] > 0 else None
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
    group_descriptions = get_effective_pass_summary_group_descriptions()
    try:
        visitor_counter = get_visitor_counts()
    except Exception:
        logging.exception('visitor analytics read error')
        visitor_counter = {'visitors_today': 0, 'total_unique_visitors': 0, 'total_pageviews': 0}
    current_year_numeric = int(CURRENT_YEAR_NUMERIC)
    return {
        'staff_logged_in': is_staff_logged_in(),
        'security_hardened': is_security_hardened(),
        'is_admin': is_admin,
        'static_asset_url': static_asset_url,
        'group_descriptions': group_descriptions,
        'to_thai_digits': to_thai_digits,
        'current_year_numeric': current_year_numeric,
        'current_academic_year_label': f"{to_thai_digits(current_year_numeric - 1)}-{to_thai_digits(current_year_numeric)}",
        'current_mode': get_current_mode(),
        'visitor_counter': visitor_counter
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


PASS_SUMMARY_GROUP_ORDER = ['กลุ่ม ๑', 'กลุ่ม ๒', 'กลุ่ม ๓', 'กลุ่ม ๔', 'กลุ่ม ๕', 'ไม่ระบุ']
PASS_SUMMARY_ABSENT_STATUSES = {'ขาดสอบ', 'ขาดสิทธิ์'}
PASS_SUMMARY_PASS_STATUSES = {'สอบได้', 'สอบซ่อมได้'}
PASS_SUMMARY_GROUP_DESCRIPTIONS = {
    'กลุ่ม ๑': '- สมาชิกองค์กรภายในวัด สำนักพระปริยัติธรรม - สามเณรประจำหมู่กุฏิสามเณรเปรียญธรรม',
    'กลุ่ม ๒': '- สมาชิกองค์กรภายในวัด ทุกสำนัก - สมาชิกองค์กรศูนย์สาขาต่างประเทศทั่วโลก - (ยกเว้น สำนักพระปริยัติธรรม) - (ยกเว้น สำนักการศึกษา)',
    'กลุ่ม ๓': '- สมาชิกศูนย์ส่งเสริมศีลธรรมจังหวัดทั่วประเทศ - พระภิกษุ-สามเณร วัดสาขาทั่วประเทศ',
    'กลุ่ม ๔': '- พระภิกษุ-สามเณร นิสิตปัจจุบันสถาบันธรรมชัย - สมาชิกองค์กร สำนักการศึกษา - สามเณรโรงเรียนเตรียมพุทธศาสตร์ (เขาแก้วเสด็จ)',
    'กลุ่ม ๕': '- พระภิกษุ-สามเณรทั่วไป (วัดอื่นๆ) - พระกัลยาณมิตร - สาธุชนทั่วไป',
    'ไม่ระบุ': '-',
}
PASS_SUMMARY_GROUP_MAP = {
    'None': 'ไม่ระบุ',
    '': 'ไม่ระบุ',
    'ไม่ระบุ': 'ไม่ระบุ',
    'พระภิกษุ/สามเณรวัดสาขา': 'กลุ่ม ๓',
    'พระภิกษุประจำหน่วยงาน': 'กลุ่ม ๒',
    'เจ้าหน้าที่ภายในองค์กร': 'กลุ่ม ๒',
    'สามเณรปริยัติสามัญ': 'กลุ่ม ๔',
    'พระนิสิตปัจจุบันสถาบันธรรมชัย': 'กลุ่ม ๔',
    'สามเณรเปรียญธรรม': 'กลุ่ม ๑',
    'พระมหาเปรียญธรรม': 'กลุ่ม ๑',
    'สาธุชนทั่วไป': 'กลุ่ม ๕'
}


def normalize_pass_summary_group(group_name):
    group_text = str(group_name or '').strip()
    if group_text in {'กลุ่ม ๑', 'กลุ่ม ๒', 'กลุ่ม ๓', 'กลุ่ม ๔', 'กลุ่ม ๕'}:
        return group_text
    return PASS_SUMMARY_GROUP_MAP.get(group_text, 'ไม่ระบุ')


def get_effective_pass_summary_group_descriptions():
    base = {}
    if isinstance(bali_summary_data, dict):
        loaded = bali_summary_data.get('group_descriptions') or {}
        if isinstance(loaded, dict):
            base = dict(loaded)
    base.update(PASS_SUMMARY_GROUP_DESCRIPTIONS)
    return base


def build_pass_summary(
    summary_df,
    class_name,
    certificate_lookup=None,
    selected_year=None,
    expected_bali_year='',
    expected_tham_year_two='',
    tham_class_names=None,
    bali_class_names=None,
):
    if summary_df is None or summary_df.empty or not class_name:
        return None
    tham_class_names = set(tham_class_names or set())
    bali_class_names = set(bali_class_names or set())

    group_rows = {}
    totals = {
        'ส่งสอบ': 0,
        'ขาดสอบ': 0,
        'ขาดสิทธิ์': 0,
        'คงสอบ': 0,
        'สอบได้': 0,
        'สอบได้_ปกศ': 0,
        'สอบซ่อม': 0,
        'สอบซ่อมได้': 0,
        'สอบซ่อมได้_ปกศ': 0,
        'รวมสอบได้': 0,
        'รวมสอบได้_ปกศ': 0,
        'สอบตก': 0
    }

    def evaluate_row_certificate_ok(row):
        if certificate_lookup is None or not selected_year:
            return False
        class_name_value = str(row.get('class_name') or '').strip()
        cert_decision = get_certificate_verification_decision(row, certificate_lookup, selected_year)
        cert_ok = cert_decision.get('verdict') == CERTIFICATE_VERDICT_PASS
        if not cert_ok:
            if class_name_value in bali_class_names:
                cert_ok = cert_matches_bali_year(row.get('cert_pali_text'), expected_bali_year)
            elif class_name_value in tham_class_names:
                tham_type_digit = get_tham_certificate_type_digit_from_class_name(class_name_value)
                cert_ok = cert_matches_tham_year_and_type(row.get('cert_nugdham_text'), expected_tham_year_two, tham_type_digit)
        return bool(cert_ok)

    for group_name in PASS_SUMMARY_GROUP_ORDER:
        group_df = summary_df[summary_df['summary_group'] == group_name]
        status_series = group_df['exam_result_status'].fillna('').astype(str)
        sent_count = int(len(group_df))
        absent_count = int((status_series == 'ขาดสอบ').sum())
        disqualified_count = int((status_series == 'ขาดสิทธิ์').sum())
        active_count = int(sent_count - absent_count - disqualified_count)
        pass_count = int((status_series == 'สอบได้').sum())
        remedial_pass_count = int((status_series == 'สอบซ่อมได้').sum())
        remedial_count = int(status_series.isin({'สอบซ่อม', 'สอบซ่อมได้'}).sum())
        total_pass_count = int(pass_count + remedial_pass_count)
        fail_count = max(int(active_count) - int(total_pass_count), 0)

        pass_cert_ok_count = 0
        remedial_pass_cert_ok_count = 0
        if certificate_lookup is not None and selected_year:
            for _, row in group_df.iterrows():
                status_value = str(row.get('exam_result_status') or '').strip()
                if status_value not in PASS_SUMMARY_PASS_STATUSES:
                    continue
                if not evaluate_row_certificate_ok(row):
                    continue
                if status_value == 'สอบได้':
                    pass_cert_ok_count += 1
                elif status_value == 'สอบซ่อมได้':
                    remedial_pass_cert_ok_count += 1
        total_pass_cert_ok_count = int(pass_cert_ok_count + remedial_pass_cert_ok_count)

        group_rows[group_name] = {
            'ส่งสอบ': sent_count,
            'ขาดสอบ': absent_count,
            'ขาดสิทธิ์': disqualified_count,
            'คงสอบ': active_count,
            'สอบได้': pass_count,
            'สอบได้_ปกศ': pass_cert_ok_count,
            'สอบซ่อม': remedial_count,
            'สอบซ่อมได้': remedial_pass_count,
            'สอบซ่อมได้_ปกศ': remedial_pass_cert_ok_count,
            'รวมสอบได้': total_pass_count,
            'รวมสอบได้_ปกศ': total_pass_cert_ok_count,
            'สอบตก': fail_count
        }
        for key in totals:
            totals[key] += int(group_rows[group_name].get(key, 0) or 0)

    return {
        'class_name': class_name,
        'class_data': {
            'groups': group_rows,
            'total': totals
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
            try:
                runtime_current_year = int(get_runtime_current_year_numeric())
                target_year_int = int(normalize_year_value(year) or CURRENT_YEAR_NUMERIC)
            except Exception:
                runtime_current_year = int(CURRENT_YEAR_NUMERIC)
                target_year_int = int(CURRENT_YEAR_NUMERIC)

            if target_year_int >= runtime_current_year and loaded_data and os.path.exists(RESULTS_FILE):
                try:
                    with open(RESULTS_FILE, 'r', encoding='utf-8') as fp:
                        legacy_data = json.load(fp)
                except (OSError, json.JSONDecodeError):
                    legacy_data = None

                if isinstance(legacy_data, dict) and legacy_data == loaded_data:
                    return {}
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
    if isinstance(result_map, dict) and result_map and 'id_card' in dataframe.columns and 'class_name' in dataframe.columns:
        legacy_index = {}
        legacy_conflicts = set()
        for legacy_key, legacy_status in result_map.items():
            key_text = str(legacy_key or '')
            if key_text.startswith('cid=') or key_text.startswith('name='):
                continue
            parts = [part.strip() for part in key_text.split('|') if part is not None]
            if len(parts) < 3:
                continue
            class_part = str(parts[1] or '').strip()
            id_part = str(parts[-2] or '').strip() if len(parts) >= 2 else ''
            if not class_part or not id_part or id_part.lower() in {'none', 'nan', 'null'}:
                continue
            idx_key = (id_part, class_part)
            if idx_key in legacy_index and legacy_index[idx_key] != legacy_status:
                legacy_conflicts.add(idx_key)
                continue
            legacy_index[idx_key] = legacy_status
        if legacy_conflicts:
            for conflict_key in legacy_conflicts:
                legacy_index.pop(conflict_key, None)
        if legacy_index:
            missing_mask = dataframe['exam_result_status'].astype(str).fillna('') == ''
            if missing_mask.any():
                id_series = dataframe.loc[missing_mask, 'id_card'].astype(str).fillna('').str.strip()
                class_series = dataframe.loc[missing_mask, 'class_name'].astype(str).fillna('').str.strip()
                mapped = [
                    legacy_index.get((id_val, class_val), '')
                    for id_val, class_val in zip(id_series.tolist(), class_series.tolist())
                ]
                dataframe.loc[missing_mask, 'exam_result_status'] = [
                    mapped_val if mapped_val else existing_val
                    for mapped_val, existing_val in zip(mapped, dataframe.loc[missing_mask, 'exam_result_status'].tolist())
                ]
    try:
        runtime_current_year = int(get_runtime_current_year_numeric())
        target_year_int = int(normalize_year_value(year_value) or CURRENT_YEAR_NUMERIC)
    except Exception:
        runtime_current_year = int(CURRENT_YEAR_NUMERIC)
        target_year_int = int(CURRENT_YEAR_NUMERIC)

    if target_year_int < runtime_current_year:
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
    required_columns = [
        'sequence_thai', 'display_name', 'age_num', 'pansa_num', 'monk_year_num', 'monk_month_num',
        'monk_day_num', 'ordain_after_num', 'dob_year_num', 'dob_month_num', 'dob_day_num',
        'age_thai', 'pansa_thai', 'age_pansa', 'ordain_sort_key', 'birth_sort_key', 'reg_status',
        'class_name', 'level_type', 'level_id', 'person_id', 'school_name', 'group_name',
        'cert_nugdham_text', 'cert_pali_text', 'id_card', 'tel', 'registration_key', 'result_key'
    ]
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
                'level_type': str(manual_item.get('level_type') or ''),
                'level_id': str(manual_item.get('level_id') or ''),
                'person_id': str(manual_item.get('person_id') or ''),
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


def load_data_from_api(year=None, store_global=True, force_refresh=False, allow_locked_refresh=False):
    global df
    API_URL = os.getenv('PARIYAT_API_URL', "https://app.pariyat.com/pages/postx/name_json.php")
    API_USER = (os.getenv('PARIYAT_API_USER') or '').strip()
    API_PASS = (os.getenv('PARIYAT_API_PASS') or '').strip()
    target_year_numeric = int(year or CURRENT_YEAR_NUMERIC)
    runtime_current_year = get_runtime_current_year_numeric()
    snapshot_lock_max_year = get_effective_snapshot_lock_max_year()
    locked_year = (snapshot_lock_max_year is not None and target_year_numeric <= snapshot_lock_max_year) or (target_year_numeric < runtime_current_year)
    
    def fetch_exam_api_rows(fetch_year_numeric):
        response = requests.get(
            API_URL,
            params={'user': API_USER, 'pass': API_PASS, 'filter_year': int(fetch_year_numeric)},
            timeout=60
        )
        response.raise_for_status()
        json_data = response.json()
        if json_data.get('status') != 'success' or 'data' not in json_data:
            raise RuntimeError('Invalid exam API payload')
        api_rows = json_data.get('data') or []
        if not isinstance(api_rows, list):
            raise RuntimeError('Invalid exam API data list')
        return api_rows

    def has_any_level_type(api_rows, allowed_level_types):
        for item in api_rows or []:
            level_type = str((item or {}).get('level_type') or '').strip()
            if level_type in allowed_level_types:
                return True
        return False

    def ensure_combined_api_rows_for_academic_year(api_rows):
        has_tham = has_any_level_type(api_rows, THAM_LEVEL_TYPES)
        has_bali = has_any_level_type(api_rows, BALI_LEVEL_TYPES)
        if has_tham and has_bali:
            return api_rows
        if has_bali and not has_tham:
            try:
                prev_rows = fetch_exam_api_rows(target_year_numeric - 1)
            except Exception:
                return api_rows
            tham_rows = [
                item for item in (prev_rows or [])
                if str((item or {}).get('level_type') or '').strip() in THAM_LEVEL_TYPES
            ]
            if not tham_rows:
                return api_rows
            return list(api_rows or []) + tham_rows
        return api_rows

    try:
        snapshot = None
        snapshot = load_api_snapshot(target_year_numeric)
        if not force_refresh and snapshot:
            if locked_year or is_snapshot_fresh(snapshot):
                result_df = build_processed_df_from_api_rows(snapshot.get('data') or [], target_year_numeric, store_global)
                print(f"--- [SUCCESS] Data loaded from snapshot (fresh). Final records: {len(result_df)}")
                return result_df

        if locked_year and snapshot and not allow_locked_refresh:
            raise RuntimeError('Snapshot is locked for this year; not refreshing from API')

        if not API_USER or not API_PASS:
            raise RuntimeError('Missing PARIYAT_API_USER or PARIYAT_API_PASS')

        api_rows = fetch_exam_api_rows(target_year_numeric)
        api_rows = ensure_combined_api_rows_for_academic_year(api_rows)
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
        lock_max_year = get_effective_snapshot_lock_max_year()
        if (lock_max_year is not None and int(year_value) <= int(lock_max_year)) or int(year_value) < int(get_runtime_current_year_numeric()):
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
    query = str(request.args.get('q', '') or '').strip()
    if query == '':
        return jsonify([])
    year_value = normalize_year_value(request.args.get('year')) or CURRENT_YEAR_NUMERIC
    mode = get_mode_value(request.args.get('mode'))
    base_df = get_df_for_year(year_value)
    if base_df is None or base_df.empty:
        return jsonify([])
    base_df = filter_df_by_mode(base_df, mode)
    if base_df is None or base_df.empty:
        return jsonify([])
    tham_class_names = set(get_department_class_names('tham'))
    bali_class_names = set(get_department_class_names('bali'))
    expected_bali_year, expected_tham_year_two = get_expected_certificate_years(year_value)
    certificate_rows, _certificate_meta = load_public_certificate_rows()
    certificate_lookup = build_certificate_verification_lookup(certificate_rows, year_value)
    results_df = base_df[base_df['display_name'].str.contains(query, case=False, na=False)]
    if results_df.empty:
        return jsonify([])
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
        
        registrations = []
        for _, row in group.iterrows():
            class_name = str(row.get('class_name') or '').strip()
            cert_decision = get_certificate_verification_decision(row, certificate_lookup, year_value)
            cert_ok_from_layer = cert_decision.get('verdict') == CERTIFICATE_VERDICT_PASS
            tham_type_digit = get_tham_certificate_type_digit_from_class_name(class_name) if class_name in tham_class_names else ''
            cert_nugdham_ok = class_name in tham_class_names and cert_matches_tham_year_and_type(
                row.get('cert_nugdham_text'),
                expected_tham_year_two,
                tham_type_digit
            )
            cert_pali_ok = class_name in bali_class_names and cert_matches_bali_year(row.get('cert_pali_text'), expected_bali_year)
            if cert_ok_from_layer:
                if class_name in tham_class_names:
                    cert_nugdham_ok = True
                elif class_name in bali_class_names:
                    cert_pali_ok = True
            registrations.append({
                'class_name': row['class_name'],
                'reg_status': row['reg_status'],
                'sequence': row['sequence_thai'],
                'cert_nugdham': to_thai_digits(row['cert_nugdham_text']),
                'cert_pali': to_thai_digits(row['cert_pali_text']),
                'cert_nugdham_current_ok': bool(cert_nugdham_ok),
                'cert_pali_current_ok': bool(cert_pali_ok),
                'cert_verdict': cert_decision.get('verdict'),
                'cert_verdict_reason': cert_decision.get('reason'),
            })

        person_data = {
            'name': name, 'age_pansa': first_row['age_pansa'],
            'school_name': to_thai_digits(first_row['school_name']),
            'group_name': to_thai_digits(first_row['group_name']),
            'id_status_text': id_status_text,
            'tel_masked_text': tel_masked_text,
            'tel_cleaned': tel_cleaned,
            'registrations': registrations
        }
        final_results.append(person_data)
    return jsonify(final_results)


@app.route('/certificates')
def public_certificates():
    selected_year = str(request.args.get('year', '') or '').strip()
    try:
        rows, meta = load_public_certificate_rows()
        available_years = build_public_certificate_year_options(rows)
    except Exception:
        logging.exception('public certificate page error')
        meta = {'timestamp': '-', 'certificate_count': '', 'person_count': '', 'source': ''}
        available_years = []
    if selected_year and selected_year not in available_years:
        available_years = [selected_year] + available_years
    return render_template('certificates.html', selected_year=selected_year, available_years=available_years, certificate_data_info=meta)


@app.route('/api/certificates/info')
def public_certificates_info():
    try:
        rows, meta = load_public_certificate_rows()
        return jsonify({
            'timestamp': meta.get('timestamp', '-'),
            'certificate_count': int(meta.get('certificate_count') or 0),
            'person_count': int(meta.get('person_count') or 0),
            'source': meta.get('source', ''),
            'available_years': build_public_certificate_year_options(rows),
        })
    except Exception as exc:
        logging.exception('public certificate info error')
        return jsonify({
            'timestamp': '-',
            'certificate_count': 0,
            'person_count': 0,
            'source': '',
            'available_years': [],
            'error': str(exc),
        }), 500


@app.route('/api/certificates/search')
def public_certificates_search():
    query = str(request.args.get('q', '') or '').strip()
    selected_year = str(request.args.get('year', '') or '').strip()
    if not query and not selected_year:
        return jsonify([])
    try:
        rows, _meta = load_public_certificate_rows()
        return jsonify(search_public_certificate_groups(rows, query=query, year=selected_year, limit=50))
    except Exception as exc:
        logging.exception('public certificate search error')
        return jsonify({'results': [], 'error': str(exc)}), 500


@app.route('/get_classes')
@staff_login_required(api=True)
def get_classes():
    selected_year = get_selected_year()
    year_df = get_df_for_year(selected_year)
    if year_df is None or year_df.empty:
        return jsonify([])
    mode = get_mode_value(request.args.get('mode'))
    year_df = filter_df_by_mode(year_df, mode)
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
    mode = get_mode_value(request.args.get('mode'))
    results_df = filter_df_by_mode(year_df.copy(), mode)
    if results_df is None or results_df.empty:
        return jsonify([])
    
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
    current_year_numeric = int(CURRENT_YEAR_NUMERIC)
    mode = get_current_mode()
    selected_year = normalize_year_value(request.args.get('year')) or current_year_numeric
    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)
    snapshot_lock = get_snapshot_lock_status(selected_year)
    return render_template(
        'index.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=current_year_numeric,
        selected_year=selected_year,
        available_years=available_years,
        mode=mode,
        snapshot_lock=snapshot_lock
    )


@app.route('/pass-list')
def pass_list():
    current_year_thai = get_current_buddhist_year(numeric=False)
    current_year_numeric = CURRENT_YEAR_NUMERIC
    
    selected_year = normalize_year_value(request.args.get('year')) or current_year_numeric
    mode = get_mode_value(request.args.get('mode'))
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
    snapshot_lock = get_snapshot_lock_status(selected_year)
    
    year_df = get_df_for_year(selected_year)
    year_df = filter_df_by_mode(year_df, mode)
    if year_df is not None and not year_df.empty:
        names_map = load_exam_names_for_year(selected_year)
        tham_class_names = set(get_department_class_names('tham'))
        bali_class_names = set(get_department_class_names('bali'))
        expected_bali_year, expected_tham_year_two = get_expected_certificate_years(selected_year)
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

        pass_df = summary_df.copy()
        
        if selected_status:
            if selected_status == 'สอบซ่อม (รวมสอบซ่อมได้)':
                pass_df = pass_df[pass_df['exam_result_status'].isin(['สอบซ่อม', 'สอบซ่อมได้'])]
            else:
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
        certificate_rows, _certificate_meta = load_public_certificate_rows()
        certificate_lookup = build_certificate_verification_lookup(certificate_rows, selected_year)
        if selected_level:
            pass_summary = build_pass_summary(
                summary_df,
                selected_level,
                certificate_lookup=certificate_lookup,
                selected_year=selected_year,
                expected_bali_year=expected_bali_year,
                expected_tham_year_two=expected_tham_year_two,
                tham_class_names=tham_class_names,
                bali_class_names=bali_class_names,
            )
        
        for _, row in pass_df.iterrows():
            lookup_key = row.get('result_key') or row.get('registration_key')
            exam_name = names_map.get(str(lookup_key or ''), '')
            class_name = str(row.get('class_name') or '').strip()
            cert_decision = get_certificate_verification_decision(row, certificate_lookup, selected_year)
            cert_ok = cert_decision.get('verdict') == CERTIFICATE_VERDICT_PASS
            if not cert_ok:
                if class_name in bali_class_names:
                    cert_ok = cert_matches_bali_year(row.get('cert_pali_text'), expected_bali_year)
                elif class_name in tham_class_names:
                    tham_type_digit = get_tham_certificate_type_digit_from_class_name(class_name)
                    cert_ok = cert_matches_tham_year_and_type(row.get('cert_nugdham_text'), expected_tham_year_two, tham_type_digit)
            pass_results.append({
                'name': row['display_name'],
                'exam_name': exam_name,
                'class_name': row['class_name'],
                'sequence': row['sequence_thai'],
                'age': row.get('age_thai', '-'),
                'pansa': row.get('pansa_thai', '-'),
                'school_name': to_thai_digits(row['school_name']),
                'group_name': to_thai_digits(row['group_name']),
                'result_status': row['exam_result_status'],
                'cert_current_year_ok': cert_ok
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
        available_statuses=available_statuses,
        snapshot_lock=snapshot_lock
    )


@app.route('/statistics')
def public_statistics():
    current_year_thai = get_current_buddhist_year(numeric=False)
    selected_year = normalize_year_value(request.args.get('year')) or CURRENT_YEAR_NUMERIC
    mode = get_mode_value(request.args.get('mode'))

    if mode == MODE_THAM:
        return redirect(url_for('public_statistics_tham', mode=mode, year=selected_year))
    if mode == MODE_BALI:
        return redirect(url_for('public_statistics_bali', mode=mode, year=selected_year))

    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)
    stats = get_statistics(year=selected_year)
    snapshot_lock = get_snapshot_lock_status(selected_year)
    return render_template(
        'statistics.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=selected_year,
        available_years=available_years,
        statistics=stats,
        department_levels=DEPARTMENT_LEVELS,
        snapshot_lock=snapshot_lock
    )


@app.route('/statistics/tham')
def public_statistics_tham():
    current_year_thai = get_current_buddhist_year(numeric=False)
    selected_year = normalize_year_value(request.args.get('year')) or CURRENT_YEAR_NUMERIC
    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)
    level_ids = []
    for subsection in DEPARTMENT_LEVELS.get('tham', {}).get('subsections', {}).values():
        level_ids.extend(subsection.get('levels', []) or [])
    stats = get_statistics(level_ids=level_ids, year=selected_year)
    snapshot_lock = get_snapshot_lock_status(selected_year)
    return render_template(
        'statistics_department.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=selected_year,
        available_years=available_years,
        statistics=stats,
        department_key='tham',
        department=DEPARTMENT_LEVELS['tham'],
        snapshot_lock=snapshot_lock
    )


@app.route('/statistics/tham/<subsection>')
def public_statistics_tham_subsection(subsection):
    current_year_thai = get_current_buddhist_year(numeric=False)
    selected_year = normalize_year_value(request.args.get('year')) or CURRENT_YEAR_NUMERIC
    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)
    if subsection not in DEPARTMENT_LEVELS['tham']['subsections']:
        return redirect(url_for('public_statistics_tham', mode=MODE_THAM, year=selected_year))

    subsection_data = DEPARTMENT_LEVELS['tham']['subsections'][subsection]
    stats = get_statistics(subsection_data['levels'], year=selected_year)
    snapshot_lock = get_snapshot_lock_status(selected_year)
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
        statistics=stats,
        snapshot_lock=snapshot_lock
    )


@app.route('/statistics/bali')
def public_statistics_bali():
    current_year_thai = get_current_buddhist_year(numeric=False)
    selected_year = normalize_year_value(request.args.get('year')) or CURRENT_YEAR_NUMERIC
    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)
    level_ids = []
    for subsection in DEPARTMENT_LEVELS.get('bali', {}).get('subsections', {}).values():
        level_ids.extend(subsection.get('levels', []) or [])
    stats = get_statistics(level_ids=level_ids, year=selected_year)
    snapshot_lock = get_snapshot_lock_status(selected_year)
    return render_template(
        'statistics_department.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=selected_year,
        available_years=available_years,
        statistics=stats,
        department_key='bali',
        department=DEPARTMENT_LEVELS['bali'],
        snapshot_lock=snapshot_lock
    )


@app.route('/statistics/bali/<subsection>')
def public_statistics_bali_subsection(subsection):
    current_year_thai = get_current_buddhist_year(numeric=False)
    selected_year = normalize_year_value(request.args.get('year')) or CURRENT_YEAR_NUMERIC
    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)
    if subsection not in DEPARTMENT_LEVELS['bali']['subsections']:
        return redirect(url_for('public_statistics_bali', mode=MODE_BALI, year=selected_year))

    subsection_data = DEPARTMENT_LEVELS['bali']['subsections'][subsection]
    stats = get_statistics(subsection_data['levels'], year=selected_year)
    snapshot_lock = get_snapshot_lock_status(selected_year)
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
        statistics=stats,
        snapshot_lock=snapshot_lock
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
    mode = get_mode_value(request.args.get('mode'))
    if mode == MODE_THAM:
        return redirect(url_for('staff_statistics_tham', mode=mode, year=selected_year))
    if mode == MODE_BALI:
        return redirect(url_for('staff_statistics_bali', mode=mode, year=selected_year))
    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)
    stats = get_statistics(year=selected_year)
    snapshot_lock = get_snapshot_lock_status(selected_year)
    return render_template(
        'statistics.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=selected_year,
        available_years=available_years,
        statistics=stats,
        department_levels=DEPARTMENT_LEVELS,
        snapshot_lock=snapshot_lock
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
    snapshot_lock = get_snapshot_lock_status(selected_year)
    return render_template(
        'statistics_department.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=selected_year,
        available_years=available_years,
        statistics=stats,
        department_key='tham',
        department=DEPARTMENT_LEVELS['tham'],
        snapshot_lock=snapshot_lock
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
        return redirect(url_for('staff_statistics_tham', mode=MODE_THAM, year=selected_year))
    
    subsection_data = DEPARTMENT_LEVELS['tham']['subsections'][subsection]
    stats = get_statistics(subsection_data['levels'], year=selected_year)
    snapshot_lock = get_snapshot_lock_status(selected_year)
    
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
        statistics=stats,
        snapshot_lock=snapshot_lock
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
    snapshot_lock = get_snapshot_lock_status(selected_year)
    return render_template(
        'statistics_department.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=selected_year,
        available_years=available_years,
        statistics=stats,
        department_key='bali',
        department=DEPARTMENT_LEVELS['bali'],
        snapshot_lock=snapshot_lock
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
        return redirect(url_for('staff_statistics_bali', mode=MODE_BALI, year=selected_year))
    
    subsection_data = DEPARTMENT_LEVELS['bali']['subsections'][subsection]
    stats = get_statistics(subsection_data['levels'], year=selected_year)
    snapshot_lock = get_snapshot_lock_status(selected_year)
    
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
        statistics=stats,
        snapshot_lock=snapshot_lock
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
        def build_group_summary(group_df):
            status_series = group_df.get('exam_result_status', '').fillna('').astype(str)
            sent_count = int(len(group_df))
            absent_count = int((status_series == 'ขาดสอบ').sum())
            disqualified_count = int((status_series == 'ขาดสิทธิ์').sum())
            active_count = int(sent_count - absent_count - disqualified_count)
            pass_count = int((status_series == 'สอบได้').sum())
            remedial_pass_count = int((status_series == 'สอบซ่อมได้').sum())
            remedial_count = int(status_series.isin({'สอบซ่อม', 'สอบซ่อมได้'}).sum())
            total_pass_count = int(pass_count + remedial_pass_count)
            fail_count = max(int(active_count) - int(total_pass_count), 0)
            return {
                'ส่งสอบ': sent_count,
                'ขาดสอบ': absent_count,
                'ขาดสิทธิ์': disqualified_count,
                'คงสอบ': active_count,
                'สอบได้': pass_count,
                'สอบซ่อม': remedial_count,
                'สอบซ่อมได้': remedial_pass_count,
                'รวมสอบได้': total_pass_count,
                'สอบตก': fail_count
            }

        summary_df = year_df.copy()
        summary_df = summary_df.assign(
            summary_group=summary_df['group_name'].map(normalize_pass_summary_group)
        )
        summary_df = summary_df[summary_df['class_name'].isin(class_names)]

        classes_data = {}
        for class_name in class_names:
            class_df = summary_df[summary_df['class_name'] == class_name]
            group_rows = {}
            totals = {
                'ส่งสอบ': 0,
                'ขาดสอบ': 0,
                'ขาดสิทธิ์': 0,
                'คงสอบ': 0,
                'สอบได้': 0,
                'สอบซ่อม': 0,
                'สอบซ่อมได้': 0,
                'รวมสอบได้': 0,
                'สอบตก': 0
            }
            for group_name in PASS_SUMMARY_GROUP_ORDER:
                group_df = class_df[class_df['summary_group'] == group_name]
                group_summary = build_group_summary(group_df)
                group_rows[group_name] = group_summary
                for key in totals:
                    totals[key] += int(group_summary.get(key, 0) or 0)

            classes_data[class_name] = {
                'groups': group_rows,
                'total': totals
            }

        grand_total = {}
        grand_totals = {
            'ส่งสอบ': 0,
            'ขาดสอบ': 0,
            'ขาดสิทธิ์': 0,
            'คงสอบ': 0,
            'สอบได้': 0,
            'สอบซ่อม': 0,
            'สอบซ่อมได้': 0,
            'รวมสอบได้': 0,
            'สอบตก': 0
        }
        for group_name in PASS_SUMMARY_GROUP_ORDER:
            group_df = summary_df[summary_df['summary_group'] == group_name]
            group_summary = build_group_summary(group_df)
            grand_total[group_name] = group_summary
            for key in grand_totals:
                grand_totals[key] += int(group_summary.get(key, 0) or 0)

        grand_total['total'] = grand_totals

        group_descriptions = {}
        group_descriptions = get_effective_pass_summary_group_descriptions()

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
            status_series = unit_df['exam_result_status'].fillna('').astype(str)
            sent_count = int(len(unit_df))
            absent_count = int((status_series == 'ขาดสอบ').sum())
            disqualified_count = int((status_series == 'ขาดสิทธิ์').sum())
            active_count = int(sent_count - absent_count - disqualified_count)
            pass_count = int((status_series == 'สอบได้').sum())
            remedial_pass_count = int((status_series == 'สอบซ่อมได้').sum())
            remedial_count = int(status_series.isin({'สอบซ่อม', 'สอบซ่อมได้'}).sum())
            total_pass_count = int(pass_count + remedial_pass_count)
            fail_count = max(int(active_count) - int(total_pass_count), 0)
            unit_rows_list.append({
                'name': school_name,
                'ส่งสอบ': sent_count,
                'ขาดสอบ': absent_count,
                'ขาดสิทธิ์': disqualified_count,
                'คงสอบ': active_count,
                'สอบได้': pass_count,
                'สอบซ่อม': remedial_count,
                'สอบซ่อมได้': remedial_pass_count,
                'รวมสอบได้': total_pass_count,
                'สอบตก': fail_count
            })
        unit_rows_list = sorted(unit_rows_list, key=lambda row: (-row.get('ส่งสอบ', 0), row.get('name', '')))

        total_sent = sum(row.get('ส่งสอบ', 0) for row in unit_rows_list)
        total_absent = sum(row.get('ขาดสอบ', 0) for row in unit_rows_list)
        total_disqualified = sum(row.get('ขาดสิทธิ์', 0) for row in unit_rows_list)
        total_active = sum(row.get('คงสอบ', 0) for row in unit_rows_list)
        total_pass = sum(row.get('สอบได้', 0) for row in unit_rows_list)
        total_remedial = sum(row.get('สอบซ่อม', 0) for row in unit_rows_list)
        total_remedial_pass = sum(row.get('สอบซ่อมได้', 0) for row in unit_rows_list)
        total_total_pass = sum(row.get('รวมสอบได้', 0) for row in unit_rows_list)
        total_fail = sum(row.get('สอบตก', 0) for row in unit_rows_list)

        classes_data[class_name] = {
            'units': unit_rows_list,
            'total': {
                'ส่งสอบ': int(total_sent),
                'ขาดสอบ': int(total_absent),
                'ขาดสิทธิ์': int(total_disqualified),
                'คงสอบ': int(total_active),
                'สอบได้': int(total_pass),
                'สอบซ่อม': int(total_remedial),
                'สอบซ่อมได้': int(total_remedial_pass),
                'รวมสอบได้': int(total_total_pass),
                'สอบตก': int(total_fail)
            }
        }

    grand_unit_rows = {}
    for school_name in sorted(summary_df['school_name_norm'].unique().tolist()):
        unit_df = summary_df[summary_df['school_name_norm'] == school_name]
        status_series = unit_df['exam_result_status'].fillna('').astype(str)
        sent_count = int(len(unit_df))
        absent_count = int((status_series == 'ขาดสอบ').sum())
        disqualified_count = int((status_series == 'ขาดสิทธิ์').sum())
        active_count = int(sent_count - absent_count - disqualified_count)
        pass_count = int((status_series == 'สอบได้').sum())
        remedial_pass_count = int((status_series == 'สอบซ่อมได้').sum())
        remedial_count = int(status_series.isin({'สอบซ่อม', 'สอบซ่อมได้'}).sum())
        total_pass_count = int(pass_count + remedial_pass_count)
        fail_count = max(int(active_count) - int(total_pass_count), 0)
        grand_unit_rows[school_name] = {
            'name': school_name,
            'ส่งสอบ': sent_count,
            'ขาดสอบ': absent_count,
            'ขาดสิทธิ์': disqualified_count,
            'คงสอบ': active_count,
            'สอบได้': pass_count,
            'สอบซ่อม': remedial_count,
            'สอบซ่อมได้': remedial_pass_count,
            'รวมสอบได้': total_pass_count,
            'สอบตก': fail_count
        }
    grand_units_list = sorted(grand_unit_rows.values(), key=lambda row: (-row.get('ส่งสอบ', 0), row.get('name', '')))

    total_sent = sum(row.get('ส่งสอบ', 0) for row in grand_units_list)
    total_absent = sum(row.get('ขาดสอบ', 0) for row in grand_units_list)
    total_disqualified = sum(row.get('ขาดสิทธิ์', 0) for row in grand_units_list)
    total_active = sum(row.get('คงสอบ', 0) for row in grand_units_list)
    total_pass = sum(row.get('สอบได้', 0) for row in grand_units_list)
    total_remedial = sum(row.get('สอบซ่อม', 0) for row in grand_units_list)
    total_remedial_pass = sum(row.get('สอบซ่อมได้', 0) for row in grand_units_list)
    total_total_pass = sum(row.get('รวมสอบได้', 0) for row in grand_units_list)
    total_fail = sum(row.get('สอบตก', 0) for row in grand_units_list)

    return {
        'classes': classes_data,
        'grand_total': {
            'units': grand_units_list,
            'total': {
                'ส่งสอบ': int(total_sent),
                'ขาดสอบ': int(total_absent),
                'ขาดสิทธิ์': int(total_disqualified),
                'คงสอบ': int(total_active),
                'สอบได้': int(total_pass),
                'สอบซ่อม': int(total_remedial),
                'สอบซ่อมได้': int(total_remedial_pass),
                'รวมสอบได้': int(total_total_pass),
                'สอบตก': int(total_fail)
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
        def build_group_summary(group_df):
            status_series = group_df.get('exam_result_status', '').fillna('').astype(str)
            sent_count = int(len(group_df))
            absent_count = int((status_series == 'ขาดสอบ').sum())
            disqualified_count = int((status_series == 'ขาดสิทธิ์').sum())
            active_count = int(sent_count - absent_count - disqualified_count)
            pass_count = int((status_series == 'สอบได้').sum())
            remedial_pass_count = int((status_series == 'สอบซ่อมได้').sum())
            remedial_count = int(status_series.isin({'สอบซ่อม', 'สอบซ่อมได้'}).sum())
            total_pass_count = int(pass_count + remedial_pass_count)
            fail_count = max(int(active_count) - int(total_pass_count), 0)
            return {
                'ส่งสอบ': sent_count,
                'ขาดสอบ': absent_count,
                'ขาดสิทธิ์': disqualified_count,
                'คงสอบ': active_count,
                'สอบได้': pass_count,
                'สอบซ่อม': remedial_count,
                'สอบซ่อมได้': remedial_pass_count,
                'รวมสอบได้': total_pass_count,
                'สอบตก': fail_count
            }

        summary_df = year_df.copy()
        summary_df = summary_df.assign(
            summary_group=summary_df['group_name'].map(normalize_pass_summary_group)
        )
        summary_df = summary_df[summary_df['class_name'].isin(class_names)]

        classes_data = {}
        for class_name in class_names:
            class_df = summary_df[summary_df['class_name'] == class_name]
            group_rows = {}
            totals = {
                'ส่งสอบ': 0,
                'ขาดสอบ': 0,
                'ขาดสิทธิ์': 0,
                'คงสอบ': 0,
                'สอบได้': 0,
                'สอบซ่อม': 0,
                'สอบซ่อมได้': 0,
                'รวมสอบได้': 0,
                'สอบตก': 0
            }
            for group_name in PASS_SUMMARY_GROUP_ORDER:
                group_df = class_df[class_df['summary_group'] == group_name]
                group_summary = build_group_summary(group_df)
                group_rows[group_name] = group_summary
                for key in totals:
                    totals[key] += int(group_summary.get(key, 0) or 0)

            classes_data[class_name] = {
                'groups': group_rows,
                'total': totals
            }

        grand_total = {}
        grand_totals = {
            'ส่งสอบ': 0,
            'ขาดสอบ': 0,
            'ขาดสิทธิ์': 0,
            'คงสอบ': 0,
            'สอบได้': 0,
            'สอบซ่อม': 0,
            'สอบซ่อมได้': 0,
            'รวมสอบได้': 0,
            'สอบตก': 0
        }
        for group_name in PASS_SUMMARY_GROUP_ORDER:
            group_df = summary_df[summary_df['summary_group'] == group_name]
            group_summary = build_group_summary(group_df)
            grand_total[group_name] = group_summary
            for key in grand_totals:
                grand_totals[key] += int(group_summary.get(key, 0) or 0)

        grand_total['total'] = grand_totals

        group_descriptions = {}
        group_descriptions = get_effective_pass_summary_group_descriptions()

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


@app.route('/staff/data-source', methods=['GET', 'POST'])
@staff_login_required()
def staff_data_source():
    current_year_thai = get_current_buddhist_year(numeric=False)
    selected_year = get_selected_year()
    available_years = list_available_years()
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years = sorted(available_years)

    settings = load_data_source_settings()
    effective_lock_max_year = get_effective_snapshot_lock_max_year()
    runtime_current_year = get_runtime_current_year_numeric()
    snapshot_items = []
    for year in available_years:
        snapshot_file = get_api_snapshot_file(year)
        fetched_at = ''
        if os.path.exists(snapshot_file):
            try:
                fetched_at = datetime.fromtimestamp(os.path.getmtime(snapshot_file)).isoformat()
            except OSError:
                fetched_at = ''
        snapshot_items.append({
            'year': int(year),
            'snapshot_exists': os.path.exists(snapshot_file),
            'snapshot_modified_at': fetched_at,
        })

    certificate_snapshot_items = []
    for year in available_years:
        snapshot_file = get_certificate_snapshot_read_file(year)
        fetched_at = ''
        if snapshot_file and os.path.exists(snapshot_file):
            try:
                fetched_at = datetime.fromtimestamp(os.path.getmtime(snapshot_file)).isoformat()
            except OSError:
                fetched_at = ''
        certificate_snapshot_items.append({
            'year': int(year),
            'snapshot_exists': bool(snapshot_file and os.path.exists(snapshot_file)),
            'snapshot_modified_at': fetched_at,
        })
    certificate_all_snapshot_file = get_certificate_snapshot_read_file('all')
    certificate_all_modified_at = ''
    if certificate_all_snapshot_file and os.path.exists(certificate_all_snapshot_file):
        try:
            certificate_all_modified_at = datetime.fromtimestamp(os.path.getmtime(certificate_all_snapshot_file)).isoformat()
        except OSError:
            certificate_all_modified_at = ''

    message = ''
    message_type = 'success'
    if request.method == 'POST':
        action = str(request.form.get('action') or '').strip()
        if action == 'set_lock_max_year':
            new_lock_year = normalize_year_value(request.form.get('lock_max_year'))
            if new_lock_year:
                settings['snapshot_lock_max_year'] = int(new_lock_year)
            else:
                settings.pop('snapshot_lock_max_year', None)
            save_data_source_settings(settings)
            write_staff_log(action='data_source', outcome='success', username=session.get('staff_username', ''), detail=f'set_lock_max_year:{settings.get("snapshot_lock_max_year")}')
            return redirect(url_for('staff_data_source', mode=get_mode_value(request.args.get('mode')), year=selected_year))

        if action == 'clear_lock_max_year':
            settings.pop('snapshot_lock_max_year', None)
            save_data_source_settings(settings)
            write_staff_log(action='data_source', outcome='success', username=session.get('staff_username', ''), detail='clear_lock_max_year')
            return redirect(url_for('staff_data_source', mode=get_mode_value(request.args.get('mode')), year=selected_year))

        if action == 'refresh_snapshot':
            target_year = normalize_year_value(request.form.get('refresh_year')) or selected_year
            try:
                load_data_from_api(target_year, store_global=False, force_refresh=True, allow_locked_refresh=True)
                DF_CACHE.pop(str(target_year), None)
                DF_CACHE.pop(int(target_year), None)
                DF_CACHE_META.pop(str(target_year), None)
                DF_CACHE_META.pop(int(target_year), None)
                write_staff_log(action='data_source', outcome='success', username=session.get('staff_username', ''), detail=f'refresh_snapshot:{target_year}')
                message = f'อัปเดต snapshot ปี {to_thai_digits(target_year)} สำเร็จ'
                message_type = 'success'
            except Exception as e:
                write_staff_log(action='data_source', outcome='failed', username=session.get('staff_username', ''), detail=f'refresh_snapshot:{target_year}:{e}')
                message = f'อัปเดต snapshot ไม่สำเร็จ: {e}'
                message_type = 'error'

            settings = load_data_source_settings()
            effective_lock_max_year = get_effective_snapshot_lock_max_year()
            snapshot_items = []
            for year in available_years:
                snapshot_file = get_api_snapshot_file(year)
                fetched_at = ''
                if os.path.exists(snapshot_file):
                    try:
                        fetched_at = datetime.fromtimestamp(os.path.getmtime(snapshot_file)).isoformat()
                    except OSError:
                        fetched_at = ''
                snapshot_items.append({
                    'year': int(year),
                    'snapshot_exists': os.path.exists(snapshot_file),
                    'snapshot_modified_at': fetched_at,
                })

        if action == 'refresh_certificate_snapshot_all':
            try:
                load_current_public_certificate_rows_for_year(None, force_refresh=True)
                invalidate_public_certificate_cache()
                CURRENT_CERTIFICATE_YEAR_CACHE.pop('all', None)
                write_staff_log(action='data_source', outcome='success', username=session.get('staff_username', ''), detail='refresh_certificate_snapshot_all')
                message = 'อัปเดต snapshot ใบประกาศ (ทั้งหมด) สำเร็จ'
                message_type = 'success'
            except Exception as e:
                write_staff_log(action='data_source', outcome='failed', username=session.get('staff_username', ''), detail=f'refresh_certificate_snapshot_all:{e}')
                message = f'อัปเดต snapshot ใบประกาศ (ทั้งหมด) ไม่สำเร็จ: {e}'
                message_type = 'error'

        if action == 'refresh_certificate_snapshot_year':
            target_year = normalize_year_value(request.form.get('refresh_certificate_year')) or selected_year
            try:
                load_current_public_certificate_rows_for_year(target_year, force_refresh=True)
                invalidate_public_certificate_cache()
                CURRENT_CERTIFICATE_YEAR_CACHE.pop(int(target_year), None)
                write_staff_log(action='data_source', outcome='success', username=session.get('staff_username', ''), detail=f'refresh_certificate_snapshot_year:{target_year}')
                message = f'อัปเดต snapshot ใบประกาศ ปี {to_thai_digits(target_year)} สำเร็จ'
                message_type = 'success'
            except Exception as e:
                write_staff_log(action='data_source', outcome='failed', username=session.get('staff_username', ''), detail=f'refresh_certificate_snapshot_year:{target_year}:{e}')
                message = f'อัปเดต snapshot ใบประกาศ ไม่สำเร็จ: {e}'
                message_type = 'error'

    return render_template(
        'staff_data_source.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        selected_year=selected_year,
        available_years=available_years,
        runtime_current_year_numeric=runtime_current_year,
        env_lock_max_year=API_SNAPSHOT_LOCK_MAX_YEAR,
        override_lock_max_year=settings.get('snapshot_lock_max_year'),
        effective_lock_max_year=effective_lock_max_year,
        snapshot_items=snapshot_items,
        certificate_snapshot_items=certificate_snapshot_items,
        certificate_all_snapshot_exists=bool(certificate_all_snapshot_file and os.path.exists(certificate_all_snapshot_file)),
        certificate_all_snapshot_modified_at=certificate_all_modified_at,
        message=message,
        message_type=message_type
    )


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


@app.route('/manage-legacy-certificates')
@staff_login_required()
def manage_legacy_certificates():
    current_year_thai = get_current_buddhist_year(numeric=False)
    rows, _search_texts, source_file, source_mtime = load_legacy_certificate_rows_cached(include_deleted=True)
    stamp_mtime = source_mtime
    try:
        overrides_mtime = os.path.getmtime(LEGACY_CERTIFICATE_OVERRIDES_FILE) if os.path.exists(LEGACY_CERTIFICATE_OVERRIDES_FILE) else None
    except OSError:
        overrides_mtime = None
    try:
        deletions_mtime = os.path.getmtime(LEGACY_CERTIFICATE_DELETIONS_FILE) if os.path.exists(LEGACY_CERTIFICATE_DELETIONS_FILE) else None
    except OSError:
        deletions_mtime = None
    for candidate in [overrides_mtime, deletions_mtime]:
        if candidate is not None and (stamp_mtime is None or candidate > stamp_mtime):
            stamp_mtime = candidate
    timestamp = datetime.fromtimestamp(stamp_mtime).strftime('%d/%m/%Y %H:%M') if stamp_mtime else '-'
    return render_template(
        'legacy_certificates_manage.html',
        current_buddhist_year=current_year_thai,
        current_year_numeric=CURRENT_YEAR_NUMERIC,
        legacy_source=os.path.basename(source_file or '') if source_file else '',
        legacy_timestamp=timestamp,
        legacy_record_count=len(rows),
    )


@app.route('/api/legacy-certificates/info')
@staff_login_required(api=True)
def legacy_certificates_info():
    rows, _search_texts, source_file, source_mtime = load_legacy_certificate_rows_cached(include_deleted=True)
    stamp_mtime = source_mtime
    try:
        overrides_mtime = os.path.getmtime(LEGACY_CERTIFICATE_OVERRIDES_FILE) if os.path.exists(LEGACY_CERTIFICATE_OVERRIDES_FILE) else None
    except OSError:
        overrides_mtime = None
    try:
        deletions_mtime = os.path.getmtime(LEGACY_CERTIFICATE_DELETIONS_FILE) if os.path.exists(LEGACY_CERTIFICATE_DELETIONS_FILE) else None
    except OSError:
        deletions_mtime = None
    for candidate in [overrides_mtime, deletions_mtime]:
        if candidate is not None and (stamp_mtime is None or candidate > stamp_mtime):
            stamp_mtime = candidate
    timestamp = datetime.fromtimestamp(stamp_mtime).strftime('%d/%m/%Y %H:%M') if stamp_mtime else '-'
    return jsonify({
        'source': os.path.basename(source_file or '') if source_file else '',
        'timestamp': timestamp,
        'record_count': len(rows),
    })


@app.route('/api/legacy-certificates/search')
@staff_login_required(api=True)
def legacy_certificates_search():
    query = str(request.args.get('q', '') or '').strip().lower()
    year_text = str(request.args.get('year', '') or '').strip()
    include_deleted = str(request.args.get('include_deleted') or '').strip().lower() in {'1', 'true', 'yes'}
    try:
        limit = int(request.args.get('limit', '50') or 50)
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 200))

    if not query and not year_text:
        return jsonify({'results': [], 'total': 0})

    rows, search_texts, source_file, _source_mtime = load_legacy_certificate_rows_cached(include_deleted=include_deleted)
    results = []
    total = 0
    for idx, row in enumerate(rows):
        if year_text and str(row.get('year') or '').strip() != year_text:
            continue
        search_text = search_texts[idx] if idx < len(search_texts) else ''
        if query and query not in search_text:
            continue
        total += 1
        if len(results) >= limit:
            continue
        results.append({
            'legacy_id': str(row.get('legacy_id') or '').strip(),
            'fingerprint': str(row.get('fingerprint') or '').strip(),
            'deleted': row.get('deleted') is True,
            'id_std': str(row.get('id_std') or '').strip(),
            'display_name': str(row.get('display_name') or '').strip(),
            'certificate_no': str(row.get('certificate_no') or '').strip(),
            'subject': str(row.get('subject') or '').strip(),
            'level': str(row.get('level') or '').strip(),
            'year': str(row.get('year') or '').strip(),
            'province': str(row.get('province') or '').strip(),
            'school': str(row.get('school') or '').strip(),
            'temple': str(row.get('temple') or '').strip(),
            'scraped_at': str(row.get('scraped_at') or '').strip(),
            'source': os.path.basename(source_file or '') if source_file else '',
        })
    return jsonify({'results': results, 'total': total})


@app.route('/api/legacy-certificates/update', methods=['POST'])
@staff_login_required(api=True)
def legacy_certificates_update():
    payload = request.get_json(silent=True) or {}
    legacy_id = str(payload.get('legacy_id') or '').strip()
    if not legacy_id.startswith('legacy:'):
        return jsonify({'success': False, 'message': 'legacy_id ไม่ถูกต้อง'}), 400
    try:
        index = int(legacy_id.split(':', 1)[1])
    except (IndexError, ValueError):
        return jsonify({'success': False, 'message': 'legacy_id ไม่ถูกต้อง'}), 400
    fingerprint = str(payload.get('fingerprint') or '').strip()
    patch = payload.get('patch') or {}
    if not isinstance(patch, dict) or not patch:
        return jsonify({'success': False, 'message': 'ไม่พบข้อมูลที่ต้องการแก้ไข'}), 400

    allowed_fields = {'display_name', 'id_std', 'certificate_no', 'subject', 'level', 'year', 'province', 'school', 'temple', 'scraped_at'}
    cleaned_patch = {}
    for key, value in patch.items():
        if key not in allowed_fields:
            continue
        cleaned_patch[key] = str(value or '').strip()
    if not cleaned_patch:
        return jsonify({'success': False, 'message': 'ไม่มีฟิลด์ที่อนุญาตให้แก้ไข'}), 400

    baseline_file = get_legacy_certificate_baseline_source_file()
    if not baseline_file:
        return jsonify({'success': False, 'message': 'ไม่พบไฟล์ฐานเก่าเพื่อแก้ไข'}), 400
    try:
        baseline_rows = load_legacy_certificate_baseline_rows(baseline_file)
    except Exception:
        baseline_rows = []
    if index < 0 or index >= len(baseline_rows) or not isinstance(baseline_rows[index], dict):
        return jsonify({'success': False, 'message': 'ไม่พบรายการที่ต้องการแก้ไข'}), 404

    overrides_map = load_legacy_certificate_overrides()
    deletions_map = load_legacy_certificate_deletions()
    baseline_row = baseline_rows[index]
    override_row = overrides_map.get(legacy_id) if isinstance(overrides_map, dict) else None
    deletion_row = deletions_map.get(legacy_id) if isinstance(deletions_map, dict) else None
    current_fingerprint = legacy_certificate_row_fingerprint(baseline_row, override_row=override_row, deletion_row=deletion_row)
    if fingerprint and fingerprint != current_fingerprint:
        return jsonify({'success': False, 'message': 'ข้อมูลถูกแก้ไขจากที่อื่นแล้ว กรุณารีเฟรชแล้วลองใหม่', 'conflict': True}), 409

    if not isinstance(overrides_map, dict):
        overrides_map = {}
    existing = overrides_map.get(legacy_id)
    if not isinstance(existing, dict):
        existing = {}
    existing_fields = existing.get('fields') if isinstance(existing.get('fields'), dict) else {}
    updated_fields = dict(existing_fields)
    updated_fields.update(cleaned_patch)
    overrides_map[legacy_id] = {
        'fields': updated_fields,
        'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'updated_by': session.get('staff_username', ''),
    }
    save_legacy_certificate_overrides(overrides_map)
    invalidate_legacy_certificate_edit_cache()
    invalidate_public_certificate_cache()
    write_staff_log(
        action='legacy_certificate_update',
        outcome='success',
        username=session.get('staff_username', ''),
        detail=f"legacy_id={legacy_id}|fields={','.join(sorted(cleaned_patch.keys()))}"
    )
    return jsonify({
        'success': True,
        'message': 'บันทึกเรียบร้อยแล้ว',
        'fingerprint': legacy_certificate_row_fingerprint(baseline_row, override_row=overrides_map.get(legacy_id), deletion_row=deletion_row),
    })


@app.route('/api/legacy-certificates/delete', methods=['POST'])
@staff_login_required(api=True)
def legacy_certificates_delete():
    payload = request.get_json(silent=True) or {}
    legacy_id = str(payload.get('legacy_id') or '').strip()
    if not legacy_id.startswith('legacy:'):
        return jsonify({'success': False, 'message': 'legacy_id ไม่ถูกต้อง'}), 400
    try:
        index = int(legacy_id.split(':', 1)[1])
    except (IndexError, ValueError):
        return jsonify({'success': False, 'message': 'legacy_id ไม่ถูกต้อง'}), 400
    fingerprint = str(payload.get('fingerprint') or '').strip()
    deleted = payload.get('deleted') is True
    reason = str(payload.get('reason') or '').strip()

    baseline_file = get_legacy_certificate_baseline_source_file()
    if not baseline_file:
        return jsonify({'success': False, 'message': 'ไม่พบไฟล์ฐานเก่าเพื่อแก้ไข'}), 400
    baseline_rows = load_legacy_certificate_baseline_rows(baseline_file)
    if index < 0 or index >= len(baseline_rows) or not isinstance(baseline_rows[index], dict):
        return jsonify({'success': False, 'message': 'ไม่พบรายการที่ต้องการแก้ไข'}), 404

    overrides_map = load_legacy_certificate_overrides()
    deletions_map = load_legacy_certificate_deletions()
    baseline_row = baseline_rows[index]
    override_row = overrides_map.get(legacy_id) if isinstance(overrides_map, dict) else None
    deletion_row = deletions_map.get(legacy_id) if isinstance(deletions_map, dict) else None
    current_fingerprint = legacy_certificate_row_fingerprint(baseline_row, override_row=override_row, deletion_row=deletion_row)
    if fingerprint and fingerprint != current_fingerprint:
        return jsonify({'success': False, 'message': 'ข้อมูลถูกแก้ไขจากที่อื่นแล้ว กรุณารีเฟรชแล้วลองใหม่', 'conflict': True}), 409

    if not isinstance(deletions_map, dict):
        deletions_map = {}
    if deleted:
        deletions_map[legacy_id] = {
            'deleted': True,
            'reason': reason,
            'deleted_at': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
            'deleted_by': session.get('staff_username', ''),
        }
    else:
        deletions_map.pop(legacy_id, None)
    save_legacy_certificate_deletions(deletions_map)
    invalidate_legacy_certificate_edit_cache()
    invalidate_public_certificate_cache()
    write_staff_log(
        action='legacy_certificate_delete' if deleted else 'legacy_certificate_undelete',
        outcome='success',
        username=session.get('staff_username', ''),
        detail=f"legacy_id={legacy_id}|reason={reason or '-'}"
    )
    updated_deletion = deletions_map.get(legacy_id) if deleted else None
    return jsonify({
        'success': True,
        'message': 'ลบรายการเรียบร้อยแล้ว' if deleted else 'ยกเลิกลบเรียบร้อยแล้ว',
        'fingerprint': legacy_certificate_row_fingerprint(baseline_row, override_row=override_row, deletion_row=updated_deletion),
        'deleted': deleted,
    })


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
                'imported_at': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
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
        'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
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
    return redirect(url_for('manage_results', mode=get_mode_value(request.args.get('mode')), year=year_value))


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
    year_value = normalize_year_value(request.args.get('year')) or CURRENT_YEAR_NUMERIC
    mode = get_mode_value(request.args.get('mode'))
    year_df = get_df_for_year(year_value)
    year_df = filter_df_by_mode(year_df, mode)
    count_value = int(len(year_df)) if year_df is not None and not year_df.empty else 0
    return jsonify({'timestamp': get_data_timestamp(), 'count': count_value})


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
