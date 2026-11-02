"""会后报告 S2-P6：真实输出修复（§1–§11）的测试。

全部替换 ``call_model``；不访问真实模型、不连服务器。
"""
from __future__ import annotations

import json
import re

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import ai_writing
import growth_talk_store as _gt
from app_utils import BASE_DIR
from growth_talk.analysis import AnalysisError
from m1 import report_checks, report_kb, report_pipeline, report_prompts
from test_m1_report_core import (Q_BODY, Q_HELP, Q_HIDE, Q_MENTOR, TRANSCRIPT,  # noqa: F401
                                 _codes, _item, _mutate, client, fake, generate,
                                 inline_jobs, rdb, url)
from test_m1_store import m1db  # noqa: F401

MAP = report_kb.ability_map()
CLOSING = "。！？!?…：:；;”\"」』）)"


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _ev(quote, code="R1.1", speaker="学生", kind="具体行为事件", status="已确认",
        verified=True, source="M1", eid="e1"):
    return {"id": eid, "ability_codes": [code], "source": source, "location": "",
            "speaker": speaker, "type": kind, "quote": quote, "quote_verified": verified,
            "interpretation": "", "limits": "", "status": status}


def _mini(text="", code="R1.1", dim="R1", tags=None, ratings=None):
    row = {"meeting": {"text": text, "src": "ai"}}
    if tags is not None:
        row["tags"] = list(tags)
    return {"doc": {"dims": {dim: {"abilities": {code: row}}}},
            "evidence": [], "y4_ratings": dict(ratings or {}), "manifest": {}}


def _version(doc_version, evidence=()):
    out = dict(doc_version)
    out["evidence"] = list(evidence)
    return out


def _got(version, code, level=None, transcript=TRANSCRIPT):
    report = {"transcript_text": transcript, "safety": []}
    return [c for c in report_checks.run_checks(report, version, first_touch_text="")
            if c["code"] == code and level in (None, c["level"])]


def _family_texts(doc):
    return [(path, text) for path, text in report_checks.family_fields(doc) if text]


def _dim_payload_codes(prompt):
    payload = json.loads(prompt.split("【能力与资料】\n", 1)[1])
    return [row["code"] for row in payload]


def _brief_codes(prompt):
    """§3 的提取提示词以能力列表 JSON 开头。"""
    return [row["code"] for row in json.loads(prompt.split("\n", 1)[0])]


# ---------------------------------------------------------------------------
# §1 单引号里的编造原话（blocker）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("left,right", [("‘", "’"), ("『", "』")])
def test_made_up_quote_in_single_marks_blocks(left, right):
    version = _mini("学生说%s根本没有说过的话%s。" % (left, right))
    hit = _got(version, "quote_unverified")
    assert hit and hit[0]["level"] == "block"


def test_real_quote_in_single_marks_passes():
    version = _version(_mini("学生说‘%s’。" % Q_HIDE), [_ev(Q_HIDE)])
    assert _got(version, "quote_unverified") == []
    assert _got(version, "quote_speaker") == []


def test_family_style_requires_double_quotes_only():
    rule = "引用原话只能用中文双引号“”，不要用单引号；不是原话就不要加任何引号。"
    assert rule in report_prompts.FAMILY_STYLE


# ---------------------------------------------------------------------------
# §2 家庭版里的证据编号（blocker）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["e4中提到的行为。", "见证据 e12。", "e4。"])
def test_evidence_ids_in_family_text_block(text):
    hit = _got(_mini(text), "family_evidence_id")
    assert hit and hit[0]["level"] == "block"
    assert hit[0]["path"] == ["dims", "R1", "abilities", "R1.1", "meeting"]


@pytest.mark.parametrize("text", ["the teacher", "e4x 的说明。", "E4 的做法。"])
def test_non_evidence_ids_do_not_block(text):
    assert _got(_mini(text), "family_evidence_id") == []


def test_y4_code_next_to_chinese_is_review():
    version = _mini("参考 013，的结果。", ratings={"013": {"label": "x"}})
    hit = _got(version, "family_code")
    assert hit and hit[0]["level"] == "review"
    assert hit[0]["path"] == ["dims", "R1", "abilities", "R1.1", "meeting"]


