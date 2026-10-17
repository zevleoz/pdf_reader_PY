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
import time
from datetime import datetime

from flask import Blueprint, render_template, session

from app_utils import DATA_DIR, JOB_FILE, role_required
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
    if session.get("role") == "advisor":
        return session.get("advisor_name") or ""
    return None


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
