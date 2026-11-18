"""发展计划数据层：表、版本、状态机与权限。

三张表挂在 ``db.Base`` 上：

- ``m1_plans``          每个学生每个 Block 一份计划（``(student_id, block_no)`` 唯一）
- ``m1_plan_versions``  内部版 / 家长版的 AI 初稿与导师编辑（``ai_doc`` 永不改动）
- ``m1_plan_files``     个性化需求的上传文件与提取文字

对外函数返回 dict，不泄漏 ORM 实例。本模块不得 import app / blueprints
（生成子进程会直接 import 它）。
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import (Column, DateTime, ForeignKey, Index, Integer, String,
                        Text, or_, select)
from sqlalchemy.orm import Session

import db as _db
import m1.kb as ability_kb
import m1.plan_kb as plan_kb
import m1.report_store as rstore
import m1.store as store

Base = _db.Base

STATUSES = ("inputs", "generating", "review", "approved")
STATUS_LABELS = {
    "inputs": "资料与目标",
    "generating": "生成中",
    "review": "待批准",
    "approved": "已批准",
}
PARENT_STATUSES = ("none", "generating", "draft", "confirmed", "exported")
PARENT_LABELS = {
    "none": "—",
    "generating": "生成中",
    "draft": "草稿 · 待确认",
    "confirmed": "已确认",
    "exported": "已导出",
}
PARTS = ("internal", "parent")
KINDS = ("ai_draft", "edit")
SOURCE_TYPES = ("ai_original", "world_bank", "other")
_SRC_VALUES = ("ai", "edited", "mentor")
# 有 AI 草稿就能开始发展计划（owner 11-12）；draft / generating 还不行。
READY_REPORT_STATUSES = ("ai_draft", "needs_check", "reviewing", "approved",
                         "published")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UPLOAD_ROOT = Path(__file__).resolve().parent.parent / "uploads" / "m1_plans"


# ---------------------------------------------------------------------------
# 模型
# ---------------------------------------------------------------------------
class M1Plan(Base):
    __tablename__ = "m1_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    prep_id = Column(Integer, ForeignKey("m1_preps.id"), nullable=True)
    report_id = Column(Integer, ForeignKey("m1_reports.id"), nullable=True)
    source_mode = Column(String(20), nullable=False, default="report", server_default="report")
    teaching_brief = Column(Text, nullable=False, default="{}", server_default="{}")
    brief_revision = Column(Integer, nullable=False, default=0, server_default="0")
    brief_confirmed_revision = Column(Integer)
    brief_confirmed_by = Column(Integer)
    session_durations = Column(Text, nullable=False, default="[60,60,60]", server_default="[60,60,60]")
    report_version_id = Column(Integer)
    mentor_user_id = Column(Integer, ForeignKey("users.id"))
    block_no = Column(Integer, nullable=False, default=1)
    period_start = Column(String(10), nullable=False, default="")
    period_end = Column(String(10), nullable=False, default="")
    credits = Column(String(20), nullable=False, default="")
    sessions = Column(Integer, nullable=False, default=3)
    wb_grade = Column(Integer)
    inputs = Column(Text, nullable=False, default="{}")
    goals = Column(Text, nullable=False, default="[]")
    personal = Column(Text, nullable=False, default="{}")
    status = Column(String(20), nullable=False, default="inputs")
    parent_status = Column(String(20), nullable=False, default="none")
    current_version_id = Column(Integer)
    parent_version_id = Column(Integer)
    rev = Column(Integer, nullable=False, default=1)
    gen_prev = Column(String(20))
    approved_by = Column(Integer)
    approved_at = Column(DateTime)
    parent_confirmed_by = Column(Integer)
    parent_confirmed_at = Column(DateTime)
    parent_exported_at = Column(DateTime)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ux_m1_plans_student_block", "student_id", "block_no", unique=True),
        Index("ix_m1_plans_prep", "prep_id"),
        Index("ix_m1_plans_mentor", "mentor_user_id"),
    )


class M1PlanVersion(Base):
    __tablename__ = "m1_plan_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey("m1_plans.id"), nullable=False)
    part = Column(String(10), nullable=False, default="internal")
    n = Column(Integer, nullable=False, default=1)
    kind = Column(String(20), nullable=False, default="ai_draft")
    ai_doc = Column(Text)
    doc = Column(Text)
    checks = Column(Text)
    manifest = Column(Text)
    source_version_id = Column(Integer)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_m1_plan_versions_plan_part_n", "plan_id", "part", "n"),
    )


class M1PlanFile(Base):
    __tablename__ = "m1_plan_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey("m1_plans.id"), nullable=False)
    filename = Column(String(300), nullable=False, default="")
    stored_path = Column(String(500), nullable=False, default="")
    text = Column(Text, nullable=False, default="")
    text_status = Column(String(20), nullable=False, default="ok")
    size = Column(Integer, nullable=False, default=0)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_m1_plan_files_plan", "plan_id"),)


class NotFound(Exception):
    """记录不存在。"""


class RevConflict(Exception):
    """``rev`` 与服务器不一致。"""

    def __init__(self, rev: int):
        super().__init__("计划已在别处更新，请刷新后重试")
        self.rev = rev


class StatusError(Exception):
    """当前状态不允许该操作；消息可直接给用户看。"""


def ensure_tables(engine=None) -> None:
    """幂等建表（主要给生成子进程与命令行用；正常启动由 ``init_db`` 建）。"""
    from m1.plan_migration import migrate
    target = engine or _db.engine
    migrate(target)
    Base.metadata.create_all(target, tables=[
        M1Plan.__table__, M1PlanVersion.__table__, M1PlanFile.__table__])
    from m1.plan_activity_proposals import ensure_table
    ensure_table(target)
    from m1.plan_collaboration import ensure_tables as ensure_collaboration
    ensure_collaboration(target)


# ---------------------------------------------------------------------------
# 内部助手
# ---------------------------------------------------------------------------
def _engine():
    return _db.engine


def _dumps(value) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _loads(value, default=None):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _field(value, src: str = "edited") -> Dict[str, str]:
    """``{"text", "src"}``；前端传纯文字时按给的字面值处理。"""
    if isinstance(value, dict):
        text = str(value.get("text") or "").strip()
        kind = value.get("src")
        return {"text": text, "src": kind if kind in _SRC_VALUES else src}
    if value is None:
        return {"text": "", "src": src}
    return {"text": str(value).strip(), "src": src}


def _field_shape(value) -> bool:
    return isinstance(value, dict) and isinstance(value.get("text"), str)


def _is_field(value) -> bool:
    return _field_shape(value)


def _date_ok(value) -> bool:
    return isinstance(value, str) and bool(_DATE_RE.fullmatch(value))


def _check_dates(start: str, end: str) -> None:
    if not _date_ok(start) or not _date_ok(end):
        raise ValueError("阶段周期格式不对")
    try:
        datetime.strptime(start, "%Y-%m-%d")
        datetime.strptime(end, "%Y-%m-%d")
    except ValueError:
        raise ValueError("阶段周期日期不存在")
    if end < start:
        raise ValueError("阶段结束日期不能早于开始日期")


def _ability_codes() -> List[str]:
    return [item.get("code") for item in ability_kb.load_kb().get("abilities") or []]


def _wb_installed() -> bool:
    try:
        from m1 import wb
    except ImportError:
        return False
    return bool(wb.installed())


def _wb_has_lesson(wb_id) -> bool:
    if not isinstance(wb_id, str) or not wb_id.strip():
        return False
    try:
        from m1 import wb
    except ImportError:
        return False
    return bool(wb.lesson(wb_id))


def parse_wb_grade(grade_text: str) -> Optional[int]:
    """把年级文字解析成 5–9 的参考年级；WB 模块没装或解析不了时返回 None。"""
    try:
        from m1 import wb
    except ImportError:
        return None
    try:
        parsed = wb.grade_from_text(grade_text or "")
        return wb.nearest_grade(parsed) if parsed is not None else None
    except Exception:
        return None


def wb_grade_or_default(plan) -> int:
    """WB 参考年级；没填时按 G9（SPEC D4，与生成步骤一致）。"""
    value = (plan or {}).get("wb_grade")
    return int(value) if value is not None else 9


def _student(sess: Session, student_id: int):
    return sess.get(_db.Student, int(student_id))


def report_ready(report) -> bool:
    """会后报告有 AI 草稿即可读取（owner 11-12）；无报告、draft、generating 不行。"""
    return bool(report) and report.get("status") in READY_REPORT_STATUSES


def _report_fingerprint(doc) -> str:
    """版本文档的指纹：规范化 JSON（键排序）的 sha1，用来发现导师的原位修改。"""
    payload = json.dumps(doc if doc is not None else {}, sort_keys=True,
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _version_fingerprint(version_id) -> Optional[str]:
    if not version_id:
        return None
    version = rstore.get_version(int(version_id))
    if version is None:
        return None
    return _report_fingerprint((version or {}).get("doc"))


def _user_name(sess: Session, user_id) -> str:
    if not user_id:
        return ""
    user = sess.get(_db.User, int(user_id))
    if not user:
        return ""
    return user.display_name or user.advisor_name or user.username or ""


def _plan_row(sess: Session, row: M1Plan) -> Dict[str, Any]:
    student = _student(sess, row.student_id)
    parent_version = (sess.get(M1PlanVersion, row.parent_version_id)
                      if row.parent_version_id else None)
    status = row.status or "inputs"
    parent_status = row.parent_status or "none"
    stale = False
    if parent_version is not None:
        stale = (status != "approved"
                 or int(parent_version.source_version_id or 0) != int(row.current_version_id or 0))
    return {
        "id": row.id,
        "student_id": row.student_id,
        "student_name": getattr(student, "name", "") or "",
        "student_code": getattr(student, "student_code", "") or "",
        "grade": getattr(student, "grade", "") or "",
        "school": getattr(student, "school", "") or "",
        "advisor_name": getattr(student, "advisor_name", "") or "",
        "source_mode": row.source_mode or "report",
        "teaching_brief": _loads(row.teaching_brief, {}),
        "brief_revision": row.brief_revision,
        "brief_confirmed_revision": row.brief_confirmed_revision,
        "brief_confirmed_by": row.brief_confirmed_by,
        "session_durations": _loads(row.session_durations, [60, 60, 60]),
        "prep_id": row.prep_id,
        "report_id": row.report_id,
        "report_version_id": row.report_version_id,
        "mentor_user_id": row.mentor_user_id,
        "mentor_name": _user_name(sess, row.mentor_user_id),
        "block_no": int(row.block_no or 1),
        "period_start": row.period_start or "",
        "period_end": row.period_end or "",
        "credits": row.credits or "",
        "sessions": int(row.sessions or 3),
        "wb_grade": row.wb_grade,
        "inputs": _loads(row.inputs, {}) or {},
        "goals": _loads(row.goals, []) or [],
        "personal": _loads(row.personal, {}) or {},
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "parent_status": parent_status,
        "parent_label": PARENT_LABELS.get(parent_status, parent_status),
        "current_version_id": row.current_version_id,
        "parent_version_id": row.parent_version_id,
        "parent_stale": stale,
        "rev": int(row.rev or 1),
        "approved_by": row.approved_by,
        "approved_at": _iso(row.approved_at),
        "parent_confirmed_by": row.parent_confirmed_by,
        "parent_confirmed_at": _iso(row.parent_confirmed_at),
        "parent_exported_at": _iso(row.parent_exported_at),
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _version_row(sess: Session, row: M1PlanVersion) -> Dict[str, Any]:
    return {
        "id": row.id,
        "plan_id": row.plan_id,
        "part": row.part,
        "n": int(row.n or 1),
        "kind": row.kind,
        "ai_doc": _loads(row.ai_doc, None),
        "doc": _activity_text_view(normalize_doc_shape(_loads(row.doc, None))),
        "checks": _loads(row.checks, []) or [],
        "manifest": _loads(row.manifest, {}) or {},
        "source_version_id": row.source_version_id,
        "created_by": row.created_by,
        "created_by_name": _user_name(sess, row.created_by),
        "created_at": _iso(row.created_at),
    }


def _touch(row: M1Plan) -> None:
    row.updated_at = datetime.utcnow()


def _bump(row: M1Plan) -> None:
    row.rev = int(row.rev or 1) + 1
    _touch(row)


def _bump_document(sess: Session, plan_id: int, actor_id=None) -> int:
    """Lifecycle change: invalidate offline section editors (document epoch)."""
    from m1.plan_collaboration import bump_document_in_session
    return bump_document_in_session(sess, plan_id, actor_id)


def _check_rev(row: M1Plan, rev) -> None:
    if int(rev) != int(row.rev or 1):
        raise RevConflict(int(row.rev or 1))


def _ensure_editable(row: M1Plan) -> None:
    if row.status == "approved":
        raise StatusError("内部版已批准，请先重新打开")
    if row.status == "generating":
        raise StatusError("正在生成，请稍后再改")


# ---------------------------------------------------------------------------
# 计划
# ---------------------------------------------------------------------------
def get_plan(plan_id: int) -> Optional[Dict[str, Any]]:
    with Session(_engine()) as sess:
        row = sess.get(M1Plan, int(plan_id))
        return _plan_row(sess, row) if row else None


def create_plan(student_id: int, *, prep_id=None, report_id=None,
                report_version_id=None, mentor_user_id,
                block_no: int, period_start: str, period_end: str,
                credits: str = "", sessions: int = 3,
                wb_grade: Optional[int] = None, created_by=None,
                source_mode="report") -> Dict[str, Any]:
    """新建计划（D2/D7）。报告有 AI 草稿即可，Block 不能重复，课次固定 3。"""
    if isinstance(sessions, bool) or int(sessions) != 3:
        raise ValueError("本轮计划课次固定为 3 节")
    if isinstance(block_no, bool) or not isinstance(block_no, int) or block_no < 1:
        raise ValueError("Block 编号需为 1 或以上")
    if wb_grade is not None and (isinstance(wb_grade, bool)
                                 or not isinstance(wb_grade, int)
                                 or not 5 <= wb_grade <= 9):
        raise ValueError("参考年级需在 G5–G9 之间")
    _check_dates(period_start, period_end)
    if source_mode not in ("report", "mentor_inputs"):
        raise ValueError("source_mode 只能是 report 或 mentor_inputs")
    report, version_id = {}, None
    if source_mode == "report":
        report = rstore.get_report_by_id(report_id) if report_id else None
        if not report or int(report["prep_id"]) != int(prep_id or 0):
            raise ValueError("会后报告不存在")
        prep = store.get_prep(prep_id)
        if not prep or int(prep["student_id"]) != int(student_id):
            raise ValueError("学生与会前准备不匹配")
        if not report_ready(report):
            raise ValueError("会后报告还没有生成 AI 草稿")
        version_id = report_version_id or report.get("current_version_id")
        version = rstore.get_version(version_id) if version_id else None
        if not version or int(version.get("report_id") or 0) != int(report_id):
            raise ValueError("会后报告还没有生成 AI 草稿")
    elif any(v is not None for v in (prep_id, report_id, report_version_id)):
        raise ValueError("直接计划不能关联会前准备或报告")
    with Session(_engine()) as sess:
        if not _student(sess, student_id):
            raise NotFound("学生不存在")
        if source_mode == "mentor_inputs":
            mentor = sess.get(_db.User, int(mentor_user_id)) if mentor_user_id else None
            if not mentor or mentor.role not in ("admin", "advisor"):
                raise ValueError("请选择有效的负责导师")
            settings = _db.effective_account_settings(mentor.role, mentor.student_scope,
                mentor.detail_level, mentor.m1_access, mentor.m1_admin)
            if not settings['m1_access']:
                raise ValueError("负责导师没有心有灵析权限")
            if not store.can_access_student(mentor, student_id):
                raise ValueError("负责导师没有该学生的访问权限")
        existing = sess.execute(select(M1Plan).where(
            M1Plan.student_id == int(student_id),
            M1Plan.block_no == int(block_no))).scalars().first()
        if existing is not None:
            raise ValueError("该 Block 已有发展计划")
        row = M1Plan(
            student_id=int(student_id), source_mode=source_mode, prep_id=prep_id,
            report_id=report_id, report_version_id=version_id,
            mentor_user_id=int(mentor_user_id) if mentor_user_id is not None else None,
            block_no=int(block_no), period_start=period_start, period_end=period_end,
            credits=str(credits or "").strip()[:20], sessions=3,
            wb_grade=int(wb_grade) if wb_grade is not None else None,
            inputs=_dumps({
                "strengths": _field(""), "needs": _field(""),
                "context": _field(""), "interests": _field(""),
                "read_at": datetime.utcnow().isoformat(),
                "report_status_at_read": report.get("status") or "",
                "report_fingerprint": _version_fingerprint(version_id),
            }),
            goals=_dumps([]),
            personal=_dumps({"notes": "", "summary": _field("")}),
            status="inputs", parent_status="none", rev=1,
            created_by=created_by,
        )
        sess.add(row)
        sess.commit()
        sess.refresh(row)
        return _plan_row(sess, row)


def update_header(plan_id: int, rev: int, **fields) -> Dict[str, Any]:
    """改 Block / 阶段周期 / 学分；只在资料与目标、待批准两个状态可用。"""
    allowed = {"block_no", "period_start", "period_end", "credits"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError("不支持的字段：%s" % "、".join(sorted(unknown)))
    with Session(_engine()) as sess:
        row = sess.get(M1Plan, int(plan_id))
        if row is None:
            raise NotFound("发展计划不存在")
        if row.status not in ("inputs", "review"):
            raise StatusError("内部版已批准，请先重新打开")
        _check_rev(row, rev)
        block_no = fields.get("block_no", row.block_no)
        start = fields.get("period_start", row.period_start)
        end = fields.get("period_end", row.period_end)
        if isinstance(block_no, bool) or not isinstance(block_no, int) or block_no < 1:
            raise ValueError("Block 编号需为 1 或以上")
        _check_dates(start, end)
        if int(block_no) != int(row.block_no or 1):
            taken = sess.execute(select(M1Plan).where(
                M1Plan.student_id == row.student_id,
                M1Plan.block_no == int(block_no),
                M1Plan.id != row.id)).scalars().first()
            if taken is not None:
                raise ValueError("该 Block 已有发展计划")
        row.block_no = int(block_no)
        row.period_start = start
        row.period_end = end
        if "credits" in fields:
            row.credits = str(fields.get("credits") or "").strip()[:20]
        _bump(row)
        from m1.plan_collaboration import bump_section_in_session
        bump_section_in_session(sess, plan_id, "header")
        sess.commit()
        sess.refresh(row)
        return _plan_row(sess, row)


def validate_goals(goals) -> List[Dict[str, Any]]:
    """1–3 项、编号来自知识库且不重复；名称永不入库。"""
    if not isinstance(goals, list):
        raise ValueError("目标必须是列表")
    if len(goals) > 3:
        raise ValueError("最多 3 项目标")
    codes = _ability_codes()
    out: List[Dict[str, Any]] = []
    seen = set()
    for index, item in enumerate(goals):
        if not isinstance(item, dict):
            raise ValueError("第 %d 项目标格式不对" % (index + 1))
        code = item.get("code")
        if code not in codes:
            raise ValueError("第 %d 项目标的能力编号无效" % (index + 1))
        if code in seen:
            raise ValueError("目标能力重复：%s" % code)
        seen.add(code)
        out.append({
            "code": code,
            "goal": _field(item.get("goal"), "mentor"),
            "start": _field(item.get("start"), "ai"),
            "expected": _field(item.get("expected"), "ai"),
            "locked": bool(item.get("locked")),
        })
    return out


def save_goals(plan_id: int, rev: int, goals) -> Dict[str, Any]:
    cleaned = validate_goals(goals)
    with Session(_engine()) as sess:
        row = sess.get(M1Plan, int(plan_id))
        if row is None:
            raise NotFound("发展计划不存在")
        _ensure_editable(row)
        _check_rev(row, rev)
        row.goals = _dumps(cleaned)
        _bump(row)
        from m1.plan_collaboration import bump_section_in_session
        bump_section_in_session(sess, plan_id, "goals")
        sess.commit()
        sess.refresh(row)
        return _plan_row(sess, row)


def save_inputs_ai(plan_id: int, values: Dict[str, Any], *, expected_rev=None,
                   actor_id=None) -> Dict[str, Any]:
    """生成子进程写四个 Development Input 字段（``src: ai``）。"""
    if expected_rev is not None:
        plan = get_plan(plan_id)
        if plan is None:
            raise NotFound("发展计划不存在")
        inputs = _loads(plan.get("inputs"), {}) or {}
        report = rstore.get_report_by_id(plan["report_id"]) if plan.get("report_id") else None
        for key in ("strengths", "needs", "context", "interests"):
            if key in values:
                inputs[key] = _field(values.get(key), "ai")
        inputs["read_at"] = datetime.utcnow().isoformat()
        inputs["report_status_at_read"] = (report or {}).get("status") or ""
        inputs["report_fingerprint"] = _version_fingerprint(plan.get("report_version_id"))
        return _save_context(plan_id, expected_rev, {"inputs": _dumps(inputs)},
                             sections=("inputs",), actor_id=actor_id)
    with Session(_engine()) as sess:
        row = sess.get(M1Plan, int(plan_id))
        if row is None:
            raise NotFound("发展计划不存在")
        _ensure_editable(row)
        inputs = _loads(row.inputs, {}) or {}
        report = rstore.get_report_by_id(row.report_id) if row.report_id else None
        for key in ("strengths", "needs", "context", "interests"):
            if key in values:
                inputs[key] = _field(values.get(key), "ai")
        inputs["read_at"] = datetime.utcnow().isoformat()
        inputs["report_status_at_read"] = (report or {}).get("status") or ""
        inputs["report_fingerprint"] = _version_fingerprint(row.report_version_id)
        row.inputs = _dumps(inputs)
        _bump(row)
        from m1.plan_collaboration import bump_section_in_session
        bump_section_in_session(sess, plan_id, "inputs", actor_id)
        sess.commit()
        sess.refresh(row)
        return _plan_row(sess, row)


def save_inputs(plan_id: int, rev: int, values: Dict[str, Any]) -> Dict[str, Any]:
    """导师改四个字段：文字有变化的标为 ``edited``。"""
    if not isinstance(values, dict):
        raise ValueError("inputs 必须是对象")
    unknown = set(values) - {"strengths", "needs", "context", "interests"}
    if unknown:
        raise ValueError("不支持的字段：%s" % "、".join(sorted(unknown)))
    with Session(_engine()) as sess:
        row = sess.get(M1Plan, int(plan_id))
        if row is None:
            raise NotFound("发展计划不存在")
        _ensure_editable(row)
        _check_rev(row, rev)
        inputs = _loads(row.inputs, {}) or {}
        for key in ("strengths", "needs", "context", "interests"):
            if key not in values:
                continue
            incoming = _field(values.get(key), "edited")
            old = inputs.get(key)
            old_text = old.get("text") if isinstance(old, dict) else ""
            if incoming["text"] == (old_text or ""):
                inputs[key] = old if isinstance(old, dict) else _field(old_text)
            else:
                inputs[key] = {"text": incoming["text"], "src": "edited"}
        row.inputs = _dumps(inputs)
        _bump(row)
        from m1.plan_collaboration import bump_section_in_session
        bump_section_in_session(sess, plan_id, "inputs")
        sess.commit()
        sess.refresh(row)
        return _plan_row(sess, row)


def save_personal(plan_id: int, rev: int, notes, summary=None) -> Dict[str, Any]:
    """保存个性化需求；``notes`` 为 ``None`` 时保留原文，``summary`` 有变化才改写。"""
    with Session(_engine()) as sess:
        row = sess.get(M1Plan, int(plan_id))
        if row is None:
            raise NotFound("发展计划不存在")
        _ensure_editable(row)
        _check_rev(row, rev)
        personal = _loads(row.personal, {}) or {}
        if notes is not None:
            personal["notes"] = str(notes or "")
        personal.setdefault("notes", "")
        if summary is not None:
            item = _field(summary, "edited")
            current = (personal.get("summary") or {}).get("text") or ""
            if item["text"] != current:
                personal["summary"] = item
        personal.setdefault("summary", _field(""))
        row.personal = _dumps(personal)
        _bump(row)
        from m1.plan_collaboration import bump_section_in_session
        bump_section_in_session(sess, plan_id, "personal")
        sess.commit()
        sess.refresh(row)
        return _plan_row(sess, row)


def save_personal_summary(plan_id: int, summary, *, expected_rev=None,
                          actor_id=None) -> Dict[str, Any]:
    """生成子进程写个性化需求总结。"""
    if expected_rev is not None:
        plan = get_plan(plan_id)
        if plan is None:
            raise NotFound("发展计划不存在")
        personal = _loads(plan.get("personal"), {}) or {}
        personal["summary"] = _field(summary, "ai")
        personal.setdefault("notes", "")
        return _save_context(plan_id, expected_rev, {"personal": _dumps(personal)},
                             sections=("personal",), actor_id=actor_id)
    with Session(_engine()) as sess:
        row = sess.get(M1Plan, int(plan_id))
        if row is None:
            raise NotFound("发展计划不存在")
        _ensure_editable(row)
        personal = _loads(row.personal, {}) or {}
        personal["summary"] = _field(summary, "ai")
        personal.setdefault("notes", "")
        row.personal = _dumps(personal)
        _bump(row)
        from m1.plan_collaboration import bump_section_in_session
        bump_section_in_session(sess, plan_id, "personal", actor_id)
        sess.commit()
        sess.refresh(row)
        return _plan_row(sess, row)


def save_goal_ai(plan_id: int, code: str, start, expected, *, goal=None,
                 expected_rev=None, actor_id=None) -> Dict[str, Any]:
    """补全目标，保留非空目标及导师编辑；以写入时的最新值为准。"""
    with Session(_engine()) as sess:
        row = sess.get(M1Plan, int(plan_id))
        if row is None:
            raise NotFound("发展计划不存在")
        _ensure_editable(row)
        goals = _loads(row.goals, []) or []
        found = False
        for item in goals:
            if item.get("code") == code:
                for key, value in (("goal", goal), ("start", start), ("expected", expected)):
                    current = _field(item.get(key), "mentor" if key == "goal" else "ai")
                    if key == "goal":
                        replace = not current["text"].strip()
                    else:
                        replace = current["src"] == "ai"
                    if replace and _field(value, "ai")["text"].strip():
                        item[key] = _field(value, "ai")
                found = True
        if not found:
            raise NotFound("没有该目标")
        if expected_rev is not None:
            _check_rev(row, expected_rev)
            return _save_context(plan_id, expected_rev, {'goals': _dumps(goals)},
                                 sections=('goals',), actor_id=actor_id)
        row.goals = _dumps(goals)
        _bump(row)
        from m1.plan_collaboration import bump_section_in_session
        bump_section_in_session(sess, plan_id, "goals", actor_id)
        sess.commit()
        sess.refresh(row)
        return _plan_row(sess, row)


def mark_report_read(plan_id: int, report_version_id: int, *,
                     expected_rev=None, actor_id=None) -> Dict[str, Any]:
    """读取会后报告后记下所读版本、当时的报告状态与文字指纹（D2 / owner 11-12）。"""
    if expected_rev is not None:
        plan = get_plan(plan_id)
        if plan is None:
            raise NotFound("发展计划不存在")
        report = rstore.get_report_by_id(plan["report_id"]) if plan.get("report_id") else None
        inputs = _loads(plan.get("inputs"), {}) or {}
        inputs["read_at"] = datetime.utcnow().isoformat()
        inputs["report_status_at_read"] = (report or {}).get("status") or ""
        inputs["report_fingerprint"] = _version_fingerprint(report_version_id)
        return _save_context(plan_id, expected_rev, {
            "report_version_id": int(report_version_id),
            "inputs": _dumps(inputs)}, sections=("inputs",), actor_id=actor_id)
    with Session(_engine()) as sess:
        row = sess.get(M1Plan, int(plan_id))
        if row is None:
            raise NotFound("发展计划不存在")
        row.report_version_id = int(report_version_id)
        report = rstore.get_report_by_id(row.report_id) if row.report_id else None
        inputs = _loads(row.inputs, {}) or {}
        inputs["read_at"] = datetime.utcnow().isoformat()
        inputs["report_status_at_read"] = (report or {}).get("status") or ""
        inputs["report_fingerprint"] = _version_fingerprint(report_version_id)
        row.inputs = _dumps(inputs)
        _bump(row)
        from m1.plan_collaboration import bump_section_in_session
        bump_section_in_session(sess, plan_id, "inputs", actor_id)
        sess.commit()
        sess.refresh(row)
        return _plan_row(sess, row)


# ---------------------------------------------------------------------------
# 版本
# ---------------------------------------------------------------------------
def add_version(plan_id: int, *, part: str, kind: str = "ai_draft",
                ai_doc=None, doc=None, checks=None, manifest=None,
                source_version_id: Optional[int] = None,
                created_by=None) -> Dict[str, Any]:
    if part not in PARTS:
        raise ValueError("未知版本类型：%s" % part)
    if kind not in KINDS:
        raise ValueError("未知版本类型：%s" % kind)
    with Session(_engine()) as sess:
        plan = sess.get(M1Plan, int(plan_id))
        if plan is None:
            raise NotFound("发展计划不存在")
        last = sess.execute(select(M1PlanVersion.n).where(
            M1PlanVersion.plan_id == int(plan_id),
            M1PlanVersion.part == part).order_by(M1PlanVersion.n.desc())).scalars().first()
        row = M1PlanVersion(
            plan_id=int(plan_id), part=part, n=int(last or 0) + 1, kind=kind,
            ai_doc=_dumps(ai_doc) if ai_doc is not None else None,
            doc=_dumps(doc) if doc is not None else None,
            checks=_dumps(checks) if checks is not None else None,
            manifest=_dumps(manifest) if manifest is not None else None,
            source_version_id=source_version_id, created_by=created_by,
        )
        sess.add(row)
        sess.flush()
        if part == "internal":
            plan.current_version_id = row.id
        else:
            plan.parent_version_id = row.id
        _bump(plan)
        data = _version_row(sess, row)
        sess.commit()
        return data


def get_version(version_id: int) -> Optional[Dict[str, Any]]:
    with Session(_engine()) as sess:
        row = sess.get(M1PlanVersion, int(version_id))
        return _version_row(sess, row) if row else None


def current_version(plan_id: int, part: str = "internal") -> Optional[Dict[str, Any]]:
    with Session(_engine()) as sess:
        plan = sess.get(M1Plan, int(plan_id))
        if plan is None:
            return None
        version_id = (plan.current_version_id if part == "internal"
                      else plan.parent_version_id)
        if not version_id:
            return None
        row = sess.get(M1PlanVersion, int(version_id))
        return _version_row(sess, row) if row else None


def internal_print_snapshot(plan_id: int) -> Optional[Dict[str, Any]]:
    """单节教案打印用的连贯只读快照。

    部署环境使用 Python ``sqlite3`` 的 legacy 事务模式：SELECT 不会自动
    开启 DBAPI 事务，SQLAlchemy 的逻辑事务也不等于 sqlite3 的读事务。
    因此这里在**第一条 SELECT 之前**显式执行 ``BEGIN``，让后续计划头、
    目标、状态、当前版本、文档和 document epoch 全部落在同一个真实读事务
    里：

    - WAL：读事务在第一条 SELECT 时固定快照，其他连接的写入可以继续提交，
      但本事务始终读到同一修订；不会出现“旧 rev + 新文档”。
    - rollback-journal：读事务持有 SHARED 锁，写入方可以写但不一定能立刻
      提交；打印是只读短事务，结束时立即 rollback 释放锁。

    事务由 ``finally`` 中的 ``rollback`` 结束（不写库、不建快照表），连接
    随后归还连接池。这里刻意不复用 ``_plan_page_context()``：后者会多次
    开启新事务，无法保证打印前置条件与页面内容属于同一修订。
    """
    from m1.plan_collaboration import _document_version

    engine = _engine()
    sqlite = str(engine.url).startswith("sqlite")
    with Session(engine) as sess:
        if sqlite:
            sess.connection().exec_driver_sql("BEGIN")
        try:
            row = sess.get(M1Plan, int(plan_id))
            if row is None:
                return None
            plan = _plan_row(sess, row)
            version = None
            if row.current_version_id:
                vrow = sess.get(M1PlanVersion, int(row.current_version_id))
                if (vrow is not None and vrow.part == "internal"
                        and int(vrow.plan_id) == int(plan_id)):
                    version = _version_row(sess, vrow)
            return {
                "plan": plan,
                "internal": version,
                "document_version": _document_version(sess, plan_id),
            }
        finally:
            if sqlite:
                sess.rollback()


def list_versions(plan_id: int) -> List[Dict[str, Any]]:
    """历史版本：编号、类型、时间、谁（README deviation 5）。"""
    with Session(_engine()) as sess:
        rows = sess.execute(select(M1PlanVersion).where(
            M1PlanVersion.plan_id == int(plan_id))
            .order_by(M1PlanVersion.part, M1PlanVersion.n)).scalars().all()
        return [{"id": row.id, "part": row.part, "n": int(row.n or 1),
                 "kind": row.kind, "created_by": row.created_by,
                 "created_by_name": _user_name(sess, row.created_by),
                 "created_at": _iso(row.created_at)}
                for row in rows]


def _prepare_part(sess: Session, plan: M1Plan, part: str, doc, checks,
                  actor_id=None) -> Dict[str, Any]:
    """Create or update the editable version for ``part`` without touching the plan row.

    Callers hold the plan write lock (collaboration) or a revision CAS (legacy
    save). ``ai_doc`` is never modified.
    """
    if part == "internal":
        _ensure_editable(plan)
        version_id = plan.current_version_id
    else:
        if plan.parent_version_id is None:
            raise StatusError("家长版还没有生成")
        if plan.parent_status == "generating":
            raise StatusError("正在生成，请稍后再改")
        version_id = plan.parent_version_id
    if not version_id:
        raise StatusError("内部版还没有生成")
    current = sess.get(M1PlanVersion, int(version_id))
    if current is None:
        raise NotFound("计划版本不存在")
    if current.kind == "edit":
        current.doc = _dumps(doc)
        if checks is not None:
            current.checks = _dumps(checks)
        sess.flush()
        return {"version_id": current.id, "ai_doc": _loads(current.ai_doc, None)}
    row = M1PlanVersion(
        plan_id=int(plan.id), part=part, n=int(current.n or 1) + 1,
        kind="edit", ai_doc=current.ai_doc, doc=_dumps(doc),
        checks=_dumps(checks) if checks is not None else current.checks,
        manifest=current.manifest, source_version_id=current.source_version_id,
        created_by=actor_id if actor_id is not None else current.created_by,
    )
    sess.add(row)
    sess.flush()
    return {"version_id": row.id, "ai_doc": _loads(row.ai_doc, None)}


def _save_part(plan_id: int, rev: int, part: str, doc, checks,
               actor_id=None) -> Dict[str, Any]:
    from sqlalchemy import update
    with Session(_engine()) as sess:
        plan = sess.get(M1Plan, int(plan_id))
        if plan is None:
            raise NotFound("发展计划不存在")
        _check_rev(plan, rev)
        prepared = _prepare_part(sess, plan, part, doc, checks, actor_id)
        values = {"rev": int(rev) + 1, "updated_at": datetime.utcnow()}
        if part == "internal":
            values["current_version_id"] = prepared["version_id"]
        else:
            values["parent_version_id"] = prepared["version_id"]
            if plan.parent_status in ("confirmed", "exported"):
                values["parent_status"] = "draft"
        conditions = [M1Plan.id == int(plan_id), M1Plan.rev == int(rev)]
        if part == "internal":
            conditions.append(M1Plan.status.in_(("inputs", "review")))
        result = sess.execute(update(M1Plan).where(*conditions).values(**values),
                              execution_options={"synchronize_session": False})
        if result.rowcount != 1:
            sess.rollback()
            fresh = get_plan(plan_id)
            raise RevConflict(int((fresh or {}).get("rev") or rev))
        result = {"rev": int(rev) + 1, "version_id": prepared["version_id"],
                  "status": plan.status,
                  "parent_status": values.get("parent_status", plan.parent_status),
                  "ai_doc": prepared["ai_doc"]}
        sess.commit()
        return result


def save_internal(plan_id: int, rev: int, doc, checks=None,
                  actor_id=None) -> Dict[str, Any]:
    """保存内部版：最新版本是 AI 初稿时先复制成 edit 版，``ai_doc`` 永不改动。"""
    return _save_part(plan_id, rev, "internal", doc, checks, actor_id=actor_id)


def save_parent(plan_id: int, rev: int, doc, checks=None,
                actor_id=None) -> Dict[str, Any]:
    """保存家长版；已确认 / 已导出的状态改回草稿。"""
    return _save_part(plan_id, rev, "parent", doc, checks, actor_id=actor_id)


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------
def report_state(plan_or_id) -> Dict[str, Any]:
    """会后报告当前状态与计划所读内容是否一致（Q2 / owner 11-12）。"""
    plan = plan_or_id if isinstance(plan_or_id, dict) else get_plan(plan_or_id)
    if not plan:
        raise NotFound("发展计划不存在")
    if plan.get("source_mode") == "mentor_inputs":
        return {"applicable": False, "fresh": True, "status": "", "label": "导师输入",
                "current_version_id": None, "report_version_id": None}
    report = rstore.get_report_by_id(plan["report_id"]) if plan.get("report_id") else None
    inputs = plan.get("inputs") or {}
    same_version = bool(report) \
        and int(report.get("current_version_id") or 0) == int(plan.get("report_version_id") or 0)
    # 状态变化（审核、发布）不改文字，不算过期；只有同一版本的文字变了才过期。
    stored = inputs.get("report_fingerprint")
    same_text = (not stored) or (same_version and stored == _version_fingerprint(
        (report or {}).get("current_version_id")))
    fresh = report_ready(report) and same_version and same_text
    return {
        "status": (report or {}).get("status", ""),
        "label": (report or {}).get("label", ""),
        "current_version_id": (report or {}).get("current_version_id"),
        "report_version_id": plan.get("report_version_id"),
        "fresh": bool(fresh),
        "read_at": inputs.get("read_at", ""),
        "status_at_read": inputs.get("report_status_at_read", ""),
    }


def generate_blockers(plan_or_id, *, use_old_report: bool = False) -> List[str]:
    """生成前的规则（DP1 §3）；返回可直接给导师看的提示，空列表表示可以生成。"""
    plan = plan_or_id if isinstance(plan_or_id, dict) else get_plan(plan_or_id)
    if not plan:
        raise NotFound("发展计划不存在")
    blockers: List[str] = []
    goals = plan.get("goals") or []
    if not 1 <= len(goals) <= 3:
        blockers.append("需要 1 到 3 项已锁定目标")
    elif any(not item.get("locked") for item in goals):
        blockers.append("目标需要先锁定")
    missing = [str(item.get("code") or "") for item in goals
               if not ((item.get("goal") or {}).get("text") or "").strip()]
    if missing:
        blockers.append("%s 的发展目标还没写" % "、".join(missing))
    if plan.get("source_mode") == "mentor_inputs":
        brief = plan.get("teaching_brief") or {}
        if plan.get("brief_confirmed_revision") != plan.get("brief_revision") or not plan.get("brief_revision"):
            blockers.append("请确认当前教学简报")
        for key, label in (("learning_need", "明确的学习需要"), ("current_situation", "具体的当前情境"), ("current_response", "学生当前反应或起点")):
            item = brief.get(key) or {}
            if not item.get("text", "").strip() or not item.get("use_for_teaching"):
                blockers.append("请补充并授权用于教学：" + label)
        return blockers
    inputs = plan.get("inputs") or {}
    if not any(((inputs.get(key) or {}).get("text") or "").strip()
               for key in ("strengths", "needs", "context", "interests")):
        blockers.append("学生资料还是空的，请先读取会后报告")
    if not use_old_report and not report_state(plan)["fresh"]:
        blockers.append("会后报告已更新，请先重新读取或选择继续使用旧版本")
    return blockers


def begin_generation(plan_id: int, part: str = "internal") -> str:
    """进入生成中，返回原状态（失败时还原用）。"""
    if part not in PARTS:
        raise ValueError("未知版本类型：%s" % part)
    with Session(_engine()) as sess:
        plan = sess.get(M1Plan, int(plan_id))
        if plan is None:
            raise NotFound("发展计划不存在")
        if part == "internal":
            if plan.status == "generating":
                raise StatusError("生成任务已在进行中")
            if plan.status not in ("inputs", "review"):
                raise StatusError("内部版已批准，请先重新打开")
            previous = plan.status
            plan.status = "generating"
        else:
            if plan.status != "approved":
                raise StatusError("请先批准内部版")
            if plan.parent_status == "generating":
                raise StatusError("生成任务已在进行中")
            previous = plan.parent_status or "none"
            plan.parent_status = "generating"
        plan.gen_prev = previous
        _bump(plan)
        _bump_document(sess, plan_id)
        sess.commit()
        return previous


def finish_generation(plan_id: int, part: str = "internal", *,
                      version_id: Optional[int] = None,
                      status: Optional[str] = None) -> Dict[str, Any]:
    """生成成功：内部版进待批准，家长版进草稿；可选地绑定新版本。"""
    if part not in PARTS:
        raise ValueError("未知版本类型：%s" % part)
    with Session(_engine()) as sess:
        plan = sess.get(M1Plan, int(plan_id))
        if plan is None:
            raise NotFound("发展计划不存在")
        if version_id:
            if part == "internal":
                plan.current_version_id = int(version_id)
            else:
                plan.parent_version_id = int(version_id)
        if part == "internal":
            plan.status = status if status in ("review", "approved") else "review"
        else:
            plan.parent_status = status if status in ("draft", "confirmed") else "draft"
        plan.gen_prev = None
        _bump(plan)
        _bump_document(sess, plan_id)
        sess.commit()
        sess.refresh(plan)
        return _plan_row(sess, plan)


def fail_generation(plan_id: int, part: str = "internal",
                    previous: Optional[str] = None) -> Dict[str, Any]:
    """生成失败：还原到生成前的状态。"""
    if part not in PARTS:
        raise ValueError("未知版本类型：%s" % part)
    with Session(_engine()) as sess:
        plan = sess.get(M1Plan, int(plan_id))
        if plan is None:
            raise NotFound("发展计划不存在")
        fallback = previous or plan.gen_prev
        if part == "internal":
            if fallback not in STATUSES or fallback == "generating":
                fallback = "review" if plan.current_version_id else "inputs"
            plan.status = fallback
        else:
            if fallback not in PARENT_STATUSES or fallback == "generating":
                fallback = "draft" if plan.parent_version_id else "none"
            plan.parent_status = fallback
        plan.gen_prev = None
        _bump(plan)
        _bump_document(sess, plan_id)
        sess.commit()
        sess.refresh(plan)
        return _plan_row(sess, plan)


def approve(plan_id: int, user_id=None) -> Dict[str, Any]:
    """待批准 → 已批准。需要核对的问题不挡批准。"""
    with Session(_engine()) as sess:
        plan = sess.get(M1Plan, int(plan_id))
        if plan is None:
            raise NotFound("发展计划不存在")
        if plan.status != "review":
            raise StatusError("当前状态不能批准内部版")
        plan.status = "approved"
        plan.approved_by = int(user_id) if user_id is not None else None
        plan.approved_at = datetime.utcnow()
        _bump(plan)
        _bump_document(sess, plan_id, user_id)
        sess.commit()
        sess.refresh(plan)
        return _plan_row(sess, plan)


def reopen(plan_id: int, user_id=None) -> Dict[str, Any]:
    """已批准 → 待批准；复制出一个新的 edit 版本，家长版据此判为过期。"""
    with Session(_engine()) as sess:
        plan = sess.get(M1Plan, int(plan_id))
        if plan is None:
            raise NotFound("发展计划不存在")
        if plan.status != "approved":
            raise StatusError("只有已批准的内部版才能重新打开")
        current = (sess.get(M1PlanVersion, plan.current_version_id)
                   if plan.current_version_id else None)
        row = M1PlanVersion(
            plan_id=int(plan_id), part="internal",
            n=int((current.n if current else 0) or 0) + 1, kind="edit",
            ai_doc=current.ai_doc if current else None,
            doc=current.doc if current else None,
            checks=current.checks if current else None,
            manifest=current.manifest if current else None,
            created_by=int(user_id) if user_id is not None else None,
        )
        sess.add(row)
        sess.flush()
        plan.current_version_id = row.id
        plan.status = "review"
        plan.approved_by = None
        plan.approved_at = None
        _bump(plan)
        _bump_document(sess, plan_id, user_id)
        sess.commit()
        sess.refresh(plan)
        return _plan_row(sess, plan)


def confirm_parent(plan_id: int, user_id=None) -> Dict[str, Any]:
    """草稿 → 已确认；内部版不是已批准或家长版过期时拒绝。"""
    with Session(_engine()) as sess:
        plan = sess.get(M1Plan, int(plan_id))
        if plan is None:
            raise NotFound("发展计划不存在")
        if plan.status != "approved":
            raise StatusError("请先批准内部版")
        if plan.parent_status != "draft":
            raise StatusError("当前状态不能确认家长版")
        if _parent_stale(sess, plan):
            raise StatusError("内部版已更改，请重新生成家长版")
        plan.parent_status = "confirmed"
        plan.parent_confirmed_by = int(user_id) if user_id is not None else None
        plan.parent_confirmed_at = datetime.utcnow()
        _bump(plan)
        sess.commit()
        sess.refresh(plan)
        return _plan_row(sess, plan)


def export_parent(plan_id: int, user_id=None) -> Dict[str, Any]:
    """已确认 / 已导出 → 已导出；过期或状态不对时拒绝。"""
    with Session(_engine()) as sess:
        plan = sess.get(M1Plan, int(plan_id))
        if plan is None:
            raise NotFound("发展计划不存在")
        if plan.parent_status not in ("confirmed", "exported"):
            raise StatusError("请先确认家长版")
        if plan.status != "approved":
            raise StatusError("请先批准内部版")
        if _parent_stale(sess, plan):
            raise StatusError("内部版已更改，请重新生成家长版")
        plan.parent_status = "exported"
        plan.parent_exported_at = datetime.utcnow()
        _bump(plan)
        sess.commit()
        sess.refresh(plan)
        return _plan_row(sess, plan)


def _parent_stale(sess: Session, plan: M1Plan) -> bool:
    if not plan.parent_version_id:
        return False
    version = sess.get(M1PlanVersion, plan.parent_version_id)
    if version is None:
        return False
    return (plan.status != "approved"
            or int(version.source_version_id or 0) != int(plan.current_version_id or 0))


# ---------------------------------------------------------------------------
# 文件
# ---------------------------------------------------------------------------
def plan_upload_dir(plan_id: int) -> Path:
    return _UPLOAD_ROOT / str(int(plan_id))


def add_file(plan_id: int, *, filename: str, stored_path: str = "", text: str = "",
             text_status: str = "ok", size: int = 0, created_by=None) -> Dict[str, Any]:
    with Session(_engine()) as sess:
        if sess.get(M1Plan, int(plan_id)) is None:
            raise NotFound("发展计划不存在")
        row = M1PlanFile(plan_id=int(plan_id), filename=filename or "",
                         stored_path=stored_path or "", text=text or "",
                         text_status=text_status if text_status in (
                             "ok", "partial", "unreadable") else "ok",
                         size=int(size or 0), created_by=created_by)
        sess.add(row)
        sess.commit()
        return {"id": row.id, "plan_id": row.plan_id, "filename": row.filename,
                "stored_path": row.stored_path, "text": row.text,
                "text_status": row.text_status, "size": row.size,
                "created_by": row.created_by, "created_at": _iso(row.created_at)}


def list_files(plan_id: int) -> List[Dict[str, Any]]:
    """文件列表（不含提取的文字，原文只留在平台内）。"""
    with Session(_engine()) as sess:
        rows = sess.execute(select(M1PlanFile).where(
            M1PlanFile.plan_id == int(plan_id)).order_by(M1PlanFile.id)).scalars().all()
        return [{"id": row.id, "filename": row.filename, "text_status": row.text_status,
                 "size": int(row.size or 0), "created_at": _iso(row.created_at)}
                for row in rows]


def get_file(file_id: int) -> Optional[Dict[str, Any]]:
    with Session(_engine()) as sess:
        row = sess.get(M1PlanFile, int(file_id))
        if row is None:
            return None
        return {"id": row.id, "plan_id": row.plan_id, "filename": row.filename,
                "stored_path": row.stored_path, "text": row.text,
                "text_status": row.text_status, "size": int(row.size or 0)}


def delete_file(file_id: int) -> Dict[str, Any]:
    with Session(_engine()) as sess:
        row = sess.get(M1PlanFile, int(file_id))
        if row is None:
            raise NotFound("文件不存在")
        data = {"id": row.id, "plan_id": row.plan_id, "stored_path": row.stored_path}
        sess.delete(row)
        sess.commit()
        return data


# ---------------------------------------------------------------------------
# 校验文档
# ---------------------------------------------------------------------------
def _need_field(value, label: str) -> None:
    if not _is_field(value):
        raise ValueError("%s格式不正确" % label)


def _legacy_list_text(value):
    """Decode only serialized lists of strings / text fields; leave prose intact."""
    if not isinstance(value, str) or not value.strip().startswith("[") or not value.strip().endswith("]"):
        return value
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        try:
            parsed = ast.literal_eval(value.strip())
        except (ValueError, SyntaxError, TypeError, RecursionError):
            return value
    if not isinstance(parsed, list) or not all(
        isinstance(item, str) or (isinstance(item, dict) and isinstance(item.get("text"), str))
        for item in parsed
    ):
        return value
    return "\n".join(text for item in parsed
                     if (text := (item if isinstance(item, str) else item["text"]).strip()))


def _activity_text_view(doc):
    """Read-time compatibility only: never rewrite persisted version snapshots."""
    if not isinstance(doc, dict):
        return doc
    for session in doc.get("sessions") or []:
        if not isinstance(session, dict):
            continue
        for activity in session.get("activities") or []:
            if not isinstance(activity, dict):
                continue
            for key in ("steps", "questions"):
                field = activity.get(key)
                if isinstance(field, dict):
                    field["text"] = _legacy_list_text(field.get("text"))
    return doc


def normalize_doc_shape(doc):
    """把旧 AI 初稿里 ``review`` 的纯字符串补成 ``{text, src}`` 字段。

    DP3 流水线早期把“上次实践回顾”问题写成了字符串，而 DP1 的校验和编辑器
    都按字段（``.text``）读写；这里在读和保存时统一形状，旧数据不必迁移。
    """
    if not isinstance(doc, dict):
        return doc
    sessions = doc.get("sessions")
    if not isinstance(sessions, list):
        return doc
    for session in sessions:
        if not isinstance(session, dict):
            continue
        review = session.get("review")
        if not isinstance(review, list):
            continue
        session["review"] = [
            {"text": item, "src": "ai"} if isinstance(item, str) else item
            for item in review
        ]
    return doc


def validate_internal_doc(plan: Dict[str, Any], doc) -> None:
    """DP1 §2.4 的形状与引用规则。"""
    if not isinstance(doc, dict):
        raise ValueError("内部版格式不正确")
    _need_field(doc.get("overview"), "Block Overview")
    goals = plan.get("goals") or []
    codes = [item.get("code") for item in goals]
    sessions = doc.get("sessions")
    expected = int(plan.get("sessions") or 3)
    if not isinstance(sessions, list) or len(sessions) != expected:
        raise ValueError("内部版必须有 %d 节课" % expected)
    platforms = plan_kb.platforms()
    seen_ids = set()
    review_hits = []
    for index, session in enumerate(sessions):
        n = index + 1
        if not isinstance(session, dict):
            raise ValueError("第 %d 节课格式不正确" % n)
        if session.get("n") != n:
            raise ValueError("第 %d 节课的编号不对" % n)
        _need_field(session.get("title"), "第 %d 节课标题" % n)
        review = session.get("review")
        if not isinstance(review, list):
            raise ValueError("第 %d 节课的上次实践回顾格式不正确" % n)
        if n == 1 and review:
            raise ValueError("第 1 节课没有上次实践回顾")
        if n > 1 and not 2 <= len(review) <= 3:
            raise ValueError("第 %d 节课需要 2 到 3 个上次实践回顾问题" % n)
        for question in review:
            _need_field(question, "第 %d 节课的回顾问题" % n)
        focus = session.get("focus")
        if not isinstance(focus, dict):
            raise ValueError("第 %d 节课的教学重点格式不正确" % n)
        if focus.get("primary") not in codes:
            raise ValueError("第 %d 节课的主要目标不在已确认目标里" % n)
        supporting = focus.get("supporting")
        if supporting not in (None, "") and supporting not in codes:
            raise ValueError("第 %d 节课的辅助目标不在已确认目标里" % n)
        _need_field(focus.get("text"), "第 %d 节课的教学重点" % n)
        content = session.get("content")
        if not isinstance(content, dict):
            raise ValueError("第 %d 节课的核心学习内容格式不正确" % n)
        for key in ("mindsets", "skills", "techniques"):
            _need_field(content.get(key), "第 %d 节课的 %s" % (n, key))
        activities = session.get("activities")
        if not isinstance(activities, list) or not activities:
            raise ValueError("第 %d 节课至少需要一个教学活动" % n)
        for position, activity in enumerate(activities):
            label = "第 %d 节课的第 %d 个活动" % (n, position + 1)
            if not isinstance(activity, dict):
                raise ValueError("%s格式不正确" % label)
            activity_id = activity.get("id")
            if not isinstance(activity_id, str) or not activity_id.strip():
                raise ValueError("%s缺少编号" % label)
            if activity_id in seen_ids:
                raise ValueError("教学活动编号重复：%s" % activity_id)
            seen_ids.add(activity_id)
            _need_field(activity.get("name"), "%s名称" % label)
            minutes = activity.get("minutes")
            if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
                raise ValueError("%s时长必须是分钟数" % label)
            for key, text in (("steps", "教学流程"), ("questions", "引导问题"),
                              ("materials", "所需材料")):
                _need_field(activity.get(key), "%s%s" % (label, text))
            source = activity.get("source")
            if not isinstance(source, dict) or source.get("type") not in SOURCE_TYPES:
                raise ValueError("%s的参考来源无效" % label)
            if source["type"] == "world_bank" and not _wb_has_lesson(source.get("wb_id")):
                raise ValueError("%s的 WB 参考课不在资料库里" % label)
            if source["type"] == "other" and not str(source.get("text") or "").strip():
                raise ValueError("%s选了其他参考，需要填写来源" % label)
            if activity.get("block_review"):
                review_hits.append((n, position, len(activities)))
        _need_field(session.get("evidence"), "第 %d 节课的课堂预期表现" % n)
        practice = session.get("practice")
        if not isinstance(practice, list) or not practice:
            raise ValueError("第 %d 节课至少需要一项课后实践" % n)
        for position, item in enumerate(practice):
            label = "第 %d 节课的第 %d 项实践" % (n, position + 1)
            if not isinstance(item, dict):
                raise ValueError("%s格式不正确" % label)
            practice_id = item.get("id")
            if not isinstance(practice_id, str) or not practice_id.strip():
                raise ValueError("%s缺少编号" % label)
            if practice_id in seen_ids:
                raise ValueError("课后实践编号重复：%s" % practice_id)
            seen_ids.add(practice_id)
            if item.get("code") not in codes:
                raise ValueError("%s的关联目标不在已确认目标里" % label)
            if item.get("platform") not in platforms:
                raise ValueError("%s的平台只能是：%s" % (label, " / ".join(platforms)))
            for key, text in (("name", "名称"), ("task", "任务"),
                              ("frequency", "频率"), ("evidence", "预期证据")):
                _need_field(item.get(key), "%s的%s" % (label, text))
        next_prep = session.get("next_prep")
        if n == expected:
            if next_prep is not None:
                raise ValueError("最后一节课没有下次课准备")
        else:
            _need_field(next_prep, "第 %d 节课的下次课准备" % n)
    if len(review_hits) != 1:
        raise ValueError("最后一节课需要且只需要一个 Block Review")
    n, position, total = review_hits[0]
    if n != expected or position != total - 1:
        raise ValueError("Block Review 必须是最后一节课的最后一个活动")
    if doc.get("mentor_notes") is not None:
        _need_field(doc.get("mentor_notes"), "导师备注")


def validate_parent_doc(plan: Dict[str, Any], doc) -> None:
    """DP1 §2.5 的形状；目标编号与顺序必须和计划一致。"""
    if not isinstance(doc, dict):
        raise ValueError("家长版格式不正确")
    if len(json.dumps(doc, ensure_ascii=False)) > plan_kb.PARENT_PAYLOAD_LIMIT:
        raise ValueError("家长版内容超过 %d 字符技术上限，请精简后保存；内容未截断"
                         % plan_kb.PARENT_PAYLOAD_LIMIT)
    _need_field(doc.get("intro"), "开场介绍")
    _need_field(doc.get("transition"), "过渡句")
    codes = [item.get("code") for item in plan.get("goals") or []]
    goals = doc.get("goals")
    if not isinstance(goals, list) or [item.get("code") for item in goals
                                       if isinstance(item, dict)] != codes:
        raise ValueError("家长版目标必须与已确认的目标一致")
    for index, item in enumerate(goals):
        if not isinstance(item, dict):
            raise ValueError("第 %d 个目标格式不正确" % (index + 1))
        _need_field(item.get("text"), "第 %d 个目标说明" % (index + 1))
    sessions = doc.get("sessions")
    if not isinstance(sessions, list) or len(sessions) != 3:
        raise ValueError("家长版必须有三节课")
    for index, session in enumerate(sessions):
        n = index + 1
        if not isinstance(session, dict) or session.get("n") != n:
            raise ValueError("第 %d 节课的编号不对" % n)
        _need_field(session.get("title"), "第 %d 节课标题" % n)
        _need_field(session.get("summary"), "第 %d 节课摘要" % n)
    platforms = plan_kb.platforms()
    options = doc.get("practice_options")
    if not isinstance(options, list):
        raise ValueError("课后实践列表格式不正确")
    refs = []
    for index, item in enumerate(options):
        if not isinstance(item, dict):
            raise ValueError("第 %d 项实践格式不正确" % (index + 1))
        ref = item.get("ref")
        if not isinstance(ref, str) or not ref.strip():
            raise ValueError("第 %d 项实践缺少编号" % (index + 1))
        if ref in refs:
            raise ValueError("课后实践编号重复：%s" % ref)
        refs.append(ref)
        if item.get("platform") not in platforms:
            raise ValueError("第 %d 项实践的平台无效" % (index + 1))
        for key, text in (("title", "名称"), ("text", "说明"),
                          ("frequency", "频率")):
            _need_field(item.get(key), "第 %d 项实践的%s" % (index + 1, text))
    picked = doc.get("practice")
    if not isinstance(picked, list) or len(picked) > 2:
        raise ValueError("课后实践最多选 2 项")
    for ref in picked:
        if ref not in refs:
            raise ValueError("选中的实践不在家长版实践列表里")
    family = doc.get("family")
    if not isinstance(family, list) or len(family) != 2:
        raise ValueError("家庭协作需要 2 条建议")
    for index, line in enumerate(family):
        _need_field(line, "第 %d 条家庭建议" % (index + 1))
    seen = doc.get("family_seen", [False, False])
    if not isinstance(seen, list) or len(seen) != 2 \
            or any(not isinstance(flag, bool) for flag in seen):
        raise ValueError("家庭建议的已看过标记格式不正确")
    ack = doc.get("family_ack")
    if ack is not None:
        if not isinstance(ack, list) or len(ack) != 2:
            raise ValueError("家庭建议的确认绑定格式不正确")
        for item in ack:
            if not isinstance(item, dict) or set(item) - {"hash", "seen"}:
                raise ValueError("家庭建议的确认绑定格式不正确")
            if not isinstance(item.get("hash"), str) or not item.get("hash"):
                raise ValueError("家庭建议的确认绑定缺少文字指纹")
            if not isinstance(item.get("seen"), bool):
                raise ValueError("家庭建议的确认绑定状态不正确")
    review = doc.get("review")
    if not isinstance(review, list) or not 2 <= len(review) <= 4:
        raise ValueError("成长观察需要 2 到 4 项")
    for index, item in enumerate(review):
        if not isinstance(item, dict):
            raise ValueError("第 %d 项成长观察格式不正确" % (index + 1))
        _need_field(item.get("label"), "第 %d 项成长观察标签" % (index + 1))
        _need_field(item.get("text"), "第 %d 项成长观察说明" % (index + 1))


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------
def is_team_member(user, student_id) -> bool:
    """该账号是否是这位学生 M1 计划团队的共同导师（账号须启用）。"""
    if student_id is None:
        return False
    from m1.plan_collaboration import _is_team_member
    return _is_team_member(store._user_dict(user), student_id)


def can_view_plan(user, plan) -> bool:
    """原有学生 / 会前准备可见范围，或该学生计划团队的共同导师。不存在返回 False。"""
    if plan is None:
        return False
    if isinstance(plan, int):
        plan = get_plan(plan)
    if not plan:
        return False
    if plan.get("source_mode") == "mentor_inputs":
        allowed = store.can_access_student(user, plan["student_id"])
    else:
        allowed = store.can_access_prep(user, plan.get("prep_id"))
    if allowed:
        return True
    return is_team_member(user, plan.get("student_id"))


def can_edit_plan(user, plan) -> bool:
    """admin、心有灵析管理账号、负责导师本人，或该学生计划团队的共同导师。"""
    if plan is None:
        return False
    if isinstance(plan, int):
        plan = get_plan(plan)
    if not plan:
        return False
    u = store._user_dict(user)
    if plan.get("source_mode") == "mentor_inputs" and not can_view_plan(u, plan):
        return False
    if u.get("role") == "admin" or store.is_m1_admin(u):
        return True
    mentor_id = plan.get("mentor_user_id")
    if mentor_id is not None and u.get("user_id") is not None \
            and int(mentor_id) == int(u.get("user_id")):
        return True
    return is_team_member(u, plan.get("student_id"))


def can_approve_plan(user, plan) -> bool:
    """批准 / 重新打开 / 确认家长版 / 导出：负责导师或 M1/全局管理员。"""
    if plan is None:
        return False
    if isinstance(plan, int):
        plan = get_plan(plan)
    if not plan:
        return False
    u = store._user_dict(user)
    if u.get("role") == "admin" or store.is_m1_admin(u):
        return True
    uid = u.get("user_id")
    mentor_id = plan.get("mentor_user_id")
    return uid is not None and mentor_id is not None and int(mentor_id) == int(uid)


def can_manage_team(user=None) -> bool:
    from m1.plan_collaboration import can_manage_team as _can_manage
    return _can_manage(user)


# ---------------------------------------------------------------------------
# 列表 / 可新建
# ---------------------------------------------------------------------------
def _visible(user: dict, plan: Dict[str, Any]) -> bool:
    if plan.get("source_mode") == "mentor_inputs":
        return can_view_plan(user, plan)
    if user.get("role") == "admin":
        return True
    if user.get("role") != "advisor":
        return False
    if is_team_member(user, plan.get("student_id")):
        return True
    if store._sees_all_students(user):
        return True
    if plan.get("mentor_user_id") is not None and user.get("user_id") is not None \
            and int(plan["mentor_user_id"]) == int(user["user_id"]):
        return True
    name = (user.get("advisor_name") or "").strip()
    return bool(name) and (plan.get("advisor_name") or "").strip() == name


def list_plans(user=None, scope: str = "all", limit: int = 500) -> List[Dict[str, Any]]:
    """发展计划列表；``mine`` 看负责或共同负责的，``all`` 看可见学生的全部。"""
    u = store._user_dict(user)
    with Session(_engine()) as sess:
        stmt = (select(M1Plan)
                .order_by(M1Plan.updated_at.desc(), M1Plan.id.desc())
                .limit(int(limit)))
        if scope == "mine" and u.get("user_id") is not None:
            from m1.plan_collaboration import PlanTeamMember
            team_ids = select(PlanTeamMember.student_id).where(
                PlanTeamMember.user_id == int(u["user_id"]))
            stmt = stmt.where(or_(M1Plan.mentor_user_id == int(u["user_id"]),
                                  M1Plan.student_id.in_(team_ids)))
        rows = [_plan_row(sess, row) for row in sess.execute(stmt).scalars().all()]
    return [row for row in rows if _visible(u, row)]


def latest_by_student(student_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """每个学生最新一个 Block 的计划（DP4 的学生列表单元格用）。"""
    ids = [int(item) for item in student_ids]
    if not ids:
        return {}
    out: Dict[int, Dict[str, Any]] = {}
    with Session(_engine()) as sess:
        rows = sess.execute(select(M1Plan).where(M1Plan.student_id.in_(ids))
                            .order_by(M1Plan.block_no.desc(),
                                      M1Plan.updated_at.desc(),
                                      M1Plan.id.desc())).scalars().all()
        for row in rows:
            if int(row.student_id) not in out:
                out[int(row.student_id)] = _plan_row(sess, row)
    return out


def _next_block(sess: Session, student_id: int) -> int:
    used = sess.execute(select(M1Plan.block_no).where(
        M1Plan.student_id == int(student_id))).scalars().all()
    return max([int(value or 0) for value in used] or [0]) + 1


def eligible_students(user=None, source_mode="report") -> List[Dict[str, Any]]:
    """会后报告已有 AI 草稿、当前账号可见的学生，附 prep 与下一个可用 Block。"""
    if source_mode == "mentor_inputs":
        with Session(_engine()) as sess:
            return [{"student_id": row.id, "name": row.name or "",
                     "grade": row.grade or "", "student_code": row.student_code or "",
                     "mentor_user_id": store._user_dict(user).get("user_id"),
                     "source_mode": "mentor_inputs", "next_block": _next_block(sess, row.id)}
                    for row in sess.execute(select(_db.Student).order_by(_db.Student.name)).scalars()
                    if store.can_access_student(user, row.id)]
    if source_mode != "report":
        raise ValueError("source_mode 只能是 report 或 mentor_inputs")
    preps = [p for p in store.list_preps(user=user)
             if store.can_access_prep(user, p["id"])]
    statuses = rstore.list_statuses([prep["id"] for prep in preps])
    chosen: Dict[int, Dict[str, Any]] = {}
    for prep in preps:
        found = statuses.get(prep["id"]) or {}
        if not report_ready(found):
            continue
        if int(prep["student_id"]) in chosen:
            continue
        chosen[int(prep["student_id"])] = prep
    if not chosen:
        return []
    with Session(_engine()) as sess:
        rows = []
        for student_id, prep in chosen.items():
            student = _student(sess, student_id)
            report = rstore.get_report(prep["id"])
            if not report or not report.get("current_version_id"):
                continue
            grade = getattr(student, "grade", "") or ""
            rows.append({
                "student_id": student_id,
                "name": getattr(student, "name", "") or "",
                "student_code": getattr(student, "student_code", "") or "",
                "grade": grade,
                "school": getattr(student, "school", "") or "",
                "prep_id": prep["id"],
                "report_id": report["id"],
                "report_version_id": report.get("current_version_id"),
                "mentor_user_id": prep.get("mentor_user_id"),
                "mentor_name": prep.get("mentor_name") or "",
                "wb_grade": parse_wb_grade(grade),
                "next_block": _next_block(sess, student_id),
            })
    rows.sort(key=lambda item: item["name"])
    return rows


# DP12 writes use a compare-and-swap at UPDATE time, not only a stale-read check.
def _save_context(plan_id, rev, changes, *, sections=(), actor_id=None):
    from sqlalchemy import update
    with Session(_engine()) as sess:
        row = sess.get(M1Plan, int(plan_id))
        if row is None:
            raise NotFound("发展计划不存在")
        _check_rev(row, rev)
        _ensure_editable(row)
        result = sess.execute(update(M1Plan).where(
            M1Plan.id == int(plan_id), M1Plan.rev == int(rev),
            M1Plan.status.in_(("inputs", "review"))).values(
                **changes, rev=int(rev) + 1, updated_at=datetime.utcnow()),
            execution_options={"synchronize_session": False})
        if result.rowcount != 1:
            sess.rollback()
            raise RevConflict(get_plan(plan_id)["rev"])
        from m1.plan_collaboration import bump_section_in_session
        for section in sections:
            bump_section_in_session(sess, plan_id, section, actor_id)
        sess.commit()
    return get_plan(plan_id)


def save_brief(plan_id, rev, brief, actor_id=None):
    from m1.plan_context import validate_brief
    clean = validate_brief(brief)
    plan = get_plan(plan_id)
    if not plan:
        raise NotFound("发展计划不存在")
    # Reject forged file/report references; free-form mentor/student attribution is allowed.
    file_ids = {str(f['id']) for f in list_files(plan_id)}
    for item in clean.values():
        if item['provenance'] == 'file' and item['source_ref'] not in file_ids:
            raise ValueError("文件来源不属于该计划")
        if item['provenance'] == 'report' and (plan['source_mode'] != 'report' or item['source_ref'] != str(plan['report_version_id'])):
            raise ValueError("报告来源不属于该计划")
    return _save_context(plan_id, rev, {
        'teaching_brief': _dumps(clean), 'brief_revision': plan['brief_revision'] + 1,
        'brief_confirmed_revision': None, 'brief_confirmed_by': None},
        sections=('brief',), actor_id=actor_id)


def confirm_brief(plan_id, rev, user_id):
    plan = get_plan(plan_id)
    if not plan:
        raise NotFound("发展计划不存在")
    if not plan['brief_revision']:
        raise ValueError("请先填写教学简报")
    return _save_context(plan_id, rev, {'brief_confirmed_revision': plan['brief_revision'],
                                        'brief_confirmed_by': user_id},
                         sections=('brief',), actor_id=user_id)


def save_durations(plan_id, rev, durations, actor_id=None):
    if not isinstance(durations, list) or len(durations) != 3 or any(
            type(n) is not int or not 15 <= n <= 180 for n in durations):
        raise ValueError("session_durations 需要三个 15–180 分钟的整数")
    return _save_context(plan_id, rev, {'session_durations': _dumps(durations)},
                         sections=('durations',), actor_id=actor_id)


def next_action(plan):
    if plan['status'] == 'generating':
        return {'action': 'poll_job', 'href': '/api/m1/plans/%d' % plan['id']}
    if plan['status'] == 'review':
        return {'action': 'review_internal', 'href': '/api/m1/plans/%d' % plan['id']}
    if plan['status'] == 'approved':
        action = {'none': 'generate_parent', 'generating': 'poll_job', 'draft': 'confirm_parent',
                  'confirmed': 'export_parent', 'exported': 'view_parent'}.get(plan['parent_status'], 'generate_parent')
        return {'action': action, 'href': '/api/m1/plans/%d' % plan['id']}
    blockers = generate_blockers(plan)
    if plan.get('source_mode') == 'mentor_inputs' and (not plan['brief_revision'] or plan['brief_confirmed_revision'] != plan['brief_revision']):
        action = 'confirm_brief' if plan['brief_revision'] else 'supply_brief'
    elif blockers:
        action = 'complete_inputs_and_goals'
    else:
        action = 'generate_internal'
    return {'action': action, 'href': '/api/m1/plans/%d' % plan['id'], 'blockers': blockers}


def save_extracted_context(plan_id, rev, inputs, brief, actor_id=None):
    # Validate references using the same path as manual updates, then atomically
    # persist profile and brief together (one revision, never overwrite concurrent edits).
    from m1.plan_context import validate_brief
    clean = validate_brief(brief)
    files = {str(f['id']) for f in list_files(plan_id)}
    plan = get_plan(plan_id)
    if not plan:
        raise NotFound('发展计划不存在')
    for item in clean.values():
        if item['provenance'] == 'file' and item['source_ref'] not in files:
            raise ValueError('AI 返回了未授权来源')
        if item['provenance'] == 'report' and (plan['source_mode'] != 'report' or item['source_ref'] != str(plan['report_version_id'])):
            raise ValueError('AI 返回了未授权来源')
    return _save_context(plan_id, rev, {'inputs': _dumps(inputs), 'teaching_brief': _dumps(clean),
                                      'brief_revision': plan['brief_revision'] + 1,
                                      'brief_confirmed_revision': None, 'brief_confirmed_by': None},
                         sections=('inputs', 'brief'), actor_id=actor_id)
