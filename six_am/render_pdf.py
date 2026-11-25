"""6 A.M. 档案 PDF 渲染器（six-am-pdf-v1）。

输入为落库的 profile dict（与 ``six_am.render_docx`` 同一数据源），章节顺序、
字段口径与 DOCX 保持一致，展示层统一走 ``presentation.build_view_model``。
中文使用 reportlab 内置的 STSong-Light CID 字体，不依赖部署机系统字体。

纯函数层：不导入 Flask、不访问数据库；返回字节流，不落盘。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from . import presentation
from . import rules as R
from .render_docx import _GAP_HINTS

PDF_SCHEMA = "six-am-pdf-v1"
BRAND_RED = "#B33A3A"
INK = "#141414"
MUTED = "#64748B"
GRAY = "#8A8A8A"
FONT = "STSong-Light"


def _dim_title(dim: str) -> str:
    base = R.DIM_NAMES.get(dim, dim)
    if dim == "A6":
        return "%s %s" % (dim, base.split(" ", 1)[-1] if " " in base else base)
    return "%s %s" % (dim, base)


def _text(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return escape(str(value))


def _list_items(items: Any) -> List[str]:
    return [str(x).strip() for x in (items or []) if str(x).strip()]


def _audit_ev(entry: Any) -> str:
    if not isinstance(entry, dict):
        return str(entry)
    if entry.get("point"):
        text = "%s=%s" % (entry.get("point"), entry.get("eval_value"))
        if entry.get("source"):
            text += "（%s）" % entry["source"]
        return text
    if entry.get("order_value") is not None:
        return "%s 第 %s 位/前 %s" % (entry.get("order_value"), entry.get("pos"), entry.get("top_n"))
    if entry.get("rule"):
        return "依赖 %s 命中" % entry["rule"]
    if entry.get("evidence"):
        return "证据 %s" % entry["evidence"]
    if entry.get("predicate"):
        return "谓词 %s" % entry["predicate"]
    if entry.get("dim"):
        return "%s state=%s" % (entry.get("dim"), entry.get("state"))
    return ""


def build_six_am_pdf(profile: Dict[str, Any], *, student: Optional[Dict[str, Any]] = None,
                     version: Optional[int] = None) -> bytes:
    """从 profile dict 渲染 6 A.M. 档案 PDF，返回文件字节。"""
    import io

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas as pdf_canvas
    from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    pdfmetrics.registerFont(UnicodeCIDFont(FONT))

    profile = profile or {}
    vm = presentation.build_view_model(profile)
    summary = vm.get("summary") or {}
    cards = vm.get("cards") or []
    stu = student or profile.get("student") or {}
    rv = profile.get("rule_version") or {}
    gaps = profile.get("gaps") or {}
    questions = profile.get("questions") or []
    answers = profile.get("answers") or []
    file_version = version if version is not None else profile.get("version")

    def style(name: str, size: float = 10.5, leading: float = 16, color: str = INK,
              bold: bool = False, space_before: float = 0, space_after: float = 3):
        return ParagraphStyle(
            name, fontName=FONT, fontSize=size, leading=leading,
            textColor=colors.HexColor(color),
            spaceBefore=space_before, spaceAfter=space_after,
            wordWrap="CJK", bold=bold,
        )

    s_title = style("title", 16, 24, BRAND_RED, space_after=4)
    s_name = style("name", 20, 28, INK, space_after=10)
    s_h1 = style("h1", 14, 21, BRAND_RED, space_before=14, space_after=6)
    s_h3 = style("h3", 11.5, 18, INK, space_before=9, space_after=3)
    s_body = style("body", 10.5, 16)
    s_field = style("field", 10.5, 16, space_after=1)
    s_small = style("small", 9.5, 14, MUTED, space_after=1)
    s_footer = style("footer", 8.5, 12, GRAY, space_after=0)
    s_cell = style("cell", 9.5, 14)
    s_cell_head = style("cell_head", 9.5, 14, "#FFFFFF")

    story: List[Any] = []

    # ── 1. 标题 + 学生信息表 ─────────────────────────────────
    story.append(Paragraph("凭远教育 · 6 A.M. 六维启动档案", s_title))
    story.append(Paragraph(_text(stu.get("name")), s_name))
    rule_label = str(rv.get("label") or "default")
    if rv.get("id"):
        rule_label += "（id=%s）" % rv["id"]
    version_label = ("v%s" % file_version) if file_version else "—"
    if profile.get("schema"):
        version_label += "（%s）" % profile["schema"]
    info = [
        [Paragraph("学生", s_cell), Paragraph(_text(stu.get("name")), s_cell),
         Paragraph("年级", s_cell), Paragraph(_text(stu.get("grade")), s_cell)],
        [Paragraph("报告编号", s_cell), Paragraph(_text(profile.get("report_id")), s_cell),
         Paragraph("生成时间", s_cell), Paragraph(_text(profile.get("generated_at")), s_cell)],
        [Paragraph("规则版本", s_cell), Paragraph(escape(rule_label), s_cell),
         Paragraph("档案版本", s_cell), Paragraph(escape(version_label), s_cell)],
    ]
    info_tbl = Table(info, colWidths=[2.6 * cm, 6.0 * cm, 2.6 * cm, 5.8 * cm])
    info_tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9D9D9")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F4F4F4")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#F4F4F4")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(info_tbl)

    # ── 2. 一、紧凑摘要 ──────────────────────────────────────
    story.append(Paragraph("一、紧凑摘要", s_h1))
    primary = summary.get("primary_obstacle") or {}
    if primary.get("dim"):
        head = _dim_title(str(primary["dim"]))
        if primary.get("state"):
            head += " · " + str(presentation.STATE_LABELS.get(primary["state"], primary["state"]))
        if primary.get("priority_reason"):
            head += "（%s）" % primary["priority_reason"]
        story.append(Paragraph("主要障碍：" + escape(head), s_field))
    else:
        story.append(Paragraph("主要障碍：暂无（各维均在 Watch 以下）。", s_field))
    order = summary.get("priority_order") or []
    if order:
        story.append(Paragraph("处理顺序：" + escape(" → ".join(_dim_title(str(d)) for d in order)), s_field))
    deferred = summary.get("deferred") or []
    if deferred:
        story.append(Paragraph("本轮暂缓（长期目标）：" + escape("；".join(
            "%s（%s）" % (_dim_title(str(d.get("dim"))), d.get("reason") or "")
            for d in deferred if isinstance(d, dict))), s_field))
    refuted = summary.get("refuted") or []
    story.append(Paragraph(
        "待确认问题：%s 条；被排除规则：%s 条" % (summary.get("open_question_count") or 0, len(refuted)),
        s_field))
    if summary.get("sequence_note"):
        story.append(Paragraph(escape(str(summary["sequence_note"])), s_small))

    # ── 3. 二、六维行动卡 ────────────────────────────────────
    story.append(Paragraph("二、六维行动卡（A1–A6）", s_h1))
    for card in cards:
        head = "%s %s · %s" % (card.get("dim"), card.get("title"), card.get("state_label"))
        if card.get("manually_edited"):
            head += "（人工修订）"
        block: List[Any] = [Paragraph(escape(head), s_h3)]
        block.append(Paragraph("当前判断：" + _text(card.get("headline")), s_body))
        block.append(Paragraph("证据状态：" + _text(card.get("evidence_label")), s_body))
        for label, key in (("Y4 事实", "y4_facts"), ("初筛假设", "hypotheses"),
                           ("补充证据", "confirmed_evidence")):
            vals = _list_items(card.get(key))
            block.append(Paragraph(escape(label + "：") + ("—" if not vals else "　".join(
                escape("· " + v) for v in vals)), s_body))
        if card.get("priority_label"):
            if card.get("deferred"):
                prio = "长期目标"
            elif card.get("priority_rank") is not None:
                prio = "优先处理 · 第 %s 位" % card["priority_rank"]
            else:
                prio = str(card["priority_label"])
            if card.get("priority_reason") and card.get("priority_reason") != prio:
                prio += "（%s）" % card["priority_reason"]
            block.append(Paragraph("处理优先级：" + escape(prio), s_body))
        for label, key in (("下一步", "next_actions"), ("避免事项", "avoid_actions")):
            vals = _list_items(card.get(key))
            block.append(Paragraph(escape(label + "：") + ("—" if not vals else "　".join(
                escape("· " + v) for v in vals)), s_body))
        asks = _list_items([q.get("ask") for q in card.get("questions") or [] if q.get("ask")])
        block.append(Paragraph("待确认问题：" + ("—" if not asks else "　".join(
            escape("· " + v) for v in asks)), s_body))
        story.append(KeepTogether(block))

    # ── 4. 三、待确认问题与数据缺口 ──────────────────────────
    story.append(Paragraph("三、待确认问题与数据缺口", s_h1))
    if questions:
        rows = [[Paragraph("优先", s_cell_head), Paragraph("怎么问（人话版）", s_cell_head),
                 Paragraph("验证目标", s_cell_head), Paragraph("关联规则", s_cell_head)]]
        for q in questions:
            rows.append([
                Paragraph(_text(q.get("priority")), s_cell),
                Paragraph(_text(q.get("ask")), s_cell),
                Paragraph(_text(q.get("id")), s_cell),
                Paragraph(escape("、".join(q.get("basis_rules") or q.get("verify") or []) or "—"), s_cell),
            ])
        q_tbl = Table(rows, colWidths=[1.2 * cm, 9.2 * cm, 2.6 * cm, 4.0 * cm], repeatRows=1)
        q_tbl.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9D9D9")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BRAND_RED)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(q_tbl)
    else:
        story.append(Paragraph("当前无需要追问的维度（各维均低于 Watch）。", s_body))
    if answers:
        story.append(Paragraph("已录入追问答案：", s_field))
        for a in answers:
            mark = {"confirm": "证实", "partial": "部分证实", "deny": "否定"}.get(
                str(a.get("result")), str(a.get("result") or ""))
            story.append(Paragraph(escape("· %s [%s] %s" % (a.get("q"), mark, a.get("text") or "")), s_small))
    missing = [k for k in _GAP_HINTS if not gaps.get(k)]
    if missing:
        story.append(Paragraph("数据缺口与补录指引：", s_field))
        for key in missing:
            label, hint = _GAP_HINTS[key]
            story.append(Paragraph(escape("· %s：尚未采集。补录：%s" % (label, hint)), s_small))
    else:
        story.append(Paragraph("四类结构化数据（家长诉求 / 排期 / 学科状态 / 标准化任务）均已采集。", s_small))
    collected = [k for k in _GAP_HINTS if gaps.get(k)]
    if collected:
        story.append(Paragraph("已采集字段：", s_small))
        for key in collected:
            label = _GAP_HINTS[key][0]
            raw = gaps.get(key)
            value = (raw.get("text") or raw.get("value") or "") if isinstance(raw, dict) else raw
            if value:
                story.append(Paragraph(escape("· %s：%s" % (label, value)), s_small))

    # ── 5. 四、附录：规则审计 ────────────────────────────────
    story.append(Paragraph("四、附录：规则审计", s_h1))
    has_audit = False
    for card in cards:
        audit = card.get("audit") or {}
        traces = audit.get("triggered_rules") or []
        mods = audit.get("cross_mods") or []
        flags = audit.get("flags") or []
        notes = audit.get("notes") or []
        refuted_rules = audit.get("refuted_rules") or []
        if not (traces or mods or flags or notes or refuted_rules):
            continue
        block = [Paragraph(escape("%s %s" % (card.get("dim"), card.get("title"))), s_h3)]
        for trace in traces:
            if not isinstance(trace, dict):
                continue
            line = "%s %s" % (trace.get("id"), trace.get("title") or "")
            marks = []
            if trace.get("contributing") is False:
                marks.append("仅记录不产出")
            if trace.get("refuted"):
                marks.append("refuted")
            if marks:
                line += "（%s）" % "、".join(marks)
            evs = [s for s in (_audit_ev(e) for e in (trace.get("evidence") or [])) if s]
            if evs:
                line += "：" + "；".join(evs)
            block.append(Paragraph(escape("· " + line), s_small))
        for mod in mods:
            block.append(Paragraph(escape("· 跨维修正 %s：%s" % (mod.get("id"), mod.get("action") or "")), s_small))
        for flag in flags:
            block.append(Paragraph(escape("· 标记：%s" % flag), s_small))
        for note in notes:
            block.append(Paragraph(escape("· 注：%s" % note), s_small))
        for ref in refuted_rules:
            block.append(Paragraph(escape("· %s %s %s（由追问 %s 否定）" % (
                ref.get("rule"), ref.get("title"), ref.get("label"), ref.get("refuted_by"))), s_small))
        story.append(KeepTogether(block))
        has_audit = True
    if not has_audit:
        story.append(Paragraph("本次档案未触发可审计规则。", s_small))

    story.append(Spacer(1, 10))
    story.append(Paragraph("— 凭远教育 · 6 A.M. 六维启动模型 —", ParagraphStyle(
        "foot", parent=s_footer, alignment=TA_CENTER)))

    class _NumberedCanvas(pdf_canvas.Canvas):
        """页脚：文档名 / 第 X 页 共 Y 页（两遍绘制，页码稳定）。"""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_pages = []

        def showPage(self):
            self._saved_pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved_pages)
            for state in self._saved_pages:
                self.__dict__.update(state)
                self._draw_footer(total)
                super().showPage()
            super().save()

        def _draw_footer(self, total: int) -> None:
            self.setFont(FONT, 8)
            self.setFillColor(colors.HexColor(GRAY))
            self.drawString(2 * cm, 1.1 * cm, "凭远教育 · 6 A.M. 六维启动档案")
            self.drawRightString(A4[0] - 2 * cm, 1.1 * cm, "第 %s 页 / 共 %s 页" % (self._pageNumber, total))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
        title="6AM 六维启动档案 - %s" % (stu.get("name") or ""),
        subject=PDF_SCHEMA,
        author="凭远教育",
        invariant=1,
    )
    doc.build(story, canvasmaker=_NumberedCanvas)
    return buf.getvalue()
