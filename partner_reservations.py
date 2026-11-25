"""Partner booking and identity mappings over the shared office schedule."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import db

BOOKING_TIMEZONE = ZoneInfo("Asia/Shanghai")


class ReservationError(Exception):
    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.code = code
        self.status = status


def _within_booking_window(day: date) -> bool:
    today = datetime.now(BOOKING_TIMEZONE).date()
    return today < day <= today + timedelta(days=db.BOOKING_MAX_DAYS_AHEAD)


def _local_iso(value: datetime) -> str:
    return value.replace(tzinfo=BOOKING_TIMEZONE).isoformat()


def get_availability(location_id: int, day: date) -> dict:
    location = db.get_location(location_id)
    if not location or not location["active"]:
        raise ReservationError("location_not_found", 404)
    if not _within_booking_window(day):
        raise ReservationError("invalid_request", 400)

    availability = {row["time_slot"]: row["is_available"]
                    for row in db.get_availability(day, location_id)}
    counts = db.get_slot_booking_counts(day, location_id)
    return {
        "location_id": location_id,
        "date": day.isoformat(),
        "timezone": BOOKING_TIMEZONE.key,
        "slots": [
            {
                "appointment_time": _local_iso(datetime.combine(day, time.fromisoformat(slot))),
                "is_available": availability.get(slot, True) and counts.get(slot, 0) <
                db.effective_slot_capacity(
                    location_id, datetime.combine(day, time.fromisoformat(slot)), db.SLOT_CAPACITY),
            }
            for slot in db.TIME_SLOTS
        ],
    }


def _reservation_record(reservation: db.PartnerReservation, booking: db.Booking | None) -> dict:
    student_id = reservation.student_id
    if booking is None or booking.student_id != student_id:
        student_id = None
    return {
        "id": reservation.id,
        "external_reservation_id": reservation.external_reservation_id,
        "booking_id": booking.id if booking else None,
        "student_id": student_id,
        "status": booking.status if booking else "cancelled",
        "location_id": booking.location_id if booking else reservation.location_id,
        "appointment_time": _local_iso(booking.appointment_time if booking else reservation.appointment_time),
        "confirmed_at": reservation.confirmed_at.replace(tzinfo=timezone.utc).isoformat(),
    }


def _query_reservation(partner_id: str):
    return (
        select(db.PartnerReservation, db.Booking)
        .outerjoin(db.Booking, db.Booking.id == db.PartnerReservation.booking_id)
        .where(db.PartnerReservation.partner_id == partner_id)
    )


def get_reservation(
    partner_id: str, reservation_id: str, *, sess: db.Session | None = None,
) -> dict | None:
    if sess is None:
        with db.Session(db.engine) as session:
            return get_reservation(partner_id, reservation_id, sess=session)
    row = sess.execute(
        _query_reservation(partner_id).where(db.PartnerReservation.id == reservation_id)
    ).one_or_none()
    return _reservation_record(*row) if row else None


def _get_or_create_student(sess, partner_id: str, external_student_id: str, student_name: str) -> int:
    identity = sess.get(db.PartnerStudent, (partner_id, external_student_id))
    if identity is not None:
        if identity.student_id is None:
            raise ReservationError("student_unavailable", 409)
        return identity.student_id
    student = db._insert_booking_student(sess, name=student_name)
    sess.add(db.PartnerStudent(
        partner_id=partner_id, external_student_id=external_student_id, student_id=student.id,
    ))
    return student.id


def create_reservation(
    partner_id: str,
    *,
    external_reservation_id: str,
    external_student_id: str,
    student_name: str,
    location_id: int,
    appointment_time: datetime,
) -> tuple[dict, bool]:
    """Create a reservation or replay its existing partner receipt."""
    digest = hashlib.sha256(json.dumps(
        [external_student_id, student_name, location_id, appointment_time.isoformat()],
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()

    for attempt in range(db._CODE_ALLOC_RETRIES):
        try:
            with db.Session(db.engine) as sess, sess.begin():
                db._lock_booking_location(sess, location_id)
                previous = sess.execute(_query_reservation(partner_id).where(
                    db.PartnerReservation.external_reservation_id == external_reservation_id,
                )).one_or_none()
                if previous:
                    reservation, booking = previous
                    if reservation.request_digest != digest:
                        raise ReservationError("reservation_conflict", 409)
                    return _reservation_record(reservation, booking), False

                location = sess.get(db.Location, location_id)
                if not location or not location.active:
                    raise ReservationError("location_not_found", 404)
                if not _within_booking_window(appointment_time.date()):
                    raise ReservationError("invalid_request", 400)
                db._check_slot(sess, location_id, appointment_time, db.SLOT_CAPACITY)
                student_id = _get_or_create_student(
                    sess, partner_id, external_student_id, student_name,
                )
                booking = db._insert_booking(
                    sess, student_name=student_name, student_id=student_id,
                    appointment_time=appointment_time, location_id=location_id,
                    source="partner",
                )
                reservation = db.PartnerReservation(
                    id=str(uuid4()), partner_id=partner_id,
                    external_reservation_id=external_reservation_id, booking_id=booking.id,
                    student_id=student_id,
                    request_digest=digest, location_id=location_id,
                    appointment_time=appointment_time,
                )
                sess.add(reservation)
                sess.flush()
                return _reservation_record(reservation, booking), True
        except db.SlotUnavailable as exc:
            raise ReservationError("slot_unavailable", 409) from exc
        except IntegrityError:
            # Another office transaction can win the reservation, identity or student-code key.
            if attempt == db._CODE_ALLOC_RETRIES - 1:
                raise
