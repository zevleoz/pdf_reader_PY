"""把 y=420-680 等分成 15 段，检测每段中心行的柱条长度（右端 x）。

核心想法：既然所有柱条都是一个"横向条带"，它们之间的间隔很小，
让我在 y=420..680 范围内，把这个区域等分成 15 个小段，
每段的中心 y 就是第 i 个柱条的中心。
然后在该 y 附近取若干行检测"最长连续暗色段的右端 x"。
"""
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
if img.shape[2] == 4: img = img[:, :, :3]
gray = np.mean(img, axis=2).astype(np.uint8)
threshold = 160
dark_mask = gray < threshold

# 把 y=420..680 等分成 15 段
y_min_pdf = 420
y_max_pdf = 680
n_segments = 15
segment_height = (y_max_pdf - y_min_pdf) / n_segments

print(f"=== 把 y={y_min_pdf}-{y_max_pdf} 等分成 {n_segments} 段 ===")
print(f"每段高: {segment_height:.1f} (pdf 坐标)")

# 对每段，在中心 y 附近 ±3 行范围内找最长连续暗色段
bar_data = []
for i in range(n_segments):
    y_center_pdf = y_min_pdf + segment_height * (i + 0.5)
    y_center_img = int(y_center_pdf * zoom)

    # 在中心附近 ±3*zoom 行找最长连续段
    right_ends = []
    left_starts = []
    lengths = []

    for y in range(y_center_img - 3, y_center_img + 4):
        if y >= gray.shape[0]: continue
        row = dark_mask[y, :]
        # 找最长连续暗色段
        best_start, best_end, best_len = 0, 0, 0
        cur_start, cur_len = -1, 0
        for x in range(row.shape[0]):
            if row[x]:
                if cur_start < 0:
                    cur_start = x
                cur_len += 1
            else:
                if cur_len > best_len:
                    best_len = cur_len
                    best_start = cur_start
                    best_end = x - 1
                cur_start = -1
                cur_len = 0
        # 不要忘了最后一段
        if cur_len > best_len:
            best_len = cur_len
            best_start = cur_start
            best_end = row.shape[0] - 1
        if best_len >= 30:
            right_ends.append(best_end)
            left_starts.append(best_start)
            lengths.append(best_len)

    if not right_ends:
        bar_data.append(None)
        print(f"  段#{i+1}: y_center={y_center_pdf:.0f} — 未检测到柱条")
        continue

    x_start_pdf = np.median(left_starts) / zoom
    x_end_pdf = np.median(right_ends) / zoom
    length_pdf = x_end_pdf - x_start_pdf
    bar_data.append({
        "y_center": y_center_pdf,
        "x_start": x_start_pdf,
        "x_end": x_end_pdf,
        "length": length_pdf,
    })
    print(f"  段#{i+1}: y_center={y_center_pdf:.0f}, x=[{x_start_pdf:.0f}-{x_end_pdf:.0f}], length={length_pdf:.0f}")

# 输出排序后的结果
print("\n=== 按长度排序（从长到短） ===")
valid_bars = [b for b in bar_data if b is not None]
valid_bars.sort(key=lambda b: -b["length"])
for i, b in enumerate(valid_bars):
    print(f"  #{i+1}: y_center={b['y_center']:.0f}, length={b['length']:.0f}")

doc.close()
