"""深入分析段 13 (安全稳定) 周围的图像内容，找真正的柱形条位置。"""
import fitz, numpy as np
from pathlib import Path

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))
page = doc[13]

# 渲染整页为高分辨率图像
zoom = 3.0
mat = fitz.Matrix(zoom, zoom)
pix = page.get_pixmap(matrix=mat, alpha=False)
img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
if img.shape[2] == 4:
    img = img[:, :, :3]
gray = np.mean(img, axis=2).astype(np.uint8)
dark_mask = gray < 150

# 详细分析段 11-14 (索引 10-13) 的暗色像素分布
y_min, y_max = 420, 680
n_seg = 15
seg_h = (y_max - y_min) / n_seg
x_start_pdf, x_end_pdf = 160, 450

val_labels_order = ['创造发明', '独立自主', '美的追求', '智力激发', '利他助人',
                     '成就感', '管理权力', '工作环境', '同事关系', '上司关系',
                     '多样变化', '经济报酬', '安全稳定', '声望地位', '生活方式']

print("=== 段 11-14 (经济报酬、安全稳定、声望地位、生活方式) 详细分析 ===")
for i in range(10, 15):
    ys_img = int((y_min + i * seg_h) * zoom)
    ye_img = int((y_min + (i + 1) * seg_h) * zoom)
    xs_img = int(x_start_pdf * zoom)
    xe_img = int(x_end_pdf * zoom)
    sub = dark_mask[ys_img:ye_img, xs_img:xe_img]
    total_dark = sub.sum()
    col_counts = sub.sum(axis=0)
    
    # 列方向暗色像素数分布
    print(f"\n  段{i+1} ({val_labels_order[i]}): y=[{y_min + i*seg_h:.0f}-{y_min + (i+1)*seg_h:.0f}] PDF")
    print(f"    total_dark={total_dark}, shape={sub.shape}")
    if len(col_counts) > 0:
        print(f"    max_col={col_counts.max()} at pos={np.argmax(col_counts)}")
        # 打印列方向暗色像素数的分布（每 20 列打印一次）
        sample_cols = col_counts[::20]
        print(f"    col_counts sample: {sample_cols[:15]}")
        # 找 "暗色像素 > max*0.15" 的最右端位置
        threshold = col_counts.max() * 0.15
        right_end = -1
        for j in range(len(col_counts) - 1, -1, -1):
            if col_counts[j] >= threshold:
                right_end = j
                break
        print(f"    threshold={threshold:.0f}, right_end_img={right_end}")
        if right_end > 0:
            right_end_pdf = x_start_pdf + right_end / zoom
            print(f"    right_end_pdf={right_end_pdf:.0f}, length={right_end_pdf - x_start_pdf:.0f}")

doc.close()
