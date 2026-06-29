import re, fitz
from pathlib import Path
doc = fitz.open('input/report_B6.pdf')
b6 = '\n'.join(p.get_text() for p in doc)
doc.close()

# 找职业兴趣区（"职业兴趣" 附近）
idx = b6.find('职业兴趣测评结果')
print('职业兴趣区:')
print(repr(b6[idx: idx+500]))

# 能力优势区
idx = b6.find('能力优势')
print('\n能力优势区:')
print(repr(b6[idx: idx+800]))

# 再找所有 "X..X分" 格式数字
ms = re.findall(r'([\d.]+)\s*分', b6)
print('\n所有 "数字分":', ms[:50])
