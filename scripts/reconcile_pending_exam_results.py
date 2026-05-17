import argparse
import importlib.util
import json
from pathlib import Path
from datetime import datetime
import difflib


BASE_DIR = Path(__file__).resolve().parents[1]
IMPORTER_FILE = BASE_DIR / "scripts" / "import_exam_results_from_excel.py"


def get_default_exam_year():
    today = datetime.now()
    buddhist_year = today.year + 543
    if today >= datetime(today.year, 6, 1):
        buddhist_year += 1
    return buddhist_year


def load_importer():
    spec = importlib.util.spec_from_file_location("importer_module", IMPORTER_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description="Reconcile pending exam results with latest application data.")
    parser.add_argument("--year", type=int, default=get_default_exam_year(), help="Exam year (พ.ศ.) to match API filter_year")
    parser.add_argument("--pending-file", default="", help="Pending file path (json)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fuzzy-match", action="store_true", help="Enable strict fuzzy match fallback (use with caution)")
    args = parser.parse_args()

    importer = load_importer()
    if not args.pending_file:
        args.pending_file = str(importer.ensure_year_pending_file(args.year))
    pending_payload = importer.load_pending_results(args.pending_file)
    pending_items = pending_payload.get("items", {})
    if not pending_items:
        print("No pending items found.")
        return

    app_module = importer.load_app_module()
    app_df = app_module.get_df_for_year(args.year)

    result_map = importer.load_existing_results(args.year)

    class_maps = {}
    matched_count = 0
    cleared_count = 0
    updated_count = 0
    remaining_items = dict(pending_items)

    for pending_key, item in pending_items.items():
        class_name = (item.get("class_name") or "").strip()
        display_name = (item.get("display_name") or "").strip()
        display_name_key = (item.get("display_name_key") or "").strip()
        base_name_key = (item.get("base_name_key") or "").strip()
        exam_result_status = (item.get("exam_result_status") or "").strip()
        source_status = (item.get("source_status") or "").strip()

        if not class_name or not display_name:
            continue

        if class_name not in class_maps:
            key_column = "result_key" if "result_key" in app_df.columns else "registration_key"
            class_df = app_df[app_df["class_name"] == class_name][["display_name", key_column]].copy()
            registration_map = dict(zip(class_df["display_name"], class_df[key_column]))
            normalized_map = {}
            base_map = {}
            for _, class_row in class_df.iterrows():
                normalized_name = importer.normalize_name_key(class_row["display_name"])
                if normalized_name and normalized_name not in normalized_map:
                    normalized_map[normalized_name] = class_row[key_column]
                base_key = importer.build_base_name_key_from_display_name(class_row["display_name"])
                if base_key:
                    if base_key in base_map and base_map[base_key] != class_row[key_column]:
                        base_map[base_key] = ""
                    elif base_key not in base_map:
                        base_map[base_key] = class_row[key_column]
            class_maps[class_name] = (registration_map, normalized_map, base_map)

        registration_map, normalized_map, base_map = class_maps[class_name]
        registration_key = registration_map.get(display_name)
        if not registration_key and display_name_key:
            registration_key = normalized_map.get(display_name_key)
        if not registration_key:
            lookup_key = base_name_key or importer.build_base_name_key_from_display_name(display_name)
            if lookup_key:
                candidate_key = base_map.get(lookup_key)
                if candidate_key:
                    registration_key = candidate_key
                elif args.fuzzy_match:
                    best_ratio = 0.0
                    second_ratio = 0.0
                    best_candidate = ""
                    for candidate_lookup, candidate_value in base_map.items():
                        if not candidate_value:
                            continue
                        ratio = difflib.SequenceMatcher(None, lookup_key, candidate_lookup).ratio()
                        if ratio > best_ratio:
                            second_ratio = best_ratio
                            best_ratio = ratio
                            best_candidate = candidate_lookup
                        elif ratio > second_ratio:
                            second_ratio = ratio
                    if best_candidate and best_ratio >= 0.85 and (best_ratio - second_ratio) >= 0.04:
                        registration_key = base_map.get(best_candidate) or registration_key
        if not registration_key:
            continue

        matched_count += 1
        if not exam_result_status and not source_status:
            exam_result_status = "สอบตก"
        if exam_result_status:
            result_map[registration_key] = exam_result_status
            updated_count += 1
        else:
            if registration_key in result_map:
                del result_map[registration_key]
            cleared_count += 1

        remaining_items.pop(pending_key, None)

    if args.dry_run:
        print(f"Pending items: {len(pending_items)}")
        print(f"Matched: {matched_count}")
        print(f"Statuses updated: {updated_count}")
        print(f"Statuses cleared: {cleared_count}")
        print(f"Remaining pending: {len(remaining_items)}")
        return

    importer.save_results(args.year, result_map)
    pending_payload["items"] = remaining_items
    importer.save_pending_results(args.pending_file, pending_payload)

    print(f"Pending items: {len(pending_items)}")
    print(f"Matched: {matched_count}")
    print(f"Statuses updated: {updated_count}")
    print(f"Statuses cleared: {cleared_count}")
    print(f"Remaining pending: {len(remaining_items)}")
    print(f"Pending file: {args.pending_file}")


if __name__ == "__main__":
    main()

