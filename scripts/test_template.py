import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from app import app, df, get_current_buddhist_year

try:
    with app.test_request_context('/pass-list'):
        current_year_thai = get_current_buddhist_year(numeric=False)
        current_year_numeric = get_current_buddhist_year(numeric=True)
        
        selected_year = str(current_year_numeric)
        selected_level = ''
        
        pass_results = []
        
        if df is not None and not df.empty:
            pass_df = df[df['exam_result_status'].isin(['สอบได้', 'สอบซ่อมได้'])].copy()
            
            for _, row in pass_df.iterrows():
                pass_results.append({
                    'name': row['display_name'],
                    'class_name': row['class_name'],
                    'sequence': row['sequence_thai'],
                    'school_name': str(row['school_name']),
                    'group_name': str(row['group_name']),
                    'result_status': row['exam_result_status']
                })
        
        available_levels = []
        if df is not None and not df.empty:
            available_levels = sorted(df['class_name'].unique().tolist())
        
        # Now try to render the template
        rendered = app.jinja_env.get_template('pass_list.html').render(
            current_buddhist_year=current_year_thai,
            current_year_numeric=current_year_numeric,
            selected_year=selected_year,
            selected_level=selected_level,
            pass_results=pass_results,
            available_levels=available_levels
        )
        
        print("=== SUCCESS! Template rendered without errors ===")
        print(f"Rendered length: {len(rendered)} chars")
        
except Exception as e:
    print(f"=== ERROR! ===\nType: {type(e).__name__}\nMessage: {e}")
    import traceback
    traceback.print_exc()
