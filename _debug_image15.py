"""在文本层中搜索"安全稳定"周围的数值。"""
import fitz, re
from pathlib import Path

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))
page = doc[13]
text = page.get_text("text")
# 搜索"安全稳定"周围的内容
lines = text.split('\n')
for i, line in enumerate(lines):
    if "安全稳定" in line or "5.46" in line or "8.39" in line or "9.39" in line:
        print(f"  L{i}: '{line}'")
doc.close()

# 另外检查整个第 12 页文本（图表可能在第 12 页）
print("\n=== 第 12 页相关内容 ===")
doc2 = fitz.open(str(pdf_path))
page12 = doc2[11]
text12 = page12.get_text("text")
lines = text12.split('\n')
for i, line in enumerate(lines):
    if any(kw in line for kw in ['安全稳定', '创造发明', '生活方式', '职业价值']):
        print(f"  L{i}: '{line}'")
doc2.close()
