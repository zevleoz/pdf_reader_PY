"""T7：报告不能把人、来源和先后顺序弄混。

全部替换 ``call_model``；不访问真实模型、不连服务器。
"""
from __future__ import annotations

import json

import ai_writing
from app_utils import BASE_DIR
from m1 import report_checks, report_kb, report_pipeline, report_prompts
from test_m1_report_core import (Q_BODY, TRANSCRIPT, _item, client, fake, generate,  # noqa: F401
                                 inline_jobs, rdb)
from test_m1_store import m1db  # noqa: F401

FIRST_MEETING = (BASE_DIR / "fixtures" / "ai_eval" / "first_meeting.txt").read_text("utf-8")
LINES = FIRST_MEETING.splitlines()          # LINES[23] 是文件第 24 行


def _line(number: int) -> str:
    return LINES[number - 1]


def _m1_item(ident, quote, codes=("R1.1",)):
    return {"id": ident, "ability_codes": list(codes), "source": "M1", "location": "",
            "speaker": "学生", "type": "具体行为事件", "quote": quote,
            "quote_verified": True, "interpretation": "", "limits": "", "status": "已确认"}


def _other_item(ident, location, quote, codes=("R1.1",)):
    return {"id": ident, "ability_codes": list(codes), "source": "OTHER", "location": location,
            "speaker": "家长", "type": "其他观察", "quote": quote,
            "quote_verified": True, "interpretation": "", "limits": "", "status": "待核实"}


class DimStub:
    """每个能力都返回一条 meeting 句和 AI 自己写的 other_clues。"""

    def __init__(self, sentence=None, ids=("e1",)):
        self.sentence, self.ids, self.prompts = sentence, list(ids), []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        payload = json.loads(prompt.split("【能力与资料】\n", 1)[1])
        if prompt.startswith("任务：判断一个维度的能力标签"):
            return {"abilities": [{
                "code": ability["code"], "internal_note": "",
                "judgements": [{"tag": "信息不足", "evidence_ids": [], "event_ids": [],
                                "rationale": "没有可用证据"}]} for ability in payload]}
        rows = []
        for ability in payload:
            meeting = {"sentences": []}
            if self.sentence and ability["code"] == "R1.1":
                meeting = {"sentences": [{"text": self.sentence, "evidence_ids": self.ids,
                                          "kind": "fact"}]}
            rows.append({"code": ability["code"], "y4_selected": [],
                         "other_clues": "First Touch：模型自己写的。补充问卷：也是。",
                         "meeting": meeting, "evidence_ids": self.ids,
                         "internal_note": ""})
        return {"abilities": rows, "core_finding": {"sentences": []},
                "context_notes": {"sentences": []}}


def _dims(monkeypatch, evidence, stub):
    monkeypatch.setattr(report_pipeline, "call_model", stub)
    adjustments = []
    dims = report_pipeline.step_dims(report_pipeline.step_mapping({}), evidence, adjustments)
    return dims, adjustments


# 1. other_clues 由代码拼出 ---------------------------------------------------
def test_other_clues_built_by_code_not_by_model(monkeypatch):
    evidence = [_m1_item("e1", Q_BODY),
                _other_item("e2", "其他资料：家长补充说明（虚构）", "她很少主动说起学校里的事")]
    stub = DimStub()
    dims, _ = _dims(monkeypatch, evidence, stub)
    clues = dims["R1"]["abilities"]["R1.1"]["other_clues"]
    assert clues["text"] == "另见：家长补充说明（虚构）。"
    assert clues["src"] == "code"
    assert "“" not in clues["text"]
    assert "First Touch" not in clues["text"] and "补充问卷" not in clues["text"]
    assert "other_clues" not in report_prompts.DIM_PROMPT


def test_questionnaire_clue_is_named_by_its_title(monkeypatch):
    evidence = [_other_item("e1", "补充问卷：虚构问卷", "我不太爱说话")]
    dims, _ = _dims(monkeypatch, evidence, DimStub())
    assert (dims["R1"]["abilities"]["R1.1"]["other_clues"]["text"]
            == "另见：补充问卷《虚构问卷》。")


