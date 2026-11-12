"""Task C：会议证据重排（全部虚构）。

抽取后按“直接 / 间接”重新匹配会议证据与能力；间接证据只进内部备注。
所有模型调用都换成固定回答，不访问真实模型。
"""
from __future__ import annotations

import json

from growth_talk.analysis import AnalysisError
import m1.report_store as report_store
from m1 import report_assessment, report_checks, report_pipeline, report_prompts
from test_m1_report_core import (FakeModel, TRANSCRIPT, fake, generate,  # noqa: F401
                                 make_report, rdb)
from test_m1_store import m1db  # noqa: F401

TEARS = "那次考砸以后我哭了，哭完才明白自己其实很难过。"
OTHER_NOTE = "家长说他最近写作业很吃力。"


def _evidence(eid, quote, codes, source="M1", speaker="学生", kind="具体行为事件"):
    return {"id": eid, "event_id": "evt-" + eid, "ability_codes": list(codes),
            "source": source, "location": "", "speaker": speaker, "type": kind,
            "quote": quote, "quote_verified": True, "interpretation": "", "limits": "",
            "status": "已确认"}


def _judgement(tag, eid):
    return {"tag": tag, "evidence_ids": [eid], "event_ids": ["evt-" + eid],
            "rationale": "虚构理由"}


class RerankModel:
    """按能力编号回答；一次调用覆盖一个维度的能力定义。"""

    def __init__(self, by_code):
        self.by_code = by_code
        self.calls = []

    def __call__(self, prompt):
        self.calls.append(prompt)
        abilities = json.loads(
            prompt.split("【能力定义】\n", 1)[1].split("\n【会议证据】\n", 1)[0])
        return {"abilities": [
            {"code": ability["code"],
             "items": [{"evidence_id": eid, "level": level, "reason": "虚构理由"}
                       for eid, level in self.by_code.get(ability["code"], [])]}
            for ability in abilities]}


def test_tears_evidence_directly_supports_emotion_identification_only(monkeypatch):
    evidence = [_evidence("e1", TEARS, ["R1.1", "R4.1"])]
    model = RerankModel({"R1.1": [("e1", "直接")], "R4.1": [("e1", "间接")]})
    monkeypatch.setattr(report_pipeline, "call_model", model)
    adjustments = []

    indirect = report_pipeline.step_rerank(evidence, adjustments)

    assert evidence[0]["ability_codes"] == ["R1.1"]
    assert indirect == {"R4.1": [TEARS]}
    assert adjustments == []
    assert len(model.calls) == 4                     # 四个维度各一次
    assert all("直接" in prompt and "间接" in prompt for prompt in model.calls)


def test_one_evidence_direct_for_at_most_three_abilities(monkeypatch):
    quote = "我上周把这件事跟同桌说了。"
    evidence = [_evidence("e1", quote, ["R1.1", "R1.2", "R1.3", "R1.4"])]
    model = RerankModel({code: [("e1", "直接")]
                         for code in ("R1.1", "R1.2", "R1.3", "R1.4")})
    monkeypatch.setattr(report_pipeline, "call_model", model)
    adjustments = []

    indirect = report_pipeline.step_rerank(evidence, adjustments)

    assert evidence[0]["ability_codes"] == ["R1.1", "R1.2", "R1.3"]
    assert indirect["R1.4"] == [quote]
    assert any("超过 3 项" in item["message"] for item in adjustments)


def test_indirect_evidence_only_reaches_internal_note(monkeypatch):
    evidence = [_evidence("e1", TEARS, ["R1.1", "R4.1"])]
    rerank = RerankModel({"R1.1": [("e1", "直接")], "R4.1": [("e1", "间接")]})
    monkeypatch.setattr(report_pipeline, "call_model", rerank)
    indirect = report_pipeline.step_rerank(evidence, [])

    monkeypatch.setattr(report_pipeline, "call_model", FakeModel())
    dims = report_pipeline.step_dims(report_pipeline.step_mapping({}), evidence, [], indirect)

    row = dims["R4"]["abilities"]["R4.1"]
    assert TEARS in row["internal_note"]
    assert TEARS not in row["meeting"]["text"]
    assert row["meeting"]["text"] == report_checks.NO_MEETING_TEXT