# ---------------------------------------------------------------------------
# §3 每个维度一次提取；跨维度合并（blocker）
# ---------------------------------------------------------------------------
class BriefModel:
    """按提示词里的能力列表返回：用该维度第一项能力编码来标记这一次调用。"""

    def __init__(self, speakers=None):
        self.calls = []
        self.speakers = speakers or {}

    def __call__(self, prompt):
        self.calls.append(prompt)
        codes = _brief_codes(prompt)
        dim = "R" + codes[0][1]
        return {"items": [_item(Q_HELP, self.speakers.get(dim, "学生"),
                                "具体行为事件", [codes[0]])]}


def test_each_dimension_asked_once_and_codes_merged(monkeypatch):
    model = BriefModel()
    monkeypatch.setattr(report_pipeline, "call_model", model)
    items = report_pipeline.extract_items(TRANSCRIPT, "%s\n%s", (), "M1", "逐字稿")
    assert len(model.calls) == 4
    seen = set()
    for prompt in model.calls:
        seen |= set(_brief_codes(prompt))
    assert len(seen) == 18
    assert len(items) == 1
    first = {dim: [c for c, info in MAP.items() if info["dim"] == dim][0]
             for dim in ("R1", "R2", "R3", "R4")}
    assert set(items[0]["ability_codes"]) == set(first.values())
    assert items[0]["speaker"] == "学生" and items[0]["status"] == "已确认"


def test_dimension_speaker_disagreement_becomes_pending(monkeypatch):
    model = BriefModel(speakers={"R2": "导师"})
    monkeypatch.setattr(report_pipeline, "call_model", model)
    items = report_pipeline.extract_items(TRANSCRIPT, "%s\n%s", (), "M1", "逐字稿")
    assert len(items) == 1
    assert items[0]["speaker"] == "待确认" and items[0]["status"] == "待核实"


# ---------------------------------------------------------------------------
# §4 漏掉的能力单独追问一次
# ---------------------------------------------------------------------------
class OmitModel:
    def __init__(self, omit, obey_follow_up=True):
        self.omit = list(omit)
        self.obey_follow_up = obey_follow_up
        self.calls = []
        self.payloads = []

    def __call__(self, prompt):
        self.calls.append(prompt)
        codes = _dim_payload_codes(prompt)
        self.payloads.append(codes)
        follow_up = codes == self.omit
        keep = [c for c in codes if c not in self.omit or (follow_up and self.obey_follow_up)]
        return {"abilities": [{"code": c, "y4_selected": [], "other_clues": "",
                              "meeting": {"sentences": []}, "tags": ["信息不足"],
                              "evidence_ids": []} for c in keep],
                "core_finding": {"sentences": []}, "context_notes": {"sentences": []}}


def test_missing_abilities_get_one_follow_up(monkeypatch):
    model = OmitModel(["R1.3", "R1.4"])
    monkeypatch.setattr(report_pipeline, "call_model", model)
    dims = report_pipeline.step_dims(report_pipeline.step_mapping({}), [], [])
    r1 = [codes for codes in model.payloads if codes and codes[0][1] == "1"]
    assert len(r1) == 2 and r1[1] == ["R1.3", "R1.4"]
    assert dims["R1"]["abilities"]["R1.3"]["tags"] == ["信息不足"]
    assert dims["R1"]["abilities"]["R1.4"]["tags"] == ["信息不足"]


def test_still_missing_abilities_stay_empty_and_no_tag_stands(monkeypatch):
    model = OmitModel(["R1.3", "R1.4"], obey_follow_up=False)
    monkeypatch.setattr(report_pipeline, "call_model", model)
    dims = report_pipeline.step_dims(report_pipeline.step_mapping({}), [], [])
    assert dims["R1"]["abilities"]["R1.3"]["tags"] == []
    assert dims["R1"]["abilities"]["R1.4"]["tags"] == []
    version = {"doc": {"dims": dims}, "evidence": [], "manifest": {}}
    hit = _got(version, "no_tag")
    assert any(c["path"] == ["dims", "R1", "abilities", "R1.3", "tags"] for c in hit)
    assert all(c["level"] == "block" for c in hit)


