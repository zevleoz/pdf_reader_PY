import cv2
import numpy as np

for i in range(1, 16):
    img = cv2.imread(f'_ranking_cell_{i}.png')
    if img is None:
        print(f'单元格{i}: 未找到')
        continue
    
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    
    white_pixels = np.sum(binary) / 255
    total_pixels = w * h
    ratio = white_pixels / total_pixels
    
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour_areas = [cv2.contourArea(c) for c in contours if cv2.contourArea(c) > 10]
    
    print(f'单元格{i}: {w}x{h}, 白色像素比例={ratio:.3f}, 轮廓数={len(contour_areas)}, 最大轮廓面积={max(contour_areas) if contour_areas else 0}')
    
    # 保存二值化图像
    cv2.imwrite(f'_cell_{i}_binary.png', binary)