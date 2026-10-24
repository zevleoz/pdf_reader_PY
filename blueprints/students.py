"""学生蓝图：学生列表 / 360° 档案页 / 报告列表 / 重命名 / 删除。"""
from __future__ import annotations

import json

from flask import Blueprint, abort, jsonify, render_template, request, session
from sqlalchemy import or_, select

import db as _db
from app_utils import (admin_required, login_required, page_login_required,
                       student_scoped, visible_student_filter, _advisor_scope)
from pipeline import PROGRESS_STAGES, compute_progress, progress_stage_meta

bp = Blueprint("students", __name__)


@bp.route("/students")
@page_login_required
def students_page():
    """学生列表页：随页注入阶段栏计数（与列表筛选同源，零 schema）。"""
    from pipeline import STAGES, compute_stages, stage_counts
    stages = compute_stages(_advisor_scope())
    initial = (request.args.get("stage") or "").strip()
    if initial not in [s["key"] for s in STAGES]:
        initial = ""
    return render_template(
        "students.html",
        nav_active="students",
        stage_meta=STAGES,
        stage_counts=stage_counts(stages),
        stage_total=len(stages),
        initial_stage=initial,
    )


@bp.route("/api/students")
@admin_required
def api_students():
    from pipeline import compute_stages
    advisor = _advisor_scope()
    stages = compute_stages(advisor)
    students = _db.get_students(advisor)
    for s in students:
        info = stages.get(s.get("id")) or {}
        s["stage"] = info.get("stage") or "ready"
        s["stage_days"] = info.get("days") or 0
    stage = (request.args.get("stage") or "").strip()
    if stage:
        students = [s for s in students if s["stage"] == stage]
    return jsonify({"ok": True, "students": students})


@bp.route("/api/students/search")
@login_required
def api_student_search():
    """⌘K 命令面板的学生搜索（Agent H 08 5.4）：只读、登录可见、advisor 限名下。

    ``GET /api/students/search?q=<kw>``：按姓名 / 编号 / 学校模糊匹配，返回前 8 条
    精简字段（name / student_code / school / advisor_name）。
    """
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"ok": True, "students": []})
    like = "%" + q + "%"
    stmt = (select(_db.Student)
            .where(or_(_db.Student.name.ilike(like),
                       _db.Student.student_code.ilike(like),
                       _db.Student.school.ilike(like)))
            .order_by(_db.Student.name.asc())
            .limit(8))
    stmt = visible_student_filter(stmt)
    with _db.Session(_db.engine) as sess:
        rows = sess.execute(stmt).all()
    return jsonify({"ok": True, "students": [
        {
            "name": row[0].name,
            "student_code": row[0].student_code or "",
            "school": row[0].school or "",
            "advisor_name": row[0].advisor_name or "",
        }
        for row in rows
    ]})


@bp.route("/api/students/<int:student_id>/reports")
@admin_required
@student_scoped
def api_student_reports(student_id):
    reports = _db.get_student_reports(student_id)
    return jsonify({"ok": True, "reports": reports})
@bp.route("/api/students/<int:student_id>", methods=["PUT"])
@admin_required
@student_scoped
def api_rename_student(student_id):
    """更新学生档案字段（姓名/学校/顾问，均可选，至少提供一项）。"""
    data = request.get_json(silent=True) or {}
    updates = {}
    if "name" in data:
        new_name = (data.get("name") or "").strip()
        if not new_name:
            return jsonify({"ok": False, "error": "姓名不能为空"}), 400
        updates["name"] = new_name
    if "school" in data:
        updates["school"] = (data.get("school") or "").strip()
    if "advisor_name" in data:
        updates["advisor_name"] = (data.get("advisor_name") or "").strip()
    if not updates:
        return jsonify({"ok": False, "error": "未提供任何修改字段"}), 400
    sess = _db.Session(_db.engine)
    try:
        student = sess.get(_db.Student, student_id)
        if not student:
            return jsonify({"ok": False, "error": "学生不存在"}), 404
        for k, v in updates.items():
            setattr(student, k, v)
        sess.commit()
        return jsonify({"ok": True, "student": {
            "id": student.id, "name": student.name,
            "grade": student.grade, "gender": student.gender,
            "school": student.school, "advisor_name": student.advisor_name
        }})
    except Exception as e:
        sess.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        sess.close()


