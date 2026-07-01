import os
from pathlib import Path
from gauge_processor import extract_mindset_gauge

PROJECT_DIR = Path(__file__).resolve().parent
PAGES_DIR = PROJECT_DIR / "pages"

b4_page_dir = PAGES_DIR / "report_B4"
mindset_img = b4_page_dir / "page_11.png"

print("=== 思维模式仪表盘识别 ===")
print(f"图片路径: {mindset_img}")
print(f"图片存在: {mindset_img.exists()}")

if mindset_img.exists():
    mindset_value = extract_mindset_gauge(str(mindset_img))
    print(f"\n思维模式分数: {mindset_value}")
    
    hard_values = {}
    if mindset_value is not None:
        hard_values["059"] = f"{mindset_value:.1f}"
        print(f"已保存到 hard_values['059']: {hard_values['059']}")
    else:
        print("识别失败，使用默认值")
else:
    print("图片不存在")