"""检查 B4 PDF 中自我概念的整体评分。"""
import fitz, re
from pathlib import Path

pdf_path = Path(__file__).resolve().parent / "input" / "report_B4.pdf"
doc = fitz.open(str(pdf_path))
b4 = ""
for p in range(len(doc)):
    b4 += doc[p].get_text("text")

# 找自我概念的整体评分
print("=== B4 中 '自我概念' 附近的 1000 字符 ===\n")
idx = b4.find("自我概念\nSELF-CONCEPT")
if idx >= 0:
    sub = b4[idx: idx + 1000]
    print(sub)

print("\n\n=== B4 中 '测评结果详情' 之后 1500 字符 ===\n")
idx2 = b4.find("测评结果详情")
if idx2 >= 0:
    sub = b4[idx2: idx2 + 1500]
    print(sub)

# 找所有数字行
print("\n\n=== B4 中自我概念区域的纯数字行 ===\n")
idx3 = b4.find("自我概念")
if idx3 >= 0:
    sub = b4[idx3: idx3 + 2500]
    lines = sub.split("\n")
    for i, ln in enumerate(lines):
        ln = ln.strip()
        if re.match(r"^[\d.]+$", ln) and len(ln) <= 5:
            # 显示前后 5 行
            context = lines[max(0, i-3): min(len(lines), i+4)]
            print(f"  行 {i}: '{ln}' -> 周围: {[c[:20] for c in context]}")

doc.close()
