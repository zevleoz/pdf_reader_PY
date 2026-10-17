"""学生管线推导测试：待办优先级视图与生命周期进度视图。

覆盖 2026-10-17 三条流程裁决：
- 已 completed 的预约不能再把学生钉在 `booked`；
- 最新问卷 `submitted` 后即便存在报告也返回 `ready`；
- 会议纪要缺失但已有问卷任务时，生命周期跳到问卷阶段而不是卡在 `minutes`；
- Six A.M. 只是报告落库后的后台更新，未落库时显示 pending。
"""
from datetime import datetime
from pathlib import Path

import pytest

import pipeline

NOW = datetime(2026, 10, 17, 12, 0, 0)

# monkeypatch 句柄（autouse fixture 注入），供 plan 里的 _stub_* 简写调用
_MP = None


@pytest.fixture(autouse=True)
def _bind_monkeypatch(monkeypatch):
    global _MP
    _MP = monkeypatch
    yield
    _MP = None


def _facts(**overrides):
    base = {
        "student_created_at": datetime(2026, 1, 1),
        "pending_booking_at": None,
        "completed_booking_at": None,
        "latest_report": None,
        "latest_report_minutes_at": None,
        "pending_assignment_at": None,
        "sent_assignment_at": None,
        "latest_assignment": None,
    }
    base.update(overrides)
    return base


def _report(rid=9, created_at=datetime(2026, 10, 10), report_date=NOW.date()):
    return {"id": rid, "created_at": created_at, "report_date": report_date}


def _assignment(status, created_at=datetime(2026, 10, 12),
                confirmed_at=None, submitted_at=None):
    return {"status": status, "created_at": created_at,
            "confirmed_at": confirmed_at, "submitted_at": submitted_at}


# ─── 打桩助手（Task 2 的聚合测试用） ────────────────────────────

def _stub_student(student_id=1, created_at=datetime(2026, 1, 1)):
    _MP.setattr(pipeline, "_student_created_at", lambda sid: created_at)


def _stub_completed_booking(student_id=1, at=datetime(2026, 10, 15)):
    _MP.setattr(pipeline, "_booking_times_for_student", lambda sid: (None, at))


def _stub_latest_report(student_id=1, report_id=9, created_at=datetime(2026, 10, 10),
                        report_date=NOW.date()):
    _MP.setattr(pipeline, "_latest_report_row",
                lambda sid: {"id": report_id, "created_at": created_at,
                             "report_date": report_date})


def _stub_minutes(report_id=9, rows=None):
    rows = rows or []
    at = rows[0].get("created_at") if rows else None
    _MP.setattr(pipeline, "_latest_minutes_at", lambda rid: at)


def _stub_assignments(student_id=1, rows=None):
    rows = rows or []
    latest = rows[0] if rows else None
    pending_at = min((r.get("created_at") for r in rows
                      if r.get("status") == "pending" and r.get("created_at")), default=None)
    sent_at = min((r.get("confirmed_at") for r in rows
                   if r.get("status") == "sent" and r.get("confirmed_at")), default=None)
    _MP.setattr(pipeline, "_assignment_facts", lambda sid: (latest, pending_at, sent_at))


# ─── Task 1：选择器 ────────────────────────────────────────────

def test_progress_ready_when_current_assignment_submitted():
    facts = _facts(
        latest_report=_report(),
        latest_report_minutes_at=datetime(2026, 10, 11),
        latest_assignment=_assignment("submitted", confirmed_at=datetime(2026, 10, 12),
                                      submitted_at=datetime(2026, 10, 16)),
    )
    assert pipeline._select_progress_stage(facts, NOW)["stage"] == "ready"


def test_progress_skips_optional_minutes_when_questionnaire_exists():
    facts = _facts(
        latest_report=_report(),
        latest_report_minutes_at=None,
        latest_assignment=_assignment("pending"),
    )
    assert pipeline._select_progress_stage(facts, NOW)["stage"] == "pending_approval"


def test_workbench_completed_booking_without_report_is_awaiting_report():
    facts = _facts(completed_booking_at=datetime(2026, 10, 15), latest_report=None)
    assert pipeline._select_workbench_stage(facts, NOW)["stage"] == "awaiting_report"


def test_workbench_submitted_assignment_beats_reported():
    facts = _facts(
        latest_report=_report(),
        latest_assignment=_assignment("submitted", confirmed_at=datetime(2026, 10, 12),
                                      submitted_at=datetime(2026, 10, 16)),
    )
    assert pipeline._select_workbench_stage(facts, NOW)["stage"] == "ready"


