"""DP13 collaboration: student M1 team, presence, leases and section patches.

The module is deliberately independent from Flask. All authoritative state lives
in the database: team membership, presence heartbeats, edit leases, section
versions, a plan-wide document epoch and an idempotency log.

Concurrency model
-----------------
* SQLite: every write starts with ``BEGIN IMMEDIATE`` so the read/modify/write
  sequence cannot interleave with another writer.
* Other databases: the plan row is locked with ``SELECT ... FOR UPDATE``.
* Section patches therefore read the *current* document after the write lock is
  held and merge into it. Two different sections never overwrite each other;
  the same section is additionally protected by section versions and leases.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import growth_talk_store as _gt
from sqlalchemy import (Column, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint, delete, func, select, update)
from sqlalchemy.orm import Session

import db as _db
import m1.plan_quality as plan_quality
import m1.plan_store as pstore
import m1.store as store

Base = pstore.Base

# --- numeric defaults (also published in DP13-COLLAB-CONTRACT.md) -----------
PRESENCE_TTL_SECONDS = 60
PRESENCE_MIN_INTERVAL_SECONDS = 2
PRESENCE_RETENTION_HOURS = 24
PRESENCE_MAX_ROWS_PER_PLAN = 50
LEASE_TTL_SECONDS = 90
POLL_SECONDS = 15
PATCH_IDEMPOTENCY_DAYS = 7
PATCH_LOG_LIMIT = 200
TAB_ID_MAX = 64
IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")

TEAM_ROLES = ("primary", "co_mentor")
PRESENCE_STATES = ("viewing", "editing", "saving", "saved", "conflict", "offline")
PLAN_SECTIONS = {"header", "durations", "brief", "inputs", "personal", "goals"}
PARENT_SECTIONS = {"parent.intro", "parent.transition", "parent.practice_options",
                   "parent.practice", "parent.family", "parent.family_seen",
                   "parent.review"}
DOCUMENT_SECTIONS = {"internal.document", "parent.document"}
SESSION_RE = re.compile(r"^internal\.session\.([1-3])$")
ACTIVITIES_RE = re.compile(r"^internal\.session\.([1-3])\.activities$")
PRACTICE_LIST_RE = re.compile(r"^internal\.session\.([1-3])\.practice$")
ACTIVITY_RE = re.compile(r"^internal\.session\.([1-3])\.activity\.([^/]{1,120})$")
PRACTICE_RE = re.compile(r"^internal\.session\.([1-3])\.practice\.([^/]{1,120})$")
PARENT_GOAL_RE = re.compile(r"^parent\.goal\.([A-Za-z0-9._-]{1,40})$")
PARENT_SESSION_RE = re.compile(r"^parent\.session\.([1-3])$")

SESSION_FIELDS = {"title", "review", "focus", "content", "evidence", "next_prep"}
ACTIVITY_FIELDS = {"name", "minutes", "steps", "questions", "materials", "source"}
PRACTICE_FIELDS = {"code", "name", "task", "frequency", "platform", "evidence"}
PARENT_SESSION_FIELDS = {"title", "summary"}


class CollaborationError(Exception):
    status = 409
    code = "collaboration_error"

    def payload(self) -> Dict[str, Any]:
        return {"ok": False, "error": str(self), "code": self.code}


class PermissionDenied(CollaborationError):
    status = 403
    code = "forbidden"


class UnknownUser(CollaborationError):
    status = 400
    code = "unknown_user"


class InvalidSection(CollaborationError):
    status = 400
    code = "invalid_section"


class ItemNotFound(CollaborationError):
    status = 404
    code = "item_not_found"


class StaleDocument(CollaborationError):
    status = 409
    code = "stale_document"

    def __init__(self, expected, current):
        super().__init__("计划已在别处更新，请刷新后再编辑")
        self.expected = expected
        self.current = current

    def payload(self):
        data = super().payload()
        data.update(expected=self.expected, current=self.current)
        return data


class StaleSection(CollaborationError):
    status = 409
    code = "stale_section"

    def __init__(self, section, expected, current, value=None):
        super().__init__("这一部分已在别处更新，请对比后再保存")
        self.section = section
        self.expected = expected
        self.current = current
        self.value = value

    def payload(self):
        data = super().payload()
        data.update(section=self.section, expected_version=self.expected,
                    current_version=self.current, current=self.value)
        return data


class LeaseRequired(CollaborationError):
    status = 409
    code = "lease_required"

    def __init__(self, section):
        super().__init__("请先取得这一部分的编辑权")
        self.section = section

    def payload(self):
        data = super().payload()
        data["section"] = self.section
        return data


class LeaseConflict(CollaborationError):
    status = 409
    code = "lease_conflict"

    def __init__(self, section, holder=None, reason="held"):
        super().__init__("这一部分正在被其他导师编辑" if holder
                         else "编辑权已失效，请重新取得")
        self.section = section
        self.holder = holder
        self.reason = reason

    def payload(self):
        data = super().payload()
        data.update(section=self.section, reason=self.reason, holder=self.holder)
        return data


class IdempotencyConflict(CollaborationError):
    status = 409
    code = "idempotency_conflict"

    def __init__(self, key):
        super().__init__("这个保存请求编号已被用于另一份内容")
        self.key = key

    def payload(self):
        data = super().payload()
        data["idempotency_key"] = self.key
        return data


class StaleFamilyAck(CollaborationError):
    status = 409
    code = "stale_family_ack"

    def __init__(self, expected, current, family=None):
        super().__init__("家庭建议已改动，请重新阅读并确认")
        self.expected = expected
        self.current = current
        self.family = family

    def payload(self):
        data = super().payload()
        data.update(expected_hashes=self.expected, current_hashes=self.current,
                    family=self.family)
        return data


class ParentBlocking(CollaborationError):
    status = 409
    code = "parent_blocking"

    def __init__(self, blocking):
        super().__init__("还有 %d 项需要处理" % len(blocking))
        self.blocking = blocking or []

    def payload(self):
        data = super().payload()
        data["blocking"] = self.blocking
        return data


# ---------------------------------------------------------------------------
# Models (additive; no existing table/column is altered)
# ---------------------------------------------------------------------------
class PlanTeamMember(Base):
    __tablename__ = "m1_plan_team_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String(20), nullable=False, default="co_mentor")
    added_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("student_id", "user_id", name="ux_m1_plan_team_student_user"),
    )


class PlanPresence(Base):
    __tablename__ = "m1_plan_presence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey("m1_plans.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tab_id = Column(String(TAB_ID_MAX), nullable=False, default="")
    state = Column(String(20), nullable=False, default="viewing")
    editing_section = Column(String(200), nullable=False, default="")
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("plan_id", "user_id", "tab_id",
                         name="ux_m1_plan_presence_plan_user_tab"),
    )


class PlanEditLease(Base):
    __tablename__ = "m1_plan_edit_leases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey("m1_plans.id"), nullable=False)
    section_key = Column(String(200), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tab_id = Column(String(TAB_ID_MAX), nullable=False, default="")
    token = Column(String(64), nullable=False, default="")
    acquired_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    renewed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    released_at = Column(DateTime)
    release_reason = Column(String(20))

    __table_args__ = (
        UniqueConstraint("token", name="ux_m1_plan_lease_token"),
    )


class PlanSectionVersion(Base):
    __tablename__ = "m1_plan_section_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey("m1_plans.id"), nullable=False)
    section_key = Column(String(200), nullable=False)
    version = Column(Integer, nullable=False, default=0)
    updated_by = Column(Integer)
    updated_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("plan_id", "section_key", name="ux_m1_plan_section_version"),
    )


class PlanCollabState(Base):
    __tablename__ = "m1_plan_collab_state"

    plan_id = Column(Integer, ForeignKey("m1_plans.id"), primary_key=True)
    document_version = Column(Integer, nullable=False, default=1)
    updated_by = Column(Integer)
    updated_at = Column(DateTime, default=datetime.utcnow)


class PlanPatchLog(Base):
    __tablename__ = "m1_plan_patch_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey("m1_plans.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    section_key = Column(String(200), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False, default="")
    expected_version = Column(Integer)
    document_version = Column(Integer)
    result = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("plan_id", "idempotency_key",
                         name="ux_m1_plan_patch_idempotency"),
    )


def ensure_tables(engine=None) -> None:
    target = engine or pstore._engine()
    for table in (PlanTeamMember.__table__, PlanPresence.__table__,
                  PlanEditLease.__table__, PlanSectionVersion.__table__,
                  PlanCollabState.__table__, PlanPatchLog.__table__):
        table.create(target, checkfirst=True)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.utcnow()


def _writer(sess: Session) -> None:
    # SQLite: reserve the writer lock *before* reading, so read/modify/write is
    # serialized across workers and processes sharing the same database file.
    bind = sess.get_bind()
    if bind is not None and bind.dialect.name == "sqlite":
        sess.connection().exec_driver_sql("BEGIN IMMEDIATE")


def _lock_plan(sess: Session, plan_id: int):
    stmt = select(pstore.M1Plan).where(pstore.M1Plan.id == int(plan_id))
    bind = sess.get_bind()
    if bind is not None and bind.dialect.name != "sqlite":
        stmt = stmt.with_for_update()
    return sess.execute(stmt).scalars().first()


def _active_user(sess: Session, user_id):
    if user_id is None:
        return None
    try:
        row = sess.get(_db.User, int(user_id))
    except (TypeError, ValueError):
        return None
    if row is None or not int(row.is_active or 0):
        return None
    return row


def _effective(user: Dict[str, Any]) -> Dict[str, Any]:
    return _db.effective_account_settings(
        user.get("role") or "", user.get("student_scope"),
        user.get("detail_level"), user.get("m1_access"),
        user.get("m1_admin"))


def _user_name(sess: Session, user_id) -> str:
    row = sess.get(_db.User, int(user_id)) if user_id else None
    if row is None:
        return ""
    return row.display_name or row.advisor_name or row.username or ""


def _team_row(sess: Session, student_id, user_id):
    return sess.execute(select(PlanTeamMember).where(
        PlanTeamMember.student_id == int(student_id),
        PlanTeamMember.user_id == int(user_id))).scalars().first()


def _is_team_member(user: Dict[str, Any], student_id) -> bool:
    uid = user.get("user_id")
    if uid is None or student_id is None:
        return False
    with Session(pstore._engine()) as sess:
        if _active_user(sess, uid) is None:
            return False
        return _team_row(sess, student_id, uid) is not None


def _can_view_student_in_session(sess, user: Dict[str, Any], student_id) -> bool:
    if _active_user(sess, user.get("user_id")) is None:
        return False
    settings = _effective(user)
    if settings.get("m1_access") != 1:
        return False
    role = user.get("role") or ""
    if role not in ("admin", "advisor"):
        return False
    if store._sees_all_students(user):
        return True
    assigned = store.assigned_students_query(user["user_id"]).subquery()
    if sess.scalar(select(assigned.c.student_id).where(assigned.c.student_id == student_id)):
        return True
    student = sess.get(_db.Student, int(student_id))
    if student is None:
        return False
    name = (user.get("advisor_name") or "").strip()
    return bool(name) and (student.advisor_name or "").strip() == name


def _can_view_plan_in_session(sess, plan: Dict[str, Any], user: Dict[str, Any]) -> bool:
    if _active_user(sess, user.get("user_id")) is None:
        return False
    settings = _effective(user)
    if settings.get("m1_access") != 1:
        return False
    if plan.get("source_mode") == "mentor_inputs":
        return _can_view_student_in_session(sess, user, plan.get("student_id"))
    if _can_view_student_in_session(sess, user, plan.get("student_id")):
        return True
    prep = sess.get(pstore.store.M1Prep, int(plan.get("prep_id") or 0))
    if prep is None:
        return False
    if prep.mentor_user_id is not None and user.get("user_id") is not None:
        if int(prep.mentor_user_id) == int(user.get("user_id")):
            return True
    return False


def can_view_student_plans(user, student_id: int) -> bool:
    u = store._user_dict(user)
    with Session(pstore._engine()) as sess:
        return _can_view_student_in_session(sess, u, student_id)


def can_edit_in_session(sess, plan: Dict[str, Any], user: Dict[str, Any]) -> bool:
    if not _can_view_plan_in_session(sess, plan, user):
        return False
    settings = _effective(user)
    if user.get("role") == "admin" or settings.get("m1_admin") == 1:
        return True
    uid = user.get("user_id")
    if uid is None:
        return False
    mentor_id = plan.get("mentor_user_id")
    if mentor_id is not None and int(mentor_id) == int(uid):
        return True
    return _team_row(sess, plan.get("student_id"), uid) is not None


def can_approve_in_session(sess, plan: Dict[str, Any], user: Dict[str, Any]) -> bool:
    if not _can_view_plan_in_session(sess, plan, user):
        return False
    settings = _effective(user)
    if user.get("role") == "admin" or settings.get("m1_admin") == 1:
        return True
    uid = user.get("user_id")
    mentor_id = plan.get("mentor_user_id")
    return uid is not None and mentor_id is not None and int(mentor_id) == int(uid)


def can_manage_team(user=None) -> bool:
    u = store._user_dict(user)
    return u.get("role") == "admin" or store.is_m1_admin(u)


def plan_role(user, plan) -> Optional[str]:
    if not plan:
        return None
    u = store._user_dict(user)
    uid = u.get("user_id")
    settings = _effective(u)
    if u.get("role") == "admin" or settings.get("m1_admin") == 1:
        return "admin"
    if uid is not None and plan.get("mentor_user_id") is not None \
            and int(plan["mentor_user_id"]) == int(uid):
        return "primary"
    if _is_team_member(u, plan.get("student_id")):
        return "co_mentor"
    return None


# ---------------------------------------------------------------------------
# Section keys and values
# ---------------------------------------------------------------------------
def valid_section_key(section: str) -> bool:
    if not isinstance(section, str) or not section or len(section) > 200:
        return False
    if section in PLAN_SECTIONS or section in PARENT_SECTIONS \
            or section in DOCUMENT_SECTIONS \
            or section in ("internal.overview", "internal.mentor_notes"):
        return True
    return bool(SESSION_RE.match(section) or ACTIVITIES_RE.match(section)
                or PRACTICE_LIST_RE.match(section) or ACTIVITY_RE.match(section)
                or PRACTICE_RE.match(section) or PARENT_GOAL_RE.match(section)
                or PARENT_SESSION_RE.match(section))


def _require_section(section: str) -> str:
    if not valid_section_key(section):
        raise InvalidSection("未知的编辑部分")
    return section


def _doc_part(section: str) -> Optional[str]:
    if section.startswith("internal."):
        return "internal"
    if section.startswith("parent."):
        return "parent"
    return None


def _field(value, default_src: str = "mentor") -> Dict[str, str]:
    if isinstance(value, str):
        return {"text": value.strip(), "src": default_src}
    if not isinstance(value, dict) or set(value) - {"text", "src"}:
        raise ValueError("文字字段格式不正确")
    text = value.get("text")
    if not isinstance(text, str):
        raise ValueError("文字字段缺少 text")
    src = value.get("src") or default_src
    if src not in ("ai", "edited", "mentor"):
        raise ValueError("文字字段来源不正确")
    return {"text": text.strip(), "src": src}


def _merge_field(current, value, default_src="mentor") -> Dict[str, str]:
    incoming = _field(value, default_src)
    old = current if isinstance(current, dict) else {}
    if incoming["text"] == str(old.get("text") or ""):
        return {"text": incoming["text"], "src": old.get("src") or default_src}
    return {"text": incoming["text"],
            "src": incoming.get("src") if incoming.get("src") != default_src
            else "mentor"}


def _section_versions(sess: Session, plan_id: int) -> Dict[str, int]:
    rows = sess.execute(select(PlanSectionVersion).where(
        PlanSectionVersion.plan_id == int(plan_id))).scalars().all()
    return {row.section_key: int(row.version or 0) for row in rows}


def section_versions(plan_id: int) -> Dict[str, int]:
    with Session(pstore._engine()) as sess:
        return _section_versions(sess, plan_id)


def _collab_state(sess: Session, plan_id: int) -> Optional[PlanCollabState]:
    return sess.get(PlanCollabState, int(plan_id))


def _document_version(sess: Session, plan_id: int) -> int:
    row = _collab_state(sess, plan_id)
    return int(row.document_version or 1) if row is not None else 1


def document_version(plan_id: int) -> int:
    with Session(pstore._engine()) as sess:
        return _document_version(sess, plan_id)


def bump_section_in_session(sess: Session, plan_id: int, section: str,
                            actor_id=None) -> int:
    _require_section(section)
    row = sess.execute(select(PlanSectionVersion).where(
        PlanSectionVersion.plan_id == int(plan_id),
        PlanSectionVersion.section_key == section)).scalars().first()
    if row is None:
        row = PlanSectionVersion(plan_id=int(plan_id), section_key=section,
                                 version=1, updated_by=actor_id,
                                 updated_at=_now())
        sess.add(row)
        sess.flush()
        return 1
    row.version = int(row.version or 0) + 1
    row.updated_by = actor_id
    row.updated_at = _now()
    sess.flush()
    return int(row.version)


def bump_document_in_session(sess: Session, plan_id: int, actor_id=None) -> int:
    row = _collab_state(sess, plan_id)
    if row is None:
        row = PlanCollabState(plan_id=int(plan_id), document_version=2,
                              updated_by=actor_id, updated_at=_now())
        sess.add(row)
        sess.flush()
        return 2
    row.document_version = int(row.document_version or 1) + 1
    row.updated_by = actor_id
    row.updated_at = _now()
    sess.flush()
    return int(row.document_version)


def _section_value(sess: Session, plan: Dict[str, Any], section: str):
    if section == "header":
        return {key: plan.get(key) for key in
                ("block_no", "period_start", "period_end", "credits")}
    if section == "durations":
        return plan.get("session_durations")
    if section == "brief":
        return plan.get("teaching_brief")
    if section == "inputs":
        return plan.get("inputs")
    if section == "personal":
        return plan.get("personal")
    if section == "goals":
        return plan.get("goals")
    part = "internal" if section.startswith("internal.") else "parent"
    version_id = (plan.get("current_version_id") if part == "internal"
                  else plan.get("parent_version_id"))
    if not version_id:
        return None
    version = sess.get(pstore.M1PlanVersion, int(version_id))
    if version is None:
        return None
    doc = pstore.normalize_doc_shape(pstore._loads(version.doc, {}))
    return _extract_section(doc, section)


def _extract_section(doc, section: str):
    if not isinstance(doc, dict):
        return None
    if section in ("internal.overview",):
        return doc.get("overview")
    if section == "internal.mentor_notes":
        return doc.get("mentor_notes")
    other = {"parent.intro": "intro", "parent.transition": "transition",
             "parent.practice_options": "practice_options",
             "parent.practice": "practice", "parent.family": "family",
             "parent.family_seen": "family_seen", "parent.review": "review"}
    if section in other:
        return doc.get(other[section])
    match = SESSION_RE.match(section) or PARENT_SESSION_RE.match(section)
    if match:
        n = int(match.group(1))
        sessions = doc.get("sessions") or []
        return sessions[n - 1] if n <= len(sessions) else None
    match = PARENT_GOAL_RE.match(section)
    if match:
        code = match.group(1)
        return next((item for item in doc.get("goals") or []
                     if isinstance(item, dict) and item.get("code") == code), None)
    match = ACTIVITY_RE.match(section)
    if match:
        n, activity_id = int(match.group(1)), match.group(2)
        sessions = doc.get("sessions") or []
        if n > len(sessions):
            return None
        return next((item for item in sessions[n - 1].get("activities") or []
                     if isinstance(item, dict) and item.get("id") == activity_id), None)
    match = ACTIVITIES_RE.match(section)
    if match:
        n = int(match.group(1))
        sessions = doc.get("sessions") or []
        return (sessions[n - 1].get("activities") or []) if n <= len(sessions) else None
    match = PRACTICE_RE.match(section)
    if match:
        n, practice_id = int(match.group(1)), match.group(2)
        sessions = doc.get("sessions") or []
        if n > len(sessions):
            return None
        return next((item for item in sessions[n - 1].get("practice") or []
                     if isinstance(item, dict) and item.get("id") == practice_id), None)
    match = PRACTICE_LIST_RE.match(section)
    if match:
        n = int(match.group(1))
        sessions = doc.get("sessions") or []
        return (sessions[n - 1].get("practice") or []) if n <= len(sessions) else None
    return None


# ---------------------------------------------------------------------------
# List/item dependencies and family acknowledgements
# ---------------------------------------------------------------------------
def list_parent_section(section: str) -> Optional[str]:
    """The whole-list section whose payload contains this item, if any."""
    match = ACTIVITY_RE.match(section or "")
    if match:
        return "internal.session.%s.activities" % match.group(1)
    match = PRACTICE_RE.match(section or "")
    if match:
        return "internal.session.%s.practice" % match.group(1)
    return None


def _list_child_prefix(section: str) -> Optional[str]:
    match = ACTIVITIES_RE.match(section or "")
    if match:
        return "internal.session.%s.activity." % match.group(1)
    match = PRACTICE_LIST_RE.match(section or "")
    if match:
        return "internal.session.%s.practice." % match.group(1)
    return None


def _list_item_ids(doc, list_section: str) -> set:
    if not isinstance(doc, dict):
        return set()
    import re as _re
    match = _re.match(r"^internal\.session\.([1-3])\.(activities|practice)$",
                      list_section or "")
    if not match:
        return set()
    n = int(match.group(1))
    sessions = doc.get("sessions") or []
    if n > len(sessions) or not isinstance(sessions[n - 1], dict):
        return set()
    key = "activities" if match.group(2) == "activities" else "practice"
    return {item.get("id") for item in sessions[n - 1].get(key) or []
            if isinstance(item, dict) and isinstance(item.get("id"), str)
            and item.get("id")}


def _related_active_lease(sess: Session, plan_id: int, section: str):
    """Find a lease that overlaps the same storage (parent list <-> child item)."""
    parent = list_parent_section(section)
    if parent:
        lease = _active_lease(sess, plan_id, parent)
        if lease is not None:
            return lease
    prefix = _list_child_prefix(section)
    if prefix:
        now = _now()
        return sess.execute(select(PlanEditLease).where(
            PlanEditLease.plan_id == int(plan_id),
            PlanEditLease.section_key.startswith(prefix),
            PlanEditLease.released_at.is_(None),
            PlanEditLease.expires_at > now)
            .order_by(PlanEditLease.id.desc())).scalars().first()
    return None


def _require_no_related_lease(sess: Session, plan_id: int, section: str,
                              exclude_token: str = "") -> None:
    lease = _related_active_lease(sess, plan_id, section)
    if lease is None:
        return
    if exclude_token and str(lease.token) == str(exclude_token):
        return
    raise LeaseConflict(section, holder=_holder(sess, lease),
                        reason="related_section")


def family_hash(value) -> str:
    text = str(value.get("text") or "") if isinstance(value, dict) else str(value or "")
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()


def family_state(doc) -> List[Dict[str, Any]]:
    """Derive the effective acknowledgement bound to the current advice text."""
    doc = doc if isinstance(doc, dict) else {}
    family = doc.get("family") if isinstance(doc.get("family"), list) else []
    seen = doc.get("family_seen") if isinstance(doc.get("family_seen"), list) else []
    acks = doc.get("family_ack") if isinstance(doc.get("family_ack"), list) else []
    out = []
    for index in range(2):
        current = family[index] if index < len(family) else {}
        current_hash = family_hash(current)
        ack = acks[index] if index < len(acks) and isinstance(acks[index], dict) else {}
        ack_hash = ack.get("hash") if isinstance(ack.get("hash"), str) else current_hash
        effective = bool(seen[index]) if index < len(seen) else False
        if ack_hash != current_hash:
            # Acknowledged text no longer matches the current advice.
            effective = False
        out.append({"hash": current_hash,
                    "ack_hash": ack_hash,
                    "seen": effective,
                    "text": str(current.get("text") or "") if isinstance(current, dict)
                    else str(current or "")})
    return out


def sync_family_ack(doc, previous=None) -> bool:
    """Persist effective acknowledgement hashes; reset only changed advice.

    ``previous`` is the family state before a text edit, used when the stored
    document predates ``family_ack``. Returns True when the ack fields changed.
    """
    if not isinstance(doc, dict):
        return False
    state = family_state(doc)
    if previous is not None:
        for index, item in enumerate(state):
            old_hash = previous[index]["hash"] if index < len(previous) else None
            if old_hash is not None and old_hash != item["hash"]:
                item["seen"] = False
    new_seen = [bool(item.get("seen")) for item in state]
    new_ack = [{"hash": item["hash"], "seen": bool(item.get("seen"))}
               for item in state]
    changed = doc.get("family_seen") != new_seen or doc.get("family_ack") != new_ack
    doc["family_seen"] = new_seen
    doc["family_ack"] = new_ack
    return changed


def _family_blocking_doc(doc):
    effective = copy.deepcopy(doc) if isinstance(doc, dict) else {}
    sync_family_ack(effective)
    return effective


def normalize_family_for_save(before_doc, after_doc) -> None:
    """Whole-document parent save: keep acknowledgements only for unchanged text."""
    if not isinstance(after_doc, dict):
        return
    after_family = after_doc.get("family") if isinstance(after_doc.get("family"), list) else []
    before_family = ((before_doc or {}).get("family")
                     if isinstance((before_doc or {}).get("family"), list) else [])
    seen = after_doc.get("family_seen") if isinstance(
        after_doc.get("family_seen"), list) else [False, False]
    seen = list(seen[:2]) + [False] * max(0, 2 - len(seen[:2]))
    if before_doc is not None:
        for index in range(2):
            old = before_family[index] if index < len(before_family) else {}
            new = after_family[index] if index < len(after_family) else {}
            if family_hash(old) != family_hash(new):
                seen[index] = False
    after_doc["family_seen"] = seen
    sync_family_ack(after_doc)


# ---------------------------------------------------------------------------
# Presence and leases
# ---------------------------------------------------------------------------
def _active_lease(sess: Session, plan_id: int, section: str):
    now = _now()
    return sess.execute(select(PlanEditLease).where(
        PlanEditLease.plan_id == int(plan_id),
        PlanEditLease.section_key == section,
        PlanEditLease.released_at.is_(None),
        PlanEditLease.expires_at > now)
        .order_by(PlanEditLease.id.desc())).scalars().first()


def _expire_leases(sess: Session, plan_id: int) -> None:
    now = _now()
    rows = sess.execute(select(PlanEditLease).where(
        PlanEditLease.plan_id == int(plan_id),
        PlanEditLease.released_at.is_(None),
        PlanEditLease.expires_at <= now)).scalars().all()
    for row in rows:
        row.released_at = now
        row.release_reason = "expired"


def _lease_payload(sess: Session, lease) -> Dict[str, Any]:
    return {"section": lease.section_key, "user_id": lease.user_id,
            "name": _user_name(sess, lease.user_id), "tab_id": lease.tab_id,
            "acquired_at": pstore._iso(lease.acquired_at),
            "renewed_at": pstore._iso(lease.renewed_at),
            "expires_at": pstore._iso(lease.expires_at)}


def _holder(sess: Session, lease) -> Dict[str, Any]:
    return {"user_id": lease.user_id, "name": _user_name(sess, lease.user_id),
            "tab_id": lease.tab_id, "expires_at": pstore._iso(lease.expires_at)}


def _require_lease(sess: Session, plan_id: int, section: str,
                   user_id, token, *, required: bool) -> Optional[PlanEditLease]:
    lease = _active_lease(sess, plan_id, section)
    if lease is None:
        if required:
            raise LeaseRequired(section)
        if token:
            raise LeaseConflict(section, reason="expired")
        return None
    if user_id is None or int(lease.user_id) != int(user_id):
        raise LeaseConflict(section, holder=_holder(sess, lease))
    if required or token:
        if not token or str(lease.token) != str(token):
            raise LeaseConflict(section, holder=_holder(sess, lease),
                                reason="token_invalid")
    lease.tab_id = lease.tab_id or ""
    lease.renewed_at = _now()
    lease.expires_at = _now() + timedelta(seconds=LEASE_TTL_SECONDS)
    return lease


def acquire_lease(plan_id: int, section: str, user: Dict[str, Any],
                  tab_id: str) -> Dict[str, Any]:
    section = _require_section(section)
    tab_id = _tab_id(tab_id)
    with Session(pstore._engine()) as sess:
        _writer(sess)
        row = _lock_plan(sess, plan_id)
        if row is None:
            raise pstore.NotFound("发展计划不存在")
        plan = pstore._plan_row(sess, row)
        if not can_edit_in_session(sess, plan, user):
            raise PermissionDenied("只有负责导师可以编辑该计划")
        _expire_leases(sess, plan_id)
        lease = _active_lease(sess, plan_id, section)
        if lease is not None and int(lease.user_id) != int(user.get("user_id")):
            raise LeaseConflict(section, holder=_holder(sess, lease))
        _require_no_related_lease(sess, plan_id, section)
        if lease is None:
            lease = PlanEditLease(
                plan_id=int(plan_id), section_key=section,
                user_id=int(user.get("user_id")), tab_id=tab_id,
                token=uuid.uuid4().hex, acquired_at=_now(), renewed_at=_now(),
                expires_at=_now() + timedelta(seconds=LEASE_TTL_SECONDS))
            sess.add(lease)
            sess.flush()
        else:
            lease.tab_id = tab_id
            lease.renewed_at = _now()
            lease.expires_at = _now() + timedelta(seconds=LEASE_TTL_SECONDS)
        result = _lease_payload(sess, lease)
        sections = _section_versions(sess, plan_id)
        result.update(version=sections.get(section, 0),
                      document_version=_document_version(sess, plan_id),
                      token=lease.token, expires_in=LEASE_TTL_SECONDS,
                      ttl=LEASE_TTL_SECONDS)
        sess.commit()
        return result


def renew_lease(plan_id: int, section: str, token: str,
                user: Dict[str, Any], tab_id: str = "") -> Dict[str, Any]:
    section = _require_section(section)
    with Session(pstore._engine()) as sess:
        _writer(sess)
        row = _lock_plan(sess, plan_id)
        if row is None:
            raise pstore.NotFound("发展计划不存在")
        plan = pstore._plan_row(sess, row)
        if not can_edit_in_session(sess, plan, user):
            raise PermissionDenied("只有负责导师可以编辑该计划")
        _expire_leases(sess, plan_id)
        lease = _active_lease(sess, plan_id, section)
        if lease is None:
            raise LeaseConflict(section, reason="expired")
        if int(lease.user_id) != int(user.get("user_id")) or str(lease.token) != str(token):
            raise LeaseConflict(section, holder=_holder(sess, lease),
                                reason="token_invalid")
        lease.renewed_at = _now()
        lease.expires_at = _now() + timedelta(seconds=LEASE_TTL_SECONDS)
        if tab_id:
            lease.tab_id = _tab_id(tab_id)
        result = _lease_payload(sess, lease)
        result.update(token=lease.token, expires_in=LEASE_TTL_SECONDS,
                      ttl=LEASE_TTL_SECONDS)
        sess.commit()
        return result


def release_lease(plan_id: int, section: str, token: str,
                  user: Dict[str, Any]) -> Dict[str, Any]:
    section = _require_section(section)
    with Session(pstore._engine()) as sess:
        _writer(sess)
        row = _lock_plan(sess, plan_id)
        if row is None:
            raise pstore.NotFound("发展计划不存在")
        plan = pstore._plan_row(sess, row)
        if not _can_view_plan_in_session(sess, plan, user):
            raise PermissionDenied("无权访问该计划")
        lease = sess.execute(select(PlanEditLease).where(
            PlanEditLease.plan_id == int(plan_id),
            PlanEditLease.section_key == section,
            PlanEditLease.token == str(token))).scalars().first()
        if lease is None:
            raise LeaseConflict(section, reason="token_invalid")
        if int(lease.user_id) != int(user.get("user_id")):
            raise PermissionDenied("只能释放自己的编辑权")
        if lease.released_at is None:
            lease.released_at = _now()
            lease.release_reason = "released"
        result = {"section": section, "released": True,
                  "released_at": pstore._iso(lease.released_at)}
        sess.commit()
        return result


def takeover_lease(plan_id: int, section: str, user: Dict[str, Any],
                   tab_id: str, reason: str = "") -> Dict[str, Any]:
    section = _require_section(section)
    tab_id = _tab_id(tab_id)
    if not can_manage_team(user):
        raise PermissionDenied("只有管理员可以接管编辑权")
    with Session(pstore._engine()) as sess:
        _writer(sess)
        row = _lock_plan(sess, plan_id)
        if row is None:
            raise pstore.NotFound("发展计划不存在")
        plan = pstore._plan_row(sess, row)
        if not can_edit_in_session(sess, plan, user):
            raise PermissionDenied("无权编辑该计划")
        _expire_leases(sess, plan_id)
        previous = _active_lease(sess, plan_id, section)
        previous_payload = _holder(sess, previous) if previous else None
        if previous is not None:
            previous.released_at = _now()
            previous.release_reason = "takeover"
        lease = PlanEditLease(
            plan_id=int(plan_id), section_key=section,
            user_id=int(user.get("user_id")), tab_id=tab_id,
            token=uuid.uuid4().hex, acquired_at=_now(), renewed_at=_now(),
            expires_at=_now() + timedelta(seconds=LEASE_TTL_SECONDS))
        sess.add(lease)
        _audit_in_session(sess, user.get("user_id"), plan.get("student_id"),
                          "m1.plan_lease_takeover",
                          {"plan_id": int(plan_id), "section": section,
                           "previous": previous_payload,
                           "reason": str(reason or "")[:300]})
        sess.flush()
        result = _lease_payload(sess, lease)
        result.update(previous=previous_payload, token=lease.token,
                      expires_in=LEASE_TTL_SECONDS, ttl=LEASE_TTL_SECONDS,
                      document_version=_document_version(sess, plan_id),
                      version=_section_versions(sess, plan_id).get(section, 0))
        sess.commit()
        return result


def _tab_id(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("缺少 tab_id")
    value = value.strip()
    if len(value) > TAB_ID_MAX or not re.fullmatch(r"[A-Za-z0-9._:-]+", value):
        raise ValueError("tab_id 格式不正确")
    return value


def _cleanup_presence(sess: Session, plan_id: int) -> None:
    cutoff = _now() - timedelta(hours=PRESENCE_RETENTION_HOURS)
    sess.execute(delete(PlanPresence).where(
        PlanPresence.plan_id == int(plan_id),
        PlanPresence.last_seen_at < cutoff))
    keep = select(PlanPresence.id).where(
        PlanPresence.plan_id == int(plan_id)).order_by(
            PlanPresence.id.desc()).limit(PRESENCE_MAX_ROWS_PER_PLAN).subquery()
    sess.execute(delete(PlanPresence).where(
        PlanPresence.plan_id == int(plan_id),
        ~PlanPresence.id.in_(select(keep.c.id))))


def heartbeat(plan_id: int, user: Dict[str, Any], tab_id: str,
              state: str = "viewing", editing_section: str = "") -> Dict[str, Any]:
    tab_id = _tab_id(tab_id)
    state = state if state in PRESENCE_STATES else "viewing"
    editing_section = editing_section or ""
    if editing_section and not valid_section_key(editing_section):
        raise InvalidSection("未知的编辑部分")
    with Session(pstore._engine()) as sess:
        _writer(sess)
        row = _lock_plan(sess, plan_id)
        if row is None:
            raise pstore.NotFound("发展计划不存在")
        plan = pstore._plan_row(sess, row)
        if not _can_view_plan_in_session(sess, plan, user):
            raise PermissionDenied("无权访问该计划")
        now = _now()
        presence = sess.execute(select(PlanPresence).where(
            PlanPresence.plan_id == int(plan_id),
            PlanPresence.user_id == int(user.get("user_id")),
            PlanPresence.tab_id == tab_id)).scalars().first()
        if presence is None:
            presence = PlanPresence(
                plan_id=int(plan_id), user_id=int(user.get("user_id")),
                tab_id=tab_id, state=state, editing_section=editing_section,
                last_seen_at=now)
            sess.add(presence)
        elif presence.last_seen_at is None or \
                (now - presence.last_seen_at).total_seconds() >= PRESENCE_MIN_INTERVAL_SECONDS:
            presence.state = state
            presence.editing_section = editing_section
            presence.last_seen_at = now
        _cleanup_presence(sess, plan_id)
        result = _snapshot_in_session(sess, plan, user, include_team=True)
        sess.commit()
        return result


def _snapshot_in_session(sess: Session, plan: Dict[str, Any], user: Dict[str, Any],
                         *, include_team: bool = True) -> Dict[str, Any]:
    now = _now()
    cutoff = now - timedelta(seconds=PRESENCE_TTL_SECONDS)
    rows = sess.execute(select(PlanPresence).where(
        PlanPresence.plan_id == int(plan["id"]),
        PlanPresence.last_seen_at >= cutoff)
        .order_by(PlanPresence.user_id, PlanPresence.last_seen_at.desc())).scalars().all()
    grouped: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        user_row = sess.get(_db.User, int(row.user_id))
        if user_row is None or not int(user_row.is_active or 0):
            continue
        found = grouped.get(int(row.user_id))
        item = {"user_id": int(row.user_id),
                "name": _user_name(sess, row.user_id),
                "role": _presence_role(sess, plan, user_row),
                "state": row.state or "viewing",
                "editing_section": row.editing_section or "",
                "last_seen": pstore._iso(row.last_seen_at),
                "tabs": 1}
        if found is None:
            grouped[int(row.user_id)] = item
        else:
            found["tabs"] += 1
            if item["editing_section"] and not found["editing_section"]:
                found["editing_section"] = item["editing_section"]
            if item["state"] in ("editing", "saving", "conflict"):
                found["state"] = item["state"]
            if (row.last_seen_at or now) > (found.get("_seen") or now):
                found["last_seen"] = item["last_seen"]
            found["_seen"] = row.last_seen_at
    for item in grouped.values():
        item.pop("_seen", None)
    leases = []
    for lease in sess.execute(select(PlanEditLease).where(
            PlanEditLease.plan_id == int(plan["id"]),
            PlanEditLease.released_at.is_(None),
            PlanEditLease.expires_at > now)).scalars().all():
        leases.append({"section": lease.section_key, "user_id": lease.user_id,
                       "name": _user_name(sess, lease.user_id),
                       "tab_id": lease.tab_id, "expires_at": pstore._iso(lease.expires_at)})
    sections = _section_versions(sess, plan["id"])
    data = {
        "document_version": _document_version(sess, plan["id"]),
        "sections": sections,
        "participants": sorted(grouped.values(), key=lambda item: item["user_id"]),
        "leases": sorted(leases, key=lambda item: item["section"]),
        "server_time": pstore._iso(now),
        "presence_ttl": PRESENCE_TTL_SECONDS,
        "lease_ttl": LEASE_TTL_SECONDS,
        "poll_seconds": POLL_SECONDS,
        "permissions": _permissions_in_session(sess, plan, user),
    }
    if include_team:
        data["team"] = _team_view_in_session(sess, plan["student_id"])
    return data


def _presence_role(sess, plan, user_row) -> str:
    if user_row.role == "admin" or int(user_row.m1_admin or 0):
        return "admin"
    if plan.get("mentor_user_id") is not None \
            and int(plan["mentor_user_id"]) == int(user_row.id):
        return "primary"
    if _team_row(sess, plan.get("student_id"), user_row.id) is not None:
        return "co_mentor"
    return "viewer"


def _permissions_in_session(sess, plan, user) -> Dict[str, Any]:
    return {"can_view": _can_view_plan_in_session(sess, plan, user),
            "can_edit": can_edit_in_session(sess, plan, user),
            "can_approve": can_approve_in_session(sess, plan, user),
            "can_manage_team": user.get("role") == "admin" or
                               _effective(user).get("m1_admin") == 1,
            "role": plan_role(user, plan)}


def snapshot(plan: Dict[str, Any], user) -> Dict[str, Any]:
    u = store._user_dict(user)
    with Session(pstore._engine()) as sess:
        if not _can_view_plan_in_session(sess, plan, u):
            raise PermissionDenied("无权访问该计划")
        _expire_leases(sess, plan["id"])
        data = _snapshot_in_session(sess, plan, u, include_team=True)
        sess.commit()
        return data


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------
def _team_view_in_session(sess: Session, student_id: int) -> Dict[str, Any]:
    plans = sess.execute(select(pstore.M1Plan).where(
        pstore.M1Plan.student_id == int(student_id))).scalars().all()
    primaries = {}
    for plan in plans:
        if plan.mentor_user_id is None:
            continue
        uid = int(plan.mentor_user_id)
        found = primaries.setdefault(uid, {"user_id": uid,
                                           "name": _user_name(sess, uid),
                                           "plan_ids": [],
                                           "block_numbers": []})
        found["plan_ids"].append(plan.id)
        found["block_numbers"].append(int(plan.block_no or 1))
    rows = sess.execute(select(PlanTeamMember).where(
        PlanTeamMember.student_id == int(student_id))
        .order_by(PlanTeamMember.id)).scalars().all()
    members = [{"user_id": row.user_id, "name": _user_name(sess, row.user_id),
                "role": "co_mentor", "added_by": row.added_by,
                "created_at": pstore._iso(row.created_at),
                "is_active": bool((sess.get(_db.User, int(row.user_id)) or
                                   type("X", (), {"is_active": 0})).is_active)}
               for row in rows]
    return {"student_id": int(student_id),
            "primaries": sorted(primaries.values(), key=lambda item: item["user_id"]),
            "co_mentors": members}


def team_view(student_id: int) -> Dict[str, Any]:
    with Session(pstore._engine()) as sess:
        return _team_view_in_session(sess, student_id)


def team_views(student_ids) -> Dict[int, Dict[str, Any]]:
    """Batch team lookup for the plan list; one session, no per-row round trips."""
    result: Dict[int, Dict[str, Any]] = {}
    with Session(pstore._engine()) as sess:
        for student_id in student_ids:
            result[int(student_id)] = _team_view_in_session(sess, int(student_id))
    return result


def add_team_member(student_id: int, member_id: int, actor: Dict[str, Any]) -> Dict[str, Any]:
    if not can_manage_team(actor):
        raise PermissionDenied("只有管理员可以管理团队")
    with Session(pstore._engine()) as sess:
        _writer(sess)
        student = sess.get(_db.Student, int(student_id))
        if student is None:
            raise pstore.NotFound("学生不存在")
        member = _active_user(sess, member_id)
        if member is None:
            raise UnknownUser("只能添加启用的账号")
        settings = _db.effective_account_settings(
            member.role, member.student_scope, member.detail_level,
            member.m1_access, member.m1_admin)
        if member.role not in ("admin", "advisor") or settings.get("m1_access") != 1:
            raise UnknownUser("只能添加有心理发展计划权限的导师")
        primary = sess.execute(select(pstore.M1Plan.id).where(
            pstore.M1Plan.student_id == int(student_id),
            pstore.M1Plan.mentor_user_id == int(member_id)).limit(1)).scalars().first()
        if primary is not None:
            raise ValueError("该导师已是这份计划的负责导师")
        existing = _team_row(sess, student_id, member_id)
        if existing is not None:
            result = _team_view_in_session(sess, student_id)
            result["created"] = False
            sess.commit()
            return result
        sess.add(PlanTeamMember(student_id=int(student_id), user_id=int(member_id),
                                role="co_mentor", added_by=actor.get("user_id"),
                                created_at=_now()))
        _audit_in_session(sess, actor.get("user_id"), student_id,
                          "m1.plan_team_add",
                          {"student_id": int(student_id),
                           "user_id": int(member_id),
                           "role": "co_mentor"})
        sess.flush()
        result = _team_view_in_session(sess, student_id)
        result["created"] = True
        sess.commit()
        return result


def remove_team_member(student_id: int, member_id: int,
                       actor: Dict[str, Any]) -> Dict[str, Any]:
    if not can_manage_team(actor):
        raise PermissionDenied("只有管理员可以管理团队")
    with Session(pstore._engine()) as sess:
        _writer(sess)
        row = _team_row(sess, student_id, member_id)
        if row is None:
            result = _team_view_in_session(sess, student_id)
            result["removed"] = False
            sess.commit()
            return result
        plan_ids = [int(item) for item in sess.execute(select(pstore.M1Plan.id).where(
            pstore.M1Plan.student_id == int(student_id))).scalars().all()]
        now = _now()
        released = 0
        if plan_ids:
            leases = sess.execute(select(PlanEditLease).where(
                PlanEditLease.plan_id.in_(plan_ids),
                PlanEditLease.user_id == int(member_id),
                PlanEditLease.released_at.is_(None))).scalars().all()
            for lease in leases:
                lease.released_at = now
                lease.release_reason = "revoked"
                released += 1
            sess.execute(delete(PlanPresence).where(
                PlanPresence.plan_id.in_(plan_ids),
                PlanPresence.user_id == int(member_id)))
        sess.delete(row)
        _audit_in_session(sess, actor.get("user_id"), student_id,
                          "m1.plan_team_remove",
                          {"student_id": int(student_id),
                           "user_id": int(member_id),
                           "released_leases": released,
                           "plan_ids": plan_ids})
        sess.flush()
        result = _team_view_in_session(sess, student_id)
        result.update(removed=True, released_leases=released)
        sess.commit()
        return result


# ---------------------------------------------------------------------------
# Patch payload validation
# ---------------------------------------------------------------------------
def _validate_patch(section: str, patch) -> Dict[str, Any]:
    list_sections = {section for section in (
        "internal.session.%d.activities" % n for n in (1, 2, 3))} | {
        "internal.session.%d.practice" % n for n in (1, 2, 3)
    } | {"parent.practice_options", "parent.practice", "parent.family",
         "parent.family_seen", "parent.review"}
    if isinstance(patch, list):
        if section not in list_sections:
            raise ValueError("这一部分需要对象格式的 patch")
    elif not isinstance(patch, dict):
        raise ValueError("patch 必须是对象")
    if section in ("header", "durations", "brief", "inputs", "personal", "goals"):
        allowed = {"header": {"block_no", "period_start", "period_end", "credits"},
                   "durations": {"session_durations"},
                   "brief": {"teaching_brief"},
                   "inputs": {"strengths", "needs", "context", "interests"},
                   "personal": {"notes", "summary"},
                   "goals": {"goals"}}[section]
        unknown = set(patch) - allowed
        if unknown:
            raise ValueError("不支持的字段：%s" % "、".join(sorted(unknown)))
        if not patch:
            raise ValueError("没有要更新的字段")
        return patch
    if section == "internal.overview":
        return {"overview": _field(patch)}
    if section == "internal.mentor_notes":
        return {"mentor_notes": _field(patch)}
    if section in ("parent.intro", "parent.transition"):
        key = section.split(".", 1)[1]
        return {key: _field(patch)}
    match = SESSION_RE.match(section)
    if match:
        unknown = set(patch) - SESSION_FIELDS
        if unknown:
            raise ValueError("不支持的字段：%s" % "、".join(sorted(unknown)))
        if not patch:
            raise ValueError("没有要更新的字段")
        return patch
    match = PARENT_SESSION_RE.match(section)
    if match:
        unknown = set(patch) - PARENT_SESSION_FIELDS
        if unknown:
            raise ValueError("不支持的字段：%s" % "、".join(sorted(unknown)))
        if not patch:
            raise ValueError("没有要更新的字段")
        return patch
    if ACTIVITIES_RE.match(section):
        if not isinstance(patch, list):
            raise ValueError("活动列表必须是数组")
        return {"activities": patch}
    if PRACTICE_LIST_RE.match(section):
        if not isinstance(patch, list):
            raise ValueError("实践列表必须是数组")
        return {"practice": patch}
    match = ACTIVITY_RE.match(section)
    if match:
        allowed = ACTIVITY_FIELDS | set(pstore.plan_kb.RICH_ACTIVITY_FIELDS)
        unknown = set(patch) - allowed
        if unknown:
            raise ValueError("不支持的字段：%s" % "、".join(sorted(unknown)))
        if not patch:
            raise ValueError("没有要更新的字段")
        return patch
    match = PRACTICE_RE.match(section)
    if match:
        unknown = set(patch) - PRACTICE_FIELDS
        if unknown:
            raise ValueError("不支持的字段：%s" % "、".join(sorted(unknown)))
        if not patch:
            raise ValueError("没有要更新的字段")
        return patch
    match = PARENT_GOAL_RE.match(section)
    if match:
        unknown = set(patch) - {"text"}
        if unknown:
            raise ValueError("不支持的字段：%s" % "、".join(sorted(unknown)))
        return {"text": _field(patch.get("text"))}
    if section == "parent.practice_options":
        if not isinstance(patch, list):
            raise ValueError("实践列表必须是数组")
        return {"practice_options": patch}
    if section == "parent.practice":
        if not isinstance(patch, list):
            raise ValueError("选中的实践必须是数组")
        return {"practice": patch}
    if section == "parent.family":
        if not isinstance(patch, list) or len(patch) != 2:
            raise ValueError("家庭协作需要 2 条建议")
        return {"family": [_field(item) for item in patch]}
    if section == "parent.family_seen":
        if not isinstance(patch, dict) or set(patch) != {"seen", "hashes"}:
            raise ValueError("family_seen 需要 seen 与 hashes，防止旧确认覆盖新建议")
        seen = patch.get("seen")
        hashes = patch.get("hashes")
        if not isinstance(seen, list) or len(seen) != 2 or any(
                not isinstance(item, bool) for item in seen):
            raise ValueError("家庭建议的已看过标记格式不正确")
        if not isinstance(hashes, list) or len(hashes) != 2 or any(
                not isinstance(item, str) for item in hashes):
            raise ValueError("family hashes 格式不正确")
        return {"family_seen": seen, "family_hashes": hashes}
    if section == "parent.review":
        if not isinstance(patch, list):
            raise ValueError("成长观察必须是数组")
        clean = []
        for item in patch:
            if not isinstance(item, dict) or set(item) - {"label", "text"}:
                raise ValueError("成长观察格式不正确")
            clean.append({"label": _field(item.get("label")),
                          "text": _field(item.get("text"))})
        return {"review": clean}
    raise InvalidSection("未知的编辑部分")


def _apply_doc_patch(doc: Dict[str, Any], section: str, patch: Dict[str, Any]) -> None:
    if section == "internal.overview":
        doc["overview"] = patch["overview"]
        return
    if section == "internal.mentor_notes":
        doc["mentor_notes"] = patch["mentor_notes"]
        return
    if section in ("parent.intro", "parent.transition"):
        doc[section.split(".", 1)[1]] = patch[section.split(".", 1)[1]]
        return
    match = SESSION_RE.match(section)
    if match:
        n = int(match.group(1))
        sessions = doc.get("sessions") or []
        if n > len(sessions) or not isinstance(sessions[n - 1], dict):
            raise ItemNotFound("这一节课不存在")
        session = sessions[n - 1]
        if "title" in patch:
            session["title"] = _merge_field(session.get("title"), patch["title"])
        if "evidence" in patch:
            session["evidence"] = _merge_field(session.get("evidence"), patch["evidence"])
        if "next_prep" in patch:
            if patch["next_prep"] is None:
                if n != len(sessions):
                    raise ValueError("只有最后一节课可以留空下次课准备")
                session["next_prep"] = None
            else:
                if n == len(sessions):
                    raise ValueError("最后一节课没有下次课准备")
                session["next_prep"] = _merge_field(session.get("next_prep"),
                                                    patch["next_prep"])
        if "review" in patch:
            if not isinstance(patch["review"], list):
                raise ValueError("上次实践回顾必须是数组")
            session["review"] = [_field(item) for item in patch["review"]]
        if "focus" in patch:
            focus = patch["focus"]
            if not isinstance(focus, dict) or set(focus) - {"primary", "supporting", "text"}:
                raise ValueError("教学重点格式不正确")
            current = session.get("focus") if isinstance(session.get("focus"), dict) else {}
            updated = dict(current)
            for key in ("primary", "supporting"):
                if key in focus:
                    updated[key] = focus[key]
            if "text" in focus:
                updated["text"] = _merge_field(current.get("text"), focus["text"])
            session["focus"] = updated
        if "content" in patch:
            content = patch["content"]
            if not isinstance(content, dict) or set(content) - {"mindsets", "skills", "techniques"}:
                raise ValueError("核心学习内容格式不正确")
            current = session.get("content") if isinstance(session.get("content"), dict) else {}
            updated = dict(current)
            for key in ("mindsets", "skills", "techniques"):
                if key in content:
                    updated[key] = _merge_field(current.get(key), content[key])
            session["content"] = updated
        return
    match = PARENT_SESSION_RE.match(section)
    if match:
        n = int(match.group(1))
        sessions = doc.get("sessions") or []
        if n > len(sessions) or not isinstance(sessions[n - 1], dict):
            raise ItemNotFound("这一节课不存在")
        session = sessions[n - 1]
        for key in ("title", "summary"):
            if key in patch:
                session[key] = _merge_field(session.get(key), patch[key])
        return
    match = ACTIVITIES_RE.match(section)
    if match:
        n = int(match.group(1))
        sessions = doc.get("sessions") or []
        if n > len(sessions):
            raise ItemNotFound("这一节课不存在")
        sessions[n - 1]["activities"] = copy.deepcopy(patch["activities"])
        return
    match = PRACTICE_LIST_RE.match(section)
    if match:
        n = int(match.group(1))
        sessions = doc.get("sessions") or []
        if n > len(sessions):
            raise ItemNotFound("这一节课不存在")
        sessions[n - 1]["practice"] = copy.deepcopy(patch["practice"])
        return
    match = ACTIVITY_RE.match(section)
    if match:
        n, activity_id = int(match.group(1)), match.group(2)
        sessions = doc.get("sessions") or []
        if n > len(sessions):
            raise ItemNotFound("这一节课不存在")
        found = [item for item in sessions[n - 1].get("activities") or []
                 if isinstance(item, dict) and item.get("id") == activity_id]
        if len(found) != 1:
            raise ItemNotFound("这个教学活动不存在")
        activity = found[0]
        for key, value in patch.items():
            if key == "minutes":
                if type(value) is not int or value < 0:
                    raise ValueError("活动时长必须是非负整数分钟")
                activity[key] = value
            elif key == "source":
                if not isinstance(value, dict):
                    raise ValueError("参考来源格式不正确")
                activity[key] = copy.deepcopy(value)
            elif key in pstore.plan_kb.RICH_ACTIVITY_FIELDS:
                if isinstance(value, str):
                    activity[key] = value
                else:
                    activity[key] = _field(value)
            else:
                activity[key] = _merge_field(activity.get(key), value)
        return
    match = PRACTICE_RE.match(section)
    if match:
        n, practice_id = int(match.group(1)), match.group(2)
        sessions = doc.get("sessions") or []
        if n > len(sessions):
            raise ItemNotFound("这一节课不存在")
        found = [item for item in sessions[n - 1].get("practice") or []
                 if isinstance(item, dict) and item.get("id") == practice_id]
        if len(found) != 1:
            raise ItemNotFound("这项课后实践不存在")
        item = found[0]
        for key, value in patch.items():
            if key == "code":
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("实践关联目标无效")
                item[key] = value.strip()
            elif key == "platform":
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("实践平台无效")
                item[key] = value.strip()
            else:
                item[key] = _merge_field(item.get(key), value)
        return
    match = PARENT_GOAL_RE.match(section)
    if match:
        code = match.group(1)
        goals = doc.get("goals") or []
        found = next((item for item in goals
                      if isinstance(item, dict) and item.get("code") == code), None)
        if found is None:
            raise ItemNotFound("这个目标不存在")
        found["text"] = patch["text"]
        return
    if section == "parent.practice_options":
        doc["practice_options"] = copy.deepcopy(patch["practice_options"])
        return
    if section == "parent.practice":
        doc["practice"] = list(patch["practice"])
        return
    if section == "parent.family":
        previous = family_state(doc)
        doc["family"] = patch["family"]
        sync_family_ack(doc, previous=previous)
        return
    if section == "parent.family_seen":
        state = family_state(doc)
        current_hashes = [item["hash"] for item in state]
        expected_hashes = patch.get("family_hashes") or []
        if expected_hashes != current_hashes:
            raise StaleFamilyAck(expected_hashes, current_hashes,
                                 family=[item["text"] for item in state])
        seen = [bool(item) for item in patch["family_seen"]]
        doc["family_seen"] = seen
        doc["family_ack"] = [{"hash": current_hashes[index], "seen": seen[index]}
                             for index in range(2)]
        return
    if section == "parent.review":
        doc["review"] = patch["review"]
        return
    raise InvalidSection("未知的编辑部分")


def _validate_doc(plan: Dict[str, Any], part: str, doc: Dict[str, Any]) -> None:
    if part == "internal":
        pstore.validate_internal_doc(plan, doc)
        plan_quality.validate_additions(doc)
    else:
        pstore.validate_parent_doc(plan, doc)


def _internal_checks(plan: Dict[str, Any], doc: Dict[str, Any]):
    try:
        from m1 import plan_checks
    except ImportError:
        return []
    fn = getattr(plan_checks, "run_checks", None)
    return fn(plan, doc) if fn else []


def _bump_dependency_versions(sess: Session, plan_id: int, section: str,
                              actor_id, before_doc, after_doc) -> None:
    """Bump the versions of storage that shares a payload with ``section``.

    A list replacement and an item edit write the same document bytes. The
    parent list version therefore changes on every child edit, and every item
    version changes on a list replacement. This makes a stale list/item payload
    fail even after its lease was released and reacquired.
    """
    parent = list_parent_section(section)
    if parent:
        bump_section_in_session(sess, plan_id, parent, actor_id)
    prefix = _list_child_prefix(section)
    if prefix:
        ids = _list_item_ids(before_doc, section) | _list_item_ids(after_doc, section)
        for item_id in sorted(ids):
            key = prefix + item_id
            if valid_section_key(key):
                bump_section_in_session(sess, plan_id, key, actor_id)
    if section == "parent.family":
        old_hashes = [family_hash(item) for item in (before_doc or {}).get("family") or []]
        new_hashes = [family_hash(item) for item in (after_doc or {}).get("family") or []]
        if old_hashes != new_hashes:
            bump_section_in_session(sess, plan_id, "parent.family_seen", actor_id)


def _bump_document_dependencies(sess: Session, plan_id: int, part: str,
                                actor_id, before_doc, after_doc) -> None:
    if part == "internal":
        for n in (1, 2, 3):
            for list_section in ("internal.session.%d.activities" % n,
                                 "internal.session.%d.practice" % n):
                bump_section_in_session(sess, plan_id, list_section, actor_id)
                _bump_dependency_versions(sess, plan_id, list_section,
                                          actor_id, before_doc, after_doc)
    else:
        old_hashes = [family_hash(item) for item in (before_doc or {}).get("family") or []]
        new_hashes = [family_hash(item) for item in (after_doc or {}).get("family") or []]
        if old_hashes != new_hashes:
            bump_section_in_session(sess, plan_id, "parent.family", actor_id)
            bump_section_in_session(sess, plan_id, "parent.family_seen", actor_id)


# ---------------------------------------------------------------------------
# Plan-column patches
# ---------------------------------------------------------------------------
def _apply_plan_patch(sess: Session, plan: Dict[str, Any], section: str,
                      patch: Dict[str, Any], user: Dict[str, Any]) -> Tuple[Dict[str, Any], Any]:
    changes: Dict[str, Any] = {}
    if section == "header":
        row = sess.get(pstore.M1Plan, int(plan["id"]))
        block_no = patch.get("block_no", row.block_no)
        start = patch.get("period_start", row.period_start)
        end = patch.get("period_end", row.period_end)
        if isinstance(block_no, bool) or not isinstance(block_no, int) or block_no < 1:
            raise ValueError("Block 编号需为 1 或以上")
        pstore._check_dates(start, end)
        if int(block_no) != int(row.block_no or 1):
            taken = sess.execute(select(pstore.M1Plan.id).where(
                pstore.M1Plan.student_id == row.student_id,
                pstore.M1Plan.block_no == int(block_no),
                pstore.M1Plan.id != row.id)).scalars().first()
            if taken is not None:
                raise ValueError("该 Block 已有发展计划")
        changes.update(block_no=int(block_no), period_start=start, period_end=end)
        if "credits" in patch:
            changes["credits"] = str(patch.get("credits") or "").strip()[:20]
        return changes, {key: changes.get(key, plan.get(key)) for key in
                         ("block_no", "period_start", "period_end", "credits")}
    if section == "durations":
        durations = patch.get("session_durations")
        if not isinstance(durations, list) or len(durations) != 3 or any(
                type(n) is not int or not 15 <= n <= 180 for n in durations):
            raise ValueError("session_durations 需要三个 15–180 分钟的整数")
        return {"session_durations": pstore._dumps(durations)}, durations
    if section == "brief":
        from m1.plan_context import validate_brief
        clean = validate_brief(patch.get("teaching_brief"))
        file_ids = {str(item) for item in sess.execute(
            select(pstore.M1PlanFile.id).where(
                pstore.M1PlanFile.plan_id == int(plan["id"]))).scalars().all()}
        for item in clean.values():
            if item["provenance"] == "file" and item["source_ref"] not in file_ids:
                raise ValueError("文件来源不属于该计划")
            if item["provenance"] == "report" and (
                    plan["source_mode"] != "report"
                    or item["source_ref"] != str(plan["report_version_id"])):
                raise ValueError("报告来源不属于该计划")
        changes.update(teaching_brief=pstore._dumps(clean),
                       brief_revision=int(plan.get("brief_revision") or 0) + 1,
                       brief_confirmed_revision=None, brief_confirmed_by=None)
        return changes, clean
    if section == "inputs":
        values = patch
        inputs = dict(plan.get("inputs") or {})
        for key in ("strengths", "needs", "context", "interests"):
            if key not in values:
                continue
            incoming = pstore._field(values.get(key), "edited")
            old = inputs.get(key)
            old_text = old.get("text") if isinstance(old, dict) else ""
            if incoming["text"] == (old_text or ""):
                inputs[key] = old if isinstance(old, dict) else pstore._field(old_text)
            else:
                inputs[key] = {"text": incoming["text"], "src": "edited"}
        return {"inputs": pstore._dumps(inputs)}, inputs
    if section == "personal":
        personal = dict(plan.get("personal") or {})
        if "notes" in patch:
            if not isinstance(patch["notes"], str):
                raise ValueError("notes 必须是文字")
            personal["notes"] = patch["notes"]
        personal.setdefault("notes", "")
        if "summary" in patch:
            item = pstore._field(patch["summary"], "edited")
            current = (personal.get("summary") or {}).get("text") or ""
            if item["text"] != current:
                personal["summary"] = item
        personal.setdefault("summary", pstore._field(""))
        return {"personal": pstore._dumps(personal)}, personal
    if section == "goals":
        cleaned = pstore.validate_goals(patch.get("goals"))
        return {"goals": pstore._dumps(cleaned)}, cleaned
    raise InvalidSection("未知的编辑部分")


# ---------------------------------------------------------------------------
# Patch application
# ---------------------------------------------------------------------------
def _request_hash(section: str, patch: Dict[str, Any], expected_version,
                  document_version) -> str:
    payload = json.dumps({"section": section, "patch": patch,
                          "expected_version": expected_version,
                          "document_version": document_version},
                         sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cleanup_patch_logs(sess: Session, plan_id: int) -> None:
    cutoff = _now() - timedelta(days=PATCH_IDEMPOTENCY_DAYS)
    sess.execute(delete(PlanPatchLog).where(
        PlanPatchLog.plan_id == int(plan_id),
        PlanPatchLog.created_at < cutoff))
    keep = select(PlanPatchLog.id).where(
        PlanPatchLog.plan_id == int(plan_id)).order_by(
            PlanPatchLog.id.desc()).limit(PATCH_LOG_LIMIT).subquery()
    sess.execute(delete(PlanPatchLog).where(
        PlanPatchLog.plan_id == int(plan_id),
        ~PlanPatchLog.id.in_(select(keep.c.id))))


def apply_section(plan_id: int, section: str, patch, user: Dict[str, Any], *,
                  expected_version=None, document_version_value=None,
                  lease_token=None, idempotency_key=None,
                  require_lease: bool = True,
                  expected_rev=None) -> Dict[str, Any]:
    section = _require_section(section)
    if section in DOCUMENT_SECTIONS:
        raise InvalidSection("请使用整份文档保存接口")
    patch = _validate_patch(section, patch)
    if expected_version is not None and (isinstance(expected_version, bool)
                                         or not isinstance(expected_version, int)
                                         or expected_version < 0):
        raise ValueError("expected_version 必须是非负整数")
    if idempotency_key is not None:
        if not isinstance(idempotency_key, str) or not IDEMPOTENCY_RE.match(idempotency_key):
            raise ValueError("idempotency_key 格式不正确")
    request_hash = _request_hash(section, patch, expected_version,
                                 document_version_value)
    with Session(pstore._engine()) as sess:
        _writer(sess)
        row = _lock_plan(sess, plan_id)
        if row is None:
            raise pstore.NotFound("发展计划不存在")
        plan = pstore._plan_row(sess, row)
        if not _can_view_plan_in_session(sess, plan, user):
            raise PermissionDenied("无权访问该计划")
        if not can_edit_in_session(sess, plan, user):
            raise PermissionDenied("只有负责导师可以编辑该计划")
        if expected_rev is not None:
            pstore._check_rev(row, expected_rev)
        if idempotency_key:
            existing = sess.execute(select(PlanPatchLog).where(
                PlanPatchLog.plan_id == int(plan_id),
                PlanPatchLog.idempotency_key == idempotency_key)).scalars().first()
            if existing is not None:
                if existing.request_hash != request_hash \
                        or int(existing.user_id) != int(user.get("user_id") or 0):
                    raise IdempotencyConflict(idempotency_key)
                result = pstore._loads(existing.result, {}) or {}
                result["replayed"] = True
                sess.commit()
                return result
        _expire_leases(sess, plan_id)
        _require_lease(sess, plan_id, section, user.get("user_id"), lease_token,
                       required=require_lease)
        _require_no_related_lease(sess, plan_id, section,
                                  exclude_token=lease_token or "")
        if document_version_value is not None:
            current_document = _document_version(sess, plan_id)
            if int(document_version_value) != current_document:
                raise StaleDocument(document_version_value, current_document)
        current_version = _section_version(sess, plan_id, section)
        if expected_version is not None and int(expected_version) != current_version:
            raise StaleSection(section, expected_version, current_version,
                               _section_value(sess, plan, section))
        part = _doc_part(section)
        checks = None
        version_id = None
        old_rev = int(row.rev or 1)
        before_doc = None
        if part:
            version = _current_version(sess, plan, part)
            if version is None:
                raise pstore.StatusError("内部版还没有生成" if part == "internal"
                                         else "家长版还没有生成")
            before_doc = pstore.normalize_doc_shape(
                pstore._loads(version.doc, {}) or {})
            doc = copy.deepcopy(before_doc)
            _apply_doc_patch(doc, section, patch)
            _validate_doc(plan, part, doc)
            checks = _internal_checks(plan, doc) if part == "internal" else None
            prepared = pstore._prepare_part(sess, row, part, doc, checks,
                                            user.get("user_id"))
            version_id = prepared["version_id"]
            values = {"rev": old_rev + 1, "updated_at": _now()}
            if part == "internal":
                values["current_version_id"] = version_id
            else:
                values["parent_version_id"] = version_id
                if row.parent_status in ("confirmed", "exported"):
                    values["parent_status"] = "draft"
            sess.execute(update(pstore.M1Plan).where(
                pstore.M1Plan.id == int(plan_id)).values(**values),
                execution_options={"synchronize_session": False})
            section_value = _extract_section(doc, section)
        else:
            if plan.get("status") in ("approved", "generating"):
                raise pstore.StatusError("内部版已批准或正在生成，请先重新打开")
            changes, section_value = _apply_plan_patch(sess, plan, section, patch, user)
            values = dict(changes)
            values.update(rev=old_rev + 1, updated_at=_now())
            sess.execute(update(pstore.M1Plan).where(
                pstore.M1Plan.id == int(plan_id)).values(**values),
                execution_options={"synchronize_session": False})
        new_version = _bump_section_row(sess, plan_id, section, current_version,
                                        user.get("user_id"))
        if part:
            _bump_dependency_versions(sess, plan_id, section,
                                      user.get("user_id"), before_doc, doc)
        result = {
            "rev": old_rev + 1,
            "section": section,
            "section_version": new_version,
            "document_version": _document_version(sess, plan_id),
            "version_id": version_id,
            "checks": checks,
            "section_value": section_value,
            "replayed": False,
        }
        if idempotency_key:
            sess.add(PlanPatchLog(
                plan_id=int(plan_id), user_id=int(user.get("user_id")),
                section_key=section, idempotency_key=idempotency_key,
                request_hash=request_hash, expected_version=expected_version,
                document_version=document_version_value,
                result=json.dumps(result, ensure_ascii=False, default=str),
                created_at=_now()))
            _cleanup_patch_logs(sess, plan_id)
        _audit_in_session(sess, user.get("user_id"), plan.get("student_id"),
                          "m1.plan_section_patch",
                          {"plan_id": int(plan_id), "section": section,
                           "section_version": new_version,
                           "version_id": version_id,
                           "idempotency_key": idempotency_key,
                           "bytes": len(json.dumps(patch, ensure_ascii=False))})
        sess.commit()
        return result


def _section_version(sess: Session, plan_id: int, section: str) -> int:
    row = sess.execute(select(PlanSectionVersion).where(
        PlanSectionVersion.plan_id == int(plan_id),
        PlanSectionVersion.section_key == section)).scalars().first()
    return int(row.version or 0) if row else 0


def _bump_section_row(sess: Session, plan_id: int, section: str,
                      expected: int, actor_id) -> int:
    row = sess.execute(select(PlanSectionVersion).where(
        PlanSectionVersion.plan_id == int(plan_id),
        PlanSectionVersion.section_key == section)).scalars().first()
    if row is None:
        if int(expected) != 0:
            raise StaleSection(section, expected, 0)
        row = PlanSectionVersion(plan_id=int(plan_id), section_key=section,
                                 version=1, updated_by=actor_id,
                                 updated_at=_now())
        sess.add(row)
        sess.flush()
        return 1
    if int(row.version or 0) != int(expected):
        raise StaleSection(section, expected, int(row.version or 0))
    row.version = int(row.version or 0) + 1
    row.updated_by = actor_id
    row.updated_at = _now()
    sess.flush()
    return int(row.version)


def _current_version(sess: Session, plan: Dict[str, Any], part: str):
    version_id = (plan.get("current_version_id") if part == "internal"
                  else plan.get("parent_version_id"))
    if not version_id:
        return None
    return sess.get(pstore.M1PlanVersion, int(version_id))


# ---------------------------------------------------------------------------
# Controlled whole-document save (legacy endpoint, not for the section editor)
# ---------------------------------------------------------------------------
def save_document(plan_id: int, part: str, rev: int, doc, checks,
                  user: Dict[str, Any]) -> Dict[str, Any]:
    if part not in pstore.PARTS:
        raise ValueError("未知版本类型")
    with Session(pstore._engine()) as sess:
        _writer(sess)
        row = _lock_plan(sess, plan_id)
        if row is None:
            raise pstore.NotFound("发展计划不存在")
        plan = pstore._plan_row(sess, row)
        if not can_edit_in_session(sess, plan, user):
            raise PermissionDenied("只有负责导师可以编辑该计划")
        pstore._check_rev(row, rev)
        _expire_leases(sess, plan_id)
        # Refuse while any collaborator holds a lease on this document: the
        # whole-document path must never clobber a live section editor.
        leases = sess.execute(select(PlanEditLease).where(
            PlanEditLease.plan_id == int(plan_id),
            PlanEditLease.released_at.is_(None),
            PlanEditLease.expires_at > _now())).scalars().all()
        if leases:
            holder = _holder(sess, leases[0])
            raise LeaseConflict(leases[0].section_key, holder=holder,
                                reason="document_locked")
        before_doc = None
        version_id = (row.current_version_id if part == "internal"
                      else row.parent_version_id)
        if version_id:
            current_version_row = sess.get(pstore.M1PlanVersion, int(version_id))
            if current_version_row is not None:
                before_doc = pstore.normalize_doc_shape(
                    pstore._loads(current_version_row.doc, {}) or {})
        if part == "parent":
            normalize_family_for_save(before_doc, doc)
        prepared = pstore._prepare_part(sess, row, part, doc, checks,
                                        user.get("user_id"))
        old_rev = int(row.rev or 1)
        values = {"rev": old_rev + 1, "updated_at": _now()}
        if part == "internal":
            values["current_version_id"] = prepared["version_id"]
        else:
            values["parent_version_id"] = prepared["version_id"]
            if row.parent_status in ("confirmed", "exported"):
                values["parent_status"] = "draft"
        sess.execute(update(pstore.M1Plan).where(
            pstore.M1Plan.id == int(plan_id)).values(**values),
            execution_options={"synchronize_session": False})
        # Force section clients to refetch: the whole document changed.
        for section in list(_section_versions(sess, plan_id)):
            if section.startswith(part + "."):
                _bump_section_row(sess, plan_id, section,
                                  _section_version(sess, plan_id, section),
                                  user.get("user_id"))
        _bump_document_dependencies(sess, plan_id, part, user.get("user_id"),
                                    before_doc, doc)
        bump_document_in_session(sess, plan_id, user.get("user_id"))
        _audit_in_session(sess, user.get("user_id"), plan.get("student_id"),
                          "m1.plan_document_save",
                          {"plan_id": int(plan_id), "part": part,
                           "version_id": prepared["version_id"]})
        result = {"rev": old_rev + 1,
                  "version_id": prepared["version_id"],
                  "document_version": _document_version(sess, plan_id),
                  "status": "approved" if row.status == "approved" else row.status,
                  "parent_status": ("draft" if part == "parent"
                                    and row.parent_status in ("confirmed", "exported")
                                    else row.parent_status),
                  "ai_doc": prepared["ai_doc"]}
        sess.commit()
        return result


# ---------------------------------------------------------------------------
# Lifecycle actions with leases and revisions checked atomically
# ---------------------------------------------------------------------------
def _active_leases(sess: Session, plan_id: int) -> List[PlanEditLease]:
    _expire_leases(sess, plan_id)
    return sess.execute(select(PlanEditLease).where(
        PlanEditLease.plan_id == int(plan_id),
        PlanEditLease.released_at.is_(None))).scalars().all()


def _revoke_all_leases(sess: Session, plan_id: int, reason: str) -> int:
    now = _now()
    count = 0
    for lease in _active_leases(sess, plan_id):
        lease.released_at = now
        lease.release_reason = reason
        count += 1
    return count


def _require_no_edits(sess: Session, plan_id: int) -> None:
    leases = _active_leases(sess, plan_id)
    if not leases:
        return
    raise LeaseConflict(leases[0].section_key,
                        holder=_holder(sess, leases[0]),
                        reason="active_edits")


def _parent_versions(sess: Session, row) -> Tuple[Optional[dict], Optional[dict]]:
    parent = (sess.get(pstore.M1PlanVersion, row.parent_version_id)
              if row.parent_version_id else None)
    internal = (sess.get(pstore.M1PlanVersion, row.current_version_id)
                if row.current_version_id else None)
    parent_doc = pstore.normalize_doc_shape(
        pstore._loads(parent.doc, {})) if parent else None
    internal_doc = pstore.normalize_doc_shape(
        pstore._loads(internal.doc, {})) if internal else None
    return parent_doc, internal_doc


def _parent_blocking(plan: Dict[str, Any], parent_doc, internal_doc):
    try:
        from m1 import plan_checks
    except ImportError:
        return []
    fn = getattr(plan_checks, "parent_blocking", None)
    if fn is None:
        return []
    return fn(_family_blocking_doc(parent_doc), plan, internal_doc)


def _require_parent_ready(sess: Session, plan: Dict[str, Any], row) -> None:
    parent_doc, internal_doc = _parent_versions(sess, row)
    blocking = _parent_blocking(plan, parent_doc, internal_doc)
    if blocking:
        raise ParentBlocking(blocking)


def approve_plan(plan_id: int, user: Dict[str, Any], rev: int,
                 version_id=None) -> Dict[str, Any]:
    with Session(pstore._engine()) as sess:
        _writer(sess)
        row = _lock_plan(sess, plan_id)
        if row is None:
            raise pstore.NotFound("发展计划不存在")
        plan = pstore._plan_row(sess, row)
        if not can_approve_in_session(sess, plan, user):
            raise PermissionDenied("只有负责导师或管理员可以批准内部版")
        pstore._check_rev(row, rev)
        if row.status != "review":
            raise pstore.StatusError("当前状态不能批准内部版")
        if version_id is not None and int(row.current_version_id or 0) != int(version_id):
            raise pstore.RevConflict(int(row.rev or 1))
        _require_no_edits(sess, plan_id)
        row.status = "approved"
        row.approved_by = int(user.get("user_id")) if user.get("user_id") else None
        row.approved_at = _now()
        row.rev = int(row.rev or 1) + 1
        row.updated_at = _now()
        document_version = bump_document_in_session(sess, plan_id, user.get("user_id"))
        _audit_in_session(sess, user.get("user_id"), plan.get("student_id"),
                          "m1.plan_approve",
                          {"plan_id": int(plan_id),
                           "version_id": int(row.current_version_id or 0),
                           "rev": int(row.rev)})
        sess.commit()
        return {"plan": pstore.get_plan(plan_id),
                "document_version": document_version,
                "rev": int(row.rev)}


def reopen_plan(plan_id: int, user: Dict[str, Any], rev: int) -> Dict[str, Any]:
    with Session(pstore._engine()) as sess:
        _writer(sess)
        row = _lock_plan(sess, plan_id)
        if row is None:
            raise pstore.NotFound("发展计划不存在")
        plan = pstore._plan_row(sess, row)
        if not can_approve_in_session(sess, plan, user):
            raise PermissionDenied("只有负责导师或管理员可以重新打开内部版")
        pstore._check_rev(row, rev)
        if row.status != "approved":
            raise pstore.StatusError("只有已批准的内部版才能重新打开")
        _revoke_all_leases(sess, plan_id, "state_change")
        current = (sess.get(pstore.M1PlanVersion, row.current_version_id)
                   if row.current_version_id else None)
        version = pstore.M1PlanVersion(
            plan_id=int(plan_id), part="internal",
            n=int((current.n if current else 0) or 0) + 1, kind="edit",
            ai_doc=current.ai_doc if current else None,
            doc=current.doc if current else None,
            checks=current.checks if current else None,
            manifest=current.manifest if current else None,
            created_by=user.get("user_id"))
        sess.add(version)
        sess.flush()
        row.current_version_id = version.id
        row.status = "review"
        row.approved_by = None
        row.approved_at = None
        row.rev = int(row.rev or 1) + 1
        row.updated_at = _now()
        document_version = bump_document_in_session(sess, plan_id, user.get("user_id"))
        _audit_in_session(sess, user.get("user_id"), plan.get("student_id"),
                          "m1.plan_reopen",
                          {"plan_id": int(plan_id), "version_id": version.id,
                           "rev": int(row.rev)})
        sess.commit()
        return {"plan": pstore.get_plan(plan_id),
                "document_version": document_version,
                "rev": int(row.rev)}


def confirm_parent_action(plan_id: int, user: Dict[str, Any], rev: int) -> Dict[str, Any]:
    with Session(pstore._engine()) as sess:
        _writer(sess)
        row = _lock_plan(sess, plan_id)
        if row is None:
            raise pstore.NotFound("发展计划不存在")
        plan = pstore._plan_row(sess, row)
        if not can_approve_in_session(sess, plan, user):
            raise PermissionDenied("只有负责导师或管理员可以确认家长版")
        pstore._check_rev(row, rev)
        if row.status != "approved":
            raise pstore.StatusError("请先批准内部版")
        if row.parent_status != "draft":
            raise pstore.StatusError("当前状态不能确认家长版")
        if pstore._parent_stale(sess, row):
            raise pstore.StatusError("内部版已更改，请重新生成家长版")
        _require_no_edits(sess, plan_id)
        _require_parent_ready(sess, plan, row)
        row.parent_status = "confirmed"
        row.parent_confirmed_by = user.get("user_id")
        row.parent_confirmed_at = _now()
        row.rev = int(row.rev or 1) + 1
        row.updated_at = _now()
        _audit_in_session(sess, user.get("user_id"), plan.get("student_id"),
                          "m1.plan_parent_confirm",
                          {"plan_id": int(plan_id), "rev": int(row.rev)})
        sess.commit()
        return {"plan": pstore.get_plan(plan_id), "rev": int(row.rev)}


def export_parent_action(plan_id: int, user: Dict[str, Any], rev: int) -> Dict[str, Any]:
    with Session(pstore._engine()) as sess:
        _writer(sess)
        row = _lock_plan(sess, plan_id)
        if row is None:
            raise pstore.NotFound("发展计划不存在")
        plan = pstore._plan_row(sess, row)
        if not can_approve_in_session(sess, plan, user):
            raise PermissionDenied("只有负责导师或管理员可以导出家长版")
        pstore._check_rev(row, rev)
        if row.parent_status not in ("confirmed", "exported"):
            raise pstore.StatusError("请先确认家长版")
        if row.status != "approved":
            raise pstore.StatusError("请先批准内部版")
        if pstore._parent_stale(sess, row):
            raise pstore.StatusError("内部版已更改，请重新生成家长版")
        _require_no_edits(sess, plan_id)
        _require_parent_ready(sess, plan, row)
        row.parent_status = "exported"
        row.parent_exported_at = _now()
        row.rev = int(row.rev or 1) + 1
        row.updated_at = _now()
        _audit_in_session(sess, user.get("user_id"), plan.get("student_id"),
                          "m1.plan_parent_export",
                          {"plan_id": int(plan_id), "rev": int(row.rev)})
        sess.commit()
        return {"plan": pstore.get_plan(plan_id), "rev": int(row.rev)}


def confirm_brief_action(plan_id: int, user: Dict[str, Any], rev: int) -> Dict[str, Any]:
    with Session(pstore._engine()) as sess:
        _writer(sess)
        row = _lock_plan(sess, plan_id)
        if row is None:
            raise pstore.NotFound("发展计划不存在")
        plan = pstore._plan_row(sess, row)
        if not can_edit_in_session(sess, plan, user):
            raise PermissionDenied("只有负责导师可以编辑该计划")
        pstore._check_rev(row, rev)
        pstore._ensure_editable(row)
        if not int(row.brief_revision or 0):
            raise ValueError("请先填写教学简报")
        row.brief_confirmed_revision = int(row.brief_revision)
        row.brief_confirmed_by = user.get("user_id")
        row.rev = int(row.rev or 1) + 1
        row.updated_at = _now()
        _bump_section_row(sess, plan_id, "brief",
                          _section_version(sess, plan_id, "brief"),
                          user.get("user_id"))
        _audit_in_session(sess, user.get("user_id"), plan.get("student_id"),
                          "m1.plan_context_update",
                          {"plan_id": int(plan_id), "action": "confirm_brief",
                           "rev": int(row.rev)})
        sess.commit()
        return {"plan": pstore.get_plan(plan_id), "rev": int(row.rev)}


# ---------------------------------------------------------------------------
# Audit helper (same transaction as the change)
# ---------------------------------------------------------------------------
def _audit_in_session(sess: Session, actor_id, student_id, action: str,
                      details: Dict[str, Any]) -> None:
    payload = dict(details or {})
    # The activity feed filters by prep_id; enrich with the plan's context.
    if payload.get("plan_id") is not None and "prep_id" not in payload:
        plan_row = sess.get(pstore.M1Plan, int(payload["plan_id"]))
        if plan_row is not None:
            payload.setdefault("prep_id", plan_row.prep_id)
            payload.setdefault("block_no", plan_row.block_no)
    sess.add(_gt.AuditLog(
        actor_id=int(actor_id) if actor_id is not None else None,
        student_id=int(student_id) if student_id is not None else None,
        action=str(action),
        details=pstore._dumps(payload)))


# ---------------------------------------------------------------------------
# Bootstrap view for detail/pages
# ---------------------------------------------------------------------------
def plan_summary(plan: Dict[str, Any], user) -> Dict[str, Any]:
    u = store._user_dict(user)
    with Session(pstore._engine()) as sess:
        return {
            "team": _team_view_in_session(sess, plan["student_id"]),
            "permissions": _permissions_in_session(sess, plan, u),
            "document_version": _document_version(sess, plan["id"]),
            "sections": _section_versions(sess, plan["id"]),
            "presence_ttl": PRESENCE_TTL_SECONDS,
            "lease_ttl": LEASE_TTL_SECONDS,
            "poll_seconds": POLL_SECONDS,
        }


def active_leases(plan_id: int) -> List[Dict[str, Any]]:
    with Session(pstore._engine()) as sess:
        _expire_leases(sess, plan_id)
        rows = sess.execute(select(PlanEditLease).where(
            PlanEditLease.plan_id == int(plan_id),
            PlanEditLease.released_at.is_(None))).scalars().all()
        data = [_lease_payload(sess, row) for row in rows]
        sess.commit()
        return data
