import pandas as pd
import json
import os


DEFAULT_GROUP_DESCRIPTIONS = {
    "กลุ่ม ๕": "- พระภิกษุ-สามเณรทั่วไป (วัดอื่นๆ)",
    "กลุ่ม ๖": "- อุบาสก อุบาสิกา - ศรัทธาวาส - บัณฑิตแก้ว, บัณฑิตอาสา - อาสาพันธุ์ตะวัน",
    "กลุ่ม ๗": "- เจ้าหน้าที่ (พนักงาน) ภายในวัด - สาธุชนทั่วไป",
    "ไม่ระบุ": "- ไม่ระบุกลุ่ม",
}


def parse_bali_summary():
    excel_path = r"D:\pariyat-search-project\ไฟล์ข้อมูล\2569 ตารางสรุปส่งสอบและสอบได้บาลี.xlsx"
    
    summary_data = {
        "year": 2569,
        "department": "บาลี",
        "classes": {},
        "group_descriptions": {}
    }
    
    # Read the "สรุป" sheet
    df_summary = pd.read_excel(excel_path, sheet_name='สรุป', header=None)
    
    # Find group descriptions from the bottom of the sheet
    for i in range(len(df_summary)):
        cell_value = str(df_summary.iloc[i, 0]).strip()
        if cell_value.startswith("กลุ่ม"):
            group_num = cell_value.split()[1]
            description = str(df_summary.iloc[i, 1]).strip() if pd.notna(df_summary.iloc[i, 1]) else ""
            summary_data["group_descriptions"][f"กลุ่ม {group_num}"] = description
            if i + 1 < len(df_summary) and pd.isna(df_summary.iloc[i + 1, 0]):
                next_desc = str(df_summary.iloc[i + 1, 1]).strip()
                if next_desc and next_desc != "nan":
                    summary_data["group_descriptions"][f"กลุ่ม {group_num}"] += " " + next_desc
    
    # Now parse the actual summary data
    class_names = ['ป. ๑-๒', 'ป.ธ. ๓', 'ป.ธ. ๔', 'ป.ธ. ๕', 'ป.ธ. ๖', 'ป.ธ. ๗', 'ป.ธ. ๘', 'ป.ธ. ๙']
    groups = ['กลุ่ม ๑', 'กลุ่ม ๒', 'กลุ่ม ๓', 'กลุ่ม ๔', 'ไม่ระบุ']
    metrics = ['ส่งสอบ', 'คงสอบ', 'สอบได้']
    
    # Column mapping as per the sheet
    group_col_map = {
        'กลุ่ม ๑': (1, 3),
        'กลุ่ม ๒': (4, 6),
        'กลุ่ม ๓': (7, 9),
        'กลุ่ม ๔': (10, 12),
        'ไม่ระบุ': (13, 15)
    }
    
    # Parse rows 6-13 are the class data
    for i in range(6, 14):
        class_name = str(df_summary.iloc[i, 0]).strip()
        if class_name in class_names:
            class_data = {
                "name": class_name,
                "groups": {},
                "total": {}
            }
            
            # Parse each group
            for group in groups:
                if group not in group_col_map:
                    continue
                
                start_col, end_col = group_col_map[group]
                group_data = {}
                
                metric_idx = 0
                for col in range(start_col, end_col + 1):
                    if metric_idx < len(metrics):
                        val = df_summary.iloc[i, col]
                        if pd.notna(val) and str(val).strip() != "":
                            try:
                                group_data[metrics[metric_idx]] = int(val)
                            except (ValueError, TypeError):
                                pass
                        metric_idx += 1
                
                class_data["groups"][group] = group_data
            
            # Parse total from columns 16-18
            total_data = {}
            metric_idx = 0
            for col in range(16, 19):
                if metric_idx < len(metrics):
                    val = df_summary.iloc[i, col]
                    if pd.notna(val) and str(val).strip() != "":
                        try:
                            total_data[metrics[metric_idx]] = int(val)
                        except (ValueError, TypeError):
                            pass
                    metric_idx += 1
            class_data["total"] = total_data
            
            summary_data["classes"][class_name] = class_data
    
    # Also parse the grand total from row 14
    total_row = 14
    summary_data["grand_total"] = {}
    for group in groups:
        if group not in group_col_map:
            continue
        
        start_col, end_col = group_col_map[group]
        group_data = {}
        
        metric_idx = 0
        for col in range(start_col, end_col + 1):
            if metric_idx < len(metrics):
                val = df_summary.iloc[total_row, col]
                if pd.notna(val) and str(val).strip() != "":
                    try:
                        group_data[metrics[metric_idx]] = int(val)
                    except (ValueError, TypeError):
                        pass
                metric_idx += 1
        
        summary_data["grand_total"][group] = group_data
    
    # Total grand total total
    total_data = {}
    metric_idx = 0
    for col in range(16, 19):
        if metric_idx < len(metrics):
            val = df_summary.iloc[total_row, col]
            if pd.notna(val) and str(val).strip() != "":
                try:
                    total_data[metrics[metric_idx]] = int(val)
                except (ValueError, TypeError):
                    pass
            metric_idx += 1
    summary_data["grand_total"]["total"] = total_data

    for group_name, description in DEFAULT_GROUP_DESCRIPTIONS.items():
        summary_data["group_descriptions"][group_name] = description
    
    return summary_data

if __name__ == "__main__":
    data = parse_bali_summary()
    os.makedirs("data", exist_ok=True)
    with open("data/bali_summary_2569.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("Bali summary parsed and saved to data/bali_summary_2569.json")
    print(json.dumps(data, ensure_ascii=False, indent=2))
