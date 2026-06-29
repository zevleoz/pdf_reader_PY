"""直接在字符模式下看柱条结构，用简单的方法检测 15 个柱条的 y 位置和长度。"""
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

# 先看"每行是否是空白行"——找到柱之间的分隔
# 用更小的阈值来检测"完全空白"的行
row_sums = dark_mask.sum(axis=1)

# y=420-680 (pdf) 是我们关注的区域
y_min = 420
y_max = 680
print(f"=== y={y_min}-{y_max} (pdf) 每行暗色像素数 ===")
for y_pdf in range(y_min, y_max, 1):
    y_img = int(y_pdf * zoom)
    if y_img >= len(row_sums): break
    n = row_sums[y_img]
    marker = "BAR" if n > 50 else ("---" if n < 10 else "...")
    print(f"  y={y_pdf}: {n:5d} dark pixels [{marker}]")

# 检测柱条：用滑动窗口找"柱条区域"的上下边界
# 柱条区域：连续多行的暗色像素数 > 某个阈值
# 间隔：连续多行的暗色像素数 < 某个阈值
print(f"\n=== 检测柱条区域 ===")
y_start_img = int(y_min * zoom)
y_end_img = int(y_max * zoom)

bars = []  # 每个元素 (y_start_img, y_end_img)
in_bar = False
bar_start = -1
for y_img in range(y_start_img, y_end_img):
    n = row_sums[y_img]
    if n > 50 and not in_bar:
        in_bar = True
        bar_start = y_img
    elif n < 10 and in_bar:
        in_bar = False
        bars.append((bar_start, y_img))
if in_bar:
    bars.append((bar_start, y_end_img))

print(f"找到 {len(bars)} 个柱条")
for i, (s, e) in enumerate(bars):
    y_s_pdf = s / zoom
    y_e_pdf = e / zoom
    y_c_pdf = (s + e) / (2 * zoom)
    # 求这根柱条在中心附近若干行的平均右端 x
    center = (s + e) // 2
    right_ends = []
    left_starts = []
    # 在中心 ±10 行的范围内
    for y in range(center - 10, center + 10):
        if y >= gray.shape[0]: continue
        row = dark_mask[y, :]
        if row.sum() < 30: continue
        true_idx = np.where(row)[0]
        if len(true_idx) >= 30:
            left_starts.append(true_idx.min())
            right_ends.append(true_idx.max())
    if not right_ends:
        continue
    left_s = np.median(left_starts) / zoom
    right_e = np.median(right_ends) / zoom
    length = right_e - left_s
    print(f"  柱#{i+1}: y=[{y_s_pdf:.0f}-{y_e_pdf:.0f}], y_center={y_c_pdf:.0f}, x=[{left_s:.0f}-{right_e:.0f}], length={length:.0f}")
doc.close()
