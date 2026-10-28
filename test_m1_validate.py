"""M1 文档校验单元测试：占位符、优先能力覆盖、原始分值泄漏。"""
from __future__ import annotations

import pytest

from m1.validate_doc import (DocValidationError, check_no_raw_numbers, redact_raw_numbers,
                             check_priority_coverage, scan_placeholders,
                             validate_doc)


def _doc(**overrides):
    doc = {
        "meta": {"student": "林晓雨", "duration": 60},
        "sources": [],
        "dims": [],
        "priority": [],
        "special": {},
        "events": [],
        "backups": [],
        "growth": {},
        "appendix": [],
        "flags": {"safety": [], "insufficient": []},
    }
    doc.update(overrides)
    return doc


def _priority(code="R2.2"):
    return {"code": code,
            "evidence": ["Y4：焦虑/安详（需关注）"],
            "hypothesis": {"id": "h", "text": "待核实", "origin": "ai",
                           "ai_text": "待核实"},
            "why": {"id": "w", "text": "需要确认", "origin": "ai",
                    "ai_text": "需要确认"}}


# ---------------------------------------------------------------------------
# 占位符
# ---------------------------------------------------------------------------
def test_placeholders_detected_in_nested_blocks():
    doc = _doc(events=[{"id": "ev1", "title": {"text": "〔AI 填写：情境〕"}}])
    found = scan_placeholders(doc)
    assert "〔" in found
    with pytest.raises(DocValidationError):
        validate_doc(doc)


def test_clean_doc_has_no_placeholders():
    doc = _doc(events=[{"id": "ev1", "title": {"text": "情境 1：期中之后"}}])
    assert scan_placeholders(doc) == []
    validate_doc(doc)


# ---------------------------------------------------------------------------
# 优先能力覆盖
# ---------------------------------------------------------------------------
def test_priority_must_be_covered_by_event_or_backup():
    doc = _doc(priority=[_priority("R2.2")],
               events=[{"id": "ev1", "abilities": ["R4.2"]}])
    assert check_priority_coverage(doc) == ["R2.2"]
    with pytest.raises(DocValidationError) as error:
        validate_doc(doc)
    assert "R2.2" in str(error.value)

    doc["backups"] = [{"code": "R2.2"}]
    assert check_priority_coverage(doc) == []


# ---------------------------------------------------------------------------
# 原始分值
# ---------------------------------------------------------------------------
def test_raw_numbers_detected_but_dates_and_units_ignored():
    evidence = [{"source": "y4", "raw": 7}, {"source": "y4", "raw": 3}]
    doc = _doc(events=[
        {"id": "ev1", "clue": "测评 2026-10-12；会议 60 分钟；R4 第 4 环节"},
        {"id": "ev2", "clue": "考后自评 7 分"},
    ])
    leaked = check_no_raw_numbers(doc, evidence)
    assert leaked == ["7"]
    with pytest.raises(DocValidationError) as error:
        validate_doc(doc, evidence)
    assert "7" in str(error.value)


def test_small_numbers_elsewhere_are_not_leaks():
    # real model output: R4 codes, durations and counts share digits with raw scores
    evidence = [{"source": "y4", "raw": 6, "text": "自我概念—能力与学校表现：较好"},
                {"source": "y4", "raw": 4, "text": "人格—宜人性：较好"}]
    doc = _doc(events=[{"id": "ev1", "clue": "R4 恢复维度；会议 60 分钟；2–4 个问题；6 个月前换班"}])
    assert check_no_raw_numbers(doc, evidence) == []


def test_score_next_to_its_indicator_is_a_leak_and_redacted():
    evidence = [{"source": "y4", "raw": 6, "text": "自我概念—能力与学校表现：较好"}]
    doc = _doc(events=[{"id": "ev1", "clue": "能力与学校表现得分 6，属于较好"}])
    assert check_no_raw_numbers(doc, evidence) == ["6"]
    assert redact_raw_numbers(doc, evidence) == 1
    assert check_no_raw_numbers(doc, evidence) == []
    assert "6" not in doc["events"][0]["clue"]


def test_no_raw_numbers_returns_empty_without_raw_values():
    doc = _doc(events=[{"id": "ev1", "clue": "考后自评 7 分"}])
    assert check_no_raw_numbers(doc, [{"source": "y4", "raw": None}]) == []
    assert check_no_raw_numbers(doc, [{"source": "y4", "raw": "SAE"}]) == []
