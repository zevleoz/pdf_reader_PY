"""M1 会前准备蓝图：页面 + ``/api/m1/*`` 数据接口。

- 页面：``/m1``、``/m1/preps/<id>``、``/m1/preps/<id>/print``
- 数据：学生清单、prep 列表/详情、会议信息、资料上传与修改、草稿自动保存、
  安全提示确认、定稿/重新打开、导出审计

权限（README §3）：Admin 全部；Advisor 名下学生或本人为 Mentor；Viewer 403。
P3 的 ``generate`` / ``jobs`` 两个路由由 P3 追加在本文件末尾的标记块内。
"""
from __future__ import annotations

import os
import re
from functools import wraps
from urllib.parse import quote

from flask import (Blueprint, abort, jsonify, redirect, render_template, request,
                   send_from_directory, session)
from jinja2 import TemplateNotFound
from sqlalchemy.exc import OperationalError

import app_utils
import db as _db
import m1.plan_collaboration as plan_collab
import m1.plan_store as pstore
import m1.report_store as rstore
import m1.roster as roster
import m1.sources as sources
import m1.store as store
from m1 import job_attempts, workflow
from app_utils import BASE_DIR, page_login_required, role_required

bp = Blueprint("m1", __name__)

_WRITE_ROLES = ("admin", "advisor")

# 会前准备是 M1 的第一部分；会后报告由 Stage 2 打开。
M1_PARTS = [
    {"key": "prep", "label": "会前准备", "enabled": True, "href_suffix": "/prep"},
    {"key": "report", "label": "会后报告", "enabled": True, "href_suffix": "/report"},
]


@bp.route("/m1/assets/<path:filename>")
def m1_asset(filename: str):
    """M1 页面静态资源（app.py 用 ``static_folder=None``，静态目录需显式路由）。"""
    return send_from_directory(str(BASE_DIR / "static" / "m1"), filename)


# ---------------------------------------------------------------------------
# 平台权限：未登录交由既有装饰器响应，已登录按账号的 M1 权限拦截
# ---------------------------------------------------------------------------
@bp.before_request
def _m1_access_guard():
    if request.endpoint == "m1.m1_asset":
        return None
    if not session.get("user_id"):
        return None
    # refreshes the session from the account; a disabled account falls through to the decorators
    if not app_utils.is_authenticated():
        return None
    if app_utils.can_use_m1():
        return None
    if request.path.startswith("/api/m1/"):
        return jsonify({"ok": False, "error": "当前账号没有心有灵析权限"}), 403
    abort(403)


# ---------------------------------------------------------------------------
# 通用助手
# ---------------------------------------------------------------------------
def _user() -> dict:
    return app_utils.current_user()


def _m1_nav() -> list:
    """M1 自己的导航：只有 M1 与其他平台，不出现 Profiling 的分组。"""
    from blueprints import auth

    profiling = next(card for card in auth._platform_cards() if card["key"] == "profiling")
    other = [{"key": "platforms", "label": "所有平台", "href": "/platforms", "icon": "file"},
             {"key": "profiling", "label": profiling["title"], "href": profiling["href"],
              "icon": "users"}]
    e4_url = os.environ.get("E4_URL", "").strip()
    if e4_url:
        other.append({"key": "e4", "label": "E4", "href": e4_url, "icon": "file",
                      "blank": True})
    return [
        {"key": "m1", "title": "心有灵析",
         "links": [{"key": "m1", "label": "心有灵析", "href": "/m1", "icon": "target"}]},
        {"key": "other", "title": "其他平台", "links": other},
    ]


def _err(message: str, status: int = 400, **extra):
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return jsonify(payload), status


def _json_body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _page_guard():
    """页面：Viewer 无权限（403 页），其余放行。"""
    if session.get("role") not in _WRITE_ROLES:
        abort(403)


def _can_manage_report() -> bool:
    return store.is_m1_admin(_user()) or app_utils.can_see_full()


def _prep_or_404(prep_id: int):
    prep = store.get_prep(prep_id)
    if not prep:
        abort(404)
    if not store.can_read_prep(_user(), prep_id):
        abort(403)
    return _sanitize_prep(prep)


def _api_read_prep(prep_id: int):
    return _api_prep(prep_id, read=True)


def _api_prep(prep_id: int, *, read=False):
    """API 取 prep：不存在 → 404，越权 → 403。返回 ``(prep, error)``。"""
    prep = store.get_prep(prep_id)
    if not prep:
        return None, _err("会前准备不存在", 404)
    allowed = store.can_read_prep if read else store.can_access_prep
    if not allowed(_user(), prep_id):
        return None, _err("无权访问该会前准备", 403)
    return _sanitize_prep(prep), None


def _nav_for_path(path: str) -> str:
    """导航高亮：列表/学生页/计划页各有自己的入口。"""
    if path.startswith("/m1/reports") or path.endswith("/report"):
        return "reports"
    if path.startswith("/m1/plans"):
        return "plans"
    if path == "/m1/preps" or path.endswith("/prep"):
        return "preps"
    return "students"


def _render_page(template: str, nav_active: str | None = None, **ctx):
    """P4 模板尚未落地时返回最小占位页。"""
    from blueprints import auth

    _page_guard()
    platform_links = [c for c in auth._platform_cards() if c["key"] != "m1"]
    try:
        return render_template(template, nav_active=nav_active or _nav_for_path(request.path),
                               nav_groups=_m1_nav(),
                               platform_links=platform_links,
                               m1_manager=store.is_m1_admin(_user()), **ctx)
    except TemplateNotFound:
        return ("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
                "<title>心有灵析</title></head><body>"
                "<h1>心有灵析</h1><p>页面模板尚未就绪。</p></body></html>"), 200


