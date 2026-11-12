"""发展计划数据层：表、版本、状态机与权限。

三张表挂在 ``db.Base`` 上：

- ``m1_plans``          每个学生每个 Block 一份计划（``(student_id, block_no)`` 唯一）
- ``m1_plan_versions``  内部版 / 家长版的 AI 初稿与导师编辑（``ai_doc`` 永不改动）
- ``m1_plan_files``     个性化需求的上传文件与提取文字

对外函数返回 dict，不泄漏 ORM 实例。本模块不得 import app / blueprints
（生成子进程会直接 import 它）。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import (Column, DateTime, ForeignKey, Index, Integer, String,
                        Text, select)
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
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UPLOAD_ROOT = Path(__file__).resolve().parent.parent / "uploads" / "m1_plans"


# ---------------------------------------------------------------------------
# 模型
# ---------------------------------------------------------------------------
class M1Plan(Base):
    __tablename__ = "m1_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    prep_id = Column(Integer, ForeignKey("m1_preps.id"), nullable=False)
    report_id = Column(Integer, ForeignKey("m1_reports.id"), nullable=False)
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
    Base.metadata.create_all(engine or _db.engine, tables=[
        M1Plan.__table__, M1PlanVersion.__table__, M1PlanFile.__table__])


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


def _student(sess: Session, student_id: int):
    return sess.get(_db.Student, int(student_id))


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
        "doc": _loads(row.doc, None),
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


def create_plan(student_id: int, *, prep_id: int, report_id: int,
                report_version_id: Optional[int], mentor_user_id,
                block_no: int, period_start: str, period_end: str,
                credits: str = "", sessions: int = 3,
                wb_grade: Optional[int], created_by=None) -> Dict[str, Any]:
    """新建计划（D2/D7）。报告必须已发布，Block 不能重复，课次固定 3。"""
    if isinstance(sessions, bool) or int(sessions) != 3:
        raise ValueError("本轮计划课次固定为 3 节")
    if isinstance(block_no, bool) or not isinstance(block_no, int) or block_no < 1:
        raise ValueError("Block 编号需为 1 或以上")
    if isinstance(wb_grade, bool) or not isinstance(wb_grade, int) \
            or not 5 <= wb_grade <= 9:
        raise ValueError("参考年级需在 G5–G9 之间")
    _check_dates(period_start, period_end)
    report = rstore.get_report_by_id(report_id)
    if not report or int(report["prep_id"]) != int(prep_id):
        raise ValueError("会后报告不存在")
    if report["status"] != "published":
        raise ValueError("会后报告还没有正式发布")
    version_id = report_version_id or report.get("current_version_id")
    if not version_id:
        raise ValueError("会后报告还没有正式发布")
    with Session(_engine()) as sess:
        if not _student(sess, student_id):
            raise NotFound("学生不存在")
        existing = sess.execute(select(M1Plan).where(
            M1Plan.student_id == int(student_id),
            M1Plan.block_no == int(block_no))).scalars().first()
        if existing is not None:
            raise ValueError("该 Block 已有发展计划")
        row = M1Plan(
            student_id=int(student_id), prep_id=int(prep_id),
            report_id=int(report_id), report_version_id=int(version_id),
            mentor_user_id=int(mentor_user_id) if mentor_user_id is not None else None,
            block_no=int(block_no), period_start=period_start, period_end=period_end,
            credits=str(credits or "").strip()[:20], sessions=3, wb_grade=int(wb_grade),
            inputs=_dumps({
                "strengths": _field(""), "needs": _field(""),
                "context": _field(""), "interests": _field(""),
                "read_at": datetime.utcnow().isoformat(),
                "report_status_at_read": "published",
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
        sess.commit()
        sess.refresh(row)
        return _plan_row(sess, row)


def save_inputs_ai(plan_id: int, values: Dict[str, Any]) -> Dict[str, Any]:
    """生成子进程写四个 Development Input 字段（``src: ai``）。"""
    with Session(_engine()) as sess:
        row = sess.get(M1Plan, int(plan_id))
        if row is None:
            raise NotFound("发展计划不存在")
        inputs = _loads(row.inputs, {}) or {}
        for key in ("strengths", "needs", "context", "interests"):
            if key in values:
                inputs[key] = _field(values.get(key), "ai")
        inputs["read_at"] = datetime.utcnow().isoformat()
        inputs["report_status_at_read"] = "published"
        row.inputs = _dumps(inputs)
        _bump(row)
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
        sess.commit()
        sess.refresh(row)
        return _plan_row(sess, row)


def save_personal_summary(plan_id: int, summary) -> Dict[str, Any]:
    """生成子进程写个性化需求总结。"""
    with Session(_engine()) as sess:
        row = sess.get(M1Plan, int(plan_id))
        if row is None:
            raise NotFound("发展计划不存在")
        personal = _loads(row.personal, {}) or {}
        personal["summary"] = _field(summary, "ai")
        personal.setdefault("notes", "")
        row.personal = _dumps(personal)
        _bump(row)
        sess.commit()
        sess.refresh(row)
        return _plan_row(sess, row)


def save_goal_ai(plan_id: int, code: str, start, expected) -> Dict[str, Any]:
    """生成子进程填一个目标的当前起点与阶段预期进展。"""
    with Session(_engine()) as sess:
        row = sess.get(M1Plan, int(plan_id))
        if row is None:
            raise NotFound("发展计划不存在")
        goals = _loads(row.goals, []) or []
        found = False
        for item in goals:
            if item.get("code") == code:
                item["start"] = _field(start, "ai")
                item["expected"] = _field(expected, "ai")
                found = True
        if not found:
            raise NotFound("没有该目标")
        row.goals = _dumps(goals)
        _bump(row)
        sess.commit()
        sess.refresh(row)
        return _plan_row(sess, row)


def mark_report_read(plan_id: int, report_version_id: int) -> Dict[str, Any]:
    """读取会后报告后记下所读版本（D2）。"""
    with Session(_engine()) as sess:
        row = sess.get(M1Plan, int(plan_id))
        if row is None:
            raise NotFound("发展计划不存在")
        row.report_version_id = int(report_version_id)
        inputs = _loads(row.inputs, {}) or {}
        inputs["read_at"] = datetime.utcnow().isoformat()
        inputs["report_status_at_read"] = "published"
        row.inputs = _dumps(inputs)
        _bump(row)
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


def _save_part(plan_id: int, rev: int, part: str, doc, checks,
               actor_id=None) -> Dict[str, Any]:
    with Session(_engine()) as sess:
        plan = sess.get(M1Plan, int(plan_id))
        if plan is None:
            raise NotFound("发展计划不存在")
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
        _check_rev(plan, rev)
        current = sess.get(M1PlanVersion, int(version_id))
        if current is None:
            raise NotFound("计划版本不存在")
        if current.kind == "edit":
            current.doc = _dumps(doc)
            if checks is not None:
                current.checks = _dumps(checks)
            version_id = current.id
            ai_doc = _loads(current.ai_doc, None)
        else:
            row = M1PlanVersion(
                plan_id=int(plan_id), part=part, n=int(current.n or 1) + 1,
                kind="edit", ai_doc=current.ai_doc, doc=_dumps(doc),
                checks=_dumps(checks) if checks is not None else current.checks,
                manifest=current.manifest, source_version_id=current.source_version_id,
                created_by=actor_id if actor_id is not None else current.created_by,
            )
            sess.add(row)
            sess.flush()
            version_id = row.id
            ai_doc = _loads(row.ai_doc, None)
            if part == "internal":
                plan.current_version_id = row.id
            else:
                plan.parent_version_id = row.id
        if part == "parent" and plan.parent_status in ("confirmed", "exported"):
            plan.parent_status = "draft"
        _bump(plan)
        result = {"rev": int(plan.rev), "version_id": version_id,
                  "status": plan.status, "parent_status": plan.parent_status,
                  "ai_doc": ai_doc}
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
    """会后报告当前状态与计划所读版本是否一致（Q2）。"""
    plan = plan_or_id if isinstance(plan_or_id, dict) else get_plan(plan_or_id)
    if not plan:
        raise NotFound("发展计划不存在")
    report = rstore.get_report_by_id(plan["report_id"]) if plan.get("report_id") else None
    fresh = bool(report) and report.get("status") == "published" \
        and int(report.get("current_version_id") or 0) == int(plan.get("report_version_id") or 0)
    return {
        "status": (report or {}).get("status", ""),
        "label": (report or {}).get("label", ""),
        "current_version_id": (report or {}).get("current_version_id"),
        "report_version_id": plan.get("report_version_id"),
        "fresh": fresh,
        "read_at": (plan.get("inputs") or {}).get("read_at", ""),
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
    if any(not ((item.get("goal") or {}).get("text") or "").strip() for item in goals):
        blockers.append("目标还不能为空")
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
def can_view_plan(user, plan) -> bool:
    """与 ``store.can_access_prep`` 同一条规则；不存在返回 False。"""
    if plan is None:
        return False
    if isinstance(plan, int):
        plan = get_plan(plan)
    if not plan:
        return False
    return store.can_access_prep(user, plan.get("prep_id"))


def can_edit_plan(user, plan) -> bool:
    """admin，或该计划从 prep 复制来的 Mentor 本人（D6）。"""
    if plan is None:
        return False
    if isinstance(plan, int):
        plan = get_plan(plan)
    if not plan:
        return False
    u = store._user_dict(user)
    if u.get("role") == "admin":
        return True
    mentor_id = plan.get("mentor_user_id")
    if mentor_id is None or u.get("user_id") is None:
        return False
    return int(mentor_id) == int(u.get("user_id"))


# ---------------------------------------------------------------------------
# 列表 / 可新建
# ---------------------------------------------------------------------------
def _visible(user: dict, plan: Dict[str, Any]) -> bool:
    if user.get("role") == "admin":
        return True
    if user.get("role") != "advisor":
        return False
    if store._sees_all_students(user):
        return True
    if plan.get("mentor_user_id") is not None and user.get("user_id") is not None \
            and int(plan["mentor_user_id"]) == int(user["user_id"]):
        return True
    name = (user.get("advisor_name") or "").strip()
    return bool(name) and (plan.get("advisor_name") or "").strip() == name


def list_plans(user=None, scope: str = "all", limit: int = 500) -> List[Dict[str, Any]]:
    """发展计划列表；``mine`` 只看自己负责的，``all`` 看可见学生的全部。"""
    u = store._user_dict(user)
    with Session(_engine()) as sess:
        stmt = (select(M1Plan)
                .order_by(M1Plan.updated_at.desc(), M1Plan.id.desc())
                .limit(int(limit)))
        if scope == "mine" and u.get("user_id") is not None:
            stmt = stmt.where(M1Plan.mentor_user_id == int(u["user_id"]))
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


def eligible_students(user=None) -> List[Dict[str, Any]]:
    """会后报告已发布、当前账号可见的学生，附 prep 与下一个可用 Block。"""
    preps = store.list_preps(user=user)
    statuses = rstore.list_statuses([prep["id"] for prep in preps])
    chosen: Dict[int, Dict[str, Any]] = {}
    for prep in preps:
        found = statuses.get(prep["id"]) or {}
        if found.get("status") != "published":
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
