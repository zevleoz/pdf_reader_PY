"""读取 4 份 PDF 的全部文本，按页输出，帮助人工核对 124 个数据点。"""
from __future__ import annotations
import fitz
from pathlib import Path

INPUT_DIR = Path("input")
pdf_files = sorted(INPUT_DIR.glob("*.pdf"))

for pdf_path in pdf_files:
    stem = pdf_path.stem
    print(f"\n{'='*80}")
    print(f"  {stem}")
    print(f"{'='*80}")
    doc = fitz.open(str(pdf_path))
    for i, page in enumerate(doc, 1):
        text = page.get_text()
        print(f"\n--- 第 {i} 页 ---")
        # 保留换行，便于看清结构
        print(text)
    doc.close()
    print()
