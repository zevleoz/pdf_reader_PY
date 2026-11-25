"""Task H 验收：多办公室授权、按办公室排班、具名可用、撤权与容量复核。"""
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

import app_utils
import db as _db
import questionnaire_store as _qs
from blueprints import system as system_bp
from blueprints import tools as tools_bp
from blueprints import workspace as workspace_bp


@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = _db.create_engine(
        f"sqlite:///{tmp_path/'task_h.db'}", connect_args={"check_same_thread": False})
    _db.Base.metadata.create_all(engine)
    monkeypatch.setattr(_db, "engine", engine)
    monkeypatch.setattr(_qs, "engine", engine)
    monkeypatch.setattr(app_utils, "_SESSION_USER_CACHE", {})
    _db.ensure_locations()
    locs = {l["name"]: l["id"] for l in _db.list_locations()}
    sh, bj, sz = locs["上海"], locs["北京"], locs["深圳"]
    admin = _db.create_user("admin", "pw", "admin", display_name="总管",
                            is_assessor=1, office_id=sh)
    chen = _db.create_user("chen", "pw", "advisor", display_name="陈老师",
                           advisor_name="陈老师", is_assessor=1,
                           office_ids=[sh, sz])
    zhou = _db.create_user("zhou", "pw", "advisor", display_name="周老师",
                           advisor_name="周老师", is_assessor=1, office_id=sh)
    a_bj = _db.create_user("a_bj", "pw", "advisor", display_name="北京老师",
                           advisor_name="北京老师", is_assessor=1, office_id=bj)
    front = _db.create_user("front", "pw", "front", display_name="前台",
                            office_ids=[sh, bj])
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(tools_bp.bp)
    app.register_blueprint(workspace_bp.bp)
    app.register_blueprint(system_bp.bp)
    app_utils.register_front_desk_guard(app)
    return {"app": app, "engine": engine, "sh": sh, "bj": bj, "sz": sz,
            "admin": admin, "chen": chen, "zhou": zhou, "a_bj": a_bj, "front": front}


def login(client, user_id, role="admin", name="总管", office_id=None):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["username"] = name
        sess["role"] = role
        sess["display_name"] = name
        sess["advisor_name"] = name
        sess["student_scope"] = "none" if role == "front" else "all"
        sess["detail_level"] = "full"
        sess["m1_access"] = 0
        sess["m1_admin"] = 0
        if office_id is not None:
            sess["office_id"] = office_id


def staff_booking(client, loc, name, slot="10:00", day=None):
    target = day or date.today() + timedelta(days=1)
    return client.post("/api/bookings/staff", json={
        "location_id": loc, "new_name": name, "source": "internal",
        "requester_name": "王顾问",
        "appointment_time": f"{target.isoformat()}T{slot}:00",
    })


def candidate_ids(client, booking_id):
    data = client.get(f"/api/booking/{booking_id}/assessor-candidates").get_json()
    return {item["id"] for item in data["candidates"]}


def test_user_offices_and_schedule_defaults_are_distinct(world):
    assert set(_db.list_user_office_ids(world["chen"])) == {world["sh"], world["sz"]}
    assert _db.assessor_office_mode(world["chen"], world["sh"]) == "legacy"
    assert _db.assessor_office_mode(world["chen"], world["sz"]) == "explicit"
    assert _db.assessor_office_mode(world["zhou"], world["sh"]) == "legacy"

    day = date.today() + timedelta(days=1)
    sh_map = _db.list_assessor_availability(world["chen"], day, 1, world["sh"])
    sz_map = _db.list_assessor_availability(world["chen"], day, 1, world["sz"])
    assert sh_map[day.isoformat()]["10:00"] is True   # 旧办公室默认开放
    assert sz_map[day.isoformat()]["10:00"] is False  # 新授权办公室默认关闭


