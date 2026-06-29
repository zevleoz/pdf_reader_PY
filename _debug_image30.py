"""测试新的 fallback 逻辑：更灵活地检测段 13（安全稳定）。"""
import fitz, numpy as np
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

# 新方案：先找到 y=420-680 中所有"有暗色像素的行"，
# 然后用 right_end 聚类来分组（如同 _debug_image29）
print("=== 新方案：right_end 聚类检测真正的 15 个柱形条 ===")

# Step 1: 计算每行的 right_end
right_ends = []
for y_pdf in range(420, 680):
    ys_img = int(y_pdf * zoom)
    ye_img = int((y_pdf + 1) * zoom)
    xs_img = int(150 * zoom)
    xe_img = int(460 * zoom)
    sub = dark_mask[ys_img:ye_img, xs_img:xe_img]
    total = sub.sum()
    col_counts = sub.sum(axis=0)
    if col_counts.max() > 2:
        max_c = col_counts.max()
        threshold = max_c * 0.15
        right_end = -1
        for j in range(len(col_counts) - 1, -1, -1):
            if col_counts[j] >= threshold:
                right_end = j
                break
        if right_end > 0:
            right_end_pdf = 150 + right_end / zoom
            right_ends.append((y_pdf, total, right_end_pdf))
        else:
            right_ends.append((y_pdf, total, 0))
    else:
        right_ends.append((y_pdf, total, 0))

# Step 2: 相似 right_end 的连续行聚类为一个柱形条
bar_segments = []
current_seg = []
current_re = None
for y, total, re in right_ends:
    if re <= 0:
        if current_seg:
            bar_segments.append(current_seg)
            current_seg = []
            current_re = None
        continue
    if current_re is None:
        current_seg = [(y, total, re)]
        current_re = re
    elif abs(re - current_re) < 30:
        current_seg.append((y, total, re))
        current_re = sum(r for _, _, r in current_seg) / len(current_seg)
    else:
        bar_segments.append(current_seg)
        current_seg = [(y, total, re)]
        current_re = re
if current_seg:
    bar_segments.append(current_seg)

# Step 3: 打印每个 bar 的信息并计算 length
print(f"找到 {len(bar_segments)} 个 bar:\n")
bars_info = []
for i, seg in enumerate(bar_segments):
    y_start = seg[0][0]
    y_end = seg[-1][0]
    avg_re = sum(r for _, _, r in seg) / len(seg)
    max_total = max(t for _, t, _ in seg)
    length = avg_re - 150
    bars_info.append((y_start, y_end, avg_re, length, max_total))
    print(f"  Bar {i+1}: y=[{y_start}-{y_end}] h={y_end-y_start+1}, "
          f"avg_re={avg_re:.0f}, length={length:.0f}, max_dark={max_total}")

# Step 4: 用已知的 14 个值做线性校准
# 假设 bars_info 的顺序就是 val_labels_order 的顺序
# （从 y=420 开始向下扫描）
val_labels_order = ['创造发明', '独立自主', '美的追求', '智力激发', '利他助人',
                     '成就感', '管理权力', '工作环境', '同事关系', '上司关系',
                     '多样变化', '经济报酬', '安全稳定', '声望地位', '生活方式']
known_values = {'创造发明': 7.70, '独立自主': 8.56, '美的追求': 3.29,
                '智力激发': 5.16, '利他助人': 9.36, '成就感': 6.48,
                '管理权力': 6.73, '工作环境': 9.32, '同事关系': 6.79,
                '上司关系': 6.67, '多样变化': 9.39, '经济报酬': 5.46,
                '声望地位': 8.39, '生活方式': 9.39}

# 用 bars_info 的 length 与已知值对比
print(f"\n=== bars_info vs 已知值 ===")
if len(bars_info) >= 15:
    lengths = [info[3] for info in bars_info[:15]]
    max_len, min_len = max(lengths), min(lengths)
    for i in range(15):
        label = val_labels_order[i]
        length = lengths[i]
        est = 3.29 + (length - min_len) / (max_len - min_len) * (9.39 - 3.29) if max_len != min_len else 5.0
        actual = known_values.get(label, "???")
        diff = abs(est - actual) if isinstance(actual, float) else "N/A"
        print(f"  {i+1:2d}. {label}: length={length:.0f}, est={est:.2f}, actual={actual}, diff={diff}")

    # 估计安全稳定
    if len(bars_info) >= 13:
        safe_stable_length = bars_info[12][3]
        safe_stable_est = 3.29 + (safe_stable_length - min_len) / (max_len - min_len) * (9.39 - 3.29)
        print(f"\n  安全稳定: length={safe_stable_length:.0f}, 估计值={safe_stable_est:.2f}")

doc.close()
