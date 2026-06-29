"""查找缺失的数据：依恋关系、体质健康、执行功能工作记忆、学习动机、学习方法与策略、自我概念、思维模式、自驱力、认知能力总得分、职业兴趣代码、能力优势排序。"""
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

a2_path = Path("input/A2 核心素养_Samson_2026031415314850446(1).pdf")
b3_path = Path("input/B3 核心学习能力_Samson_2026031417084772022(1).pdf")
b4_path = Path("input/B4 核心认知能力和成长型思维_Samson_2026031416112834275(1).pdf")
b6_path = Path("input/B6 职业发展_Samson_2026031417271196372(1).pdf")

# A2 - 依恋关系（第7-8页）
print_page(a2_path, 7, "A2 依恋关系-1")
print_page(a2_path, 8, "A2 依恋关系-2")
print_page(a2_path, 9, "A2 依恋关系-3")

# A2 - 体质健康（第10-12页）
print_page(a2_path, 10, "A2 体质健康-1")
print_page(a2_path, 11, "A2 体质健康-2")
print_page(a2_path, 12, "A2 体质健康-3")

# B3 - 执行功能中的工作记忆
print_page(b3_path, 5, "B3 工作记忆")
print_page(b3_path, 6, "B3 认知灵活性-2")
print_page(b3_path, 7, "B3 学习动机-1")
print_page(b3_path, 8, "B3 学习动机-2")
print_page(b3_path, 9, "B3 学习动机-3")
print_page(b3_path, 10, "B3 学习方法与策略-1")
print_page(b3_path, 11, "B3 学习方法与策略-2")

# B4 - 认知能力总得分/百分位（第2-3页）
print_page(b4_path, 3, "B4 认知能力-2")
print_page(b4_path, 4, "B4 自我概念-1")
print_page(b4_path, 5, "B4 自我概念-2")
print_page(b4_path, 6, "B4 思维模式-1")
print_page(b4_path, 7, "B4 思维模式-2")
print_page(b4_path, 8, "B4 自驱力-1")
print_page(b4_path, 9, "B4 自驱力-2")
print_page(b4_path, 10, "B4 自驱力-3")

# B6 - 职业兴趣代码
print_page(b6_path, 5, "B6 职业兴趣-2")
print_page(b6_path, 6, "B6 职业兴趣-3")
print_page(b6_path, 7, "B6 能力优势-1")
print_page(b6_path, 8, "B6 能力优势-2")
print_page(b6_path, 9, "B6 能力优势-3")
print_page(b6_path, 10, "B6 能力优势排序")
print_page(b6_path, 11, "B6 职业价值观-1")
print_page(b6_path, 12, "B6 职业价值观-2")
print_page(b6_path, 13, "B6 职业价值观-3")
print_page(b6_path, 14, "B6 职业价值观-4")
print_page(b6_path, 15, "B6 职业价值观排序-1")
print_page(b6_path, 16, "B6 职业价值观排序-2")
