"""检测 B6 PDF 中的图像对象。"""
from __future__ import annotations
import fitz
from pathlib import Path

pdf_path = Path("input/B6 职业发展_Samson_2026031417271196372(1).pdf")
doc = fitz.open(str(pdf_path))

for page_idx in [13, 14]:  # 第 14、15 页
    page = doc[page_idx]
    page_num = page_idx + 1
    print(f"\n{'='*80}")
    print(f"  B6 第 {page_num} 页")
    print(f"{'='*80}")

    # 1. 检查图像对象
    images = page.get_images(full=True)
    print(f"\n图像对象: {len(images)} 个")
    for i, img in enumerate(images):
        xref, xref2, width, height, bpc, colorspace, alt_colorspace, name = img[:8]
        print(f"  #{i}: xref={xref}, size={width}x{height}, bpc={bpc}, colorspace={colorspace}, name={name}")

    # 2. 提取并保存图像
    if images:
        try:
            for i, img in enumerate(images):
                xref = img[0]
                pix = fitz.Pixmap(doc, xref)
                if pix.n >= 5:  # 转换为 RGB
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                save_path = f"output/b6_page{page_num}_img{i}.png"
                pix.save(save_path)
                print(f"  已保存: {save_path}")
                pix = None
        except Exception as e:
            print(f"  保存图像出错: {e}")

    # 3. 将整页渲染为图像（用于调试）
    zoom = 2.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    page_img_path = f"output/b6_page{page_num}_full.png"
    pix.save(page_img_path)
    print(f"\n全页已渲染: {page_img_path} ({pix.width}x{pix.height})")

doc.close()
