"""DP3：发展计划 AI 流水线（提示词分区、返回修正、单节重做、家长版）。"""
from __future__ import annotations

import copy
import json
import re

import pytest

import m1.kb as kb
import m1.plan_jobs as plan_jobs
import m1.plan_kb as plan_kb
import m1.plan_pipeline as pipeline
import m1.plan_prompts as prompts
import m1.plan_store as pstore
import m1.report_store as rstore
import m1.store as store
import m1.wb as wb
from m1.jobs import read_job, write_job
from test_m1dp_store import _create, _goal, _published_prep
from test_m1_store import m1db  # noqa: F401  pytest fixture


@pytest.fixture()
def ready(m1db):
    pstore.ensure_tables(m1db.engine)
    prep, report = _published_prep(m1db)
    plan = _create(m1db, prep, report)
    pstore.save_inputs_ai(plan["id"], {
        "strengths": "能主动找朋友聊。",
        "needs": "在小组里说出不同意见。",
        "context": "小组讨论时多半先同意。",
        "interests": "喜欢足球和纪录片。",
    })
    plan = pstore.get_plan(plan["id"])
    pstore.save_goals(plan["id"], plan["rev"], [_goal("R2.2"), _goal("R3.3")])
    return m1db, pstore.get_plan(plan["id"])


def _session_data(n):
    return {
        "title": "第 %d 节课的标题" % n,
        "review": [] if n == 1 else ["上次练了多少次？", "哪一次最有用？"],
        "focus": {"primary": "R2.2" if n != 2 else "R3.3",
                  "supporting": "R3.3" if n == 1 else None,
                  "text": "这节课练习觉察和表达。"},
        "content": {"mindsets": "先把感受说出来。", "skills": "用一句话表达。",
                    "techniques": "先停一下再回答。"},
        "activities": [{
            "name": "活动 %d" % n,
            "minutes": 20,
            "steps": "先做一个例子，再让学生练一次。",
            "questions": "你注意到了什么？",
            "materials": "无",
            "source": {"type": "ai_original", "wb_id": None},
        }],
        "evidence": "能在课堂里说出一次自己的感受。",
        "practice": [{
            "code": "R2.2",
            "name": "练习 %d" % n,
            "task": "每天记录一次。",
            "frequency": "每天 5 分钟",
            "platform": "StoryMap",
            "evidence": "能拿出记录。",
        }],
        "next_prep": None if n == 3 else "看看这周的记录。",
    }


def _parent_result(payload):
    codes = [goal["code"] for goal in payload["goals"]]
    refs = [practice["ref"] for session in payload["sessions"]
            for practice in session.get("practices") or []]
    numbers = [session["n"] for session in payload["sessions"]] or [1, 2, 3]
    return {
        "intro": "这个阶段会围绕表达和觉察展开，课堂里先练小的尝试。",
        "goals": [{"code": code, "text": "这一阶段会练习把感受说清楚。"} for code in codes],
        "sessions": [{"n": n, "title": "第 %d 节课" % n,
                      "summary": "这一节练习觉察和表达。"} for n in numbers],
        "transition": "接下来是把课堂里的练习放进日常。",
        "practice": [{"ref": ref, "title": "日常练习", "text": "每天留五分钟记录。",
                      "frequency": "每天 5 分钟", "platform": "StoryMap"} for ref in refs],
        "family": ["可以听她说说这周的记录。", "每周留一次轻松的聊天时间。"],
        "review": [{"label": "觉察", "text": "可以观察她是否说出自己的感受。"},
                   {"label": "表达", "text": "可以观察她不同意时的说法。"}],
    }


