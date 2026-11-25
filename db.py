"""Database layer — SQLite (default) or PostgreSQL (via DATABASE_URL).

Usage:
    from db import init_db, add_student, add_report, get_students, ...

Set DATABASE_URL env var to use PostgreSQL (e.g. Neon):
    DATABASE_URL=postgresql://user:pass@host/dbname
"""

from __future__ import annotations

import os
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Date, DateTime,
    ForeignKey, Index, UniqueConstraint, select, insert, update, delete, func, event, inspect, text
)
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import declarative_base, Session

Base = declarative_base()

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "data" / "y4_students.db"

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_DB}")

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=connect_args)

# student_code 分配在并发下可能撞唯一索引，插入端做有限次重试（见 add_student 等）。
_CODE_ALLOC_RETRIES = 5

# SQLite 默认不校验 ForeignKey；显式开启后，引用完整性（含 ON DELETE 行为）才生效。
# 守卫：仅 SQLite 注册（PostgreSQL 由数据库自身强制，且不支持 PRAGMA 语法）。
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Student(Base):
    __tablename__ = "students"
    id = Column(Integer, primary_key=True, autoincrement=True)
    student_code = Column(String(20), unique=True, index=True)  # Y4-0001 格式唯一业务 ID
    name = Column(String(100), nullable=False)
    gender = Column(String(20))
    birthday = Column(String(50))
    grade = Column(String(50))
    email = Column(String(200))
    phone = Column(String(50))
    advisor_name = Column(String(100))
    school = Column(String(200))
    single_parent = Column(String(10), default="false")
    created_at = Column(DateTime, default=datetime.utcnow)


class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    report_date = Column(Date, nullable=False)
    pdf_path = Column(String(500), nullable=False)
    data_json = Column(Text, nullable=False)
    interpretation = Column(Text)  # AI 解读结果
    created_at = Column(DateTime, default=datetime.utcnow)


class MeetingMinutes(Base):
    __tablename__ = "meeting_minutes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=True)
    transcript_text = Column(Text)  # 原始逐字稿
    minutes_text = Column(Text)     # AI 生成的会议纪要（渲染后的 Markdown）
    minutes_json = Column(Text, nullable=True)  # 结构化纪要 JSON（内部中间层，minutes-v1）
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Location(Base):
    """预约办公室（上海/北京/深圳）。updated_at 在该办公室的预约或开放时段变化时刷新。"""
    __tablename__ = "locations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    assessor_label = Column(String(100), nullable=True)
    active = Column(Integer, default=1)
    sort = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    student_name = Column(String(100), nullable=False)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=True)
    student_email = Column(String(200))
    student_phone = Column(String(50))
    appointment_time = Column(DateTime, nullable=False)
    status = Column(String(20), default="pending")
    notes = Column(Text)
    advisor_name = Column(String(100))
    school = Column(String(200))
    single_parent = Column(String(10), default="false")
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Task C：预约来源、经办人、测评师分配与邀请链接
    source = Column(String(30), nullable=True)
    requester_name = Column(String(100), nullable=True)
    created_by = Column(Integer, nullable=True)
    assessor_id = Column(Integer, nullable=True)
    assigned_at = Column(DateTime, nullable=True)
    invite_token = Column(String(255), nullable=True)
    staff_request_id = Column(String(36), nullable=True)
    __table_args__ = (
        Index("ux_booking_invite", "invite_token", unique=True),
        Index("ux_booking_staff_request", "created_by", "staff_request_id", unique=True),
    )


class PartnerStudent(Base):
    __tablename__ = "partner_students"
    partner_id = Column(String(128), primary_key=True)
    external_student_id = Column(String(128), primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="SET NULL"),
                        nullable=True, index=True)


class PartnerReservation(Base):
    __tablename__ = "partner_reservations"
    id = Column(String(36), primary_key=True)
    partner_id = Column(String(128), nullable=False)
    external_reservation_id = Column(String(128), nullable=False)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="SET NULL"),
                        nullable=True, unique=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="SET NULL"),
                        nullable=True, index=True)
    request_digest = Column(String(64), nullable=False)
    location_id = Column(Integer, nullable=False)
    appointment_time = Column(DateTime, nullable=False)
    confirmed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("partner_id", "external_reservation_id"),)


class AssessorAvailability(Base):
    """测评师自己维护的可约时段；无记录时沿用办公室开放状态。"""
    __tablename__ = "assessor_availability"
    id = Column(Integer, primary_key=True, autoincrement=True)
    assessor_id = Column(Integer, nullable=False, index=True)
    location_id = Column(Integer, nullable=True)
    date = Column(Date, nullable=False)
    time_slot = Column(String(10), nullable=False)
    is_available = Column(Integer, default=1)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserOffice(Base):
    """Task H：账号被授权的办公室（多办公室）。users.office_id 保留为主办公室。"""
    __tablename__ = "user_offices"
    user_id = Column(Integer, primary_key=True)
    office_id = Column(Integer, primary_key=True)
    is_default = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class AssessorOfficeSetting(Base):
    """保留历史授权来源及默认测评师配置标记。"""
    __tablename__ = "assessor_office_settings"
    assessor_id = Column(Integer, primary_key=True)
    office_id = Column(Integer, primary_key=True)
    mode = Column(String(16), nullable=False, default="explicit")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OfficeDefaultAssessor(Base):
    """Task K：办公室的默认测评师（显式按稳定用户 ID 配置，不按姓名或角色推断）。"""
    __tablename__ = "office_default_assessors"
    office_id = Column(Integer, primary_key=True)
    assessor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Availability(Base):
    __tablename__ = "availability"
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    time_slot = Column(String(10), nullable=False)
    is_available = Column(Integer, default=1)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class E4Mapping(Base):
    """Y4→E4 映射指认：由用户在界面逐条指认，非推断。

    一个 Y4 指标可同时映射到多个 E4 维度（复合主键 code+e4_dim）。
    e4_sub 为可选子类别（可空）。
    """
    __tablename__ = "e4_mapping"
    code = Column(String(20), primary_key=True)    # Y4 指标编号，如 "015"
    e4_dim = Column(String(4), primary_key=True)   # E1/E2/E3/E4
    e4_sub = Column(String(50), nullable=True)     # 子类别（可选）
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SixAmProfile(Base):
    """6 A.M. 六维启动档案：每次重跑插入新行（version 递增），不覆盖旧行。"""
    __tablename__ = "six_am_profiles"
    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    profile_json = Column(Text, nullable=False)
    version = Column(Integer, nullable=False, default=1)   # 该学生档案版本号，递增
    created_at = Column(DateTime, default=datetime.utcnow)


class SixAmRuleVersion(Base):
    """6 A.M. 规则版本：params_json = {"params": {...}, "rule_overrides": {...}}。

    status: draft（可多个）/ published（至多 1 个）/ archived。
    """
    __tablename__ = "six_am_rule_versions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    label = Column(String(100), nullable=False)            # 如 "draft-20261013-1"
    status = Column(String(20), nullable=False, default="draft")
    params_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime)


class SixAmReview(Base):
    """6AM 团队评议：对某一档案的单个维度记录结论（只追加，不覆盖旧行）。

    verdict: agree / adjust / evidence；adjust 时 adjusted_state 记录团队状态。
    评议不改变模型判定，也不产生新档案版本。
    """
    __tablename__ = "six_am_reviews"
    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("six_am_profiles.id"), nullable=False)
    report_id = Column(Integer, nullable=False)
    dim = Column(String(4), nullable=False)
    verdict = Column(String(16), nullable=False)
    adjusted_state = Column(String(16))
    note = Column(Text)
    owner = Column(String(50))
    due_date = Column(String(10))
    author = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)


class User(Base):
    """平台用户（Admin / Advisor / Viewer 三角色）。

    role: 'admin' / 'advisor' / 'viewer'；role=advisor 时 advisor_name 关联
    students.advisor_name 用于数据隔离。密码存 werkzeug 哈希。
    """
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="viewer")
    advisor_name = Column(String(100))
    display_name = Column(String(100))
    email = Column(String(255), nullable=True)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    # 账号可见范围（管理员设置）；空值/NULL 表示使用角色默认值，见 effective_account_settings
    student_scope = Column(String(10), default="")
    detail_level = Column(String(10), default="")
    m1_access = Column(Integer, nullable=True)
    # 心有灵析管理（仅 advisor 有意义；生效值见 effective_account_settings）
    m1_admin = Column(Integer, nullable=True)
    # Task C：测评师身份与所属办公室（前台账号也用 office_id 限定接待范围）
    is_assessor = Column(Integer, nullable=False, default=0)
    office_id = Column(Integer, nullable=True)


def init_db() -> None:
    """Create tables if they don't exist, and run migrations."""
    # 2.0 问卷子系统（Agent C）的 7 张表定义在 questionnaire_store，
    # 需在 create_all 之前 import 以完成 ORM 注册（SQLite 与 PG 通用，
    # 不使用 _migrate_schema 那种 SQLite-only 的原生 DDL）。
    try:
        import questionnaire_store  # noqa: F401
    except Exception as e:  # 问卷子系统导入失败不应阻断既有功能
        print(f"[DB] 问卷子系统模型注册失败 (非致命): {e}")
    try:
        import growth_talk_store  # noqa: F401
    except Exception as e:  # Growth Talk 子系统导入失败不应阻断既有功能
        print(f"[DB] Growth Talk 模型注册失败 (非致命): {e}")
    # M1 会前准备的 3 张表（m1_preps / m1_sources / m1_versions）同样要在
    # create_all 之前注册；init_db 在蓝图导入之前运行，否则全新库里不会建表。
    try:
        import m1.store  # noqa: F401
    except Exception as e:  # M1 导入失败不应阻断既有功能
        print(f"[DB] M1 模型注册失败 (非致命): {e}")
    # Y4 单文件上传的任务队列表 y4_jobs，同样要在 create_all 之前注册。
    try:
        import y4_upload  # noqa: F401
    except Exception as e:  # 导入失败不应阻断既有功能
        print(f"[DB] Y4 上传模型注册失败 (非致命): {e}")
    import m1.plan_store as _plan_store
    _plan_store.ensure_tables(engine)
    Base.metadata.create_all(engine)
    try:
        import y4_upload as _y4u
        _y4u.ensure_schema()
    except Exception as e:
        print(f"[DB] y4_jobs 补列失败 (非致命): {e}")
    _migrate_schema()
    try:
        _ensure_ops_schema()
    except Exception as e:
        print(f"[DB] 预约/测评师字段补列失败 (非致命): {e}")
    try:
        _ensure_task_h_schema()
    except Exception as e:
        print(f"[DB] 多办公室/排班迁移失败 (非致命): {e}")
    try:
        _ensure_task_k_schema()
    except Exception as e:
        print(f"[DB] 办公室默认测评师迁移失败 (非致命): {e}")
    try:
        ensure_locations()
    except Exception as e:
        print(f"[DB] 办公室初始化失败 (非致命): {e}")
    try:
        import questionnaire_store as _qstore
        _qstore.ensure_indexes()
    except Exception as e:
        print(f"[DB] 问卷部分唯一索引创建失败 (非致命): {e}")
    try:
        import questionnaire_store as _qstore
        _qstore.backfill_scores()
    except Exception as e:
        print(f"[DB] 问卷分数补算失败 (非致命): {e}")
    try:
        import growth_talk_store as _gtstore
        _gtstore.ensure_indexes()
    except Exception as e:
        print(f"[DB] First Touch 部分唯一索引创建失败 (非致命，可能仍有重复会谈): {e}")


