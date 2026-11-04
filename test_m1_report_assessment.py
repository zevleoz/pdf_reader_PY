"""M1 判断层：事件 ID、中央标签规则与一次修正。

所有模型调用都是虚构回答；不访问真实 AI。
"""
from __future__ import annotations

import json
import re

from m1 import report_assessment, report_checks, report_kb, report_pipeline, report_prompts
from test_m1_report_core import (Q_HELP, _item, _messages, fake,  # noqa: F401
                                 generate, rdb)
from test_m1_store import m1db  # noqa: F401  临时库与虚构学生


def _evidence(eid, event, code="R1.1", kind="具体行为事件", speaker="学生",
              source="M1", status="已确认", verified=True):
    return {"id": eid, "event_id": event, "ability_codes": [code], "source": source,
            "location": "", "speaker": speaker, "type": kind, "quote": "例句" + eid,
            "quote_verified": verified, "interpretation": "", "limits": "", "status": status}


def _judge(tag, eid, event, rationale="示例判断理由"):
    return {"tag": tag, "evidence_ids": [eid], "event_ids": [event], "rationale": rationale}


def _rows(version):
    return {code: row for dim in version["doc"]["dims"].values()
            for code, row in dim["abilities"].items()}


def test_event_id_uses_shared_event_key_and_stable_fallback():
    items = report_pipeline.assign_ids([
        {"source": "M1", "event_key": "数学小测", "quote": "我上周没考好", "location": "第 3 段"},
        {"source": "M1", "event_key": "数学小测", "quote": "小测前我很紧张", "location": "第 4 段"},
        {"source": "M1", "quote": "重复引文", "location": "第 9 段"},
        {"source": "OTHER", "event_key": "数学小测", "quote": "家长补充", "location": "问卷"},
    ])
    assert items[0]["event_id"] == items[1]["event_id"]        # 同一事件共享
    repeated = report_pipeline.assign_ids(
        [{"source": "M1", "quote": "重复引文", "location": "第 9 段"}])[0]
    assert repeated["event_id"] == items[2]["event_id"]         # 无 key 时位置稳定
    assert items[3]["event_id"] != items[1]["event_id"]         # 不同来源不合并
    assert "event_key" not in items[0]


def test_double_tag_requires_two_events():
    evidence = [_evidence("e1", "evt-1"), _evidence("e2", "evt-2", kind="主观感受")]
    raw = {"judgements": [_judge("积极资源", "e1", "evt-1"),
                          _judge("可能存在", "e2", "evt-2")]}
    assert report_assessment.assessment_errors(raw, evidence, "R1.1") == []
    result = report_assessment.resolve_assessment(raw, evidence, "R1.1")
    assert result["tags"] == ["积极资源", "可能存在"]
    assert result["evidence_ids"] == ["e1", "e2"]


def test_double_tag_same_event_keeps_only_supported_resource():
    evidence = [_evidence("e1", "evt-1"), _evidence("e2", "evt-1", kind="主观感受")]
    raw = {"judgements": [_judge("积极资源", "e1", "evt-1"),
                          _judge("可能存在", "e2", "evt-1")]}
    assert report_assessment.assessment_errors(raw, evidence, "R1.1")
    result = report_assessment.resolve_assessment(raw, evidence, "R1.1")
    assert result["tags"] == ["积极资源"]
    assert any("同一事件" in message for message in result["diagnostics"])


def test_resource_and_confirmed_need_are_mutually_exclusive():
    evidence = [_evidence("e1", "evt-1"), _evidence("e2", "evt-2")]
    raw = {"judgements": [_judge("积极资源", "e1", "evt-1"),
                          _judge("确认发展需求", "e2", "evt-2")]}
    assert any("积极资源" in error and "确认发展需求" in error
               for error in report_assessment.assessment_errors(raw, evidence, "R1.1"))
    result = report_assessment.resolve_assessment(raw, evidence, "R1.1")
    assert result["tags"] == ["积极资源"]
    assert any("不与「确认发展需求」并列" in message
               for message in result["diagnostics"])


def test_assessment_prompt_disallows_resource_and_confirmed_need():
    prompt = report_prompts.ASSESS_PROMPT
    assert "积极资源不能与确认发展需求并列" in prompt
    assert "只允许“积极资源 + 确认发展需求”" not in prompt


def test_information_insufficient_never_combines():
    evidence = [_evidence("e1", "evt-1")]
    raw = {"judgements": [_judge("信息不足", "e1", "evt-1"), _judge("积极资源", "e1", "evt-1")]}
    result = report_assessment.resolve_assessment(raw, evidence, "R1.1")
    assert result["tags"] == ["积极资源"]
    no_evidence = {"judgements": [{"tag": "信息不足", "evidence_ids": [],
                                   "event_ids": [], "rationale": "没有证据"}]}
    assert report_assessment.resolve_assessment(no_evidence, [], "R1.1")["tags"] == ["信息不足"]


def test_confirmed_need_demotes_without_clear_behaviour_evidence():
    vague = [_evidence("e1", "evt-1", kind="主观感受", speaker="待确认")]
    raw = {"judgements": [_judge("确认发展需求", "e1", "evt-1")]}
    assert report_assessment.resolve_assessment(raw, vague, "R1.1")["tags"] == ["可能存在"]
    empty = [_evidence("e1", "evt-1", status="不采用", verified=False)]
    assert report_assessment.resolve_assessment(raw, empty, "R1.1")["tags"] == ["信息不足"]


