"""Copilot 2.0 蓝图：七阶段会谈 session、补充材料、项目推荐与报告流。

全部路由要求 admin/advisor 登录；Advisor 只能访问自己名下的学生会谈
（越权统一 404，避免泄露学生是否存在）。LLM 耗时端点一律投递到
``growth_talk/jobs.py`` 的子进程作业，路由只返回 jobId 供前端轮询。
"""
from __future__ import annotations

import io
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from flask import (Blueprint, abort, jsonify, request, send_file, session,
                   render_template)
from sqlalchemy import select
from sqlalchemy.orm import Session

import db as _db
import growth_talk_store as store
from app_utils import role_required
from growth_talk import analysis, copilot, copilot_report, jobs, report_contract
from growth_talk.errors import ActionError
from growth_talk.report_pdf import render_report_pdf
from growth_talk.upload import MAX_UPLOAD_BYTES, UploadError, extract_upload

bp = Blueprint("copilot", __name__)

_JOB_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_UPLOAD_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}


# ---------------------------------------------------------------------------
# 通用助手
# ---------------------------------------------------------------------------
def _error(message: str, status: int):
    return jsonify({"ok": False, "error": message}), status


def _error_response(exc: Exception):
    """把领域异常映射为平台 JSON 信封；未识别异常交回 Flask。"""
    if isinstance(exc, store.NotFoundError):
        return _error(str(exc) or "记录不存在", 404)
    if isinstance(exc, store.RevisionConflict):
        return _error(str(exc), 409)
    if isinstance(exc, ActionError):
        return _error(exc.message, exc.status)
    if isinstance(exc, UploadError):
        return _error(exc.message, exc.status)
    if isinstance(exc, jobs.JobLaunchError):
        return _error(str(exc) or "任务启动失败", 503)
    if isinstance(exc, ValueError):
        return _error(str(exc), 422)
    if isinstance(exc, analysis.AnalysisError):
        return _error(str(exc) or "画像分析服务暂不可用", 502)
    raise exc


def _json_body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _actor_id():
    return session.get("user_id")


def _actor_name() -> str:
    return (session.get("display_name") or session.get("advisor_name")
            or "顾问")


def _student_or_404(student_id: int) -> dict | None:
    student = _db.get_student(student_id)
    if not student:
        return None
    if session.get("role") == "advisor":
        if (student.get("advisor_name") or "") != (session.get("advisor_name") or ""):
            return None
    return student


def _student_profile(student_id: int) -> dict | None:
    with Session(_db.engine) as sess:
        row = sess.get(_db.Student, int(student_id))
        if not row:
            return None
        return {
            "id": row.id, "student_code": row.student_code,
            "name": row.name, "grade": row.grade or "",
            "school": getattr(row, "school", None) or "",
            "advisor_name": getattr(row, "advisor_name", None) or "",
        }


def _session_or_404(session_id: int) -> dict | None:
    """按住会谈并做顾问隔离；越权与不存在都返回 None。"""
    row = store.get_session(session_id)
    if not row:
        return None
    if session.get("role") == "advisor" and row.get("advisor_id") != _actor_id():
        return None
    if not _student_or_404(row["student_id"]):
        return None
    return row


def _revision_error(body: dict, row: dict):
    revision = body.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        return _error("请提供会谈修订号", 400)
    if revision != row["revision"]:
        return _error("会谈已更新，请保留草稿并刷新确认", 409)
    return None


def _dispatch(row: dict, kind: str, extra: dict | None = None):
    payload = {
        "session_id": row["id"],
        "student_id": row["student_id"],
        "advisor_id": _actor_id(),
        "revision": row["revision"],
        **(extra or {}),
    }
    try:
        job_id = jobs.launch_copilot_job(kind, payload)
    except jobs.JobLaunchError as exc:
        return _error_response(exc)
    return jsonify({"jobId": job_id, "status": "running",
                    "revision": row["revision"]})


