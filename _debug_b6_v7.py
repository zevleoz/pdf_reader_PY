import re, fitz
doc = fitz.open('input/report_B6.pdf')
b6 = '\n'.join(p.get_text() for p in doc)
doc.close()

# 能力优势锚点
anchor = b6.find("能力优势测评报告")
print('anchor:', anchor)
seg = b6[anchor: anchor+1500]
with open('/tmp/b6_ability.txt', 'w') as f:
    f.write(seg)
print(seg)
