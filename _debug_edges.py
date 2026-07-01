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


def analyze_with_edges(img: np.ndarray):
    h, w = img.shape[:2]
    
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    
    edges = cv2.Canny(gray, 50, 150)
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_chart_edges.png', edges)
    
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    bar_candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 1000 or area > 200000:
            continue
        
        x, y, cw, ch = cv2.boundingRect(contour)
        
        if cw < 20 or ch < 50:
            continue
        
        bar_candidates.append({'x': x, 'y': y, 'w': cw, 'h': ch, 'area': area})
    
    bar_candidates.sort(key=lambda c: c['y'])
    
    print(f"边缘检测到 {len(bar_candidates)} 个候选条形:")
    for i, bc in enumerate(bar_candidates):
        print(f"候选 {i+1}: y={bc['y']}, x={bc['x']}, h={bc['h']}, w={bc['w']}, area={bc['area']}")
    
    debug_img = img.copy()
    for i, bc in enumerate(bar_candidates):
        cv2.rectangle(debug_img, (bc['x'], bc['y']), (bc['x'] + bc['w'], bc['y'] + bc['h']), (0, 0, 255), 2)
        cv2.putText(debug_img, f"{i+1}", (bc['x'], bc['y'] - 5), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_chart_edge_boxes.png', cv2.cvtColor(debug_img, cv2.COLOR_RGB2BGR))
    print("\n边缘检测图像已保存")
    
    return bar_candidates


def analyze_hsv_separate(img: np.ndarray):
    h, w = img.shape[:2]
    
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    
    yellow_mask = (hsv[:, :, 0] > 20) & (hsv[:, :, 0] < 45) & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 100)
    blue_mask = (hsv[:, :, 0] > 100) & (hsv[:, :, 0] < 130) & (hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 50)
    
    yellow_kernel = np.ones((5, 5), np.uint8)
    yellow_mask_clean = cv2.morphologyEx(yellow_mask.astype(np.uint8), cv2.MORPH_CLOSE, yellow_kernel)
    yellow_mask_clean = cv2.morphologyEx(yellow_mask_clean, cv2.MORPH_OPEN, yellow_kernel)
    
    blue_kernel = np.ones((5, 5), np.uint8)
    blue_mask_clean = cv2.morphologyEx(blue_mask.astype(np.uint8), cv2.MORPH_CLOSE, blue_kernel)
    blue_mask_clean = cv2.morphologyEx(blue_mask_clean, cv2.MORPH_OPEN, blue_kernel)
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_chart_yellow_clean.png', yellow_mask_clean * 255)
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_chart_blue_clean.png', blue_mask_clean * 255)
    
    contours_yellow, _ = cv2.findContours(yellow_mask_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours_blue, _ = cv2.findContours(blue_mask_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    print(f"\n黄色区域检测到 {len(contours_yellow)} 个轮廓")
    for i, contour in enumerate(contours_yellow):
        x, y, cw, ch = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        print(f"黄色 {i+1}: x={x}, y={y}, w={cw}, h={ch}, area={area}")
    
    print(f"\n蓝色区域检测到 {len(contours_blue)} 个轮廓")
    for i, contour in enumerate(contours_blue):
        x, y, cw, ch = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        print(f"蓝色 {i+1}: x={x}, y={y}, w={cw}, h={ch}, area={area}")


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    pdf_path = base_dir / "input" / "report_B6.pdf"
    
    chart_img = extract_chart_area(pdf_path, 13)
    if chart_img is not None:
        print("=== 边缘检测 ===")
        analyze_with_edges(chart_img)
        print("\n=== HSV分割 ===")
        analyze_hsv_separate(chart_img)