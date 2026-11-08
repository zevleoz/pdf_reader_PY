#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
new_iteration/render_y4_2.py — Y4-2 学习力报告（只用 B3 数据）

  build_context(raw)        纯函数：报告快照 -> 模板上下文（不读写任何文件）
  render_html(raw, out_html) 渲染 report_y4_2.html
  render_pdf(raw, out_pdf)   HTML -> Chrome headless 打印为 PDF
  has_b3(raw)               该快照是否有 B3 数据（可下载 Y4-2）

不读、不写 data/report_data.json。文字只来自 B3 印出的标签与数据值，不含 AI 文字。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import render_v2  # noqa: E402

TEMPLATE_NAME = "report_y4_2.html"

# B3 印出的五色 / 分档名
TIER_COLORS = {"T1": "#5A9E5F", "T2": "#5CA0B0", "T3": "#F2B630", "T4": "#F07C2C", "T5": "#E0403A"}
PCT_LABELS = {"T1": "优势表现型", "T2": "良好发展型", "T3": "一般发展型", "T4": "需要支持型", "T5": "重点支持型"}
FREQ_LABELS = {"T1": "高频使用", "T2": "较常使用", "T3": "有时使用", "T4": "较少使用", "T5": "从未使用"}
# 百分位分档（左到右 T5..T1）：区间 [lo, hi)
PCT_SEGMENTS = [("T5", 0, 20, "<20"), ("T4", 20, 40, "20–39"), ("T3", 40, 70, "40–69"),
                ("T2", 70, 90, "70–89"), ("T1", 90, 100, "≥90")]
# 0–10 分档（左到右 T5..T1）
SCORE_SEGMENTS = [("T5", 0, 3, "1–2"), ("T4", 3, 5, "3–4"), ("T3", 5, 7, "5–6"),
                  ("T2", 7, 9, "7–8"), ("T1", 9, 10, "9–10")]

EF_CODES = (("063", "抑制控制"), ("064", "工作记忆"), ("065", "认知灵活性"))
MOTIVATION_QUADS = {"tl": "内驱型", "tr": "双高型", "bl": "低动机型", "br": "外驱型"}
METHOD_QUADS = {"tl": "深度理解型", "tr": "双高整合型", "bl": "低策略型", "br": "表层任务型"}

# 分页预算（mm）：一页可放的明细高度
ROW_H, ROW_H_WRAP, GROUP_H = 7.4, 10.8, 9.0
PAGE_CAP_MM = 205.0
INLINE_CAP_MM = 70.0
STAGE_LETTERS = ("P", "D", "C", "A")


# ---------------------------------------------------------------- 工具

