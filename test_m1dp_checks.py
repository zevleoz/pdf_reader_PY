"""DP3：发展计划检查项（WB 抄写、用词、必填、家长版阻断）。"""
from __future__ import annotations

import copy

import m1.plan_checks as checks
import m1.plan_kb as plan_kb
import m1.wb as wb

LESSON_TEXT = (
    "When Didier felt worried he told his friend about the group project. "
    "Didier practiced saying one sentence at a time."
)


def _field(text, src="ai"):
    return {"text": text, "src": src}


def _activity(name="活动一", steps="先做一次示范，再让学生练。", source=None):
    return {
        "id": "s1a1", "name": _field(name), "minutes": 20,
        "steps": _field(steps), "questions": _field("你注意到了什么？"),
        "materials": _field("无"),
        "source": source or {"type": "ai_original", "wb_id": None, "text": ""},
        "block_review": False,
    }


def _session(n, *, primary="R2.2", supporting="R3.3", activities=None):
    return {
        "n": n, "title": _field("第 %d 节" % n), "review": [],
        "focus": {"primary": primary, "supporting": supporting, "text": _field("教学重点")},
        "content": {"mindsets": _field(""), "skills": _field(""), "techniques": _field("")},
        "activities": activities if activities is not None else [_activity()],
        "evidence": _field("能在课堂里说出一次感受。"),
        "practice": [{
            "id": "s%dp1" % n, "code": "R2.2", "name": _field("练习"),
            "task": _field("每天记录一次。"), "frequency": _field("每天 5 分钟"),
            "platform": "StoryMap", "evidence": _field("能拿出记录。"),
        }],
        "next_prep": None if n == 3 else _field("看看记录。"),
    }


def _doc():
    return {"overview": _field("阶段总体目标。"),
            "sessions": [_session(1), _session(2), _session(3)],
            "mentor_notes": _field("")}


def _plan():
    return {
        "wb_grade": 9,
        "goals": [
            {"code": "R2.2", "goal": _field("能在情绪起伏时说出自己的感受"),
             "expected": _field("三节课里能多试几次。")},
            {"code": "R3.3", "goal": _field("能在不同意时说出理由"),
             "expected": _field("能在小组里试一次。")},
        ],
    }


def _install_wb(monkeypatch):
    monkeypatch.setattr(wb, "installed", lambda: True)
    monkeypatch.setattr(wb, "candidates", lambda code, grade, limit=2: [
        {"wb_id": "WB-G9-DEMO-ONE", "cite": "G9 p.10", "match": "部分对应"}])
    monkeypatch.setattr(wb, "lesson_text", lambda wb_id: LESSON_TEXT)
    monkeypatch.setattr(wb, "lesson",
                        lambda wb_id: {"name": "NEGATIVE EMOTIONAL CHAIN"}
                        if wb_id == "WB-G9-DEMO-ONE" else None)


def _texts(items):
    return [item["text"] for item in items]


# ---------------------------------------------------------------------------
# 内部版
# ---------------------------------------------------------------------------
def test_six_word_run_flags_copy(monkeypatch):
    _install_wb(monkeypatch)
    doc = _doc()
    doc["sessions"][0]["activities"][0]["steps"] = _field(
        "When Didier felt worried he told his friend, then we practiced.")
    review = checks.internal_review(_plan(), doc)
    assert any(checks.COPY_TEXT in text for text in _texts(review))
    item = next(item for item in review if item["text"] == checks.COPY_TEXT)
    assert item["label"] == "Session 1 · Activity 1"
    assert item["path"] == ["sessions", 0, "activities", 0]


def test_character_name_from_lesson_flags_copy(monkeypatch):
    _install_wb(monkeypatch)
    doc = _doc()
    doc["sessions"][0]["activities"][0]["steps"] = _field("先让 Didier 说一句，再问感受。")
    assert checks.COPY_TEXT in _texts(checks.internal_review(_plan(), doc))


def test_lesson_title_inside_activity_flags_copy(monkeypatch):
    _install_wb(monkeypatch)
    doc = _doc()
    doc["sessions"][0]["activities"][0]["name"] = _field("NEGATIVE EMOTIONAL CHAIN 改写")
    assert checks.COPY_TEXT in _texts(checks.internal_review(_plan(), doc))