def _migrate_schema() -> None:
    """Add new columns/tables for schema evolution."""
    import sqlite3
    if not DATABASE_URL.startswith("sqlite"):
        return
    # 以实际配置的 DATABASE_URL 为准（默认即 DEFAULT_DB），避免测试/多库场景误迁移
    db_path = DATABASE_URL.split("sqlite:///", 1)[-1]
    if not Path(db_path).exists():
        return
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check existing columns in bookings table
    cursor.execute("PRAGMA table_info(bookings)")
    existing_cols = {row[1] for row in cursor.fetchall()}

    migrations = [
        ("advisor_name", "ALTER TABLE bookings ADD COLUMN advisor_name VARCHAR(100) DEFAULT ''"),
        ("school", "ALTER TABLE bookings ADD COLUMN school VARCHAR(200) DEFAULT ''"),
        ("single_parent", "ALTER TABLE bookings ADD COLUMN single_parent VARCHAR(10) DEFAULT 'false'"),
        ("student_id", "ALTER TABLE bookings ADD COLUMN student_id INTEGER"),
        ("location_id", "ALTER TABLE bookings ADD COLUMN location_id INTEGER"),
    ]
    for col_name, sql in migrations:
        if col_name not in existing_cols:
            try:
                cursor.execute(sql)
                conn.commit()
            except Exception:
                pass

    # availability.location_id（预约办公室）
    cursor.execute("PRAGMA table_info(availability)")
    avail_cols = {row[1] for row in cursor.fetchall()}
    if avail_cols and "location_id" not in avail_cols:
        try:
            cursor.execute("ALTER TABLE availability ADD COLUMN location_id INTEGER")
            conn.commit()
        except Exception:
            pass

    # Check existing columns in students table
    cursor.execute("PRAGMA table_info(students)")
    student_cols = {row[1] for row in cursor.fetchall()}
    student_migrations = [
        ("advisor_name", "ALTER TABLE students ADD COLUMN advisor_name VARCHAR(100) DEFAULT ''"),
        ("school", "ALTER TABLE students ADD COLUMN school VARCHAR(200) DEFAULT ''"),
        ("single_parent", "ALTER TABLE students ADD COLUMN single_parent VARCHAR(10) DEFAULT 'false'"),
        # student_code：先加普通列（SQLite ALTER TABLE 不支持加 UNIQUE），唯一性用索引实现
        ("student_code", "ALTER TABLE students ADD COLUMN student_code VARCHAR(20)"),
    ]
    for col_name, sql in student_migrations:
        if col_name not in student_cols:
            try:
                cursor.execute(sql)
                conn.commit()
            except Exception:
                pass

    # student_code 唯一索引（NULL 可重复，回填由迁移脚本负责）
    # 名称与 ORM 的 index=True 保持一致，避免重复索引
    try:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_students_student_code ON students(student_code)")
        conn.commit()
    except Exception:
        pass

    # Check existing columns in reports table
    cursor.execute("PRAGMA table_info(reports)")
    report_cols = {row[1] for row in cursor.fetchall()}
    report_migrations = [
        ("interpretation", "ALTER TABLE reports ADD COLUMN interpretation TEXT"),
    ]
    for col_name, sql in report_migrations:
        if col_name not in report_cols:
            try:
                cursor.execute(sql)
                conn.commit()
            except Exception:
                pass

    # Check if meeting_minutes table exists; if not create
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='meeting_minutes'")
    if not cursor.fetchone():
        try:
            cursor.execute("""
                CREATE TABLE meeting_minutes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL,
                    report_id INTEGER,
                    transcript_text TEXT,
                    minutes_text TEXT,
                    minutes_json TEXT,
                    created_at DATETIME,
                    updated_at DATETIME,
                    FOREIGN KEY (student_id) REFERENCES students(id),
                    FOREIGN KEY (report_id) REFERENCES reports(id)
                )
            """)
            conn.commit()
        except Exception:
            pass

    # meeting_minutes: add minutes_json for existing databases
    cursor.execute("PRAGMA table_info(meeting_minutes)")
    mm_cols = {row[1] for row in cursor.fetchall()}
    if "minutes_json" not in mm_cols:
        try:
            cursor.execute("ALTER TABLE meeting_minutes ADD COLUMN minutes_json TEXT")
            conn.commit()
        except Exception:
            pass

    # Check if e4_mapping table exists; if not create (multi-dim: code+e4_dim composite PK)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='e4_mapping'")
    if not cursor.fetchone():
        try:
            cursor.execute("""
                CREATE TABLE e4_mapping (
                    code VARCHAR(20) NOT NULL,
                    e4_dim VARCHAR(4) NOT NULL,
                    e4_sub VARCHAR(50),
                    updated_at DATETIME,
                    PRIMARY KEY (code, e4_dim)
                )
            """)
            conn.commit()
        except Exception:
            pass
    else:
        # Migrate old single-PK table to composite-PK if needed
        cursor.execute("PRAGMA table_info(e4_mapping)")
        cols = {row[1]: row for row in cursor.fetchall()}
        # Check if e4_dim is part of PK (old schema has code as sole PK)
        pk_info = [row for row in cursor.execute("PRAGMA table_info(e4_mapping)").fetchall() if row[5]]
        if len(pk_info) == 1 and pk_info[0][1] == "code":
            # Old single-PK schema: migrate to composite
            try:
                cursor.execute("CREATE TABLE e4_mapping_new (code VARCHAR(20) NOT NULL, e4_dim VARCHAR(4) NOT NULL, e4_sub VARCHAR(50), updated_at DATETIME, PRIMARY KEY (code, e4_dim))")
                cursor.execute("INSERT OR IGNORE INTO e4_mapping_new (code, e4_dim, e4_sub, updated_at) SELECT code, e4_dim, e4_sub, updated_at FROM e4_mapping")
                cursor.execute("DROP TABLE e4_mapping")
                cursor.execute("ALTER TABLE e4_mapping_new RENAME TO e4_mapping")
                conn.commit()
            except Exception:
                try: conn.rollback()
                except Exception: pass

    # Check if six_am_profiles / six_am_rule_versions tables exist; if not create
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='six_am_profiles'")
    if not cursor.fetchone():
        try:
            cursor.execute("""
                CREATE TABLE six_am_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL,
                    report_id INTEGER NOT NULL,
                    profile_json TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME,
                    FOREIGN KEY (student_id) REFERENCES students(id),
                    FOREIGN KEY (report_id) REFERENCES reports(id)
                )
            """)
            conn.commit()
        except Exception:
            pass

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='six_am_rule_versions'")
    if not cursor.fetchone():
        try:
            cursor.execute("""
                CREATE TABLE six_am_rule_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label VARCHAR(100) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'draft',
                    params_json TEXT NOT NULL,
                    created_at DATETIME,
                    published_at DATETIME
                )
            """)
            conn.commit()
        except Exception:
            pass

    # Check if users table exists; if not create (2.0 角色体系)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not cursor.fetchone():
        try:
            cursor.execute("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username VARCHAR(100) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    role VARCHAR(20) NOT NULL DEFAULT 'viewer',
                    advisor_name VARCHAR(100),
                    display_name VARCHAR(100),
                    email VARCHAR(255),
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME
                )
            """)
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)")
            conn.commit()
        except Exception:
            pass

    # users.email（First Touch 账号合并）：存量库幂等补齐
    cursor.execute("PRAGMA table_info(users)")
    user_cols = {row[1] for row in cursor.fetchall()}
    if "email" not in user_cols:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN email VARCHAR(255)")
            conn.commit()
        except Exception:
            pass

    # users 可见范围三列（管理员设置账号可见性）：存量库幂等补齐
    for col, ddl in (("student_scope", "VARCHAR(10) DEFAULT ''"),
                     ("detail_level", "VARCHAR(10) DEFAULT ''"),
                     ("m1_access", "INTEGER"),
                     ("m1_admin", "INTEGER")):
        if col not in user_cols:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
                conn.commit()
            except Exception:
                pass

    conn.close()


def _ensure_ops_schema() -> None:
    """跨 SQLite/PostgreSQL 幂等补齐 Task C 字段与唯一索引。"""
    insp = inspect(engine)
    tables = set(insp.get_table_names())

    def add_columns(table: str, columns) -> None:
        if table not in tables:
            return
        existing = {c["name"] for c in insp.get_columns(table)}
        with engine.begin() as conn:
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))

    add_columns("bookings", [
        ("source", "VARCHAR(30)"),
        ("requester_name", "VARCHAR(100)"),
        ("created_by", "INTEGER"),
        ("assessor_id", "INTEGER"),
        ("assigned_at", "TIMESTAMP"),
        ("invite_token", "VARCHAR(255)"),
        ("staff_request_id", "VARCHAR(36)"),
    ])
    add_columns("users", [
        ("is_assessor", "INTEGER NOT NULL DEFAULT 0"),
        ("office_id", "INTEGER"),
    ])
    with engine.begin() as conn:
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_booking_invite ON bookings (invite_token)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_booking_staff_request "
                          "ON bookings (created_by, staff_request_id)"))
        # 同一测评师同一时刻只能接待一个预约；已取消的预约不占用。
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_booking_assessor_slot "
            "ON bookings (assessor_id, appointment_time) "
            "WHERE assessor_id IS NOT NULL AND status != 'cancelled'"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_assessor_availability_slot "
            "ON assessor_availability (assessor_id, location_id, date, time_slot)"))


def _ensure_task_h_schema() -> None:
    """Task H 幂等迁移：多办公室授权、排班起点标记、按办公室唯一的可约记录。

    可重复执行；旧单办公室账号回填成一条授权，原 office_id 仍为主办公室。
    """
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    if "user_offices" not in tables:
        UserOffice.__table__.create(bind=engine)
    if "assessor_office_settings" not in tables:
        AssessorOfficeSetting.__table__.create(bind=engine)

    with Session(engine) as sess:
        users = sess.execute(select(User.id, User.office_id, User.is_assessor)).all()
        existing = {(r[0], r[1]) for r in sess.execute(
            select(UserOffice.user_id, UserOffice.office_id)).all()}
        for uid, office_id, is_assessor in users:
            if office_id in (None, ""):
                continue
            office_id = int(office_id)
            if (uid, office_id) not in existing:
                sess.add(UserOffice(user_id=uid, office_id=office_id, is_default=1))
            if int(is_assessor or 0):
                exists = sess.get(AssessorOfficeSetting, (uid, office_id))
                if not exists:
                    # 原单办公室账号延续旧规则；新办公室在授权时另写 explicit。
                    sess.add(AssessorOfficeSetting(
                        assessor_id=uid, office_id=office_id, mode="legacy"))
        sess.commit()

        # 旧可约记录的 location_id 为空时回填到该账号的主办公室，避免跨办公室互相覆盖。
        users_by_id = {uid: office_id for uid, office_id, _ in users if office_id not in (None, "")}
        legacy_rows = sess.execute(
            select(AssessorAvailability).where(AssessorAvailability.location_id.is_(None))
        ).scalars().all()
        for row in legacy_rows:
            office_id = users_by_id.get(row.assessor_id)
            if office_id not in (None, ""):
                row.location_id = int(office_id)
        sess.commit()

    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ux_assessor_availability_slot"))
        conn.execute(text(
            "CREATE UNIQUE INDEX ux_assessor_availability_slot "
            "ON assessor_availability (assessor_id, location_id, date, time_slot)"))


def _ensure_task_k_schema() -> None:
    """Task K 幂等迁移：办公室默认测评师表（按稳定用户 ID 配置）。"""
    insp = inspect(engine)
    if "office_default_assessors" not in set(insp.get_table_names()):
        OfficeDefaultAssessor.__table__.create(bind=engine)


# ─── Student CRUD ───────────────────────────────────────────────

def next_student_code(sess=None) -> str:
    """分配下一个学生业务 ID（`Y4-0001` 起）。

    基于现有 code 的最大序号 +1。``sess`` 非空时复用调用方事务（事务内 SELECT MAX + 1）；
    否则自开 Session。并发下由 ``student_code`` 唯一索引兜底。
    """
    def _calc(s) -> str:
        rows = s.execute(select(Student.student_code)).all()
        max_n = 0
        for (c,) in rows:
            if c and str(c).startswith("Y4-"):
                try:
                    max_n = max(max_n, int(str(c)[3:]))
                except ValueError:
                    pass
        return f"Y4-{max_n + 1:04d}"

    if sess is not None:
        return _calc(sess)
    with Session(engine) as s:
        return _calc(s)


def create_student(name: str, grade: str = "", school: str = "",
                   phone: str = "", advisor_name: str = "") -> int:
    """Create a student without de-duplicating. Returns student id.

    与 ``add_student`` / ``find_or_create_student`` 一样按 ``next_student_code``
    分配 ``Y4-XXXX`` 编号，并在并发撞唯一索引时有限次重试。
    """
    name = (name or "").strip()
    for attempt in range(_CODE_ALLOC_RETRIES):
        with Session(engine) as sess:
            try:
                stmt = insert(Student).values(
                    student_code=next_student_code(sess),
                    name=name, grade=grade, school=school,
                    phone=phone, advisor_name=advisor_name,
                )
                result = sess.execute(stmt)
                sess.commit()
                return result.lastrowid
            except IntegrityError:
                sess.rollback()
                if attempt == _CODE_ALLOC_RETRIES - 1:
                    raise


def add_student(name: str, gender: str = "", birthday: str = "",
                grade: str = "", email: str = "", phone: str = "") -> int:
    """Create a student record. Returns student id."""
    for attempt in range(_CODE_ALLOC_RETRIES):
        with Session(engine) as sess:
            try:
                stmt = insert(Student).values(
                    student_code=next_student_code(sess),
                    name=name, gender=gender, birthday=birthday,
                    grade=grade, email=email, phone=phone,
                )
                result = sess.execute(stmt)
                sess.commit()
                return result.lastrowid
            except IntegrityError:
                # 并发下 student_code 撞唯一索引：回滚后重新分配并重试
                sess.rollback()
                if attempt == _CODE_ALLOC_RETRIES - 1:
                    raise


def find_or_create_student(name: str, gender: str = "", birthday: str = "",
                           grade: str = "", email: str = "", phone: str = "",
                           advisor_name: str = "", school: str = "",
                           single_parent: str = "false") -> int:
    """Find student by (name, birthday), or create one. Returns student id.

    匹配规则：优先 (name, birthday)；birthday 为空时退化为纯姓名匹配；同名不同生日创建新学生。
    若命中历史数据中同名但生日为空的记录，则补录生日（避免同名重复建档）。
    命中后更新 advisor/school/single_parent 字段。
    """
    name = (name or "").strip()
    birthday = (birthday or "").strip()
    with Session(engine) as sess:
        row = None
        if birthday:
            row = sess.execute(
                select(Student).where(Student.name == name, Student.birthday == birthday)
            ).first()
            if not row:
                # 兼容历史：同名但生日为空的记录视为同一人
                row = sess.execute(
                    select(Student).where(
                        Student.name == name,
                        (Student.birthday == "") | (Student.birthday.is_(None)),
                    )
                ).first()
        else:
            row = sess.execute(select(Student).where(Student.name == name)).first()
        if row:
            student = row[0]
            # Update booking-related fields if provided
            update_values = {}
            # 顾问：仅当现值为空时才回填（预约/手动填过的不被 OCR 覆盖）
            if advisor_name and not (student.advisor_name or "").strip():
                update_values["advisor_name"] = advisor_name
            if school:
                update_values["school"] = school
            if single_parent and single_parent != "false":
                update_values["single_parent"] = single_parent
            # 历史记录补录生日（仅当原值为空）
            if birthday and not (student.birthday or "").strip():
                update_values["birthday"] = birthday
            if update_values:
                sess.execute(update(Student).where(Student.id == student.id).values(**update_values))
                sess.commit()
            return student.id
    # Create new student
    for attempt in range(_CODE_ALLOC_RETRIES):
        with Session(engine) as sess:
            try:
                stmt = insert(Student).values(
                    student_code=next_student_code(sess),
                    name=name, gender=gender, birthday=birthday,
                    grade=grade, email=email, phone=phone,
                    advisor_name=advisor_name, school=school, single_parent=single_parent,
                )
                result = sess.execute(stmt)
                sess.commit()
                return result.lastrowid
            except IntegrityError:
                # 并发下 student_code 撞唯一索引：回滚后重新分配并重试
                sess.rollback()
                if attempt == _CODE_ALLOC_RETRIES - 1:
                    raise


def get_students(advisor_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """List students with report counts, minutes count, and latest report date.

    ``advisor_name`` 非 None 时仅返回该顾问名下学生（advisor 数据隔离）。
    """
    with Session(engine) as sess:
        stmt = select(Student).order_by(Student.created_at.desc())
        if advisor_name is not None:
            stmt = stmt.where(Student.advisor_name == advisor_name)
        rows = sess.execute(stmt).all()
        results = []
        for row in rows:
            student = row[0]
            count_stmt = select(func.count(Report.id)).where(Report.student_id == student.id)
            report_count = sess.execute(count_stmt).scalar() or 0
            minutes_count_stmt = select(func.count(MeetingMinutes.id)).where(MeetingMinutes.student_id == student.id)
            minutes_count = sess.execute(minutes_count_stmt).scalar() or 0
            latest_stmt = select(Report).where(Report.student_id == student.id).order_by(Report.created_at.desc()).limit(1)
            latest_row = sess.execute(latest_stmt).first()
            latest_report_date = latest_row[0].report_date.isoformat() if latest_row and latest_row[0].report_date else None
            results.append({
                "id": student.id,
                "student_code": student.student_code or "",
                "name": student.name,
                "gender": student.gender,
                "grade": student.grade,
                "email": student.email,
                "phone": student.phone,
                "advisor_name": student.advisor_name or "",
                "school": student.school or "",
                "single_parent": student.single_parent or "false",
                "created_at": student.created_at.isoformat() if student.created_at else None,
                "report_count": report_count,
                "minutes_count": minutes_count,
                "latest_report_date": latest_report_date,
            })
        return results


def get_student(student_id: int) -> Optional[Dict[str, Any]]:
    """按 id 取学生基本信息（用于 advisor 归属校验等）。不存在返回 None。"""
    with Session(engine) as sess:
        row = sess.execute(select(Student).where(Student.id == int(student_id))).first()
        if not row:
            return None
        s = row[0]
        return {
            "id": s.id,
            "student_code": s.student_code or "",
            "name": s.name,
            "advisor_name": s.advisor_name or "",
            "school": s.school or "",
        }


def get_student_by_code(code: str) -> Optional[Dict[str, Any]]:
    """按 student_code 取学生完整档案（360° 档案页页头用）。不存在返回 None。"""
    with Session(engine) as sess:
        row = sess.execute(
            select(Student).where(Student.student_code == str(code))).first()
        if not row:
            return None
        s = row[0]
        return {
            "id": s.id,
            "student_code": s.student_code or "",
            "name": s.name,
            "gender": s.gender or "",
            "birthday": s.birthday or "",
            "grade": s.grade or "",
            "email": s.email or "",
            "phone": s.phone or "",
            "advisor_name": s.advisor_name or "",
            "school": s.school or "",
            "single_parent": s.single_parent or "false",
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }


def get_latest_report_raw(student_id: int) -> Optional[Dict[str, Any]]:
    """最新一条报告的 data_json（360° 档案页「画像」tab 分组渲染用）；无报告返回 None。"""
    with Session(engine) as sess:
        stmt = (select(Report).where(Report.student_id == int(student_id))
                .order_by(Report.created_at.desc(), Report.id.desc()).limit(1))
        row = sess.execute(stmt).first()
        if not row:
            return None
        r = row[0]
        try:
            raw = json.loads(r.data_json) if r.data_json else {}
        except Exception:
            raw = {}
        return {
            "report_id": r.id,
            "report_date": r.report_date.isoformat() if r.report_date else None,
            "data": raw,
        }


def get_report_student_id(report_id: int) -> Optional[int]:
    """取报告所属学生 id；报告不存在返回 None。"""
    with Session(engine) as sess:
        row = sess.execute(select(Report.student_id).where(Report.id == int(report_id))).first()
        return row[0] if row else None


# ─── Report CRUD ────────────────────────────────────────────────

def add_report(student_id: int, report_date: date, pdf_path: str,
               data_json: str) -> int:
    """Save a report record. Returns report id."""
    with Session(engine) as sess:
        stmt = insert(Report).values(
            student_id=student_id,
            report_date=report_date,
            pdf_path=pdf_path,
            data_json=data_json,
        )
        result = sess.execute(stmt)
        sess.commit()
        return result.lastrowid


def get_student_reports(student_id: int) -> List[Dict[str, Any]]:
    """Get all reports for a student."""
    with Session(engine) as sess:
        stmt = select(Report).where(Report.student_id == student_id).order_by(Report.created_at.desc())
        rows = sess.execute(stmt).all()
        return [{
            "id": row[0].id,
            "report_date": row[0].report_date.isoformat() if row[0].report_date else None,
            "pdf_path": row[0].pdf_path,
            "created_at": row[0].created_at.isoformat() if row[0].created_at else None,
            "interpretation": row[0].interpretation,
        } for row in rows]


def save_interpretation(report_id: int, content: str) -> None:
    """Save (or overwrite) the AI interpretation text for a report."""
    with Session(engine) as sess:
        stmt = update(Report).where(Report.id == report_id).values(interpretation=content)
        sess.execute(stmt)
        sess.commit()


def get_report_raw(report_id: int) -> Optional[Dict[str, Any]]:
    """Get the full raw data_json of a report (for later reuse, e.g. AI re-interpretation)."""
    with Session(engine) as sess:
        stmt = select(Report, Student).join(Student).where(Report.id == report_id)
        row = sess.execute(stmt).first()
        if not row:
            return None
        report, student = row
        raw = json.loads(report.data_json) if report.data_json else {}
        return {
            "report_id": report.id,
            "student_id": student.id,
            "student_name": student.name,
            "grade": student.grade,
            "report_date": report.report_date.isoformat() if report.report_date else None,
            "interpretation": report.interpretation or "",
            "raw": raw,
        }


def report_snapshot_with_student_name(raw: Dict[str, Any], student_name: Optional[str]) -> Dict[str, Any]:
    """Use the profile name for rendering without rewriting the stored report snapshot."""
    name = (student_name or "").strip()
    if not name:
        return raw
    return {**raw, "student": {**(raw.get("student") or {}), "name": name}}


_B3D_STRING_CODES = ("motivation_type", "method_type")
_B3D_LIST_KEYS = ("practice_dims", "practice_items", "exec_dims", "exec_items")


def _parse_b3d_code(code: str) -> Tuple[str, Optional[int]]:
    """``b3d.motivation_type`` → (键, None)；``b3d.exec_items.3`` → (键, 3)。"""
    parts = code.split(".")
    if len(parts) == 2 and parts[1] in _B3D_STRING_CODES:
        return parts[1], None
    if len(parts) == 3 and parts[1] in _B3D_LIST_KEYS and parts[2].isdigit():
        return parts[1], int(parts[2])
    raise ValueError(f"未知编号 {code}")


def _check_b3d_edit(detail: Any, code: str, text: str) -> None:
    key, idx = _parse_b3d_code(code)
    if not isinstance(detail, dict):
        raise ValueError(f"报告没有 B3 明细，不能修改 {code}")
    if idx is None:
        return
    rows = detail.get(key)
    if not isinstance(rows, list) or idx >= len(rows) or not isinstance(rows[idx], dict):
        raise ValueError(f"未知编号 {code}")
    if text != "":
        try:
            num = float(text)
        except ValueError:
            num = None
        if num is None or not math.isfinite(num):
            raise ValueError(f"编号 {code} 需要数值，收到「{text}」")


def _apply_b3d_edit(detail: Dict[str, Any], code: str, text: str) -> Optional[str]:
    """写入一条 b3d.* 修改；返回旧值文本，值没变返回 None。"""
    key, idx = _parse_b3d_code(code)
    if idx is None:
        old = detail.get(key)
        old_text = "" if old is None else str(old)
        if old_text == text:
            return None
        detail[key] = text
        return old_text
    row = detail[key][idx]
    old = row.get("score")
    new = None if text == "" else float(text)
    if old == new:
        return None
    row["score"] = new
    return "" if old is None else f"{old:g}"


def update_report_values(report_id: int, edits: Dict[str, str],
                         editor: str) -> Dict[str, Any]:
    """把手工修改写入报告快照（``data_json`` → ``schema_124[].value``）。

    整批校验通过后才落库：未知编号、编号不允许编辑、数值项写了非数值，都会
    拒绝整次调用且不做任何修改。空白会被去掉，``""`` 表示清空该值。
    值没有变化的编号不写库、不追加修改记录。

    返回 ``{"changed": [编号, ...]}``。
    """
    from data_points import POINT_META

    if not isinstance(edits, dict):
        raise ValueError("edits 必须是「编号 → 值」的对象")

    with Session(engine) as sess:
        report = sess.execute(
            select(Report).where(Report.id == int(report_id))).scalar_one_or_none()
        if report is None:
            raise LookupError(f"报告 {report_id} 不存在")

        try:
            raw = json.loads(report.data_json) if report.data_json else {}
        except Exception:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        items = raw.get("schema_124") or []
        by_code = {str(it.get("code", "")): it
                   for it in items if isinstance(it, dict)}

        cleaned: Dict[str, str] = {}
        detail = raw.get("b3_detail")
        for code, value in edits.items():
            code = str(code)
            if code.startswith("b3d."):
                if not isinstance(value, str):
                    raise ValueError(f"编号 {code} 的值必须是字符串")
                _check_b3d_edit(detail, code, value.strip())
                cleaned[code] = value.strip()
                continue
            item = by_code.get(code)
            if item is None:
                raise ValueError(f"未知编号 {code}")
            if not isinstance(value, str):
                raise ValueError(f"编号 {code} 的值必须是字符串")
            text = value.strip()
            type_ = item.get("type") or POINT_META.get(code, {}).get("type")
            if type_ == "number" and text != "":
                try:
                    num = float(text)
                except ValueError:
                    num = None
                if num is None or not math.isfinite(num):
                    raise ValueError(
                        f"编号 {code} 需要数值，收到「{text}」")
            cleaned[code] = text

        edits_log = raw.get("edits")
        if not isinstance(edits_log, list):
            edits_log = []
            raw["edits"] = edits_log
        now = datetime.now().isoformat(timespec="seconds")

        changed: List[str] = []
        for code, text in cleaned.items():
            if code.startswith("b3d."):
                old_text = _apply_b3d_edit(detail, code, text)
                if old_text is None:
                    continue
            else:
                item = by_code[code]
                old = item.get("value")
                old_text = "" if old is None else str(old)
                if old_text == text:
                    continue
                item["value"] = text
            edits_log.append({"code": code, "old": old_text, "new": text,
                              "by": editor, "at": now})
            changed.append(code)

        if any(c.startswith("b3d.") for c in changed):
            import b3_detail
            detail["checks"] = b3_detail.compute_checks(detail)

        if changed:
            report.data_json = json.dumps(raw, ensure_ascii=False)
            sess.commit()

    return {"changed": changed}


def get_report_pdf_path(report_id: int) -> Optional[str]:
    """Return the stored pdf_path for a single report, or None if missing."""
    with Session(engine) as sess:
        stmt = select(Report.pdf_path).where(Report.id == report_id)
        return sess.execute(stmt).scalar()


def get_all_reports() -> List[Dict[str, Any]]:
    """Get all reports joined with student info (for export)."""
    with Session(engine) as sess:
        stmt = select(Report, Student).join(Student).order_by(Report.created_at.desc())
        rows = sess.execute(stmt).all()
        results = []
        for report, student in rows:
            data = json.loads(report.data_json) if report.data_json else {}
            s124 = data.get("schema_124", [])
            flat = {item.get("code", ""): item.get("value", "") for item in s124 if item.get("value")}
            results.append({
                "report_id": report.id,
                "student_id": student.id,
                "student_name": student.name,
                "gender": student.gender,
                "grade": student.grade,
                "report_date": report.report_date.isoformat() if report.report_date else None,
                "pdf_path": report.pdf_path,
                "data": flat,
            })
        return results


# ─── Booking CRUD ──────────────────────────────────────────────

class SlotUnavailable(Exception):
    """kind: 'full' 或 'closed'；booked 为当前人数，capacity 为本次可用容量。"""
    def __init__(self, kind: str, booked: int = 0, capacity: int = None):
        super().__init__(kind)
        self.kind, self.booked = kind, booked
        self.capacity = capacity


def _lock_booking_location(sess: Session, location_id: int) -> None:
    """Serialize scheduling writes since an assessor can cover multiple offices."""
    if sess.bind.dialect.name == "sqlite":
        sess.connection().exec_driver_sql("BEGIN IMMEDIATE")
    else:
        sess.execute(select(Location.id).order_by(Location.id).with_for_update()).all()


def _lock_and_check_slot(sess: Session, location_id: Optional[int],
                         appt_time: datetime, capacity: Optional[int]) -> None:
    """Check slot capacity under the shared booking write lock when configured."""
    if capacity is None or location_id is None:
        return
    _lock_booking_location(sess, location_id)
    _check_slot(sess, location_id, appt_time, capacity)


def _check_slot(sess: Session, location_id: int, appt_time: datetime, capacity: int) -> None:
    d, ts = appt_time.date(), appt_time.strftime("%H:%M")
    av = sess.execute(select(Availability.is_available).where(
        Availability.date == d, Availability.time_slot == ts,
        Availability.location_id == location_id)).first()
    if av is not None and not av[0]:
        raise SlotUnavailable("closed")
    booked = sess.execute(select(func.count(Booking.id)).where(
        Booking.location_id == location_id, Booking.status != "cancelled",
        Booking.appointment_time == appt_time)).scalar() or 0
    if (d, ts) in _unanimous_assessor_closures(sess, d, d, location_id):
        raise SlotUnavailable("closed")
    if booked >= capacity:
        raise SlotUnavailable("full", booked, capacity)


def _insert_booking_student(sess: Session, **fields: Any) -> Student:
    student = Student(student_code=next_student_code(sess), **fields)
    sess.add(student)
    sess.flush()
    return student


def _insert_booking(sess: Session, **fields: Any) -> Booking:
    booking = Booking(status="pending", **fields)
    sess.add(booking)
    sess.flush()
    _touch_location(sess, booking.location_id)
    return booking


def add_booking(student_name: str, appointment_time: datetime,
                student_email: str = "", student_phone: str = "",
                notes: str = "", advisor_name: str = "",
                school: str = "", single_parent: str = "false",
                student_id: Optional[int] = None,
                location_id: Optional[int] = None,
                capacity: Optional[int] = None,
                source: Optional[str] = None,
                requester_name: Optional[str] = None,
                created_by: Optional[int] = None,
                invite_token: Optional[str] = None,
                staff_request_id: Optional[str] = None) -> int:
    """Create a booking. Returns booking id. capacity 给定时原子检查容量/关闭，失败抛 SlotUnavailable。"""
    with Session(engine) as sess:
        _lock_and_check_slot(sess, location_id, appointment_time, capacity)
        booking = _insert_booking(sess,
            location_id=location_id,
            student_name=student_name,
            student_email=student_email,
            student_phone=student_phone,
            student_id=student_id,
            appointment_time=appointment_time,
            notes=notes,
            advisor_name=advisor_name,
            school=school,
            single_parent=single_parent,
            source=source,
            requester_name=requester_name,
            created_by=created_by,
            invite_token=invite_token,
            staff_request_id=staff_request_id,
        )
        booking_id = booking.id
        sess.commit()
        return booking_id


def create_booking_with_student(student_name: str, appointment_time: datetime,
                                advisor_name: str = "", school: str = "",
                                single_parent: str = "false",
                                notes: str = "",
                                location_id: Optional[int] = None,
                                match_existing: bool = True,
                                capacity: Optional[int] = None,
                                source: Optional[str] = None,
                                requester_name: Optional[str] = None,
                                created_by: Optional[int] = None,
                                invite_token: Optional[str] = None,
                                staff_request_id: Optional[str] = None) -> tuple:
    """Create student + booking in one transaction. Returns (student_id, booking_id).

    match_existing=True（旧行为）按姓名复用已有学生；公开预约链接传 False，一律新建学生。
    """
    for attempt in range(_CODE_ALLOC_RETRIES):
        with Session(engine) as sess:
            try:
                _lock_and_check_slot(sess, location_id, appointment_time, capacity)
                # 1. Find or create student
                existing = (sess.execute(select(Student).where(Student.name == student_name)).first()
                            if match_existing else None)
                if existing:
                    student = existing[0]
                    update_values = {}
                    if advisor_name:
                        update_values["advisor_name"] = advisor_name
                    if school:
                        update_values["school"] = school
                    if single_parent and single_parent != "false":
                        update_values["single_parent"] = single_parent
                    if update_values:
                        sess.execute(update(Student).where(Student.id == student.id).values(**update_values))
                    sess.flush()
                    student_id = student.id
                else:
                    student = _insert_booking_student(
                        sess, name=student_name, advisor_name=advisor_name,
                        school=school, single_parent=single_parent,
                    )
                    student_id = student.id

                # 2. Create booking linked to student
                booking = _insert_booking(
                    sess, student_name=student_name, student_id=student_id,
                    appointment_time=appointment_time, notes=notes, advisor_name=advisor_name,
                    school=school, single_parent=single_parent,
                    location_id=location_id, source=source,
                    requester_name=requester_name, created_by=created_by,
                    invite_token=invite_token, staff_request_id=staff_request_id)
                booking_id = booking.id
                sess.commit()
                return student_id, booking_id
            except IntegrityError:
                # 并发下 student_code 撞唯一索引：回滚整笔事务后重试
                sess.rollback()
                if attempt == _CODE_ALLOC_RETRIES - 1:
                    raise


def get_bookings(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """List bookings, optionally filtered by status. Includes report_count per booking."""
    with Session(engine) as sess:
        stmt = select(Booking)
        if status:
            stmt = stmt.where(Booking.status == status)
        stmt = stmt.order_by(Booking.appointment_time.desc())
        rows = sess.execute(stmt).all()
        results = []
        for row in rows:
            booking = row[0]
            report_count = 0
            if booking.student_id:
                count_stmt = select(func.count(Report.id)).where(Report.student_id == booking.student_id)
                report_count = sess.execute(count_stmt).scalar() or 0
            results.append({
                "id": booking.id,
                "student_name": booking.student_name,
                "student_id": booking.student_id,
                "student_email": booking.student_email,
                "student_phone": booking.student_phone,
                "appointment_time": booking.appointment_time.isoformat() if booking.appointment_time else None,
                "status": booking.status,
                "notes": booking.notes,
                "advisor_name": booking.advisor_name,
                "school": booking.school,
                "single_parent": booking.single_parent,
                "location_id": booking.location_id,
                "created_at": booking.created_at.isoformat() if booking.created_at else None,
                "source": booking.source or "",
                "requester_name": booking.requester_name or "",
                "created_by": booking.created_by,
                "assessor_id": booking.assessor_id,
                "assigned_at": booking.assigned_at.isoformat() if booking.assigned_at else None,
                "report_count": report_count,
            })
        return results


def update_booking_status(booking_id: int, status: str) -> None:
    with Session(engine) as sess:
        row = sess.execute(select(Booking.location_id).where(Booking.id == booking_id)).first()
        _touch_location(sess, row[0] if row else None)
        stmt = update(Booking).where(Booking.id == booking_id).values(status=status)
        sess.execute(stmt)
        sess.commit()


def complete_booking(booking_id: int) -> int:
    """Mark booking completed. Student is already created at booking time.
    Returns student_id if linked, else creates one for backward compat."""
    with Session(engine) as sess:
        stmt = select(Booking).where(Booking.id == booking_id)
        row = sess.execute(stmt).first()
        if not row:
            raise ValueError(f"Booking {booking_id} not found")
        booking = row[0]
        if booking.student_id:
            update_booking_status(booking_id, "completed")
            return booking.student_id
        # Backward compat: old bookings without student_id
        student_id = find_or_create_student(name=booking.student_name)
        sess.execute(update(Booking).where(Booking.id == booking_id).values(
            status="completed", student_id=student_id))
        sess.commit()
        return student_id


# ─── Delete operations ─────────────────────────────────────────

class StudentHasY4Records(ValueError):
    """Raised when guarded deletion finds a Y4 report or assessment round."""


def delete_student(student_id: int, *, protect_y4: bool = False) -> None:
    """Delete a student and all their dependent records.

    开启 SQLite ForeignKey 后，直接删 students 会因子表外键引用而失败；
    这里按「子表先删 / 可空外键解绑，父表后删」的顺序清理，覆盖
    reports / bookings / meeting_minutes / six_am_profiles 以及问卷子系统的
    assignments / assignment_tokens / responses / questionnaire_scores /
    response_drafts / student_accounts。
    """
    # 问卷子系统模型定义在 questionnaire_store（模块级互相 import，延迟导入避免循环）
    try:
        from questionnaire_store import (
            Assignment, AssignmentToken, QuestionnaireScore, Response, ResponseDraft,
            StudentAccount,
        )
        has_qstore = True
    except Exception:
        # 导入失败说明问卷子系统未启用/表未创建，通常也无相关行
        has_qstore = False

    with Session(engine) as sess:
        if protect_y4:
            from y4_upload import Y4Round

            if engine.dialect.name == "sqlite":
                sess.connection().exec_driver_sql("BEGIN IMMEDIATE")
            else:
                sess.execute(select(Student.id).where(Student.id == student_id).with_for_update())
            report = select(Report.id).where(Report.student_id == student_id).limit(1)
            round_ = select(Y4Round.id).where(Y4Round.student_id == student_id).limit(1)
            if sess.execute(report).first() or sess.execute(round_).first():
                raise StudentHasY4Records("此档案关联 Y4 记录，已保留档案和报告。")

        # 1. 问卷子系统：tokens / responses / drafts 依赖 assignments，先清理
        if has_qstore:
            sess.execute(delete(QuestionnaireScore).where(
                QuestionnaireScore.student_id == student_id))
            assignment_ids = [
                r[0] for r in sess.execute(
                    select(Assignment.id).where(Assignment.student_id == student_id)).all()
            ]
            if assignment_ids:
                sess.execute(delete(AssignmentToken).where(
                    AssignmentToken.assignment_id.in_(assignment_ids)))
                sess.execute(delete(Response).where(
                    Response.assignment_id.in_(assignment_ids)))
                sess.execute(delete(ResponseDraft).where(
                    ResponseDraft.assignment_id.in_(assignment_ids)))
            sess.execute(delete(Response).where(Response.student_id == student_id))
            sess.execute(delete(Assignment).where(Assignment.student_id == student_id))
            sess.execute(delete(StudentAccount).where(StudentAccount.student_id == student_id))

        # 2. reports 的子表：meeting_minutes.report_id 可空 → 解绑；six_am_profiles.report_id NOT NULL → 删除
        report_ids = [
            r[0] for r in sess.execute(
                select(Report.id).where(Report.student_id == student_id)).all()
        ]
        if report_ids:
            sess.execute(update(MeetingMinutes).where(
                MeetingMinutes.report_id.in_(report_ids)).values(report_id=None))
            sess.execute(delete(SixAmProfile).where(
                SixAmProfile.report_id.in_(report_ids)))

        # 3. 直接挂学生的 meeting_minutes / 6AM 档案
        sess.execute(delete(MeetingMinutes).where(MeetingMinutes.student_id == student_id))
        sess.execute(delete(SixAmProfile).where(SixAmProfile.student_id == student_id))

        # 4. bookings.student_id 可空 → 解绑（保留预约历史，不级联删除）
        sess.execute(update(Booking).where(Booking.student_id == student_id)
                     .values(student_id=None))

        # 5. reports 与 student 本体
        sess.execute(delete(Report).where(Report.student_id == student_id))
        sess.execute(delete(Student).where(Student.id == student_id))
        sess.commit()


def update_student(student_id: int, **kwargs) -> None:
    """Update a student's fields. Only non-empty values are applied."""
    if not kwargs:
        return
    with Session(engine) as sess:
        sess.execute(update(Student).where(Student.id == student_id).values(**kwargs))
        sess.commit()


