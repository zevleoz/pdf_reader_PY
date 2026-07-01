import cv2
import numpy as np
import fitz

doc = fitz.open('input/report_B6.pdf')
page = doc[14]
zoom = 200 / 72.0
mat = fitz.Matrix(zoom, zoom)
pix = page.get_pixmap(matrix=mat, alpha=False)
img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
doc.close()

h, w = img.shape[:2]
print(f'页面尺寸: {w} x {h}')

chart_region = img[200:600, 50:w-50]
print(f'图表区域: {chart_region.shape}')

hsv = cv2.cvtColor(chart_region, cv2.COLOR_RGB2HSV)
yellow_mask = (hsv[:,:,0] > 15) & (hsv[:,:,0] < 50) & (hsv[:,:,1] > 50) & (hsv[:,:,2] > 80)
blue_mask = (hsv[:,:,0] > 90) & (hsv[:,:,0] < 140) & (hsv[:,:,1] > 30) & (hsv[:,:,2] > 50)
red_mask = (hsv[:,:,0] > 0) & (hsv[:,:,0] < 20) & (hsv[:,:,1] > 30) & (hsv[:,:,2] > 80)
green_mask = (hsv[:,:,0] > 40) & (hsv[:,:,0] < 80) & (hsv[:,:,1] > 30) & (hsv[:,:,2] > 50)
combined_mask = yellow_mask | blue_mask | red_mask | green_mask

kernel = np.ones((3,3), np.uint8)
combined_mask = cv2.morphologyEx(combined_mask.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_OPEN, kernel)

contours, _ = cv2.findContours(combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

bars = []
for contour in contours:
    area = cv2.contourArea(contour)
    if area < 200 or area > 100000:
        continue
    x, y, cw, ch = cv2.boundingRect(contour)
    if cw < 15 or ch < 30:
        continue
    bars.append({'x': x, 'y': y, 'w': cw, 'h': ch})

bars.sort(key=lambda c: c['x'])

print(f'\n条形位置（从左到右）:')
for i, bar in enumerate(bars):
    print(f'  {i+1}: x={bar["x"]}, y={bar["y"]}, w={bar["w"]}, h={bar["h"]}')

print(f'\n条形中心位置:')
for i, bar in enumerate(bars):
    center_x = bar['x'] + bar['w'] // 2
    print(f'  {i+1}: center_x={center_x}')

labels = ["创造发明", "独立自主", "美的追求", "智力激发", "利他助人",
          "成就感", "管理权力", "工作环境", "同事关系", "上司关系",
          "多样变化", "经济报酬", "安全稳定", "声望地位", "生活方式"]

print(f'\n标签数量: {len(labels)}')
print(f'条形数量: {len(bars)}')

print(f'\n按位置分配标签:')
for i, bar in enumerate(bars):
    if i < len(labels):
        print(f'  x={bar["x"]}: {labels[i]}')
