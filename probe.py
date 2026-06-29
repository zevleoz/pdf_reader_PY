"""探查脚本：把 input/ 中 4 份 PDF 每页的文本内容详细打印，
用于观察"得分 / 百分位 / 评分等级"在文本层的呈现方式。

也会把每页渲染成 PNG，方便人工核查图表位置。
"""
from __future__ import annotations
import json
from pathlib import Path
import fitz

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUT_DIR = BASE_DIR / "probe"
OUT_DIR.mkdir(exist_ok=True)

for pdf_path in sorted(INPUT_DIR.glob("*.pdf")):
    doc = fitz.open(pdf_path)
    print(f"\n{'='*80}")
    print(f"FILE: {pdf_path.name} ({doc.page_count} pages)")
    print("="*80)

    img_dir = OUT_DIR / pdf_path.stem
    img_dir.mkdir(exist_ok=True)

    data = {}
    for i, page in enumerate(doc, 1):
        text = page.get_text()
        # 打印全部文本（截断）
        print(f"\n--- Page {i} ---")
        lines = text.splitlines()
        for line in lines[:30]:
            s = line.strip()
            if s:
                print(f"   {s}")
        if len(lines) > 30:
            print(f"   ... (+{len(lines)-30} more lines)")

        # 同时存一页图片，方便肉眼核对
        zoom = 1.4
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        pix.save(str(img_dir / f"page_{i:02d}.png"))

        # 结构化保存
        data[f"page_{i:02d}"] = {
            "text_lines": [l.strip() for l in lines if l.strip()],
            "images": len(page.get_images(full=True)),
            "size": [page.rect.width, page.rect.height],
        }

    (OUT_DIR / f"{pdf_path.stem}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    doc.close()

print("\nDone. Images and JSON under", OUT_DIR)