def _kb_payload():
    """知识库：能力行 + 固定框架文字。P1 未落地时返回空结构。"""
    try:
        from m1.kb import load_kb
        kb = load_kb()
    except Exception:
        return {"version": "", "dims": [], "abilities": []}, {}
    abilities = []
    for item in kb.get("abilities") or []:
        abilities.append({
            "code": item.get("code") or "",
            "name": item.get("name") or "",
            "dim": item.get("dim") or "",
            "gap_note": item.get("gap_note") or "",
            "ask": item.get("ask") or "",
            "indicator_note": item.get("indicator_note") or "",
        })
    return ({"version": kb.get("version") or "", "dims": kb.get("dims") or [],
             "abilities": abilities}, kb.get("fixed") or {})


def _y4_items(prep: dict, auto: dict, version: dict | None):
    """Y4 证据条目（只给档位文本，绝不含 raw）。优先用版本快照。"""
    items = []
    snapshot = (version or {}).get("y4_snapshot") or {}
    if isinstance(snapshot, dict):
        items = snapshot.get("items") or []
    if not items:
        items = (auto.get("y4") or {}).get("items") or []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append({
            "id": item.get("id") or "",
            "text": item.get("text") or "",
            "abilities": item.get("abilities") or [],
            "band": item.get("band") or "",
        })
    return out


def _strip_raw(items) -> list:
    """去掉证据条目里的 ``raw``（分值只入库，任何接口都不返回）。"""
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        copy = dict(item)
        copy.pop("raw", None)
        out.append(copy)
    return out


def _sanitize_auto(auto: dict) -> dict:
    y4 = dict(auto.get("y4") or {})
    y4["items"] = _strip_raw(y4.get("items"))
    return {**auto, "y4": y4}


def _sanitize_version(version: dict | None) -> dict | None:
    if not version:
        return version
    version = dict(version)
    snapshot = version.get("y4_snapshot")
    if isinstance(snapshot, dict):
        version["y4_snapshot"] = {**snapshot,
                                  "items": _strip_raw(snapshot.get("items"))}
    if isinstance(version.get("evidence"), list):
        version["evidence"] = _strip_raw(version["evidence"])
    return version


def _sanitize_prep(prep: dict) -> dict:
    return {**prep, "current_version": _sanitize_version(prep.get("current_version"))}


def _doc_blocks(value, found=None) -> dict:
    """id → block for every ``{id, text}`` block in a document (flags excluded)."""
    found = {} if found is None else found
    if isinstance(value, dict):
        if isinstance(value.get("id"), str) and isinstance(value.get("text"), str):
            found.setdefault(value["id"], value)
        for key, child in value.items():
            if key != "fact_flags":
                _doc_blocks(child, found)
    elif isinstance(value, list):
        for child in value:
            _doc_blocks(child, found)
    return found


def _open_fact_flags(doc) -> list:
    """Fact flags the mentor still has to deal with. A flag is closed when it was
    acknowledged, or when its block's text is no longer the text that was flagged
    (edited or removed). A flag without a block closes only by acknowledgement."""
    flags = doc.get("fact_flags") if isinstance(doc, dict) else None
    if not isinstance(flags, list):
        return []
    blocks = _doc_blocks(doc)
    open_flags = []
    for flag in flags:
        if not isinstance(flag, dict) or flag.get("acked"):
            continue
        block_id = flag.get("block_id")
        if block_id and flag.get("block_text") is not None:
            block = blocks.get(block_id)
            if block is None or (block.get("text") or "").strip() != \
                    (flag.get("block_text") or "").strip():
                continue
        open_flags.append(flag)
    return open_flags


_MATERIAL_LABELS = {
    "parent": "家长反馈",
    "case_review": "Case Review",
    "first_touch_extra": "First Touch 补充",
    "other": "其他资料",
}
_MATERIAL_ORDER = ("parent", "case_review", "first_touch_extra", "other")

_PREP_STATUS_LABELS = {"draft": "草稿", "generating": "生成中",
                       "review": "待审阅", "final": "已定稿"}


def _first_touch_present(student_id) -> bool:
    try:
        return bool((sources._first_touch(student_id) or {}).get("present"))
    except Exception:
        return False


def _prep_materials(prep: dict) -> list:
    """列表行：会前准备的资料标签（Y4 恒在）。"""
    out = ["Y4"]
    if _first_touch_present(prep["student_id"]):
        out.append("First Touch")
    present = {row["category"] for row in store.list_sources(prep["id"])}
    for category in _MATERIAL_ORDER:
        if category in present:
            out.append(_MATERIAL_LABELS[category])
    return out


def _counted(label: str, count: int) -> str:
    return label if count <= 1 else "%s %d 份" % (label, count)


def _prep_version(prep: dict):
    """与 ``_detail`` 相同的取值：定稿看当前版本，草稿看 edit 再看当前。"""
    if prep.get("status") == "final":
        return store.get_current_version(prep["id"])
    return (store.get_latest_version(prep["id"], "edit")
            or store.get_current_version(prep["id"]))


