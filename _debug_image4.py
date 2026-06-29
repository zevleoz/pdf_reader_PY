"""更精确地检测水平柱形条。核心想法：
1. 在 B6 第 14 页 y=400..780 范围内，找垂直方向的暗色像素密度局部极大值
2. 每个局部极大值就是一根水平柱的中心
3. 对每根柱，测量其右侧边界 x（柱的长度）
4. 用已知 2 个锚点校准得到分数
"""
import json
from pathlib import Path
import fitz
from PIL import Image
import numpy as np

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))
page = doc[13]

# 渲染为 3x 分辨率
zoom = 3.0
mat = fitz.Matrix(zoom, zoom)
pix = page.get_pixmap(matrix=mat, alpha=False)
img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
if img.shape[2] == 4:
    img = img[:, :, :3]
gray = np.mean(img, axis=2).astype(np.uint8)

# 阈值化
threshold = 180
dark_mask = gray < threshold

# 1) 在 y=400..780 (pdf) 范围内，计算每行暗色像素密度
pdf_y_min = 400
pdf_y_max = 780
img_y_min = int(pdf_y_min * zoom)
img_y_max = int(pdf_y_max * zoom)
H_sub = img_y_max - img_y_min
W_sub = gray.shape[1]

# 计算每行的"平均暗色像素位置 x"
row_density = dark_mask[img_y_min:img_y_max, :].mean(axis=1)
row_num_pixels = dark_mask[img_y_min:img_y_max, :].sum(axis=1)

# 找到每行暗色像素的"右端 x"
def right_end_x(row):
    indices = np.where(row)[0]
    if len(indices) < 50:
        return -1
    return indices.max()

right_ends = []
for r in range(img_y_min, img_y_max):
    row = dark_mask[r, :]
    re = right_end_x(row)
    right_ends.append(re)

print("=== 每行的暗色像素密度和右端 x（采样） ===")
for i in range(0, H_sub, 30):
    print(f"  pdf_y={img_y_min/zoom + i/zoom:.0f}: density={row_density[i]:.3f}, num_pixels={row_num_pixels[i]}, right_end_x={right_ends[i]}")

# 2) 找垂直方向的"带"：用滑动窗口
# 窗口大小：20 行 PDF ≈ 60 行图像
# 方法：先做行密度的平滑，然后找局部极大值（15 个最显著的峰）
window = int(6 * zoom)  # 6 PDF rows ≈ 18 img rows
smoothed = []
for i in range(H_sub):
    start = max(0, i - window)
    end = min(H_sub, i + window)
    smoothed.append(row_num_pixels[start:end].mean())
smoothed = np.array(smoothed)

# 找局部极大值
print("\n=== 平滑后的行像素数（找局部极大值） ===")
# 简化：找区间内的局部极大值点，要求和前后点比是最大的
maxima = []
for i in range(window, H_sub - window):
    if smoothed[i] == smoothed[i-window:i+window].max() and smoothed[i] > 100:
        maxima.append((i, smoothed[i]))

# 合并相邻的极大值（保留最强的）
maxima.sort(key=lambda m: -m[1])
selected = []
for idx, val in maxima:
    too_close = any(abs(s[0] - idx) < 3*zoom for s in selected)
    if not too_close:
        selected.append((idx, val))
selected.sort(key=lambda s: s[0])
print(f"找到 {len(selected)} 个候选峰值:")
for i, (idx, val) in enumerate(selected[:25]):
    y_pdf = (img_y_min + idx) / zoom
    # 对这个 y 位置附近的行，取平均 right_end_x
    ys = range(max(0, idx - window), min(H_sub, idx + window))
    re_vals = [right_ends[j] for j in ys if right_ends[j] > 0]
    right_end = int(np.median(re_vals)) if re_vals else -1
    print(f"  峰#{i+1}: y_pdf={y_pdf:.0f}, avg_pixels={val:.0f}, right_end_x_pdf={right_end/zoom:.0f}")

doc.close()
