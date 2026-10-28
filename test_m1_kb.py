"""M1 知识库契约测试：18 项能力、指标编号、固定文字。"""
from __future__ import annotations

import copy

import pytest

import data_points
from m1 import kb as kbmod


def _raw_kb():
    import json
    from pathlib import Path
    path = Path(kbmod.__file__).resolve().parent / "kb" / "r4_abilities.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_kb_loads_with_18_abilities():
    kb = kbmod.load_kb()
    abilities = kb["abilities"]
    assert len(abilities) == 18
    assert [dim["id"] for dim in kb["dims"]] == ["R1", "R2", "R3", "R4"]
    counts = {dim: len([a for a in abilities if a["dim"] == dim]) for dim in ("R1", "R2", "R3", "R4")}
    assert counts == {"R1": 4, "R2": 5, "R3": 6, "R4": 3}


def test_every_indicator_code_exists():
    for ability in kbmod.load_kb()["abilities"]:
        for code in ability["indicators"]:
            assert code in data_points.POINT_META


def test_every_ability_has_name_gap_and_ask():
    for ability in kbmod.load_kb()["abilities"]:
        assert ability["name"].strip()
        assert ability["gap_note"].strip()
        assert ability["ask"].strip()


def test_r1_2_uses_indicator_note():
    ability = kbmod.ability("R1.2")
    assert ability["indicator_note"].startswith("暂无直接对应指标")


def test_ability_lookup():
    assert kbmod.ability("R1.1")["name"] == "情绪识别与身体觉察"
    with pytest.raises(KeyError):
        kbmod.ability("R9.9")


def test_validate_rejects_wrong_count():
    kb = copy.deepcopy(_raw_kb())
    kb["abilities"].pop()
    with pytest.raises(ValueError, match="18"):
        kbmod.validate_kb(kb)


def test_validate_rejects_duplicate_code():
    kb = copy.deepcopy(_raw_kb())
    kb["abilities"][1]["code"] = kb["abilities"][0]["code"]
    with pytest.raises(ValueError, match="重复"):
        kbmod.validate_kb(kb)


def test_validate_rejects_unknown_indicator():
    kb = copy.deepcopy(_raw_kb())
    kb["abilities"][0]["indicators"].append("999")
    with pytest.raises(ValueError, match="schema_124"):
        kbmod.validate_kb(kb)


def test_validate_rejects_empty_gap_note():
    kb = copy.deepcopy(_raw_kb())
    kb["abilities"][0]["gap_note"] = " "
    with pytest.raises(ValueError, match="gap_note"):
        kbmod.validate_kb(kb)


def test_validate_rejects_empty_ask():
    kb = copy.deepcopy(_raw_kb())
    kb["abilities"][0]["ask"] = ""
    with pytest.raises(ValueError, match="ask"):
        kbmod.validate_kb(kb)


def test_validate_rejects_unknown_dim():
    kb = copy.deepcopy(_raw_kb())
    kb["abilities"][0]["dim"] = "R9"
    with pytest.raises(ValueError, match="维度未知"):
        kbmod.validate_kb(kb)


def test_fixed_text_is_present():
    fixed = kbmod.load_kb()["fixed"]
    assert len(fixed["structure_rows"]) == 4
    assert len(fixed["agenda_60"]) == 5
    assert len(fixed["quick_check"]) == 4
    assert fixed["principle_callout"].startswith("M1 属于情绪与关系发展支持")
    assert fixed["appendix_callout"].startswith("围绕 18 项 R4 能力")
    assert "Situation：" in fixed["event_path_callout"]