def _detail(prep: dict) -> dict:
    prep = _sanitize_prep(prep)
    job_id = None
    if prep["status"] == "generating":
        job_id = job_attempts.current("prep", prep["id"])
        if not job_id:
            prep = _sanitize_prep(store.get_prep(prep["id"]) or prep)
    auto = _sanitize_auto(sources.auto_sources(prep["student_id"]))
    uploaded = [{k: v for k, v in row.items() if k != "stored_path"}
                for row in store.list_sources(prep["id"])]
    # a final prep shows its locked final row (it carries reviewed_at);
    # a draft shows the working edit row
    if prep.get("status") == "final":
        current = store.get_current_version(prep["id"])
    else:
        current = (store.get_latest_version(prep["id"], "edit")
                   or store.get_current_version(prep["id"]))
    version = _sanitize_version(current)
    kb, fixed = _kb_payload()
    return {
        "ok": True,
        "job_id": job_id,
        "can_edit": store.can_access_prep(_user(), prep["id"]),
        "prep": prep,
        "status": prep["status"],
        "rev": prep["rev"],
        "doc": (version or {}).get("doc"),
        "version": version,
        "sources": uploaded,
        "auto": auto,
        "kb": kb,
        "fixed": fixed,
        "y4_items": _y4_items(prep, auto, version),
    }


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------
@bp.route("/m1")
@page_login_required
def page_home():
    meeting_student = request.args.get("create_meeting", type=int)
    if meeting_student:
        student = _db.get_student(meeting_student)
        if not student or not store.can_access_student(_user(), meeting_student):
            abort(404)
        if not _meeting_creation(student,
                                 store.list_preps(user=_user(), student_id=meeting_student, limit=1)).get("href"):
            return redirect(f"/m1/students/{meeting_student}#meetings")
    student_id = meeting_student or request.args.get("student", type=int)
    return _render_page("m1/home.html", nav_active="students", student_id=student_id,
                        create_meeting=bool(meeting_student),
                        ctx={"studentId": student_id})


@bp.route("/m1/preps")
@page_login_required
def page_preps():
    return _render_page("m1/lists.html", nav_active="preps", kind="preps")


@bp.route("/m1/reports")
@page_login_required
def page_reports():
    return _render_page("m1/lists.html", nav_active="reports", kind="reports")


@bp.route("/m1/plans")
@page_login_required
def page_plans():
    return _render_page("m1/lists.html", nav_active="plans", kind="plans")


@bp.route("/m1/preps/<int:prep_id>")
@page_login_required
def page_student(prep_id: int):
    prep = _prep_or_404(prep_id)
    return _render_page("m1/student.html", prep=prep, prep_id=prep["id"],
                        ctx={"prep": prep})


@bp.route("/m1/preps/<int:prep_id>/prep")
@page_login_required
def page_workspace(prep_id: int):
    prep = _prep_or_404(prep_id)
    if not store.can_access_prep(_user(), prep_id):
        return _render_page("m1/document_readonly.html", prep=prep, prep_id=prep_id,
                            kind="prep", detail=_detail(prep))
    return _render_page("m1/workspace.html", nav_active="preps", prep=prep,
                        prep_id=prep["id"], m1_parts=M1_PARTS, ctx={"prep": prep})


@bp.route("/m1/preps/<int:prep_id>/print")
@page_login_required
def page_print(prep_id: int):
    prep = _prep_or_404(prep_id)
    prep["current_version"] = _sanitize_version(prep.get("current_version"))
    detail = _detail(prep)
    # the fact flags are for the mentor's review only and never reach the print page
    nested_prep = detail.get("prep") or {}
    for holder in (detail, detail.get("version") or {},
                   prep.get("current_version") or {},
                   nested_prep.get("current_version") or {}):
        if isinstance(holder.get("doc"), dict):
            holder["doc"] = {key: value for key, value in holder["doc"].items()
                             if key != "fact_flags"}
    return _render_page("m1/print.html", prep=prep, prep_id=prep["id"],
                        detail=detail, ctx={"prep": prep, "detail": detail})


# ---------------------------------------------------------------------------
# 学生 / prep 列表
# ---------------------------------------------------------------------------
def _visible_plans(user):
    try:
        return pstore.list_plans(user, scope="all")
    except OperationalError:
        pstore.ensure_tables()
        return pstore.list_plans(user, scope="all")


def _plan_step_url(plan: dict) -> str:
    step = "inputs"
    if plan.get("status") in ("generating", "review"):
        step = "internal"
    elif plan.get("status") == "approved":
        step = "parent"
    return "/m1/plans/%d#step=%s" % (plan["id"], step)


def _plan_cell(plan: dict | None):
    """学生列表「发展计划」单元格：Block 号 + 阶段 + 状态语气。"""
    if not plan:
        return None
    label = plan.get("status_label") or ""
    tone = "s1"
    if plan.get("parent_version_id") and plan.get("parent_stale"):
        label, tone = "家长版 已过期", "s2"
    elif plan.get("status") == "approved":
        parent = plan.get("parent_status")
        if parent == "draft":
            label = "家长版待确认"
        elif parent == "confirmed":
            label = "家长版已确认"
        elif parent == "generating":
            label = "家长版生成中"
        elif parent == "exported":
            label, tone = "已导出", "s0"
        else:
            label, tone = "已批准", "s0"
    return {"id": plan["id"], "block_no": int(plan.get("block_no") or 1),
            "label": label, "tone": tone, "step_url": _plan_step_url(plan)}