def _num(v) -> Optional[float]:
    """数值或 None（空串/None/非数字/非有限 -> None）。"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _fmt(v: Optional[float], one: bool = True) -> str:
    """0–10 分数保留一位小数；百分位（one=False）取整显示。"""
    if v is None:
        return "—"
    return f"{v:.1f}" if one else render_v2.fnum(v)


def tier_score(score: float) -> str:
    if score < 3:
        return "T5"
    if score < 5:
        return "T4"
    if score < 7:
        return "T3"
    if score < 9:
        return "T2"
    return "T1"


def tier_percentile(p: float) -> str:
    if p >= 90:
        return "T1"
    if p >= 70:
        return "T2"
    if p >= 40:
        return "T3"
    if p >= 20:
        return "T4"
    return "T5"


def _schema_values(raw: dict) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for it in (raw.get("schema_124") or []):
        if isinstance(it, dict) and it.get("code") is not None:
            out[str(it["code"])] = it.get("value")
    return out


def has_b3(raw: Optional[dict]) -> bool:
    """有 B3：pdf_titles 含 B3，或 063–071 / 134 / 135 任一非空。"""
    if not isinstance(raw, dict):
        return False
    if "B3" in (raw.get("pdf_titles") or []):
        return True
    vals = _schema_values(raw)
    codes = [f"{n:03d}" for n in range(63, 72)] + ["134", "135"]
    return any(str(vals.get(c) if vals.get(c) is not None else "").strip() for c in codes)


def _segments(kind: str) -> List[dict]:
    segs = PCT_SEGMENTS if kind == "pct" else SCORE_SEGMENTS
    labels = PCT_LABELS if kind == "pct" else FREQ_LABELS
    return [{"code": c, "color": TIER_COLORS[c], "width": (hi - lo) / (100.0 if kind == "pct" else 10.0) * 100, "range": rng, "label": labels[c]}
            for c, lo, hi, rng in segs]


def _marker_left(v: float, kind: str) -> float:
    top = 100.0 if kind == "pct" else 10.0
    return max(0.0, min(100.0, v / top * 100.0))


# ---------------------------------------------------------------- 各页数据

def _scale_card(name: str, score: Optional[float]) -> Optional[dict]:
    if score is None:
        return None
    t = tier_score(score)
    return {"name": name, "txt": _fmt(score), "tier": t, "color": TIER_COLORS[t],
            "label": FREQ_LABELS[t], "left": _marker_left(score, "score")}


def _quadrant(title: str, ptype: str, names: Dict[str, str], axis_x: str, axis_y: str,
              me: tuple, peer: tuple, desc: str) -> dict:
    cells = [{"pos": k, "name": names[k], "on": names[k] == ptype} for k in ("tl", "tr", "bl", "br")]

    def dot(xy):
        x, y = xy
        if x is None or y is None:
            return None
        cx = max(0.0, min(10.0, x))
        cy = max(0.0, min(10.0, y))
        return {"left": cx * 10, "bottom": cy * 10, "x": _fmt(x), "y": _fmt(y)}

    return {
        "title": title, "type": ptype, "cells": cells, "axis_x": axis_x, "axis_y": axis_y,
        "me": dot(me),
        # D6：两个均值都有才画同龄点
        "peer": dot(peer) if (peer[0] is not None and peer[1] is not None) else None,
        "desc": desc,
    }


def _cells(score: Optional[float]) -> List[float]:
    """10 格，每格 1 分；返回每格填充百分比。"""
    s = 0.0 if score is None else max(0.0, min(10.0, score))
    return [round(max(0.0, min(1.0, s - i)) * 100, 1) for i in range(10)]


def _item_row(name: str, desc: str, score: Optional[float]) -> dict:
    t = tier_score(score) if score is not None else ""
    return {"name": name, "desc": desc, "txt": _fmt(score), "cells": _cells(score),
            "color": TIER_COLORS.get(t, "#C9C9C4"), "word": FREQ_LABELS.get(t, "—"),
            "h": ROW_H_WRAP if len(desc) > 34 else ROW_H}


def _group_items(entries: List[dict], key: str) -> List[dict]:
    """按 key（dim / stage）分组，保持首次出现的顺序。"""
    order: List[str] = []
    groups: Dict[str, List[dict]] = {}
    for e in entries:
        g = str(e.get(key) or "")
        if g not in groups:
            groups[g] = []
            order.append(g)
        groups[g].append(_item_row(str(e.get("name") or ""), str(e.get("desc") or ""),
                                   _num(e.get("score"))))
    return [{"name": g, "rows": groups[g]} for g in order]


def _paginate(groups: List[dict], cap: float = PAGE_CAP_MM, first_cap: Optional[float] = None) -> List[List[dict]]:
    """把分组按高度预算切页；组内可跨页（续页带组名）。"""
    pages: List[List[dict]] = []
    cur: List[dict] = []
    used = 0.0
    limit = first_cap if first_cap is not None else cap
    for g in groups:
        part: List[dict] = []
        used_g = GROUP_H
        if used + used_g + g["rows"][0]["h"] > limit and cur:
            pages.append(cur)
            cur, used, limit = [], 0.0, cap
        for it in g["rows"]:
            need = it["h"] + (GROUP_H if not part else 0)
            if used + need > limit and (cur or part):
                if part:
                    cur.append({"name": g["name"], "rows": part})
                pages.append(cur)
                cur, part, used, limit = [], [], 0.0, cap
                need = it["h"] + GROUP_H
            used += need
            part.append(it)
        if part:
            cur.append({"name": g["name"], "rows": part})
    if cur:
        pages.append(cur)
    return pages


def _bar_row(name: str, score: Optional[float]) -> dict:
    if score is None:
        return {"name": name, "txt": "—", "pct": 0, "color": "#C9C9C4"}
    t = tier_score(score)
    return {"name": name, "txt": _fmt(score), "pct": max(0.0, min(100.0, score * 10)),
            "color": TIER_COLORS[t]}


# ---------------------------------------------------------------- 上下文

def build_context(raw: dict) -> dict:
    raw = raw or {}
    student = dict(raw.get("student") or {})
    vals = _schema_values(raw)
    b3 = raw.get("b3_detail") if isinstance(raw.get("b3_detail"), dict) else {}

    # P1 / P2：执行功能百分位
    ef = []
    for code, name in EF_CODES:
        p = _num(vals.get(code))
        if p is None:
            continue
        t = tier_percentile(p)
        ef.append({"name": name, "txt": _fmt(p, False), "tier": t, "color": TIER_COLORS[t],
                   "label": PCT_LABELS[t], "left": _marker_left(p, "pct")})

    m_type = str(b3.get("motivation_type") or "").strip()
    q_type = str(b3.get("method_type") or "").strip()
    m_scores = (_num(vals.get("066")), _num(vals.get("067")))   # 深层, 表面
    q_scores = (_num(vals.get("069")), _num(vals.get("070")))

    def type_card(ptype, scores):
        if not ptype:
            return None
        deep, surf = scores
        sub = " · ".join(s for s in (
            f"深层 {_fmt(deep)}" if deep is not None else "",
            f"表面 {_fmt(surf)}" if surf is not None else "") if s)
        return {"type": ptype, "sub": sub}

    motivation = type_card(m_type, m_scores)
    method = type_card(q_type, q_scores)
    s134 = _scale_card("学习方法实践", _num(vals.get("134")))
    s135 = _scale_card("学习策略执行", _num(vals.get("135")))

    # P3：类型定位
    quads = []
    if m_type:
        quads.append(_quadrant(
            "学习动机", m_type, MOTIVATION_QUADS, "表面动机", "深层动机",
            me=(m_scores[1], m_scores[0]),
            peer=(_num(vals.get("129")), _num(vals.get("128"))),
            desc=str(b3.get("motivation_desc") or "").strip()))
    if q_type:
        quads.append(_quadrant(
            "学习方法", q_type, METHOD_QUADS, "表面方法", "深层方法",
            me=(q_scores[1], q_scores[0]),
            peer=(_num(vals.get("132")), _num(vals.get("131"))),
            desc=str(b3.get("method_desc") or "").strip()))
    quads_peer = any(q["peer"] for q in quads)

    # P4：学习方法实践
    p_dims = [d for d in (b3.get("practice_dims") or []) if isinstance(d, dict)]
    practice_groups: List[dict] = []
    for d in p_dims:
        g = str(d.get("group") or "")
        if not practice_groups or practice_groups[-1]["name"] != g:
            practice_groups.append({"name": g, "dims": []})
        practice_groups[-1]["dims"].append(_bar_row(str(d.get("name") or ""), _num(d.get("score"))))
    loop = " → ".join(g["name"] for g in practice_groups if g["name"])

    # P5：方法明细
    p_items = [i for i in (b3.get("practice_items") or []) if isinstance(i, dict)]
    practice_pages = _paginate(_group_items(p_items, "dim"))

    # P6：策略执行
    e_dims = [d for d in (b3.get("exec_dims") or []) if isinstance(d, dict)]
    e_items = [i for i in (b3.get("exec_items") or []) if isinstance(i, dict)]
    stage_order: List[str] = []
    stage_dims: Dict[str, List[dict]] = {}
    for d in e_dims:
        s = str(d.get("stage") or "")
        if s not in stage_dims:
            stage_dims[s] = []
            stage_order.append(s)
        stage_dims[s].append(_bar_row(str(d.get("name") or ""), _num(d.get("score"))))
    stages = []
    for i, s in enumerate(stage_order):
        stages.append({"no": i + 1, "name": s, "dims": stage_dims[s],
                       "letter": STAGE_LETTERS[i] if len(stage_order) == 4 else ""})
    if len(stages) == 4:  # 顺时针：①② / ④③
        stages = [stages[0], stages[1], stages[3], stages[2]]

    exec_groups = _group_items(e_items, "stage")
    exec_cost = sum(GROUP_H + sum(it["h"] for it in g["rows"]) for g in exec_groups)
    exec_inline = bool(exec_groups) and exec_cost <= INLINE_CAP_MM
    exec_pages = [] if exec_inline else _paginate(exec_groups)

    pages: List[str] = []
    if ef or motivation or method or s134 or s135:
        pages.append("P1")
    if ef:
        pages.append("P2")
    if quads:
        pages.append("P3")
    if p_dims:
        pages.append("P4")
    for i in range(len(practice_pages)):
        pages.append("P5" if i == 0 else f"P5{chr(97 + i)}")
    has_p6 = bool(stages or exec_groups)
    if has_p6:
        pages.append("P6")
        for i in range(len(exec_pages)):
            pages.append("P6b" if i == 0 else f"P6{chr(98 + i)}")

    return {
        "student": {
            "name": student.get("name") or "",
            "grade": student.get("grade") or "",
            "test_date": student.get("test_date") or "",
        },
        "ef": ef, "ef_segments": _segments("pct"),
        "score_segments": _segments("score"),
        "motivation": motivation, "method": method, "s134": s134, "s135": s135,
        "quads": quads, "quads_peer": quads_peer,
        "practice_groups": practice_groups, "loop_text": loop,
        "p5_title_en": f"{len(p_items)} Methods in Detail",
        "practice_pages": practice_pages,
        "stages": stages, "exec_inline_groups": exec_groups if exec_inline else [],
        "exec_pages": exec_pages,
        "exec_title_en": f"{len(e_items)} Practices in Detail",
        "has_p6": has_p6,
        "pages": pages,
        "tier_colors": TIER_COLORS,
    }


# ---------------------------------------------------------------- 渲染

def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(HERE)),
                       autoescape=select_autoescape(default=True, default_for_string=True))


def render_html(raw: dict, out_html) -> str:
    """渲染 HTML；out_html 同目录下放一份 branding/。"""
    out = Path(out_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    dst = out.parent / "branding"
    dst.mkdir(parents=True, exist_ok=True)
    src = HERE / "branding"
    if src.is_dir():
        for asset in src.iterdir():
            target = dst / asset.name
            if asset.is_file() and not target.exists():
                shutil.copy2(str(asset), str(target))
    html = _env().get_template(TEMPLATE_NAME).render(**build_context(raw))
    out.write_text(html, encoding="utf-8")
    return html


def render_pdf(raw: dict, out_pdf) -> Path:
    """渲染为 PDF（Chrome headless，与 render_v2.main 相同的打印参数）。"""
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    if out_pdf.exists():
        out_pdf.unlink()
    with tempfile.TemporaryDirectory(prefix="y4_2_") as tmp:
        html_path = Path(tmp) / "report_y4_2.html"
        render_html(raw, html_path)
        args = [render_v2.find_chrome(), "--headless=new", "--disable-gpu",
                f"--print-to-pdf={out_pdf}", "--no-pdf-header-footer",
                f"file://{html_path}"]
        result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if not out_pdf.exists():
        raise RuntimeError(f"Chrome PDF 生成失败: {result.stderr[:500]}")
    return out_pdf
