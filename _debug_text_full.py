from __future__ import annotations

import fitz
from pathlib import Path


def analyze_text_full(pdf_path: Path, page_idx: int):
    doc = fitz.open(str(pdf_path))
    page = doc[page_idx]
    
    text = page.get_text()
    print(f"第{page_idx+1}页完整文本:\n")
    print(text)
    print("\n" + "="*80 + "\n")
    
    blocks = page.get_text("dict")["blocks"]
    
    for i, block in enumerate(blocks):
        if block["type"] == 0:
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if text:
                        bbox = span["bbox"]
                        print(f"文本: '{text}' | x={bbox[0]:.1f}, y={bbox[1]:.1f}, w={bbox[2]-bbox[0]:.1f}, h={bbox[3]-bbox[1]:.1f}, size={span['size']:.1f}")
        elif block["type"] == 1:
            bbox = block["bbox"]
            print(f"图像: x={bbox[0]:.1f}, y={bbox[1]:.1f}, w={bbox[2]-bbox[0]:.1f}, h={bbox[3]-bbox[1]:.1f}")
    
    doc.close()


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    pdf_path = base_dir / "input" / "report_B6.pdf"
    
    analyze_text_full(pdf_path, 13)