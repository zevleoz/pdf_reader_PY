import re, fitz

# --- B6 工作价值观
doc = fitz.open('input/report_B6.pdf')
b6 = '\n'.join(p.get_text() for p in doc)
doc.close()

# 锚点：找 "MY WORK VALUES" 或 "职业价值观" 或 "生活方式"
for kw in ["MY WORK VALUES", "职业价值观", "工作价值观"]:
    idx = b6.find(kw)
    if idx >= 0:
        print(f"Found {kw} at {idx}")
        print(b6[idx: idx+3000])
        print("========")
        break
