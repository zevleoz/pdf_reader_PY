import fitz

doc = fitz.open('input/report_A2.pdf')
a2 = '\n'.join(p.get_text() for p in doc)
doc.close()

# 找体质健康与饮食习惯
idx = a2.find("体质健康")
print("=== 体质健康 2000 字符 ===")
print(a2[idx: idx+2000])

# 找 饮食习惯 附近
i2 = a2.find("饮食习惯")
print("\n\n=== 饮食习惯附近 600 字符 ===")
print(a2[max(0, i2-100): i2+600])

# 看 B6 职业价值观完整文本
doc = fitz.open('input/report_B6.pdf')
b6 = '\n'.join(p.get_text() for p in doc)
doc.close()
for kw in ["职业价值观测评报告", "创造发明", "独立自主"]:
    idx = b6.find(kw)
    if idx >= 0:
        print(f"\n=== B6 中 '{kw}' 附近 1000 字符 ===")
        print(b6[max(0, idx-100): idx+1000])
