"""DP2：World Bank SEL 参考资料查询与构建脚本（数据不入库）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from m1 import wb
from scripts import build_wb_library as builder

FIXTURE_DIR = Path(__file__).resolve().parent / "tests" / "fixtures" / "wb_mini"


@pytest.fixture
def fixture_dir(monkeypatch):
    monkeypatch.setenv("M1_WB_DIR", str(FIXTURE_DIR))
    return FIXTURE_DIR


def test_missing_dir_is_not_installed(monkeypatch, tmp_path):
    monkeypatch.setenv("M1_WB_DIR", str(tmp_path / "missing"))
    assert wb.installed() is False
    assert wb.lesson("WB-G9-DEMO-ONE") is None
    assert wb.lesson_text("WB-G9-DEMO-ONE") is None
    assert wb.cite("WB-G9-DEMO-ONE") == ""
    assert wb.candidates("R4.9", 9) == []


def test_fixture_is_installed_without_lesson_text(fixture_dir):
    assert wb.installed() is True
    entry = wb.lesson("WB-G9-DEMO-ONE")
    assert entry["name"] == "LESSON ONE"
    assert "text" not in entry


def test_lesson_text_follows_has_text(fixture_dir):
    assert wb.lesson_text("WB-G9-DEMO-ONE").startswith("LESSON ONE")
    assert wb.lesson_text("WB-G9-DEMO-TWO") is None
    assert wb.lesson_text("WB-G9-UNKNOWN") is None


def test_cite_format(fixture_dir):
    assert wb.cite("WB-G9-DEMO-ONE") == "G9 · LESSON ONE · PDF p.10"


@pytest.mark.parametrize("raw,expected", [
    ("G9", 9),
    ("g9", 9),
    ("Grade 9", 9),
    ("9年级", 9),
    ("九年级", 9),
    ("初一", 7),
    ("初二", 8),
    ("初三", 9),
    ("高一", 10),
    ("高二", 11),
    ("高三", 12),
    ("小学五年级", 5),
    ("五年级", 5),
    ("六年级", 6),
    ("七年级", 7),
    ("八年级", 8),
    ("四年级", 4),
    ("国际部", None),
    ("", None),
    (None, None),
])
def test_grade_from_text(raw, expected):
    assert wb.grade_from_text(raw) == expected


@pytest.mark.parametrize("grade,expected", [(4, 5), (5, 5), (6, 6), (9, 9), (10, 9), (12, 9)])
def test_nearest_grade(grade, expected):
    assert wb.nearest_grade(grade) == expected


def test_candidates_keep_order_skip_missing_text_and_limit(fixture_dir):
    result = wb.candidates("R4.9", 9)
    assert [item["wb_id"] for item in result] == ["WB-G9-DEMO-ONE", "WB-G9-DEMO-THREE"]
    assert result[0] == {
        "wb_id": "WB-G9-DEMO-ONE",
        "cite": "G9 · LESSON ONE · PDF p.10",
        "skill": "DEMO SKILL ONE",
        "match": "部分对应（示例一）",
        "limit": "示例限制一",
        "objective": "sample objective one",
    }
    assert [item["wb_id"] for item in wb.candidates("R4.9", 9, limit=1)] == ["WB-G9-DEMO-ONE"]
    assert wb.candidates("R4.9", 9, limit=0) == []
    assert wb.candidates("R4.9", 5) == []
    assert wb.candidates("R4.1", 9) == []


LESSONS = {
    "WB-G5-A": {"grade": 5, "pdf": "G5.pdf", "pdf_page": 39, "name": "Lesson One: Feelings"},
    "WB-G5-B": {"grade": 5, "pdf": "G5.pdf", "pdf_page": 45, "name": "Lesson Two: Calm"},
}


def test_parse_source_ref():
    assert builder.parse_source_ref("G5.pdf · PDF p.39 · 书内 p.41") == {
        "pdf": "G5.pdf", "pdf_page": 39, "book_page": 41}
    assert builder.parse_source_ref("G5.pdf · PDF p.45") == {
        "pdf": "G5.pdf", "pdf_page": 45, "book_page": None}
    assert builder.parse_source_ref("第 5 课") is None
    assert builder.parse_source_ref("") is None


def test_names_match_ignores_case_whitespace_and_quotes():
    assert builder.names_match("Lesson  One: Feelings", "LESSON ONE: FEELINGS") is True
    assert builder.names_match("Don’t Worry", 'DON\'T WORRY') is True
    assert builder.names_match("Lesson One", "Lesson Two") is False
    assert builder.names_match("", "") is False


def test_join_lesson_by_grade_and_page():
    row = {"grade": 5, "name": "lesson one:  feelings",
           "source": "G5.pdf · PDF p.39 · 书内 p.41"}
    assert builder.join_lesson(row, LESSONS) == ("WB-G5-A", None)


def test_join_lesson_rejects_name_mismatch():
    row = {"grade": 5, "name": "Lesson Three",
           "source": "G5.pdf · PDF p.39 · 书内 p.41"}
    wb_id, reason = builder.join_lesson(row, LESSONS)
    assert wb_id is None
    assert reason.startswith("课名不符")


def test_join_lesson_rejects_missing_page_and_bad_source():
    wb_id, reason = builder.join_lesson(
        {"grade": 5, "name": "Lesson One: Feelings", "source": "G5.pdf · PDF p.99"}, LESSONS)
    assert wb_id is None
    assert "没有同年级同页课程" in reason

    wb_id, reason = builder.join_lesson(
        {"grade": 5, "name": "Lesson One: Feelings", "source": "见课本"}, LESSONS)
    assert wb_id is None
    assert reason == "来源及页码无法解析"

    wb_id, reason = builder.join_lesson(
        {"grade": None, "name": "Lesson One: Feelings", "source": "G5.pdf · PDF p.39"}, LESSONS)
    assert wb_id is None
    assert reason == "年级无法解析"


def test_join_lesson_rejects_wrong_grade():
    row = {"grade": 6, "name": "Lesson One: Feelings",
           "source": "G5.pdf · PDF p.39"}
    wb_id, reason = builder.join_lesson(row, LESSONS)
    assert wb_id is None
    assert "没有同年级同页课程" in reason


def test_section_start_detection():
    assert builder.looks_like_section_start("REFERENCES") is True
    assert builder.looks_like_section_start("Glossary of Terms") is True
    assert builder.looks_like_section_start("STUDENT MATERIAL") is False
    assert builder.looks_like_section_start("") is False