def delete_report(report_id: int) -> None:
    """Delete a single report and its FK dependents.

    meeting_minutes.report_id 可空 → 解绑（保留纪要）；six_am_profiles.report_id
    NOT NULL → 连带删除（报告派生产物）。
    """
    with Session(engine) as sess:
        sess.execute(update(MeetingMinutes).where(MeetingMinutes.report_id == report_id)
                     .values(report_id=None))
        sess.execute(delete(SixAmProfile).where(SixAmProfile.report_id == report_id))
        sess.execute(delete(Report).where(Report.id == report_id))
        sess.commit()


def delete_booking(booking_id: int) -> None:
    """Delete a booking."""
    with Session(engine) as sess:
        row = sess.execute(select(Booking.location_id).where(Booking.id == booking_id)).first()
        _touch_location(sess, row[0] if row else None)
        sess.execute(delete(Booking).where(Booking.id == booking_id))
        sess.commit()


# ─── Locations (预约办公室) ─────────────────────────────────────

DEFAULT_LOCATIONS = ["上海", "北京", "深圳"]
DEFAULT_LOCATION_NAME = "上海"


def _touch_location(sess: Session, location_id: Optional[int]) -> None:
    """该办公室的预约/开放时段有变化 → 刷新 updated_at（在调用方事务内）。"""
    if location_id is None:
        return
    sess.execute(update(Location).where(Location.id == location_id)
                 .values(updated_at=datetime.utcnow()))


def ensure_locations() -> int:
    """幂等：首次建表时写入上海/北京/深圳，并把 location_id 为空的预约与开放时段归到上海。
    返回上海的 id。"""
    with Session(engine) as sess:
        if sess.execute(select(func.count(Location.id))).scalar() == 0:
            for i, name in enumerate(DEFAULT_LOCATIONS):
                sess.add(Location(name=name, active=1, sort=i, updated_at=datetime.utcnow()))
            sess.flush()
        default_id = _default_location_id(sess)
        for model in (Booking, Availability):
            sess.execute(update(model).where(model.location_id.is_(None))
                         .values(location_id=default_id))
        sess.commit()
        return default_id


def _default_location_id(sess: Session) -> int:
    row = sess.execute(select(Location.id).where(Location.name == DEFAULT_LOCATION_NAME)
                       .order_by(Location.id)).first()
    if row is None:
        row = sess.execute(select(Location.id).order_by(Location.sort, Location.id)).first()
    return row[0]


def get_default_location_id() -> int:
    """未指定办公室时使用上海（旧链接兼容）。"""
    with Session(engine) as sess:
        if sess.execute(select(func.count(Location.id))).scalar():
            return _default_location_id(sess)
    return ensure_locations()


def _location_dict(loc: "Location") -> Dict[str, Any]:
    return {
        "id": loc.id,
        "name": loc.name,
        "assessor_label": loc.assessor_label,
        "active": bool(loc.active),
        "updated_at": loc.updated_at.isoformat() if loc.updated_at else None,
    }


def list_locations(active_only: bool = True) -> List[Dict[str, Any]]:
    get_default_location_id()  # 确保已初始化
    with Session(engine) as sess:
        stmt = select(Location).order_by(Location.sort, Location.id)
        if active_only:
            stmt = stmt.where(Location.active == 1)
        return [_location_dict(r[0]) for r in sess.execute(stmt).all()]


def get_location(location_id: int) -> Optional[Dict[str, Any]]:
    with Session(engine) as sess:
        loc = sess.get(Location, location_id)
        return _location_dict(loc) if loc else None


# ─── Availability CRUD ──────────────────────────────────────────

SLOT_CAPACITY = 4
BOOKING_MAX_DAYS_AHEAD = 29
TIME_SLOTS = [
    "09:00", "09:30", "10:00", "10:30", "11:00",
    "13:00", "13:30", "14:00", "14:30", "15:00",
    "15:30", "16:00", "16:30", "17:00",
]


