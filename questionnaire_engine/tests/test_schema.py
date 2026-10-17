"""问卷 schema 工具单测：答案校验与分段分组。"""
from __future__ import annotations

import pytest

from questionnaire_engine import schema as S

SCHEMA = {
    "version": 1,
    "sections": [
        {"id": "a", "title": "第一段", "intro": "…"},
        {"id": "b", "title": "第二段", "intro": "…"},
    ],
    "questions": [
        {"id": "q1", "type": "single", "title": "单选", "required": True,
         "options": [{"value": "0", "label": "A"}, {"value": "1", "label": "B"}], "section": "a"},
        {"id": "q2", "type": "multi", "title": "多选", "required": True,
         "options": [{"value": "x", "label": "X"}, {"value": "y", "label": "Y"}], "section": "a"},
        {"id": "q3", "type": "scale", "title": "量表", "required": False,
         "scale": {"min": 1, "max": 5}, "section": "b"},
        {"id": "q4", "type": "text", "title": "文字", "required": True, "max_length": 5, "section": "b"},
    ],
}


def test_sections_grouping():
    groups = S.group_by_section(SCHEMA)
    assert [g[0]["id"] for g in groups] == ["a", "b"]
    assert [len(g[1]) for g in groups] == [2, 2]


def test_grouping_without_sections():
    groups = S.group_by_section({"questions": SCHEMA["questions"]})
    assert len(groups) == 1 and groups[0][0] is None
    assert len(groups[0][1]) == 4


def test_validate_ok():
    answers = {"q1": "1", "q2": ["x", "y"], "q3": 3, "q4": "好的"}
    assert S.validate_answers(SCHEMA, answers) == []


def test_validate_required_missing():
    errs = S.validate_answers(SCHEMA, {})
    assert len(errs) == 3          # q1 / q2 / q4 必填，q3 非必填


def test_validate_illegal_option():
    errs = S.validate_answers(SCHEMA, {"q1": "9", "q2": ["z"], "q4": "ok"})
    assert any("第 1 题" in e for e in errs)
    assert any("选项 z 非法" in e for e in errs)


def test_validate_scale_range_and_text_length():
    errs = S.validate_answers(SCHEMA, {"q1": "1", "q2": ["x"], "q3": 9, "q4": "一二三四五六"})
    assert any("取值需在 1 到 5 之间" in e for e in errs)
    assert any("超过字数上限" in e for e in errs)


def test_validate_errors_reference_question_number():
    # 漏答第 1、2、4 题：错误按题号定位，不含整段题干
    errs = S.validate_answers(SCHEMA, {})
    assert errs == ["第 1 题：需要作答", "第 2 题：至少选择一项", "第 4 题：需要作答"]


def test_validate_numeric_option_alignment():
    # 选项 value 是字符串 "0"/"1"，答案传数字 0 也应合法
    assert S.validate_answers(SCHEMA, {"q1": 0, "q2": ["x"], "q4": "ok"}) == []
