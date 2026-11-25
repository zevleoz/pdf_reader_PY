"""Task K 验收：上海默认测评师、候选过滤顺序与分配面板的预选依据。"""
from datetime import date, datetime, timedelta

import pytest
from flask import Flask

import app_utils
import db as _db
import questionnaire_store as _qs
from blueprints import system as system_bp
from blueprints import tools as tools_bp
from blueprints import workspace as workspace_bp


@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = _db.create_engine(
        f"sqlite:///{tmp_path/'task_k.db'}", connect_args={"check_same_thread": False})
    _db.Base.metadata.create_all(engine)
    monkeypatch.setattr(_db, "engine", engine)
    monkeypatch.setattr(_qs, "engine", engine)
    monkeypatch.setattr(app_utils, "_SESSION_USER_CACHE", {})
    _db.ensure_locations()
    locs = {l["name"]: l["id"] for l in _db.list_locations()}
    sh, bj, sz = locs["上海"], locs["北京"], locs["深圳"]
    jeff = _db.create_user("jeff", "pw", "admin", display_name="Jeff",
                           is_assessor=1, office_ids=[sh, sz])
    zhou = _db.create_user("zhou", "pw", "advisor", display_name="周老师",
                           advisor_name="周老师", is_assessor=1, office_id=sh)
    chen = _db.create_user("chen", "pw", "advisor", display_name="陈老师",
                           advisor_name="陈老师", is_assessor=1, office_ids=[sh, sz])
    not_assessor = _db.create_user("ops", "pw", "admin", display_name="运营管理员",
                                   is_assessor=0, office_id=sh)
    inactive = _db.create_user("resting", "pw", "advisor", display_name="休假老师",
                               is_assessor=1, office_id=sh)
    _db.update_user(inactive, is_active=0)
    # 第二个办公室为 explicit：未排班时默认关闭
    explicit = _db.create_user("newoffice", "pw", "advisor", display_name="新授权老师",
                               is_assessor=1, office_ids=[sz, sh])
    bj_only = _db.create_user("beijing", "pw", "advisor", display_name="北京老师",
                              is_assessor=1, office_id=bj)
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(tools_bp.bp)
    app.register_blueprint(workspace_bp.bp)
    app.register_blueprint(system_bp.bp)
    app_utils.register_front_desk_guard(app)
    return {"app": app, "engine": engine, "sh": sh, "bj": bj, "sz": sz,
            "jeff": jeff, "zhou": zhou, "chen": chen, "not_assessor": not_assessor,
            "inactive": inactive, "explicit": explicit, "bj_only": bj_only}


def login(client, user_id, role="admin", name="Jeff"):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["username"] = name
        sess["role"] = role
        sess["display_name"] = name
        sess["advisor_name"] = name
        sess["student_scope"] = "all"
        sess["detail_level"] = "full"
        sess["m1_access"] = 0
        sess["m1_admin"] = 0


def staff_booking(client, loc, name, slot="10:00", day=None):
    target = day or date.today() + timedelta(days=1)
    return client.post("/api/bookings/staff", json={
        "location_id": loc, "new_name": name, "source": "internal",
        "requester_name": "王顾问",
        "appointment_time": f"{target.isoformat()}T{slot}:00",
    })


def candidate_rows(client, booking_id):
    data = client.get(f"/api/booking/{booking_id}/assessor-candidates").get_json()
    return data["candidates"]


def test_filter_step_that_empties_candidates_is_identifiable(world):
    """逐段核对：身份/启用 → 办公室授权 → 排班默认值/明确关闭 → 撞期。"""
    client = world["app"].test_client()
    login(client, world["jeff"])
    day = date.today() + timedelta(days=1)
    booking = staff_booking(client, world["sh"], "上海候选核对").get_json()["booking_id"]
    ids = {row["id"] for row in candidate_rows(client, booking)}

    # 1) 测评师身份、启用状态与角色过滤（SQL 层）
    assert world["jeff"] in ids and world["zhou"] in ids
    assert world["not_assessor"] not in ids
    assert world["inactive"] not in ids

    # 2) 办公室授权过滤
    assert world["bj_only"] not in ids

    # 3) 排班默认值：explicit 且无记录 → 排除
    assert world["explicit"] not in ids

    # 3b) 明确关闭 → 排除
    _db.set_assessor_availability(world["jeff"], world["sh"], day,
                                  [{"time_slot": "10:00", "is_available": False}])
    ids = {row["id"] for row in candidate_rows(client, booking)}
    assert world["jeff"] not in ids and world["zhou"] in ids

    # 4) 同刻撞期 → 排除（跨办公室同样占位）
    _db.set_assessor_availability(world["jeff"], world["sh"], day,
                                  [{"time_slot": "10:00", "is_available": True}])
    second = staff_booking(client, world["sh"], "同刻第二单").get_json()["booking_id"]
    assert _db.assign_booking_assessor(second, world["jeff"]) is None
    ids = {row["id"] for row in candidate_rows(client, booking)}
    assert world["jeff"] not in ids and world["zhou"] in ids


