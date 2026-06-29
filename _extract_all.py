"""全面提取 A2/B3/B4/B6 的文字层数据，按用户要求整理。"""
from __future__ import annotations
import fitz
import re
from pathlib import Path

def extract_all_text_with_pos(pdf_path):
    """提取 PDF 所有页面的文字，附带位置信息。"""
    doc = fitz.open(str(pdf_path))
    pages_data = []
    for i in range(doc.page_count):
        page = doc[i]
        text_dict = page.get_text("dict")
        items = []
        for b in text_dict["blocks"]:
            if "lines" not in b:
                continue
            for line in b["lines"]:
                for span in line["spans"]:
                    t = span["text"].strip()
                    if t:
                        items.append({
                            "text": t,
                            "x": span["bbox"][0],
                            "y": span["bbox"][1],
                            "size": round(span["size"], 1),
                            "page": i + 1,
                        })
        items.sort(key=lambda x: (x["y"], x["x"]))
        pages_data.append({"page": i + 1, "items": items, "raw_text": page.get_text()})
    doc.close()
    return pages_data


def group_by_row(items, y_tol=12):
    """将文字按行分组。"""
    rows = []
    for item in items:
        found = False
        for row in rows:
            if abs(row["y"] - item["y"]) < y_tol:
                row["items"].append(item)
                found = True
                break
        if not found:
            rows.append({"y": item["y"], "items": [item]})
    for row in rows:
        row["items"].sort(key=lambda x: x["x"])
    rows.sort(key=lambda r: r["y"])
    return rows


# ============== A2 提取 ==============
a2_path = Path("input/A2 核心素养_Samson_2026031415314850446(1).pdf")
a2_data = extract_all_text_with_pos(a2_path)

print("=" * 80)
print("A2 关键页面提取")
print("=" * 80)

# 第 4 页 - 情绪稳定性
page4 = a2_data[3]  # index 3 = page 4
rows4 = group_by_row(page4["items"])
print("\n【A2 第 4 页 - 情绪稳定性】")
for row in rows4:
    text = " ".join(t["text"] for t in row["items"])
    if any("\u4e00" <= c <= "\u9fff" for c in text) or re.search(r'\d+\.?\d*', text):
        print(f"  y~{row['y']:.0f}: {text}")

# 第 5 页 - 情绪稳定性子项
page5 = a2_data[4]
rows5 = group_by_row(page5["items"])
print("\n【A2 第 5 页 - 情绪稳定性四个子项】")
for row in rows5:
    text = " ".join(t["text"] for t in row["items"])
    if any("\u4e00" <= c <= "\u9fff" for c in text) or re.search(r'\d+\.?\d*', text):
        print(f"  y~{row['y']:.0f}: {text}")

# 第 6 页 - 依恋关系
page6 = a2_data[5]
rows6 = group_by_row(page6["items"])
print("\n【A2 第 6 页 - 依恋关系】")
for row in rows6:
    text = " ".join(t["text"] for t in row["items"])
    if any("\u4e00" <= c <= "\u9fff" for c in text) or re.search(r'\d+\.?\d*', text):
        print(f"  y~{row['y']:.0f}: {text}")

# 第 7 页 - 体质健康
page7 = a2_data[6]
rows7 = group_by_row(page7["items"])
print("\n【A2 第 7 页 - 体质健康】")
for row in rows7:
    text = " ".join(t["text"] for t in row["items"])
    if any("\u4e00" <= c <= "\u9fff" for c in text) or re.search(r'\d+\.?\d*', text):
        print(f"  y~{row['y']:.0f}: {text}")

# 第 8 页 - 人格（大五）
page8 = a2_data[7]
rows8 = group_by_row(page8["items"])
print("\n【A2 第 8 页 - 人格（大五）】")
for row in rows8:
    text = " ".join(t["text"] for t in row["items"])
    if any("\u4e00" <= c <= "\u9fff" for c in text) or re.search(r'\d+\.?\d*', text):
        print(f"  y~{row['y']:.0f}: {text}")


# ============== B3 提取 ==============
b3_path = Path("input/B3 核心学习能力_Samson_2026031417084772022(1).pdf")
b3_data = extract_all_text_with_pos(b3_path)

print("\n" + "=" * 80)
print("B3 关键页面提取")
print("=" * 80)

# 第 2 页 - 执行功能
page2_b3 = b3_data[1]
rows2_b3 = group_by_row(page2_b3["items"])
print("\n【B3 第 2 页 - 执行功能】")
for row in rows2_b3:
    text = " ".join(t["text"] for t in row["items"])
    if any("\u4e00" <= c <= "\u9fff" for c in text) or re.search(r'\d+\.?\d*', text):
        print(f"  y~{row['y']:.0f}: {text}")

# 第 4 页 - 学习动机
page4_b3 = b3_data[3]
rows4_b3 = group_by_row(page4_b3["items"])
print("\n【B3 第 4 页 - 学习动机】")
for row in rows4_b3:
    text = " ".join(t["text"] for t in row["items"])
    if any("\u4e00" <= c <= "\u9fff" for c in text) or re.search(r'\d+\.?\d*', text):
        print(f"  y~{row['y']:.0f}: {text}")

