"""检查 A2 PDF 文本层中 "饮食习惯" 附近的内容。"""
import fitz, re
from pathlib import Path

pdf_path = Path(__file__).resolve().parent / "input" / "report_A2.pdf"
doc = fitz.open(str(pdf_path))
a2 = ""
for p in range(len(doc)):
    a2 += doc[p].get_text("text")

# 找 "饮食习惯" 前后 300 字符
idx = a2.find("饮食习惯")
if idx >= 0:
    start = max(0, idx - 100)
    end = min(len(a2), idx + 300)
    print("=== 饮食习惯 附近 400 字符 ===")
    print(repr(a2[start:end]))
    print()

# 也找 "饮食" 相关的其他内容
for m in re.finditer(r"(饮食|体质健康|BMI|身高|体重)", a2):
    start = max(0, m.start() - 50)
    end = min(len(a2), m.end() + 100)
    print(f"  '{m.group()}' at pos {m.start()}: {repr(a2[start:end])}")
    print()

# 找所有 "X分" 格式
print("=== A2 中所有 'X分' 格式 ===")
for m in re.finditer(r"([\d.]+)\s*分", a2):
    pos = m.start()
    start = max(0, pos - 50)
    end = min(len(a2), pos + 50)
    print(f"  '{m.group(0)}' at pos {pos}: {repr(a2[start:end][:80])}")

doc.close()
