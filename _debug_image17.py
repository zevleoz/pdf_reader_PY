"""检查 B6 职业价值观文本层的完整内容。"""
import fitz, re
from pathlib import Path

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))

# 读取 B6 所有文本
b6_text = ""
for p in range(len(doc)):
    b6_text += f"\n=== PAGE {p+1} ===\n"
    b6_text += doc[p].get_text("text")

# 找 "得分情况如下" 之后的内容
anchor = b6_text.find("得分情况如下")
if anchor >= 0:
    # 打印之后 2000 字符
    print("=== '得分情况如下' 之后 2000 字符 ===")
    print(b6_text[anchor:anchor+2000])
    print()

# 找 14 项数值相关的文本：直接搜索每个已知的数值
known_values = ["7.70", "8.56", "3.29", "5.16", "9.36", "6.48", "6.73",
                 "9.32", "6.79", "6.67", "9.39", "5.46", "8.39"]
print("=== 已知数值所在的上下文 ===")
for v in known_values:
    for m in re.finditer(re.escape(v), b6_text):
        start = max(0, m.start() - 50)
        end = min(len(b6_text), m.end() + 50)
        print(f"  {v}: ...{b6_text[start:end]}...")
        break

doc.close()
