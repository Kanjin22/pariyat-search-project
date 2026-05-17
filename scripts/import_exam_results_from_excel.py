import argparse
import importlib.util
import json
import re
import difflib
import hashlib
from datetime import datetime
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
APP_FILE = BASE_DIR / "app" / "app.py"
RESULTS_DIR = BASE_DIR / "data"
LEGACY_RESULTS_FILE = RESULTS_DIR / "exam_results.json"
DEFAULT_PENDING_FILE = RESULTS_DIR / "pending_exam_results.json"


def get_default_exam_year():
    today = datetime.now()
    buddhist_year = today.year + 543
    if today >= datetime(today.year, 6, 1):
        buddhist_year += 1
    return buddhist_year


def get_results_file(year):
    return RESULTS_DIR / f"exam_results_{int(year)}.json"


def get_names_file(year):
    return RESULTS_DIR / f"exam_names_{int(year)}.json"


def get_pending_file(year):
    return RESULTS_DIR / f"pending_exam_results_{int(year)}.json"


def get_manual_file(year):
    return RESULTS_DIR / f"manual_registrations_{int(year)}.json"


def ensure_year_pending_file(year):
    target_file = get_pending_file(year)
    if target_file.exists():
        return target_file
    if int(year) == int(get_default_exam_year()) and DEFAULT_PENDING_FILE.exists():
        target_file.parent.mkdir(parents=True, exist_ok=True)
        with DEFAULT_PENDING_FILE.open("r", encoding="utf-8") as legacy_reader:
            payload = json.load(legacy_reader)
        with target_file.open("w", encoding="utf-8") as pending_writer:
            json.dump(payload, pending_writer, ensure_ascii=False, indent=2)
        return target_file
    return target_file

STATUS_MAP = {
    "": "สอบตก",
    "ผ่าน": "สอบได้",
    "ไม่ผ่าน": "สอบตก",
    "สอบตก": "สอบตก",
    "ขาดสอบ": "ขาดสอบ",
    "ขาดสิทธิ์": "ขาดสิทธิ์",
    "สอบได้": "สอบได้",
    "สอบซ่อม": "สอบซ่อม",
    "สอบซ่อมได้": "สอบซ่อมได้",
}


