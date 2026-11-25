"""Partner booking API against the existing public and research workflows."""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

import app_utils
import db
import partner_reservations
import questionnaire_store

PREFIX = "/api/partners/v1/y4"
BASE = "https://institute.example"
TOKENS = {"alpha": "a" * 43, "beta": "b" * 43, "reader": "r" * 43}


def headers(actor="alpha"):
    return {"Authorization": f"Bearer {TOKENS[actor]}"}


def config(partner, *credentials):
    return {
        "id": partner,
        "enabled": True,
        "scopes": ["booking", "results"],
        "credentials": [
            {"sha256": hashlib.sha256(TOKENS[actor].encode()).hexdigest(), "scopes": [scope]}
            for actor, scope in credentials
        ],
    }


@pytest.fixture()
def world(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/partner_bookings.db"
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "DATABASE_URL", url)
    monkeypatch.setattr(questionnaire_store, "engine", engine)
    monkeypatch.delenv("Y4_PARTNERS_FILE", raising=False)
    monkeypatch.setenv("Y4_PARTNERS_JSON", json.dumps([
        config("alpha", ("alpha", "booking"), ("reader", "results")),
        config("beta", ("beta", "booking")),
    ]))
    from app import create_app

    app_utils._SESSION_USER_CACHE.clear()
    app = create_app()
    app.config.update(TESTING=True, SECRET_KEY="partner-booking-test")
    yield app, engine
    app_utils._SESSION_USER_CACHE.clear()
    engine.dispose()


@pytest.fixture()
def payload():
    day = datetime.now(partner_reservations.BOOKING_TIMEZONE).date() + timedelta(days=1)
    return {
        "external_reservation_id": "request-001",
        "external_student_id": "student-001",
        "student_name": "虚构同名学生",
        "location_id": 1,
        "appointment_time": f"{day.isoformat()}T10:00:00+08:00",
    }


def submit(app, payload, actor="alpha"):
    return app.test_client().post(f"{PREFIX}/reservations", json=payload,
                                  headers=headers(actor), base_url=BASE)


def fetch(app, reservation_id, actor="alpha"):
    return app.test_client().get(f"{PREFIX}/reservations/{reservation_id}",
                                 headers=headers(actor), base_url=BASE)


def record(response, partner="alpha"):
    return partner_reservations.get_reservation(partner, response.json["id"])


def count(engine, model):
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(model))


def test_replay_conflicts_and_partner_identity(world, payload):
    app, engine = world
    first = submit(app, payload)
    assert first.status_code == 201
    assert set(first.json) == {
        "id", "external_reservation_id", "location_id", "appointment_time", "confirmed_at", "status",
    }
    assert first.json["status"] == "pending"
    same_in_utc = {**payload, "appointment_time": payload["appointment_time"][:10] + "T02:00:00Z"}
    replay = submit(app, same_in_utc)
    assert replay.status_code == 200 and replay.json == first.json
    assert count(engine, db.Booking) == 1
    assert count(engine, db.Student) == 1

    conflict = submit(app, {**payload, "location_id": 2})
    assert conflict.status_code == 409 and conflict.json == {"error": "reservation_conflict"}
    assert fetch(app, first.json["id"], "beta").status_code == 404
    assert fetch(app, first.json["id"]).json == first.json
    discovery = fetch(app, first.json["id"], "reader")
    assert discovery.status_code == 200 and discovery.json["current_result_version"] is None
    assert submit(app, payload, "reader").status_code == 403

    second = submit(app, {**payload, "external_reservation_id": "request-002", "location_id": 2})
    another_student = submit(app, {**payload, "external_reservation_id": "request-003",
                                   "external_student_id": "student-002"})
    other_partner = submit(app, payload, "beta")
    assert all(reply.status_code == 201 for reply in (second, another_student, other_partner))
    original_student = record(first)["student_id"]
    assert record(second)["student_id"] == original_student
    assert len({original_student, record(another_student)["student_id"],
                record(other_partner, "beta")["student_id"]}) == 3