# ---------------------------------------------------------------------------
# §5 分析步骤只看到可支持判断的证据
# ---------------------------------------------------------------------------
def test_dim_payload_only_passes_supported_items():
    evidence = [
        _ev("我心跳很快", eid="e1"),
        _ev("我心跳很快", eid="e2", status="待核实", verified=False),
        _ev("我心跳很快", eid="e3", status="不采用"),
        _ev("会主动找老师", eid="e4", source="OTHER", speaker="家长", kind="其他观察"),
    ]
    rows = report_pipeline._dim_payload("R1", report_pipeline.step_mapping({}), evidence)
    row = next(r for r in rows if r["code"] == "R1.1")
    assert [e["id"] for e in row["meeting_evidence"]] == ["e1"]
    assert set(row["meeting_evidence"][0]) == {"id", "speaker", "type", "quote",
                                               "interpretation", "limits"}
    assert [e["id"] for e in row["first_touch_and_other"]] == ["e4"]
    assert set(row["first_touch_and_other"][0]) == {
        "id", "speaker", "type", "quote", "interpretation", "limits", "source"}
    assert "quote_verified" not in json.dumps(rows, ensure_ascii=False)
    assert "status" not in json.dumps(rows, ensure_ascii=False)


@pytest.mark.parametrize("text", ["", report_checks.NO_MEETING_TEXT])
def test_meeting_unused_is_a_review_item(text):
    version = _version(_mini(text, code="R2.1", dim="R2"), [_ev("我独自待着", code="R2.1")])
    hit = _got(version, "meeting_unused")
    assert hit and hit[0]["level"] == "review"
    assert hit[0]["path"] == ["dims", "R2", "abilities", "R2.1", "meeting"]


def test_meeting_unused_needs_supported_m1_item():
    version = _version(_mini("", code="R2.1", dim="R2"),
                       [_ev("我独自待着", code="R2.1", status="待核实", verified=False)])
    assert _got(version, "meeting_unused") == []


# ---------------------------------------------------------------------------
# §6 家长版语言
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("word", ["待核实", "未核实", "证据条目", "证据编号", "数据质量",
                                 "零证据", "零会议证据", "quote_verified", "First Touch记录"])
def test_process_word_is_a_review_item(word):
    hit = _got(_mini("这里有 %s 的内容。" % word), "process_word")
    assert hit and hit[0]["level"] == "review" and word in hit[0]["message"]


def test_family_style_plain_language_rules():
    for line in ("不要写系统或流程用语，例如：待核实、未核实、证据条目、证据编号、数据质量、"
                 "零证据、标注、quote_verified。",
                 "资料不足时用一句平实的话说明还需要进一步了解，不要把“缺少资料”写成对学生的发现。",
                 "句子要短，家长一读就懂；不要堆砌术语和抽象名词。"):
        assert line in report_prompts.FAMILY_STYLE
    assert report_prompts.FAMILY_STYLE.startswith(ai_writing.rules_block())


# ---------------------------------------------------------------------------
# §7 综合判断与方案
# ---------------------------------------------------------------------------
def test_double_tag_needs_two_supported_items():
    row = _mini("", code="R2.3", dim="R2", tags=["积极资源", "可能存在"])
    one = _version(row, [_ev("我有时会走神", code="R2.3")])
    hit = _got(one, "double_tag_evidence")
    assert hit and hit[0]["level"] == "review" and hit[0]["path"][:2] == ["dims", "R2"]
    two = _version(row, [_ev("我有时会走神", code="R2.3", eid="e1"),
                         _ev("我会先深呼吸", code="R2.3", eid="e2")])
    assert _got(two, "double_tag_evidence") == []


def test_dim_prompt_tag_rules():
    assert "双标签要求两个不同情境、各有证据；同一事件不能同时支持两个标签。" in \
        report_prompts.DIM_PROMPT
    assert "积极资源和发展需求都要写进 meeting，并说明分别出现在什么情境。" in \
        report_prompts.DIM_PROMPT


