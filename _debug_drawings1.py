"""检查 PDF 绘图命令。使用 fitz 的 drawing 分析。"""
import json
from pathlib import Path
import fitz

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))

# 看第 14 页的绘制路径
page = doc[13]
# 用 get_drawings() 获取 vector drawing
drawings = page.get_drawings()
print(f"第 14 页有 {len(drawings)} 个绘图命令")

# 看前 10 个绘图的 bbox
for i, d in enumerate(drawings[:20]):
    rect = d.get("rect")
    items = d.get("items") or []
    fill = d.get("fill")
    stroke = d.get("stroke")
    print(f"  drawing#{i}: bbox={rect}, items={len(items)}, fill={fill}, stroke={stroke}")

doc.close()
