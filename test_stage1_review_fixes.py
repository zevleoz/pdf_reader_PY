# -*- coding: utf-8 -*-
"""S1-P5：Stage 1 评审的修复。

覆盖评审指出的漏网路由（概要账号经 API 仍可读到纪要、问卷答案与联系方式）、
预约按名下学生隔离，以及 M1 权限检查先刷新会话。

不打桩 ``is_authenticated``：会话同步是被测对象，用户都真实落在独立 SQLite 里。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app_utils
import db as _db
import questionnaire_store as qs
from blueprints import m1 as m1_bp
from blueprints import questionnaires as questionnaires_bp
from blueprints import students as students_bp
from blueprints import tools as tools_bp

from test_questionnaire_scoring import World

PHONE = "13800000000"
EMAIL = "student@example.com"
MINUTES_ERROR = "当前账号不显示纪要内容。"
SUMMARY_ERROR = "当前账号只显示完成状态。"
SUMMARY_REASON = "当前账号只显示完成状态。"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/review_fixes.db")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    _db.Base.metadata.create_all(engine)
    qs.ensure_indexes(bind=engine)
    monkeypatch.setattr(qs, "engine", engine)
    monkeypatch.setattr(_db, "engine", engine)
    app_utils._SESSION_USER_CACHE.clear()
    w = World(engine)
    with Session(engine) as sess:
        mine = sess.get(_db.Student, w.student_id)
        mine.phone, mine.email = PHONE, EMAIL
        sess.commit()
    w.admin_id = 1
    w.full_viewer_id = _db.create_user("full-viewer", "pw-123456", "viewer",
                                       detail_level="full")
    w.summary_viewer_id = _db.create_user("summary-viewer", "pw-123456", "viewer")
    w.advisor_summary_id = _db.create_user("advisor-summary", "pw-123456", "advisor",
                                           advisor_name="Mine", detail_level="summary")
    w.advisor_full_id = _db.create_user("advisor-full", "pw-123456", "advisor",
                                        advisor_name="Mine", detail_level="full")
    w.advisor_all_id = _db.create_user("advisor-all", "pw-123456", "advisor",
                                       student_scope="all", detail_level="full")
    w.advisor_other_id = _db.create_user("advisor-other", "pw-123456", "advisor",
                                         advisor_name="Other")
    w.nameless_id = _db.create_user("nameless", "pw-123456", "advisor")

    w.minutes_id = _db.add_minutes(w.student_id, None, "逐字稿", "纪要正文")
    w.other_minutes_id = _db.add_minutes(w.other_id, None, "别的逐字稿", "别的纪要正文")
    w.assignment_id = w.submit("Q-DEP-01", 1)
    w.other_assignment_id = w.submit("Q-DEP-01", 1, student_id=w.other_id)

    w.booking_mine_id = _db.add_booking(
        "测试学生", datetime(2026, 10, 20, 10, 0), student_email=EMAIL,
        student_phone=PHONE, advisor_name="Mine", student_id=w.student_id)
    w.booking_other_id = _db.add_booking(
        "别的学生", datetime(2026, 10, 21, 10, 0), student_email="other@example.com",
        student_phone="13900000000", advisor_name="Other", student_id=w.other_id)
    yield w
    app_utils._SESSION_USER_CACHE.clear()
    engine.dispose()


@pytest.fixture()
def app(world):
    root = Path(__file__).resolve().parent
    application = Flask(__name__, template_folder=str(root / "templates"))
    application.secret_key = "test"
    application.config["TESTING"] = True
    for module in (tools_bp, m1_bp, questionnaires_bp, students_bp):
        application.register_blueprint(module.bp)
    application.jinja_env.filters["dt_short"] = app_utils.dt_short
    application.context_processor(lambda: {"csrf_token": lambda: "tok"})
    app_utils.register_admin_context(application)
    return application


def _client(app, user_id, role, advisor_name=""):
    """旧 session 形态：只有 role / advisor_name，缺三项设置。"""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role
        sess["advisor_name"] = advisor_name
    return client


def _set(user_id, **fields):
    assert _db.update_user(user_id, **fields)
    app_utils.invalidate_session_user(user_id)


def _clients(world, app):
    return {
        "full": _client(app, world.full_viewer_id, "viewer"),
        "summary": _client(app, world.summary_viewer_id, "viewer"),
        "advisor_summary": _client(app, world.advisor_summary_id, "advisor", "Mine"),
        "advisor_full": _client(app, world.advisor_full_id, "advisor", "Mine"),
    }


# ---------------------------------------------------------------------------
# §1 行 1：纪要详情
# ---------------------------------------------------------------------------
def test_minutes_detail_gated(world, app):
    clients = _clients(world, app)
    url = f"/api/minutes/{world.minutes_id}"
    full = clients["full"].get(url)
    assert full.status_code == 200 and full.get_json()["minutes_text"] == "纪要正文"
    summary = clients["summary"].get(url)
    assert summary.status_code == 403
    assert summary.get_json() == {"ok": False, "error": MINUTES_ERROR}


# ---------------------------------------------------------------------------
# §1 行 2：学生纪要列表
# ---------------------------------------------------------------------------
def test_student_minutes_list_gated(world, app):
    clients = _clients(world, app)
    url = f"/api/students/{world.student_id}/minutes"
    full = clients["full"].get(url).get_json()
    assert [m["id"] for m in full["minutes"]] == [world.minutes_id]
    summary = clients["summary"].get(url).get_json()
    assert summary == {"ok": True, "minutes": [], "restricted": True}


# ---------------------------------------------------------------------------
# §1 行 3：纪要 DOCX
# ---------------------------------------------------------------------------
def test_transcript_docx_gated_for_advisor(world, app):
    clients = _clients(world, app)
    payload = {"minutes_id": world.minutes_id}
    blocked = clients["advisor_summary"].post("/api/transcript/docx", json=payload)
    assert blocked.status_code == 403
    assert blocked.get_json() == {"ok": False, "error": MINUTES_ERROR}
    allowed = clients["advisor_full"].post("/api/transcript/docx", json=payload)
    assert allowed.status_code == 200
    assert allowed.get_data()[:2] == b"PK"


# ---------------------------------------------------------------------------
# §1 行 4：问卷作答
# ---------------------------------------------------------------------------
def test_assignment_response_gated(world, app):
    clients = _clients(world, app)
    url = f"/api/questionnaires/assignments/{world.assignment_id}/response"
    full = clients["full"].get(url)
    assert full.status_code == 200 and full.get_json()["response"]["answers"]
    summary = clients["summary"].get(url)
    assert summary.status_code == 403
    assert summary.get_json() == {"ok": False, "error": SUMMARY_ERROR}


# ---------------------------------------------------------------------------
# §1 行 5：任务列表的 reason 句子
# ---------------------------------------------------------------------------
def test_assignments_reason_is_a_sentence(world, app):
    clients = _clients(world, app)
    full = clients["full"].get("/api/questionnaires/assignments").get_json()
    assert next(r for r in full["assignments"]
                if r["id"] == world.assignment_id)["reason"] != SUMMARY_REASON
    summary = clients["summary"].get("/api/questionnaires/assignments").get_json()
    assert summary["assignments"]
    assert all(r["reason"] == SUMMARY_REASON for r in summary["assignments"])


# ---------------------------------------------------------------------------
# §1 行 6 / 行 7：联系方式
# ---------------------------------------------------------------------------
def test_api_bookings_hide_contact(world, app):
    clients = _clients(world, app)
    full = clients["full"].get("/api/bookings").get_json()["bookings"]
    assert next(b for b in full if b["id"] == world.booking_mine_id)["student_email"] == EMAIL
    summary = clients["summary"].get("/api/bookings").get_json()["bookings"]
    assert all(b["student_email"] == "" and b["student_phone"] == "" for b in summary)


def test_student_bookings_hide_contact(world, app):
    clients = _clients(world, app)
    url = "/students/Y4-9001/api/bookings"
    full = clients["full"].get(url).get_json()["bookings"]
    assert full[0]["student_email"] == EMAIL and full[0]["student_phone"] == PHONE
    summary = clients["summary"].get(url).get_json()["bookings"]
    assert [b["id"] for b in summary] == [world.booking_mine_id]
    assert summary[0]["student_email"] == "" and summary[0]["student_phone"] == ""


# ---------------------------------------------------------------------------
# §2 预约跟随名下学生
# ---------------------------------------------------------------------------
def test_bookings_follow_scope(world, app):
    admin = _client(app, world.admin_id, "admin")
    assert admin.get("/api/bookings").status_code == 200
    all_ids = {b["id"] for b in admin.get("/api/bookings").get_json()["bookings"]}
    assert all_ids == {world.booking_mine_id, world.booking_other_id}

    mentor = _client(app, world.advisor_all_id, "advisor")
    assert {b["id"] for b in mentor.get("/api/bookings").get_json()["bookings"]} == all_ids

    own = _client(app, world.advisor_summary_id, "advisor", "Mine")
    assert [b["id"] for b in own.get("/api/bookings").get_json()["bookings"]] == [
        world.booking_mine_id]

    _set(world.summary_viewer_id, student_scope="own", advisor_name="Mine")
    viewer = _client(app, world.summary_viewer_id, "viewer")
    assert [b["id"] for b in viewer.get("/api/bookings").get_json()["bookings"]] == [
        world.booking_mine_id]

    # 名下但没有绑定姓名：看不到任何预约
    nameless = _client(app, world.nameless_id, "advisor")
    assert nameless.get("/api/bookings").get_json()["bookings"] == []


def test_bookings_contact_for_own_summary_advisor(world, app):
    client = _client(app, world.advisor_summary_id, "advisor", "Mine")
    rows = client.get("/api/bookings").get_json()["bookings"]
    assert [b["id"] for b in rows] == [world.booking_mine_id]
    assert rows[0]["student_email"] == "" and rows[0]["student_phone"] == ""


# ---------------------------------------------------------------------------
# §4 测试 5：名下范围仍作用于被拦截的路由
# ---------------------------------------------------------------------------
def test_own_scope_still_blocks_other_advisor(world, app):
    client = _client(app, world.advisor_summary_id, "advisor", "Mine")
    assert client.get(f"/api/minutes/{world.other_minutes_id}").status_code == 403
    url = f"/api/questionnaires/assignments/{world.other_assignment_id}/response"
    assert client.get(url).status_code == 403


# ---------------------------------------------------------------------------
# §3 M1 权限检查：先刷新会话
# ---------------------------------------------------------------------------
def test_m1_turned_on_applies_without_relogin(world, app):
    uid = _db.create_user("m1-mentor", "pw-123456", "advisor", student_scope="all",
                          m1_access=0)
    client = _client(app, uid, "advisor")
    assert client.get("/api/m1/preps").status_code == 403
    with client.session_transaction() as sess:
        assert sess["m1_access"] == 0  # 旧 session 已同步为关闭

    assert _db.update_user(uid, m1_access=1)
    app_utils.invalidate_session_user(uid)
    assert client.get("/api/m1/preps").status_code == 200


def test_m1_turned_off_applies_without_relogin(world, app):
    uid = _db.create_user("m1-mentor-off", "pw-123456", "advisor", student_scope="all",
                          m1_access=1)
    client = _client(app, uid, "advisor")
    assert client.get("/api/m1/preps").status_code == 200
    with client.session_transaction() as sess:
        assert sess["m1_access"] == 1

    assert _db.update_user(uid, m1_access=0)
    app_utils.invalidate_session_user(uid)
    response = client.get("/api/m1/preps")
    assert response.status_code == 403
    assert response.get_json()["error"] == "当前账号没有 M1 权限"


def test_disabled_account_gets_401(world, app):
    uid = _db.create_user("m1-disabled", "pw-123456", "advisor", student_scope="all",
                          m1_access=1)
    client = _client(app, uid, "advisor")
    assert client.get("/api/m1/preps").status_code == 200

    assert _db.update_user(uid, is_active=0)
    app_utils.invalidate_session_user(uid)
    assert client.get("/api/m1/preps").status_code == 401