class FakeModel:
    def __init__(self, session=None, parent=None):
        self.prompts = []
        self.session = session or {}
        self.parent = parent

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if prompt.startswith(prompts.TASK_OVERVIEW):
            return {"overview": "这个阶段先练觉察，再把表达放进日常。",
                    "sessions": [{"n": 1, "primary": "R2.2", "supporting": "R3.3"},
                                 {"n": 2, "primary": "R3.3", "supporting": None},
                                 {"n": 3, "primary": "R2.2", "supporting": "R3.3"}]}
        if prompt.startswith(prompts.TASK_SESSION):
            n = int(re.search(r"第 (\d) 节课", prompt).group(1))
            return self.session.get(n) or _session_data(n)
        if prompt.startswith(prompts.TASK_PARENT):
            if self.parent is not None:
                return self.parent
            return _parent_result(json.loads(prompt.split("【内部版】\n", 1)[1]))
        if prompt.startswith(prompts.TASK_GOAL):
            return {"start": "偶尔能说一句。", "expected": "三节课里能多试几次。"}
        if prompt.startswith(prompts.TASK_PERSONAL):
            return {"summary": "家长希望先练表达，再放进日常。"}
        if prompt.startswith(prompts.TASK_INPUTS):
            return {"strengths": "能主动找朋友聊。", "needs": "说出不同意见。",
                    "context": "小组讨论时先同意。", "interests": "足球。"}
        raise AssertionError(prompt[:40])


def _generate(plan, monkeypatch, fake):
    monkeypatch.setattr(pipeline, "call_model", fake)
    pstore.begin_generation(plan["id"], "internal")
    return pipeline.generate(plan["id"])


# ---------------------------------------------------------------------------
# 内部版生成
# ---------------------------------------------------------------------------
def test_generate_runs_overview_then_sessions_in_order(ready, monkeypatch):
    _db, plan = ready
    fake = FakeModel()
    version_id = _generate(plan, monkeypatch, fake)
    assert fake.prompts[0].startswith(prompts.TASK_OVERVIEW)
    session_prompts = [p for p in fake.prompts if p.startswith(prompts.TASK_SESSION)]
    assert len(session_prompts) == 3
    assert "第 1 节课" in session_prompts[0]
    assert "练习 1" in session_prompts[1]
    assert "练习 2" in session_prompts[2]
    version = pstore.get_version(version_id)
    assert [s["n"] for s in version["doc"]["sessions"]] == [1, 2, 3]
    assert [a["id"] for a in version["doc"]["sessions"][0]["activities"]] == ["s1a1"]
    assert pstore.get_plan(plan["id"])["status"] == "review"


def test_prompts_never_include_transcript_private_notes_or_files(ready, monkeypatch):
    db, plan = ready
    rstore.set_transcript(plan["report_id"], text="逐字稿机密标记：学生说……", filename="t.txt")
    pstore.save_personal(plan["id"], plan["rev"], "私下备注：父母刚离婚，请不要提到。")
    pstore.add_file(plan["id"], filename="meeting.txt",
                    text="会议记录原文：家长希望先练表达。", text_status="ok")
    plan = pstore.get_plan(plan["id"])
    fake = FakeModel()
    _generate(plan, monkeypatch, fake)
    for prompt in fake.prompts:
        assert "逐字稿机密标记" not in prompt
        assert "私下备注" not in prompt
        assert "会议记录原文" not in prompt


def test_no_wb_installed_keeps_everything_ai_original(ready, monkeypatch, tmp_path):
    _db, plan = ready
    monkeypatch.setenv("M1_WB_DIR", str(tmp_path / "missing"))
    fake = FakeModel()
    version_id = _generate(plan, monkeypatch, fake)
    for prompt in fake.prompts:
        assert "WB-G9" not in prompt
    version = pstore.get_version(version_id)
    sources = [a["source"]["type"] for s in version["doc"]["sessions"]
               for a in s["activities"]]
    assert sources and set(sources) == {"ai_original"}
    assert version["manifest"]["wb_candidates"] == {"1": [], "2": [], "3": []}


