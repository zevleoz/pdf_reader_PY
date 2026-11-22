"""会后报告（首次情绪力分析报告）数据层。

``m1_reports`` 存当前状态与修订号，``m1_report_versions`` 存生成版本和导师编辑。
``m1_report_official`` 保留审核和发布时的内容，``m1_report_writes`` 存最近一次浏览器写入回执。
``m1_report_speakers`` 存发言人识别及导师更正。

对外函数返回 dict，不泄漏 ORM 实例。本模块不得 import app / blueprints
（生成子进程会直接 import 它）。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (Column, DateTime, ForeignKey, Index, Integer, String,
                        Text, and_, select, update)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import db as _db

Base = _db.Base

STATUSES = ("draft", "generating", "ai_draft", "needs_check", "reviewing",
            "approved", "published")
EDITABLE_STATUSES = ("ai_draft", "needs_check", "reviewing", "approved")
OFFICIAL_STATUSES = ("approved", "published")

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


class M1ReportOfficial(Base):
    """Immutable content for the revision that was approved or published."""

    __tablename__ = "m1_report_official"

    report_id = Column(Integer, ForeignKey("m1_reports.id", ondelete="CASCADE"),
                       primary_key=True)
    rev = Column(Integer, primary_key=True)
    version_id = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False)
    actor_id = Column(Integer)
    official_at = Column(DateTime, nullable=False)
    version = Column(Text, nullable=False)
    print_content = Column(Text)


class M1ReportWrite(Base):
    """Latest browser write receipt for reconciling an uncertain response."""

    __tablename__ = "m1_report_writes"

    report_id = Column(Integer, ForeignKey("m1_reports.id", ondelete="CASCADE"),
                       primary_key=True)
    write_id = Column(String(36), nullable=False)
    rev = Column(Integer, nullable=False)


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
        super().__init__("报告已在别处更新，请保留未保存的文字，刷新后重新核对")
        self.rev = rev


class StatusError(Exception):
    """当前状态不允许该操作；消息可直接给用户看。"""


def ensure_tables(engine=None) -> None:
    """幂等建表（主要给生成子进程与命令行用；正常启动由 ``init_db`` 建）。"""
    Base.metadata.create_all(engine or _db.engine, tables=[
        M1Report.__table__, M1ReportVersion.__table__, M1ReportSpeakers.__table__,
        M1ReportOfficial.__table__, M1ReportWrite.__table__])


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


def _report_for_write(sess, report_id):
    row = sess.get(M1Report, int(report_id))
    if row is None:
        raise NotFound("报告不存在")
    return row


def _advance(sess, report, *, expected_rev=None, version_id=None, statuses=STATUSES,
             status_error="当前状态不能修改报告", **values):
    """Acquire the report row with a CAS before mutating any dependent rows."""
    rev = report.rev if expected_rev is None else expected_rev
    version_id = report.current_version_id if version_id is None else version_id
    if report.rev != rev or report.current_version_id != version_id:
        raise RevConflict(report.rev)
    if report.status not in statuses:
        raise StatusError(status_error)
    changed = sess.execute(update(M1Report).where(
        M1Report.id == report.id, M1Report.rev == rev,
        M1Report.current_version_id == version_id, M1Report.status.in_(statuses),
    ).values(rev=rev + 1, updated_at=datetime.utcnow(), **values)
        .execution_options(synchronize_session=False)).rowcount
    if changed != 1:
        sess.refresh(report)
        raise RevConflict(report.rev)
    return rev + 1


def _record_write(sess, report_id, write_id, rev):
    if not write_id:
        return
    receipt = sess.get(M1ReportWrite, report_id)
    if receipt:
        receipt.write_id = write_id
        receipt.rev = rev
    else:
        sess.add(M1ReportWrite(report_id=report_id, write_id=write_id, rev=rev))


def write_revision(report_id: int, write_id: str) -> Optional[int]:
    with Session(_engine()) as sess:
        row = sess.get(M1ReportWrite, int(report_id))
        return row.rev if row and row.write_id == write_id else None


def _record_official(sess, report, version, *, rev, status, actor, official_at,
                     print_content=None):
    sess.add(M1ReportOfficial(
        report_id=report.id, rev=rev, version_id=version.id, status=status,
        actor_id=actor, official_at=official_at, version=_dumps(_version_row(version)),
        print_content=_dumps(print_content) if print_content is not None else None))


def _archive_legacy_official(sess, report):
    if (report.status not in OFFICIAL_STATUSES or not report.current_version_id
            or sess.get(M1ReportOfficial, (report.id, report.rev))):
        return
    version = sess.get(M1ReportVersion, report.current_version_id)
    if version:
        # Legacy publications tracked the publication time, but only approvals tracked an actor.
        published = report.status == "published"
        _record_official(sess, report, version, rev=report.rev, status=report.status,
                         actor=None if published else report.approved_by,
                         official_at=(report.published_at if published else report.approved_at)
                         or report.updated_at or report.created_at or datetime.utcnow())


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------
def get_report(prep_id: int, *, with_transcript: bool = True) -> Optional[Dict[str, Any]]:
    with Session(_engine()) as sess:
        row = sess.execute(select(M1Report).where(
            M1Report.prep_id == int(prep_id))).scalars().first()
        return _report_row(row, with_transcript=with_transcript) if row else None


def _candidate_query(prep_id):
    return (select(M1Report, M1ReportVersion)
            .outerjoin(M1ReportVersion, and_(M1ReportVersion.report_id == M1Report.id,
                                            M1ReportVersion.id == M1Report.current_version_id))
            .where(M1Report.prep_id == int(prep_id)))


def get_candidate(prep_id: int):
    """Read the report, current version and speaker labels in one database statement."""
    query = _candidate_query(prep_id).add_columns(M1ReportSpeakers).outerjoin(
        M1ReportSpeakers, M1ReportSpeakers.report_id == M1Report.id)
    with Session(_engine()) as sess:
        row = sess.execute(query).first()
        if not row:
            return None, None, None
        report, version, speaker_row = row
        return (_report_row(report), _version_row(version) if version else None,
                _speakers_row(speaker_row) if speaker_row else None)


def print_snapshot(prep_id: int, *, expected_rev=None, version_id=None):
    """Validate the pin against the same statement that selects the printable content."""
    query = _candidate_query(prep_id)
    if expected_rev is not None:
        query = query.add_columns(M1ReportOfficial).outerjoin(
            M1ReportOfficial, and_(M1ReportOfficial.report_id == M1Report.id,
                                   M1ReportOfficial.rev == expected_rev,
                                   M1ReportOfficial.version_id == version_id))
    else:
        # Use the saved rendering for the current official revision on existing print URLs.
        query = query.add_columns(M1ReportOfficial).outerjoin(
            M1ReportOfficial, and_(M1ReportOfficial.report_id == M1Report.id,
                                   M1ReportOfficial.rev == M1Report.rev))
    with Session(_engine()) as sess:
        row = sess.execute(query).first()
        if not row:
            return None, None, None
        report, version, official = row
        result = _report_row(report)
        if official:
            result.update(status=official.status, label=STATUS_LABELS[official.status],
                          rev=official.rev, current_version_id=official.version_id)
            return result, _loads(official.version), _loads(official.print_content)
        if expected_rev is not None and (report.rev != expected_rev
                                         or report.current_version_id != version_id):
            raise RevConflict(report.rev)
        return result, _version_row(version) if version else None, None


def latest_official_revision(report_id: int):
    """Prefer the last publication, falling back to the last approval."""
    with Session(_engine()) as sess:
        row = sess.execute(select(M1ReportOfficial.rev, M1ReportOfficial.version_id)
                           .where(M1ReportOfficial.report_id == int(report_id))
                           .order_by((M1ReportOfficial.status == "published").desc(),
                                     M1ReportOfficial.rev.desc())).first()
        return {"rev": row.rev, "version_id": row.version_id} if row else None


def get_report_by_id(report_id: int) -> Optional[Dict[str, Any]]:
    with Session(_engine()) as sess:
        row = sess.get(M1Report, int(report_id))
        return _report_row(row) if row else None


def _speakers_row(row):
    return {"report_id": row.report_id, "transcript_hash": row.transcript_hash,
            "status": row.status, "format": row.format,
            "turns": _loads(row.turns, []), "labels": _loads(row.labels, {}),
            "message": row.message, "updated_by": row.updated_by,
            "updated_at": _iso(row.updated_at)}


def get_speakers(report_id: int) -> Optional[Dict[str, Any]]:
    with Session(_engine()) as sess:
        row = sess.query(M1ReportSpeakers).filter_by(report_id=int(report_id)).first()
        return _speakers_row(row) if row else None


def save_speakers(report_id: int, *, expected_rev=None, write_id=None,
                  allow_generating=False, **fields: Any):
    allowed = ("transcript_hash", "status", "format", "turns", "labels", "message", "updated_by")
    with Session(_engine()) as sess:
        report = _report_for_write(sess, report_id)
        statuses = EDITABLE_STATUSES + ("draft",)
        if allow_generating:
            statuses += ("generating",)
        rev = _advance(sess, report, expected_rev=expected_rev, statuses=statuses)
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
        _record_write(sess, report_id, write_id, rev)
        sess.flush()
        sess.refresh(report)
        result = _report_row(report), _speakers_row(row)
        sess.commit()
        return result


def get_or_create_report(prep_id: int, created_by=None) -> Dict[str, Any]:
    with Session(_engine()) as sess:
        row = sess.execute(select(M1Report).where(
            M1Report.prep_id == int(prep_id))).scalars().first()
        if row is None:
            row = M1Report(prep_id=int(prep_id), status="draft",
                           created_by=created_by)
            sess.add(row)
            try:
                sess.commit()
            except IntegrityError:
                sess.rollback()
                row = sess.execute(select(M1Report).where(
                    M1Report.prep_id == int(prep_id))).scalars().first()
                if row is None:
                    raise
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


def list_overview(prep_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """列表页用的报告概览：是否有逐字稿、是否已开始；未开始的行标签为「未开始」。"""
    ids = [int(i) for i in prep_ids]
    if not ids:
        return {}
    with Session(_engine()) as sess:
        rows = sess.execute(select(M1Report)
                            .where(M1Report.prep_id.in_(ids))).scalars().all()
        out = {}
        for row in rows:
            has_transcript = bool((row.transcript_text or "").strip())
            started = has_transcript or row.status != "draft"
            out[int(row.prep_id)] = {
                "status": row.status,
                "label": STATUS_LABELS.get(row.status, row.status) if started else "未开始",
                "started": started,
                "has_transcript": has_transcript,
                "updated_at": _iso(row.updated_at),
            }
        return out


def set_transcript(report_id: int, *, text: str, filename: str = "",
                   stored_path: str = "", expected_rev=None, write_id=None) -> Dict[str, Any]:
    with Session(_engine()) as sess:
        report = _report_for_write(sess, report_id)
        rev = _advance(sess, report, expected_rev=expected_rev,
                       statuses=EDITABLE_STATUSES + ("draft",),
                       status_error="报告正在生成或已正式发布，请稍后再修改逐字稿",
                       transcript_text=text or "", transcript_filename=filename or "",
                       transcript_path=stored_path or "")
        _record_write(sess, report_id, write_id, rev)
        sess.refresh(report)
        result = _report_row(report)
        sess.commit()
        return result


def save_cover(report_id, student_id, rev, updates, write_id=None):
    with Session(_engine()) as sess:
        report = _report_for_write(sess, report_id)
        rev = _advance(sess, report, expected_rev=rev, statuses=("draft",))
        sess.execute(update(_db.Student).where(_db.Student.id == student_id).values(**updates))
        _record_write(sess, report_id, write_id, rev)
        sess.commit()
        return rev


def set_status(report_id: int, status: str, *, from_status=None) -> None:
    if status not in STATUSES:
        raise ValueError("未知状态：%s" % status)
    with Session(_engine()) as sess:
        report = _report_for_write(sess, report_id)
        if from_status is not None and report.status != from_status:
            return
        _advance(sess, report, statuses=tuple(s for s in STATUSES if s != "published"),
                 status=status)
        _archive_legacy_official(sess, report)
        sess.commit()


def begin_generation(report_id: int, *, expected_rev=None) -> str:
    """置为 generating，返回原状态（失败时还原用）。已在生成则抛 StatusError。"""
    with Session(_engine()) as sess:
        report = _report_for_write(sess, report_id)
        previous = report.status
        _advance(sess, report, expected_rev=expected_rev, statuses=EDITABLE_STATUSES + ("draft",),
                 status="generating", status_error="报告正在生成或已正式发布")
        _archive_legacy_official(sess, report)
        sess.commit()
        return previous


# ---------------------------------------------------------------------------
# 版本
# ---------------------------------------------------------------------------
def add_version(report_id: int, *, y4_ratings, evidence, ai_doc, doc, checks,
                manifest, status: str, safety=None, created_by=None,
                expected_rev=None) -> Dict[str, Any]:
    """生成结果落库：新版本成为当前版本，安全确认与审核记录清零。"""
    if status not in STATUSES:
        raise ValueError("未知状态：%s" % status)
    with Session(_engine()) as sess:
        report = _report_for_write(sess, report_id)
        statuses = STATUSES if expected_rev is None else EDITABLE_STATUSES + ("draft", "generating")
        _advance(sess, report, expected_rev=expected_rev, statuses=statuses)
        _archive_legacy_official(sess, report)
        sess.refresh(report)
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
                 checks=None, version_id=None, write_id=None) -> Dict[str, Any]:
    """Save edits only while the revision, current version and status still match."""
    with Session(_engine()) as sess:
        report = _report_for_write(sess, report_id)
        saved_rev = _advance(sess, report, expected_rev=rev, version_id=version_id,
                             statuses=EDITABLE_STATUSES, status="reviewing",
                             approved_by=None, approved_at=None,
                             status_error="报告当前不可修改。已发布的报告请先重新打开")
        _archive_legacy_official(sess, report)
        row = sess.get(M1ReportVersion, report.current_version_id)
        if row is None:
            raise NotFound("报告版本不存在")
        if doc is not None:
            row.doc = _dumps(doc)
        if evidence is not None:
            row.evidence = _dumps(evidence)
        if checks is not None:
            row.checks = _dumps(checks)
        _record_write(sess, report_id, write_id, saved_rev)
        result = {"rev": saved_rev, "status": "reviewing", "version_id": row.id}
        sess.commit()
        return result


def store_checks(version_id: int, checks) -> None:
    with Session(_engine()) as sess:
        row = sess.get(M1ReportVersion, int(version_id))
        if row is not None:
            row.checks = _dumps(checks)
            sess.commit()


# ---------------------------------------------------------------------------
# 安全提示 / 审核流程
# ---------------------------------------------------------------------------
def ack_safety(report_id: int, user_id=None) -> Dict[str, Any]:
    with Session(_engine()) as sess:
        report = _report_for_write(sess, report_id)
        _advance(sess, report, statuses=EDITABLE_STATUSES + ("draft",),
                 safety_ack_by=int(user_id) if user_id is not None else None,
                 safety_ack_at=datetime.utcnow())
        sess.refresh(report)
        result = _report_row(report)
        sess.commit()
        return result


def _make_official(report_id, user_id, status, expected_rev, version_id, print_content):
    now = datetime.utcnow()
    actor = int(user_id) if user_id is not None else None
    if status == "published":
        statuses, fields = EDITABLE_STATUSES, {"published_at": now}
    else:
        statuses = EDITABLE_STATUSES[:-1]
        fields = {"approved_at": now, "approved_by": actor}

    with Session(_engine()) as sess:
        report = _report_for_write(sess, report_id)
        rev = _advance(sess, report, expected_rev=expected_rev, version_id=version_id,
                       statuses=statuses, status=status,
                       status_error="当前状态不能%s" % STATUS_LABELS[status], **fields)
        version = sess.get(M1ReportVersion, report.current_version_id)
        if not version:
            raise NotFound("报告版本不存在")
        _archive_legacy_official(sess, report)
        _record_official(sess, report, version, rev=rev, status=status, actor=actor,
                         official_at=now, print_content=print_content)
        sess.refresh(report)
        result = _report_row(report)
        sess.commit()
        return result


def approve(report_id: int, user_id=None, *, expected_rev=None, version_id=None,
            print_content=None) -> Dict[str, Any]:
    return _make_official(report_id, user_id, "approved", expected_rev,
                          version_id, print_content)


def publish(report_id: int, user_id=None, *, expected_rev=None, version_id=None,
            print_content=None) -> Dict[str, Any]:
    return _make_official(report_id, user_id, "published", expected_rev,
                          version_id, print_content)


def reopen(report_id: int, *, expected_rev=None, version_id=None) -> Dict[str, Any]:
    with Session(_engine()) as sess:
        report = _report_for_write(sess, report_id)
        _advance(sess, report, expected_rev=expected_rev, version_id=version_id,
                 statuses=OFFICIAL_STATUSES, status="reviewing",
                 approved_by=None, approved_at=None, published_at=None,
                 status_error="只有审核通过或已发布的报告才能重新打开")
        _archive_legacy_official(sess, report)
        # Plans keep their existing version reference and detect later text edits by fingerprint.
        sess.refresh(report)
        result = _report_row(report)
        sess.commit()
        return result