def load_app_module():
    spec = importlib.util.spec_from_file_location("app_module", APP_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalize_text(value):
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def build_display_name(row):
    first_name = normalize_text(row.get("ชื่อ"))
    pali_name = normalize_text(row.get("ฉายา"))
    last_name = normalize_text(row.get("นามสกุล"))

    if first_name and pali_name and last_name:
        return f"{first_name} {pali_name} ({last_name})"
    if first_name and last_name:
        return f"{first_name} {last_name}"
    if first_name and pali_name:
        return f"{first_name} {pali_name}"
    return first_name


def normalize_name_key(value):
    text = normalize_text(value)
    if not text:
        return ""
    text = text.replace("_", " ").replace("-", " ")
    text = text.replace("(", " ").replace(")", " ")
    text = re.sub(r"[\s\u200b\u200c\u200d\ufeff]+", "", text)
    return text


def strip_thai_title_prefix(value):
    text = normalize_text(value)
    if not text:
        return ""
    compact = re.sub(r"[\s\u200b\u200c\u200d\ufeff]+", "", text)
    prefixes = [
        "พระครูสังฆรักษ์",
        "พระครูปลัด",
        "พระครู",
        "พระมหา",
        "พระอธิการ",
        "พระปลัด",
        "พระใบฎีกา",
        "พระ",
        "สามเณร",
    ]
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if compact.startswith(prefix):
                compact = compact[len(prefix) :]
                changed = True
                break
    return compact


def build_base_name_key_from_display_name(display_name):
    text = normalize_text(display_name)
    if not text:
        return ""
    match = re.search(r"\(([^)]+)\)", text)
    if match:
        last_name = normalize_text(match.group(1))
        without_parentheses = re.sub(r"\s*\([^)]*\)\s*", " ", text).strip()
        first_token = without_parentheses.split()[0] if without_parentheses.split() else ""
        first_name = strip_thai_title_prefix(first_token)
        return normalize_name_key(f"{first_name}{last_name}")

    parts = [part for part in text.split() if part]
    if len(parts) < 2:
        return ""
    last_name = parts[-1]
    first_name = strip_thai_title_prefix(parts[0])
    return normalize_name_key(f"{first_name}{last_name}")


def build_base_name_key_from_excel_row(row):
    first_name_raw = normalize_text(row.get("ชื่อ"))
    last_name = normalize_text(row.get("นามสกุล"))
    if not first_name_raw or not last_name:
        return ""
    first_name = strip_thai_title_prefix(first_name_raw)
    return normalize_name_key(f"{first_name}{last_name}")


def extract_last_name_from_display_name(display_name):
    text = normalize_text(display_name)
    if not text:
        return ""
    match = re.search(r"\(([^)]+)\)", text)
    if match:
        return normalize_text(match.group(1))
    parts = [part for part in text.split() if part]
    return parts[-1] if len(parts) >= 2 else ""


def find_fuzzy_match_key(target_key, base_registration_map, cutoff=0.85, min_delta=0.04):
    target_key = normalize_name_key(target_key)
    if not target_key:
        return ""
    best_ratio = 0.0
    second_ratio = 0.0
    best_match = ""
    for candidate_key, registration_key in base_registration_map.items():
        if not registration_key:
            continue
        ratio = difflib.SequenceMatcher(None, target_key, candidate_key).ratio()
        if ratio > best_ratio:
            second_ratio = best_ratio
            best_ratio = ratio
            best_match = candidate_key
        elif ratio > second_ratio:
            second_ratio = ratio
    if best_match and best_ratio >= cutoff and (best_ratio - second_ratio) >= min_delta:
        return base_registration_map.get(best_match, "")
    return ""


def build_manual_result_key(year, class_name, name_key, sequence_value):
    raw = f"{int(year)}|{class_name}|{name_key}|{sequence_value}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"manual={digest}|class={class_name}"


def build_name_candidates(row):
    first_name = normalize_text(row.get("ชื่อ"))
    pali_name = normalize_text(row.get("ฉายา"))
    last_name = normalize_text(row.get("นามสกุล"))

    candidates = []
    if first_name and pali_name and last_name:
        candidates.append(f"{first_name} {pali_name} ({last_name})")
    if first_name and pali_name:
        candidates.append(f"{first_name} {pali_name}")
    if first_name and last_name:
        candidates.append(f"{first_name} {last_name}")
        candidates.append(f"{first_name} ({last_name})")
    if first_name:
        candidates.append(first_name)

    return [candidate for candidate in dict.fromkeys(candidates) if candidate]


def load_existing_results(year):
    target_file = get_results_file(year)
    if target_file.exists():
        with target_file.open("r", encoding="utf-8") as result_file:
            return json.load(result_file)
    if int(year) == int(get_default_exam_year()) and LEGACY_RESULTS_FILE.exists():
        with LEGACY_RESULTS_FILE.open("r", encoding="utf-8") as legacy_reader:
            payload = json.load(legacy_reader)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        with target_file.open("w", encoding="utf-8") as result_file:
            json.dump(payload, result_file, ensure_ascii=False, indent=2)
        return payload
    return {}


def load_existing_names(year):
    target_file = get_names_file(year)
    if not target_file.exists():
        return {}
    with target_file.open("r", encoding="utf-8") as names_file:
        payload = json.load(names_file)
    return payload if isinstance(payload, dict) else {}


def save_names(year, names_map):
    target_file = get_names_file(year)
    target_file.parent.mkdir(parents=True, exist_ok=True)
    with target_file.open("w", encoding="utf-8") as names_file:
        json.dump(names_map, names_file, ensure_ascii=False, indent=2)


def load_existing_manual(year):
    target_file = get_manual_file(year)
    if not target_file.exists():
        return {}
    with target_file.open("r", encoding="utf-8") as manual_file:
        payload = json.load(manual_file)
    return payload if isinstance(payload, dict) else {}


def save_manual(year, manual_map):
    target_file = get_manual_file(year)
    target_file.parent.mkdir(parents=True, exist_ok=True)
    with target_file.open("w", encoding="utf-8") as manual_file:
        json.dump(manual_map, manual_file, ensure_ascii=False, indent=2)


def save_results(year, result_map):
    target_file = get_results_file(year)
    target_file.parent.mkdir(parents=True, exist_ok=True)
    with target_file.open("w", encoding="utf-8") as result_file:
        json.dump(result_map, result_file, ensure_ascii=False, indent=2)


def load_pending_results(pending_file):
    pending_path = Path(pending_file)
    if not pending_path.exists():
        return {"version": 1, "items": {}}
    with pending_path.open("r", encoding="utf-8") as pending_reader:
        payload = json.load(pending_reader)
    if isinstance(payload, dict) and isinstance(payload.get("items"), dict):
        payload.setdefault("version", 1)
        return payload
    return {"version": 1, "items": {}}


def save_pending_results(pending_file, payload):
    pending_path = Path(pending_file)
    pending_path.parent.mkdir(parents=True, exist_ok=True)
    with pending_path.open("w", encoding="utf-8") as pending_writer:
        json.dump(payload, pending_writer, ensure_ascii=False, indent=2)


def resolve_sheet_status(row):

    if "ผลการสอบ" in row.index:
        return normalize_text(row.get("ผลการสอบ"))

    if "ผลสอบ" in row.index or "ผลสอบซ่อม" in row.index:
        result_1 = normalize_text(row.get("ผลสอบ"))
        result_2 = normalize_text(row.get("ผลสอบซ่อม"))

        if result_1 == "สอบซ่อม" and result_2 == "ผ่าน":
            return "สอบซ่อมได้"
        if result_1 == "สอบซ่อม":
            return "สอบซ่อม"
        if result_1:
            return result_1
        if result_2 == "ผ่าน":
            return "สอบได้"
        return result_2

    result_1 = normalize_text(row.get("ผลสอบ 1"))
    result_2 = normalize_text(row.get("ผลสอบ 2"))

    if result_1 == "สอบซ่อม" and result_2 == "ผ่าน":
        return "สอบซ่อมได้"
    if result_1 == "สอบซ่อม":
        return "สอบซ่อม"
    if result_1:
        return result_1
    if result_2 == "ผ่าน":
        return "สอบได้"
    return result_2


def main():
    parser = argparse.ArgumentParser(description="Import exam results from an Excel sheet.")
    parser.add_argument("--workbook", required=True, help="Path to Excel workbook")
    parser.add_argument("--sheet", required=True, help="Sheet name to import")
    parser.add_argument("--class-name", required=True, help="Class name in the application data")
    parser.add_argument("--year", type=int, default=get_default_exam_year(), help="Exam year (พ.ศ.) to match API filter_year")
    parser.add_argument("--allow-unmatched", action="store_true", help="Keep unmatched rows in pending file instead of failing")
    parser.add_argument("--pending-file", default="", help="Path to pending results file (json)")
    parser.add_argument("--fuzzy-match", action="store_true", help="Enable strict fuzzy match fallback (use with caution)")
    parser.add_argument("--promote-unmatched", action="store_true", help="Create manual registrations for unmatched rows")
    args = parser.parse_args()
    if not args.pending_file:
        args.pending_file = str(ensure_year_pending_file(args.year))

    workbook_path = Path(args.workbook)
    excel_df = pd.read_excel(workbook_path, sheet_name=args.sheet).fillna("")
    excel_df["display_name"] = excel_df.apply(build_display_name, axis=1)
    excel_df["resolved_result"] = excel_df.apply(resolve_sheet_status, axis=1)

    unknown_statuses = sorted(
        {
            normalize_text(value)
            for value in excel_df["resolved_result"].tolist()
            if normalize_text(value) not in STATUS_MAP
        }
    )
    if unknown_statuses:
        raise ValueError(f"Unknown exam result values: {unknown_statuses}")

    app_module = load_app_module()
    app_df = app_module.get_df_for_year(args.year)
    key_column = "result_key" if "result_key" in app_df.columns else "registration_key"
    class_df = app_df[app_df["class_name"] == args.class_name][["display_name", key_column]].copy()
    registration_map = dict(zip(class_df["display_name"], class_df[key_column]))
    normalized_registration_map = {}
    base_registration_map = {}
    last_name_map = {}
    for _, class_row in class_df.iterrows():
        normalized_name = normalize_name_key(class_row["display_name"])
        if normalized_name and normalized_name not in normalized_registration_map:
            normalized_registration_map[normalized_name] = class_row[key_column]
        base_name_key = build_base_name_key_from_display_name(class_row["display_name"])
        if base_name_key:
            if base_name_key in base_registration_map and base_registration_map[base_name_key] != class_row[key_column]:
                base_registration_map[base_name_key] = ""
            elif base_name_key not in base_registration_map:
                base_registration_map[base_name_key] = class_row[key_column]
        last_name_key = normalize_name_key(extract_last_name_from_display_name(class_row["display_name"]))
        if last_name_key:
            if last_name_key in last_name_map and last_name_map[last_name_key] != class_row[key_column]:
                last_name_map[last_name_key] = ""
            elif last_name_key not in last_name_map:
                last_name_map[last_name_key] = class_row[key_column]

    duplicate_names = class_df[class_df.duplicated("display_name", keep=False)]["display_name"].tolist()
    if duplicate_names:
        raise ValueError(f"Duplicate display names found for class {args.class_name}: {duplicate_names}")

    excel_df["matched_registration_key"] = ""
    unmatched_names = []
    pending_rows = []
    for index, row in excel_df.iterrows():
        display_name = row["display_name"]
        if not display_name:
            continue

        registration_key = registration_map.get(display_name)
        if not registration_key:
            for candidate_name in build_name_candidates(row):
                registration_key = registration_map.get(candidate_name)
                if registration_key:
                    break
                normalized_candidate = normalize_name_key(candidate_name)
                registration_key = normalized_registration_map.get(normalized_candidate)
                if registration_key:
                    break
        if not registration_key:
            base_key = build_base_name_key_from_excel_row(row)
            if base_key:
                candidate_key = base_registration_map.get(base_key)
                if candidate_key:
                    registration_key = candidate_key
                elif args.fuzzy_match:
                    registration_key = find_fuzzy_match_key(base_key, base_registration_map)
        if not registration_key:
            last_name_key = normalize_name_key(normalize_text(row.get("นามสกุล")))
            if last_name_key:
                candidate_key = last_name_map.get(last_name_key)
                if candidate_key:
                    registration_key = candidate_key

        if registration_key:
            excel_df.at[index, "matched_registration_key"] = registration_key
        else:
            unmatched_names.append(display_name)
            pending_rows.append((index, row))

    if unmatched_names and not args.allow_unmatched:
        raise ValueError(f"Names not found in application data: {unmatched_names}")

    result_map = load_existing_results(args.year)
    names_map = load_existing_names(args.year)
    manual_map = load_existing_manual(args.year) if args.promote_unmatched else {}
    updated_count = 0
    cleared_count = 0
    status_summary = {}

    for idx, row in excel_df.iterrows():
        display_name = row["display_name"]
        if not display_name:
            continue

        match_key = row["matched_registration_key"]
        if not match_key and args.promote_unmatched:
            name_key = normalize_name_key(display_name)
            sequence_value = normalize_text(row.get("ลำดับ") or idx)
            match_key = build_manual_result_key(args.year, args.class_name, name_key or display_name, sequence_value)
            excel_df.at[idx, "matched_registration_key"] = match_key
            if match_key not in manual_map:
                manual_map[match_key] = {
                    "display_name": display_name,
                    "class_name": args.class_name,
                    "sequence": sequence_value,
                    "school_name": "",
                    "group_name": "",
                    "reg_status": "manual",
                }
        if not match_key:
            continue
        source_status = normalize_text(row.get("resolved_result"))
        mapped_status = STATUS_MAP[source_status]

        if mapped_status:
            result_map[match_key] = mapped_status
            names_map[match_key] = display_name
            updated_count += 1
            status_summary[mapped_status] = status_summary.get(mapped_status, 0) + 1
        else:
            if match_key in result_map:
                del result_map[match_key]
            cleared_count += 1

    save_results(args.year, result_map)
    save_names(args.year, names_map)
    if args.promote_unmatched:
        save_manual(args.year, manual_map)

    pending_updated = 0
    pending_payload = None
    if pending_rows and not args.promote_unmatched:
        pending_payload = load_pending_results(args.pending_file)
        pending_items = pending_payload.get("items", {})
        imported_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        for index, row in pending_rows:
            display_name = row["display_name"]
            source_status = normalize_text(row.get("resolved_result"))
            mapped_status = STATUS_MAP[source_status]
            name_key = normalize_name_key(display_name)
            pending_key = f"{args.class_name}|{name_key or display_name}|{args.sheet}|{index}"
            pending_items[pending_key] = {
                "class_name": args.class_name,
                "display_name": display_name,
                "display_name_key": name_key,
                "base_name_key": build_base_name_key_from_excel_row(row),
                "exam_result_status": mapped_status,
                "source_status": source_status,
                "workbook": str(workbook_path),
                "sheet": str(args.sheet),
                "imported_at": imported_at,
            }
            pending_updated += 1
        pending_payload["items"] = pending_items
        save_pending_results(args.pending_file, pending_payload)

    print(f"Workbook: {workbook_path}")
    print(f"Sheet: {args.sheet}")
    print(f"Class: {args.class_name}")
    print(f"Rows processed: {len(excel_df)}")
    print(f"Statuses updated: {updated_count}")
    print(f"Statuses cleared: {cleared_count}")
    print(f"Matched names: {len(excel_df[excel_df['matched_registration_key'] != ''])}")
    if pending_rows:
        print(f"Unmatched names: {len(pending_rows)}")
        if pending_updated:
            print(f"Pending saved: {pending_updated} -> {args.pending_file}")
    if status_summary:
        print("Status summary:")
        for status_name, count in sorted(status_summary.items()):
            print(f"  - {status_name}: {count}")
    if pending_rows:
        print("Unmatched list:")
        for name in unmatched_names:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
