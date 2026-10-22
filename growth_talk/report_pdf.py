"""Growth Talk 中文 PDF 渲染（移植 first-touch ``lib/report-pdf.ts``）。

A4 单栏版式：身份块 → 01 会议总结 → 02 兴趣分型（4×4 网格与区域导览）
→ 03 Y4 画像 → 04 项目推荐清单。所有文本先按真实字体度量换行，
分页时宁可拆卡也不丢弃内容。
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT_NAME = "NotoSansCJKsc"
# 源仓库提供的是 CFF/PostScript 轮廓的 .otf，reportlab 只支持 TrueType 轮廓；
# 因此随仓库提供由同一字体转换得到的 .ttf（字形与 OFL 许可均未改变）。
FONT_PATH = (Path(__file__).resolve().parent.parent
             / "static" / "fonts" / "NotoSansCJKsc-Regular.ttf")

INK = HexColor("#1b2923")
MUTED = HexColor("#65746b")
GREEN = HexColor("#176146")
ORANGE = HexColor("#c46238")
WHITE = HexColor("#ffffff")
PAPER = HexColor("#fcfdfb")
LINE = HexColor("#d8e3dc")
STRONG = HexColor("#dcece1")
EXPLORE = HexColor("#f9e9df")
CAPABLE = HexColor("#e2edf4")
QUIET = HexColor("#f1f4ee")
PANEL = HexColor("#f5f8f4")

PAGE_WIDTH, PAGE_HEIGHT = A4
BODY = 9.5
LINE_GAP = 2.5
TAG_SIZE = 7.5
TAG_GAP = 4
CARD_PAD = 14
PROJECT_PAD = 16
PROJECT_TITLE = 13
PROJECT_GAP = 8
SHANGHAI = ZoneInfo("Asia/Shanghai")


def report_filename(name: str) -> str:
    """对齐源 ``reportPdfDownloadDisposition`` 的文件名清洗规则。"""
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", name or "").strip()
    value = re.sub(r"[. ]+$", "", value) or "学生"
    return f"{value} - First Touch Report.pdf"


def _ensure_font() -> None:
    if FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return
    pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))


def _line_height(size: float) -> float:
    return 16.0 if size == BODY else size * 1.2 + LINE_GAP


def _wrap(text: str, size: float, width: float) -> list[tuple[str, int]]:
    """按真实字体宽度换行，返回 (行文本, 该行结束于原文的下标)。"""
    lines: list[tuple[str, int]] = []
    index, total = 0, len(text)
    while index < total:
        if text[index] == "\n":
            lines.append(("", index + 1))
            index += 1
            continue
        start = index
        line, line_width = "", 0.0
        boundary = None
        cursor = index
        while cursor < total and text[cursor] != "\n":
            char = text[cursor]
            char_width = pdfmetrics.stringWidth(char, FONT_NAME, size)
            if line and line_width + char_width > width:
                break
            line += char
            line_width += char_width
            if char in " 。；，、":
                boundary = cursor + 1
            cursor += 1
        if (cursor < total and text[cursor] != "\n"
                and boundary is not None and boundary > start):
            lines.append((text[start:boundary], boundary))
            index = boundary
        else:
            if cursor < total and text[cursor] != "\n" and cursor == start:
                cursor = start + 1
            lines.append((text[start:cursor], cursor))
            index = cursor
    return lines


def _measure(text: str, size: float = BODY, width: float | None = None) -> float:
    if not text:
        return 0.0
    return len(_wrap(text, size, width or 0)) * _line_height(size)


def _take(text: str, max_height: float, size: float,
          width: float) -> tuple[str, str]:
    lines = _wrap(text, size, width)
    fits = int(max_height // _line_height(size))
    if fits <= 0:
        raise ValueError("报告文字无法放入 A4 正文区域")
    if fits >= len(lines):
        return text.strip(), ""
    end = lines[fits - 1][1]
    return text[:end].strip(), text[end:].strip()


class _Flow:
    """自上而下的排版游标；y 为距页面顶部的距离。"""

    def __init__(self, pdf: canvas.Canvas, x: float, top: float,
                 bottom: float, width: float):
        self.pdf = pdf
        self.x = x
        self.top = top
        self.bottom = bottom
        self.width = width
        self.y = top

    def page(self) -> None:
        self.pdf.showPage()
        self.y = self.top

    def space(self, height: float) -> None:
        if self.y + height > self.bottom:
            self.page()

    def draw(self, text, size=BODY, color=INK, x=None, width=None,
             align="left") -> float:
        x = self.x if x is None else x
        width = self.width if width is None else width
        height = 0.0
        for line, _end in _wrap(text, size, width):
            baseline = PAGE_HEIGHT - self.y - size
            self.pdf.setFont(FONT_NAME, size)
            self.pdf.setFillColor(color)
            if align == "right":
                self.pdf.drawRightString(x + width, baseline, line)
            elif align == "center":
                self.pdf.drawCentredString(x + width / 2, baseline, line)
            else:
                self.pdf.drawString(x, baseline, line)
            self.y += _line_height(size)
            height += _line_height(size)
        return height

    def paragraph(self, text, size=BODY, color=INK, after=7) -> None:
        if not isinstance(text, str) or not text.strip():
            return
        blocks = re.split(r"\n\s*\n", text.strip())
        for position, block in enumerate(blocks):
            rest = block.strip()
            while rest:
                self.space(_line_height(size))
                chunk, rest = _take(rest, self.bottom - self.y, size,
                                   self.width)
                self.draw(chunk, size, color)
                rest = rest.strip()
                if rest:
                    self.page()
            if position < len(blocks) - 1:
                self.y += 5
        self.y += after


def _heading(flow: _Flow, title: str, major=True, first_text="",
             reserve=0.0) -> None:
    size = 12.5 if major else 9
    numbered = re.match(r"^(\d{2})\s+(.+)$", title) if major else None
    title_height = 32 if numbered else _measure(title, size, flow.width)
    lead = max(reserve, min(_measure(first_text), 32) if first_text else 16)
    flow.space(title_height + lead + (14 if major else 4))
    if numbered:
        flow.y += 7
        flow.pdf.setFillColor(PANEL)
        flow.pdf.roundRect(flow.x, PAGE_HEIGHT - flow.y - 32,
                           flow.width, 32, 4, stroke=0, fill=1)
        flow.pdf.setFillColor(GREEN)
        flow.pdf.roundRect(flow.x, PAGE_HEIGHT - flow.y - 32, 32, 32, 4,
                           stroke=0, fill=1)
        flow.pdf.setFillColor(WHITE)
        flow.pdf.setFont(FONT_NAME, 11)
        flow.pdf.drawCentredString(flow.x + 16, PAGE_HEIGHT - flow.y - 24,
                                   numbered.group(1))
        flow.pdf.setFillColor(GREEN)
        flow.pdf.setFont(FONT_NAME, size)
        flow.pdf.drawString(flow.x + 44, PAGE_HEIGHT - flow.y - 26,
                            numbered.group(2))
        flow.y += 39
        return
    if major:
        flow.y += 8
        flow.pdf.setFillColor(ORANGE)
        flow.pdf.rect(flow.x, PAGE_HEIGHT - flow.y - title_height, 3,
                      title_height, stroke=0, fill=1)
    flow.draw(title, size, GREEN if major else MUTED,
              flow.x + (12 if major else 0),
              flow.width - (12 if major else 0))
    flow.y += 7 if major else 3


def _tag_rows(labels: list[str], width: float) -> list[dict]:
    rows: list[dict] = []
    row = {"tags": [], "height": 0.0}
    x = 0.0
    for label in labels:
        tag_width = min(width, pdfmetrics.stringWidth(label, FONT_NAME,
                                                      TAG_SIZE) + 10)
        tag_height = _measure(label, TAG_SIZE, tag_width - 10) + 6
        if row["tags"] and x + tag_width > width:
            rows.append(row)
            row = {"tags": [], "height": 0.0}
            x = 0.0
        row["tags"].append({"label": label, "x": x,
                            "width": tag_width, "height": tag_height})
        row["height"] = max(row["height"], tag_height)
        x += tag_width + TAG_GAP
    if row["tags"]:
        rows.append(row)
    return rows


def _rows_height(rows: list[dict]) -> float:
    return sum(row["height"] + TAG_GAP for row in rows)


def _draw_block(pdf: canvas.Canvas, text: str, size: float, color,
                x: float, y: float, width: float) -> None:
    """在固定位置绘制多行文本（不移动排版游标）。"""
    pdf.setFont(FONT_NAME, size)
    pdf.setFillColor(color)
    offset = 0.0
    for line, _end in _wrap(text, size, width):
        pdf.drawString(x, PAGE_HEIGHT - y - size - offset, line)
        offset += _line_height(size)


def _region_color(competence: int, preference: int) -> HexColor:
    if competence >= 2:
        return STRONG if preference >= 2 else CAPABLE
    return EXPLORE if preference >= 2 else QUIET


def _grid(flow: _Flow, interests: list[dict]) -> None:
    cell_width = flow.width / 4
    bands = [[[
        item["label"] for item in interests
        if item.get("preferenceScore") == preference
        and item.get("competenceScore") == competence
    ] for preference in range(4)] for competence in (3, 2, 1, 0)]

    for index, labels_by_cell in enumerate(bands):
        competence = 3 - index
        cells = [_tag_rows(labels, cell_width - 18) for labels in labels_by_cell]
        continuation = False
        while any(cells):
            axis_height = 17 if (index == 0 or flow.y == flow.top
                                 or continuation) else 0
            minimum = max(44.0, max(
                (cell[0]["height"] if cell else 0) + 28 for cell in cells
            )) + 3
            flow.space(minimum + axis_height)
            max_band = flow.bottom - flow.y - axis_height - 3
            band_rows = []
            for cell in cells:
                used, count = 24.0, 0
                while (count < len(cell)
                       and used + cell[count]["height"] + TAG_GAP <= max_band):
                    used += cell[count]["height"] + TAG_GAP
                    count += 1
                band_rows.append(cell[:count])
            band_height = max(44.0, max(
                24 + _rows_height(rows) for rows in band_rows))
            if axis_height:
                flow.pdf.setFont(FONT_NAME, 7.5)
                flow.pdf.setFillColor(MUTED)
                flow.pdf.drawString(flow.x, PAGE_HEIGHT - flow.y - 7.5,
                                    "擅长程度 ↑"
                                    + ("  /  续" if continuation else ""))
                flow.pdf.drawRightString(flow.x + flow.width,
                                         PAGE_HEIGHT - flow.y - 7.5,
                                         "喜欢程度 →")
                flow.y += 17
            band_y = flow.y
            for column, rows in enumerate(band_rows):
                cell_x = flow.x + column * cell_width
                flow.pdf.setFillColor(_region_color(competence, column))
                flow.pdf.roundRect(cell_x, PAGE_HEIGHT - band_y - band_height,
                                   cell_width - 3, band_height, 3,
                                   stroke=0, fill=1)
                flow.pdf.setFillColor(MUTED)
                flow.pdf.setFont(FONT_NAME, 6.5)
                flow.pdf.drawString(cell_x + 7,
                                    PAGE_HEIGHT - band_y - 4 - 6.5,
                                    f"{competence} / {column}")
                row_y = band_y + 19
                for row in rows:
                    for tag in row["tags"]:
                        tag_x = cell_x + 7 + tag["x"]
                        flow.pdf.setFillColor(WHITE)
                        flow.pdf.setStrokeColor(LINE)
                        flow.pdf.setLineWidth(0.4)
                        flow.pdf.roundRect(tag_x, PAGE_HEIGHT - row_y
                                           - tag["height"], tag["width"],
                                           tag["height"], 3, stroke=1, fill=1)
                        _draw_block(flow.pdf, tag["label"], TAG_SIZE, INK,
                                    tag_x + 5, row_y + 3, tag["width"] - 10)
                    row_y += row["height"] + TAG_GAP
            cells = [cells[i][len(band_rows[i]):] for i in range(4)]
            flow.y = band_y + band_height + 3
            if any(cells):
                flow.page()
                continuation = True
    flow.y += 3
    flow.paragraph(
        "分值：0 不喜欢 / 不擅长，1 一般，2 喜欢 / 擅长，3 非常喜欢 / 非常擅长。",
        7.5, MUTED, 3,
    )


def _region_guide(flow: _Flow) -> None:
    guides = [
        ("核心优势潜力", "喜欢且擅长", STRONG),
        ("重点探索空间", "喜欢，能力仍在形成", EXPLORE),
        ("辅助优势储备", "擅长，兴趣可继续观察", CAPABLE),
        ("待继续观察", "目前两维线索较弱", QUIET),
    ]
    flow.space(_measure("区域介绍", 9) + 3 + 46)
    _heading(flow, "区域介绍", False)
    width = flow.width / 4
    for index, (label, text, fill) in enumerate(guides):
        x = flow.x + index * width
        flow.pdf.setFillColor(fill)
        flow.pdf.roundRect(x, PAGE_HEIGHT - flow.y - 39, width - 5, 39, 3,
                           stroke=0, fill=1)
        flow.pdf.setFillColor(INK)
        flow.pdf.setFont(FONT_NAME, 8)
        flow.pdf.drawString(x + 8, PAGE_HEIGHT - flow.y - 6 - 8, label)
        flow.pdf.setFillColor(MUTED)
        flow.pdf.setFont(FONT_NAME, 7)
        flow.pdf.drawString(x + 8, PAGE_HEIGHT - flow.y - 21 - 7, text)
    flow.y += 46


def _parse_project_introduction(text: str) -> list[tuple[str, str]] | None:
    for labels in (
        ["兴趣锚点", "探索问题", "起步尝试", "后续方向"],
        ["兴趣锚点", "核心问题", "具体例子", "探索旅程"],
    ):
        pattern = ("^" + "".join(
            rf"{label}[：:]([\s\S]*?)" + ("" if i == len(labels) - 1 else r"\n")
            for i, label in enumerate(labels)
        ) + "$")
        match = re.match(pattern, text or "")
        if match:
            return [(label, match.group(i + 1))
                    for i, label in enumerate(labels)]
    return None


def _project_fields(suggestion: dict) -> list[tuple[str, str]]:
    introduction = suggestion.get("introduction") or ""
    parsed = _parse_project_introduction(introduction)
    if parsed:
        return parsed
    return [
        ("项目介绍", introduction),
        ("成长价值", suggestion.get("growthValue") or ""),
        ("可能产出", "、".join(suggestion.get("possibleOutputs") or [])),
    ]


def _field_overhead(label: str, width: float) -> float:
    return _measure(label, 8, width) + 5


def _field_height(label: str, text: str, width: float) -> float:
    return _measure(text, BODY, width) + _field_overhead(label, width)


def _project_title_height(title: str, width: float) -> float:
    return (12 + _measure("项目 01", 7.5, width) + 2
            + _measure(title, PROJECT_TITLE, width) + 10)


def _project_height(title: str, fields: list[tuple[str, str]],
                    width: float) -> float:
    inner = width - PROJECT_PAD * 2
    return (_project_title_height(title, inner)
            + sum(_field_height(label, text, inner) + PROJECT_GAP
                  for label, text in fields) + 8)


def _project_card(flow: _Flow, title: str, fields: list[tuple[str, str]],
                  index: int, continuation: bool = False) -> None:
    width = flow.width - PROJECT_PAD * 2
    height = _project_height(title, fields, flow.width)
    y = flow.y
    flow.pdf.setFillColor(WHITE)
    flow.pdf.setStrokeColor(LINE)
    flow.pdf.setLineWidth(0.7)
    flow.pdf.roundRect(flow.x, PAGE_HEIGHT - y - height, flow.width, height,
                       5, stroke=1, fill=1)
    flow.y = y + 12
    flow.draw(f"项目 {index + 1:02d}"
              + ("  /  续页" if continuation else ""),
              7.5, MUTED if continuation else ORANGE,
              flow.x + PROJECT_PAD, width)
    flow.y += 2
    flow.draw(title, PROJECT_TITLE, INK, flow.x + PROJECT_PAD, width)
    flow.y += 10
    for label, text in fields:
        flow.draw(label, 8, MUTED, flow.x + PROJECT_PAD, width)
        flow.y += 5
        flow.draw(text, BODY, INK, flow.x + PROJECT_PAD, width)
        flow.y += PROJECT_GAP
    flow.y = y + height + 12


def _project(flow: _Flow, suggestion: dict, index: int) -> None:
    title = suggestion.get("title") or ""
    fields = _project_fields(suggestion)
    inner = flow.width - PROJECT_PAD * 2
    height = _project_height(title, fields, flow.width)
    if height <= flow.bottom - flow.top:
        flow.space(height)
        _project_card(flow, title, fields, index)
        return

    remaining = [(label, (text or "").strip()) for label, text in fields]
    continuation = False
    while remaining:
        current_title = title + ("（续）" if continuation else "")
        header = _project_title_height(current_title, inner) + 8
        flow.space(header + _field_height(remaining[0][0], "字", inner)
                   + PROJECT_GAP)
        available = flow.bottom - flow.y - header
        chunk_fields = []
        while remaining:
            label, text = remaining[0]
            needed = _field_height(label, text, inner) + PROJECT_GAP
            if needed <= available:
                chunk_fields.append(remaining.pop(0))
                available -= needed
                continue
            room = (available - _field_overhead(label, inner)
                    - PROJECT_GAP)
            if room >= _line_height(BODY):
                chunk, rest = _take(text, room, BODY, inner)
                chunk_fields.append((label, chunk))
                if rest.strip():
                    remaining[0] = (label + "（续）", rest)
                else:
                    remaining.pop(0)
            break
        if not chunk_fields:
            raise ValueError("报告文字无法放入 A4 正文区域")
        _project_card(flow, current_title, chunk_fields, index,
                      continuation)
        if remaining:
            flow.page()
            continuation = True


def _career_panel(flow: _Flow, label: str, text: str) -> None:
    width = flow.width - CARD_PAD * 2
    height = _measure(text, BODY, width) + 40
    if height > flow.bottom - flow.top:
        _heading(flow, label, False, text)
        flow.paragraph(text)
        return
    flow.space(height)
    flow.pdf.setFillColor(PANEL)
    flow.pdf.roundRect(flow.x, PAGE_HEIGHT - flow.y - height, flow.width,
                       height, 4, stroke=0, fill=1)
    flow.pdf.setFillColor(GREEN)
    flow.pdf.rect(flow.x, PAGE_HEIGHT - flow.y - 12 - 14, 3, 14,
                  stroke=0, fill=1)
    flow.pdf.setFont(FONT_NAME, 9)
    flow.pdf.setFillColor(GREEN)
    flow.pdf.drawString(flow.x + CARD_PAD,
                        PAGE_HEIGHT - flow.y - 9 - 9, label)
    flow.y += 28
    flow.draw(text, BODY, INK, flow.x + CARD_PAD, width)
    flow.y += 8


def _meeting_at(report: dict) -> str | None:
    value = report.get("meetingAt")
    if value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            local = parsed.astimezone(SHANGHAI)
            return (f"{local.year}年{local.month}月{local.day}日 "
                    f"{local.hour}:{local.minute:02d}")
        except ValueError:
            return None
    summary = report.get("meetingSummary") or ""
    match = re.match(r"^访谈日期：([^\n]+)", summary)
    return match.group(1) if match else None


class _ReportCanvas(canvas.Canvas):
    def __init__(self, buffer, *, header_left: str, student_name: str,
                 footer_left: str):
        super().__init__(buffer, pagesize=A4, pageCompression=1)
        self._saved_states = []
        self._header_left = header_left
        self._student_name = student_name
        self._footer_left = footer_left

    def showPage(self):
        self._saved_states.append(dict(self.__dict__))
        self._startPage()

    def _stamp(self, number: int, total: int) -> None:
        self.setFont(FONT_NAME, 7)
        self.setFillColor(MUTED)
        self.drawString(43, PAGE_HEIGHT - 34, self._header_left)
        self.setFillColor(GREEN)
        self.drawRightString(PAGE_WIDTH - 43, PAGE_HEIGHT - 34,
                             self._student_name)
        self.setStrokeColor(LINE)
        self.setLineWidth(0.5)
        self.line(43, 40, PAGE_WIDTH - 43, 40)
        self.setFont(FONT_NAME, 6.5)
        self.setFillColor(MUTED)
        self.drawString(43, 30, self._footer_left)
        self.drawRightString(PAGE_WIDTH - 43, 30, f"{number} / {total}")

    def save(self):
        total = len(self._saved_states)
        for number, state in enumerate(self._saved_states, start=1):
            self.__dict__.update(state)
            self._stamp(number, total)
            super().showPage()
        super().save()


def render_report_pdf(report: dict, *, draft: bool = False) -> bytes:
    """渲染 1.0 报告 payload（或同构草稿）为 PDF 字节。"""
    _ensure_font()
    student = report.get("student") or {}
    name = student.get("name") or "学生"
    grade = student.get("grade") or "年级未填写"
    school = student.get("school") or "学校未填写"
    meeting_summary = report.get("meetingSummary") or ""
    interests = report.get("interests") or []
    narrative = report.get("narrative") or ""
    career = report.get("career")
    suggestions = report.get("suggestions") or []
    version = report.get("version")
    report_id = report.get("reportId")
    confirmed_by = (report.get("confirmedBy") or {}).get("name") \
        if isinstance(report.get("confirmedBy"), dict) else None

    buffer = io.BytesIO()
    pdf = _ReportCanvas(
        buffer,
        header_left="FIRST TOUCH   /   " + ("DRAFT 草稿" if draft
                                           else "CONFIRMED REPORT"),
        student_name=name,
        footer_left=("当前预览 · 尚未确认" if draft
                     else f"{report_id} · v{version}"),
    )
    pdf.setTitle(f"{name} · 会谈报告" + ("（草稿）" if draft else ""))
    pdf.setAuthor(confirmed_by or "First Touch")

    flow = _Flow(pdf, 43, 55, PAGE_HEIGHT - 55, PAGE_WIDTH - 86)
    identity = _Flow(pdf, 43 + 14, 55, PAGE_HEIGHT - 55, flow.width - 14)
    identity.draw("FIRST TOUCH / 学生成长报告", 8, GREEN)
    identity.y += 3
    identity.paragraph(f"{name} · 会谈报告", 20, INK, 3)
    identity.paragraph(
        f"{grade} · {school}"
        + ("  |  草稿 · 待顾问确认" if draft else f"  |  已确认 · v{version}"),
        9, MUTED, 3,
    )
    meeting_at = _meeting_at(report)
    if meeting_at:
        identity.paragraph(f"访谈日期：{meeting_at}", 8, MUTED, 2)
    pdf.setFillColor(GREEN)
    pdf.rect(flow.x, PAGE_HEIGHT - min(identity.y, flow.bottom),
             3, min(identity.y, flow.bottom) - flow.y - 2,
             stroke=0, fill=1)
    flow.y = identity.y + 4

    missing = report.get("missing") or []
    if draft and missing:
        _heading(flow, "本次报告未包含的内容")
        flow.paragraph("；".join(str(item) for item in missing), 8, MUTED)

    _heading(flow, "01 会议总结", True, meeting_summary)
    flow.paragraph(re.sub(r"^访谈日期：[^\n]*\n\n", "", meeting_summary))

    _heading(flow, "02 兴趣分型", True, "", 70)
    _grid(flow, [item for item in interests
                 if item.get("preferenceScore") is not None
                 and item.get("competenceScore") is not None])
    _heading(flow, "兴趣分型说明", False, narrative)
    flow.paragraph(narrative)
    _region_guide(flow)

    if career:
        flow.page()
        _heading(flow, "03 Y4 画像")
        for key, label in (("careerInterests", "职业兴趣"),
                           ("abilityTendencies", "能力倾向"),
                           ("valuePreferences", "价值偏好")):
            _career_panel(flow, label, career.get(key) or "未填写")
        validation = report.get("y4Validation") or []
        if validation:
            _heading(flow, "会议对 Y4 的验证")
            for text in validation:
                flow.paragraph(f"• {text}")

    if suggestions:
        first_height = _project_height(suggestions[0].get("title") or "",
                                       _project_fields(suggestions[0]),
                                       flow.width)
        page_height = flow.bottom - flow.top
        if page_height - 46 < first_height <= page_height:
            if flow.y != flow.top:
                flow.page()
            pdf.setFont(FONT_NAME, 8)
            pdf.setFillColor(GREEN)
            pdf.drawString(flow.x, PAGE_HEIGHT - flow.top + 14,
                           "04 项目推荐清单")
        else:
            _heading(flow, "04 项目推荐清单", True, "",
                     min(first_height, page_height - 46))
        for index, item in enumerate(suggestions):
            _project(flow, item, index)

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
