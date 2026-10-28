"""外部 API 蓝图：/api/v1/*（Bearer Key 鉴权，契约不变）。

CORS 由 app.py 的全局 after_request 统一注入（保持对所有 /api/v1/* 响应生效）。
"""
from __future__ import annotations

import json
import os
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

import db as _db
import growth_talk_store as gt_store
import app_utils
from app_utils import (BASE_DIR, Y4_API_KEY, Y4_API_CORS_ORIGINS,
                       Y4_API_RATE_LIMIT, Y4_API_E4_RATE_LIMIT)
from ai_client import (_build_phase1_md_text, _build_y4_payload,
                       _generate_e4_protocol_core,
                       _report_qualification_payload)

bp = Blueprint("api_v1", __name__)


import time as _v1_time
import hmac as _v1_hmac
import hashlib

_E4_CACHE: dict = {}
_E4_CACHE_TTL = int(os.environ.get('Y4_E4_CACHE_TTL', '600'))


def _v1_rate_check(limit: int = Y4_API_RATE_LIMIT, scope: str = 'default') -> bool:
    """外部 API 限流（委托 app_utils.rate_check，与登录限流共用同一实现）。"""
    return app_utils.rate_check(limit, scope)


ERROR_CODES = (
    'UNAUTHORIZED', 'BAD_REQUEST', 'NOT_FOUND',
    'RATE_LIMITED', 'SERVICE_UNAVAILABLE', 'AI_UNAVAILABLE',
)


def _v1_error(code, message, status):
    """返回 /api/v1/* 统一结构化错误信封。"""
    return jsonify({"ok": False, "code": code, "error": message}), status


def _v1_int_id(value, name):
    """校验路径 int 参数为正整数；非法返回 BAD_REQUEST 信封，合法返回 None。"""
    if not isinstance(value, int) or value <= 0:
        return _v1_error("BAD_REQUEST", f"{name} 非法", 400)
    return None


