import re, fitz
from pathlib import Path
doc = fitz.open('input/report_B6.pdf')
b6 = '\n'.join(p.get_text() for p in doc)
doc.close()

# Holland code
m = re.search(r'(?:Holland|职业兴趣)[\s\S]{0,400}?(?:代码|Code|类型)[\s\S]{0,120}?([A-Za-z]{3,6})', b6)
print('Holland match:', m.group(1) if m else None)

# Let's anchor on "Holland Code" line and look immediately after
idx = b6.find('Holland Code')
print('Holland Code context:', repr(b6[idx:idx+80]))

# 研究型 附近
m = re.search(r'研究型[\s\S]{0,80}?([\d.]+)\s*(?:分|得分)?', b6)
print('研究型:', m.group(1) if m else None)
idx = b6.find('研究型')
print('研究型 context:', repr(b6[idx:idx+200]))

# 逻辑数学能力 附近
m = re.search(r'逻辑数学能力[\s\S]{0,80}?([\d.]+)\s*(?:分|得分)?', b6)
print('逻辑数学:', m.group(1) if m else None)
idx = b6.find('逻辑数学能力')
print('context:', repr(b6[idx:idx+200]))

# 音乐能力
m = re.search(r'音乐能力[\s\S]{0,80}?([\d.]+)\s*(?:分|得分)?', b6)
print('音乐:', m.group(1) if m else None)
idx = b6.find('音乐能力')
print('context:', repr(b6[idx:idx+200]))

# 空间能力
m = re.search(r'空间能力[\s\S]{0,80}?([\d.]+)\s*(?:分|得分)?', b6)
print('空间:', m.group(1) if m else None)
idx = b6.find('空间能力')
print('context:', repr(b6[idx:idx+200]))

# 身体运动
m = re.search(r'身体运动能力[\s\S]{0,80}?([\d.]+)\s*(?:分|得分)?', b6)
print('身体运动:', m.group(1) if m else None)
idx = b6.find('身体运动能力')
print('context:', repr(b6[idx:idx+200]))

# 人际关系
m = re.search(r'人际关系能力[\s\S]{0,80}?([\d.]+)\s*(?:分|得分)?', b6)
print('人际关系:', m.group(1) if m else None)
idx = b6.find('人际关系能力')
print('context:', repr(b6[idx:idx+200]))

# 内省
m = re.search(r'内省能力[\s\S]{0,80}?([\d.]+)\s*(?:分|得分)?', b6)
print('内省:', m.group(1) if m else None)
idx = b6.find('内省能力')
print('context:', repr(b6[idx:idx+200]))

# 自然能力
m = re.search(r'自然能力[\s\S]{0,80}?([\d.]+)\s*(?:分|得分)?', b6)
print('自然:', m.group(1) if m else None)
idx = b6.find('自然能力')
print('context:', repr(b6[idx:idx+200]))
