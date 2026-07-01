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


def analyze_columns(img: np.ndarray):
    h, w = img.shape[:2]
    print(f"图表图像: {w}x{h}")
    
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    
    yellow_mask = (hsv[:, :, 0] > 20) & (hsv[:, :, 0] < 45) & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 100)
    blue_mask = (hsv[:, :, 0] > 100) & (hsv[:, :, 0] < 130) & (hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 50)
    
    combined_mask = yellow_mask | blue_mask
    
    column_sums = np.sum(combined_mask, axis=0)
    
    print(f"\n列像素统计:")
    print(f"  最大: {np.max(column_sums)}")
    print(f"  最小: {np.min(column_sums)}")
    print(f"  平均: {np.mean(column_sums)}")
    
    threshold = np.mean(column_sums) * 2
    
    active_columns = []
    current_column = None
    for i, val in enumerate(column_sums):
        if val > threshold:
            if current_column is None:
                current_column = i
        else:
            if current_column is not None:
                active_columns.append((current_column, i))
                current_column = None
    if current_column is not None:
        active_columns.append((current_column, w))
    
    print(f"\n检测到 {len(active_columns)} 个活跃列组:")
    for i, (start, end) in enumerate(active_columns):
        width = end - start
        print(f"  列组 {i+1}: x={start}-{end}, 宽度={width}")
    
    row_sums = np.sum(combined_mask, axis=1)
    
    threshold_row = np.mean(row_sums) * 2
    
    active_rows = []
    current_row = None
    for i, val in enumerate(row_sums):
        if val > threshold_row:
            if current_row is None:
                current_row = i
        else:
            if current_row is not None:
                active_rows.append((current_row, i))
                current_row = None
    if current_row is not None:
        active_rows.append((current_row, h))
    
    print(f"\n检测到 {len(active_rows)} 个活跃行组:")
    for i, (start, end) in enumerate(active_rows):
        height = end - start
        print(f"  行组 {i+1}: y={start}-{end}, 高度={height}")
    
    debug_img = img.copy()
    for start, end in active_columns:
        cv2.rectangle(debug_img, (start, 0), (end, h), (0, 0, 255), 1)
    for start, end in active_rows:
        cv2.rectangle(debug_img, (0, start), (w, end), (0, 255, 0), 1)
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_chart_grid.png', cv2.cvtColor(debug_img, cv2.COLOR_RGB2BGR))
    
    return active_columns, active_rows


def analyze_bar_heights(img: np.ndarray, active_rows: list):
    h, w = img.shape[:2]
    
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    yellow_mask = (hsv[:, :, 0] > 20) & (hsv[:, :, 0] < 45) & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 100)
    blue_mask = (hsv[:, :, 0] > 100) & (hsv[:, :, 0] < 130) & (hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 50)
    combined_mask = yellow_mask | blue_mask
    
    print(f"\n分析每个行组的条形高度:")
    
    bars = []
    for row_idx, (row_start, row_end) in enumerate(active_rows):
        row_mask = combined_mask[row_start:row_end, :]
        
        row_width = np.sum(row_mask, axis=0)
        threshold = np.max(row_width) * 0.1
        
        bar_start = None
        bar_end = None
        for col_idx, val in enumerate(row_width):
            if val > threshold:
                if bar_start is None:
                    bar_start = col_idx
                bar_end = col_idx
        
        if bar_start is not None and bar_end is not None:
            bar_width = bar_end - bar_start + 1
            bar_height = row_end - row_start
            
            bar_center_x = (bar_start + bar_end) // 2
            bar_center_y = (row_start + row_end) // 2
            
            bars.append({
                'row': row_idx,
                'y': row_start,
                'x': bar_start,
                'width': bar_width,
                'height': bar_height,
                'center_x': bar_center_x,
                'center_y': bar_center_y
            })
            
            print(f"  行组 {row_idx+1}: y={row_start}-{row_end}, 条形宽度={bar_width}, 条形高度={bar_height}")
    
    return bars


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    pdf_path = base_dir / "input" / "report_B6.pdf"
    
    chart_img = extract_chart_area(pdf_path, 13)
    if chart_img is not None:
        active_cols, active_rows = analyze_columns(chart_img)
        bars = analyze_bar_heights(chart_img, active_rows)
        
        print(f"\n共检测到 {len(bars)} 个条形")
        for bar in bars:
            print(f"  条形: y={bar['y']}, width={bar['width']}")