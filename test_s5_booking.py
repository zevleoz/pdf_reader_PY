# -*- coding: utf-8 -*-
"""S5-R1：办公室、预约 API、公开预约页。独立 SQLite，不碰真实库，不调用 AI。"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app_utils
import db as _db
from blueprints import tools as tools_bp

SH, BJ, SZ = "上海", "北京", "深圳"


def _iso(d, t="10:00"):
    return f"{d.isoformat()}T{t}:00"


def _tomorrow():
    return date.today() + timedelta(days=1)


@pytest.fixture()
def world(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/s5.db"
    engine = create_engine(url)
    monkeypatch.setattr(_db, "engine", engine)
    monkeypatch.setattr(_db, "DATABASE_URL", url)
    _db.Base.metadata.create_all(engine)
    _db.ensure_locations()
    app_utils._SESSION_USER_CACHE.clear()
    with Session(engine) as sess:
        sess.add(_db.User(id=1, username="admin", password_hash="x", role="admin"))
        sess.commit()
    _db.create_user("mine", "pw-123456", "advisor", advisor_name="Mine")
    yield engine
    app_utils._SESSION_USER_CACHE.clear()
    engine.dispose()


@pytest.fixture()
def app(world):
    root = Path(__file__).resolve().parent
    application = Flask(__name__, template_folder=str(root / "templates"))
    application.secret_key = "test"
    application.config["TESTING"] = True
    application.register_blueprint(tools_bp.bp)
    application.context_processor(lambda: {"csrf_token": lambda: "tok"})
    app_utils.register_admin_context(application)
    return application


def _login(app, user_id, role, advisor_name=""):
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"], s["role"], s["advisor_name"] = user_id, role, advisor_name
    return c


@pytest.fixture()
def admin(app):
    return _login(app, 1, "admin")


@pytest.fixture()
def advisor(app, world):
    with Session(world) as sess:
        uid = sess.execute(select(_db.User.id).where(_db.User.username == "mine")).scalar()
    return _login(app, uid, "advisor", "Mine")


def _loc(name):
    return next(l["id"] for l in _db.list_locations(active_only=False) if l["name"] == name)


def _public(client, d, t="10:00", loc=None, name="小明", **extra):
    body = {"student_name": name, "appointment_time": _iso(d, t), **extra}
    if loc is not None:
        body["location_id"] = loc
    return client.post("/api/booking", json=body)


# ── 数据与迁移 ─────────────────────────────────────────────────
def test_seed_offices_in_order(world):
    assert [l["name"] for l in _db.list_locations()] == [SH, BJ, SZ]
    assert _db.ensure_locations() == _loc(SH)
    assert len(_db.list_locations(active_only=False)) == 3  # 不重复写入


def test_migration_moves_null_rows_to_shanghai_and_is_idempotent(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE bookings (id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_name VARCHAR(100) NOT NULL, student_email VARCHAR(200), student_phone VARCHAR(50),
        appointment_time DATETIME NOT NULL, status VARCHAR(20), notes TEXT, created_at DATETIME)""")
    conn.execute("""CREATE TABLE availability (id INTEGER PRIMARY KEY AUTOINCREMENT,
        date DATE NOT NULL, time_slot VARCHAR(10) NOT NULL, is_available INTEGER, created_at DATETIME)""")
    conn.execute("INSERT INTO bookings (student_name, appointment_time, status) VALUES ('旧', '2026-12-01 10:00:00', 'pending')")
    conn.execute("INSERT INTO availability (date, time_slot, is_available) VALUES ('2026-12-01', '10:00', 0)")
    conn.commit()
    conn.close()
    url = f"sqlite:///{path}"
    engine = create_engine(url)
    monkeypatch.setattr(_db, "engine", engine)
    monkeypatch.setattr(_db, "DATABASE_URL", url)
    try:
        _db.init_db()
        _db.init_db()  # 第二次：不变
        sh = _loc(SH)
        with Session(engine) as sess:
            assert [r[0] for r in sess.execute(select(_db.Booking.location_id))] == [sh]
            assert [r[0] for r in sess.execute(select(_db.Availability.location_id))] == [sh]
            assert sess.execute(select(_db.Location.id)).all().__len__() == 3
    finally:
        engine.dispose()


# ── 规则：每办公室容量、日期窗口 ───────────────────────────────
def test_capacity_is_per_office(app, world):
    c = app.test_client()
    d, sh, bj = _tomorrow(), _loc(SH), _loc(BJ)
    for i in range(4):
        assert _public(c, d, loc=sh, name=f"学生{i}").status_code == 200
    r = _public(c, d, loc=sh, name="第五位")
    assert r.status_code == 409
    assert _public(c, d, loc=bj, name="北京的").status_code == 200
    slots = c.get(f"/api/availability?date={d}&loc={sh}").get_json()["slots"]
    assert next(s for s in slots if s["time_slot"] == "10:00")["booked_count"] == 4
    slots = c.get(f"/api/availability?date={d}&loc={bj}").get_json()["slots"]
    assert next(s for s in slots if s["time_slot"] == "10:00")["booked_count"] == 1


