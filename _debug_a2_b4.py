"""检查 A2 中是否有饮食习惯分数数字，以及 B4 中是否有自我概念档位备注。"""
import fitz, re
from pathlib import Path

# 检查 A2
pdf_path = Path(__file__).resolve().parent / "input" / "report_A2.pdf"
doc = fitz.open(str(pdf_path))
a2 = ""
for p in range(len(doc)):
    a2 += doc[p].get_text("text")

# 找 "饮食习惯" 之后 500 字符内的所有数字
print("=== A2: '饮食习惯' 之后 500 字符 ===")
idx = a2.find("饮食习惯")
if idx >= 0:
    sub = a2[idx: idx + 500]
    print(sub)
    nums = re.findall(r"[\d.]+", sub)
    print(f"\n  找到的数字: {nums}")

# 检查 BMI 区域
print("\n\n=== A2: BMI 区域（身高/体重之后）===")
idx = a2.find("BMI：")
if idx >= 0:
    sub = a2[idx: idx + 300]
    print(sub)

# 检查 "得分情况吧" 之后的内容
print("\n\n=== A2: '得分情况吧' 之后 800 字符 ===")
idx = a2.find("得分情况吧")
if idx >= 0:
    sub = a2[idx: idx + 800]
    print(sub)

doc.close()

# 检查 B4：自我概念档位体系备注
pdf_path2 = Path(__file__).resolve().parent / "input" / "report_B4.pdf"
doc2 = fitz.open(str(pdf_path2))
b4 = ""
for p in range(len(doc2)):
    b4 += doc2[p].get_text("text")

print("\n\n=== B4: '自我概念' 相关区域 ===")
for m in re.finditer(r"自我概念", b4):
    pos = m.start()
    start = max(0, pos - 100)
    end = min(len(b4), pos + 400)
    print(f"  在 pos {pos}: {repr(b4[start:end][:300])}")
    print()

# 检查 B4 中是否有 "档位体系"
print("\n\n=== B4: '档位' 相关 ===")
for m in re.finditer(r"档位|体系|grade|Level", b4):
    pos = m.start()
    start = max(0, pos - 50)
    end = min(len(b4), pos + 100)
    print(f"  '{m.group()}' at pos {pos}: {repr(b4[start:end][:150])}")

doc2.close()