def _parse_meeting_at(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return value.strip()


def _entry_mode(row: dict) -> str:
    script = row.get("script") or {}
    mode = script.get("entryMode")
    if mode in ("direct", "guided"):
        return mode
    events = row.get("events") or []
    if row.get("phase", 0) >= 5 and not any(
            0 < event.get("phase", 0) < 5 for event in events):
        return "direct"
    return "guided"


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------
@bp.route("/api/v2/students/<int:sid>/copilot/sessions")
@role_required("admin", "advisor")
def api_list_sessions(sid: int):
    if not _student_or_404(sid):
        return _error("学生不存在或未分配至你的本地工作区", 404)
    advisor_id = None if session.get("role") == "admin" else _actor_id()
    return jsonify({"sessions": store.list_sessions(sid, advisor_id)})


@bp.route("/api/v2/students/<int:sid>/copilot/sessions", methods=["POST"])
@role_required("admin", "advisor")
def api_create_session(sid: int):
    if not _student_or_404(sid):
        return _error("学生不存在或未分配至你的本地工作区", 404)
    body = _json_body()
    entry_mode = "direct" if body.get("entryMode") == "direct" else "guided"
    if body.get("meetingAt") is not None:
        meeting_at = _parse_meeting_at(body.get("meetingAt"))
        if meeting_at is None:
            return _error("会议日期时间无效", 400)
    else:
        meeting_at = datetime.utcnow().replace(microsecond=0).isoformat()
    row, created = store.create_session(sid, _actor_id(), entry_mode, meeting_at)
    if created:
        return jsonify({"session": row}), 201
    return jsonify({"session": row, "existing": True})


@bp.route("/api/v2/copilot/sessions/<int:session_id>")
@role_required("admin", "advisor")
def api_get_session(session_id: int):
    row = _session_or_404(session_id)
    if not row:
        return _error("会谈不存在", 404)

    run_id = row.get("run_id")
    report_id = None
    has_generated = False
    if run_id:
        with Session(store.engine()) as sess:
            report = sess.execute(
                select(store.GtReport).where(
                    store.GtReport.run_id == run_id,
                    store.GtReport.student_id == row["student_id"],
                    store.GtReport.status == "CONFIRMED",
                ).order_by(store.GtReport.id.desc())
            ).scalars().first()
            report_id = report.id if report else None
        full = store.get_run_full(run_id) or {}
        has_generated = bool(report_id or full.get("quadrant"))

    source_names = {}
    meeting_source = (store.get_source(row["meeting_source_id"])
                      if row.get("meeting_source_id") else None)
    if meeting_source:
        source_names[str(meeting_source["id"])] = (
            meeting_source.get("file_name") or meeting_source.get("title") or "")

    supplements = row.get("supplements") or []
    projects_current = bool(supplements) and copilot.recommendations_current(
        row.get("meeting_source_id"), row.get("interests") or [],
        supplements[0].get("analysis") or {})

    return jsonify({
        "session": row,
        "entryMode": _entry_mode(row),
        "student": _student_profile(row["student_id"]),
        "reportId": report_id,
        "hasGeneratedReport": has_generated,
        "sourceFileNames": source_names,
        "projectsCurrent": projects_current,
    })


# ---------------------------------------------------------------------------
# 阶段 / 话术 / 校准 / 兴趣草稿
# ---------------------------------------------------------------------------
@bp.route("/api/v2/copilot/sessions/<int:session_id>/phase", methods=["PATCH"])
@role_required("admin", "advisor")
def api_save_phase(session_id: int):
    row = _session_or_404(session_id)
    if not row:
        return _error("会谈不存在", 404)
    body = _json_body()
    phase = body.get("phase")
    if (isinstance(phase, bool) or not isinstance(phase, int)
            or phase < 0 or phase >= len(copilot.PHASES)):
        return _error("阶段无效", 400)
    error = _revision_error(body, row)
    if error:
        return error

    interests = None
    if body.get("interests") is not None:
        try:
            interests = copilot.validate_interest_drafts(body["interests"])
        except ValueError as exc:
            return _error(str(exc), 400)

    entry_mode = body.get("entryMode")
    if entry_mode is not None and entry_mode not in ("direct", "guided"):
        return _error("会谈入口无效", 400)

    meeting_at = None
    if body.get("meetingAt") is not None:
        meeting_at = _parse_meeting_at(body.get("meetingAt"))
        if meeting_at is None:
            return _error("会议日期时间无效", 400)

    script_content = None
    if body.get("script") is not None:
        if not isinstance(body.get("script"), dict):
            return _error("话术格式无效", 400)
        try:
            script_content = copilot.validate_script_fields(body["script"])
        except ValueError as exc:
            return _error(str(exc) or "话术格式无效", 400)

    supplement_patch = body.get("supplementAnalysis")
    if supplement_patch is not None and (
            not isinstance(supplement_patch, dict)
            or isinstance(supplement_patch, list)):
        return _error("审核线索格式无效", 400)

    supplement = store.latest_supplement(session_id)
    saved_supplement = None
    analysis_update = None
    if supplement and (supplement_patch is not None or interests is not None):
        current_analysis = supplement.get("analysis") or {}
        next_analysis = copilot.merge_supplement_analysis(
            current_analysis, supplement_patch or {})
        if (interests is not None and phase in (5, 6)
                and isinstance(current_analysis.get("newInterests"), list)):
            try:
                next_analysis["interestReview"] = copilot.validate_interest_review_save(
                    row.get("interests") or [], current_analysis, interests,
                    body.get("interestReview"))
            except ValueError as exc:
                return _error(str(exc) or "请确认兴趣评分差异", 409)
        status = "REVIEWED" if interests is not None else supplement.get("status")
        analysis_update = (supplement["id"], next_analysis, status)

    if interests is not None:
        store.replace_session_interests(session_id, interests)
    if analysis_update:
        store.save_supplement_analysis(*analysis_update)

    fields = {"phase": phase}
    if meeting_at:
        fields["meeting_at"] = meeting_at
    if script_content is not None or entry_mode:
        merged_script = dict(row.get("script") or {})
        merged_script.update(script_content or {})
        if entry_mode:
            merged_script["entryMode"] = entry_mode
        fields["script"] = merged_script
    if phase == len(copilot.PHASES) - 1:
        fields["status"] = "REVIEW"
    store.update_session_fields(session_id, **fields)

    revision = store.bump_session_revision(
        session_id, body["revision"], _actor_id(), "phase_saved")
    result = store.get_session(session_id)
    if analysis_update:
        result = {
            **result,
            "savedSupplement": {
                "id": analysis_update[0],
                "analysis": analysis_update[1],
                "status": analysis_update[2],
            },
        }
    return jsonify({"revision": revision, "result": result})


@bp.route("/api/v2/copilot/sessions/<int:session_id>/career-calibration",
          methods=["PATCH"])
@role_required("admin", "advisor")
def api_save_calibration(session_id: int):
    row = _session_or_404(session_id)
    if not row:
        return _error("会谈不存在", 404)
    body = _json_body()
    error = _revision_error(body, row)
    if error:
        return error

    values = {}
    for key in ("careerInterests", "abilityTendencies",
                "valuePreferences", "notes"):
        value = body.get(key, "")
        if not isinstance(value, str) or len(value) > 4000:
            return _error("文本格式或长度无效", 400)
        values[key] = value.strip()
    store.upsert_calibration(
        session_id,
        values["careerInterests"], values["abilityTendencies"],
        values["valuePreferences"], values["notes"])
    revision = store.bump_session_revision(
        session_id, body["revision"], _actor_id(), "calibration_saved")
    current = store.get_session(session_id) or {}
    return jsonify({"revision": revision,
                    "result": current.get("calibration")})


@bp.route("/api/v2/copilot/sessions/<int:session_id>/interest-draft",
          methods=["PATCH"])
@role_required("admin", "advisor")
def api_save_interest_draft(session_id: int):
    row = _session_or_404(session_id)
    if not row:
        return _error("会谈不存在", 404)
    body = _json_body()
    try:
        interests = copilot.validate_interest_drafts(body.get("interests"))
    except ValueError as exc:
        return _error(str(exc), 400)
    error = _revision_error(body, row)
    if error:
        return error

    store.replace_session_interests(session_id, interests)
    supplement = store.latest_supplement(session_id)
    if supplement:
        current_analysis = supplement.get("analysis") or {}
        bindings = copilot.bind_interest_analysis(
            row.get("interests") or [], current_analysis)
        store.save_supplement_analysis(
            supplement["id"],
            {**current_analysis, "interestBindings": bindings},
            supplement.get("status"))

    revision = store.bump_session_revision(
        session_id, body["revision"], _actor_id(), "interests_saved")
    return jsonify({"revision": revision,
                    "result": store.get_session(session_id)})


# ---------------------------------------------------------------------------
# 资料上传 / Y4 校准
# ---------------------------------------------------------------------------
@bp.route("/api/v2/copilot/sessions/<int:session_id>/sources",
          methods=["POST"])
@role_required("admin", "advisor")
def api_upload_source(session_id: int):
    row = _session_or_404(session_id)
    if not row:
        return _error("会谈不存在", 404)
    revision = request.form.get("revision", type=int)
    if revision is None or revision < 1:
        return _error("请提供会谈修订号", 400)
    if revision != row["revision"]:
        return _error("会谈已更新，请保留草稿并刷新确认", 409)

    kind = (request.form.get("kind") or "MEETING").strip()
    if kind not in ("MEETING", "Y4"):
        return _error("请选择 Y4 报告或会议文字稿", 400)
    if kind == "Y4":
        return _error("Y4 报告请使用平台已生成的报告，无需上传", 400)

    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return _error("请选择 Y4 报告或会议文字稿", 400)
    file_name = os.path.basename(upload.filename.replace("\\", "/"))
    suffix = Path(file_name).suffix.lower()
    if suffix not in _UPLOAD_SUFFIXES:
        return _error("仅支持 PDF / DOCX / TXT / MD", 400)
    data = upload.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return _error("文件不能为空且不能超过 25 MB", 400)
    try:
        content = extract_upload(file_name, data)
    except UploadError as exc:
        return _error_response(exc)

    create_kwargs = {
        "purpose": "MEETING",
        "mime_type": upload.mimetype or "application/octet-stream",
        "file_name": file_name,
        "file_size": len(data),
        "source_format": suffix.lstrip(".") or "text",
    }
    source = store.create_source(
        row["student_id"], "GROWTH_TALK", "GROWTH_TALK", file_name, content,
        **create_kwargs)
    store.delete_superseded_sources(row["student_id"], "GROWTH_TALK")
    store.update_session_fields(session_id, meeting_source_id=source["id"])
    store.create_supplement(session_id, source["id"])
    revision = store.bump_session_revision(
        session_id, revision, _actor_id(), "source_uploaded")
    return jsonify({
        "revision": revision,
        "result": {"sourceId": source["id"], "fileName": file_name},
    }), 201


@bp.route("/api/v2/copilot/sessions/<int:session_id>/y4-calibrate",
          methods=["POST"])
@role_required("admin", "advisor")
def api_y4_calibrate(session_id: int):
    row = _session_or_404(session_id)
    if not row:
        return _error("会谈不存在", 404)
    body = _json_body()
    error = _revision_error(body, row)
    if error:
        return error

    report = None
    with Session(_db.engine) as sess:
        if row.get("y4_report_id"):
            report = sess.get(_db.Report, int(row["y4_report_id"]))
            if report and report.student_id != row["student_id"]:
                report = None
        if report is None:
            report = sess.execute(
                select(_db.Report)
                .where(_db.Report.student_id == row["student_id"])
                .order_by(_db.Report.id.desc())
            ).scalars().first()
    if not report:
        return _error("该学生还没有已确认的 Y4 报告，请先生成 Y4 报告", 422)

    try:
        payload = json.loads(report.data_json or "{}")
    except ValueError:
        payload = {}
    try:
        calibration = copilot.generate_career_calibration(
            payload if isinstance(payload, dict) else {},
            report.interpretation or "")
    except ValueError as exc:
        return _error(str(exc) or "该学生还没有已确认的 Y4 报告，请先生成 Y4 报告",
                      422)
    except analysis.AnalysisError as exc:
        return _error_response(exc)

    store.upsert_calibration(
        session_id, calibration["career_interests"],
        calibration["ability_tendencies"],
        calibration["value_preferences"], "")
    store.update_session_fields(session_id, y4_report_id=report.id)
    revision = store.bump_session_revision(
        session_id, body["revision"], _actor_id(), "career_analysis_completed")
    return jsonify({
        "revision": revision,
        "analysis": {
            "careerInterests": calibration["career_interests"],
            "abilityTendencies": calibration["ability_tendencies"],
            "valuePreferences": calibration["value_preferences"],
        },
    })


# ---------------------------------------------------------------------------
# 会后补充 / 下一步 / 项目推荐 / 报告准备（异步作业）
# ---------------------------------------------------------------------------
@bp.route("/api/v2/copilot/sessions/<int:session_id>/supplement",
          methods=["POST"])
@role_required("admin", "advisor")
def api_supplement(session_id: int):
    row = _session_or_404(session_id)
    if not row:
        return _error("会谈不存在", 404)
    body = _json_body()
    error = _revision_error(body, row)
    if error:
        return error
    return _dispatch(row, "supplement")


@bp.route("/api/v2/copilot/sessions/<int:session_id>/next-steps",
          methods=["POST"])
@role_required("admin", "advisor")
def api_next_steps(session_id: int):
    row = _session_or_404(session_id)
    if not row:
        return _error("会谈不存在", 404)
    body = _json_body()
    error = _revision_error(body, row)
    if error:
        return error
    return _dispatch(row, "next_steps")


@bp.route("/api/v2/copilot/sessions/<int:session_id>/projects",
          methods=["POST"])
@role_required("admin", "advisor")
def api_generate_projects(session_id: int):
    row = _session_or_404(session_id)
    if not row:
        return _error("会谈不存在", 404)
    body = _json_body()
    error = _revision_error(body, row)
    if error:
        return error
    return _dispatch(row, "projects_generate")


@bp.route("/api/v2/copilot/sessions/<int:session_id>/projects",
          methods=["PATCH"])
@role_required("admin", "advisor")
def api_review_projects(session_id: int):
    row = _session_or_404(session_id)
    if not row:
        return _error("会谈不存在", 404)
    body = _json_body()
    error = _revision_error(body, row)
    if error:
        return error
    items = body.get("items")
    if not isinstance(items, list):
        return _error("审核内容无效", 400)
    return _dispatch(row, "projects_review",
                     {"items": items, "actor": _actor_name()})


@bp.route("/api/v2/copilot/sessions/<int:session_id>/report-prepare",
          methods=["POST"])
@role_required("admin", "advisor")
def api_prepare_report(session_id: int):
    row = _session_or_404(session_id)
    if not row:
        return _error("会谈不存在", 404)
    body = _json_body()
    error = _revision_error(body, row)
    if error:
        return error
    return _dispatch(row, "report_prepare")


@bp.route("/api/v2/copilot/jobs/<job_id>")
@role_required("admin", "advisor")
def api_job_status(job_id: str):
    if not _JOB_ID_RE.fullmatch(job_id):
        return _error("任务不存在", 404)
    job = jobs.read_copilot_job(job_id)
    if job is None:
        return _error("任务不存在", 404)
    student_id = job.get("student_id")
    if student_id and not _student_or_404(student_id):
        return _error("学生不存在或未分配至你的本地工作区", 404)
    if (session.get("role") == "advisor"
            and job.get("advisor_id") not in (None, _actor_id())):
        return _error("任务不存在", 404)
    return jsonify(job)


# ---------------------------------------------------------------------------
# 报告预览 / 确认 / PDF
# ---------------------------------------------------------------------------
@bp.route("/api/v2/copilot/sessions/<int:session_id>/report-preview",
          methods=["POST"])
@role_required("admin", "advisor")
def api_preview_report(session_id: int):
    row = _session_or_404(session_id)
    if not row:
        return _error("会谈不存在", 404)
    if not row.get("run_id"):
        return _error("请先将会谈资料送入报告审核", 409)
    try:
        preview = report_contract.build_report_preview(row["run_id"])
    except (store.NotFoundError, store.RevisionConflict, ActionError,
            ValueError) as exc:
        return _error_response(exc)
    return jsonify(preview)


@bp.route("/api/v2/copilot/sessions/<int:session_id>/report-confirm",
          methods=["POST"])
@role_required("admin", "advisor")
def api_confirm_report(session_id: int):
    row = _session_or_404(session_id)
    if not row:
        return _error("会谈不存在", 404)
    body = _json_body()
    try:
        report, status = copilot_report.confirm_session_report(
            session_id,
            revision=body.get("revision"),
            fingerprint=str(body.get("fingerprint") or ""),
            suggestion_ids=body.get("suggestionIds",
                                    body.get("suggestion_ids", [])),
            confirmed_by=_actor_name(),
            reviewed_meeting=(body.get("reviewedMeeting") is True
                              or body.get("reviewed_meeting") is True),
            reviewed_narrative=(body.get("reviewedNarrative") is True
                                or body.get("reviewed_narrative") is True),
        )
    except (store.NotFoundError, store.RevisionConflict, ActionError,
            ValueError) as exc:
        return _error_response(exc)
    return jsonify({"report": report}), status


@bp.route("/api/v2/copilot/sessions/<int:session_id>/report-pdf")
@role_required("admin", "advisor")
def api_report_pdf(session_id: int):
    row = _session_or_404(session_id)
    if not row:
        return _error("会谈不存在", 404)
    revision = request.args.get("revision", type=int)
    fingerprint = request.args.get("fingerprint", "")
    try:
        copilot_report.assert_report_pdf_fresh(session_id, revision, fingerprint)
    except (store.NotFoundError, store.RevisionConflict, ActionError) as exc:
        return _error_response(exc)

    student = _student_profile(row["student_id"]) or {
        "id": row["student_id"], "name": "", "grade": "", "school": ""}
    current = store.get_session(session_id) or row
    draft = copilot_report.report_draft(current, student)
    try:
        preview = report_contract.build_report_preview(current["run_id"])
    except (store.NotFoundError, store.RevisionConflict, ActionError) as exc:
        return _error_response(exc)
    payload = {
        "student": {
            "name": student.get("name") or "",
            "grade": student.get("grade") or "",
            "school": student.get("school") or "",
        },
        "meetingSummary": preview["meetingSummary"],
        "narrative": preview["narrative"],
        "career": preview.get("career"),
        "interests": [
            item for item in draft.get("interests") or []
            if item.get("preferenceScore") is not None
            and item.get("competenceScore") is not None
        ],
        "y4Validation": draft.get("y4Validation") or [],
        "missing": [
            item.get("label") for item in draft.get("missing") or []
            if not item.get("required")
        ],
    }
    data = render_report_pdf(payload, draft=True)
    try:
        copilot_report.assert_report_pdf_fresh(session_id, revision, fingerprint)
    except (store.NotFoundError, store.RevisionConflict, ActionError) as exc:
        return _error_response(exc)

    filename = f"{student.get('name') or '学生'}-会谈报告-草稿.pdf"
    response = send_file(
        io.BytesIO(data), mimetype="application/pdf",
        as_attachment=True,
        download_name=f"first-touch-draft-{session_id}.pdf")
    response.headers["Content-Disposition"] = (
        f"attachment; filename=\"first-touch-draft-{session_id}.pdf\"; "
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------
def _visible_students() -> list[dict]:
    """当前角色可见的学生（admin 全量 / advisor 限名下）。"""
    stmt = select(_db.Student).order_by(_db.Student.created_at.desc())
    if session.get("role") == "advisor":
        stmt = stmt.where(
            _db.Student.advisor_name == (session.get("advisor_name") or ""))
    with Session(_db.engine) as sess:
        rows = sess.execute(stmt).scalars().all()
    return [{
        "id": row.id,
        "student_code": row.student_code or "",
        "name": row.name or "",
        "grade": row.grade or "",
        "school": getattr(row, "school", None) or "",
        "advisor_name": getattr(row, "advisor_name", None) or "",
    } for row in rows]


def _latest_y4_reports(student_ids: list[int]) -> dict:
    """每个学生在本平台最新的 Y4 报告：``{sid: {reportId, count, latestDate}}``。"""
    if not student_ids:
        return {}
    with Session(_db.engine) as sess:
        rows = sess.execute(
            select(_db.Report.student_id, _db.Report.id, _db.Report.report_date)
            .where(_db.Report.student_id.in_(student_ids))
            .order_by(_db.Report.student_id,
                      _db.Report.created_at.desc(), _db.Report.id.desc())
        ).all()
    report_map: dict = {}
    for sid, report_id, report_date in rows:
        item = report_map.setdefault(
            sid, {"reportId": report_id, "count": 0, "latestDate": ""})
        item["count"] += 1
        if not item["latestDate"]:
            item["latestDate"] = report_date.isoformat() if report_date else ""
    return report_map


def _first_touch_students() -> list[dict]:
    """First Touch 学生卡片：最近会谈阶段、会谈数、已确认报告数、Y4 报告摘要。"""
    advisor_id = _actor_id() if session.get("role") == "advisor" else None
    students = _visible_students()
    y4_map = _latest_y4_reports([item["id"] for item in students])
    cards = []
    for student in students:
        sessions = store.list_sessions(student["id"], advisor_id)
        latest = sessions[0] if sessions else None
        y4 = y4_map.get(student["id"]) or {}
        cards.append({
            "id": student["id"],
            "code": student.get("student_code") or "",
            "name": student.get("name") or "",
            "grade": student.get("grade") or "",
            "school": student.get("school") or "",
            "advisorName": student.get("advisor_name") or "",
            "sessionCount": len(sessions),
            "phase": latest["phase"] if latest else None,
            "phaseLabel": (copilot.PHASES[latest["phase"]]
                           if latest and 0 <= latest["phase"] < len(copilot.PHASES)
                           else ""),
            "reportCount": len(store.list_reports(student["id"])),
            "y4ReportCount": y4.get("count", 0),
            "y4LatestDate": y4.get("latestDate", ""),
        })
    return cards


@bp.route("/first-touch")
@role_required("admin", "advisor")
def page_home():
    return render_template(
        "first_touch/home.html", nav_active="first_touch",
        ctx={
            "students": _first_touch_students(),
            "canImport": session.get("role") == "advisor",
        })


@bp.route("/first-touch/copilot")
@role_required("admin", "advisor")
def page_chat_picker():
    students = [card for card in _first_touch_students()
                if card["sessionCount"]]
    for card in students:
        card["chatCount"] = len(store.list_chats(card["id"]))
    return render_template("first_touch/chat_picker.html",
                           nav_active="first_touch.copilot",
                           ctx={"students": students})


@bp.route("/first-touch/copilot/<int:sid>")
@role_required("admin", "advisor")
def page_chat(sid: int):
    profile = _student_profile(sid)
    if not profile or not _student_or_404(sid):
        abort(404)
    active_chat_id = (request.args.get("chat") or "").strip()
    active = None
    if active_chat_id and _JOB_ID_RE.fullmatch(active_chat_id):
        try:
            row = store.get_chat(active_chat_id)
        except store.NotFoundError:
            row = None
        if row and row.get("studentId") == sid:
            active = row
    sessions = store.list_sessions(
        sid, _actor_id() if session.get("role") == "advisor" else None)
    ctx = {
        "sid": sid,
        "name": profile.get("name") or "",
        "code": profile.get("student_code") or "",
        "grade": profile.get("grade") or "",
        "school": profile.get("school") or "",
        "chats": store.list_chats(sid),
        "activeChat": active,
        "sessionId": sessions[0]["id"] if sessions else None,
        "canWrite": session.get("role") in ("admin", "advisor"),
    }
    return render_template("first_touch/chat.html",
                           nav_active="first_touch.copilot", ctx=ctx)


@bp.route("/first-touch/guide")
@role_required("admin", "advisor")
def page_guide():
    return render_template("first_touch/guide.html",
                           nav_active="first_touch.guide")


@bp.route("/first-touch/archive/<int:sid>")
@role_required("admin")
def page_archive(sid: int):
    profile = _student_profile(sid)
    if not profile:
        abort(404)
    store.write_audit(_actor_id(), sid, "archive_viewed",
                      json.dumps({"path": request.path}, ensure_ascii=False))
    ctx = {
        "sid": sid,
        "name": profile.get("name") or "",
        "code": profile.get("student_code") or "",
        "grade": profile.get("grade") or "",
        "school": profile.get("school") or "",
        "sources": store.list_sources(sid),
        "runs": store.list_runs(sid),
        "reports": store.list_reports(sid),
    }
    return render_template("first_touch/archive.html",
                           nav_active="first_touch.archive", ctx=ctx)


@bp.route("/api/first-touch/students", methods=["POST"])
@role_required("admin", "advisor")
def api_create_student():
    """手动建档：按姓名幂等，顾问自动归属当前登录顾问。"""
    body = _json_body()
    name = body.get("name")
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        return _error("请填写学生姓名", 400)
    if len(name) > 100:
        return _error("学生姓名不能超过 100 字", 400)
    grade = body.get("grade") if isinstance(body.get("grade"), str) else ""
    school = body.get("school") if isinstance(body.get("school"), str) else ""
    grade, school = grade.strip(), school.strip()
    if len(grade) > 50 or len(school) > 200:
        return _error("年级或学校名称过长", 400)
    advisor_name = session.get("advisor_name") or ""
    if session.get("role") == "admin":
        advisor_name = ((body.get("advisorName") or "").strip()
                        if isinstance(body.get("advisorName"), str)
                        else advisor_name) or advisor_name
    with Session(_db.engine) as sess:
        existed = sess.execute(
            select(_db.Student.id).where(_db.Student.name == name)
        ).first() is not None
    student_id = _db.find_or_create_student(
        name=name, grade=grade, school=school, advisor_name=advisor_name)
    return jsonify({"ok": True, "student": _student_profile(student_id)}), (
        200 if existed else 201)


@bp.route("/api/first-touch/import-y4", methods=["POST"])
@role_required("admin", "advisor")
def api_import_y4():
    """把平台已有 Y4 报告导入 First Touch：建会谈并绑定最新报告。"""
    body = _json_body()
    raw_ids = body.get("studentIds")
    if not isinstance(raw_ids, list) or not raw_ids:
        return _error("请选择要导入的学生", 400)
    if len(raw_ids) > 200:
        return _error("一次最多导入 200 名学生", 400)
    ids: list[int] = []
    for value in raw_ids:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return _error("学生参数无效", 400)
        if value not in ids:
            ids.append(value)
    visible = {item["id"] for item in _visible_students()}
    allowed = [sid for sid in ids if sid in visible]
    if not allowed:
        return _error("没有可导入的学生", 400)
    report_map = _latest_y4_reports(allowed)
    imported = 0
    skipped = len(ids) - len(allowed)
    for sid in allowed:
        info = report_map.get(sid)
        if not info:
            skipped += 1
            continue
        row, _created = store.create_session(sid, _actor_id(), "guided")
        if row.get("y4_report_id") != info["reportId"]:
            store.update_session_fields(row["id"], y4_report_id=info["reportId"])
        store.write_audit(
            _actor_id(), sid, "first_touch_y4_imported",
            json.dumps({"reportId": info["reportId"]}, ensure_ascii=False))
        imported += 1
    return jsonify({"ok": True, "imported": imported, "skipped": skipped})


@bp.route("/first-touch/students/<int:sid>")
@role_required("admin", "advisor")
def page_workspace(sid: int):
    profile = _student_profile(sid)
    if not profile or not _student_or_404(sid):
        abort(404)
    entry_mode = "direct" if request.args.get("entry") == "direct" else "guided"
    row, _created = store.create_session(
        sid, _actor_id(), entry_mode,
        datetime.utcnow().replace(microsecond=0).isoformat())
    ctx = {
        "sid": sid,
        "code": profile.get("student_code") or "",
        "name": profile.get("name") or "",
        "grade": profile.get("grade") or "",
        "school": profile.get("school") or "",
        "sessionId": row["id"],
        "canWrite": session.get("role") in ("admin", "advisor"),
        "phases": copilot.PHASES,
    }
    return render_template("first_touch/workspace.html", nav_active="first_touch",
                           ctx=ctx)


# ---------------------------------------------------------------------------
# 聊天
# ---------------------------------------------------------------------------
def _assistant_response(student_id: int, row: dict | None = None):
    body = _json_body()
    question = body.get("question")
    question = question.strip() if isinstance(question, str) else ""
    if not question or len(question) > 1000:
        return _error("问题不能为空且不能超过 1000 字", 400)
    try:
        history = copilot.validate_chat_context(body.get("history"))
    except ValueError as exc:
        return _error(str(exc), 400)

    chat_id = body.get("chatId", body.get("chat_id"))
    if chat_id is not None:
        if not isinstance(chat_id, str) or not _JOB_ID_RE.fullmatch(chat_id):
            return _error("聊天上下文格式无效", 400)
        try:
            chat = store.get_chat(chat_id)
        except store.NotFoundError:
            return _error("对话不存在", 404)
        if chat.get("studentId") != student_id:
            return _error("对话不存在", 404)
    else:
        chat_id = store.create_chat(
            student_id, _actor_id(), row["id"] if row else None)

    payload = {
        "student_id": student_id,
        "advisor_id": _actor_id(),
        "session_id": row["id"] if row else None,
        "chat_id": chat_id,
        "question": question,
        "history": history,
    }
    try:
        job_id = jobs.launch_copilot_job("assistant", payload)
    except jobs.JobLaunchError as exc:
        return _error_response(exc)
    return jsonify({"jobId": job_id, "chatId": chat_id,
                    "status": "running"})


@bp.route("/api/students/<int:sid>/copilot/assistant", methods=["POST"])
@role_required("admin", "advisor")
def api_student_assistant(sid: int):
    if not _student_or_404(sid):
        return _error("学生不存在或未分配至你的本地工作区", 404)
    return _assistant_response(sid)


@bp.route("/api/v2/copilot/sessions/<int:session_id>/assistant",
          methods=["POST"])
@role_required("admin", "advisor")
def api_session_assistant(session_id: int):
    row = _session_or_404(session_id)
    if not row:
        return _error("会谈不存在", 404)
    return _assistant_response(row["student_id"], row)


@bp.route("/api/students/<int:sid>/copilot/chats")
@role_required("admin", "advisor")
def api_list_chats(sid: int):
    if not _student_or_404(sid):
        return _error("学生不存在或未分配至你的本地工作区", 404)
    return jsonify({"chats": store.list_chats(sid)})


@bp.route("/api/copilot/chats/<chat_id>")
@role_required("admin", "advisor")
def api_get_chat(chat_id: str):
    try:
        chat = store.get_chat(chat_id)
    except store.NotFoundError:
        return _error("对话不存在", 404)
    if not _student_or_404(chat["studentId"]):
        return _error("对话不存在", 404)
    return jsonify({"chat": chat})