def test_mentor_behaviour_alone_cannot_confirm_need():
    raw = {"judgements": [_judge("确认发展需求", "e1", "evt-1")]}
    mentor = [_evidence("e1", "evt-1", speaker="导师")]
    assert report_assessment.resolve_assessment(raw, mentor, "R1.1")["tags"] == ["可能存在"]
    for speaker in ("学生", "家长"):
        valid = [_evidence("e1", "evt-1", speaker=speaker)]
        assert report_assessment.resolve_assessment(raw, valid, "R1.1")["tags"] == ["确认发展需求"]


def test_extraction_prompts_do_not_offload_filtering_to_mentor():
    for prompt in (report_prompts.MEETING_PROMPT, report_prompts.FIRST_TOUCH_PROMPT):
        assert "宁可多提取一些" not in prompt
        assert "供导师逐条筛选" not in prompt
        assert "导师会审核每一条" not in prompt
        assert "完整" in prompt and "精确" in prompt


def test_assess_prompt_rejects_mentor_evidence_for_need():
    prompt = report_prompts.ASSESS_PROMPT
    assert "导师" in prompt
    assert "不能作为“确认发展需求”的决定性证据" in prompt


def test_invalid_candidate_can_be_corrected_once(rdb, fake):
    fake.meeting_items = fake.meeting_items + [
        _item(Q_HELP, "学生", "具体行为事件", ["R1.2"])]
    calls = {"n": 0}

    def flaky(ability):
        views = ability["meeting_evidence"]
        concrete = next(e for e in views if e["type"] == "具体行为事件")
        calls["n"] += 1
        if calls["n"] == 1:                # 第一次：两个标签都指向同一事件
            return [_judge("积极资源", concrete["id"], concrete["event_id"]),
                    _judge("可能存在", concrete["id"], concrete["event_id"])]
        return [_judge("积极资源", concrete["id"], concrete["event_id"]),
                _judge("可能存在", views[0]["id"], views[0]["event_id"])]

    fake.assessment_overrides = {"R1.2": flaky}
    _r, version = generate(rdb)
    assert calls["n"] == 2                 # 同维度只修正一次
    assert _rows(version)["R1.2"]["tags"] == ["积极资源", "可能存在"]
    assert report_kb.tags_problem(_rows(version)["R1.2"]["tags"]) == ""


def test_persistent_invalid_assessment_uses_central_fallback(rdb, fake):
    def same_event(ability):
        view = next(e for e in ability["meeting_evidence"] if e["type"] == "具体行为事件")
        return [_judge("积极资源", view["id"], view["event_id"]),
                _judge("可能存在", view["id"], view["event_id"])]

    fake.meeting_items = fake.meeting_items + [
        _item(Q_HELP, "学生", "具体行为事件", ["R1.2"])]
    fake.assessment_overrides = {"R1.2": same_event}
    _r, version = generate(rdb)
    row = _rows(version)["R1.2"]
    assert row["tags"] == ["积极资源"] and report_kb.tags_problem(row["tags"]) == ""
    assert any("同一事件" in message for message in _messages(version))
    # 写作收到的是中央归一后的标签
    writes = [p for p in fake.calls
              if p.startswith(report_prompts.TASK_DIM) and '"R1.2"' in p]
    assert writes and '"tags": ["积极资源"]' in writes[-1]


def test_profile_receives_resolved_tags_not_model_candidate(rdb, fake):
    def resource_without_support(ability):
        guided = [e for e in ability["meeting_evidence"] if e["type"] == "假设性回应"][0]
        return [_judge("积极资源", guided["id"], guided["event_id"])]

    fake.assessment_overrides = {"R1.2": resource_without_support}
    _r, version = generate(rdb)
    assert _rows(version)["R1.2"]["tags"] == ["信息不足"]       # 候选被中央规则推翻
    profile = next(p for p in fake.calls if p.startswith(report_prompts.TASK_PROFILE))
    start = profile.index('{"code": "R1.2"')
    row = json.loads(profile[start:profile.index("}", start) + 1])
    assert row["tags"] == ["信息不足"]
    assert "积极资源" not in row["tags"]


def test_meeting_prompt_has_no_speaker_and_explains_speech_act():
    prompt = report_prompts.MEETING_PROMPT
    assert '"speaker"' not in prompt and "speaker" not in prompt
    assert '"event_key"' in prompt
    assert "speech_act" in prompt
    assert "引导下回答不得写成学生日常自主表现" in prompt


def test_unlocatable_quote_is_discarded_without_manual_block(rdb, fake):
    _r, version = generate(rdb)
    discarded = [e for e in version["evidence"] if e["status"] == "不采用"]
    assert discarded and all(not report_checks.supports_judgement(e) for e in discarded)
    assert [c for c in version["checks"] if c["code"] in ("quote_unverified", "no_tag")
            and c["level"] == "block"] == []


def test_all_abilities_keep_a_legal_tag(rdb, fake):
    _r, version = generate(rdb)
    rows = _rows(version)
    assert len(rows) == 18
    assert all(row["tags"] and report_kb.tags_problem(row["tags"]) == ""
               for row in rows.values())


def test_assessment_prompt_does_not_ask_for_writing():
    prompt = report_prompts.ASSESS_PROMPT
    assert report_prompts.TASK_ASSESS in prompt
    assert "meeting" not in prompt or "不写家长版文字" in prompt
    assert "final_assessment" not in prompt
    assert "rationale" in prompt
    assert re.search(r"event_ids", prompt)
