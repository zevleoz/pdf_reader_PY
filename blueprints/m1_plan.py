"""M1 发展计划蓝图：``/api/m1/plans*``（数据层 + 权限）。

页面由 DP5 / DP6 添加；本文件只提供 API：
列表 / 可新建学生 / 新建 / 详情 / 改表头 / 目标 / Development Inputs /
个性化需求 / 文件 / 内部版保存与批准 / 家长版保存、确认、导出 / 版本历史。

写操作只允许 admin 与该计划的 Mentor 本人；只读对可见学生开放。
"""
from __future__ import annotations

import html
import uuid
from pathlib import Path

from flask import Blueprint, Response, abort, jsonify, request

import app_utils
import db as _db
import m1.kb as kb
import m1.plan_collaboration as collab
import m1.plan_kb as plan_kb
import m1.plan_store as pstore
from m1 import job_attempts
import m1.report_store as rstore
import m1.sources as sources
import m1.store as store
from blueprints.m1 import (_err, _json_body, _m1_access_guard, _render_page,
                           _user)
from growth_talk.upload import UploadError, extract_upload

bp = Blueprint("m1_plan", __name__)
bp.before_request(_m1_access_guard)


@bp.before_request
def _require_staff():
    """所有端点都是 M1 API：未登录 401，非 admin/advisor 或没有 M1 权限 403。"""
    if not app_utils.is_authenticated():
        return jsonify({"ok": False, "error": "请先登录"}), 401
    if not app_utils.can_use_m1():
        return jsonify({"ok": False, "error": "当前账号没有心有灵析权限"}), 403
    return None


_MAX_UPLOAD = 10 * 1024 * 1024
_ALLOWED_EXT = (".txt", ".docx", ".pdf")
_EDITABLE_MSG = "只有负责导师可以修改该计划"


# ---------------------------------------------------------------------------
# 助手
# ---------------------------------------------------------------------------
def _user_id() -> int | None:
    return _user().get("user_id")


def _plan_or_error(plan_id: int, *, edit: bool = False):
    """不存在或越权一律 404（不暴露计划是否存在）；写操作再校验 Mentor。"""
    plan = pstore.get_plan(plan_id)
    user = _user()
    if not plan or not pstore.can_view_plan(user, plan):
        return None, _err("发展计划不存在", 404)
    if edit and not pstore.can_edit_plan(user, plan):
        return None, _err(_EDITABLE_MSG, 403)
    scope = "plan_parent" if plan["parent_status"] == "generating" else "plan_internal"
    if plan["status"] == "generating" or plan["parent_status"] == "generating":
        job_attempts.current(scope, plan["id"])
        plan = pstore.get_plan(plan["id"]) or plan
    return plan, None


def _run(callable_):
    """把数据层的异常翻译成 API 语义。"""
    try:
        return callable_(), None
    except collab.CollaborationError as exc:
        return None, (jsonify(exc.payload()), exc.status)
    except pstore.NotFound as exc:
        return None, _err(str(exc), 404)
    except pstore.RevConflict as exc:
        return None, _err(str(exc), 409, rev=exc.rev)
    except pstore.StatusError as exc:
        return None, _err(str(exc), 409)
    except ValueError as exc:
        return None, _err(str(exc), 400)


def _rev(body: dict):
    value = body.get("rev")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _legacy_section(plan: dict, section: str, patch: dict, body: dict):
    """Narrow legacy write: revision CAS + foreign-lease refusal + section version.

    The rich editor moves to ``PATCH /sections/<key>``; these endpoints stay for
    compatibility but can no longer bypass an active collaborator's lease.
    """
    token = body.get("lease_token")
    if token is not None and not isinstance(token, str):
        return None, _err("lease_token 格式不正确", 400)
    rev = _rev(body)
    if rev is None:
        return None, _err("缺少 rev", 400)
    _, error = _run(lambda: collab.apply_section(
        plan["id"], section, patch, _user(), expected_version=None,
        document_version_value=None, lease_token=token, require_lease=False,
        expected_rev=rev))
    if error:
        return None, error
    return pstore.get_plan(plan["id"]), None


def _audit(action: str, plan: dict, **details) -> None:
    payload = {"plan_id": plan.get("id"), "prep_id": plan.get("prep_id"),
               "block_no": plan.get("block_no")}
    payload.update(details)
    store.audit(_user_id(), plan.get("student_id"), action, payload)


def _internal_checks(plan: dict, doc: dict):
    """DP3 的质量检查（未安装时为空）。"""
    try:
        from m1 import plan_checks
    except ImportError:
        return []
    fn = getattr(plan_checks, "run_checks", None) or getattr(plan_checks,
                                                            "internal_checks", None)
    if fn is None:
        return []
    return fn(plan, doc)


def _parent_blocking(plan: dict, doc: dict, internal_doc):
    """DP3 / DP6 的家长版导出检查（未安装时为空）。"""
    try:
        from m1 import plan_checks
    except ImportError:
        return []
    fn = getattr(plan_checks, "parent_blocking", None)
    if fn is None:
        return []
    return fn(doc, plan, internal_doc)


def _goal_rows(plan: dict):
    rows = []
    for item in plan.get("goals") or []:
        try:
            ability = kb.ability(item.get("code"))
        except KeyError:
            ability = {}
        rows.append(dict(item, name=ability.get("name", ""),
                         dim=ability.get("dim", "")))
    return rows


def _wb_candidates(plan: dict):
    installed = pstore._wb_installed()
    out = {}
    if not installed:
        return out
    from m1 import wb
    for item in plan.get("goals") or []:
        out[item["code"]] = wb.candidates(
            item["code"], pstore.wb_grade_or_default(plan)) or []
    return out


def _payload(plan: dict) -> dict:
    files = pstore.list_files(plan["id"])
    internal = pstore.current_version(plan["id"], "internal")
    parent = pstore.current_version(plan["id"], "parent")
    return {
        "plan": plan,
        "job_id": _current_job_id(plan),
        "next_action": pstore.next_action(plan),
        "goals": _goal_rows(plan),
        "personal": {"notes": (plan.get("personal") or {}).get("notes", ""),
                     "summary": (plan.get("personal") or {}).get("summary")
                     or {"text": "", "src": "ai"},
                     "files": files},
        "internal": internal,
        "parent": parent,
        "parent_stale": plan["parent_stale"],
        "parent_family": [{"hash": item["hash"], "seen": bool(item["seen"])}
                          for item in collab.family_state((parent or {}).get("doc") or {})]
                         if parent else [],
        "report": pstore.report_state(plan),
        "can_generate": pstore.generate_blockers(plan),
        "can_edit": pstore.can_edit_plan(_user(), plan),
        "can_approve": pstore.can_approve_plan(_user(), plan),
        "can_manage_team": pstore.can_manage_team(_user()),
        "collaboration": collab.plan_summary(plan, _user()),
        "wb": {"installed": pstore._wb_installed(),
               "candidates": _wb_candidates(plan)},
        "abilities": [{"code": item.get("code"), "name": item.get("name"),
                       "dim": item.get("dim")}
                      for item in kb.load_kb().get("abilities") or []],
        "fixed": plan_kb.fixed(),
        "platforms": plan_kb.platforms(),
        "versions": pstore.list_versions(plan["id"]),
    }


