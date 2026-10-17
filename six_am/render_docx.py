"""6 A.M. 档案 DOCX 渲染器（six-am-docx-v1）。

输入为 engine.run 产出的 profile dict（实施计划 §3.3），确定性渲染，返回字节流，
不落盘。章节标题即解析锚点，core properties 写 schema 版本便于机器解析。

章节（固定顺序，实施计划 §6.1）：
  1. 标题 + 学生信息表
  2. State 总表
  3. 六维判定详述
  4. 优先级与处理顺序
  5. 支持方案
  6. 追问清单
  7. 数据缺口
  8. 附录：全部命中规则明细
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import rules as R

FONT = "微软雅黑"
DOCX_SCHEMA = "six-am-docx-v1"

_GAP_HINTS = {
    "family_complaint": ("家长诉求（R2.8）", "主诉标签（无兴趣 / 动力不足 / 其他）+ 主诉原文 + 采集来源（家长环节/顾问记录）"),
    "schedule": ("排期（R3.6）", "一周日程概要（每天课程/活动时段数）+ 自由时间估计（小时/周）+ 负荷评级（高/中/低）"),
    "subject_status": ("学科状态（R4.9）", "逐学科条目：学科名 + 学生自评水平 + 实际状态（成绩/教师反馈）+ 偏差方向（自评低于/等于/高于实际）"),
    "standard_task": ("标准化任务结果（R5.7）", "任务形式 + 能否拆出有序步骤（是/否）+ 能否承诺第一步与开始时间（是/否）+ 情绪反应（畏难/烦躁/无所谓/正常）"),
}

_DIM_ROW_ORDER = ["A1", "A2", "A3", "A4", "A5", "A6"]


def build_six_am_docx(profile: Dict[str, Any]) -> bytes:
    """从 profile dict 渲染 6 A.M. 档案 DOCX，返回文件字节。"""
    import io
    from datetime import datetime

    from docx import Document
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    BRAND_RED = RGBColor(0xB3, 0x3A, 0x3A)
    INK = RGBColor(0x14, 0x14, 0x14)
    GRAY = RGBColor(0x8A, 0x8A, 0x8A)
    MUTED = RGBColor(0x64, 0x74, 0x8B)

    def _set_eastasia(target) -> None:
        rPr = target._element.get_or_add_rPr()
        rFonts = rPr.find(qn("w:rFonts"))
        if rFonts is None:
            rFonts = OxmlElement("w:rFonts")
            rPr.append(rFonts)
        rFonts.set(qn("w:eastAsia"), FONT)

    def _run(p, text: str, size: float = 11, color=INK, bold: bool = False):
        r = p.add_run(str(text))
        r.font.name = FONT
        r.font.size = Pt(size)
        r.font.color.rgb = color
        r.bold = bold
        _set_eastasia(r)
        return r

    def _body(text: str, size: float = 11, color=INK, bold: bool = False,
              space_before: float = 2, space_after: float = 2,
              line: Optional[float] = 20, align=None):
        p = doc.add_paragraph()
        if align is not None:
            p.alignment = align
        pf = p.paragraph_format
        pf.space_before = Pt(space_before)
        pf.space_after = Pt(space_after)
        if line:
            pf.line_spacing = Pt(line)
        _run(p, text, size=size, color=color, bold=bold)
        return p

    def _h1(text: str):
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(14)
        pf.space_after = Pt(6)
        _run(p, text, size=15, color=BRAND_RED, bold=True)
        return p

    def _h3(text: str):
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(8)
        pf.space_after = Pt(3)
        _run(p, text, size=12, color=INK, bold=True)
        return p

    def _clear_cell(cell):
        p = cell.paragraphs[0]
        for r in list(p.runs):
            r._element.getparent().remove(r._element)
        return p

    def _cell_text(cell, text: str, size: float = 10, color=INK, bold: bool = False, align=None):
        p = _clear_cell(cell)
        p.paragraph_format.space_before = Pt(1)
        p.paragraph_format.space_after = Pt(1)
        if align is not None:
            p.alignment = align
        _run(p, text, size=size, color=color, bold=bold)
        return p

    def _shade(cell, fill: str) -> None:
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), fill)
        tcPr.append(shd)

    def _table_grid(table, color: str = "D9D9D9") -> None:
        tblPr = table._tbl.tblPr
        borders = OxmlElement("w:tblBorders")
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            el = OxmlElement(f"w:{edge}")
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), "4")
            el.set(qn("w:space"), "0")
            el.set(qn("w:color"), color)
            borders.append(el)
        tblPr.append(borders)

    def _table(rows: List[List[str]], widths: Optional[List[float]] = None,
               header: bool = True) -> None:
        if not rows:
            return
        t = doc.add_table(rows=len(rows), cols=len(rows[0]))
        _table_grid(t)
        for ri, row in enumerate(rows):
            for ci, val in enumerate(row):
                cell = t.cell(ri, ci)
                is_head = header and ri == 0
                _cell_text(cell, val, bold=is_head,
                           color=RGBColor(0xFF, 0xFF, 0xFF) if is_head else INK)
                if is_head:
                    _shade(cell, "B33A3A")
                if widths and ci < len(widths):
                    cell.width = Cm(widths[ci])
        return t

    # ── 工具：effect / evidence 文本化 ────────────────────────
    def _effect_text(eff: Dict[str, Any]) -> str:
        if not eff:
            return ""
        parts: List[str] = []
        if eff.get("state"):
            parts.append(f"state → {eff['state']}")
        if eff.get("subtype"):
            parts.append(f"亚型 → {eff['subtype']}")
        if eff.get("confidence"):
            parts.append(f"confidence → {eff['confidence']}")
        if eff.get("escalate"):
            parts.append(str(eff["escalate"]))
        if eff.get("state_add"):
            parts.append(f"升级 +{eff['state_add']}")
        if eff.get("deescalate"):
            parts.append("降一级")
        if eff.get("flags"):
            parts.append("标记：" + "、".join(str(f) for f in eff["flags"]))
        ops = eff.get("support_ops") or []
        for op in ops:
            delta = op.get("delta", 0)
            sign = "+" if float(delta or 0) >= 0 else ""
            kind = op.get("kind") or ""
            parts.append(f"{op.get('direction', '')} {sign}{delta}{('（' + kind + '）') if kind else ''}")
        return "；".join(parts)

    def _ev_text(e: Dict[str, Any]) -> str:
        if not isinstance(e, dict):
            return str(e)
        if e.get("point"):
            s = f"{e['point']}={e.get('eval_value', '')}"
            if e.get("source"):
                s += f"（{e['source']}）"
            if e.get("bias"):
                s += f"[{e['bias']}]"
            return s
        if e.get("order_value") is not None:
            return f"排序：{e.get('order_value')} 第 {e.get('pos')} 位/前 {e.get('top_n')}"
        if e.get("rule"):
            return f"依赖 {e['rule']} 命中"
        if e.get("evidence"):
            return f"证据 {e['evidence']}={e.get('value')}"
        if e.get("predicate"):
            return f"谓词 {e['predicate']}"
        if e.get("dim"):
            return f"{e.get('dim')} state={e.get('state')}"
        return str(e)

    def _dim_title(dim: str) -> str:
        base = R.DIM_NAMES.get(dim, dim)
        if dim == "A6":
            return f"{dim} {base.split(' ', 1)[-1] if ' ' in base else base}"
        return f"{dim} {base}"

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.2)
        section.bottom_margin = Cm(2.2)
        section.left_margin = Cm(2.2)
        section.right_margin = Cm(2.2)

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = INK
    _set_eastasia(normal)

    student = profile.get("student") or {}
    dims = profile.get("dimensions") or {}
    rv = profile.get("rule_version") or {}
    gaps = profile.get("gaps") or {}
    answers = profile.get("answers") or []

    # ── 1. 标题 + 学生信息表 ─────────────────────────────────
    _body("凭远教育 · 6 A.M. 六维启动档案", size=16, color=BRAND_RED, bold=True,
          space_before=0, space_after=4, line=None)
    _body(student.get("name") or "—", size=20, color=INK, bold=True,
          space_before=0, space_after=10, line=None)
    _table([
        ["学生", student.get("name") or "—", "年级", student.get("grade") or "—"],
        ["报告编号", str(profile.get("report_id") or "—"), "生成时间", profile.get("generated_at") or "—"],
        ["规则版本", (str(rv.get("label")) if rv.get("label") else "default")
         + (f"（id={rv.get('id')}）" if rv.get("id") else ""),
         "档案 Schema", profile.get("schema") or "six-am-profile-v1"],
    ], widths=[2.6, 6.4, 2.6, 6.4], header=False)

    # ── 2. State 总表 ────────────────────────────────────────
    _h1("一、State 总表")
    rows = [["维度", "State", "亚型", "Confidence", "ObstacleScore", "优先级"]]
    priority = {o.get("dim"): o for o in profile.get("obstacles") or []}
    for dim in _DIM_ROW_ORDER:
        rec = dims.get(dim) or {}
        if dim == "A6":
            rows.append([_dim_title(dim), "—", "—", "—", "—", "支持方式选择器"])
            continue
        sc = (rec.get("score") or {}).get("total")
        ob = priority.get(dim) or {}
        rows.append([
            _dim_title(dim),
            rec.get("state") or "—",
            rec.get("subtype_name") or rec.get("subtype") or "—",
            rec.get("confidence") or "—",
            ("%.2f" % sc) if isinstance(sc, (int, float)) else "—",
            ("高优先 · 第 %s 位" % ob.get("sequence")) if ob.get("high_priority")
            else (("第 %s 位" % ob.get("sequence")) if ob.get("sequence") else "—"),
        ])
    _table(rows, widths=[4.2, 2.2, 5.2, 2.6, 2.4, 2.6])

    # ── 3. 六维判定详述 ──────────────────────────────────────
    _h1("二、六维判定详述")
    for dim in _DIM_ROW_ORDER:
        rec = dims.get(dim) or {}
        _h3(_dim_title(dim))
        if dim == "A6":
            sr = rec.get("support_ranking") or {}
            ranked = sr.get("ranked") or []
            summary = "｜".join(f"{i.get('direction')}（{i.get('predicted_effectiveness')}）" for i in ranked)
            _body("支持方向排序：" + (summary or "—"))
        else:
            conclusion = f"结论：{rec.get('state') or '—'}"
            if rec.get("subtype_name"):
                conclusion += f" · {rec['subtype_name']}"
            if rec.get("confidence"):
                conclusion += f" · confidence {rec['confidence']}"
            _body(conclusion, bold=True, color=INK)
            if rec.get("activation_key"):
                _body("启动钥匙：" + str(rec["activation_key"]), color=MUTED)
        traces = rec.get("triggered_rules") or []
        hit_lines = []
        for t in traces:
            line = f"{t.get('id')}（{t.get('title') or ''}）"
            if t.get("refuted"):
                line += "  [已被追问否定 refuted]"
            eff = _effect_text(t.get("effect") or {})
            if eff:
                line += " → " + eff
            for e in (t.get("evidence") or [])[:4]:
                line += "；证据：" + _ev_text(e)
            hit_lines.append(line)
        if hit_lines:
            _body("命中规则与证据：", color=MUTED, space_before=4)
            for line in hit_lines:
                _body("· " + line, size=10)
        for mod in rec.get("cross_mods") or []:
            _body(f"跨维修正 {mod.get('id')}：{mod.get('action')}", size=10, color=MUTED)
        for note in rec.get("notes") or []:
            _body("注：" + str(note), size=10, color=MUTED)

    # ── 4. 优先级与处理顺序 ──────────────────────────────────
    _h1("三、优先级与处理顺序")
    obstacles = profile.get("obstacles") or []
    if obstacles:
        rows = [["处理顺序", "维度", "ObstacleScore", "高优先", "说明"]]
        for o in sorted(obstacles, key=lambda x: (x.get("sequence") or 99)):
            rows.append([
                str(o.get("sequence") or "—"),
                _dim_title(str(o.get("dim"))),
                "%.2f" % float(o.get("score") or 0),
                "是" if o.get("high_priority") else "否",
                o.get("sequence_note") or "—",
            ])
        _table(rows, widths=[2.0, 4.4, 2.6, 1.8, 8.2])
    else:
        _body("无进入 Obstacle 列表的维度（各维均为 Secure 或分数为 0）。")
    if profile.get("sequence_note"):
        _body(profile["sequence_note"], size=10, color=MUTED, space_before=4)

    # ── 5. 支持方案 ──────────────────────────────────────────
    _h1("四、支持方案")
    plan = profile.get("support_plan") or {}
    ranked = plan.get("ranked") or []
    if ranked:
        rows = [["方向", "子机制", "预测有效性", "依据规则", "注意事项"]]
        for item in ranked:
            rows.append([
                str(item.get("direction") or ""),
                "、".join(item.get("sub_mechanisms") or []) or "—",
                str(item.get("predicted_effectiveness") or "—"),
                "、".join(item.get("basis_rules") or []) or "—",
                item.get("cautions") or "—",
            ])
        _table(rows, widths=[3.0, 5.0, 2.4, 3.6, 5.0])
    avoid = plan.get("avoid") or []
    if avoid:
        _body("避免 / 慎用清单：", bold=True, space_before=6)
        for a in avoid:
            _body(f"· {a.get('direction')}（{a.get('kind') or '慎用'}）：{a.get('reason') or ''}"
                  f"  依据：{'、'.join(a.get('basis_rules') or [])}", size=10)

    # ── 6. 追问清单 ──────────────────────────────────────────
    _h1("五、追问清单（按优先级）")
    questions = profile.get("questions") or []
    if questions:
        rows = [["#", "怎么问（人话版）", "验证目标", "关联规则"]]
        for q in questions:
            rows.append([
                str(q.get("priority") or ""),
                str(q.get("ask") or ""),
                str(q.get("id") or ""),
                "、".join(q.get("basis_rules") or q.get("verify") or []) or "—",
            ])
        _table(rows, widths=[1.2, 9.6, 2.6, 5.6])
    else:
        _body("当前无需要追问的维度（各维均低于 Watch）。")
    if answers:
        _body("已录入追问答案：", bold=True, space_before=6)
        for a in answers:
            mark = {"confirm": "证实", "partial": "部分证实", "deny": "否定"}.get(
                str(a.get("result")), str(a.get("result") or ""))
            _body(f"· {a.get('q')} [{mark}] {a.get('text') or ''}", size=10)

    # ── 7. 数据缺口 ──────────────────────────────────────────
    _h1("六、数据缺口与补录指引")
    missing = [k for k in _GAP_HINTS if not gaps.get(k)]
    if missing:
        for k in missing:
            label, hint = _GAP_HINTS[k]
            _body(f"· {label}：尚未采集。补录：{hint}", size=10)
    else:
        _body("四类结构化数据（家长诉求 / 排期 / 学科状态 / 标准化任务）均已采集。", size=10)
    collected = [k for k in _GAP_HINTS if gaps.get(k)]
    if collected:
        _body("已采集字段：", color=MUTED, space_before=4)
        for k in collected:
            _body(f"· {_GAP_HINTS[k][0]}：{gaps.get(k)}", size=9.5, color=MUTED)

    # ── 8. 附录：全部命中规则明细 ────────────────────────────
    _h1("七、附录：命中规则明细（审计）")
    for dim in _DIM_ROW_ORDER:
        rec = dims.get(dim) or {}
        traces = rec.get("triggered_rules") or []
        if not traces:
            continue
        _h3(_dim_title(dim))
        for t in traces:
            flags = []
            if t.get("contributing") is False:
                flags.append("仅记录不产出")
            if t.get("refuted"):
                flags.append("refuted")
            suffix = f"（{'、'.join(flags)}）" if flags else ""
            _body(f"{t.get('id')} {t.get('title') or ''}{suffix}：{_effect_text(t.get('effect') or {}) or '无效果产出'}",
                  size=9.5)

    # ── 页脚 + core properties ───────────────────────────────
    doc.add_paragraph()
    fp = doc.add_paragraph()
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _run(fp, "— 凭远教育 · 6 A.M. 六维启动模型 —", size=9, color=GRAY)

    cp = doc.core_properties
    cp.title = f"6AM 六维启动档案 - {student.get('name') or ''}"
    cp.subject = DOCX_SCHEMA
    cp.keywords = f"{DOCX_SCHEMA};{profile.get('schema') or 'six-am-profile-v1'}"
    cp.comments = "6 A.M. 六维启动模型档案（v0.2），章节标题为解析锚点。"

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()