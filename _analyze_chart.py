import fitz
import cv2
import numpy as np

doc = fitz.open('input/report_B6.pdf')
page = doc[14]
mat = fitz.Matrix(2, 2)
pix = page.get_pixmap(matrix=mat, alpha=False)
img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

h, w = img.shape[:2]
print(f'页面尺寸: {w}x{h}')

chart_region = img[200:600, 50:1500]
cv2.imwrite('_chart_zoomed.png', cv2.cvtColor(chart_region, cv2.COLOR_RGB2BGR))
print('已保存放大的图表区域')

hsv = cv2.cvtColor(chart_region, cv2.COLOR_RGB2HSV)
yellow_mask = (hsv[:,:,0] > 15) & (hsv[:,:,0] < 50) & (hsv[:,:,1] > 50) & (hsv[:,:,2] > 80)
blue_mask = (hsv[:,:,0] > 90) & (hsv[:,:,0] < 140) & (hsv[:,:,1] > 30) & (hsv[:,:,2] > 50)
red_mask = (hsv[:,:,0] > 0) & (hsv[:,:,0] < 20) & (hsv[:,:,1] > 30) & (hsv[:,:,2] > 80)
green_mask = (hsv[:,:,0] > 40) & (hsv[:,:,0] < 80) & (hsv[:,:,1] > 30) & (hsv[:,:,2] > 50)
combined_mask = yellow_mask | blue_mask | red_mask | green_mask

contours, _ = cv2.findContours(combined_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
bar_contours = []
for contour in contours:
    area = cv2.contourArea(contour)
    if area < 200 or area > 100000:
        continue
    x, y, cw, ch = cv2.boundingRect(contour)
    if cw < 15 or ch < 30:
        continue
    bar_contours.append({'x': x, 'y': y, 'w': cw, 'h': ch})

bar_contours.sort(key=lambda c: c['x'])
print(f'检测到 {len(bar_contours)} 个条形:')
for i, bc in enumerate(bar_contours):
    x_val = bc["x"]
    y_val = bc["y"]
    h_val = bc["h"]
    print(f'  条形{i+1}: x={x_val}, y={y_val}, h={h_val}')

doc.close()