def _visible_work_sources(user, **kwargs):
    try:
        return roster.visible_sources(user, **kwargs)
    except OperationalError:
        pstore.ensure_tables()
        return roster.visible_sources(user, **kwargs)


def _attach_student_work(rows):
    reports = rstore.list_overview([prep["id"] for row in rows for prep in row["_preps"]])
    report_allowed = _can_manage_report()
    for row in rows:
        row.update(workflow.summarize(row["_preps"], row["_plans"], reports,
                                      report_allowed=report_allowed))
        row["hub_url"] = f"/m1/students/{row['student_id']}"
    return reports


def student_work_summary(student_id):
    rows = _visible_work_sources(_user(), student_id=student_id, include_unassigned=True)
    _attach_student_work(rows)
    if not rows:
        return {"next": None, "tasks": [], "workflow_state": "idle"}
    return {key: rows[0][key] for key in ("next", "tasks", "workflow_state", "hub_url")}


@bp.route("/api/m1/students")
@role_required(*_WRITE_ROLES)
def api_students():
    rows = store.list_students(_user())
    plans = {plan['student_id']: plan for plan in reversed(pstore.list_plans(_user()))}
    for row in rows:
        row['plan'] = _plan_cell(plans.get(row['id']))
        row['overview_url'] = '/api/m1/students/%d/overview' % row['id']
    return jsonify({"ok": True, "students": rows})


@bp.route("/api/m1/preps")
@role_required(*_WRITE_ROLES)
def api_preps():
    student_id = request.args.get("student_id", type=int)
    status = (request.args.get("status") or "").strip() or None
    if status and status not in store.STATUSES:
        return _err("status 无效")
    user = _user()
    rows = store.list_preps(user=user, student_id=student_id, status=status)
    overview = rstore.list_overview([row["id"] for row in rows])
    work_rows = _visible_work_sources(user, student_id=student_id)
    overview.update(_attach_student_work(work_rows))
    work = {row["student_id"]: row for row in work_rows}
    assigned = store.assigned_student_ids(user)
    for row in rows:
        found = overview.get(row["id"])
        if found:
            row["report"] = {"status": found["status"], "label": found["label"],
                             "started": found["started"]}
        else:
            row["report"] = {"status": "draft", "label": "未开始", "started": False}
        row["materials"] = _prep_materials(row)
        row["transcript"] = bool(found and found.get("has_transcript"))
        published_at = ""
        if found and found.get("status") == "published":
            report_row = rstore.get_report(row["id"], with_transcript=False)
            published_at = (report_row or {}).get("published_at") or ""
        row["published_at"] = published_at
        plan = work.get(row["student_id"], {}).get("plan")
        row["plan"] = _plan_cell(plan)
        row["can_edit"] = store.can_access_prep(user, row["id"])
        row["report"]["can_edit"] = row["can_edit"] and _can_manage_report()
        row["assigned"] = row["student_id"] in assigned
        row["next"] = work.get(row["student_id"], {}).get("next")
    return jsonify({"ok": True, "me": user.get("user_id"), "preps": rows})


@bp.route("/api/m1/roster")
@role_required(*_WRITE_ROLES)
def api_roster():
    """Discovery uses the same student-wide read visibility as document routes."""
    user = _user()
    include_unassigned = request.args.get("include_unassigned") == "1"
    rows = _visible_work_sources(user, include_unassigned=include_unassigned)
    reports = _attach_student_work(rows)
    for row in rows:
        prep = row["prep"]
        if prep:
            report = reports.get(prep["id"])
            prep["has_doc"] = bool(prep.pop("current_version_id"))
            prep["report"] = ({k: report[k] for k in ("status", "label", "started")}
                              if report else {"status": "draft", "label": "未开始", "started": False})
        row["plan"] = _plan_cell(row["plan"])
        row.pop("_preps")
        row.pop("_plans")
        row.pop("tasks")
    return jsonify({"ok": True, "me": user.get("user_id"), "students": rows})


@bp.route("/api/m1/mentors")
@role_required(*_WRITE_ROLES)
def api_mentors():
    """可选的心有灵析 Mentor：启用的 admin/advisor 且心有灵析打开。仅管理员 / 心有灵析管理。"""
    if not store.is_m1_admin(_user()):
        return _err("只有管理员可以更换 Mentor", 403)
    rows = []
    for u in _db.list_users():
        if not u.get("is_active") or u.get("role") not in ("admin", "advisor"):
            continue
        if not u.get("m1_access"):
            continue
        rows.append({"id": u["id"], "display_name": u.get("display_name") or u.get("username")})
    return jsonify({"ok": True, "mentors": rows})


