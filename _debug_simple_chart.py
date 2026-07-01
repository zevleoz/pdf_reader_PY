from __future__ import annotations

import fitz
import cv2
import numpy as np
from pathlib import Path


def extract_chart_area(pdf_path: Path, page_idx: int) -> np.ndarray:
    doc = fitz.open(str(pdf_path))
    page = doc[page_idx]
    
    blocks = page.get_text("dict")["blocks"]
    
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
                doc.close()
                return img
    
    doc.close()
    return None


def analyze_chart(img: np.ndarray):
    h, w = img.shape[:2]
    print(f"图表图像: {w}x{h}")
    
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_simple_gray.png', gray)
    
    edges = cv2.Canny(gray, 30, 100)
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_simple_edges.png', edges)
    
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    bar_contours = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 500 or area > 100000:
            continue
        
        x, y, cw, ch = cv2.boundingRect(contour)
        
        if cw < 20 or ch < 20:
            continue
        
        bar_contours.append({'x': x, 'y': y, 'w': cw, 'h': ch, 'area': area})
    
    bar_contours.sort(key=lambda c: c['x'])
    
    print(f"\n边缘检测到 {len(bar_contours)} 个轮廓:")
    for i, bc in enumerate(bar_contours):
        print(f"轮廓 {i+1}: x={bc['x']}, y={bc['y']}, h={bc['h']}, w={bc['w']}, area={bc['area']}")
    
    debug_img = img.copy()
    for i, bc in enumerate(bar_contours):
        cv2.rectangle(debug_img, (bc['x'], bc['y']), (bc['x'] + bc['w'], bc['y'] + bc['h']), (0, 0, 255), 2)
        cv2.putText(debug_img, f"{i+1}", (bc['x'], bc['y'] - 5), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_simple_boxes.png', cv2.cvtColor(debug_img, cv2.COLOR_RGB2BGR))
    
    return bar_contours


def analyze_rows(img: np.ndarray):
    h, w = img.shape[:2]
    
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    
    vertical_projection = np.sum(gray < 240, axis=0)
    
    threshold = np.max(vertical_projection) * 0.3
    
    bars = []
    current_bar = None
    
    for x, val in enumerate(vertical_projection):
        if val > threshold:
            if current_bar is None:
                current_bar = {'start_x': x}
        else:
            if current_bar is not None:
                current_bar['end_x'] = x
                current_bar['width'] = x - current_bar['start_x']
                
                col_region = gray[:, current_bar['start_x']:x]
                row_sums = np.sum(col_region < 240, axis=1)
                
                bar_top = None
                bar_bottom = None
                for y, val in enumerate(row_sums):
                    if val > current_bar['width'] * 0.3:
                        if bar_top is None:
                            bar_top = y
                        bar_bottom = y
                
                if bar_top is not None and bar_bottom is not None:
                    current_bar['top'] = bar_top
                    current_bar['bottom'] = bar_bottom
                    current_bar['height'] = bar_bottom - bar_top
                    bars.append(current_bar)
                
                current_bar = None
    
    bars.sort(key=lambda b: b['start_x'])
    
    print(f"\n行投影检测到 {len(bars)} 个条形:")
    for i, bar in enumerate(bars):
        print(f"条形 {i+1}: x={bar['start_x']}-{bar['end_x']}, y={bar['top']}-{bar['bottom']}, w={bar['width']}, h={bar['height']}")
    
    return bars


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    pdf_path = base_dir / "input" / "report_B6.pdf"
    
    chart_img = extract_chart_area(pdf_path, 13)
    if chart_img is not None:
        print("=== 边缘检测 ===")
        bar_contours = analyze_chart(chart_img)
        
        print("\n=== 行投影 ===")
        bars = analyze_rows(chart_img)