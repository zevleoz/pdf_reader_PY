"""M1 会后报告蓝图（首次情绪力分析报告）：页面 + ``/api/m1/preps/<id>/report*``。

权限 = M1 权限（``_m1_access_guard`` 与 ``can_access_prep``）再加 ``can_see_full()``：
概要账号 403。只有员工能看，没有学生或家长入口；家庭版是员工下载的 PDF。
"""
from __future__ import annotations

import copy
import uuid
from pathlib import Path

from flask import Blueprint, abort, jsonify, request, session

import app_utils
import m1.report_checks as checks_mod
import m1.report_kb as kb
import m1.report_store as rstore
import m1.report_y4 as report_y4
import m1.sources as sources
import m1.store as store
from app_utils import page_login_required, role_required
from blueprints.m1 import (_WRITE_ROLES, _api_prep, _err, _json_body, _m1_access_guard,
                           _prep_or_404, _render_page, _user)
from growth_talk.upload import UploadError, extract_upload

bp = Blueprint("m1_report", __name__)
bp.before_request(_m1_access_guard)

IMPACT_NOTICE = "综合判断已改。附录已自动更新，请检查 04 和 05 是否需要调整。"
_FIELD_KEYS = ("goal", "mentor", "family", "evidence")


@bp.before_request
def _report_access_guard():
    """概要账号（detail_level != full）看不到会后报告。"""
    if not session.get("user_id"):
        return None
    if app_utils.can_see_full():
        return None
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "当前账号不能查看会后报告"}), 403
    abort(403)


# ---------------------------------------------------------------------------
# 助手
# ---------------------------------------------------------------------------
def _state(prep: dict):
    report = rstore.get_report(prep["id"])
    version = rstore.current_version(report["id"]) if report else None
    return report, version


def _live_checks(report, version):
    if not report or not version:
        return []
    return checks_mod.run_checks(report, version)


def _public_report(report: dict) -> dict:
    out = {k: v for k, v in report.items() if k not in ("transcript_text", "transcript_path")}
    return out


def y4_lines(doc: dict, ratings: dict) -> dict:
    """能力编号 → 家庭版 Y4 行（按 ``Y4_SHOW_VALUES`` 决定是否带数值）。"""
    out = {}
    for _dim, code, row in checks_mod.abilities_in(doc or {}):
        lines = []
        for y4_code in row.get("y4_selected") or []:
            entry = (ratings or {}).get(y4_code)
            if not entry:
                continue
            if report_y4.Y4_SHOW_VALUES:
                lines.append(entry["family_line"])
            else:
                lines.append("%s：%s" % (entry["label"], entry.get("rating") or "未评级"))
        out[code] = lines
    return out


def _inputs(prep: dict) -> dict:
    y4 = {"report_id": None, "date": "", "complete": False}
    try:
        from growth_talk import y4_snapshot
        report = y4_snapshot.latest_complete_y4(prep["student_id"])
        if report is not None:
            day = getattr(report, "report_date", None)
            y4 = {"report_id": report.id,
                  "date": day.isoformat() if hasattr(day, "isoformat") else "",
                  "complete": True}
    except Exception:
        pass
    try:
        ft = sources._first_touch(prep["student_id"])
        first_touch = {"present": bool(ft.get("present")), "date": ft.get("date") or ""}
    except Exception:
        first_touch = {"present": False, "date": ""}
    others = [{"id": s["id"], "label": s["label"], "category": s["category"],
               "filename": s["filename"], "detected_date": s["detected_date"]}
              for s in store.list_sources(prep["id"])]
    return {"y4": y4, "first_touch": first_touch, "others": others}


def _payload(prep: dict) -> dict:
    report, version = _state(prep)
    doc = (version or {}).get("doc") or {}
    mapped = {code: info["indicators"] for code, info in kb.ability_map().items()}
    return {
        "ok": True,
        "report": _public_report(report) if report else {
            "id": None, "prep_id": prep["id"], "status": "draft",
            "label": rstore.STATUS_LABELS["draft"], "rev": 1,
            "transcript_filename": "", "transcript_length": 0, "safety": [],
            "safety_ack_by": None, "safety_ack_at": None,
            "approved_by": None, "approved_at": None},
        "inputs": _inputs(prep),
        "doc": version.get("doc") if version else None,
        "evidence": (version or {}).get("evidence") or [],
        "ratings": (version or {}).get("y4_ratings") or {},
        "mapped": mapped,
        "checks": _live_checks(report, version),
        "appendix": kb.appendix(doc) if doc else [],
        "fixed": kb.fixed(),
        "has_edits": rstore.has_edits(report, version) if report else False,
        "versions": rstore.list_versions(report["id"]) if report else [],
    }