def test_configured_shanghai_default_is_first_and_survives_rename(world):
    day = date.today() + timedelta(days=1)
    _db.set_office_default_assessor(world["sh"], world["jeff"])
    assert _db.get_office_default_assessor(world["sh"]) == world["jeff"]
    assert _db.assessor_office_mode(world["jeff"], world["sh"]) == "legacy"

    client = world["app"].test_client()
    login(client, world["jeff"])
    booking = staff_booking(client, world["sh"], "上海默认首选").get_json()["booking_id"]
    rows = candidate_rows(client, booking)
    assert rows[0]["id"] == world["jeff"] and rows[0]["is_default"] is True
    assert sum(1 for row in rows if row["is_default"]) == 1

    _db.update_user(world["jeff"], display_name="Jeff 改名后")
    rows = candidate_rows(client, booking)
    assert rows[0]["id"] == world["jeff"] and rows[0]["is_default"] is True

    # 深圳预约不继承上海默认；候选里没有任何 is_default
    _db.set_assessor_availability(world["chen"], world["sz"], day,
                                  [{"time_slot": "10:00", "is_available": True}])
    sz_booking = {"id": 99999, "assessor_id": None,
                  "location_id": world["sz"],
                  "appointment_time": f"{day.isoformat()}T10:00:00"}
    sz_rows = _db.get_assessor_candidates(sz_booking)
    assert world["chen"] in {row["id"] for row in sz_rows}
    assert all(not row["is_default"] for row in sz_rows)


def test_existing_assignment_is_not_rewritten_and_still_selected_first(world):
    day = date.today() + timedelta(days=1)
    client = world["app"].test_client()
    login(client, world["jeff"])
    booking = staff_booking(client, world["sh"], "旧单改派核对", slot="11:00").get_json()["booking_id"]
    _db.assign_booking_assessor(booking, world["zhou"])

    _db.set_office_default_assessor(world["sh"], world["jeff"])
    assert _db.get_booking_detail(booking)["assessor_id"] == world["zhou"]
    rows = candidate_rows(client, booking)
    assert rows[0]["id"] == world["zhou"] and rows[0]["assigned"] is True

    # 未分配的新单才由前端按默认候选预选（接口同时给出 is_default）
    fresh = staff_booking(client, world["sh"], "新单预选核对", slot="11:00")
    assert fresh.status_code == 200, fresh.get_json()
    rows = candidate_rows(client, fresh.get_json()["booking_id"])
    assert rows[0]["id"] == world["jeff"] and rows[0]["is_default"] is True


def test_jeff_leave_or_shenzhen_clash_blocks_shanghai_assignment(world):
    day = date.today() + timedelta(days=1)
    _db.set_office_default_assessor(world["sh"], world["jeff"])
    _db.set_assessor_availability(world["jeff"], world["sz"], day,
                                  [{"time_slot": "10:00", "is_available": True}])
    client = world["app"].test_client()
    login(client, world["jeff"])
    sz_booking = staff_booking(client, world["sz"], "深圳同刻", slot="10:00")
    assert sz_booking.status_code == 200, sz_booking.get_json()
    assert _db.assign_booking_assessor(sz_booking.get_json()["booking_id"], world["jeff"]) is None

    sh_booking = staff_booking(client, world["sh"], "上海同刻", slot="10:00").get_json()["booking_id"]
    ids = {row["id"] for row in candidate_rows(client, sh_booking)}
    assert world["jeff"] not in ids and world["zhou"] in ids
    denied = client.post(f"/api/booking/{sh_booking}/assign", json={"assessor_id": world["jeff"]})
    assert denied.status_code == 409

    # 明确关闭（请假）时同样让位给其他合格老师
    _db.set_assessor_availability(world["jeff"], world["sh"], day,
                                  [{"time_slot": "13:00", "is_available": False}])
    leave_booking = staff_booking(client, world["sh"], "请假时段", slot="13:00").get_json()["booking_id"]
    ids = {row["id"] for row in candidate_rows(client, leave_booking)}
    assert world["jeff"] not in ids and world["zhou"] in ids


def test_empty_candidate_state_is_reproducible_and_actionable(world):
    """还原空候选：上海同刻所有授权测评师都无排班/被关闭，面板应给可操作说明。"""
    day = date.today() + timedelta(days=1)
    for uid in (world["jeff"], world["zhou"], world["chen"], world["explicit"]):
        _db.set_assessor_availability(uid, world["sh"], day,
                                      [{"time_slot": "15:00", "is_available": False}])
    with _db.Session(world["engine"]) as sess:
        booking = _db.Booking(
            student_name="空候选核对",
            appointment_time=datetime.combine(day, datetime.strptime("15:00", "%H:%M").time()),
            status="pending", location_id=world["sh"], source="internal")
        sess.add(booking)
        sess.commit()
        booking_id = booking.id
    assert _db.get_assessor_candidates(_db.get_booking_detail(booking_id)) == []


def test_default_assessor_config_is_idempotent_and_validated(world):
    _db._ensure_task_k_schema()
    _db._ensure_task_k_schema()  # 可重复执行
    _db.set_office_default_assessor(world["sh"], world["jeff"])
    _db.set_office_default_assessor(world["sh"], world["jeff"])
    assert _db.get_office_default_assessor(world["sh"]) == world["jeff"]
    assert _db.assessor_office_mode(world["jeff"], world["sh"]) == "legacy"
    assert _db.assessor_office_mode(world["jeff"], world["sz"]) == "explicit"

    with pytest.raises(ValueError):
        _db.set_office_default_assessor(world["sh"], world["not_assessor"])
    with pytest.raises(ValueError):
        _db.set_office_default_assessor(world["sh"], world["bj_only"])
    with pytest.raises(ValueError):
        _db.set_office_default_assessor(world["sh"], world["inactive"])
    with pytest.raises(ValueError):
        _db.set_office_default_assessor(99999, world["jeff"])
