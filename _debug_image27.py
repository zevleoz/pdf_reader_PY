"""更细致地分析 y=620-655 PDF 区域（安全稳定所在段）的暗色像素分布。"""
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

# 用更严格的阈值：只检测真正的暗色像素（图表的柱形条/线条）
dark_mask = gray < 150

print("=== y=620-655 PDF 区域，每 2 行的暗色像素分布 ===")
for y_pdf in range(620, 655, 2):
    ys_img = int(y_pdf * zoom)
    ye_img = int((y_pdf + 1) * zoom)
    xs_img = int(150 * zoom)
    xe_img = int(460 * zoom)
    sub = dark_mask[ys_img:ye_img, xs_img:xe_img]
    total = sub.sum()
    if total > 0:
        col_counts = sub.sum(axis=0)
        # 找列方向的暗色像素分布（更细粒度）
        print(f"  y={y_pdf} PDF: total={total}, nonzero_cols={(col_counts > 0).sum()}, max={col_counts.max()}")
        # 打印具体哪些列有暗色像素
        nonzero_positions = [150 + i/zoom for i, c in enumerate(col_counts) if c > 0]
        if len(nonzero_positions) < 20:
            print(f"    暗色像素列位置 (PDF x): {[f'{p:.0f}' for p in nonzero_positions]}")
        else:
            print(f"    共 {len(nonzero_positions)} 个暗色列，范围 [{min(nonzero_positions):.0f}, {max(nonzero_positions):.0f}]")

# 现在，让我看看 y=625-645 区域的"暗色像素块"是否可能在 x 方向上有明显的柱形条
# 分析 x=150-460, y=625-645 的整体暗色像素密度
print(f"\n=== y=625-645 区域的整体暗色像素密度 ===")
ys_img = int(625 * zoom)
ye_img = int(645 * zoom)
xs_img = int(150 * zoom)
xe_img = int(460 * zoom)
sub = dark_mask[ys_img:ye_img, xs_img:xe_img]
col_counts = sub.sum(axis=0)
# 分块看：每 50 个图像列（约 17 PDF 单位）的暗色像素总数
block_size = 50
for i in range(0, len(col_counts), block_size):
    block_sum = col_counts[i:i+block_size].sum()
    if block_sum > 0:
        x_start_pdf = 150 + i / zoom
        x_end_pdf = 150 + (i + block_size) / zoom
        print(f"  x=[{x_start_pdf:.0f}-{x_end_pdf:.0f}] PDF: dark_pixels={block_sum}")

# 降低阈值：检测更弱的暗色信号（gray < 200）
dark_mask_loose = gray < 200
print(f"\n=== 降低阈值后 (gray < 200) y=625-645 区域 ===")
sub_loose = dark_mask_loose[ys_img:ye_img, xs_img:xe_img]
col_counts_loose = sub_loose.sum(axis=0)
print(f"  total_dark (loose)={sub_loose.sum()}")
for i in range(0, len(col_counts_loose), block_size):
    block_sum = col_counts_loose[i:i+block_size].sum()
    if block_sum > 0:
        x_start_pdf = 150 + i / zoom
        x_end_pdf = 150 + (i + block_size) / zoom
        print(f"  x=[{x_start_pdf:.0f}-{x_end_pdf:.0f}] PDF: dark_pixels={block_sum}")

# 找最右端的暗色像素列（loose threshold）
if col_counts_loose.max() > 0:
    threshold = col_counts_loose.max() * 0.1
    right_end = -1
    for j in range(len(col_counts_loose) - 1, -1, -1):
        if col_counts_loose[j] >= threshold:
            right_end = j
            break
    if right_end > 0:
        right_end_pdf = 150 + right_end / zoom
        print(f"\n  loose threshold: right_end_pdf={right_end_pdf:.0f}, length={right_end_pdf - 150:.0f}")

doc.close()
