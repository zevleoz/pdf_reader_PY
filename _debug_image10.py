"""更聪明的柱条检测：在 y=420..680 的区域，对每根柱条的 y 附近，
计算该行从某一固定 x_left 开始的"暗色像素最右位置"作为长度。

改进点：
1. 先确定"整体的柱条左边界"
2. 对每段中心 y，找该行从 x_left 开始的"最右暗色像素位置"
3. 长度 = right_end - left_start
4. 用所有柱条的最大长度作为 10 分锚点校准
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
threshold = 150
dark_mask = gray < threshold

# 1) 先看整个 y=420-680, x=100-500 的暗色像素"列分布"
#    列中暗色像素总数 = 该列有多少行是暗色的
col_counts = dark_mask[int(420*zoom):int(680*zoom), int(100*zoom):int(500*zoom)].sum(axis=0)

print("=== 列方向暗色像素数（x=100-500, pdf 坐标）===")
# 每 10 个 x 采样一次
for i in range(0, len(col_counts), 10*int(zoom)):
    x_pdf = 100 + i / zoom
    print(f"  x={x_pdf:.0f}: {col_counts[i]:5d}")

# 2) 找到"左边界"：从左向右扫描，找第一个"暗色像素数 > 100"的列
left_bound = -1
for i in range(0, len(col_counts)):
    if col_counts[i] > 100:
        left_bound = 100 + i / zoom
        break
print(f"\n左边界: x={left_bound:.0f} (pdf 坐标)")

# 3) 找到"右边界"：从右向左扫描，找最后一个"暗色像素数 > 100"的列
right_bound = -1
for i in range(len(col_counts)-1, -1, -1):
    if col_counts[i] > 100:
        right_bound = 100 + i / zoom
        break
print(f"右边界: x={right_bound:.0f} (pdf 坐标)")
print(f"最大可能长度: {right_bound - left_bound:.0f} (pdf 坐标)")

# 4) 现在检测 15 根柱条的 y 中心位置
#    方法：从 y=420-680 找 15 个"暗色像素局部极大值"的 y 位置
row_counts = dark_mask[int(420*zoom):int(680*zoom), int(100*zoom):int(500*zoom)].sum(axis=1)

# 平滑处理（窗口大小 5）
window = 5
smoothed = np.convolve(row_counts, np.ones(window)/window, mode='same')

# 找"局部极大值"——在一个小窗口内是最大的
local_maxima = []
window_max = 10
for i in range(window_max, len(smoothed) - window_max):
    if smoothed[i] == smoothed[i-window_max:i+window_max].max() and smoothed[i] > 300:
        local_maxima.append(i)

# 合并相邻的局部极大值（差距 < 10 像素图像）
merged_maxima = []
for m in local_maxima:
    if merged_maxima and m - merged_maxima[-1] < 10:
        continue
    merged_maxima.append(m)

print(f"\n=== 找到 {len(merged_maxima)} 个 y 方向局部极大值 ===")
for i, m in enumerate(merged_maxima):
    y_pdf = 420 + m / zoom
    # 在这个 y 附近找这一行的"暗色像素最右位置"
    y_center_img = int(420 * zoom + m)
    # 在 y 中心附近 ±5 行找"每行的暗色像素最右位置"
    right_ends = []
    for y in range(y_center_img - 5, y_center_img + 6):
        if y >= gray.shape[0]: continue
        row = dark_mask[y, :]
        # 找"从左到右扫描中，最后一个暗色像素"的位置
        true_idx = np.where(row)[0]
        if len(true_idx) >= 30:
            right_ends.append(true_idx.max())
    if not right_ends:
        continue
    right_end_img = np.median(right_ends)
    right_end_pdf = right_end_img / zoom

    # 计算柱条长度（相对于左边界）
    length_pdf = right_end_pdf - left_bound
    print(f"  峰#{i+1}: y_pdf={y_pdf:.0f}, right_end_pdf={right_end_pdf:.0f}, length={length_pdf:.0f}")

# 5) 现在我来做更重要的分析：
#    把 y=420-680 分成 15 段，每段找到"这一段所有行的平均暗色像素最右位置"
print(f"\n=== 15 段的平均暗色像素最右位置 ===")
y_min = 420
y_max = 680
n_segments = 15
segment_height = (y_max - y_min) / n_segments

for i in range(n_segments):
    y_start_img = int((y_min + i * segment_height) * zoom)
    y_end_img = int((y_min + (i+1) * segment_height) * zoom)
    # 在 y_start_img to y_end_img 之间，找每行的暗色像素最右位置
    right_ends = []
    left_starts_list = []
    for y in range(y_start_img, y_end_img):
        if y >= gray.shape[0]: continue
        row = dark_mask[y, :]
        true_idx = np.where(row)[0]
        if len(true_idx) >= 30:
            right_ends.append(true_idx.max())
            left_starts_list.append(true_idx.min())
    if not right_ends:
        print(f"  段#{i+1}: 无数据")
        continue
    # 用中位数更稳
    right_end_img = np.median(right_ends)
    left_start_img = np.median(left_starts_list)
    right_end_pdf = right_end_img / zoom
    left_start_pdf = left_start_img / zoom
    length_pdf = right_end_pdf - left_start_pdf
    print(f"  段#{i+1}: y_center={y_min + (i+0.5)*segment_height:.0f}, "
          f"x_start={left_start_pdf:.0f}, x_end={right_end_pdf:.0f}, length={length_pdf:.0f}")

doc.close()