def _loc_filter(model, location_id: Optional[int]):
    """location_id 为 None 时不按办公室过滤（旧调用）。"""
    return [] if location_id is None else [model.location_id == location_id]


def get_availability(date_val: date, location_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Get all availability entries for a given date (and office, if given)."""
    with Session(engine) as sess:
        stmt = (select(Availability).where(Availability.date == date_val,
                                           *_loc_filter(Availability, location_id))
                .order_by(Availability.time_slot))
        rows = sess.execute(stmt).all()
        result = []
        for row in rows:
            result.append({
                "id": row[0].id,
                "date": row[0].date.isoformat() if row[0].date else None,
                "time_slot": row[0].time_slot,
                "is_available": bool(row[0].is_available),
            })
        return result


def _upsert_availability(sess: Session, date_val: date, time_slot: str,
                         is_available: bool, location_id: Optional[int]) -> int:
    existing = sess.execute(
        select(Availability).where(
            Availability.date == date_val,
            Availability.time_slot == time_slot,
            *_loc_filter(Availability, location_id),
        )
    ).first()
    av = 1 if is_available else 0
    if existing:
        sess.execute(update(Availability).where(Availability.id == existing[0].id)
                     .values(is_available=av))
        return existing[0].id
    entry = Availability(date=date_val, time_slot=time_slot,
                         is_available=av, location_id=location_id)
    sess.add(entry)
    sess.flush()
    return entry.id


def set_availability(date_val: date, time_slot: str, is_available: bool,
                     location_id: Optional[int] = None) -> int:
    """Create or update an availability entry. Returns the id."""
    with Session(engine) as sess:
        if location_id is not None:
            _lock_booking_location(sess, location_id)
        rid = _upsert_availability(sess, date_val, time_slot, is_available, location_id)
        _touch_location(sess, location_id)
        sess.commit()
        return rid


def batch_set_availability(date_val: date, slots: List[Dict[str, Any]],
                           location_id: Optional[int] = None) -> None:
    """Set availability for all time slots on a given date.
    slots is a list of {"time_slot": "09:00", "is_available": True/False}
    """
    with Session(engine) as sess:
        if location_id is not None:
            _lock_booking_location(sess, location_id)
        for slot in slots:
            _upsert_availability(sess, date_val, slot["time_slot"],
                                 bool(slot.get("is_available", False)), location_id)
        _touch_location(sess, location_id)
        sess.commit()


def bulk_set_availability(location_id: int,
                          changes: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """批量开/关某办公室的时段。changes: [{"date": date, "time": "09:00", "open": bool}]。
    已有非取消预约的时段不能关闭，返回 refused=[{date,time}]，其余照常生效。"""
    refused: List[Dict[str, str]] = []
    applied = False
    with Session(engine) as sess:
        _lock_booking_location(sess, location_id)
        for ch in changes:
            d, t, want_open = ch["date"], ch["time"], bool(ch["open"])
            if not want_open:
                start = datetime.combine(d, datetime.strptime(t, "%H:%M").time())
                n = sess.execute(select(func.count(Booking.id)).where(
                    Booking.location_id == location_id,
                    Booking.status != "cancelled",
                    Booking.appointment_time == start)).scalar()
                if n:
                    refused.append({"date": d.isoformat(), "time": t})
                    continue
            _upsert_availability(sess, d, t, want_open, location_id)
            applied = True
        if applied:
            _touch_location(sess, location_id)
        sess.commit()
    return refused


def get_available_slots(date_val: date, location_id: Optional[int] = None) -> List[str]:
    """Get list of available time slot strings for a date."""
    entries = get_availability(date_val, location_id)
    return [e["time_slot"] for e in entries if e["is_available"]]


def get_slot_booking_counts(date_val: date, location_id: Optional[int] = None) -> Dict[str, int]:
    """Count non-cancelled bookings per time_slot for a given date.
    Returns {"09:00": 2, "10:00": 0, ...}
    """
    with Session(engine) as sess:
        stmt = select(Booking).where(
            Booking.status != "cancelled",
            Booking.appointment_time >= date_val,
            Booking.appointment_time < date_val + timedelta(days=1),
            *_loc_filter(Booking, location_id),
        )
        rows = sess.execute(stmt).all()
        counts: Dict[str, int] = {}
        for row in rows:
            booking = row[0]
            if booking.appointment_time:
                ts = booking.appointment_time.strftime("%H:%M")
                counts[ts] = counts.get(ts, 0) + 1
        return counts


def get_booking_counts_range(start_date: date, end_date: date,
                             location_id: Optional[int] = None) -> Dict[str, Dict[str, int]]:
    """Count non-cancelled bookings per time_slot for a date range.
    Returns {"2026-08-13": {"09:00": 2, "10:00": 1}, ...}
    """
    with Session(engine) as sess:
        stmt = select(Booking).where(
            Booking.status != "cancelled",
            Booking.appointment_time >= start_date,
            Booking.appointment_time < end_date + timedelta(days=1),
            *_loc_filter(Booking, location_id),
        )
        rows = sess.execute(stmt).all()
        result: Dict[str, Dict[str, int]] = {}
        for row in rows:
            booking = row[0]
            if booking.appointment_time:
                date_str = booking.appointment_time.date().isoformat()
                ts = booking.appointment_time.strftime("%H:%M")
                if date_str not in result:
                    result[date_str] = {}
                result[date_str][ts] = result[date_str].get(ts, 0) + 1
        return result


def get_week_bookings(location_id: int, start_date: date, days: int = 7) -> List[Dict[str, Any]]:
    """某办公室 [start_date, start_date+days) 内的非取消预约，附学生编号与测评师。"""
    from sqlalchemy.orm import aliased
    assessor = aliased(User)
    with Session(engine) as sess:
        stmt = (select(Booking, Student.student_code, assessor.display_name)
                .outerjoin(Student, Student.id == Booking.student_id)
                .outerjoin(assessor, assessor.id == Booking.assessor_id)
                .where(Booking.status != "cancelled",
                       Booking.location_id == location_id,
                       Booking.appointment_time >= start_date,
                       Booking.appointment_time < start_date + timedelta(days=days))
                .order_by(Booking.appointment_time, Booking.id))
        out = []
        for b, code, assessor_name in sess.execute(stmt).all():
            out.append({
                "id": b.id,
                "student_name": b.student_name,
                "student_code": code,
                "status": b.status,
                "advisor_name": b.advisor_name,
                "appointment_time": b.appointment_time,
                "source": b.source or "",
                "requester_name": b.requester_name or "",
                "assessor_id": b.assessor_id,
                "assessor_name": assessor_name or "",
            })
        return out


# ─── Task C：预约交接 / 测评师分配 / 可约时段 ─────────────────────

def get_booking_detail(booking_id: int) -> Optional[Dict[str, Any]]:
    """单条预约（含学生编号、办公室、经办人和测评师姓名）。"""
    from sqlalchemy.orm import aliased
    assessor = aliased(User)
    creator = aliased(User)
    with Session(engine) as sess:
        stmt = (select(Booking, Student.student_code, Location.name,
                       assessor.display_name, assessor.id, creator.display_name)
                .outerjoin(Student, Student.id == Booking.student_id)
                .outerjoin(Location, Location.id == Booking.location_id)
                .outerjoin(assessor, assessor.id == Booking.assessor_id)
                .outerjoin(creator, creator.id == Booking.created_by)
                .where(Booking.id == int(booking_id)))
        row = sess.execute(stmt).first()
        if not row:
            return None
        b, code, loc_name, assessor_name, assessor_id, creator_name = row
        return {
            "id": b.id,
            "student_id": b.student_id,
            "student_name": b.student_name,
            "student_code": code or "",
            "appointment_time": b.appointment_time.isoformat() if b.appointment_time else None,
            "appointment_date": b.appointment_time.date().isoformat() if b.appointment_time else "",
            "appointment_slot": b.appointment_time.strftime("%H:%M") if b.appointment_time else "",
            "status": b.status,
            "location_id": b.location_id,
            "location_name": loc_name or "",
            "source": b.source or "",
            "requester_name": b.requester_name or "",
            "created_by": b.created_by,
            "created_by_name": creator_name or "",
            "advisor_name": b.advisor_name or "",
            "assessor_id": assessor_id,
            "assessor_name": assessor_name or "",
            "assigned_at": b.assigned_at.isoformat() if b.assigned_at else None,
        }


def get_bookings_for_date(day: date, location_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """某天未取消的预约，按时间升序。前台交接列表使用。"""
    from sqlalchemy.orm import aliased
    assessor = aliased(User)
    with Session(engine) as sess:
        stmt = (select(Booking, Student.student_code, Location.name, assessor.display_name)
                .outerjoin(Student, Student.id == Booking.student_id)
                .outerjoin(Location, Location.id == Booking.location_id)
                .outerjoin(assessor, assessor.id == Booking.assessor_id)
                .where(Booking.status != "cancelled",
                       Booking.appointment_time >= day,
                       Booking.appointment_time < day + timedelta(days=1)))
        if location_id is not None:
            stmt = stmt.where(Booking.location_id == int(location_id))
        stmt = stmt.order_by(Booking.appointment_time, Booking.id)
        return [
            {
                "id": b.id,
                "student_id": b.student_id,
                "student_name": b.student_name,
                "student_code": code or "",
                "appointment_time": b.appointment_time.isoformat(),
                "appointment_slot": b.appointment_time.strftime("%H:%M"),
                "status": b.status,
                "location_id": b.location_id,
                "location_name": loc_name or "",
                "advisor_name": b.advisor_name or "",
                "source": b.source or "",
                "requester_name": b.requester_name or "",
                "assessor_id": b.assessor_id,
                "assessor_name": assessor_name or "",
            }
            for b, code, loc_name, assessor_name in sess.execute(stmt).all()
        ]


def get_booking_by_invite(token: str) -> Optional[Dict[str, Any]]:
    """邀请链接是否已落单（用于拒绝重复使用同一链接）。"""
    with Session(engine) as sess:
        row = sess.execute(select(Booking.id).where(Booking.invite_token == token)).first()
        return {"booking_id": row[0]} if row else None


def get_staff_booking_by_request(created_by: int, request_id: str) -> Optional[Dict[str, Any]]:
    with Session(engine) as sess:
        row = sess.execute(select(Booking.id, Booking.source).where(
            Booking.created_by == created_by, Booking.staff_request_id == request_id,
        )).first()
        return {"booking_id": row.id, "source": row.source} if row else None


def get_student_bookings(student_id: int) -> List[Dict[str, Any]]:
    """某学生的全部预约（用于档案「预约与分配」），附测评师与经办人姓名。"""
    from sqlalchemy.orm import aliased
    assessor = aliased(User)
    creator = aliased(User)
    with Session(engine) as sess:
        stmt = (select(Booking, Location.name, assessor.display_name, assessor.id,
                       creator.display_name)
                .outerjoin(Location, Location.id == Booking.location_id)
                .outerjoin(assessor, assessor.id == Booking.assessor_id)
                .outerjoin(creator, creator.id == Booking.created_by)
                .where(Booking.student_id == int(student_id))
                .order_by(Booking.appointment_time.desc(), Booking.id.desc()))
        out = []
        for b, loc_name, assessor_name, assessor_id, creator_name in sess.execute(stmt).all():
            out.append({
                "id": b.id,
                "appointment_time": b.appointment_time.isoformat() if b.appointment_time else None,
                "appointment_date": b.appointment_time.date().isoformat() if b.appointment_time else "",
                "appointment_slot": b.appointment_time.strftime("%H:%M") if b.appointment_time else "",
                "status": b.status,
                "location_id": b.location_id,
                "location_name": loc_name or "",
                "source": b.source or "",
                "requester_name": b.requester_name or "",
                "created_by_name": creator_name or "",
                "assessor_id": assessor_id,
                "assessor_name": assessor_name or "",
                "assigned_at": b.assigned_at.isoformat() if b.assigned_at else None,
            })
        return out


def _authorized_assessor_ids(sess: Session, location_id: int) -> List[int]:
    """该办公室被授权且启用的测评师 id；未迁移库按空处理（沿用原容量）。"""
    try:
        rows = sess.execute(
            select(User.id)
            .join(UserOffice, UserOffice.user_id == User.id)
            .where(UserOffice.office_id == int(location_id),
                   User.is_assessor == 1, User.is_active == 1,
                   User.role.in_(("admin", "advisor")))
            .order_by(User.display_name, User.id)).all()
    except OperationalError:
        sess.rollback()
        return []
    return [int(r[0]) for r in rows]


def _assessor_declines(sess: Session, assessor_ids: List[int], location_id: int,
                       start: date, end: date):
    return sess.execute(select(AssessorAvailability.date, AssessorAvailability.time_slot,
                               AssessorAvailability.assessor_id).where(
        AssessorAvailability.assessor_id.in_(assessor_ids),
        AssessorAvailability.location_id == location_id,
        AssessorAvailability.date.between(start, end),
        AssessorAvailability.is_available == 0))


def _assessor_ids_available(sess: Session, location_id: int, appt: datetime) -> List[int]:
    ids = _authorized_assessor_ids(sess, location_id)
    if not ids:
        return []
    day, slot = appt.date(), appt.strftime("%H:%M")
    declined = {aid for _, time_slot, aid in _assessor_declines(sess, ids, location_id, day, day)
                if time_slot == slot}
    return [aid for aid in ids if aid not in declined]


def _unanimous_assessor_closures(sess: Session, start: date, end: date, location_id: int):
    """Only an explicit decline by every eligible teacher closes an office slot."""
    ids = _authorized_assessor_ids(sess, location_id)
    if not ids:
        return set()
    declines = defaultdict(set)
    for day, slot, assessor in _assessor_declines(sess, ids, location_id, start, end):
        declines[day, slot].add(assessor)
    return {cell for cell, teachers in declines.items() if len(teachers) == len(ids)}


def effective_slot_capacity(location_id: Optional[int], appt: datetime,
                            hard_cap: Optional[int] = None) -> int:
    cap = int(hard_cap if hard_cap is not None else SLOT_CAPACITY)
    if location_id is None:
        return cap
    day, slot = appt.date(), appt.strftime("%H:%M")
    with Session(engine) as sess:
        return 0 if (day, slot) in _unanimous_assessor_closures(sess, day, day, location_id) else cap


def slot_capacity_range(start: date, end: date, location_id: int,
                        hard_cap: Optional[int] = None) -> Dict[str, Dict[str, int]]:
    """Office capacity is independent of assigned assessors and unassigned bookings."""
    cap = int(hard_cap if hard_cap is not None else SLOT_CAPACITY)
    with Session(engine) as sess:
        closed = _unanimous_assessor_closures(sess, start, end, location_id)
    return {
        day.isoformat(): {slot: 0 if (day, slot) in closed else cap for slot in TIME_SLOTS}
        for day in (start + timedelta(days=i) for i in range((end - start).days + 1))
    }


def get_slot_assessors(location_id: int, appt: datetime) -> List[Dict[str, Any]]:
    """内部排班显示：该时段可承接且尚未在该时刻被占用的具名老师。"""
    with Session(engine) as sess:
        ids = _assessor_ids_available(sess, int(location_id), appt)
        if not ids:
            return []
        busy = {int(r[0]) for r in sess.execute(select(Booking.assessor_id).where(
            Booking.assessor_id.in_(ids),
            Booking.status != "cancelled",
            Booking.appointment_time == appt)).all()}
        out = []
        for uid, name, username in sess.execute(
                select(User.id, User.display_name, User.username)
                .where(User.id.in_(ids)).order_by(User.display_name, User.id)).all():
            if int(uid) in busy:
                continue
            out.append({"id": int(uid), "display_name": name or username})
        return out


def get_office_default_assessor(office_id: Optional[int]) -> Optional[int]:
    """办公室显式配置的默认测评师用户 ID；未配置或旧库缺表时返回 None。"""
    if office_id in (None, ""):
        return None
    try:
        with Session(engine) as sess:
            row = sess.get(OfficeDefaultAssessor, int(office_id))
            return int(row.assessor_id) if row else None
    except OperationalError:
        return None


def set_office_default_assessor(office_id: int, assessor_id: int,
                                grant_access: bool = False) -> Dict[str, Any]:
    """幂等配置某办公室的默认测评师。

    只把该账号在该办公室标记为默认测评师，不改动其其他办公室，
    也不改写任何已有预约的测评师。显示名变化不影响，因为只认稳定用户 ID。

    grant_access=True 时，额外启用该账号的测评师身份并授予该办公室，用于线上首次部署
    或历史账号尚未配置权限的情况；授权动作只针对显式传入的账号和办公室。
    """
    with Session(engine) as sess:
        office = sess.get(Location, int(office_id))
        if not office or not office.active:
            raise ValueError("办公室不存在或已停用")
        user = sess.get(User, int(assessor_id))
        if not user or not int(user.is_active or 0):
            raise ValueError("该账号不存在或已停用")
        if user.role not in ("admin", "advisor"):
            raise ValueError("只有管理员或顾问账号可以配置为测评师")
        granted_assessor = False
        granted_office = False
        if grant_access:
            if not int(user.is_assessor or 0):
                user.is_assessor = 1
                granted_assessor = True
            link = sess.get(UserOffice, (int(assessor_id), int(office_id)))
            if not link:
                has_office = sess.scalar(
                    select(func.count()).select_from(UserOffice)
                    .where(UserOffice.user_id == int(assessor_id))) or 0
                sess.add(UserOffice(user_id=int(assessor_id), office_id=int(office_id),
                                    is_default=0 if has_office else 1))
                granted_office = True
            if not user.office_id:
                user.office_id = int(office_id)
        else:
            if not int(user.is_assessor or 0):
                raise ValueError("该账号不是可用测评师，请先在用户管理启用测评师身份")
            if not sess.get(UserOffice, (int(assessor_id), int(office_id))):
                raise ValueError("该账号未获该办公室授权，请先在用户管理启用该办公室")
        row = sess.get(OfficeDefaultAssessor, int(office_id))
        if row:
            row.assessor_id = int(assessor_id)
            row.updated_at = datetime.utcnow()
        else:
            sess.add(OfficeDefaultAssessor(office_id=int(office_id), assessor_id=int(assessor_id)))
        setting = sess.get(AssessorOfficeSetting, (int(assessor_id), int(office_id)))
        if setting:
            setting.mode = "legacy"
        else:
            sess.add(AssessorOfficeSetting(
                assessor_id=int(assessor_id), office_id=int(office_id), mode="legacy"))
        sess.commit()
        return {"office_id": int(office_id), "assessor_id": int(assessor_id),
                "granted_assessor": granted_assessor, "granted_office": granted_office,
                "mode": "legacy"}


def get_assessor_candidates(booking: Dict[str, Any]) -> List[Dict[str, Any]]:
    """与预约同办公室、已获授权、该时段未关闭且未撞单的启用测评师。

    配置了该办公室默认测评师时，其排在首位（is_default=True）；是否预选由前端决定。
    """
    appt = datetime.fromisoformat(booking["appointment_time"])
    location_id = int(booking["location_id"] or 0)
    with Session(engine) as sess:
        ids = _assessor_ids_available(sess, location_id, appt)
        users = sess.execute(select(User).where(User.id.in_(ids))).scalars().all()
        office = sess.get(Location, location_id)
        office_name = office.name if office else ""
        default_row = sess.get(OfficeDefaultAssessor, location_id)
        default_id = int(default_row.assessor_id) if default_row else None
        busy = {r[0] for r in sess.execute(
            select(Booking.assessor_id).where(
                Booking.assessor_id.isnot(None),
                Booking.status != "cancelled",
                Booking.appointment_time == appt,
                Booking.id != booking["id"])).all()}
        out = []
        for u in users:
            uid = int(u.id)
            if uid in busy:
                continue
            out.append({
                "id": uid,
                "display_name": u.display_name or u.username,
                "username": u.username,
                "office_id": location_id,
                "office_name": office_name or "",
                "assigned": uid == int(booking.get("assessor_id") or 0),
                "is_default": uid == default_id,
            })
        out.sort(key=lambda c: (not c["assigned"], not c["is_default"],
                                c["display_name"], c["id"]))
        return out


def assign_booking_assessor(booking_id: int, assessor_id: int) -> None:
    """原子分配测评师。校验办公室授权、可约、未撞单；失败抛 ValueError。"""
    with Session(engine) as sess:
        _lock_booking_location(sess, 0)
        booking = sess.get(Booking, int(booking_id))
        if not booking or booking.status == "cancelled":
            raise ValueError("预约不存在或已取消")
        user = sess.get(User, int(assessor_id))
        if not user or not int(user.is_active or 0) or not int(user.is_assessor or 0):
            raise ValueError("该账号不是可用测评师")
        if user.role not in ("admin", "advisor"):
            raise ValueError("该账号不是可用测评师")
        location_id = int(booking.location_id or 0)
        allowed = sess.execute(select(UserOffice.office_id).where(
            UserOffice.user_id == int(assessor_id),
            UserOffice.office_id == location_id)).first()
        if not allowed:
            raise ValueError("测评师不属于该办公室")
        day, slot = booking.appointment_time.date(), booking.appointment_time.strftime("%H:%M")
        row = sess.execute(select(AssessorAvailability.is_available).where(
            AssessorAvailability.assessor_id == int(assessor_id),
            AssessorAvailability.location_id == location_id,
            AssessorAvailability.date == day,
            AssessorAvailability.time_slot == slot)).first()
        if row is not None and not row[0]:
            raise ValueError("该测评师此时间不可约")
        conflict = sess.execute(select(Booking.id).where(
            Booking.assessor_id == int(assessor_id),
            Booking.status != "cancelled",
            Booking.appointment_time == booking.appointment_time,
            Booking.id != int(booking_id))).first()
        if conflict:
            raise ValueError("该测评师在此时间已有其他预约")
        booking.assessor_id = int(assessor_id)
        booking.assigned_at = datetime.utcnow()
        try:
            sess.commit()
        except IntegrityError:
            sess.rollback()
            raise ValueError("该测评师在此时间已有其他预约")


def list_assessor_availability(assessor_id: int, start: date, days: int = 14,
                               location_id: Optional[int] = None) -> Dict[str, Dict[str, bool]]:
    """测评师 [start, start+days) 的可约状态。

    指定办公室时，未标记不可约的时段默认开放；
    未指定时沿用旧行为，只返回已有记录。
    """
    end = start + timedelta(days=days - 1)
    with Session(engine) as sess:
        stmt = select(AssessorAvailability).where(
            AssessorAvailability.assessor_id == int(assessor_id),
            AssessorAvailability.date >= start,
            AssessorAvailability.date <= end)
        if location_id not in (None, ""):
            stmt = stmt.where(AssessorAvailability.location_id == int(location_id))
        rows = sess.execute(stmt).scalars().all()
        record: Dict[str, Dict[str, bool]] = {}
        for r in rows:
            record.setdefault(r.date.isoformat(), {})[r.time_slot] = bool(r.is_available)
        if location_id in (None, ""):
            return record
        out: Dict[str, Dict[str, bool]] = {}
        for offset in range(days):
            d = start + timedelta(days=offset)
            values = dict(record.get(d.isoformat(), {}))
            for slot in TIME_SLOTS:
                values.setdefault(slot, True)
            out[d.isoformat()] = values
        return out


def set_assessor_availability(assessor_id: int, location_id: Optional[int], day: date,
                              slots: List[Dict[str, Any]]) -> None:
    """批量写入测评师某办公室某天的可约状态（幂等 upsert，按办公室隔离）。"""
    if location_id in (None, ""):
        with Session(engine) as sess:
            user = sess.get(User, int(assessor_id))
            location_id = user.office_id if user else None
    if location_id in (None, ""):
        raise ValueError("请选择办公室")
    with Session(engine) as sess:
        _lock_booking_location(sess, int(location_id))
        assessor = sess.get(User, int(assessor_id))
        office = sess.get(Location, int(location_id))
        if not assessor or not assessor.is_active or not assessor.is_assessor or assessor.role not in ("admin", "advisor"):
            raise PermissionError("当前账号不是测评师")
        if not office or not office.active or not sess.get(UserOffice, (assessor.id, office.id)):
            raise PermissionError("无权使用该办公室")
        for item in slots:
            slot = str(item.get("time_slot") or "")
            if slot not in TIME_SLOTS:
                raise ValueError("时间不在可预约时段内")
            want = 1 if item.get("is_available") else 0
            row = sess.execute(select(AssessorAvailability).where(
                AssessorAvailability.assessor_id == int(assessor_id),
                AssessorAvailability.location_id == int(location_id),
                AssessorAvailability.date == day,
                AssessorAvailability.time_slot == slot)).scalars().first()
            if row:
                row.is_available = want
            else:
                sess.add(AssessorAvailability(
                    assessor_id=int(assessor_id), location_id=int(location_id),
                    date=day, time_slot=slot, is_available=want))
        sess.commit()


def get_availability_range(start_date: date, end_date: date,
                           location_id: Optional[int] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Get availability for a date range, grouped by date string.
    Returns {"2026-08-13": [{"time_slot": "09:00", "is_available": true}, ...], ...}
    Only returns dates that have at least one record.
    """
    with Session(engine) as sess:
        stmt = select(Availability).where(
            Availability.date >= start_date,
            Availability.date <= end_date,
            *_loc_filter(Availability, location_id),
        ).order_by(Availability.date, Availability.time_slot)
        rows = sess.execute(stmt).all()
        result: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            av = row[0]
            date_str = av.date.isoformat() if av.date else None
            if date_str not in result:
                result[date_str] = []
            result[date_str].append({
                "id": av.id,
                "date": date_str,
                "time_slot": av.time_slot,
                "is_available": bool(av.is_available),
            })
        return result


# ─── MeetingMinutes CRUD ────────────────────────────────────────

def add_minutes(student_id: int, report_id: Optional[int],
                transcript_text: str, minutes_text: str,
                minutes_json: Optional[str] = None) -> int:
    """Create a meeting minutes record. Returns minutes id."""
    now = datetime.utcnow()
    with Session(engine) as sess:
        stmt = insert(MeetingMinutes).values(
            student_id=student_id,
            report_id=report_id,
            transcript_text=transcript_text,
            minutes_text=minutes_text,
            minutes_json=minutes_json,
            created_at=now,
            updated_at=now,
        )
        result = sess.execute(stmt)
        sess.commit()
        return result.lastrowid


def get_minutes(minutes_id: int) -> Optional[Dict[str, Any]]:
    """Get a single meeting minutes record with student and report info."""
    with Session(engine) as sess:
        stmt = (select(MeetingMinutes, Student, Report)
                .join(Student, MeetingMinutes.student_id == Student.id)
                .join(Report, MeetingMinutes.report_id == Report.id, isouter=True)
                .where(MeetingMinutes.id == minutes_id))
        row = sess.execute(stmt).first()
        if not row:
            return None
        mm, student, report = row
        return {
            "id": mm.id,
            "student_id": mm.student_id,
            "student_name": student.name,
            "student_grade": student.grade or "",
            "student_gender": student.gender or "",
            "report_id": mm.report_id,
            "report_date": report.report_date.isoformat() if report and report.report_date else None,
            "transcript_text": mm.transcript_text or "",
            "minutes_text": mm.minutes_text or "",
            "minutes_json": mm.minutes_json,
            "created_at": mm.created_at.isoformat() if mm.created_at else None,
            "updated_at": mm.updated_at.isoformat() if mm.updated_at else None,
        }


def get_minutes_by_student(student_id: int) -> List[Dict[str, Any]]:
    """List all meeting minutes for a student, ordered by created_at desc.
    Includes related report date if available, and a preview of minutes_text.
    """
    with Session(engine) as sess:
        stmt = (select(MeetingMinutes, Report)
                .join(Report, MeetingMinutes.report_id == Report.id, isouter=True)
                .where(MeetingMinutes.student_id == student_id)
                .order_by(MeetingMinutes.created_at.desc()))
        rows = sess.execute(stmt).all()
        results = []
        for mm, report in rows:
            mt = mm.minutes_text or ""
            preview = mt[:120] + ("…" if len(mt) > 120 else "")
            results.append({
                "id": mm.id,
                "student_id": mm.student_id,
                "report_id": mm.report_id,
                "report_date": report.report_date.isoformat() if report and report.report_date else None,
                "preview": preview,
                "created_at": mm.created_at.isoformat() if mm.created_at else None,
                "updated_at": mm.updated_at.isoformat() if mm.updated_at else None,
            })
        return results


def get_minutes_by_report(report_id: int) -> List[Dict[str, Any]]:
    """List meeting minutes linked to a specific report, ordered by created_at desc."""
    with Session(engine) as sess:
        stmt = select(MeetingMinutes).where(MeetingMinutes.report_id == report_id).order_by(
            MeetingMinutes.created_at.desc())
        rows = sess.execute(stmt).all()
        results = []
        for row in rows:
            mm = row[0]
            mt = mm.minutes_text or ""
            preview = mt[:120] + ("…" if len(mt) > 120 else "")
            results.append({
                "id": mm.id,
                "student_id": mm.student_id,
                "report_id": mm.report_id,
                "preview": preview,
                "created_at": mm.created_at.isoformat() if mm.created_at else None,
                "updated_at": mm.updated_at.isoformat() if mm.updated_at else None,
            })
        return results


def update_minutes(minutes_id: int, **fields) -> None:
    """Update meeting minutes fields. Sets updated_at automatically."""
    if not fields:
        return
    fields["updated_at"] = datetime.utcnow()
    with Session(engine) as sess:
        sess.execute(update(MeetingMinutes).where(MeetingMinutes.id == minutes_id).values(**fields))
        sess.commit()


def delete_minutes(minutes_id: int) -> None:
    """Delete a meeting minutes record."""
    with Session(engine) as sess:
        sess.execute(delete(MeetingMinutes).where(MeetingMinutes.id == minutes_id))
        sess.commit()


# ─── E4 Mapping CRUD (multi-dim) ───────────────────────────────

def get_e4_mapping() -> Dict[str, List[Dict[str, str]]]:
    """读取全部 Y4→E4 映射。返回 {code: [{e4_dim, e4_sub}, ...]}。

    一个 code 可映射到多个 E4 维度。
    """
    with Session(engine) as sess:
        rows = sess.execute(select(E4Mapping)).all()
        result: Dict[str, List[Dict[str, str]]] = {}
        for r in rows:
            m = r[0]
            result.setdefault(m.code, []).append({
                "e4_dim": m.e4_dim,
                "e4_sub": m.e4_sub or "",
            })
        return result


def save_e4_mapping(entries: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, str]]]:
    """保存映射指认。entry: {code, e4_dims: [{e4_dim, e4_sub}, ...]}。

    对每个 code：
    - 先删除该 code 的所有旧行
    - 再按 e4_dims 列表逐行插入（e4_sub 可空）
    - e4_dims 为空列表表示删除该 code 的全部映射
    """
    with Session(engine) as sess:
        for e in entries:
            code = str(e.get("code", "")).strip()
            if not code:
                continue
            # 先删除该 code 的所有旧行
            sess.execute(delete(E4Mapping).where(E4Mapping.code == code))
            dims = e.get("e4_dims") or []
            for d in dims:
                dim = (d.get("e4_dim") or "").strip()
                if not dim:
                    continue
                sub = (d.get("e4_sub") or "").strip()
                sess.execute(insert(E4Mapping).values(
                    code=code, e4_dim=dim, e4_sub=sub or None,
                    updated_at=datetime.utcnow()))
        sess.commit()
    return get_e4_mapping()