def test_clues_skip_meeting_items_and_unsupported_items(monkeypatch):
    unverified = dict(_other_item("e2", "其他资料：甲", "没有核实的话"),
                      quote_verified=False)
    dims, _ = _dims(monkeypatch, [_m1_item("e1", Q_BODY), unverified], DimStub())
    assert dims["R1"]["abilities"]["R1.1"]["other_clues"]["text"] == report_pipeline.NO_CLUES


# 2、3. 每一句只对照自己的证据 -------------------------------------------------
def _fixture_evidence():
    return [_m1_item("e1", "我是在她第三次说“下次还你”的时候，才讲了一句“你能不能这周还给我”")]


def _one_dim(meeting_ids, core_text="核心发现句。"):
    return {"R1": {
        "abilities": {"R1.1": {"evidence_ids": [],
                               "meeting": {"text": "会议句。", "src": "ai", "sentences": [
                                   {"text": "会议句。", "evidence_ids": meeting_ids, "kind": "fact"}]}}},
        "core_finding": {"text": core_text, "src": "ai", "sentences": []},
        "context_notes": {"text": "", "src": "ai", "sentences": []}}}


def test_meeting_guard_source_is_the_cited_paragraph_and_the_question_before_it():
    index = report_checks.TextIndex(FIRST_MEETING)
    sources = report_pipeline.guard_sources(_one_dim(["e1"]), _fixture_evidence(), index)
    source = sources[("dims", "R1", "abilities", "R1.1", "meeting")]
    assert _line(23) in source and _line(24) in source
    assert _line(20) not in source and "林同学跟我道歉" not in source


def test_portrait_source_has_no_ai_sentences():
    index = report_checks.TextIndex(FIRST_MEETING)
    dims = _one_dim(["e1"], core_text="AI写的核心发现。")
    sources = report_pipeline.guard_sources(dims, _fixture_evidence(), index)
    for key in (("portrait", "R1"), "all"):
        assert "AI写的核心发现" not in sources[key]
        assert "会议句" not in sources[key]
        assert _line(24) in sources[key]


def test_generate_checks_each_field_against_its_own_evidence(rdb, fake, monkeypatch):
    seen = {}
    real = ai_writing.run_guard

    def spy(blocks, *args, **kwargs):
        for block in blocks:
            seen[block["id"]] = block["source"]
        return real(blocks, *args, **kwargs)

    monkeypatch.setattr(ai_writing, "run_guard", spy)
    generate(rdb)
    meeting = seen["dims/R1/abilities/R1.1/meeting#0"]     # T8 §2：每句一块
    assert TRANSCRIPT.splitlines()[1].split("学生：", 1)[1] in meeting
    assert "我没跟同学说" not in meeting                    # 另一件事的段落
    portrait = seen["portrait/R1"]
    assert "整个下午都觉得很烦" not in portrait             # R1.1 meeting 里 AI 写的句子
    assert "本维度的资料有限" not in portrait               # core_finding 里 AI 写的句子
    assert "我心跳很快" in portrait


# 4. 提示词 ---------------------------------------------------------------------
def test_fact_check_prompt_asks_five_questions_including_order_and_cause():
    assert "五个问题" in ai_writing.FACT_CHECK_PROMPT
    assert "四个问题" not in ai_writing.FACT_CHECK_PROMPT
    assert "前后和起因" in ai_writing.FACT_CHECK_PROMPT
    assert "人物要对上" in ai_writing.FACT_CHECK_PROMPT


# 5. meeting 里的判断句 -----------------------------------------------------------
def test_judgement_tail_is_cut_from_meeting(monkeypatch):
    sentence = "学生半夜起来喝了水又重新躺下，说明存在持续性的反刍思维。"
    dims, adjustments = _dims(monkeypatch, [_m1_item("e1", Q_BODY)], DimStub(sentence))
    meeting = dims["R1"]["abilities"]["R1.1"]["meeting"]
    assert meeting["text"] == "学生半夜起来喝了水又重新躺下。"
    assert meeting["sentences"][0]["text"] == "学生半夜起来喝了水又重新躺下。"
    cut = [a for a in adjustments if a["message"] == "R1.1：会议核实情况里的判断句已删除"]
    assert len(cut) == 1


