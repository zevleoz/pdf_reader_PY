"""B3 新版（2026-11）报告读取辅助。

新版 B3 与旧版的差异（影响抽取的部分）：
  * 文本层是乱码（自定义字体编码），按关键词选页会全部落空；
  * 学习动机 / 学习方法与策略两页不再印出"平均得分"数字，
    同龄群体均值只以半环图上的虚线表示（图是位图）；
  * 不再印出"自我效能感"和"学习自我调节"两项，改为两个新分项
    （学习方法实践与提升、学习策略执行与优化）。

新版映射（owner 决定 2026-11-07）：
  * 学习方法实践与提升的"测评结果"得分 → 068 学习动机-自我效能感；
  * 学习策略执行与优化的"测评结果"得分 → 071 学习方法与策略-学习自我调节；
  * 130/133 在新版没有常模平均数，一律留空。
旧版 B3 的读法保持不变。

本模块：
  * is_new_b3()       判断是否为新版版式（看两张半环图）；
  * vision_pages()    新版需要送视觉模型的页码；
  * read_gauges()     从半环图像素直接量出学生得分和虚线（同龄均值），
                      不经过模型、不做估计以外的推断。学生得分的量值用来
                      与图上印的数字互相校验；
  * NEW_LAYOUT_PROMPT_LINES  新版 B3 的 schema 替代行。
"""
from __future__ import annotations

from pathlib import Path
import math
from typing import Dict, List, Optional, Tuple

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

# 半环图在页面上的大小约 297 x 171 pt；按此识别，不依赖页码
_GAUGE_W = (280.0, 315.0)
_GAUGE_H = (155.0, 185.0)
_SCALE = 4.0

# 新版 17 页版式里的数据页：执行功能总览 + 三个分项 + 动机 + 方法 + 两个新增分项
_NEW_LAYOUT_PAGES = [3, 4, 6, 8, 10, 12, 14, 16]

# 第 1 张半环图 = 学习动机，第 2 张 = 学习方法与策略
# (左半边得分, 右半边得分, 左半边均值, 右半边均值)
_GAUGE_CODES = [
    ("066", "067", "128", "129"),
    ("069", "070", "131", "132"),
]

# 新版不再提供的项（常模均值）；068/071 改由新分项的"测评结果"得分填入
DROPPED_CODES = ("130", "133")

# 新版 B3 的 schema 替代行：键为 code，值为整行（须匹配 extract._SCHEMA_ITEM_LINE_RE）
NEW_LAYOUT_PROMPT_LINES = {
    "068": '068 学习方法实践与提升-得分 number（B3，"学习方法实践与提升报告"页右侧"测评结果"卡片中"得分 X/10"的 X）',
    "071": '071 学习策略执行与优化-得分 number（B3，"学习策略执行与优化报告"页右侧"测评结果"卡片中"得分 X/10"的 X）',
    "128": '128 学习动机-深层动机常模平均数 number（B3，新版不印此数字，一律输出 ""）',
    "129": '129 学习动机-表面动机常模平均数 number（B3，新版不印此数字，一律输出 ""）',
    "130": '130 学习动机-自我效能感常模平均数 number（B3，新版不印此数字，一律输出 ""）',
    "131": '131 学习方法与策略-学习深层方法与策略常模平均数 number（B3，新版不印此数字，一律输出 ""）',
    "132": '132 学习方法与策略-学习表面方法与策略常模平均数 number（B3，新版不印此数字，一律输出 ""）',
    "133": '133 学习方法与策略-学习自我调节常模平均数 number（B3，新版不印此数字，一律输出 ""）',
}


def _gauge_rects(doc) -> List[Tuple[int, "fitz.Rect"]]:
    out = []
    for pno in range(len(doc)):
        page = doc[pno]
        for info in page.get_image_info():
            r = fitz.Rect(info["bbox"])
            if (_GAUGE_W[0] <= r.width <= _GAUGE_W[1]
                    and _GAUGE_H[0] <= r.height <= _GAUGE_H[1]
                    and r.y1 < page.rect.height * 0.6):
                out.append((pno, r))
                break
    return out


def is_new_b3(pdf_path: Path) -> bool:
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return False
    try:
        return len(_gauge_rects(doc)) == 2
    finally:
        doc.close()


def vision_pages(pdf_path: Path) -> List[int]:
    doc = fitz.open(str(pdf_path))
    try:
        total = len(doc)
    finally:
        doc.close()
    return [p for p in _NEW_LAYOUT_PAGES if p <= total]