def _next_action(plan: dict):
    status = plan.get("status")
    parent = plan.get("parent_status")
    if status == "inputs":
        return {"label": "继续发展计划", "hash": "#step=inputs"}
    if status == "generating":
        return {"label": "查看生成进度", "hash": "#step=internal"}
    if status == "review":
        return {"label": "审阅内部版", "hash": "#step=internal"}
    if parent == "generating":
        return {"label": "查看家长版生成", "hash": "#step=parent"}
    if parent in ("none", None):
        return {"label": "生成家长版", "hash": "#step=parent"}
    if parent == "draft":
        return {"label": "确认家长版", "hash": "#step=parent"}
    if parent == "confirmed":
        return {"label": "导出家长版", "hash": "#step=parent"}
    return None


# ---------------------------------------------------------------------------
# 列表 / 新建
# ---------------------------------------------------------------------------
@bp.route("/api/m1/plans")
def api_plans():
    scope = request.args.get("scope", "all")
    if scope not in ("mine", "all"):
        return _err("scope 只能是 mine 或 all", 400)
    rows = pstore.list_plans(_user(), scope=scope)
    student_ids = sorted({int(row["student_id"]) for row in rows
                          if row.get("student_id") is not None})
    teams = collab.team_views(student_ids) if student_ids else {}
    for row in rows:
        team = teams.get(int(row.get("student_id") or 0)) or {}
        row["team"] = {"primaries": team.get("primaries") or [],
                       "co_mentors": team.get("co_mentors") or []}
        row["next"] = _next_action(row)
    return jsonify({"ok": True, "plans": rows})


@bp.route("/api/m1/plans/eligible")
def api_plans_eligible():
    rows, error = _run(lambda: pstore.eligible_students(_user(), request.args.get("source_mode", "report")))
    return error if error else jsonify({"ok": True, "students": rows})


@bp.route("/api/m1/plans", methods=["POST"])
def api_plan_create():
    body = _json_body()
    if body.get("source_mode", "report") == "mentor_inputs":
        return _create_direct(body)
    if body.get("source_mode", "report") != "report":
        return _err("source_mode 只能是 report 或 mentor_inputs", 400)
    try:
        student_id = int(body.get("student_id"))
        prep_id = int(body.get("prep_id"))
        block_no = int(body.get("block_no"))
    except (TypeError, ValueError):
        return _err("缺少学生、会前准备或 Block", 400)
    prep = store.get_prep(prep_id)
    if not prep or not store.can_access(_user(), prep):
        return _err("会前准备不存在", 404)
    if int(prep["student_id"]) != student_id:
        return _err("学生与会前准备不匹配", 400)
    report = rstore.get_report(prep_id)
    if not pstore.report_ready(report):
        return _err("会后报告还没有生成 AI 草稿", 409)
    grade = body.get("wb_grade")
    if grade in (None, ""):
        grade = pstore.parse_wb_grade(prep.get("grade") or "")
    else:
        try:
            grade = int(grade)
        except (TypeError, ValueError):
            return _err("参考年级需在 G5–G9 之间", 400)
    plan, error = _run(lambda: pstore.create_plan(
        student_id, prep_id=prep_id, report_id=report["id"],
        report_version_id=report.get("current_version_id"),
        mentor_user_id=prep.get("mentor_user_id") or _user_id(),
        block_no=block_no,
        period_start=str(body.get("period_start") or ""),
        period_end=str(body.get("period_end") or ""),
        credits=str(body.get("credits") or ""),
        sessions=3, wb_grade=grade, created_by=_user_id()))
    if error:
        return error
    _audit("m1.plan_create", plan)
    return jsonify({"ok": True, "plan": plan}), 201


# ---------------------------------------------------------------------------
# 详情 / 表头
# ---------------------------------------------------------------------------
@bp.route("/api/m1/plans/<int:plan_id>")
def api_plan_detail(plan_id: int):
    plan, error = _plan_or_error(plan_id)
    if error:
        return error
    return jsonify({"ok": True, **_payload(plan)})


@bp.route("/api/m1/plans/<int:plan_id>", methods=["PATCH"])
def api_plan_header(plan_id: int):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    body = _json_body()
    rev = _rev(body)
    if rev is None:
        return _err("缺少 rev", 400)
    fields = {key: body[key] for key in ("block_no", "period_start", "period_end", "credits")
              if key in body}
    if not fields:
        return _err("没有要更新的字段", 400)
    if "block_no" in fields:
        try:
            fields["block_no"] = int(fields["block_no"])
        except (TypeError, ValueError):
            return _err("Block 编号需为 1 或以上", 400)
    updated, error = _legacy_section(plan, "header", fields, body)
    if error:
        return error
    return jsonify({"ok": True, "plan": updated})


# ---------------------------------------------------------------------------
# 目标 / Development Inputs / 个性化需求
# ---------------------------------------------------------------------------
@bp.route("/api/m1/plans/<int:plan_id>/goals", methods=["PUT"])
def api_plan_goals(plan_id: int):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    body = _json_body()
    rev = _rev(body)
    if rev is None:
        return _err("缺少 rev", 400)
    updated, error = _legacy_section(plan, "goals", {"goals": body.get("goals")}, body)
    if error:
        return error
    return jsonify({"ok": True, "plan": updated, "goals": _goal_rows(updated)})


@bp.route("/api/m1/plans/<int:plan_id>/inputs", methods=["PUT"])
def api_plan_inputs(plan_id: int):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    body = _json_body()
    rev = _rev(body)
    if rev is None:
        return _err("缺少 rev", 400)
    values = body.get("inputs")
    if not isinstance(values, dict):
        values = {key: body[key] for key in ("strengths", "needs", "context", "interests")
                  if key in body}
    updated, error = _legacy_section(plan, "inputs", values, body)
    if error:
        return error
    return jsonify({"ok": True, "plan": updated})


@bp.route("/api/m1/plans/<int:plan_id>/personal", methods=["PUT"])
def api_plan_personal(plan_id: int):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    body = _json_body()
    rev = _rev(body)
    if rev is None:
        return _err("缺少 rev", 400)
    notes = body.get("notes")
    summary = body.get("summary")
    if isinstance(body.get("personal"), dict):
        if notes is None:
            notes = body["personal"].get("notes")
        if summary is None:
            summary = body["personal"].get("summary")
    if notes is None and summary is None:
        return _err("缺少 notes", 400)
    if summary is not None and not isinstance(summary, str):
        return _err("summary 必须是文字", 400)
    patch = {}
    if notes is not None:
        patch["notes"] = notes
    if summary is not None:
        patch["summary"] = summary
    updated, error = _legacy_section(plan, "personal", patch, body)
    if error:
        return error
    return jsonify({"ok": True, "plan": updated})


