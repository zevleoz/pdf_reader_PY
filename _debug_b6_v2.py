import fitz
doc = fitz.open('input/report_B6.pdf')
# page 13-15 职业价值观区
for i in range(12, 18):
    if i < len(doc):
        print(f'\n=== page {i+1} ===')
        print(doc[i].get_text()[:1500])
doc.close()
