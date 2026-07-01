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
                break
    
    doc.close()
    return chart_image


def analyze_projection(img: np.ndarray):
    h, w = img.shape[:2]
    
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    
    vertical_projection = np.sum(binary, axis=1)
    horizontal_projection = np.sum(binary, axis=0)
    
    print(f"垂直投影: min={np.min(vertical_projection)}, max={np.max(vertical_projection)}")
    print(f"水平投影: min={np.min(horizontal_projection)}, max={np.max(horizontal_projection)}")
    
    v_lines = []
    current_line = None
    for i, val in enumerate(vertical_projection):
        if val > 100:
            if current_line is None:
                current_line = i
        else:
            if current_line is not None:
                v_lines.append((current_line, i))
                current_line = None
    if current_line is not None:
        v_lines.append((current_line, h))
    
    print(f"\n垂直投影检测到 {len(v_lines)} 条水平线:")
    for i, (start, end) in enumerate(v_lines):
        height = end - start
        if height > 20:
            print(f"  线 {i+1}: y={start}-{end}, 高度={height}")
    
    h_lines = []
    current_line = None
    for i, val in enumerate(horizontal_projection):
        if val > 50:
            if current_line is None:
                current_line = i
        else:
            if current_line is not None:
                h_lines.append((current_line, i))
                current_line = None
    if current_line is not None:
        h_lines.append((current_line, w))
    
    print(f"\n水平投影检测到 {len(h_lines)} 条垂直线:")
    for i, (start, end) in enumerate(h_lines):
        width = end - start
        if width > 20:
            print(f"  线 {i+1}: x={start}-{end}, 宽度={width}")
    
    debug_img = img.copy()
    for start, end in v_lines:
        cv2.line(debug_img, (0, start), (w, start), (0, 255, 0), 1)
        cv2.line(debug_img, (0, end), (w, end), (0, 255, 0), 1)
    
    for start, end in h_lines:
        cv2.line(debug_img, (start, 0), (start, h), (255, 0, 0), 1)
        cv2.line(debug_img, (end, 0), (end, h), (255, 0, 0), 1)
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_chart_projection.png', cv2.cvtColor(debug_img, cv2.COLOR_RGB2BGR))
    print("\n投影分析图像已保存")


def analyze_bar_colors(img: np.ndarray):
    h, w = img.shape[:2]
    
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    
    for row in range(0, h, 100):
        row_hsv = hsv[row, :, :]
        avg_h = np.mean(row_hsv[:, 0])
        avg_s = np.mean(row_hsv[:, 1])
        avg_v = np.mean(row_hsv[:, 2])
        print(f"行 {row}: H={avg_h:.1f}, S={avg_s:.1f}, V={avg_v:.1f}")
    
    yellow_mask = (hsv[:, :, 0] > 10) & (hsv[:, :, 0] < 50) & (hsv[:, :, 1] > 30) & (hsv[:, :, 2] > 80)
    blue_mask = (hsv[:, :, 0] > 90) & (hsv[:, :, 0] < 140) & (hsv[:, :, 1] > 30) & (hsv[:, :, 2] > 50)
    green_mask = (hsv[:, :, 0] > 40) & (hsv[:, :, 0] < 80) & (hsv[:, :, 1] > 30) & (hsv[:, :, 2] > 50)
    
    print(f"\n黄色像素: {np.sum(yellow_mask)}")
    print(f"蓝色像素: {np.sum(blue_mask)}")
    print(f"绿色像素: {np.sum(green_mask)}")
    
    combined_mask = yellow_mask | blue_mask | green_mask
    print(f"合计彩色像素: {np.sum(combined_mask)}")
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_chart_yellow_mask.png', yellow_mask.astype(np.uint8) * 255)
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_chart_blue_mask.png', blue_mask.astype(np.uint8) * 255)
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_chart_green_mask.png', green_mask.astype(np.uint8) * 255)


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    pdf_path = base_dir / "input" / "report_B6.pdf"
    
    chart_img = extract_chart_area(pdf_path, 13)
    if chart_img is not None:
        print("=== 投影分析 ===")
        analyze_projection(chart_img)
        print("\n=== 颜色分析 ===")
        analyze_bar_colors(chart_img)