# ---------------------------------------------------------------------------
# 文件
# ---------------------------------------------------------------------------
@bp.route("/api/m1/plans/<int:plan_id>/files", methods=["POST"])
def api_plan_file_upload(plan_id: int):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return _err("请选择文件", 400)
    filename = upload.filename
    ext = sources._safe_extension(filename)
    if ext not in _ALLOWED_EXT:
        return _err("只支持 .txt / .docx / .pdf", 400)
    data = upload.read()
    if len(data) > _MAX_UPLOAD:
        return _err("文件不能超过 10 MB", 400)
    try:
        text = extract_upload(filename, data)
    except UploadError as exc:
        return _err(exc.message, exc.status_code)
    target_dir = pstore.plan_upload_dir(plan["id"])
    sources._assert_outside_static(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    stored = target_dir / ("%s%s" % (uuid.uuid4().hex[:16], ext))
    stored.write_bytes(data)
    saved = pstore.add_file(plan["id"], filename=filename, stored_path=str(stored),
                            text=text, text_status=sources._text_status(text),
                            size=len(data), created_by=_user_id())
    _audit("plan.file", plan, file_id=saved["id"], filename=filename)
    public = {key: saved[key] for key in ("id", "filename", "text_status", "size",
                                          "created_at")}
    return jsonify({"ok": True, "file": public}), 201


@bp.route("/api/m1/plan-files/<int:file_id>", methods=["DELETE"])
def api_plan_file_delete(file_id: int):
    info = pstore.get_file(file_id)
    if not info:
        return _err("文件不存在", 404)
    plan, error = _plan_or_error(info["plan_id"], edit=True)
    if error:
        return error
    removed = pstore.delete_file(file_id)
    _remove_stored_file(removed.get("stored_path"), plan["id"])
    _audit("plan.file_delete", plan, file_id=file_id)
    return jsonify({"ok": True})


def _remove_stored_file(stored_path, plan_id) -> None:
    if not stored_path:
        return
    try:
        Path(stored_path).resolve().relative_to(pstore.plan_upload_dir(plan_id).resolve())
    except (ValueError, OSError):
        return
    try:
        Path(stored_path).unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 内部版
# ---------------------------------------------------------------------------
@bp.route("/api/m1/plans/<int:plan_id>/internal", methods=["PUT"])
def api_plan_internal_save(plan_id: int):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    body = _json_body()
    rev = _rev(body)
    if rev is None:
        return _err("缺少 rev", 400)
    doc = body.get("doc")
    if doc is None:
        return _err("缺少内部版内容", 400)
    doc = pstore.normalize_doc_shape(doc)
    try:
        pstore.validate_internal_doc(plan, doc)
        from m1.plan_quality import validate_additions
        validate_additions(doc)
    except ValueError as exc:
        return _err(str(exc), 400)
    checks = _internal_checks(plan, doc)
    result, error = _run(lambda: collab.save_document(
        plan["id"], "internal", rev, doc, checks, _user()))
    if error:
        return error
    return jsonify({"ok": True, "rev": result["rev"],
                    "version_id": result["version_id"], "checks": checks,
                    "plan": pstore.get_plan(plan["id"])})


@bp.route("/api/m1/plans/<int:plan_id>/approve", methods=["POST"])
def api_plan_approve(plan_id: int):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    if not pstore.can_approve_plan(_user(), plan):
        return _err("只有负责导师或管理员可以批准内部版", 403)
    body = _json_body()
    rev = _rev(body)
    if rev is None:
        return _err("缺少 rev", 400)
    result, error = _run(lambda: collab.approve_plan(
        plan["id"], _user(), rev, version_id=body.get("version_id")))
    if error:
        return error
    updated = result["plan"]
    return jsonify({"ok": True, "plan": updated,
                    "document_version": result["document_version"]})


@bp.route("/api/m1/plans/<int:plan_id>/reopen", methods=["POST"])
def api_plan_reopen(plan_id: int):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    if not pstore.can_approve_plan(_user(), plan):
        return _err("只有负责导师或管理员可以重新打开内部版", 403)
    body = _json_body()
    rev = _rev(body)
    if rev is None:
        return _err("缺少 rev", 400)
    result, error = _run(lambda: collab.reopen_plan(plan["id"], _user(), rev))
    if error:
        return error
    updated = result["plan"]
    return jsonify({"ok": True, "plan": updated,
                    "document_version": result["document_version"]})


# ---------------------------------------------------------------------------
# 家长版
# ---------------------------------------------------------------------------
@bp.route("/api/m1/plans/<int:plan_id>/parent", methods=["PUT"])
def api_plan_parent_save(plan_id: int):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    body = _json_body()
    rev = _rev(body)
    if rev is None:
        return _err("缺少 rev", 400)
    doc = body.get("doc")
    if doc is None:
        return _err("缺少家长版内容", 400)
    try:
        pstore.validate_parent_doc(plan, doc)
    except ValueError as exc:
        return _err(str(exc), 400)
    result, error = _run(lambda: collab.save_document(
        plan["id"], "parent", rev, doc, None, _user()))
    if error:
        return error
    updated = pstore.get_plan(plan["id"])
    internal = pstore.current_version(plan["id"], "internal")
    blocking = _parent_blocking(updated, doc,
                                (internal or {}).get("doc") or {})
    return jsonify({"ok": True, "rev": result["rev"],
                    "version_id": result["version_id"],
                    "blocking": blocking,
                    "stale": bool(updated.get("parent_stale")),
                    "plan": updated})


@bp.route("/api/m1/plans/<int:plan_id>/parent/confirm", methods=["POST"])
def api_plan_parent_confirm(plan_id: int):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    if not pstore.can_approve_plan(_user(), plan):
        return _err("只有负责导师或管理员可以确认家长版", 403)
    body = _json_body()
    rev = _rev(body)
    if rev is None:
        return _err("缺少 rev", 400)
    parent = pstore.current_version(plan["id"], "parent")
    internal = pstore.current_version(plan["id"], "internal")
    blocking = _parent_blocking(plan, parent.get("doc") if parent else None,
                                internal.get("doc") if internal else None)
    if blocking:
        return _err("还有 %d 项需要处理" % len(blocking), 409, blocking=blocking)
    result, error = _run(lambda: collab.confirm_parent_action(plan["id"], _user(), rev))
    if error:
        return error
    return jsonify({"ok": True, "plan": result["plan"]})


@bp.route("/api/m1/plans/<int:plan_id>/parent/export", methods=["POST"])
def api_plan_parent_export(plan_id: int):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    if not pstore.can_approve_plan(_user(), plan):
        return _err("只有负责导师或管理员可以导出家长版", 403)
    if plan.get("parent_status") not in ("confirmed", "exported"):
        return _err("请先确认家长版", 409)
    body = _json_body()
    rev = _rev(body)
    if rev is None:
        return _err("缺少 rev", 400)
    parent = pstore.current_version(plan["id"], "parent")
    internal = pstore.current_version(plan["id"], "internal")
    blocking = _parent_blocking(plan, parent.get("doc") if parent else None,
                                internal.get("doc") if internal else None)
    if blocking:
        return _err("还有 %d 项需要处理" % len(blocking), 409, blocking=blocking)
    result, error = _run(lambda: collab.export_parent_action(plan["id"], _user(), rev))
    if error:
        return error
    return jsonify({"ok": True, "plan": result["plan"],
                    "print_url": "/m1/plans/%d/parent/print" % plan["id"]})


# ---------------------------------------------------------------------------
# 版本
# ---------------------------------------------------------------------------
@bp.route("/api/m1/plans/<int:plan_id>/versions")
def api_plan_versions(plan_id: int):
    plan, error = _plan_or_error(plan_id)
    if error:
        return error
    return jsonify({"ok": True, "versions": pstore.list_versions(plan["id"])})


# ---------------------------------------------------------------------------
# AI 生成（DP3）
# ---------------------------------------------------------------------------
def _editable_plan(plan_id: int):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return None, error
    if plan.get('source_mode') == 'mentor_inputs':
        rev = _json_body().get('rev')
        if type(rev) is not int:
            return None, _err('缺少整数 rev', 400)
        if rev != plan['rev']:
            return None, _err('计划已在别处更新，请刷新后重试', 409, rev=plan['rev'])
    if plan["status"] in ("approved", "generating"):
        return None, _err("内部版已批准或正在生成，请先重新打开", 409)
    return plan, None


def _start_job(plan: dict, kind: str, *, part: str | None = None, **kwargs):
    from m1 import plan_jobs

    if kind in ('plan_brief', 'plan_inputs', 'plan_goal', 'plan_personal'):
        kwargs['expected_rev'] = plan['rev']
    scope = "plan_" + part if part else None
    reserved_id = None
    previous = None
    if scope:
        try:
            reserved_id, previous = job_attempts.reserve(
                scope, plan["id"], lambda: pstore.begin_generation(plan["id"], part),
                plan_id=plan["id"], kind=kind)
        except (pstore.StatusError, job_attempts.AttemptConflict) as exc:
            return _err(str(exc), 409)
    try:
        job_id = plan_jobs.launch_job(
            plan["id"], kind, actor_id=_user_id(), previous_status=previous,
            job_id=reserved_id, attempt_scope=scope, **kwargs)
    except (OSError, plan_jobs.JobLaunchError):
        if reserved_id:
            job_attempts.cancel(scope, plan["id"], reserved_id)
        return _err("任务未能启动，请重试。", 503)
    return jsonify({"ok": True, "job_id": job_id}), 202


@bp.route("/api/m1/plans/<int:plan_id>/read-report", methods=["POST"])
def api_plan_read_report(plan_id: int):
    plan, error = _editable_plan(plan_id)
    if error:
        return error
    return _start_job(plan, "plan_inputs")


@bp.route("/api/m1/plans/<int:plan_id>/goals/<code>/fill", methods=["POST"])
def api_plan_goal_fill(plan_id: int, code: str):
    plan, error = _editable_plan(plan_id)
    if error:
        return error
    if not any(item.get("code") == code for item in plan.get("goals") or []):
        return _err("没有这项发展目标", 404)
    return _start_job(plan, "plan_goal", code=code)


@bp.route("/api/m1/plans/<int:plan_id>/personal/summary", methods=["POST"])
def api_plan_personal_summary(plan_id: int):
    plan, error = _editable_plan(plan_id)
    if error:
        return error
    notes = str((plan.get("personal") or {}).get("notes") or "").strip()
    if not notes and not pstore.list_files(plan["id"]):
        return _err("请先填写个性化需求或上传会议记录", 400)
    return _start_job(plan, "plan_personal")


@bp.route("/api/m1/plans/<int:plan_id>/generate", methods=["POST"])
def api_plan_generate(plan_id: int):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    body = _json_body()
    if plan.get('source_mode') == 'mentor_inputs':
        if type(body.get('rev')) is not int:
            return _err('缺少整数 rev', 400)
        if body['rev'] != plan['rev']:
            return _err('计划已在别处更新，请刷新后重试', 409, rev=plan['rev'])
    use_old_report = bool(body.get("use_old_report"))
    blockers = pstore.generate_blockers(plan, use_old_report=use_old_report)
    if blockers:
        return _err(blockers[0], 409, blockers=blockers, next_action=pstore.next_action(plan))
    return _start_job(plan, "plan_generate", part="internal",
                      use_old_report=use_old_report)


@bp.route("/api/m1/plans/<int:plan_id>/regenerate", methods=["POST"])
def api_plan_regenerate(plan_id: int):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    if plan["status"] != "review":
        return _err("只有待批准的内部版可以单独重新生成", 409)
    body = _json_body()
    section = body.get("section")
    if isinstance(section, str) and section.strip() in ("overview", "1", "2", "3"):
        section = "overview" if section.strip() == "overview" else int(section.strip())
    if section not in ("overview", 1, 2, 3):
        return _err("section 只能是 overview、1、2 或 3", 400)
    return _start_job(plan, "plan_regen", part="internal", section=section)


@bp.route("/api/m1/plans/<int:plan_id>/parent/generate", methods=["POST"])
def api_plan_parent_generate(plan_id: int):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    return _start_job(plan, "plan_parent", part="parent")


# ---------------------------------------------------------------------------
# DP5 页面：① 资料与目标 / ② 内部版审阅批准 / 内部版打印
# ---------------------------------------------------------------------------
_GEN_NOTES = {
    "read": "规则读取",
    "wb": "代码按 R4 能力 × 年级查表，最多 2 节",
    "overview": "AI",
    "sessions": "AI · 活动全部为这个学生设计，不照搬教材",
    "checks": "WB 课名页码对得上 · 与教材原文不雷同 · 第 3 节有阶段回顾",
}


def _day(value, with_year: bool = False) -> str:
    text = str(value or "")[:10]
    parts = text.split("-")
    if len(parts) != 3:
        return ""
    return text if with_year else "%s-%s" % (parts[1], parts[2])


def _period(plan: dict) -> str:
    start = _day(plan.get("period_start"), True)
    end = _day(plan.get("period_end"))
    if not start:
        return "—"
    return "%s 至 %s" % (start, end or "—")


def _user_name(user_id) -> str:
    if not user_id:
        return ""
    try:
        from sqlalchemy.orm import Session

        import db as _db
        with Session(pstore._engine()) as sess:
            row = sess.get(_db.User, int(user_id))
            if row is None:
                return ""
            return (row.display_name or row.advisor_name
                    or row.username or "")
    except Exception:
        return ""


def _goal_display(plan: dict):
    rows = _goal_rows(plan)
    for row in rows:
        row["goal_text"] = ((row.get("goal") or {}).get("text") or "")
        row["start"] = row.get("start") or {"text": "", "src": "ai"}
        row["expected"] = row.get("expected") or {"text": "", "src": "ai"}
    return rows


def _read_goal_chips(plan: dict):
    used = {item.get("code") for item in plan.get("goals") or []}
    version = None
    if plan.get("report_version_id"):
        try:
            version = rstore.get_version(int(plan["report_version_id"]))
        except Exception:
            version = None
    rows = ((version or {}).get("doc") or {}).get("plan") or []
    out, seen = [], set()
    for row in rows:
        if len(out) >= 3:
            break
        code = row.get("ability") if isinstance(row, dict) else ""
        if not code or code in seen:
            continue
        try:
            name = kb.ability(code).get("name", "")
        except KeyError:
            name = ""
        out.append({"code": code, "name": name, "used": code in used})
        seen.add(code)
    return out


def _field_text(value) -> str:
    if isinstance(value, dict):
        return str(value.get("text") or "")
    return str(value or "")


def _practice_index(internal_doc):
    """内部版实践 id → 所在节次与关联能力。"""
    out = {}
    for index, session in enumerate((internal_doc or {}).get("sessions") or []):
        for practice in session.get("practice") or []:
            ref = practice.get("id")
            if ref:
                out[ref] = {"n": session.get("n") or index + 1,
                            "code": practice.get("code") or ""}
    return out


def _parent_view(plan: dict, doc, internal_doc) -> dict:
    """把家长版 doc 摊平成模板直接可用的文字。"""
    doc = doc if isinstance(doc, dict) else {}
    names = {row["code"]: row.get("name", "") for row in _goal_rows(plan)}
    goals = []
    for item in doc.get("goals") or []:
        if not isinstance(item, dict):
            continue
        code = item.get("code") or ""
        goals.append({"code": code, "name": names.get(code, ""),
                      "text": _field_text(item.get("text"))})
    sessions = []
    for index, item in enumerate(doc.get("sessions") or []):
        if not isinstance(item, dict):
            continue
        sessions.append({"n": item.get("n") or index + 1,
                         "title": _field_text(item.get("title")),
                         "summary": _field_text(item.get("summary"))})
    lookup = _practice_index(internal_doc)
    picked = doc.get("practice") if isinstance(doc.get("practice"), list) else []
    options, cards = [], []
    for index, item in enumerate(doc.get("practice_options") or []):
        if not isinstance(item, dict):
            continue
        ref = item.get("ref") or ""
        info = lookup.get(ref) or {}
        row = {"index": index, "ref": ref,
               "title": _field_text(item.get("title")),
               "text": _field_text(item.get("text")),
               "frequency": _field_text(item.get("frequency")),
               "platform": item.get("platform") or "",
               "n": info.get("n") or "",
               "code": info.get("code") or ""}
        options.append(row)
        if ref in picked:
            cards.append(row)
    order = {ref: index for index, ref in enumerate(picked)}
    cards.sort(key=lambda row: order.get(row["ref"], 99))
    family = [_field_text(line) for line in doc.get("family") or []]
    seen = doc.get("family_seen") if isinstance(doc.get("family_seen"), list) else []
    family_ack = [{"hash": item["hash"], "seen": bool(item["seen"])}
                  for item in collab.family_state(doc)]
    review = []
    for item in doc.get("review") or []:
        if not isinstance(item, dict):
            continue
        review.append({"label": _field_text(item.get("label")),
                       "text": _field_text(item.get("text"))})
    return {"goals": goals, "sessions": sessions,
            "options": options, "practice_cards": cards, "picked": picked,
            "family": family,
            "family_seen": [bool(seen[i]) if i < len(seen) else False
                            for i in range(len(family))],
            "family_ack": family_ack,
            "review": review,
            "intro": _field_text(doc.get("intro")),
            "transition": _field_text(doc.get("transition"))}


def _parent_hints(plan: dict, doc, internal_doc):
    try:
        from m1 import plan_checks
    except ImportError:
        return []
    fn = getattr(plan_checks, "parent_hints", None)
    return fn(doc, plan, internal_doc) if fn else []


def _doc_cites(doc: dict) -> dict:
    from m1 import wb

    ids = set()
    for session in (doc or {}).get("sessions") or []:
        for activity in session.get("activities") or []:
            src = activity.get("source") or {}
            if src.get("type") == "world_bank" and src.get("wb_id"):
                ids.add(src["wb_id"])
    return {wb_id: wb.cite(wb_id) for wb_id in ids}


def _session_candidates(doc: dict, candidates: dict):
    from m1 import wb

    out = {}
    for index, session in enumerate((doc or {}).get("sessions") or []):
        focus = session.get("focus") or {}
        rows, seen = [], set()
        for code in (focus.get("primary"), focus.get("supporting")):
            for cand in candidates.get(code) or []:
                wb_id = cand.get("wb_id")
                if not wb_id or wb_id in seen:
                    continue
                lesson = wb.lesson(wb_id) or {}
                rows.append({"wb_id": wb_id, "cite": cand.get("cite") or "",
                             "name": lesson.get("name") or ""})
                seen.add(wb_id)
        for activity in session.get("activities") or []:
            src = activity.get("source") or {}
            wb_id = src.get("wb_id")
            if src.get("type") == "world_bank" and wb_id and wb_id not in seen:
                rows.append({"wb_id": wb_id, "cite": wb.cite(wb_id), "name": ""})
                seen.add(wb_id)
        out[index] = rows
    return out


def _wb_groups(goals, candidates: dict):
    if not pstore._wb_installed():
        return []
    from m1 import wb

    groups = []
    for goal in goals:
        if not goal.get("locked"):
            continue
        rows = []
        for cand in candidates.get(goal["code"]) or []:
            lesson = wb.lesson(cand.get("wb_id") or "") or {}
            rows.append({"wb_id": cand.get("wb_id"), "name": lesson.get("name") or "",
                         "cite": cand.get("cite") or "", "match": cand.get("match") or "",
                         "limit": cand.get("limit") or ""})
        groups.append({"code": goal["code"], "name": goal.get("name", ""), "rows": rows})
    return groups


def _gen_steps():
    from m1 import plan_jobs

    return [{"id": key, "label": label, "note": _GEN_NOTES.get(key, "")}
            for key, label in plan_jobs.STEP_DEFS["plan_generate"]]


def _current_job_id(plan: dict):
    if plan["parent_status"] == "generating":
        return job_attempts.current("plan_parent", plan["id"])
    if plan["status"] == "generating":
        return job_attempts.current("plan_internal", plan["id"])
    return None


def _default_step(plan: dict) -> str:
    if plan["status"] in ("inputs", "generating"):
        return "inputs"
    if plan["status"] in ("review", "approved") and plan.get("parent_status") == "none":
        return "internal"
    return "parent"


def _state_label(plan: dict, internal) -> str:
    status = plan["status"]
    if status == "inputs":
        return "资料与目标"
    if status == "generating":
        return "正在生成"
    if status == "approved":
        return "内部版 · 已批准"
    if internal and internal.get("kind") == "ai_draft":
        return "内部版 · AI 初稿"
    return "内部版 · 待批准"


def _plan_page_context(plan: dict) -> dict:
    if plan["status"] == "generating" or plan["parent_status"] == "generating":
        scope = "plan_parent" if plan["parent_status"] == "generating" else "plan_internal"
        job_attempts.current(scope, plan["id"])
        plan = pstore.get_plan(plan["id"]) or plan
    user = _user()
    can_edit = pstore.can_edit_plan(user, plan)
    step1 = can_edit and plan["status"] in ("inputs", "review")
    step2 = can_edit and plan["status"] == "review"
    internal = pstore.current_version(plan["id"], "internal")
    checks = list((internal or {}).get("checks") or [])
    review_checks = [item for item in checks if item.get("level") == "review"]
    hint_checks = [item for item in checks if item.get("level") == "hint"]
    report = pstore.report_state(plan)
    goals = _goal_display(plan)
    candidates = _wb_candidates(plan)
    doc = (internal or {}).get("doc") or {}
    student = next((row for row in store.list_students(user)
                    if row["id"] == plan.get("student_id")), {})
    personal = plan.get("personal") or {}
    session_candidates = _session_candidates(doc, candidates)
    blockers = pstore.generate_blockers(plan)
    job_id = _current_job_id(plan)
    kb_data = kb.load_kb()
    parent = pstore.current_version(plan["id"], "parent")
    parent_doc = (parent or {}).get("doc") or {}
    parent_status = plan.get("parent_status") or "none"
    parent_view = _parent_view(plan, parent_doc, doc)
    parent_blocking = _parent_blocking(plan, parent_doc, doc) if parent else []
    parent_editable = bool(can_edit and parent and
                           parent_status in ("draft", "confirmed", "exported"))
    page_state = {
        "planId": plan["id"], "status": plan["status"], "rev": plan["rev"],
        "userId": user.get("user_id"), "userName": _user_name(user.get("user_id")),
        "canEdit": can_edit, "step1": step1, "step2": step2,
        "canApprove": pstore.can_approve_plan(user, plan),
        "canManageTeam": pstore.can_manage_team(user),
        "collaboration": collab.plan_summary(plan, user),
        "defaultStep": _default_step(plan),
        "jobId": job_id,
        "doc": doc, "checks": checks, "reportFresh": report["fresh"],
        "blockers": blockers,
        "parent": {"doc": parent_doc, "status": parent_status,
                   "stale": bool(plan.get("parent_stale")),
                   "editable": parent_editable,
                   "family": collab.family_state(parent_doc)},
        "parentBlocking": parent_blocking,
        "sessionCandidates": session_candidates,
        "goals": [{"code": g["code"], "locked": bool(g.get("locked")),
                   "goal": {"text": g["goal_text"],
                            "src": (g.get("goal") or {}).get("src") or "ai"},
                   "start": g["start"], "expected": g["expected"]} for g in goals],
    }
    return {
        "plan": plan,
        "goals": goals,
        "read_goals": _read_goal_chips(plan),
        "abilities": kb_data["abilities"],
        "dims": kb_data["dims"],
        "can_edit": can_edit,
        "step1_editable": step1,
        "step2_editable": step2,
        "internal_version": internal,
        "review_checks": review_checks,
        "hint_checks": hint_checks,
        "blockers": blockers,
        "report": report,
        "y4_date": _day(student.get("y4_date")),
        "grade_text": student.get("grade") or "",
        "personal": personal,
        "files": pstore.list_files(plan["id"]),
        "wb_installed": pstore._wb_installed(),
        "wb_groups": _wb_groups(goals, candidates),
        "session_candidates": session_candidates,
        "source_labels": plan_kb.source_labels(),
        "block_review": plan_kb.block_review(),
        "cites": _doc_cites(doc),
        "period": _period(plan),
        "gen_steps": _gen_steps(),
        "default_step": _default_step(plan),
        "state_label": _state_label(plan, internal),
        "job_id": job_id,
        "approved_at": _day(plan.get("approved_at"), True),
        "approver_name": _user_name(plan.get("approved_by")),
        "has_parent_step": True,
        "parent": parent,
        "parent_status": parent_status,
        "parent_stale": bool(plan.get("parent_stale")),
        "parent_editable": parent_editable,
        "parent_view": parent_view,
        "parent_blocking": parent_blocking,
        "parent_hints": _parent_hints(plan, parent_doc, doc),
        "parent_fixed": plan_kb.parent(),
        "parent_limits": plan_kb.PARENT_LIMITS,
        "parent_labels": pstore.PARENT_LABELS,
        "internal_changed": _day((internal or {}).get("created_at")),
        "page_state": page_state,
    }


@bp.route("/m1/plans/<int:plan_id>")
def page_plan(plan_id: int):
    plan = pstore.get_plan(plan_id)
    if not plan or not pstore.can_view_plan(_user(), plan):
        abort(404)
    return _render_page("m1/plan.html", nav_active="plans",
                        **_plan_page_context(plan))


def _print_error(plan_id: int, status: int, message: str) -> Response:
    """打印页是顶层导航，错误也要给出可阅读的 HTML 而不是 JSON。"""
    body = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>无法导出本节教案</title></head>'
        '<body style="margin:0;padding:48px 24px;font:15px/1.8 '
        '-apple-system,BlinkMacSystemFont,\'PingFang SC\',sans-serif;'
        'color:#0f172a;background:#f7f8fa">'
        '<div style="max-width:560px;margin:0 auto;background:#fff;'
        'border:1px solid #e5e7eb;border-radius:10px;padding:28px">'
        '<h1 style="font-size:17px;margin:0 0 10px">无法导出本节教案</h1>'
        '<p id="print-error" style="margin:0 0 18px;color:#334155">%s</p>'
        '<p style="margin:0"><a href="/m1/plans/%d" '
        'style="color:#b33a3a;text-decoration:none">返回计划</a></p>'
        '</div></body></html>'
    ) % (html.escape(message), int(plan_id))
    return Response(body, status=status, content_type="text/html; charset=utf-8")


