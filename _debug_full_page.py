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


def analyze_full_page(img: np.ndarray):
    h, w = img.shape[:2]
    print(f"页面: {w}x{h}")
    
    chart_region = img[400:800, 100:500]
    chart_h, chart_w = chart_region.shape[:2]
    print(f"图表区域: {chart_w}x{chart_h}")
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_page14_chart_raw.png', cv2.cvtColor(chart_region, cv2.COLOR_RGB2BGR))
    
    gray = cv2.cvtColor(chart_region, cv2.COLOR_RGB2GRAY)
    
    _, binary = cv2.threshold(gray, 210, 255, cv2.THRESH_BINARY_INV)
    
    kernel = np.ones((3, 3), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_page14_chart_binary.png', binary)
    
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    bar_contours = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 200 or area > 50000:
            continue
        
        x, y, cw, ch = cv2.boundingRect(contour)
        
        if cw < 15 or ch < 20:
            continue
        
        bar_contours.append({'x': x, 'y': y, 'w': cw, 'h': ch, 'area': area})
    
    bar_contours.sort(key=lambda c: c['y'])
    
    print(f"\n检测到 {len(bar_contours)} 个条形:")
    for i, bc in enumerate(bar_contours):
        print(f"条形 {i+1}: y={bc['y']}, x={bc['x']}, h={bc['h']}, w={bc['w']}, area={bc['area']}")
    
    debug_img = chart_region.copy()
    for i, bc in enumerate(bar_contours):
        cv2.rectangle(debug_img, (bc['x'], bc['y']), (bc['x'] + bc['w'], bc['y'] + bc['h']), (0, 0, 255), 2)
        cv2.putText(debug_img, f"{i+1}", (bc['x'], bc['y'] - 5), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_page14_chart_boxes.png', cv2.cvtColor(debug_img, cv2.COLOR_RGB2BGR))
    
    return bar_contours


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    pdf_path = base_dir / "input" / "report_B6.pdf"
    
    img_14 = render_page(pdf_path, 13)
    analyze_full_page(img_14)