def api_key_required(f):
    """Decorator: require Bearer token for external /api/v1/* endpoints.

    Checks ``Authorization: Bearer <Y4_API_KEY>`` header. Returns 401 JSON if
    missing/invalid. Independent of admin session — safe for server-to-server.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not Y4_API_KEY:
            return _v1_error("SERVICE_UNAVAILABLE",
                             "外部 API 未配置 (Y4_API_KEY 未设置)", 503)
        auth = request.headers.get('Authorization', '')
        token = auth[7:].strip() if auth.startswith('Bearer ') else ''
        if not token or not _v1_hmac.compare_digest(token, Y4_API_KEY):
            return _v1_error("UNAUTHORIZED", "无效的 API Key", 401)
        if not _v1_rate_check():
            return _v1_error("RATE_LIMITED", "请求过于频繁，请稍后再试", 429)
        return f(*args, **kwargs)
    return wrapper




@bp.route('/api/v1/<path:_any>', methods=['OPTIONS'])
def _v1_options(_any):
    """Preflight handler for /api/v1/* CORS."""
    return ('', 204)


@bp.route('/api/v1/health', methods=['GET'])
def v1_health():
    """健康检查端点（无需 API Key，不计入限流）。

    供接入方验证服务连通性与基本可用性；CORS 头由 _apply_v1_cors 注入。
    """
    from datetime import datetime, timezone
    return jsonify({"ok": True, "status": "healthy", "service": "y4-api",
                    "version": "v1",
                    "time": datetime.now(timezone.utc).isoformat()}), 200
@bp.route('/api/v1/students')
@api_key_required
def v1_students():
    """学生列表（含报告数、最新报告日期等摘要）。

    仅返回外部接入方所需的最小字段集；联系方式（email/phone）、
    家庭状况（single_parent）、导师姓名（advisor_name）等敏感 PII 不外泄。
    """
    _V1_STUDENT_FIELDS = ('id', 'name', 'grade', 'school',
                          'report_count', 'latest_report_date')
    students = _db.get_students()
    slim = [{k: s.get(k) for k in _V1_STUDENT_FIELDS} for s in students]
    return jsonify({"ok": True, "students": slim})


@bp.route('/api/v1/students/<int:student_id>/reports')
@api_key_required
def v1_student_reports(student_id):
    """某学生的报告列表。

    仅返回外部接入方所需的摘要字段；pdf_path（服务器文件路径）、
    interpretation（AI 解读全文）不在此端点外泄，后者可通过 y4-json/y4-md 专用端点获取。
    """
    err = _v1_int_id(student_id, 'student_id')
    if err:
        return err
    _V1_REPORT_FIELDS = ('id', 'report_date', 'created_at')
    reports = _db.get_student_reports(student_id)
    slim = [{k: r.get(k) for k in _V1_REPORT_FIELDS} for r in reports]
    # 额外提供 has_interpretation 布尔值，方便接入方判断是否已生成解读。
    for r, orig in zip(slim, reports):
        r['has_interpretation'] = bool(orig.get('interpretation'))
    return jsonify({"ok": True, "reports": slim})


@bp.route('/api/v1/students/<int:student_id>/growth-talk-reports')
@api_key_required
def v1_student_growth_talk_reports(student_id):
    """某学生已确认的 Growth Talk 报告列表（仅摘要字段）。

    DRAFT 报告不对外暴露；未知学生返回空列表。
    """
    err = _v1_int_id(student_id, 'student_id')
    if err:
        return err
    reports = [
        {"id": r["id"], "version": r["version"], "status": r["status"],
         "confirmed_at": r["confirmed_at"], "confirmed_by": r["confirmed_by"]}
        for r in gt_store.list_reports(student_id)
        if r.get("status") == "CONFIRMED"
    ]
    return jsonify({"ok": True, "reports": reports})


@bp.route('/api/v1/growth-talk-reports/<int:report_id>')
@api_key_required
def v1_growth_talk_report(report_id):
    """已确认 Growth Talk 报告详情（payload 原文，DRAFT 视为不存在）。"""
    err = _v1_int_id(report_id, 'report_id')
    if err:
        return err
    report = gt_store.get_report(report_id)
    if not report or report.get("status") != "CONFIRMED":
        return _v1_error("NOT_FOUND", "报告不存在", 404)
    try:
        payload = json.loads(report.get("payload") or "{}")
    except (TypeError, ValueError):
        payload = {}
    return jsonify({"ok": True, "report": payload})


@bp.route('/api/v1/reports/<int:report_id>')
@api_key_required
def v1_report_meta(report_id):
    """报告元数据（不含 raw 全量数据）。"""
    err = _v1_int_id(report_id, 'report_id')
    if err:
        return err
    record = _db.get_report_raw(report_id)
    if not record:
        return _v1_error("NOT_FOUND", "报告不存在", 404)
    meta = {
        "report_id": record["report_id"],
        "student_id": record["student_id"],
        "student_name": record["student_name"],
        "grade": record["grade"],
        "report_date": record["report_date"],
        "has_interpretation": bool(record.get("interpretation")),
    }
    return jsonify({"ok": True, "report": meta})


@bp.route('/api/v1/reports/<int:report_id>/y4-json')
@api_key_required
def v1_report_y4_json(report_id):
    """导出 Y4 JSON（四维数据点 + 常模参照 + AI 解读）。"""
    err = _v1_int_id(report_id, 'report_id')
    if err:
        return err
    payload, err = _report_qualification_payload(report_id)
    if err:
        return _v1_error("NOT_FOUND", err, 404)
    items = payload['items']
    student = payload['student']
    interpretation = payload['report'].get('interpretation') or ''
    student_name = payload['report'].get('student_name') or student.get('name') or '测试'
    y4 = _build_y4_payload(items, interpretation, student, student_name)
    return jsonify({"ok": True, "json": y4})


@bp.route('/api/v1/reports/<int:report_id>/y4-md')
@api_key_required
def v1_report_y4_md(report_id):
    """下载 Y4 Markdown 报告（?include_raw=1 包含原始数据）。"""
    import io as _io
    err = _v1_int_id(report_id, 'report_id')
    if err:
        return err
    _raw_val = request.args.get('include_raw', '0').lower()
    if _raw_val not in ('0', '1', 'true', 'yes', 'false', 'no'):
        return _v1_error("BAD_REQUEST", "include_raw 非法", 400)
    payload, err = _report_qualification_payload(report_id)
    if err:
        return _v1_error("NOT_FOUND", err, 404)
    items = payload['items']
    student = payload['student']
    interpretation = payload['report'].get('interpretation') or ''
    student_name = payload['report'].get('student_name') or student.get('name') or '测试'
    include_raw = _raw_val in ('1', 'true', 'yes')
    md_text = _build_phase1_md_text(items, include_raw, interpretation, student, student_name)
    buf = _io.BytesIO(md_text.encode('utf-8'))
    safe_name = student_name.replace(' ', '').replace('/', '_')
    return send_file(buf, mimetype='text/markdown', as_attachment=True,
                     download_name=f"Y4报告_{safe_name}.md")


@bp.route('/api/v1/reports/<int:report_id>/pdf')
@api_key_required
def v1_report_pdf(report_id):
    """下载 Y4 PDF 报告文件。"""
    err = _v1_int_id(report_id, 'report_id')
    if err:
        return err
    pdf_path_str = _db.get_report_pdf_path(report_id)
    if not pdf_path_str:
        return _v1_error("NOT_FOUND", "报告不存在或无 PDF", 404)
    pdf_path = Path(pdf_path_str)
    if not pdf_path.is_absolute():
        pdf_path = (BASE_DIR / pdf_path).resolve()
    # 路径围栏：解析后必须落在项目目录内，防止越目录读取任意文件。
    try:
        pdf_path.relative_to(BASE_DIR)
    except ValueError:
        return _v1_error("NOT_FOUND", "PDF 路径非法", 404)
    if not pdf_path.exists():
        return _v1_error("NOT_FOUND", "PDF 文件丢失", 404)
    record = _db.get_report_raw(report_id)
    student_name = (record or {}).get('student_name') or 'report'
    safe_name = student_name.replace(' ', '').replace('/', '_')
    return send_file(str(pdf_path), mimetype='application/pdf',
                     as_attachment=True, download_name=f"Y4报告_{safe_name}.pdf")


@bp.route('/api/v1/reports/<int:report_id>/e4-protocol')
@api_key_required
def v1_report_e4_protocol(report_id):
    """生成并下载 E4 协议 Markdown（含跨维度 AI 分析 + 总览）。

    注意：此端点会实时调用 AI 模型生成分析，响应时间可能较长（通常 10-30 秒）。
    查询参数 ?include_raw=1 可在协议中包含原始数据。
    """
    import io as _io
    if not _v1_rate_check(limit=Y4_API_E4_RATE_LIMIT, scope='e4'):
        return _v1_error("RATE_LIMITED", "E4 生成请求过于频繁，请稍后再试", 429)
    err = _v1_int_id(report_id, 'report_id')
    if err:
        return err
    _raw_val = request.args.get('include_raw', '0').lower()
    if _raw_val not in ('0', '1', 'true', 'yes', 'false', 'no'):
        return _v1_error("BAD_REQUEST", "include_raw 非法", 400)
    include_raw = _raw_val in ('1', 'true', 'yes')
    payload, err = _report_qualification_payload(report_id)
    if err:
        return _v1_error("NOT_FOUND", err, 404)
    items = payload['items']
    student = payload['student']
    interpretation = payload['report'].get('interpretation') or ''
    student_name = payload['report'].get('student_name') or student.get('name') or '测试'
    cache_key = (report_id, include_raw)
    interp_hash = hashlib.md5(interpretation.encode('utf-8')).hexdigest()
    now = _v1_time.time()
    cached = _E4_CACHE.get(cache_key)
    if cached and (now - cached[1] < _E4_CACHE_TTL) and cached[2] == interp_hash:
        content_md = cached[0]
        buf = _io.BytesIO(content_md.encode('utf-8'))
        safe_name = student_name.replace(' ', '').replace('/', '_')
        resp = send_file(buf, mimetype='text/markdown', as_attachment=True,
                         download_name=f"E4协议_{safe_name}.md")
        resp.headers['X-Cache'] = 'HIT'
        return resp
    try:
        result = _generate_e4_protocol_core(items, include_raw, interpretation,
                                             student, student_name)
    except Exception:
        return _v1_error("AI_UNAVAILABLE", "AI 服务暂时不可用，请稍后重试", 503)
    content_md = result.get('content_md', '')
    stats = result.get('stats') or {}
    ai_failed = (any(s.get('error') for s in stats.get('step2') or [])
                 or bool((stats.get('step3') or {}).get('error')))
    # AI 步骤失败（如模型 429）时协议缺「判断」：不缓存，让下一次请求重新生成
    if not ai_failed:
        _E4_CACHE[cache_key] = (content_md, now, interp_hash)
    buf = _io.BytesIO(content_md.encode('utf-8'))
    safe_name = student_name.replace(' ', '').replace('/', '_')
    resp = send_file(buf, mimetype='text/markdown', as_attachment=True,
                     download_name=f"E4协议_{safe_name}.md")
    resp.headers['X-Cache'] = 'MISS'
    return resp