def _session_by_no(doc: dict, session_no: int):
    for index, session in enumerate((doc or {}).get("sessions") or []):
        if not isinstance(session, dict):
            continue
        try:
            n = int(session.get("n"))
        except (TypeError, ValueError):
            n = index + 1
        if n == session_no:
            return session
    return None


def _session_print_duration(plan: dict, session_no: int) -> int:
    durations = plan.get("session_durations") or []
    value = durations[session_no - 1] if len(durations) >= session_no else 60
    try:
        return int(value)
    except (TypeError, ValueError):
        return 60


def _session_goal_projection(plan: dict, session: dict):
    """只投影本节 primary/supporting 引用的已确认目标。

    找不到引用时返回原代码用于诚实提示；绝不回退到其他目标。
    """
    focus = session.get("focus") or {}
    codes = []
    for code in (focus.get("primary"), focus.get("supporting")):
        code = str(code or "").strip()
        if code and code not in codes:
            codes.append(code)
    by_code = {row.get("code"): row for row in _goal_display(plan)}
    goals = [by_code[code] for code in codes if code in by_code]
    missing = [code for code in codes if code not in by_code]
    return goals, missing, bool(codes)


@bp.route("/m1/plans/<int:plan_id>/sessions/<int:session_no>/print")
def page_plan_session_print(plan_id: int, session_no: int):
    """导出单节内部教案（浏览器打印 / 另存为 PDF）。

    这是只读动作，不新增编辑或最终批准权限；权限与整份内部版打印一致。
    可选前置条件：``?expected_rev=<int>&version_id=<int>``（必须同时提供）。
    ``expected_rev`` 覆盖当前版本的就地编辑，``version_id`` 覆盖当前版本切换；
    两者都在 ``internal_print_snapshot`` 的同一个 SQLite 读事务里核对。
    """
    if session_no not in (1, 2, 3):
        abort(404)
    raw_rev = request.args.get("expected_rev")
    raw_version = request.args.get("version_id")
    if (raw_rev is None) != (raw_version is None):
        return _print_error(plan_id, 400, "打印参数不完整，请返回重新预览。")
    expected_rev = expected_version = None
    if raw_rev is not None:
        try:
            expected_rev = int(raw_rev)
            expected_version = int(raw_version)
        except (TypeError, ValueError):
            return _print_error(plan_id, 400, "打印参数格式不正确，请返回重新预览。")

    snapshot = pstore.internal_print_snapshot(plan_id)
    if not snapshot:
        abort(404)
    plan = snapshot["plan"]
    if not pstore.can_view_plan(_user(), plan):
        abort(404)
    internal = snapshot.get("internal")
    if not internal:
        abort(404)
    if plan.get("status") == "generating":
        return _print_error(plan_id, 409, "内部版正在更新，完成后可重新导出本节 PDF。")
    if expected_rev is not None and (
            expected_rev != int(plan.get("rev") or 0)
            or expected_version != int(internal.get("id") or 0)):
        return _print_error(plan_id, 409, "计划已有更新，请返回后重新预览。")

    doc = internal.get("doc") or {}
    session = _session_by_no(doc, session_no)
    if session is None:
        abort(404)
    goals, missing_codes, has_reference = _session_goal_projection(plan, session)
    return _render_page(
        "m1/plan_session_print.html",
        plan=plan,
        session=session,
        session_no=session_no,
        session_duration=_session_print_duration(plan, session_no),
        session_goals=goals,
        missing_goal_codes=missing_codes,
        has_goal_reference=has_reference,
        show_session_goals=True,
        grade_text=plan.get("grade") or "",
        period=_period(plan),
        source_labels=plan_kb.source_labels(),
        block_review=plan_kb.block_review(),
        cites=_doc_cites({"sessions": [session]}),
        auto_print=request.args.get("print") == "1",
    )


