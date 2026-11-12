"""DP1：发展计划数据层（建表、版本、状态机、并发与固定文字）。"""
from __future__ import annotations

import pytest

import m1.plan_kb as plan_kb
import m1.plan_store as pstore
import m1.report_store as report_store
from test_m1_store import m1db  # noqa: F401  pytest fixture


@pytest.fixture()
def plan_db(m1db):
    pstore.ensure_tables(m1db.engine)
    return m1db


def _published_prep(db, *, student_id=None, mentor_id=None):
    prep = db.prep(student_id or db.student_id, mentor_id or db.alice_id)
    report = report_store.get_or_create_report(prep["id"], db.alice_id)
    report_store.add_version(report["id"], y4_ratings={}, evidence=[], ai_doc={},
                             doc={}, checks=[], manifest={}, status="approved")
    report_store.publish(report["id"], db.alice_id)
    return prep, report_store.get_report(prep["id"])


def _drafted_prep(db, *, student_id=None):
    prep = db.prep(student_id or db.student_id, db.alice_id)
    report = report_store.get_or_create_report(prep["id"], db.alice_id)
    report_store.add_version(report["id"], y4_ratings={}, evidence=[], ai_doc={},
                             doc={}, checks=[], manifest={}, status="ai_draft")
    return prep, report_store.get_report(prep["id"])


def _create(db, prep, report, **overrides):
    data = dict(prep_id=prep["id"], report_id=report["id"],
                report_version_id=report.get("current_version_id"),
                mentor_user_id=db.alice_id, block_no=1,
                period_start="2026-11-17", period_end="2026-12-15",
                credits="3", sessions=3, wb_grade=9, created_by=db.alice_id)
    data.update(overrides)
    return pstore.create_plan(prep["student_id"], **data)


def _new_plan(db, **overrides):
    prep, report = _published_prep(db)
    return _create(db, prep, report, **overrides)


def _goal(code="R2.2", locked=True, text="能在情绪起伏时说出自己的感受"):
    return {"code": code,
            "goal": {"text": text, "src": "mentor"},
            "start": {"text": "偶尔能说", "src": "ai"},
            "expected": {"text": "多数时候能说", "src": "ai"},
            "locked": locked}


def _approved_plan(db):
    plan = _new_plan(db)
    pstore.save_goals(plan["id"], plan["rev"], [_goal()])
    plan = pstore.get_plan(plan["id"])
    pstore.begin_generation(plan["id"], "internal")
    version = pstore.add_version(plan["id"], part="internal", kind="ai_draft",
                                 ai_doc={"sessions": []}, doc={"sessions": []},
                                 checks=[{"level": "review", "text": "有一条待核对"}])
    pstore.finish_generation(plan["id"], "internal", version_id=version["id"])
    plan = pstore.get_plan(plan["id"])
    pstore.approve(plan["id"], db.alice_id)
    return pstore.get_plan(plan["id"])


# ---------------------------------------------------------------------------
# 建表 / 新建
# ---------------------------------------------------------------------------
def test_plan_tables_created(plan_db):
    from sqlalchemy import inspect
    names = set(inspect(plan_db.engine).get_table_names())
    assert {"m1_plans", "m1_plan_versions", "m1_plan_files"} <= names


def test_create_requires_ai_draft_report(plan_db):
    prep = plan_db.prep()
    report = report_store.get_or_create_report(prep["id"])
    with pytest.raises(ValueError, match="还没有生成 AI 草稿"):
        _create(plan_db, prep, report)


def test_create_from_ai_draft_report(plan_db):
    prep, report = _drafted_prep(plan_db)
    plan = _create(plan_db, prep, report)
    assert plan["report_version_id"] == report["current_version_id"]
    assert plan["inputs"]["report_status_at_read"] == "ai_draft"


def test_create_refuses_duplicate_block(plan_db):
    prep, report = _published_prep(plan_db)
    _create(plan_db, prep, report)
    with pytest.raises(ValueError, match="已有发展计划"):
        _create(plan_db, prep, report)


def test_create_refuses_two_sessions_and_bad_dates(plan_db):
    prep, report = _published_prep(plan_db)
    with pytest.raises(ValueError, match="固定为 3 节"):
        _create(plan_db, prep, report, sessions=2)
    with pytest.raises(ValueError, match="不能早于"):
        _create(plan_db, prep, report, period_start="2026-12-16")


def test_create_copies_report_version_and_mentor(plan_db):
    prep, report = _published_prep(plan_db)
    plan = _create(plan_db, prep, report)
    assert plan["status"] == "inputs"
    assert plan["report_version_id"] == report["current_version_id"]
    assert plan["mentor_user_id"] == plan_db.alice_id
    assert plan["goals"] == []


