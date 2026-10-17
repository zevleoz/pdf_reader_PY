"""问卷子系统数据层（Agent C）——题库 / 识别规则版本 / 任务 / 一次性链接 /
临时学生账号 / 原始答案 / 草稿。

设计要点（对应 spec 6.2 与 03 指令包 §5.1）：

- 6 张新表 + ``response_drafts`` 的 ORM 模型定义在本模块，注册到 ``db.Base``；
  ``db.init_db()`` 在 ``create_all`` 前 import 本模块以完成注册（见 db.py）。
- 活动任务去重：``(student_id, questionnaire_id)`` 在 status ∈ (pending, sent)
  内唯一 —— ORM 声明不了带 WHERE 的索引，用 ``ensure_indexes()`` 建部分唯一索引
  （SQLite 与 PostgreSQL 都支持 ``CREATE UNIQUE INDEX ... WHERE``）。
- 一次性链接：DB 只存 token 的 sha256 哈希，验证时哈希比对；明文仅在
  confirm / reissue 的响应里出现一次（spec 6.2）。
- 临时学生账号：初始密码仅创建时明文返回一次，DB 存 werkzeug 哈希。
- 本模块是「集成胶水层」，允许 import db / evaluation_rules / questionnaire_engine；
  规则求值本身在 questionnaire_engine（纯函数）里。
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import (Column, ForeignKey, Integer, String, Text, DateTime,
                        insert, select, update, delete, func)
from werkzeug.security import check_password_hash, generate_password_hash

import db as _db

Base = _db.Base
Session = _db.Session
engine = _db.engine

TOKEN_TTL_DAYS = 7
ACTIVE_STATUSES = ("pending", "sent")
# 状态机（spec 6.5）：pending → sent → submitted / expired；另有 rejected
STATUSES = ("pending", "sent", "submitted", "expired", "rejected")
DELIVERIES = ("link", "account", "both")
SEED_DIR = Path(__file__).resolve().parent / "questionnaires_seed"


# ─── ORM 模型 ──────────────────────────────────────────────────

class Questionnaire(Base):
    """固定题库（seed 导入；不可在线编题，只能启停）。"""
    __tablename__ = "questionnaires"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), nullable=False, unique=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    schema_json = Column(Text, nullable=False)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)


class QuestionnaireRule(Base):
    """识别规则版本。status: draft（可多个）/ published（至多 1 个）/ archived。

    沿用 six_am_rule_versions 的「唯一 published」不变式。
    """
    __tablename__ = "questionnaire_rules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="draft")
    rules_json = Column(Text, nullable=False)
    note = Column(String(300))
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime)


class Assignment(Base):
    """问卷任务。``reason`` 为识别/人工填写的原因，写入界面与档案。

    部分唯一索引 ux_assignments_active 保证活动任务不重复（见 ensure_indexes）。
    """
    __tablename__ = "assignments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    questionnaire_id = Column(Integer, ForeignKey("questionnaires.id"), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    source = Column(String(20), nullable=False, default="auto")
    reason = Column(Text)
    delivery = Column(String(20))
    confirmed_by = Column(Integer, ForeignKey("users.id"))
    confirmed_at = Column(DateTime)
    submitted_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


class AssignmentToken(Base):
    """一次性链接。token 列存 sha256 十六进制（防库泄露后链接被伪造）。"""
    __tablename__ = "assignment_tokens"
    id = Column(Integer, primary_key=True, autoincrement=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=False, index=True)
    token = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


class StudentAccount(Base):
    """临时学生账号；每生最多一个，username 默认 = students.student_code。"""
    __tablename__ = "student_accounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False, unique=True)
    username = Column(String(100), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)


class Response(Base):
    """原始答案（不计分、不并入 124 指标）。"""
    __tablename__ = "responses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    questionnaire_id = Column(Integer, ForeignKey("questionnaires.id"), nullable=False)
    answers_json = Column(Text, nullable=False)
    submitted_via = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ResponseDraft(Base):
    """账号模式的作答进度（每任务一条）。"""
    __tablename__ = "response_drafts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=False, unique=True)
    answers_json = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ─── 表/索引初始化 ─────────────────────────────────────────────

def create_tables(bind=None) -> None:
    """只创建问卷子系统相关表（幂等；供迁移脚本与 db.init_db 调用）。"""
    tables = [Questionnaire.__table__, QuestionnaireRule.__table__,
              Assignment.__table__, AssignmentToken.__table__,
              StudentAccount.__table__, Response.__table__,
              ResponseDraft.__table__]
    Base.metadata.create_all(bind or engine, tables=tables)


def ensure_indexes(bind=None) -> None:
    """活动任务部分唯一索引。

    SQLite 不支持 ORM 层带 WHERE 的唯一约束，这里用原生 DDL；
    ``CREATE UNIQUE INDEX IF NOT EXISTS ... WHERE`` 在 SQLite 9.6+ 与
    PostgreSQL 9.5+ 语义一致。
    """
    from sqlalchemy import text
    ddl = ("CREATE UNIQUE INDEX IF NOT EXISTS ux_assignments_active "
           "ON assignments (student_id, questionnaire_id) "
           "WHERE status IN ('pending', 'sent')")
    with (bind or engine).begin() as conn:
        conn.execute(text(ddl))


# ─── 序列化 ────────────────────────────────────────────────────

def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def _q_row(m: "Questionnaire", with_schema: bool = False) -> Dict[str, Any]:
    out = {
        "id": m.id,
        "code": m.code,
        "title": m.title,
        "description": m.description or "",
        "is_active": int(m.is_active or 0),
        "created_at": _iso(m.created_at),
    }
    if with_schema:
        try:
            out["schema"] = json.loads(m.schema_json or "{}")
        except Exception:
            out["schema"] = {}
    return out


def _r_row(m: "QuestionnaireRule") -> Dict[str, Any]:
    return {
        "id": m.id,
        "version": m.version,
        "status": m.status,
        "rules_json": m.rules_json,
        "note": m.note or "",
        "created_by": m.created_by,
        "created_at": _iso(m.created_at),
        "published_at": _iso(m.published_at),
    }


def _a_row(m: "Assignment") -> Dict[str, Any]:
    return {
        "id": m.id,
        "student_id": m.student_id,
        "questionnaire_id": m.questionnaire_id,
        "status": m.status,
        "source": m.source,
        "reason": m.reason or "",
        "delivery": m.delivery or "",
        "confirmed_by": m.confirmed_by,
        "confirmed_at": _iso(m.confirmed_at),
        "submitted_at": _iso(m.submitted_at),
        "created_at": _iso(m.created_at),
    }


# ─── 题库 ──────────────────────────────────────────────────────

def list_questionnaires(active_only: bool = False) -> List[Dict[str, Any]]:
    with Session(engine) as sess:
        stmt = select(Questionnaire).order_by(Questionnaire.id)
        if active_only:
            stmt = stmt.where(Questionnaire.is_active == 1)
        return [_q_row(m) for m in sess.execute(stmt).scalars().all()]


def get_questionnaire(qid: int, with_schema: bool = False) -> Optional[Dict[str, Any]]:
    with Session(engine) as sess:
        m = sess.get(Questionnaire, int(qid))
        return _q_row(m, with_schema=with_schema) if m else None


def get_questionnaire_by_code(code: str, with_schema: bool = False) -> Optional[Dict[str, Any]]:
    with Session(engine) as sess:
        m = sess.execute(select(Questionnaire)
                         .where(Questionnaire.code == str(code))).scalars().first()
        return _q_row(m, with_schema=with_schema) if m else None


def set_questionnaire_active(qid: int, active: bool) -> bool:
    with Session(engine) as sess:
        res = sess.execute(update(Questionnaire).where(Questionnaire.id == int(qid))
                           .values(is_active=1 if active else 0))
        sess.commit()
        return bool(res.rowcount)


# ─── 题库 seed 导入 ────────────────────────────────────────────

def load_seed_files(seed_dir: Optional[Path] = None) -> Dict[str, Any]:
    """读取 ``questionnaires_seed/*.json`` 并按 code upsert 题库。

    seed 文件结构：``{code, title, description, schema: {version, questions, ...}}``。
    库中已有但 seed 里消失的问卷不删除，置 is_active=0 并记录在报告中。
    """
    seed_dir = Path(seed_dir or SEED_DIR)
    report: Dict[str, Any] = {"added": [], "updated": [], "unchanged": [],
                              "missing_files": [], "disabled": []}
    if not seed_dir.exists():
        report["missing_files"].append(str(seed_dir))
        return report

    files = sorted(p for p in seed_dir.glob("*.json") if not p.name.startswith("_"))
    loaded_codes = set()
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            report.setdefault("errors", []).append(f"{path.name}: 解析失败 {e}")
            continue
        code = str(data.get("code") or "").strip()
        schema = data.get("schema") or {}
        if not code or not isinstance(schema, dict) or not schema.get("questions"):
            report.setdefault("errors", []).append(f"{path.name}: 缺少 code 或 schema.questions")
            continue
        loaded_codes.add(code)
        title = data.get("title") or code
        description = data.get("description") or ""
        schema_json = json.dumps(schema, ensure_ascii=False)
        existing = get_questionnaire_by_code(code, with_schema=True)
        with Session(engine) as sess:
            if existing is None:
                sess.execute(insert(Questionnaire).values(
                    code=code, title=title, description=description,
                    schema_json=schema_json, is_active=1))
                report["added"].append(code)
            else:
                same = (existing.get("title") == title
                        and existing.get("description") == description
                        and json.dumps(existing.get("schema") or {}, ensure_ascii=False) == schema_json
                        and existing.get("is_active") == 1)
                sess.execute(update(Questionnaire).where(Questionnaire.id == existing["id"]).values(
                    title=title, description=description,
                    schema_json=schema_json, is_active=1))
                report["unchanged" if same else "updated"].append(code)
            sess.commit()

    with Session(engine) as sess:
        rows = sess.execute(select(Questionnaire)).scalars().all()
        for m in rows:
            if m.code not in loaded_codes and int(m.is_active or 0) == 1:
                sess.execute(update(Questionnaire).where(Questionnaire.id == m.id)
                             .values(is_active=0))
                report["disabled"].append(m.code)
        sess.commit()
    return report


# ─── 识别规则版本 ──────────────────────────────────────────────

def list_rule_versions() -> List[Dict[str, Any]]:
    with Session(engine) as sess:
        stmt = select(QuestionnaireRule).order_by(QuestionnaireRule.id.desc())
        return [_r_row(m) for m in sess.execute(stmt).scalars().all()]


def get_rule_version(vid: int) -> Optional[Dict[str, Any]]:
    with Session(engine) as sess:
        m = sess.get(QuestionnaireRule, int(vid))
        return _r_row(m) if m else None


def get_published_rules() -> Optional[Dict[str, Any]]:
    """当前 published 版 rules_json（dict）；无 published 返回 None。"""
    with Session(engine) as sess:
        m = sess.execute(select(QuestionnaireRule)
                         .where(QuestionnaireRule.status == "published")).scalars().first()
    if not m:
        return None
    try:
        return json.loads(m.rules_json or "{}")
    except Exception:
        return None


def save_rule_version(rules_json: Any, note: str = "",
                      created_by: Optional[int] = None) -> int:
    """新建 draft 版本（version = 当前最大 version + 1）。"""
    if not isinstance(rules_json, (dict, list)):
        raise ValueError("rules_json 必须是对象")
    payload = json.dumps(rules_json, ensure_ascii=False)
    with Session(engine) as sess:
        maxv = sess.execute(select(func.max(QuestionnaireRule.version))).scalar() or 0
        res = sess.execute(insert(QuestionnaireRule).values(
            version=int(maxv) + 1, status="draft", rules_json=payload,
            note=note or "", created_by=created_by))
        sess.commit()
        return res.lastrowid


def publish_rule_version(vid: int) -> None:
    """发布：目标 → published；其余 published → archived（唯一 published 不变式）。"""
    with Session(engine) as sess:
        sess.execute(update(QuestionnaireRule)
                     .where(QuestionnaireRule.status == "published")
                     .values(status="archived"))
        sess.execute(update(QuestionnaireRule).where(QuestionnaireRule.id == int(vid))
                     .values(status="published", published_at=datetime.utcnow()))
        sess.commit()


def delete_rule_version(vid: int) -> bool:
    """只允许删 draft 版本。"""
    with Session(engine) as sess:
        res = sess.execute(delete(QuestionnaireRule)
                           .where(QuestionnaireRule.id == int(vid),
                                  QuestionnaireRule.status == "draft"))
        sess.commit()
        return bool(res.rowcount)


def load_rules_seed(path: Optional[Path] = None) -> Dict[str, Any]:
    """种子规则导入：仅在库中**没有任何**规则版本时导入并直接发布。

    seed 文件 ``questionnaires_seed/_rules_v1.json``；之后所有变更走规则管理页。
    """
    with Session(engine) as sess:
        count = sess.execute(select(func.count()).select_from(QuestionnaireRule)).scalar() or 0
    if count:
        return {"skipped": "rules_exist", "count": int(count)}
    p = Path(path or (SEED_DIR / "_rules_v1.json"))
    if not p.exists():
        return {"skipped": "no_seed_file", "path": str(p)}
    data = json.loads(p.read_text(encoding="utf-8"))
    payload = {"version": int(data.get("version") or 1), "rules": data.get("rules") or []}
    vid = save_rule_version(payload, note=data.get("note") or "初始识别规则",
                           created_by=None)
    publish_rule_version(vid)
    return {"published": vid, "rule_count": len(payload["rules"])}


# ─── 任务 ──────────────────────────────────────────────────────

def _find_active_assignment(sess, student_id: int, questionnaire_id: int) -> Optional["Assignment"]:
    return sess.execute(select(Assignment).where(
        Assignment.student_id == int(student_id),
        Assignment.questionnaire_id == int(questionnaire_id),
        Assignment.status.in_(ACTIVE_STATUSES))).scalars().first()


def create_assignment(student_id: int, questionnaire_id: int, *,
                      source: str = "manual", reason: str = "",
                      status: str = "pending") -> Tuple[int, bool]:
    """创建任务；同生同卷已有活动任务时复用。返回 (assignment_id, created)。"""
    with Session(engine) as sess:
        dup = _find_active_assignment(sess, student_id, questionnaire_id)
        if dup is not None:
            return dup.id, False
        res = sess.execute(insert(Assignment).values(
            student_id=int(student_id), questionnaire_id=int(questionnaire_id),
            status=status, source=source, reason=reason or ""))
        sess.commit()
        return res.lastrowid, True


def get_assignment(aid: int) -> Optional[Dict[str, Any]]:
    with Session(engine) as sess:
        m = sess.get(Assignment, int(aid))
        return _a_row(m) if m else None


def refresh_expired() -> int:
    """把「链接全部过期且无可用未用 token」的 sent 任务标记为 expired。"""
    with Session(engine) as sess:
        changed = _refresh_expired(sess)
        if changed:
            sess.commit()
    return changed


def _refresh_expired(sess) -> int:
    """同上，但在调用方事务内执行（不 commit）；由 list/counts 合并入口复用，
    保证一次请求内只刷新一次、行与计数读到同一状态。"""
    now = datetime.utcnow()
    changed = 0
    rows = sess.execute(select(Assignment).where(Assignment.status == "sent")).scalars().all()
    for a in rows:
        tokens = sess.execute(select(AssignmentToken)
                              .where(AssignmentToken.assignment_id == a.id)).scalars().all()
        if not tokens:
            continue  # 纯账号模式无 token，不自动过期
        live = any(t.used_at is None and t.expires_at and t.expires_at > now for t in tokens)
        if not live:
            a.status = "expired"
            changed += 1
    return changed


def list_assignments(status: Optional[str] = None, *,
                     advisor_name: Optional[str] = None,
                     student_id: Optional[int] = None,
                     limit: int = 500,
                     with_counts: bool = False):
    """任务列表（带学生与问卷信息）。advisor_name 给定时按归属过滤。

    ``with_counts=True`` 时返回 ``(rows, counts)``——一次过期刷新后在**同一事务**
    内取出列表与状态计数，避免同请求内状态翻转导致行数与计数不符。
    """
    with Session(engine) as sess:
        _refresh_expired(sess)
        stmt = (select(Assignment, _db.Student, Questionnaire)
                .join(_db.Student, Assignment.student_id == _db.Student.id)
                .join(Questionnaire, Assignment.questionnaire_id == Questionnaire.id)
                .order_by(Assignment.id.desc()).limit(int(limit)))
        if status:
            stmt = stmt.where(Assignment.status == status)
        if advisor_name is not None:
            stmt = stmt.where(_db.Student.advisor_name == advisor_name)
        if student_id is not None:
            stmt = stmt.where(Assignment.student_id == int(student_id))
        out = []
        for a, s, q in sess.execute(stmt).all():
            row = _a_row(a)
            row.update({"student_code": s.student_code or "", "student_name": s.name,
                        "advisor_name": s.advisor_name or "",
                        "questionnaire_code": q.code, "questionnaire_title": q.title})
            out.append(row)

        if not with_counts:
            sess.commit()
            return out

        cstmt = (select(Assignment.status, func.count())
                 .join(_db.Student, Assignment.student_id == _db.Student.id)
                 .group_by(Assignment.status))
        if advisor_name is not None:
            cstmt = cstmt.where(_db.Student.advisor_name == advisor_name)
        counts = {st: int(c) for st, c in sess.execute(cstmt).all()}
        sess.commit()
        return out, counts


def list_assignments_for_student(student_id: int) -> List[Dict[str, Any]]:
    """某学生的全部问卷任务（D 包档案页「问卷」tab 直接消费）。"""
    return list_assignments(student_id=student_id)


def assignment_status_counts(advisor_name: Optional[str] = None) -> Dict[str, int]:
    with Session(engine) as sess:
        _refresh_expired(sess)
        sess.commit()
        stmt = (select(Assignment.status, func.count())
                .join(_db.Student, Assignment.student_id == _db.Student.id)
                .group_by(Assignment.status))
        if advisor_name is not None:
            stmt = stmt.where(_db.Student.advisor_name == advisor_name)
        return {st: int(c) for st, c in sess.execute(stmt).all()}


# ─── token / 账号 ──────────────────────────────────────────────

def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_token(assignment_id: int, days: int = TOKEN_TTL_DAYS) -> str:
    """作废旧 token，签发新的一次性链接，返回**明文**（仅本次可见）。"""
    raw = secrets.token_urlsafe(24)
    with Session(engine) as sess:
        sess.execute(delete(AssignmentToken)
                     .where(AssignmentToken.assignment_id == int(assignment_id),
                            AssignmentToken.used_at.is_(None)))
        sess.execute(insert(AssignmentToken).values(
            assignment_id=int(assignment_id), token=_hash_token(raw),
            expires_at=datetime.utcnow() + timedelta(days=int(days))))
        sess.commit()
    return raw


def get_token_by_raw(raw: str) -> Optional[Dict[str, Any]]:
    with Session(engine) as sess:
        m = sess.execute(select(AssignmentToken)
                         .where(AssignmentToken.token == _hash_token(raw or ""))).scalars().first()
        if not m:
            return None
        return {"id": m.id, "assignment_id": m.assignment_id, "expires_at": _iso(m.expires_at),
                "used_at": _iso(m.used_at)}


def mark_token_used(token_id: int) -> None:
    with Session(engine) as sess:
        sess.execute(update(AssignmentToken).where(AssignmentToken.id == int(token_id))
                     .values(used_at=datetime.utcnow()))
        sess.commit()


def _default_username(student_code: str, student_id: int) -> str:
    return (student_code or "").strip() or f"y4{int(student_id):04d}"


def ensure_student_account(student_id: int) -> Dict[str, Any]:
    """确保该生有临时账号。新建时返回一次性明文密码。

    已存在则复用、**不重置密码**（如需新密码走 reset_student_password）。
    """
    with Session(engine) as sess:
        existing = sess.execute(select(StudentAccount)
                                .where(StudentAccount.student_id == int(student_id))).scalars().first()
        if existing:
            return {"account_id": existing.id, "username": existing.username,
                    "password": None, "created": False}
        st = sess.get(_db.Student, int(student_id))
        username = _default_username(st.student_code if st else "", student_id)
        # username 唯一：冲突时追加序号
        clash = sess.execute(select(StudentAccount)
                             .where(StudentAccount.username == username)).scalars().first()
        if clash:
            username = f"{username}-{int(student_id)}"
        password = secrets.token_urlsafe(8)
        res = sess.execute(insert(StudentAccount).values(
            student_id=int(student_id), username=username,
            password_hash=generate_password_hash(password), is_active=1))
        sess.commit()
        return {"account_id": res.lastrowid, "username": username,
                "password": password, "created": True}


def reset_student_password(student_id: int) -> Dict[str, Any]:
    with Session(engine) as sess:
        m = sess.execute(select(StudentAccount)
                         .where(StudentAccount.student_id == int(student_id))).scalars().first()
        if not m:
            return {"ok": False, "error": "该学生尚无账号"}
        password = secrets.token_urlsafe(8)
        m.password_hash = generate_password_hash(password)
        sess.commit()
        return {"ok": True, "username": m.username, "password": password}


def set_student_account_active(student_id: int, active: bool) -> bool:
    with Session(engine) as sess:
        res = sess.execute(update(StudentAccount).where(StudentAccount.student_id == int(student_id))
                           .values(is_active=1 if active else 0))
        sess.commit()
        return bool(res.rowcount)


def get_student_account(student_id: int) -> Optional[Dict[str, Any]]:
    with Session(engine) as sess:
        m = sess.execute(select(StudentAccount)
                         .where(StudentAccount.student_id == int(student_id))).scalars().first()
        if not m:
            return None
        return {"account_id": m.id, "student_id": m.student_id, "username": m.username,
                "is_active": int(m.is_active or 0), "created_at": _iso(m.created_at)}


def verify_student_login(username: str, password: str) -> Optional[Dict[str, Any]]:
    """学生端登录校验。成功返回 {account_id, student_id, username, student_name, student_code}。"""
    with Session(engine) as sess:
        m = sess.execute(select(StudentAccount)
                         .where(StudentAccount.username == (username or "").strip())).scalars().first()
        if not m or not int(m.is_active or 0):
            return None
        if not check_password_hash(m.password_hash, password or ""):
            return None
        st = sess.get(_db.Student, m.student_id)
        return {"account_id": m.id, "student_id": m.student_id, "username": m.username,
                "student_name": st.name if st else "", "student_code": st.student_code if st else ""}


# ─── 确认 / 分发 ───────────────────────────────────────────────

def confirm_assignment(aid: int, delivery: str, *, user_id: Optional[int] = None,
                       base_url: str = "", ttl_days: int = TOKEN_TTL_DAYS) -> Dict[str, Any]:
    """确认任务并分发。返回一次性明文（链接 / 初始密码）与可复制文本块。"""
    if delivery not in DELIVERIES:
        return {"ok": False, "error": f"delivery 必须是 {DELIVERIES} 之一"}
    a = get_assignment(aid)
    if not a:
        return {"ok": False, "error": "任务不存在"}
    if a["status"] not in ("pending", "expired"):
        return {"ok": False, "error": f"当前状态（{a['status']}）不可确认"}

    with Session(engine) as sess:
        sess.execute(update(Assignment).where(Assignment.id == int(aid)).values(
            status="sent", delivery=delivery,
            confirmed_by=user_id, confirmed_at=datetime.utcnow()))
        sess.commit()

    pkg = build_package(aid, delivery, base_url=base_url, ttl_days=ttl_days)
    pkg["ok"] = True
    return pkg


def build_package(aid: int, delivery: str, *, base_url: str = "",
                  ttl_days: int = TOKEN_TTL_DAYS) -> Dict[str, Any]:
    """生成分发文本块。链接明文与初始密码只在本次响应中出现。"""
    a = get_assignment(aid)
    if not a:
        return {"ok": False, "error": "任务不存在"}
    q = get_questionnaire(a["questionnaire_id"])
    student = _db.get_student(a["student_id"]) or {}
    base = (base_url or "").rstrip("/")

    out = {"assignment_id": aid, "questionnaire_title": (q or {}).get("title", ""),
           "student_name": student.get("name", ""), "student_code": student.get("student_code", ""),
           "delivery": delivery, "link_url": None, "account": None, "text": ""}
    lines = []

    if delivery in ("link", "both"):
        raw = issue_token(aid, days=ttl_days)
        out["link_url"] = f"{base}/q/{raw}" if base else f"/q/{raw}"
        lines.append(f"【{out['questionnaire_title']}】在线作答链接（7 天内有效，仅一次）：")
        lines.append(out["link_url"])

    if delivery in ("account", "both"):
        acc = ensure_student_account(a["student_id"])
        login_url = f"{base}/student/login" if base else "/student/login"
        out["account"] = {"username": acc["username"], "password": acc["password"],
                          "created": acc["created"], "login_url": login_url}
        if lines:
            lines.append("")
        lines.append("【学生账号】登录后在待办中作答：")
        lines.append(f"账号：{acc['username']}")
        if acc["created"]:
            lines.append(f"初始密码：{acc['password']}（仅本次显示）")
        else:
            lines.append("密码：沿用既有密码（如需重置请用「重置密码」）")
        lines.append(f"登录地址：{login_url}")

    out["text"] = "\n".join(lines)
    return out


def get_package(aid: int, base_url: str = "") -> Dict[str, Any]:
    """可复制的分发信息（**不含**链接明文与密码明文 —— 两者只在生成时出现一次）。"""
    a = get_assignment(aid)
    if not a:
        return {"ok": False, "error": "任务不存在"}
    q = get_questionnaire(a["questionnaire_id"])
    student = _db.get_student(a["student_id"]) or {}
    delivery = a.get("delivery") or ""
    base = (base_url or "").rstrip("/")
    acc = get_student_account(a["student_id"]) if delivery in ("account", "both") else None
    return {
        "ok": True,
        "assignment_id": aid,
        "delivery": delivery,
        "questionnaire_title": (q or {}).get("title", ""),
        "student_name": student.get("name", ""),
        "student_code": student.get("student_code", ""),
        "link_available": delivery in ("link", "both"),
        "account": {"username": acc["username"]} if acc else None,
        "login_url": f"{base}/student/login" if base else "/student/login",
        "note": "链接明文与初始密码仅在「确认发送 / 重新生成链接」时显示一次；"
                "需要链接请点「重新生成链接」，忘记密码请点「重置密码」。",
    }


def token_expiry_map(assignment_ids) -> Dict[int, Optional[str]]:
    """批量取各任务「未使用 token 的最晚过期时间」：``{assignment_id: iso|None}``。

    工作台「等待学生完成」队列展示链接有效期用（零 schema，只读聚合，避免 N+1）。
    """
    ids = [int(i) for i in (assignment_ids or [])]
    if not ids:
        return {}
    with Session(engine) as sess:
        rows = sess.execute(
            select(AssignmentToken.assignment_id, func.max(AssignmentToken.expires_at))
            .where(AssignmentToken.assignment_id.in_(ids),
                   AssignmentToken.used_at.is_(None))
            .group_by(AssignmentToken.assignment_id)).all()
    return {aid: _iso(exp) for aid, exp in rows}


def reject_assignment(aid: int) -> bool:
    with Session(engine) as sess:
        res = sess.execute(update(Assignment)
                           .where(Assignment.id == int(aid),
                                  Assignment.status.in_(ACTIVE_STATUSES))
                           .values(status="rejected"))
        sess.commit()
        return bool(res.rowcount)


def reissue_assignment(aid: int, *, base_url: str = "",
                       ttl_days: int = TOKEN_TTL_DAYS) -> Dict[str, Any]:
    """重新生成链接（expired / sent 均可）：作废旧链接 → 新链接 → sent。"""
    a = get_assignment(aid)
    if not a:
        return {"ok": False, "error": "任务不存在"}
    if a["status"] == "submitted":
        return {"ok": False, "error": "该任务已提交，无需重新生成"}
    with Session(engine) as sess:
        sess.execute(update(Assignment).where(Assignment.id == int(aid)).values(
            status="sent", delivery=(a.get("delivery") or "link"),
            confirmed_at=(a.get("confirmed_at") and datetime.fromisoformat(a["confirmed_at"]))
            or datetime.utcnow()))
        sess.commit()
    pkg = build_package(aid, a.get("delivery") or "link", base_url=base_url, ttl_days=ttl_days)
    pkg["ok"] = True
    return pkg


# ─── 提交 / 答案 / 草稿 ────────────────────────────────────────

def submit_response(aid: int, answers: Dict[str, Any], via: str) -> Dict[str, Any]:
    """写原始答案 + 置 submitted。重复提交拒绝。"""
    a = get_assignment(aid)
    if not a:
        return {"ok": False, "error": "任务不存在"}
    if a["status"] == "submitted":
        return {"ok": False, "error": "该问卷已提交，请勿重复提交"}
    if a["status"] not in ("sent", "pending"):
        return {"ok": False, "error": "该任务当前不可提交"}
    now = datetime.utcnow()
    with Session(engine) as sess:
        sess.execute(insert(Response).values(
            assignment_id=aid, student_id=a["student_id"],
            questionnaire_id=a["questionnaire_id"],
            answers_json=json.dumps(answers or {}, ensure_ascii=False),
            submitted_via=via))
        sess.execute(update(Assignment).where(Assignment.id == aid)
                     .values(status="submitted", submitted_at=now))
        sess.execute(delete(ResponseDraft).where(ResponseDraft.assignment_id == aid))
        sess.commit()
    return {"ok": True}


def get_response(aid: int) -> Optional[Dict[str, Any]]:
    with Session(engine) as sess:
        m = sess.execute(select(Response).where(Response.assignment_id == int(aid))
                         .order_by(Response.id.desc())).scalars().first()
        if not m:
            return None
        try:
            answers = json.loads(m.answers_json or "{}")
        except Exception:
            answers = {}
        return {"id": m.id, "assignment_id": m.assignment_id, "student_id": m.student_id,
                "questionnaire_id": m.questionnaire_id, "answers": answers,
                "submitted_via": m.submitted_via, "created_at": _iso(m.created_at)}


def save_draft(aid: int, answers: Dict[str, Any]) -> None:
    with Session(engine) as sess:
        existing = sess.execute(select(ResponseDraft)
                                .where(ResponseDraft.assignment_id == int(aid))).scalars().first()
        payload = json.dumps(answers or {}, ensure_ascii=False)
        if existing:
            existing.answers_json = payload
            existing.updated_at = datetime.utcnow()
        else:
            sess.execute(insert(ResponseDraft).values(assignment_id=int(aid), answers_json=payload))
        sess.commit()


def get_draft(aid: int) -> Dict[str, Any]:
    with Session(engine) as sess:
        m = sess.execute(select(ResponseDraft)
                         .where(ResponseDraft.assignment_id == int(aid))).scalars().first()
    if not m:
        return {"answers": {}, "updated_at": None}
    try:
        answers = json.loads(m.answers_json or "{}")
    except Exception:
        answers = {}
    return {"answers": answers, "updated_at": _iso(m.updated_at)}


# ─── 学生端：待办 / 已完成 ─────────────────────────────────────

def list_student_todos(student_id: int) -> List[Dict[str, Any]]:
    """账号模式下的待办问卷（delivery ∈ account/both 且 status='sent'）。"""
    refresh_expired()
    with Session(engine) as sess:
        stmt = (select(Assignment, Questionnaire)
                .join(Questionnaire, Assignment.questionnaire_id == Questionnaire.id)
                .where(Assignment.student_id == int(student_id),
                       Assignment.status == "sent",
                       Assignment.delivery.in_(("account", "both")))
                .order_by(Assignment.id))
        return [dict(_a_row(a), questionnaire_code=q.code, questionnaire_title=q.title,
                     question_count=len((json.loads(q.schema_json or "{}").get("questions") or [])))
                for a, q in sess.execute(stmt).all()]


def list_student_done(student_id: int) -> List[Dict[str, Any]]:
    with Session(engine) as sess:
        stmt = (select(Assignment, Questionnaire)
                .join(Questionnaire, Assignment.questionnaire_id == Questionnaire.id)
                .where(Assignment.student_id == int(student_id),
                       Assignment.status == "submitted")
                .order_by(Assignment.id.desc()))
        return [dict(_a_row(a), questionnaire_code=q.code, questionnaire_title=q.title)
                for a, q in sess.execute(stmt).all()]


# ─── 识别引擎输入装配（用既有「有效评价体系」补 eval_value）──────

def build_engine_items(schema_124: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """把 report 的 schema_124 转成引擎条目：``{code, label, value, eval_value}``。

    ``eval_value`` 由 ``evaluation_rules`` 的既有口径推导（含 068 相对常模 130
    的「偏低」判定），使规则可用 ``source="eval"`` 引用有效评价档位。
    """
    from evaluation_rules import (_code_int, _find_norm, derive_evaluation,
                                  is_hidden_raw, is_norm_item, is_order_item)
    src = [it for it in (schema_124 or []) if isinstance(it, dict)]
    items: List[Dict[str, Any]] = []
    for it in src:
        if is_hidden_raw(it):
            continue
        code = str(it.get("code") or "")
        label = it.get("label") or ""
        value = it.get("value")
        entry = {"code": code, "label": label, "value": value, "eval_value": None}
        if is_norm_item({"label": label}):
            pass                       # 常模参照值不参与评价
        elif is_order_item({"label": label}):
            entry["eval_value"] = value
        else:
            norm = _find_norm(src, _code_int(code))
            ev, _note = derive_evaluation(code, label, value, norm)
            entry["eval_value"] = ev
        items.append(entry)
    return items


def known_indicator_codes() -> set:
    from data_points import POINT_META
    return set(POINT_META.keys())


def schedule_for_student(student_id: int) -> List[Dict[str, Any]]:
    """试算：用该生最新报告的 schema_124 跑 published 规则，返回命中明细。"""
    rules = get_published_rules()
    reports = _db.get_student_reports(int(student_id))
    if not reports:
        return []
    rec = _db.get_report_raw(reports[0]["id"])
    if not rec:
        return []
    items = build_engine_items((rec.get("raw") or {}).get("schema_124") or [])
    from questionnaire_engine import evaluate
    return evaluate(items, rules)


def recognize_for_report(report_id: int) -> Dict[str, Any]:
    """报告落库后的识别钩子：published 规则求值 → 建 pending 任务。

    纯副作用函数，不依赖 Flask 请求上下文；异常由调用方 try/except 兜住。
    """
    rules = get_published_rules()
    if not rules:
        return {"skipped": "no_published_rules"}
    rec = _db.get_report_raw(int(report_id))
    if not rec:
        return {"skipped": "report_not_found"}
    items = build_engine_items((rec.get("raw") or {}).get("schema_124") or [])
    from questionnaire_engine import evaluate
    hits = evaluate(items, rules)
    created, reused, missing = [], [], []
    for h in hits:
        q = get_questionnaire_by_code(h["questionnaire_code"])
        if not q or not q.get("is_active"):
            missing.append(h["questionnaire_code"])
            continue
        aid, is_new = create_assignment(rec["student_id"], q["id"], source="auto",
                                        reason=h.get("reason", ""))
        (created if is_new else reused).append({"assignment_id": aid,
                                                "questionnaire_code": q["code"],
                                                "questionnaire_title": q["title"]})
    return {"hits": hits, "created": created, "reused": reused, "missing": missing}
