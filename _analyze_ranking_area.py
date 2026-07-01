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

# 查看排序区域（根据之前的分析，编号在y≈329-656区域）
ranking_region = img[300:700, :]
cv2.imwrite('_ranking_full.png', cv2.cvtColor(ranking_region, cv2.COLOR_RGB2BGR))
print('已保存排序区域')

# 查看排序区域的左侧（编号）
ranking_left = img[300:700, :200]
cv2.imwrite('_ranking_left.png', cv2.cvtColor(ranking_left, cv2.COLOR_RGB2BGR))
print('已保存排序区域左侧')

# 查看排序区域的右侧（价值观）
ranking_right = img[300:700, 200:]
cv2.imwrite('_ranking_right.png', cv2.cvtColor(ranking_right, cv2.COLOR_RGB2BGR))
print('已保存排序区域右侧')

# 分析排序区域的行
gray = cv2.cvtColor(ranking_region, cv2.COLOR_RGB2GRAY)
_, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

horizontal_projection = np.sum(binary, axis=1)

rows = []
start_row = None
for row in range(len(horizontal_projection)):
    if horizontal_projection[row] > 50 and start_row is None:
        start_row = row
    elif horizontal_projection[row] <= 50 and start_row is not None:
        rows.append((start_row, row))
        start_row = None
if start_row is not None:
    rows.append((start_row, len(horizontal_projection)))

print(f'\n检测到 {len(rows)} 行:')
for i, (start, end) in enumerate(rows):
    print(f'  行{i+1}: y={start}-{end}, 高度={end-start}')
    # 保存每行的图像
    row_img = ranking_region[start:end, :]
    cv2.imwrite(f'_ranking_row_{i+1}.png', cv2.cvtColor(row_img, cv2.COLOR_RGB2BGR))

doc.close()