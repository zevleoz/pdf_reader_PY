"""查找缺失数据。"""
from __future__ import annotations
import fitz
from pathlib import Path

def extract_text(pdf_path, page_num):
    doc = fitz.open(str(pdf_path))
    page = doc[page_num - 1]
    text = page.get_text()
    doc.close()
    return text

def print_page(pdf_path, page_num, label):
    text = extract_text(pdf_path, page_num)
    print(f"\n{'='*80}")
    print(f"  {label} (第 {page_num} 页)")
    print(f"{'='*80}")
    lines = text.strip().split('\n')
    for i, line in enumerate(lines):
        line = line.strip()
        if line:
            print(f"  {i:3d}: {line}")

b4_path = Path("input/B4 核心认知能力和成长型思维_Samson_2026031416112834275(1).pdf")
b6_path = Path("input/B6 职业发展_Samson_2026031417271196372(1).pdf")

# B4 - 检查更多页面
for p in range(1, 15):
    text = extract_text(b4_path, p)
    if any(k in text for k in ['认知能力', '自我概念', '思维模式', '自驱力', '自主性', '胜任感', '归属感']):
        print_page(b4_path, p, f"B4 关键页-{p}")

# B6 - 找职业兴趣代码和职业价值观条形图文字
for p in range(1, 8):
    text = extract_text(b6_path, p)
    if any(k in text for k in ['代码', 'Code', '职业兴趣', 'IER', 'ECS', 'ESI']):
        print_page(b6_path, p, f"B6 职业兴趣页-{p}")
