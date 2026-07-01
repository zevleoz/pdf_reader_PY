import cv2
import numpy as np

VALUE_LABELS = [
    "创造发明", "独立自主", "美的追求", "智力激发", "利他助人",
    "成就感", "管理权力", "工作环境", "同事关系", "上司关系",
    "多样变化", "经济报酬", "安全稳定", "声望地位", "生活方式"
]

def extract_ranking_from_page15(img_path: str) -> list:
    img = cv2.imread(img_path)
    if img is None:
        return []
    
    h, w = img.shape[:2]
    
    ranking_region = img[int(h * 0.55):int(h * 0.95), :]
    rh, rw = ranking_region.shape[:2]
    
    gray = cv2.cvtColor(ranking_region, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blur, 200, 255, cv2.THRESH_BINARY_INV)
    
    kernel = np.ones((3, 3), np.uint8)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
    
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    number_boxes = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 50 or area > 500:
            continue
        
        x, y, cw, ch = cv2.boundingRect(contour)
        
        if cw < 10 or ch < 10:
            continue
        
        if x > rw * 0.85:
            number_boxes.append({'x': x, 'y': y, 'w': cw, 'h': ch})
    
    number_boxes = sorted(number_boxes, key=lambda b: b['y'])[:15]
    
    print(f"检测到 {len(number_boxes)} 个数字框（右侧）")
    
    ranking = []
    for i, box in enumerate(number_boxes):
        x, y, cw, ch = box['x'], box['y'], box['w'], box['h']
        
        text_region = ranking_region[y:y+ch, :x-10]
        
        text_gray = cv2.cvtColor(text_region, cv2.COLOR_BGR2GRAY)
        _, text_thresh = cv2.threshold(text_gray, 200, 255, cv2.THRESH_BINARY_INV)
        
        col_sum = text_thresh.sum(axis=0)
        non_zero_cols = np.where(col_sum > 500)[0]
        
        if len(non_zero_cols) > 0:
            text_start = non_zero_cols.min()
            text_end = non_zero_cols.max()
            
            print(f"  排名 {i+1}: 数字位置 ({x},{y}), 文本宽度 {text_end-text_start}")
            
            ranking.append({
                'rank': i + 1,
                'y': y,
                'text_width': text_end - text_start
            })
    
    return ranking

def match_labels_by_text_width(ranking: list, bar_scores: dict) -> dict:
    sorted_labels = sorted(bar_scores.keys(), key=lambda k: bar_scores[k], reverse=True)
    
    ranking.sort(key=lambda r: r['y'])
    
    result = {}
    for i, rank_item in enumerate(ranking):
        if i < len(sorted_labels):
            result[sorted_labels[i]] = rank_item['rank']
    
    return result

if __name__ == '__main__':
    ranking = extract_ranking_from_page15('data/page15.png')
    print(f"\n排序结果: {ranking}")
