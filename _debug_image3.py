"""提取并分析 B6 第 14 页的完整图像。看有没有 15 个柱形条。"""
import json
from pathlib import Path
import fitz
from PIL import Image
import numpy as np

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))

# 渲染 B6 第 14 页为 3x 分辨率
page = doc[13]
mat = fitz.Matrix(3.0, 3.0)
pix = page.get_pixmap(matrix=mat, alpha=False)
# 保存以便检查
out_path = Path(__file__).resolve().parent / "data" / "_tmp_b6_p14.png"
pix.save(str(out_path))
print(f"已保存 {out_path}: {pix.width}x{pix.height}")

# 分析该页中每一行的"暗色像素密度"——找柱形条
img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
gray = np.mean(img, axis=2).astype(np.uint8)
dark_mask = gray < 200

# 按 y 行统计暗色像素列数（每 PDF 坐标约 3 像素）
# 但实际上，让我们输出每个 y 坐标附近的 dark pixel 占比
print("\n=== 每行暗色像素占比（每 10 行采样一次）===")
H, W = gray.shape
for y in range(0, H, 30):
    row = dark_mask[y, :]
    density = row.mean()
    if density > 0.02:
        print(f"  y={y:4d} (pdf y={y/3:.0f}): density={density:.3f}")

# 现在更精细：y = 1200..2400（pdf y=400-800）
print("\n=== y=400-780 (pdf) 区域详细柱形条检测 ===")
def detect_bar_endpoints(gray_img, y_pdf_min, y_pdf_max, zoom, threshold=200):
    H, W = gray_img.shape
    dark_mask = gray_img < threshold
    rows = []
    y_min_img = int(y_pdf_min * zoom)
    y_max_img = int(y_pdf_max * zoom)
    for y_img in range(y_min_img, y_max_img, max(1, int(2 * zoom))):
        if y_img >= H: break
        row = dark_mask[y_img, :]
        true_indices = np.where(row)[0]
        if len(true_indices) < 30:
            continue
        # 找连续段
        segments = []
        cur = -1
        for i, v in enumerate(row):
            if v and cur < 0: cur = i
            elif not v and cur >= 0:
                segments.append((cur, i-1)); cur = -1
        if cur >= 0: segments.append((cur, len(row)-1))
        # 取最长段
        if segments:
            segments.sort(key=lambda s: -(s[1]-s[0]))
            x_s, x_e = segments[0]
            length = x_e - x_s
            if length >= 30:
                rows.append((y_img, x_s, x_e, length))
    return rows

rows = detect_bar_endpoints(gray, 400, 780, 3.0, 200)
print(f"找到 {len(rows)} 个暗色水平段")
# 聚类为 15 根柱
rows.sort(key=lambda r: r[0])
clusters = []
last_y = -1
for r in rows:
    if clusters and r[0] - last_y <= 20:
        clusters[-1].append(r)
    else:
        clusters.append([r])
    last_y = r[0]

# 排序并输出
for i, cluster in enumerate(clusters):
    if len(cluster) < 3:
        continue
    ys = [c[0] for c in cluster]
    lengths = [c[3] for c in cluster]
    x_ends = [c[2] for c in cluster]
    y_c = (min(ys) + max(ys)) // 2
    length = sorted(lengths)[len(lengths)//2]
    x_end = sorted(x_ends)[len(x_ends)//2]
    print(f"  柱#{i+1}: y_pdf={y_c/3:.0f}, length_pdf={length/3:.0f}, x_end_pdf={x_end/3:.0f}")

doc.close()