# ─── 6AM CRUD ──────────────────────────────────────────────────

def _six_am_profile_row(m: "SixAmProfile") -> Dict[str, Any]:
    return {
        "id": m.id,
        "student_id": m.student_id,
        "report_id": m.report_id,
        "profile_json": m.profile_json,
        "version": m.version,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def add_six_am_profile(student_id: int, report_id: int, profile_json: str,
                       version: int = 1) -> int:
    """插入一条 6AM 档案（每次重跑插入新行）。Returns profile id."""
    with Session(engine) as sess:
        result = sess.execute(insert(SixAmProfile).values(
            student_id=student_id, report_id=report_id,
            profile_json=profile_json, version=version))
        sess.commit()
        return result.lastrowid


def get_six_am_profile(profile_id: int) -> Optional[Dict[str, Any]]:
    with Session(engine) as sess:
        m = sess.get(SixAmProfile, profile_id)
        return _six_am_profile_row(m) if m else None


def get_latest_six_am_profile(report_id: int) -> Optional[Dict[str, Any]]:
    """取该报告最新版本档案（version 最大；并列取 id 最大）。"""
    with Session(engine) as sess:
        stmt = (select(SixAmProfile).where(SixAmProfile.report_id == report_id)
                .order_by(SixAmProfile.version.desc(), SixAmProfile.id.desc()).limit(1))
        m = sess.execute(stmt).scalars().first()
        return _six_am_profile_row(m) if m else None


def get_six_am_profiles_by_student(student_id: int) -> List[Dict[str, Any]]:
    """该学生全部档案（version 降序）。"""
    with Session(engine) as sess:
        stmt = (select(SixAmProfile).where(SixAmProfile.student_id == student_id)
                .order_by(SixAmProfile.version.desc(), SixAmProfile.id.desc()))
        return [_six_am_profile_row(m) for m in sess.execute(stmt).scalars().all()]


def get_six_am_report_ids() -> List[int]:
    """存在 6AM 档案的 report_id 去重列表（沙盒"全部学生"用）。"""
    with Session(engine) as sess:
        rows = sess.execute(select(SixAmProfile.report_id).distinct()).scalars().all()
        return [int(r) for r in rows if r]


def update_six_am_profile_json(profile_id: int, profile_json: str,
                               session: Optional[Session] = None) -> bool:
    """就地更新指定档案的 profile_json（不新建版本，不改 version / created_at）。

    用于人工行动修订落库；记录不存在返回 False。
    默认自建 Session 并提交；传入 ``session`` 时只执行 update、不提交，
    供迁移脚本在一个事务中批量覆盖。
    """
    stmt = (update(SixAmProfile).where(SixAmProfile.id == int(profile_id))
            .values(profile_json=profile_json))
    if session is not None:
        return session.execute(stmt).rowcount > 0
    with Session(engine) as sess:
        result = sess.execute(stmt)
        sess.commit()
        return result.rowcount > 0


def _six_am_rv_row(m: "SixAmRuleVersion") -> Dict[str, Any]:
    return {
        "id": m.id,
        "label": m.label,
        "status": m.status,
        "params_json": m.params_json,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "published_at": m.published_at.isoformat() if m.published_at else None,
    }


def list_six_am_rule_versions() -> List[Dict[str, Any]]:
    with Session(engine) as sess:
        stmt = select(SixAmRuleVersion).order_by(SixAmRuleVersion.id.desc())
        return [_six_am_rv_row(m) for m in sess.execute(stmt).scalars().all()]


def get_six_am_rule_version(vid: int) -> Optional[Dict[str, Any]]:
    with Session(engine) as sess:
        m = sess.get(SixAmRuleVersion, vid)
        return _six_am_rv_row(m) if m else None


def save_six_am_rule_version(label: str, params_json: str) -> int:
    """新建 draft 版本。Returns version id."""
    with Session(engine) as sess:
        result = sess.execute(insert(SixAmRuleVersion).values(
            label=label, status="draft", params_json=params_json))
        sess.commit()
        return result.lastrowid


def publish_six_am_rule_version(vid: int) -> None:
    """发布：目标 → published；其余 published → archived（唯一 published 不变式）。"""
    with Session(engine) as sess:
        sess.execute(update(SixAmRuleVersion)
                     .where(SixAmRuleVersion.status == "published")
                     .values(status="archived"))
        sess.execute(update(SixAmRuleVersion).where(SixAmRuleVersion.id == vid)
                     .values(status="published", published_at=datetime.utcnow()))
        sess.commit()


def delete_six_am_rule_version(vid: int) -> None:
    """删除 draft 版本（published/archived 不在此列，由发布链路管理）。"""
    with Session(engine) as sess:
        sess.execute(delete(SixAmRuleVersion).where(SixAmRuleVersion.id == vid,
                                                     SixAmRuleVersion.status == "draft"))
        sess.commit()


# ─── 6AM 团队评议 / 概览 ────────────────────────────────────────

def _six_am_review_row(m: "SixAmReview") -> Dict[str, Any]:
    return {
        "id": m.id,
        "profile_id": m.profile_id,
        "report_id": m.report_id,
        "dim": m.dim,
        "verdict": m.verdict,
        "adjusted_state": m.adjusted_state,
        "note": m.note or "",
        "owner": m.owner or "",
        "due_date": m.due_date or "",
        "author": m.author or "",
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def add_six_am_review(**fields: Any) -> Dict[str, Any]:
    """追加一条团队评议（不改档案、不新增版本）。Returns review row."""
    with Session(engine) as sess:
        result = sess.execute(insert(SixAmReview).values(**fields))
        sess.commit()
        m = sess.get(SixAmReview, result.lastrowid)
        return _six_am_review_row(m)


def latest_six_am_reviews(profile_id: int) -> Dict[str, Dict[str, Any]]:
    """该档案每个维度最新的一条评议（{dim: row}）。"""
    with Session(engine) as sess:
        stmt = (select(SixAmReview).where(SixAmReview.profile_id == int(profile_id))
                .order_by(SixAmReview.id.desc()))
        rows = sess.execute(stmt).scalars().all()
    out: Dict[str, Dict[str, Any]] = {}
    for m in rows:
        out.setdefault(m.dim, _six_am_review_row(m))
    return out


def list_latest_six_am_profiles(advisor_scope: Optional[str] = None) -> List[Dict[str, Any]]:
    """每个学生最新报告的最新档案，附学生与报告信息（概览页用）。

    advisor_scope 非 None 时只返回 advisor_name 匹配的学生。
    """
    with Session(engine) as sess:
        stmt = (select(SixAmProfile, Student.name, Student.grade, Student.advisor_name,
                       Report.report_date)
                .join(Student, Student.id == SixAmProfile.student_id)
                .join(Report, Report.id == SixAmProfile.report_id))
        if advisor_scope is not None:
            stmt = stmt.where(Student.advisor_name == advisor_scope)
        rows = sess.execute(stmt).all()
    best: Dict[int, Any] = {}
    for m, name, grade, advisor_name, report_date in rows:
        key = (report_date or date.min, m.report_id, m.version or 0, m.id)
        cur = best.get(m.student_id)
        if cur is None or key > cur[0]:
            best[m.student_id] = (key, m, name, grade, advisor_name, report_date)
    out: List[Dict[str, Any]] = []
    for _key, m, name, grade, advisor_name, report_date in best.values():
        row = _six_am_profile_row(m)
        row.update({"name": name or "", "grade": grade or "",
                    "advisor_name": advisor_name or "",
                    "report_date": report_date.isoformat() if report_date else None})
        out.append(row)
    return sorted(out, key=lambda r: (r.get("name") or "", r.get("student_id") or 0))


def list_students_latest_report(advisor_scope: Optional[str] = None) -> List[Dict[str, Any]]:
    """每个学生 + 其最新报告（按 report_date、id）；无报告的学生 report_id 为 None。

    advisor_scope 非 None 时只返回 advisor_name 匹配的学生。6AM 总览与全部生成用。
    """
    with Session(engine) as sess:
        stmt = (select(Student.id, Student.name, Student.grade, Report.id, Report.report_date)
                .select_from(Student)
                .join(Report, Report.student_id == Student.id, isouter=True))
        if advisor_scope is not None:
            stmt = stmt.where(Student.advisor_name == advisor_scope)
        rows = sess.execute(stmt).all()
    best: Dict[int, Dict[str, Any]] = {}
    for sid, name, grade, rid, rdate in rows:
        cur = best.get(sid)
        key = (rdate or date.min, rid or 0)
        if cur is None or (rid is not None and key > cur["_key"]):
            best[sid] = {"_key": key, "student_id": sid, "name": name or "",
                         "grade": grade or "", "report_id": rid,
                         "report_date": rdate.isoformat() if rdate else None}
    out = []
    for row in best.values():
        row.pop("_key", None)
        out.append(row)
    return sorted(out, key=lambda r: (r["name"], r["student_id"]))


def get_previous_six_am_profile(profile_id: int) -> Optional[Dict[str, Any]]:
    """同一报告的上一版档案（version 次小）；无上一版返回 None。"""
    with Session(engine) as sess:
        m = sess.get(SixAmProfile, int(profile_id)) if profile_id else None
        if not m:
            return None
        stmt = (select(SixAmProfile)
                .where(SixAmProfile.report_id == m.report_id,
                       SixAmProfile.version < m.version)
                .order_by(SixAmProfile.version.desc(), SixAmProfile.id.desc()).limit(1))
        prev = sess.execute(stmt).scalars().first()
        return _six_am_profile_row(prev) if prev else None


# ─── Dashboard aggregation ─────────────────────────────────────

def _normalize_name(name: str) -> str:
    """规范化顾问名:小写 + 折叠空白 + 去常见标点。用于相似名检测。"""
    import re
    if not name:
        return ""
    s = str(name).lower().strip()
    # 折叠内部空白
    s = re.sub(r"\s+", "", s)
    # 移除常见中英文标点
    s = re.sub(r"[·・.,，。!！?？'\"`()（）\[\]【】]", "", s)
    return s


def _levenshtein_ratio(a: str, b: str) -> float:
    """计算两个字符串的相似度 (0-1),基于 Levenshtein 距离。"""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    la, lb = len(a), len(b)
    dp = list(range(lb + 1))
    for i in range(1, la + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, lb + 1):
            tmp = dp[j]
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + cost)
            prev = tmp
    dist = dp[lb]
    return 1.0 - dist / max(la, lb)


_WEAK_GRADES = {"偏低", "明显偏低", "严重偏低", "需关注", "需特殊关注"}
_DIMS = ["心力", "精力", "学习力", "生涯力"]


def _is_weak_item(item: Dict[str, Any]) -> bool:
    """启发式弱项判定。"""
    sg = str(item.get("score_grade") or "").strip()
    if sg in _WEAK_GRADES:
        return True
    # value < mean * 0.85
    v = item.get("value")
    m = item.get("mean")
    try:
        vf = float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        vf = None
    try:
        mf = float(m) if m is not None and m != "" else None
    except (TypeError, ValueError):
        mf = None
    if vf is not None and mf is not None and mf > 0 and vf < mf * 0.85:
        return True
    # percentile < 40
    p = item.get("percentile")
    try:
        pf = float(p) if p is not None and p != "" else None
    except (TypeError, ValueError):
        pf = None
    if pf is not None and pf < 40:
        return True
    return False


_SCHOOL_SUFFIXES = ("国际学校", "国际", "实验学校", "实验", "中学", "学校", "分校", "校区", "外国语学校", "外国语")


def _normalize_school(name: str) -> str:
    """学校名归一化：小写 + 去空格 + 去常见后缀。"""
    s = (name or "").strip().lower().replace(" ", "")
    for suf in _SCHOOL_SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf):
            s = s[: -len(suf)]
    return s