@pytest.mark.parametrize("facts_kwargs,expected", [
    # 无预约无报告 → booked
    ({}, "booked"),
    # pending 预约 → booked
    ({"pending_booking_at": datetime(2026, 10, 5)}, "booked"),
    # completed 预约但无报告 → 生命周期 report
    ({"completed_booking_at": datetime(2026, 10, 15)}, "report"),
    # 有报告无纪要无问卷 → 可选节点 minutes
    ({"latest_report": _report()}, "minutes"),
    # 有报告有纪要无问卷 → pending_approval
    ({"latest_report": _report(), "latest_report_minutes_at": datetime(2026, 10, 11)},
     "pending_approval"),
    # 最新问卷 expired 且无更新 submitted → pending_approval
    ({"latest_report": _report(), "latest_report_minutes_at": datetime(2026, 10, 11),
      "latest_assignment": _assignment("expired")}, "pending_approval"),
    ({"latest_report": _report(), "latest_assignment": _assignment("rejected")},
     "pending_approval"),
    # 最新问卷 sent → awaiting_student
    ({"latest_report": _report(),
      "latest_assignment": _assignment("sent", confirmed_at=datetime(2026, 10, 13))},
     "awaiting_student"),
], ids=["empty", "pending-booking", "completed-booking", "no-minutes-no-task",
        "with-minutes-no-task", "expired", "rejected", "sent"])
def test_progress_stage_matrix(facts_kwargs, expected):
    assert pipeline._select_progress_stage(_facts(**facts_kwargs), NOW)["stage"] == expected


def test_progress_since_for_booked_uses_booking_time():
    facts = _facts(pending_booking_at=datetime(2026, 10, 5),
                   student_created_at=datetime(2026, 1, 1))
    assert pipeline._select_progress_stage(facts, NOW)["since"] == datetime(2026, 10, 5)


@pytest.mark.parametrize("facts_kwargs,expected", [
    ({"latest_assignment": _assignment("pending")}, "pending_approval"),
    ({"latest_assignment": _assignment("sent", confirmed_at=datetime(2026, 10, 13))},
     "awaiting_student"),
    ({"latest_assignment": _assignment("submitted", submitted_at=datetime(2026, 10, 16))},
     "ready"),
    ({"pending_booking_at": datetime(2026, 10, 5)}, "booked"),
    ({"completed_booking_at": datetime(2026, 10, 15)}, "awaiting_report"),
    ({"latest_report": _report()}, "reported"),
    ({}, "ready"),
], ids=["pending", "sent", "submitted", "booking", "completed-booking", "report", "none"])
def test_workbench_stage_matrix(facts_kwargs, expected):
    assert pipeline._select_workbench_stage(_facts(**facts_kwargs), NOW)["stage"] == expected


def test_stages_metadata_contains_lifecycle_and_workbench_keys():
    assert pipeline.PROGRESS_STAGE_KEYS == [
        "booked", "report", "minutes", "pending_approval", "awaiting_student", "ready"]
    assert "awaiting_report" in pipeline.STAGE_KEYS
    assert pipeline.progress_stage_meta("minutes").get("optional") is True
    assert pipeline.progress_stage_meta("not-a-stage")["key"] == "ready"


# ─── Task 2：聚合取数 ──────────────────────────────────────────

def test_compute_progress_includes_six_am_pending_status():
    _stub_student(student_id=1)
    _stub_completed_booking(student_id=1)
    _stub_latest_report(student_id=1, report_id=9)
    _stub_minutes(report_id=9, rows=[])
    _stub_assignments(student_id=1, rows=[])
    _MP.setattr(pipeline._db, "get_latest_six_am_profile", lambda report_id: None)
    result = pipeline.compute_progress(1)
    assert result["six_am"]["status"] == "pending"
    assert result["stage"] == "minutes"


def test_compute_progress_reports_six_am_version_when_profile_exists():
    _stub_student(student_id=1)
    _stub_completed_booking(student_id=1)
    _stub_latest_report(student_id=1, report_id=9)
    _stub_minutes(report_id=9, rows=[{"created_at": datetime(2026, 10, 11)}])
    _stub_assignments(student_id=1, rows=[])
    _MP.setattr(pipeline._db, "get_latest_six_am_profile",
                lambda report_id: {"version": 3, "created_at": "2026-10-12T08:00:00"})
    result = pipeline.compute_progress(1)
    assert result["six_am"]["status"] == "ready"
    assert result["six_am"]["version"] == 3
    assert result["stage"] == "pending_approval"


def test_compute_progress_six_am_is_none_without_report():
    _stub_student(student_id=1)
    _stub_completed_booking(student_id=1, at=None)
    _MP.setattr(pipeline, "_latest_report_row", lambda sid: None)
    _stub_assignments(student_id=1, rows=[])
    _stub_minutes(report_id=9)
    result = pipeline.compute_progress(1)
    assert result["six_am"] is None
    assert result["stage"] == "booked"


# ─── Task 5：列表阶段栏兼容 awaiting_report ────────────────────

def test_students_template_supports_awaiting_report_badge():
    text = Path("templates/students.html").read_text(encoding="utf-8")
    assert "awaiting_report" in text
    # 阶段名由服务端注入的 stage_meta 渲染，标签源头在 pipeline.STAGES
    assert pipeline.stage_meta("awaiting_report")["label"] == "待生成报告"