def test_plain_chinese_activity_is_not_copy(monkeypatch):
    _install_wb(monkeypatch)
    doc = _doc()
    doc["sessions"][0]["activities"][0]["steps"] = _field("让学生先说一件今天的小事。")
    assert checks.COPY_TEXT not in _texts(checks.internal_review(_plan(), doc))


def test_promise_word_in_evidence_is_a_review_item():
    doc = _doc()
    doc["sessions"][2]["evidence"] = _field("学生已经掌握这种表达。")
    review = checks.internal_review(_plan(), doc)
    item = next(item for item in review if "已经掌握" in item["text"])
    assert item["label"] == "Session 3 · 课堂预期表现"
    assert "只能写课堂里看得到的表现" in item["text"]


def test_world_bank_source_missing_from_index(monkeypatch):
    _install_wb(monkeypatch)
    doc = _doc()
    doc["sessions"][0]["activities"][0]["source"] = {
        "type": "world_bank", "wb_id": "WB-NOT-THERE", "text": ""}
    review = checks.internal_review(_plan(), doc)
    assert any("不在资料库里" in text for text in _texts(review))


def test_other_source_needs_text():
    doc = _doc()
    doc["sessions"][0]["activities"][0]["source"] = {
        "type": "other", "wb_id": None, "text": ""}
    review = checks.internal_review(_plan(), doc)
    assert any("需要填写来源" in text for text in _texts(review))


def test_required_fields_and_hints():
    doc = _doc()
    doc["sessions"][0]["title"] = _field("")
    doc["sessions"][0]["activities"][0]["steps"] = _field("")
    doc["sessions"][0]["practice"] = []
    doc["sessions"][1]["focus"]["supporting"] = None
    doc["sessions"][2]["activities"][0]["minutes"] = 95
    review = checks.internal_review(_plan(), doc)
    hint = checks.internal_hints(_plan(), doc)
    labels = [item["label"] for item in review]
    assert "Session 1 · 标题" in labels
    assert "Session 1 · Activity 1" in labels
    assert "Session 1 · 课后实践" in labels
    hints = _texts(hint)
    assert any("没有作为任何一节课的主要目标" in text for text in hints)
    assert any("没有关联辅助目标" in text for text in hints)
    assert any("超过 90 分钟" in text for text in hints)


# ---------------------------------------------------------------------------
# 家长版
# ---------------------------------------------------------------------------
def _internal():
    return {"sessions": [
        {"n": 1, "practice": [{"id": "s1p1"}]},
        {"n": 2, "practice": [{"id": "s2p1"}]},
        {"n": 3, "practice": [{"id": "s3p1"}]},
    ], "mentor_notes": _field("")}


def _parent():
    return {
        "intro": _field("这个阶段会围绕表达展开。"),
        "goals": [{"code": "R2.2", "text": _field("这一阶段会练习把感受说清楚。")},
                  {"code": "R3.3", "text": _field("这一阶段会练习说出理由。")}],
        "sessions": [{"n": n, "title": _field("第 %d 节" % n),
                      "summary": _field("这一节练习表达。")} for n in (1, 2, 3)],
        "transition": _field("接下来放进日常。"),
        "practice_options": [
            {"ref": "s1p1", "title": _field("练习一"), "text": _field("每天记录。"),
             "frequency": _field("每天"), "platform": "StoryMap"},
            {"ref": "s2p1", "title": _field("练习二"), "text": _field("每周一次。"),
             "frequency": _field("每周"), "platform": "Echo"},
            {"ref": "s3p1", "title": _field("练习三"), "text": _field("每周回顾。"),
             "frequency": _field("每周"), "platform": "无"},
        ],
        "practice": ["s1p1"],
        "family": [_field("可以听她说说这周的记录。"), _field("每周留一次聊天时间。")],
        "family_seen": [True, True],
        "review": [{"label": _field("觉察"), "text": _field("可以观察她是否说出感受。")},
                   {"label": _field("表达"), "text": _field("可以观察她不同意时的说法。")}],
    }


def test_valid_parent_has_no_blocking():
    assert checks.parent_blocking(_parent(), _plan(), _internal()) == []