def _cluster_by_substring(raw_names: list) -> dict:
    """按子串关系聚类：短名是长名的子串 → 合并到短名。

    返回 {raw_name: cluster_key} 映射，cluster_key 为归一化后的代表名。
    """
    from collections import Counter

    norm_map: Dict[str, list] = {}
    for name in raw_names:
        if not name:
            continue
        key = _normalize_school(name)
        norm_map.setdefault(key, []).append(name)

    keys = sorted(norm_map.keys(), key=len)
    key_to_canon: Dict[str, str] = {}
    used: set = set()
    for k in keys:
        if k in used:
            continue
        key_to_canon[k] = k
        for other in keys:
            if other == k or other in used:
                continue
            if k in other:
                key_to_canon[other] = k
                used.add(other)
        used.add(k)

    result = {}
    for key, names in norm_map.items():
        canon = key_to_canon.get(key, key)
        for name in names:
            result[name] = canon
    return result


def get_dashboard_stats() -> Dict[str, Any]:
    """聚合全部仪表盘统计数据。空数据时返回零值,不报错。"""
    # 延迟导入避免循环依赖
    try:
        from evaluation_rules import dimension_of
    except Exception:
        dimension_of = lambda item: "学习力"  # fallback

    with Session(engine) as sess:
        total_students = sess.execute(select(func.count(Student.id))).scalar() or 0
        total_reports = sess.execute(select(func.count(Report.id))).scalar() or 0
        total_subtests = total_reports * 4

        # ── 学生构成 ──
        gender_rows = sess.execute(
            select(Student.gender, func.count(Student.id))
            .group_by(Student.gender)
        ).all()
        by_gender = [{"label": (g or "未填"), "count": c} for g, c in gender_rows]

        grade_rows = sess.execute(
            select(Student.grade, func.count(Student.id))
            .group_by(Student.grade)
        ).all()
        by_grade = [{"label": (g or "未填"), "count": c} for g, c in grade_rows]

        # ── 学校:从 report.data_json 提取(OCR 数据) + 归一化聚类 ──
        from collections import Counter
        report_school_rows = sess.execute(
            select(Report.data_json, Student.school)
            .select_from(Student)
            .join(Report, Report.student_id == Student.id, isouter=True)
        ).all()
        raw_schools = []
        for dj, stu_school in report_school_rows:
            try:
                data = json.loads(dj) if dj else {}
            except Exception:
                data = {}
            sch = (data.get("student") or {}).get("school") or stu_school or ""
            if sch:
                raw_schools.append(sch)
        cluster_map = _cluster_by_substring(raw_schools)
        school_counts: Counter = Counter()
        canon_to_display: Dict[str, str] = {}
        for raw in raw_schools:
            canon = cluster_map.get(raw, _normalize_school(raw))
            school_counts[canon] += 1
            if canon not in canon_to_display:
                canon_to_display[canon] = raw
        by_school = [{"label": canon_to_display.get(c, c), "count": n}
                     for c, n in school_counts.most_common()]

        # ── 顾问产出(同时取 students + bookings) ──
        # 按 students.advisor_name 聚合 report_count
        advisor_report = sess.execute(
            select(Student.advisor_name, func.count(Report.id))
            .select_from(Student)
            .join(Report, Report.student_id == Student.id, isouter=True)
            .where(Student.advisor_name != None, Student.advisor_name != "")
            .group_by(Student.advisor_name)
        ).all()
        advisor_report_map = {a: c for a, c in advisor_report}

        # 按 students.advisor_name 聚合 student_count
        advisor_student = sess.execute(
            select(Student.advisor_name, func.count(Student.id))
            .where(Student.advisor_name != None, Student.advisor_name != "")
            .group_by(Student.advisor_name)
        ).all()
        advisor_student_map = {a: c for a, c in advisor_student}

        # 从 bookings 补充(取不在 students 里的顾问名)
        booking_advisor = sess.execute(
            select(Booking.advisor_name, func.count(Booking.id))
            .where(Booking.advisor_name != None, Booking.advisor_name != "")
            .group_by(Booking.advisor_name)
        ).all()
        booking_advisor_map = {a: c for a, c in booking_advisor}

        # 合并顾问列表（按 _normalize_name 归一化合并大小写/标点差异）
        all_raw_names = set(advisor_report_map.keys()) | set(advisor_student_map.keys()) | set(booking_advisor_map.keys())
        # raw_name → normalized key
        name_norm_map = {name: _normalize_name(name) for name in all_raw_names if name}
        # normalized key → 展示名（取最长原始名）
        norm_to_display: Dict[str, str] = {}
        # 按 normalized key 聚合各计数
        norm_report: Dict[str, int] = {}
        norm_student: Dict[str, int] = {}
        norm_booking: Dict[str, int] = {}
        for name in all_raw_names:
            if not name:
                continue
            nk = name_norm_map[name]
            if nk not in norm_to_display or len(name) > len(norm_to_display[nk]):
                norm_to_display[nk] = name
            norm_report[nk] = norm_report.get(nk, 0) + advisor_report_map.get(name, 0)
            norm_student[nk] = norm_student.get(nk, 0) + advisor_student_map.get(name, 0)
            norm_booking[nk] = norm_booking.get(nk, 0) + booking_advisor_map.get(name, 0)
        advisor_performance = []
        for nk, display_name in norm_to_display.items():
            advisor_performance.append({
                "advisor_name": display_name,
                "report_count": norm_report.get(nk, 0),
                "student_count": norm_student.get(nk, 0),
                "booking_count": norm_booking.get(nk, 0),
            })
        # 按报告数降序
        advisor_performance.sort(key=lambda x: (x["report_count"], x["student_count"]), reverse=True)

        # ── 相似名检测 ──
        # 规范化分组
        norm_groups: Dict[str, list] = {}
        for name in all_raw_names:
            nk = _normalize_name(name)
            norm_groups.setdefault(nk, []).append(name)
        advisor_name_review = []
        for nk, originals in norm_groups.items():
            distinct = list(set(originals))
            if len(distinct) > 1:
                advisor_name_review.append({
                    "canonical": sorted(distinct, key=len)[-1],  # 取最长作为建议 canonical
                    "variants": distinct,
                    "reason": "大小写/空格/标点差异",
                    "suggestion": f"疑似同一顾问的不同写法,建议合并为 {sorted(distinct, key=len)[-1]}",
                })
        # 不同规范名间的 Levenshtein 相似度
        norm_keys = list(norm_groups.keys())
        for i in range(len(norm_keys)):
            for j in range(i + 1, len(norm_keys)):
                a, b = norm_keys[i], norm_keys[j]
                if not a or not b:
                    continue
                sim = _levenshtein_ratio(a, b)
                if 0.7 < sim < 1.0:
                    oa = norm_groups[a]
                    ob = norm_groups[b]
                    all_variants = list(set(oa + ob))
                    advisor_name_review.append({
                        "canonical": sorted(all_variants, key=len)[-1],
                        "variants": all_variants,
                        "reason": f"书写相似(相似度 {sim:.2f})",
                        "suggestion": f"名称写法相近,可能为同一顾问,请确认是否合并为 {sorted(all_variants, key=len)[-1]}",
                    })

        # ── 维度趋势 ──
        report_rows = sess.execute(
            select(Report, Student).join(Student, Report.student_id == Student.id)
        ).all()
        dim_weak_counts = {d: 0 for d in _DIMS}
        weak_indicator_counts: Dict[str, Dict] = {}  # code -> {label, dim, count}
        student_dim_weak: Dict[int, set] = {}  # student_id -> set of weak dims
        timeline_map: Dict[str, Dict] = {}

        for report, student in report_rows:
            sid = student.id
            student_dim_weak.setdefault(sid, set())
            try:
                data = json.loads(report.data_json) if report.data_json else {}
            except Exception:
                data = {}
            items = data.get("schema_124") or []
            for item in items:
                dim = dimension_of(item)
                if dim not in _DIMS:
                    continue
                if _is_weak_item(item):
                    student_dim_weak[sid].add(dim)
                    code = str(item.get("code", ""))
                    if code and code not in weak_indicator_counts:
                        weak_indicator_counts[code] = {
                            "code": code,
                            "label": item.get("label", ""),
                            "dim": dim,
                            "count": 0,
                        }
                    if code in weak_indicator_counts:
                        weak_indicator_counts[code]["count"] += 1
            # 时间线
            rd = report.report_date
            if rd:
                mkey = f"{rd.year:04d}-{rd.month:02d}"
                if mkey not in timeline_map:
                    timeline_map[mkey] = {"report_count": 0, "students": set()}
                timeline_map[mkey]["report_count"] += 1
                timeline_map[mkey]["students"].add(sid)

        for sid, dims in student_dim_weak.items():
            for d in dims:
                dim_weak_counts[d] = dim_weak_counts.get(d, 0) + 1

        # 高频弱项 Top 5
        weak_top = sorted(weak_indicator_counts.values(), key=lambda x: x["count"], reverse=True)[:5]

        # 跨维度共现矩阵 4x4
        co_weak = [[0] * len(_DIMS) for _ in range(len(_DIMS))]
        for sid, dims in student_dim_weak.items():
            dim_list = list(dims)
            for i in range(len(dim_list)):
                for j in range(i, len(dim_list)):
                    a = _DIMS.index(dim_list[i])
                    b = _DIMS.index(dim_list[j])
                    co_weak[a][b] += 1
                    if a != b:
                        co_weak[b][a] += 1

        # 时间线排序
        timeline = []
        for mk in sorted(timeline_map.keys()):
            v = timeline_map[mk]
            timeline.append({
                "month": mk,
                "report_count": v["report_count"],
                "student_count": len(v["students"]),
            })

        # 报告日期范围
        date_range = sess.execute(
            select(func.min(Report.report_date), func.max(Report.report_date))
        ).first()
        earliest_date = date_range[0].isoformat() if date_range and date_range[0] else None
        latest_date = date_range[1].isoformat() if date_range and date_range[1] else None

        # ── 要点卡片数据 ──
        # 主导年级
        most_common_grade = max(by_grade, key=lambda x: x["count"])["label"] if by_grade else "-"
        most_common_grade_count = max(by_grade, key=lambda x: x["count"])["count"] if by_grade else 0
        # 最活跃顾问
        top_advisor = advisor_performance[0]["advisor_name"] if advisor_performance and advisor_performance[0]["report_count"] > 0 else "-"
        top_advisor_count = advisor_performance[0]["report_count"] if advisor_performance else 0
        # 最常见薄弱维度
        weakest_dim = "-"
        weakest_dim_count = 0
        if any(dim_weak_counts.values()):
            weakest_dim = max(dim_weak_counts, key=lambda k: dim_weak_counts[k])
            weakest_dim_count = dim_weak_counts[weakest_dim]

        return {
            "headline": {
                "total_students": total_students,
                "total_reports": total_reports,
                "subtests_per_report": 4,
                "total_subtests": total_subtests,
            },
            "highlights": {
                "most_common_grade": most_common_grade,
                "most_common_grade_count": most_common_grade_count,
                "top_advisor": top_advisor,
                "top_advisor_count": top_advisor_count,
                "weakest_dim": weakest_dim,
                "weakest_dim_count": weakest_dim_count,
                "earliest_date": earliest_date,
                "latest_date": latest_date,
            },
            "student_makeup": {
                "by_gender": by_gender,
                "by_grade": by_grade,
                "by_school": by_school,
            },
            "advisor_performance": advisor_performance,
            "advisor_name_review": advisor_name_review,
            "dimension_trends": {
                "dims": _DIMS,
                "weak_counts": dim_weak_counts,
                "weak_pct": {d: round((dim_weak_counts.get(d, 0) / total_students * 100), 1) if total_students else 0 for d in _DIMS},
                "weak_top": weak_top,
                "co_weak": co_weak,
                "total_students_with_reports": len(student_dim_weak),
            },
            "timeline": timeline,
            "feedback_placeholder": {
                "available": False,
                "note": "学生反馈数据接入后将在此展示",
            },
        }


