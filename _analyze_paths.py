"""详细分析 B6 第 14、15 页的所有绘图路径，寻找条形图的数值。"""
from __future__ import annotations
import fitz
from pathlib import Path

pdf_path = Path("input/B6 职业发展_Samson_2026031417271196372(1).pdf")
doc = fitz.open(str(pdf_path))

for page_idx in [13, 14]:
    page = doc[page_idx]
    page_num = page_idx + 1
    print(f"\n{'='*80}")
    print(f"  B6 第 {page_num} 页 - 所有绘图路径分析")
    print(f"{'='*80}")

    # 1. 分析所有绘图对象
    drawings = page.get_drawings()
    print(f"\n共 {len(drawings)} 个 drawing 对象")

    # 收集所有水平线和垂直线
    horizontal_lines = []
    vertical_lines = []
    rect_paths = []

    for d in drawings:
        items = d.get("items", [])
        for item in items:
            op = item[0]
            if op == "l":  # line
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) < 3:  # 水平线
                    horizontal_lines.append({
                        "x0": p1.x, "x1": p2.x, "y": p1.y,
                        "length": abs(p2.x - p1.x),
                    })
                elif abs(p1.x - p2.x) < 3:  # 垂直线
                    vertical_lines.append({
                        "x": p1.x, "y0": p1.y, "y1": p2.y,
                        "length": abs(p2.y - p1.y),
                    })
            elif op == "re":
                rect = item[1]
                rect_paths.append({
                    "x0": rect.x0, "y0": rect.y0,
                    "x1": rect.x1, "y1": rect.y1,
                    "w": rect.width, "h": rect.height,
                    "fill": d.get("fill"), "stroke": d.get("stroke"),
                })

    # 按 y 排序水平线
    horizontal_lines.sort(key=lambda x: x["y"])
    vertical_lines.sort(key=lambda x: x["x"])
    rect_paths.sort(key=lambda r: r["y0"])

    print(f"\n水平线: {len(horizontal_lines)} 条")
    print(f"垂直线: {len(vertical_lines)} 条")
    print(f"矩形路径: {len(rect_paths)} 个")

    # 2. 获取文字及其位置
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
                        "x": span["bbox"][0],
                        "y": span["bbox"][1],
                        "w": span["bbox"][2] - span["bbox"][0],
                        "h": span["bbox"][3] - span["bbox"][1],
                        "size": round(span["size"], 1),
                    })
    text_items.sort(key=lambda x: (x["y"], x["x"]))

    # 3. 识别可能的条形图（矩形填充）- 寻找宽度不同的横向填充矩形
    # 职业价值观可能用细矩形填充表示条形
    # 检查所有 rect，特别是高度较小（1-20px）的
    print(f"\n所有矩形路径（可能是条形图）:")
    for r in rect_paths:
        # 查找同一 y 范围内的中文文字
        nearby_zh = [t["text"] for t in text_items
                     if abs(t["y"] - r["y0"]) < 30 and any("\u4e00" <= c <= "\u9fff" for c in t["text"])]
        nearby_num = [t["text"] for t in text_items
                      if abs(t["y"] - r["y0"]) < 30 and t["text"].replace(".", "").replace(" ", "").isdigit()]
        color = r.get("fill")
        if color:
            color_str = f"RGB({color[0]:.2f},{color[1]:.2f},{color[2]:.2f})"
        else:
            color_str = r.get("stroke", "no-color")

        print(f"  y=[{r['y0']:.1f}-{r['y1']:.1f}] x=[{r['x0']:.1f}-{r['x1']:.1f}] "
              f"w={r['w']:.1f} h={r['h']:.1f} 填充: {color_str}")
        if nearby_zh or nearby_num:
            print(f"    附近文字: {nearby_zh} / 数字: {nearby_num}")

    # 4. 尝试另一种方式：提取所有 text，连同它们的精确位置
    print(f"\n【按行分组文字 - 详细版】")
    rows = []
    for item in text_items:
        found = False
        for row in rows:
            if abs(row["y"] - item["y"]) < 12:
                row["items"].append(item)
                found = True
                break
        if not found:
            rows.append({"y": item["y"], "items": [item]})

    for row in rows:
        items_sorted = sorted(row["items"], key=lambda x: x["x"])
        parts = []
        for t in items_sorted:
            parts.append(f"{t['text']}(x={t['x']:.0f},s={t['size']:.0f})")
        line_content = "  ".join(parts)
        if any("\u4e00" <= c <= "\u9fff" for c in line_content) or \
           any(t["text"].replace(".", "").replace(" ", "").isdigit() and len(t["text"]) <= 6 for t in items_sorted):
            print(f"  y~{row['y']:.1f}: {line_content}")

doc.close()