@bp.route("/api/m1/preps", methods=["POST"])
@role_required(*_WRITE_ROLES)
def api_create_prep():
    body = _json_body()
    student_id = body.get("student_id")
    if not student_id:
        return _err("缺少 student_id")
    try:
        student_id = int(student_id)
    except (TypeError, ValueError):
        return _err("student_id 必须是数字")

    meeting_date = str(body.get("meeting_date") or "").strip()
    if meeting_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", meeting_date):
        return _err("会议日期格式不对")
    duration = body.get("duration")
    duration = 60 if duration in (None, "") else duration
    if isinstance(duration, bool) or not isinstance(duration, int) \
            or duration not in store.DURATIONS:
        return _err("时长只能是 60、75 或 90 分钟")

    student = _db.get_student(student_id)
    if not student:
        return _err("学生不存在", 404)
    user = _user()
    if not store.can_access_student(user, student_id):
        return _err("无权访问该学生", 403)

    from growth_talk.y4_snapshot import latest_complete_y4
    report = latest_complete_y4(student_id)
    if report is None:
        return _err("Y4 尚未完成", 400, reason="Y4 尚未完成")

    mentor_name = (user.get("display_name") or user.get("advisor_name") or "")
    attendees = []
    if mentor_name:
        attendees.append("%s（心有灵析 Mentor）" % mentor_name)
    if student.get("name"):
        attendees.append(student["name"])
    prep, created = store.create_first_prep(
        student_id, created_by=user.get("user_id"),
        mentor_user_id=user.get("user_id"), duration=duration,
        meeting_date=meeting_date, attendees=attendees,
    )
    store.audit(user.get("user_id"), student_id, "m1.create" if created else "m1.create_reused",
                {"prep_id": prep["id"]})
    return jsonify({"ok": True, "prep": prep, "created": created}), 201 if created else 200


# ---------------------------------------------------------------------------
# prep 详情 / 会议信息
# ---------------------------------------------------------------------------
@bp.route("/api/m1/preps/<int:prep_id>")
@role_required(*_WRITE_ROLES)
def api_prep_detail(prep_id: int):
    prep, error = _api_read_prep(prep_id)
    if error:
        return error
    return jsonify(_detail(prep))


@bp.route("/api/m1/preps/<int:prep_id>/overview")
@role_required(*_WRITE_ROLES)
def api_prep_overview(prep_id: int):
    """学生页：自动来源、会前准备与会后报告两部分的状态和资料。"""
    prep, error = _api_read_prep(prep_id)
    if error:
        return error

    auto = sources.auto_sources(prep["student_id"])
    y4 = auto.get("y4") or {}
    first_touch = auto.get("first_touch") or {}
    questionnaire_rows = auto.get("questionnaires") or []
    done = sum(1 for q in questionnaire_rows if q.get("status") == "已完成")
    total = len(questionnaire_rows)

    version = _prep_version(prep)
    doc = version.get("doc") if version else None
    label = _PREP_STATUS_LABELS.get(prep["status"], prep["status"])
    if prep["status"] == "draft" and not doc:
        label = "待生成"
    names = {row.get("code"): row.get("name") or ""
             for row in _kb_payload()[0].get("abilities") or []}
    priority = []
    doc_priority = (doc.get("priority") if isinstance(doc, dict) else None) or []
    for row in doc_priority:
        code = row.get("code") if isinstance(row, dict) else None
        if code in names:
            priority.append({"code": code, "name": names[code]})

    prep_materials = ["Y4"]
    if first_touch.get("present"):
        prep_materials.append("First Touch")
    if done > 0:
        prep_materials.append("补充问卷 %d/%d" % (done, total))
    prep_uploads = store.list_sources(prep["id"])
    for category in _MATERIAL_ORDER:
        count = sum(1 for src in prep_uploads if src["category"] == category)
        if count:
            prep_materials.append(_counted(_MATERIAL_LABELS[category], count))

    report = rstore.get_report(prep_id, with_transcript=True)
    report_version = rstore.current_version(report["id"]) if report else None
    has_transcript = bool((report or {}).get("transcript_text", "").strip())
    started = bool(report) and (has_transcript or report["status"] != "draft")
    report_materials = ["Y4"]
    if first_touch.get("present"):
        report_materials.append("First Touch")
    if done > 0:
        report_materials.append("补充问卷 %d/%d" % (done, total))
    report_uploads = store.list_sources(prep["id"], part="report")
    if report_uploads:
        report_materials.append("其他资料 %d 份" % len(report_uploads))
    if has_transcript:
        report_materials.append("逐字稿")

    plans = [row for row in _visible_plans(_user())
             if int(row["student_id"]) == int(prep["student_id"])]
    plans.sort(key=lambda row: (int(row.get("block_no") or 0), int(row.get("id") or 0)),
               reverse=True)
    for row in plans:
        row["step_url"] = _plan_step_url(row)
        row["finished"] = row.get("parent_status") == "exported"
        row["goal_names"] = {item.get("code"): names.get(item.get("code"), "")
                             for item in row.get("goals") or []}

    return jsonify({
        "ok": True,
        "work": student_work_summary(prep["student_id"]),
        "meeting_label": workflow.meeting_label(prep["meeting_date"]),
        "can_edit": store.can_access_prep(_user(), prep["id"]),
        "prep": prep,
        "auto": {
            "y4": {"complete": bool(y4.get("complete")), "date": y4.get("date") or ""},
            "first_touch": {"present": bool(first_touch.get("present")),
                            "date": first_touch.get("date") or ""},
            "questionnaires": {"done": done, "total": total},
        },
        "report_can_edit": store.can_access_prep(_user(), prep_id) and _can_manage_report(),
        "prep_part": {
            "status": prep["status"],
            "label": label,
            "has_doc": bool(doc),
            "version_n": int((version or {}).get("n") or 0),
            "finalized_at": ((version or {}).get("reviewed_at") or "")
            if prep["status"] == "final" else "",
            "duration": int(prep.get("duration") or 60),
            "priority": priority,
            "materials": prep_materials,
        },
        "report_part": {
            "status": (report or {}).get("status", "draft"),
            "label": (report or {}).get("label", "未开始")
            if started else "未开始",
            "started": started,
            "transcript_filename": (report or {}).get("transcript_filename") or "",
            "has_version": bool(report_version),
            "updated_at": (report or {}).get("updated_at") or "",
            "published_at": (report or {}).get("published_at") or "",
            "materials": report_materials,
        },
        "plans": plans,
        "can_create_plan": (store.can_access_prep(_user(), prep_id)
                            and pstore.report_ready(report)),
        "activity": store.list_activity(prep_id, prep["student_id"]),
    })