def test_other_material_only_positive_resource_is_information_insufficient():
    other = _evidence("e1", OTHER_NOTE, ["R1.1"], source="OTHER",
                      speaker="学生", kind="主观感受")
    raw = {"judgements": [_judgement("积极资源", "e1")]}
    result = report_assessment.resolve_assessment(raw, [other], "R1.1")

    assert result["tags"] == ["信息不足"]
    assert any("积极资源" in message and "没有直接的会议证据" in message
               for message in result["diagnostics"])


def test_possible_with_only_unconfirmed_speaker_is_information_insufficient():
    evidence = [_evidence("e1", TEARS, ["R1.1"], speaker="待确认", kind="主观感受")]
    raw = {"judgements": [_judgement("可能存在", "e1")]}
    result = report_assessment.resolve_assessment(raw, evidence, "R1.1")

    assert result["tags"] == ["信息不足"]
    assert any("只有他人观察" in message for message in result["diagnostics"])


def test_possible_with_student_self_report_is_kept():
    other = _evidence("e1", OTHER_NOTE, ["R1.1"], source="OTHER",
                      speaker="学生", kind="主观感受")
    raw = {"judgements": [_judgement("可能存在", "e1")]}
    assert report_assessment.resolve_assessment(raw, [other], "R1.1")["tags"] == ["可能存在"]


def test_possible_with_parent_behaviour_evidence_is_kept():
    parent = _evidence("e1", OTHER_NOTE, ["R1.1"], source="OTHER",
                       speaker="家长", kind="其他观察")
    raw = {"judgements": [_judgement("可能存在", "e1")]}
    assert report_assessment.resolve_assessment(raw, [parent], "R1.1")["tags"] == ["可能存在"]


def test_no_meeting_evidence_at_all_is_information_insufficient():
    raw = {"judgements": [_judgement("确认发展需求", "e1")]}
    assert report_assessment.resolve_assessment(raw, [], "R1.1")["tags"] == ["信息不足"]


def test_generation_reranks_once_per_dimension(rdb, fake):
    generate(rdb)
    calls = [prompt for prompt in fake.calls
             if prompt.startswith(report_prompts.TASK_RERANK)]
    assert len(calls) == 4
    for prompt in calls:
        abilities = json.loads(
            prompt.split("【能力定义】\n", 1)[1].split("\n【会议证据】\n", 1)[0])
        evidence = json.loads(prompt.split("【会议证据】\n", 1)[1])
        assert len({ability["code"][:2] for ability in abilities}) == 1
        assert evidence and all("ability_codes" not in view for view in evidence)


def test_rerank_failure_keeps_codes_and_does_not_block(rdb, monkeypatch):
    base = FakeModel()

    def ask(prompt):
        if prompt.startswith(report_prompts.TASK_RERANK):
            raise AnalysisError("超时")
        return base(prompt)

    monkeypatch.setattr(report_pipeline, "call_model", ask)
    report = make_report(rdb, transcript=TRANSCRIPT)

    version_id = report_pipeline.generate(rdb.prep_row["id"], actor_id=rdb.alice_id)
    saved = report_store.get_version(version_id)
    adjustments = saved["manifest"]["adjustments"]

    codes = {code for item in saved["evidence"] for code in item["ability_codes"]}
    assert {"R1.1", "R4.1"} <= codes                 # 沿用抽取时的编号
    assert sum("沿用抽取时的能力编号" in item["message"]
               for item in adjustments) == 4
    assert report_store.get_report_by_id(report["id"])["current_version_id"] == version_id
