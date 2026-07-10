import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate import build_view_data, render_html
from data_points import USER_DATA

def load_cached_data():
    cache_file = Path(__file__).resolve().parent / "data" / "final_merged_report.json"
    if not cache_file.exists():
        print(f"缓存文件不存在: {cache_file}")
        return None
    
    with open(cache_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    for item in data.get('text_items', []):
        code = item.get('code')
        if code:
            USER_DATA[code] = str(item['value'])
    
    print(f"已加载缓存数据，共 {len(USER_DATA)} 条")
    return data

if __name__ == "__main__":
    cached_data = load_cached_data()
    if not cached_data:
        sys.exit(1)
    
    student_info = cached_data.get('student', {})
    
    try:
        view_data = build_view_data()
        view_data['student']['name'] = student_info.get('name', 'Test')
        view_data['student']['grade'] = student_info.get('grade', '')
        view_data['student']['test_date'] = student_info.get('test_date', '')
        view_data['student']['school'] = student_info.get('school', '')
        
        output_path = Path(__file__).resolve().parent / "output" / "test_report.html"
        render_html(view_data, output_path)
        print(f"HTML已生成: {output_path}")
        
        try:
            from weasyprint import HTML
            pdf_path = output_path.with_suffix('.pdf')
            HTML(str(output_path)).write_pdf(str(pdf_path))
            print(f"PDF已生成: {pdf_path}")
        except ImportError:
            print("WeasyPrint未安装，仅生成了HTML")
            
    except Exception as e:
        print(f"生成失败: {e}")
        import traceback
        traceback.print_exc()