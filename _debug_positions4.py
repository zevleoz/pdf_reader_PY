"""详细查看 B6 第 14、15、16 页，找职业价值观的完整结构。"""
import json
from pathlib import Path
import fitz

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))

# 只输出 14-16 页
for page_idx in [13, 14, 15]:
    page = doc[page_idx]
    blocks = page.get_text("dict")["blocks"]
    print(f"\n========== Page {page_idx+1} (doc {page_idx}) ==========")
    items = []
    for block in blocks:
        for line in block.get("lines", []):
            for span in line["spans"]:
                t = span["text"].strip()
                if not t: continue
                bbox = span["bbox"]
                items.append({
                    "text": t,
                    "x": bbox[0], "y": bbox[1],
                    "x1": bbox[2], "y1": bbox[3],
                    "size": span["size"],
                })
    for item in items:
        print(f"  x={item['x']:.0f} y={item['y']:.0f} x1={item['x1']:.0f} size={item['size']:.1f} text={repr(item['text'])}")

doc.close()
