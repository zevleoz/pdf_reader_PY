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

ranking_region = img[700:h-200, :]
print(f'排序区域: {ranking_region.shape}')

cv2.imwrite('_ranking_region.png', cv2.cvtColor(ranking_region, cv2.COLOR_RGB2BGR))

gray = cv2.cvtColor(ranking_region, cv2.COLOR_RGB2GRAY)
_, binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)

cv2.imwrite('_ranking_binary.png', binary)

contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

cells = []
for contour in contours:
    area = cv2.contourArea(contour)
    if area < 50 or area > 5000:
        continue
    x, y, cw, ch = cv2.boundingRect(contour)
    if cw < 10 or ch < 10:
        continue
    cells.append({'x': x, 'y': y, 'w': cw, 'h': ch})

cells.sort(key=lambda c: (c['y'], c['x']))

print(f'\n排序区域单元格:')
for i, cell in enumerate(cells):
    print(f'  {i+1}: x={cell["x"]}, y={cell["y"]}, w={cell["w"]}, h={cell["h"]}')

for i, cell in enumerate(cells):
    cell_img = ranking_region[cell['y']:cell['y']+cell['h'], cell['x']:cell['x']+cell['w']]
    cv2.imwrite(f'_cell_{i+1}.png', cv2.cvtColor(cell_img, cv2.COLOR_RGB2BGR))

print(f'\n提取了 {len(cells)} 个单元格')
