from __future__ import annotations

import fitz
import cv2
import numpy as np
from pathlib import Path


def extract_images_from_page(pdf_path: Path, page_idx: int):
    doc = fitz.open(str(pdf_path))
    page = doc[page_idx]
    
    blocks = page.get_text("dict")["blocks"]
    
    images = []
    for block in blocks:
        if block["type"] == 1:
            bbox = block["bbox"]
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            if w > 50 and h > 50:
                img_rect = fitz.Rect(bbox)
                pix = page.get_pixmap(matrix=fitz.Matrix(4, 4), clip=img_rect, alpha=False)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                images.append({
                    'img': img,
                    'bbox': bbox,
                    'x': bbox[0],
                    'y': bbox[1],
                    'w': w,
                    'h': h
                })
    
    doc.close()
    return images


def analyze_single_image(img_data: dict, index: int):
    img = img_data['img']
    h, w = img.shape[:2]
    
    print(f"\n图像 {index}: x={img_data['x']:.1f}, y={img_data['y']:.1f}, 大小={w}x{h}")
    
    cv2.imwrite(f'/Users/jefflau/projects/pdf_report_converter/PDF_converter/_img_{index}_raw.png', cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    
    yellow_mask = (hsv[:, :, 0] > 20) & (hsv[:, :, 0] < 45) & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 100)
    blue_mask = (hsv[:, :, 0] > 100) & (hsv[:, :, 0] < 130) & (hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 50)
    red_mask = (hsv[:, :, 0] > 0) & (hsv[:, :, 0] < 15) & (hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 80)
    
    combined_mask = yellow_mask | blue_mask | red_mask
    
    cv2.imwrite(f'/Users/jefflau/projects/pdf_report_converter/PDF_converter/_img_{index}_mask.png', combined_mask.astype(np.uint8) * 255)
    
    contours, _ = cv2.findContours(combined_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    bar_height = 0
    for contour in contours:
        area = cv2.contourArea(contour)
        if area > 50:
            _, y, _, ch = cv2.boundingRect(contour)
            if ch > bar_height:
                bar_height = ch
    
    print(f"  检测到条形高度: {bar_height}")
    
    return bar_height


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    pdf_path = base_dir / "input" / "report_B6.pdf"
    
    images = extract_images_from_page(pdf_path, 14)
    
    print(f"第15页检测到 {len(images)} 个图像")
    
    bar_heights = []
    for i, img_data in enumerate(images):
        height = analyze_single_image(img_data, i+1)
        if height > 0:
            bar_heights.append({
                'index': i,
                'x': img_data['x'],
                'y': img_data['y'],
                'height': height
            })
    
    bar_heights.sort(key=lambda b: b['y'])
    
    print(f"\n共检测到 {len(bar_heights)} 个有效的条形高度:")
    for bh in bar_heights:
        print(f"  y={bh['y']:.1f}: 高度={bh['height']}")