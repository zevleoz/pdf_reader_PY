"""对每段，用"列方向暗色像素数"来检测柱条的右端位置。

方法：
1. 把 y=420-680 分成 15 段
2. 对每段，统计 x=160..450 每列的暗色像素数
3. 找到"列数明显下降"的位置——这就是柱条的右端
4. 用最大柱条长度作为 10 分的校准
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

# 1) 把 y=420-680 分成 15 段
y_min = 420
y_max = 680
n_segments = 15
segment_height = (y_max - y_min) / n_segments

# 2) 对每段，统计 x=160-450 每列的暗色像素数
x_start_pdf = 160
x_end_pdf = 450
x_start_img = int(x_start_pdf * zoom)
x_end_img = int(x_end_pdf * zoom)

print(f"=== 15 段的列方向暗色像素分布 ===")
bar_lengths = []
for i in range(n_segments):
    y_s_pdf = y_min + i * segment_height
    y_e_pdf = y_min + (i+1) * segment_height
    y_s_img = int(y_s_pdf * zoom)
    y_e_img = int(y_e_pdf * zoom)

    # 取这个 y 范围内的子区域
    sub = dark_mask[y_s_img:y_e_img, x_start_img:x_end_img]
    # 统计每列的暗色像素数
    col_counts = sub.sum(axis=0)

    # 找"列数突然下降"的位置（柱状图的右端）
    # 方法：从左向右扫描，找第一个"列数 < 最大列数的 10%"的位置
    if len(col_counts) == 0:
        print(f"  段#{i+1}: y=[{y_s_pdf:.0f}-{y_e_pdf:.0f}], — 空")
        continue
    max_count = col_counts.max()
    if max_count < 5:
        print(f"  段#{i+1}: y=[{y_s_pdf:.0f}-{y_e_pdf:.0f}], max_count={max_count}")
        continue
    # 找到"第一个列数 < 10% 的位置"
    threshold_count = max_count * 0.15
    # 找到第一个满足条件的列
    right_end_img = -1
    for j in range(len(col_counts)-1, -1, -1):
        if col_counts[j] >= threshold_count:
            right_end_img = j
            break
    # 或者反过来：从左向右，找"最大列数的中心"
    # 找到最大列数对应的 x，然后以这个 x 作为柱条的右端
    if right_end_img >= 0:
        right_end_pdf = x_start_pdf + right_end_img / zoom
        length_pdf = right_end_pdf - x_start_pdf
        bar_lengths.append({
            "segment": i+1,
            "y_center_pdf": (y_s_pdf + y_e_pdf) / 2,
            "length_pdf": length_pdf,
            "right_end_pdf": right_end_pdf,
            "max_count": max_count,
        })
        print(f"  段#{i+1}: y=[{y_s_pdf:.0f}-{y_e_pdf:.0f}], y_center={(y_s_pdf+y_e_pdf)/2:.0f}, "
              f"right_end_pdf={right_end_pdf:.0f}, length={length_pdf:.0f}, max_count={max_count}")
    else:
        print(f"  段#{i+1}: y=[{y_s_pdf:.0f}-{y_e_pdf:.0f}] — 无法确定右端")

# 3) 现在看看得到的柱条长度
print(f"\n=== 柱条长度分析 ===")
bar_lengths.sort(key=lambda b: -b["length_pdf"])
print("按长度从大到小排序：")
for b in bar_lengths:
    print(f"  #{b['segment']}: y_center={b['y_center_pdf']:.0f}, length={b['length_pdf']:.0f}")

# 4) 用最大长度作为 10 分的参考，最小长度作为 0 分的参考
if bar_lengths:
    max_len = max(b["length_pdf"] for b in bar_lengths)
    min_len = min(b["length_pdf"] for b in bar_lengths)
    print(f"\n最大长度: {max_len:.0f} (对应 10 分)")
    print(f"最小长度: {min_len:.0f} (对应 0 分)")

    # 把每段的长度映射为 0-10 的分数
    print(f"\n=== 每段的估计得分 ===")
    for b in bar_lengths:
        score = (b["length_pdf"] - min_len) / (max_len - min_len) * 10
        print(f"  段#{b['segment']} (y={b['y_center_pdf']:.0f}): length={b['length_pdf']:.0f}, score={score:.2f}")

doc.close()
