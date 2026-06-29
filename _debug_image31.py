"""测试不同的 x 范围和段边界，找安全稳定的柱形条。"""
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

# 测试：用更宽松的暗色检测（gray < 180）
dark_mask = gray < 180

# 关键修改：重新调整 15 段的 y 边界
# 基于聚类分析的结果，真实的柱形条分布是不均匀的
# 让我用 "有暗色像素的 y 范围" 来自动确定 15 段的边界

# Step 1: 找 y=420-680 中每行的暗色像素数
print("=== y=420-680 每行暗色像素 (x=100-500) ===")
dark_lines = []
for y_pdf in range(420, 680):
    ys_img = int(y_pdf * zoom)
    ye_img = int((y_pdf + 1) * zoom)
    xs_img = int(100 * zoom)
    xe_img = int(500 * zoom)
    sub = dark_mask[ys_img:ye_img, xs_img:xe_img]
    total = sub.sum()
    dark_lines.append((y_pdf, total))

# Step 2: 找"暗色像素明显多于背景"的行
# 先找平均背景水平
bg_dark = [t for _, t in dark_lines if t < 20]
bg_avg = sum(bg_dark) / len(bg_dark) if bg_dark else 5
print(f"平均背景暗色像素: {bg_avg:.0f}")

# Step 3: 滑动窗口找高密度区域
print(f"\n=== 高密度暗色像素区间（可能对应一个柱形条）===")
bar_regions = []
current_start = None
for y_pdf, total in dark_lines:
    if total > 20:  # 阈值：明显高于背景
        if current_start is None:
            current_start = y_pdf
    else:
        if current_start is not None:
            bar_regions.append((current_start, y_pdf - 1))
            current_start = None
if current_start is not None:
    bar_regions.append((current_start, dark_lines[-1][0]))

for i, (y_s, y_e) in enumerate(bar_regions):
    height = y_e - y_s + 1
    # 在这个区间内找 right_end
    ys_img = int(y_s * zoom)
    ye_img = int((y_e + 1) * zoom)
    xs_img = int(150 * zoom)
    xe_img = int(460 * zoom)
    sub = dark_mask[ys_img:ye_img, xs_img:xe_img]
    col_counts = sub.sum(axis=0)
    if col_counts.max() > 0:
        max_c = col_counts.max()
        threshold = max_c * 0.15
        right_end = -1
        for j in range(len(col_counts) - 1, -1, -1):
            if col_counts[j] >= threshold:
                right_end = j
                break
        right_end_pdf = 150 + right_end / zoom if right_end > 0 else 150
        length = right_end_pdf - 150
        print(f"  Bar {i+1}: y=[{y_s}-{y_e}] h={height}, "
              f"right_end={right_end_pdf:.0f}, length={length:.0f}, max_col={max_c}")

doc.close()
