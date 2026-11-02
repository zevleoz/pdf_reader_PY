"""M1R-P2：家长版文字上限、Y4 上限与线索去重。

复用 test_m1_report_core.py 的假模型和数据库 fixture；不调用真实模型。
"""
from __future__ import annotations

import json

from m1 import report_checks, report_display, report_kb, report_pipeline, report_prompts
from test_m1_report_core import (FakeModel, TRANSCRIPT, fake, generate,  # noqa: F401
                                 rdb)
from test_m1_store import m1db  # noqa: F401  临时库与虚构学生


def _sentence(chars, first="一"):
    """构造恰好 chars 个字（含句号）的整句。"""
    return first + "字" * (chars - len(first) - 1) + "。"


def _long(clauses=3, chars=40):
    return "".join(_sentence(chars, t) for t in "一二三"[:clauses])


def _doc_with_meeting(text, tags=("信息不足",)):
    row = {"meeting": {"text": text, "src": "ai"}, "tags": list(tags)}
    return {"dims": {"R1": {"abilities": {"R1.1": row}}}}


def _checks(doc, code):
    return [c for c in report_checks.run_checks({"transcript_text": ""}, {"doc": doc},
                                                first_touch_text="")
            if c["code"] == code]


# ---------------------------------------------------------------------------
# §4.2 保留整句
# ---------------------------------------------------------------------------
def test_cap_keeps_whole_sentences():
    a, b, c = _sentence(30, "一"), _sentence(30, "二"), _sentence(30, "三")
    field = {"text": a + b + c, "src": "ai"}
    adjustments = []
    report_pipeline._cap_field(field, 60, "R1.1 首次会议核实情况",
                               ["dims", "R1", "abilities", "R1.1", "meeting"], adjustments)
    assert field["text"] == a + b
    assert len(adjustments) == 1
    assert "超过 60 字，已删去后面的句子" in adjustments[0]["message"]


def test_cap_long_first_sentence():
    field = {"text": _sentence(90, "长"), "src": "ai"}
    adjustments = []
    report_pipeline._cap_field(field, 60, "R1.1 首次会议核实情况",
                               ["dims", "R1", "abilities", "R1.1", "meeting"], adjustments)
    assert field["text"] == _sentence(90, "长")
    assert [a["message"] for a in adjustments] == ["R1.1 首次会议核实情况：第一句已超过 60 字，请导师精简"]


def test_cap_with_sentence_rows():
    rows = [{"text": _sentence(30, "一"), "evidence_ids": []},
            {"text": _sentence(30, "二"), "evidence_ids": []},
            {"text": _sentence(30, "三"), "evidence_ids": []}]
    field = {"text": "".join(r["text"] for r in rows), "sentences": [dict(r) for r in rows],
             "src": "ai"}
    adjustments = []
    report_pipeline._cap_field(field, 60, "R1.1 首次会议核实情况", ["meeting"], adjustments)
    assert field["sentences"] == rows[:2]
    assert field["text"] == "".join(r["text"] for r in rows[:2])
    assert len(adjustments) == 1


# ---------------------------------------------------------------------------
# §4.4 Y4 上限
# ---------------------------------------------------------------------------
def test_y4_capped_at_three(rdb, fake):
    indicators = report_kb.ability_map()["R1.1"]["indicators"]
    picked = indicators + ["999", "888"]
    assert len(picked) == 6
    fake.overrides["R1.1"] = {"y4_selected": picked}
    _report, version = generate(rdb)
    saved = version["doc"]["dims"]["R1"]["abilities"]["R1.1"]["y4_selected"]
    assert saved == indicators[:3]


# ---------------------------------------------------------------------------
# §4.3 其他线索只写资料名（M1R-P6）
# ---------------------------------------------------------------------------
def _clue_item(item_id, quote, codes, location="其他资料：家长访谈"):
    return {"id": item_id, "quote": quote, "ability_codes": list(codes), "source": "FT",
            "status": "已确认", "quote_verified": True, "location": location}


def test_one_clue_per_ability_no_repeat():
    evidence = [_clue_item("e1", "甲", ["R1.1"], location="其他资料：Miranda review"),
                _clue_item("e2", "乙", ["R1.1"], location="其他资料：访谈 9/25"),
                _clue_item("e3", "丙", ["R1.1"], location="First Touch")]
    line = report_display.sources_line(evidence, "R1.1")
    assert line == "另见：Miranda review；访谈 9/25等 3 份资料。"
    assert "“" not in line


def test_long_clue_uses_first_sentence():
    evidence = [
        {"id": "e1", "quote": "甲", "ability_codes": ["R1.1"], "source": "M1",
         "status": "已确认", "quote_verified": True, "location": "M1 会议"},
        _clue_item("e2", "乙", ["R1.1"], location="其他资料：未核实"),
    ]
    evidence[1].update(status="待核实", quote_verified=False)
    assert report_display.sources_line(evidence, "R1.1") == ""