def test_closed_slot_is_per_office(app, admin):
    c, d = app.test_client(), _tomorrow()
    sh, bj = _loc(SH), _loc(BJ)
    admin.post("/api/availability/bulk", json={"location_id": sh, "changes": [
        {"date": d.isoformat(), "time": "10:00", "open": False}]})
    assert _public(c, d, loc=sh).status_code == 409
    assert _public(c, d, loc=bj).status_code == 200


def test_date_window_enforced_server_side(app):
    c = app.test_client()
    today = date.today()
    for bad in (today, today - timedelta(days=1), today + timedelta(days=30)):
        r = _public(c, bad)
        assert r.status_code == 400 and r.get_json()["error"]
    assert _public(c, today + timedelta(days=1)).status_code == 200
    assert _public(c, today + timedelta(days=29), name="最后一天").status_code == 200


def test_bad_slot_time_and_office(app):
    c, d = app.test_client(), _tomorrow()
    assert _public(c, d, t="12:00").status_code == 400
    assert _public(c, d, loc=9999).status_code == 404
    assert _public(c, d, loc="x").status_code == 400
    assert c.post("/api/booking", json={"student_name": "x", "appointment_time": "bad"}).status_code == 400


def test_old_calls_without_loc_use_shanghai(app, admin):
    c, d = app.test_client(), _tomorrow()
    assert _public(c, d).status_code == 200  # 无 location_id
    sh = _loc(SH)
    with Session(_db.engine) as sess:
        assert sess.execute(select(_db.Booking.location_id)).scalar() == sh
    slots = c.get(f"/api/availability?date={d}").get_json()["slots"]
    assert next(s for s in slots if s["time_slot"] == "10:00")["booked_count"] == 1
    month = c.get("/api/availability/month").get_json()
    assert month["ok"] and month["bookings"][d.isoformat()]["10:00"] == 1
    # 旧的 POST /api/availability 不带 location_id → 上海
    r = admin.post("/api/availability", json={"date": d.isoformat(),
                   "slots": [{"time_slot": "11:00", "is_available": False}]})
    assert r.get_json()["ok"]
    got = c.get(f"/api/availability?date={d}&loc={sh}").get_json()["slots"]
    assert next(s for s in got if s["time_slot"] == "11:00")["is_open"] is False
    got = c.get(f"/api/availability?date={d}&loc={_loc(BJ)}").get_json()["slots"]
    assert next(s for s in got if s["time_slot"] == "11:00")["is_open"] is True


def test_locations_api_lists_active_only(app, world):
    with Session(world) as sess:
        sess.execute(_db.update(_db.Location).where(_db.Location.name == SZ).values(active=0))
        sess.commit()
    got = app.test_client().get("/api/locations").get_json()["locations"]
    assert [l["name"] for l in got] == [SH, BJ]
    assert set(got[0]) == {"id", "name"}


# ── 学生：公开预约总是新建；员工可关联 ─────────────────────────
def test_public_booking_creates_new_student_even_with_same_name(app, world):
    with Session(world) as sess:
        sess.add(_db.Student(student_code="Y4-0001", name="重名", advisor_name="Other"))
        sess.commit()
    r = _public(app.test_client(), _tomorrow(), name="重名", advisor_name="Mine", school="某校").get_json()
    with Session(world) as sess:
        studs = sess.execute(select(_db.Student).where(_db.Student.name == "重名")).all()
        assert len(studs) == 2
        new = sess.get(_db.Student, r["student_id"])
        assert new.student_code != "Y4-0001" and new.advisor_name == "Mine" and new.school == "某校"
        assert sess.get(_db.Student, studs[0][0].id).advisor_name == "Other"  # 旧学生未被改动


def test_staff_booking_links_existing_student(app, admin, world):
    with Session(world) as sess:
        st = _db.Student(student_code="Y4-0002", name="已有", advisor_name="Mine", school="甲校")
        sess.add(st)
        sess.commit()
        sid = st.id
    d = date.today()
    r = admin.post("/api/bookings/staff", json={"location_id": _loc(BJ), "appointment_time": _iso(d, "16:30"),
                                                 "student_code": "Y4-0002"})
    assert r.status_code == 200 and r.get_json()["ok"]  # 员工可约今天
    with Session(world) as sess:
        b = sess.get(_db.Booking, r.get_json()["booking_id"])
        assert b.student_id == sid and b.location_id == _loc(BJ) and b.student_name == "已有"
        assert sess.execute(select(_db.Student)).all().__len__() == 1


