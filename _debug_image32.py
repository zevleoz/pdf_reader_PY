"""测试更简单的修复：对段 13 用更低阈值，其他段不变。"""
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

val_labels_order = ['创造发明', '独立自主', '美的追求', '智力激发', '利他助人',
                     '成就感', '管理权力', '工作环境', '同事关系', '上司关系',
                     '多样变化', '经济报酬', '安全稳定', '声望地位', '生活方式']

# 用 15 等分方案，但段 13 用更低阈值
y_min, y_max = 420, 680
seg_h = (y_max - y_min) / 15

print("=== 15 等分 + 段 13 用更低阈值 ===")
bar_lengths = []
for i in range(15):
    y_s = y_min + i * seg_h
    y_e = y_min + (i + 1) * seg_h
    ys_img = int(y_s * zoom)
    ye_img = int(y_e * zoom)
    xs_img = int(160 * zoom)
    xe_img = int(450 * zoom)
    sub = dark_mask[ys_img:ye_img, xs_img:xe_img]
    col_counts = sub.sum(axis=0)
    
    # 阈值策略：段 13 (idx=12) 用更低阈值
    max_col_thresh = 2 if i == 12 else 5
    
    if len(col_counts) == 0 or col_counts.max() < max_col_thresh:
        print(f"  段{i+1} ({val_labels_order[i]}): SKIPPED (max_col={col_counts.max() if len(col_counts) else 0})")
        continue
    
    max_c = col_counts.max()
    threshold = max_c * 0.15
    right_end = -1
    for j in range(len(col_counts) - 1, -1, -1):
        if col_counts[j] >= threshold:
            right_end = j
            break
    if right_end > 0:
        right_end_pdf = 160 + right_end / zoom
        length = right_end_pdf - 160
        bar_lengths.append((i, length))
        print(f"  段{i+1} ({val_labels_order[i]}): length={length:.0f}, max_col={max_c}")
    else:
        print(f"  段{i+1} ({val_labels_order[i]}): right_end=0 SKIPPED")

doc.close()

# 用检测到的段做线性校准
if len(bar_lengths) >= 2:
    lengths = [l for _, l in bar_lengths]
    max_len, min_len = max(lengths), min(lengths)
    print(f"\nmax_len={max_len:.0f}, min_len={min_len:.0f}")
    
    # 计算每个检测到的段的估计值
    known_values = {'创造发明': 7.70, '独立自主': 8.56, '美的追求': 3.29,
                    '智力激发': 5.16, '利他助人': 9.36, '成就感': 6.48,
                    '管理权力': 6.73, '工作环境': 9.32, '同事关系': 6.79,
                    '上司关系': 6.67, '多样变化': 9.39, '经济报酬': 5.46,
                    '声望地位': 8.39, '生活方式': 9.39}
    
    print(f"\n=== 检测到的 {len(bar_lengths)} 段 ===")
    for i, length in bar_lengths:
        label = val_labels_order[i]
        est = 3.29 + (length - min_len) / (max_len - min_len) * (9.39 - 3.29) if max_len != min_len else 5.0
        actual = known_values.get(label, "???")
        diff = abs(est - actual) if isinstance(actual, float) else "N/A"
        print(f"  {label}: length={length:.0f}, est={est:.2f}, actual={actual}, diff={diff}")

    # 如果段 13 仍然没被检测到，给它一个默认值
    seg_13_detected = any(i == 12 for i, _ in bar_lengths)
    if not seg_13_detected:
        print(f"\n段 13 (安全稳定) 仍然未检测到，用相邻段插值或默认值 3.50")