@bp.route("/api/m1/preps/<int:prep_id>", methods=["PATCH"])
@role_required(*_WRITE_ROLES)
def api_update_prep(prep_id: int):
    prep, error = _api_prep(prep_id)
    if error:
        return error
    body = _json_body()
    fields = {}
    for key in ("meeting_date", "mentor_user_id", "duration", "attendees"):
        if key in body:
            fields[key] = body[key]
    if not fields:
        return _err("没有需要更新的字段")
    if "mentor_user_id" in fields and not store.is_m1_admin(_user()):
        return _err("只有管理员可以更换 Mentor", 403)
    if "mentor_user_id" in fields and fields["mentor_user_id"] not in (None, ""):
        try:
            fields["mentor_user_id"] = int(fields["mentor_user_id"])
        except (TypeError, ValueError):
            return _err("mentor_user_id 必须是数字")
        mentor = _db.get_user_by_id(fields["mentor_user_id"])
        if not mentor:
            return _err("心有灵析 Mentor 不存在", 404)
        if not mentor["is_active"] or not mentor["m1_access"]:
            return _err("请选择已启用心有灵析权限的导师", 422)
    try:
        updated = store.update_prep(prep_id, **fields)
    except ValueError as exc:
        return _err(str(exc), 422)
    store.audit(_user().get("user_id"), prep["student_id"], "m1.meta", fields)
    return jsonify({"ok": True, "prep": updated})


# ---------------------------------------------------------------------------
# 资料
# ---------------------------------------------------------------------------
@bp.route("/api/m1/preps/<int:prep_id>/sources", methods=["POST"])
@role_required(*_WRITE_ROLES)
def api_add_source(prep_id: int):
    prep, error = _api_prep(prep_id)
    if error:
        return error

    upload = request.files.get("file")
    body = _json_body() if not upload else {}
    category = (request.form.get("category") or body.get("category")
                or "other").strip()
    if category not in store.SOURCE_CATEGORIES:
        return _err("资料类别无效")

    try:
        if upload is not None:
            data = upload.read()
            filename = upload.filename or ""
            if not filename:
                return _err("缺少文件名")
            source = sources.add_upload(prep_id, filename, data, category, _user())
        else:
            source = sources.add_text(prep_id, body.get("text") or "", category,
                                      _user())
    except sources.UploadError as exc:
        return _err(exc.message, exc.status)
    except ValueError as exc:
        return _err(str(exc), 422)

    store.audit(_user().get("user_id"), prep["student_id"], "m1.source_add",
                {"prep_id": prep_id, "source_id": source["id"],
                 "category": category, "filename": source.get("filename")})
    return jsonify({"ok": True, "source": source}), 201


@bp.route("/api/m1/sources/<int:source_id>", methods=["PATCH"])
@role_required(*_WRITE_ROLES)
def api_update_source(source_id: int):
    row = store.get_source(source_id)
    if not row:
        return _err("资料不存在", 404)
    prep, error = _api_prep(row["prep_id"])
    if error:
        return error
    body = _json_body()
    category = body.get("category")
    date_value = body.get("detected_date", body.get("date"))
    if category is None and date_value is None:
        return _err("没有需要更新的字段")
    try:
        updated = store.update_source(source_id, category=category,
                                      detected_date=date_value)
    except ValueError as exc:
        return _err(str(exc), 422)
    store.audit(_user().get("user_id"), prep["student_id"], "m1.source_update",
                {"prep_id": prep["id"], "source_id": source_id,
                 "category": updated["category"],
                 "detected_date": updated["detected_date"]})
    return jsonify({"ok": True, "source": updated})


@bp.route("/api/m1/sources/<int:source_id>", methods=["DELETE"])
@role_required(*_WRITE_ROLES)
def api_delete_source(source_id: int):
    row = store.get_source(source_id)
    if not row:
        return _err("资料不存在", 404)
    prep, error = _api_prep(row["prep_id"])
    if error:
        return error
    deleted = store.delete_source(source_id)
    sources.remove_upload_file(deleted.get("stored_path") or "")
    store.audit(_user().get("user_id"), prep["student_id"], "m1.source_delete",
                {"prep_id": prep["id"], "source_id": source_id})
    return jsonify({"ok": True, "deleted": source_id})