def test_staff_booking_new_name_and_rules(app, admin, world):
    sh = _loc(SH)
    ok = admin.post("/api/bookings/staff", json={"location_id": sh, "appointment_time": _iso(_tomorrow()),
                                                  "new_name": "新同学"})
    assert ok.status_code == 200
    with Session(world) as sess:
        assert sess.execute(select(_db.Student).where(_db.Student.name == "新同学")).first()
    far = date.today() + timedelta(days=30)
    assert admin.post("/api/bookings/staff", json={"location_id": sh, "appointment_time": _iso(far),
                                                    "new_name": "x"}).status_code == 400
    assert admin.post("/api/bookings/staff", json={"location_id": sh, "appointment_time": _iso(_tomorrow()),
                                                    "student_code": "NOPE"}).status_code == 404
    assert admin.post("/api/bookings/staff", json={"location_id": sh, "appointment_time": _iso(_tomorrow()),
                                                    "student_code": "a", "new_name": "b"}).status_code in (400, 404)
    for i in range(3):
        _public(app.test_client(), _tomorrow(), loc=sh, name=f"占{i}")
    full = admin.post("/api/bookings/staff", json={"location_id": sh, "appointment_time": _iso(_tomorrow()),
                                                    "new_name": "第五"})
    assert full.status_code == 409  # 已有 4 人（含上面员工约的 1 人）


def test_staff_booking_requires_login_and_undo_by_cancel(app, admin, world):
    sh, d = _loc(SH), _tomorrow()
    assert app.test_client().post("/api/bookings/staff", json={}).status_code == 401
    bid = admin.post("/api/bookings/staff", json={"location_id": sh, "appointment_time": _iso(d),
                                                   "new_name": "撤销"}).get_json()["booking_id"]
    assert admin.post(f"/api/booking/{bid}/cancel").get_json()["ok"]
    slots = app.test_client().get(f"/api/availability?date={d}&loc={sh}").get_json()["slots"]
    assert next(s for s in slots if s["time_slot"] == "10:00")["booked_count"] == 0


# ── 批量开关 ──────────────────────────────────────────────────
def test_bulk_close_refuses_booked_and_applies_rest(app, admin):
    c, d, sh = app.test_client(), _tomorrow(), _loc(SH)
    _public(c, d, t="10:00", loc=sh)
    r = admin.post("/api/availability/bulk", json={"location_id": sh, "changes": [
        {"date": d.isoformat(), "time": "10:00", "open": False},
        {"date": d.isoformat(), "time": "10:30", "open": False}]}).get_json()
    assert r["ok"] and r["refused"] == [{"date": d.isoformat(), "time": "10:00"}]
    slots = c.get(f"/api/availability?date={d}&loc={sh}").get_json()["slots"]
    by = {s["time_slot"]: s for s in slots}
    assert by["10:00"]["is_open"] is True and by["10:30"]["is_open"] is False
    # 取消后可以关闭；重新开放也可以
    bid = admin.get("/api/bookings/week", query_string={"loc": sh, "start": d.isoformat()}).get_json()
    cell = next(s for s in bid["slots"] if s["time"] == "10:00" and s["date"] == d.isoformat())
    admin.post(f"/api/booking/{cell['bookings'][0]['id']}/cancel")
    r = admin.post("/api/availability/bulk", json={"location_id": sh, "changes": [
        {"date": d.isoformat(), "time": "10:00", "open": False},
        {"date": d.isoformat(), "time": "10:30", "open": True}]}).get_json()
    assert r["refused"] == []


def test_bulk_validation_and_cancelled_does_not_block(app, admin):
    sh = _loc(SH)
    for bad in ({"location_id": sh}, {"location_id": sh, "changes": [{"date": "x", "time": "10:00", "open": True}]},
                {"location_id": sh, "changes": [{"date": "2030-01-01", "time": "12:00", "open": True}]},
                {"location_id": sh, "changes": [{"date": "2030-01-01", "time": "10:00", "open": "yes"}]}):
        assert admin.post("/api/availability/bulk", json=bad).status_code == 400
    assert admin.post("/api/availability/bulk", json={"location_id": 9999, "changes": []}).status_code == 404


def test_bulk_forbidden_for_non_admin(app, advisor):
    body = {"location_id": _loc(SH), "changes": []}
    assert advisor.post("/api/availability/bulk", json=body).status_code == 403
    assert app.test_client().post("/api/availability/bulk", json=body).status_code == 401
    assert advisor.post("/api/availability", json={"date": _tomorrow().isoformat(), "slots": []}).status_code == 403


