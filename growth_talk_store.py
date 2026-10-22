"""Growth Talk 数据层（SQLite / SQLAlchemy）。

所有 ORM 模型都挂在 ``db.Base`` 上，``db.init_db()`` 导入本模块后由
``Base.metadata.create_all`` 自动建表。对外函数统一返回 dict（或 dict 列表），
不把 ORM 实例泄漏给调用方；时间戳统一为 ``datetime.utcnow()`` 的 ISO 字符串。

本模块禁止 import app / blueprints（gtjob 子进程会直接 import 它）。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any, Iterable, Optional

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, func, select, update,
)
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

import db as _db

Base = _db.Base


# ---------------------------------------------------------------------------
# 模型（字段从 first-touch prisma/schema.prisma 1:1 翻译）
# ---------------------------------------------------------------------------
class GtSource(Base):
    __tablename__ = "gt_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    type = Column(String(50), nullable=False)
    purpose = Column(String(30), nullable=False, default="UNKNOWN")
    source_kind = Column(String(50), nullable=False)
    title = Column(String(300), nullable=False)
    content = Column(Text, nullable=False)
    mime_type = Column(String(200))
    file_name = Column(String(300))
    original_path = Column(String(500))
    file_size = Column(Integer)
    source_format = Column(String(50))
    external_report_id = Column(String(200))
    external_student_id = Column(String(200))
    external_version = Column(Integer)
    external_status = Column(String(50))
    external_confirmed_at = Column(String(32))
    external_confirmed_by = Column(String(200))
    structured_payload = Column(Text)
    extracted_text = Column(Text)
    extraction_status = Column(String(30), nullable=False, default="EXTRACTED")
    key_points_draft = Column(Text)
    key_points_confirmed = Column(Text)
    confirmed_at = Column(String(32))
    confirmed_by_name = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_gt_sources_student_created", "student_id", "created_at"),
    )


class GtRun(Base):
    __tablename__ = "gt_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    source_id = Column(Integer, ForeignKey("gt_sources.id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    revision = Column(Integer, nullable=False, default=1)
    status = Column(String(30), nullable=False, default="DRAFT")
    error = Column(Text)
    model = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("student_id", "version", name="uq_gt_runs_student_version"),
    )


class GtUnderstanding(Base):
    __tablename__ = "gt_understandings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("gt_runs.id"), nullable=False, unique=True)
    summary = Column(Text, nullable=False)
    topics = Column(Text, nullable=False, default="[]")
    keywords = Column(Text, nullable=False, default="[]")
    model = Column(String(100))
    status = Column(String(30), nullable=False, default="PENDING_REVIEW")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GtInterest(Base):
    __tablename__ = "gt_interest_evidence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("gt_runs.id"), nullable=False)
    label = Column(String(200), nullable=False)
    subtopic = Column(String(300))
    evidence = Column(Text, nullable=False)
    source_round = Column(String(200))
    evidence_strength = Column(String(20))
    uncertainty = Column(Text)
    preference_score = Column(Integer)
    competence_score = Column(Integer)
    special_focus = Column(Boolean, nullable=False, default=False)
    status = Column(String(30), nullable=False, default="PENDING_REVIEW")
    confirmed_at = Column(String(32))
    confirmed_by = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_gt_interest_run_status", "run_id", "status"),
    )


class GtQuadrant(Base):
    __tablename__ = "gt_quadrants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("gt_runs.id"), nullable=False, unique=True)
    points = Column(Text, nullable=False, default="[]")
    narrative = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default="DRAFT")
    model = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GtSuggestion(Base):
    __tablename__ = "gt_suggestions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("gt_runs.id"), nullable=False)
    title = Column(String(200), nullable=False)
    introduction = Column(Text, nullable=False)
    growth_value = Column(Text, nullable=False)
    possible_outputs = Column(Text, nullable=False, default="[]")
    recommendation_basis = Column(Text)
    interest_refs = Column(Text, nullable=False, default="[]")
    exploration_tags = Column(Text, nullable=False, default="[]")
    status = Column(String(30), nullable=False, default="DRAFT")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_gt_suggestions_run_status", "run_id", "status"),
    )


class GtReport(Base):
    __tablename__ = "gt_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    run_id = Column(Integer, ForeignKey("gt_runs.id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(30), nullable=False, default="DRAFT")
    payload = Column(Text, nullable=False)
    confirmed_at = Column(String(32))
    confirmed_by = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("student_id", "version", name="uq_gt_reports_student_version"),
    )


class ExternalIdentity(Base):
    __tablename__ = "external_identities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    source_system = Column(String(50), nullable=False)
    external_student_id = Column(String(200), nullable=False)
    details = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("source_system", "external_student_id",
                         name="uq_external_identities_system_external"),
        Index("ix_external_identities_student", "student_id"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_id = Column(Integer)
    student_id = Column(Integer)
    action = Column(String(100), nullable=False)
    details = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class CrmDeliveryReceipt(Base):
    __tablename__ = "crm_delivery_receipts"

    message_id = Column(String(200), primary_key=True)
    junction_student_id = Column(String(200), nullable=False)
    kind = Column(String(30), nullable=False)
    task_id = Column(String(200))
    revision = Column(Integer, nullable=False)
    payload_hash = Column(String(64), nullable=False)
    student_id = Column(Integer)
    received_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_crm_receipts_junction_kind_revision",
              "junction_student_id", "kind", "revision"),
    )


class CrmAppointment(Base):
    __tablename__ = "crm_appointments"

    task_id = Column(String(200), primary_key=True)
    junction_student_id = Column(String(200), nullable=False)
    student_id = Column(Integer)
    teacher_id = Column(Integer)
    revision = Column(Integer, nullable=False)
    status = Column(String(30), nullable=False)
    start_at = Column(String(32), nullable=False)
    end_at = Column(String(32), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_crm_appointments_teacher_status_start",
              "teacher_id", "status", "start_at"),
    )


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------
class RevisionConflict(Exception):
    """乐观锁 revision 不匹配，或引用了不允许删除的数据。"""


class NotFoundError(Exception):
    """目标记录不存在。"""


# ---------------------------------------------------------------------------
# 内部助手
# ---------------------------------------------------------------------------
def _engine():
    """读取 db.engine 的当前值（monkeypatch 测试可生效）。"""
    return _db.engine


def engine():
    """公开 engine 访问器，供 runs 等同包模块开启事务会话。"""
    return _db.engine


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _json_text(value: Any, default: str = "[]") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _model_dict(row, columns: Iterable[str]) -> dict:
    data = {}
    for name in columns:
        value = getattr(row, name, None)
        if isinstance(value, datetime):
            value = _iso(value)
        data[name] = value
    # CRM 表的业务主键是 message_id / task_id，没有 id 列。
    if hasattr(row, "id"):
        data["id"] = row.id
    return data


_SOURCE_FIELDS = (
    "student_id", "type", "purpose", "source_kind", "title", "content",
    "mime_type", "file_name", "original_path", "file_size", "source_format",
    "external_report_id", "external_student_id", "external_version",
    "external_status", "external_confirmed_at", "external_confirmed_by",
    "structured_payload", "extracted_text", "extraction_status",
    "key_points_draft", "key_points_confirmed", "confirmed_at",
    "confirmed_by_name", "created_at",
)

_RUN_FIELDS = (
    "student_id", "source_id", "version", "revision", "status", "error",
    "model", "created_at", "updated_at",
)

_INTEREST_FIELDS = (
    "run_id", "label", "subtopic", "evidence", "source_round",
    "evidence_strength", "uncertainty", "preference_score",
    "competence_score", "special_focus", "status", "confirmed_at",
    "confirmed_by", "created_at", "updated_at",
)

_QUADRANT_FIELDS = (
    "run_id", "points", "narrative", "status", "model", "created_at",
    "updated_at",
)

_SUGGESTION_FIELDS = (
    "run_id", "title", "introduction", "growth_value", "possible_outputs",
    "recommendation_basis", "interest_refs", "exploration_tags", "status",
    "created_at", "updated_at",
)

_REPORT_FIELDS = (
    "student_id", "run_id", "version", "status", "payload", "confirmed_at",
    "confirmed_by", "created_at",
)


def _source_dict(row: GtSource) -> dict:
    return _model_dict(row, _SOURCE_FIELDS)


def _run_dict(row: GtRun) -> dict:
    return _model_dict(row, _RUN_FIELDS)


def _interest_dict(row: GtInterest) -> dict:
    return _model_dict(row, _INTEREST_FIELDS)


def _quadrant_dict(row: GtQuadrant) -> dict:
    return _model_dict(row, _QUADRANT_FIELDS)


def _suggestion_dict(row: GtSuggestion) -> dict:
    return _model_dict(row, _SUGGESTION_FIELDS)


def _report_dict(row: GtReport) -> dict:
    return _model_dict(row, _REPORT_FIELDS)


def _receipt_dict(row: CrmDeliveryReceipt) -> dict:
    return _model_dict(row, (
        "message_id", "junction_student_id", "kind", "task_id", "revision",
        "payload_hash", "student_id", "received_at",
    ))


def _appointment_dict(row: CrmAppointment) -> dict:
    return _model_dict(row, (
        "task_id", "junction_student_id", "student_id", "teacher_id",
        "revision", "status", "start_at", "end_at", "updated_at",
    ))


def _get(run_value: Any, *names, default=None):
    for name in names:
        if isinstance(run_value, dict) and name in run_value:
            return run_value[name]
    return default


def _interest_values(item: dict) -> dict:
    return {
        "label": str(_get(item, "label", default="") or "").strip(),
        "subtopic": _get(item, "subtopic", "sub_topic"),
        "evidence": str(_get(item, "evidence", default="") or ""),
        "source_round": _get(item, "source_round", "sourceRound"),
        "evidence_strength": _get(item, "evidence_strength", "evidenceStrength"),
        "uncertainty": _get(item, "uncertainty"),
        "preference_score": _get(item, "preference_score", "preferenceScore"),
        "competence_score": _get(item, "competence_score", "competenceScore"),
        "special_focus": bool(_get(item, "special_focus", "specialFocus", default=False)),
        "status": _get(item, "status", default="PENDING_REVIEW"),
    }


def _suggestion_values(item: dict) -> dict:
    return {
        "title": str(_get(item, "title", default="") or "").strip(),
        "introduction": str(_get(item, "introduction", default="") or ""),
        "growth_value": str(_get(item, "growth_value", "growthValue", default="") or ""),
        "possible_outputs": _json_text(_get(item, "possible_outputs", "possibleOutputs")),
        "recommendation_basis": _get(item, "recommendation_basis", "recommendationBasis"),
        "interest_refs": _json_text(_get(item, "interest_refs", "interestRefs")),
        "exploration_tags": _json_text(_get(item, "exploration_tags", "explorationTags")),
        "status": _get(item, "status", default="DRAFT"),
    }


def _validate_score(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 3:
        raise ValueError("分值必须是 0 到 3 的整数")
    return value


def _source_referenced(sess: Session, source_id: int) -> bool:
    run_ids = select(GtRun.id).where(GtRun.source_id == source_id)
    if sess.execute(select(GtRun.id).where(GtRun.source_id == source_id)).first():
        return True
    if sess.execute(select(GtReport.id).where(GtReport.run_id.in_(run_ids))).first():
        return True
    return False


def _with_retry(fn, *, attempts: int = 3):
    """SQLite 写串行化的轻量重试（对应源仓库 Serializable/P2034/P2002）。"""
    last = None
    for attempt in range(attempts):
        try:
            return fn()
        except (IntegrityError, OperationalError) as exc:
            last = exc
            text = str(exc).lower()
            if "database is locked" not in text and "unique" not in text:
                raise
            if attempt + 1 >= attempts:
                raise
            time.sleep(0.05 * (attempt + 1))
    raise last  # pragma: no cover


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
def create_source(
    student_id: int,
    type: str,
    source_kind: str,
    title: str,
    content: str,
    *,
    purpose: str = "UNKNOWN",
    mime_type=None,
    file_name=None,
    original_path=None,
    file_size=None,
    source_format=None,
) -> dict:
    def _run():
        with Session(_engine()) as sess:
            row = GtSource(
                student_id=student_id, type=type, purpose=purpose,
                source_kind=source_kind, title=title, content=content,
                mime_type=mime_type, file_name=file_name,
                original_path=original_path, file_size=file_size,
                source_format=source_format,
            )
            sess.add(row)
            sess.commit()
            sess.refresh(row)
            return _source_dict(row)

    return _with_retry(_run)


def get_source(source_id: int) -> Optional[dict]:
    with Session(_engine()) as sess:
        row = sess.get(GtSource, source_id)
        return _source_dict(row) if row else None


def list_sources(student_id: int, type: str | None = None,
                 purpose: str | None = None) -> list[dict]:
    with Session(_engine()) as sess:
        stmt = select(GtSource).where(GtSource.student_id == student_id)
        if type:
            stmt = stmt.where(GtSource.type == type)
        if purpose:
            stmt = stmt.where(GtSource.purpose == purpose)
        stmt = stmt.order_by(GtSource.created_at.desc(), GtSource.id.desc())
        return [_source_dict(row) for row in sess.execute(stmt).scalars()]


def set_source_key_points(source_id: int, payload: str, status: str = "CONFIRMED") -> None:
    with Session(_engine()) as sess:
        row = sess.get(GtSource, source_id)
        if not row:
            raise NotFoundError("资料不存在")
        row.key_points_confirmed = payload
        if status == "CONFIRMED":
            row.confirmed_at = _iso(datetime.utcnow())
        sess.commit()


def is_source_referenced(source_id: int) -> bool:
    with Session(_engine()) as sess:
        return _source_referenced(sess, source_id)


def delete_source(source_id: int) -> None:
    with Session(_engine()) as sess:
        if _source_referenced(sess, source_id):
            raise RevisionConflict("资料已被历史分析或确认报告引用，不能删除")
        row = sess.get(GtSource, source_id)
        if row:
            sess.delete(row)
            sess.commit()


def delete_superseded_sources(student_id: int, type: str) -> None:
    with Session(_engine()) as sess:
        rows = sess.execute(
            select(GtSource)
            .where(GtSource.student_id == student_id, GtSource.type == type)
            .order_by(GtSource.created_at.desc(), GtSource.id.desc())
        ).scalars().all()
        for row in rows[1:]:
            if not _source_referenced(sess, row.id):
                sess.delete(row)
        sess.commit()


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------
def create_run(student_id: int, source_id: int) -> dict:
    def _run():
        with Session(_engine()) as sess:
            current = sess.execute(
                select(func.max(GtRun.version)).where(GtRun.student_id == student_id)
            ).scalar() or 0
            row = GtRun(
                student_id=student_id, source_id=source_id,
                version=current + 1, revision=1, status="RUNNING",
                model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            )
            sess.add(row)
            sess.commit()
            sess.refresh(row)
            return _run_dict(row)

    return _with_retry(_run)


def get_run(run_id: int) -> Optional[dict]:
    with Session(_engine()) as sess:
        row = sess.get(GtRun, run_id)
        return _run_dict(row) if row else None


def get_run_full(run_id: int) -> Optional[dict]:
    with Session(_engine()) as sess:
        row = sess.get(GtRun, run_id)
        if not row:
            return None
        data = _run_dict(row)
        understanding = sess.execute(
            select(GtUnderstanding).where(GtUnderstanding.run_id == run_id)
        ).scalar_one_or_none()
        quadrant = sess.execute(
            select(GtQuadrant).where(GtQuadrant.run_id == run_id)
        ).scalar_one_or_none()
        interests = sess.execute(
            select(GtInterest).where(GtInterest.run_id == run_id)
            .order_by(GtInterest.created_at.asc(), GtInterest.id.asc())
        ).scalars().all()
        suggestions = sess.execute(
            select(GtSuggestion).where(GtSuggestion.run_id == run_id)
            .order_by(GtSuggestion.created_at.asc(), GtSuggestion.id.asc())
        ).scalars().all()
        data["understanding"] = _model_dict(
            understanding,
            ("run_id", "summary", "topics", "keywords", "model", "status",
             "created_at", "updated_at"),
        ) if understanding else None
        data["interests"] = [_interest_dict(item) for item in interests]
        data["quadrant"] = _quadrant_dict(quadrant) if quadrant else None
        data["suggestions"] = [_suggestion_dict(item) for item in suggestions]
        return data


def list_runs(student_id: int) -> list[dict]:
    with Session(_engine()) as sess:
        ids = sess.execute(
            select(GtRun.id).where(GtRun.student_id == student_id)
            .order_by(GtRun.version.desc(), GtRun.id.desc())
        ).scalars().all()
    return [get_run_full(run_id) for run_id in ids]


def set_run_status(run_id: int, status: str, error: str | None = None) -> None:
    with Session(_engine()) as sess:
        sess.execute(
            update(GtRun).where(GtRun.id == run_id).values(
                status=status, error=error, updated_at=datetime.utcnow(),
            )
        )
        sess.commit()


def bump_run_revision(run_id: int, expected_revision: int) -> int:
    with Session(_engine()) as sess:
        result = sess.execute(
            update(GtRun)
            .where(GtRun.id == run_id, GtRun.revision == expected_revision)
            .values(revision=GtRun.revision + 1, updated_at=datetime.utcnow())
        )
        if not result.rowcount:
            sess.rollback()
            raise RevisionConflict("内容已更新，请刷新后重试")
        sess.commit()
        return int(sess.execute(
            select(GtRun.revision).where(GtRun.id == run_id)
        ).scalar_one())


# ---------------------------------------------------------------------------
# 审核实体
# ---------------------------------------------------------------------------
def save_understanding(run_id: int, summary: str, topics: str, keywords: str, model: str | None) -> None:
    with Session(_engine()) as sess:
        row = sess.execute(
            select(GtUnderstanding).where(GtUnderstanding.run_id == run_id)
        ).scalar_one_or_none()
        if row:
            row.summary = summary
            row.topics = topics
            row.keywords = keywords
            row.model = model
        else:
            sess.add(GtUnderstanding(
                run_id=run_id, summary=summary, topics=topics,
                keywords=keywords, model=model,
            ))
        sess.commit()


def replace_interests(run_id: int, items: list[dict]) -> None:
    with Session(_engine()) as sess:
        existing = sess.execute(
            select(GtInterest).where(GtInterest.run_id == run_id)
        ).scalars().all()
        for row in existing:
            sess.delete(row)
        for item in items:
            values = _interest_values(item)
            if not values["label"]:
                continue
            values["preference_score"] = _validate_score(values["preference_score"])
            values["competence_score"] = _validate_score(values["competence_score"])
            sess.add(GtInterest(run_id=run_id, **{
                k: v for k, v in values.items() if k != "run_id"
            }))
        sess.commit()


def save_quadrant(run_id: int, points: str, narrative: str, model: str | None) -> None:
    with Session(_engine()) as sess:
        row = sess.execute(
            select(GtQuadrant).where(GtQuadrant.run_id == run_id)
        ).scalar_one_or_none()
        if row:
            row.points = points
            row.narrative = narrative
            row.model = model
            row.status = "DRAFT"
            row.updated_at = datetime.utcnow()
        else:
            sess.add(GtQuadrant(
                run_id=run_id, points=points, narrative=narrative, model=model,
            ))
        sess.commit()


def replace_suggestions(run_id: int, items: list[dict]) -> None:
    """替换未确认的建议；已 CONFIRMED 的建议保留（对齐源 generateSuggestions）。"""
    with Session(_engine()) as sess:
        existing = sess.execute(
            select(GtSuggestion).where(
                GtSuggestion.run_id == run_id,
                GtSuggestion.status != "CONFIRMED",
            )
        ).scalars().all()
        for row in existing:
            sess.delete(row)
        for item in items:
            values = _suggestion_values(item)
            sess.add(GtSuggestion(run_id=run_id, **values))
        sess.commit()


def update_interest(interest_id: int, fields: dict) -> None:
    mapped = {
        "label": ("label", str),
        "subtopic": ("subtopic", None),
        "evidence": ("evidence", str),
        "source_round": ("source_round", None),
        "sourceRound": ("source_round", None),
        "evidence_strength": ("evidence_strength", None),
        "evidenceStrength": ("evidence_strength", None),
        "uncertainty": ("uncertainty", None),
        "preference_score": ("preference_score", "score"),
        "preferenceScore": ("preference_score", "score"),
        "competence_score": ("competence_score", "score"),
        "competenceScore": ("competence_score", "score"),
        "special_focus": ("special_focus", bool),
        "specialFocus": ("special_focus", bool),
        "status": ("status", str),
        "confirmed_at": ("confirmed_at", None),
        "confirmed_by": ("confirmed_by", None),
    }
    values = {}
    for key, value in fields.items():
        spec = mapped.get(key)
        if not spec:
            continue
        column, transform = spec
        if transform == "score":
            value = _validate_score(value)
        elif transform is bool:
            value = bool(value)
        elif transform is str and value is not None:
            value = str(value)
        values[column] = value
    if not values:
        return
    values["updated_at"] = datetime.utcnow()
    with Session(_engine()) as sess:
        sess.execute(
            update(GtInterest).where(GtInterest.id == interest_id).values(**values)
        )
        sess.commit()


def add_interest(run_id: int, label: str, **kw) -> dict:
    payload = {"label": label, "evidence": kw.pop("evidence", "顾问手动添加，待补充证据。"),
               "status": kw.pop("status", "PENDING_REVIEW")}
    payload.update(kw)
    values = _interest_values(payload)
    values["preference_score"] = _validate_score(values["preference_score"])
    values["competence_score"] = _validate_score(values["competence_score"])
    with Session(_engine()) as sess:
        row = GtInterest(run_id=run_id, **values)
        sess.add(row)
        sess.commit()
        sess.refresh(row)
        return _interest_dict(row)


def delete_interest(interest_id: int) -> None:
    with Session(_engine()) as sess:
        row = sess.get(GtInterest, interest_id)
        if row:
            sess.delete(row)
            sess.commit()


def confirm_interests(run_id: int, items: list[dict], confirmed_by: str) -> None:
    now = _iso(datetime.utcnow())
    with Session(_engine()) as sess:
        for item in items:
            interest_id = _get(item, "interestId", "interest_id")
            if interest_id is None:
                continue
            preference = _validate_score(_get(item, "preferenceScore", "preference_score"))
            competence = _validate_score(_get(item, "competenceScore", "competence_score"))
            sess.execute(
                update(GtInterest)
                .where(GtInterest.id == interest_id, GtInterest.run_id == run_id)
                .values(
                    preference_score=preference,
                    competence_score=competence,
                    status="CONFIRMED",
                    confirmed_at=now,
                    confirmed_by=confirmed_by,
                    updated_at=datetime.utcnow(),
                )
            )
        sess.commit()


def mark_outputs_stale(run_id: int) -> None:
    with Session(_engine()) as sess:
        sess.execute(
            update(GtQuadrant).where(GtQuadrant.run_id == run_id)
            .values(status="STALE", updated_at=datetime.utcnow())
        )
        sess.execute(
            update(GtSuggestion).where(GtSuggestion.run_id == run_id)
            .values(status="STALE", updated_at=datetime.utcnow())
        )
        sess.commit()


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def create_report(student_id: int, run_id: int, payload: str, confirmed_by: str,
                  *, payload_builder=None,
                  expected_revision: int | None = None) -> dict:
    def _run():
        confirmed_at = _iso(datetime.utcnow())
        with Session(_engine()) as sess:
            current = sess.execute(
                select(func.max(GtReport.version))
                .where(GtReport.student_id == student_id)
            ).scalar() or 0
            row = GtReport(
                student_id=student_id, run_id=run_id, version=current + 1,
                status="CONFIRMED", payload=payload,
                confirmed_at=confirmed_at, confirmed_by=confirmed_by,
            )
            sess.add(row)
            sess.flush()
            if payload_builder is not None:
                row.payload = payload_builder(row.id, row.version)
            sess.execute(
                update(GtUnderstanding).where(GtUnderstanding.run_id == run_id)
                .values(status="CONFIRMED", updated_at=datetime.utcnow())
            )
            sess.execute(
                update(GtQuadrant).where(GtQuadrant.run_id == run_id)
                .values(status="CONFIRMED", updated_at=datetime.utcnow())
            )
            bump = update(GtRun).where(GtRun.id == run_id)
            if expected_revision is not None:
                bump = bump.where(GtRun.revision == expected_revision)
            result = sess.execute(
                bump.values(revision=GtRun.revision + 1, updated_at=datetime.utcnow())
            )
            if not result.rowcount:
                sess.rollback()
                raise RevisionConflict("内容已变化，请重新预览")
            sess.add(AuditLog(
                actor_id=None, student_id=student_id, action="report_confirmed",
                details=json.dumps({
                    "runId": run_id, "version": current + 1,
                    "confirmedBy": confirmed_by,
                }, ensure_ascii=False),
            ))
            sess.commit()
            sess.refresh(row)
            return _report_dict(row)

    return _with_retry(_run)


def get_report(report_id: int) -> Optional[dict]:
    with Session(_engine()) as sess:
        row = sess.get(GtReport, report_id)
        return _report_dict(row) if row else None


def list_reports(student_id: int) -> list[dict]:
    with Session(_engine()) as sess:
        rows = sess.execute(
            select(GtReport).where(GtReport.student_id == student_id)
            .order_by(GtReport.version.desc(), GtReport.id.desc())
        ).scalars().all()
        return [_report_dict(row) for row in rows]


# ---------------------------------------------------------------------------
# 外部身份
# ---------------------------------------------------------------------------
def upsert_external_identity(student_id: int, source_system: str, external_student_id: str,
                             *, details: str | None = None) -> None:
    def _run():
        with Session(_engine()) as sess:
            row = sess.execute(
                select(ExternalIdentity).where(
                    ExternalIdentity.source_system == source_system,
                    ExternalIdentity.external_student_id == external_student_id,
                )
            ).scalar_one_or_none()
            if row:
                row.student_id = student_id
                if details is not None:
                    row.details = details
                row.updated_at = datetime.utcnow()
            else:
                sess.add(ExternalIdentity(
                    student_id=student_id, source_system=source_system,
                    external_student_id=external_student_id, details=details,
                ))
            sess.commit()

    _with_retry(_run)


def find_student_by_external(source_system: str, external_student_id: str) -> Optional[int]:
    with Session(_engine()) as sess:
        return sess.execute(
            select(ExternalIdentity.student_id).where(
                ExternalIdentity.source_system == source_system,
                ExternalIdentity.external_student_id == external_student_id,
            )
        ).scalar_one_or_none()


def get_external_identity(source_system: str, external_student_id: str) -> Optional[dict]:
    with Session(_engine()) as sess:
        row = sess.execute(
            select(ExternalIdentity).where(
                ExternalIdentity.source_system == source_system,
                ExternalIdentity.external_student_id == external_student_id,
            )
        ).scalar_one_or_none()
        if not row:
            return None
        return {
            "id": row.id, "student_id": row.student_id,
            "source_system": row.source_system,
            "external_student_id": row.external_student_id,
            "details": row.details,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }


def list_external_identities(student_id: int, source_system: str | None = None) -> list[dict]:
    with Session(_engine()) as sess:
        stmt = select(ExternalIdentity).where(ExternalIdentity.student_id == student_id)
        if source_system:
            stmt = stmt.where(ExternalIdentity.source_system == source_system)
        rows = sess.execute(stmt.order_by(ExternalIdentity.id.asc())).scalars().all()
        return [{
            "id": row.id, "student_id": row.student_id,
            "source_system": row.source_system,
            "external_student_id": row.external_student_id,
            "details": row.details,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        } for row in rows]


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------
def write_audit(actor_id: int | None, student_id: int | None, action: str, details: str) -> None:
    if not isinstance(details, str):
        details = json.dumps(details, ensure_ascii=False)
    with Session(_engine()) as sess:
        sess.add(AuditLog(actor_id=actor_id, student_id=student_id,
                          action=action, details=details))
        sess.commit()


def list_audit(student_id: int | None = None, action: str | None = None,
               limit: int = 100) -> list[dict]:
    with Session(_engine()) as sess:
        stmt = select(AuditLog)
        if student_id is not None:
            stmt = stmt.where(AuditLog.student_id == student_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        rows = sess.execute(
            stmt.order_by(AuditLog.id.desc()).limit(limit)
        ).scalars().all()
        return [{
            "id": row.id, "actor_id": row.actor_id,
            "student_id": row.student_id, "action": row.action,
            "details": row.details, "created_at": _iso(row.created_at),
        } for row in rows]


# ---------------------------------------------------------------------------
# CRM
# ---------------------------------------------------------------------------
def get_receipt(message_id: str) -> Optional[dict]:
    with Session(_engine()) as sess:
        row = sess.get(CrmDeliveryReceipt, message_id)
        return _receipt_dict(row) if row else None


def create_receipt(message_id: str, junction_student_id: str, kind: str,
                   revision: int, payload_hash: str, student_id: int | None = None,
                   task_id: str | None = None) -> dict:
    with Session(_engine()) as sess:
        row = CrmDeliveryReceipt(
            message_id=message_id, junction_student_id=junction_student_id,
            kind=kind, task_id=task_id, revision=revision,
            payload_hash=payload_hash, student_id=student_id,
        )
        sess.add(row)
        sess.commit()
        sess.refresh(row)
        return _receipt_dict(row)


def get_appointment(task_id: str) -> Optional[dict]:
    with Session(_engine()) as sess:
        row = sess.get(CrmAppointment, task_id)
        return _appointment_dict(row) if row else None


def list_appointments(teacher_id: int | None = None) -> list[dict]:
    with Session(_engine()) as sess:
        stmt = select(CrmAppointment)
        if teacher_id is not None:
            stmt = stmt.where(CrmAppointment.teacher_id == teacher_id)
        rows = sess.execute(
            stmt.order_by(CrmAppointment.start_at.asc(), CrmAppointment.task_id.asc())
        ).scalars().all()
        return [_appointment_dict(row) for row in rows]


def upsert_appointment(task_id: str, junction_student_id: str,
                       student_id: int | None, teacher_id: int | None,
                       revision: int, status: str, start_at: str,
                       end_at: str) -> dict:
    with Session(_engine()) as sess:
        row = sess.get(CrmAppointment, task_id)
        if row:
            row.junction_student_id = junction_student_id
            row.student_id = student_id
            row.teacher_id = teacher_id
            row.revision = revision
            row.status = status
            row.start_at = start_at
            row.end_at = end_at
            row.updated_at = datetime.utcnow()
        else:
            row = CrmAppointment(
                task_id=task_id, junction_student_id=junction_student_id,
                student_id=student_id, teacher_id=teacher_id,
                revision=revision, status=status,
                start_at=start_at, end_at=end_at,
            )
            sess.add(row)
        sess.commit()
        sess.refresh(row)
        return _appointment_dict(row)