def test_profile_prompt_plan_rules():
    for line in ("关键发展需求只能来自下面标记为“确认发展需求”或“可能存在”的能力，"
                 "不能只凭 Y4 或资料不足得出。没有这类能力时，如实写明目前没有确认的发展需求。",
                 "阶段目标必须针对学生尚未做到的行为；逐字稿已显示学生能做到的，不要作为目标。",
                 "综合画像不能与各能力的分析矛盾。",
                 "每格尽量不超过 80 字。"):
        assert line in report_prompts.PROFILE_PROMPT


# ---------------------------------------------------------------------------
# §8 单字证据引文不能挡下导师的话
# ---------------------------------------------------------------------------
def test_one_char_evidence_quote_does_not_mask_mentor_sentence():
    version = _version(_mini("老师问过“%s”。" % Q_MENTOR), [_ev("你")])
    hit = _got(version, "quote_speaker")
    assert hit and hit[0]["level"] == "block"
    assert _got(version, "quote_no_evidence") == []


def test_short_family_quote_inside_evidence_quote_still_matches():
    version = _version(_mini("学生说“心跳很快”。"), [_ev(Q_BODY)])
    assert _got(version, "quote_speaker") == []
    assert _got(version, "quote_no_evidence") == []


# ---------------------------------------------------------------------------
# §9 附录另起一页
# ---------------------------------------------------------------------------
def test_appendix_starts_on_a_new_page():
    css = (BASE_DIR / "static" / "m1" / "report_print.css").read_text("utf-8")
    rules = [m.group(1) for m in re.finditer(r"\.appendix\s*\{([^}]*)\}", css)]
    assert rules and any("break-before: page" in body for body in rules)
    assert ".draftmark::after" in css


# ---------------------------------------------------------------------------
# §10 写作标准与事实核对
# ---------------------------------------------------------------------------
def test_fact_unsupported_blocks_and_edit_clears(rdb, fake):
    fake.unsupported = ("下课",)
    fake.overrides = {"R1.1": {"meeting": {"sentences": [
        {"text": "学生下课后在教室待着。", "evidence_ids": ["e1"], "kind": "fact"}]}}}
    report, version = generate(rdb)
    assert version["doc"]["guard"]["status"] == "checked"
    path = ["dims", "R1", "abilities", "R1.1", "meeting"]
    hit = [c for c in version["checks"] if c["code"] == "fact_unsupported"]
    assert len(hit) == 1 and hit[0]["level"] == "block" and hit[0]["path"] == path
    assert "下课" in hit[0]["message"]
    edited = _mutate(version, lambda v: v["doc"]["dims"]["R1"]["abilities"]["R1.1"]
                     ["meeting"].update(src="edited"))
    assert "fact_unsupported" not in _codes(report, edited, "block")


def test_fact_sentence_without_evidence_is_dropped():
    adjustments = []
    raw = {"sentences": [
        {"text": "学生下课后一个人在教室待着", "evidence_ids": [], "kind": "fact"},
        {"text": "学生可能有时会走神", "evidence_ids": [], "kind": "inference"},
        {"text": "学生有时会走神", "evidence_ids": [], "kind": "inference"},
        {"text": "学生说可以试试", "evidence_ids": ["e1", "e2"], "kind": "fact"}]}
    out = report_pipeline._sentences(raw, {"e1"}, ["dims", "R1"], adjustments,
                                     "R1", report_checks.NO_MEETING_TEXT)
    assert out["text"] == "学生可能有时会走神。学生说可以试试。"
    assert out["sentences"][-1]["evidence_ids"] == ["e1"]
    messages = [a["message"] for a in adjustments]
    assert "R1：事实句没有有效证据，已删除" in messages
    assert "R1：推断句没有留有余地，已删除" in messages
    empty = report_pipeline._sentences({"sentences": []}, {"e1"}, ["dims", "R1"], [],
                                       "R1", report_checks.NO_MEETING_TEXT)
    assert empty["text"] == report_checks.NO_MEETING_TEXT