# ---------------------------------------------------------------------------
# §4.4 会议核实情况的双标签上限
# ---------------------------------------------------------------------------
class _LongMeetingModel(FakeModel):
    """R1.1 双标签、R1.2 单标签，两者都拿到同一段 75 字的会议文字。"""

    def _dim(self, prompt):
        out = super()._dim(prompt)
        payload = json.loads(prompt.split("【能力与资料】\n", 1)[1])
        ids = {row["code"]: [e["id"] for e in row["meeting_evidence"]] for row in payload}
        sentences = [_sentence(25, t) for t in ("一", "二", "三")]
        for row in out["abilities"]:
            code = row["code"]
            if code not in ("R1.1", "R1.2"):
                continue
            row["meeting"] = {"sentences": [
                {"text": text, "evidence_ids": ids.get(code, [])[:1], "kind": "fact"}
                for text in sentences]}
            row["tags"] = (["积极资源", "确认发展需求"] if code == "R1.1"
                           else ["积极资源"])
        return out


def test_meeting_limit_two_tags(rdb, monkeypatch):
    model = _LongMeetingModel()
    monkeypatch.setattr(report_pipeline, "call_model", model)
    _report, version = generate(rdb)
    rows = version["doc"]["dims"]["R1"]["abilities"]
    assert len(rows["R1.1"]["meeting"]["text"]) == 75
    assert len(rows["R1.2"]["meeting"]["text"]) == 50
    assert any("R1.2 首次会议核实情况：超过 60 字" in item["message"]
               for item in version["manifest"]["adjustments"])


# ---------------------------------------------------------------------------
# §4.5 综合画像各栏上限
# ---------------------------------------------------------------------------
class _LongProfileModel(FakeModel):
    def _profile(self):
        out = super()._profile()
        text = _long()
        out["portrait"] = {d: text for d in ("R1", "R2", "R3", "R4")}
        out["findings"] = {k: {"finding": text, "meaning": text}
                           for k in ("resources", "needs", "open")}
        out["plan"] = [dict(row, goal=text, mentor=text, family=text, evidence=text)
                       for row in out["plan"]]
        out["review_advice"] = text
        return out


def test_profile_fields_capped(rdb, monkeypatch):
    model = _LongProfileModel()
    monkeypatch.setattr(report_pipeline, "call_model", model)
    _report, version = generate(rdb)
    assert all(len(text) <= limit for _p, _n, text, limit
               in report_checks.family_fields_with_limits(version["doc"]))


# ---------------------------------------------------------------------------
# §5 检查
# ---------------------------------------------------------------------------
def test_field_too_long_check():
    path = ["dims", "R1", "abilities", "R1.1", "meeting"]
    hits = [c for c in _checks(_doc_with_meeting("字" * 60 + "。"), "field_too_long")
            if c["path"] == path]
    assert hits and hits[0]["level"] == "review"
    assert not [c for c in _checks(_doc_with_meeting("字" * 59 + "。"), "field_too_long")
                if c["path"] == path]


def test_total_too_long_check():
    assert report_checks.ai_text_length(_doc_with_meeting("字" * 2999 + "。")) == 3000
    assert not _checks(_doc_with_meeting("字" * 2999 + "。"), "too_long")
    longer = _doc_with_meeting("字" * 3000 + "。")
    assert report_checks.ai_text_length(longer) == 3001
    assert _checks(longer, "too_long")


# ---------------------------------------------------------------------------
# §3 提示词
# ---------------------------------------------------------------------------
def test_prompts_carry_limits():
    assert "合计不超过 60 字" in report_prompts.DIM_PROMPT
    assert "最多 3 个" in report_prompts.DIM_PROMPT
    assert "不超过 40 字" in report_prompts.PROFILE_PROMPT
    assert "照段首标注填写" in report_prompts.MEETING_PROMPT
    assert "默认选 1–2 个最有代表性的事件" not in report_prompts.DIM_PROMPT


# ---------------------------------------------------------------------------
# 整份生成
# ---------------------------------------------------------------------------
class _LongEverythingModel(_LongProfileModel):
    def _dim(self, prompt):
        out = super()._dim(prompt)
        rows = [{"text": _sentence(40, "可能"), "evidence_ids": [], "kind": "inference"}
                for _ in range(3)]
        for row in out["abilities"]:
            row["meeting"] = {"sentences": [dict(r) for r in rows]}
        out["core_finding"] = {"sentences": [dict(r) for r in rows]}
        out["context_notes"] = {"sentences": [dict(r) for r in rows]}
        return out


def test_full_generate_is_short(rdb, monkeypatch):
    model = _LongEverythingModel()
    monkeypatch.setattr(report_pipeline, "call_model", model)
    _report, version = generate(rdb)
    doc = version["doc"]
    total = report_checks.ai_text_length(doc)
    assert total <= report_checks.TOTAL_MAX
