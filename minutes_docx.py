"""McKinsey 风格会议纪要 DOCX 渲染器（minutes-v1）。

输入为 minutes_schema.validate_minutes 归一后的结构化 dict，确定性渲染 DOCX。
DOCX 本身即机器可读交付物：固定 H1 章节标题、会议信息表、行动项表、
core properties 均为下游 python-docx 解析锚点，规范见 docs/minutes_docx_spec.md。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from minutes_schema import SCHEMA_VERSION

FONT = "微软雅黑"


def build_minutes_docx(d: dict) -> bytes:
    """从结构化数据渲染 McKinsey 风格 DOCX，返回文件字节。"""
    import io
    import re
    from datetime import datetime

    from docx import Document
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    BRAND_RED = "B33A3A"
    BRAND_RED_RGB = RGBColor(0xB3, 0x3A, 0x3A)
    INK = RGBColor(0x14, 0x14, 0x14)
    GRAY = RGBColor(0x8A, 0x8A, 0x8A)
    WHITE = RGBColor(0xFF, 0xFF, 0xFF)

    def clean(s: Any) -> str:
        """兜底剥离 Markdown 加粗符号。"""
        return re.sub(r"\*\*(.+?)\*\*", r"\1", str(s or ""))

    def _set_eastasia(target) -> None:
        rPr = target._element.get_or_add_rPr()
        rFonts = rPr.find(qn("w:rFonts"))
        if rFonts is None:
            rFonts = OxmlElement("w:rFonts")
            rPr.append(rFonts)
        rFonts.set(qn("w:eastAsia"), FONT)

    def _run(p, text: str, size: float = 11, color=INK, bold: bool = False):
        r = p.add_run(text)
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
        _run(p, text, size=16, color=BRAND_RED_RGB, bold=True)
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

    def _cell_text(cell, text: str, size: float = 11, color=INK,
                   bold: bool = False, align=None):
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

    def _table_no_borders(table) -> None:
        tblPr = table._tbl.tblPr
        borders = OxmlElement("w:tblBorders")
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            el = OxmlElement(f"w:{edge}")
            el.set(qn("w:val"), "none")
            el.set(qn("w:sz"), "0")
            el.set(qn("w:space"), "0")
            borders.append(el)
        tblPr.append(borders)

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

    def _cell_borders(cell, edges: Dict[str, Optional[Any]]) -> None:
        """edges: edge -> (sz_eighths, hex) 或 None(无边框)。"""
        tcPr = cell._tc.get_or_add_tcPr()
        tcBorders = tcPr.find(qn("w:tcBorders"))
        if tcBorders is None:
            tcBorders = OxmlElement("w:tcBorders")
            tcPr.append(tcBorders)
        for edge in ("top", "left", "bottom", "right"):
            el = tcBorders.find(qn(f"w:{edge}"))
            if el is None:
                el = OxmlElement(f"w:{edge}")
                tcBorders.append(el)
            spec = edges.get(edge)
            if spec is None:
                el.set(qn("w:val"), "none")
                el.set(qn("w:sz"), "0")
                el.set(qn("w:space"), "0")
            else:
                sz, color = spec
                el.set(qn("w:val"), "single")
                el.set(qn("w:sz"), str(sz))
                el.set(qn("w:space"), "0")
                el.set(qn("w:color"), color)

    def _sub(title: str, value: Any) -> None:
        v = clean(value)
        if not v:
            return
        _h3(title)
        for para in v.split("\n"):
            para = para.strip()
            if para:
                _body(para)

    # ------------------------------------------------------------------
    # Document setup
    # ------------------------------------------------------------------
    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.2)
        section.bottom_margin = Cm(2.2)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(11)
    normal.font.color.rgb = INK
    _set_eastasia(normal)

    meta = d.get("meeting_meta") or {}

    # ---- Header: brand line + student name title ----
    _body("凭远教育 · Y4 解读会会议纪要", size=16, color=BRAND_RED_RGB, bold=True,
          space_before=0, space_after=4, line=None, align=WD_ALIGN_PARAGRAPH.LEFT)
    name = meta.get("student_name") or "—"
    _body(name, size=20, color=INK, bold=True,
          space_before=0, space_after=10, line=None, align=WD_ALIGN_PARAGRAPH.LEFT)

    # ---- Meeting info table (machine anchor #1) ----
    gen_date = datetime.now().strftime("%Y-%m-%d")
    info_rows = [
        ("学生", meta.get("student_name") or ""),
        ("年级", meta.get("grade") or ""),
        ("性别", meta.get("gender") or ""),
        ("会议日期", meta.get("meeting_date") or ""),
        ("解读老师", meta.get("advisor") or ""),
        ("参会人", meta.get("attendees") or ""),
        ("生成日期", gen_date),
    ]
    info_tbl = doc.add_table(rows=len(info_rows), cols=2)
    info_tbl.autofit = False
    _table_no_borders(info_tbl)
    for i, (label, val) in enumerate(info_rows):
        c0, c1 = info_tbl.rows[i].cells
        c0.width = Cm(3.0)
        c1.width = Cm(12.0)
        _cell_text(c0, label, bold=True, color=INK)
        _cell_text(c1, clean(val) if val else "—")

    # ---- Executive summary box ----
    _h1("执行摘要")
    box = doc.add_table(rows=1, cols=1)
    _table_no_borders(box)
    box_cell = box.rows[0].cells[0]
    _shade(box_cell, "F5F5F5")
    _cell_borders(box_cell, {"left": (24, BRAND_RED), "top": None, "bottom": None, "right": None})
    summary_items = d.get("executive_summary") or []
    if summary_items:
        first = True
        for i, s in enumerate(summary_items, 1):
            p = _clear_cell(box_cell) if first else box_cell.add_paragraph()
            first = False
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.line_spacing = Pt(20)
            _run(p, f"{i}. {clean(s)}", size=11, color=INK)
    else:
        p = _clear_cell(box_cell)
        _run(p, "—", size=11, color=GRAY)

    # ---- 心力 ----
    _h1("心力")
    xinli = d.get("xinli") or {}
    _sub("情绪与自我概念", xinli.get("emotion"))
    _sub("同伴关系", xinli.get("peers"))
    _sub("家庭与依恋", xinli.get("family"))
    _sub("内驱力", xinli.get("motivation"))
    _sub("人格", xinli.get("personality"))

    # ---- 精力 ----
    _h1("精力")
    jingli_val = clean((d.get("jingli") or {}).get("overview"))
    if jingli_val:
        for para in jingli_val.split("\n"):
            para = para.strip()
            if para:
                _body(para)

    # ---- 学习力 ----
    _h1("学习力")
    xue = d.get("xuexili") or {}
    _sub("认知资源优势", xue.get("cognitive"))
    _sub("执行能力与认知灵活性", xue.get("executive"))
    _sub("学习动机", xue.get("motivation"))
    _sub("学习方法与策略", xue.get("methods"))
    _sub("学习力整体判断", xue.get("overall"))

    # ---- 生涯力 ----
    _h1("生涯力")
    sy = d.get("shengyali") or {}
    _sub("职业兴趣", sy.get("interests"))
    _sub("能力优势与专业方向", sy.get("direction"))
    _sub("职业价值观", sy.get("values"))
    _sub("生涯力整体判断", sy.get("overall"))

    # ---- Action items table (machine anchor #2) ----
    _h1("后续行动项")
    action_tbl = doc.add_table(rows=1, cols=5)
    action_tbl.autofit = False
    _table_grid(action_tbl)
    headers = ["优先级", "行动", "原因", "方式", "时间"]
    for j, h in enumerate(headers):
        c = action_tbl.rows[0].cells[j]
        _shade(c, BRAND_RED)
        _cell_text(c, h, bold=True, color=WHITE, align=WD_ALIGN_PARAGRAPH.CENTER)
    action_items = d.get("action_items") or []
    if action_items:
        for it in action_items:
            row = action_tbl.add_row()
            vals = [
                str(it.get("priority", "")),
                clean(it.get("what", "")),
                clean(it.get("why", "")),
                clean(it.get("how", "")),
                clean(it.get("timeline", "")),
            ]
            for j, v in enumerate(vals):
                align = WD_ALIGN_PARAGRAPH.CENTER if j == 0 else None
                _cell_text(row.cells[j], v, align=align)
    else:
        row = action_tbl.add_row()
        merged = row.cells[0]
        for c in row.cells[1:]:
            merged = merged.merge(c)
        _cell_text(merged, "本次会议未形成明确行动项", color=GRAY,
                   align=WD_ALIGN_PARAGRAPH.CENTER)

    # ---- Overall judgment ----
    _h1("会议总体判断")
    oj = clean(d.get("overall_judgment"))
    if oj:
        for para in oj.split("\n"):
            para = para.strip()
            if para:
                _body(para)
    else:
        _body("—", color=GRAY)

    # ---- Footer ----
    doc.add_paragraph()
    fp = doc.add_paragraph()
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _run(fp, "— 凭远教育 · Y4 综合测评系统 —", size=9, color=GRAY)

    # ---- Core properties (machine-readable metadata) ----
    cp = doc.core_properties
    cp.title = f"Y4解读会会议纪要 - {meta.get('student_name') or ''}"
    cp.subject = "meeting-minutes"
    cp.keywords = f"{SCHEMA_VERSION};student_id 由调用方传入"
    cp.comments = "凭远教育会议纪要标准模板 minutes-v1,机器解析规范见 docs/minutes_docx_spec.md"

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()