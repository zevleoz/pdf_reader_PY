import re, fitz
doc = fitz.open('input/report_B6.pdf')
# 按页分开看
for i, page in enumerate(doc):
    text = page.get_text()
    if "能力优势" in text or "语言能力" in text:
        print(f"=== Page {i+1} ===")
        print(text[:3000])
        print("---END---\n")
doc.close()
