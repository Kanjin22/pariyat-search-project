import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import app as pariyat_app


def build_report_for_year(year: int):
    year_df = pariyat_app.get_df_for_year(year)
    if year_df is None or year_df.empty:
        return {
            "year": int(year),
            "total_rows": 0,
            "missing_id_card": 0,
            "duplicate_registration_key": 0,
            "duplicate_result_key": 0,
            "result_map_total": 0,
            "result_map_key_types": {},
            "top_registration_key_dupes": [],
            "top_result_key_dupes": [],
        }

    df = year_df.copy()
    df["id_card"] = df.get("id_card", "").astype(str).fillna("").str.strip()
    df["registration_key"] = df.get("registration_key", "").astype(str).fillna("").str.strip()
    df["result_key"] = df.get("result_key", "").astype(str).fillna("").str.strip()
    df["display_name"] = df.get("display_name", "").astype(str).fillna("").str.strip()
    df["class_name"] = df.get("class_name", "").astype(str).fillna("").str.strip()

    missing_id_card = int((df["id_card"] == "").sum())

    reg_counts = df["registration_key"].value_counts(dropna=False)
    reg_dupes = reg_counts[reg_counts > 1]

    result_counts = df["result_key"].value_counts(dropna=False)
    result_dupes = result_counts[result_counts > 1]

    def sample_rows(key_col: str, key_value: str, limit: int = 5):
        rows = df.loc[df[key_col] == key_value, ["display_name", "class_name", "id_card", "registration_key", "result_key"]]
        return rows.head(limit).to_dict(orient="records")

    top_reg_dupes = []
    for key_value, count_value in reg_dupes.head(10).items():
        top_reg_dupes.append(
            {"key": str(key_value), "count": int(count_value), "rows": sample_rows("registration_key", key_value)}
        )

    top_result_dupes = []
    for key_value, count_value in result_dupes.head(10).items():
        top_result_dupes.append(
            {"key": str(key_value), "count": int(count_value), "rows": sample_rows("result_key", key_value)}
        )

    result_map = pariyat_app.load_exam_results_for_year(year)
    prev_year_map = pariyat_app.load_exam_results_for_year(int(year) - 1)
    key_types = {}
    if isinstance(result_map, dict):
        for key in result_map.keys():
            k = str(key)
            if k.startswith("cid="):
                key_types["cid"] = key_types.get("cid", 0) + 1
            elif k.startswith("name="):
                key_types["name"] = key_types.get("name", 0) + 1
            else:
                key_types["registration"] = key_types.get("registration", 0) + 1

    def count_matches(df_subset: pd.DataFrame, result_map_candidate: dict):
        if df_subset is None or df_subset.empty or not isinstance(result_map_candidate, dict) or not result_map_candidate:
            return {"total": int(len(df_subset)) if df_subset is not None else 0, "match_result_key": 0, "match_registration_key": 0, "match_any": 0}
        keys = set(result_map_candidate.keys())
        rk = df_subset["result_key"].astype(str).isin(keys)
        regk = df_subset["registration_key"].astype(str).isin(keys)
        anyk = rk | regk
        sample = df_subset.loc[anyk, ["display_name", "class_name", "id_card", "registration_key", "result_key"]].head(5).to_dict(orient="records")
        sample_status = []
        for row in sample:
            rk_val = str(row.get("result_key") or "")
            reg_val = str(row.get("registration_key") or "")
            status = ""
            if rk_val in result_map_candidate:
                status = result_map_candidate.get(rk_val) or ""
            elif reg_val in result_map_candidate:
                status = result_map_candidate.get(reg_val) or ""
            sample_status.append({"key": rk_val if rk_val in result_map_candidate else reg_val, "status": status, "row": row})
        return {
            "total": int(len(df_subset)),
            "match_result_key": int(rk.sum()),
            "match_registration_key": int(regk.sum()),
            "match_any": int(anyk.sum()),
            "sample": sample_status,
        }

    tham_df = pariyat_app.filter_df_by_mode(df, "tham")
    bali_df = pariyat_app.filter_df_by_mode(df, "bali")
    overview_df = df

    match_stats = {
        "tham_using_year": count_matches(tham_df, result_map),
        "tham_using_prev_year": count_matches(tham_df, prev_year_map),
        "bali_using_year": count_matches(bali_df, result_map),
        "bali_using_prev_year": count_matches(bali_df, prev_year_map),
        "overview_using_year": count_matches(overview_df, result_map),
        "overview_mixed_expected": {
            "total": int(len(overview_df)),
            "match_any": int(count_matches(tham_df, prev_year_map)["match_any"] + count_matches(bali_df, result_map)["match_any"]),
        },
    }

    return {
        "year": int(year),
        "total_rows": int(len(df)),
        "missing_id_card": missing_id_card,
        "duplicate_registration_key": int(len(reg_dupes)),
        "duplicate_result_key": int(len(result_dupes)),
        "result_map_total": int(len(result_map)) if isinstance(result_map, dict) else 0,
        "result_map_key_types": key_types,
        "match_stats": match_stats,
        "top_registration_key_dupes": top_reg_dupes,
        "top_result_key_dupes": top_result_dupes,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", nargs="+", type=int, required=True)
    args = parser.parse_args()

    reports = [build_report_for_year(year) for year in args.years]
    pd.set_option("display.max_colwidth", 200)
    for report in reports:
        print("=" * 80)
        print(f"YEAR: {report['year']}")
        print(f"total_rows: {report['total_rows']}")
        print(f"missing_id_card: {report['missing_id_card']}")
        print(f"duplicate_registration_key: {report['duplicate_registration_key']}")
        print(f"duplicate_result_key: {report['duplicate_result_key']}")
        print(f"result_map_total: {report['result_map_total']}")
        print(f"result_map_key_types: {report['result_map_key_types']}")
        if report.get("match_stats"):
            print("match_stats:")
            for key, value in report["match_stats"].items():
                print(f"  {key}: {value}")
        if report["top_result_key_dupes"]:
            print("- top duplicate result_key samples:")
            for item in report["top_result_key_dupes"][:5]:
                print(f"  - count={item['count']} key={item['key']}")
                for row in item["rows"]:
                    print(f"      {row}")
        if report["top_registration_key_dupes"]:
            print("- top duplicate registration_key samples:")
            for item in report["top_registration_key_dupes"][:5]:
                print(f"  - count={item['count']} key={item['key']}")
                for row in item["rows"]:
                    print(f"      {row}")


if __name__ == "__main__":
    main()
