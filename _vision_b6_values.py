"""视觉层（本地）解析 B6 职业价值观图表。
职业价值观报告页（PDF第12页）是一张横向柱状图：每列一根横条，
顶端有精确数字分。我们直接抽取本页图像的数字与中文标签对应。

策略：
1) 渲染 report_B6.pdf 的第 12 页为 PNG（dpi=150 足以看清数字）
2) 用 pytesseract / easyocr 读取整张图片的中文标签与数字
3) 按 "数字紧邻右侧标签" 的规则对 15 个项目对齐
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz


PDF_PATH = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
OUT_JSON = Path(__file__).resolve().parent / "data" / "vision_b6_work_values.json"
PAGE_INDEX = 11  # 第 12 页（从0开始）

TARGET_LABELS = ["创造发明", "独立自主", "美的追求", "智力激发", "利他助人",
                 "成就感", "管理权力", "工作环境", "同事关系", "上司关系",
                 "多样变化", "经济报酬", "安全稳定", "声望地位", "生活方式"]


def render_page_to_image(pdf_path: Path, page_index: int, dpi: int = 180) -> Optional[Path]:
    """渲染 PDF 中指定页为 PNG。"""
    if not pdf_path.exists():
        return None
    doc = fitz.open(str(pdf_path))
    page = doc[page_index]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    doc.close()
    out_dir = Path(__file__).resolve().parent / "pages"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"b6_values_p{page_index+1}_d{dpi}.png"
    pix.save(str(out_path))
    return out_path


def ocr_image_tesseract(img_path: Path) -> List[Tuple[str, float, float, float, float]]:
    """用 pytesseract 做 OCR（中文+英文+数字），返回 [(text, x0,y0,x1,y1), ...]。
    如果 tesseract 不可用返回 []。
    """
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        return []
    try:
        img = Image.open(str(img_path))
        data = pytesseract.image_to_data(img, lang='chi_sim+eng', output_type=pytesseract.Output.DICT)
    except Exception as e:
        print(f"  [视觉] OCR 失败: {e}")
        return []
    W, H = img.size
    n = len(data.get('text', []))
    out: List[Tuple[str, float, float, float, float]] = []
    # 逐行聚合（用 block+line 合并文本）
    cur_key: Optional[Tuple[int, int, int]] = None
    cur_box: Optional[List[float]] = None
    cur_text = ""
    for i in range(n):
        key = (data['block_num'][i], data['line_num'][i], data['par_num'][i])
        conf = int(data['conf'][i])
        if conf < 20:
            continue
        t = data['text'][i].strip()
        if not t:
            continue
        left, top, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
        box = [left / W, top / H, (left + w) / W, (top + h) / H]
        if key == cur_key:
            cur_box[0] = min(cur_box[0], box[0])
            cur_box[1] = min(cur_box[1], box[1])
            cur_box[2] = max(cur_box[2], box[2])
            cur_box[3] = max(cur_box[3], box[3])
            cur_text += ("" if cur_text.endswith("-") else " ") + t
        else:
            if cur_key is not None and cur_text.strip():
                out.append((cur_text.strip(), *cur_box))
            cur_key = key
            cur_box = box
            cur_text = t
    if cur_key is not None and cur_text.strip():
        out.append((cur_text.strip(), *cur_box))
    return out


def extract_from_text_layer(b6_text: str) -> Dict[str, str]:
    """在 B6 文本层中抓取已有的 "数字\n标签" 结构作为基础。
    这里仅作为补充——主要工作由视觉层完成。
    """
    anchor = max(b6_text.find("得分情况如下"),
                 b6_text.find("我的职业价值观   丨"),
                 b6_text.find("MY WORK VALUES"),
                 0)
    seg = b6_text[anchor: anchor + 1500]
    lines = [l.strip() for l in seg.splitlines() if l.strip()]
    result: Dict[str, str] = {}
    num_cache: Optional[str] = None
    for ln in lines:
        if re.match(r"^[\d.]+$", ln):
            num_cache = ln
            continue
        if num_cache is not None and ln in TARGET_LABELS:
            result[ln] = num_cache
            num_cache = None
            continue
        # 其它中文行重置缓存
        if any("\u4e00" <= c <= "\u9fff" for c in ln):
            num_cache = None
    return result


def align_labels_numbers(items: List[Tuple[str, float, float, float, float]]) -> Dict[str, str]:
    """将 OCR 结果按 y 中心聚类：同一行的 "数字" 与 "中文标签" 视为一组。
    只保留已知 15 个标签。
    """
    if not items:
        return {}
    # 归一化：每行一个记录，y 中心 = (y0+y1)/2
    rows: List[Tuple[float, str]] = []
    for text, x0, y0, x1, y1 in items:
        yc = (y0 + y1) / 2.0
        rows.append((yc, text))
    # 按 y 排序
    rows.sort(key=lambda r: r[0])
    # 在同一 y±0.005 高度的条目视为同一行；先找包含标签名的行，再在同行中找数字
    by_row: Dict[int, List[str]] = {}
    clusters: List[List[str]] = []
    cur_y = -1
    for yc, text in rows:
        if cur_y < 0 or abs(yc - cur_y) > 0.010:
            clusters.append([text])
            cur_y = yc
        else:
            clusters[-1].append(text)
    # 对每个 cluster：找出一个已知 label 和一个最接近的数字
    out: Dict[str, str] = {}
    for c in clusters:
        labels = [t for t in c if t in TARGET_LABELS]
        nums = [t for t in c if re.match(r"^[\d.]+$", t)]
        if labels and nums:
            out[labels[0]] = nums[0]
        # 退一步：数字带 "分" 也可以
        if labels and not nums:
            m = re.search(r"([\d.]+)\s*分", " ".join(c))
            if m:
                out[labels[0]] = m.group(1)
    return out


def main() -> Dict[str, str]:
    result: Dict[str, str] = {}
    # 1) 文本层强匹配
    if PDF_PATH.exists():
        doc = fitz.open(str(PDF_PATH))
        b6_text = "\n".join(p.get_text() for p in doc)
        doc.close()
        text_layer = extract_from_text_layer(b6_text)
        result.update(text_layer)

    # 2) 视觉 OCR 补充
    try:
        img = render_page_to_image(PDF_PATH, PAGE_INDEX, dpi=180)
        if img:
            ocr_items = ocr_image_tesseract(img)
            if ocr_items:
                vis = align_labels_numbers(ocr_items)
                for k, v in vis.items():
                    result.setdefault(k, v)
    except Exception as e:
        print(f"  [视觉] 视觉 OCR 跳过: {e}")

    OUT_JSON.parent.mkdir(exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  [视觉] 职业价值观视觉补全: {len(result)} 项 -> {OUT_JSON}")
    return result


if __name__ == "__main__":
    print(main())