def test_parent_over_limit_blocks_with_section_and_number():
    limits = plan_kb.PARENT_LIMITS
    doc = _parent()
    doc["goals"][0]["text"] = _field("练" * (limits["goal"] + 1))
    doc["family"][0] = _field("练" * (limits["family"] + 1))
    texts = _texts(checks.parent_blocking(doc, _plan(), _internal()))
    assert "01 阶段成长目标 · 第 1 项 · 超过 %d 字，请缩短" % limits["goal"] in texts
    assert "04 家庭协作与支持 · 第 1 项 · 超过 %d 字，请缩短" % limits["family"] in texts


def test_parent_at_exact_limit_is_allowed():
    limits = plan_kb.PARENT_LIMITS
    doc = _parent()
    doc["intro"] = _field("练" * limits["intro"])
    doc["goals"][0]["text"] = _field("练" * limits["goal"])
    doc["sessions"][0]["title"] = _field("练" * limits["session_title"])
    doc["sessions"][0]["summary"] = _field("练" * limits["session_summary"])
    doc["transition"] = _field("练" * limits["transition"])
    doc["practice_options"][0]["title"] = _field("练" * limits["practice_title"])
    doc["practice_options"][0]["text"] = _field("练" * limits["practice_text"])
    doc["practice_options"][0]["frequency"] = _field("练" * limits["practice_frequency"])
    doc["family"][0] = _field("练" * limits["family"])
    doc["review"][0]["label"] = _field("练" * limits["review_label"])
    doc["review"][0]["text"] = _field("练" * limits["review_text"])
    assert checks.parent_blocking(doc, _plan(), _internal()) == []


def test_parent_family_unseen_blocks():
    doc = _parent()
    doc["family_seen"] = [True, False]
    items = checks.parent_blocking(doc, _plan(), _internal())
    assert any("导出前要导师看过" in item["text"] for item in items)
    assert any(item["label"] == "04 家庭协作 · 第 2 条" for item in items)


def test_parent_goal_codes_mismatch_blocks():
    doc = _parent()
    doc["goals"] = doc["goals"][:1]
    assert any("目标" in item["text"] for item in checks.parent_blocking(
        doc, _plan(), _internal()))


def test_parent_practice_must_come_from_approved_internal():
    doc = _parent()
    doc["practice"] = ["s9p9"]
    doc["practice_options"][0]["ref"] = "s9p9"
    texts = _texts(checks.parent_blocking(doc, _plan(), _internal()))
    assert sum("不是来自已批准的内部版" in text for text in texts) == 2


def test_parent_requires_one_or_two_picks():
    doc = _parent()
    doc["practice"] = []
    assert any("选择 1 至 2 项" in text for text in
               _texts(checks.parent_blocking(doc, _plan(), _internal())))
    doc["practice"] = ["s1p1", "s2p1", "s3p1"]
    assert any("选择 1 至 2 项" in text for text in
               _texts(checks.parent_blocking(doc, _plan(), _internal())))


def test_parent_copied_eight_characters_blocks():
    doc = _parent()
    plan = _plan()
    plan["personal"] = {"notes": "家长说：最近写作业时总是先沉默很久才开口。"}
    doc["intro"] = _field("家长说：最近写作业时总是先沉默很久才开口。")
    assert any("原文相同" in text for text in
               _texts(checks.parent_blocking(doc, plan, _internal())))


def test_parent_promise_word_and_stale_block():
    doc = _parent()
    doc["goals"][0]["text"] = _field("这个阶段显著提升表达能力。")
    plan = _plan()
    plan["parent_stale"] = True
    texts = _texts(checks.parent_blocking(doc, plan, _internal()))
    assert any("显著提升" in text for text in texts)
    assert any("内部版已更改" in text for text in texts)


def test_parent_hint_for_review_repeating_goal():
    doc = _parent()
    doc["review"][0]["text"] = _field("能在情绪起伏时说出自己的感受")
    hints = checks.parent_hints(doc, _plan(), _internal())
    assert hints and "太接近" in hints[0]["text"]


def test_parent_empty_title_blocks():
    doc = copy.deepcopy(_parent())
    doc["sessions"][0]["title"] = _field("")
    assert any("课程标题是空的" in text for text in
               _texts(checks.parent_blocking(doc, _plan(), _internal())))
