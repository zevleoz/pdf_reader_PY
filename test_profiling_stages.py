# -*- coding: utf-8 -*-
"""C2：Profiling 阶段规则（纯函数）与事实取数（临时库，不触碰 data/y4_students.db）。"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, insert

import db as _db
import growth_talk_store as gt
import profiling_stages as ps
import questionnaire_store as qs

T0 = datetime(2026, 10, 1, 9, 0, 0)


# ── 临时库与造数辅助（test_profiling_api.py 复用） ───────────────────────
@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/profiling_stages.db")
    _db.Base.metadata.create_all(engine)
    qs.ensure_indexes(bind=engine)
    monkeypatch.setattr(_db, "engine", engine)
    monkeypatch.setattr(qs, "engine", engine)
    yield engine
    engine.dispose()


def mk_student(name="测试甲", school="示例中学", advisor="Mine"):
    return _db.create_student(name, school=school, advisor_name=advisor)


def code_of(sid):
    with _db.Session(_db.engine) as s:
        return s.get(_db.Student, sid).student_code


def mk_booking(sid, status="pending", when=T0):
    bid = _db.add_booking("x", when, student_id=sid)
    with _db.Session(_db.engine) as s:
        s.execute(_db.Booking.__table__.update().where(_db.Booking.id == bid)
                  .values(status=status, created_at=when))
        s.commit()
    return bid


def mk_report(sid, d=date(2026, 10, 2), created=None):
    rid = _db.add_report(sid, d, "x.pdf", "{}")
    if created:
        with _db.Session(_db.engine) as s:
            s.execute(_db.Report.__table__.update().where(_db.Report.id == rid)
                      .values(created_at=created))
            s.commit()
    return rid


def mk_minutes(sid, rid):
    return _db.add_minutes(sid, rid, "t", "m")


def mk_profile(sid, rid, version=1):
    return _db.add_six_am_profile(sid, rid, json.dumps({"dims": {}}), version=version)


def mk_review(pid, rid, dim, verdict="agree"):
    return _db.add_six_am_review(profile_id=pid, report_id=rid, dim=dim, verdict=verdict)


def mk_questionnaire(code="Q1"):
    with _db.Session(_db.engine) as s:
        r = s.execute(insert(qs.Questionnaire).values(code=code, title=code, schema_json="{}"))
        s.commit()
        return r.lastrowid


def mk_assignment(sid, qid, status="sent", submitted_at=None):
    with _db.Session(_db.engine) as s:
        r = s.execute(insert(qs.Assignment).values(
            student_id=sid, questionnaire_id=qid, status=status, submitted_at=submitted_at))
        s.commit()
        return r.lastrowid


def mk_gt_report(sid, status="CONFIRMED", confirmed_at="2026-10-05T10:00:00", version=1):
    with _db.Session(_db.engine) as s:
        s.execute(insert(gt.GtReport).values(
            student_id=sid, run_id=1, version=version, status=status, payload="{}",
            confirmed_at=confirmed_at))
        s.commit()


def mk_copilot(sid, status="ACTIVE", advisor_id=1):
    with _db.Session(_db.engine) as s:
        s.execute(insert(gt.CopilotSession).values(
            student_id=sid, advisor_id=advisor_id, status=status))
        s.commit()


def state_of(progress, key):
    return next(s for s in progress["stages"] if s["key"] == key)["state"]


def required_done_facts():
    return {"has_booking": True, "booking_at": T0, "has_report": True,
            "report_at": T0, "minutes_at": T0, "six_am_profile": True,
            "six_am_profile_at": T0,
            "six_am_reviewed": True, "six_am_reviewed_at": T0}


# ── 1. 规则表（纯函数） ────────────────────────────────────────────────
def test_stage_order_and_labels():
    p = ps.build_progress({})
    assert [(s["key"], s["label"], s["required"]) for s in p["stages"]] == [
        ("booking", "预约", True), ("y4_report", "Y4 报告", True),
        ("interpretation", "解读会", True), ("questionnaires", "补充问卷", False),
        ("first_touch", "First Touch", False), ("six_am", "6AM", True)]
    assert set(p) == {"stages", "next", "done", "label"}


def test_nothing_next_is_booking():
    p = ps.build_progress({})
    assert p["next"] == {"key": "booking", "label": "预约"}
    assert p["done"] is False and p["label"] == "预约"


def test_booked_only_next_is_report():
    p = ps.build_progress({"has_booking": True, "booking_at": T0})
    assert p["next"]["key"] == "y4_report" and p["label"] == "Y4 报告"


def test_report_without_booking_counts_booking_done_and_next_is_interpretation():
    p = ps.build_progress({"has_report": True, "report_at": T0})
    assert state_of(p, "booking") == "done"
    assert p["next"] == {"key": "interpretation", "label": "解读会"}
    assert next(s for s in p["stages"] if s["key"] == "booking")["at"] == T0.isoformat()


def test_booking_time_wins_over_report_time_when_both_exist():
    later = T0 + timedelta(days=3)
    p = ps.build_progress({"has_booking": True, "booking_at": T0,
                           "has_report": True, "report_at": later})
    assert next(s for s in p["stages"] if s["key"] == "booking")["at"] == T0.isoformat()


def test_report_without_booking_through_the_database(world):
    sid = mk_student()
    rid = mk_report(sid, created=T0)
    p = ps.progress_for_student(sid)
    assert state_of(p, "booking") == "done" and p["next"]["key"] == "interpretation"
    mk_minutes(sid, rid)
    assert ps.progress_for_student(sid)["next"]["key"] == "six_am"


def test_cancelled_booking_plus_report_still_starts_profiling(world):
    sid = mk_student()
    mk_booking(sid, status="cancelled")
    mk_report(sid, created=T0)
    assert state_of(ps.progress_for_student(sid), "booking") == "done"


def test_student_with_nothing_through_the_database_next_is_booking(world):
    sid = mk_student()
    p = ps.progress_for_student(sid)
    assert p["next"] == {"key": "booking", "label": "预约"} and state_of(p, "booking") == "todo"


def test_report_next_is_interpretation():
    p = ps.build_progress({"has_booking": True, "has_report": True, "report_at": T0})
    assert p["next"]["key"] == "interpretation"


def test_minutes_no_six_am_next_is_six_am():
    f = required_done_facts()
    for k in ("six_am_profile", "six_am_reviewed"):
        f.pop(k)
    p = ps.build_progress(f)
    assert p["next"] == {"key": "six_am", "label": "6AM"} and p["done"] is False


def test_all_required_done():
    p = ps.build_progress(required_done_facts())
    assert p["done"] is True and p["label"] == "已完成" and p["next"] is None


def test_done_stage_carries_iso_time_and_todo_is_null():
    p = ps.build_progress({"has_booking": True, "booking_at": T0})
    by = {s["key"]: s for s in p["stages"]}
    assert by["booking"]["at"] == T0.isoformat() and by["booking"]["state"] == "done"
    assert by["y4_report"]["at"] is None and by["y4_report"]["state"] == "todo"


def test_no_overdue_in_model():
    p = ps.build_progress({})
    assert "overdue" not in json.dumps(p).lower()


# ── 2. 可选阶段 ───────────────────────────────────────────────────────
def test_questionnaire_unsubmitted_is_todo_and_never_blocks():
    f = required_done_facts()
    f.update(q_assigned=2, q_all_submitted=False)
    p = ps.build_progress(f)
    assert state_of(p, "questionnaires") == "todo"
    assert p["done"] is True and p["next"] is None


def test_questionnaire_not_next_step_while_required_missing():
    p = ps.build_progress({"has_booking": True, "has_report": True, "minutes_at": T0,
                           "q_assigned": 1, "q_all_submitted": False})
    assert p["next"]["key"] == "six_am"


def test_questionnaire_nothing_assigned_not_used_and_submitted_done():
    assert state_of(ps.build_progress({}), "questionnaires") == "not_used"
    p = ps.build_progress({"q_assigned": 2, "q_all_submitted": True, "q_at": T0})
    assert state_of(p, "questionnaires") == "done"


def test_first_touch_states():
    assert state_of(ps.build_progress({}), "first_touch") == "not_used"
    f = required_done_facts()
    f["ft_started"] = True
    p = ps.build_progress(f)
    assert state_of(p, "first_touch") == "todo"
    assert p["done"] is True and p["next"] is None
    f.update(ft_confirmed=True, ft_at="2026-10-05T10:00:00")
    p = ps.build_progress(f)
    assert state_of(p, "first_touch") == "done"
    assert next(s for s in p["stages"] if s["key"] == "first_touch")["at"] == "2026-10-05T10:00:00"


# ── 3. 6AM 规则的两种取值 ──────────────────────────────────────────────
def test_default_is_reviewed_and_profile_alone_is_not_done():
    assert ps.SIX_AM_DONE == "reviewed"
    f = required_done_facts()
    f.pop("six_am_reviewed")  # 有档案、没评完
    p = ps.build_progress(f)
    assert p["done"] is False and p["next"]["key"] == "six_am"


def test_rule_table_profile_mode_accepts_profile_alone(monkeypatch):
    monkeypatch.setattr(ps, "SIX_AM_DONE", "profile")
    f = required_done_facts()
    f.pop("six_am_reviewed")
    assert ps.build_progress(f)["done"] is True


def test_all_required_done_through_the_database_by_default(world):
    sid = mk_student()
    mk_booking(sid)
    rid = mk_report(sid)
    mk_minutes(sid, rid)
    pid = mk_profile(sid, rid)
    assert ps.progress_for_student(sid)["next"]["key"] == "six_am"
    for d in ps.six_am_dimension_ids():
        mk_review(pid, rid, d)
    p = ps.progress_for_student(sid)
    assert p["done"] is True and p["label"] == "已完成" and p["next"] is None


def test_six_am_rule_both_modes_through_the_database(world, monkeypatch):
    sid = mk_student()
    mk_booking(sid)
    rid = mk_report(sid)
    mk_minutes(sid, rid)
    mk_profile(sid, rid)  # 有档案，没有任何评议

    monkeypatch.setattr(ps, "SIX_AM_DONE", "profile")
    assert ps.progress_for_student(sid)["done"] is True

    monkeypatch.setattr(ps, "SIX_AM_DONE", "reviewed")
    p = ps.progress_for_student(sid)
    assert p["done"] is False and p["next"]["key"] == "six_am"


def test_six_am_reviewed_needs_every_dimension_with_a_verdict(world, monkeypatch):
    monkeypatch.setattr(ps, "SIX_AM_DONE", "reviewed")
    dims = ps.six_am_dimension_ids()
    assert len(dims) >= 5 and dims[0] == "A1"
    sid = mk_student()
    mk_booking(sid)
    rid = mk_report(sid)
    mk_minutes(sid, rid)
    pid = mk_profile(sid, rid)
    for d in dims[:-1]:
        mk_review(pid, rid, d)
    mk_review(pid, rid, dims[-1], verdict="")  # 空 verdict 不算
    assert ps.progress_for_student(sid)["done"] is False
    mk_review(pid, rid, dims[-1], verdict="agree")  # 同维度最新一条为准
    p = ps.progress_for_student(sid)
    assert p["done"] is True
    assert next(s for s in p["stages"] if s["key"] == "six_am")["at"] is not None


def test_six_am_reviewed_only_counts_latest_profile_version(world, monkeypatch):
    monkeypatch.setattr(ps, "SIX_AM_DONE", "reviewed")
    sid = mk_student()
    mk_booking(sid)
    rid = mk_report(sid)
    mk_minutes(sid, rid)
    old = mk_profile(sid, rid, version=1)
    for d in ps.six_am_dimension_ids():
        mk_review(old, rid, d)
    mk_profile(sid, rid, version=2)  # 新版本没有评议
    assert ps.progress_for_student(sid)["done"] is False


def _reviewed_world(verdict_by_dim):
    sid = mk_student()
    mk_booking(sid)
    rid = mk_report(sid)
    mk_minutes(sid, rid)
    pid = mk_profile(sid, rid)
    for d, v in verdict_by_dim.items():
        mk_review(pid, rid, d, verdict=v)
    return sid, rid, pid


def test_reviewed_rule_agree_and_adjust_count_evidence_does_not(world, monkeypatch):
    monkeypatch.setattr(ps, "SIX_AM_DONE", "reviewed")
    dims = ps.six_am_dimension_ids()
    verdicts = {d: ("adjust" if i % 2 else "agree") for i, d in enumerate(dims)}
    sid, rid, pid = _reviewed_world(verdicts)
    assert ps.progress_for_student(sid)["done"] is True
    # 最新一条变成 evidence：该维度不再算已评议
    mk_review(pid, rid, dims[0], verdict="evidence")
    p = ps.progress_for_student(sid)
    assert p["done"] is False and p["next"]["key"] == "six_am"
    # 再追加 agree：恢复
    mk_review(pid, rid, dims[0], verdict="agree")
    assert ps.progress_for_student(sid)["done"] is True


def test_reviewed_rule_all_evidence_is_not_reviewed(world, monkeypatch):
    monkeypatch.setattr(ps, "SIX_AM_DONE", "reviewed")
    sid, _rid, _pid = _reviewed_world({d: "evidence" for d in ps.six_am_dimension_ids()})
    assert ps.progress_for_student(sid)["done"] is False


# ── 4. 取消的预约 ─────────────────────────────────────────────────────
def test_cancelled_booking_does_not_count(world):
    sid = mk_student()
    mk_booking(sid, status="cancelled")
    p = ps.progress_for_student(sid)
    assert state_of(p, "booking") == "todo" and p["next"]["key"] == "booking"
    mk_booking(sid, status="completed")
    assert state_of(ps.progress_for_student(sid), "booking") == "done"


# ── 5. 事实取数（各 "done" 事实的来源） ─────────────────────────────────
def test_minutes_must_belong_to_the_latest_report(world):
    sid = mk_student()
    mk_booking(sid)
    old = mk_report(sid, date(2026, 9, 1))
    mk_minutes(sid, old)
    new = mk_report(sid, date(2026, 10, 1))
    p = ps.progress_for_student(sid)
    assert p["next"]["key"] == "interpretation"
    mk_minutes(sid, new)
    assert ps.progress_for_student(sid)["next"]["key"] == "six_am"


def test_questionnaire_facts_from_assignments(world):
    sid = mk_student()
    q1, q2 = mk_questionnaire("Q1"), mk_questionnaire("Q2")
    assert state_of(ps.progress_for_student(sid), "questionnaires") == "not_used"
    mk_assignment(sid, q1, "rejected")  # 被驳回 = 没分配
    assert state_of(ps.progress_for_student(sid), "questionnaires") == "not_used"
    mk_assignment(sid, q1, "submitted", T0)
    mk_assignment(sid, q2, "sent")
    assert state_of(ps.progress_for_student(sid), "questionnaires") == "todo"
    mk_assignment(sid, q2, "submitted", T0 + timedelta(days=1))
    p = ps.progress_for_student(sid)
    assert state_of(p, "questionnaires") == "done"
    assert next(s for s in p["stages"] if s["key"] == "questionnaires")["at"] == \
        (T0 + timedelta(days=1)).isoformat()


def test_first_touch_facts_from_gt_tables(world):
    sid = mk_student()
    assert state_of(ps.progress_for_student(sid), "first_touch") == "not_used"
    mk_copilot(sid, "ARCHIVED")
    assert state_of(ps.progress_for_student(sid), "first_touch") == "not_used"
    mk_copilot(sid, "ACTIVE", advisor_id=2)
    assert state_of(ps.progress_for_student(sid), "first_touch") == "todo"
    mk_gt_report(sid, "DRAFT")
    assert state_of(ps.progress_for_student(sid), "first_touch") == "todo"
    mk_gt_report(sid, "CONFIRMED", version=2)
    assert state_of(ps.progress_for_student(sid), "first_touch") == "done"


def test_batch_matches_single(world):
    a, b = mk_student("甲"), mk_student("乙")
    mk_booking(a)
    mk_report(b)
    batch = ps.progress_for_students([a, b])
    assert batch[a] == ps.progress_for_student(a)
    assert batch[b] == ps.progress_for_student(b)
    assert batch[a]["next"]["key"] == "y4_report"
    # D6（2026-11-04）：有报告即已开始，没有预约也不再是下一步；没有纪要则下一步是解读会
    assert batch[b]["next"]["key"] == "interpretation"
