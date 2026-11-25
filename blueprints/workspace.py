"""工作台蓝图（spec 5.2 / Agent B 5.5；16 包 §B 合并问卷任务台账）。

工作台 = 单一日程页（16 包 §B1），自上而下：

- 页头：标题 + 动态摘要 + 主操作（新建任务 / 新建报告）
- 生成作业卡：进行中或 24h 内有结果时出现（/api/progress 轮询）
- 问卷任务台账：五个状态 tab（数据走 GET /api/questionnaires/assignments，前端取数）
- 次要区块「最近活跃学生」（带阶段 chip）

viewer 角色只读开放：页面根节点带 data-role，JS 隐藏所有写操作入口。
问卷任务对 assignments 表做容错查询——表不存在时台账显示「模块未启用」。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, render_template, session

from app_utils import (DATA_DIR, JOB_FILE, _advisor_scope, admin_required, login_required,
                       role_required, visible_student_filter)
from pipeline import STAGES, compute_stages

bp = Blueprint("workspace", __name__)

# 生成作业视为“进行中”的时长上限（与 blueprints/reports.py 的 _job_running 一致）
_JOB_STALE_SECONDS = 1200
# 已完工作业在区块中保留的时长
_JOB_RECENT_SECONDS = 24 * 3600


@bp.route("/workspace")
@role_required("admin", "advisor", "viewer")
def workspace_page():
    return render_template(
        "workspace.html",
        nav_active="workspace",
        ws={
            "enabled": _questionnaire_enabled(),
            "job": _generation_job() if session.get("role") != "viewer" else None,
            "recent": _recent_students(),
            "stageMeta": STAGES,
        },
    )


def _advisor():
    """advisor 角色返回其 advisor_name 用于归属过滤；其他角色返回 None。"""
    return _advisor_scope()


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _seconds_ago(value):
    dt = _parse_iso(value)
    if not dt:
        return None
    return (datetime.utcnow() - dt).total_seconds()


# ---------------------------------------------------------------------------
# 问卷模块可用性探测（台账数据由前端直接调 /api/questionnaires/assignments）
# ---------------------------------------------------------------------------
def _questionnaire_enabled() -> bool:
    try:
        import questionnaire_store as _qs
        _qs.assignment_status_counts(advisor_name=_advisor())
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 队列 3：进行中的生成作业（data/_job.json + data/_progress.json）
# ---------------------------------------------------------------------------
def _read_json(path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {}


def _generation_job():
    """组装生成作业卡片数据；无进行中/近期作业时返回 None（逻辑对齐 /api/progress）。"""
    job = _read_json(JOB_FILE)
    if not job:
        return None
    status = job.get("status") or "idle"
    updated = job.get("updated_at") or 0
    age = (time.time() - updated) if updated else None

    if status == "running" and (age is None or age < _JOB_STALE_SECONDS):
        prog_file = DATA_DIR / "_progress.json"
        prog = {}
        try:
            if prog_file.exists() and prog_file.stat().st_mtime >= (job.get("started_at") or 0):
                prog = json.loads(prog_file.read_text(encoding="utf-8"))
        except Exception:
            prog = {}
        job_percent = job.get("percent") or 0
        prog_percent = prog.get("percent") or 0
        percent = max(job_percent, prog_percent) if prog_percent else job_percent
        message = prog.get("message") if prog_percent > job_percent else job.get("message")
        return {
            "running": True,
            "status": status,
            "percent": max(0, min(100, int(percent or 0))),
            "message": message or "生成中…",
            "filename": job.get("filename") or "",
            "ago": _ago(age),
        }

    if status in ("done", "error") and age is not None and age < _JOB_RECENT_SECONDS:
        return {
            "running": False,
            "status": status,
            "percent": int(job.get("percent") or 0),
            "message": job.get("message") or ("报告已生成" if status == "done" else "生成失败"),
            "filename": job.get("filename") or "",
            "error": job.get("error") or "",
            "ago": _ago(age),
        }
    return None


# ---------------------------------------------------------------------------
# 次要区块：最近活跃学生（reports 表最近更新；advisor 仅见名下；带阶段 chip）
# ---------------------------------------------------------------------------
def _recent_students(limit: int = 5):
    import db as _db
    from sqlalchemy import select
    advisor = _advisor()
    stmt = select(_db.Report, _db.Student).join(_db.Student)
    if advisor is not None:
        stmt = stmt.where(_db.Student.advisor_name == advisor)
    stmt = stmt.order_by(_db.Report.created_at.desc(), _db.Report.id.desc()).limit(40)

    stages = compute_stages(advisor)
    out, seen = [], set()
    with _db.Session(_db.engine) as sess:
        for report, student in sess.execute(stmt).all():
            if student.id in seen:
                continue
            seen.add(student.id)
            info = stages.get(student.id) or {}
            out.append({
                "student_id": student.id,
                "student_code": student.student_code or "",
                "name": student.name,
                "advisor_name": student.advisor_name or "",
                "report_date": report.report_date.isoformat() if report.report_date else "",
                "ago": _ago(_seconds_ago(report.created_at.isoformat()) if report.created_at else None),
                "stage": info.get("stage") or "ready",
                "stage_days": info.get("days") or 0,
            })
            if len(out) >= limit:
                break
    return out


def _ago(seconds) -> str:
    """把秒数转成“刚刚 / N 分钟前 / N 小时前 / N 天前”。"""
    if seconds is None:
        return ""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{seconds // 60} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    return f"{seconds // 86400} 天前"


# ---------------------------------------------------------------------------
# Profiling 阶段 API（C2：学生档案数据，只读；规则见 profiling_stages.py）
# ---------------------------------------------------------------------------
def _int_arg(name, default, lo, hi=None):
    from flask import request
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    value = max(lo, value)
    return min(hi, value) if hi else value


@bp.route("/api/profiling/students")
@login_required
def api_profiling_students():
    from flask import jsonify, request
    from sqlalchemy import select
    import db as _db
    import profiling_stages as ps

    stage = (request.args.get("stage") or "").strip()
    if stage and stage != "done" and stage not in ps.STAGE_KEYS:
        return jsonify({"ok": False, "error": "未知阶段"}), 400
    sort = "name" if (request.args.get("sort") or "").strip() == "name" else "updated"
    stmt = visible_student_filter(select(
        _db.Student.id, _db.Student.student_code, _db.Student.name,
        _db.Student.school, _db.Student.advisor_name, _db.Student.created_at))
    body = ps.list_students(
        stmt, q=request.args.get("q") or "", stage=stage,
        advisor=(request.args.get("advisor") or "").strip(),
        page=_int_arg("page", 1, 1), per_page=_int_arg("per_page", 50, 1, 200),
        sort=sort)
    return jsonify({"ok": True, **body})


@bp.route("/api/profiling/students", methods=["POST"])
@admin_required
def api_create_profiling_student():
    """B：名单直接建档（不经预约）。顾问只能建在自己名下。"""
    from flask import jsonify, request
    import db as _db

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "姓名不能为空"}), 400
    if len(name) > 100:
        return jsonify({"ok": False, "error": "姓名过长"}), 400
    grade = (data.get("grade") or "").strip()[:50]
    school = (data.get("school") or "").strip()[:200]
    phone = (data.get("phone") or "").strip()[:50]
    advisor = (data.get("advisor_name") or "").strip()[:100]

    scope = _advisor_scope()
    if scope is not None:
        advisor = scope
    if not advisor:
        advisor = (session.get("advisor_name") or "").strip()

    sid = _db.create_student(name, grade=grade, school=school,
                             phone=phone, advisor_name=advisor)
    with _db.Session(_db.engine) as sess:
        code = sess.get(_db.Student, sid).student_code
    return jsonify({"ok": True, "student": {
        "id": sid, "code": code, "name": name, "grade": grade,
        "school": school, "advisor_name": advisor,
    }}), 201


@bp.route("/api/profiling/students/<code>", methods=["DELETE"])
@role_required("admin", "advisor")
def api_delete_profiling_student(code):
    from flask import jsonify
    from sqlalchemy.exc import IntegrityError
    import db as _db

    student = _db.get_student_by_code(code)
    scope = _advisor_scope()
    if not student or (scope is not None and (student.get("advisor_name") or "") != scope):
        return jsonify({"ok": False, "error": "学生不存在或不可访问"}), 404
    try:
        _db.delete_student(student["id"], protect_y4=True)
    except _db.StudentHasY4Records as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    except IntegrityError:
        return jsonify({"ok": False, "error": "此档案仍有关联记录，请核对后重试。"}), 409
    return jsonify({"ok": True})


@bp.route("/api/profiling/students/<code>/progress")
@login_required
def api_profiling_student_progress(code):
    from flask import jsonify
    import db as _db
    import profiling_stages as ps

    st = _db.get_student_by_code(code)
    scope = _advisor_scope()
    if not st or (scope is not None and (st.get("advisor_name") or "") != scope):
        return jsonify({"ok": False, "error": "学生不存在"}), 404
    return jsonify({"ok": True, "progress": ps.progress_for_student(st["id"])})


@bp.route("/api/profiling/students/<code>")
@login_required
def api_profiling_student(code):
    """S4-C5a：学生档案页的主数据（同一接口返回头部、权限与进度；各 tab 另行取数）。"""
    from flask import jsonify
    from sqlalchemy import select
    import db as _db
    import profiling_stages as ps
    from app_utils import can_see_full
    from blueprints.students import _first_touch_context, _questionnaire_flags

    st = _db.get_student_by_code(code)
    scope = _advisor_scope()
    if not st or (scope is not None and (st.get("advisor_name") or "") != scope):
        return jsonify({"ok": False, "error": "学生不存在"}), 404

    full = can_see_full()
    role = session.get("role")
    can_write = role != "viewer"

    with _db.Session(_db.engine) as sess:
        latest = sess.execute(
            select(_db.Report.id, _db.Report.report_date)
            .where(_db.Report.student_id == st["id"])
            .order_by(_db.Report.report_date.desc(), _db.Report.id.desc())
            .limit(1)).first()
    latest_report = None
    six_am = None
    if latest:
        latest_report = {
            "id": latest[0],
            "report_date": latest[1].isoformat() if latest[1] else None,
        }
        prof = _db.get_latest_six_am_profile(latest[0])
        if prof:
            six_am = {"report_id": latest[0], "profile_id": prof["id"],
                      "version": prof["version"]}

    return jsonify({
        "ok": True,
        "student": {
            "id": st["id"], "code": st.get("student_code"), "name": st.get("name"),
            "grade": st.get("grade"), "gender": st.get("gender"),
            "birthday": st.get("birthday"), "school": st.get("school"),
            "advisor_name": st.get("advisor_name"),
            "email": (st.get("email") or "") if full else "",
            "phone": (st.get("phone") or "") if full else "",
        },
        "permissions": {
            "can_write": can_write,
            "is_admin": role == "admin",
            "full": full,
            "can_review": bool(can_write and full),
        },
        "progress": ps.progress_for_student(st["id"]),
        "latest_report": latest_report,
        "six_am": six_am,
        "first_touch": _first_touch_context(st["id"], restricted=not full),
        "questionnaire_flags": _questionnaire_flags(st["id"]) if full else [],
    })


@bp.route("/api/profiling/students/<code>/schedule")
@login_required
def api_profiling_student_schedule(code):
    """档案「预约与分配」：该生预约、来源、经办人与测评师。"""
    from flask import jsonify
    import db as _db
    import questionnaire_store as _qs

    st = _db.get_student_by_code(code)
    scope = _advisor_scope()
    if not st or (scope is not None and (st.get("advisor_name") or "") != scope):
        return jsonify({"ok": False, "error": "学生不存在"}), 404
    acct = _qs.get_student_account(st["id"])
    bookings = _db.get_student_bookings(st["id"])
    can_assign = _wb_can_assign()
    offices = _wb_office_ids() if can_assign else []
    for booking in bookings:
        booking["can_assign"] = can_assign and (not offices or booking["location_id"] in offices)
    return jsonify({
        "ok": True,
        "bookings": bookings,
        "can_assign": can_assign,
        "account": {
            "exists": bool(acct),
            "username": (acct or {}).get("username") or "",
            "is_active": (acct or {}).get("is_active") or 0,
        },
    })


@bp.route("/api/profiling/students/<code>/y4")
@login_required
def api_profiling_student_y4(code):
    """S4-C5b：学生档案页的 Y4 数据（四维健康度、研判四名单计数、有效评价指标）。

    只读规则代码（db.report_dimension_health / ai_client._build_qualification_view /
    y4_questions.evaluate_y4_questions），不调用任何 AI 模型。
    """
    from flask import jsonify
    from sqlalchemy import select
    import db as _db
    import evaluation_rules as _er
    import y4_questions as _y4q
    from ai_client import _build_qualification_view

    st = _db.get_student_by_code(code)
    scope = _advisor_scope()
    if not st or (scope is not None and (st.get("advisor_name") or "") != scope):
        return jsonify({"ok": False, "error": "学生不存在"}), 404

    with _db.Session(_db.engine) as sess:
        latest = sess.execute(
            select(_db.Report.id, _db.Report.report_date)
            .where(_db.Report.student_id == st["id"])
            .order_by(_db.Report.report_date.desc(), _db.Report.id.desc())
            .limit(1)).first()
    if not latest:
        return jsonify({"ok": True, "report": None, "dims": [], "signals": None, "items": []})

    record = _db.get_report_raw(latest[0])
    raw = (record or {}).get("raw") or {}
    all_items = raw.get("schema_124") or []

    health = _db.report_dimension_health(all_items)
    dims = [{"name": d, **health[d]} for d in _db._DIMS]

    schema_items = [it for it in all_items if not _er.is_hidden_raw(it)]
    items, _summary, _done, _opts = _build_qualification_view(schema_items)
    result = _y4q.evaluate_y4_questions(items, raw.get("student", {}) or {})
    lists = result.get("lists") or {}
    signals = {
        "强干预": len(lists.get(_y4q.LIST_STRONG_I) or []),
        "弱干预": len(lists.get(_y4q.LIST_WEAK_I) or []),
        "强潜能": len(lists.get(_y4q.LIST_STRONG_P) or []),
        "弱潜能": len(lists.get(_y4q.LIST_WEAK_P) or []),
    }
    return jsonify({
        "ok": True,
        "report": {"id": latest[0],
                   "report_date": latest[1].isoformat() if latest[1] else None},
        "dims": dims,
        "signals": signals,
        "items": [{"code": it.get("code", ""), "label": it.get("label", ""),
                   "value": it.get("raw_value"), "dimension": it.get("dimension", ""),
                   "eval": it.get("eval_value") or ""} for it in items],
    })


# ---------------------------------------------------------------------------
# S4-C6a：工作台待处理队列（只读；规则复用 profiling_stages，不调用任何 AI）
# ---------------------------------------------------------------------------
_UPCOMING_LIMIT = 5


def _wb_six_am_reviewed(student_ids):
    """{student_id: reviewed|None}：最新报告的最新 6AM 档案里，A1–A5 中最新团队结论为
    agree/adjust 的个数；没有档案则为 None。按块 IN 查询，与学生数无关。"""
    import db as _db
    import profiling_stages as ps
    from sqlalchemy import select

    out = {}
    report_of = {}
    dim_ids = ps.six_am_dimension_ids()
    with _db.Session(_db.engine) as sess:
        for part in ps._chunks(sorted(student_ids)):
            latest = {}
            for sid, rid in sess.execute(
                    select(_db.Report.student_id, _db.Report.id)
                    .where(_db.Report.student_id.in_(part))
                    .order_by(_db.Report.student_id.asc(), _db.Report.report_date.desc(),
                              _db.Report.id.desc())).all():
                latest.setdefault(sid, rid)
            report_of.update(latest)
            owner = {rid: sid for sid, rid in latest.items()}
            if not owner:
                continue
            best = {}
            for pid, rid in sess.execute(
                    select(_db.SixAmProfile.id, _db.SixAmProfile.report_id)
                    .where(_db.SixAmProfile.report_id.in_(list(owner)))
                    .order_by(_db.SixAmProfile.report_id.asc(),
                              _db.SixAmProfile.version.desc(),
                              _db.SixAmProfile.id.desc())).all():
                best.setdefault(rid, pid)
            profile_owner = {pid: owner[rid] for rid, pid in best.items()}
            latest_rev = {}
            if profile_owner:
                for pid, dim, verdict in sess.execute(
                        select(_db.SixAmReview.profile_id, _db.SixAmReview.dim,
                               _db.SixAmReview.verdict)
                        .where(_db.SixAmReview.profile_id.in_(list(profile_owner)))
                        .order_by(_db.SixAmReview.id.desc())).all():
                    latest_rev.setdefault((pid, dim), (verdict or "").strip())
            for pid, sid in profile_owner.items():
                out[sid] = sum(1 for d in dim_ids
                               if latest_rev.get((pid, d)) in ps.REVIEWED_VERDICTS)
    return {sid: out.get(sid) for sid in student_ids}, report_of


def _wb_first_touch_updated(student_ids):
    """{student_id: 未归档 copilot 会话的最晚更新时间 iso | None}。"""
    import db as _db
    import growth_talk_store as _gt
    import profiling_stages as ps
    from sqlalchemy import func, select

    out = {}
    with _db.Session(_db.engine) as sess:
        for part in ps._chunks(sorted(student_ids)):
            for sid, at in sess.execute(
                    select(_gt.CopilotSession.student_id, func.max(_gt.CopilotSession.updated_at))
                    .where(_gt.CopilotSession.student_id.in_(part),
                           _gt.CopilotSession.status != "ARCHIVED")
                    .group_by(_gt.CopilotSession.student_id)).all():
                out[sid] = at.isoformat() if at else None
    return out


def _wb_now():
    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)


def _primary_admin_user_id():
    """主管理员账号标识（显式配置，与办公室默认测评师配置相互独立）。

    读取 ``WORKBENCH_PRIMARY_ADMIN_USER_ID``；用作工作台首次进入的默认范围判断，
    不使用显示名、用户名或角色推断。
    """
    raw = (os.environ.get("WORKBENCH_PRIMARY_ADMIN_USER_ID") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _is_primary_admin():
    uid = session.get("user_id")
    primary = _primary_admin_user_id()
    try:
        return bool(primary and uid and int(uid) == primary)
    except (TypeError, ValueError):
        return False


def _workbench_mode():
    """工作台范围：``mine``（账号绑定的顾问名下）或 ``all``（账号可访问范围）。

    显式点选的 mode 优先于默认值。默认值：主管理员账号（显式配置的稳定用户 ID）
    即使绑定了顾问姓名也进入 ``all``；其他绑定顾问的账号进入 ``mine``；未绑定顾问
    的账号进入 ``all``。仅有名下学生权限的账号请求 all 也不会扩大范围。
    """
    from flask import request

    bound = (session.get("advisor_name") or "").strip()
    can_all = _advisor_scope() is None
    requested = (request.args.get("mode") or "").strip()
    if requested == "all" and can_all:
        mode = "all"
    elif requested == "mine" and bound:
        mode = "mine"
    elif bound and not (can_all and _is_primary_admin()):
        mode = "mine"
    else:
        mode = "all"
    return mode, bound, can_all


def _wb_upcoming(mode, bound, scope):
    """接下来的预约：已关联学生以学生归属为准；未关联的只在全范围出现。"""
    import db as _db
    from sqlalchemy import select

    stmt = (select(_db.Booking, _db.Student.student_code)
            .outerjoin(_db.Student, _db.Booking.student_id == _db.Student.id)
            .where(_db.Booking.status == "pending",
                   _db.Booking.appointment_time >= _wb_now())
            .order_by(_db.Booking.appointment_time.asc(), _db.Booking.id.asc())
            .limit(_UPCOMING_LIMIT))
    if mode == "mine":
        stmt = stmt.where(_db.Booking.student_id.isnot(None),
                          _db.Student.advisor_name == bound)
    elif scope is not None:
        stmt = stmt.where(_db.Booking.student_id.isnot(None),
                          _db.Student.advisor_name == scope)
    can_assign = _wb_can_assign()
    offices = _wb_office_ids() if can_assign else []
    with _db.Session(_db.engine) as sess:
        return [{"booking_id": b.id, "student_name": b.student_name,
                 "student_code": code or None,
                 "appointment_time": b.appointment_time.isoformat(),
                 "advisor_name": b.advisor_name or "", "source": b.source or "",
                 "can_assign": can_assign and (not offices or b.location_id in offices)}
                for b, code in sess.execute(stmt).all()]


_WB_ASSIGN_LIMIT = 20


def _wb_can_assign():
    return session.get("role") == "admin"


def _wb_office_ids():
    import db as _db

    return _db.list_user_office_ids(session["user_id"])

def _wb_pending_assignments(mode, bound, scope):
    """待分配测评师：有效、待服务且尚未分配的预约，按预约时间从近到远。

    已关联学生的预约按学生是否落在当前范围判断；无学生档案的预约不进入此组
    （没有可直达的档案页）。办公室权限消费账号被授权的办公室。
    """
    import db as _db
    from sqlalchemy import select

    if not _wb_can_assign():
        return []
    stmt = (select(_db.Booking, _db.Student.student_code, _db.Location.name)
            .join(_db.Student, _db.Booking.student_id == _db.Student.id)
            .outerjoin(_db.Location, _db.Booking.location_id == _db.Location.id)
            .where(_db.Booking.status == "pending",
                   _db.Booking.appointment_time >= _wb_now(),
                   _db.Booking.assessor_id.is_(None))
            .order_by(_db.Booking.appointment_time.asc(), _db.Booking.id.asc())
            .limit(_WB_ASSIGN_LIMIT))
    if mode == "mine":
        stmt = stmt.where(_db.Student.advisor_name == bound)
    elif scope is not None:
        stmt = stmt.where(_db.Student.advisor_name == scope)
    office_ids = _wb_office_ids()
    if office_ids:
        stmt = stmt.where(_db.Booking.location_id.in_(office_ids))
    with _db.Session(_db.engine) as sess:
        return [{"booking_id": b.id, "student_code": code or None,
                 "student_name": b.student_name,
                 "office_name": office_name or "",
                 "appointment_time": b.appointment_time.isoformat()}
                for b, code, office_name in sess.execute(stmt).all()]


@bp.route("/api/profiling/workbench")
@login_required
def api_profiling_workbench():
    """工作台数据（我的/全部范围、阶段计数、待处理队列、接下来的预约、待分配测评师）。"""
    from flask import jsonify
    from sqlalchemy import select
    import db as _db
    import profiling_stages as ps
    import questionnaire_store as _qs
    from app_utils import can_see_full

    scope = _advisor_scope()
    full = can_see_full()
    can_write = session.get("role") != "viewer"
    mode, bound, can_all = _workbench_mode()

    stmt = visible_student_filter(select(
        _db.Student.id, _db.Student.student_code, _db.Student.name, _db.Student.created_at))
    if mode == "mine":
        stmt = stmt.where(_db.Student.advisor_name == bound)
    with _db.Session(_db.engine) as sess:
        rows = sess.execute(stmt).all()
    students = {r.id: {"id": r.id, "code": r.student_code or "", "name": r.name or "",
                       "created_at": r.created_at} for r in rows}
    q_scope = bound if mode == "mine" else scope
    facts = ps.load_facts(students)
    prog = {sid: ps.build_progress(f) for sid, f in facts.items()}

    counts = {k: 0 for k in ("booking", "y4_report", "interpretation", "six_am", "done")}
    for p in prog.values():
        counts[ps._stage_bucket(p)] += 1

    def who(sid):
        s = students[sid]
        return {"id": s["id"], "code": s["code"], "name": s["name"]}

    def newest_first(sids):
        def key(sid):
            at = ps._parse_dt(ps.updated_at_of(prog[sid], students[sid]["created_at"]))
            return (at or datetime.min, sid)
        return sorted(sids, key=key, reverse=True)

    queue = []

    # flag：只给完整权限账号
    if full:
        for f in _qs.list_open_flags(advisor_name=q_scope):
            if f.get("student_id") not in students:
                continue
            queue.append({
                "kind": "flag", "student": who(f["student_id"]),
                "assignment_id": f["assignment_id"],
                "questionnaire_title": f.get("questionnaire_title") or "",
                "flags": [{"label": x.get("label") or "", "answer": x.get("answer") or ""}
                          for x in (f.get("flags") or [])],
                "submitted_at": f.get("submitted_at"),
            })

    # confirm：待确认任务按学生分组，最早创建的组在前（不含 reason）
    groups = {}
    for a in _qs.list_assignments("pending", advisor_name=q_scope, limit=100000):
        if a["student_id"] not in students:
            continue
        g = groups.setdefault(a["student_id"], {"assignments": [], "created_at": None})
        g["assignments"].append({"id": a["id"], "questionnaire_title": a["questionnaire_title"],
                                 "source": a["source"]})
        if a["created_at"] and (g["created_at"] is None or a["created_at"] < g["created_at"]):
            g["created_at"] = a["created_at"]
    for sid, g in sorted(groups.items(), key=lambda kv: (kv[1]["created_at"] or "", kv[0])):
        g["assignments"].sort(key=lambda x: x["id"])
        queue.append({"kind": "confirm", "student": who(sid), **g})

    # six_am：下一步是 6AM
    six_ids = newest_first([sid for sid, p in prog.items()
                            if p["next"] and p["next"]["key"] == "six_am"])
    reviewed, report_of = _wb_six_am_reviewed(six_ids) if six_ids else ({}, {})
    for sid in six_ids:
        queue.append({"kind": "six_am", "student": who(sid),
                      "report_id": report_of.get(sid), "reviewed": reviewed.get(sid)})

    # first_touch：已开始、未确认
    ft_ids = newest_first([sid for sid, f in facts.items()
                           if f.get("ft_started") and not f.get("ft_confirmed")])
    ft_at = _wb_first_touch_updated(ft_ids) if ft_ids else {}
    for sid in ft_ids:
        queue.append({"kind": "first_touch", "student": who(sid),
                      "updated_at": ft_at.get(sid)})

    # booking：下一步是预约
    for sid in newest_first([sid for sid, p in prog.items()
                             if p["next"] and p["next"]["key"] == "booking"]):
        queue.append({"kind": "booking", "student": who(sid)})

    return jsonify({
        "ok": True,
        "permissions": {"can_write": can_write, "full": full},
        "mode": mode,
        "can_switch": bool(can_all and bound),
        "bound_advisor": bound,
        "can_assign": _wb_can_assign(),
        "counts": counts,
        "queue": queue,
        "upcoming": _wb_upcoming(mode, bound, scope),
        "pending_assignments": _wb_pending_assignments(mode, bound, scope),
        "job": _generation_job() if session.get("role") != "viewer" else None,
    })