@bp.route("/m1/plans/<int:plan_id>/print")
def page_plan_print(plan_id: int):
    plan = pstore.get_plan(plan_id)
    if not plan or not pstore.can_view_plan(_user(), plan):
        abort(404)
    internal = pstore.current_version(plan["id"], "internal")
    if not internal:
        abort(404)
    ctx = _plan_page_context(plan)
    return _render_page("m1/plan_print.html", internal=internal,
                        auto_print=request.args.get("print") == "1", **ctx)


@bp.route("/m1/plans/<int:plan_id>/parent/print")
def page_plan_parent_print(plan_id: int):
    plan = pstore.get_plan(plan_id)
    if not plan or not pstore.can_view_plan(_user(), plan):
        abort(404)
    parent = pstore.current_version(plan["id"], "parent")
    if not parent:
        abort(404)
    ctx = _plan_page_context(plan)
    wm = (ctx["parent_status"] not in ("confirmed", "exported")
          or ctx["parent_stale"])
    return _render_page("m1/plan_parent_print.html", wm=wm,
                        auto_print=request.args.get("print") == "1" and not wm,
                        **ctx)



def _create_direct(body):
    try:
        if type(body.get('student_id')) is not int or type(body.get('block_no')) is not int:
            raise ValueError()
        student_id = body['student_id']
        mentor_id = body.get('mentor_user_id', _user_id())
        if type(mentor_id) is not int:
            raise ValueError()
    except (ValueError, TypeError):
        return _err('学生、Block 和负责导师需要整数', 400)
    if not store.can_read_student(_user(), student_id):
        return _err('学生不存在', 404)
    if mentor_id != _user_id() and not store.is_m1_admin(_user()):
        return _err('只有管理员可以指定其他负责导师', 403)
    if any(body.get(k) is not None for k in ('prep_id', 'report_id', 'report_version_id')):
        return _err('直接计划不能关联会前准备或报告', 400)
    plan, error = _run(lambda: pstore.create_plan(
        student_id, source_mode='mentor_inputs', mentor_user_id=mentor_id,
        block_no=body['block_no'], period_start=body.get('period_start', ''),
        period_end=body.get('period_end', ''), credits=body.get('credits', ''),
        sessions=body.get('sessions', 3), wb_grade=body.get('wb_grade'), created_by=_user_id()))
    if error:
        return error
    _audit('m1.plan_create', plan, source_mode='mentor_inputs')
    return jsonify({'ok': True, 'plan': plan, 'next_action': pstore.next_action(plan)}), 201


