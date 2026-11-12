"""C3：会前准备 accuracy（T6b 第 1–5、7–9 项，加上“只对照所引证据”的核对）。

模型一律用假的，绝不访问网络；资料来自虚构的 fixtures/ai_eval/first_meeting.txt。
"""
from __future__ import annotations

import json
import re

import pytest

import blueprints.m1 as m1_blueprint
import m1.pipeline as pipeline
import m1.prompts as prompts
import m1.sources as sources
import m1.store as store
from app_utils import BASE_DIR
from growth_talk.analysis import AnalysisError
from test_m1_pipeline import (_auto, _fake_ask, _latest_draft, _login,  # noqa: F401
                              api_client)
from test_m1_store import m1db  # noqa: F401  复用临时库

MEETING = (BASE_DIR / "fixtures" / "ai_eval" / "first_meeting.txt").read_text(encoding="utf-8")


def _line(number: int) -> str:
    """Line ``number`` (from 1) of the fictional meeting, without its time mark."""
    return re.sub(r"^\[[\d:]+\]\s*", "", MEETING.split("\n")[number - 1])


def _meeting_items(monkeypatch, rows, text=MEETING):
    """Evidence built by ``_source_text_items`` from model answers fixed in ``rows``
    (``quote`` plus optional ``text`` and ``kind``)."""
    answer = [{"text": row.get("text", ""), "quote": row["quote"], "abilities": [],
               "kind": row.get("kind", "direct"), "prompted": False,
               "independent": False} for row in rows]
    monkeypatch.setattr(pipeline, "_ask", lambda prompt, schema: {"items": answer})
    return pipeline._source_text_items(_auto(ft_text=text), [])


# ---------------------------------------------------------------------------
# 1. 标记不能自己关闭
# ---------------------------------------------------------------------------
def test_flags_stay_open_right_after_generation(m1db, monkeypatch):
    auto = _auto(ft_text="2026-10-12 First Touch。晚上躺在床上一直在想哪道题错了。")
    monkeypatch.setattr(pipeline.sources, "auto_sources", lambda sid: auto)
    prep = m1db.prep()
    base = _fake_ask({"source_items": {"copilot_session:3": [{
        "text": "晚上一直在想错题", "quote": "晚上躺在床上一直在想哪道题错了",
        "abilities": ["R2.2"], "kind": "direct", "independent": False}]},
        "recommend": ["R2.2"]})

    def ask(prompt, schema):
        result = base(prompt, schema)
        if schema == pipeline.SCHEMA_ABILITY:
            for row in result["abilities"]:
                if row["cites"]:  # a date the source never gave, kept by the rewrite
                    row["check_text"] = "学生晚上躺在床上一直在想哪道题错了，从3月中旬开始。"
        return result

    monkeypatch.setattr(pipeline, "_ask", ask)

    pipeline.generate(prep["id"])

    doc = _latest_draft(prep["id"])["doc"]
    appendix_flags = [f for f in doc["fact_flags"] if f["block_id"].startswith("ap-c-")]
    assert appendix_flags, "the date should be flagged in an appendix check text"
    open_flags = m1_blueprint._open_fact_flags(doc)
    assert [f["id"] for f in open_flags] == [f["id"] for f in doc["fact_flags"]
                                             if not f["acked"]]
    assert {f["id"] for f in appendix_flags} <= {f["id"] for f in open_flags}
    # the source note was added after the check, and the flag already knows that text
    noted = [(f, row["check"]) for f in appendix_flags for row in doc["appendix"]
             if row["check"]["id"] == f["block_id"] and "（来源：" in row["check"]["text"]]
    assert noted, "a flagged check text that got its source note after the check"
    flag, check = noted[0]
    assert flag["block_text"] == check["text"]

    # a real edit afterwards still closes the flag
    check["text"] = "学生晚上躺在床上一直在想哪道题错了。"
    assert flag["id"] not in {f["id"] for f in m1_blueprint._open_fact_flags(doc)}


# ---------------------------------------------------------------------------
# 2. 真实发生过的事不是设想
# ---------------------------------------------------------------------------
def test_a_real_event_after_an_if_question_stays_direct(monkeypatch):
    real = _line(40).split("：", 1)[1][:34]            # 上个月小晴因为……我中午就坐在她旁边
    supposed = _line(48).split("：", 1)[1][:24]        # 我会先深呼吸……
    assert "上个月" in real and "如果" in _line(39) and "如果下次" in _line(47)

    rows = _meeting_items(monkeypatch, [{"quote": real}, {"quote": supposed}])

    by_quote = {row["quote"]: row for row in rows}
    assert by_quote[real]["kind"] == "direct"
    assert not by_quote[real]["text"].startswith("学生设想")
    assert by_quote[supposed]["kind"] == "hypothetical"
    assert by_quote[supposed]["text"].startswith("学生设想")


@pytest.mark.parametrize("word", ["上个月", "上周", "上次", "那次", "有一次", "当时",
                                  "之前", "昨天", "去年", "上学期"])
def test_each_time_word_keeps_a_real_event_direct(monkeypatch, word):
    text = "导师：如果朋友心情不好，你一般怎么做？\n学生：%s我陪她坐了一会儿，没有多问。\n" % word
    rows = _meeting_items(monkeypatch, [{"quote": "我陪她坐了一会儿，没有多问"}], text)
    assert [row["kind"] for row in rows] == ["direct"]


