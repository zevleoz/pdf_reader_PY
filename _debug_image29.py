"""基于 right_end 平台分析 y=420-680 区域，找真正的 15 个柱形条。"""
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

# 计算 y=420-680 范围内每行的 right_end
print("=== y=420-680 每行 right_end 值 ===")
right_ends = []
for y_pdf in range(420, 680):
    ys_img = int(y_pdf * zoom)
    ye_img = int((y_pdf + 1) * zoom)
    xs_img = int(150 * zoom)
    xe_img = int(460 * zoom)
    sub = dark_mask[ys_img:ye_img, xs_img:xe_img]
    total = sub.sum()
    col_counts = sub.sum(axis=0)
    if col_counts.max() > 2:  # 有明显暗色像素
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

# 找"相似 right_end"的连续行（同一柱形条）
print(f"\n=== 聚类分析：相似 right_end 连续行 = 一个柱形条 ===")
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
    # 判断是否属于当前段（right_end 差不超过 30 PDF 单位）
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

# 打印每个柱形条段
for i, seg in enumerate(bar_segments):
    y_start = seg[0][0]
    y_end = seg[-1][0]
    avg_re = sum(r for _, _, r in seg) / len(seg)
    max_total = max(t for _, t, _ in seg)
    length = avg_re - 150
    print(f"  Bar {i+1}: y=[{y_start}-{y_end}] PDF, height={y_end-y_start+1}, "
          f"avg_right_end={avg_re:.0f}, length={length:.0f}, max_dark={max_total}")

doc.close()
