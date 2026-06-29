"""查找思维模式具体得分和自驱力数据。"""
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

# 打印B4所有页面的文本长度，找包含"思维模式得分"或"自主性"等关键词的页
doc = fitz.open(str(b4_path))
print(f"B4 共 {doc.page_count} 页")
for p in range(1, doc.page_count + 1):
    text = extract_text(b4_path, p)
    keywords = ['思维模式', '自主性', '胜任感', '归属感', '自驱力', '成长型', '固定型']
    found = [k for k in keywords if k in text]
    if found:
        print(f"\n第 {p} 页: 含 {found}，{len(text)} 字符")
        # 只打印数字相关部分
        lines = text.strip().split('\n')
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if any(k in line_stripped for k in ['思维模式', '自主性', '胜任感', '归属感', '自驱力', '得分', '平均']) or line_stripped.replace('.', '').replace(' ', '').isdigit():
                print(f"  {i:3d}: {line_stripped}")
doc.close()
