import json
from pathlib import Path
import fitz

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))

print(f"总页数: {len(doc)}")

# 打印每一页的文本（用"dict"获得坐标）
for page_idx in range(len(doc)):
    page = doc[page_idx]
    blocks = page.get_text("dict")["blocks"]
    items = []
    for block in blocks:
        for line in block.get("lines", []):
            for span in line["spans"]:
                t = span["text"].strip()
                if not t: continue
                bbox = span["bbox"]
                items.append({
                    "text": t,
                    "x0": bbox[0], "y0": bbox[1],
                    "x1": bbox[2], "y1": bbox[3],
                    "size": span["size"],
                })
    # 找中文标签和数字
    chinese_labels = [i for i in items if any('\u4e00' <= c <= '\u9fff' for c in i["text"])]
    pure_nums = [i for i in items if i["text"].replace(".", "").isdigit()]
    if chinese_labels or pure_nums:
        print(f"---- Page {page_idx+1} (doc {page_idx}) ----")
        for i in chinese_labels:
            print(f"  LABEL: x={i['x0']:.0f} y={i['y0']:.0f} size={i['size']:.1f} text={repr(i['text'])}")
        for i in pure_nums:
            print(f"  NUM:   x={i['x0']:.0f} y={i['y0']:.0f} size={i['size']:.1f} text={repr(i['text'])}")

doc.close()
