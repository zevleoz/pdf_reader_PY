import re, fitz
from pathlib import Path
doc = fitz.open('input/report_B6.pdf')
b6 = '\n'.join(p.get_text() for p in doc)
doc.close()

def _score_after_kw(kw, text, max_chars=400):
    i = text.find(kw)
    if i < 0: return None
    seg = text[i: i + max_chars]
    m = re.search(r"([\d.]+)\s*分", seg)
    if m: return m.group(1)
    m = re.search(r"(?:[\s\n]|^)([\d.]+)\s*\n(?:\s*[A-Za-z]+\s*\n)*[\u4e00-\u9fa5]{2,10}", seg)
    if m: return m.group(1)
    nums = re.findall(r"\b(\d+(?:\.\d+)?)\b", seg)
    for n in nums:
        if n in ("0", "10"): continue
        if n.isdigit() and 1 <= int(n) <= 10:
            return n
    if nums: return nums[0]
    return None

for kw in ['现实型', '研究型', '艺术型', '社会型', '事业型', '常规型']:
    v = _score_after_kw(kw, b6, 300)
    print(f'{kw}: {v}')
    # 查看 300 字符里的内容
    idx = b6.find(kw)
    print(f'  context: {repr(b6[idx: idx+300])[:300]}')

print()
print('=== 能力优势 ===')
anchor = max(b6.find("我的能力优势一览表"), b6.find("能力优势测评报告"), b6.find("能力优势\n"), 0)
seg = b6[anchor: anchor + 2000]
print('anchor:', anchor)
print('seg starts with:', repr(seg[:500]))

for kw in ["语言能力", "逻辑数学能力", "音乐能力", "空间能力",
           "身体运动能力", "人际关系能力", "内省能力", "自然能力"]:
    v = _score_after_kw(kw, seg, 500)
    print(f'{kw}: {v}')
    # 调试
    i = seg.find(kw)
    if i >= 0:
        print(f'  context: {repr(seg[i:i+200])}')