# ── 周视图 ────────────────────────────────────────────────────
def test_week_shape_and_location_updated_at(app, admin):
    c, d, sh = app.test_client(), _tomorrow(), _loc(SH)
    before = admin.get("/api/bookings/week", query_string={"loc": sh, "start": d.isoformat()}).get_json()
    assert len(before["slots"]) == 7 * 14 and before["location"]["id"] == sh
    assert set(before["slots"][0]) == {"date", "time", "closed", "past", "count", "bookings"}
    _public(c, d, loc=sh)
    after = admin.get("/api/bookings/week", query_string={"loc": sh, "start": d.isoformat()}).get_json()
    assert after["location"]["updated_at"] > before["location"]["updated_at"]
    cell = next(s for s in after["slots"] if s["date"] == d.isoformat() and s["time"] == "10:00")
    assert cell["count"] == 1 and set(cell["bookings"][0]) == {"id", "student_name", "student_code", "status"}
    # 另一办公室的更新时间不变
    bj = _loc(BJ)
    assert admin.get("/api/bookings/week", query_string={"loc": bj, "start": d.isoformat()}).get_json()["slots"][0]["count"] == 0
    # 无 loc 默认上海
    assert admin.get("/api/bookings/week", query_string={"start": d.isoformat()}).get_json()["location"]["id"] == sh
    # 过去的时段标 past
    mon = date.today() - timedelta(days=date.today().weekday())
    wk = admin.get("/api/bookings/week", query_string={"loc": sh, "start": (mon - timedelta(days=7)).isoformat()}).get_json()
    assert all(s["past"] for s in wk["slots"])


def test_week_masks_contact_and_scopes_advisor(app, admin, advisor, world):
    d, sh = _tomorrow(), _loc(SH)
    c = app.test_client()
    _public(c, d, t="09:00", loc=sh, name="我的学生", advisor_name="Mine")
    _public(c, d, t="09:00", loc=sh, name="别人学生", advisor_name="Other")
    with Session(world) as sess:
        sess.execute(_db.update(_db.Booking).values(student_email="a@b.c", student_phone="13800000000"))
        sess.commit()
    q = {"loc": sh, "start": d.isoformat()}
    full = admin.get("/api/bookings/week", query_string=q)
    mine = advisor.get("/api/bookings/week", query_string=q)
    for resp in (full, mine):
        assert "13800000000" not in resp.get_data(as_text=True) and "a@b.c" not in resp.get_data(as_text=True)
    cell = lambda r: next(s for s in r.get_json()["slots"] if s["date"] == d.isoformat() and s["time"] == "09:00")
    assert cell(full)["count"] == 2 and len(cell(full)["bookings"]) == 2
    assert cell(mine)["count"] == 2  # 顾问看到全部计数
    assert [b["student_name"] for b in cell(mine)["bookings"]] == ["我的学生"]
    assert app.test_client().get("/api/bookings/week").status_code == 401


# ── 页面 ──────────────────────────────────────────────────────
def test_booking_page_renders_with_and_without_loc(app):
    c = app.test_client()
    for url in ("/booking", f"/booking?loc={_loc(BJ)}"):
        r = c.get(url)
        html = r.get_data(as_text=True)
        assert r.status_code == 200 and "已预约" in html and "/api/locations" in html
        assert "fonts.googleapis" not in html and "gstatic" not in html and "http://" not in html


# ── 容量竞态：检查与插入原子 ───────────────────────────────────
def test_capacity_check_is_atomic_in_db_helper(world):
    d, sh = _tomorrow(), _loc(SH)
    appt = datetime.combine(d, datetime.strptime("10:00", "%H:%M").time())
    for i in range(3):
        _db.create_booking_with_student(f"s{i}", appt, location_id=sh, match_existing=False, capacity=4)
    # 路由层的预检查可能都读到 3；两次写入只能成功一次
    _db.create_booking_with_student("第四", appt, location_id=sh, match_existing=False, capacity=4)
    with pytest.raises(_db.SlotUnavailable) as ei:
        _db.create_booking_with_student("第五", appt, location_id=sh, match_existing=False, capacity=4)
    assert ei.value.kind == "full"
    with pytest.raises(_db.SlotUnavailable):
        _db.add_booking("第六", appt, location_id=sh, capacity=4)
    assert _db.get_slot_booking_counts(d, sh)["10:00"] == 4


def test_route_returns_409_when_precheck_is_bypassed(app, monkeypatch):
    d, sh = _tomorrow(), _loc(SH)
    c = app.test_client()
    for i in range(3):
        _public(c, d, loc=sh, name=f"a{i}")
    monkeypatch.setattr(tools_bp, "_slot_error", lambda *a, **k: None)  # 模拟两个请求都通过预检查
    assert _public(c, d, loc=sh, name="b1").status_code == 200
    assert _public(c, d, loc=sh, name="b2").status_code == 409
