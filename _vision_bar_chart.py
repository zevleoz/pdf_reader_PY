"""通过图像处理从 B6 第 12 页的柱状图推断 15 个职业价值观得分。

策略：
1. 渲染 B6 PDF 第 12 页为图像
2. 在图像中找到每一行的中文标签（如"创造发明"、"生活方式"）
3. 在标签同一行的右侧区域，检测横向像素填充率（即柱子的水平宽度）
4. 根据已知 2 个锚点（生活方式 9.39、美的追求 3.29）将宽度线性映射为分数
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

import fitz
from PIL import Image


TARGET_LABELS = ["创造发明", "独立自主", "美的追求", "智力激发", "利他助人",
                 "成就感", "管理权力", "工作环境", "同事关系", "上司关系",
                 "多样变化", "经济报酬", "安全稳定", "声望地位", "生活方式"]


def render_page(pdf_path: Path, page_idx: int, dpi: int = 220) -> Image.Image:
    doc = fitz.open(str(pdf_path))
    page = doc[page_idx]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    doc.close()
    return img


def find_label_position(img: Image.Image, label: str,
                         anchor_text: str = "我的职业价值观") -> Tuple[int, int, int, int]:
    """用 pytesseract 对整张图做 OCR，返回标签包围盒 (x0,y0,x1,y1)。"""
    try:
        import pytesseract
    except Exception:
        return (-1, -1, -1, -1)
    try:
        d = pytesseract.image_to_data(img, lang='chi_sim+eng',
                                       output_type=pytesseract.Output.DICT)
    except Exception:
        return (-1, -1, -1, -1)
    # 按 block 收集文本
    n = len(d.get('text', []))
    for i in range(n):
        t = d['text'][i].strip()
        if t == label:
            x0, y0 = d['left'][i], d['top'][i]
            w, h = d['width'][i], d['height'][i]
            return (x0, y0, x0 + w, y0 + h)
    # 退一步：允许标签跨多个 token 匹配
    # 简单：找完全包含 label 的连续 token
    cur_text = ""
    for i in range(n):
        cur_text += d['text'][i]
        if label in cur_text:
            # 回溯到包含 label 的起点
            s = ""
            for j in range(max(0, i - 5), i + 1):
                s += d['text'][j]
                if label in s:
                    x0 = min(d['left'][k] for k in range(j, i + 1))
                    y0 = min(d['top'][k] for k in range(j, i + 1))
                    x1 = max(d['left'][k] + d['width'][k] for k in range(j, i + 1))
                    y1 = max(d['top'][k] + d['height'][k] for k in range(j, i + 1))
                    return (x0, y0, x1, y1)
            break
    return (-1, -1, -1, -1)


def bar_width_in_row(img: Image.Image, y_center: int, x_min: int, x_max: int,
                      half_h: int = 8, threshold: int = 200) -> int:
    """返回 y_center 行（半高 half_h）内在 x_min..x_max 范围内，暗色像素
    从左到右扫描时的最后一个非白列的 x 值，用于估计柱宽度。

    threshold: 灰度阈值（越大越白）；返回 柱子右缘 x 坐标 - x_min。
    """
    gray = img.convert("L")
    W, H = gray.size
    y0 = max(0, y_center - half_h)
    y1 = min(H, y_center + half_h)
    # 在 y0..y1 行中：每列取最小灰度值；如果某列有任何暗色像素，认为在柱内
    dark_in_col = []
    for x in range(x_min, x_max):
        darkest = 255
        for y in range(y0, y1):
            v = gray.getpixel((x, y))
            if v < darkest:
                darkest = v
        dark_in_col.append(darkest < threshold)
    # 找最大的连续 True 段
    max_len = 0
    cur_len = 0
    for b in dark_in_col:
        if b:
            cur_len += 1
            if cur_len > max_len:
                max_len = cur_len
        else:
            cur_len = 0
    return max_len


def estimate_scores(img: Image.Image) -> Dict[str, float]:
    """对 15 个标签做 OCR+柱宽估计，然后用两个锚点校准。"""
    W, H = img.size
    # 对整张图做一次 OCR
    try:
        import pytesseract
        d = pytesseract.image_to_data(img, lang='chi_sim+eng',
                                       output_type=pytesseract.Output.DICT)
    except Exception as e:
        print(f"[视觉] OCR 库或语言包不可用: {e}")
        return {}
    n = len(d.get('text', []))

    # 先找到 "我的职业价值观" 锚点，只考虑这个标题下方的区域
    anchor_y = 0
    for i in range(n):
        t = d['text'][i].strip()
        if "职业价值观" in t and ("我的" in t or "MY" in t):
            anchor_y = d['top'][i] + d['height'][i]
            break
    if anchor_y == 0:
        anchor_y = H // 4  # 退一步：取图像上 1/4 作为起点

    # 找到每个标签的 y 中心；且 y > anchor_y
    labels_positions: Dict[str, Tuple[int, int, int, int]] = {}
    for i in range(n):
        t = d['text'][i].strip()
        if not t:
            continue
        yc = d['top'][i] + d['height'][i] // 2
        if yc < anchor_y:
            continue
        # 精确匹配
        if t in TARGET_LABELS:
            x0, y0 = d['left'][i], d['top'][i]
            x1, y1 = x0 + d['width'][i], y0 + d['height'][i]
            if t not in labels_positions or labels_positions[t][1] < y0:
                labels_positions[t] = (x0, y0, x1, y1)

    # 如果某些标签没有被 OCR 识别出来——用模糊匹配（如 "创造" 包含 "创造"）
    for label in TARGET_LABELS:
        if label in labels_positions:
            continue
        for i in range(n):
            t = d['text'][i].strip()
            if not t:
                continue
            if label in t or t in label:
                x0, y0 = d['left'][i], d['top'][i]
                x1, y1 = x0 + d['width'][i], y0 + d['height'][i]
                if y1 > anchor_y:
                    labels_positions[label] = (x0, y0, x1, y1)
                    break

    # 估计每个标签对应的柱宽：右侧 60% 图像宽度
    results: Dict[str, int] = {}
    x_search_min = int(W * 0.15)
    x_search_max = int(W * 0.98)
    for label, (x0, y0, x1, y1) in labels_positions.items():
        yc = (y0 + y1) // 2
        w = bar_width_in_row(img, yc, x_search_min, x_search_max, half_h=6,
                              threshold=180)
        results[label] = w
        print(f"  {label}: yc={yc} width={w}px")

    if not results:
        return {}

    # 校准：用已知锚点 "生活方式"=9.39 和 "美的追求"=3.29
    # 如果只有一个锚点可用，则用线性缩放（以 x 轴长度为参考）
    # 取 x_search_max - x_search_min 为 10 分的参考长度来做基线
    # 先尝试用两个锚点：
    known = {"生活方式": 9.39, "美的追求": 3.29}
    anchors = [(results[k], v) for k, v in known.items() if k in results]
    if len(anchors) >= 2:
        (w1, v1), (w2, v2) = anchors[0], anchors[1]
        slope = (v2 - v1) / (w2 - w1) if (w2 - w1) != 0 else 0.01
        intercept = v1 - slope * w1
        print(f"  校准: v = {slope:.4f} * width + {intercept:.4f}")
        return {label: max(0.0, slope * w + intercept) for label, w in results.items()}
    elif len(anchors) == 1:
        (w_a, v_a) = anchors[0]
        slope = v_a / w_a if w_a > 0 else 0.01
        return {label: max(0.0, slope * w) for label, w in results.items()}
    else:
        # 假设总宽度对应 10 分
        total_w = x_search_max - x_search_min
        slope = 10.0 / total_w
        return {label: max(0.0, slope * w) for label, w in results.items()}


def main() -> Dict[str, float]:
    base = Path(__file__).resolve().parent
    pdf = base / "input" / "report_B6.pdf"
    img = render_page(pdf, 11, dpi=220)
    print(f"[视觉] B6 第 12 页 {img.width}x{img.height}")
    scores = estimate_scores(img)
    out = base / "data" / "_vision_b6_values.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(scores, f, ensure_ascii=False, indent=2)
    print(f"[视觉] 写入 {out}，共 {len(scores)} 项")
    return scores


if __name__ == "__main__":
    s = main()
    for k in TARGET_LABELS:
        if k in s:
            print(f"  {k}: {s[k]:.2f}")
        else:
            print(f"  {k}: MISSING")
