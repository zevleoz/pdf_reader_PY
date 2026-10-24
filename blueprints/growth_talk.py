"""Growth Talk 蓝图：已确认报告的下载入口。

Growth Talk 1.0 工作区已由 First Touch 取代：旧的页面路由保留 302 跳转，
其余分析/上传/审核路由已移除。报告下载仍供 First Touch 与 360 档案页使用。
"""
from __future__ import annotations

import io
import json
from urllib.parse import quote

from flask import (Blueprint, abort, jsonify, redirect, send_file, session)

import db as _db
import growth_talk_store as store
from app_utils import role_required
from growth_talk import report_contract
from growth_talk.report_pdf import render_report_pdf, report_filename

bp = Blueprint("growth_talk", __name__)


def _error(message: str, status: int):
    return jsonify({"ok": False, "error": message}), status


def _student_or_404(student_id: int) -> dict | None:
    """取学生并做 Advisor 归属校验；不存在或越权都返回 None（路由统一 404）。"""
    student = _db.get_student(student_id)
    if not student:
        return None
    if session.get("role") == "advisor":
        if (student.get("advisor_name") or "") != (session.get("advisor_name") or ""):
            return None
    return student


def _report_or_404(report_id: int):
    report = store.get_report(report_id)
    if not report or report.get("status") != "CONFIRMED":
        return None
    if not _student_or_404(report["student_id"]):
        return None
    return report


# ---------------------------------------------------------------------------
# 页面：旧工作区入口跳转到 First Touch
# ---------------------------------------------------------------------------
@bp.route("/students/<int:sid>/growth-talk")
@role_required("admin", "advisor")
def page_workspace(sid: int):
    if not _student_or_404(sid):
        abort(404)
    return redirect(f"/first-touch/students/{sid}")


# ---------------------------------------------------------------------------
# 报告下载
# ---------------------------------------------------------------------------
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
