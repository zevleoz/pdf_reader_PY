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


def test_label_majority_fills_unsure():
    turns = [{"label": "发言人1", "role": "导师", "src": "ai"} for _ in range(4)]
    turns.append({"label": "发言人1", "role": "待确认", "src": "ai"})
    assert speakers.label_roles(turns) == {"发言人1": "导师"}
    assert turns[-1]["role"] == "导师" and turns[-1]["src"] == "label"

    split = ([{"label": "发言人2", "role": "导师", "src": "ai"} for _ in range(3)]
             + [{"label": "发言人2", "role": "学生", "src": "ai"} for _ in range(2)])
    assert speakers.label_roles(split) == {"发言人2": ""}
    assert [t["role"] for t in split] == ["导师", "导师", "导师", "学生", "学生"]


def test_ai_total_failure_is_error(rdb, monkeypatch):
    def boom(prompt):
        raise RuntimeError("AI 不可用")

    result = speakers.identify(HEADER_TEXT, boom)
    assert result["status"] == "error"

    ask = _speaker_model(calls=[])

    def failing(prompt):
        if prompt.startswith(speakers.TASK_SPEAKERS):
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
