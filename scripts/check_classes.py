import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from app import df

if df is not None and not df.empty:
    print("=== Available class names ===")
    class_names = sorted(df['class_name'].unique().tolist())
    for name in class_names:
        print(f"- {name}")