# ---------------------------------------------------------------------------
# 目标
# ---------------------------------------------------------------------------
def test_goals_refuse_four_unknown_and_duplicate(plan_db):
    plan = _new_plan(plan_db)
    with pytest.raises(ValueError, match="最多 3 项"):
        pstore.save_goals(plan["id"], plan["rev"],
                          [_goal("R1.1"), _goal("R1.2"), _goal("R1.3"), _goal("R2.1")])
    with pytest.raises(ValueError, match="编号无效"):
        pstore.save_goals(plan["id"], plan["rev"], [_goal("NOPE")])
    with pytest.raises(ValueError, match="重复"):
        pstore.save_goals(plan["id"], plan["rev"], [_goal("R2.2"), _goal("R2.2")])


def test_goal_names_come_from_kb_not_stored(plan_db):
    plan = _new_plan(plan_db)
    item = _goal()
    item["name"] = "导师自己编的名字"
    updated = pstore.save_goals(plan["id"], plan["rev"], [item])
    assert updated["goals"] == [{"code": "R2.2",
                                 "goal": {"text": "能在情绪起伏时说出自己的感受",
                                          "src": "mentor"},
                                 "start": {"text": "偶尔能说", "src": "ai"},
                                 "expected": {"text": "多数时候能说", "src": "ai"},
                                 "locked": True}]


def test_stale_rev_is_refused(plan_db):
    plan = _new_plan(plan_db)
    pstore.save_goals(plan["id"], plan["rev"], [_goal()])
    with pytest.raises(pstore.RevConflict):
        pstore.save_goals(plan["id"], plan["rev"], [_goal("R2.1")])


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------
def test_state_machine_and_generation_failure(plan_db):
    plan = _new_plan(plan_db)
    assert pstore.begin_generation(plan["id"], "internal") == "inputs"
    assert pstore.get_plan(plan["id"])["status"] == "generating"
    with pytest.raises(pstore.StatusError, match="已在进行中"):
        pstore.begin_generation(plan["id"], "internal")
    pstore.fail_generation(plan["id"], "internal")
    assert pstore.get_plan(plan["id"])["status"] == "inputs"

    pstore.begin_generation(plan["id"], "internal")
    version = pstore.add_version(plan["id"], part="internal", kind="ai_draft",
                                 ai_doc={"sessions": []}, doc={"sessions": []},
                                 checks=[])
    pstore.finish_generation(plan["id"], "internal", version_id=version["id"])
    plan = pstore.get_plan(plan["id"])
    assert plan["status"] == "review"
    assert plan["current_version_id"] == version["id"]

    with pytest.raises(pstore.StatusError, match="请先批准"):
        pstore.begin_generation(plan["id"], "parent")


def test_approve_does_not_need_checks_cleared(plan_db):
    plan = _approved_plan(plan_db)
    assert plan["status"] == "approved"
    assert pstore.current_version(plan["id"])["checks"] == [
        {"level": "review", "text": "有一条待核对"}]


def test_approved_plan_is_read_only_until_reopened(plan_db):
    plan = _approved_plan(plan_db)
    with pytest.raises(pstore.StatusError, match="重新打开"):
        pstore.save_goals(plan["id"], plan["rev"], [_goal("R2.1")])
    with pytest.raises(pstore.StatusError, match="重新打开"):
        pstore.update_header(plan["id"], plan["rev"], credits="4")
    reopened = pstore.reopen(plan["id"], plan_db.alice_id)
    assert reopened["status"] == "review"
    assert reopened["approved_at"] is None
    pstore.save_goals(reopened["id"], reopened["rev"], [_goal("R2.1")])


def test_reopen_after_parent_makes_it_stale(plan_db):
    plan = _approved_plan(plan_db)
    pstore.add_version(plan["id"], part="parent", kind="ai_draft",
                       doc={"sessions": []},
                       source_version_id=plan["current_version_id"])
    pstore.finish_generation(plan["id"], "parent")
    assert pstore.get_plan(plan["id"])["parent_stale"] is False

    pstore.reopen(plan["id"])
    assert pstore.get_plan(plan["id"])["parent_stale"] is True
    pstore.approve(plan["id"], plan_db.alice_id)
    assert pstore.get_plan(plan["id"])["parent_stale"] is True

    plan = pstore.get_plan(plan["id"])
    pstore.add_version(plan["id"], part="parent", kind="ai_draft",
                       doc={"sessions": []},
                       source_version_id=plan["current_version_id"])
    pstore.finish_generation(plan["id"], "parent")
    assert pstore.get_plan(plan["id"])["parent_stale"] is False


