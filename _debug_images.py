"""检查 PDF 中的嵌入图像（位图）。"""
import json
from pathlib import Path
import fitz

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))

for page_idx in range(len(doc)):
    page = doc[page_idx]
    # 列出当前页的所有图像
    images = page.get_images(full=True)
    if images:
        print(f"=== 第 {page_idx+1} 页有 {len(images)} 个图像 ===")
        for i, img in enumerate(images):
            # img 格式: (xref, smask, width, height, bpc, colorspace, ...)
            print(f"  #{i}: xref={img[0]}, size={img[2]}x{img[3]}, bpc={img[4]}, cs={img[5]}")

doc.close()
