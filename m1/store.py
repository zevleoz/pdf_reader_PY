"""M1 会前准备数据层（SQLite / SQLAlchemy）。

三张表挂在 ``db.Base`` 上，``db.init_db()`` 导入本模块后由
``Base.metadata.create_all`` 建表：

- ``m1_preps``     一次会前准备（学生 + 会议信息 + 当前草稿版本）
- ``m1_sources``   导师上传/粘贴的补充资料（Y4、First Touch、补充问卷为自动来源，不入表）
- ``m1_versions``  不可变的 AI 初稿 / 定稿，以及唯一可覆盖的 edit 草稿

对外函数统一返回 dict，不把 ORM 实例泄漏给调用方。本模块不得 import
app / blueprints（P3 的生成子进程会直接 import 它）。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (Column, DateTime, ForeignKey, Index, Integer, String,
                        Text, select)
from sqlalchemy.orm import Session

import db as _db
import growth_talk_store as _gt

Base = _db.Base

STATUSES = ("draft", "generating", "review", "final")
KINDS = ("ai_draft", "edit", "final")
SOURCE_CATEGORIES = ("parent", "case_review", "other", "first_touch_extra")
SOURCE_STATUSES = ("ok", "partial", "unreadable")
DURATIONS = (60, 75, 90)


# ---------------------------------------------------------------------------
# 模型
# ---------------------------------------------------------------------------
class M1Prep(Base):
    __tablename__ = "m1_preps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    meeting_date = Column(String(20), nullable=False, default="")
    mentor_user_id = Column(Integer, ForeignKey("users.id"))
    duration = Column(Integer, nullable=False, default=60)
    attendees = Column(Text, nullable=False, default="[]")
    status = Column(String(20), nullable=False, default="draft")
    current_version_id = Column(Integer)
    rev = Column(Integer, nullable=False, default=1)
    safety_ack_by = Column(Integer)
    safety_ack_at = Column(DateTime)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_m1_preps_student_updated", "student_id", "updated_at"),
        Index("ix_m1_preps_mentor", "mentor_user_id"),
    )


class M1Source(Base):
    __tablename__ = "m1_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prep_id = Column(Integer, ForeignKey("m1_preps.id"), nullable=False)
    category = Column(String(30), nullable=False)
    label = Column(String(200), nullable=False, default="")
    filename = Column(String(300), nullable=False, default="")
    stored_path = Column(String(500), nullable=False, default="")
    text = Column(Text, nullable=False, default="")
    detected_date = Column(String(20), nullable=False, default="")
    status = Column(String(20), nullable=False, default="ok")
    uploaded_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_m1_sources_prep", "prep_id"),
    )


class M1Version(Base):
    __tablename__ = "m1_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prep_id = Column(Integer, ForeignKey("m1_preps.id"), nullable=False)
    n = Column(Integer, nullable=False, default=1)
    kind = Column(String(20), nullable=False)
    y4_snapshot = Column(Text)
    kb_version = Column(String(50))
    evidence = Column(Text)
    ai_output = Column(Text)
    doc = Column(Text)
    ai_generated_at = Column(DateTime)
    reviewed_at = Column(DateTime)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_m1_versions_prep_n", "prep_id", "n"),
    )


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------
class NotFoundError(Exception):
    """记录不存在。"""


class RevConflict(Exception):
    """``rev`` 与服务器不一致；``doc`` 为服务器当前草稿。"""

    def __init__(self, rev: int, doc: Optional[dict]):
        super().__init__("草稿已在别处更新，请刷新后重试")
        self.rev = rev
        self.doc = doc


class FinalizeBlocked(Exception):
    """定稿被拒（安全提示未确认 / 尚无初稿）。"""


# ---------------------------------------------------------------------------
# 内部助手
# ---------------------------------------------------------------------------
def _engine():
    """读取 db.engine 的当前值（测试 monkeypatch 可生效）。"""
    return _db.engine


def _dumps(value) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _loads(value, default=None):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return default
    return parsed


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _user_dict(user) -> dict:
    if user is None:
        try:
            import app_utils
            return app_utils.current_user()
        except Exception:
            return {"user_id": None, "role": "", "advisor_name": "", "display_name": ""}
    if isinstance(user, dict):
        return user
    return {
        "user_id": getattr(user, "id", None),
        "role": getattr(user, "role", "") or "",
        "advisor_name": getattr(user, "advisor_name", "") or "",
        "display_name": getattr(user, "display_name", "") or "",
    }


def _prep_row(row: M1Prep, student=None, mentor_name: str = "") -> Dict[str, Any]:
    return {
        "id": row.id,
        "student_id": row.student_id,
        "student_name": getattr(student, "name", "") or "",
        "student_code": getattr(student, "student_code", "") or "",
        "grade": getattr(student, "grade", "") or "",
        "school": getattr(student, "school", "") or "",
        "advisor_name": getattr(student, "advisor_name", "") or "",
        "meeting_date": row.meeting_date or "",
        "mentor_user_id": row.mentor_user_id,
        "mentor_name": mentor_name,
        "duration": int(row.duration or 60),
        "attendees": _loads(row.attendees, []) or [],
        "status": row.status,
        "current_version_id": row.current_version_id,
        "rev": int(row.rev or 1),
        "safety_ack_by": row.safety_ack_by,
        "safety_ack_at": _iso(row.safety_ack_at),
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _source_row(row: M1Source) -> Dict[str, Any]:
    return {
        "id": row.id,
        "prep_id": row.prep_id,
        "category": row.category,
        "label": row.label or "",
        "filename": row.filename or "",
        "stored_path": row.stored_path or "",
        "text": row.text or "",
        "detected_date": row.detected_date or "",
        "status": row.status,
        "uploaded_by": row.uploaded_by,
        "created_at": _iso(row.created_at),
    }


def _version_row(row: M1Version, *, with_doc: bool = True) -> Dict[str, Any]:
    out = {
        "id": row.id,
        "prep_id": row.prep_id,
        "n": int(row.n or 1),
        "kind": row.kind,
        "y4_snapshot": _loads(row.y4_snapshot, {}),
        "kb_version": row.kb_version or "",
        "evidence": _loads(row.evidence, []),
        "ai_output": _loads(row.ai_output, {}),
        "ai_generated_at": _iso(row.ai_generated_at),
        "reviewed_at": _iso(row.reviewed_at),
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
    }
    if with_doc:
        out["doc"] = _loads(row.doc, None)
    return out


def _student(sess: Session, student_id: int):
    return sess.get(_db.Student, int(student_id))


def _mentor_name(sess: Session, user_id) -> str:
    if not user_id:
        return ""
    user = sess.get(_db.User, int(user_id))
    if not user:
        return ""
    return user.display_name or user.advisor_name or user.username or ""


def _next_n(sess: Session, prep_id: int) -> int:
    rows = sess.execute(
        select(M1Version.n).where(M1Version.prep_id == int(prep_id))
    ).scalars().all()
    return max([int(n or 0) for n in rows] or [0]) + 1


def _latest_version(sess: Session, prep_id: int, kind: Optional[str] = None,
                    with_doc: bool = True) -> Optional[Dict[str, Any]]:
    stmt = select(M1Version).where(M1Version.prep_id == int(prep_id))
    if kind:
        stmt = stmt.where(M1Version.kind == kind)
    row = sess.execute(
        stmt.order_by(M1Version.n.desc(), M1Version.id.desc())
    ).scalars().first()
    return _version_row(row, with_doc=with_doc) if row else None


# ---------------------------------------------------------------------------
# Preps
# ---------------------------------------------------------------------------
def create_prep(student_id: int, *, created_by=None, meeting_date: str = "",
                mentor_user_id=None, duration: int = 60,
                attendees: Optional[List[str]] = None) -> Dict[str, Any]:
    """新建一次会前准备。会议日期不自动生成，由导师在界面确认。"""
    student_id = int(student_id)
    with Session(_engine()) as sess:
        student = _student(sess, student_id)
        if not student:
            raise NotFoundError("学生不存在")
        row = M1Prep(
            student_id=student_id,
            meeting_date=(meeting_date or "").strip(),
            mentor_user_id=mentor_user_id if mentor_user_id is not None else created_by,
            duration=int(duration or 60),
            attendees=_dumps(list(attendees or [])),
            status="draft", rev=1, created_by=created_by,
        )
        sess.add(row)
        sess.flush()
        prep_id = row.id
        data = _prep_row(row, student,
                         _mentor_name(sess, row.mentor_user_id))
        sess.commit()
        return data


def get_prep(prep_id: int) -> Optional[Dict[str, Any]]:
    with Session(_engine()) as sess:
        row = sess.get(M1Prep, int(prep_id))
        if not row:
            return None
        data = _prep_row(row, _student(sess, row.student_id),
                         _mentor_name(sess, row.mentor_user_id))
        version = (sess.get(M1Version, row.current_version_id)
                   if row.current_version_id else None)
        data["current_version"] = _version_row(version) if version else None
        return data


def list_preps(*, user=None, student_id: Optional[int] = None,
               status: Optional[str] = None,
               limit: int = 200) -> List[Dict[str, Any]]:
    """会前准备列表；advisor 只看名下学生的与自己做 Mentor 的。"""
    user = _user_dict(user)
    with Session(_engine()) as sess:
        stmt = (select(M1Prep, _db.Student)
                .join(_db.Student, M1Prep.student_id == _db.Student.id)
                .order_by(M1Prep.updated_at.desc(), M1Prep.id.desc())
                .limit(int(limit)))
        if student_id is not None:
            stmt = stmt.where(M1Prep.student_id == int(student_id))
        if status:
            stmt = stmt.where(M1Prep.status == status)
        if user.get("role") == "advisor":
            scope = user.get("advisor_name") or ""
            stmt = stmt.where(
                (_db.Student.advisor_name == scope)
                | (M1Prep.mentor_user_id == user.get("user_id")))
        elif user.get("role") != "admin":
            return []
        return [_prep_row(prep, student, _mentor_name(sess, prep.mentor_user_id))
                for prep, student in sess.execute(stmt).all()]


def update_prep(prep_id: int, **fields) -> Dict[str, Any]:
    """更新会议信息（meeting_date / mentor_user_id / duration / attendees）。"""
    allowed = {"meeting_date", "mentor_user_id", "duration", "attendees"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError("不支持的字段：%s" % "、".join(sorted(unknown)))
    with Session(_engine()) as sess:
        row = sess.get(M1Prep, int(prep_id))
        if not row:
            raise NotFoundError("会前准备不存在")
        if "meeting_date" in fields:
            row.meeting_date = str(fields["meeting_date"] or "").strip()[:20]
        if "mentor_user_id" in fields:
            value = fields["mentor_user_id"]
            row.mentor_user_id = int(value) if value not in (None, "") else None
        if "duration" in fields:
            duration = int(fields["duration"] or 60)
            if not 5 <= duration <= 600:
                raise ValueError("会议时长需在 5–600 分钟之间")
            row.duration = duration
        if "attendees" in fields:
            attendees = fields["attendees"]
            if not isinstance(attendees, list):
                raise ValueError("参会人员需为字符串列表")
            row.attendees = _dumps([str(x).strip() for x in attendees if str(x).strip()])
        row.updated_at = datetime.utcnow()
        sess.commit()
        sess.refresh(row)
        return _prep_row(row, _student(sess, row.student_id),
                         _mentor_name(sess, row.mentor_user_id))


def set_status(prep_id: int, status: str) -> None:
    if status not in STATUSES:
        raise ValueError("未知状态：%s" % status)
    with Session(_engine()) as sess:
        row = sess.get(M1Prep, int(prep_id))
        if not row:
            raise NotFoundError("会前准备不存在")
        row.status = status
        row.updated_at = datetime.utcnow()
        sess.commit()


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
def add_source(prep_id: int, *, category: str, label: str = "", filename: str = "",
               stored_path: str = "", text: str = "", detected_date: str = "",
               status: str = "ok", uploaded_by=None) -> Dict[str, Any]:
    if category not in SOURCE_CATEGORIES:
        raise ValueError("未知资料类别：%s" % category)
    if status not in SOURCE_STATUSES:
        raise ValueError("未知资料状态：%s" % status)
    with Session(_engine()) as sess:
        if not sess.get(M1Prep, int(prep_id)):
            raise NotFoundError("会前准备不存在")
        row = M1Source(
            prep_id=int(prep_id), category=category, label=label or filename,
            filename=filename or "", stored_path=stored_path or "",
            text=text or "", detected_date=detected_date or "", status=status,
            uploaded_by=uploaded_by,
        )
        sess.add(row)
        sess.flush()
        data = _source_row(row)
        sess.commit()
        return data


def list_sources(prep_id: int) -> List[Dict[str, Any]]:
    with Session(_engine()) as sess:
        rows = sess.execute(
            select(M1Source).where(M1Source.prep_id == int(prep_id))
            .order_by(M1Source.id)
        ).scalars().all()
        return [_source_row(row) for row in rows]


def get_source(source_id: int) -> Optional[Dict[str, Any]]:
    with Session(_engine()) as sess:
        row = sess.get(M1Source, int(source_id))
        return _source_row(row) if row else None


def update_source(source_id: int, *, category: Optional[str] = None,
                  detected_date: Optional[str] = None) -> Dict[str, Any]:
    with Session(_engine()) as sess:
        row = sess.get(M1Source, int(source_id))
        if not row:
            raise NotFoundError("资料不存在")
        if category is not None:
            if category not in SOURCE_CATEGORIES:
                raise ValueError("未知资料类别：%s" % category)
            row.category = category
        if detected_date is not None:
            row.detected_date = str(detected_date or "").strip()[:20]
        data = _source_row(row)
        sess.commit()
        return data


def delete_source(source_id: int) -> Dict[str, Any]:
    """删除资料记录；返回被删行（含 stored_path，供调用方清理文件）。"""
    with Session(_engine()) as sess:
        row = sess.get(M1Source, int(source_id))
        if not row:
            raise NotFoundError("资料不存在")
        data = _source_row(row)
        sess.delete(row)
        sess.commit()
        return data


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------
def add_version(prep_id: int, kind: str, *, doc: Optional[dict] = None,
                y4_snapshot: Optional[dict] = None, kb_version: str = "",
                evidence=None, ai_output: Optional[dict] = None,
                ai_generated_at=None, reviewed_at=None, created_by=None,
                set_current: bool = True) -> Dict[str, Any]:
    """追加版本行。``ai_draft`` / ``final`` 落库后不再修改。"""
    if kind not in KINDS:
        raise ValueError("未知版本类型：%s" % kind)
    with Session(_engine()) as sess:
        prep = sess.get(M1Prep, int(prep_id))
        if not prep:
            raise NotFoundError("会前准备不存在")
        row = M1Version(
            prep_id=int(prep_id), n=_next_n(sess, prep_id), kind=kind,
            y4_snapshot=_dumps(y4_snapshot) if y4_snapshot is not None else None,
            kb_version=kb_version or None,
            evidence=_dumps(evidence) if evidence is not None else None,
            ai_output=_dumps(ai_output) if ai_output is not None else None,
            doc=_dumps(doc) if doc is not None else None,
            ai_generated_at=ai_generated_at, reviewed_at=reviewed_at,
            created_by=created_by,
        )
        sess.add(row)
        sess.flush()
        if set_current:
            prep.current_version_id = row.id
        prep.updated_at = datetime.utcnow()
        data = _version_row(row)
        sess.commit()
        return data


def get_version(version_id: int) -> Optional[Dict[str, Any]]:
    with Session(_engine()) as sess:
        row = sess.get(M1Version, int(version_id))
        return _version_row(row) if row else None


def get_current_version(prep_id: int) -> Optional[Dict[str, Any]]:
    with Session(_engine()) as sess:
        prep = sess.get(M1Prep, int(prep_id))
        if not prep or not prep.current_version_id:
            return None
        row = sess.get(M1Version, prep.current_version_id)
        return _version_row(row) if row else None


def get_latest_version(prep_id: int, kind: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with Session(_engine()) as sess:
        return _latest_version(sess, prep_id, kind)


def list_versions(prep_id: int) -> List[Dict[str, Any]]:
    with Session(_engine()) as sess:
        rows = sess.execute(
            select(M1Version).where(M1Version.prep_id == int(prep_id))
            .order_by(M1Version.n, M1Version.id)
        ).scalars().all()
        return [_version_row(row, with_doc=False) for row in rows]


def save_doc(prep_id: int, rev: int, doc: dict) -> Dict[str, Any]:
    """自动保存草稿：``rev`` 与服务器一致才写，成功后 ``rev + 1``。

    编辑只写单个 ``edit`` 行（每个草稿一行，随保存覆盖）；``ai_draft`` /
    ``final`` 永不改动。``rev`` 不一致抛 :class:`RevConflict`，附带服务器草稿。
    """
    if not isinstance(doc, dict):
        raise ValueError("doc 必须是对象")
    with Session(_engine()) as sess:
        prep = sess.get(M1Prep, int(prep_id))
        if not prep:
            raise NotFoundError("会前准备不存在")
        if prep.status == "final":
            raise FinalizeBlocked("已定稿版本不可直接修改，请先基于此版本再修改")
        if int(rev) != int(prep.rev or 1):
            current = _latest_version(sess, prep_id, "edit")
            raise RevConflict(int(prep.rev or 1), current.get("doc") if current else None)
        edit = sess.execute(
            select(M1Version).where(M1Version.prep_id == int(prep_id),
                                    M1Version.kind == "edit")
            .order_by(M1Version.n.desc(), M1Version.id.desc())
        ).scalars().first()
        if edit is None:
            draft = _latest_version(sess, prep_id, "ai_draft")
            edit = M1Version(
                prep_id=int(prep_id), n=_next_n(sess, prep_id), kind="edit",
                y4_snapshot=(draft or {}).get("y4_snapshot") and
                _dumps(draft["y4_snapshot"]) or None,
                kb_version=(draft or {}).get("kb_version") or None,
                evidence=_dumps((draft or {}).get("evidence") or []) if draft else None,
                ai_output=_dumps((draft or {}).get("ai_output") or {}) if draft else None,
                doc=_dumps(doc), created_by=prep.created_by,
            )
            sess.add(edit)
            sess.flush()
            prep.current_version_id = edit.id
        else:
            edit.doc = _dumps(doc)
        prep.rev = int(prep.rev or 1) + 1
        prep.updated_at = datetime.utcnow()
        result = {"rev": prep.rev, "version_id": edit.id}
        sess.commit()
        return result


def ack_safety(prep_id: int, user_id=None) -> Dict[str, Any]:
    """记录安全提示已确认（导师已知晓并按流程处理）。"""
    with Session(_engine()) as sess:
        prep = sess.get(M1Prep, int(prep_id))
        if not prep:
            raise NotFoundError("会前准备不存在")
        prep.safety_ack_by = int(user_id) if user_id is not None else None
        prep.safety_ack_at = datetime.utcnow()
        prep.updated_at = datetime.utcnow()
        data = _prep_row(prep, _student(sess, prep.student_id),
                         _mentor_name(sess, prep.mentor_user_id))
        sess.commit()
        return data


def _safety_flags(doc: dict) -> list:
    flags = (doc or {}).get("flags") or {}
    safety = flags.get("safety") if isinstance(flags, dict) else None
    return safety if isinstance(safety, list) else []


def finalize_prep(prep_id: int, user_id=None) -> Dict[str, Any]:
    """把当前 edit 草稿固化为 ``final`` 版本；安全提示未确认时拒绝。"""
    with Session(_engine()) as sess:
        prep = sess.get(M1Prep, int(prep_id))
        if not prep:
            raise NotFoundError("会前准备不存在")
        edit = sess.execute(
            select(M1Version).where(M1Version.prep_id == int(prep_id),
                                    M1Version.kind == "edit")
            .order_by(M1Version.n.desc(), M1Version.id.desc())
        ).scalars().first()
        if edit is None or not _loads(edit.doc, None):
            raise FinalizeBlocked("尚无 AI 初稿，不能定稿")
        doc = _loads(edit.doc, {}) or {}
        if _safety_flags(doc) and not prep.safety_ack_at:
            raise FinalizeBlocked("存在安全提示，需先确认后才可定稿")
        if prep.status == "final":
            raise FinalizeBlocked("该会前准备已定稿")
        row = M1Version(
            prep_id=int(prep_id), n=_next_n(sess, prep_id), kind="final",
            y4_snapshot=edit.y4_snapshot, kb_version=edit.kb_version,
            evidence=edit.evidence, ai_output=edit.ai_output,
            doc=edit.doc, ai_generated_at=edit.ai_generated_at,
            reviewed_at=datetime.utcnow(), created_by=user_id,
        )
        sess.add(row)
        sess.flush()
        prep.status = "final"
        prep.current_version_id = row.id
        prep.rev = int(prep.rev or 1) + 1
        prep.updated_at = datetime.utcnow()
        data = _version_row(row)
        sess.commit()
        return data


def reopen_prep(prep_id: int, user_id=None) -> Dict[str, Any]:
    """把 final 版本复制成新的 edit 草稿；final 行保持原样。"""
    with Session(_engine()) as sess:
        prep = sess.get(M1Prep, int(prep_id))
        if not prep:
            raise NotFoundError("会前准备不存在")
        final = None
        if prep.current_version_id:
            final = sess.get(M1Version, prep.current_version_id)
        if final is None or final.kind != "final":
            final = sess.execute(
                select(M1Version).where(M1Version.prep_id == int(prep_id),
                                        M1Version.kind == "final")
                .order_by(M1Version.n.desc(), M1Version.id.desc())
            ).scalars().first()
        if final is None:
            raise FinalizeBlocked("尚无定稿版本，无需重新打开")
        row = M1Version(
            prep_id=int(prep_id), n=_next_n(sess, prep_id), kind="edit",
            y4_snapshot=final.y4_snapshot, kb_version=final.kb_version,
            evidence=final.evidence, ai_output=final.ai_output,
            doc=final.doc, created_by=user_id,
        )
        sess.add(row)
        sess.flush()
        prep.status = "review"
        prep.current_version_id = row.id
        prep.rev = int(prep.rev or 1) + 1
        prep.updated_at = datetime.utcnow()
        data = _version_row(row)
        sess.commit()
        return data


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------
def can_access_student(user, student_id: int) -> bool:
    """README §3：admin 全部；advisor 仅名下学生；viewer 无。"""
    u = _user_dict(user)
    role = u.get("role") or ""
    if role == "admin":
        return True
    if role != "advisor":
        return False
    with Session(_engine()) as sess:
        student = _student(sess, student_id)
        if not student:
            return False
        # an advisor account without a name owns nobody (empty must not match empty)
        name = (u.get("advisor_name") or "").strip()
        return bool(name) and (student.advisor_name or "").strip() == name


def can_access_prep(user, prep_id: int) -> bool:
    """admin 全部；advisor 名下学生或本人是该准备推进的 Mentor。"""
    u = _user_dict(user)
    role = u.get("role") or ""
    if role == "admin":
        return True
    if role != "advisor":
        return False
    with Session(_engine()) as sess:
        prep = sess.get(M1Prep, int(prep_id))
        if not prep:
            return False
        if prep.mentor_user_id is not None and u.get("user_id") is not None:
            if int(prep.mentor_user_id) == int(u.get("user_id")):
                return True
        student = _student(sess, prep.student_id)
        if not student:
            return False
        # an advisor account without a name owns nobody (empty must not match empty)
        name = (u.get("advisor_name") or "").strip()
        return bool(name) and (student.advisor_name or "").strip() == name


def can_access(user, target) -> bool:
    """``target`` 可以是 prep dict 或 student dict（README §3 的规则）。"""
    if target is None:
        return False
    if isinstance(target, M1Prep):
        return can_access_prep(user, target.id)
    if isinstance(target, _db.Student):
        return can_access_student(user, target.id)
    if isinstance(target, dict):
        if "mentor_user_id" in target or target.get("kind") == "prep":
            return can_access_prep(user, target.get("id"))
        return can_access_student(user, target.get("id"))
    if isinstance(target, int):
        return can_access_prep(user, target)
    return False


# ---------------------------------------------------------------------------
# 学生清单 / 审计
# ---------------------------------------------------------------------------
def list_students(user=None) -> List[Dict[str, Any]]:
    """可挑学生：Y4 是否完整 + 未完成原因（只返回调用者可见的学生）。"""
    from growth_talk import y4_snapshot

    u = _user_dict(user)
    with Session(_engine()) as sess:
        stmt = select(_db.Student).order_by(_db.Student.name)
        if u.get("role") == "advisor":
            name = (u.get("advisor_name") or "").strip()
            if not name:
                return []
            stmt = stmt.where(_db.Student.advisor_name == name)
        elif u.get("role") != "admin":
            return []
        students = sess.execute(stmt).scalars().all()
        rows = []
        for student in students:
            complete_date = ""
            latest_date = ""
            for report in sess.execute(
                    select(_db.Report).where(_db.Report.student_id == student.id)
                    .order_by(_db.Report.report_date.desc(), _db.Report.id.desc())
            ).scalars():
                if report.report_date and not latest_date:
                    latest_date = report.report_date.isoformat()
                if not complete_date and y4_snapshot.is_complete(report):
                    complete_date = (report.report_date.isoformat()
                                     if report.report_date else "")
            has_prep = sess.execute(
                select(M1Prep.id).where(M1Prep.student_id == student.id).limit(1)
            ).scalars().first()
            rows.append({
                "id": student.id,
                "student_code": student.student_code or "",
                "name": student.name or "",
                "grade": student.grade or "",
                "school": student.school or "",
                "advisor_name": student.advisor_name or "",
                "y4_complete": bool(complete_date),
                "y4_date": complete_date,
                "y4_latest_date": latest_date,
                "reason": "" if complete_date else "Y4 尚未完成",
                "has_prep": bool(has_prep),
            })
        return rows


def audit(user_id, student_id, action: str, details=None) -> None:
    """写既有 ``audit_log`` 表（growth_talk_store.AuditLog）。"""
    with Session(_engine()) as sess:
        sess.add(_gt.AuditLog(
            actor_id=int(user_id) if user_id is not None else None,
            student_id=int(student_id) if student_id is not None else None,
            action=str(action),
            details=_dumps(details or {}),
        ))
        sess.commit()