# 6. 第一人称与旁人观察 -----------------------------------------------------------
def _kinds(text, source):
    return {item["kind"] for item in ai_writing.lint_facts(text, source)}


def test_self_regulation_is_not_first_person():
    assert "first_person" not in _kinds("学生具备一定的自我调节能力", "学生：我在上课。")
    assert "first_person" in _kinds("我会先深呼吸", "学生：我在上课。")


def test_parent_words_count_as_one_observer():
    source = "妈妈观察到她考试前一两天容易晚睡"
    assert "observer" not in _kinds("家长观察到学生考试前容易晚睡", source)
    assert "observer" not in _kinds("家长填写了问卷", "妈妈填写了问卷，说她容易晚睡")
    assert "observer" in _kinds("老师观察到学生上午犯困", "学生：我上午有点犯困。")


# 7. 方案里的提议 -----------------------------------------------------------------
def _lint_flags(text, source="学生提到过自己的感受。"):
    state = {"flags": []}
    field = {"text": text, "src": "ai"}
    report_pipeline._lint_pass([(["plan", 0, "goal"], field, source)], state)
    return state["flags"]


def test_proposals_are_not_checked_as_facts():
    assert _lint_flags("连续两周内，在至少两次事件中主动提及感受") == []
    assert _lint_flags("回应：‘你愿意说说吗？’") == []
    assert [f["kind"] for f in _lint_flags("学生表示同伴亲近得分偏低")] == ["y4_as_speech"]


# 8. 证据提取 -----------------------------------------------------------------------
def _extract(monkeypatch, items, roles=None):
    def model(prompt):
        return {"items": [dict(i) for i in items]}
    monkeypatch.setattr(report_pipeline, "call_model", model)
    return report_pipeline.extract_items(FIRST_MEETING, "%s\n%s", (), "M1", "逐字稿",
                                         roles=roles)


def test_ellipsis_in_the_transcript_itself_is_verified(monkeypatch):
    out = _extract(monkeypatch, [_item("其实……我当时没有想到大家会不会笑我", "学生", "主观感受",
                                       ["R1.1"])])
    assert len(out) == 1 and out[0]["quote_verified"] is True


def test_ellipsis_not_in_the_transcript_stays_unverified(monkeypatch):
    out = _extract(monkeypatch, [_item("我心里……还是有点生气", "学生", "主观感受", ["R1.1"])])
    assert out and out[0]["quote_verified"] is False


def test_mentor_sentence_at_the_start_of_a_quote_is_dropped(monkeypatch):
    mentor = "如果下次又遇到一个特别紧张的场合，比如又要上台，你会怎么办？"
    student = _line(48).split("学生：", 1)[1]
    out = _extract(monkeypatch, [
        _item(mentor + "我会先深呼吸……", "学生", "假设性回应", ["R1.1"]),
        _item(student, "学生", "假设性回应", ["R2.1"])])
    assert len(out) == 1
    assert out[0]["quote"] == student and sorted(out[0]["ability_codes"]) == ["R1.1", "R2.1"]
    assert out[0]["location"].startswith("逐字稿第 48 段")


def test_quote_made_only_of_mentor_sentences_is_dropped(monkeypatch):
    mentor = "如果下次又遇到一个特别紧张的场合，比如又要上台，你会怎么办？你觉得你真的会这样做吗？"
    assert _extract(monkeypatch, [_item(mentor, "学生", "假设性回应", ["R1.1"])]) == []


def test_overlapping_quotes_become_one_item_with_both_code_sets(monkeypatch):
    long = _line(56).split("学生：", 1)[1]
    short = "我有时候会把担心的事情写在便利贴上"
    out = _extract(monkeypatch, [_item(long, "学生", "具体行为事件", ["R1.1"]),
                                 _item(short, "学生", "具体行为事件", ["R2.1"])])
    assert len(out) == 1 and out[0]["quote"] == long
    assert sorted(out[0]["ability_codes"]) == ["R1.1", "R2.1"]


