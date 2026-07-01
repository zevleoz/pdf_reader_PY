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

# 查看条形图下方的标签区域（放大后）
labels_region = img[550:800, :]
cv2.imwrite('_labels_region_highres.png', cv2.cvtColor(labels_region, cv2.COLOR_RGB2BGR))
print('已保存高分辨率标签区域')

# 尝试二值化处理来检测文字
gray = cv2.cvtColor(labels_region, cv2.COLOR_RGB2GRAY)
_, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
cv2.imwrite('_labels_binary.png', binary)
print('已保存二值化标签区域')

# 垂直投影分析
vertical_projection = np.sum(binary, axis=0)

# 找到文字列
text_columns = []
start_col = None
for col in range(len(vertical_projection)):
    if vertical_projection[col] > 100 and start_col is None:
        start_col = col
    elif vertical_projection[col] <= 100 and start_col is not None:
        text_columns.append((start_col, col))
        start_col = None
if start_col is not None:
    text_columns.append((start_col, len(vertical_projection)))

print(f'检测到 {len(text_columns)} 个文字列:')
for i, (start, end) in enumerate(text_columns):
    print(f'  列{i+1}: {start}-{end}')

# 保存每个文字列
for i, (start, end) in enumerate(text_columns):
    col_img = labels_region[:, start:end]
    cv2.imwrite(f'_label_col_{i+1}.png', cv2.cvtColor(col_img, cv2.COLOR_RGB2BGR))

doc.close()