def test_a_plain_supposed_answer_after_an_if_question_stays_hypothetical(monkeypatch):
    text = "导师：如果下次又遇到特别紧张的场合，你会怎么办？\n学生：我会先深呼吸，再慢慢开口。\n"
    rows = _meeting_items(monkeypatch, [{"quote": "我会先深呼吸，再慢慢开口"}], text)
    assert [row["kind"] for row in rows] == ["hypothetical"]


# ---------------------------------------------------------------------------
# 3. 保留学生的更正
# ---------------------------------------------------------------------------
def test_student_correction_keeps_only_what_follows_it(monkeypatch):
    whole = _line(30).split("：", 1)[1][:60]
    assert "不对" in whole and "一般都不会" in whole

    rows = _meeting_items(monkeypatch, [{
        "quote": whole, "text": "学生表示自己一般不会跟妈妈说"}])

    assert len(rows) == 1
    item = rows[0]
    assert "上次月考之后我说过一次" in item["quote"] and "上次月考之后我说过一次" in item["text"]
    assert "一般都不会" not in item["quote"] and "一般都不会" not in item["text"]
    assert item["quote"] == item["text"] and not item["quote"].startswith(("，", "不对"))


def test_a_question_word_is_not_a_correction(monkeypatch):
    text = "学生：我这样做对不对，我也说不清楚，但我每天都会再检查一遍作业。\n"
    rows = _meeting_items(monkeypatch, [{
        "quote": "我这样做对不对，我也说不清楚，但我每天都会再检查一遍作业"}], text)
    assert rows[0]["quote"].startswith("我这样做对不对")


def test_prompt_says_to_record_only_what_the_student_settled_on():
    assert "学生中途改口时，只记录改口后的说法。" in prompts.SOURCE_ITEMS_PROMPT


# ---------------------------------------------------------------------------
# 4. 冲突来自真实的证据对，由代码写句子
# ---------------------------------------------------------------------------
def _evidence(item_id, source, group, text, quote="", kind="direct"):
    return {"id": item_id, "source": source, "source_ref": "ref-" + item_id,
            "date": "2026-10-20", "kind": kind, "group": group, "text": text,
            "quote": quote, "abilities": [], "band": ""}


_PAIR_EVIDENCE = [
    _evidence("a-1", "parent", "g-parent", "家长说学生回家后话变少"),
    _evidence("a-2", "first_touch", "g-ft", "学生说回家后会和妈妈聊几句"),
    _evidence("a-3", "first_touch", "g-ft", "学生说展示后松了一口气"),
]
_ROW = {"code": "R1.1", "potential": ["有一条积极线索"], "interference": ["有一条干扰线索"],
        "known": "已知线索", "new_clues": "", "missing": [], "check_text": "资料里写到的情况。",
        "recommend": True, "reason_code": "none", "cites": ["a-1", "a-2"]}


def _judge(monkeypatch, pairs):
    monkeypatch.setattr(pipeline, "_ask", lambda prompt, schema: {
        "abilities": [dict(_ROW, contradictions=pairs)]})
    return pipeline._judge_abilities(_PAIR_EVIDENCE)["R1.1"]["contradictions"]


def test_a_pair_from_one_group_is_dropped(monkeypatch):
    assert _judge(monkeypatch, [{"a": "a-2", "b": "a-3"}]) == []


def test_a_valid_pair_renders_both_items_and_nothing_else(monkeypatch):
    found = _judge(monkeypatch, [{"a": "a-1", "b": "a-3"}])
    assert found == ["%s：家长说学生回家后话变少；%s：学生说展示后松了一口气。" % (
        pipeline.SOURCE_LABELS["parent"], pipeline.SOURCE_LABELS["first_touch"])]


@pytest.mark.parametrize("pair", [
    {"a": "a-1", "b": "a-1"}, {"a": "a-1", "b": "no-such"}, {"a": "a-1"},
    "家长与学生的说法不一致", None,
])
def test_broken_pairs_are_ignored(monkeypatch, pair):
    assert _judge(monkeypatch, [pair]) == []


def test_model_written_special_conflict_is_ignored(monkeypatch):
    monkeypatch.setattr(pipeline, "_ask", lambda prompt, schema: {
        "special": {"conflict": "学生在展示后表示松了一口气，与话变少矛盾",
                    "context": "", "attention": ""}})

    plan = pipeline._build_plan({"duration": 60}, _PAIR_EVIDENCE, {}, [], [])
    assert plan["special"]["conflict"]["text"] == "本次资料中未见两个独立来源之间的明显矛盾。"

    judgements = {"R1.1": {"contradictions": ["甲：乙。", "丙：丁。"]},
                  "R1.2": {"contradictions": ["甲：乙。", "戊：己。", "庚：辛。"]}}
    plan = pipeline._build_plan({"duration": 60}, _PAIR_EVIDENCE, judgements, [], [])
    assert plan["special"]["conflict"]["text"].split("\n") == ["甲：乙。", "丙：丁。", "戊：己。"]


