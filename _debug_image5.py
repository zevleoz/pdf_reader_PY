"""更精细地检测 15 根水平柱：基于垂直间隔的柱形条检测。

方法：
1. 在 y=430..680 区域，检测"垂直方向有留白"的 y 位置——这是柱与柱之间的间隔
2. 每两个相邻间隔之间的暗色区域，就是一根柱
3. 取每根柱的"水平平均右端 x"作为柱长度
4. 用已知 2 个锚点校准为 0..10 的分数
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
dark_mask = gray < threshold  # True 表示是暗色（图表元素）

# 1) 找出"垂直方向"的留白线：row_density 非常低的位置
pdf_y_min = 420
pdf_y_max = 690
img_y_min = int(pdf_y_min * zoom)
img_y_max = int(pdf_y_max * zoom)

row_density = dark_mask[img_y_min:img_y_max, :].mean(axis=1)

# 找"局部极小值"——留白位置
# 先用较大窗口平滑以去除噪声
window = 3
smoothed = []
for i in range(len(row_density)):
    s = max(0, i - window)
    e = min(len(row_density), i + window + 1)
    smoothed.append(np.mean(row_density[s:e]))
smoothed = np.array(smoothed)

# 找局部极小值
local_minima = []
for i in range(3, len(smoothed) - 3):
    if smoothed[i] < 0.05 and smoothed[i] == smoothed[i-3:i+4].min():
        local_minima.append(i)

# 合并相邻的极小值（差距 < 3 行图像）
merged_minima = []
for m in local_minima:
    if merged_minima and m - merged_minima[-1] < 15:
        continue
    merged_minima.append(m)

print(f"找到 {len(merged_minima)} 个留白位置:")
for m in merged_minima:
    print(f"  y_pdf={(img_y_min + m)/zoom:.0f}, density={smoothed[m]:.4f}")

# 2) 现在把"留白之间"的暗色区域视为一根柱
bars = []
for i in range(len(merged_minima) - 1):
    y_start = merged_minima[i]
    y_end = merged_minima[i+1]
    if y_end - y_start < 5:  # 至少 5 行图像
        continue
    # 检查这个区域的中间行是否有足够的暗色像素
    mid = (y_start + y_end) // 2
    center_y_img = img_y_min + mid
    row = dark_mask[center_y_img, :]
    if row.sum() < 50:  # 少于 50 个暗色像素
        continue
    # 找这根柱的"右端 x"
    # 用一个更鲁棒的方法：取柱中心附近若干行的中位数
    ys_range = range(center_y_img - 6, center_y_img + 6)
    right_ends = []
    for y in ys_range:
        if y >= gray.shape[0]: continue
        row = dark_mask[y, :]
        true_idx = np.where(row)[0]
        if len(true_idx) >= 30:
            right_ends.append(true_idx.max())
    if not right_ends:
        continue
    right_end = int(np.median(right_ends))
    y_center_pdf = (img_y_min + y_start + img_y_min + y_end) / (2 * zoom)
    bars.append({
        "y_pdf_center": y_center_pdf,
        "x_end_pdf": right_end / zoom,
        "length_pdf": right_end / zoom - 100,  # 大约左起点 x=100
    })

print(f"\n共 {len(bars)} 根柱:")
for i, b in enumerate(bars):
    print(f"  柱#{i+1}: y_center_pdf={b['y_pdf_center']:.0f}, x_end_pdf={b['x_end_pdf']:.0f}, length={b['length_pdf']:.0f}")

# 3) 找"左边界"：找柱的起点（所有柱的暗色像素最左 x 的最小值）
x_starts = []
for b in bars:
    y_center = int(b['y_pdf_center'] * zoom)
    ys_range = range(y_center - 10, y_center + 10)
    for y in ys_range:
        if y >= gray.shape[0]: continue
        row = dark_mask[y, :]
        true_idx = np.where(row)[0]
        if len(true_idx) >= 30:
            x_starts.append(true_idx.min())
x_start = int(np.median(x_starts))
print(f"\n柱的左边界 x={x_start/zoom:.0f} (pdf坐标)")

# 4) 用左边界重新计算每根柱的长度（更准确）
for b in bars:
    b['x_start_pdf'] = x_start / zoom
    b['bar_length_pdf'] = b['x_end_pdf'] - b['x_start_pdf']

# 5) 现在用锚点校准：
#    生活方式 = 9.39 应该对应最长的一根柱（假设）
#    美的追求 = 3.29 应该对应较短的一根柱
#    我们需要找到哪根柱对应哪个标签

# 方法：通过 y 坐标找标签（文本层有两个标签：生活方式 x=420 y=220, 美的追求 x=499 y=220）
# 但 15 个项目的文本标签不在 PDF 文本层，是画在图片里的

# 先输出每根柱的位置
print("\n=== 15 根柱的检测结果（按 y 排序） ===")
bars_sorted = sorted(bars, key=lambda b: b['y_pdf_center'])
for i, b in enumerate(bars_sorted):
    print(f"  柱#{i+1}: y_center={b['y_pdf_center']:.0f}, bar_length={b['bar_length_pdf']:.0f}")

doc.close()
