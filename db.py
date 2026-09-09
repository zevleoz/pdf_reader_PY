"""Database layer — SQLite (default) or PostgreSQL (via DATABASE_URL).

Usage:
    from db import init_db, add_student, add_report, get_students, ...

Set DATABASE_URL env var to use PostgreSQL (e.g. Neon):
    DATABASE_URL=postgresql://user:pass@host/dbname
"""

from __future__ import annotations

import os
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Date, DateTime,
    ForeignKey, select, insert, update, delete, func
)
from sqlalchemy.orm import declarative_base, Session

Base = declarative_base()

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "data" / "y4_students.db"

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_DB}")

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=connect_args)


class Student(Base):
    __tablename__ = "students"
    id = Column(Integer, primary_key=True, autoincrement=True)
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
    minutes_text = Column(Text)     # AI 生成的会议纪要
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
    created_at = Column(DateTime, default=datetime.utcnow)


class Availability(Base):
    __tablename__ = "availability"
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    time_slot = Column(String(10), nullable=False)
    is_available = Column(Integer, default=1)
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


def init_db() -> None:
    """Create tables if they don't exist, and run migrations."""
    Base.metadata.create_all(engine)
    _migrate_schema()


def _migrate_schema() -> None:
    """Add new columns/tables for schema evolution."""
    import sqlite3
    if not DATABASE_URL.startswith("sqlite"):
        return
    db_path = str(DEFAULT_DB)
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
    ]
    for col_name, sql in migrations:
        if col_name not in existing_cols:
            try:
                cursor.execute(sql)
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
    ]
    for col_name, sql in student_migrations:
        if col_name not in student_cols:
            try:
                cursor.execute(sql)
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
                    created_at DATETIME,
                    updated_at DATETIME,
                    FOREIGN KEY (student_id) REFERENCES students(id),
                    FOREIGN KEY (report_id) REFERENCES reports(id)
                )
            """)
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

    conn.close()


# ─── Student CRUD ───────────────────────────────────────────────

def add_student(name: str, gender: str = "", birthday: str = "",
                grade: str = "", email: str = "", phone: str = "") -> int:
    """Create a student record. Returns student id."""
    with Session(engine) as sess:
        stmt = insert(Student).values(
            name=name, gender=gender, birthday=birthday,
            grade=grade, email=email, phone=phone,
        )
        result = sess.execute(stmt)
        sess.commit()
        return result.lastrowid


def find_or_create_student(name: str, gender: str = "", birthday: str = "",
                           grade: str = "", email: str = "", phone: str = "",
                           advisor_name: str = "", school: str = "",
                           single_parent: str = "false") -> int:
    """Find student by name, or create one. Returns student id.
    If found, update advisor/school/single_parent fields."""
    with Session(engine) as sess:
        stmt = select(Student).where(Student.name == name)
        row = sess.execute(stmt).first()
        if row:
            student = row[0]
            # Update booking-related fields if provided
            update_values = {}
            if advisor_name:
                update_values["advisor_name"] = advisor_name
            if school:
                update_values["school"] = school
            if single_parent and single_parent != "false":
                update_values["single_parent"] = single_parent
            if update_values:
                sess.execute(update(Student).where(Student.id == student.id).values(**update_values))
                sess.commit()
            return student.id
    # Create new student
    with Session(engine) as sess:
        stmt = insert(Student).values(
            name=name, gender=gender, birthday=birthday,
            grade=grade, email=email, phone=phone,
            advisor_name=advisor_name, school=school, single_parent=single_parent,
        )
        result = sess.execute(stmt)
        sess.commit()
        return result.lastrowid


def get_students() -> List[Dict[str, Any]]:
    """List all students with their report counts, minutes count, and latest report date."""
    with Session(engine) as sess:
        stmt = select(Student).order_by(Student.created_at.desc())
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
            "raw": raw,
        }


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

def add_booking(student_name: str, appointment_time: datetime,
                student_email: str = "", student_phone: str = "",
                notes: str = "", advisor_name: str = "",
                school: str = "", single_parent: str = "false",
                student_id: Optional[int] = None) -> int:
    """Create a booking. Returns booking id."""
    with Session(engine) as sess:
        stmt = insert(Booking).values(
            student_name=student_name,
            student_email=student_email,
            student_phone=student_phone,
            student_id=student_id,
            appointment_time=appointment_time,
            status="pending",
            notes=notes,
            advisor_name=advisor_name,
            school=school,
            single_parent=single_parent,
        )
        result = sess.execute(stmt)
        sess.commit()
        return result.lastrowid


def create_booking_with_student(student_name: str, appointment_time: datetime,
                                advisor_name: str = "", school: str = "",
                                single_parent: str = "false",
                                notes: str = "") -> tuple:
    """Create student + booking in one transaction. Returns (student_id, booking_id)."""
    with Session(engine) as sess:
        # 1. Find or create student
        existing = sess.execute(select(Student).where(Student.name == student_name)).first()
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
            result = sess.execute(insert(Student).values(
                name=student_name, advisor_name=advisor_name,
                school=school, single_parent=single_parent))
            sess.flush()
            student_id = result.lastrowid

        # 2. Create booking linked to student
        result = sess.execute(insert(Booking).values(
            student_name=student_name, student_id=student_id,
            appointment_time=appointment_time, status="pending",
            notes=notes, advisor_name=advisor_name,
            school=school, single_parent=single_parent))
        booking_id = result.lastrowid
        sess.commit()
        return student_id, booking_id


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
                "created_at": booking.created_at.isoformat() if booking.created_at else None,
                "report_count": report_count,
            })
        return results


def update_booking_status(booking_id: int, status: str) -> None:
    with Session(engine) as sess:
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

def delete_student(student_id: int) -> None:
    """Delete a student and all their reports."""
    with Session(engine) as sess:
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
    """Delete a single report."""
    with Session(engine) as sess:
        sess.execute(delete(Report).where(Report.id == report_id))
        sess.commit()


def delete_booking(booking_id: int) -> None:
    """Delete a booking."""
    with Session(engine) as sess:
        sess.execute(delete(Booking).where(Booking.id == booking_id))
        sess.commit()


# ─── Availability CRUD ──────────────────────────────────────────

TIME_SLOTS = [
    "09:00", "09:30", "10:00", "10:30", "11:00",
    "13:00", "13:30", "14:00", "14:30", "15:00",
    "15:30", "16:00", "16:30", "17:00",
]


def get_availability(date_val: date) -> List[Dict[str, Any]]:
    """Get all availability entries for a given date."""
    with Session(engine) as sess:
        stmt = select(Availability).where(Availability.date == date_val).order_by(Availability.time_slot)
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


def set_availability(date_val: date, time_slot: str, is_available: bool) -> int:
    """Create or update an availability entry. Returns the id."""
    with Session(engine) as sess:
        existing = sess.execute(
            select(Availability).where(
                Availability.date == date_val,
                Availability.time_slot == time_slot
            )
        ).first()
        if existing:
            sess.execute(
                update(Availability).where(Availability.id == existing[0].id)
                .values(is_available=1 if is_available else 0)
            )
            sess.commit()
            return existing[0].id
        else:
            stmt = insert(Availability).values(
                date=date_val,
                time_slot=time_slot,
                is_available=1 if is_available else 0,
            )
            result = sess.execute(stmt)
            sess.commit()
            return result.lastrowid


def batch_set_availability(date_val: date, slots: List[Dict[str, Any]]) -> None:
    """Set availability for all time slots on a given date.
    slots is a list of {"time_slot": "09:00", "is_available": True/False}
    """
    with Session(engine) as sess:
        for slot in slots:
            ts = slot["time_slot"]
            av = 1 if slot.get("is_available", False) else 0
            existing = sess.execute(
                select(Availability).where(
                    Availability.date == date_val,
                    Availability.time_slot == ts
                )
            ).first()
            if existing:
                sess.execute(
                    update(Availability).where(Availability.id == existing[0].id)
                    .values(is_available=av)
                )
            else:
                sess.execute(
                    insert(Availability).values(
                        date=date_val,
                        time_slot=ts,
                        is_available=av,
                    )
                )
        sess.commit()


def get_available_slots(date_val: date) -> List[str]:
    """Get list of available time slot strings for a date."""
    entries = get_availability(date_val)
    return [e["time_slot"] for e in entries if e["is_available"]]


def get_slot_booking_counts(date_val: date) -> Dict[str, int]:
    """Count non-cancelled bookings per time_slot for a given date.
    Returns {"09:00": 2, "10:00": 0, ...}
    """
    from sqlalchemy import extract
    with Session(engine) as sess:
        stmt = select(Booking).where(
            Booking.status != "cancelled",
            Booking.appointment_time >= date_val,
            Booking.appointment_time < date_val + timedelta(days=1),
        )
        rows = sess.execute(stmt).all()
        counts: Dict[str, int] = {}
        for row in rows:
            booking = row[0]
            if booking.appointment_time:
                ts = booking.appointment_time.strftime("%H:%M")
                counts[ts] = counts.get(ts, 0) + 1
        return counts


def get_booking_counts_range(start_date: date, end_date: date) -> Dict[str, Dict[str, int]]:
    """Count non-cancelled bookings per time_slot for a date range.
    Returns {"2026-08-13": {"09:00": 2, "10:00": 1}, ...}
    """
    with Session(engine) as sess:
        stmt = select(Booking).where(
            Booking.status != "cancelled",
            Booking.appointment_time >= start_date,
            Booking.appointment_time < end_date + timedelta(days=1),
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


def get_availability_range(start_date: date, end_date: date) -> Dict[str, List[Dict[str, Any]]]:
    """Get availability for a date range, grouped by date string.
    Returns {"2026-08-13": [{"time_slot": "09:00", "is_available": true}, ...], ...}
    Only returns dates that have at least one record.
    """
    with Session(engine) as sess:
        stmt = select(Availability).where(
            Availability.date >= start_date,
            Availability.date <= end_date
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
                transcript_text: str, minutes_text: str) -> int:
    """Create a meeting minutes record. Returns minutes id."""
    now = datetime.utcnow()
    with Session(engine) as sess:
        stmt = insert(MeetingMinutes).values(
            student_id=student_id,
            report_id=report_id,
            transcript_text=transcript_text,
            minutes_text=minutes_text,
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

        school_rows = sess.execute(
            select(Student.school, func.count(Student.id))
            .where(Student.school != None, Student.school != "")
            .group_by(Student.school)
        ).all()
        by_school = [{"label": (s or "未填"), "count": c} for s, c in school_rows]

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

        # 合并顾问列表
        all_advisor_names = set(advisor_report_map.keys()) | set(advisor_student_map.keys()) | set(booking_advisor_map.keys())
        advisor_performance = []
        for name in all_advisor_names:
            rc = advisor_report_map.get(name, 0)
            sc = advisor_student_map.get(name, 0)
            advisor_performance.append({
                "advisor_name": name,
                "report_count": rc,
                "student_count": sc,
                "booking_count": booking_advisor_map.get(name, 0),
            })
        # 按报告数降序
        advisor_performance.sort(key=lambda x: (x["report_count"], x["student_count"]), reverse=True)

        # ── 相似名检测 ──
        # 规范化分组
        norm_groups: Dict[str, list] = {}
        for name in all_advisor_names:
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
            _to_number, _code_int,
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

            for item in items:
                code = str(item.get("code", ""))
                if not code:
                    continue
                label = item.get("label", "") or ""
                value = item.get("value")
                dim = dimension_of(item)

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


def get_student_profiles() -> List[Dict[str, Any]]:
    """每个学生的四维健康度侧写,用于个体对比。"""
    from collections import defaultdict
    try:
        from evaluation_rules import (
            dimension_of, derive_evaluation, _find_norm,
            _to_number, _code_int,
        )
    except Exception:
        return []

    weak_evals = {"偏低", "明显偏低", "严重偏低", "需关注", "需特殊关注"}

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

            dim_stats = {d: {"weak": 0, "total": 0} for d in _DIMS}
            for item in items:
                code = str(item.get("code", ""))
                if not code:
                    continue
                dim = dimension_of(item)
                if dim not in _DIMS:
                    continue
                norm = _find_norm(items, _code_int(code))
                ev, _ = derive_evaluation(code, item.get("label", ""), item.get("value"), norm)
                dim_stats[dim]["total"] += 1
                if ev and ev in weak_evals:
                    dim_stats[dim]["weak"] += 1

            dims = {}
            health_sum = 0
            health_count = 0
            for d in _DIMS:
                ds = dim_stats[d]
                healthy = round((1 - ds["weak"] / ds["total"]) * 100, 1) if ds["total"] else 100.0
                dims[d] = {
                    "healthy": healthy,
                    "weak_count": ds["weak"],
                    "total": ds["total"],
                }
                if ds["total"] > 0:
                    health_sum += healthy
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
            _to_number, _code_int,
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

            for item in items:
                code = str(item.get("code", ""))
                if not code:
                    continue
                label = item.get("label", "") or ""
                dim = dimension_of(item)
                if dim not in _DIMS:
                    continue
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
