"""Database layer — SQLite (default) or PostgreSQL (via DATABASE_URL).

Usage:
    from db import init_db, add_student, add_report, get_students, ...

Set DATABASE_URL env var to use PostgreSQL (e.g. Neon):
    DATABASE_URL=postgresql://user:pass@host/dbname
"""

from __future__ import annotations

import os
import json
from datetime import date, datetime
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
    student_email = Column(String(200))
    student_phone = Column(String(50))
    appointment_time = Column(DateTime, nullable=False)
    status = Column(String(20), default="pending")
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db() -> None:
    """Create tables if they don't exist."""
    Base.metadata.create_all(engine)


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
                           grade: str = "", email: str = "", phone: str = "") -> int:
    """Find student by name, or create one. Returns student id."""
    with Session(engine) as sess:
        stmt = select(Student).where(Student.name == name)
        row = sess.execute(stmt).first()
        if row:
            return row[0].id
    return add_student(name, gender, birthday, grade, email, phone)


def get_students() -> List[Dict[str, Any]]:
    """List all students with their report counts."""
    with Session(engine) as sess:
        stmt = select(Student).order_by(Student.created_at.desc())
        rows = sess.execute(stmt).all()
        results = []
        for row in rows:
            student = row[0]
            count_stmt = select(func.count(Report.id)).where(Report.student_id == student.id)
            report_count = sess.execute(count_stmt).scalar() or 0
            results.append({
                "id": student.id,
                "name": student.name,
                "gender": student.gender,
                "grade": student.grade,
                "email": student.email,
                "phone": student.phone,
                "created_at": student.created_at.isoformat() if student.created_at else None,
                "report_count": report_count,
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
                notes: str = "") -> int:
    """Create a booking. Returns booking id."""
    with Session(engine) as sess:
        stmt = insert(Booking).values(
            student_name=student_name,
            student_email=student_email,
            student_phone=student_phone,
            appointment_time=appointment_time,
            status="pending",
            notes=notes,
        )
        result = sess.execute(stmt)
        sess.commit()
        return result.lastrowid


def get_bookings(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """List bookings, optionally filtered by status."""
    with Session(engine) as sess:
        stmt = select(Booking)
        if status:
            stmt = stmt.where(Booking.status == status)
        stmt = stmt.order_by(Booking.appointment_time.desc())
        rows = sess.execute(stmt).all()
        return [{
            "id": row[0].id,
            "student_name": row[0].student_name,
            "student_email": row[0].student_email,
            "student_phone": row[0].student_phone,
            "appointment_time": row[0].appointment_time.isoformat() if row[0].appointment_time else None,
            "status": row[0].status,
            "notes": row[0].notes,
            "created_at": row[0].created_at.isoformat() if row[0].created_at else None,
        } for row in rows]


def update_booking_status(booking_id: int, status: str) -> None:
    with Session(engine) as sess:
        stmt = update(Booking).where(Booking.id == booking_id).values(status=status)
        sess.execute(stmt)
        sess.commit()


def complete_booking(booking_id: int) -> int:
    """Mark booking completed and create student record. Returns student id."""
    with Session(engine) as sess:
        stmt = select(Booking).where(Booking.id == booking_id)
        row = sess.execute(stmt).first()
        if not row:
            raise ValueError(f"Booking {booking_id} not found")
        booking = row[0]
        # Create student from booking info
        student_id = add_student(
            name=booking.student_name,
            email=booking.student_email or "",
            phone=booking.student_phone or "",
        )
        update_booking_status(booking_id, "completed")
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
