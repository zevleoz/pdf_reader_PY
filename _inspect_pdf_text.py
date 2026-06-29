"""深入提取 PDF 文本 - 找出所有数字数据。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import fitz

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "data"

pdfs = sorted(INPUT_DIR.glob("*.pdf"))

for pdf in pdfs:
    print("\n" + "=" * 60)
    print("PDF: {}".format(pdf.name))
    print("=" * 60)

    doc = fitz.open(str(pdf))
    print("总页数: {}".format(len(doc)))

    # 检查每页是否有文本
    total_text = 0
    total_images = 0
    for i, page in enumerate(doc, 1):
        text = page.get_text()
        text_len = len(text.strip())
        images = page.get_images(full=True)
        total_text += text_len
        total_images += len(images)
        if text_len < 100:
            print("  page {:02d}: text={} chars, images={} [可能是扫描/图表]".format(
                i, text_len, len(images)))

    print("\n总文本: {} 字符, 总图片: {}".format(total_text, total_images))

    # 提取第 3-6 页的详细文本（通常包含数据）
    for page_num in range(2, min(7, len(doc))):
        text = doc[page_num].get_text()
        if text.strip():
            print("\n--- Page {} (first 600 chars) ---".format(page_num + 1))
            lines = text.split("\n")
            print("\n".join(l for l in lines[:30]))

    doc.close()

print("\n" + "=" * 60)
print("结论:")
print("  - 如果每页都有文本 (>200 chars)，用正则提取即可")
print("  - 如果有很多扫描/图片页，才需要视觉 LLM")
print("=" * 60)
