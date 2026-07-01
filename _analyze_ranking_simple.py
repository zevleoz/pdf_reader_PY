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

gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
_, binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)

horizontal_proj = np.sum(binary, axis=1)
vertical_proj = np.sum(binary, axis=0)

print(f'\n水平投影（前20行）:')
for i in range(min(20, h)):
    if horizontal_proj[i] > 0:
        print(f'  行{i}: {horizontal_proj[i]}')

print(f'\n水平投影（后30行）:')
for i in range(max(0, h-30), h):
    if horizontal_proj[i] > 0:
        print(f'  行{i}: {horizontal_proj[i]}')

print(f'\n垂直投影（非零区域）:')
non_zero_cols = np.where(vertical_proj > 0)[0]
if len(non_zero_cols) > 0:
    print(f'  非零列范围: {non_zero_cols[0]} - {non_zero_cols[-1]}')

chart_bottom_y = 600

ranking_region = img[chart_bottom_y:h-200, :]
cv2.imwrite('_ranking_simple.png', cv2.cvtColor(ranking_region, cv2.COLOR_RGB2BGR))
print(f'\n排序区域: {ranking_region.shape}')

rank_gray = cv2.cvtColor(ranking_region, cv2.COLOR_RGB2GRAY)
_, rank_binary = cv2.threshold(rank_gray, 180, 255, cv2.THRESH_BINARY_INV)

rank_h, rank_w = ranking_region.shape[:2]
horizontal_lines = []
for y in range(rank_h):
    if np.sum(rank_binary[y, :]) > 100:
        horizontal_lines.append(y)

print(f'\n水平线条位置: {horizontal_lines[:20]}')

vertical_lines = []
for x in range(rank_w):
    if np.sum(rank_binary[:, x]) > 50:
        vertical_lines.append(x)

print(f'\n垂直线条位置: {vertical_lines[:20]}')

cells = []
row_starts = horizontal_lines[::2] if len(horizontal_lines) > 0 else []
col_starts = vertical_lines[::2] if len(vertical_lines) > 0 else []

print(f'\n可能的行起始: {row_starts[:10]}')
print(f'可能的列起始: {col_starts[:10]}')

for i, row_start in enumerate(row_starts[:5]):
    row_end = row_starts[i+1] if i+1 < len(row_starts) else rank_h
    for j, col_start in enumerate(col_starts[:3]):
        col_end = col_starts[j+1] if j+1 < len(col_starts) else rank_w
        cell_h = row_end - row_start
        cell_w = col_end - col_start
        if cell_h > 20 and cell_w > 50:
            cells.append({'row': i+1, 'col': j+1, 'y': row_start, 'x': col_start, 'h': cell_h, 'w': cell_w})

print(f'\n检测到的单元格:')
for cell in cells:
    print(f'  行{cell["row"]}列{cell["col"]}: y={cell["y"]}, x={cell["x"]}, h={cell["h"]}, w={cell["w"]}')
