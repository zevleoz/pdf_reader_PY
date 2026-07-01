from __future__ import annotations

import fitz
import cv2
import numpy as np
from pathlib import Path


def render_page(pdf_path: Path, page_idx: int, dpi: int = 200) -> np.ndarray:
    doc = fitz.open(str(pdf_path))
    page = doc[page_idx]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    doc.close()
    return img


def analyze_text_layout(pdf_path: Path, page_idx: int):
    doc = fitz.open(str(pdf_path))
    page = doc[page_idx]
    
    blocks = page.get_text("dict")["blocks"]
    
    print(f"第{page_idx+1}页文本块分析:")
    print("-" * 80)
    
    for i, block in enumerate(blocks):
        if block["type"] == 0:
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if text:
                        bbox = span["bbox"]
                        print(f"文本: '{text}' | x={bbox[0]:.1f}, y={bbox[1]:.1f}")
        elif block["type"] == 1:
            bbox = block["bbox"]
            print(f"图像: x={bbox[0]:.1f}, y={bbox[1]:.1f}, w={bbox[2]-bbox[0]:.1f}, h={bbox[3]-bbox[1]:.1f}")
    
    doc.close()


def analyze_bar_chart(img: np.ndarray, page_num: int):
    h, w = img.shape[:2]
    
    r = img[:, :, 0]
    g = img[:, :, 1]
    b = img[:, :, 2]
    
    yellow_mask = (r > 180) & (g > 130) & (b < 180) & (r > g) & (g > b)
    
    kernel = np.ones((3, 3), np.uint8)
    yellow_mask = cv2.morphologyEx(yellow_mask.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
    
    contours, _ = cv2.findContours(yellow_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    bar_contours = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 300:
            continue
        
        x, y, cw, ch = cv2.boundingRect(contour)
        
        if cw < 15 or ch < 50:
            continue
        
        bar_contours.append({'x': x, 'y': y, 'w': cw, 'h': ch, 'area': area})
    
    bar_contours.sort(key=lambda c: c['y'])
    
    print(f"\n第{page_num}页条形检测:")
    print(f"检测到 {len(bar_contours)} 个条形")
    for i, bc in enumerate(bar_contours):
        print(f"条形 {i+1}: y={bc['y']}, x={bc['x']}, h={bc['h']}, w={bc['w']}")
    
    debug_img = img.copy()
    for i, bc in enumerate(bar_contours):
        cv2.rectangle(debug_img, (bc['x'], bc['y']), (bc['x'] + bc['w'], bc['y'] + bc['h']), (0, 0, 255), 2)
        cv2.putText(debug_img, f"{i+1}:h={bc['h']}", (bc['x'], bc['y'] - 5), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    
    cv2.imwrite(f'/Users/jefflau/projects/pdf_report_converter/PDF_converter/_debug_page{page_num}.png', cv2.cvtColor(debug_img, cv2.COLOR_RGB2BGR))
    print(f"调试图像已保存: _debug_page{page_num}.png")


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    pdf_path = base_dir / "input" / "report_B6.pdf"
    
    analyze_text_layout(pdf_path, 13)
    img_14 = render_page(pdf_path, 13)
    analyze_bar_chart(img_14, 14)