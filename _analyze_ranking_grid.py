import fitz
import cv2
import numpy as np

doc = fitz.open('input/report_B6.pdf')
page = doc[14]
mat = fitz.Matrix(3, 3)
pix = page.get_pixmap(matrix=mat, alpha=False)
img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

h, w = img.shape[:2]
print(f'页面尺寸: {w}x{h}')

# 查看排序区域（放大后）
ranking_region = img[500:1000, :600]
cv2.imwrite('_ranking_grid.png', cv2.cvtColor(ranking_region, cv2.COLOR_RGB2BGR))
print('已保存高分辨率排序区域')

# 分割成3列
col_width = ranking_region.shape[1] // 3
for col in range(3):
    col_img = ranking_region[:, col * col_width:(col + 1) * col_width]
    cv2.imwrite(f'_ranking_col_{col + 1}.png', cv2.cvtColor(col_img, cv2.COLOR_RGB2BGR))
    print(f'已保存第{col + 1}列')

# 分割成5行
row_height = ranking_region.shape[0] // 5
for row in range(5):
    row_img = ranking_region[row * row_height:(row + 1) * row_height, :]
    cv2.imwrite(f'_ranking_row_{row + 1}.png', cv2.cvtColor(row_img, cv2.COLOR_RGB2BGR))
    print(f'已保存第{row + 1}行')

# 分割成15个单元格
for col in range(3):
    for row in range(5):
        cell_img = ranking_region[row * row_height:(row + 1) * row_height, col * col_width:(col + 1) * col_width]
        cell_num = col * 5 + row + 1
        cv2.imwrite(f'_ranking_cell_{cell_num}.png', cv2.cvtColor(cell_img, cv2.COLOR_RGB2BGR))
        print(f'已保存单元格{cell_num}')

doc.close()