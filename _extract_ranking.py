import cv2
import numpy as np

VALUE_LABELS = [
    "创造发明", "独立自主", "美的追求", "智力激发", "利他助人",
    "成就感", "管理权力", "工作环境", "同事关系", "上司关系",
    "多样变化", "经济报酬", "安全稳定", "声望地位", "生活方式"
]

def extract_ranking_from_page15(img_path: str) -> dict:
    img = cv2.imread(img_path)
    if img is None:
        return {}
    
    h, w = img.shape[:2]
    
    lower_half = img[int(h * 0.45):int(h * 0.95), :]
    lh, lw = lower_half.shape[:2]
    
    gray = cv2.cvtColor(lower_half, cv2.COLOR_BGR2GRAY)
    
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    
    adaptive = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                     cv2.THRESH_BINARY_INV, 11, 2)
    
    kernel = np.ones((2, 2), np.uint8)
    adaptive = cv2.morphologyEx(adaptive, cv2.MORPH_OPEN, kernel)
    
    contours, _ = cv2.findContours(adaptive, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    number_contours = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 20 or area > 800:
            continue
        
        x, y, cw, ch = cv2.boundingRect(contour)
        
        if cw < 8 or ch < 8:
            continue
        
        aspect_ratio = float(cw) / ch if ch > 0 else 0
        if aspect_ratio > 2 or aspect_ratio < 0.3:
            continue
        
        number_contours.append({'x': x, 'y': y, 'w': cw, 'h': ch, 'area': area})
    
    number_contours = sorted(number_contours, key=lambda c: c['y'])
    
    print(f"检测到 {len(number_contours)} 个数字轮廓")
    
    ranking = []
    for i, cnt in enumerate(number_contours[:15]):
        x, y, cw, ch = cnt['x'], cnt['y'], cnt['w'], cnt['h']
        
        row_center_y = y + ch // 2
        row_start = max(0, row_center_y - 30)
        row_end = min(lh, row_center_y + 30)
        
        row_region = adaptive[row_start:row_end, :]
        
        col_sums = row_region.sum(axis=0)
        
        non_zero_cols = np.where(col_sums > 500)[0]
        
        if len(non_zero_cols) > 0:
            text_start = non_zero_cols.min()
            text_end = non_zero_cols.max()
            
            print(f"  排名 {i+1}: 数字位置 ({x},{y}), 文本区域 {text_start}-{text_end}")
            
            ranking.append({
                'rank': i + 1,
                'y': y,
                'text_region': (text_start, text_end)
            })
    
    return {'ranking': ranking}

if __name__ == '__main__':
    result = extract_ranking_from_page15('data/page15.png')
    print(f"\n排序结果: {result}")
