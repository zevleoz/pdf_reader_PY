"""高精度提取：先查看各 PDF 的关键数据页面内容，然后精准提取。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

import fitz

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"

pdfs = sorted(INPUT_DIR.glob("*.pdf"))

# 定义每个 PDF 中感兴趣的页面（基于结构）
for pdf in pdfs:
    print("\n" + "=" * 70)
    print("PDF: {}".format(pdf.name))
    print("=" * 70)

    doc = fitz.open(str(pdf))
    print("总页数: {}".format(len(doc)))

    # 提取所有页面中包含数字的重要文本行
    for page_idx in range(len(doc)):
        text = doc[page_idx].get_text()
        lines = [l.strip() for l in text.splitlines() if l.strip()]

        if len(lines) < 3:
            continue

        # 提取可能有数据的行
        data_lines = []
        for i, line in enumerate(lines):
            # 标签行（中文字符）
            if re.search(r"[\u4e00-\u9fff]{2,20}", line) and len(line) < 40:
                # 同行或下一行有数字
                has_num = bool(re.search(r"\d+(?:\.\d+)?\s*(?:分|%|cm|kg|CM|KG|小时)?", line))
                next_has_num = False
                if i + 1 < len(lines):
                    next_has_num = bool(re.search(r"^\d+(?:\.\d+)?\s*(?:分|%|cm|kg|CM|KG|小时|岁)?$", lines[i+1]))
                if has_num or next_has_num:
                    data_lines.append((i, line))
                    if next_has_num and i + 1 < len(lines):
                        data_lines.append((i + 1, "  -> " + lines[i + 1]))

        # 找 "我的得分" / "平均" 模式
        score_lines = []
        for i, line in enumerate(lines):
            if "我的得分" in line or "平均分" in line or "同龄人" in line or "得分" in line:
                score_lines.append((i, line))
                # 显示附近上下文
                for j in range(max(0, i-2), min(len(lines), i+3)):
                    if j != i:
                        score_lines.append((j, "    " + lines[j]))

        print("\n  Page {} ({} lines)".format(page_idx + 1, len(lines)))
        if data_lines:
            print("  [潜在数据点]")
            for idx, line in data_lines[:15]:
                print("    {:3d}: {}".format(idx, line[:80]))

        if score_lines:
            print("  [得分上下文]")
            for idx, line in score_lines[:20]:
                print("    {:3d}: {}".format(idx, line[:100]))

    doc.close()