def test_wb_id_outside_candidates_becomes_ai_original_with_check(ready, monkeypatch):
    _db, plan = ready
    monkeypatch.setattr(wb, "installed", lambda: True)
    monkeypatch.setattr(wb, "candidates", lambda code, grade, limit=2: [
        {"wb_id": "WB-G9-DEMO-ONE", "cite": "G9 p.10", "match": "部分对应",
         "limit": "示例限制", "objective": "sample"}])
    monkeypatch.setattr(wb, "lesson_text", lambda wb_id: "When Didier felt worried he told his friend.")
    monkeypatch.setattr(wb, "lesson", lambda wb_id: {"name": "LESSON ONE"})
    override = _session_data(1)
    override["activities"][0]["source"] = {"type": "world_bank", "wb_id": "WB-G9-OUTSIDE"}
    fake = FakeModel(session={1: override})
    version_id = _generate(plan, monkeypatch, fake)
    version = pstore.get_version(version_id)
    activity = version["doc"]["sessions"][0]["activities"][0]
    assert activity["source"]["type"] == "ai_original"
    assert activity["source"]["wb_id"] is None
    assert any("不在本次提供的 WB 参考课里" in item["text"] for item in version["checks"])


def test_session_three_ends_with_one_kb_block_review(ready, monkeypatch):
    _db, plan = ready
    fake = FakeModel()
    version_id = _generate(plan, monkeypatch, fake)
    session = pstore.get_version(version_id)["doc"]["sessions"][2]
    reviews = [a for a in session["activities"] if a.get("block_review")]
    assert len(reviews) == 1
    assert session["activities"][-1] is reviews[0]
    assert reviews[0]["name"]["text"] == plan_kb.block_review()["name"]
    assert reviews[0]["minutes"] == plan_kb.block_review()["minutes"]
    assert reviews[0]["questions"] == {"text": "", "src": "mentor"}
    checks = pstore.get_version(version_id)["checks"]
    assert not any("引导问题" in item.get("text", "") for item in checks)


def test_regenerate_one_session_keeps_mentor_edits_elsewhere(ready, monkeypatch):
    _db, plan = ready
    fake = FakeModel()
    _generate(plan, monkeypatch, fake)
    current = pstore.current_version(plan["id"], "internal")
    doc = copy.deepcopy(current["doc"])
    doc["sessions"][0]["title"]["text"] = "导师改的第 1 节"
    doc["sessions"][2]["title"]["text"] = "导师改的第 3 节"
    plan = pstore.get_plan(plan["id"])
    pstore.save_internal(plan["id"], plan["rev"], doc, [])
    pstore.begin_generation(plan["id"], "internal")
    new_id = pipeline.regenerate(plan["id"], 2)
    new_doc = pstore.get_version(new_id)["doc"]
    assert new_doc["sessions"][0]["title"]["text"] == "导师改的第 1 节"
    assert new_doc["sessions"][1]["title"]["text"] == "第 2 节课的标题"
    assert new_doc["sessions"][2]["title"]["text"] == "导师改的第 3 节"


def test_bad_json_twice_fails_job_and_restores_state(ready, monkeypatch, tmp_path):
    _db, plan = ready
    monkeypatch.setattr(pipeline, "call_model", lambda prompt: "not json")
    pstore.begin_generation(plan["id"], "internal")
    job_dir = tmp_path / "jobs"
    monkeypatch.setattr("m1.jobs.JOB_DIR", str(job_dir))
    monkeypatch.setattr(plan_jobs, "JOB_DIR", str(job_dir))
    job_id = "a" * 32
    write_job(job_id, status="queued", plan_id=plan["id"], kind="plan_generate",
              steps=plan_jobs.new_steps("plan_generate"))
    args = {"plan_id": plan["id"], "kind": "plan_generate",
            "previous_status": "inputs"}
    with pytest.raises(pipeline.PlanError, match="格式无效"):
        plan_jobs.run_job(job_id, args)
    assert pstore.get_plan(plan["id"])["status"] == "inputs"
    job = read_job(job_id)
    assert job["status"] == "error"
    assert job["message"].startswith("生成失败")