def test_parent_confirm_and_edit_falls_back_to_draft(plan_db):
    plan = _approved_plan(plan_db)
    pstore.add_version(plan["id"], part="parent", kind="ai_draft",
                       doc={"sessions": []},
                       source_version_id=plan["current_version_id"])
    pstore.finish_generation(plan["id"], "parent")
    plan = pstore.get_plan(plan["id"])
    assert plan["parent_status"] == "draft"
    pstore.confirm_parent(plan["id"], plan_db.alice_id)
    plan = pstore.get_plan(plan["id"])
    assert plan["parent_status"] == "confirmed"

    pstore.save_parent(plan["id"], plan["rev"], {"sessions": [1, 2, 3]})
    assert pstore.get_plan(plan["id"])["parent_status"] == "draft"


def test_export_needs_confirmation_and_fresh_parent(plan_db):
    plan = _approved_plan(plan_db)
    pstore.add_version(plan["id"], part="parent", kind="ai_draft",
                       doc={"sessions": []},
                       source_version_id=plan["current_version_id"])
    pstore.finish_generation(plan["id"], "parent")
    with pytest.raises(pstore.StatusError, match="先确认"):
        pstore.export_parent(plan["id"], plan_db.alice_id)
    plan = pstore.get_plan(plan["id"])
    pstore.confirm_parent(plan["id"], plan_db.alice_id)
    exported = pstore.export_parent(plan["id"], plan_db.alice_id)
    assert exported["parent_status"] == "exported"
    assert exported["parent_exported_at"]


def test_ai_doc_never_changes_and_edit_version_is_reused(plan_db):
    plan = _new_plan(plan_db)
    ai_doc = {"overview": {"text": "AI 初稿", "src": "ai"}, "sessions": []}
    version = pstore.add_version(plan["id"], part="internal", kind="ai_draft",
                                 ai_doc=ai_doc, doc=ai_doc, checks=[])
    plan = pstore.get_plan(plan["id"])
    first = pstore.save_internal(plan["id"], plan["rev"],
                                 {"overview": {"text": "导师改了一次", "src": "edited"},
                                  "sessions": []})
    saved = pstore.get_version(first["version_id"])
    assert saved["kind"] == "edit"
    assert saved["ai_doc"] == ai_doc
    assert saved["doc"]["overview"]["text"] == "导师改了一次"

    plan = pstore.get_plan(plan["id"])
    second = pstore.save_internal(plan["id"], plan["rev"],
                                  {"overview": {"text": "导师改了两次", "src": "edited"},
                                   "sessions": []})
    assert second["version_id"] == first["version_id"]
    saved = pstore.get_version(second["version_id"])
    assert saved["ai_doc"] == ai_doc
    assert saved["doc"]["overview"]["text"] == "导师改了两次"


# ---------------------------------------------------------------------------
# 固定文字 / 报告状态
# ---------------------------------------------------------------------------
def test_plan_fixed_kb_validates_and_has_block_review():
    data = plan_kb.fixed()
    assert data["parent"]["footer_p1"] == "心有灵析 · PERSONALIZED DEVELOPMENT"
    assert data["parent"]["header_right_p2"] == "GROW THROUGH PRACTICE"
    assert plan_kb.block_review()["name"].startswith("Block Review & Summary")
    assert len(plan_kb.block_review()["parts"]) == 4
    assert plan_kb.platforms() == ["StoryMap", "Echo", "无"]
    assert plan_kb.source_label("world_bank") == "World Bank · 改编"


def test_plan_fixed_kb_rejects_empty_text():
    bad = plan_kb.fixed()
    import copy
    bad = copy.deepcopy(bad)
    bad["parent"]["quote"] = ""
    with pytest.raises(ValueError, match="quote"):
        plan_kb.validate_fixed(bad)


def test_report_status_change_keeps_plan_fresh(plan_db):
    plan = _approved_plan(plan_db)
    report = report_store.get_report_by_id(plan["report_id"])
    report_store.reopen(report["id"])
    plan = pstore.get_plan(plan["id"])
    assert pstore.report_state(plan)["fresh"] is True
    assert not any("会后报告已更新" in item for item in pstore.generate_blockers(plan))


def test_report_edit_marks_plan_stale(plan_db):
    prep, report = _drafted_prep(plan_db)
    plan = _create(plan_db, prep, report)
    assert pstore.report_state(plan)["fresh"] is True
    report_store.save_version(report["id"], report["rev"],
                              doc={"overview": {"text": "导师改了"}})
    plan = pstore.get_plan(plan["id"])
    assert pstore.report_state(plan)["fresh"] is False
    blockers = pstore.generate_blockers(plan)
    assert any("会后报告已更新" in item for item in blockers)
    assert not any("会后报告已更新" in item
                   for item in pstore.generate_blockers(plan, use_old_report=True))
