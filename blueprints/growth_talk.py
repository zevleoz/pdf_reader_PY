"""Growth Talk 蓝图：资料上传、分析作业、顾问审核、报告预览/确认/下载。

页面路由（``/students/<sid>/growth-talk``）随 Task 9 的 workspace 模板一起
加入；本模块只负责会话 API。所有路由都要求 admin/advisor 登录，Advisor
只能操作自己名下的学生（越权统一 404，避免泄露学生是否存在）。
"""
from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote

from flask import (Blueprint, abort, jsonify, render_template, request, send_file,
                   session)

import db as _db
import growth_talk_store as store
from app_utils import DATA_DIR, role_required
from growth_talk import analysis, jobs, report_contract, runs
from growth_talk.errors import ActionError
from growth_talk.report_pdf import render_report_pdf, report_filename
from growth_talk.upload import MAX_UPLOAD_BYTES, UploadError, extract_upload

bp = Blueprint("growth_talk", __name__)

# 分片暂存目录（测试通过 monkeypatch 本模块常量隔离到 tmp_path）
GT_UPLOAD_DIR = Path(DATA_DIR) / "_gt_uploads"

_UPLOAD_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_KIND_PURPOSE = {
    "GROWTH_TALK": "MEETING",
    "Y4_CAREER_PROFILE": "CAREER",
}
_MAX_TOTAL_CHUNKS = 2000
_ANALYSIS_STATUS = {
    "RUNNING": "running",
    "PENDING_REVIEW": "done",
    "FAILED": "error",
    "DRAFT": "done",
}


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
        return _error(str(exc) or "分析任务启动失败", 503)
    if isinstance(exc, ValueError):
        return _error(str(exc), 422)
    if isinstance(exc, analysis.AnalysisError):
        return _error(str(exc) or "画像分析服务暂不可用", 502)
    raise exc


def _json_body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _actor_name() -> str:
    return (session.get("display_name") or session.get("advisor_name")
            or "顾问")


def _actor_id():
    return session.get("user_id")


def _student_or_404(student_id: int) -> dict | None:
    """取学生并做 Advisor 归属校验；不存在或越权都返回 None（路由统一 404）。"""
    student = _db.get_student(student_id)
    if not student:
        return None
    if session.get("role") == "advisor":
        if (student.get("advisor_name") or "") != (session.get("advisor_name") or ""):
            return None
    return student


def _student_profile(student_id: int) -> dict:
    """Copilot 上下文需要年级，get_student 不含该字段，这里直接取 ORM 行。"""
    with _db.Session(_db.engine) as sess:
        row = sess.get(_db.Student, int(student_id))
        if not row:
            return {"name": "", "grade": ""}
        return {"name": row.name or "", "grade": row.grade or ""}


def _run_or_404(run_id: int):
    run = store.get_run(run_id)
    if not run or not _student_or_404(run["student_id"]):
        return None
    return run


def _source_or_404(source_id: int):
    source = store.get_source(source_id)
    if not source or not _student_or_404(source["student_id"]):
        return None
    return source


def _report_or_404(report_id: int):
    report = store.get_report(report_id)
    if not report or report.get("status") != "CONFIRMED":
        return None
    if not _student_or_404(report["student_id"]):
        return None
    return report


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """同目录唯一临时文件 + fsync + os.replace，避免半截分片。"""
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent),
                                    prefix=f".{path.name}.",
                                    suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _upload_dir(upload_id: str) -> Path:
    return Path(GT_UPLOAD_DIR) / upload_id


