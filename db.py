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
    created_at = Column(DateTime, default=datetime.utcnow)


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
    """List all students with their report counts and latest report date."""
    with Session(engine) as sess:
        stmt = select(Student).order_by(Student.created_at.desc())
        rows = sess.execute(stmt).all()
        results = []
        for row in rows:
            student = row[0]
            count_stmt = select(func.count(Report.id)).where(Report.student_id == student.id)
            report_count = sess.execute(count_stmt).scalar() or 0
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
        } for row in rows]


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
