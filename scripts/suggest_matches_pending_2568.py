import difflib
import json
import importlib.util
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
APP_FILE = BASE_DIR / "app" / "app.py"
IMPORTER_FILE = BASE_DIR / "scripts" / "import_exam_results_from_excel.py"
PENDING_FILE = BASE_DIR / "data" / "pending_exam_results_2568.json"


def load_module(file_path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def extract_last_name(display_name: str):
    text = str(display_name or "").strip()
    if not text:
        return ""
    if "(" in text and ")" in text:
        inside = text.split("(", 1)[1].split(")", 1)[0].strip()
        return inside
    parts = [p for p in text.split() if p]
    return parts[-1] if len(parts) >= 2 else ""


def main():
    if not PENDING_FILE.exists():
        print(f"Pending file not found: {PENDING_FILE}")
        return

    app_module = load_module(APP_FILE, "app_module")
    importer = load_module(IMPORTER_FILE, "importer_module")

    df = app_module.get_df_for_year(2568)
    pending_payload = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    items = pending_payload.get("items", {})

    df = df.assign(
        base_key=df["display_name"].apply(importer.build_base_name_key_from_display_name),
        last_name=df["display_name"].apply(extract_last_name),
    )
    df_base_keys = df["base_key"].tolist()
    df_base_key_set = set(df_base_keys)

    print("pending_total", len(items))
    for _, item in items.items():
        class_name = (item.get("class_name") or "").strip()
        display_name = (item.get("display_name") or "").strip()
        base_key = (item.get("base_name_key") or "").strip() or importer.build_base_name_key_from_display_name(display_name)
        last_name = extract_last_name(display_name)

        print("-" * 80)
        print("pending:", class_name, "|", display_name)
        print(" base_key:", base_key, " last_name:", last_name)

        same_last = df[df["last_name"] == last_name]
        if not same_last.empty:
            preview = same_last[["class_name", "display_name", "id_card"]].head(8).to_dict("records")
            print(" same_last_name_preview:", preview)
            continue

        close = difflib.get_close_matches(base_key, df_base_key_set, n=5, cutoff=0.75)
        if close:
            candidates = df[df["base_key"].isin(close)][["class_name", "display_name", "id_card", "base_key"]]
            print(" fuzzy_candidates:", candidates.to_dict("records"))
        else:
            print(" no_suggestions")


if __name__ == "__main__":
    main()

