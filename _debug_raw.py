import fitz
from pathlib import Path

# 看 B6 第 8 页附近完整文本
doc = fitz.open('input/report_B6.pdf')
for page_idx in range(len(doc)):
    text = doc[page_idx].get_text()
    if "能力优势" in text or "语言能力" in text or "职业价值观" in text or "创造发明" in text:
        print(f"\n===== Page {page_idx+1} (doc page {page_idx}) =====")
        print(text[:4000])
doc.close()

# 看 A2 体质健康
doc2 = fitz.open('input/report_A2.pdf')
for page_idx in range(len(doc2)):
    text = doc2[page_idx].get_text()
    if "体质健康" in text or "饮食" in text or "BMI" in text or "情绪稳定性" in text:
        print(f"\n===== A2 Page {page_idx+1} =====")
        print(text[:4000])
doc2.close()