def test_generate_job_writes_activity(ready, monkeypatch, tmp_path):
    _db, plan = ready
    monkeypatch.setattr(pipeline, "call_model", FakeModel())
    job_dir = tmp_path / "jobs"
    monkeypatch.setattr("m1.jobs.JOB_DIR", str(job_dir))
    monkeypatch.setattr(plan_jobs, "JOB_DIR", str(job_dir))
    pstore.begin_generation(plan["id"], "internal")
    job_id = "b" * 32
    write_job(job_id, status="queued", plan_id=plan["id"], kind="plan_generate",
              steps=plan_jobs.new_steps("plan_generate"))
    args = {"plan_id": plan["id"], "kind": "plan_generate",
            "previous_status": "inputs", "actor_id": plan["mentor_user_id"]}
    plan_jobs.run_job(job_id, args)
    rows = store.list_activity(plan["prep_id"], plan["student_id"])
    assert any("内部教学计划已生成" in row["text"] for row in rows)


# ---------------------------------------------------------------------------
# 家长版
# ---------------------------------------------------------------------------
def _approved(plan, monkeypatch, fake):
    version_id = _generate(plan, monkeypatch, fake)
    plan = pstore.get_plan(plan["id"])
    pstore.approve(plan["id"], plan["mentor_user_id"])
    return version_id


def test_parent_prompt_has_no_report_transcript_or_notes(ready, monkeypatch):
    _db, plan = ready
    rstore.set_transcript(plan["report_id"], text="逐字稿机密标记：学生说……", filename="t.txt")
    pstore.save_personal(plan["id"], plan["rev"], "私下备注：父母刚离婚。")
    fake = FakeModel()
    version_id = _generate(pstore.get_plan(plan["id"]), monkeypatch, fake)
    plan = pstore.get_plan(plan["id"])
    doc = copy.deepcopy(pstore.get_version(version_id)["doc"])
    doc["mentor_notes"]["text"] = "导师内部备注：不要提家庭。"
    pstore.save_internal(plan["id"], plan["rev"], doc, [])
    plan = pstore.get_plan(plan["id"])
    pstore.approve(plan["id"], plan["mentor_user_id"])
    fake.prompts.clear()
    pstore.begin_generation(plan["id"], "parent")
    pipeline.generate_parent(plan["id"])
    prompt = fake.prompts[-1]
    assert "逐字稿机密标记" not in prompt
    assert "私下备注" not in prompt
    assert "导师内部备注" not in prompt


def test_parent_prompt_lengths_match_shared_limits(ready, monkeypatch):
    _db, plan = ready
    _approved(plan, monkeypatch, FakeModel())
    plan = pstore.get_plan(plan["id"])
    fake = FakeModel()
    monkeypatch.setattr(pipeline, "call_model", fake)
    pstore.begin_generation(plan["id"], "parent")
    pipeline.generate_parent(plan["id"])
    prompt = fake.prompts[-1]

    limits = plan_kb.PARENT_LIMITS
    phrases = [
        "60 至 %(intro)d 字" % limits,
        "不超过 %(goal)d 字" % limits,
        "不超过 %(session_title)d 字" % limits,
        "30 至 %(session_summary)d 字" % limits,
        "不超过 %(transition)d 字" % limits,
        "分别不超过 %(practice_title)d、%(practice_text)d、%(practice_frequency)d 字" % limits,
        "每条不超过 %(family)d 字" % limits,
        "不超过 %(review_label)d 字" % limits,
        "不超过 %(review_text)d 字" % limits,
    ]
    for phrase in phrases:
        assert phrase in prompt
    for old in ("120 字", "80 字"):
        assert old not in prompt


