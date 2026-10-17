"""学生管线阶段推导（Agent J：10-student-pipeline-view.md §3）。

纯查询层推导，**零 schema 变更**：一次聚合查询取各表所需聚合值后在内存推导。

本模块同时服务两套语义（2026-10-17 流程裁决：双视图）：

- ``compute_stages()`` —— **待办优先级视图**（``/students`` 阶段栏、``/workspace``
  最近活跃学生）：一个学生同一时刻只属于一个「最靠前的未完成动作」，
  顺序为 ``pending_approval > awaiting_student > awaiting_report > booked >
  reported > ready``。
- ``compute_progress()`` —— **生命周期进度视图**（学生 360° 顶部 stepper）：
  一个学生沿 ``booked → report → minutes → pending_approval → awaiting_student
  → ready`` 单向推进；``minutes`` 是可选节点，Six A.M. 不在 stepper 占位。

停留时长（``since``）取该阶段起始动作的时间；``days`` 为距今整数天。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select

import db as _db
import questionnaire_store as _qs

# 待办优先级视图的阶段顺序与展示元数据（``/students`` / ``/workspace`` 共用；
# key 即 URL ?stage= 取值）。取「最靠前的未完成动作」，命中即归。
STAGES = [
    {"key": "pending_approval", "label": "问卷待确认", "badge": "badge-warn",
     "color": "var(--warn)"},
    {"key": "awaiting_student", "label": "等待学生作答", "badge": "badge-brand",
     "color": "var(--brand)"},
    {"key": "awaiting_report", "label": "待生成报告", "badge": "badge-brand",
     "color": "var(--brand)"},
    {"key": "booked", "label": "预约待测评", "badge": "badge-neutral",
     "color": "var(--faint)"},
    {"key": "reported", "label": "报告已生成", "badge": "badge-ok",
     "color": "var(--ok)"},
    {"key": "ready", "label": "已就绪", "badge": "badge-neutral",
     "color": "var(--faint)"},
]
STAGE_KEYS = [s["key"] for s in STAGES]

# 生命周期进度视图的阶段顺序（学生 360° 顶部 stepper 专用）。
# ``minutes`` 为可选进度节点：没有纪要时不阻塞问卷；Six A.M. 不在其中占位。
PROGRESS_STAGES = [
    {"key": "booked", "label": "预约待测评", "badge": "badge-neutral",
     "color": "var(--faint)"},
    {"key": "report", "label": "生成报告", "badge": "badge-brand",
     "color": "var(--brand)"},
    {"key": "minutes", "label": "会议纪要", "badge": "badge-neutral",
     "color": "var(--faint)", "optional": True},
    {"key": "pending_approval", "label": "问卷待确认", "badge": "badge-warn",
     "color": "var(--warn)"},
    {"key": "awaiting_student", "label": "等待学生作答", "badge": "badge-brand",
     "color": "var(--brand)"},
    {"key": "ready", "label": "已就绪", "badge": "badge-ok",
     "color": "var(--ok)"},
]
PROGRESS_STAGE_KEYS = [s["key"] for s in PROGRESS_STAGES]

# 「预约待测评」只看最近 30 天内的 booking（启发式）：
# 太久以前的旧预约不代表当前动作，避免把一年前的预约算成「待测评」。
_BOOKING_LOOKBACK_DAYS = 30


def _iso(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _parse_dt(value):
    """ISO 字符串 → datetime（已是 datetime/date 时原样返回；无效值返回 None）。"""
    if value is None or isinstance(value, (datetime,)):
        return value
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return datetime(value.year, value.month, value.day)
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _days_since(since, now: datetime) -> int:
    """距今天数（向下取整，负数按 0）。"""
    if since is None:
        return 0
    base = since.date() if isinstance(since, datetime) else since
    return max(0, (now.date() - base).days)


def _stage_result(stage: str, since, now: datetime) -> dict:
    days = _days_since(since, now)
    return {
        "stage": stage,
        "since": _iso(since),
        "days": days,
        "since_label": f"已 {days} 天" if days else "今天",
    }


# ---------------------------------------------------------------------------
# 选择器：facts → 阶段（纯函数，便于单测）
# ---------------------------------------------------------------------------

def _select_progress_stage(facts: dict, now: datetime) -> dict:
    """生命周期进度：学生沿固定顺序推进，返回 ``{stage, since}``。"""
    report = facts.get("latest_report")
    latest_assignment = facts.get("latest_assignment")
    completed_at = facts.get("completed_booking_at")

    # 1. 没有任何已完成预约 / 报告 → 仍在预约待测评
    if not completed_at and not report:
        return {"stage": "booked",
                "since": facts.get("pending_booking_at") or facts.get("student_created_at")}
    # 2. 已完成预约但没有报告 → 待生成报告
    if completed_at and not report:
        return {"stage": "report", "since": completed_at}
    # 3. 有报告、无纪要、也没有任何问卷任务 → 可选节点「会议纪要」
    if not latest_assignment and not facts.get("latest_report_minutes_at"):
        return {"stage": "minutes", "since": (report or {}).get("created_at")}
    # 4. 已有问卷任务：按最新问卷状态判定
    if latest_assignment:
        status = latest_assignment.get("status")
        if status == "sent":
            return {"stage": "awaiting_student",
                    "since": (facts.get("sent_assignment_at")
                              or latest_assignment.get("confirmed_at")
                              or latest_assignment.get("created_at"))}
        if status == "submitted":
            return {"stage": "ready",
                    "since": (latest_assignment.get("submitted_at")
                              or latest_assignment.get("created_at"))}
        if status == "pending":
            return {"stage": "pending_approval",
                    "since": (facts.get("pending_assignment_at")
                              or latest_assignment.get("created_at"))}
        # expired / rejected：历史任务不阻塞，但没有更新的 submitted 时仍回到问卷处理
        return {"stage": "pending_approval", "since": latest_assignment.get("created_at")}
    # 5. 有报告、已有纪要、没有问卷任务 → 进入问卷待确认
    return {"stage": "pending_approval", "since": (report or {}).get("created_at")}


def _select_workbench_stage(facts: dict, now: datetime) -> dict:
    """待办优先级：取「现在最该处理」的动作，返回 ``{stage, since}``。"""
    latest_assignment = facts.get("latest_assignment")
    if latest_assignment:
        status = latest_assignment.get("status")
        if status == "pending":
            return {"stage": "pending_approval",
                    "since": (facts.get("pending_assignment_at")
                              or latest_assignment.get("created_at"))}
        if status == "sent":
            return {"stage": "awaiting_student",
                    "since": (facts.get("sent_assignment_at")
                              or latest_assignment.get("confirmed_at")
                              or latest_assignment.get("created_at"))}
        if status == "submitted":
            return {"stage": "ready",
                    "since": (latest_assignment.get("submitted_at")
                              or latest_assignment.get("created_at"))}
    if facts.get("pending_booking_at"):
        return {"stage": "booked", "since": facts["pending_booking_at"]}
    if facts.get("completed_booking_at") and not facts.get("latest_report"):
        return {"stage": "awaiting_report", "since": facts["completed_booking_at"]}
    report = facts.get("latest_report")
    if report:
        return {"stage": "reported",
                "since": report.get("report_date") or report.get("created_at")}
    return {"stage": "ready", "since": facts.get("student_created_at")}


# ---------------------------------------------------------------------------
# 单学生事实取数（compute_progress 用；小函数便于单测打桩）
# ---------------------------------------------------------------------------

def _student_created_at(student_id: int):
    with _db.Session(_db.engine) as sess:
        row = sess.execute(select(_db.Student.created_at)
                           .where(_db.Student.id == int(student_id))).first()
    return row[0] if row else None


def _booking_times_for_student(student_id: int):
    """最近一次非 cancelled 的 pending / completed 预约时间 ``(pending_at, completed_at)``。"""
    with _db.Session(_db.engine) as sess:
        rows = sess.execute(
            select(_db.Booking.status, _db.Booking.created_at)
            .where(_db.Booking.student_id == int(student_id),
                   _db.Booking.status != "cancelled")
            .order_by(_db.Booking.created_at.desc(), _db.Booking.id.desc())).all()
    pending_at = completed_at = None
    for status, created in rows:
        if status == "pending" and pending_at is None:
            pending_at = created
        elif status == "completed" and completed_at is None:
            completed_at = created
        if pending_at and completed_at:
            break
    return pending_at, completed_at


def _latest_report_row(student_id: int):
    with _db.Session(_db.engine) as sess:
        r = sess.execute(select(_db.Report).where(_db.Report.student_id == int(student_id))
                         .order_by(_db.Report.created_at.desc(), _db.Report.id.desc())
                         .limit(1)).scalars().first()
    if not r:
        return None
    return {"id": r.id, "created_at": r.created_at, "report_date": r.report_date}


def _latest_minutes_at(report_id: int):
    """该报告关联的最新纪要时间（无纪要返回 None）。"""
    with _db.Session(_db.engine) as sess:
        return sess.execute(select(func.max(_db.MeetingMinutes.created_at))
                            .where(_db.MeetingMinutes.report_id == int(report_id))).scalar()


def _assignment_facts(student_id: int):
    """``(latest_assignment, pending_assignment_at, sent_assignment_at)``。

    复用 ``_qs.list_assignments_for_student``（内含惰性过期刷新）。
    """
    rows = _qs.list_assignments_for_student(int(student_id)) or []
    latest = rows[0] if rows else None
    if latest:
        latest = {
            "status": latest.get("status"),
            "created_at": _parse_dt(latest.get("created_at")),
            "confirmed_at": _parse_dt(latest.get("confirmed_at")),
            "submitted_at": _parse_dt(latest.get("submitted_at")),
        }
    pending_at = min((_parse_dt(r.get("created_at")) for r in rows
                      if r.get("status") == "pending" and r.get("created_at")), default=None)
    sent_at = min((_parse_dt(r.get("confirmed_at")) for r in rows
                   if r.get("status") == "sent" and r.get("confirmed_at")), default=None)
    return latest, pending_at, sent_at


def _build_facts(student_id: int) -> dict:
    report = _latest_report_row(student_id)
    latest_assignment, pending_at, sent_at = _assignment_facts(student_id)
    pending_booking_at, completed_booking_at = _booking_times_for_student(student_id)
    return {
        "student_created_at": _student_created_at(student_id),
        "pending_booking_at": pending_booking_at,
        "completed_booking_at": completed_booking_at,
        "latest_report": report,
        "latest_report_minutes_at": _latest_minutes_at(report["id"]) if report else None,
        "pending_assignment_at": pending_at,
        "sent_assignment_at": sent_at,
        "latest_assignment": latest_assignment,
    }


def _six_am_state(report) -> dict | None:
    """Six A.M. 状态：无报告 None；有报告但档案未落库为 pending；否则 ready。"""
    if not report:
        return None
    profile = None
    try:
        profile = _db.get_latest_six_am_profile(int(report["id"]))
    except Exception:
        profile = None
    if profile:
        return {"status": "ready", "label": "已更新",
                "version": profile.get("version"), "updated_at": profile.get("created_at")}
    return {"status": "pending", "label": "后台更新中", "version": None, "updated_at": None}


def compute_progress(student_id: int) -> dict:
    """该学生的生命周期进度：``{stage, since, days, since_label, six_am}``。

    零 schema；只取单学生事实（学生 / 最新非 cancelled 预约 / 最新报告 /
    该报告纪要时间 / 最新问卷任务 / 最新 6AM 档案）。
    """
    now = datetime.utcnow()
    facts = _build_facts(int(student_id))
    picked = _select_progress_stage(facts, now)
    result = _stage_result(picked["stage"], picked["since"], now)
    result["six_am"] = _six_am_state(facts.get("latest_report"))
    return result


# ---------------------------------------------------------------------------
# 批量推导（待办优先级视图）
# ---------------------------------------------------------------------------

def compute_stages(advisor_name=None) -> dict:
    """推导每个学生的待办优先级阶段：``{student_id: {stage, since, days, since_label}}``。

    ``advisor_name`` 给定时先过滤学生集（advisor 数据隔离），再算阶段。
    一次请求内聚合所有学生（join 各表取聚合值后内存推导），不做 N+1。
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(days=_BOOKING_LOOKBACK_DAYS)

    with _db.Session(_db.engine) as sess:
        stmt = select(_db.Student.id, _db.Student.created_at)
        if advisor_name is not None:
            stmt = stmt.where(_db.Student.advisor_name == advisor_name)
        students = sess.execute(stmt).all()

        pending_min = dict(sess.execute(
            select(_qs.Assignment.student_id, func.min(_qs.Assignment.created_at))
            .where(_qs.Assignment.status == "pending")
            .group_by(_qs.Assignment.student_id)).all())
        sent_min = dict(sess.execute(
            select(_qs.Assignment.student_id, func.min(_qs.Assignment.confirmed_at))
            .where(_qs.Assignment.status == "sent")
            .group_by(_qs.Assignment.student_id)).all())

        # 最新一条问卷任务（按 id 降序取每个学生的第一条）
        latest_assignment: dict = {}
        for sid, status, created, confirmed, submitted in sess.execute(
                select(_qs.Assignment.student_id, _qs.Assignment.status,
                       _qs.Assignment.created_at, _qs.Assignment.confirmed_at,
                       _qs.Assignment.submitted_at)
                .order_by(_qs.Assignment.student_id.asc(), _qs.Assignment.id.desc())).all():
            latest_assignment.setdefault(sid, {
                "status": status, "created_at": created, "confirmed_at": confirmed,
                "submitted_at": submitted})

        def _booking_map(status_value):
            return dict(sess.execute(
                select(_db.Booking.student_id, func.max(_db.Booking.created_at))
                .where(_db.Booking.student_id.isnot(None),
                       _db.Booking.created_at >= cutoff,
                       _db.Booking.status == status_value)
                .group_by(_db.Booking.student_id)).all())

        pending_booking = _booking_map("pending")
        completed_booking = _booking_map("completed")

        latest_report: dict = {}
        for sid, rid, report_date, created in sess.execute(
                select(_db.Report.student_id, _db.Report.id, _db.Report.report_date,
                       _db.Report.created_at)
                .order_by(_db.Report.student_id.asc(), _db.Report.report_date.desc(),
                          _db.Report.id.desc())).all():
            latest_report.setdefault(sid, {"id": rid, "report_date": report_date,
                                           "created_at": created})

    out: dict = {}
    for sid, created_at in students:
        facts = {
            "student_created_at": created_at,
            "pending_booking_at": pending_booking.get(sid),
            "completed_booking_at": completed_booking.get(sid),
            "latest_report": latest_report.get(sid),
            "latest_report_minutes_at": None,
            "pending_assignment_at": pending_min.get(sid),
            "sent_assignment_at": sent_min.get(sid),
            "latest_assignment": latest_assignment.get(sid),
        }
        picked = _select_workbench_stage(facts, now)
        out[sid] = _stage_result(picked["stage"], picked["since"], now)
    return out


def stage_counts(stages: dict) -> dict:
    """把 ``compute_stages`` 结果聚合成各阶段计数（阶段栏与筛选同源）。"""
    counts = {k: 0 for k in STAGE_KEYS}
    for info in (stages or {}).values():
        key = info.get("stage")
        if key in counts:
            counts[key] += 1
    return counts


def stage_meta(key: str) -> dict:
    """按 key 取待办视图阶段元数据；未知 key 归 ready。"""
    for s in STAGES:
        if s["key"] == key:
            return s
    return STAGES[-1]


def progress_stage_meta(key: str) -> dict:
    """按 key 取生命周期阶段元数据；未知 key 归 ready。"""
    for s in PROGRESS_STAGES:
        if s["key"] == key:
            return s
    return PROGRESS_STAGES[-1]
