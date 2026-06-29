"""显示 B6 PDF 第 14 页 y=420..680 的垂直像素分布。

关键：检测"是否存在 15 根水平柱"。
如果存在 15 根水平柱，则每根柱之间有空白间隔。
"""
import json
from pathlib import Path
import fitz
import numpy as np

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))
page = doc[13]
zoom = 3.0
mat = fitz.Matrix(zoom, zoom)
pix = page.get_pixmap(matrix=mat, alpha=False)
img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
if img.shape[2] == 4: img = img[:, :, :3]
gray = np.mean(img, axis=2).astype(np.uint8)

threshold = 160
dark_mask = gray < threshold

# 显示 y=420..680 的像素模式（每 10 行一个样本）
# 对每个采样 y，显示该行在 x=100..500 范围内的 0/1 字符
print("=== y=420-680 的暗色像素（每 10 行样本）===")
for y_pdf in range(420, 690, 2):
    y_img = int(y_pdf * zoom)
    if y_img >= gray.shape[0]:
        break
    row = dark_mask[y_img, :]
    # 显示 x=100..500 的像素，每 5 个像素一个字符
    line = []
    for x_pdf in range(100, 500, 2):
        x_img = int(x_pdf * zoom)
        if x_img >= gray.shape[1]:
            break
        if row[x_img]:
            line.append('#')
        else:
            line.append('.')
    print(f"  y={y_pdf}: {''.join(line)}")

# 更精细：看每一行的暗色像素列数
print("\n=== 每行暗色像素统计（y=420-680, 每 5 行一个样本）===")
for y_pdf in range(420, 690, 5):
    y_img = int(y_pdf * zoom)
    if y_img >= gray.shape[0]: break
    row = dark_mask[y_img, :]
    # 找该行最长的连续暗色段
    longest = 0
    cur = 0
    x_start = 0
    best_s, best_e = 0, 0
    for x in range(row.shape[0]):
        if row[x]:
            cur += 1
            if cur == 1:
                x_start = x
            if cur > longest:
                longest = cur
                best_s = x_start
                best_e = x
        else:
            cur = 0
    print(f"  y_pdf={y_pdf}: total_dark_pixels={row.sum():5d}, longest_segment={longest:4d}({best_s/zoom:.0f}~{best_e/zoom:.0f})")

doc.close()