def test_overlap_is_not_merged_across_speakers(monkeypatch):
    long = _line(56).split("学生：", 1)[1]
    short = "我有时候会把担心的事情写在便利贴上"
    # 发言人由逐字稿段首决定，不再看提取模型给的 speaker
    out = _extract(monkeypatch, [_item(long, "学生", "具体行为事件", ["R1.1"]),
                                 _item(short, "家长", "具体行为事件", ["R2.1"])],
                   roles=lambda quote: "学生" if quote == long else "导师")
    assert len(out) == 2


# 5. T8：逐句检查与引文检查 --------------------------------------------------
def _said(number):
    return _line(number).split("学生：", 1)[1]


def _meeting_dims(*sentences):
    """sentences: (文字, [证据 id])"""
    rows = [{"text": text, "evidence_ids": ids, "kind": "fact"} for text, ids in sentences]
    return {"R1": {"abilities": {"R1.1": {"evidence_ids": [], "meeting": {
        "text": "".join(t for t, _ in sentences), "src": "ai", "sentences": rows}}},
        "core_finding": {"text": "", "src": "ai", "sentences": []},
        "context_notes": {"text": "", "src": "ai", "sentences": []}}}


def _flags_for(sentence, item):
    index = report_checks.TextIndex(FIRST_MEETING)
    state = {"flags": []}
    report_pipeline._sentence_checks(_meeting_dims((sentence, [item["id"]])), [item],
                                     index, state)
    return state["flags"]


def _kinds_for(sentence, item):
    return [f["kind"] for f in _flags_for(sentence, item)]


def _run_quote_checks(rdb, fake, mutate):
    from test_m1_report_core import _clean, _mutate
    report, version = _clean(rdb, fake)
    version = _mutate(version, mutate)
    return report_checks.run_checks(report, version, first_touch_text="")


PARENT_QUOTE = "沈若曦在家里很少主动说起学校里的事。"
PARENT_ITEM = _other_item("e90", "家长补充说明（虚构）", PARENT_QUOTE)
PARENT_TEXT = "家长补充说明（虚构）：“%s”" % PARENT_QUOTE


def _set_clues(version, with_item):
    version["doc"]["dims"]["R1"]["abilities"]["R1.1"]["other_clues"] = {
        "text": PARENT_TEXT, "src": "ai"}
    if with_item:
        version["evidence"].append(dict(PARENT_ITEM))


def test_parent_quote_backed_by_verified_evidence_is_not_blocked(rdb, fake):
    checks = _run_quote_checks(rdb, fake, lambda v: _set_clues(v, True))
    assert not [c for c in checks if c["code"] == "quote_unverified"]


def test_parent_quote_without_evidence_is_informational(rdb, fake):
    checks = _run_quote_checks(rdb, fake, lambda v: _set_clues(v, False))
    assert [c for c in checks if c["code"] == "quote_unverified" and c["level"] == "review"]


def test_quoted_suggestion_in_the_plan_is_a_review_not_a_block(rdb, fake):
    def mutate(version):
        version["doc"]["plan"][0]["mentor"] = {"text": "轻声提醒：‘要不要试试？’", "src": "ai"}
        version["doc"]["plan"][0]["family"] = {"text": "可以说“要不要试试？”", "src": "ai"}
    checks = _run_quote_checks(rdb, fake, mutate)
    found = [c for c in checks if c["code"] == "quote_unverified"
             and c["path"][:1] == ["plan"]]
    assert found and all(c["level"] == "review" for c in found)
    assert "建议用语带引号，请确认不是在引用学生原话" in found[0]["message"]


