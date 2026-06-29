import fitz
import re
from pathlib import Path

# 从 A2 的各页面提取详细数字
def page_text(pdf_name, page_idx):
    doc = fitz.open(f'input/{pdf_name}')
    txt = doc[page_idx].get_text()
    doc.close()
    return txt

A2 = 'A2 核心素养_Samson_2026031415314850446(1).pdf'
B3 = 'B3 核心学习能力_Samson_2026031417084772022(1).pdf'
B4 = 'B4 核心认知能力和成长型思维_Samson_2026031416112834275(1).pdf'
B6 = 'B6 职业发展_Samson_2026031417271196372(1).pdf'

# A2 - 情绪稳定性 (page 4 index=4, 即第5页；但图表在 "测评结果详情" 里)
print("=== A2 page 4 (index 4 即第5页 - 情绪稳定性) ===")
print(page_text(A2, 4))

print("\n=== A2 page 6 (index 6 即第7页 - 人格) ===")
print(page_text(A2, 6))

print("\n=== A2 page 8 (index 8 即第9页 - 社会性) ===")
print(page_text(A2, 8))

print("\n=== A2 page 10 (index 10 即第11页 - 体质健康) ===")
print(page_text(A2, 10))

print("\n=== B3 page 8 (index 8 - 学习动机) ===")
print(page_text(B3, 8))

print("\n=== B3 page 10 (index 10 - 学习方法) ===")
print(page_text(B3, 10))

print("\n=== B4 page 3 (index 3 - 认知能力模型) ===")
print(page_text(B4, 3))

print("\n=== B4 page 14 (index 14 - 自驱力) ===")
print(page_text(B4, 14))

print("\n=== B6 page 3-4 (职业兴趣) ===")
print(page_text(B6, 3))
print(page_text(B6, 4))

print("\n=== B6 page 8 (能力优势) ===")
print(page_text(B6, 7))
print(page_text(B6, 8))

print("\n=== B6 page 15 (职业价值观) ===")
print(page_text(B6, 13))
print(page_text(B6, 14))
