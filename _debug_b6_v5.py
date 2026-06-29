import re, fitz
doc = fitz.open('input/report_B6.pdf')
b6 = '\n'.join(p.get_text() for p in doc)
doc.close()

anchor = b6.find("职业兴趣测评结果")
print('anchor:', anchor)
seg = b6[anchor: anchor+1500]
# 打印 seg 的原始文本
with open('/tmp/b6_interests.txt', 'w') as f:
    f.write(seg)
print('wrote /tmp/b6_interests.txt')
