"""会后报告（首次情绪力分析报告）数据层。

两张表挂在 ``db.Base`` 上：

- ``m1_reports``          每个 ``m1_preps`` 一份报告（逐字稿、状态、安全提示、审核人）
- ``m1_report_versions``  每次生成一个版本；``ai_doc`` 不再改，``doc`` 随导师保存覆盖

对外函数返回 dict，不泄漏 ORM 实例。本模块不得 import app / blueprints
（生成子进程会直接 import 它）。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (Column, DateTime, ForeignKey, Index, Integer, String,
                        Text, select)
from sqlalchemy.orm import Session

import db as _db

Base = _db.Base

STATUSES = ("draft", "generating", "ai_draft", "needs_check", "reviewing",
            "approved", "published")
STATUS_LABELS = {
    "draft": "待生成",
    "generating": "生成中",
    "ai_draft": "AI 草稿",
    "needs_check": "待核实",
    "reviewing": "导师审核中",
    "approved": "审核通过",
    "published": "正式发布",
}


class M1Report(Base):
    __tablename__ = "m1_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prep_id = Column(Integer, ForeignKey("m1_preps.id"), nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="draft")
    transcript_text = Column(Text, nullable=False, default="")
    transcript_filename = Column(String(300), nullable=False, default="")
    transcript_path = Column(String(500), nullable=False, default="")
    current_version_id = Column(Integer)
    rev = Column(Integer, nullable=False, default=1)
    safety = Column(Text, nullable=False, default="[]")
    safety_ack_by = Column(Integer)
    safety_ack_at = Column(DateTime)
    approved_by = Column(Integer)
    approved_at = Column(DateTime)
    published_at = Column(DateTime)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class M1ReportVersion(Base):
    __tablename__ = "m1_report_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("m1_reports.id"), nullable=False)
    n = Column(Integer, nullable=False, default=1)
    y4_ratings = Column(Text)
    evidence = Column(Text)
    ai_doc = Column(Text)
    doc = Column(Text)
    checks = Column(Text)
    manifest = Column(Text)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_m1_report_versions_report_n", "report_id", "n"),)


class M1ReportSpeakers(Base):
    """会后报告的发言人识别结果（每份报告一行）。"""
    __tablename__ = "m1_report_speakers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("m1_reports.id"), nullable=False, unique=True)
    transcript_hash = Column(String(64), nullable=False, default="")
    status = Column(String(20), nullable=False, default="none")
    format = Column(String(20), nullable=False, default="")
    turns = Column(Text, nullable=False, default="[]")
    labels = Column(Text, nullable=False, default="{}")
    message = Column(String(500), nullable=False, default="")
    updated_by = Column(Integer)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NotFound(Exception):
    """记录不存在。"""


class RevConflict(Exception):
    """``rev`` 与服务器不一致。"""

    def __init__(self, rev: int):
        super().__init__("报告已在别处更新，请刷新后重试")
        self.rev = rev


class StatusError(Exception):
    """当前状态不允许该操作；消息可直接给用户看。"""


def ensure_tables(engine=None) -> None:
    """幂等建表（主要给生成子进程与命令行用；正常启动由 ``init_db`` 建）。"""
    Base.metadata.create_all(engine or _db.engine, tables=[
        M1Report.__table__, M1ReportVersion.__table__, M1ReportSpeakers.__table__])


# ---------------------------------------------------------------------------
# 内部助手
# ---------------------------------------------------------------------------
def _engine():
    return _db.engine


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(value, default=None):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _report_row(row: M1Report, *, with_transcript: bool = True) -> Dict[str, Any]:
    out = {
        "id": row.id,
        "prep_id": row.prep_id,
        "status": row.status,
        "label": STATUS_LABELS.get(row.status, row.status),
        "transcript_filename": row.transcript_filename or "",
        "transcript_path": row.transcript_path or "",
        "transcript_length": len(row.transcript_text or ""),
        "current_version_id": row.current_version_id,
        "rev": int(row.rev or 1),
        "safety": _loads(row.safety, []) or [],
        "safety_ack_by": row.safety_ack_by,
        "safety_ack_at": _iso(row.safety_ack_at),
        "approved_by": row.approved_by,
        "approved_at": _iso(row.approved_at),
        "published_at": _iso(row.published_at),
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }
    if with_transcript:
        out["transcript_text"] = row.transcript_text or ""
    return out


def _version_row(row: M1ReportVersion) -> Dict[str, Any]:
    return {
        "id": row.id,
        "report_id": row.report_id,
        "n": int(row.n or 1),
        "y4_ratings": _loads(row.y4_ratings, {}) or {},
        "evidence": _loads(row.evidence, []) or [],
        "ai_doc": _loads(row.ai_doc, None),
        "doc": _loads(row.doc, None),
        "checks": _loads(row.checks, []) or [],
        "manifest": _loads(row.manifest, {}) or {},
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
    }


def _touch(row: M1Report) -> None:
    row.updated_at = datetime.utcnow()


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------
def get_report(prep_id: int, *, with_transcript: bool = True) -> Optional[Dict[str, Any]]:
    with Session(_engine()) as sess:
        row = sess.execute(select(M1Report).where(
            M1Report.prep_id == int(prep_id))).scalars().first()
        return _report_row(row, with_transcript=with_transcript) if row else None


def get_report_by_id(report_id: int) -> Optional[Dict[str, Any]]:
    with Session(_engine()) as sess:
        row = sess.get(M1Report, int(report_id))
        return _report_row(row) if row else None


def get_speakers(report_id: int) -> Optional[Dict[str, Any]]:
    with Session(_engine()) as sess:
        row = sess.query(M1ReportSpeakers).filter_by(report_id=int(report_id)).first()
        if not row:
            return None
        return {"report_id": row.report_id, "transcript_hash": row.transcript_hash,
                "status": row.status, "format": row.format,
                "turns": _loads(row.turns, []), "labels": _loads(row.labels, {}),
                "message": row.message, "updated_by": row.updated_by,
                "updated_at": _iso(row.updated_at)}


def save_speakers(report_id: int, **fields: Any) -> None:
    allowed = ("transcript_hash", "status", "format", "turns", "labels", "message", "updated_by")
    with Session(_engine()) as sess:
        row = sess.query(M1ReportSpeakers).filter_by(report_id=int(report_id)).first()
        if not row:
            row = M1ReportSpeakers(report_id=int(report_id))
            sess.add(row)
        for key in allowed:
            if key not in fields:
                continue
            value = fields[key]
            if key in ("turns", "labels"):
                value = _dumps(value)
            setattr(row, key, value if value is not None else getattr(row, key))
        sess.commit()


def get_or_create_report(prep_id: int, created_by=None) -> Dict[str, Any]:
    with Session(_engine()) as sess:
        row = sess.execute(select(M1Report).where(
            M1Report.prep_id == int(prep_id))).scalars().first()
        if row is None:
            row = M1Report(prep_id=int(prep_id), status="draft",
                           created_by=created_by)
            sess.add(row)
            sess.commit()
        return _report_row(row)


def list_statuses(prep_ids: List[int]) -> Dict[int, Dict[str, str]]:
    ids = [int(i) for i in prep_ids]
    if not ids:
        return {}
    with Session(_engine()) as sess:
        rows = sess.execute(select(M1Report.prep_id, M1Report.status)
                            .where(M1Report.prep_id.in_(ids))).all()
        return {pid: {"status": status, "label": STATUS_LABELS.get(status, status)}
                for pid, status in rows}


def set_transcript(report_id: int, *, text: str, filename: str = "",
                   stored_path: str = "") -> Dict[str, Any]:
    with Session(_engine()) as sess:
        row = sess.get(M1Report, int(report_id))
        if row is None:
            raise NotFound("报告不存在")
        if row.status == "generating":
            raise StatusError("报告正在生成，请稍后再换逐字稿")
        row.transcript_text = text or ""
        row.transcript_filename = filename or ""
        row.transcript_path = stored_path or ""
        row.rev = int(row.rev or 1) + 1
        _touch(row)
        sess.commit()
        return _report_row(row)


def set_status(report_id: int, status: str) -> None:
    if status not in STATUSES:
        raise ValueError("未知状态：%s" % status)
    with Session(_engine()) as sess:
        row = sess.get(M1Report, int(report_id))
        if row is None:
            raise NotFound("报告不存在")
        row.status = status
        _touch(row)
        sess.commit()


def begin_generation(report_id: int) -> str:
    """置为 generating，返回原状态（失败时还原用）。已在生成则抛 StatusError。"""
    with Session(_engine()) as sess:
        row = sess.get(M1Report, int(report_id))
        if row is None:
            raise NotFound("报告不存在")
        if row.status == "generating":
            raise StatusError("生成任务已在进行中")
        previous = row.status
        row.status = "generating"
        _touch(row)
        sess.commit()
        return previous


# ---------------------------------------------------------------------------
# 版本
# ---------------------------------------------------------------------------
def add_version(report_id: int, *, y4_ratings, evidence, ai_doc, doc, checks,
                manifest, status: str, safety=None, created_by=None) -> Dict[str, Any]:
    """生成结果落库：新版本成为当前版本，安全确认与审核记录清零。"""
    if status not in STATUSES:
        raise ValueError("未知状态：%s" % status)
    with Session(_engine()) as sess:
        report = sess.get(M1Report, int(report_id))
        if report is None:
            raise NotFound("报告不存在")
        last = sess.execute(
            select(M1ReportVersion.n).where(M1ReportVersion.report_id == int(report_id))
            .order_by(M1ReportVersion.n.desc())).scalars().first()
        row = M1ReportVersion(
            report_id=int(report_id), n=int(last or 0) + 1,
            y4_ratings=_dumps(y4_ratings), evidence=_dumps(evidence),
            ai_doc=_dumps(ai_doc), doc=_dumps(doc), checks=_dumps(checks),
            manifest=_dumps(manifest), created_by=created_by)
        sess.add(row)
        sess.flush()
        report.current_version_id = row.id
        report.status = status
        if safety is not None:
            report.safety = _dumps(safety)
        report.safety_ack_by = None
        report.safety_ack_at = None
        report.approved_by = None
        report.approved_at = None
        report.published_at = None
        report.rev = int(report.rev or 1) + 1
        _touch(report)
        data = _version_row(row)
        sess.commit()
        return data


def get_version(version_id: int) -> Optional[Dict[str, Any]]:
    with Session(_engine()) as sess:
        row = sess.get(M1ReportVersion, int(version_id))
        return _version_row(row) if row else None


def current_version(report_id: int) -> Optional[Dict[str, Any]]:
    with Session(_engine()) as sess:
        report = sess.get(M1Report, int(report_id))
        if not report or not report.current_version_id:
            return None
        row = sess.get(M1ReportVersion, report.current_version_id)
        return _version_row(row) if row else None


def list_versions(report_id: int) -> List[Dict[str, Any]]:
    with Session(_engine()) as sess:
        rows = sess.execute(
            select(M1ReportVersion).where(M1ReportVersion.report_id == int(report_id))
            .order_by(M1ReportVersion.n)).scalars().all()
        return [{"id": r.id, "n": int(r.n or 1), "created_at": _iso(r.created_at)}
                for r in rows]


def has_edits(report: Dict[str, Any], version: Optional[Dict[str, Any]]) -> bool:
    """导师是否改过当前版本：文档与 AI 原稿不同，或已进入审核流程。"""
    if not version:
        return False
    if report.get("status") in ("reviewing", "approved", "published"):
        return True
    return version.get("doc") != version.get("ai_doc")


def save_version(report_id: int, rev: int, *, doc=None, evidence=None,
                 checks=None) -> Dict[str, Any]:
    """保存导师的修改：``rev`` 一致才写，成功后 ``rev + 1``，状态进入 ``reviewing``。

    ``published`` 须先重新打开；``draft`` / ``generating`` 没有可保存的内容。
    """
    with Session(_engine()) as sess:
        report = sess.get(M1Report, int(report_id))
        if report is None:
            raise NotFound("报告不存在")
        if report.status == "published":
            raise StatusError("已正式发布，请先重新打开再修改")
        if report.status in ("draft", "generating") or not report.current_version_id:
            raise StatusError("报告还没有可修改的内容")
        if int(rev) != int(report.rev or 1):
            raise RevConflict(int(report.rev or 1))
        row = sess.get(M1ReportVersion, report.current_version_id)
        if row is None:
            raise NotFound("报告版本不存在")
        if doc is not None:
            row.doc = _dumps(doc)
        if evidence is not None:
            row.evidence = _dumps(evidence)
        if checks is not None:
            row.checks = _dumps(checks)
        report.status = "reviewing"
        if report.approved_by is not None or report.approved_at is not None:
            report.approved_by = None
            report.approved_at = None
        report.rev = int(report.rev or 1) + 1
        _touch(report)
        data = {"rev": report.rev, "status": report.status, "version_id": row.id}
        sess.commit()
        return data


def store_checks(version_id: int, checks) -> None:
    with Session(_engine()) as sess:
        row = sess.get(M1ReportVersion, int(version_id))
        if row is not None:
            row.checks = _dumps(checks)
            sess.commit()


# ---------------------------------------------------------------------------
# 安全提示 / 审核
# ---------------------------------------------------------------------------
def ack_safety(report_id: int, user_id=None) -> Dict[str, Any]:
    with Session(_engine()) as sess:
        report = sess.get(M1Report, int(report_id))
        if report is None:
            raise NotFound("报告不存在")
        report.safety_ack_by = int(user_id) if user_id is not None else None
        report.safety_ack_at = datetime.utcnow()
        _touch(report)
        sess.commit()
        return _report_row(report)


def approve(report_id: int, user_id=None) -> Dict[str, Any]:
    with Session(_engine()) as sess:
        report = sess.get(M1Report, int(report_id))
        if report is None:
            raise NotFound("报告不存在")
        if report.status not in ("ai_draft", "needs_check", "reviewing"):
            raise StatusError("当前状态不能审核通过")
        report.status = "approved"
        report.approved_by = int(user_id) if user_id is not None else None
        report.approved_at = datetime.utcnow()
        report.rev = int(report.rev or 1) + 1
        _touch(report)
        sess.commit()
        return _report_row(report)


def publish(report_id: int, user_id=None) -> Dict[str, Any]:
    with Session(_engine()) as sess:
        report = sess.get(M1Report, int(report_id))
        if report is None:
            raise NotFound("报告不存在")
        if report.status not in ("ai_draft", "needs_check", "reviewing", "approved"):
            raise StatusError("当前状态不能正式发布")
        report.status = "published"
        report.published_at = datetime.utcnow()
        report.rev = int(report.rev or 1) + 1
        _touch(report)
        sess.commit()
        return _report_row(report)


def reopen(report_id: int) -> Dict[str, Any]:
    with Session(_engine()) as sess:
        report = sess.get(M1Report, int(report_id))
        if report is None:
            raise NotFound("报告不存在")
        if report.status not in ("approved", "published"):
            raise StatusError("只有审核通过或已发布的报告才能重新打开")
        report.status = "reviewing"
        report.approved_by = None
        report.approved_at = None
        report.published_at = None
        report.rev = int(report.rev or 1) + 1
        _touch(report)
        sess.commit()
        return _report_row(report)
