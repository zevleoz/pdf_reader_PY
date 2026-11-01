"""会后报告 S2-P5 修复 2–5：引文覆盖全部字段、未核实证据、导师标注、新的提示级检查。"""
from __future__ import annotations

import copy

import pytest

from m1 import report_checks, report_pipeline
from test_m1_api import login_as  # noqa: F401
from test_m1_report_core import (Q_BODY, Q_FAKE, Q_HIDE, Q_MENTOR, TRANSCRIPT,  # noqa: F401
                                 FakeModel, _clean, _item, _mutate, fake, generate, rdb)
from test_m1_store import m1db  # noqa: F401


def _checks(report, version):
    return report_checks.run_checks(report, version, first_touch_text="")


def _codes(report, version, level=None):
    return {c["code"] for c in _checks(report, version) if level in (None, c["level"])}


def _ev(version, code, **kw):
    ev = {"id": "e99", "source": "M1", "ability_codes": [code], "speaker": "学生",
          "type": "具体行为事件", "quote": Q_BODY, "quote_verified": True,
          "status": "已确认", "interpretation": "", "limits": "", "location": ""}
    ev.update(kw)
    return ev


# ---- Fix 2 -----------------------------------------------------------------
FAKE_Q = "“我每天晚上都会反复做噩梦”"
REAL_Q = "“我没跟同学说，一个人趴在桌上”"


def _set(doc, where):
    if where == "portrait":
        doc["portrait"]["R1"] = "观察" + FAKE_Q
    elif where == "findings":
        doc["findings"]["needs"]["finding"] = "发现" + FAKE_Q
    elif where == "plan":
        doc["plan"][0]["goal"] = "目标" + FAKE_Q
    else:
        doc["review_advice"] = "建议" + FAKE_Q


@pytest.mark.parametrize("where", ["portrait", "findings", "plan", "review"])
def test_fake_quote_in_every_family_field_blocks(rdb, fake, where):
    report, version = _clean(rdb, fake)
    assert "quote_unverified" not in _codes(report, version)
    version = _mutate(version, lambda v: _set(v["doc"], where))
    assert "quote_unverified" in _codes(report, version, "block")


def test_real_quote_in_family_field_does_not_fail_verification(rdb, fake):
    report, version = _clean(rdb, fake)
    version = _mutate(version, lambda v: v["doc"].update(review_advice="建议" + REAL_Q))
    assert "quote_unverified" not in _codes(report, version)


def test_profile_prompt_forbids_quotes():
    from m1 import report_prompts
    assert "综合画像和方案中不要使用引号引用原话。" in report_prompts.PROFILE_PROMPT


# ---- Fix 3 -----------------------------------------------------------------
def test_supports_judgement():
    assert not report_checks.supports_judgement({"status": "不采用", "quote_verified": True})
    assert not report_checks.supports_judgement({"status": "待核实", "quote_verified": False})
    assert report_checks.supports_judgement({"status": "待核实", "quote_verified": True})
    assert report_checks.supports_judgement({"status": "已确认", "quote_verified": False})


def test_need_downgraded_when_only_unverified_evidence(rdb, fake):
    fake.meeting_items = [_item(Q_BODY, "学生", "具体行为事件", ["R1.1"])]
    orig = report_pipeline.extract_items

    def unverified(*a, **k):
        items = orig(*a, **k)
        for i in items:
            i["quote_verified"] = False
            i["status"] = "待核实"
        return items
    report_pipeline.extract_items, saved = unverified, orig
    try:
        fake.overrides["R1.1"] = {"tags": ["确认发展需求"]}
        _r, version = generate(rdb, fake)
    finally:
        report_pipeline.extract_items = saved
    tags = version["doc"]["dims"]["R1"]["abilities"]["R1.1"]["tags"]
    assert "确认发展需求" not in tags


def _need_version(version, ev):
    version = copy.deepcopy(version)
    row = version["doc"]["dims"]["R1"]["abilities"]["R1.1"]
    row["tags"] = ["确认发展需求"]
    version["evidence"] = [ev]
    return version


def test_need_speaker_blocks_unverified_and_confirm_clears(rdb, fake):
    report, version = _clean(rdb, fake)
    bad = _need_version(version, _ev(version, "R1.1", quote_verified=False, status="待核实"))
    assert "need_speaker" in _codes(report, bad, "block")
    ok = _need_version(version, _ev(version, "R1.1", quote_verified=False, status="已确认"))
    assert "need_speaker" not in _codes(report, ok)


# ---- Fix 4 -----------------------------------------------------------------
def test_mentor_labelled():
    idx = report_checks.TextIndex(TRANSCRIPT + "\n老师 00:05：别担心。\nMentor: hello there\n"
                                  "学生：第一段\n学生：第二段")
    assert report_checks.mentor_labelled(idx, Q_MENTOR)
    assert not report_checks.mentor_labelled(idx, Q_BODY)
    assert report_checks.mentor_labelled(idx, "别担心")
    assert report_checks.mentor_labelled(idx, "hello there")
    assert not report_checks.mentor_labelled(idx, "第一段学生第二段")   # 跨段
    assert not report_checks.mentor_labelled(idx, "不存在的话")


