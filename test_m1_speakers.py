"""M1R-P1：发言人识别。所有 AI 调用都换成虚构回答，不访问真实模型。"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import inspect

import m1.report_store as report_store
import m1.speakers as speakers
from m1 import report_pipeline
from test_m1_report_core import (FakeModel, _item, admin_login, advisor_login,  # noqa: F401
                                 client, make_report, rdb, url)
from test_m1_store import m1db  # noqa: F401  临时库与虚构学生（rdb 依赖它）

LABELLED = "\n".join([
    "[00:00:10] 导师：最近情绪怎么样？",
    "[00:00:20] 学生：上周数学小测没考好。",
    "[00:00:30] 导师：那你当时怎么做的？",
    "[00:00:40] 学生：我没跟同学说，一个人趴着。",
    "[00:00:50] 导师：下次可以试试深呼吸。",
    "[00:01:00] 学生：我觉得可以试试。",
])

HEADER_TEXT = "\n".join([
    "发言人1 00:00:05", "我们先看看上周的情况。",
    "发言人2 00:00:15", "上周数学小测没考好。",
    "发言人1 00:00:25", "那你当时怎么做的。",
    "发言人2 00:00:35", "我没跟同学说。",
    "发言人1 00:00:45", "下次可以试试深呼吸。",
    "发言人2 00:00:55", "后来慢慢好一点。",
    "发言人1 00:01:05", "我们再看看别的。",
    "发言人2 00:01:15", "我觉得可以试试。",
])

MENTOR_LINE = "我们先看看上周的情况。"
MENTOR_TRANSCRIPT = "\n".join([
    "发言人1 00:00:05", MENTOR_LINE,
    "发言人2 00:00:15", "上周数学小测没考好。",
    "发言人1 00:00:25", "那你当时怎么做的。",
    "发言人1 00:00:35", "我们再看看别的。",
    "发言人2 00:00:45", "我没跟同学说。",
    "发言人2 00:00:55", "后来慢慢好一点。",
])


def _speaker_model(roles=None, calls=None):
    """发言人提示词按标签或给定表回答；其余交给 FakeModel。"""
    base = FakeModel()
    roles = roles or {"发言人1": "导师", "发言人2": "学生"}

    def ask(prompt):
        if calls is not None:
            calls.append(prompt)
        if prompt.startswith(speakers.TASK_SPEAKERS):
            rows = json.loads(prompt.split("【段落】\n", 1)[1])
            return {"turns": [{"n": row["n"], "role": roles.get(row["label"], "待确认")}
                              for row in rows if not row.get("context")]}
        return base(prompt)

    ask.model = base
    return ask


def test_rule_labels_need_no_ai():
    def ask(prompt):
        raise AssertionError("有标签时不应调用 AI")

    result = speakers.identify(LABELLED, ask)
    assert result["status"] == "done"
    assert result["format"] == "labelled"
    assert result["turns"]
    assert all(t["role"] in ("导师", "学生") and t["src"] == "rule" for t in result["turns"])


def test_header_form_labels():
    def ask(prompt):
        rows = json.loads(prompt.split("【段落】\n", 1)[1])
        return {"turns": [{"n": row["n"],
                           "role": "导师" if row["label"] == "发言人1" else "学生"}
                          for row in rows if not row.get("context")]}

    result = speakers.identify(HEADER_TEXT, ask)
    turns = result["turns"]
    assert result["format"] == "labelled"
    assert len(turns) == 8
    assert turns[0]["text"] == "我们先看看上周的情况。"          # 文本行接在标题后
    assert turns[1]["text"] == "上周数学小测没考好。"
    assert speakers.label_roles(turns) == {"发言人1": "导师", "发言人2": "学生"}


def test_colon_in_speech_is_not_a_label():
    text = LABELLED + "\n[00:01:10] 学生：我觉得：其实还好。"
    result = speakers.parse(text)
    assert result["format"] == "labelled"
    assert {t["label"] for t in result["turns"]} == {"导师", "学生"}
    assert any("我觉得：其实还好" in t["text"] for t in result["turns"])
    assert all(t["label"] != "我觉得" for t in result["turns"])


def test_unlabelled_lines_and_long_split():
    sentence = "甲" * 29 + "。"
    long_line = sentence * 15
    assert len(long_line) == 450
    result = speakers.parse(long_line)
    assert result["format"] == "unlabelled"
    turns = result["turns"]
    assert len(turns) == 3
    assert all(len(t["text"]) <= 200 for t in turns)
    assert "".join(t["text"] for t in turns) == long_line


def test_bad_ai_roles_become_unsure():
    parsed = speakers.parse("第一句话。\n第二句话。\n第三句话。")
    turns = parsed["turns"]

    def ask(prompt):
        return {"turns": [{"n": 1, "role": "老师"}, {"n": 99, "role": "学生"}]}

    stats = speakers.assign_roles(turns, ask)
    assert stats["ai_set"] == 0
    assert turns[0]["role"] == "待确认"
    assert all(t["role"] == "待确认" for t in turns)


def test_apply_edits_resets_speech_act_on_label_edit():
    turns = [
        {"n": 1, "label": "发言人1", "time": "", "text": "最近怎么样？", "role": "导师",
         "speech_act": "mentor_question", "src": "ai"},
        {"n": 2, "label": "发言人2", "time": "", "text": "还好。", "role": "导师",
         "speech_act": "mentor_question", "src": "ai"},
    ]
    speakers.apply_edits(turns, {"发言人1": "学生", "发言人2": "学生"}, {})
    assert [t["role"] for t in turns] == ["学生", "学生"]
    assert all(t["speech_act"] == "unclear" for t in turns)
    assert all(t["src"] == "edited" for t in turns)


def test_apply_edits_recomputes_speech_act_on_turn_edit():
    turns = [
        {"n": 1, "label": "", "time": "", "text": "最近怎么样？", "role": "学生",
         "speech_act": "student_experience", "src": "ai"},
        {"n": 2, "label": "", "time": "", "text": "还好。", "role": "导师",
         "speech_act": "mentor_question", "src": "ai"},
    ]
    speakers.apply_edits(turns, {}, {1: "导师", 2: "学生"})
    assert turns[0]["role"] == "导师" and turns[0]["speech_act"] == "mentor_question"
    assert turns[1]["role"] == "学生" and turns[1]["speech_act"] == "unclear"


def test_reconcile_prompt_contains_all_unlabelled_text():
    text = "\n".join(["我觉得很累。", "你可以先说说上周。", "上周小测没考好。"])
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        if prompt.startswith(speakers.TASK_SPEAKERS):
            rows = json.loads(prompt.split("【段落】\n", 1)[1])
            acts = {1: ("学生", "student_emotion_or_thought"),
                    2: ("导师", "mentor_guidance"),
                    3: ("学生", "student_experience")}
            return {"turns": [{"n": row["n"], "role": acts[row["n"]][0],
                               "speech_act": acts[row["n"]][1]}
                              for row in rows if not row.get("context")]}
        return {"turns": []}

    result = speakers.identify(text, ask)
    reconcile = [p for p in prompts if p.startswith(speakers.TASK_RECONCILE)]
    assert reconcile, "无标签逐字稿也应执行全场复核"
    for turn in result["turns"]:
        assert turn["text"] in reconcile[0]


def test_reconcile_prompt_contains_all_labelled_ai_text():
    turns = []
    for number in range(1, 13):
        turns.append({"n": number, "label": "发言人1" if number % 2 else "发言人2",
                      "time": "", "text": "需要复核的第 %d 段原文" % number,
                      "role": "学生", "speech_act": "student_experience", "src": "ai"})
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return {"turns": []}

    speakers._reconcile_roles(turns, ask)
    assert prompts
    for turn in turns:
        assert turn["text"] in prompts[0]


def test_speaker_algorithm_change_invalidates_cache(monkeypatch):
    text = "一段虚构会议原文"
    row = {"status": "done", "transcript_hash": speakers.transcript_hash(text)}
    report = {"transcript_text": text}
    assert speakers.is_current(row, report)
    assert hasattr(speakers, "SPEAKER_ALGORITHM_VERSION")
    monkeypatch.setattr(speakers, "SPEAKER_ALGORITHM_VERSION",
                        speakers.SPEAKER_ALGORITHM_VERSION + "-test")
    assert not speakers.is_current(row, report)


def test_unlabelled_student_thought_and_mentor_guidance():
    text = "我觉得自己很没用。\n你可以先说说上周的事。"

    def ask(prompt):
        rows = json.loads(prompt.split("【段落】\n", 1)[1])
        acts = {1: ("学生", "student_emotion_or_thought"),
                2: ("导师", "mentor_guidance")}
        return {"turns": [{"n": row["n"], "role": acts[row["n"]][0],
                           "speech_act": acts[row["n"]][1]}
                          for row in rows if not row.get("context")]}

    result = speakers.identify(text, ask)
    assert result["status"] == "done"
    assert [(t["role"], t["speech_act"]) for t in result["turns"]] == [
        ("学生", "student_emotion_or_thought"), ("导师", "mentor_guidance")]


def test_window_has_following_context_and_full_text(monkeypatch):
    monkeypatch.setattr(speakers, "WINDOW_TURNS", 1)
    long_text = "乙" * 400
    text = "\n".join(["第一段。", "第二段。", long_text, "第四段。", "第五段。"])
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        rows = json.loads(prompt.split("【段落】\n", 1)[1])
        return {"turns": [{"n": row["n"], "role": "学生",
                           "speech_act": "student_experience"}
                          for row in rows if not row.get("context")]}

    result = speakers.identify(text, ask)
    rows = json.loads(prompts[0].split("【段落】\n", 1)[1])
    assert {r["n"] for r in rows if r.get("context") and r["n"] > 1} == {2, 3, 4, 5}
    assert long_text in prompts[0]                       # 400 字全文，没有 300 字截断
    assert "".join(t["text"] for t in result["turns"]) == "第一段。第二段。" + long_text \
        + "第四段。第五段。"


def test_single_long_sentence_is_not_truncated():
    text = "甲" * 500

    def ask(prompt):
        rows = json.loads(prompt.split("【段落】\n", 1)[1])
        return {"turns": [{"n": row["n"], "role": "学生",
                           "speech_act": "student_experience"}
                          for row in rows if not row.get("context")]}

    result = speakers.identify(text, ask)
    assert "".join(t["text"] for t in result["turns"]) == text


def test_ai_cannot_override_rule_or_context_turns():
    text = "\n".join([
        "[00:00:05] 导师：我们先看看上周的情况。",
        "[00:00:10] 导师：有什么想聊的吗？",
        "[00:00:15] 导师：慢慢说。",
        "[00:00:20] 发言人1：上周数学小测没考好。",
        "[00:00:25] 发言人1：我一个人趴着。",
        "[00:00:30] 发言人1：后来好一点。",
    ])

    def ask(prompt):
        rows = json.loads(prompt.split("【段落】\n", 1)[1])
        turns = [{"n": row["n"], "role": "学生", "speech_act": "student_experience"}
                 for row in rows if not row.get("context")]
        turns.append({"n": 1, "role": "学生", "speech_act": "student_experience"})
        return {"turns": turns}

    result = speakers.identify(text, ask)
    turns = result["turns"]
    assert len(turns) == 6                               # 不新增、不重复段
    assert [t["role"] for t in turns[:3]] == ["导师", "导师", "导师"]
    assert turns[1]["speech_act"] == "mentor_question"
    assert [t["role"] for t in turns[3:]] == ["学生", "学生", "学生"]


def test_reconcile_corrects_only_target_turns():
    turns = [
        {"n": 1, "label": "导师", "time": "", "text": "最近怎么样？", "role": "导师",
         "speech_act": "mentor_question", "src": "rule"},
        {"n": 2, "label": "发言人1", "time": "", "text": "还行。", "role": "待确认",
         "speech_act": "unclear", "src": "ai"},
    ]

    def ask(prompt):
        assert prompt.startswith(speakers.TASK_RECONCILE)
        return {"turns": [{"n": 1, "role": "学生", "speech_act": "student_experience"},
                          {"n": 2, "role": "学生", "speech_act": "student_experience"}]}

    assert speakers._reconcile_roles(turns, ask) == 1
    assert turns[0]["role"] == "导师" and turns[0]["src"] == "rule"
    assert turns[1]["role"] == "学生" and turns[1]["speech_act"] == "student_experience"


def test_prompt_text_preserves_marked_text_contract():
    turns = [
        {"n": 1, "label": "", "time": "00:00:10", "text": "今天很开心", "role": "导师",
         "speech_act": "mentor_question", "src": "rule"},
        {"n": 2, "label": "", "time": "", "text": "今天很开心吗", "role": "学生",
         "speech_act": "student_emotion_or_thought", "src": "rule"},
    ]
    assert speakers.marked_text(turns) == ("[00:00:10] 导师：今天很开心\n"
                                           "学生：今天很开心吗")
    assert speakers.prompt_text(turns) == (
        "[00:00:10] 导师[mentor_question]：今天很开心\n"
        "学生[student_emotion_or_thought]：今天很开心吗")


def test_label_majority_does_not_fill_unsure():
    turns = [{"label": "发言人1", "role": "导师", "src": "ai"} for _ in range(4)]
    turns.append({"label": "发言人1", "role": "待确认", "src": "ai"})
    assert speakers.label_roles(turns) == {"发言人1": "导师"}
    assert turns[-1]["role"] == "待确认" and turns[-1]["src"] == "ai"

    split = ([{"label": "发言人2", "role": "导师", "src": "ai"} for _ in range(3)]
             + [{"label": "发言人2", "role": "学生", "src": "ai"} for _ in range(2)])
    assert speakers.label_roles(split) == {"发言人2": ""}
    assert [t["role"] for t in split] == ["导师", "导师", "导师", "学生", "学生"]


def test_ai_total_failure_degrades_to_unsure(rdb, monkeypatch):
    def boom(prompt):
        raise RuntimeError("AI 不可用")

    result = speakers.identify(HEADER_TEXT, boom)
    assert result["status"] == "done"
    assert all(t["role"] == "待确认" and t["speech_act"] == "unclear"
               for t in result["turns"])
    assert "待确认" in result["message"] and "继续生成" in result["message"]

    ask = _speaker_model(calls=[])

    def failing(prompt):
        if prompt.startswith((speakers.TASK_SPEAKERS, speakers.TASK_RECONCILE)):
            raise RuntimeError("AI 不可用")
        return ask(prompt)

    monkeypatch.setattr(report_pipeline, "call_model", failing)
    report = make_report(rdb, transcript=HEADER_TEXT)
    version_id = report_pipeline.generate(rdb.prep_row["id"], actor_id=rdb.alice_id)
    assert version_id
    assert report_store.get_report_by_id(report["id"])["current_version_id"] == version_id


def test_marked_text_and_lookup():
    turns = [
        {"n": 1, "label": "", "time": "00:00:10", "text": "今天很开心", "role": "导师",
         "src": "rule"},
        {"n": 2, "label": "", "time": "00:00:20", "text": "今天很开心吗", "role": "学生",
         "src": "rule"},
    ]
    assert speakers.marked_text(turns) == "[00:00:10] 导师：今天很开心\n[00:00:20] 学生：今天很开心吗"
    lookup = speakers.role_lookup(turns)
    assert lookup("今天很开心") == "待确认"       # 两段不同角色
    assert lookup("吗") == "学生"                 # 只落在第二段


def test_mentor_words_never_become_student_evidence(rdb, monkeypatch):
    ask = _speaker_model()
    ask.model.meeting_items = [_item(MENTOR_LINE, "学生", "具体行为事件", ["R1.1"])]
    monkeypatch.setattr(report_pipeline, "call_model", ask)

    report = make_report(rdb, transcript=MENTOR_TRANSCRIPT)
    report_pipeline.generate(rdb.prep_row["id"], actor_id=rdb.alice_id)
    version = report_store.current_version(report["id"])
    matched = [e for e in version["evidence"] if e["quote"] == MENTOR_LINE]
    assert all(e["speaker"] != "学生" for e in matched)
    row = report_store.get_speakers(report["id"])
    assert row and row["status"] == "done"
    assert row["labels"]["发言人1"] == "导师"


def test_reuse_and_stale(rdb, monkeypatch):
    calls = []
    ask = _speaker_model(calls=calls)
    monkeypatch.setattr(report_pipeline, "call_model", ask)
    report = make_report(rdb, transcript=HEADER_TEXT)

    report_pipeline.generate(rdb.prep_row["id"], actor_id=rdb.alice_id)
    assert sum(1 for p in calls if p.startswith(speakers.TASK_SPEAKERS)) == 1
    report_pipeline.generate(rdb.prep_row["id"], actor_id=rdb.alice_id)
    assert sum(1 for p in calls if p.startswith(speakers.TASK_SPEAKERS)) == 1

    report_store.set_transcript(report["id"], text=HEADER_TEXT + "\n发言人1 00:01:25\n再看一次。")
    report_pipeline.generate(rdb.prep_row["id"], actor_id=rdb.alice_id)
    assert sum(1 for p in calls if p.startswith(speakers.TASK_SPEAKERS)) == 2


def test_speakers_api(client, rdb, monkeypatch):
    admin_login(client, rdb)
    ask = _speaker_model()
    monkeypatch.setattr(report_pipeline, "call_model", ask)
    base = url(rdb, "/speakers")

    res = client.get(base)
    assert res.status_code == 200
    assert res.get_json()["speakers"]["status"] == "none"

    report = make_report(rdb, transcript=HEADER_TEXT)
    report_pipeline.generate(rdb.prep_row["id"], actor_id=rdb.alice_id)
    res = client.get(base)
    data = res.get_json()["speakers"]
    assert data["status"] == "done" and data["counts"]["导师"] == 4
    assert data["counts"]["学生"] == 4

    res = client.put(base, json={"labels": {"发言人1": "学生"}})
    data = res.get_json()
    assert data["notice"] == "发言人已修改，重新生成报告后生效"
    assert all(t["role"] == "学生" for t in data["speakers"]["turns"]
               if t["label"] == "发言人1")

    res = client.put(base, json={"turns": {"1": "老师"}})
    assert res.status_code == 400

    report_store.set_status(report["id"], "generating")
    res = client.put(base, json={"labels": {"发言人1": "学生"}})
    assert res.status_code == 409
    report_store.set_status(report["id"], "needs_check")

    advisor_login(client, rdb.alice_id, "Alice", m1_access=1, detail_level="summary",
                  student_scope="all")
    assert client.get(base).status_code == 403
    assert client.put(base, json={"labels": {"发言人1": "学生"}}).status_code == 403


def test_table_created(rdb):
    report_store.ensure_tables(rdb.engine)
    assert "m1_report_speakers" in inspect(rdb.engine).get_table_names()