def get_indicator_aggregates() -> Dict[str, Any]:
    """聚合所有报告的指标数据,用 evaluation_rules 推导有效评价。

    返回每个指标的:code, label, dim, avg_value, most_common_eval, weak_count, total_count, weak_pct。
    以及按维度分组和按弱项频率排序的列表。
    """
    from collections import Counter
    try:
        from evaluation_rules import (
            dimension_of, derive_evaluation, _find_norm,
            _to_number, _code_int, build_evaluation_view,
        )
    except Exception:
        return {"all_indicators": [], "by_dimension": {}, "most_frequently_weak": []}

    weak_evals = {"偏低", "明显偏低", "严重偏低", "需关注", "需特殊关注"}

    with Session(engine) as sess:
        report_rows = sess.execute(
            select(Report).order_by(Report.created_at)
        ).all()

        indicators: Dict[str, Dict[str, Any]] = {}

        for row in report_rows:
            report = row[0]
            try:
                data = json.loads(report.data_json) if report.data_json else {}
            except Exception:
                data = {}
            items = data.get("schema_124") or []

            # 用 build_evaluation_view 拿到含规则推导 + 档位 fallback 的 eval_value
            eval_items, _ = build_evaluation_view(items)
            eval_map: Dict[str, str] = {}
            for ei in eval_items:
                c = str(ei.get("code", ""))
                if c and ei.get("eval_value"):
                    eval_map[c] = ei["eval_value"]

            for item in items:
                code = str(item.get("code", ""))
                if not code:
                    continue
                label = item.get("label", "") or ""
                value = item.get("value")
                dim = dimension_of(item)

                # 优先用 build_evaluation_view 的结果（含档位 fallback）
                eval_val = eval_map.get(code)
                rule_note = None
                if not eval_val:
                    norm = _find_norm(items, _code_int(code))
                    eval_val, rule_note = derive_evaluation(code, label, value, norm)

                if code not in indicators:
                    indicators[code] = {
                        "code": code,
                        "label": label,
                        "dim": dim,
                        "values": [],
                        "evals": [],
                        "weak_count": 0,
                        "total_count": 0,
                        "rule_note": rule_note or "",
                    }
                ind = indicators[code]
                ind["total_count"] += 1
                num = _to_number(value)
                if num is not None:
                    ind["values"].append(num)
                if eval_val:
                    ind["evals"].append(eval_val)
                    if eval_val in weak_evals:
                        ind["weak_count"] += 1

        all_indicators = []
        for code, ind in sorted(indicators.items()):
            avg_value = round(sum(ind["values"]) / len(ind["values"]), 1) if ind["values"] else None
            eval_counter = Counter(ind["evals"])
            most_common_eval = eval_counter.most_common(1)[0][0] if eval_counter else None
            weak_pct = round(ind["weak_count"] / ind["total_count"] * 100, 1) if ind["total_count"] else 0
            all_indicators.append({
                "code": code,
                "label": ind["label"],
                "dim": ind["dim"],
                "avg_value": avg_value,
                "most_common_eval": most_common_eval,
                "weak_count": ind["weak_count"],
                "total_count": ind["total_count"],
                "weak_pct": weak_pct,
                "rule_note": ind["rule_note"],
            })

        by_dimension: Dict[str, List] = {}
        for ind in all_indicators:
            by_dimension.setdefault(ind["dim"], []).append(ind)

        most_frequently_weak = sorted(
            [i for i in all_indicators if i["weak_pct"] > 0],
            key=lambda x: x["weak_pct"], reverse=True,
        )[:15]

        dimension_summary = {}
        for dim in _DIMS:
            inds = by_dimension.get(dim, [])
            weak_inds = [i for i in inds if i["weak_pct"] > 0]
            weak_names = sorted(weak_inds, key=lambda x: x["weak_pct"], reverse=True)[:3]
            dim_total = len(inds)
            dim_weak = len(weak_inds)
            dim_weak_pct = round(dim_weak / dim_total * 100, 1) if dim_total else 0
            dimension_summary[dim] = {
                "total": dim_total,
                "weak": dim_weak,
                "weak_pct": dim_weak_pct,
                "healthy_pct": round(100 - dim_weak_pct, 1),
                "weak_names": [n["label"] for n in weak_names],
            }

        return {
            "all_indicators": all_indicators,
            "by_dimension": by_dimension,
            "most_frequently_weak": most_frequently_weak,
            "dimension_summary": dimension_summary,
        }


def get_indicator_distributions() -> Dict[str, Any]:
    """各维度的指标评价分布:高/不低/偏低/需关注各多少,及弱项/强项名称。"""
    agg = get_indicator_aggregates()
    all_inds = agg.get("all_indicators", [])
    by_dim = agg.get("by_dimension", {})

    result = {}
    for dim in _DIMS:
        inds = by_dim.get(dim, [])
        dist = {}
        weak_list = []
        strong_list = []
        for ind in inds:
            ev = ind.get("most_common_eval")
            if not ev:
                continue
            dist[ev] = dist.get(ev, 0) + 1
            if ind.get("weak_pct", 0) > 0:
                weak_list.append({
                    "label": ind["label"],
                    "weak_pct": ind["weak_pct"],
                })
            if ev in ("高", "较高", "较好"):
                strong_list.append({
                    "label": ind["label"],
                    "avg_value": ind.get("avg_value"),
                })
        weak_list.sort(key=lambda x: x["weak_pct"], reverse=True)
        strong_list.sort(key=lambda x: x.get("avg_value") or 0, reverse=True)
        result[dim] = {
            "total": len(inds),
            "evaluated": sum(dist.values()),
            "distribution": dist,
            "weak_indicators": weak_list[:5],
            "strong_indicators": strong_list[:5],
        }
    return result


def report_dimension_health(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """一份报告 schema_124 的四维健康度:{维度: {healthy, weak_count, total}}。

    get_student_profiles 与学生档案页共用同一份计算(healthy = 非偏弱指标占比)。
    """
    from evaluation_rules import (
        dimension_of, derive_evaluation, _find_norm,
        _code_int, build_evaluation_view,
    )

    weak_evals = {"偏低", "明显偏低", "严重偏低", "需关注", "需特殊关注"}

    # 用 build_evaluation_view 拿到含规则推导 + 档位 fallback 的 eval_value
    eval_items, _ = build_evaluation_view(items)
    eval_map: Dict[str, str] = {}
    for ei in eval_items:
        c = str(ei.get("code", ""))
        if c and ei.get("eval_value"):
            eval_map[c] = ei["eval_value"]

    dim_stats = {d: {"weak": 0, "total": 0} for d in _DIMS}
    for item in items:
        code = str(item.get("code", ""))
        if not code:
            continue
        dim = dimension_of(item)
        if dim not in _DIMS:
            continue
        # 优先用 build_evaluation_view 的结果（含档位 fallback）
        ev = eval_map.get(code)
        if not ev:
            norm = _find_norm(items, _code_int(code))
            ev, _ = derive_evaluation(code, item.get("label", ""), item.get("value"), norm)
        dim_stats[dim]["total"] += 1
        if ev and ev in weak_evals:
            dim_stats[dim]["weak"] += 1

    dims = {}
    for d in _DIMS:
        ds = dim_stats[d]
        healthy = round((1 - ds["weak"] / ds["total"]) * 100, 1) if ds["total"] else 100.0
        dims[d] = {
            "healthy": healthy,
            "weak_count": ds["weak"],
            "total": ds["total"],
        }
    return dims


def get_student_profiles() -> List[Dict[str, Any]]:
    """每个学生的四维健康度侧写,用于个体对比。"""
    try:
        import evaluation_rules  # noqa: F401  (不可用时与原行为一致:返回空)
    except Exception:
        return []

    with Session(engine) as sess:
        report_rows = sess.execute(
            select(Report, Student).join(Student, Report.student_id == Student.id).order_by(Report.created_at)
        ).all()

        profiles = []
        for report, student in report_rows:
            try:
                data = json.loads(report.data_json) if report.data_json else {}
            except Exception:
                data = {}
            items = data.get("schema_124") or []
            student_obj = data.get("student") or {}

            dims = report_dimension_health(items)
            health_sum = 0
            health_count = 0
            for d in _DIMS:
                if dims[d]["total"] > 0:
                    health_sum += dims[d]["healthy"]
                    health_count += 1

            overall = round(health_sum / health_count, 1) if health_count else 0

            profiles.append({
                "student_name": student_obj.get("name") or student.name or "",
                "grade": student_obj.get("grade") or student.grade or "",
                "school": student_obj.get("school") or student.school or "",
                "gender": student_obj.get("gender") or student.gender or "",
                "report_date": (report.report_date.isoformat() if report.report_date else ""),
                "dimensions": dims,
                "overall_health": overall,
            })

        if profiles:
            max_health = max(p["overall_health"] for p in profiles)
            min_health = min(p["overall_health"] for p in profiles)
            for p in profiles:
                p["is_healthiest"] = p["overall_health"] == max_health and max_health > 0
                p["is_needs_attention"] = p["overall_health"] == min_health and min_health < max_health

        return profiles


def get_dimension_correlations() -> Dict[str, Any]:
    """维度间关联强度:哪些维度经常一起偏弱。"""
    profiles = get_student_profiles()
    weak_evals = {"偏低", "明显偏低", "严重偏低", "需关注", "需特殊关注"}

    # 每个学生在哪些维度有弱项
    student_weak_dims = []
    for p in profiles:
        weak_set = set()
        for d in _DIMS:
            ds = p["dimensions"].get(d, {})
            if ds.get("weak_count", 0) > 0:
                weak_set.add(d)
        student_weak_dims.append(weak_set)

    total_students = len(student_weak_dims)

    # 维度弱项学生数
    weak_counts = {d: 0 for d in _DIMS}
    for sw in student_weak_dims:
        for d in sw:
            weak_counts[d] += 1

    # 共现矩阵
    matrix = [[0.0] * len(_DIMS) for _ in range(len(_DIMS))]
    for i in range(len(_DIMS)):
        matrix[i][i] = 1.0
        for j in range(i + 1, len(_DIMS)):
            co = sum(1 for sw in student_weak_dims if _DIMS[i] in sw and _DIMS[j] in sw)
            min_w = min(weak_counts[_DIMS[i]], weak_counts[_DIMS[j]])
            corr = co / min_w if min_w > 0 else 0.0
            matrix[i][j] = round(corr, 2)
            matrix[j][i] = round(corr, 2)

    # 维度对列表
    pairs = []
    for i in range(len(_DIMS)):
        for j in range(i + 1, len(_DIMS)):
            co = int(matrix[i][j] * min(weak_counts[_DIMS[i]], weak_counts[_DIMS[j]])) if min(weak_counts[_DIMS[i]], weak_counts[_DIMS[j]]) > 0 else 0
            corr = matrix[i][j]
            if corr > 0.6:
                strength = "强"
            elif corr > 0.3:
                strength = "中"
            else:
                strength = "弱"
            pairs.append({
                "dim_a": _DIMS[i],
                "dim_b": _DIMS[j],
                "co_weak": co,
                "correlation": corr,
                "strength": strength,
            })

    pairs.sort(key=lambda x: x["correlation"], reverse=True)

    return {
        "pairs": pairs,
        "matrix": matrix,
        "labels": _DIMS,
        "total_students": total_students,
        "weak_counts": weak_counts,
    }


def get_indicator_trends() -> Dict[str, Any]:
    """指标级趋势:最常偏弱/偏强的具体指标,附带弱项学生名单(用于悬停展开)。

    直接触及 134 个指标,而非四维汇总。
    """
    try:
        from evaluation_rules import (
            dimension_of, derive_evaluation, _find_norm,
            _to_number, _code_int, build_evaluation_view,
        )
    except Exception:
        return {"most_frequently_weak": [], "most_frequently_strong": [],
                "total_indicators_evaluated": 0, "total_with_weak": 0}

    weak_evals = {"偏低", "明显偏低", "严重偏低", "需关注", "需特殊关注"}
    strong_evals = {"高", "较好", "不低", "相对健康", "正常"}

    with Session(engine) as sess:
        report_rows = sess.execute(
            select(Report, Student).join(Student, Report.student_id == Student.id).order_by(Report.created_at)
        ).all()

        indicators: Dict[str, Dict[str, Any]] = {}

        for report, student in report_rows:
            try:
                data = json.loads(report.data_json) if report.data_json else {}
            except Exception:
                data = {}
            items = data.get("schema_124") or []
            student_obj = data.get("student") or {}
            student_name = student_obj.get("name") or student.name or "未命名"

            # 用 build_evaluation_view 拿到含规则推导 + 档位 fallback 的 eval_value
            eval_items, _ = build_evaluation_view(items)
            eval_map: Dict[str, str] = {}
            for ei in eval_items:
                c = str(ei.get("code", ""))
                if c and ei.get("eval_value"):
                    eval_map[c] = ei["eval_value"]

            for item in items:
                code = str(item.get("code", ""))
                if not code:
                    continue
                label = item.get("label", "") or ""
                dim = dimension_of(item)
                if dim not in _DIMS:
                    continue
                # 优先用 build_evaluation_view 的结果（含档位 fallback）
                ev = eval_map.get(code)
                if not ev:
                    norm = _find_norm(items, _code_int(code))
                    ev, _ = derive_evaluation(code, label, item.get("value"), norm)

                if code not in indicators:
                    indicators[code] = {
                        "code": code,
                        "label": label,
                        "dim": dim,
                        "weak_count": 0,
                        "strong_count": 0,
                        "total_count": 0,
                        "weak_students": [],
                        "strong_students": [],
                    }
                ind = indicators[code]
                ind["total_count"] += 1
                if ev and ev in weak_evals:
                    ind["weak_count"] += 1
                    if len(ind["weak_students"]) < 10:
                        ind["weak_students"].append(student_name)
                elif ev and ev in strong_evals:
                    ind["strong_count"] += 1
                    if len(ind["strong_students"]) < 10:
                        ind["strong_students"].append(student_name)

        all_inds = list(indicators.values())
        for ind in all_inds:
            ind["weak_pct"] = round(ind["weak_count"] / ind["total_count"] * 100, 1) if ind["total_count"] else 0
            ind["strong_pct"] = round(ind["strong_count"] / ind["total_count"] * 100, 1) if ind["total_count"] else 0

        most_weak = sorted(
            [i for i in all_inds if i["weak_count"] > 0],
            key=lambda x: x["weak_count"], reverse=True,
        )[:8]
        most_strong = sorted(
            [i for i in all_inds if i["strong_count"] > 0],
            key=lambda x: x["strong_count"], reverse=True,
        )[:5]

        return {
            "most_frequently_weak": most_weak,
            "most_frequently_strong": most_strong,
            "total_indicators_evaluated": len(all_inds),
            "total_with_weak": sum(1 for i in all_inds if i["weak_count"] > 0),
        }


def get_cluster_patterns() -> Dict[str, Any]:
    """学生聚类画像:按弱项维度签名(哪些维度有弱项)把学生分组。

    空签名 = balanced(无弱项)。
    """
    profiles = get_student_profiles()

    groups: Dict[frozenset, List[Dict[str, Any]]] = {}
    for p in profiles:
        weak_set = frozenset(
            d for d in _DIMS
            if p["dimensions"].get(d, {}).get("weak_count", 0) > 0
        )
        groups.setdefault(weak_set, []).append(p)

    clusters = []
    balanced_students = []
    for sig, members in groups.items():
        if not sig:
            balanced_students = [m["student_name"] for m in members]
            continue
        signature = "+".join(sorted(sig, key=lambda d: _DIMS.index(d)))
        avg_health = round(sum(m["overall_health"] for m in members) / len(members), 1) if members else 0
        clusters.append({
            "signature": signature,
            "students": [m["student_name"] for m in members],
            "count": len(members),
            "overall_health_avg": avg_health,
            "is_common": len(members) >= 2,
        })

    clusters.sort(key=lambda x: x["count"], reverse=True)

    return {
        "clusters": clusters,
        "total_students": len(profiles),
        "balanced_count": len(balanced_students),
        "balanced_students": balanced_students,
    }


def get_dimension_balance() -> Dict[str, Any]:
    """维度平衡度:每个学生四维健康度的方差,识别严重失衡型。

    balance_score = 100 * (1 - std/50),50 为四值在 [0,100] 上的近似最大标准差。
    is_imbalanced: balance_score < 60。
    """
    import statistics

    profiles = get_student_profiles()
    students = []
    for p in profiles:
        dims = p.get("dimensions", {})
        values = [dims.get(d, {}).get("healthy", 0) for d in _DIMS]
        if not any(v for v in values):
            continue
        std = statistics.pstdev(values) if len(values) > 1 else 0
        balance_score = round(max(0, 100 * (1 - std / 50)), 1)
        non_zero = [(d, v) for d, v in zip(_DIMS, values) if dims.get(d, {}).get("total", 0) > 0]
        if non_zero:
            weakest_dim, weakest_val = min(non_zero, key=lambda x: x[1])
            strongest_dim, strongest_val = max(non_zero, key=lambda x: x[1])
            gap = round(strongest_val - weakest_val, 1)
        else:
            weakest_dim = strongest_dim = ""
            gap = 0

        students.append({
            "student_name": p["student_name"],
            "grade": p.get("grade", ""),
            "dimensions": {d: dims.get(d, {}).get("healthy", 0) for d in _DIMS},
            "overall_health": p["overall_health"],
            "balance_score": balance_score,
            "is_imbalanced": balance_score < 60,
            "weakest_dim": weakest_dim,
            "strongest_dim": strongest_dim,
            "gap": gap,
        })

    avg_balance = round(sum(s["balance_score"] for s in students) / len(students), 1) if students else 0
    imbalanced_count = sum(1 for s in students if s["is_imbalanced"])

    return {
        "students": students,
        "avg_balance_score": avg_balance,
        "imbalanced_count": imbalanced_count,
    }


# ─── User CRUD（2.0 角色体系）──────────────────────────────────

VALID_ROLES = ("admin", "advisor", "viewer", "front")
VALID_STUDENT_SCOPES = ("all", "own", "none")
VALID_DETAIL_LEVELS = ("full", "summary")
# 角色默认值：(student_scope, detail_level, m1_access)
ROLE_ACCOUNT_DEFAULTS = {
    "admin": ("all", "full", 1),
    "advisor": ("own", "full", 1),
    "viewer": ("all", "summary", 0),
    # 前台只处理当日预约与账号交接，不获得任何学生档案范围
    "front": ("none", "summary", 0),
}
# 未知角色（未登录等）一律按最窄范围处理
_UNKNOWN_ROLE_ACCOUNT = ("own", "summary", 0)


def _flag01(value) -> int:
    try:
        return 1 if int(value) else 0
    except (TypeError, ValueError):
        return 0


def effective_account_settings(role, student_scope=None, detail_level=None,
                               m1_access=None, m1_admin=None) -> Dict[str, Any]:
    """角色 + 存储值 → 生效值。空值/非法值回落角色默认；admin 固定；viewer 的 M1 恒为 0。

    m1_admin（心有灵析管理）：admin 恒为 1，viewer 恒为 0；advisor 取存储值，且仅在心有灵析打开时有效。
    """
    defaults = ROLE_ACCOUNT_DEFAULTS.get(role)
    if defaults is None or role == "admin":
        scope, detail, m1 = defaults or _UNKNOWN_ROLE_ACCOUNT
        return {"student_scope": scope, "detail_level": detail, "m1_access": m1,
                "m1_admin": 1 if role == "admin" else 0}
    if m1_access in (None, ""):
        m1 = defaults[2]
    else:
        try:
            m1 = 1 if int(m1_access) else 0
        except (TypeError, ValueError):
            m1 = defaults[2]
    m1 = 0 if role in ("viewer", "front") else m1
    scope = student_scope if student_scope in VALID_STUDENT_SCOPES else defaults[0]
    if role == "front":
        scope = "none"
    return {
        "student_scope": scope,
        "detail_level": detail_level if detail_level in VALID_DETAIL_LEVELS else defaults[1],
        "m1_access": m1,
        "m1_admin": _flag01(m1_admin) if (role == "advisor" and m1 == 1) else 0,
    }


def _clean_account_settings(student_scope, detail_level, m1_access):
    """校验入参取值。None 表示未提供；"" 表示恢复角色默认值。"""
    error = "可见学生或可见内容的取值无效"
    if student_scope is not None:
        student_scope = str(student_scope).strip()
        if student_scope and student_scope not in VALID_STUDENT_SCOPES:
            raise ValueError(error)
    if detail_level is not None:
        detail_level = str(detail_level).strip()
        if detail_level and detail_level not in VALID_DETAIL_LEVELS:
            raise ValueError(error)
    if m1_access is not None and m1_access != "":
        cleaned = {True: 1, False: 0, 1: 1, 0: 0, "1": 1, "0": 0}.get(
            m1_access if isinstance(m1_access, (bool, int, str)) else None)
        if cleaned is None:
            raise ValueError(error)
        m1_access = cleaned
    return student_scope, detail_level, m1_access


def _account_values_to_store(role, advisor_name, student_scope, detail_level,
                             m1_access) -> Dict[str, Any]:
    """按角色限制得出落库值：admin 固定；own 必须有顾问姓名；viewer 的 M1 存 0。"""
    if role == "admin":
        scope, detail, m1 = ROLE_ACCOUNT_DEFAULTS["admin"]
        return {"student_scope": scope, "detail_level": detail, "m1_access": m1}
    if role == "front":
        return {"student_scope": "none", "detail_level": "summary", "m1_access": 0}
    if student_scope == "own" and not (advisor_name or "").strip():
        raise ValueError("名下学生范围需要绑定顾问姓名")
    m1 = None if m1_access in (None, "") else m1_access
    if role == "viewer" and m1 == 1:
        m1 = 0
    return {"student_scope": student_scope or "", "detail_level": detail_level or "",
            "m1_access": m1}


def _clean_m1_admin(value):
    """心有灵析管理入参：None/"" → None（未设置）；其余必须是 0/1 或布尔。"""
    if value is None or value == "":
        return None
    cleaned = {True: 1, False: 0, 1: 1, 0: 0, "1": 1, "0": 0}.get(
        value if isinstance(value, (bool, int, str)) else None)
    if cleaned is None:
        raise ValueError("心有灵析管理的取值无效")
    return cleaned


def list_user_office_ids(user_id: int) -> List[int]:
    """该账号被授权的办公室 id（升序）；未迁移库回落到 users.office_id。"""
    with Session(engine) as sess:
        try:
            rows = sess.execute(
                select(UserOffice.office_id).where(UserOffice.user_id == int(user_id))
                .order_by(UserOffice.office_id.asc())).all()
            ids = [int(r[0]) for r in rows]
        except OperationalError:
            sess.rollback()
            ids = []
        if ids:
            return ids
        legacy = sess.execute(select(User.office_id).where(User.id == int(user_id))).scalar()
        return [int(legacy)] if legacy not in (None, "") else []


def user_has_office(user_id: int, office_id) -> bool:
    if office_id in (None, ""):
        return False
    return int(office_id) in list_user_office_ids(int(user_id))


def _sync_user_offices(sess: Session, user_id: int, office_ids, primary_id=None) -> List[int]:
    """写入账号办公室授权；返回规范化后的 id 列表。

    office_ids 为 None 表示不改；空列表表示清空（前台/测评师会被上层拒绝）。
    """
    if office_ids is None:
        return list_user_office_ids(user_id)
    cleaned: List[int] = []
    for raw in office_ids:
        if raw in (None, ""):
            continue
        try:
            oid = int(raw)
        except (TypeError, ValueError):
            raise ValueError("办公室参数错误")
        if oid not in cleaned:
            cleaned.append(oid)
    if primary_id not in (None, ""):
        primary = int(primary_id)
        if primary in cleaned:
            cleaned.remove(primary)
            cleaned.insert(0, primary)
    current = {int(r[0]) for r in sess.execute(
        select(UserOffice.office_id).where(UserOffice.user_id == int(user_id))).all()}
    for oid in current - set(cleaned):
        sess.execute(delete(UserOffice).where(
            UserOffice.user_id == int(user_id), UserOffice.office_id == oid))
    for index, oid in enumerate(cleaned):
        row = sess.get(UserOffice, (int(user_id), oid))
        if row:
            row.is_default = 1 if index == 0 else 0
        else:
            sess.add(UserOffice(user_id=int(user_id), office_id=oid,
                                is_default=1 if index == 0 else 0))
    return cleaned


def set_user_offices(user_id: int, office_ids, primary_id=None) -> List[int]:
    """公开入口：设置某账号的办公室授权，并同步排班起点标记。"""
    with Session(engine) as sess:
        _lock_booking_location(sess, 0)
        user = sess.get(User, int(user_id))
        if not user:
            raise ValueError("用户不存在")
        before = {int(r[0]) for r in sess.execute(
            select(UserOffice.office_id).where(UserOffice.user_id == int(user_id))).all()}
        cleaned = _sync_user_offices(sess, int(user_id), office_ids, primary_id)
        if cleaned:
            user.office_id = cleaned[0]
        else:
            user.office_id = None
        if int(user.is_assessor or 0):
            for oid in cleaned:
                setting = sess.get(AssessorOfficeSetting, (int(user_id), oid))
                if oid not in before:
                    # 新授权办公室清理旧授权留下的未来排班记录。
                    sess.execute(delete(AssessorAvailability).where(
                        AssessorAvailability.assessor_id == int(user_id),
                        AssessorAvailability.location_id == oid,
                        AssessorAvailability.date >= date.today()))
                    if setting:
                        setting.mode = "explicit"
                    else:
                        sess.add(AssessorOfficeSetting(
                            assessor_id=int(user_id), office_id=oid, mode="explicit"))
                elif not setting:
                    sess.add(AssessorOfficeSetting(
                        assessor_id=int(user_id), office_id=oid, mode="legacy"))
        sess.commit()
        return cleaned


def list_future_assignments_for_office(assessor_id: int, office_id: int) -> List[Dict[str, Any]]:
    """撤权后需要重新安排的未来预约（仅返回待重新安排清单，不改动预约）。"""
    now = datetime.now()
    with Session(engine) as sess:
        rows = sess.execute(
            select(Booking.id, Booking.student_name, Booking.appointment_time)
            .where(Booking.assessor_id == int(assessor_id),
                   Booking.location_id == int(office_id),
                   Booking.status != "cancelled",
                   Booking.appointment_time >= now)
            .order_by(Booking.appointment_time.asc())).all()
        return [{"booking_id": r[0], "student_name": r[1],
                 "appointment_time": r[2].isoformat()} for r in rows]


def assessor_office_mode(assessor_id: int, office_id: int) -> str:
    """返回已有排班设置标记，供迁移与默认测评师配置使用。"""
    with Session(engine) as sess:
        row = sess.get(AssessorOfficeSetting, (int(assessor_id), int(office_id)))
        return row.mode if row else "explicit"


def _row_to_user_dict(u: "User") -> Dict[str, Any]:
    """User ORM 对象 → 普通 dict（避免 detached instance）。"""
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "advisor_name": u.advisor_name or "",
        "display_name": u.display_name or "",
        "is_active": int(u.is_active or 0),
        "is_assessor": int(u.is_assessor or 0),
        "office_id": u.office_id,
        "office_ids": list_user_office_ids(u.id),
        "created_at": u.created_at.isoformat() if u.created_at else None,
        **effective_account_settings(u.role, u.student_scope, u.detail_level, u.m1_access,
                                    u.m1_admin),
    }


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """按登录名查用户，返回 dict（含 password_hash，仅供内部校验用）。"""
    username = (username or "").strip()
    if not username:
        return None
    with Session(engine) as sess:
        row = sess.execute(select(User).where(User.username == username)).first()
        if not row:
            return None
        d = _row_to_user_dict(row[0])
        d["password_hash"] = row[0].password_hash
        return d


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """按 id 查用户，返回 dict（不含 password_hash）。"""
    with Session(engine) as sess:
        row = sess.execute(select(User).where(User.id == int(user_id))).first()
        return _row_to_user_dict(row[0]) if row else None