@bp.route("/api/students/<int:student_id>", methods=["DELETE"])
@admin_required
@student_scoped
def api_delete_student(student_id):
    try:
        _db.delete_student(student_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# 学生 360° 档案页（spec 5.3 / Agent D 5.1）
#
# 页面路由 + 六个按 tab 懒加载的只读 JSON 端点。所有端点都复用同一套权限校验
# （admin 全见 / advisor 限名下 / viewer 只读），不只在页面路由拦截。
# ---------------------------------------------------------------------------
def _scoped_student(code):
    """按 code 取学生档案并做 advisor 归属校验。

    返回 ``(student, error)``：``error`` 为 ``(message, http_status)`` 或 None。
    """
    st = _db.get_student_by_code(code)
    if not st:
        return None, ("学生不存在", 404)
    if session.get("role") == "advisor":
        if (st.get("advisor_name") or "") != (session.get("advisor_name") or ""):
            return None, ("无权访问该学生", 403)
    return st, None


def _group_indicators(schema):
    """按 data_points 的分组规则对 schema_124 分组；空组跳过，保持组顺序。"""
    try:
        import data_points as _dp
        rules = list(_dp._GROUP_RULES)
        resolve = _dp._resolve_group
    except Exception:
        rules, resolve = [], (lambda _c: "其他")
    names = [name for _lo, _hi, name in rules]
    buckets: dict = {}
    for it in schema or []:
        code = str(it.get("code") or "")
        buckets.setdefault(resolve(code), []).append({
            "code": code,
            "label": it.get("label") or "",
            "value": it.get("value"),
            "source_pdf": it.get("source_pdf") or "",
        })
    ordered = [n for n in names if buckets.get(n)]
    ordered += [n for n in buckets if n not in ordered]
    return [{"name": n, "items": buckets[n]} for n in ordered]


def _student_progress_context(student_id):
    """360° 页头部：该生**生命周期进度** + 「下一步建议」卡数据。

    零 schema；阶段走 ``pipeline.compute_progress()``（不是待办优先级的
    ``compute_stages()``），建议卡的数据从既有只读查询复用。
    """
    from datetime import datetime

    info = compute_progress(student_id) or {}
    key = info.get("stage") or "ready"
    meta = progress_stage_meta(key)
    suggestion = None

    if key == "report":
        suggestion = {
            "text": "测评后上传 PDF 生成报告",
            "action_kind": "link", "action_label": "去生成报告", "action_href": "/generate",
        }
    elif key == "minutes":
        suggestion = {
            "text": "可补充会议纪要，也可直接处理问卷",
            "action_kind": "link", "action_label": "去写会议纪要",
            "action_href": "/tools/transcript",
        }
    elif key == "pending_approval":
        n = 0
        try:
            import questionnaire_store as _qs
            n = len([a for a in _qs.list_assignments_for_student(student_id)
                     if a.get("status") == "pending"])
        except Exception:
            n = 0
        suggestion = {
            "text": f"有 {n} 份问卷待确认" if n else "有问卷任务待确认",
            "action_kind": "link", "action_label": "去确认", "action_href": "/workspace",
        }
    elif key == "awaiting_student":
        row = None
        expired = False
        try:
            import questionnaire_store as _qs
            rows = [a for a in _qs.list_assignments_for_student(student_id)
                    if a.get("status") == "sent"]
            row = rows[0] if rows else None
            if row:
                exp = _qs.token_expiry_map([row["id"]]).get(row["id"])
                if exp:
                    expired = exp < datetime.utcnow().isoformat()
        except Exception:
            row = None
        suggestion = {
            "text": ("等待学生完成《%s》" % (row.get("questionnaire_title") or "问卷"))
                    if row else "等待学生完成问卷",
            "action_kind": "package", "action_label": "分发信息",
            "assignment_id": (row.get("id") if row else None),
            "expired": bool(expired),
        }
    elif key == "booked":
        latest = None
        try:
            bs = [b for b in _db.get_bookings() if b.get("student_id") == student_id]
            bs.sort(key=lambda b: (b.get("appointment_time") or ""), reverse=True)
            latest = bs[0] if bs else None
        except Exception:
            latest = None
        suggestion = {
            "text": ("已预约 %s，测评后上传 PDF" % (latest.get("appointment_time") or "—"))
                    if latest else "已预约，测评后上传 PDF",
            "action_kind": "link", "action_label": "去生成报告", "action_href": "/generate",
        }
    # ready → 不显示下一步建议卡

    # 「发起问卷任务」只在没有活动问卷（pending/sent）或学生已就绪时，作为次要操作出现，
    # 避免与当前阶段主按钮重复。
    has_active_assignment = False
    try:
        import questionnaire_store as _qs
        has_active_assignment = any(
            a.get("status") in ("pending", "sent")
            for a in _qs.list_assignments_for_student(student_id)
        )
    except Exception:
        has_active_assignment = False

    return {
        "stage": key,
        "label": meta["label"],
        "days": info.get("days") or 0,
        "since_label": info.get("since_label") or "",
        "suggestion": suggestion,
        "six_am": info.get("six_am"),
        "show_create_task": key == "ready" or not has_active_assignment,
    }


@bp.route("/students/<code>")
@page_login_required
def student_360(code):
    st, err = _scoped_student(code)
    if err:
        abort(err[1])
    import growth_talk_store as gt_store
    gt_reports = [
        report for report in gt_store.list_reports(st["id"])
        if report.get("status") == "CONFIRMED"
    ]
    return render_template(
        "student_360.html",
        nav_active="students",
        profile=st,
        can_write=session.get("role") != "viewer",
        is_admin=session.get("role") == "admin",
        stage=_student_progress_context(st["id"]),
        stage_meta=PROGRESS_STAGES,
        gt_reports=gt_reports,
    )


@bp.route("/students/<code>/api/profile")
@page_login_required
def api_student_profile(code):
    st, err = _scoped_student(code)
    if err:
        return jsonify({"ok": False, "error": err[0]}), err[1]
    latest = _db.get_latest_report_raw(st["id"])
    if not latest:
        return jsonify({"ok": True, "report": None, "groups": [], "total": 0})
    schema = (latest.get("data") or {}).get("schema_124") or []
    return jsonify({
        "ok": True,
        "report": {"id": latest["report_id"], "report_date": latest["report_date"]},
        "groups": _group_indicators(schema),
        "total": len(schema),
    })


@bp.route("/students/<code>/api/reports")
@page_login_required
def api_student_reports_by_code(code):
    st, err = _scoped_student(code)
    if err:
        return jsonify({"ok": False, "error": err[0]}), err[1]
    return jsonify({"ok": True, "reports": _db.get_student_reports(st["id"])})


@bp.route("/students/<code>/api/questionnaires")
@page_login_required
def api_student_questionnaires(code):
    st, err = _scoped_student(code)
    if err:
        return jsonify({"ok": False, "error": err[0]}), err[1]
    try:
        import questionnaire_store as _qs
        rows = _qs.list_assignments_for_student(st["id"])
    except Exception:
        # C 包未落地：返回空态而非报错（打桩契约）
        return jsonify({"ok": True, "enabled": False, "assignments": []})
    out = []
    for a in rows:
        answers = None
        if a.get("status") == "submitted":
            try:
                answers = (_qs.get_response(a["id"]) or {}).get("answers")
            except Exception:
                answers = None
        out.append({
            "id": a.get("id"),
            "questionnaire_title": a.get("questionnaire_title") or "",
            "questionnaire_code": a.get("questionnaire_code") or "",
            "status": a.get("status") or "",
            "source": a.get("source") or "",
            "reason": a.get("reason") or "",
            "delivery": a.get("delivery") or "",
            "created_at": a.get("created_at"),
            "submitted_at": a.get("submitted_at"),
            "answers": answers,
        })
    return jsonify({"ok": True, "enabled": True, "assignments": out})


@bp.route("/students/<code>/api/bookings")
@page_login_required
def api_student_bookings(code):
    st, err = _scoped_student(code)
    if err:
        return jsonify({"ok": False, "error": err[0]}), err[1]
    rows = [b for b in _db.get_bookings() if b.get("student_id") == st["id"]]
    return jsonify({"ok": True, "bookings": rows})


@bp.route("/students/<code>/api/minutes")
@page_login_required
def api_student_minutes_by_code(code):
    st, err = _scoped_student(code)
    if err:
        return jsonify({"ok": False, "error": err[0]}), err[1]
    out = []
    for r in _db.get_minutes_by_student(st["id"]):
        full = _db.get_minutes(r["id"]) or {}
        out.append({**r, "minutes_text": full.get("minutes_text") or ""})
    return jsonify({"ok": True, "minutes": out})


@bp.route("/students/<code>/api/six-am")
@page_login_required
def api_student_six_am(code):
    st, err = _scoped_student(code)
    if err:
        return jsonify({"ok": False, "error": err[0]}), err[1]
    out = []
    for r in _db.get_six_am_profiles_by_student(st["id"]):
        try:
            prof = json.loads(r.get("profile_json") or "{}")
        except Exception:
            prof = {}
        out.append({
            "id": r["id"],
            "report_id": r["report_id"],
            "version": r["version"],
            "created_at": r["created_at"],
            "profile": prof,
        })
    return jsonify({"ok": True, "profiles": out})
