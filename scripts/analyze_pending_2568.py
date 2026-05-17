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


def main():
    if not PENDING_FILE.exists():
        print(f"Pending file not found: {PENDING_FILE}")
        return

    app_module = load_module(APP_FILE, "app_module")
    importer = load_module(IMPORTER_FILE, "importer_module")

    df = app_module.get_df_for_year(2568)
    pending_payload = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    items = pending_payload.get("items", {})
    print("pending_total", len(items))

    df = df.assign(
        base_name_key=df["display_name"].apply(importer.build_base_name_key_from_display_name),
        normalized_display_name=df["display_name"].apply(importer.normalize_name_key),
    )

    for pending_key, item in items.items():
        class_name = (item.get("class_name") or "").strip()
        display_name = (item.get("display_name") or "").strip()
        base_key = (item.get("base_name_key") or "").strip() or importer.build_base_name_key_from_display_name(display_name)
        display_key = (item.get("display_name_key") or "").strip()

        candidates = df[df["base_name_key"] == base_key]
        same_class = candidates[candidates["class_name"] == class_name]

        print("-" * 80)
        print("pending:", class_name, "|", display_name)
        print(" base_key:", base_key, " display_key:", display_key)
        print(" candidates_total:", len(candidates), " candidates_same_class:", len(same_class))
        if len(candidates) > 0:
            preview = candidates[["class_name", "display_name", "id_card"]].head(5).to_dict("records")
            print(" candidates_preview:", preview)


if __name__ == "__main__":
    main()

