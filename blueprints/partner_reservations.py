"""Service-to-service availability and booking endpoints."""
from __future__ import annotations

import re
from datetime import date, datetime

from flask import Blueprint, g, jsonify, request

import db
import partner_reservations as reservations
from partner_auth import require_partner

bp = Blueprint("partner_reservations", __name__, url_prefix="/api/partners/v1/y4")

_FIELDS = {
    "external_reservation_id", "external_student_id", "student_name",
    "location_id", "appointment_time",
}
_PUBLIC_FIELDS = (
    "id", "external_reservation_id", "location_id", "appointment_time", "confirmed_at", "status",
)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_APPOINTMENT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


def _error(code: str, status: int):
    return jsonify(error=code), status


def _location_id(value) -> int:
    if type(value) is not int or not 0 < value <= 2_147_483_647:
        raise ValueError
    return value


def _text(value, max_length: int) -> str:
    if (
        not isinstance(value, str)
        or not 0 < len(value) <= max_length
        or any(ord(char) < 32 or 127 <= ord(char) <= 159 or 0xD800 <= ord(char) <= 0xDFFF
               for char in value)
    ):
        raise ValueError
    return value


def _parse_request(data) -> dict:
    if not isinstance(data, dict) or set(data) != _FIELDS:
        raise ValueError
    for key in ("external_reservation_id", "external_student_id"):
        value = _text(data[key], 128)
        if value != value.strip():
            raise ValueError
    name = _text(data["student_name"], 100).strip()
    if not name:
        raise ValueError
    raw_time = data["appointment_time"]
    if not isinstance(raw_time, str) or not _APPOINTMENT.fullmatch(raw_time):
        raise ValueError
    appointment_time = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
    appointment_time = appointment_time.astimezone(reservations.BOOKING_TIMEZONE).replace(tzinfo=None)
    if (
        appointment_time.strftime("%H:%M") not in db.TIME_SLOTS
        or appointment_time.second
        or appointment_time.microsecond
    ):
        raise ValueError
    return {
        **data,
        "student_name": name,
        "appointment_time": appointment_time,
        "location_id": _location_id(data["location_id"]),
    }


def _public_reservation(record: dict) -> dict:
    return {field: record[field] for field in _PUBLIC_FIELDS}


@bp.get("/availability")
@require_partner("booking")
def get_availability():
    try:
        raw_date = request.args.get("date", "")
        if not _DATE.fullmatch(raw_date):
            raise ValueError
        day = date.fromisoformat(raw_date)
        location_id = _location_id(int(request.args.get("location_id", "")))
        return jsonify(reservations.get_availability(location_id, day))
    except ValueError:
        return _error("invalid_request", 400)
    except reservations.ReservationError as exc:
        return _error(exc.code, exc.status)


@bp.post("/reservations")
@require_partner("booking")
def create_reservation():
    try:
        fields = _parse_request(request.get_json(silent=True))
        record, created = reservations.create_reservation(g.partner_id, **fields)
    except (ValueError, OverflowError):
        return _error("invalid_request", 400)
    except reservations.ReservationError as exc:
        return _error(exc.code, exc.status)
    return jsonify(_public_reservation(record)), 201 if created else 200


@bp.get("/reservations/<reservation_id>")
@require_partner("booking", "results")
def get_reservation(reservation_id: str):
    record = reservations.get_reservation(g.partner_id, reservation_id)
    if record is None:
        return _error("reservation_not_found", 404)

    response = _public_reservation(record)
    if "results" in g.partner_scopes:
        from partner_results import current_result_version

        response["current_result_version"] = current_result_version(g.partner_id, reservation_id)
    return jsonify(response)
