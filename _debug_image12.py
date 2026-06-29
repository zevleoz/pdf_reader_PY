"""查看每 15 段的详细统计，找到第 13 段(安全稳定)缺失的原因。"""
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
if img.shape[2] == 4:
    img = img[:, :, :3]
gray = np.mean(img, axis=2).astype(np.uint8)
threshold = 150
dark_mask = gray < threshold

# 看文本层中已知的 2 个锚点标签
# 生活方式：文本在 PDF y=220 附近
# 美的追求：文本在 PDF y=220 附近
# 但这只是文本层的标签（在图表上方）
# 实际柱形条在 y=420-680 区域

# 先把 y=420-680 分成 15 段看每段的暗色像素
y_min, y_max = 420, 680
n_seg = 15
seg_h = (y_max - y_min) / n_seg
x_start_pdf, x_end_pdf = 160, 450

val_labels_order = ['创造发明', '独立自主', '美的追求', '智力激发', '利他助人',
                     '成就感', '管理权力', '工作环境', '同事关系', '上司关系',
                     '多样变化', '经济报酬', '安全稳定', '声望地位', '生活方式']

print(f"=== 每段详细的暗色像素统计 (y_range, x_range, length, dark_pixels) ===")
for i in range(n_seg):
    ys_pdf = y_min + i * seg_h
    ye_pdf = y_min + (i + 1) * seg_h
    yc_pdf = (ys_pdf + ye_pdf) / 2
    ys_img = int(ys_pdf * zoom)
    ye_img = int(ye_pdf * zoom)
    xs_img = int(x_start_pdf * zoom)
    xe_img = int(x_end_pdf * zoom)
    if ys_img >= gray.shape[0] or xs_img >= gray.shape[1]:
        print(f"  段{i+1} ({val_labels_order[i]}): OUT OF BOUNDS")
        continue
    sub = dark_mask[ys_img:ye_img, xs_img:xe_img]
    total_dark = sub.sum()
    col_counts = sub.sum(axis=0)
    if len(col_counts) == 0:
        print(f"  段{i+1} ({val_labels_order[i]}): empty column")
        continue
    max_c = col_counts.max()
    print(f"  段{i+1} ({val_labels_order[i]}): y=[{ys_pdf:.0f}-{ye_pdf:.0f}] yc={yc_pdf:.0f} total_dark={total_dark} max_col={max_c}")
    # 找 "右端 x"
    thr = max_c * 0.15
    right_end_img = -1
    for j in range(len(col_counts) - 1, -1, -1):
        if col_counts[j] >= thr:
            right_end_img = j
            break
    if right_end_img > 0:
        right_end_pdf = x_start_pdf + right_end_img / zoom
        length_pdf = right_end_pdf - x_start_pdf
        print(f"    -> right_end_pdf={right_end_pdf:.0f} length={length_pdf:.0f}")
    else:
        print(f"    -> 未找到柱形条 (right_end_img={right_end_img})")

doc.close()
