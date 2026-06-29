import json
from pathlib import Path
import fitz

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
TARGET_LABELS = ["创造发明", "独立自主", "美的追求", "智力激发", "利他助人",
                 "成就感", "管理权力", "工作环境", "同事关系", "上司关系",
                 "多样变化", "经济报酬", "安全稳定", "声望地位", "生活方式"]

doc = fitz.open(str(pdf_path))
page = doc[11]  # 第 12 页
# 找所有文本块：每个 span
blocks = page.get_text("dict")["blocks"]

items = []
for block in blocks:
    for line in block.get("lines", []):
        for span in line["spans"]:
            t = span["text"].strip()
            if not t: continue
            font_size = span["size"]
            font = span["origin"] if "origin" in span else 0
            bbox = span["bbox"]  # (x0, y0, x1, y1)
            items.append({
                "text": t,
                "x0": bbox[0],
                "y0": bbox[1],
                "x1": bbox[2],
                "y1": bbox[3],
                "size": font_size,
            })

# 打印带坐标（只打印包含目标标签或纯数字的 span
interesting = []
for item in items:
    t = item["text"]
    if t in TARGET_LABELS:
        interesting.append(item)
    elif t.replace(".", "").isdigit():
        interesting.append(item)
    elif "职业价值观" in t:
        interesting.append(item)

with open("/tmp/b6_items.json", "w", encoding="utf-8") as f:
    json.dump(interesting, f, ensure_ascii=False, indent=2)

for item in interesting[-50:]:
    print(f"x={item['x0']:.1f} y={item['y0']:.1f} x1={item['x1']:.1f} size={item['size']:.1f} text={repr(item['text'])}")