def _need_report(prep: dict):
    """取报告与当前版本；没有返回 ``(None, None, error)``。"""
    report, version = _state(prep)
    if not report or not version:
        return None, None, _err("报告还没有生成", 409)
    return report, version, None


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------
@bp.route("/m1/preps/<int:prep_id>/report")
@page_login_required
def page_report(prep_id: int):
    prep = _prep_or_404(prep_id)
    return _render_page("m1/report_workspace.html", prep=prep, prep_id=prep["id"],
                        ctx={"prep": prep})


@bp.route("/m1/preps/<int:prep_id>/report/print")
@page_login_required
def page_report_print(prep_id: int):
    prep = _prep_or_404(prep_id)
    report, version = _state(prep)
    if not report or not version:
        abort(404)
    doc = version.get("doc") or {}
    draft = report["status"] not in ("approved", "published")
    return _render_page(
        "m1/report_print.html", prep=prep, prep_id=prep["id"], fixed=kb.fixed(), doc=doc,
        appendix=kb.appendix(doc), y4_lines=y4_lines(doc, version.get("y4_ratings")),
        draft=draft, status_label=report["label"])


@bp.route("/m1/preps/<int:prep_id>/report/evidence")
@page_login_required
def page_report_evidence(prep_id: int):
    prep = _prep_or_404(prep_id)
    report, version = _state(prep)
    if not report or not version:
        abort(404)
    return _render_page(
        "m1/report_evidence.html", prep=prep, prep_id=prep["id"], fixed=kb.fixed(),
        report=_public_report(report), doc=version.get("doc") or {},
        evidence=version.get("evidence") or [], ratings=version.get("y4_ratings") or {},
        manifest=version.get("manifest") or {}, checks=_live_checks(report, version))


# ---------------------------------------------------------------------------
# 数据
# ---------------------------------------------------------------------------
@bp.route("/api/m1/preps/<int:prep_id>/report")
@role_required(*_WRITE_ROLES)
def api_report(prep_id: int):
    prep, error = _api_prep(prep_id)
    if error:
        return error
    return jsonify(_payload(prep))


@bp.route("/api/m1/report-statuses")
@role_required(*_WRITE_ROLES)
def api_report_statuses():
    preps = store.list_preps(user=_user())
    found = rstore.list_statuses([p["id"] for p in preps])
    default = {"status": "draft", "label": rstore.STATUS_LABELS["draft"]}
    return jsonify({"statuses": {str(p["id"]): found.get(p["id"], default) for p in preps}})


@bp.route("/api/m1/preps/<int:prep_id>/report/transcript", methods=["POST"])
@role_required(*_WRITE_ROLES)
def api_report_transcript(prep_id: int):
    prep, error = _api_prep(prep_id)
    if error:
        return error
    report = rstore.get_or_create_report(prep_id, _user().get("user_id"))
    if report["status"] == "generating":
        return _err("报告正在生成，请稍后再换逐字稿", 409)

    upload = request.files.get("file")
    stored_path = ""
    filename = ""
    try:
        if upload is not None:
            data = upload.read()
            filename = upload.filename or ""
            if not filename:
                return _err("缺少文件名")
            text = extract_upload(filename, data)
            directory = sources.prep_upload_dir(prep_id)
            sources._assert_outside_static(directory)
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / ("transcript-%s%s" % (uuid.uuid4().hex[:12],
                                                       sources._safe_extension(filename)))
            target.write_bytes(data)
            stored_path = str(target)
        else:
            text = (_json_body().get("text") or "").strip()
            if not text:
                raise UploadError(400, "请先粘贴逐字稿内容")
    except UploadError as exc:
        return _err(exc.message, exc.status)
    except ValueError as exc:
        return _err(str(exc), 422)
    if not (text or "").strip():
        sources.remove_upload_file(stored_path)
        return _err("没有读到文字内容", 422)

    old_path = report.get("transcript_path") or ""
    updated = rstore.set_transcript(report["id"], text=text, filename=filename,
                                    stored_path=stored_path)
    if old_path and old_path != stored_path:
        sources.remove_upload_file(old_path)
    store.audit(_user().get("user_id"), prep["student_id"], "m1.report_transcript",
                {"prep_id": prep_id, "filename": filename, "length": len(text)})
    return jsonify({"ok": True, "report": _public_report(updated)})