def test_parent_truncates_fields_to_shared_limits(ready, monkeypatch):
    _db, plan = ready
    _approved(plan, monkeypatch, FakeModel())
    plan = pstore.get_plan(plan["id"])
    internal = pstore.current_version(plan["id"], "internal")["doc"]
    parent = _parent_result({
        "goals": plan["goals"],
        "sessions": [{"n": session["n"],
                      "practices": [{"ref": practice["id"]}
                                    for practice in session.get("practice") or []]}
                     for session in internal["sessions"]],
    })
    limits = plan_kb.PARENT_LIMITS
    long_goal = "练" * (limits["goal"] - 1) + "。" + "练" * 20 + "。"
    parent["goals"][0]["text"] = long_goal
    parent["family"][0] = "练" * (limits["family"] - 1) + "。" + "练" * 20 + "。"

    fake = FakeModel(parent=parent)
    monkeypatch.setattr(pipeline, "call_model", fake)
    pstore.begin_generation(plan["id"], "parent")
    parent_id = pipeline.generate_parent(plan["id"])
    version = pstore.get_version(parent_id)
    assert len(version["doc"]["goals"][0]["text"]["text"]) == limits["goal"]
    assert len(version["doc"]["family"][0]["text"]) == limits["family"]
    labels = [item["text"] for item in version["checks"]]
    assert any("超过 %d 字，已删去后面的句子" % limits["goal"] in text for text in labels)
    assert any("超过 %d 字，已删去后面的句子" % limits["family"] in text for text in labels)


def test_parent_wrong_goal_count_fails(ready, monkeypatch):
    _db, plan = ready
    _approved(plan, monkeypatch, FakeModel())
    plan = pstore.get_plan(plan["id"])
    bad = _parent_result({"goals": [{"code": "R2.2"}, {"code": "R3.3"}],
                          "sessions": [{"n": 1, "practices": [{"ref": "s1p1"}]}]})
    bad["goals"] = bad["goals"][:1]
    monkeypatch.setattr(pipeline, "call_model", FakeModel(parent=bad))
    pstore.begin_generation(plan["id"], "parent")
    with pytest.raises(pipeline.PlanError, match="目标数量"):
        pipeline.generate_parent(plan["id"])
    pstore.fail_generation(plan["id"], "parent", previous="none")
    assert pstore.get_plan(plan["id"])["parent_status"] == "none"


def test_parent_picks_only_practice_when_there_is_exactly_one(ready, monkeypatch):
    _db, plan = ready
    doc = {
        "overview": {"text": "总体目标。"},
        "sessions": [{
            "n": 1, "title": {"text": "第 1 节"}, "review": [],
            "focus": {"primary": "R2.2", "supporting": None, "text": "重点"},
            "content": {"mindsets": "", "skills": "", "techniques": ""},
            "activities": [], "evidence": {"text": "表现"},
            "practice": [{"id": "s1p1", "code": "R2.2", "name": {"text": "练习"},
                          "task": {"text": "任务"}, "frequency": {"text": "每天"},
                          "platform": "StoryMap", "evidence": {"text": "记录"}}],
            "next_prep": {"text": "下次"},
        }],
        "mentor_notes": {"text": ""},
    }
    pstore.begin_generation(plan["id"], "internal")
    version = pstore.add_version(plan["id"], part="internal", kind="ai_draft",
                                 ai_doc=doc, doc=doc, checks=[])
    pstore.finish_generation(plan["id"], "internal", version_id=version["id"])
    plan = pstore.get_plan(plan["id"])
    pstore.approve(plan["id"], plan["mentor_user_id"])
    fake = FakeModel()
    monkeypatch.setattr(pipeline, "call_model", fake)
    pstore.begin_generation(plan["id"], "parent")
    parent_id = pipeline.generate_parent(plan["id"])
    parent_doc = pstore.get_version(parent_id)["doc"]
    assert parent_doc["practice"] == ["s1p1"]
    assert parent_doc["family_seen"] == [False, False]


def test_parent_leaves_practice_unpicked_when_several(ready, monkeypatch):
    _db, plan = ready
    _approved(plan, monkeypatch, FakeModel())
    plan = pstore.get_plan(plan["id"])
    monkeypatch.setattr(pipeline, "call_model", FakeModel())
    pstore.begin_generation(plan["id"], "parent")
    parent_id = pipeline.generate_parent(plan["id"])
    parent_doc = pstore.get_version(parent_id)["doc"]
    assert parent_doc["practice"] == []
    assert len(parent_doc["practice_options"]) == 3
    codes = [goal["code"] for goal in parent_doc["goals"]]
    assert codes == [goal["code"] for goal in plan["goals"]]
    assert all(kb.ability(code) for code in codes)