def test_the_conflict_block_is_not_sent_to_the_guard():
    item = _evidence("a-1", "first_touch", "g-ft", "学生说展示后松了一口气",
                     quote="我当时反而松了一口气")
    doc = {"special": {
        "conflict": pipeline._block("c1", "家长初始反馈：话变少；First Touch：松了一口气。"),
        "context": pipeline._block("c2", "学生说展示后松了一口气。"),
        "attention": pipeline._block("c3", "学生说展示后松了一口气。")}}

    blocks = pipeline._guard_inputs(doc, [item], {}, {}, {"ref-a-1": "学生：我当时反而松了一口气"}, {})

    assert {b["id"] for b in blocks} == {"c2", "c3"}


def test_prompts_no_longer_ask_the_model_to_write_a_conflict():
    assert '{"a": "证据id", "b": "证据id"}' in prompts.ABILITY_PROMPT
    assert '"special": {"context": "", "context_ids": [], "attention": "", "attention_ids": []}' \
        in prompts.MEETING_PLAN_PROMPT
    assert "conflict" not in prompts.MEETING_PLAN_PROMPT
    assert "两个 Y4 指标" not in prompts.MEETING_PLAN_PROMPT


# ---------------------------------------------------------------------------
# 5. 附录文字像人写的
# ---------------------------------------------------------------------------
def test_check_text_prompt_asks_for_third_person_and_no_stitching():
    assert "最多两句、不超过 80 字" in prompts.ABILITY_PROMPT
    assert "不要把几条证据用分号串起来" in prompts.ABILITY_PROMPT
    assert "直接陈述" not in prompts.ABILITY_PROMPT


def _check_doc(text, code="R1.1"):
    return {"appendix": [{"code": code, "recommend": False,
                          "reason": pipeline._block("ap-r-" + code, pipeline._APPENDIX_LEFT_OUT),
                          "check": pipeline._block("ap-c-" + code, text)}]}


