"""找到 '安全稳定' 在文本层中的精确坐标，然后在附近检测柱形条。"""
import fitz, numpy as np
from pathlib import Path

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))
page = doc[13]

# 第一步：找所有文本 span 的位置
dict_data = page.get_text("dict")
print("=== 包含 '经济报酬'、'安全稳定'、'声望地位'、'生活方式' 的文本块 ===")
for block in dict_data["blocks"]:
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            text = span["text"].strip()
            if any(k in text for k in ['经济报酬', '安全稳定', '声望地位', '生活方式']):
                x0, y0, x1, y1 = span["bbox"]
                size = span["size"]
                print(f"  '{text}' at ({x0:.0f},{y0:.0f})-({x1:.0f},{y1:.0f}), size={size:.1f}")

# 第二步：分析 y=600-700 区域的暗色像素分布（列方向平均）
zoom = 3.0
mat = fitz.Matrix(zoom, zoom)
pix = page.get_pixmap(matrix=mat, alpha=False)
img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
if img.shape[2] == 4:
    img = img[:, :, :3]
gray = np.mean(img, axis=2).astype(np.uint8)
dark_mask = gray < 150

# 在 y=600-700 PDF 范围内，找每一行的暗色像素数
print(f"\n=== y=600-700 PDF 区域的暗色像素分布 ===")
for y_pdf in range(600, 700, 5):
    ys_img = int(y_pdf * zoom)
    ye_img = int((y_pdf + 4) * zoom)
    xs_img = int(100 * zoom)
    xe_img = int(500 * zoom)
    if ys_img >= dark_mask.shape[0] or xe_img >= dark_mask.shape[1]:
        continue
    sub = dark_mask[ys_img:ye_img, xs_img:xe_img]
    total = sub.sum()
    col_counts = sub.sum(axis=0)
    if col_counts.max() > 0:
        max_c = col_counts.max()
        # 找最右端的暗色位置
        right_end = -1
        for j in range(len(col_counts) - 1, -1, -1):
            if col_counts[j] >= max_c * 0.15:
                right_end = j
                break
        right_end_pdf = 100 + right_end / zoom if right_end > 0 else 0
        print(f"  y=[{y_pdf}-{y_pdf+4}] PDF: total_dark={total}, max_col={max_c}, right_end_pdf={right_end_pdf:.0f}")

# 第三步：更广泛地检测整个图表区域（y=350-700），找"高密度暗色像素"的行
print(f"\n=== y=350-700 区域的高暗色像素行（可能是柱形条标签）===")
dark_rows = []
for y_pdf in range(350, 700, 3):
    ys_img = int(y_pdf * zoom)
    ye_img = int((y_pdf + 2) * zoom)
    if ye_img >= dark_mask.shape[0]:
        break
    sub = dark_mask[ys_img:ye_img, int(50*zoom):int(550*zoom)]
    total = sub.sum()
    if total > 100:  # 有明显的暗色像素
        col_counts = sub.sum(axis=0)
        max_c = col_counts.max()
        right_end = -1
        for j in range(len(col_counts) - 1, -1, -1):
            if col_counts[j] >= max_c * 0.15:
                right_end = j
                break
        right_end_pdf = 50 + right_end / zoom if right_end > 0 else 0
        dark_rows.append((y_pdf, total, max_c, right_end_pdf))
        print(f"  y={y_pdf} PDF: total_dark={total}, max_col={max_c}, right_end_pdf={right_end_pdf:.0f}")

doc.close()

# 找明显的 "柱形条行"（暗色像素非常密集的连续水平区域）
print(f"\n=== 可能的柱形条位置聚类 ===")
dark_rows.sort(key=lambda r: r[1], reverse=True)
print("  Top 20 darkest rows:")
for y, total, max_c, re in dark_rows[:20]:
    print(f"    y={y} PDF: total_dark={total}, right_end={re:.0f}")