def _measure(pix) -> Optional[Dict[str, float]]:
    """极坐标扫描半环图，量出左右两半的得分与虚线（同龄均值），单位为 0–10 分。

    * 圆心：图宽中点、彩色区最低行的下一行；
    * 0 分半径 = 彩色环内沿；10 分半径 = 最外一圈连续刻度线的中心；
    * 得分 = 彩色占比 > 50% 的最大半径；
    * 刻度线 / 柱边描线是"连续"的暗环（各角度几乎都暗），虚线只在约一半角度上暗，
      据此只取断续暗环作为均值线。
    """
    w, h, n = pix.width, pix.height, pix.n
    buf = pix.samples

    def px(x: float, y: float):
        xi, yi = int(x), int(y)
        if not (0 <= xi < w and 0 <= yi < h):
            return None
        i = (yi * w + xi) * n
        return buf[i], buf[i + 1], buf[i + 2]

    def colored(p) -> bool:
        return max(p) - min(p) > 60

    cy = None
    for y in range(h - 1, 0, -1):
        if any(colored(px(x, y)) for x in range(0, w, 3)):
            cy = y + 1
            break
    if cy is None:
        return None
    cx = w / 2.0
    angles = [math.radians(a / 2.0) for a in range(20, 140)]   # 10°–70° 仰角
    step = 0.5 * w / 1189.0

    out: Dict[str, float] = {}
    for side, sgn in (("l", -1), ("r", 1)):
        prof = []   # (r, colored_frac, dark_frac)
        r = 0.14 * w
        while r < 0.42 * w:
            col = dark = cnt = 0
            for a in angles:
                ca, sa = math.cos(a), math.sin(a)
                p = px(cx + sgn * r * ca, cy - r * sa)
                pa = px(cx + sgn * (r - 5 * step * 2) * ca, cy - (r - 5 * step * 2) * sa)
                pb = px(cx + sgn * (r + 5 * step * 2) * ca, cy - (r + 5 * step * 2) * sa)
                if p is None or pa is None or pb is None:
                    continue
                cnt += 1
                col += colored(p)
                dark += (min(sum(pa), sum(pb)) - sum(p)) > 30
            if cnt:
                prof.append((r, col / cnt, dark / cnt))
            r += step

        col_r = [r for r, c, _ in prof if c > 0.5]
        if not col_r:
            continue
        r0, r_bar = min(col_r), max(col_r)

        # 暗环分段：连续 dark ≥ 0.4 的半径区间
        runs, cur = [], []
        for r, _c, dk in prof:
            if dk >= 0.4:
                cur.append((r, dk))
            elif cur:
                runs.append(cur)
                cur = []
        if cur:
            runs.append(cur)
        solid = [rn for rn in runs if max(dk for _, dk in rn) >= 0.85]
        dashed = [rn for rn in runs if max(dk for _, dk in rn) < 0.85]
        if not solid:
            continue

        def centre(rn):
            return sum(r * dk for r, dk in rn) / sum(dk for _, dk in rn)

        r10 = max(centre(rn) for rn in solid)
        unit = (r10 - r0) / 10.0
        if unit <= 0:
            continue
        out[f"{side}_score"] = (r_bar - r0) / unit
        if len(dashed) == 1:
            out[f"{side}_norm"] = (centre(dashed[0]) - r0) / unit
    return out


def read_gauges(pdf_path: Path) -> Dict[str, float]:
    """返回 {code: 量得的值}，值保留 2 位小数，由调用方决定如何取整/校验。
    只包含量到的项；非新版版式返回 {}。"""
    doc = fitz.open(str(pdf_path))
    try:
        rects = _gauge_rects(doc)
        if len(rects) != 2:
            return {}
        out: Dict[str, float] = {}
        for (pno, rect), codes in zip(rects, _GAUGE_CODES):
            pix = doc[pno].get_pixmap(matrix=fitz.Matrix(_SCALE, _SCALE),
                                      clip=rect, alpha=False)
            m = _measure(pix) or {}
            for key, code in zip(("l_score", "r_score", "l_norm", "r_norm"), codes):
                if key in m:
                    out[code] = round(m[key], 2)
        return out
    finally:
        doc.close()


def reconcile(vision: Dict[str, object], measured: Dict[str, float],
              tol: float = 0.2) -> Tuple[Dict[str, str], List[str]]:
    """把量得值并入视觉结果。返回 (更新项, 警告)。

    * 得分（066/067/069/070）：以图上印的数字（视觉结果）为准；视觉为空时用量值；
      两者相差超过 tol 记警告。
    * 常模均值（128/129/131/132）：新版没有印数字，只能用量值；仅当同一张图的
      两个得分量值都与印的数字相符（≤ tol）时才采用，否则留空并警告。
    * 新版没有常模均值的项（130/133）置空，避免模型编造；068/071 由视觉结果
      按新版 schema 从新分项读取，这里不改。"""
    updates: Dict[str, str] = {}
    warnings: List[str] = []

    def _num(x) -> Optional[float]:
        try:
            return float(str(x).strip())
        except (TypeError, ValueError):
            return None

    for l_s, r_s, l_n, r_n in _GAUGE_CODES:
        trusted = True
        for code in (l_s, r_s):
            printed, meas = _num(vision.get(code)), measured.get(code)
            if meas is None:
                trusted = False
                continue
            if printed is None:
                updates[code] = f"{meas:.1f}"
                trusted = False   # 无印刷值可校验
                warnings.append(f"{code} 视觉未读到，用图形量值 {meas:.1f}")
            elif abs(printed - meas) > tol:
                trusted = False
                warnings.append(f"{code} 印刷值 {printed} 与图形量值 {meas:.2f} 不符")
        for code in (l_n, r_n):
            meas = measured.get(code)
            if trusted and meas is not None:
                updates[code] = f"{meas:.1f}"
            else:
                updates[code] = ""
                warnings.append(f"{code} 同龄均值无法可靠读取，留空")

    for code in DROPPED_CODES:
        updates[code] = ""
    # 068/071 由视觉结果按新版 schema 从新分项读取，原样保留
    for code in ("068", "071"):
        if code in vision:
            updates[code] = str(vision[code]).strip()
    return updates, warnings


if __name__ == "__main__":  # 手动检查：python b3_gauge.py <pdf>
    import sys
    p = Path(sys.argv[1])
    print("new layout:", is_new_b3(p))
    print("pages:", vision_pages(p))
    print("measured:", read_gauges(p))
