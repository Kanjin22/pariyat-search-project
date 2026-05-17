import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from app import app, df, load_exam_results, save_exam_results, apply_exam_results

# Data from user
pa9_data = [
    {"seq": 4, "name": "พระมหาสมบัติ", "nickname": "ธมฺมทีโป", "lastname": "ฤกษ์สว่าง", "result": "ขาดสอบ"},
    {"seq": 7, "name": "พระมหาไพบูณ", "nickname": "โสภณชโย", "lastname": "มะดารักษ์", "result": "ขาดสอบ"},
    {"seq": 8, "name": "พระมหาสมบุญ", "nickname": "อนนฺตชโย", "lastname": "บุญธรรม", "result": "ขาดสอบ"},
    {"seq": 22, "name": "พระประดิษฐ์ ป.", "nickname": "สิรีภาโส", "lastname": "แสงสี", "result": "ขาดสอบ"},
    {"seq": 24, "name": "พระมหาหมี", "nickname": "ชุตินฺทชโย", "lastname": "อายี", "result": "ขาดสอบ"},
    {"seq": 27, "name": "พระมหาศุภมิตร", "nickname": "ธมฺมสมฺภตฺโต", "lastname": "เจตนาจรัสแสง", "result": "ขาดสอบ"},
    {"seq": 5, "name": "พระมหามนต์ชัย", "nickname": "อภิชาโน", "lastname": "ศรีเทพ", "result": "สอบได้"},
    {"seq": 6, "name": "พระมหาศิริ", "nickname": "สิริสาโร", "lastname": "กาญจนวิชานนท์", "result": "สอบได้"},
    {"seq": 15, "name": "พระมหาภัทร์นฤน", "nickname": "ฐิตปุณฺโญ", "lastname": "บุญเทศ", "result": "สอบได้"},
    {"seq": 18, "name": "พระมหาศรายุทธ", "nickname": "ธมฺมินฺโท", "lastname": "กล่ำอินทร์", "result": "สอบได้"},
    {"seq": 23, "name": "พระมหาอภิสิทธิ์", "nickname": "ธมฺมาภิสิทฺโธ", "lastname": "เหล่าชินชาติ", "result": "สอบได้"},
    {"seq": 29, "name": "พระมหาสามารถ", "nickname": "สามญฺญชโย", "lastname": "พรายน้ำ", "result": "สอบได้"},
    {"seq": 30, "name": "พระมหาวายุ", "nickname": "เวทคฺคชโย", "lastname": "คำทองนาค", "result": "สอบได้"},
    {"seq": 31, "name": "สามเณรเจษฎา", "nickname": "", "lastname": "กัณหาพิมพ์", "result": "สอบได้"},
]

if df is None or df.empty:
    print("Data not loaded!")
    sys.exit(1)

# Filter for ป.ธ.๙
pa9_df = df[df['class_name'] == 'ป.ธ.๙'].copy()

if pa9_df.empty:
    print("No data found for ป.ธ.๙!")
    sys.exit(1)

print(f"Found {len(pa9_df)} records for ป.ธ.๙")

# Load current results
result_map = load_exam_results()

updated_count = 0

for person in pa9_data:
    seq = person["seq"]
    name = person["name"]
    result = person["result"]
    
    # Find by sequence number (convert sequence_thai to numeric)
    # First, let's look for a matching name or sequence
    
    # Try to find by display name contains the name
    match = pa9_df[pa9_df['display_name'].str.contains(name, na=False)]
    
    if len(match) > 0:
        registration_key = match.iloc[0]['registration_key']
        
        # Update the result
        if result in ["ผ่าน", "สอบได้"]:
            result_map[registration_key] = "สอบได้"
        elif result == "ขาดสอบ":
            result_map[registration_key] = "ขาดสอบ"
        else:
            result_map.pop(registration_key, None)
            
        updated_count += 1
        print(f"Updated: {name} ({seq}) -> {result}")
    else:
        print(f"NOT FOUND: {name} ({seq})")

# Save the results
save_exam_results(result_map)
print(f"\nTotal updated: {updated_count} records")
