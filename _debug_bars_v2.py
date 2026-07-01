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


def analyze_bar_chart(img: np.ndarray):
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
    
    print(f"检测到 {len(bar_contours)} 个条形")
    print("-" * 80)
    for i, bc in enumerate(bar_contours):
        print(f"条形 {i+1}: y={bc['y']}, x={bc['x']}, h={bc['h']}, w={bc['w']}, area={bc['area']}")
    
    groups = []
    current_group = []
    for bc in bar_contours:
        if not current_group:
            current_group.append(bc)
        else:
            if bc['y'] - current_group[-1]['y'] < 100:
                current_group.append(bc)
            else:
                groups.append(current_group)
                current_group = [bc]
    if current_group:
        groups.append(current_group)
    
    print(f"\n条形分布在 {len(groups)} 个行组:")
    for i, g in enumerate(groups):
        print(f"  组 {i+1}: {len(g)} 个条形, y范围: {g[0]['y']} - {g[-1]['y']}")
        for j, bc in enumerate(g):
            print(f"    条形 {j+1}: y={bc['y']}, h={bc['h']}, x={bc['x']}")
    
    debug_img = img.copy()
    for i, bc in enumerate(bar_contours):
        cv2.rectangle(debug_img, (bc['x'], bc['y']), (bc['x'] + bc['w'], bc['y'] + bc['h']), (0, 0, 255), 2)
        cv2.putText(debug_img, f"{i+1}:h={bc['h']}", (bc['x'], bc['y'] - 5), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_debug_bars.png', cv2.cvtColor(debug_img, cv2.COLOR_RGB2BGR))
    print("\n调试图像已保存: _debug_bars.png")


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    pdf_path = base_dir / "input" / "report_B6.pdf"
    
    img_15 = render_page(pdf_path, 14)
    print(f"第15页: {img_15.shape[1]}x{img_15.shape[0]}")
    
    analyze_bar_chart(img_15)