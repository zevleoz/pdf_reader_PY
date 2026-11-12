"""Task B：没有说话人分离的逐字稿，证据归属由提取模型逐条判断。

全部使用虚构内容；模型调用都换成固定回答，不访问真实模型。
"""
from __future__ import annotations

import json

import pytest

import m1.report_store as report_store
import m1.speakers as speakers
from m1 import report_pipeline
from test_m1_report_core import FakeModel, _item, make_report, rdb  # noqa: F401
from test_m1_store import m1db  # noqa: F401

# 平台把整场对话都标在同一个账号标签下：段落里既有提问也有回答
SINGLE_LABEL_TEXT = "\n".join([
    "[00:00:10] 账号甲：你会主动约朋友吗？我不太敢，怕他拒绝。",
    "[00:00:25] 账号甲：上周想约同桌打球，想了两天没说。",
    "[00:00:40] 账号甲：后来他问我要不要一起去，我就答应了。",
    "[00:00:55] 账号甲：其实我也想多认识几个同学。",
])

# 有正常说话人标签的逐字稿（每类至少 3 行，规则才会认定有标签）
LABELLED_TEXT = "\n".join([
    "[00:00:10] 导师：你会主动约朋友吗？",
    "[00:00:15] 导师：上周和同桌相处得怎么样？",
    "[00:00:20] 导师：有什么想说的都可以说。",
    "[00:00:30] 学生：我不太敢，怕他拒绝。",
    "[00:00:35] 学生：上周想约同桌打球，想了两天没说。",
    "[00:00:40] 学生：后来他问我要不要一起去，我就答应了。",
])

ANSWER = "我不太敢，怕他拒绝。"
QUESTION = "你会主动约朋友吗？"


def _speaker_model(roles=None):
    """发言人识别一律回答固定角色；其余提示词交给 FakeModel。"""
    base = FakeModel()
    roles = roles or {}

    def ask(prompt):
        if prompt.startswith(speakers.TASK_SPEAKERS):
            rows = json.loads(prompt.split("【段落】\n", 1)[1])
            return {"turns": [{"n": row["n"], "role": roles.get(row["n"], "学生"),
                               "speech_act": "student_experience"}
                              for row in rows if not row.get("context")]}
        if prompt.startswith(speakers.TASK_RECONCILE):
            return {"turns": []}
        return base(prompt)

    ask.model = base
    return ask


def _run(rdb, monkeypatch, transcript, items):
    ask = _speaker_model()
    ask.model.meeting_items = items
    monkeypatch.setattr(report_pipeline, "call_model", ask)
    report = make_report(rdb, transcript=transcript)
    report_pipeline.generate(rdb.prep_row["id"], actor_id=rdb.alice_id)
    version = report_store.current_version(report["id"])
    return ask, [e for e in version["evidence"] if e["source"] == "M1"]


def test_single_label_transcript_is_detected():
    assert report_pipeline.single_speaker_transcript(SINGLE_LABEL_TEXT) is True
    assert report_pipeline.single_speaker_transcript(LABELLED_TEXT) is False
    # 没有标签，也没有任何一段被认作学生
    assert report_pipeline.single_speaker_transcript(
        "第一句话。\n第二句话。", turns=[{"role": "导师"}, {"role": "导师"}]) is True
    assert report_pipeline.single_speaker_transcript(
        "第一句话。\n第二句话。", turns=[{"role": "导师"}, {"role": "学生"}]) is False


def test_only_the_answer_becomes_student_evidence(rdb, monkeypatch):
    ask, items = _run(rdb, monkeypatch, SINGLE_LABEL_TEXT, [
        _item(QUESTION + ANSWER, "学生", "具体行为事件", ["R2.1"])])

    assert [e["quote"] for e in items if e["speaker"] == "学生"] == [ANSWER]
    assert not any(QUESTION in e["quote"] for e in items if e["speaker"] == "学生")
    prompts = [p for p in ask.model.calls if p.startswith("任务：从逐字稿中提取证据条目")]
    assert prompts and all("speaker_basis" in p for p in prompts)


def test_pure_question_is_not_student_experience(rdb, monkeypatch):
    _ask, items = _run(rdb, monkeypatch, SINGLE_LABEL_TEXT, [
        _item(QUESTION, "学生", "具体行为事件", ["R2.1"])])

    assert items == []


def test_labelled_transcript_keeps_label_based_speakers(rdb, monkeypatch):
    ask, items = _run(rdb, monkeypatch, LABELLED_TEXT, [
        _item(ANSWER, "导师", "其他观察", ["R2.1"])])       # 模型猜的发言人应被忽略

    assert [e["quote"] for e in items] == [ANSWER]
    assert items[0]["speaker"] == "学生"
    prompts = [p for p in ask.model.calls if p.startswith("任务：从逐字稿中提取证据条目")]
    assert prompts and all("speaker_basis" not in p for p in prompts)