def test_candidates_follow_office_authorization_and_immediate_conflict(world):
    client = world["app"].test_client()
    login(client, world["admin"])
    day = date.today() + timedelta(days=1)
    _db.set_assessor_availability(world["chen"], world["sz"], day,
                                  [{"time_slot": "10:00", "is_available": True}])
    sz_booking = staff_booking(client, world["sz"], "深圳同学").get_json()["booking_id"]

    # 未排班的时段：新授权办公室默认关闭，不进入候选
    _db.set_assessor_availability(world["chen"], world["sz"], day,
                                  [{"time_slot": "10:00", "is_available": False}])
    assert world["chen"] not in candidate_ids(client, sz_booking)
    assert world["zhou"] not in candidate_ids(client, sz_booking)

    _db.set_assessor_availability(world["chen"], world["sz"], day,
                                  [{"time_slot": "10:00", "is_available": True}])
    assert world["chen"] in candidate_ids(client, sz_booking)

    sh_booking = staff_booking(client, world["sh"], "上海同学").get_json()["booking_id"]
    assigned = client.post(f"/api/booking/{sh_booking}/assign",
                           json={"assessor_id": world["chen"]})
    assert assigned.status_code == 200, assigned.get_json()
    # 同一时刻不能既在上海又在深圳：深圳候选即时移除陈老师
    assert world["chen"] not in candidate_ids(client, sz_booking)


def test_assessor_cannot_edit_unauthorized_office(world):
    client = world["app"].test_client()
    login(client, world["zhou"], "advisor", "周老师", office_id=world["sh"])
    day = (date.today() + timedelta(days=1)).isoformat()
    forbidden = client.post("/api/assessor/availability", json={
        "date": day, "location_id": world["bj"],
        "slots": [{"time_slot": "10:00", "is_available": True}],
    })
    assert forbidden.status_code == 403

    multi = world["app"].test_client()
    login(multi, world["chen"], "advisor", "陈老师", office_id=world["sh"])
    missing = multi.post("/api/assessor/availability", json={
        "date": day, "slots": [{"time_slot": "10:00", "is_available": True}],
    })
    assert missing.status_code == 400 and "办公室" in missing.get_json()["error"]


def test_multi_office_assessor_must_pick_office(world):
    client = world["app"].test_client()
    login(client, world["chen"], "advisor", "陈老师", office_id=world["sh"])
    listed = client.get("/api/assessor/availability").get_json()
    assert {o["id"] for o in listed["offices"]} == {world["sh"], world["sz"]}
    assert listed["requires_office"] is True
    assert listed["availability"] == {}

    picked = client.get(f"/api/assessor/availability?location_id={world['sz']}").get_json()
    assert picked["office_id"] == world["sz"]
    day = date.today().isoformat()
    assert picked["availability"][day]["10:00"] is False


def test_public_capacity_counts_named_staff_without_leaking_names(world):
    client = world["app"].test_client()
    login(client, world["admin"])
    day = date.today() + timedelta(days=1)
    public = client.get(f"/api/availability?date={day.isoformat()}&loc={world['bj']}").get_json()
    slot = next(s for s in public["slots"] if s["time_slot"] == "10:00")
    assert slot["capacity"] == 1
    body = str(public)
    assert "北京老师" not in body and "assessor" not in body

    first = staff_booking(client, world["bj"], "甲同学", day=day)
    assert first.status_code == 200, first.get_json()
    second = staff_booking(client, world["bj"], "乙同学", day=day)
    assert second.status_code == 409
    assert "1/1" in second.get_json()["error"]


def test_revoke_office_lists_future_assignments_and_blocks_new_ones(world):
    client = world["app"].test_client()
    login(client, world["admin"])
    day = date.today() + timedelta(days=1)
    _db.set_assessor_availability(world["chen"], world["sz"], day,
                                  [{"time_slot": "11:00", "is_available": True}])
    booking = staff_booking(client, world["sz"], "待重排同学", slot="11:00").get_json()["booking_id"]
    assert client.post(f"/api/booking/{booking}/assign",
                       json={"assessor_id": world["chen"]}).status_code == 200

    revoked = client.put(f"/api/users/{world['chen']}", json={"office_ids": [world["sh"]]})
    assert revoked.status_code == 200, revoked.get_json()
    body = revoked.get_json()
    assert _db.list_user_office_ids(world["chen"]) == [world["sh"]]
    assert any(item["booking_id"] == booking for item in body["reassignments"])

    new_booking = staff_booking(client, world["sz"], "撤权后同学", slot="13:00").get_json()["booking_id"]
    assert world["chen"] not in candidate_ids(client, new_booking)
    denied = client.post(f"/api/booking/{new_booking}/assign", json={"assessor_id": world["chen"]})
    assert denied.status_code == 400
    # 历史及已约记录保留，只是不再新增
    kept = _db.get_booking_detail(booking)
    assert kept and kept["assessor_id"] == world["chen"]


