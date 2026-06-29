"""检测 15 根水平柱并按 y 位置排序。

策略：
1. 在 y=420-680 范围内，用"垂直列的留白"检测柱之间的间隔
2. 每根柱取"最常出现的右端 x"作为长度
3. 输出 y 中心位置和长度
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

# 分析 y=420-680 区域：
# 1) 每行的暗色像素数
row_sum = dark_mask[int(420*zoom):int(680*zoom), :].sum(axis=1)

# 2) 找"留白线"：该行暗色像素少于 20
empty_lines = np.where(row_sum < 20)[0] + int(420 * zoom)

# 3) 用留白线把图像分割成区域
# 找连续的 empty line，将它们合并成"空白带"
all_y_img = list(range(int(420 * zoom), int(680 * zoom)))

# 检测柱条：从 y=420 开始，找"第一个暗色区域"，然后"空白"，然后"下一个暗色区域"...
bars = []
in_bar = False
bar_start = -1

for i, y_img in enumerate(range(int(420 * zoom), int(680 * zoom))):
    row = dark_mask[y_img, :]
    n_dark = row.sum()
    if n_dark > 30 and not in_bar:
        in_bar = True
        bar_start = y_img
    elif n_dark < 8 and in_bar:
        in_bar = False
        bar_end = y_img
        if bar_end - bar_start > 5:
            bars.append((bar_start, bar_end))

# 把柱条输出
print(f"找到 {len(bars)} 个柱条:")
bar_data = []
for (s, e) in bars:
    # 取柱条中心附近的行
    center_y = (s + e) // 2
    # 在中心 ±5 行内，找每行最长的连续暗色段
    right_ends = []
    left_starts = []
    lengths = []
    for y in range(center_y - 10, center_y + 10):
        if y >= gray.shape[0]: continue
        row = dark_mask[y, :]
        if row.sum() < 30: continue
        # 找最长连续段
        cur = 0
        best_s, best_e, best_len = 0, 0, 0
        seg_start = -1
        for x in range(row.shape[0]):
            if row[x]:
                cur += 1
                if cur == 1:
                    seg_start = x
                if cur > best_len:
                    best_len = cur
                    best_s = seg_start
                    best_e = x
            else:
                cur = 0
        if best_len >= 30:
            right_ends.append(best_e)
            left_starts.append(best_s)
            lengths.append(best_len)
    if not right_ends:
        continue
    y_center_pdf = (s + e) / (2 * zoom)
    # 用中位数更可靠
    x_start_pdf = np.median(left_starts) / zoom
    x_end_pdf = np.median(right_ends) / zoom
    length_pdf = x_end_pdf - x_start_pdf
    bar_data.append({
        "y_center": y_center_pdf,
        "x_start": x_start_pdf,
        "x_end": x_end_pdf,
        "length": length_pdf,
    })
    print(f"  y_center={y_center_pdf:.0f}, x=[{x_start_pdf:.0f}, {x_end_pdf:.0f}], length={length_pdf:.0f}")

# 现在检测柱的左边界和右边界
# 让我看看柱条的整体分布
if bar_data:
    lefts = [b["x_start"] for b in bar_data]
    rights = [b["x_end"] for b in bar_data]
    print(f"\n左边界 min={min(lefts):.0f}, max={max(lefts):.0f}")
    print(f"右边界 min={min(rights):.0f}, max={max(rights):.0f}")

    # 现在我需要知道：x=180 和 x=420 之间，哪个标签对应哪根柱？
    # 我假设：所有柱的左边界都在同一个 x 位置（固定的起点），
    # 长度变化代表分数变化
    # 这是一个典型的"条形图"：所有条从同一 x 开始，长度不同

    # 找到共同的左边界（中位数）
    common_left = np.median(lefts)
    print(f"共同左边界: {common_left:.0f}")

    # 用"长度"排序，按长度从大到小输出
    bar_data.sort(key=lambda b: -b["length"])
    print(f"\n按长度排序（前 15 个）:")
    for i, b in enumerate(bar_data[:15]):
        print(f"  #{i+1}: y_center={b['y_center']:.0f}, length={b['length']:.0f}")

doc.close()