# 第 6 页 - 学习方法与策略
page6_b3 = b3_data[5]
rows6_b3 = group_by_row(page6_b3["items"])
print("\n【B3 第 6 页 - 学习方法与策略】")
for row in rows6_b3:
    text = " ".join(t["text"] for t in row["items"])
    if any("\u4e00" <= c <= "\u9fff" for c in text) or re.search(r'\d+\.?\d*', text):
        print(f"  y~{row['y']:.0f}: {text}")


# ============== B4 提取 ==============
b4_path = Path("input/B4 核心认知能力和成长型思维_Samson_2026031416112834275(1).pdf")
b4_data = extract_all_text_with_pos(b4_path)

print("\n" + "=" * 80)
print("B4 关键页面提取")
print("=" * 80)

# 第 2 页 - 认知能力总览
page2_b4 = b4_data[1]
rows2_b4 = group_by_row(page2_b4["items"])
print("\n【B4 第 2 页 - 认知能力总览】")
for row in rows2_b4:
    text = " ".join(t["text"] for t in row["items"])
    if any("\u4e00" <= c <= "\u9fff" for c in text) or re.search(r'\d+\.?\d*', text):
        print(f"  y~{row['y']:.0f}: {text}")

# 第 4 页 - 自我概念
page4_b4 = b4_data[3]
rows4_b4 = group_by_row(page4_b4["items"])
print("\n【B4 第 4 页 - 自我概念】")
for row in rows4_b4:
    text = " ".join(t["text"] for t in row["items"])
    if any("\u4e00" <= c <= "\u9fff" for c in text) or re.search(r'\d+\.?\d*', text):
        print(f"  y~{row['y']:.0f}: {text}")

# 第 6 页 - 思维模式
page6_b4 = b4_data[5]
rows6_b4 = group_by_row(page6_b4["items"])
print("\n【B4 第 6 页 - 思维模式】")
for row in rows6_b4:
    text = " ".join(t["text"] for t in row["items"])
    if any("\u4e00" <= c <= "\u9fff" for c in text) or re.search(r'\d+\.?\d*', text):
        print(f"  y~{row['y']:.0f}: {text}")

# 第 8 页 - 自驱力
page8_b4 = b4_data[7]
rows8_b4 = group_by_row(page8_b4["items"])
print("\n【B4 第 8 页 - 自驱力】")
for row in rows8_b4:
    text = " ".join(t["text"] for t in row["items"])
    if any("\u4e00" <= c <= "\u9fff" for c in text) or re.search(r'\d+\.?\d*', text):
        print(f"  y~{row['y']:.0f}: {text}")


# ============== B6 提取 ==============
b6_path = Path("input/B6 职业发展_Samson_2026031417271196372(1).pdf")
b6_data = extract_all_text_with_pos(b6_path)

print("\n" + "=" * 80)
print("B6 关键页面提取")
print("=" * 80)

# 第 4 页 - 职业兴趣
page4_b6 = b6_data[3]
rows4_b6 = group_by_row(page4_b6["items"])
print("\n【B6 第 4 页 - 职业兴趣】")
for row in rows4_b6:
    text = " ".join(t["text"] for t in row["items"])
    if any("\u4e00" <= c <= "\u9fff" for c in text) or re.search(r'\d+\.?\d*', text):
        print(f"  y~{row['y']:.0f}: {text}")

# 第 8 页 - 能力优势
page8_b6 = b6_data[7]
rows8_b6 = group_by_row(page8_b6["items"])
print("\n【B6 第 8 页 - 能力优势】")
for row in rows8_b6:
    text = " ".join(t["text"] for t in row["items"])
    if any("\u4e00" <= c <= "\u9fff" for c in text) or re.search(r'\d+\.?\d*', text):
        print(f"  y~{row['y']:.0f}: {text}")

# 第 14 页 - 职业价值观
page14_b6 = b6_data[13]
rows14_b6 = group_by_row(page14_b6["items"])
print("\n【B6 第 14 页 - 职业价值观（文字层）】")
for row in rows14_b6:
    text = " ".join(t["text"] for t in row["items"])
    if any("\u4e00" <= c <= "\u9fff" for c in text) or re.search(r'\d+\.?\d*', text):
        print(f"  y~{row['y']:.0f}: {text}")

# 第 15 页 - 职业价值观排序
page15_b6 = b6_data[14]
rows15_b6 = group_by_row(page15_b6["items"])
print("\n【B6 第 15 页 - 职业价值观排序（文字层）】")
for row in rows15_b6:
    text = " ".join(t["text"] for t in row["items"])
    if any("\u4e00" <= c <= "\u9fff" for c in text) or re.search(r'\d+\.?\d*', text):
        print(f"  y~{row['y']:.0f}: {text}")