def test_meeting_field_is_guarded_one_block_per_sentence():
    index = report_checks.TextIndex(FIRST_MEETING)
    evidence = [_m1_item("e1", _said(30)), _m1_item("e2", _said(54))]
    dims = _meeting_dims(("第一句。", ["e1"]), ("第二句。", ["e2"]))
    sources = report_pipeline.guard_sources(dims, evidence, index)
    path = ("dims", "R1", "abilities", "R1.1", "meeting")
    assert _line(30) in sources[path + (0,)] and _line(54) not in sources[path + (0,)]
    assert _line(54) in sources[path + (1,)] and _line(30) not in sources[path + (1,)]

    seen = {}

    def guard(blocks, *args, **kwargs):
        for block in blocks:
            seen[block["id"]] = block["source"]
        return {"blocks": {"dims/R1/abilities/R1.1/meeting#1": "改后的第二句。"},
                "flags": [], "status": "checked"}

    state = {"status": "checked", "flags": []}
    field = dims["R1"]["abilities"]["R1.1"]["meeting"]
    original = ai_writing.run_guard
    ai_writing.run_guard = guard
    try:
        report_pipeline._guard_pass(
            [(list(path), field, sources["all"])], "", state, sources)
    finally:
        ai_writing.run_guard = original
    assert set(seen) == {"dims/R1/abilities/R1.1/meeting#0", "dims/R1/abilities/R1.1/meeting#1"}
    assert _line(30) in seen["dims/R1/abilities/R1.1/meeting#0"]
    assert _line(54) not in seen["dims/R1/abilities/R1.1/meeting#0"]
    assert _line(54) in seen["dims/R1/abilities/R1.1/meeting#1"]
    assert field["text"] == "第一句。改后的第二句。" and "sentences" not in field


def test_unchanged_sentences_keep_their_structure():
    index = report_checks.TextIndex(FIRST_MEETING)
    evidence = [_m1_item("e1", _said(30))]
    dims = _meeting_dims(("第一句。", ["e1"]), ("第二句。", ["e1"]))
    sources = report_pipeline.guard_sources(dims, evidence, index)
    field = dims["R1"]["abilities"]["R1.1"]["meeting"]
    original = ai_writing.run_guard
    ai_writing.run_guard = lambda blocks, *a, **k: {
        "blocks": {b["id"]: b["text"] for b in blocks}, "flags": [], "status": "checked"}
    try:
        report_pipeline._guard_pass(
            [(["dims", "R1", "abilities", "R1.1", "meeting"], field, sources["all"])],
            "", {"status": "checked", "flags": []}, sources)
    finally:
        ai_writing.run_guard = original
    assert len(field["sentences"]) == 2 and field["text"] == "第一句。第二句。"


def test_wrong_person_in_a_meeting_sentence_is_flagged():
    item = _m1_item("e1", _said(32))
    assert "person" in _kinds_for("认为同伴试图安慰自己", item)


def test_person_that_is_in_the_event_is_not_flagged():
    item = _m1_item("e1", _said(30))
    assert _kinds_for("向家长表达数学最后一道大题没做出来", item) == []


def test_hypothetical_answer_written_as_habit_is_flagged():
    item = dict(_m1_item("e1", _said(48)), type="假设性回应")
    assert "hypothetical" in _kinds_for("学生在上台前会与同学对稿子", item)
    assert _kinds_for("学生设想下次会提前对稿子", item) == []


def test_dropped_hedge_is_flagged():
    item = _m1_item("e1", _said(54))
    assert "intensity" in _kinds_for("学生考试前会把重点在脑子里再过一遍", item)
    assert _kinds_for("学生有时会把重点再过一遍", item) == []


def test_label_the_student_never_used_is_flagged():
    item = _m1_item("e1", _said(56))
    assert "label" in _kinds_for("以此缓解焦虑", item)


def test_intensity_words_cover_hardly_any_and_completely():
    source = _line(12)
    flagged = ai_writing.lint_facts("下午上课时对课程内容几乎毫无记忆", source)
    assert "intensity" in {f["kind"] for f in flagged}


def test_speaker_label_is_removed_from_an_evidence_quote(monkeypatch):
    quote = "她愣了一下，然后第二天就还给我了"
    out = _extract(monkeypatch, [_item("学生：" + quote, "学生", "具体行为事件", ["R1.1"])])
    assert len(out) == 1 and out[0]["quote"] == quote and out[0]["quote_verified"] is True
