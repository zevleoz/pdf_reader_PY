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

chart_region = img[200:600, 50:1600]
print(f'图表区域: {chart_region.shape}')

chart_h, chart_w = chart_region.shape[:2]

label_region = chart_region[chart_h-100:chart_h, :]
cv2.imwrite('_label_region.png', cv2.cvtColor(label_region, cv2.COLOR_RGB2BGR))
print(f'标签区域: {label_region.shape}')

gray = cv2.cvtColor(label_region, cv2.COLOR_RGB2GRAY)
_, binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)

cv2.imwrite('_label_binary.png', binary)

contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

labels = []
for contour in contours:
    area = cv2.contourArea(contour)
    if area < 50 or area > 2000:
        continue
    x, y, cw, ch = cv2.boundingRect(contour)
    if cw < 10 or ch < 5:
        continue
    labels.append({'x': x, 'y': y, 'w': cw, 'h': ch})

labels.sort(key=lambda c: c['x'])

print(f'\n检测到的标签:')
for i, label in enumerate(labels):
    print(f'  {i+1}: x={label["x"]}, y={label["y"]}, w={label["w"]}, h={label["h"]}')

bar_x_positions = [145, 232, 320, 406, 493, 581, 668, 756, 843, 930, 1018, 1104, 1192, 1279, 1366]

print(f'\n条形中心位置（相对于图表区域）:')
for i, x in enumerate(bar_x_positions):
    print(f'  {i+1}: x={x}')

print(f'\n标签中心位置:')
for i, label in enumerate(labels):
    center_x = label['x'] + label['w'] // 2
    print(f'  {i+1}: center_x={center_x}')

print(f'\n尝试匹配标签和条形:')
for bar_idx, bar_x in enumerate(bar_x_positions):
    best_match = None
    min_dist = float('inf')
    for label_idx, label in enumerate(labels):
        label_center_x = label['x'] + label['w'] // 2
        dist = abs(bar_x - label_center_x)
        if dist < min_dist:
            min_dist = dist
            best_match = label_idx
    
    if best_match is not None and min_dist < 50:
        print(f'  条形{bar_idx+1} (x={bar_x}) -> 标签{best_match+1} (x={labels[best_match]["x"]})')
    else:
        print(f'  条形{bar_idx+1} (x={bar_x}) -> 无匹配')

for i, label in enumerate(labels):
    label_img = label_region[label['y']:label['y']+label['h'], label['x']:label['x']+label['w']]
    cv2.imwrite(f'_label_{i+1}.png', cv2.cvtColor(label_img, cv2.COLOR_RGB2BGR))
