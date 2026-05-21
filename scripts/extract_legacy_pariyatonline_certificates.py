import argparse
import csv
import html
import json
import re
import string
import sys
import time
from datetime import datetime, timezone
from getpass import getpass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
THAI_BATCH_FILTERS = "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผพภมยรลวศษสหฬอฮเแโใไ"


class TableHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._tables = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cell_text = []
        self._current_table = []
        self._current_row = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table":
            self._in_table = True
            self._current_table = []
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._current_row = []
        elif self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._cell_text = []
        elif self._in_cell and tag == "br":
            self._cell_text.append("\n")

    def handle_data(self, data):
        if self._in_cell:
            self._cell_text.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._in_row and self._in_cell and tag in {"td", "th"}:
            self._in_cell = False
            self._current_row.append("".join(self._cell_text))
            self._cell_text = []
        elif self._in_table and self._in_row and tag == "tr":
            self._in_row = False
            if any(normalize_text(cell) for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._current_row = []
        elif self._in_table and tag == "table":
            self._in_table = False
            if self._current_table:
                self._tables.append(self._current_table)
            self._current_table = []

    def get_tables(self):
        return self._tables


def normalize_text(value):
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    text = str(value)
    text = re.sub(r"[\s\u200b\u200c\u200d\ufeff]+", " ", text)
    return text.strip()


def parse_filter_args(filter_args):
    filters = {}
    for item in filter_args:
        if "=" not in item:
            raise ValueError(f"Invalid --filters value: {item!r} (expected key=value)")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid --filters value: {item!r} (missing key)")
        filters[key] = value.strip()
    return filters


def is_retryable_exception(exc):
    return isinstance(exc, (requests.Timeout, requests.ConnectionError))


def perform_request(session, method, url, timeout, retries, retry_backoff, description, **kwargs):
    last_error = None
    for attempt in range(1, max(1, int(retries)) + 1):
        try:
            return session.request(method=method, url=url, timeout=timeout, **kwargs)
        except Exception as exc:
            last_error = exc
            if not is_retryable_exception(exc) or attempt >= max(1, int(retries)):
                raise
            wait_seconds = max(float(retry_backoff), 0.0) * attempt
            print(
                f"Warning: {description} failed on attempt {attempt}/{retries}: {exc}. "
                f"Retrying in {wait_seconds:.1f}s...",
                file=sys.stderr,
            )
            if wait_seconds > 0:
                time.sleep(wait_seconds)
    raise last_error


def login(session, base_url, username, password, timeout, retries, retry_backoff):
    index_url = urljoin(base_url + "/", "index.php")
    perform_request(
        session,
        "GET",
        index_url,
        timeout,
        retries,
        retry_backoff,
        "load login page",
    )

    login_url = urljoin(base_url + "/", "chkuser.php")
    resp = perform_request(
        session,
        "POST",
        login_url,
        timeout,
        retries,
        retry_backoff,
        "submit login form",
        data={"user_login": username, "pass_login": password, "loginclick": "Login"},
        allow_redirects=True,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Login failed with HTTP {resp.status_code}")

    verify_url = urljoin(base_url + "/", "main.php?page=search_persons")
    verify = perform_request(
        session,
        "GET",
        verify_url,
        timeout,
        retries,
        retry_backoff,
        "verify login session",
    )
    if verify.status_code >= 400:
        raise RuntimeError(f"Login verify failed with HTTP {verify.status_code}")

    verify_text = verify.text
    if "เข้าสู่ระบบ" in verify_text and "user_login" in verify_text:
        raise RuntimeError("Login appears unsuccessful (still seeing login form)")


def search_students_page(session, base_url, filters, timeout, retries, retry_backoff):
    search_url = urljoin(base_url + "/", "main.php?page=search_persons")
    resp = perform_request(
        session,
        "POST",
        search_url,
        timeout,
        retries,
        retry_backoff,
        f"search students page filters={filters!r}",
        data=filters,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Search request failed with HTTP {resp.status_code}")

    match = re.search(
        r"""href=['"]([^'"]*excel/excel_std_names\.php[^'"]*)['"]""",
        resp.text,
        flags=re.IGNORECASE,
    )
    export_url = ""
    if match:
        export_url = urljoin(base_url + "/", match.group(1).lstrip("/"))
    return resp.text, export_url


def download_students_excel(session, export_url, output_path, timeout, retries, retry_backoff):
    resp = perform_request(
        session,
        "GET",
        export_url,
        timeout,
        retries,
        retry_backoff,
        f"download students excel {export_url}",
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Excel download failed with HTTP {resp.status_code}")
    if not resp.content:
        raise RuntimeError("Excel download returned empty content")
    if b"\xe0\xb8\x81\xe0\xb8\xa3\xe0\xb8\xb8\xe0\xb8\x93\xe0\xb8\xb2\xe0\xb9\x80\xe0\xb8\x82\xe0\xb9\x89\xe0\xb8\xb2\xe0\xb8\xa3\xe0\xb8\xb0\xe0\xb8\x9a\xe0\xb8\x9a" in resp.content:
        raise RuntimeError("Excel download returned an access/login warning page instead of an Excel file")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(resp.content)
    return output_path


def read_students_excel(workbook_path):
    try:
        workbook = pd.read_excel(workbook_path, sheet_name=None)
    except ImportError as exc:
        raise RuntimeError(
            "Reading the legacy Excel export requires the optional package 'xlrd'."
        ) from exc
    if not workbook:
        raise RuntimeError(f"No sheets found in workbook: {workbook_path}")

    first_sheet_name = next(iter(workbook))
    df = workbook[first_sheet_name].copy()
    df.columns = [normalize_text(col) or f"column_{idx}" for idx, col in enumerate(df.columns)]
    return df.fillna(""), first_sheet_name


def pick_student_display_name(student_payload):
    if not isinstance(student_payload, dict):
        return ""
    for key in ["display_name", "ชื่อ-สกุล", "ชื่อ", "name", "full_name"]:
        value = normalize_text(student_payload.get(key))
        if value:
            return value
    return ""


def strip_html_tags(value):
    text = re.sub(r"<[^>]+>", " ", value or "")
    return normalize_text(html.unescape(text))


def extract_students_from_search_html(html_text):
    students = []
    for row_html in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html_text, flags=re.IGNORECASE | re.DOTALL):
        id_match = re.search(
            r"<input[^>]*class=['\"]chk_select['\"][^>]*value=['\"](\d+)['\"]",
            row_html,
            flags=re.IGNORECASE,
        )
        if not id_match:
            continue

        id_std = normalize_text(id_match.group(1))
        name_match = re.search(
            r"href\s*=\s*['\"]?main\.php\?page=(?:editstudent_monk|viewstudentdetail)&id_std=\d+['\"]?[^>]*>(.*?)</a>",
            row_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        cert_link_match = re.search(
            r"add_certi_postx&id_std=(\d+)",
            row_html,
            flags=re.IGNORECASE,
        )
        display_name = strip_html_tags(name_match.group(1)) if name_match else ""
        students.append(
            {
                "id_std": id_std,
                "display_name": display_name,
                "has_certificate_link": bool(cert_link_match),
                "matched_filters": [],
            }
        )
    return students


def build_batch_name_filters(batch_values, preset_name, batch_max_filters):
    values = []
    for value in batch_values:
        text = normalize_text(value)
        if text:
            values.append(text)

    preset_map = {
        "latin": list(string.ascii_lowercase),
        "digits": list(string.digits),
        "thai": list(THAI_BATCH_FILTERS),
        "latin-digits": list(string.ascii_lowercase + string.digits),
        "thai-latin": list(THAI_BATCH_FILTERS + string.ascii_lowercase),
        "all": list(THAI_BATCH_FILTERS + string.ascii_lowercase + string.digits),
    }
    if preset_name:
        values.extend(preset_map[preset_name])

    deduped = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)

    if batch_max_filters > 0:
        deduped = deduped[:batch_max_filters]
    return deduped


def collect_search_students(session, base_url, base_filters, batch_name_filters, timeout, retries, retry_backoff):
    search_students = {}
    search_runs = []
    export_candidates = []
    failed_filters = []

    if batch_name_filters:
        run_filters = []
        for name_filter in batch_name_filters:
            filters = dict(base_filters)
            filters["name_all_filter"] = name_filter
            run_filters.append((name_filter, filters))
    else:
        label = normalize_text(base_filters.get("name_all_filter")) or "(default)"
        run_filters = [(label, dict(base_filters))]

    total_runs = len(run_filters)
    for run_index, (filter_label, filters) in enumerate(run_filters, start=1):
        print(
            f"[search {run_index}/{total_runs}] filter={filter_label!r}",
            file=sys.stderr,
        )
        try:
            search_html, export_url = search_students_page(
                session,
                base_url,
                filters,
                timeout,
                retries,
                retry_backoff,
            )
        except Exception as exc:
            failed_filters.append({"filter": filter_label, "error": str(exc)})
            search_runs.append(
                {
                    "filter": filter_label,
                    "count": 0,
                    "export_url": "",
                    "error": str(exc),
                }
            )
            print(
                f"Warning: skipping filter {filter_label!r} because search failed: {exc}",
                file=sys.stderr,
            )
            continue
        students = extract_students_from_search_html(search_html)
        search_runs.append(
            {
                "filter": filter_label,
                "count": len(students),
                "export_url": export_url,
                "error": "",
            }
        )
        print(
            f"[search {run_index}/{total_runs}] filter={filter_label!r} hits={len(students)} unique_total={len(search_students)}",
            file=sys.stderr,
        )
        if export_url:
            export_candidates.append({"filter": filter_label, "export_url": export_url})

        for student in students:
            id_std = student["id_std"]
            if id_std not in search_students:
                search_students[id_std] = student
            if filter_label not in search_students[id_std]["matched_filters"]:
                search_students[id_std]["matched_filters"].append(filter_label)
            if not search_students[id_std].get("display_name") and student.get("display_name"):
                search_students[id_std]["display_name"] = student["display_name"]

    return list(search_students.values()), search_runs, export_candidates, failed_filters


def pick_id_std_column(df):
    for col in df.columns:
        col_text = str(col)
        if re.search(r"\bid\b", col_text, flags=re.IGNORECASE):
            return col
        if "id_std" in col_text.lower():
            return col
        if "รหัส" in col_text:
            return col

    best_col = ""
    best_ratio = 0.0
    for col in df.columns:
        series = df[col].dropna().astype(str).str.strip()
        if series.empty:
            continue
        mask = series.str.fullmatch(r"\d{6,}")
        ratio = float(mask.sum()) / float(len(series))
        if ratio > best_ratio and int(mask.sum()) >= 5:
            best_ratio = ratio
            best_col = col
    return best_col


def fetch_certificate_page(session, base_url, id_std, timeout, retries, retry_backoff):
    url = urljoin(base_url + "/", "main.php")
    resp = perform_request(
        session,
        "GET",
        url,
        timeout,
        retries,
        retry_backoff,
        f"fetch certificate page id_std={id_std}",
        params={"page": "add_certi_postx", "id_std": id_std},
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Fetch cert page failed for id_std={id_std} with HTTP {resp.status_code}")
    return resp.text


def extract_certificates_from_html(html_text):
    parser = TableHTMLParser()
    parser.feed(html_text)
    tables = parser.get_tables()
    results = []

    for table in tables:
        if not table:
            continue

        header = [normalize_text(cell) for cell in table[0]]
        if "เลขที่ปกศ." not in header and "เลขที่ใบประกาศ" not in header:
            continue

        idx = {name: header.index(name) for name in header if name in header}
        cert_key = "เลขที่ปกศ." if "เลขที่ปกศ." in idx else "เลขที่ใบประกาศ"
        required = ["วิชา", "ชั้น", cert_key, "สังกัดวัด", "ปี", "จังหวัด", "สำนักเรียน"]
        if not all(name in idx for name in required):
            continue

        for row in table[1:]:
            row = row + [""] * (len(header) - len(row))
            cert_no = normalize_text(row[idx[cert_key]])
            if not cert_no:
                continue
            results.append(
                {
                    "subject": normalize_text(row[idx["วิชา"]]),
                    "level": normalize_text(row[idx["ชั้น"]]),
                    "certificate_no": cert_no,
                    "temple": normalize_text(row[idx["สังกัดวัด"]]),
                    "year": normalize_text(row[idx["ปี"]]),
                    "province": normalize_text(row[idx["จังหวัด"]]),
                    "school": normalize_text(row[idx["สำนักเรียน"]]),
                }
            )

    return results


def load_processed_ids(output_path):
    processed = set()
    if not output_path.exists():
        return processed

    with output_path.open("r", encoding="utf-8") as reader:
        for line in reader:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            id_std = normalize_text(payload.get("id_std"))
            if id_std:
                processed.add(id_std)
    return processed


def normalize_student_row(row):
    payload = {}
    for key, value in row.items():
        key_text = normalize_text(key)
        if not key_text:
            continue
        payload[key_text] = normalize_text(value)
    return payload


def build_summary_rows_from_output(output_path):
    summary_rows = []
    seen = set()
    if not output_path.exists():
        return summary_rows

    with output_path.open("r", encoding="utf-8") as reader:
        for line in reader:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            id_std = normalize_text(payload.get("id_std"))
            scraped_at = normalize_text(payload.get("scraped_at"))
            student = payload.get("student") or {}
            display_name = pick_student_display_name(student)
            certificates = payload.get("certificates") or []
            for certificate in certificates:
                row = {
                    "id_std": id_std,
                    "display_name": display_name,
                    "certificate_no": normalize_text(certificate.get("certificate_no")),
                    "subject": normalize_text(certificate.get("subject")),
                    "level": normalize_text(certificate.get("level")),
                    "year": normalize_text(certificate.get("year")),
                    "province": normalize_text(certificate.get("province")),
                    "school": normalize_text(certificate.get("school")),
                    "temple": normalize_text(certificate.get("temple")),
                    "scraped_at": scraped_at,
                }
                dedupe_key = (
                    row["id_std"],
                    row["certificate_no"],
                    row["subject"],
                    row["level"],
                    row["year"],
                    row["province"],
                    row["school"],
                    row["temple"],
                )
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                summary_rows.append(row)

    summary_rows.sort(key=lambda item: (item["certificate_no"], item["display_name"], item["id_std"]))
    return summary_rows


def build_filter_report_rows(output_path, search_runs):
    report_map = {}
    for run in search_runs:
        filter_name = normalize_text(run.get("filter"))
        report_map[filter_name] = {
            "filter": filter_name,
            "search_hits": int(run.get("count") or 0),
            "unique_students": 0,
            "students_with_certificates": 0,
            "certificate_rows": 0,
        }

    seen_student_filter = set()
    seen_cert_student_filter = set()

    if output_path.exists():
        with output_path.open("r", encoding="utf-8") as reader:
            for line in reader:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue

                id_std = normalize_text(payload.get("id_std"))
                student = payload.get("student") or {}
                matched_filters = student.get("matched_filters") or []
                certificates = payload.get("certificates") or []

                for filter_name in matched_filters:
                    filter_name = normalize_text(filter_name)
                    if not filter_name:
                        continue
                    if filter_name not in report_map:
                        report_map[filter_name] = {
                            "filter": filter_name,
                            "search_hits": 0,
                            "unique_students": 0,
                            "students_with_certificates": 0,
                            "certificate_rows": 0,
                        }

                    student_key = (filter_name, id_std)
                    if student_key not in seen_student_filter:
                        seen_student_filter.add(student_key)
                        report_map[filter_name]["unique_students"] += 1

                    if certificates:
                        report_map[filter_name]["certificate_rows"] += len(certificates)
                        cert_student_key = (filter_name, id_std)
                        if cert_student_key not in seen_cert_student_filter:
                            seen_cert_student_filter.add(cert_student_key)
                            report_map[filter_name]["students_with_certificates"] += 1

    return sorted(report_map.values(), key=lambda item: item["filter"])


def write_summary_csv(csv_path, rows):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "id_std",
        "display_name",
        "certificate_no",
        "subject",
        "level",
        "year",
        "province",
        "school",
        "temple",
        "scraped_at",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as writer:
        csv_writer = csv.DictWriter(writer, fieldnames=fieldnames)
        csv_writer.writeheader()
        csv_writer.writerows(rows)


def write_summary_json(json_path, rows):
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as writer:
        json.dump(rows, writer, ensure_ascii=False, indent=2)


def write_filter_report_csv(csv_path, rows):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "filter",
        "search_hits",
        "unique_students",
        "students_with_certificates",
        "certificate_rows",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as writer:
        csv_writer = csv.DictWriter(writer, fieldnames=fieldnames)
        csv_writer.writeheader()
        csv_writer.writerows(rows)


def write_filter_report_json(json_path, rows):
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as writer:
        json.dump(rows, writer, ensure_ascii=False, indent=2)


def load_search_cache(cache_path, base_url, base_filters, batch_name_filters):
    if cache_path is None or not cache_path.exists():
        return None
    try:
        with cache_path.open("r", encoding="utf-8") as reader:
            payload = json.load(reader)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if normalize_text(payload.get("base_url")) != normalize_text(base_url):
        return None
    cached_filters = payload.get("base_filters")
    if not isinstance(cached_filters, dict):
        return None
    if {normalize_text(key): normalize_text(value) for key, value in cached_filters.items()} != {
        normalize_text(key): normalize_text(value) for key, value in base_filters.items()
    }:
        return None
    cached_batch_filters = payload.get("batch_name_filters")
    if [normalize_text(item) for item in (cached_batch_filters or [])] != [
        normalize_text(item) for item in batch_name_filters
    ]:
        return None
    search_students = payload.get("search_students")
    search_runs = payload.get("search_runs")
    export_candidates = payload.get("export_candidates")
    failed_filters = payload.get("failed_filters")
    if not all(isinstance(item, list) for item in [search_students, search_runs, export_candidates, failed_filters]):
        return None
    return search_students, search_runs, export_candidates, failed_filters


def write_search_cache(
    cache_path,
    base_url,
    base_filters,
    batch_name_filters,
    search_students,
    search_runs,
    export_candidates,
    failed_filters,
):
    if cache_path is None:
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "base_url": base_url,
        "base_filters": base_filters,
        "batch_name_filters": batch_name_filters,
        "cached_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "search_students": search_students,
        "search_runs": search_runs,
        "export_candidates": export_candidates,
        "failed_filters": failed_filters,
    }
    with cache_path.open("w", encoding="utf-8") as writer:
        json.dump(payload, writer, ensure_ascii=False, indent=2)


def write_output_record(output_path, record):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as writer:
        writer.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Extract legacy certificate records from pariyatonline.")
    parser.add_argument("--base-url", default="https://www.pariyatonline.com/new_student")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--sleep", type=float, default=0.4)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--retry-backoff", type=float, default=2.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--filters", action="append", default=[])
    parser.add_argument(
        "--batch-name-filter",
        action="append",
        default=[],
        help="Repeatable name_all_filter values to run as a batch",
    )
    parser.add_argument(
        "--auto-name-filter-set",
        choices=["latin", "digits", "thai", "latin-digits", "thai-latin", "all"],
        default="",
        help="Auto-generate name_all_filter values for batch mode",
    )
    parser.add_argument(
        "--batch-max-filters",
        type=int,
        default=0,
        help="Limit how many generated batch filters are used (0 = all)",
    )
    parser.add_argument("--students-excel", default=str(DATA_DIR / "legacy_students.xlsx"))
    parser.add_argument("--output", default=str(DATA_DIR / "legacy_certificates.ndjson"))
    parser.add_argument("--summary-csv", default="")
    parser.add_argument("--summary-json", default="")
    parser.add_argument("--filter-report-csv", default="")
    parser.add_argument("--filter-report-json", default="")
    parser.add_argument("--search-cache-json", default=str(DATA_DIR / "legacy_search_cache.json"))
    parser.add_argument("--refresh-search-cache", action="store_true")
    args = parser.parse_args()

    username = args.username.strip()
    password = args.password
    if not username:
        username = input("Username: ").strip()
    if not password:
        password = getpass("Password: ")

    filters = parse_filter_args(args.filters)
    batch_name_filters = build_batch_name_filters(
        batch_values=args.batch_name_filter,
        preset_name=args.auto_name_filter_set,
        batch_max_filters=args.batch_max_filters,
    )
    students_excel_path = Path(args.students_excel)
    output_path = Path(args.output)
    summary_csv_path = Path(args.summary_csv) if args.summary_csv else None
    summary_json_path = Path(args.summary_json) if args.summary_json else None
    filter_report_csv_path = Path(args.filter_report_csv) if args.filter_report_csv else None
    filter_report_json_path = Path(args.filter_report_json) if args.filter_report_json else None
    search_cache_path = Path(args.search_cache_json) if args.search_cache_json else None
    processed_ids = load_processed_ids(output_path)
    failed_students = []
    failed_filters = []

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LegacyCertificateExtractor/1.0",
        }
    )

    print("Logging in to legacy system...", file=sys.stderr)
    login(session, args.base_url, username, password, args.timeout, args.retries, args.retry_backoff)
    print("Login successful. Preparing student ids from search...", file=sys.stderr)
    cached_search = None
    if not args.refresh_search_cache:
        cached_search = load_search_cache(
            cache_path=search_cache_path,
            base_url=args.base_url,
            base_filters=filters,
            batch_name_filters=batch_name_filters,
        )
    if cached_search is not None:
        print(f"Loaded cached search results from {search_cache_path}", file=sys.stderr)
        search_students, search_runs, export_candidates, failed_filters = cached_search
    else:
        print("Collecting student ids from search...", file=sys.stderr)
        search_students, search_runs, export_candidates, failed_filters = collect_search_students(
            session=session,
            base_url=args.base_url,
            base_filters=filters,
            batch_name_filters=batch_name_filters,
            timeout=args.timeout,
            retries=args.retries,
            retry_backoff=args.retry_backoff,
        )
        write_search_cache(
            cache_path=search_cache_path,
            base_url=args.base_url,
            base_filters=filters,
            batch_name_filters=batch_name_filters,
            search_students=search_students,
            search_runs=search_runs,
            export_candidates=export_candidates,
            failed_filters=failed_filters,
        )
        if search_cache_path is not None:
            print(f"Saved search cache to {search_cache_path}", file=sys.stderr)
    if not search_students:
        raise RuntimeError("Could not extract any students with id_std from the search results page")
    print(f"Collected {len(search_students)} unique students from search.", file=sys.stderr)

    workbook_path = None
    sheet_name = ""
    df = None
    id_std_column = ""
    if len(search_runs) == 1 and export_candidates:
        try:
            workbook_path = download_students_excel(
                session=session,
                export_url=export_candidates[0]["export_url"],
                output_path=students_excel_path,
                timeout=args.timeout,
                retries=args.retries,
                retry_backoff=args.retry_backoff,
            )
            df, sheet_name = read_students_excel(workbook_path)
            id_std_column = pick_id_std_column(df)
        except Exception as exc:
            print(f"Warning: Excel metadata unavailable: {exc}", file=sys.stderr)

    processed_count = 0
    skipped_count = 0
    found_cert_count = 0

    student_iterable = []
    if df is not None and id_std_column:
        for _, row in df.iterrows():
            row_payload = normalize_student_row(row.to_dict())
            student_iterable.append(
                {
                    "id_std": normalize_text(row.get(id_std_column)),
                    "student": row_payload,
                }
            )
    else:
        for student in search_students:
            student_iterable.append(
                {
                    "id_std": student["id_std"],
                    "student": {
                        "display_name": student["display_name"],
                        "matched_filters": student.get("matched_filters", []),
                    },
                }
            )

    total_students = len(student_iterable)
    for item in student_iterable:
        id_std = normalize_text(item.get("id_std"))
        if not id_std:
            continue
        if args.limit and processed_count >= args.limit:
            break
        if id_std in processed_ids:
            skipped_count += 1
            continue

        try:
            html_text = fetch_certificate_page(
                session,
                args.base_url,
                id_std,
                args.timeout,
                args.retries,
                args.retry_backoff,
            )
        except Exception as exc:
            failed_students.append({"id_std": id_std, "error": str(exc)})
            print(f"Warning: skipping id_std={id_std} because fetch failed: {exc}", file=sys.stderr)
            continue
        if "เข้าสู่ระบบ" in html_text and "user_login" in html_text:
            try:
                login(session, args.base_url, username, password, args.timeout, args.retries, args.retry_backoff)
                html_text = fetch_certificate_page(
                    session,
                    args.base_url,
                    id_std,
                    args.timeout,
                    args.retries,
                    args.retry_backoff,
                )
            except Exception as exc:
                failed_students.append({"id_std": id_std, "error": f"session expired and re-login failed: {exc}"})
                print(f"Warning: skipping id_std={id_std} because session refresh failed: {exc}", file=sys.stderr)
                continue
            if "เข้าสู่ระบบ" in html_text and "user_login" in html_text:
                failed_students.append({"id_std": id_std, "error": "session expired and login page still returned"})
                print(f"Warning: skipping id_std={id_std} because login page was still returned after re-login", file=sys.stderr)
                continue

        certificates = extract_certificates_from_html(html_text)
        record = {
            "id_std": id_std,
            "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "student": item["student"],
            "certificates": certificates,
        }
        write_output_record(output_path, record)

        processed_ids.add(id_std)
        processed_count += 1
        found_cert_count += len(certificates)

        print(
            f"[{processed_count}/{total_students}] id_std={id_std} certificates={len(certificates)}",
            file=sys.stderr,
        )
        if args.sleep > 0:
            time.sleep(args.sleep)

    summary_rows = build_summary_rows_from_output(output_path)
    filter_report_rows = build_filter_report_rows(output_path, search_runs)
    if summary_csv_path is not None:
        write_summary_csv(summary_csv_path, summary_rows)
    if summary_json_path is not None:
        write_summary_json(summary_json_path, summary_rows)
    if filter_report_csv_path is not None:
        write_filter_report_csv(filter_report_csv_path, filter_report_rows)
    if filter_report_json_path is not None:
        write_filter_report_json(filter_report_json_path, filter_report_rows)

    print(f"Workbook: {workbook_path or 'not used'}")
    print(f"Sheet: {sheet_name or 'not used'}")
    print(f"Rows in workbook: {len(df) if df is not None else 0}")
    print(f"id_std column: {id_std_column or 'from search HTML'}")
    print(f"Rows in search results: {len(search_students)}")
    print(f"Search runs: {len(search_runs)}")
    if batch_name_filters:
        print(f"Batch filters used: {', '.join(batch_name_filters)}")
    print(f"Processed rows this run: {processed_count}")
    print(f"Skipped already processed: {skipped_count}")
    print(f"Certificates found this run: {found_cert_count}")
    print(f"Failed filters: {len(failed_filters)}")
    print(f"Failed students: {len(failed_students)}")
    print(f"Output: {output_path}")
    if summary_csv_path is not None:
        print(f"Summary CSV: {summary_csv_path} ({len(summary_rows)} rows)")
    if summary_json_path is not None:
        print(f"Summary JSON: {summary_json_path} ({len(summary_rows)} rows)")
    if filter_report_csv_path is not None:
        print(f"Filter report CSV: {filter_report_csv_path} ({len(filter_report_rows)} rows)")
    if filter_report_json_path is not None:
        print(f"Filter report JSON: {filter_report_json_path} ({len(filter_report_rows)} rows)")
    if failed_filters:
        print("Failed filter details:")
        for item in failed_filters[:20]:
            print(f"  - {item['filter']}: {item['error']}")
    if failed_students:
        print("Failed student details:")
        for item in failed_students[:20]:
            print(f"  - {item['id_std']}: {item['error']}")


if __name__ == "__main__":
    main()