@bp.route('/api/m1/plans/<int:plan_id>/brief', methods=['PUT'])
@bp.route('/api/m1/plans/<int:plan_id>/brief/confirm', methods=['POST'])
@bp.route('/api/m1/plans/<int:plan_id>/durations', methods=['PUT'])
def api_plan_context_save(plan_id):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    body = _json_body()
    if type(body.get('rev')) is not int:
        return _err('缺少整数 rev', 400)
    if request.path.endswith('/confirm'):
        result, error = _run(lambda: collab.confirm_brief_action(
            plan_id, _user(), body['rev']))
        saved = (result or {}).get('plan')
    elif request.path.endswith('/durations'):
        saved, error = _legacy_section(
            plan, "durations", {"session_durations": body.get('session_durations')}, body)
    else:
        saved, error = _legacy_section(
            plan, "brief", {"teaching_brief": body.get('teaching_brief')}, body)
    if error:
        return error
    return jsonify({'ok': True, 'plan': saved, 'next_action': pstore.next_action(saved)})


@bp.route('/api/m1/plans/<int:plan_id>/extract-inputs', methods=['POST'])
@bp.route('/api/m1/plans/<int:plan_id>/brief/extract', methods=['POST'])
def api_plan_extract_inputs(plan_id):
    plan, error = _editable_plan(plan_id)
    if error:
        return error
    body = _json_body()
    if type(body.get('rev')) is not int:
        return _err('缺少整数 rev', 400)
    if body['rev'] != plan['rev']:
        return _err('计划已在别处更新，请刷新后重试', 409, rev=plan['rev'])
    return _start_job(plan, 'plan_brief')


