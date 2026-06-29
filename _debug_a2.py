import fitz
doc = fitz.open('input/report_A2.pdf')
for i in range(len(doc)):
    print(f'\n=== page {i+1} ===')
    print(doc[i].get_text()[:800])
doc.close()
