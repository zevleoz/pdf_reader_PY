"""新版 B3「学习方法实践 / 学习策略执行」明细的读取辅助（Y4-2 学习力报告用）。

只处理新版 B3；名称、分组、说明文字全部由视觉调用从 PDF 页面读出，这里不写死。
输出写入报告快照的 ``raw["b3_detail"]``（见 docs/audits/plans-b3/Y4-2-build.md）。
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

import b3_gauge

CHECK_TOLERANCE = 2.0

TIER_LABELS_SCORE = {
    "T1": "高频使用", "T2": "较常使用", "T3": "有时使用",
    "T4": "较少使用", "T5": "从未使用",
}
TIER_LABELS_PCT = {
    "T1": "优势表现型", "T2": "良好发展型", "T3": "一般发展型",
    "T4": "需要支持型", "T5": "重点支持型",
}
TIER_COLORS = {"T5": "#E0403A", "T4": "#F07C2C", "T3": "#F2B630",
               "T2": "#5CA0B0", "T1": "#5A9E5F"}


def tier_score(score: float) -> Tuple[str, str]:
    """0–10 分 → (T 编号, 频率词)。"""
    s = float(score)
    if s < 3:
        code = "T5"
    elif s < 5:
        code = "T4"
    elif s < 7:
        code = "T3"
    elif s < 9:
        code = "T2"
    else:
        code = "T1"
    return code, TIER_LABELS_SCORE[code]


def tier_percentile(p: float) -> Tuple[str, str]:
    """百分位 → (T 编号, 类型名)。"""
    v = float(p)
    if v >= 90:
        code = "T1"
    elif v >= 70:
        code = "T2"
    elif v >= 40:
        code = "T3"
    elif v >= 20:
        code = "T4"
    else:
        code = "T5"
    return code, TIER_LABELS_PCT[code]


def detail_pages(pdf_path: Path) -> List[int]:
    """要送去视觉识别的页码（从 1 起）：学习动机页、学习方法与策略页，
    以及学习方法与策略页之后的四页（方法实践总览/明细、策略执行总览/明细，
    中间隔一页成长建议）。由半环图所在页推出，页码整体平移也适用。"""
    doc = fitz.open(str(pdf_path))
    try:
        total = len(doc)
        gauge = [pno + 1 for pno, _r in b3_gauge._gauge_rects(doc)]
    finally:
        doc.close()
    if len(gauge) != 2:
        return []
    motivation, method = gauge
    pages = [motivation, method] + [method + k for k in range(2, 6)]
    return [p for p in pages if p <= total]


def build_prompt() -> str:
    return """你是严谨的数据录入员。下面的图片依次是「新版 B3 核心学习能力报告」中的若干页：
学习动机页、学习方法与策略页，以及其后的「学习方法实践与提升报告」「学习策略执行与优化报告」各自的总览页和明细页。
请只输出一个 JSON 对象，不要任何解释，字段如下：

{
  "motivation_type": "学习动机页上印刷的「当前类型」名称",
  "method_type": "学习方法与策略页上印刷的「当前类型」名称",
  "practice_dims": [{"group": "分组名", "name": "维度名", "score": 数字}],
  "practice_items": [{"dim": "所属维度名", "name": "条目名", "desc": "具体方法与说明", "score": 数字}],
  "exec_dims": [{"stage": "阶段名", "name": "维度名", "score": 数字}],
  "exec_items": [{"stage": "阶段名", "name": "条目名", "desc": "具体方法与说明", "score": 数字}]
}

各字段的来源：
- practice_dims：「学习方法实践与提升报告」总览页的「维度结果一览」。每个维度一条，group 是左侧的大类（如图中粗体分组名），name 是维度名，score 是该维度行末尾格子里印刷的分数。
- practice_items：同一报告明细页的表格，每一行一条；dim 是该行所属的维度，name 是条目名，desc 是「具体方法与说明」列的原文，score 是该行的得分。表格有几行就输出几条，按页面顺序。
- exec_dims：「学习策略执行与优化报告」总览页的「维度结果一览」。stage 是阶段名（如左侧分组），name 是维度名，score 是印刷的分数；该格为空时 score 填 null。
- exec_items：同一报告明细页的表格，每行一条；stage 是该行所属阶段，name 是条目名，desc 是「具体方法与说明」原文，score 是该行得分；空白填 null。

规则：
1. 所有名称、说明文字必须逐字抄自页面，不要改写、不要补全、不要编造。
2. 页面上看不清或没有的文字填 ""，看不清或空白的分数填 null；不要猜测。
3. 分数是 0–10 的数字（可含一位小数），不要带单位；不要根据箭头或颜色推算分数。
4. 不要自己计算平均分；维度分数按页面印刷的数字填写。
5. 只输出 JSON。"""


def _num(x: Any) -> Optional[float]:
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        v = float(x)
    elif isinstance(x, str):
        t = x.strip().rstrip("分")
        if not t:
            return None
        try:
            v = float(t)
        except ValueError:
            return None
    else:
        return None
    return v if math.isfinite(v) else None


def _text(x: Any) -> str:
    if x is None:
        return ""
    return str(x).strip()


def _rows(parsed: Dict[str, Any], key: str, fields: Tuple[str, ...],
          text_keys: Tuple[str, ...]) -> List[Dict[str, Any]]:
    src = parsed.get(key)
    out: List[Dict[str, Any]] = []
    if not isinstance(src, list):
        return out
    for row in src:
        if not isinstance(row, dict):
            continue
        entry: Dict[str, Any] = {}
        for f in fields:
            entry[f] = _num(row.get(f)) if f == "score" else _text(row.get(f))
        out.append(entry)
    return out


def compute_checks(detail: Dict[str, Any]) -> List[str]:
    """D3：维度分与条目平均相差超过 2.0 时给出警告（只用于看板，不进 PDF）。"""
    checks: List[str] = []
    items = detail.get("practice_items") or []
    for dim in detail.get("practice_dims") or []:
        s = dim.get("score")
        if s is None:
            continue
        scores = [it["score"] for it in items
                  if it.get("dim") == dim.get("name") and it.get("score") is not None]
        if not scores:
            continue
        avg = sum(scores) / len(scores)
        if abs(s - avg) > CHECK_TOLERANCE + 1e-9:
            checks.append(
                f"{dim['name']} 维度分 {s:.1f} 与条目平均 {avg:.1f} 相差超过 {CHECK_TOLERANCE:.1f}")
    return checks


def normalise(parsed: Any) -> Dict[str, Any]:
    """把模型返回的 JSON 整理成 b3_detail 契约：类型转换、丢弃未知键、补 format 与 checks。"""
    if not isinstance(parsed, dict):
        parsed = {}
    detail: Dict[str, Any] = {
        "format": "new",
        "motivation_type": _text(parsed.get("motivation_type")),
        "method_type": _text(parsed.get("method_type")),
        "practice_dims": _rows(parsed, "practice_dims",
                               ("group", "name", "score"), ()),
        "practice_items": _rows(parsed, "practice_items",
                                ("dim", "name", "desc", "score"), ()),
        "exec_dims": _rows(parsed, "exec_dims", ("stage", "name", "score"), ()),
        "exec_items": _rows(parsed, "exec_items",
                            ("stage", "name", "desc", "score"), ()),
    }
    detail["checks"] = compute_checks(detail)
    return detail
