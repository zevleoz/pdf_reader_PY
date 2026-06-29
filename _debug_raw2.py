import fitz
doc = fitz.open('input/report_B6.pdf')
# 打印第 11、12、13、14 页的原始文本
for page_idx in [10, 11, 12, 13, 14]:
    text = doc[page_idx].get_text()
    print(f"\n===== Page {page_idx+1} (doc page {page_idx}) =====")
    print(text[:3000])
doc.close()
