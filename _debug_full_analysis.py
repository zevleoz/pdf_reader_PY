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


def analyze_page(img: np.ndarray):
    h, w = img.shape[:2]
    print(f"页面: {w}x{h}")
    
    chart_region = img[400:800, :]
    chart_h, chart_w = chart_region.shape[:2]
    print(f"图表区域: {chart_w}x{chart_h}")
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_full_chart_raw.png', cv2.cvtColor(chart_region, cv2.COLOR_RGB2BGR))
    
    hsv = cv2.cvtColor(chart_region, cv2.COLOR_RGB2HSV)
    
    yellow_mask = (hsv[:, :, 0] > 20) & (hsv[:, :, 0] < 45) & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 100)
    blue_mask = (hsv[:, :, 0] > 100) & (hsv[:, :, 0] < 130) & (hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 50)
    red_mask = (hsv[:, :, 0] > 0) & (hsv[:, :, 0] < 15) & (hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 80)
    
    combined_mask = yellow_mask | blue_mask | red_mask
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_full_chart_color_mask.png', combined_mask.astype(np.uint8) * 255)
    
    contours, _ = cv2.findContours(combined_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    bar_contours = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 1000 or area > 100000:
            continue
        
        x, y, cw, ch = cv2.boundingRect(contour)
        
        if cw < 30 or ch < 30:
            continue
        
        bar_contours.append({'x': x, 'y': y, 'w': cw, 'h': ch, 'area': area})
    
    bar_contours.sort(key=lambda c: c['x'])
    
    print(f"\n检测到 {len(bar_contours)} 个彩色条形:")
    for i, bc in enumerate(bar_contours):
        print(f"条形 {i+1}: x={bc['x']}, y={bc['y']}, h={bc['h']}, w={bc['w']}, area={bc['area']}")
    
    debug_img = chart_region.copy()
    for i, bc in enumerate(bar_contours):
        cv2.rectangle(debug_img, (bc['x'], bc['y']), (bc['x'] + bc['w'], bc['y'] + bc['h']), (0, 0, 255), 2)
        cv2.putText(debug_img, f"{i+1}:h={bc['h']}", (bc['x'], bc['y'] - 5), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_full_chart_boxes.png', cv2.cvtColor(debug_img, cv2.COLOR_RGB2BGR))
    
    return bar_contours


def analyze_color_columns(img: np.ndarray):
    h, w = img.shape[:2]
    
    chart_region = img[400:800, :]
    chart_h, chart_w = chart_region.shape[:2]
    
    hsv = cv2.cvtColor(chart_region, cv2.COLOR_RGB2HSV)
    
    yellow_mask = (hsv[:, :, 0] > 20) & (hsv[:, :, 0] < 45) & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 100)
    blue_mask = (hsv[:, :, 0] > 100) & (hsv[:, :, 0] < 130) & (hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 50)
    
    combined_mask = yellow_mask | blue_mask
    
    column_sums = np.sum(combined_mask, axis=0)
    
    active_columns = []
    current_col = None
    for i, val in enumerate(column_sums):
        if val > 50:
            if current_col is None:
                current_col = i
        else:
            if current_col is not None:
                active_columns.append((current_col, i))
                current_col = None
    if current_col is not None:
        active_columns.append((current_col, chart_w))
    
    print(f"\n检测到 {len(active_columns)} 个彩色列:")
    for i, (start, end) in enumerate(active_columns):
        col_width = end - start
        print(f"列 {i+1}: x={start}-{end}, 宽度={col_width}")
    
    bars = []
    for col_start, col_end in active_columns:
        col_width = end - col_start
        if col_width < 20:
            continue
        
        col_mask = combined_mask[:, col_start:col_end]
        row_sums = np.sum(col_mask, axis=1)
        
        bar_top = None
        bar_bottom = None
        for row_idx, val in enumerate(row_sums):
            if val > col_width * 0.5:
                if bar_top is None:
                    bar_top = row_idx
                bar_bottom = row_idx
        
        if bar_top is not None and bar_bottom is not None:
            bar_height = bar_bottom - bar_top + 1
            bars.append({
                'x': col_start,
                'y': bar_top,
                'w': col_width,
                'h': bar_height
            })
    
    bars.sort(key=lambda b: b['x'])
    
    print(f"\n从彩色列检测到 {len(bars)} 个条形:")
    for i, bar in enumerate(bars):
        print(f"条形 {i+1}: x={bar['x']}, y={bar['y']}, h={bar['h']}, w={bar['w']}")
    
    return bars


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    pdf_path = base_dir / "input" / "report_B6.pdf"
    
    img_14 = render_page(pdf_path, 13)
    
    print("=== 轮廓检测 ===")
    bar_contours = analyze_page(img_14)
    
    print("\n=== 列分析 ===")
    bars = analyze_color_columns(img_14)