@bp.route("/api/m1/preps/<int:prep_id>/report/generate", methods=["POST"])
@role_required(*_WRITE_ROLES)
def api_report_generate(prep_id: int):
    prep, error = _api_prep(prep_id)
    if error:
        return error
    report = rstore.get_or_create_report(prep_id, _user().get("user_id"))
    if report["status"] == "generating":
        return _err("生成任务已在进行中", 409)
    if not (report.get("transcript_text") or "").strip():
        return _err("请先添加 M1 会议逐字稿", 400)
    version = rstore.current_version(report["id"])
    if rstore.has_edits(report, version) and not _json_body().get("confirm_overwrite"):
        return _err("需要确认覆盖", 409)

    from m1 import report_jobs
    try:
        previous = rstore.begin_generation(report["id"])
    except rstore.StatusError as exc:
        return _err(str(exc), 409)
    try:
        job_id = report_jobs.launch_job(prep_id, report["id"], previous_status=previous,
                                        actor_id=_user().get("user_id"))
    except Exception as exc:
        rstore.set_status(report["id"], previous)
        return _err("生成任务启动失败：%s" % exc, 500)
    store.audit(_user().get("user_id"), prep["student_id"], "m1.report_generate",
                {"prep_id": prep_id, "job_id": job_id, "previous_status": previous})
    return jsonify({"ok": True, "job_id": job_id})


# ---------------------------------------------------------------------------
# 编辑文档
# ---------------------------------------------------------------------------
class ChangeError(ValueError):
    pass


def _is_str(value) -> bool:
    return isinstance(value, str)


def _set_field(holder: dict, key: str, value, edited: list):
    old = holder.get(key)
    old_text = checks_mod.field_text(old)
    new_text = value.strip()
    if isinstance(old, dict) and old_text == new_text:
        return
    holder[key] = {"text": new_text, "src": "edited"}
    edited.append(key)