def test_front_desk_sees_all_authorized_offices(world):
    client = world["app"].test_client()
    login(client, world["admin"])
    today = date.today()
    _db.set_assessor_availability(world["chen"], world["sz"], today,
                                  [{"time_slot": "10:00", "is_available": True}])
    sh_id = staff_booking(client, world["sh"], "今日上海", day=today).get_json()["booking_id"]
    bj_id = staff_booking(client, world["bj"], "今日北京", day=today).get_json()["booking_id"]
    sz_id = staff_booking(client, world["sz"], "今日深圳", day=today).get_json()["booking_id"]

    front = world["app"].test_client()
    login(front, world["front"], "front", "前台", office_id=world["sh"])
    listed = {b["id"] for b in front.get("/api/handoff/bookings").get_json()["bookings"]}
    assert listed == {sh_id, bj_id}
    assert sz_id not in listed


def test_last_capacity_race_only_one_succeeds_and_cancel_releases(world):
    appt = datetime.combine(date.today() + timedelta(days=1),
                            datetime.strptime("15:00", "%H:%M").time())
    barrier = Barrier(2)

    def attempt(name):
        barrier.wait(timeout=5)
        try:
            return _db.create_booking_with_student(
                name, appt, location_id=world["bj"], capacity=_db.SLOT_CAPACITY,
                source="internal")[1]
        except _db.SlotUnavailable:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(attempt, "并发甲"), pool.submit(attempt, "并发乙")]
        winners = [r.result(timeout=10) for r in results]
    booked = [bid for bid in winners if bid]
    assert len(booked) == 1
    with _db.Session(world["engine"]) as sess:
        total = sess.execute(_db.select(_db.func.count(_db.Booking.id)).where(
            _db.Booking.location_id == world["bj"],
            _db.Booking.appointment_time == appt,
            _db.Booking.status != "cancelled")).scalar()
    assert total == 1

    _db.update_booking_status(booked[0], "cancelled")
    _, released = _db.create_booking_with_student(
        "取消后补位", appt, location_id=world["bj"], capacity=_db.SLOT_CAPACITY,
        source="internal")
    assert released


def test_migration_backfills_legacy_single_office_idempotently(tmp_path, monkeypatch):
    engine = _db.create_engine(
        f"sqlite:///{tmp_path/'legacy.db'}", connect_args={"check_same_thread": False})
    _db.Base.metadata.create_all(engine)
    monkeypatch.setattr(_db, "engine", engine)
    with _db.Session(engine) as sess:
        user = _db.User(username="legacy", password_hash=generate_password_hash("pw"),
                        role="advisor", is_active=1, is_assessor=1, office_id=7,
                        student_scope="all", detail_level="full")
        sess.add(user)
        sess.flush()
        uid = user.id
        sess.add(_db.AssessorAvailability(assessor_id=uid, location_id=None,
                                          date=date.today(), time_slot="10:00",
                                          is_available=0))
        sess.commit()
    with engine.begin() as conn:
        conn.execute(_db.text(
            "CREATE UNIQUE INDEX ux_assessor_availability_slot "
            "ON assessor_availability (assessor_id, date, time_slot)"))

    _db._ensure_task_h_schema()
    _db._ensure_task_h_schema()  # 可重复执行
    assert _db.list_user_office_ids(uid) == [7]
    assert _db.assessor_office_mode(uid, 7) == "legacy"
    with _db.Session(engine) as sess:
        rows = sess.query(_db.UserOffice).filter_by(user_id=uid).all()
        attrs = sess.query(_db.AssessorAvailability).filter_by(assessor_id=uid).all()
    assert len(rows) == 1 and rows[0].is_default == 1
    assert len(attrs) == 1 and attrs[0].location_id == 7
    with engine.begin() as conn:
        index_sql = conn.execute(_db.text(
            "SELECT sql FROM sqlite_master WHERE name='ux_assessor_availability_slot'")).scalar()
    assert "location_id" in index_sql
