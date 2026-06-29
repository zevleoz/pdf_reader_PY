"""降低段检测阈值，测试段 13 是否能提取出合理数值。"""
import json
import fitz
import numpy as np
from pathlib import Path

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))
page = doc[13]
zoom = 3.0
mat = fitz.Matrix(zoom, zoom)
pix = page.get_pixmap(matrix=mat, alpha=False)
img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
if img.shape[2] == 4:
    img = img[:, :, :3]
gray = np.mean(img, axis=2).astype(np.uint8)
dark_mask = gray < 150

# 分段
y_min, y_max = 420, 680
n_seg = 15
seg_h = (y_max - y_min) / n_seg
x_start_pdf, x_end_pdf = 160, 450

# 降低检测阈值测试
bar_lengths = []
for i in range(n_seg):
    ys_img = int((y_min + i * seg_h) * zoom)
    ye_img = int((y_min + (i + 1) * seg_h) * zoom)
    xs_img = int(x_start_pdf * zoom)
    xe_img = int(x_end_pdf * zoom)
    sub = dark_mask[ys_img:ye_img, xs_img:xe_img]
    total_dark = sub.sum()
    col_counts = sub.sum(axis=0)
    if len(col_counts) == 0:
        continue
    max_c = col_counts.max()
    # 找右端
    right_end_img = -1
    for j in range(len(col_counts) - 1, -1, -1):
        if col_counts[j] >= max_c * 0.15:  # 用相对阈值而不是绝对阈值
            right_end_img = j
            break
    if right_end_img > 0:
        right_end_pdf = x_start_pdf + right_end_img / zoom
        length = right_end_pdf - x_start_pdf
        bar_lengths.append((i, length))
        print(f"  段{i+1}: length={length:.0f}, total_dark={total_dark}, max_col={max_c}")
    else:
        print(f"  段{i+1}: NOT DETECTED, total_dark={total_dark}, max_col={max_c}")

doc.close()

# 现在用 14 个已知数值做线性校准
known_values = {
    0: ('创造发明', 7.70),
    1: ('独立自主', 8.56),
    2: ('美的追求', 3.29),
    3: ('智力激发', 5.16),
    4: ('利他助人', 9.36),
    5: ('成就感', 6.48),
    6: ('管理权力', 6.73),
    7: ('工作环境', 9.32),
    8: ('同事关系', 6.79),
    9: ('上司关系', 6.67),
    10: ('多样变化', 9.39),
    11: ('经济报酬', 5.46),
    13: ('声望地位', 8.39),
    14: ('生活方式', 9.39),
}

print("\n=== 线性校准（用 14 个已知点） ===")
# 收集已检测段的长度
length_by_idx = {idx: length for idx, length in bar_lengths}

# 用 2 个锚点（最大/最小值）做线性映射
# 最大：生活方式 (idx=14) 9.39，最小：美的追求 (idx=2) 3.29
# 但如果标签映射不对，这就错了。让我们用检测到的长度 vs 已知数值看相关性。
print("已知数值 vs 检测到的长度：")
calibration_points = []
for idx, (label, val) in known_values.items():
    if idx in length_by_idx:
        calibration_points.append((val, length_by_idx[idx], label))
        print(f"  {label}: value={val:.2f}, length={length_by_idx[idx]:.0f}")

# 简单线性：v = a * length + b
# 用已知最小值和最大值计算
if calibration_points:
    vals_sorted = sorted(calibration_points)
    min_val, min_len, min_lbl = vals_sorted[0]
    max_val, max_len, max_lbl = vals_sorted[-1]
    print(f"\nmin = {min_lbl}: value={min_val:.2f}, length={min_len:.0f}")
    print(f"max = {max_lbl}: value={max_val:.2f}, length={max_len:.0f}")

    # 线性映射
    if max_len != min_len:
        for idx in range(15):
            if idx in length_by_idx:
                length = length_by_idx[idx]
                est = min_val + (length - min_len) / (max_len - min_len) * (max_val - min_val)
                label = known_values.get(idx, (f"idx{idx}", 0))[0]
                known_val = known_values.get(idx, (None, None))[1]
                diff = abs(known_val - est) if known_val is not None else "N/A"
                print(f"  {label} (idx={idx}): est={est:.2f}, known={known_val}, diff={diff}")