def test_pipeline_moves_mentor_labelled_student_to_pending(rdb, fake):
    fake.meeting_items = [_item(Q_MENTOR, "学生", "具体行为事件", ["R1.1"]),
                          _item(Q_BODY, "学生", "具体行为事件", ["R1.1"])]
    _r, version = generate(rdb, fake)
    by_quote = {e["quote"]: e for e in version["evidence"]}
    mentor = by_quote[Q_MENTOR]
    assert mentor["speaker"] == "待确认" and mentor["status"] == "待核实"
    assert "逐字稿标注为导师" in mentor["limits"]
    assert by_quote[Q_BODY]["speaker"] == "学生"


def _quote_version(version, evidence, src="ai", quote=Q_BODY):
    version = copy.deepcopy(version)
    version["doc"]["dims"]["R1"]["abilities"]["R1.1"]["meeting"] = {
        "text": "学生说“%s”。" % quote, "src": src}
    version["evidence"] = evidence
    return version


def _quote_checks(report, version):
    return [c for c in _checks(report, version) if c["code"].startswith("quote_")]


def test_quote_all_discarded_blocks(rdb, fake):
    report, version = _clean(rdb, fake)
    v = _quote_version(version, [_ev(version, "R1.1", status="不采用")])
    c = _quote_checks(report, v)
    assert [(x["level"], x["code"]) for x in c] == [("block", "quote_speaker")]
    assert "不采用" in c[0]["message"]


def test_quote_mentor_or_pending_speaker_blocks(rdb, fake):
    report, version = _clean(rdb, fake)
    for speaker in ("导师", "待确认"):
        v = _quote_version(version, [_ev(version, "R1.1", speaker=speaker)])
        assert [(x["level"], x["code"]) for x in _quote_checks(report, v)] == \
            [("block", "quote_speaker")]
    v = _quote_version(version, [_ev(version, "R1.1", speaker="学生")])
    assert _quote_checks(report, v) == []


def test_quote_no_match_mentor_labelled_blocks(rdb, fake):
    report, version = _clean(rdb, fake)
    v = _quote_version(version, [], quote=Q_MENTOR)
    assert [(x["level"], x["code"]) for x in _quote_checks(report, v)] == \
        [("block", "quote_speaker")]


def test_quote_no_match_ai_blocks_edited_reviews(rdb, fake):
    report, version = _clean(rdb, fake)
    ai = _quote_checks(report, _quote_version(version, [], src="ai"))
    assert [(x["level"], x["code"]) for x in ai] == [("block", "quote_no_evidence")]
    ed = _quote_checks(report, _quote_version(version, [], src="edited"))
    assert [(x["level"], x["code"]) for x in ed] == [("review", "quote_no_evidence")]


def test_review_case_mentor_line_marked_student_blocks_and_clears(rdb, fake):
    fake.meeting_items = [_item(Q_MENTOR, "学生", "具体行为事件", ["R1.1"])]
    report, version = _clean(rdb, fake)
    v = _quote_version(version, version["evidence"], quote=Q_MENTOR)
    assert "quote_speaker" in _codes(report, v, "block")
    removed = _quote_version(version, version["evidence"], quote=Q_BODY)
    assert "quote_speaker" not in _codes(report, removed)


# ---- Fix 5 -----------------------------------------------------------------
def test_tag_evidence_notice_does_not_block(rdb, fake):
    report, version = _clean(rdb, fake)
    v = copy.deepcopy(version)
    v["evidence"] = []
    row = v["doc"]["dims"]["R1"]["abilities"]
    row["R1.1"]["tags"] = ["确认发展需求"]
    row["R1.2"]["tags"] = ["积极资源"]
    row["R1.3"]["tags"] = ["暂未发现"]
    checks = [c for c in _checks(report, v) if c["code"] == "tag_evidence" and c["path"][1] == "R1"]
    assert len(checks) == 3 and {c["level"] for c in checks} == {"review"}
    assert "tag_evidence" not in _codes(report, v, "block")


def test_family_code_notice_does_not_block(rdb, fake):
    report, version = _clean(rdb, fake)
    code = next(iter(version["y4_ratings"]))
    for text in ("参考指标 %s 的结果" % code, "见证据 e12"):
        v = copy.deepcopy(version)
        v["doc"]["review_advice"] = text
        got = [c for c in _checks(report, v) if c["code"] == "family_code"]
        assert got and got[0]["level"] == "review"
        assert "family_code" not in _codes(report, v, "block")
    assert "family_code" not in _codes(report, version)
