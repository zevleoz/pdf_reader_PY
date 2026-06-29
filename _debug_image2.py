"""用更精确的图像分析来识别 B6 第 14 页的 15 个职业价值观柱形条。

分析思路：
1. 渲染 B6 PDF 第 14 页为高分辨率图像
2. 分析每行暗色像素：找出 15 个不同 y 位置的"柱形条"
3. 测量每个柱形条的右端 x 位置
4. 通过"x 轴刻度"（0-10）将位置线性映射为分数
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

import fitz
from PIL import Image
import numpy as np

TARGET_LABELS = ["创造发明", "独立自主", "美的追求", "智力激发", "利他助人",
                 "成就感", "管理权力", "工作环境", "同事关系", "上司关系",
                 "多样变化", "经济报酬", "安全稳定", "声望地位", "生活方式"]


def render_pdf_page(pdf_path: Path, page_idx: int, zoom: float = 3.0) -> Tuple[np.ndarray, int]:
    """渲染 PDF 某页，返回（灰度图数组，页面像素宽度）。"""
    doc = fitz.open(str(pdf_path))
    page = doc[page_idx]
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if img.shape[2] == 4:
        img = img[:, :, :3]
    gray = np.mean(img, axis=2).astype(np.uint8)
    doc.close()
    return gray, pix.width


def detect_horizontal_bars(gray: np.ndarray, pdf_page_width: float,
                           pdf_page_height: float, zoom: float,
                           y_min_pdf: float = 400, y_max_pdf: float = 780,
                           threshold: int = 200,
                           min_bar_length_pdf: float = 20) -> List[Tuple[float, float]]:
    """检测 y_min_pdf 到 y_max_pdf 之间的水平柱形条。
    返回 [(y_pdf_center, bar_length_in_pdf_x), ...]
    """
    H, W = gray.shape
    actual_zoom = W / pdf_page_width

    y_min_img = int(y_min_pdf * actual_zoom)
    y_max_img = int(y_max_pdf * actual_zoom)

    dark_mask = gray < threshold

    # 找每行的暗色像素起始/结束位置
    bar_info: List[Tuple[int, int, int]] = []  # (y_img, x_start, x_end)
    for y in range(y_min_img, y_max_img):
        row = dark_mask[y, :]
        if not np.any(row):
            continue
        # 找最长连续段
        # 简化：找第一个 True 的位置和最后一个 True 的位置
        true_indices = np.where(row)[0]
        if len(true_indices) < 10:
            continue
        # 用更精细的方法：找连续段，选最长
        segments = []
        cur_start = -1
        for i, v in enumerate(row):
            if v and cur_start < 0:
                cur_start = i
            elif not v and cur_start >= 0:
                segments.append((cur_start, i - 1))
                cur_start = -1
        if cur_start >= 0:
            segments.append((cur_start, len(row) - 1))
        # 选择最长段
        if segments:
            segments.sort(key=lambda s: -(s[1] - s[0]))
            x_s, x_e = segments[0]
            length = x_e - x_s
            if length >= min_bar_length_pdf * actual_zoom:
                bar_info.append((y, x_s, x_e))

    # 聚类：同一根柱相邻行归为一组
    # 按 y 聚类，相邻 y 差距 <= 5
    bar_info.sort(key=lambda t: t[0])
    clusters: List[List[Tuple[int, int, int]]] = []
    last_y = -1
    for entry in bar_info:
        y = entry[0]
        if clusters and y - last_y <= 12:
            clusters[-1].append(entry)
        else:
            clusters.append([entry])
        last_y = y

    # 过滤簇，取平均
    results = []
    for cluster in clusters:
        if len(cluster) < 3:  # 少于 3 行的忽略
            continue
        y_imgs = [c[0] for c in cluster]
        x_starts = [c[1] for c in cluster]
        x_ends = [c[2] for c in cluster]
        y_center_img = (min(y_imgs) + max(y_imgs)) / 2
        y_pdf = y_center_img / actual_zoom
        # 用中位数更稳
        x_start_med = sorted(x_starts)[len(x_starts) // 2]
        x_end_med = sorted(x_ends)[len(x_ends) // 2]
        length_pdf = (x_end_med - x_start_med) / actual_zoom
        results.append((y_pdf, length_pdf, x_start_med / actual_zoom, x_end_med / actual_zoom))

    return results


def main():
    base = Path(__file__).resolve().parent
    b6_pdf = base / "input" / "report_B6.pdf"

    # 渲染 B6 PDF 第 14 页（doc index 13）
    gray, width = render_pdf_page(b6_pdf, 13, zoom=3.0)
    print(f"B6 第 14 页渲染: {gray.shape}")

    # 分析水平柱形条
    bars = detect_horizontal_bars(gray, pdf_page_width=594.75,
                                   pdf_page_height=842.24, zoom=3.0,
                                   y_min_pdf=400, y_max_pdf=780,
                                   threshold=200, min_bar_length_pdf=30)

    print(f"\n共识别 {len(bars)} 个柱形条:")
    for i, (y_pdf, length_pdf, x_s_pdf, x_e_pdf) in enumerate(bars[:25]):
        print(f"  #{i+1}: y={y_pdf:.0f}, len={length_pdf:.0f}, x=[{x_s_pdf:.0f}, {x_e_pdf:.0f}]")

    # 找"最可能是 15 根柱形条"的连续区域
    # 筛选：y 范围比较集中的 15 个
    if len(bars) >= 15:
        # 找长度差异不大的 15 个（排序后找连续的 length 值）
        # 先用 y 值聚类：15 个连续 y 值之间的差应该比较均匀
        possible_groups = []
        for start in range(0, len(bars) - 14):
            group = bars[start:start + 15]
            y_diffs = [group[i+1][0] - group[i][0] for i in range(14)]
            avg_diff = sum(y_diffs) / len(y_diffs)
            variance = sum((d - avg_diff)**2 for d in y_diffs) / len(y_diffs)
            lengths = [b[1] for b in group]
            possible_groups.append((variance, start, group, avg_diff, max(lengths), min(lengths)))
        possible_groups.sort(key=lambda t: t[0])

        best = possible_groups[0]
        print(f"\n最均匀的 15 根柱（y 方差={best[0]:.1f}）:")
        for i, (y_pdf, length_pdf, x_s_pdf, x_e_pdf) in enumerate(best[2]):
            print(f"  #{i+1}: y={y_pdf:.0f}, len={length_pdf:.0f}, x=[{x_s_pdf:.0f}, {x_e_pdf:.0f}]")


if __name__ == "__main__":
    main()