def test_guard_failure_blocks_and_is_not_silent(rdb, fake, monkeypatch):
    original = fake.__call__

    def no_check(prompt):
        if prompt.startswith("你是事实核对员") or \
                prompt.startswith("下面这段文字有几处没有资料依据"):
            raise AnalysisError("超时")
        return original(prompt)
    monkeypatch.setattr(report_pipeline, "call_model", no_check)
    report, version = generate(rdb)
    assert version["doc"]["guard"]["status"] in ("partial", "skipped")
    hit = [c for c in version["checks"] if c["code"] == "fact_unchecked"]
    assert hit and hit[0]["level"] == "block"
    assert hit[0]["message"] == "部分内容未完成事实核对，请人工核对。"


def test_confirm_flag_route_clears_the_block(client, rdb, fake, inline_jobs):
    fake.unsupported = ("下课",)
    fake.overrides = {"R1.1": {"meeting": {"sentences": [
        {"text": "学生下课后一个人在教室待着。", "evidence_ids": ["e1"], "kind": "fact"}]}}}
    from test_m1_report_core import generated_via_api
    payload = generated_via_api(client, rdb, fake, inline_jobs)
    rev = payload["report"]["rev"]
    path = ["dims", "R1", "abilities", "R1.1", "meeting"]
    assert any(c["code"] == "fact_unsupported" for c in payload["checks"])

    assert client.post(url(rdb, "/confirm-flag"), json={"path": path}).status_code == 400
    wrong = client.post(url(rdb, "/confirm-flag"), json={"rev": rev, "path": ["review_advice"]})
    assert wrong.status_code == 404

    res = client.post(url(rdb, "/confirm-flag"), json={"rev": rev, "path": path})
    assert res.status_code == 200
    body = res.get_json()
    assert body["status"] == "reviewing" and body["rev"] == rev + 1
    assert "fact_unsupported" not in {c["code"] for c in body["checks"]}
    reloaded = client.get(url(rdb)).get_json()
    assert reloaded["doc"]["guard_ack"] == [path]
    with Session(rdb.engine) as sess:
        actions = [r.action for r in sess.execute(select(_gt.AuditLog)).scalars()]
    assert "m1.report_confirm_flag" in actions


# ---------------------------------------------------------------------------
# §11 证据过滤规则
# ---------------------------------------------------------------------------
LESSON_TRANSCRIPT = "\n".join([
    "导师：我们先聊聊最近的事。",
    "学生：上周有一次，我上台前心跳很快。",
    "导师：是不是怕同学笑你？",
    "学生：嗯，可能吧，我不确定。",
    "导师：如果下次再紧张，你会怎么做？",
    "学生：我会先深呼吸。",
    "导师：如果下次再这样，你觉得呢？",
    "学生：上个月我也这样，那次是演讲比赛。",
    "导师：你当时是怎么想的？",
    "学生：我不对，其实我是怕忘词。",
    "导师：我觉得她是不敢表达。",
])


class LessonModel:
    def __init__(self, items):
        self.items = items
        self.calls = []

    def __call__(self, prompt):
        self.calls.append(prompt)
        return {"items": [dict(item) for item in self.items]}


def test_m1_evidence_rules_on_a_short_transcript(monkeypatch):
    items = [
        _item("我觉得她是不敢表达", "导师", "其他观察", ["R1.1"]),
        _item("嗯", "学生", "其他观察", ["R1.1"]),
        _item("可能吧，我不确定", "学生", "自我评价", ["R1.2"]),
        _item("我会先深呼吸", "学生", "具体行为事件", ["R1.2"]),
        _item("上个月我也这样，那次是演讲比赛", "学生", "具体行为事件", ["R1.2"]),
        _item("我不对，其实我是怕忘词", "学生", "自我评价", ["R1.3"]),
    ]
    model = LessonModel(items)
    monkeypatch.setattr(report_pipeline, "call_model", model)
    found = report_pipeline.extract_items(LESSON_TRANSCRIPT, "%s\n%s", (), "M1", "逐字稿")
    by_quote = {item["quote"]: item for item in found}
    assert set(by_quote) == {"我会先深呼吸", "上个月我也这样，那次是演讲比赛", "其实我是怕忘词"}
    assert by_quote["我会先深呼吸"]["type"] == "假设性回应"
    assert by_quote["上个月我也这样，那次是演讲比赛"]["type"] == "具体行为事件"
    assert by_quote["其实我是怕忘词"]["quote_verified"] is True
    assert by_quote["其实我是怕忘词"]["location"] == "逐字稿第 10 段"