def _read_upload(upload_id: str) -> bytes:
    """按 index 顺序合并分片；失败抛 ActionError(400)，成功后由调用方清理。"""
    directory = _upload_dir(upload_id)
    if not directory.is_dir():
        raise ActionError(400, "未找到上传数据，请重新上传")

    indexed = []
    for part in directory.glob("*.part"):
        try:
            indexed.append((int(part.stem), part))
        except ValueError:
            raise ActionError(400, "上传数据损坏，请重新上传")
    indexed.sort(key=lambda item: item[0])
    indexes = [index for index, _part in indexed]
    if indexes != list(range(len(indexes))):
        raise ActionError(400, "分片不完整，请重新上传")

    total_file = directory / ".total"
    if total_file.exists():
        try:
            total = int(total_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            raise ActionError(400, "分片元数据损坏，请重新上传")
        if total != len(indexes):
            raise ActionError(400, "分片不完整，请重新上传")

    data = b"".join(part.read_bytes() for _index, part in indexed)
    if not data:
        raise ActionError(400, "文件不能为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ActionError(400, "文件不能为空且不能超过 25 MB")
    return data


def _cleanup_upload(upload_id: str) -> None:
    shutil.rmtree(_upload_dir(upload_id), ignore_errors=True)


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------
@bp.route("/students/<int:sid>/growth-talk")
@role_required("admin", "advisor")
def page_workspace(sid: int):
    student = _student_or_404(sid)
    if not student:
        abort(404)
    ctx = {
        "id": student["id"],
        "code": student.get("student_code"),
        "name": student.get("name"),
        "canWrite": session.get("role") in ("admin", "advisor"),
        "reports": [
            {
                "id": report["id"], "version": report["version"],
                "confirmed_at": report["confirmed_at"],
                "confirmed_by": report["confirmed_by"],
            }
            for report in store.list_reports(sid)
            if report.get("status") == "CONFIRMED"
        ],
    }
    return render_template("growth_talk/workspace.html",
                           nav_active="students", ctx=ctx)


# ---------------------------------------------------------------------------
# 分片上传
# ---------------------------------------------------------------------------
@bp.route("/api/growth-talk/upload/chunk", methods=["POST"])
@role_required("admin", "advisor")
def api_upload_chunk():
    upload_id = (request.form.get("upload_id") or "").strip()
    index = request.form.get("index", type=int)
    total = request.form.get("total", type=int)
    chunk = request.files.get("file") or request.files.get("chunk")

    if not upload_id or not _UPLOAD_ID_RE.fullmatch(upload_id):
        return _error("upload_id 非法", 400)
    if index is None or index < 0 or chunk is None:
        return _error("上传参数不完整", 400)
    if total is not None and not (1 <= total <= _MAX_TOTAL_CHUNKS):
        return _error("total 非法", 400)
    if total is not None and index >= total:
        return _error("index 超出 total", 400)

    try:
        data = chunk.read()
    except OSError as exc:
        return _error(f"读取分片失败: {exc}", 500)
    if not data:
        return _error("分片内容为空", 400)

    directory = _upload_dir(upload_id)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if total is not None:
            total_path = directory / ".total"
            if total_path.exists():
                try:
                    existing = int(total_path.read_text(encoding="utf-8").strip())
                except (OSError, ValueError):
                    return _error("分片元数据损坏，请重新上传", 400)
                if existing != total:
                    return _error("分片总数与已上传不一致，请重新上传", 400)
            else:
                _atomic_write_bytes(total_path, str(total).encode("utf-8"))
        _atomic_write_bytes(directory / f"{index:06d}.part", data)
    except OSError as exc:
        return _error(f"写入分片失败: {exc}", 500)

    print(f"[gt-upload] id={upload_id} index={index}/{total or '?'} "
          f"bytes={len(data)}", flush=True)
    return jsonify({"ok": True, "received": index})


# ---------------------------------------------------------------------------
# 资料（source）
# ---------------------------------------------------------------------------
@bp.route("/api/students/<int:sid>/growth-talk/sources", methods=["POST"])
@role_required("admin", "advisor")
def api_create_source(sid: int):
    if not _student_or_404(sid):
        return _error("学生不存在", 404)
    body = _json_body()
    kind = str(body.get("source_kind") or "").strip()
    if kind not in _KIND_PURPOSE:
        return _error("资料分类无效", 400)

    upload_id = str(body.get("upload_id") or "").strip()
    file_name = str(body.get("file_name") or "").strip()
    if file_name:
        # 浏览器可能提交 C:\fakepath\ 前缀；只保留文件名。
        file_name = os.path.basename(file_name.replace("\\", "/"))
    if upload_id:
        if not _UPLOAD_ID_RE.fullmatch(upload_id):
            return _error("upload_id 非法", 400)
        if not file_name:
            return _error("请选择文件", 400)
        if (kind == "Y4_CAREER_PROFILE"
                and Path(file_name).suffix.lower() == ".json"):
            return _error("职业兴趣资料不支持 JSON", 400)
        try:
            data = _read_upload(upload_id)
            content = extract_upload(file_name, data)
        except (ActionError, UploadError) as exc:
            return _error_response(exc)
        title = Path(file_name).name
        file_size = len(data)
        mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        source_format = Path(file_name).suffix.lower().lstrip(".") or "text"
    else:
        text = body.get("text")
        title = str(body.get("title") or "").strip()
        if not isinstance(text, str) or not text.strip():
            return _error("请输入资料正文", 400)
        if not title:
            return _error("请填写资料标题", 400)
        content = text.strip()
        file_name = None
        file_size = len(content.encode("utf-8"))
        mime_type = "text/plain; charset=utf-8"
        source_format = "text"

    source = store.create_source(
        sid, kind, kind, title, content,
        purpose=_KIND_PURPOSE[kind],
        mime_type=mime_type, file_name=file_name,
        file_size=file_size, source_format=source_format,
    )
    if upload_id:
        _cleanup_upload(upload_id)
    store.delete_superseded_sources(sid, kind)
    store.write_audit(_actor_id(), sid, "source_uploaded", json.dumps(
        {"sourceId": source["id"], "type": kind}, ensure_ascii=False))
    return jsonify(source), 201


@bp.route("/api/students/<int:sid>/growth-talk/sources")
@role_required("admin", "advisor")
def api_list_sources(sid: int):
    if not _student_or_404(sid):
        return _error("学生不存在", 404)
    return jsonify({"sources": store.list_sources(sid)})


@bp.route("/api/growth-talk/sources/<int:source_id>")
@role_required("admin", "advisor")
def api_get_source(source_id: int):
    source = _source_or_404(source_id)
    if not source:
        return _error("资料不存在", 404)
    return jsonify({"source": source})


@bp.route("/api/growth-talk/sources/<int:source_id>", methods=["DELETE"])
@role_required("admin", "advisor")
def api_delete_source(source_id: int):
    source = _source_or_404(source_id)
    if not source:
        return _error("资料不存在", 404)
    try:
        store.delete_source(source_id)
    except store.RevisionConflict as exc:
        return _error_response(exc)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# 职业兴趣分析（同步）
# ---------------------------------------------------------------------------
@bp.route("/api/students/<int:sid>/growth-talk/career-analysis", methods=["POST"])
@role_required("admin", "advisor")
def api_career_analysis(sid: int):
    if not _student_or_404(sid):
        return _error("学生不存在", 404)
    body = _json_body()
    source_id = body.get("source_id", body.get("sourceId"))
    try:
        source_id = int(source_id)
    except (TypeError, ValueError):
        return _error("请选择职业兴趣报告", 400)
    source = store.get_source(source_id)
    if (not source or source["student_id"] != sid
            or source["type"] != "Y4_CAREER_PROFILE"):
        return _error("资料不存在", 404)

    try:
        result = runs.career_analysis(source_id)
    except (store.NotFoundError, ActionError, analysis.AnalysisError) as exc:
        return _error_response(exc)
    store.write_audit(_actor_id(), sid, "career_analyzed_confirmed",
                      json.dumps({"sourceId": source_id}, ensure_ascii=False))
    return jsonify(result)


# ---------------------------------------------------------------------------
# 分析作业
# ---------------------------------------------------------------------------
@bp.route("/api/students/<int:sid>/growth-talk/runs", methods=["POST"])
@role_required("admin", "advisor")
def api_create_run(sid: int):
    if not _student_or_404(sid):
        return _error("学生不存在", 404)
    body = _json_body()
    meeting_sources = store.list_sources(sid, type="GROWTH_TALK",
                                         purpose="MEETING")
    if not meeting_sources:
        return _error("请先上传会议纪要", 409)
    latest = meeting_sources[0]
    requested = body.get("source_id", body.get("sourceId"))
    if requested is not None:
        try:
            requested = int(requested)
        except (TypeError, ValueError):
            return _error("请使用当前会议资料", 409)
        if requested != latest["id"]:
            return _error("请使用当前会议资料", 409)

    run = store.create_run(sid, latest["id"])
    try:
        jobs.launch_analysis(run["id"])
    except jobs.JobLaunchError as exc:
        return _error_response(exc)
    return jsonify({"run_id": run["id"], "runId": run["id"]}), 201


@bp.route("/api/growth-talk/jobs/<int:run_id>")
@role_required("admin", "advisor")
def api_job_status(run_id: int):
    run = _run_or_404(run_id)
    if not run:
        return _error("分析不存在", 404)
    job = jobs.read_gt_job(run_id)
    if job is None:
        job = {
            "status": _ANALYSIS_STATUS.get(run["status"], run["status"].lower()),
            "message": run.get("error") or "",
        }
    payload = dict(job)
    payload["runStatus"] = run["status"]
    payload["runId"] = run_id
    return jsonify(payload)


@bp.route("/api/students/<int:sid>/growth-talk/runs")
@role_required("admin", "advisor")
def api_list_runs(sid: int):
    if not _student_or_404(sid):
        return _error("学生不存在", 404)
    return jsonify({"runs": [run for run in store.list_runs(sid) if run]})


@bp.route("/api/growth-talk/runs/<int:run_id>", methods=["PUT"])
@role_required("admin", "advisor")
def api_apply_action(run_id: int):
    if not _run_or_404(run_id):
        return _error("分析不存在", 404)
    body = _json_body()
    action = body.get("action")
    if not isinstance(action, str) or not action:
        return _error("不支持的操作", 400)
    if "expected_revision" not in body and "expectedRevision" in body:
        body["expected_revision"] = body["expectedRevision"]

    try:
        result = runs.apply_action(run_id, action, body, _actor_name(),
                                   actor_id=_actor_id())
    except (store.NotFoundError, store.RevisionConflict, ActionError,
            analysis.AnalysisError, ValueError) as exc:
        return _error_response(exc)
    return jsonify(result)


# ---------------------------------------------------------------------------
# 报告预览 / 确认 / 下载
# ---------------------------------------------------------------------------
@bp.route("/api/growth-talk/runs/<int:run_id>/preview-report", methods=["POST"])
@role_required("admin", "advisor")
def api_preview_report(run_id: int):
    if not _run_or_404(run_id):
        return _error("分析不存在", 404)
    try:
        preview = report_contract.build_report_preview(run_id)
    except (store.NotFoundError, ActionError, ValueError) as exc:
        return _error_response(exc)
    return jsonify(preview)


@bp.route("/api/growth-talk/runs/<int:run_id>/report", methods=["POST"])
@role_required("admin", "advisor")
def api_confirm_report(run_id: int):
    if not _run_or_404(run_id):
        return _error("分析不存在", 404)
    body = _json_body()
    try:
        result = report_contract.confirm_report(
            run_id,
            reviewed_meeting=body.get("reviewedMeeting") is True
            or body.get("reviewed_meeting") is True,
            reviewed_narrative=body.get("reviewedNarrative") is True
            or body.get("reviewed_narrative") is True,
            suggestion_ids=body.get("suggestionIds",
                                    body.get("suggestion_ids", [])),
            fingerprint=str(body.get("fingerprint") or ""),
            confirmed_by=_actor_name(),
            actor_id=_actor_id(),
        )
    except (store.NotFoundError, store.RevisionConflict, ActionError,
            ValueError) as exc:
        return _error_response(exc)
    return jsonify(result), 201


@bp.route("/api/growth-talk/reports/<int:report_id>/download.json")
@role_required("admin", "advisor", "viewer")
def api_download_report_json(report_id: int):
    report = _report_or_404(report_id)
    if not report:
        return _error("报告不存在", 404)
    response = send_file(
        io.BytesIO(report["payload"].encode("utf-8")),
        mimetype="application/json; charset=utf-8",
        as_attachment=True,
        download_name=f"first-touch-{report['id']}-v{report['version']}.json",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/api/growth-talk/reports/<int:report_id>/download.pdf")
@role_required("admin", "advisor", "viewer")
def api_download_report_pdf(report_id: int):
    report = _report_or_404(report_id)
    if not report:
        return _error("报告不存在", 404)
    try:
        payload = json.loads(report["payload"])
    except (TypeError, ValueError):
        return _error("历史原始报告不支持 PDF 导出", 409)
    if payload.get("schema") != report_contract.REPORT_SCHEMA_VERSION:
        return _error("历史原始报告不支持 PDF 导出", 409)

    data = render_report_pdf(payload)
    filename = report_filename(((payload.get("student") or {}).get("name")
                                or "学生"))
    response = send_file(io.BytesIO(data), mimetype="application/pdf",
                         as_attachment=True,
                         download_name="First Touch Report.pdf")
    response.headers["Content-Disposition"] = (
        "attachment; filename=\"First Touch Report.pdf\"; "
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )
    response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------
@bp.route("/api/growth-talk/runs/<int:run_id>/copilot", methods=["POST"])
@role_required("admin", "advisor")
def api_copilot(run_id: int):
    run = _run_or_404(run_id)
    if not run:
        return _error("分析不存在", 404)
    body = _json_body()
    sid = run["student_id"]

    meeting_sources = store.list_sources(sid, type="GROWTH_TALK",
                                         purpose="MEETING")
    career_sources = store.list_sources(sid, type="Y4_CAREER_PROFILE")
    if not meeting_sources or not career_sources:
        return _error("请先上传会议纪要和 Y4 职业兴趣画像报告", 409)

    full = store.get_run_full(run_id) or run
    student = _student_profile(sid)
    career_text = (career_sources[0].get("content")
                   or career_sources[0].get("key_points_confirmed")
                   or career_sources[0].get("key_points_draft") or "")
    quadrant = full.get("quadrant")
    context = {
        "studentName": student["name"],
        "grade": student["grade"],
        "meetingTranscript": meeting_sources[0]["content"][:30000],
        "y4Report": career_text[:30000],
        "meetingUnderstanding": (full.get("understanding") or {}).get("summary"),
        "interests": [{
            "label": item["label"],
            "evidence": item["evidence"],
            "preferenceScore": item["preference_score"],
            "competenceScore": item["competence_score"],
        } for item in full.get("interests", []) if item["status"] != "DISMISSED"],
        "quadrantNarrative": (quadrant["narrative"]
                              if quadrant and quadrant["status"] != "STALE"
                              else None),
        "suggestions": [{
            "title": item["title"],
            "introduction": item["introduction"],
            "growthValue": item["growth_value"],
        } for item in full.get("suggestions", []) if item["status"] != "STALE"],
    }
    question = body.get("question")
    try:
        answer = analysis.ask_growth_talk_copilot(question, context)
    except ValueError as exc:
        return _error_response(exc)
    except analysis.AnalysisError as exc:
        return _error_response(exc)

    store.write_audit(_actor_id(), sid, "growth_talk_copilot_asked", json.dumps(
        {"runId": run_id,
         "questionLength": len(question.strip()) if isinstance(question, str) else 0},
        ensure_ascii=False))
    return jsonify(answer)
