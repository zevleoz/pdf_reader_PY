"""从 B6 PDF 第 14 页和第 15 页的条形图中提取职业价值观的数值。

策略：分析每页的矢量图形路径(drawings)，识别出横向条形图的长度，再与数字刻度(0-10)对应，算出每个条形的数值。"""
from __future__ import annotations
import fitz
from pathlib import Path

pdf_path = Path("input/B6 职业发展_Samson_2026031417271196372(1).pdf")
doc = fitz.open(str(pdf_path))

# 职业价值观主页面：第 14 页（索引 13）
# 职业价值观一览表：第 15 页（索引 14）

for page_idx in [13, 14]:
    page = doc[page_idx]
    page_num = page_idx + 1
    print(f"\n{'='*80}")
    print(f"  B6 第 {page_num} 页")
    print(f"{'='*80}")

    # 1. 获取页面文字和位置
    print("\n【文字与位置】")
    text_dict = page.get_text("dict")
    text_items = []
    for b in text_dict["blocks"]:
        if "lines" not in b:
            continue
        for line in b["lines"]:
            for span in line["spans"]:
                t = span["text"].strip()
                if t:
                    text_items.append({
                        "text": t,
                        "x0": span["bbox"][0],
                        "y0": span["bbox"][1],
                        "x1": span["bbox"][2],
                        "y1": span["bbox"][3],
                        "size": round(span["size"], 1),
                        "font": span.get("font", ""),
                    })

    # 分组：按 y 位置相似的行
    text_items.sort(key=lambda x: (x["y0"], x["x0"]))

    # 2. 获取所有矢量绘图（用于识别条形图）
    print("\n【矢量图形（矩形）】")
    drawings = page.get_drawings()
    rectangles = []
    for d in drawings:
        # 只看矩形填充
        if d["type"] == "f":  # filled
            # 获取矩形边界
            items = d.get("items", [])
            for item in items:
                if len(item) >= 2:
                    op = item[0]
                    if op == "re":  # rectangle
                        rect = item[1]
                        width = round(rect.width, 1)
                        height = round(rect.height, 1)
                        if 1 < width < 1000 and 1 < height < 100:  # 可能是条形
                            rectangles.append({
                                "x0": round(rect.x0, 1),
                                "y0": round(rect.y0, 1),
                                "x1": round(rect.x1, 1),
                                "y1": round(rect.y1, 1),
                                "w": width,
                                "h": height,
                                "color": d.get("fill"),
                            })

    # 按 y 排序
    rectangles.sort(key=lambda r: (r["y0"]))
    print(f"共 {len(rectangles)} 个矩形")

    # 3. 寻找横向对齐的文字和条形（同一 y 范围）
    print("\n【条形 + 文字配对分析】")

    # 找出 y 区间内所有文字标签（中文标签）和数字（条形数值）
    for r in rectangles:
        y_range = (r["y0"] - 20, r["y1"] + 20)
        x_range = (0, r["x1"] + 30)
        nearby_texts = [t for t in text_items
                         if y_range[0] <= t["y0"] <= y_range[1]
                         and t["x0"] <= r["x1"] + 50]
        if nearby_texts:
            # 只打印有中文标签的
            has_chinese = any("\u4e00" <= c <= "\u9fff" for t in nearby_texts for c in t["text"])
            if has_chinese or len(nearby_texts) > 0:
                label_text = " | ".join(t["text"] for t in nearby_texts)
                print(f"  条形: y=[{r['y0']:.1f}, {r['y1']:.1f}] x=[{r['x0']:.1f}, {r['x1']:.1f}] w={r['w']:.1f} h={r['h']:.1f}")
                print(f"    附近文字: {label_text}")

    # 4. 打印整页所有中文标签及其数值
    print("\n【详细列表（按行分组）】")
    # 按 y 聚类，相同行（y 差小于 15）归为一组
    rows = []
    for item in text_items:
        # 找现有 row
        found = False
        for row in rows:
            if abs(row["y"] - item["y0"]) < 15:
                row["items"].append(item)
                found = True
                break
        if not found:
            rows.append({"y": item["y0"], "items": [item]})

    for row in rows:
        items_sorted = sorted(row["items"], key=lambda x: x["x0"])
        line_content = " | ".join(t["text"] for t in items_sorted)
        if any("\u4e00" <= c <= "\u9fff" for c in line_content) or \
           any(t["text"].replace(".", "").replace(" ", "").isdigit() and len(t["text"]) <= 8 for t in items_sorted):
            print(f"  y~{row['y']:.1f}: {line_content}")

doc.close()
