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

chart_region = img[200:600, 50:w-50]
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

chart_h, chart_w = chart_region.shape[:2]
label_region = img[600:700, 50:w-50]
cv2.imwrite('_labels_region.png', cv2.cvtColor(label_region, cv2.COLOR_RGB2BGR))

print(f'标签区域: {label_region.shape[1]}x{label_region.shape[0]}')

bar_width = bar_contours[1]['x'] - bar_contours[0]['x'] if len(bar_contours) > 1 else 87

for i, bar in enumerate(bar_contours):
    x_center = bar['x'] + bar['w'] // 2
    start_x = max(0, x_center - bar_width // 2)
    end_x = min(label_region.shape[1], x_center + bar_width // 2)
    
    label_img = label_region[:, int(start_x):int(end_x)]
    cv2.imwrite(f'_label_{i+1}.png', cv2.cvtColor(label_img, cv2.COLOR_RGB2BGR))
    
    h, w = label_img.shape[:2]
    gray = cv2.cvtColor(label_img, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    white_ratio = np.sum(binary) / 255 / (w * h)
    
    print(f'标签{i+1}: x={bar["x"]}, 区域={start_x:.0f}-{end_x:.0f}, 白色比例={white_ratio:.3f}')

doc.close()