"""检查 '得分情况如下' 之后所有文本，看看职业价值观结构化数据到底在哪里。"""
import fitz, re
from pathlib import Path

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))

b6_text = doc[13].get_text("text")  # 第 14 页
lines = [l.strip() for l in b6_text.splitlines() if l.strip()]
print(f"第 14 页有 {len(lines)} 行非空文本：")
for i, l in enumerate(lines):
    print(f"  L{i}: {repr(l)}")

# 现在检查第 13 页（索引 12）——可能职业价值观结构化数据在第 13 页
print("\n\n=== 第 13 页 ===")
b6_text_p12 = doc[12].get_text("text")
lines = [l.strip() for l in b6_text_p12.splitlines() if l.strip()]
for i, l in enumerate(lines):
    print(f"  L{i}: {repr(l)}")

# 检查第 6 页到第 18 页的职业价值观相关内容
print("\n\n=== 职业价值观相关内容：检查所有页 ===")
for p in range(len(doc)):
    txt = doc[p].get_text("text")
    if "职业价值观" in txt or "创造发明" in txt:
        print(f"\n--- 第 {p+1} 页 ---")
        # 打印前 50 行
        lines = [l.strip() for l in txt.splitlines() if l.strip()][:50]
        for i, l in enumerate(lines):
            print(f"  L{i}: {repr(l)}")

doc.close()
