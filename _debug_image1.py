"""用图像处理估计 B6 职业价值观 15 个得分。"""
import json
from pathlib import Path
import numpy as np
import fitz
from PIL import Image

TARGET_LABELS = ["创造发明", "独立自主", "美的追求", "智力激发", "利他助人",
                 "成就感", "管理权力", "工作环境", "同事关系", "上司关系",
                 "多样变化", "经济报酬", "安全稳定", "声望地位", "生活方式"]

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"

# 1) 渲染 B6 第 14 页为高分辨率图像
doc = fitz.open(str(pdf_path))
page = doc[13]
zoom = 3.0
mat = fitz.Matrix(zoom, zoom)
pix = page.get_pixmap(matrix=mat, alpha=False)
# 转为 numpy 灰度图
img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
if img.shape[2] == 4:
    img = img[:, :, :3]
gray = np.mean(img, axis=2).astype(np.uint8)
print(f"Image shape: {gray.shape} (pix: {pix.width}x{pix.height})")

# 2) 找到文本层里的两个锚点标签位置（PDF 坐标）
#    "生活方式" x=420 y=220
#    "美的追求" x=499 y=220
#    数字 9.39 x=414 y=189
#    数字 3.29 x=493 y=189
# 但标签 y=220 只占很小部分。15 项柱应该在页面下方。
# 让我看看 y>400 区域的图像内容。

# 扫描 y=400 到 y=780 区间，每行的暗色像素列数（水平柱）
# 思路：对每一行，计算"暗色像素"的水平分布
# 找到每一行的最大暗色像素块（即柱）的右端点

# 先看灰度分布：
threshold_value = 180  # 阈值：小于阈值是暗色
dark_mask = gray < threshold_value

# 找连续暗色块：从左到右，找最长连续 True 的段
# 对每一行做一次，找到其右边界（x_max）
def bar_right_end(row, min_len=10):
    """返回最长连续 True 段的最后一个索引；没有则返回 -1。"""
    best_end = -1
    best_len = 0
    cur_start = -1
    for i, v in enumerate(row):
        if v and cur_start < 0:
            cur_start = i
        elif not v and cur_start >= 0:
            length = i - cur_start
            if length > best_len:
                best_len = length
                best_end = i - 1
            cur_start = -1
    if cur_start >= 0:
        length = len(row) - cur_start
        if length > best_len:
            best_len = length
            best_end = len(row) - 1
    return best_end if best_len >= min_len else -1

# 分析 y=400..780（PDF 坐标），注意 zoom=3 所以图像 y = PDF y * 3
# 不过页面渲染从 y=0 开始，所以图像 y = PDF y * zoom
# 让我看 y 从 400 到 800（图像 y 从 1200 到 2400）
results = []
# 按行（图像坐标）找柱的右边缘
for y_img in range(int(400*zoom), int(800*zoom), max(1, int(5*zoom))):
    if y_img >= gray.shape[0]: break
    row = dark_mask[y_img, :]
    end = bar_right_end(row, min_len=50)
    if end >= 0:
        results.append((y_img, end))

# 现在用聚类：把 y_img 相近的归为同一行（同一根柱）
# 同一根柱占约 25 行（PDF 约 8）
clusters = []  # [(y_min, y_max, x_end_avg)]
for y_img, x_end in results:
    if clusters and y_img - clusters[-1][1] < 30:
        # 扩展当前 cluster
        y_min, y_max, x_sum, cnt = clusters[-1]
        clusters[-1] = (y_min, y_img, x_sum + x_end, cnt + 1)
    else:
        clusters.append((y_img, y_img, x_end, 1))

print(f"\n找到 {len(clusters)} 个水平柱条簇:")
for idx, (y_min, y_max, x_sum, cnt) in enumerate(clusters[:20]):
    x_avg = x_sum / cnt
    pdf_y = (y_min + y_max) / 2 / zoom
    print(f"  柱#{idx+1}: y_pdf~{pdf_y:.0f}, x_end_avg_img={x_avg:.0f}, count={cnt}")

# 提取 top 15 个最"有希望"的柱条
clusters_sorted = sorted(clusters, key=lambda c: -c[3])[:15]
clusters_sorted.sort(key=lambda c: c[0])  # 按 y 排序

# 但是，我们知道 "生活方式" 和 "美的追求" 的真实得分。
# 让我们通过他们的 x 坐标来校准。
# 生活方式 label x_pdf = 420，美的追求 label x_pdf = 499
# 数字 生活方式 9.39 x_pdf = 414；美的追求 3.29 x_pdf = 493
# 但这 2 个值是"最大/最小"，不是每个项目的值
# 等等——让我再看：这 2 个数字是页面上部的"最高分 / 最低分"指标

# 我需要看看这些柱条对应的 x_end_img 是什么
print("\n=== 柱条（按 y 排序）===")
for idx, (y_min, y_max, x_sum, cnt) in enumerate(clusters_sorted):
    x_end_avg = x_sum / cnt
    x_end_pdf = x_end_avg / zoom
    print(f"  柱#{idx+1}: y_pdf~{(y_min+y_max)/2/zoom:.0f}, x_end_pdf={x_end_pdf:.1f}, len_pixel_cnt={cnt}")

# 现在如果要估计得分，需要找"每个柱条的长度"相对与整个 x 轴刻度
# 让我找 x 轴的最小/最大刻度——即柱条可能的 x 范围
# 看页面上是否存在刻度数字（0, 2, 4, 6, 8, 10 在某一行 y=?）

# 找所有文本中的数字，分析是否是刻度
page14 = doc[13]
blocks = page14.get_text("dict")["blocks"]
scale_nums = []
for block in blocks:
    for line in block.get("lines", []):
        for span in line["spans"]:
            t = span["text"].strip()
            if not t: continue
            try:
                v = float(t)
                if 0 <= v <= 10 and span["size"] < 12:
                    bbox = span["bbox"]
                    scale_nums.append({"x": bbox[0], "y": bbox[1], "val": v, "size": span["size"]})
            except ValueError:
                pass
print(f"\n=== 疑似刻度数字 {len(scale_nums)} 个 ===")
for d in scale_nums[:30]:
    print(f"  x={d['x']:.0f} y={d['y']:.0f} size={d['size']:.1f} val={d['val']}")

doc.close()
