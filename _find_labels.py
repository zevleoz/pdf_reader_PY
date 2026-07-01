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

# 查看条形图区域下方的区域
labels_region = img[600:750, :]
cv2.imwrite('_labels_below_chart.png', cv2.cvtColor(labels_region, cv2.COLOR_RGB2BGR))
print('已保存条形图下方区域')

# 查看条形图区域右侧
right_region = img[200:600, 1000:]
cv2.imwrite('_right_region.png', cv2.cvtColor(right_region, cv2.COLOR_RGB2BGR))
print('已保存条形图右侧区域')

# 查看条形图区域左侧
left_region = img[200:600, :100]
cv2.imwrite('_left_region.png', cv2.cvtColor(left_region, cv2.COLOR_RGB2BGR))
print('已保存条形图左侧区域')

# 查看整个页面的文本层
text = page.get_text()
print('\n页面文本:')
print(text[:2000])

doc.close()