def test_check_text_keeps_whole_sentences_up_to_120_characters():
    sentence = "学生说晚上躺在床上会一直想哪道题错了，白天上课时也偶尔会走神。"
    text = sentence * 4
    assert len(text) > 120
    doc = _check_doc(text)

    pipeline._append_source_notes(doc, {"R1.1": {"cites": []}}, {})

    kept = doc["appendix"][0]["check"]["text"]
    assert kept == sentence * (120 // len(sentence)) and len(kept) <= 120
    assert kept.endswith("。")


def test_a_long_first_sentence_is_not_cut():
    text = "学生" + "说" * 130 + "。第二句。"
    doc = _check_doc(text)
    pipeline._append_source_notes(doc, {"R1.1": {"cites": []}}, {})
    assert doc["appendix"][0]["check"]["text"] == "学生" + "说" * 130 + "。"


def test_source_note_lists_only_sources_whose_text_is_used():
    by_id = {
        "a": {"source": "first_touch", "text": "晚上躺在床上一直在想哪道题错了", "quote": ""},
        "b": {"source": "parent", "text": "家长说成绩下降", "quote": "期中后回家不怎么说话"},
        "c": {"source": "case_review", "text": "老师观察到低头", "quote": ""},
    }
    doc = _check_doc("学生晚上躺在床上一直在想哪道题错了。")

    pipeline._append_source_notes(doc, {"R1.1": {"cites": ["a", "b", "c"]}}, by_id)

    assert doc["appendix"][0]["check"]["text"].endswith(
        "（来源：%s）" % pipeline.SOURCE_LABELS["first_touch"])

    doc = _check_doc("学生晚上躺在床上一直在想哪道题错了。")
    pipeline._append_source_notes(doc, {"R1.1": {"cites": ["b", "c"]}}, by_id)
    assert "来源" not in doc["appendix"][0]["check"]["text"]


def test_ai_blocks_end_as_sentences():
    doc = {
        "priority": [{"hypothesis": pipeline._block("h-R1.1", "可能和考试有关，"),
                      "why": pipeline._block("w-R1.1", "还需要了解具体情况；")}],
        "events": [{"id": "ev1", "title": pipeline._block("ev1-title", "展示前的紧张"),
                    "questions": pipeline._block("ev1-questions", "1. 当时发生了什么？\n2. 后来呢")}],
        "special": {"conflict": pipeline._block("c1", "甲：乙；丙：丁。"),
                    "context": pipeline._block("c2", "学生说起过家里的安排、")},
    }

    pipeline._end_blocks_properly(doc)

    assert doc["priority"][0]["hypothesis"]["text"] == "可能和考试有关。"
    assert doc["priority"][0]["why"]["text"] == "还需要了解具体情况。"
    assert doc["events"][0]["title"]["text"] == "展示前的紧张"  # a title takes no full stop
    assert doc["events"][0]["questions"]["text"] == "1. 当时发生了什么？\n2. 后来呢"
    assert doc["special"]["conflict"]["text"] == "甲：乙；丙：丁。"
    assert doc["special"]["context"]["text"] == "学生说起过家里的安排。"
    assert doc["priority"][0]["hypothesis"]["ai_text"] == "可能和考试有关。"


# ---------------------------------------------------------------------------
# 6. 每一块只对照它所引的证据
# ---------------------------------------------------------------------------
def _quote_of(number, sentence=0):
    """One sentence of a student line (a whole line is too long to quote)."""
    return re.split(r"(?<=[。！？])", _line(number).split("：", 1)[1])[sentence].strip()


def _items_for(monkeypatch, *specs):
    """Evidence for ``(line number, sentence index)`` pairs, built together so ids differ."""
    rows = _meeting_items(monkeypatch, [{"quote": _quote_of(*spec)} for spec in specs])
    assert len(rows) == len(specs)
    return rows


def _item_for(monkeypatch, number, sentence=0, **extra):
    return _items_for(monkeypatch, (number, sentence))[0]


def test_guard_source_is_the_cited_paragraph_and_the_one_before(monkeypatch):
    item = _item_for(monkeypatch, 24, sentence=1)
    texts = {item["source_ref"]: MEETING}

    source = pipeline._guard_source([item], texts)

    assert _line(23) in source and _line(24) in source          # the question and the answer
    assert _line(25) not in source                              # not what comes after
    assert _line(20) not in source and _line(26) not in source  # not another event


def test_guard_source_for_other_material_is_its_label_and_text():
    y4 = _evidence("y4-1", "y4", "Y4", "亲子沟通：偏低")
    source = pipeline._guard_source([y4], {})
    assert "亲子沟通：偏低" in source and "Y4" in source


def _two_sentence_summary(monkeypatch):
    first, second = items = _items_for(monkeypatch, (20, 0), (24, 1))
    texts = {first["source_ref"]: MEETING}
    sentences = [
        {"text": "学生没有把生气说出来，林同学已经道歉了。", "evidence_ids": [first["id"]]},
        {"text": "林同学道歉之后，学生才在第三次听到“下次还你”时说出口。",
         "evidence_ids": [second["id"]]},
    ]
    summaries = {"first_touch": {"text": "".join(s["text"] for s in sentences),
                                 "evidence_ids": [first["id"], second["id"]],
                                 "sentences": sentences}}
    doc = {"sources": [{"key": "first_touch",
                        "extracted": pipeline._block("src-first-touch", summaries["first_touch"]["text"])}]}
    return doc, items, texts, summaries


def test_each_summary_sentence_is_its_own_guard_block_with_its_own_source(monkeypatch):
    doc, items, texts, summaries = _two_sentence_summary(monkeypatch)

    blocks = pipeline._guard_inputs(doc, items, {}, {}, texts, summaries)

    by_id = {b["id"]: b for b in blocks}
    assert set(by_id) == {"src-first-touch#0", "src-first-touch#1"}
    assert "道歉" in by_id["src-first-touch#0"]["source"]
    assert "道歉" not in by_id["src-first-touch#1"]["source"]
    assert _line(24).split("：", 1)[1][:20] in by_id["src-first-touch#1"]["source"]


def test_an_event_placed_after_another_events_apology_is_flagged(monkeypatch):
    doc, items, texts, summaries = _two_sentence_summary(monkeypatch)

    def ask(prompt, schema):
        assert schema == pipeline.SCHEMA_VERIFY or schema == pipeline.SCHEMA_REWRITE
        if schema == pipeline.SCHEMA_REWRITE:
            raise RuntimeError("no rewrite")
        text = prompt.split("【文字】\n", 1)[1].split("\n【资料】\n", 1)[0]
        source = prompt.split("\n【资料】\n", 1)[1]
        rows = []
        for piece in re.split(r"[。！？；\n]+", text):
            if not piece.strip():
                continue
            wrong = "道歉" in piece and "道歉" not in source
            rows.append({"text": piece, "verdict": "unsupported" if wrong else "supported",
                         "problem": "资料没有写道歉" if wrong else ""})
        return {"sentences": rows}

    monkeypatch.setattr(pipeline, "_ask", ask)

    pipeline._fact_check(doc, items, {}, {}, texts, summaries, "")

    flags = doc["fact_flags"]
    assert [f["kind"] for f in flags] == ["unsupported"], flags
    assert flags[0]["block_id"] == "src-first-touch"
    assert flags[0]["sentence"].startswith("林同学道歉之后")
    # the block keeps both sentences; the flag remembers the block's text
    assert flags[0]["block_text"] == doc["sources"][0]["extracted"]["text"]
    assert "道歉了" in flags[0]["block_text"]


def _sentence_flags(monkeypatch, number, text, sentence=0):
    item = _item_for(monkeypatch, number, sentence)
    texts = {item["source_ref"]: MEETING}
    summaries = {"first_touch": {"sentences": [
        {"text": text, "evidence_ids": [item["id"]]}]}}
    doc = {"sources": [{"key": "first_touch",
                        "extracted": pipeline._block("src-first-touch", text)}]}
    return pipeline._sentence_code_flags(doc, [item], texts, summaries)


def test_a_person_missing_from_the_cited_evidence_is_flagged_by_code(monkeypatch):
    # line 26 is the paintbrush story: no classmate named in it or in the question before it
    flags = _sentence_flags(monkeypatch, 26, "展示之后林同学道歉，学生反而松了一口气。")
    assert [f["kind"] for f in flags] == ["person"]
    assert flags[0]["block_id"] == "src-first-touch"
    assert _sentence_flags(monkeypatch, 26, "对方愣了一下，第二天就还了，学生松了一口气。") == []


def test_a_supposed_answer_written_as_fact_is_flagged_by_code(monkeypatch):
    flags = _sentence_flags(monkeypatch, 48, "学生上台前会先深呼吸，再和同学对稿。")
    assert "hypothetical" in [f["kind"] for f in flags]
    assert not [f for f in _sentence_flags(monkeypatch, 48, "学生设想上台前先深呼吸，再和同学对稿。")
                if f["kind"] == "hypothetical"]


def test_sometimes_written_as_always_and_unused_labels_are_flagged_by_code(monkeypatch):
    flags = _sentence_flags(monkeypatch, 52, "学生考试前躺下以后总在想题目，有些焦虑。", sentence=1)
    assert {"intensity", "label"} <= {f["kind"] for f in flags}
    assert _sentence_flags(monkeypatch, 52, "学生有时候考试前躺下以后会一直在想题目。", sentence=1) == []


# ---------------------------------------------------------------------------
# 7. 只说“要去了解什么”的块不做事实核对
# ---------------------------------------------------------------------------
def test_blocks_about_what_to_find_out_are_not_fact_checked():
    item = _evidence("a-1", "first_touch", "g-ft", "学生说展示后松了一口气",
                     quote="我当时反而松了一口气")
    texts = {"ref-a-1": "学生：我当时反而松了一口气"}
    text = "学生说展示后松了一口气。"
    doc = {
        "dims": [{"dim": "R1", "potential": pipeline._block("p-R1", text),
                  "interference": pipeline._block("i-R1", text),
                  "gap": pipeline._block("g-R1", text)}],
        "priority": [{"code": "R1.1", "hypothesis": pipeline._block("h-R1.1", text),
                      "why": pipeline._block("w-R1.1", text)}],
        "events": [{"id": "ev1", "title": pipeline._block("ev1-title", text),
                    "gap": pipeline._block("ev1-gap", text),
                    "questions": pipeline._block("ev1-questions", text)}],
        "backups": [{"code": "R1.2", "missing": pipeline._block("bk-g-R1.2", text),
                     "question": pipeline._block("bk-q-R1.2", text)}],
    }
    judgements = {"R1.1": {"cites": ["a-1"]}}
    plan = {"event_ids": {"ev1": ["a-1"]}}

    blocks = pipeline._guard_inputs(doc, [item], judgements, plan, texts, {})

    ids = {b["id"] for b in blocks}
    assert {"h-R1.1", "ev1-title"} <= ids
    assert not {i for i in ids if i.startswith(("w-", "g-", "bk-")) or i.endswith("-gap")}


# ---------------------------------------------------------------------------
# 8. 长逐字稿的一段失败，不拖垮整份文档
# ---------------------------------------------------------------------------
def _long_source(m1db, monkeypatch):
    long_text = (BASE_DIR / "fixtures" / "ai_eval" / "long_tail.txt").read_text(encoding="utf-8")
    auto = _auto()
    monkeypatch.setattr(pipeline.sources, "auto_sources", lambda sid: auto)
    prep = m1db.prep()
    sources.add_text(prep["id"], long_text, "other")
    pieces = pipeline._split_pieces(long_text.strip())
    assert len(pieces) >= 3
    return prep, pieces, auto


def _piece_model(monkeypatch, pieces, failing, calls):
    base = _fake_ask({})

    def ask(prompt, schema):
        if schema == pipeline.SCHEMA_SOURCE:
            text = json.loads(prompt.split("【资料】\n", 1)[1])["text"]
            number = pieces.index(text) + 1
            calls.append(number)
            if number in failing and calls.count(number) <= failing[number]:
                raise AnalysisError("timeout")
        return base(prompt, schema)

    monkeypatch.setattr(pipeline, "_ask", ask)


def test_a_piece_that_fails_twice_is_flagged_and_kept_at_finalize(api_client, m1db, monkeypatch):
    prep, pieces, auto = _long_source(m1db, monkeypatch)
    calls = []
    _piece_model(monkeypatch, pieces, {2: 2}, calls)

    pipeline.generate(prep["id"])

    assert calls.count(2) == 2 and calls.count(1) == 1 and calls.count(3) == 1
    draft = _latest_draft(prep["id"])
    label = pipeline._text_sources(auto, store.list_sources(prep["id"]))[0]["label"]
    unread = [f for f in draft["doc"]["fact_flags"] if f["kind"] == "unread"]
    assert [f["sentence"] for f in unread] == ["资料「%s」第 2 段未能读取，请人工查看原文。" % label]
    assert unread[0]["block_id"] == "" and unread[0]["acked"] is False
    assert any(item["source"] == "other" for item in draft["evidence"])  # other pieces were used

    _login(api_client, m1db.alice_id, "advisor", "Alice")
    res = api_client.post("/api/m1/preps/%d/finalize" % prep["id"])
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["open_flags"] == 1
    final = store.get_current_version(prep["id"])
    assert unread[0]["id"] in [f["id"] for f in final["doc"]["fact_flags"]]


def test_a_piece_that_fails_once_is_retried_and_leaves_no_flag(m1db, monkeypatch):
    prep, pieces, _auto_rows = _long_source(m1db, monkeypatch)
    calls = []
    _piece_model(monkeypatch, pieces, {2: 1}, calls)

    pipeline.generate(prep["id"])

    assert calls.count(2) == 2
    doc = _latest_draft(prep["id"])["doc"]
    assert not [f for f in doc["fact_flags"] if f["kind"] == "unread"]


def test_when_every_piece_fails_generation_still_raises(m1db, monkeypatch):
    prep, pieces, _auto_rows = _long_source(m1db, monkeypatch)
    _piece_model(monkeypatch, pieces, {n: 99 for n in range(1, len(pieces) + 1)}, [])

    with pytest.raises(AnalysisError):
        pipeline.generate(prep["id"])


# ---------------------------------------------------------------------------
# 9. Y4 提醒
# ---------------------------------------------------------------------------
def test_style_reminds_that_y4_relationship_scores_are_feelings_not_frequency():
    assert ("Y4 的信任、沟通、亲近分数反映学生对关系的感受，不是沟通次数或频率；"
            "不要写成学生自己说的。") in prompts._STYLE


# ===========================================================================
# C3b：c2/c3 的窄来源、每个展示句的代码检查、常与强情绪词、家长来源
# ===========================================================================
PARENT = (BASE_DIR / "fixtures" / "ai_eval" / "parent_note.txt").read_text(encoding="utf-8")


def _doc_with(block_id, text, holder="special", key="context"):
    block = pipeline._block(block_id, text)
    return {holder: {key: block}}


def _code_flags(monkeypatch, specs, doc, judgements=None, plan=None):
    """Code-check flags for ``doc``; ``specs`` are (line, sentence index) quotes."""
    items = _items_for(monkeypatch, *specs)
    texts = {items[0]["source_ref"]: MEETING}
    plan = plan(items) if callable(plan) else plan
    judgements = judgements(items) if callable(judgements) else judgements
    return items, pipeline._sentence_code_flags(doc, items, texts, {}, judgements, plan)


def test_c2_written_as_often_is_flagged_against_the_items_it_cites(monkeypatch):
    doc = _doc_with("c2", "常写到十一点多，早上起不来。")
    items, flags = _code_flags(
        monkeypatch, [(2, 0), (4, 0)], doc,
        plan=lambda rows: {"special_ids": {"c2": [r["id"] for r in rows]}})
    assert [(f["block_id"], f["kind"]) for f in flags] == [("c2", "intensity")]
    assert "有时" in flags[0]["problem"]


def test_c2_and_c3_are_checked_against_what_they_cite_or_nothing(monkeypatch):
    items = _items_for(monkeypatch, (2, 0), (20, 0))
    texts = {items[0]["source_ref"]: MEETING}
    doc = {"special": {"conflict": pipeline._block("c1", "x"),
                       "context": pipeline._block("c2", "学生做作业常到很晚。"),
                       "attention": pipeline._block("c3", "学生有些生气没有说出来。")}}
    plan = {"special_ids": {"c2": [items[0]["id"]], "c3": []}}

    blocks = {b["id"]: b for b in pipeline._guard_inputs(doc, items, {}, plan, texts, {})}

    assert _line(20).split("：", 1)[1][:12] not in blocks["c2"]["source"]   # only its own item
    assert _line(2).split("：", 1)[1][:12] in blocks["c2"]["source"]
    assert blocks["c3"]["source"] == "（没有对应证据）"                      # no ids: nothing supports it


def test_a_factual_c3_without_ids_is_flagged_by_the_model_check(monkeypatch):
    items = _items_for(monkeypatch, (2, 0))
    texts = {items[0]["source_ref"]: MEETING}
    doc = {"special": {"conflict": pipeline._block("c1", "本次资料中未见两个独立来源之间的明显矛盾。"),
                       "context": pipeline._block("c2", "信息不足，待会议中补充。"),
                       "attention": pipeline._block("c3", "父母观察到学生情绪变化。")}}

    def ask(prompt, schema):
        if schema == pipeline.SCHEMA_REWRITE:
            raise RuntimeError("no rewrite")
        source = prompt.split("\n【资料】\n", 1)[1]
        text = prompt.split("【文字】\n", 1)[1].split("\n【资料】\n", 1)[0]
        wrong = source.strip() == "（没有对应证据）"
        return {"sentences": [{"text": t, "verdict": "unsupported" if wrong else "supported",
                               "problem": "资料没有写到" if wrong else ""}
                              for t in re.split(r"[。！？；\n]+", text) if t.strip()]}

    monkeypatch.setattr(pipeline, "_ask", ask)
    pipeline._fact_check(doc, items, {}, {}, texts, {}, "")

    assert [(f["block_id"], f["kind"]) for f in doc["fact_flags"]] == [("c3", "unsupported")]


def test_strong_emotion_words_need_the_evidence_to_use_them(monkeypatch):
    doc = {"appendix": [{"code": "R2.4", "check": pipeline._block("ap-c-R2.4", "学生在情绪激动时选择压抑愤怒。")}]}
    items, flags = _code_flags(
        monkeypatch, [(20, 0)], doc,
        judgements=lambda rows: {"R2.4": {"cites": [r["id"] for r in rows]}})
    assert sorted((f["kind"], f["problem"]) for f in flags) == [
        ("label", "资料里没有“情绪激动”这个说法"), ("label", "资料里没有“愤怒”这个说法")]

    doc = {"appendix": [{"code": "R2.4", "check": pipeline._block("ap-c-R2.4", "学生有点生气，但是没说出来。")}]}
    items, flags = _code_flags(
        monkeypatch, [(20, 0)], doc,
        judgements=lambda rows: {"R2.4": {"cites": [r["id"] for r in rows]}})
    assert flags == []


@pytest.mark.parametrize("text", ["常写到很晚", "常因担心显得小气", "时常觉得累", "常常想到这件事",
                                  "常会走神", "常在晚上写作业", "常到十一点才睡", "常持续到很晚", "常选择不说"])
def test_often_is_matched(text):
    assert pipeline._OFTEN_RE.search(text)


@pytest.mark.parametrize("word", ["正常", "日常", "异常", "非常", "平常", "通常", "常规", "常见"])
def test_often_is_not_matched_in_ordinary_words(word):
    assert not pipeline._OFTEN_RE.search(word)
    assert not pipeline._OFTEN_RE.search("学生%s地写作业" % word)
    assert not pipeline._OFTEN_RE.search("学生%s写作业" % word)      # 正常写…, 日常会…
    assert not pipeline._OFTEN_RE.search("学生%s会走神" % word)


def test_often_needs_a_frequency_the_evidence_gave():
    sentence = "学生做作业常写到很晚。"
    assert pipeline._word_flags(sentence, "有时候写到十一点多")[0][0] == "intensity"
    assert pipeline._word_flags(sentence, "每天作业挺多的") == []
    assert pipeline._word_flags(sentence, "写作业到很晚")[0][0] == "intensity"
    assert pipeline._word_flags(sentence, "他总是写到很晚") == []


def test_the_first_sentence_of_a_why_block_gets_the_code_checks(monkeypatch):
    doc = {"priority": [{"code": "R1.4", "hypothesis": pipeline._block("h-R1.4", "x"),
                         "why": pipeline._block("w-R1.4", "学生常因评语开心。需要了解后续。")}]}
    items, flags = _code_flags(
        monkeypatch, [(62, 1), (64, 0)], doc,
        judgements=lambda rows: {"R1.4": {"cites": [r["id"] for r in rows]}})
    assert [(f["block_id"], f["sentence"], f["kind"]) for f in flags] == [
        ("w-R1.4", "学生常因评语开心。", "intensity")]
    # w- blocks stay out of the model check
    texts = {items[0]["source_ref"]: MEETING}
    blocks = pipeline._guard_inputs(
        doc, items, {"R1.4": {"cites": [i["id"] for i in items]}}, {}, texts, {})
    assert "w-R1.4" not in {b["id"] for b in blocks}


def test_art_activity_praise_has_no_code_rule(monkeypatch):
    """Reported, not covered: the 语文 essay praise written as 艺术活动 is caught by no rule."""
    doc = {"priority": [{"code": "R1.4", "hypothesis": pipeline._block("h-R1.4", "x"),
                         "why": pipeline._block("w-R1.4", "学生在艺术活动中获得正向反馈。")}]}
    _items, flags = _code_flags(
        monkeypatch, [(62, 1), (64, 0)], doc,
        judgements=lambda rows: {"R1.4": {"cites": [r["id"] for r in rows]}})
    assert flags == []


def test_every_shown_block_with_cites_is_code_checked(monkeypatch):
    sentence = "学生常写到很晚。"
    doc = {"dims": [{"dim": "R1", "potential": pipeline._block("p-R1", "R1.1 " + sentence),
                     "interference": pipeline._block("i-R1", "R1.1 " + sentence + "；R1.2 学生写作业。")}],
           "priority": [{"code": "R1.1", "hypothesis": pipeline._block("h-R1.1", sentence),
                         "why": pipeline._block("w-R1.1", "还需要了解。")}],
           "appendix": [{"code": "R1.1", "check": pipeline._block("ap-c-R1.1", sentence)}]}
    items, flags = _code_flags(
        monkeypatch, [(2, 0)], doc,
        judgements=lambda rows: {"R1.1": {"cites": [r["id"] for r in rows]}})
    # (the shared hedge rule also flags w-R1.1: every cited quote says 有时 and no sentence of it does)
    assert {f["block_id"] for f in flags} == {"ap-c-R1.1", "h-R1.1", "i-R1", "p-R1", "w-R1.1"}
    assert len(flags) == len({(f["block_id"], f["sentence"], f["kind"], f["problem"]) for f in flags})


def test_a_parent_note_sentence_is_not_a_person_false_alarm(monkeypatch):
    quote = "她做作业有时候要到很晚，早上起床有点吃力"
    assert quote in PARENT
    monkeypatch.setattr(pipeline, "_ask", lambda prompt, schema: {"items": [{
        "text": "", "quote": quote, "abilities": [], "kind": "context",
        "prompted": False, "independent": False}]})
    uploaded = [{"id": 7, "category": "parent", "label": "家长初始反馈", "text": PARENT,
                 "detected_date": "2026-10-09"}]
    items = pipeline._source_text_items(_auto(), uploaded)
    texts = {items[0]["source_ref"]: PARENT}
    sentence = "家长反映学生做作业有时要到很晚，早上起床有点吃力。"
    summaries = {"parent": {"sentences": [{"text": sentence, "evidence_ids": [items[0]["id"]]}]}}
    doc = {"sources": [{"key": "parent", "extracted": pipeline._block("src-parent", sentence)}]}

    flags = pipeline._sentence_code_flags(doc, items, texts, summaries)

    assert flags == []
    # the label is only added for the code checks, never to the guard source
    assert "家长初始反馈：" not in pipeline._guard_source(items, texts)


def test_check_text_prompt_asks_for_one_matter_per_sentence_and_no_invented_consequences():
    assert "每句只写一件事；不要把不同事件写进同一句，也不要写资料里没有的后果（如“影响关系”）。" \
        in prompts.ABILITY_PROMPT


# ===========================================================================
# C3c：核对改写之后的最终文字，再做一次代码检查
# ===========================================================================
def _guarded_summary(monkeypatch, spec, draft, rewritten):
    """One summary sentence citing the ``spec`` quote; the first fact check rejects it,
    the rewrite returns ``rewritten`` and the second check accepts that."""
    items = _items_for(monkeypatch, spec)
    texts = {items[0]["source_ref"]: MEETING}
    summaries = {"first_touch": {"sentences": [{"text": draft, "evidence_ids": [items[0]["id"]]}]}}
    doc = {"sources": [{"key": "first_touch", "extracted": pipeline._block("src-first-touch", draft)}]}
    checks = []

    def ask(prompt, schema):
        if schema == pipeline.SCHEMA_REWRITE:
            return {"text": rewritten}
        text = prompt.split("【文字】\n", 1)[1].split("\n【资料】\n", 1)[0]
        checks.append(text)
        first = len(checks) == 1
        return {"sentences": [{"text": t, "verdict": "unsupported" if first else "supported",
                               "problem": "资料没有写到" if first else ""}
                              for t in re.split(r"[。！？；\n]+", text) if t.strip()]}

    monkeypatch.setattr(pipeline, "_ask", ask)
    pipeline._fact_check(doc, items, {}, {}, texts, summaries, "")
    return doc


def test_a_rewrite_that_drops_sometimes_is_flagged_on_the_final_sentence(monkeypatch):
    doc = _guarded_summary(monkeypatch, (2, 0), "学生有时候写到十一点多，周三周五作业尤其多。",
                           "学生写到十一点多，周三周五作业尤其多。")

    assert doc["sources"][0]["extracted"]["text"] == "学生写到十一点多，周三周五作业尤其多。"
    code = [f for f in doc["fact_flags"] if f["kind"] == "intensity"]
    assert [f["sentence"] for f in code] == ["学生写到十一点多，周三周五作业尤其多。"]
    assert code[0]["sentence"] in doc["sources"][0]["extracted"]["text"]


def test_a_draft_code_flag_for_a_sentence_the_rewrite_removed_is_dropped(monkeypatch):
    draft, final = "林同学道歉后，学生情绪激动地没有说话。", "林同学道歉后，学生没有把生气说出来。"
    doc = _guarded_summary(monkeypatch, (20, 0), draft, final)

    assert doc["sources"][0]["extracted"]["text"] == final
    assert [f for f in doc["fact_flags"] if f["kind"] == "label"] == []
    assert all(f["sentence"] != draft for f in doc["fact_flags"])


def test_often_until_late_is_matched_and_ordinary_words_still_are_not():
    assert pipeline._OFTEN_RE.search("学生常至深夜才睡")
    for word in ("正常", "日常", "非常"):
        assert not pipeline._OFTEN_RE.search("学生%s至深夜" % word)
        assert not pipeline._OFTEN_RE.search("学生%s" % word)


# ===========================================================================
# C3d：复述了带“有时”的原话却丢掉“有时”
# ===========================================================================
def _paraphrase_flags(monkeypatch, sentence):
    """Check cell citing the line 52 and 54 items (hedged) and the line 20 item (not),
    so the shared all-quotes-hedged rule stays silent."""
    doc = {"appendix": [{"code": "R2.2", "check": pipeline._block("ap-c-R2.2", sentence)}]}
    _items, flags = _code_flags(
        monkeypatch, [(52, 1), (54, 0), (20, 0)], doc,
        judgements=lambda rows: {"R2.2": {"cites": [r["id"] for r in rows]}})
    return flags


@pytest.mark.parametrize("sentence", [
    "学生考试前一两天躺下后会想题目，约半小时才睡着。",
    "学生在睡前会把重点在脑子里再过一遍，有助于复习。",
])
def test_a_paraphrase_that_drops_the_hedge_is_flagged(monkeypatch, sentence):
    flags = _paraphrase_flags(monkeypatch, sentence)
    assert [(f["block_id"], f["sentence"], f["kind"]) for f in flags] == [
        ("ap-c-R2.2", sentence, "intensity")]
    assert "有时" in flags[0]["problem"]


def test_a_paraphrase_that_keeps_the_hedge_is_not_flagged(monkeypatch):
    assert _paraphrase_flags(monkeypatch, "学生有时会在考试前一两天躺下后想题目。") == []


def test_a_sentence_sharing_under_six_characters_with_the_hedged_quote_is_not_flagged(monkeypatch):
    assert _paraphrase_flags(monkeypatch, "学生考试前会想题目。") == []
