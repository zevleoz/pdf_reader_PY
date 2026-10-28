"""M1 会前准备蓝图：页面 + ``/api/m1/*`` 数据接口。

- 页面：``/m1``、``/m1/preps/<id>``、``/m1/preps/<id>/print``
- 数据：学生清单、prep 列表/详情、会议信息、资料上传与修改、草稿自动保存、
  安全提示确认、定稿/重新打开、导出审计

权限（README §3）：Admin 全部；Advisor 名下学生或本人为 Mentor；Viewer 403。
P3 的 ``generate`` / ``jobs`` 两个路由由 P3 追加在本文件末尾的标记块内。
"""
from __future__ import annotations

from functools import wraps

from flask import (Blueprint, abort, jsonify, render_template, request,
                   send_from_directory, session)
from jinja2 import TemplateNotFound

import db as _db
import m1.sources as sources
import m1.store as store
from app_utils import BASE_DIR, page_login_required, role_required

bp = Blueprint("m1", __name__)

_WRITE_ROLES = ("admin", "advisor")


@bp.route("/m1/assets/<path:filename>")
def m1_asset(filename: str):
    """M1 页面静态资源（app.py 用 ``static_folder=None``，静态目录需显式路由）。"""
    return send_from_directory(str(BASE_DIR / "static" / "m1"), filename)


# ---------------------------------------------------------------------------
# 通用助手
# ---------------------------------------------------------------------------
def _user() -> dict:
    return {
        "user_id": session.get("user_id"),
        "role": session.get("role") or "",
        "advisor_name": session.get("advisor_name") or "",
        "display_name": session.get("display_name") or "",
    }


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


def _prep_or_404(prep_id: int):
    prep = store.get_prep(prep_id)
    if not prep:
        abort(404)
    if not store.can_access(_user(), prep):
        abort(403)
    return prep


def _api_prep(prep_id: int):
    """API 取 prep：不存在 → 404，越权 → 403。返回 ``(prep, error)``。"""
    prep = store.get_prep(prep_id)
    if not prep:
        return None, _err("会前准备不存在", 404)
    if not store.can_access(_user(), prep):
        return None, _err("无权访问该会前准备", 403)
    return prep, None


def _render_page(template: str, **ctx):
    """P4 模板尚未落地时返回最小占位页。"""
    _page_guard()
    try:
        return render_template(template, nav_active="m1", **ctx)
    except TemplateNotFound:
        return ("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
                "<title>M1 会前准备</title></head><body>"
                "<h1>M1 会前准备</h1><p>页面模板尚未就绪。</p></body></html>"), 200


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


def _detail(prep: dict) -> dict:
    auto = _sanitize_auto(sources.auto_sources(prep["student_id"]))
    uploaded = store.list_sources(prep["id"])
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
    student_id = request.args.get("student", type=int)
    return _render_page("m1/home.html", student_id=student_id,
                        ctx={"studentId": student_id})


@bp.route("/m1/preps/<int:prep_id>")
@page_login_required
def page_workspace(prep_id: int):
    prep = _prep_or_404(prep_id)
    return _render_page("m1/workspace.html", prep=prep, prep_id=prep["id"],
                        ctx={"prep": prep})


@bp.route("/m1/preps/<int:prep_id>/print")
@page_login_required
def page_print(prep_id: int):
    prep = _prep_or_404(prep_id)
    detail = _detail(prep)
    return _render_page("m1/print.html", prep=prep, prep_id=prep["id"],
                        detail=detail, ctx={"prep": prep, "detail": detail})


# ---------------------------------------------------------------------------
# 学生 / prep 列表
# ---------------------------------------------------------------------------
@bp.route("/api/m1/students")
@role_required(*_WRITE_ROLES)
def api_students():
    return jsonify({"ok": True, "students": store.list_students(_user())})


@bp.route("/api/m1/preps")
@role_required(*_WRITE_ROLES)
def api_preps():
    student_id = request.args.get("student_id", type=int)
    status = (request.args.get("status") or "").strip() or None
    if status and status not in store.STATUSES:
        return _err("status 无效")
    rows = store.list_preps(user=_user(), student_id=student_id, status=status)
    return jsonify({"ok": True, "preps": rows})


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

    # 同一学生已有未定稿的准备时直接复用（360 页按钮与列表入口一致）。
    existing = [p for p in store.list_preps(user=user, student_id=student_id)
                if p["status"] != "final"]
    if existing:
        prep = existing[0]
        store.audit(user.get("user_id"), student_id, "m1.create_reused",
                    {"prep_id": prep["id"]})
        return jsonify({"ok": True, "prep": prep, "created": False})

    mentor_name = (user.get("display_name") or user.get("advisor_name") or "")
    attendees = []
    if mentor_name:
        attendees.append("%s（M1 Mentor）" % mentor_name)
    if student.get("name"):
        attendees.append(student["name"])
    prep = store.create_prep(
        student_id, created_by=user.get("user_id"),
        mentor_user_id=user.get("user_id"), duration=60,
        meeting_date="", attendees=attendees,
    )
    store.audit(user.get("user_id"), student_id, "m1.create", {"prep_id": prep["id"]})
    return jsonify({"ok": True, "prep": prep, "created": True}), 201


# ---------------------------------------------------------------------------
# prep 详情 / 会议信息
# ---------------------------------------------------------------------------
@bp.route("/api/m1/preps/<int:prep_id>")
@role_required(*_WRITE_ROLES)
def api_prep_detail(prep_id: int):
    prep, error = _api_prep(prep_id)
    if error:
        return error
    return jsonify(_detail(prep))


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
    if "mentor_user_id" in fields and fields["mentor_user_id"] not in (None, ""):
        try:
            fields["mentor_user_id"] = int(fields["mentor_user_id"])
        except (TypeError, ValueError):
            return _err("mentor_user_id 必须是数字")
        if not _db.get_user_by_id(fields["mentor_user_id"]):
            return _err("M1 Mentor 不存在", 404)
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
    try:
        version = store.finalize_prep(prep_id, _user().get("user_id"))
    except store.FinalizeBlocked as exc:
        return _err(str(exc), 409)
    store.audit(_user().get("user_id"), prep["student_id"], "m1.final",
                {"prep_id": prep_id, "version_id": version["id"]})
    return jsonify({"ok": True, "version": version, "prep": store.get_prep(prep_id)})


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
    if prep["status"] == "generating":
        return _err("生成任务已在进行中", 409)

    from m1 import jobs as m1_jobs

    previous = prep["status"]
    store.set_status(prep_id, "generating")
    try:
        job_id = m1_jobs.launch_job(prep_id, previous_status=previous,
                                    actor_id=_user().get("user_id"))
    except Exception as exc:
        store.set_status(prep_id, previous)
        return _err("生成任务启动失败：%s" % exc, 500)

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
    prep = store.get_prep(job.get("prep_id") or 0)
    if not prep:
        return _err("任务不存在", 404)
    if not store.can_access(_user(), prep):
        return _err("无权访问该任务", 403)
    return jsonify({"ok": True, "job": job})