@bp.route('/api/m1/plans/<int:plan_id>/activity-proposals', methods=['POST'])
def api_activity_proposal_create(plan_id):
    from m1 import plan_activity_proposals as proposals
    from m1.plan_quality import require_teachable_budget
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    body = _json_body()
    rev, version_id, activity_id = body.get('rev'), body.get('source_version_id'), body.get('activity_id')
    _, error = _run(lambda: proposals.source(plan_id, rev, version_id, activity_id))
    if error:
        return error
    _, error = _run(lambda: require_teachable_budget(plan))
    if error:
        return error
    blockers = pstore.generate_blockers(plan)
    if blockers:
        return _err('；'.join(blockers), 409)
    return _start_job(plan, 'plan_activity_proposal', expected_rev=rev,
                      source_version_id=version_id, activity_id=activity_id)


@bp.route('/api/m1/plans/<int:plan_id>/activity-proposals/<proposal_id>', methods=['GET'])
def api_activity_proposal_get(plan_id, proposal_id):
    from m1 import plan_activity_proposals as proposals
    _, error = _plan_or_error(plan_id)
    if error:
        return error
    result, error = _run(lambda: proposals.get(plan_id, proposal_id))
    if error:
        return error
    return jsonify(ok=True, proposal=result)


@bp.route('/api/m1/plans/<int:plan_id>/activity-proposals/<proposal_id>/accept', methods=['POST'])
def api_activity_proposal_accept(plan_id, proposal_id):
    from m1 import plan_activity_proposals as proposals
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    body = _json_body()
    if type(body.get('rev')) is not int or type(body.get('source_version_id')) is not int or not isinstance(body.get('activity_id'), str):
        return _err('需要整数rev/source_version_id和活动编号', 400)
    result, error = _run(lambda: proposals.accept(plan_id, proposal_id, body['rev'],
        body['source_version_id'], body['activity_id'], actor_id=_user_id()))
    if error:
        return error
    return jsonify(ok=True, plan=pstore.get_plan(plan_id), **result)


