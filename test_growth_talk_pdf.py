"""Growth Talk PDF 排版不变量测试（不联网，使用真实 CJK 字体）。"""
from __future__ import annotations

import re

import fitz
import pytest

from growth_talk.report_pdf import render_report_pdf, report_filename


def _report(**overrides) -> dict:
    report = {
        "schema": "first-touch.report.v1",
        "reportId": "12",
        "version": 1,
        "yuguoStudentId": "Y4-9001",
        "status": "CONFIRMED",
        "confirmedAt": "2026-10-22T10:30:00",
        "confirmedBy": {"id": "1", "name": "顾问A"},
        "student": {
            "name": "林小满", "grade": "10",
            "school": "上海市民办学校",
        },
        "meetingSummary": (
            "访谈日期：2026年10月22日 18:30\n\n"
            "本次会议主要围绕兴趣与经历展开。林小满每周参加篮球训练，"
            "并在学校机器人社团负责搭建与调试。"
        ),
        "career": {
            "careerInterests": "对工程实践与运动训练都有持续投入。",
            "abilityTendencies": "空间推理与动手调试表现较稳定。",
            "valuePreferences": "重视自主探索与可验证的成果。",
        },
        "interests": [
            {"id": "1", "label": "篮球", "evidence": "每周参加校队训练",
             "preferenceScore": 3, "competenceScore": 2,
             "quadrant": "非常喜欢 × 擅长"},
            {"id": "2", "label": "机器人搭建", "evidence": "负责社团调试",
             "preferenceScore": 2, "competenceScore": 3,
             "quadrant": "喜欢 × 非常擅长"},
            {"id": "3", "label": "游戏设计", "evidence": "自己尝试做关卡",
             "preferenceScore": 2, "competenceScore": 1,
             "quadrant": "喜欢 × 一般擅长"},
        ],
        "narrative": (
            "林小满在运动与工程两类活动中都表现出主动投入，篮球训练中的"
            "即时判断与机器人社团里的持续调试形成对照。两类活动目前都"
            "有稳定投入，但兴趣与能力的组合并不相同。\n\n"
            "机器人搭建更依赖长期积累与问题拆解，篮球更依赖临场判断与"
            "团队配合。后续会谈可以继续观察他在两类活动中的投入变化。"
        ),
        "suggestions": [{
            "id": "1",
            "title": "篮球比赛观察记录",
            "introduction": "连续记录三场比赛中的关键决策，并复盘判断依据。",
            "growthValue": "练习观察、记录与赛后复盘。",
            "possibleOutputs": ["观察记录表", "复盘小结"],
            "interestRefs": ["1"],
        }],
        "sources": [{
            "id": "1", "type": "GROWTH_TALK",
            "createdAt": "2026-10-20T10:00:00",
        }],
        "promptVersions": {"meeting": "v1"},
    }
    report.update(overrides)
    return report


def _text(data: bytes) -> str:
    with fitz.open(stream=data, filetype="pdf") as document:
        return "\x0c".join(page.get_text() for page in document)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def test_pdf_generates_nonempty():
    data = render_report_pdf(_report())
    assert data[:5] == b"%PDF-"
    assert len(data) > 10_000


def test_region_guide_on_page_one():
    pages = _text(render_report_pdf(_report())).split("\x0c")
    assert "兴趣分型说明" in pages[0]
    assert "核心优势潜力" in pages[0]


def test_y4_section_starts_page_two():
    pages = _text(render_report_pdf(_report())).split("\x0c")
    assert "Y4 画像" in pages[1]
    assert "03" in pages[1]


def test_crowded_quadrant_keeps_all_labels():
    labels = [f"篮球比赛观察记录第{index}轮" for index in range(1, 8)]
    labels.append("机器人社团搭建与调试期间持续记录问题拆解过程的长期观察主题")
    interests = [{
        "id": str(index), "label": label, "evidence": "多次训练记录",
        "preferenceScore": 3, "competenceScore": 3,
        "quadrant": "非常喜欢 × 非常擅长",
    } for index, label in enumerate(labels, start=1)]
    text = _compact(_text(render_report_pdf(_report(interests=interests))))
    for label in labels:
        assert label in text


def test_oversized_project_gets_continuation():
    introduction = "项目介绍内容。" * 1200
    growth_value = "成长价值说明。" * 800
    outputs = "可能产出清单。" * 400
    report = _report(suggestions=[{
        "id": "1", "title": "超长探索建议",
        "introduction": introduction, "growthValue": growth_value,
        "possibleOutputs": [outputs], "interestRefs": ["1"],
    }])
    text = _compact(_text(render_report_pdf(report)))
    assert "（续）" in text
    assert "项目介绍" in text and "成长价值" in text and "可能产出" in text
    assert introduction[:40] in text
    assert growth_value[:40] in text
    assert outputs[:40] in text


def test_draft_marked():
    text = _compact(_text(render_report_pdf(_report(), draft=True)))
    assert "DRAFT草稿" in text
    assert "当前预览·尚未确认" in text


def test_report_filename_sanitizes():
    assert report_filename('林/小满:*?"<>|') == "林_小满_______ - First Touch Report.pdf"
    assert report_filename("  ..  ") == "学生 - First Touch Report.pdf"