def apply_changes(doc: dict, changes) -> tuple:
    """校验并应用 ``changes``；返回 ``(新文档, 标签是否改变)``。非法路径抛 ChangeError。"""
    if not isinstance(changes, list) or not changes:
        raise ChangeError("changes 必须是非空列表")
    doc = copy.deepcopy(doc)
    abilities = kb.ability_map()
    dims = set(kb.dim_ids())
    tags_changed = False
    for change in changes:
        if not isinstance(change, dict) or not isinstance(change.get("path"), list):
            raise ChangeError("每项修改需要 path")
        path, value = change["path"], change.get("value")
        edited: list = []
        head = path[0] if path else None
        if path[:1] == ["meta"] and len(path) == 2:
            if path[1] not in checks_mod.META_KEYS or not _is_str(value):
                raise ChangeError("不允许修改该字段：%s" % ".".join(map(str, path)))
            doc.setdefault("meta", {})[path[1]] = value.strip()
        elif head == "dims" and len(path) == 3 and path[1] in dims \
                and path[2] in ("core_finding", "context_notes"):
            if not _is_str(value):
                raise ChangeError("值必须是文字")
            _set_field(doc["dims"][path[1]], path[2], value, edited)
        elif head == "dims" and len(path) == 5 and path[1] in dims and path[2] == "abilities" \
                and path[3] in abilities and abilities[path[3]]["dim"] == path[1]:
            row = doc["dims"][path[1]]["abilities"].get(path[3])
            if row is None:
                raise ChangeError("报告中没有该能力：%s" % path[3])
            key = path[4]
            if key in ("other_clues", "meeting"):
                if not _is_str(value):
                    raise ChangeError("值必须是文字")
                _set_field(row, key, value, edited)
            elif key == "tags":
                if not isinstance(value, list) or kb.tags_problem(value):
                    raise ChangeError("标签不符合协议 §7.3：%s" % (
                        kb.tags_problem(value) if isinstance(value, list) else "必须是列表"))
                if value != row.get("tags"):
                    tags_changed = True
                    row["tags"] = list(value)
                    row["tags_src"] = "edited"
            elif key == "y4_selected":
                allowed = set(abilities[path[3]]["indicators"])
                if not isinstance(value, list) or any(
                        not _is_str(v) or v not in allowed for v in value):
                    raise ChangeError("Y4 指标必须来自该能力的指定映射")
                row["y4_selected"] = list(value)
            else:
                raise ChangeError("不允许修改该字段：%s" % ".".join(map(str, path)))
        elif head == "portrait" and len(path) == 2 and path[1] in dims:
            if not _is_str(value):
                raise ChangeError("值必须是文字")
            _set_field(doc.setdefault("portrait", {}), path[1], value, edited)
        elif head == "findings" and len(path) == 3 and path[1] in ("resources", "needs", "open") \
                and path[2] in ("finding", "meaning"):
            if not _is_str(value):
                raise ChangeError("值必须是文字")
            _set_field(doc.setdefault("findings", {}).setdefault(path[1], {}), path[2],
                       value, edited)
        elif path == ["plan"]:
            if not isinstance(value, list) or not (1 <= len(value) <= 3):
                raise ChangeError("方案需要 1 到 3 项")
            old_rows = doc.get("plan") if isinstance(doc.get("plan"), list) else []
            rows = []
            for index, raw in enumerate(value):
                if not isinstance(raw, dict) or raw.get("ability") not in abilities:
                    raise ChangeError("方案第 %d 项的能力编号无效" % (index + 1))
                old = old_rows[index] if index < len(old_rows) and isinstance(old_rows[index], dict) else {}
                row = {"ability": raw["ability"]}
                for sub in _FIELD_KEYS:
                    item = raw.get(sub)
                    text = item.get("text") if isinstance(item, dict) else item
                    if text is None:
                        text = ""
                    if not _is_str(text):
                        raise ChangeError("方案第 %d 项的%s必须是文字" % (index + 1, sub))
                    holder = {sub: old.get(sub)}
                    _set_field(holder, sub, text, [])
                    row[sub] = holder[sub] if isinstance(holder[sub], dict) else \
                        {"text": text.strip(), "src": "edited"}
                rows.append(row)
            doc["plan"] = rows
        elif path == ["review_advice"]:
            if not _is_str(value):
                raise ChangeError("值必须是文字")
            _set_field(doc, "review_advice", value, edited)
        else:
            raise ChangeError("不允许修改该字段：%s" % ".".join(map(str, path)))
    return doc, tags_changed


def _rev(body: dict):
    rev = body.get("rev")
    if isinstance(rev, bool) or not isinstance(rev, int):
        return None
    return rev


@bp.route("/api/m1/preps/<int:prep_id>/report/doc", methods=["PUT"])
@role_required(*_WRITE_ROLES)
def api_report_doc(prep_id: int):
    prep, error = _api_prep(prep_id)
    if error:
        return error
    body = _json_body()
    rev = _rev(body)
    if rev is None:
        return _err("缺少 rev")
    report, version, error = _need_report(prep)
    if error:
        return error
    try:
        new_doc, tags_changed = apply_changes(version.get("doc") or {}, body.get("changes"))
    except ChangeError as exc:
        return _err(str(exc), 400)
    candidate = dict(version, doc=new_doc)
    checks = checks_mod.run_checks(report, candidate)
    try:
        saved = rstore.save_version(report["id"], rev, doc=new_doc, checks=checks)
    except rstore.RevConflict as exc:
        return jsonify({"ok": False, "error": str(exc), "rev": exc.rev}), 409
    except rstore.StatusError as exc:
        return _err(str(exc), 409)
    store.audit(_user().get("user_id"), prep["student_id"], "m1.report_edit",
                {"prep_id": prep_id, "rev": saved["rev"],
                 "paths": [c.get("path") for c in body["changes"] if isinstance(c, dict)]})
    return jsonify({"ok": True, "rev": saved["rev"], "status": saved["status"],
                    "checks": checks, "appendix": kb.appendix(new_doc),
                    "impacts": [IMPACT_NOTICE] if tags_changed else []})


