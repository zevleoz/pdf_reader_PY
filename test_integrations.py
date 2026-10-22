"""Yuguo / CRM 集成测试（tmp SQLite；所有出站 HTTP 一律打桩）。

覆盖计划 Task 10 钉住的关键不变量：
- 老师目录 Bearer 鉴权（未配置 503 / 错误 401）与只含启用 Advisor；
- CRM 交付按 messageId + payload hash 幂等，同 ID 不同内容 409；
- 学生 revision 单调，过期版本 409；
- 单条导入失败（身份/版本冲突）不影响其他学生；
- 改派同步不回退旧版本，原顾问收到可已读通知；
- Yuguo 401 / 超时 / 连接失败的三种中文文案。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app_utils
import db as _db
import growth_talk_store as store
from blueprints import integrations as routes
from growth_talk import yuguo_client


class IntegrationDB:
    """tmp SQLite 上的用户/学生/外身份数据工厂。"""

    def __init__(self, engine):
        self.engine = engine
        self.admin_id = None
        self.alice_id = None
        self.bob_id = None
        self.carol_id = None
        self.student_id = None

    def seed(self):
        with Session(self.engine) as sess:
            admin = _db.User(username="admin", password_hash="x", role="admin",
                             display_name="管理员", is_active=1)
            alice = _db.User(username="alice", password_hash="x", role="advisor",
                             advisor_name="Alice", display_name="Alice",
                             email="alice@example.com", is_active=1)
            bob = _db.User(username="bob", password_hash="x", role="advisor",
                           advisor_name="Bob", display_name="Bob",
                           email="bob@example.com", is_active=1)
            carol = _db.User(username="carol", password_hash="x", role="advisor",
                             advisor_name="Carol", display_name="Carol",
                             email="carol@example.com", is_active=0)
            sess.add_all([admin, alice, bob, carol])
            sess.flush()
            student = _db.Student(student_code="Y4-9001", name="测试学生",
                                  grade="10", school="测试中学",
                                  advisor_name="Alice")
            sess.add(student)
            sess.commit()
            self.admin_id = admin.id
            self.alice_id = alice.id
            self.bob_id = bob.id
            self.carol_id = carol.id
            self.student_id = student.id


@pytest.fixture()
def idb(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'integrations.db'}")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables = [
        _db.User.__table__,
        _db.Student.__table__,
        store.ExternalIdentity.__table__,
        store.AuditLog.__table__,
        store.CrmDeliveryReceipt.__table__,
        store.CrmAppointment.__table__,
    ]
    _db.Base.metadata.create_all(engine, tables=tables)
    monkeypatch.setattr(_db, "engine", engine)

    helper = IntegrationDB(engine)
    helper.seed()
    yield helper
    engine.dispose()


@pytest.fixture()
def client(idb, monkeypatch):
    # 只跳过「会话用户是否仍有效」的检查；角色走真实实现。
    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    monkeypatch.setattr(routes, "_last_sync_at", 0.0)
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(routes.bp)
    return app.test_client()


def login_as(client, role="advisor", advisor_name="Alice", user_id=2,
             display_name="Alice"):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role
        sess["advisor_name"] = advisor_name
        sess["display_name"] = display_name


# ---------------------------------------------------------------------------
# 出站桩
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _delivery(**overrides):
    now = datetime.now(timezone.utc)
    payload = {
        "schema": "junction.student_delivery.1.1.0",
        "messageId": "crm-message-1",
        "junctionStudentId": "junction-1",
        "revision": 1,
        "recipient": "first_touch",
        "kind": "student",
        "status": "active",
        "teacherId": "3",
        "issuedAt": _iso(now),
        "expiresAt": _iso(now + timedelta(days=1)),
        "student": {"name": "新学生", "grade": "10", "school": "新中学",
                    "contactPhone": "+8613800000000"},
        "authorization": {"grantId": "grant-1", "purpose": "service_delivery",
                          "grantedAt": _iso(now), "expiresAt": None},
    }
    payload.update(overrides)
    return payload


def _appointment_delivery(**overrides):
    now = datetime.now(timezone.utc)
    payload = _delivery(
        messageId="crm-appointment-1",
        kind="appointment",
        status="scheduled",
        nativeStudentId="native-1",
        appointment={
            "taskId": "task-1",
            "startAt": _iso(now + timedelta(hours=2)),
            "endAt": _iso(now + timedelta(hours=3)),
            "moduleCode": "interview",
            "moduleName": "访谈",
        },
    )
    payload.pop("student", None)
    payload.update(overrides)
    return payload


def _student_payload(student_id, teacher_id, version=1, name="远端学生"):
    return {
        "students": [{
            "id": student_id, "name": name, "grade": "10",
            "school": "远端中学", "phone": None,
            "teacherId": str(teacher_id), "assignmentVersion": version,
        }],
        "rejectedStudents": [],
        "summary": {"assigned": 1, "exportable": 1, "rejected": 0},
    }


# ---------------------------------------------------------------------------
# 老师目录
# ---------------------------------------------------------------------------
def test_teachers_directory_auth_and_shape(client, idb, monkeypatch):
    token = "d" * 40
    # 未配置 token → 503
    monkeypatch.delenv("FIRST_TOUCH_DIRECTORY_TOKEN", raising=False)
    response = client.get("/api/integrations/teachers")
    assert response.status_code == 503

    monkeypatch.setenv("FIRST_TOUCH_DIRECTORY_TOKEN", token)
    response = client.get("/api/integrations/teachers",
                          headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401
    assert response.get_json() == {"error": "Unauthorized"}

    response = client.get("/api/integrations/teachers",
                          headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    teachers = response.get_json()["teachers"]
    assert [item["name"] for item in teachers] == ["Alice", "Bob"]
    assert all(set(item) == {"id", "name", "email"} for item in teachers)
    assert idb.carol_id not in [item["id"] for item in teachers]
    assert idb.admin_id not in [item["id"] for item in teachers]
    assert teachers[0]["email"] == "alice@example.com"


# ---------------------------------------------------------------------------
# CRM 交付
# ---------------------------------------------------------------------------
def _post_delivery(client, payload, token="c" * 40):
    return client.post("/api/integrations/crm/deliveries", json=payload,
                       headers={"Authorization": f"Bearer {token}"})


def test_crm_delivery_idempotent_replay(client, idb, monkeypatch):
    monkeypatch.setenv("CRM_INTEGRATION_TOKEN", "c" * 40)
    payload = _delivery(teacherId=str(idb.bob_id))

    first = _post_delivery(client, payload)
    assert first.status_code == 200
    body = first.get_json()
    assert body["messageId"] == payload["messageId"]
    assert body["recipient"] == "first_touch"
    assert body["status"] == "accepted"
    assert body["revision"] == 1
    student_id = body["studentId"]
    assert isinstance(student_id, int)

    second = _post_delivery(client, payload)
    assert second.status_code == 200
    assert second.get_json()["studentId"] == student_id
    assert len(store.list_audit()) == 0
    assert store.get_receipt(payload["messageId"])["student_id"] == student_id


def test_crm_delivery_conflicting_message_id(client, idb, monkeypatch):
    monkeypatch.setenv("CRM_INTEGRATION_TOKEN", "c" * 40)
    payload = _delivery(teacherId=str(idb.bob_id))
    assert _post_delivery(client, payload).status_code == 200

    conflicting = dict(payload, revision=payload["revision"] + 1)
    response = _post_delivery(client, conflicting)
    assert response.status_code == 409
    assert response.get_json()["message"] == "Message ID conflict"


def test_crm_delivery_stale_revision(client, idb, monkeypatch):
    monkeypatch.setenv("CRM_INTEGRATION_TOKEN", "c" * 40)
    newer = _delivery(teacherId=str(idb.bob_id), revision=3)
    assert _post_delivery(client, newer).status_code == 200

    stale = _delivery(messageId="crm-message-2", teacherId=str(idb.bob_id),
                      revision=2)
    response = _post_delivery(client, stale)
    assert response.status_code == 409
    assert response.get_json()["message"] == "Stale CRM student revision"


def test_crm_student_revoked_cancels_scheduled_appointments(client, idb,
                                                            monkeypatch):
    monkeypatch.setenv("CRM_INTEGRATION_TOKEN", "c" * 40)
    teacher = str(idb.bob_id)
    assert _post_delivery(client, _delivery(teacherId=teacher)).status_code == 200
    assert _post_delivery(client, _appointment_delivery(
        teacherId=teacher)).status_code == 200

    revoked = _delivery(messageId="crm-revoke-1", teacherId=teacher,
                        status="revoked", revision=2)
    revoked.pop("student")
    response = _post_delivery(client, revoked)
    assert response.status_code == 200

    appointment = store.get_appointment("task-1")
    assert appointment["status"] == "CANCELLED"
    student = _db.get_student(response.get_json()["studentId"])
    assert not (student.get("advisor_name") or "")


def test_crm_appointment_rejects_started_slot(client, idb, monkeypatch):
    monkeypatch.setenv("CRM_INTEGRATION_TOKEN", "c" * 40)
    teacher = str(idb.bob_id)
    assert _post_delivery(client, _delivery(teacherId=teacher)).status_code == 200

    now = datetime.now(timezone.utc)
    started = _appointment_delivery(
        teacherId=teacher,
        appointment={
            "taskId": "task-started",
            "startAt": _iso(now - timedelta(minutes=5)),
            "endAt": _iso(now + timedelta(minutes=55)),
            "moduleCode": "interview",
            "moduleName": "访谈",
        },
    )
    response = _post_delivery(client, started)
    assert response.status_code == 400
    assert response.get_json()["message"] == "Appointment has already started"


def test_crm_appointments_session_scope(client, idb, monkeypatch):
    monkeypatch.setenv("CRM_INTEGRATION_TOKEN", "c" * 40)
    assert _post_delivery(
        client, _delivery(teacherId=str(idb.bob_id))).status_code == 200
    assert _post_delivery(
        client, _appointment_delivery(teacherId=str(idb.bob_id))).status_code == 200

    login_as(client, role="advisor", advisor_name="Bob",
             user_id=idb.bob_id, display_name="Bob")
    response = client.get("/api/crm-appointments")
    assert response.status_code == 200
    appointments = response.get_json()["appointments"]
    assert [item["taskId"] for item in appointments] == ["task-1"]
    assert appointments[0]["status"] == "SCHEDULED"
    assert appointments[0]["teacherId"] == str(idb.bob_id)

    login_as(client, role="advisor", advisor_name="Alice",
             user_id=idb.alice_id, display_name="Alice")
    assert client.get("/api/crm-appointments").get_json()["appointments"] == []

    login_as(client, role="admin", advisor_name="", user_id=idb.admin_id,
             display_name="管理员")
    assert len(client.get("/api/crm-appointments").get_json()["appointments"]) == 1


# ---------------------------------------------------------------------------
# Yuguo 学生导入 / 改派
# ---------------------------------------------------------------------------
def test_import_yuguo_partial_failure_isolation(idb, monkeypatch):
    with Session(idb.engine) as sess:
        local = _db.Student(student_code="Y4-9002", name="本地学生",
                            advisor_name="Alice")
        sess.add(local)
        sess.flush()
        sess.add(store.ExternalIdentity(
            student_id=local.id, source_system="yuguo",
            external_student_id="yg-2",
            details=json.dumps({"assignmentVersion": 9, "teacherId": "2"}),
        ))
        sess.commit()
        local_id = local.id

    payload = {
        "students": [
            {"id": "yg-1", "name": "新学生", "grade": "10", "school": "远端中学",
             "phone": None, "teacherId": str(idb.bob_id), "assignmentVersion": 1},
            {"id": "yg-2", "name": "本地学生", "grade": "10", "school": "远端中学",
             "phone": None, "teacherId": str(idb.bob_id), "assignmentVersion": 2},
        ],
        "rejectedStudents": [],
        "summary": {"assigned": 2, "exportable": 2, "rejected": 0},
    }
    teacher = {"id": idb.bob_id, "role": "advisor", "advisor_name": "Bob",
               "display_name": "Bob", "username": "bob"}
    result = routes.import_yuguo_students(teacher, payload)

    assert result["localImport"]["status"] == "PARTIAL"
    assert result["localImport"]["created"] == 1
    assert result["localImport"]["conflicts"] == 1
    assert result["localImport"]["fetched"] == 2
    assert result["localImport"]["eligible"] == 2
    assert [item["id"] for item in result["rejectedStudents"]] == ["yg-2"]
    assert result["rejectedStudents"][0]["reasonCode"] == "LOCAL_CONFLICT"

    # 冲突学生保持原归属，新学生落到 Bob 名下并写入外身份。
    assert _db.get_student(local_id)["advisor_name"] == "Alice"
    new_id = store.find_student_by_external("yuguo", "yg-1")
    assert new_id and _db.get_student(new_id)["advisor_name"] == "Bob"
    identity = store.get_external_identity("yuguo", "yg-1")
    assert json.loads(identity["details"])["assignmentVersion"] == 1


def test_reconcile_stale_version_noop(idb, monkeypatch):
    with Session(idb.engine) as sess:
        local = _db.Student(student_code="Y4-9003", name="旧版本学生",
                            advisor_name="Bob")
        sess.add(local)
        sess.flush()
        sess.add(store.ExternalIdentity(
            student_id=local.id, source_system="yuguo",
            external_student_id="yg-3",
            details=json.dumps({"assignmentVersion": 5,
                                "teacherId": str(idb.bob_id)}),
        ))
        sess.commit()
        local_id = local.id

    monkeypatch.setattr(routes, "fetch_students_for_teacher",
                        lambda key: _student_payload("yg-3", idb.alice_id,
                                                     version=4))
    routes.reconcile_yuguo_assignments(force=True)

    assert _db.get_student(local_id)["advisor_name"] == "Bob"
    assert store.list_audit(action="yuguo_assignment_synced") == []


def test_assignment_notice_flow(client, idb, monkeypatch):
    with Session(idb.engine) as sess:
        local = _db.Student(student_code="Y4-9004", name="改派学生",
                            advisor_name="Alice")
        sess.add(local)
        sess.flush()
        sess.add(store.ExternalIdentity(
            student_id=local.id, source_system="yuguo",
            external_student_id="yg-4",
            details=json.dumps({"assignmentVersion": 1,
                                "teacherId": str(idb.alice_id)}),
        ))
        sess.commit()
        local_id = local.id

    monkeypatch.setattr(routes, "fetch_students_for_teacher",
                        lambda key: _student_payload("yg-4", idb.bob_id,
                                                     version=2))
    routes.reconcile_yuguo_assignments(force=True)

    assert _db.get_student(local_id)["advisor_name"] == "Bob"
    events = store.list_audit(action="yuguo_assignment_synced")
    assert len(events) == 1
    details = json.loads(events[0]["details"])
    assert details["removedTeacherName"] == "Alice"
    assert details["teacherName"] == "Bob"
    assert details["ownershipChanged"] is True

    notices = routes.assignment_notices_for("Alice")
    assert len(notices) == 1
    assert notices[0]["studentName"] == "改派学生"
    assert notices[0]["teacherName"] == "Bob"

    login_as(client, role="advisor", advisor_name="Alice",
             user_id=idb.alice_id, display_name="Alice")
    response = client.post("/api/account/assignment-sync",
                           json={"acknowledge": str(notices[0]["id"])})
    assert response.status_code == 200
    body = response.get_json()
    assert body["notices"] == []
    assert body["accessRevision"] == notices[0]["id"]
    assert routes.assignment_notices_for("Alice") == []


def test_import_route_uses_session_teacher(client, idb, monkeypatch):
    monkeypatch.setattr(
        routes, "fetch_students_for_teacher",
        lambda key: _student_payload("yg-5", idb.alice_id))
    login_as(client, role="advisor", advisor_name="Alice",
             user_id=idb.alice_id, display_name="Alice")

    response = client.post("/students/import-yuguo")
    assert response.status_code == 200
    result = response.get_json()
    assert result["localImport"]["created"] == 1
    assert result["localImport"]["status"] == "COMPLETED"
    assert store.find_student_by_external("yuguo", "yg-5") is not None


# ---------------------------------------------------------------------------
# 出站错误文案
# ---------------------------------------------------------------------------
def test_yuguo_error_mapping(monkeypatch):
    monkeypatch.setenv("YUGUO_BASE_URL", "https://yuguo.example.com")
    monkeypatch.setenv("YUGUO_STUDENT_READ_TOKEN", "r" * 32)

    def raise_http_401(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized",
                                     {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", raise_http_401)
    with pytest.raises(yuguo_client.YuguoError) as error:
        yuguo_client.fetch_students_for_teacher("1")
    assert "Yuguo 凭证不一致" in str(error.value)

    def raise_timeout(request, timeout=None):
        raise TimeoutError("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", raise_timeout)
    with pytest.raises(yuguo_client.YuguoError) as error:
        yuguo_client.fetch_students_for_teacher("1")
    assert "Yuguo 连接超时" in str(error.value)

    def raise_connection(request, timeout=None):
        raise urllib.error.URLError(ConnectionRefusedError("refused"))

    monkeypatch.setattr(urllib.request, "urlopen", raise_connection)
    with pytest.raises(yuguo_client.YuguoError) as error:
        yuguo_client.fetch_students_for_teacher("1")
    assert "无法连接 Yuguo" in str(error.value)


def test_yuguo_students_payload_validation(monkeypatch):
    monkeypatch.setenv("YUGUO_BASE_URL", "https://yuguo.example.com")
    monkeypatch.setenv("YUGUO_STUDENT_READ_TOKEN", "r" * 32)
    payload = _student_payload("yg-6", 2)
    payload["summary"]["assigned"] = 9  # 与 students/rejected 不一致

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda request, timeout=None: FakeResponse(payload))
    with pytest.raises(yuguo_client.YuguoError) as error:
        yuguo_client.fetch_students_for_teacher("2")
    assert "不兼容" in str(error.value)
