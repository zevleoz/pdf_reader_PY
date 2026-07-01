from __future__ import annotations

import fitz
import cv2
import numpy as np
from pathlib import Path


def extract_chart_area(pdf_path: Path, page_idx: int) -> np.ndarray:
    doc = fitz.open(str(pdf_path))
    page = doc[page_idx]
    
    blocks = page.get_text("dict")["blocks"]
    
    chart_image = None
    for block in blocks:
        if block["type"] == 1:
            bbox = block["bbox"]
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            if w > 300 and h > 300:
                chart_rect = fitz.Rect(bbox)
                pix = page.get_pixmap(matrix=fitz.Matrix(4, 4), clip=chart_rect, alpha=False)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                chart_image = img
                print(f"提取图表区域: x={bbox[0]}, y={bbox[1]}, w={w}, h={h}")
                break
    
    doc.close()
    return chart_image


def analyze_chart(img: np.ndarray):
    h, w = img.shape[:2]
    print(f"图表图像: {w}x{h}")
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_chart_raw.png', cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    
    yellow_mask = (h > 15) & (h < 40) & (s > 50) & (v > 100)
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_chart_yellow.png', yellow_mask.astype(np.uint8) * 255)
    
    kernel = np.ones((5, 5), np.uint8)
    yellow_mask = cv2.morphologyEx(yellow_mask.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
    yellow_mask = cv2.morphologyEx(yellow_mask.astype(np.uint8), cv2.MORPH_OPEN, kernel)
    
    contours, _ = cv2.findContours(yellow_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    bar_contours = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 200:
            continue
        
        x, y, cw, ch = cv2.boundingRect(contour)
        
        if cw < 10 or ch < 30:
            continue
        
        bar_contours.append({'x': x, 'y': y, 'w': cw, 'h': ch, 'area': area})
    
    bar_contours.sort(key=lambda c: c['y'])
    
    print(f"\n检测到 {len(bar_contours)} 个条形:")
    for i, bc in enumerate(bar_contours):
        print(f"条形 {i+1}: y={bc['y']}, x={bc['x']}, h={bc['h']}, w={bc['w']}, area={bc['area']}")
    
    debug_img = img.copy()
    for i, bc in enumerate(bar_contours):
        cv2.rectangle(debug_img, (bc['x'], bc['y']), (bc['x'] + bc['w'], bc['y'] + bc['h']), (0, 0, 255), 2)
        cv2.putText(debug_img, f"{i+1}:h={bc['h']}", (bc['x'], bc['y'] - 5), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_chart_analyzed.png', cv2.cvtColor(debug_img, cv2.COLOR_RGB2BGR))
    print("\n调试图像已保存")
    
    return bar_contours


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    pdf_path = base_dir / "input" / "report_B6.pdf"
    
    chart_img = extract_chart_area(pdf_path, 13)
    if chart_img is not None:
        analyze_chart(chart_img)