"""Task C 验收：内部预约来源、账号交接、测评师分配、前台隔离。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from flask import Flask

import app_utils
import db as _db
import questionnaire_store as _qs
from blueprints import tools as tools_bp
from blueprints import workspace as workspace_bp


@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = _db.create_engine(
        f"sqlite:///{tmp_path/'task_c.db'}", connect_args={"check_same_thread": False})
    _db.Base.metadata.create_all(engine)
    monkeypatch.setattr(_db, "engine", engine)
    monkeypatch.setattr(_qs, "engine", engine)
    monkeypatch.setattr(app_utils, "_SESSION_USER_CACHE", {})
    _db.ensure_locations()
    locs = {l["name"]: l["id"] for l in _db.list_locations()}
    sh = locs.get("上海") or next(iter(locs.values()))
    bj = locs.get("北京") or next(v for k, v in locs.items() if v != sh)

    admin = _db.create_user("admin", "pw", "admin", display_name="总管",
                            is_assessor=1, office_id=sh)
    advisor = _db.create_user("advisor1", "pw", "advisor", display_name="李顾问",
                              advisor_name="李顾问", office_id=sh)
    a_sh = _db.create_user("a_sh", "pw", "advisor", display_name="张测评",
                           advisor_name="张测评", is_assessor=1, office_id=sh)
    a_bj = _db.create_user("a_bj", "pw", "advisor", display_name="王测评",
                           advisor_name="王测评", is_assessor=1, office_id=bj)
    front_sh = _db.create_user("front_sh", "pw", "front", display_name="前台小周",
                               office_id=sh)
    front_bj = _db.create_user("front_bj", "pw", "front", display_name="前台小王",
                               office_id=bj)

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(tools_bp.bp)
    app.register_blueprint(workspace_bp.bp)
    app_utils.register_front_desk_guard(app)
    return {
        "app": app, "engine": engine, "sh": sh, "bj": bj,
        "admin": admin, "advisor": advisor, "a_sh": a_sh, "a_bj": a_bj,
        "front_sh": front_sh, "front_bj": front_bj,
    }


def login(client, user_id, role, name, advisor_name="", office_id=None):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["username"] = name
        sess["role"] = role
        sess["display_name"] = name
        sess["advisor_name"] = advisor_name
        sess["student_scope"] = "none" if role == "front" else "all"
        sess["detail_level"] = "full"
        sess["m1_access"] = 0
        sess["m1_admin"] = 0
        if office_id is not None:
            sess["office_id"] = office_id


def tomorrow(slot="10:00"):
    d = date.today() + timedelta(days=1)
    return d, slot


def staff_booking(client, loc, name, slot="10:00", source="internal", requester="王顾问",
                  day=None):
    d, slot = tomorrow(slot)
    return client.post("/api/bookings/staff", json={
        "location_id": loc, "new_name": name, "source": source,
        "requester_name": requester,
        "appointment_time": f"{(day or d).isoformat()}T{slot}:00",
    })


def test_staff_booking_source_and_account_handoff_idempotent(world):
    client = world["app"].test_client()
    login(client, world["admin"], "admin", "总管")
    r = staff_booking(client, world["sh"], "陈同学", source="referral")
    assert r.status_code == 200, r.get_json()
    bid = r.get_json()["booking_id"]

    h = client.get(f"/api/booking/{bid}/handoff").get_json()["booking"]
    assert h["source"] == "referral" and h["source_label"] == "转介绍"
    assert h["requester_name"] == "王顾问"
    assert h["account"]["exists"] is False

    first = client.post(f"/api/booking/{bid}/handoff/account").get_json()
    second = client.post(f"/api/booking/{bid}/handoff/account").get_json()
    assert first["created"] is True and first["password"]
    assert second["created"] is False and second["password"] is None
    assert first["username"] == second["username"]
    assert first["student_id"] == second["student_id"] == h["student_id"]
    with _db.Session(world["engine"]) as sess:
        assert sess.query(_qs.StudentAccount).filter_by(
            student_id=h["student_id"]).count() == 1


def test_two_offices_same_name_students_get_distinct_accounts(world):
    client = world["app"].test_client()
    login(client, world["admin"], "admin", "总管")
    r1 = staff_booking(client, world["sh"], "同名学生")
    r2 = staff_booking(client, world["bj"], "同名学生", slot="11:00")
    assert r1.status_code == 200 and r2.status_code == 200
    b1, b2 = r1.get_json()["booking_id"], r2.get_json()["booking_id"]
    h1 = client.get(f"/api/booking/{b1}/handoff").get_json()["booking"]
    h2 = client.get(f"/api/booking/{b2}/handoff").get_json()["booking"]
    assert h1["student_id"] != h2["student_id"]
    assert h1["student_code"] != h2["student_code"]
    a1 = client.post(f"/api/booking/{b1}/handoff/account").get_json()
    a2 = client.post(f"/api/booking/{b2}/handoff/account").get_json()
    assert a1["username"] != a2["username"]


def test_assign_validates_office_availability_and_conflict(world):
    client = world["app"].test_client()
    login(client, world["admin"], "admin", "总管")
    d, slot = tomorrow("10:00")
    b1 = staff_booking(client, world["sh"], "甲同学").get_json()["booking_id"]
    b2 = staff_booking(client, world["sh"], "乙同学").get_json()["booking_id"]

    cands = client.get(f"/api/booking/{b1}/assessor-candidates").get_json()["candidates"]
    ids = {c["id"] for c in cands}
    assert world["a_sh"] in ids and world["admin"] in ids
    assert world["a_bj"] not in ids

    # 跨办公室拒绝
    bad = client.post(f"/api/booking/{b1}/assign", json={"assessor_id": world["a_bj"]})
    assert bad.status_code == 400 and "办公室" in bad.get_json()["error"]

    # 关闭时段后不可分配
    _db.set_assessor_availability(world["a_sh"], world["sh"], d,
                                  [{"time_slot": slot, "is_available": False}])
    closed = client.post(f"/api/booking/{b1}/assign", json={"assessor_id": world["a_sh"]})
    assert closed.status_code == 400 and "不可约" in closed.get_json()["error"]

    # 正常分配后再把同一测评师分给同一时段的另一预约 → 冲突
    _db.set_assessor_availability(world["a_sh"], world["sh"], d,
                                  [{"time_slot": slot, "is_available": True}])
    ok = client.post(f"/api/booking/{b1}/assign", json={"assessor_id": world["a_sh"]})
    assert ok.status_code == 200
    conflict = client.post(f"/api/booking/{b2}/assign", json={"assessor_id": world["a_sh"]})
    assert conflict.status_code == 409 and "已有" in conflict.get_json()["error"]
    left = client.get(f"/api/booking/{b2}/assessor-candidates").get_json()["candidates"]
    assert world["a_sh"] not in {c["id"] for c in left}


def test_front_desk_only_today_office_and_no_backend_access(world):
    admin_client = world["app"].test_client()
    login(admin_client, world["admin"], "admin", "总管")
    today = date.today()
    r1 = staff_booking(admin_client, world["sh"], "今日学生", day=today)
    r2 = staff_booking(admin_client, world["bj"], "北京学生", day=today)
    b1 = r1.get_json()["booking_id"]
    b2 = r2.get_json()["booking_id"]
    code1 = admin_client.get(f"/api/booking/{b1}/handoff").get_json()["booking"]["student_code"]

    front = world["app"].test_client()
    login(front, world["front_sh"], "front", "前台小周", office_id=world["sh"])
    listed = front.get("/api/handoff/bookings").get_json()["bookings"]
    assert {b["id"] for b in listed} == {b1}
    assert front.get(f"/api/booking/{b1}/handoff").status_code == 200
    assert front.get(f"/api/booking/{b2}/handoff").status_code == 403
    assert front.post(f"/api/booking/{b1}/handoff/account").status_code == 200

    # 直达后台接口全部拒绝
    assert front.get(f"/api/profiling/students/{code1}").status_code == 403
    assert front.get(f"/api/students/{code1}/y4").status_code == 403
    assert front.get(f"/students/{code1}/api/y4/build/file").status_code == 403
    assert front.get(f"/api/bookings/week?loc={world['sh']}").status_code == 403
    assert front.get(f"/api/students").status_code == 403

    # 非当日预约也不能处理
    fut = date.today() + timedelta(days=2)
    future = staff_booking(admin_client, world["sh"], "未来学生", day=fut).get_json()["booking_id"]
    assert front.get(f"/api/booking/{future}/handoff").status_code == 403


def test_front_can_login_and_logout_through_guard(world):
    from blueprints import auth as auth_bp

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(auth_bp.bp)
    app.register_blueprint(tools_bp.bp)
    app_utils.register_front_desk_guard(app)
    client = app.test_client()
    login(client, world["front_sh"], "front", "前台小周", office_id=world["sh"])

    r = client.post("/api/admin/login", json={"username": "front_sh", "password": "pw"})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["role"] == "front"
    # 已登录前台仍可打开交接列表，也能正常退出
    assert client.get("/api/handoff/bookings").status_code == 200
    assert client.post("/api/admin/logout").status_code == 200
    assert client.get("/api/handoff/bookings").status_code == 401


def test_parent_invite_is_single_use_and_keeps_staff_attribution(world):
    client = world["app"].test_client()
    login(client, world["advisor"], "advisor", "李顾问", "李顾问")
    inv = client.post("/api/bookings/invite",
                      json={"location_id": world["sh"], "source": "referral"}).get_json()
    assert inv["ok"] and "/booking?invite=" in inv["url"]
    d, slot = tomorrow("10:00")
    payload = {"location_id": world["sh"], "student_name": "邀请学生",
               "appointment_time": f"{d.isoformat()}T{slot}:00",
               "invite": inv["invite_token"]}
    pub = world["app"].test_client()
    r = pub.post("/api/booking", json=payload)
    assert r.status_code == 200, r.get_json()
    h = client.get(f"/api/booking/{r.get_json()['booking_id']}/handoff").get_json()["booking"]
    assert h["source"] == "referral"
    assert h["created_by"] == world["advisor"]
    assert h["requester_name"] == "李顾问"
    again = pub.post("/api/booking", json={**payload, "appointment_time":
                                           f"{tomorrow('11:00')[0].isoformat()}T11:00:00"})
    assert again.status_code == 409


def test_assessor_availability_is_self_service_only(world):
    client = world["app"].test_client()
    login(client, world["a_sh"], "advisor", "张测评", "张测评")
    d, slot = tomorrow("13:00")
    r = client.post("/api/assessor/availability", json={
        "date": d.isoformat(),
        "slots": [{"time_slot": slot, "is_available": False}],
    })
    assert r.status_code == 200
    got = client.get(f"/api/assessor/availability?start={d.isoformat()}&days=1").get_json()
    assert got["availability"][d.isoformat()][slot] is False

    non_assessor = world["app"].test_client()
    login(non_assessor, world["advisor"], "advisor", "李顾问", "李顾问")
    assert non_assessor.get("/api/assessor/availability").status_code == 403


def test_profile_schedule_exposes_assignment(world):
    client = world["app"].test_client()
    login(client, world["admin"], "admin", "总管")
    bid = staff_booking(client, world["sh"], "档案学生").get_json()["booking_id"]
    code = client.get(f"/api/booking/{bid}/handoff").get_json()["booking"]["student_code"]
    client.post(f"/api/booking/{bid}/assign", json={"assessor_id": world["a_sh"]})
    body = client.get(f"/api/profiling/students/{code}/schedule").get_json()
    assert body["ok"] and body["can_assign"] is True
    row = body["bookings"][0]
    assert row["assessor_id"] == world["a_sh"]
    assert row["assessor_name"] == "张测评"
    assert row["source"] == "internal"


def test_role_change_to_front_applies_before_backend_route(world):
    from blueprints import students as students_bp

    app = world["app"]
    app.register_blueprint(students_bp.bp)
    client = app.test_client()
    login(client, world["advisor"], "advisor", "李顾问", advisor_name="李顾问")
    assert client.get("/students/absent/api/y4/build/file").status_code == 404
    _db.update_user(world["advisor"], role="front", office_id=world["sh"])
    app_utils.invalidate_session_user(world["advisor"])
    assert client.get("/students/absent/api/y4/build/file").status_code == 403


def test_staff_retry_reuses_booking_and_student_across_sessions(world):
    request_id = str(uuid4())
    d, slot = tomorrow()
    start = Barrier(2)

    def submit(_):
        client = world["app"].test_client()
        login(client, world["advisor"], "advisor", "李顾问", advisor_name="李顾问")
        start.wait(timeout=10)
        return client.post("/api/bookings/staff", json={
            "location_id": world["sh"], "new_name": "重复确认测试",
            "appointment_time": f"{d.isoformat()}T{slot}:00", "request_id": request_id,
        })

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(submit, range(2))
    assert first.status_code == second.status_code == 200
    assert first.get_json() == second.get_json()
    with _db.Session(world["engine"]) as sess:
        assert sess.query(_db.Booking).filter_by(staff_request_id=request_id).count() == 1
        assert sess.query(_db.Student).filter_by(name="重复确认测试").count() == 1


def test_same_second_invites_are_distinct_and_concurrent_redemption_is_single_use(world):
    owner = world["app"].test_client()
    login(owner, world["advisor"], "advisor", "李顾问", advisor_name="李顾问")
    payload = {"location_id": world["sh"], "source": "referral"}
    first = owner.post("/api/bookings/invite", json=payload).get_json()["invite_token"]
    second = owner.post("/api/bookings/invite", json=payload).get_json()["invite_token"]
    assert first != second
    d, _ = tomorrow()
    start = Barrier(2)

    def redeem(slot):
        client = world["app"].test_client()
        start.wait(timeout=10)
        return client.post("/api/booking", json={
            "location_id": world["sh"], "student_name": "一次性邀请测试",
            "appointment_time": f"{d.isoformat()}T{slot}:00", "invite": first,
        })

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(redeem, ("10:00", "11:00")))
    assert sorted(r.status_code for r in responses) == [200, 409]
    with _db.Session(world["engine"]) as sess:
        assert sess.query(_db.Booking).filter_by(invite_token=first).count() == 1
        assert sess.query(_db.Student).filter_by(name="一次性邀请测试").count() == 1


def test_concurrent_account_handoff_reuses_existing_account(world, monkeypatch):
    admin = world["app"].test_client()
    login(admin, world["admin"], "admin", "总管")
    booking = staff_booking(admin, world["sh"], "并发账号向导").get_json()["booking_id"]
    original_hash = _qs.generate_password_hash
    before_insert = Barrier(2)

    def synchronized_hash(password):
        before_insert.wait(timeout=10)
        return original_hash(password)

    monkeypatch.setattr(_qs, "generate_password_hash", synchronized_hash)

    def issue(_):
        client = world["app"].test_client()
        login(client, world["admin"], "admin", "总管")
        return client.post(f"/api/booking/{booking}/handoff/account")

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(issue, range(2)))
    assert [r.status_code for r in responses] == [200, 200]
    accounts = [r.get_json() for r in responses]
    assert len({(a["student_id"], a["username"]) for a in accounts}) == 1
    assert sum(a["created"] for a in accounts) == sum(bool(a["password"]) for a in accounts) == 1