def test_hypothetical_evidence_cannot_confirm_needs_or_resources():
    mapping = report_pipeline.step_mapping({})
    evidence = [_ev("我会先深呼吸", kind="假设性回应")]
    path = ["dims", "R1", "abilities", "R1.1"]

    row = report_pipeline._blank_row()
    row["tags"] = ["确认发展需求"]
    report_pipeline.enforce_ability("R1.1", row, evidence, mapping, [], path)
    assert row["tags"] == ["可能存在"]

    row = report_pipeline._blank_row()
    row["tags"] = ["积极资源"]
    report_pipeline.enforce_ability("R1.1", row, evidence, mapping, [], path)
    assert row["tags"] == ["信息不足"]


class ChunkModel:
    def __init__(self):
        self.calls = []

    def __call__(self, prompt):
        self.calls.append(prompt)
        if "标记X" in prompt:
            raise AnalysisError("超时")
        return {"items": [_item("今天和同桌做手工", "学生", "具体行为事件", ["R3.5"])]}


def test_chunk_is_retried_once_then_recorded(monkeypatch):
    text = "\n".join(["甲" * 5990, "标记X" + "丙" * 900, "学生：今天和同桌做手工。"])
    model = ChunkModel()
    monkeypatch.setattr(report_pipeline, "call_model", model)
    failures = []
    items = report_pipeline.extract_items(text, "%s\n%s", (), "M1", "逐字稿", failures)
    assert failures == [2]
    assert sum("标记X" in call for call in model.calls) == 8       # 4 个维度各重试一次
    assert [item["quote"] for item in items] == ["今天和同桌做手工"]


def test_every_chunk_failing_stops_the_run(monkeypatch):
    def always_fail(prompt):
        raise AnalysisError("超时")
    monkeypatch.setattr(report_pipeline, "call_model", always_fail)
    with pytest.raises(AnalysisError):
        report_pipeline.extract_items("学生：今天和同桌做手工。", "%s\n%s", (), "M1", "逐字稿")


def test_chunk_failed_check_message():
    version = {"doc": {}, "evidence": [], "manifest": {"chunk_failed": [2]}}
    hit = _got(version, "chunk_failed")
    assert hit == [{"level": "block", "code": "chunk_failed",
                    "message": "逐字稿第 2 段未能读取，请查看原文或重新生成。", "path": []}]


def test_readable_text():
    assert report_pipeline._readable("学生说可以试试，") == "学生说可以试试。"
    assert report_pipeline._readable("家里支持；") == "家里支持。"
    assert report_pipeline._readable("第一，第二、") == "第一，第二。"
    assert report_pipeline._readable("已经写完了。") == "已经写完了。"
    assert report_pipeline._readable("   ") == ""


def test_generated_family_fields_end_with_closing_punctuation(rdb, fake):
    _report, version = generate(rdb)
    for path, text in _family_texts(version["doc"]):
        assert text[-1] in CLOSING, (path, text)


def test_dim_prompt_writing_lines():
    for line in ("按事情本身的样子写，先写发生了什么。",
                 "有会议证据的能力，meeting 必须据此写，不能留空。",
                 "不要照抄逐字稿，不要用第一人称，不要用分号把几件事串起来，"
                 "不要把不同事件混在一起。每项能力写一小段完整的话。",
                 "Y4 的信任、沟通、亲近分数反映学生对关系的感受，不是次数或频率，"
                 "也不是学生自己说的。"):
        assert line in report_prompts.DIM_PROMPT
    assert "组织逻辑：具体情境与学生表达" not in report_prompts.DIM_PROMPT
