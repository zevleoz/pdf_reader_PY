"""重新分析整个图表区域：15 个柱形条的实际 y 位置可能不在 420-680。"""
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

# 分析 y=200-700 PDF 区域的每行暗色像素数
print("=== y=200-700 区域每行暗色像素数 (x=150-460) ===")
dark_by_row = []
for y_pdf in range(200, 700):
    ys_img = int(y_pdf * zoom)
    ye_img = int((y_pdf + 1) * zoom)
    if ye_img >= dark_mask.shape[0]:
        break
    sub = dark_mask[ys_img:ye_img, int(150*zoom):int(460*zoom)]
    total = sub.sum()
    dark_by_row.append((y_pdf, total))

# 找"高密度暗色像素块"（可能是柱形条行）
# 用滑动窗口：找连续 10-20 行都有大量暗色像素的区域
window_size = 15
print(f"\n=== 连续 {window_size} 行的平均暗色像素 > 100 的区间 ===")
i = 0
while i < len(dark_by_row) - window_size:
    window = dark_by_row[i:i+window_size]
    avg = sum(t for _, t in window) / window_size
    if avg > 100:
        y_start = window[0][0]
        # 扩展窗口直到平均密度下降
        j = i + window_size
        while j < len(dark_by_row):
            new_avg = sum(t for _, t in dark_by_row[i:j+1]) / (j - i + 1)
            if new_avg < 50:
                break
            j += 1
        y_end = dark_by_row[j-1][0]
        max_total = max(t for _, t in dark_by_row[i:j])
        print(f"  y=[{y_start}-{y_end}] PDF: rows={y_end-y_start+1}, avg_dark={avg:.0f}, max={max_total}")
        i = j + 5  # 跳过已检测的块
    else:
        i += 1

# 另一种方法：找每个行的 right_end（最右端的暗色像素位置）
print(f"\n=== 每行 right_end_pdf (y=420-680) ===")
for y_pdf in range(420, 680, 3):
    ys_img = int(y_pdf * zoom)
    ye_img = int((y_pdf + 2) * zoom)
    xs_img = int(150 * zoom)
    xe_img = int(460 * zoom)
    sub = dark_mask[ys_img:ye_img, xs_img:xe_img]
    total = sub.sum()
    col_counts = sub.sum(axis=0)
    if col_counts.max() > 0:
        max_c = col_counts.max()
        threshold = max_c * 0.15
        right_end = -1
        for j in range(len(col_counts) - 1, -1, -1):
            if col_counts[j] >= threshold:
                right_end = j
                break
        if right_end > 0:
            right_end_pdf = 150 + right_end / zoom
            print(f"  y={y_pdf} PDF: total={total}, max={max_c}, right_end_pdf={right_end_pdf:.0f}")
        else:
            print(f"  y={y_pdf} PDF: total={total}, max={max_c}, NO right_end")
    else:
        print(f"  y={y_pdf} PDF: total={total} (EMPTY)")

doc.close()