# ---------------------------------------------------------------------------
# 草稿 / 定稿
# ---------------------------------------------------------------------------
@bp.route("/api/m1/preps/<int:prep_id>/doc", methods=["PUT"])
@role_required(*_WRITE_ROLES)
def api_save_doc(prep_id: int):
    prep, error = _api_prep(prep_id)
    if error:
        return error
    body = _json_body()
    rev = body.get("rev")
    doc = body.get("doc")
    if isinstance(rev, bool) or not isinstance(rev, int):
        return _err("缺少 rev")
    if not isinstance(doc, dict):
        return _err("doc 必须是对象")
    # 浏览器保存不能改动事实标记：以最近一次草稿里存的为准，
    # 既不能删掉标记，也不能把 acked 设成 true；只有 ack 路由能设 acked。
    draft = store.get_latest_version(prep_id, "edit") or {}
    stored_doc = draft.get("doc")
    stored_flags = stored_doc.get("fact_flags") if isinstance(stored_doc, dict) else None
    if stored_flags is not None:
        doc["fact_flags"] = stored_flags
    else:
        doc.pop("fact_flags", None)
    try:
        result = store.save_doc(prep_id, rev, doc)
    except store.RevConflict as exc:
        return jsonify({"ok": False, "error": str(exc), "rev": exc.rev,
                        "doc": exc.doc}), 409
    except store.FinalizeBlocked as exc:
        return _err(str(exc), 409)
    store.audit(_user().get("user_id"), prep["student_id"], "m1.edit",
                {"prep_id": prep_id, "rev": result["rev"]})
    return jsonify({"ok": True, "rev": result["rev"],
                    "version_id": result["version_id"]})


@bp.route("/api/m1/preps/<int:prep_id>/safety-ack", methods=["POST"])
@role_required(*_WRITE_ROLES)
def api_safety_ack(prep_id: int):
    prep, error = _api_prep(prep_id)
    if error:
        return error
    updated = store.ack_safety(prep_id, _user().get("user_id"))
    store.audit(_user().get("user_id"), prep["student_id"], "m1.safety_ack",
                {"prep_id": prep_id})
    return jsonify({"ok": True, "prep": updated})


@bp.route("/api/m1/preps/<int:prep_id>/finalize", methods=["POST"])
@role_required(*_WRITE_ROLES)
def api_finalize(prep_id: int):
    prep, error = _api_prep(prep_id)
    if error:
        return error
    draft = store.get_latest_version(prep_id, "edit") or {}
    open_flags = _open_fact_flags(draft.get("doc"))
    safety_unacked = bool(store._safety_flags(draft.get("doc") or {})) \
        and not prep.get("safety_ack_at")
    try:
        version = store.finalize_prep(prep_id, _user().get("user_id"))
    except store.FinalizeBlocked as exc:
        return _err(str(exc), 409)
    store.audit(_user().get("user_id"), prep["student_id"], "m1.final",
                {"prep_id": prep_id, "version_id": version["id"],
                 "open_flags": len(open_flags),
                 "safety_unacked": safety_unacked})
    return jsonify({"ok": True, "version": version, "prep": store.get_prep(prep_id),
                    "open_flags": len(open_flags),
                    "safety_unacked": safety_unacked})


@bp.route("/api/m1/preps/<int:prep_id>/fact-flags/<flag_id>/ack", methods=["POST"])
@role_required(*_WRITE_ROLES)
def api_fact_flag_ack(prep_id: int, flag_id: str):
    prep, error = _api_prep(prep_id)
    if error:
        return error
    draft = store.get_latest_version(prep_id, "edit") or {}
    doc = draft.get("doc")
    flags = doc.get("fact_flags") if isinstance(doc, dict) else None
    flag = next((row for row in flags or []
                 if isinstance(row, dict) and row.get("id") == flag_id), None)
    if flag is None:
        return _err("没有这条核对标记", 404)
    flag["acked"] = True
    try:
        result = store.save_doc(prep_id, prep["rev"], doc)
    except store.RevConflict as exc:
        return jsonify({"ok": False, "error": str(exc), "rev": exc.rev,
                        "doc": exc.doc}), 409
    except store.FinalizeBlocked as exc:
        return _err(str(exc), 409)
    store.audit(_user().get("user_id"), prep["student_id"], "m1.fact_flag_ack",
                {"prep_id": prep_id, "flag_id": flag_id, "kind": flag.get("kind")})
    return jsonify({"ok": True, "rev": result["rev"], "flag_id": flag_id})


@bp.route("/api/m1/preps/<int:prep_id>/reopen", methods=["POST"])
@role_required(*_WRITE_ROLES)
def api_reopen(prep_id: int):
    prep, error = _api_prep(prep_id)
    if error:
        return error
    try:
        version = store.reopen_prep(prep_id, _user().get("user_id"))
    except store.FinalizeBlocked as exc:
        return _err(str(exc), 409)
    store.audit(_user().get("user_id"), prep["student_id"], "m1.reopen",
                {"prep_id": prep_id, "version_id": version["id"]})
    return jsonify({"ok": True, "version": version, "prep": store.get_prep(prep_id)})


@bp.route("/api/m1/preps/<int:prep_id>/export", methods=["POST"])
@role_required(*_WRITE_ROLES)
def api_export(prep_id: int):
    prep, error = _api_prep(prep_id)
    if error:
        return error
    store.audit(_user().get("user_id"), prep["student_id"], "m1.export",
                {"prep_id": prep_id, "status": prep["status"]})
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# P3: generate / jobs（P3 追加）
# ---------------------------------------------------------------------------
@bp.route("/api/m1/preps/<int:prep_id>/generate", methods=["POST"])
@role_required(*_WRITE_ROLES)
def api_generate(prep_id: int):
    prep, error = _api_prep(prep_id)
    if error:
        return error
    from m1 import jobs as m1_jobs

    def begin():
        current = store.get_prep(prep_id)
        if current["status"] == "generating":
            raise job_attempts.AttemptConflict("生成任务已在进行中")
        store.set_status(prep_id, "generating")
        return current["status"]

    actor = _user().get("user_id")
    try:
        reserved_id, previous = job_attempts.reserve("prep", prep_id, begin, prep_id=prep_id)
    except job_attempts.AttemptConflict as exc:
        return _err(str(exc), 409)
    try:
        job_id = m1_jobs.launch_job(prep_id, previous_status=previous,
                                    actor_id=actor, job_id=reserved_id, attempt_scope="prep")
    except Exception:
        job_attempts.cancel("prep", prep_id, reserved_id)
        return _err("生成任务未能启动，请重试。", 500)

    store.audit(_user().get("user_id"), prep["student_id"], "m1.generate",
                {"prep_id": prep_id, "job_id": job_id,
                 "previous_status": previous})
    return jsonify({"ok": True, "job_id": job_id})