@bp.route("/api/m1/preps/<int:prep_id>/report/evidence/<eid>", methods=["PUT"])
@role_required(*_WRITE_ROLES)
def api_report_evidence(prep_id: int, eid: str):
    prep, error = _api_prep(prep_id)
    if error:
        return error
    body = _json_body()
    rev = _rev(body)
    if rev is None:
        return _err("缺少 rev")
    status, speaker = body.get("status"), body.get("speaker")
    if status is None and speaker is None:
        return _err("没有需要更新的字段")
    if status is not None and status not in checks_mod.EVIDENCE_STATUSES:
        return _err("审核状态无效")
    if speaker is not None and speaker not in checks_mod.SPEAKERS:
        return _err("发言人无效")
    report, version, error = _need_report(prep)
    if error:
        return error
    evidence = copy.deepcopy(version.get("evidence") or [])
    target = next((e for e in evidence if e.get("id") == eid), None)
    if target is None:
        return _err("证据条目不存在", 404)
    if status is not None:
        target["status"] = status
    if speaker is not None:
        target["speaker"] = speaker
    checks = checks_mod.run_checks(report, dict(version, evidence=evidence))
    try:
        saved = rstore.save_version(report["id"], rev, evidence=evidence, checks=checks)
    except rstore.RevConflict as exc:
        return jsonify({"ok": False, "error": str(exc), "rev": exc.rev}), 409
    except rstore.StatusError as exc:
        return _err(str(exc), 409)
    store.audit(_user().get("user_id"), prep["student_id"], "m1.report_evidence",
                {"prep_id": prep_id, "evidence_id": eid, "status": status, "speaker": speaker})
    return jsonify({"ok": True, "rev": saved["rev"], "status": saved["status"],
                    "evidence": target, "checks": checks})


# ---------------------------------------------------------------------------
# 安全确认 / 审核流程
# ---------------------------------------------------------------------------
@bp.route("/api/m1/preps/<int:prep_id>/report/safety-ack", methods=["POST"])
@role_required(*_WRITE_ROLES)
def api_report_safety_ack(prep_id: int):
    prep, error = _api_prep(prep_id)
    if error:
        return error
    report = rstore.get_report(prep_id)
    if not report:
        return _err("报告还没有生成", 409)
    updated = rstore.ack_safety(report["id"], _user().get("user_id"))
    store.audit(_user().get("user_id"), prep["student_id"], "m1.report_safety_ack",
                {"prep_id": prep_id})
    return jsonify({"ok": True, "report": _public_report(updated)})


@bp.route("/api/m1/preps/<int:prep_id>/report/approve", methods=["POST"])
@role_required(*_WRITE_ROLES)
def api_report_approve(prep_id: int):
    prep, error = _api_prep(prep_id)
    if error:
        return error
    report, version, error = _need_report(prep)
    if error:
        return error
    checks = checks_mod.run_checks(report, version)
    blocks = checks_mod.blocking(checks)
    if blocks:
        return _err("还有 %d 项阻断问题，不能审核通过" % len(blocks), 400,
                    blocking=blocks, checks=checks)
    try:
        updated = rstore.approve(report["id"], _user().get("user_id"))
    except rstore.StatusError as exc:
        return _err(str(exc), 409)
    store.audit(_user().get("user_id"), prep["student_id"], "m1.report_approve",
                {"prep_id": prep_id, "version_id": version["id"]})
    return jsonify({"ok": True, "report": _public_report(updated), "checks": checks})


@bp.route("/api/m1/preps/<int:prep_id>/report/publish", methods=["POST"])
@role_required(*_WRITE_ROLES)
def api_report_publish(prep_id: int):
    prep, error = _api_prep(prep_id)
    if error:
        return error
    report = rstore.get_report(prep_id)
    if not report:
        return _err("报告还没有生成", 409)
    try:
        updated = rstore.publish(report["id"], _user().get("user_id"))
    except rstore.StatusError as exc:
        return _err(str(exc), 409)
    store.audit(_user().get("user_id"), prep["student_id"], "m1.report_publish",
                {"prep_id": prep_id})
    return jsonify({"ok": True, "report": _public_report(updated)})


@bp.route("/api/m1/preps/<int:prep_id>/report/reopen", methods=["POST"])
@role_required(*_WRITE_ROLES)
def api_report_reopen(prep_id: int):
    prep, error = _api_prep(prep_id)
    if error:
        return error
    report = rstore.get_report(prep_id)
    if not report:
        return _err("报告还没有生成", 409)
    try:
        updated = rstore.reopen(report["id"])
    except rstore.StatusError as exc:
        return _err(str(exc), 409)
    store.audit(_user().get("user_id"), prep["student_id"], "m1.report_reopen",
                {"prep_id": prep_id})
    return jsonify({"ok": True, "report": _public_report(updated)})
