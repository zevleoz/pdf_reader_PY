"""直接搜索 B6 文本层中"安全稳定"前后的数字。"""
import fitz, re
from pathlib import Path

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))

# 读取 B6 所有文本
all_text = ""
for p in range(len(doc)):
    all_text += f"\n=== PAGE {p+1} ===\n"
    all_text += doc[p].get_text("text")

# 搜索 "安全稳定" 前后 200 字符
matches = list(re.finditer(r"安全稳定", all_text))
print(f"找到 {len(matches)} 处 '安全稳定'\n")
for m in matches:
    start = max(0, m.start() - 300)
    end = min(len(all_text), m.end() + 300)
    ctx = all_text[start:end]
    # 只显示前 500 字符
    print(f"--- Context around pos {m.start()} ---")
    print(ctx)
    print()

doc.close()

# 另外检查：安全稳定周围找 "经济报酬" 和 "声望地位" 的位置
print("\n=== '经济报酬' 前后的数字 ===")
for m in re.finditer(r"经济报酬", all_text):
    start = max(0, m.start() - 200)
    end = min(len(all_text), m.end() + 200)
    print(all_text[start:end])
    print()

print("\n=== '声望地位' 前后的数字 ===")
for m in re.finditer(r"声望地位", all_text):
    start = max(0, m.start() - 200)
    end = min(len(all_text), m.end() + 200)
    print(all_text[start:end])
    print()