@bp.route("/api/m1/jobs/<job_id>")
@role_required(*_WRITE_ROLES)
def api_job_status(job_id: str):
    from m1 import jobs as m1_jobs

    if not m1_jobs.JOB_ID_RE.fullmatch(job_id or ""):
        return _err("任务不存在", 404)
    job = m1_jobs.read_job(job_id)
    if not job:
        return _err("任务不存在", 404)
    if job.get("plan_id"):
        plan = pstore.get_plan(job.get("plan_id"))
        if not plan:
            return _err("任务不存在", 404)
        if not pstore.can_view_plan(_user(), plan):
            return _err("无权访问该任务", 403)
        if job.get("kind") in ("plan_generate", "plan_regen", "plan_parent"):
            scope = "plan_parent" if job["kind"] == "plan_parent" else "plan_internal"
            job_attempts.current(scope, plan["id"])
        return jsonify({"ok": True, "job": m1_jobs.read_job(job_id) or job})
    prep = store.get_prep(job.get("prep_id") or 0)
    if not prep:
        return _err("任务不存在", 404)
    if not store.can_read_prep(_user(), prep["id"]):
        return _err("无权访问该任务", 403)
    if job.get("report_id"):
        job_attempts.current("report", job["report_id"])
    else:
        job_attempts.current("prep", prep["id"])
    return jsonify({"ok": True, "job": m1_jobs.read_job(job_id) or job})


def _student_overview_payload(student_id: int) -> dict:
    plans = pstore.list_plans(_user(), student_id=student_id)
    for plan in plans:
        plan['next_action'] = pstore.next_action(plan)
    preps = store.list_preps(user=_user(), student_id=student_id)
    statuses = rstore.list_overview([p["id"] for p in preps])
    for prep in preps:
        prep["can_edit"] = store.can_access_prep(_user(), prep["id"])
        prep["report"] = statuses.get(prep["id"]) or {}
    student = _db.get_student(student_id) or {}
    meeting = _meeting_creation(student, preps)
    return {'ok': True,
            'work': student_work_summary(student_id),
            'meeting_creation': meeting,
            'profile_href': _profile_href(student),
            'student': {k: student.get(k) for k in ('id', 'name', 'student_code', 'grade', 'school')},
            'preps': preps, 'plans': plans,
            'can_create_direct': store.can_read_student(_user(), student_id),
            'can_create_first_meeting': bool(meeting.get('href')),
            'can_manage_team': pstore.can_manage_team(_user()),
            'team': plan_collab.team_view(student_id),
            'create_plan': {'method': 'POST', 'href': '/api/m1/plans',
                            'source_mode': 'mentor_inputs', 'student_id': student_id}}


def _profile_href(student, *, y4=False):
    scope = app_utils._advisor_scope()
    if scope is not None and (student.get("advisor_name") or "") != scope:
        return ""
    code = student.get("student_code")
    return f"/app/students/{quote(code, safe='')}" + ("?tab=y4" if y4 else "") if code else ""


def _meeting_creation(student, preps):
    from growth_talk.y4_snapshot import latest_complete_y4

    student_id = student["id"]
    if preps or not store.can_access_student(_user(), student_id):
        return {}
    if latest_complete_y4(student_id) is None:
        return {"reason": "Y4 尚未完成", "y4_href": _profile_href(student, y4=True)}
    return {"href": f"/m1?create_meeting={student_id}"}


def _can_view_student_hub(student_id: int) -> bool:
    return (store.can_read_student(_user(), student_id)
            or bool(store.list_preps(user=_user(), student_id=student_id, limit=1)))


@bp.route('/api/m1/students/<int:student_id>/overview')
@role_required(*_WRITE_ROLES)
def api_student_overview(student_id):
    """Student-scoped JSON hub, including students with no meetings or reports."""
    student = _db.get_student(student_id)
    if not student or not _can_view_student_hub(student_id):
        return _err('学生不存在', 404)
    return jsonify(_student_overview_payload(student_id))


@bp.route('/m1/students/<int:student_id>')
@role_required(*_WRITE_ROLES)
def page_student_hub(student_id):
    """Student hub page; same access check as the JSON overview endpoint."""
    student = _db.get_student(student_id)
    if not student or not _can_view_student_hub(student_id):
        abort(404)
    return _render_page('m1/student_hub.html', nav_active='students',
                        student=student, student_id=student_id,
                        can_create_direct=store.can_read_student(_user(), student_id),
                        meeting_creation=_meeting_creation(
                            student, store.list_preps(user=_user(), student_id=student_id, limit=1)),
                        profile_href=_profile_href(student),
                        ctx={'student': student})