@bp.route('/api/m1/plans/<int:plan_id>/activity-proposals/<proposal_id>/cancel', methods=['POST'])
def api_activity_proposal_cancel(plan_id, proposal_id):
    from m1 import plan_activity_proposals as proposals
    _, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    result, error = _run(lambda: proposals.cancel(plan_id, proposal_id))
    if error:
        return error
    return jsonify(ok=True, proposal=result)


# ---------------------------------------------------------------------------
# DP13：学生团队、在线状态、编辑租约与分段保存
# ---------------------------------------------------------------------------
@bp.route('/api/m1/plans/<int:plan_id>/collaboration')
def api_plan_collaboration(plan_id):
    plan, error = _plan_or_error(plan_id)
    if error:
        return error
    result, error = _run(lambda: collab.snapshot(plan, _user()))
    if error:
        return error
    return jsonify(ok=True, **result)


@bp.route('/api/m1/plans/<int:plan_id>/presence', methods=['GET', 'POST'])
def api_plan_presence(plan_id):
    plan, error = _plan_or_error(plan_id)
    if error:
        return error
    if request.method == 'GET':
        result, error = _run(lambda: collab.snapshot(plan, _user()))
    else:
        body = _json_body()
        tab_id = body.get('tab_id')
        state = body.get('state', 'viewing')
        if not isinstance(state, str):
            return _err('state 格式不正确', 400)
        result, error = _run(lambda: collab.heartbeat(
            plan['id'], _user(), tab_id, state=state,
            editing_section=str(body.get('editing_section') or '')))
    return error if error else jsonify(ok=True, **result)


@bp.route('/api/m1/plans/<int:plan_id>/leases/acquire', methods=['POST'])
def api_plan_lease_acquire(plan_id):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    body = _json_body()
    result, error = _run(lambda: collab.acquire_lease(
        plan['id'], str(body.get('section') or ''), _user(),
        body.get('tab_id')))
    return error if error else jsonify(ok=True, **result)


@bp.route('/api/m1/plans/<int:plan_id>/leases/renew', methods=['POST'])
def api_plan_lease_renew(plan_id):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    body = _json_body()
    result, error = _run(lambda: collab.renew_lease(
        plan['id'], str(body.get('section') or ''), str(body.get('token') or ''),
        _user(), body.get('tab_id') or ''))
    return error if error else jsonify(ok=True, **result)


@bp.route('/api/m1/plans/<int:plan_id>/leases/release', methods=['POST'])
def api_plan_lease_release(plan_id):
    plan, error = _plan_or_error(plan_id)
    if error:
        return error
    body = _json_body()
    result, error = _run(lambda: collab.release_lease(
        plan['id'], str(body.get('section') or ''), str(body.get('token') or ''),
        _user()))
    return error if error else jsonify(ok=True, **result)


@bp.route('/api/m1/plans/<int:plan_id>/leases/takeover', methods=['POST'])
def api_plan_lease_takeover(plan_id):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    if not pstore.can_manage_team(_user()):
        return _err('只有管理员可以接管编辑权', 403)
    body = _json_body()
    result, error = _run(lambda: collab.takeover_lease(
        plan['id'], str(body.get('section') or ''), _user(),
        body.get('tab_id'), str(body.get('reason') or '')))
    return error if error else jsonify(ok=True, **result)


@bp.route('/api/m1/plans/<int:plan_id>/sections/<section>', methods=['PATCH'])
def api_plan_section_patch(plan_id, section):
    plan, error = _plan_or_error(plan_id, edit=True)
    if error:
        return error
    body = _json_body()
    for key in ('expected_version', 'document_version', 'lease_token',
                'idempotency_key'):
        if body.get(key) is None:
            return _err('缺少 %s' % key, 400)
    if type(body.get('expected_version')) is not int:
        return _err('expected_version 必须是整数', 400)
    if type(body.get('document_version')) is not int:
        return _err('document_version 必须是整数', 400)
    if not isinstance(body.get('lease_token'), str):
        return _err('lease_token 格式不正确', 400)
    if not isinstance(body.get('idempotency_key'), str):
        return _err('idempotency_key 格式不正确', 400)
    result, error = _run(lambda: collab.apply_section(
        plan['id'], section, body.get('patch'), _user(),
        expected_version=body['expected_version'],
        document_version_value=body['document_version'],
        lease_token=body['lease_token'],
        idempotency_key=body['idempotency_key'],
        require_lease=True))
    if error:
        return error
    return jsonify(ok=True, plan=pstore.get_plan(plan['id']), **result)


def _student_or_error(student_id: int):
    student = _db.get_student(student_id)
    if not student:
        return None, _err('学生不存在', 404)
    if not collab.can_view_student_plans(_user(), student_id):
        return None, _err('学生不存在', 404)
    return student, None


@bp.route('/api/m1/students/<int:student_id>/team')
def api_student_team(student_id):
    _, error = _student_or_error(student_id)
    if error:
        return error
    result, error = _run(lambda: collab.team_view(student_id))
    return error if error else jsonify(ok=True, team=result)


@bp.route('/api/m1/students/<int:student_id>/team', methods=['POST'])
def api_student_team_add(student_id):
    if not pstore.can_manage_team(_user()):
        return _err('只有管理员可以管理团队', 403)
    body = _json_body()
    if type(body.get('user_id')) is not int:
        return _err('user_id 必须是整数', 400)
    result, error = _run(lambda: collab.add_team_member(
        student_id, body['user_id'], _user()))
    return error if error else jsonify(ok=True, team=result)


@bp.route('/api/m1/students/<int:student_id>/team/<int:user_id>',
          methods=['DELETE'])
def api_student_team_remove(student_id, user_id):
    if not pstore.can_manage_team(_user()):
        return _err('只有管理员可以管理团队', 403)
    result, error = _run(lambda: collab.remove_team_member(
        student_id, user_id, _user()))
    return error if error else jsonify(ok=True, team=result)