def list_users() -> List[Dict[str, Any]]:
    """列出全部用户（不含 password_hash），按创建时间升序。"""
    with Session(engine) as sess:
        rows = sess.execute(select(User).order_by(User.id.asc())).all()
        return [_row_to_user_dict(r[0]) for r in rows]


def create_user(username: str, password: str, role: str,
                advisor_name: str = "", display_name: str = "",
                student_scope: Optional[str] = None, detail_level: Optional[str] = None,
                m1_access: Any = None, m1_admin: Any = None,
                is_assessor: Any = 0, office_id: Optional[int] = None,
                office_ids: Optional[List[int]] = None) -> int:
    """创建用户，返回 id。role 必须是 VALID_ROLES 之一，username 唯一。"""
    from werkzeug.security import generate_password_hash
    username = (username or "").strip()
    role = (role or "").strip()
    if not username:
        raise ValueError("username 不能为空")
    if role not in VALID_ROLES:
        raise ValueError(f"role 必须是 {VALID_ROLES} 之一")
    if not password:
        raise ValueError("password 不能为空")
    student_scope, detail_level, m1_access = _clean_account_settings(
        student_scope, detail_level, m1_access)
    account = _account_values_to_store(role, advisor_name, student_scope, detail_level, m1_access)
    account["m1_admin"] = _clean_m1_admin(m1_admin) if role == "advisor" else None
    if role == "front":
        is_assessor = 0
    office = int(office_id) if office_id not in (None, "") else None
    authorized: List[int] = []
    if office_ids is not None:
        for raw in office_ids:
            if raw in (None, ""):
                continue
            oid = int(raw)
            if oid not in authorized:
                authorized.append(oid)
    elif office is not None:
        authorized = [office]
    if office is not None and office not in authorized:
        authorized.insert(0, office)
    if role == "front" and not authorized:
        raise ValueError("前台账号需要绑定办公室")
    if _flag01(is_assessor) and not authorized:
        raise ValueError("测评师需要绑定办公室")
    with Session(engine) as sess:
        if sess.execute(select(User).where(User.username == username)).first():
            raise ValueError(f"用户名已存在: {username}")
        stmt = insert(User).values(
            username=username,
            password_hash=generate_password_hash(password),
            role=role,
            advisor_name=advisor_name or None,
            display_name=display_name or None,
            is_active=1,
            is_assessor=_flag01(is_assessor),
            office_id=authorized[0] if authorized else None,
            **account,
        )
        result = sess.execute(stmt)
        sess.flush()
        user_id = result.inserted_primary_key[0] if result.inserted_primary_key else None
        if user_id is None:
            user_id = sess.execute(select(User.id).where(User.username == username)).scalar()
        _sync_user_offices(sess, int(user_id), authorized)
        for index, oid in enumerate(authorized):
            if _flag01(is_assessor):
                sess.add(AssessorOfficeSetting(
                    assessor_id=int(user_id), office_id=oid,
                    mode="legacy" if index == 0 else "explicit"))
        sess.commit()
        return int(user_id)


def update_user(user_id: int, password: Optional[str] = None,
                role: Optional[str] = None, advisor_name: Optional[str] = None,
                display_name: Optional[str] = None,
                is_active: Optional[int] = None,
                student_scope: Optional[str] = None, detail_level: Optional[str] = None,
                m1_access: Any = None, m1_admin: Any = None,
                is_assessor: Any = None, office_id: Any = None,
                office_ids: Optional[List[int]] = None) -> bool:
    """更新用户可控字段（改密/改角色/停用/改名/可见范围/测评师）。返回是否更新成功。

    可见范围三项：None 不改，"" 恢复角色默认值。改角色且未同时提供时恢复新角色的默认值，
    避免原角色的范围（如 admin 的全部 + 完整）被带到新角色。
    """
    student_scope, detail_level, m1_access = _clean_account_settings(
        student_scope, detail_level, m1_access)
    m1_admin = _clean_m1_admin(m1_admin)
    values: Dict[str, Any] = {}
    if password:
        from werkzeug.security import generate_password_hash
        values["password_hash"] = generate_password_hash(password)
    if role is not None:
        if role not in VALID_ROLES:
            raise ValueError(f"role 必须是 {VALID_ROLES} 之一")
        values["role"] = role
    if advisor_name is not None:
        values["advisor_name"] = advisor_name or None
    if display_name is not None:
        values["display_name"] = display_name or None
    if is_active is not None:
        values["is_active"] = int(bool(is_active))
    if office_id is not None:
        values["office_id"] = int(office_id) if office_id != "" else None
    if is_assessor is not None:
        values["is_assessor"] = _flag01(is_assessor)
    account_touched = (role is not None or advisor_name is not None or student_scope is not None
                       or detail_level is not None or m1_access is not None)
    offices_touched = office_ids is not None or office_id is not None
    if not values and not account_touched and m1_admin is None and not offices_touched:
        return False
    with Session(engine) as sess:
        if offices_touched or role is not None or is_assessor is not None or is_active is not None:
            _lock_booking_location(sess, 0)
        if account_touched:
            row = sess.get(User, int(user_id))
            if not row:
                return False
            new_role = role if role is not None else row.role
            reset = new_role != row.role
            values.update(_account_values_to_store(
                new_role,
                advisor_name if advisor_name is not None else row.advisor_name,
                student_scope if student_scope is not None else ("" if reset else row.student_scope),
                detail_level if detail_level is not None else ("" if reset else row.detail_level),
                m1_access if m1_access is not None else (None if reset else row.m1_access),
            ))
        if m1_admin is not None or role is not None:
            row = sess.get(User, int(user_id))
            if not row:
                return False
            new_role = role if role is not None else row.role
            if new_role != "advisor":
                values["m1_admin"] = None
            elif m1_admin is not None:
                values["m1_admin"] = m1_admin
            elif role is not None and role != row.role:
                values["m1_admin"] = None
        current = sess.get(User, int(user_id))
        if not current:
            return False
        final_role = role if role is not None else current.role
        authorized: Optional[List[int]] = None
        if office_ids is not None:
            authorized = []
            for raw in office_ids:
                if raw in (None, ""):
                    continue
                oid = int(raw)
                if oid not in authorized:
                    authorized.append(oid)
            primary = int(office_id) if office_id not in (None, "") else None
            if primary is not None and primary in authorized:
                authorized.remove(primary)
                authorized.insert(0, primary)
        elif office_id is not None:
            authorized = [int(office_id)] if office_id != "" else []
        if authorized is not None:
            values["office_id"] = authorized[0] if authorized else None
        if final_role == "front":
            values["is_assessor"] = 0
            if values.get("office_id", current.office_id) in (None, ""):
                raise ValueError("前台账号需要绑定办公室")
        if int(values.get("is_assessor", current.is_assessor or 0)) \
                and values.get("office_id", current.office_id) in (None, ""):
            raise ValueError("测评师需要绑定办公室")
        result = sess.execute(update(User).where(User.id == int(user_id)).values(**values))
        if authorized is not None:
            before = {int(r[0]) for r in sess.execute(
                select(UserOffice.office_id).where(UserOffice.user_id == int(user_id))).all()}
            _sync_user_offices(sess, int(user_id), authorized)
            final_assessor = int(values.get("is_assessor", current.is_assessor or 0))
            for oid in authorized:
                setting = sess.get(AssessorOfficeSetting, (int(user_id), oid))
                if final_assessor:
                    if oid not in before:
                        sess.execute(delete(AssessorAvailability).where(
                            AssessorAvailability.assessor_id == int(user_id),
                            AssessorAvailability.location_id == oid,
                            AssessorAvailability.date >= date.today()))
                        mode = "legacy" if not before else "explicit"
                        if setting:
                            setting.mode = mode
                        else:
                            sess.add(AssessorOfficeSetting(
                                assessor_id=int(user_id), office_id=oid, mode=mode))
                    elif setting is None:
                        sess.add(AssessorOfficeSetting(
                            assessor_id=int(user_id), office_id=oid, mode="legacy"))
        sess.commit()
        return result.rowcount > 0


def count_users_by_role(role: str) -> int:
    """统计某角色的用户数（用于防止删除/停用最后一个 admin）。"""
    with Session(engine) as sess:
        return int(sess.execute(
            select(func.count()).select_from(User).where(User.role == role, User.is_active == 1)
        ).scalar() or 0)


def delete_user(user_id: int) -> bool:
    """物理删除用户。返回是否删除成功。"""
    with Session(engine) as sess:
        result = sess.execute(delete(User).where(User.id == int(user_id)))
        sess.commit()
        return result.rowcount > 0


def change_own_password(user_id: int, current: str, replacement: str) -> bool:
    """Compare and replace the active account's existing password hash."""
    from werkzeug.security import check_password_hash, generate_password_hash

    with Session(engine) as sess:
        previous = sess.scalar(select(User.password_hash).where(
            User.id == user_id, User.is_active == 1, User.role.in_(("admin", "advisor", "viewer"))))
        if not previous or not check_password_hash(previous, current):
            return False
        changed = sess.execute(update(User).where(
            User.id == user_id, User.is_active == 1, User.password_hash == previous,
            User.role.in_(("admin", "advisor", "viewer"))
        ).values(password_hash=generate_password_hash(replacement))).rowcount
        sess.commit()
        return changed == 1


def verify_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """校验登录名+密码。成功返回用户 dict（不含 password_hash），失败返回 None。

    停用用户（is_active=0）一律返回 None。
    """
    from werkzeug.security import check_password_hash
    user = get_user_by_username(username)
    if not user or not user.get("is_active"):
        return None
    if not check_password_hash(user.get("password_hash") or "", password or ""):
        return None
    user.pop("password_hash", None)
    return user
