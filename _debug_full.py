"""详细分析 B6 第 14 页的所有 text span 和 drawing 对象。"""
import json
import re
from pathlib import Path
import fitz

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))
page = doc[13]  # 第 14 页

# 1) 打印所有 text span
print("=== 所有 TEXT SPAN ===")
blocks = page.get_text("dict")["blocks"]
span_list = []
for block in blocks:
    for line in block.get("lines", []):
        for span in line["spans"]:
            t = span["text"]
            if not t or t.isspace(): continue
            bbox = span["bbox"]
            span_list.append({
                "text": t, "x": bbox[0], "y": bbox[1],
                "x1": bbox[2], "y1": bbox[3],
                "size": span["size"], "font": span["font"]
            })
span_list.sort(key=lambda s: (s["y"], s["x"]))
for s in span_list:
    print(f"  x={s['x']:.0f}, y={s['y']:.0f}, size={s['size']:.1f}: {repr(s['text'])}")

# 2) 打印所有 drawing
print("\n=== 所有 DRAWING ===")
drawings = page.get_drawings()
for i, d in enumerate(drawings):
    rect = d.get("rect")
    fill = d.get("fill")
    stroke = d.get("stroke")
    print(f"  #{i}: bbox={rect}, fill={fill}, stroke={stroke}, items={len(d.get('items', []))}")
    # 打印 items 细节（前几个）
    for j, item in enumerate(d.get("items", [])[:5]):
        print(f"    item{j}: {item}")

doc.close()
