"""深度分析 B6 PDF 第 13-16 页，寻找职业价值观的所有数值。"""
from __future__ import annotations
import fitz
from pathlib import Path

pdf_path = Path("input/B6 职业发展_Samson_2026031417271196372(1).pdf")
doc = fitz.open(str(pdf_path))

# 从第 13 页开始，直到末尾，逐页寻找数字及其上下文
for page_idx in range(len(doc)):
    page = doc[page_idx]
    blocks = page.get_text("dict")["blocks"]
    page_num = page_idx + 1

    # 收集所有文本行，带位置信息
    text_items = []
    for b in blocks:
        if "lines" not in b:
            continue
        for line in b["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if text:
                    text_items.append({
                        "text": text,
                        "size": round(span["size"], 1),
                        "x": round(span["bbox"][0], 1),
                        "y": round(span["bbox"][1], 1),
                        "font": span.get("font", ""),
                    })

    # 寻找数字行，并打印相邻上下文
    print(f"\n=== B6 第 {page_num} 页 (共 {len(doc)} 页) ===")
    for i, item in enumerate(text_items):
        t = item["text"]
        # 纯数字（含小数点），长度 <= 8
        if t.replace(".", "").replace(" ", "").isdigit() and len(t) <= 8:
            # 打印此数字及其前后 5 行上下文
            start = max(0, i - 5)
            end = min(len(text_items), i + 6)
            print(f"\n  [数字行] text='{t}' (x={item['x']}, y={item['y']}, size={item['size']})")
            for k in range(start, end):
                marker = ">>>" if k == i else "   "
                it = text_items[k]
                print(f"  {marker} x={it['x']:>7.1f} y={it['y']:>7.1f} size={it['size']:>5.1f} | {it['text'][:60]}")

doc.close()