def test_shared_last_slot_race(world, payload):
    app, engine = world
    appointment = datetime.fromisoformat(payload["appointment_time"]).replace(tzinfo=None)
    for i in range(db.SLOT_CAPACITY - 1):
        db.add_booking(f"虚构占位 {i + 1}", appointment, location_id=1, capacity=db.SLOT_CAPACITY)

    simultaneous = Barrier(2)

    def submit_partner():
        simultaneous.wait(timeout=5)
        return submit(app, payload)

    def submit_public():
        simultaneous.wait(timeout=5)
        return app.test_client().post("/api/booking", json={
            "appointment_time": appointment.isoformat(), "location_id": 1, "student_name": "虚构家长预约",
        })

    with ThreadPoolExecutor(max_workers=2) as pool:
        partner = pool.submit(submit_partner)
        public = pool.submit(submit_public)
        partner_status = partner.result(timeout=10).status_code
        public_status = public.result(timeout=10).status_code

    assert (partner_status, public_status) in {(201, 409), (409, 200)}
    assert count(engine, db.Booking) == db.SLOT_CAPACITY
    assert count(engine, db.Student) == 1
    assert count(engine, db.PartnerStudent) == (partner_status == 201)
    response = app.test_client().get(
        f"{PREFIX}/availability", base_url=BASE, headers=headers(),
        query_string={"location_id": "1", "date": appointment.date().isoformat()},
    )
    assert response.status_code == 200 and response.json["timezone"] == "Asia/Shanghai"
    assert all(set(slot) == {"appointment_time", "is_available"} for slot in response.json["slots"])
    assert any(slot == {"appointment_time": payload["appointment_time"], "is_available": False}
               for slot in response.json["slots"])


def test_availability_and_create_follow_office_and_slot_closures(world, payload):
    app, engine = world
    appointment = datetime.fromisoformat(payload["appointment_time"])
    with Session(engine) as session, session.begin():
        session.get(db.Location, 2).active = 0
    db.set_availability(appointment.date(), "10:00", False, location_id=1)

    def availability(location_id):
        return app.test_client().get(
            f"{PREFIX}/availability", base_url=BASE, headers=headers(),
            query_string={"location_id": str(location_id), "date": appointment.date().isoformat()},
        )

    assert availability(2).json == {"error": "location_not_found"}
    assert submit(app, {**payload, "location_id": 2}).status_code == 404
    slot = next(row for row in availability(1).json["slots"]
                if row["appointment_time"] == payload["appointment_time"])
    assert slot["is_available"] is False
    reply = submit(app, payload)
    assert reply.status_code == 409 and reply.json == {"error": "slot_unavailable"}
    assert count(engine, db.PartnerStudent) == 0


def test_staff_schedule_assignment_cancel_and_unlink(world, payload):
    app, engine = world
    first = submit(app, payload)
    assert first.status_code == 201
    booking = record(first)
    student = db.get_student(booking["student_id"])
    assessor = db.create_user("demo-assessor", "fictional-password", "admin",
                              is_assessor=True, office_id=1)
    admin = app.test_client()
    with admin.session_transaction() as session:
        session.update(user_id=assessor, role="admin")
    upcoming = admin.get("/api/profiling/workbench").json["upcoming"]
    assert [(item["booking_id"], item["source"]) for item in upcoming] == [
        (booking["booking_id"], "partner"),
    ]
    schedule_url = f"/api/profiling/students/{student['student_code']}/schedule"
    assert admin.get(schedule_url).json["bookings"][0]["source"] == "partner"
    assign = admin.post(f"/api/booking/{booking['booking_id']}/assign", json={"assessor_id": assessor})
    assert assign.status_code == 200 and assign.json["booking"]["assessor_id"] == assessor

    assert admin.post(f"/api/booking/{booking['booking_id']}/cancel").status_code == 200
    assert fetch(app, first.json["id"]).json["status"] == "cancelled"

    other_student = db.create_student("虚构替换学生")
    with Session(engine) as session, session.begin():
        session.get(db.Booking, booking["booking_id"]).student_id = other_student
    assert record(first)["student_id"] is None

    db.delete_booking(booking["booking_id"])
    assert record(first)["booking_id"] is None
    assert fetch(app, first.json["id"]).json["status"] == "cancelled"
    assert submit(app, payload).status_code == 200


@pytest.mark.parametrize("changes", [
    {"appointment_time": "2026-01-01T10:00:00"},
    {"appointment_time": "2026-01-01T10:00:00+08:00"},
    {"appointment_time": "9999-12-31T23:59:59Z"},
    {"partner_id": "beta"},
    {"location_id": True},
    {"external_student_id": "shrink "},
])
def test_rejects_invalid_or_untrusted_booking_input(world, payload, changes):
    app, engine = world
    reply = submit(app, {**payload, **changes})
    assert reply.status_code == 400 and reply.json == {"error": "invalid_request"}
    assert count(engine, db.Booking) == 0 and count(engine, db.PartnerStudent) == 0
