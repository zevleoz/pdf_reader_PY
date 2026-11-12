# -*- coding: utf-8 -*-
"""S1-P1：账号可见范围（可见学生 / 可见内容 / M1 权限）的存储、策略与服务端强制。

不打桩 ``is_authenticated``：会话同步是被测对象，用户都真实落在独立 SQLite 里。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from flask import Flask, session
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

import app_utils
import db as _db
import questionnaire_store as qs
from blueprints import auth as auth_bp
from blueprints import questionnaires as questionnaires_bp
from blueprints import reports as reports_bp
from blueprints import students as students_bp
from blueprints import system as system_bp
from m1 import store as m1_store

from test_questionnaire_scoring import World

PHONE = "13800000000"
EMAIL = "student@example.com"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/visibility.db")

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
        for student_id in (w.student_id, w.other_id):
            report = _db.Report(
                student_id=student_id, report_date=date(2026, 9, 2), pdf_path="r.pdf",
                data_json=json.dumps({"schema_124": [
                    {"code": "072", "value": "SAE", "type": "string"}]}))
            sess.add(report)
            sess.flush()
            if student_id == w.student_id:
                w.report_id = report.id
            else:
                w.other_report_id = report.id
        sess.commit()
    w.admin_id = 1
    w.mine_id = _db.create_user("mine", "pw-123456", "advisor", advisor_name="Mine")
    w.summary_id = _db.create_user("readonly", "pw-123456", "viewer")
    yield w
    app_utils._SESSION_USER_CACHE.clear()
    engine.dispose()


@pytest.fixture()
def app(world):
    root = Path(__file__).resolve().parent
    application = Flask(__name__, template_folder=str(root / "templates"))
    application.secret_key = "test"
    application.config["TESTING"] = True
    for module in (auth_bp, questionnaires_bp, reports_bp, students_bp, system_bp):
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


# ── 1. 迁移 ─────────────────────────────────────────────────────
def test_migration_adds_columns_and_keeps_rows(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username VARCHAR(100) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL, role VARCHAR(20) NOT NULL DEFAULT 'viewer',
        advisor_name VARCHAR(100), display_name VARCHAR(100),
        is_active INTEGER NOT NULL DEFAULT 1, created_at DATETIME)""")
    conn.execute("INSERT INTO users (username, password_hash, role, advisor_name) "
                 "VALUES ('old-advisor', 'h', 'advisor', 'Mine'), ('old-viewer', 'h', 'viewer', NULL)")
    conn.commit()
    conn.close()

    url = f"sqlite:///{path}"
    engine = create_engine(url)
    monkeypatch.setattr(_db, "engine", engine)
    monkeypatch.setattr(_db, "DATABASE_URL", url)
    _db.init_db()
    _db.init_db()  # 幂等

    conn = sqlite3.connect(path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    conn.close()
    assert {"student_scope", "detail_level", "m1_access"} <= columns

    by_name = {u["username"]: u for u in _db.list_users()}
    assert by_name["old-advisor"]["advisor_name"] == "Mine"
    assert by_name["old-advisor"]["student_scope"] == "own"
    assert by_name["old-viewer"]["detail_level"] == "summary"
    engine.dispose()


# ── 2. 默认值 ───────────────────────────────────────────────────
@pytest.mark.parametrize("role,scope,detail,m1", [
    ("admin", "all", "full", 1),
    ("advisor", "own", "full", 1),
    ("viewer", "all", "summary", 0),
])
def test_role_defaults(world, app, role, scope, detail, m1):
    uid = _db.create_user("u-" + role, "pw-123456", role,
                          advisor_name="Mine" if role == "advisor" else "")
    user = _db.get_user_by_id(uid)
    assert (user["student_scope"], user["detail_level"], user["m1_access"]) == (scope, detail, m1)
    # 旧 session（缺三项）解析出同样的结果
    with app.test_request_context():
        session.update(user_id=uid, role=role, advisor_name="Mine")
        policy = app_utils.account_policy()
        assert (policy["student_scope"], policy["detail_level"], policy["m1_access"]) == (
            scope, detail, m1)
        assert app_utils.can_see_full() is (detail == "full")
        assert app_utils.can_use_m1() is bool(m1)


def test_stored_row_is_blank_until_admin_chooses(world):
    with Session(world.engine) as sess:
        row = sess.get(_db.User, world.mine_id)
        assert row.student_scope == "" and row.detail_level == "" and row.m1_access is None


def test_invalid_values_are_rejected(world):
    for fields in ({"student_scope": "some"}, {"detail_level": "half"}, {"m1_access": 5}):
        with pytest.raises(ValueError, match="可见学生或可见内容的取值无效"):
            _db.update_user(world.mine_id, **fields)
    with pytest.raises(ValueError, match="可见学生或可见内容的取值无效"):
        _db.create_user("bad", "pw-123456", "viewer", student_scope="some")


def test_blank_resets_to_role_default(world):
    _set(world.mine_id, student_scope="all", detail_level="summary", m1_access=0)
    _set(world.mine_id, student_scope="", detail_level="", m1_access="")
    user = _db.get_user_by_id(world.mine_id)
    assert (user["student_scope"], user["detail_level"], user["m1_access"]) == ("own", "full", 1)


# ── 3. 顾问 + 全部学生 ──────────────────────────────────────────
def test_advisor_all_reads_other_advisors_student(world, app):
    mentor = _db.create_user("mentor", "pw-123456", "advisor", student_scope="all")
    client = _client(app, mentor, "advisor")
    assert client.get("/students/Y4-9002/api/reports").status_code == 200
    with app.test_request_context():
        session.update(role="advisor", advisor_name="", student_scope="all")
        assert app_utils._advisor_scope() is None
        stmt = select(_db.Student)
        assert str(app_utils.visible_student_filter(stmt)) == str(stmt)


# ── 4. 顾问 + 名下（默认）───────────────────────────────────────
def test_advisor_own_default_unchanged(world, app):
    client = _client(app, world.mine_id, "advisor", "Mine")
    assert client.get("/students/Y4-9001/api/reports").status_code == 200
    assert client.get("/students/Y4-9002/api/reports").status_code == 403
    names = {s["name"] for s in client.get("/api/students").get_json()["students"]}
    assert names == {"测试学生"}


# ── 5. 只读 + 名下 ──────────────────────────────────────────────
def test_viewer_own_is_narrowed(world, app):
    _set(world.summary_id, student_scope="own", advisor_name="Mine")
    client = _client(app, world.summary_id, "viewer")
    assert client.get("/students/Y4-9001/api/reports").status_code == 200
    assert client.get("/students/Y4-9002/api/reports").status_code == 403
    found = client.get("/api/students/search?q=学生").get_json()["students"]
    assert {s["name"] for s in found} == {"测试学生"}


def test_own_needs_a_name(world):
    with pytest.raises(ValueError, match="名下学生范围需要绑定顾问姓名"):
        _db.update_user(world.summary_id, student_scope="own")
    with pytest.raises(ValueError, match="名下学生范围需要绑定顾问姓名"):
        _db.create_user("nameless", "pw-123456", "viewer", student_scope="own")
    # 已显式 own 的账号不能把姓名清空
    _set(world.summary_id, student_scope="own", advisor_name="Mine")
    with pytest.raises(ValueError, match="名下学生范围需要绑定顾问姓名"):
        _db.update_user(world.summary_id, advisor_name="")


def test_viewer_m1_is_stored_as_zero(world):
    _set(world.summary_id, m1_access=1)
    with Session(world.engine) as sess:
        assert sess.get(_db.User, world.summary_id).m1_access == 0
    assert _db.get_user_by_id(world.summary_id)["m1_access"] == 0


# ── 6. 概要 ─────────────────────────────────────────────────────
@pytest.fixture()
def clients(world, app):
    """同一账号的两种可见内容：完整 / 概要。"""
    full_id = _db.create_user("full-viewer", "pw-123456", "viewer", detail_level="full")
    return {"full": _client(app, full_id, "viewer"),
            "summary": _client(app, world.summary_id, "viewer")}


def test_summary_api_students_hides_contact(world, clients):
    def row(client):
        students = client.get("/api/students").get_json()["students"]
        return next(s for s in students if s["id"] == world.student_id)
    assert (row(clients["full"])["phone"], row(clients["full"])["email"]) == (PHONE, EMAIL)
    assert (row(clients["summary"])["phone"], row(clients["summary"])["email"]) == ("", "")


def test_summary_student_360(world, clients, monkeypatch):
    world.submit("Q-DEP-01", 1)
    captured = {}

    def fake_render(_template, **context):
        captured.update(context)
        return "ok"

    monkeypatch.setattr(students_bp, "render_template", fake_render)
    assert clients["full"].get("/students/Y4-9001").status_code == 200
    assert captured["profile"]["phone"] == PHONE and captured["questionnaire_flags"]
    assert clients["summary"].get("/students/Y4-9001").status_code == 200
    assert captured["profile"]["phone"] == "" and captured["profile"]["email"] == ""
    assert captured["questionnaire_flags"] == []
    assert captured["profile"]["name"] == "测试学生"


def test_summary_profile_scores(world, clients):
    world.submit("Q-DEP-01", 1)
    assert clients["full"].get("/students/Y4-9001/api/profile").get_json()["questionnaire_scores"]
    summary = clients["summary"].get("/students/Y4-9001/api/profile").get_json()
    assert summary["questionnaire_scores"] == []
    assert summary["report"]["id"] == world.report_id  # Y4 指标仍可见


def test_summary_questionnaires(world, clients):
    aid = world.submit("Q-DEP-01", 1)
    with Session(world.engine) as sess:
        sess.get(qs.Assignment, aid).reason = "内部原因"
        sess.commit()
    full = clients["full"].get("/students/Y4-9001/api/questionnaires").get_json()
    assert "restricted" not in full
    item = full["assignments"][0]
    assert item["answers"] and item["scores"] and item["reason"] == "内部原因"

    summary = clients["summary"].get("/students/Y4-9001/api/questionnaires").get_json()
    assert summary["restricted"] is True
    item = summary["assignments"][0]
    assert item["answers"] is None and item["scores"] is None and item["reason"] == ""
    assert item["status"] == "submitted"  # 完成状态仍可见


def test_summary_minutes(world, clients):
    _db.add_minutes(world.student_id, None, "逐字稿", "纪要正文")
    full = clients["full"].get("/students/Y4-9001/api/minutes").get_json()
    assert full["minutes"][0]["minutes_text"] == "纪要正文"
    assert clients["summary"].get("/students/Y4-9001/api/minutes").get_json() == {
        "ok": True, "minutes": [], "restricted": True}


def test_summary_report_raw_forbidden(world, clients):
    url = f"/api/reports/{world.report_id}/raw"
    assert clients["full"].get(url).status_code == 200
    response = clients["summary"].get(url)
    assert response.status_code == 403
    assert response.get_json()["error"] == "当前账号不能查看原始数据"


def test_summary_open_flags_empty(world, clients):
    aid = world.submit("Q-DEP-01", 1)
    full = clients["full"].get("/api/questionnaires/assignments").get_json()
    assert [f["assignment_id"] for f in full["open_flags"]] == [aid]
    assert next(r for r in full["assignments"] if r["id"] == aid)["flagged"] is True
    summary = clients["summary"].get("/api/questionnaires/assignments").get_json()
    assert summary["open_flags"] == []
    assert next(r for r in summary["assignments"] if r["id"] == aid)["flagged"] is False


# ── 7. 导出 ─────────────────────────────────────────────────────
def test_export_summary_forbidden_full_allowed(clients):
    assert clients["full"].get("/api/export").status_code == 200
    response = clients["summary"].get("/api/export")
    assert response.status_code == 403
    assert response.get_json()["error"] == "当前账号不能导出"


def test_export_respects_scope(world, app):
    own = _client(app, world.mine_id, "advisor", "Mine").get("/api/export")
    assert own.status_code == 200
    text = own.get_data(as_text=True)
    assert "测试学生" in text and "别的学生" not in text

    mentor = _db.create_user("mentor", "pw-123456", "advisor", student_scope="all")
    text = _client(app, mentor, "advisor").get("/api/export").get_data(as_text=True)
    assert "测试学生" in text and "别的学生" in text


# ── 8. M1 store ─────────────────────────────────────────────────
def test_m1_store_scopes(world):
    mine_prep = m1_store.create_prep(world.student_id, created_by=world.mine_id)
    other_prep = m1_store.create_prep(world.other_id, created_by=1)
    both_students = {world.student_id, world.other_id}
    both_preps = {mine_prep["id"], other_prep["id"]}

    def preps(user):
        return {p["id"] for p in m1_store.list_preps(user=user)}

    def students(user):
        return {s["id"] for s in m1_store.list_students(user)}

    every = {"user_id": 50, "role": "advisor", "advisor_name": "", "student_scope": "all"}
    assert preps(every) == both_preps and students(every) == both_students
    assert m1_store.can_access_student(every, world.other_id)
    assert m1_store.can_access_prep(every, other_prep["id"])

    # 缺字段的调用方按默认 own，行为不变
    own = {"user_id": world.mine_id, "role": "advisor", "advisor_name": "Mine"}
    assert preps(own) == {mine_prep["id"]} and students(own) == {world.student_id}
    assert m1_store.can_access_student(own, world.student_id)
    assert not m1_store.can_access_student(own, world.other_id)
    assert not m1_store.can_access_prep(own, other_prep["id"])

    # 空姓名不拥有任何学生（即使学生的顾问也为空）
    with Session(world.engine) as sess:
        nobody = _db.Student(student_code="Y4-9003", name="无顾问", advisor_name="")
        sess.add(nobody)
        sess.commit()
        nobody_id = nobody.id
    unassigned = m1_store.create_prep(nobody_id, created_by=1)
    nameless = {"user_id": 51, "role": "advisor", "advisor_name": ""}
    assert unassigned["id"] not in preps(nameless) and students(nameless) == set()

    viewer = {"user_id": 52, "role": "viewer", "advisor_name": "", "student_scope": "all"}
    assert preps(viewer) == set() and students(viewer) == set()
    assert not m1_store.can_access_student(viewer, world.student_id)
    assert not m1_store.can_access_prep(viewer, mine_prep["id"])


# ── 9. 管理员不可被降低 ─────────────────────────────────────────
def test_admin_cannot_be_lowered_through_api(world, app):
    client = _client(app, world.admin_id, "admin")
    response = client.put(f"/api/users/{world.admin_id}", json={
        "student_scope": "own", "detail_level": "summary", "m1_access": 0})
    assert response.status_code == 200
    user = _db.get_user_by_id(world.admin_id)
    assert (user["student_scope"], user["detail_level"], user["m1_access"]) == ("all", "full", 1)
    with Session(world.engine) as sess:
        row = sess.get(_db.User, world.admin_id)
        assert (row.student_scope, row.detail_level, row.m1_access) == ("all", "full", 1)
    # 防锁死仍生效
    assert client.put(f"/api/users/{world.admin_id}",
                      json={"role": "viewer"}).status_code == 400


def test_role_change_does_not_carry_old_settings(world):
    other_admin = _db.create_user("admin2", "pw-123456", "admin")
    _set(other_admin, role="viewer")
    user = _db.get_user_by_id(other_admin)
    assert (user["student_scope"], user["detail_level"], user["m1_access"]) == (
        "all", "summary", 0)


def test_api_round_trip_and_errors(world, app):
    client = _client(app, world.admin_id, "admin")
    created = client.post("/api/users", json={
        "username": "m1-mentor", "password": "pw-123456", "role": "advisor",
        "student_scope": "all", "detail_level": "full", "m1_access": 1}).get_json()
    assert created["ok"]
    listed = {u["id"]: u for u in client.get("/api/users").get_json()["users"]}
    mentor = listed[created["id"]]
    assert (mentor["student_scope"], mentor["detail_level"], mentor["m1_access"]) == (
        "all", "full", 1)
    assert listed[world.summary_id]["detail_level"] == "summary"

    bad = client.post("/api/users", json={
        "username": "x", "password": "pw-123456", "role": "viewer", "student_scope": "own"})
    assert bad.status_code == 400 and bad.get_json()["error"] == "名下学生范围需要绑定顾问姓名"
    bad = client.put(f"/api/users/{world.summary_id}", json={"detail_level": "half"})
    assert bad.status_code == 400 and bad.get_json()["error"] == "可见学生或可见内容的取值无效"
    # null 恢复默认
    assert client.put(f"/api/users/{created['id']}",
                      json={"student_scope": None, "advisor_name": "Mine"}).status_code == 200
    assert _db.get_user_by_id(created["id"])["student_scope"] == "own"


def test_login_sets_effective_values(world, app):
    client = app.test_client()
    response = client.post("/api/admin/login",
                           json={"username": "readonly", "password": "pw-123456"})
    assert response.get_json()["ok"]
    with client.session_transaction() as sess:
        assert (sess["student_scope"], sess["detail_level"], sess["m1_access"]) == (
            "all", "summary", 0)


# ── 10. 无需重新登录 ────────────────────────────────────────────
def test_put_applies_to_existing_session(world, app):
    admin = _client(app, world.admin_id, "admin")
    target = _client(app, world.mine_id, "advisor", "Mine")
    assert target.get("/students/Y4-9002/api/reports").status_code == 403
    assert target.get("/api/export").status_code == 200

    assert admin.put(f"/api/users/{world.mine_id}", json={
        "student_scope": "all", "detail_level": "summary"}).status_code == 200

    assert target.get("/students/Y4-9002/api/reports").status_code == 200
    assert target.get("/api/export").status_code == 403
    with target.session_transaction() as sess:
        assert sess["student_scope"] == "all" and sess["detail_level"] == "summary"


def test_role_and_delete_apply_to_existing_session(world, app):
    admin = _client(app, world.admin_id, "admin")
    target = _client(app, world.mine_id, "advisor", "Mine")
    assert target.get("/api/students").status_code == 200

    assert admin.put(f"/api/users/{world.mine_id}", json={"role": "viewer"}).status_code == 200
    assert target.get("/api/students").status_code == 200
    with target.session_transaction() as sess:
        assert sess["role"] == "viewer"

    assert admin.delete(f"/api/users/{world.mine_id}").status_code == 200
    assert target.get("/api/students").status_code == 401


def test_other_workers_catch_up_after_ttl(world, app, monkeypatch):
    """未调用 invalidate 时（其他 worker）旧快照保留到 TTL 结束。"""
    target = _client(app, world.mine_id, "advisor", "Mine")
    assert target.get("/api/export").status_code == 200
    assert _db.update_user(world.mine_id, detail_level="summary")
    assert target.get("/api/export").status_code == 200
    now = app_utils.time.time()
    monkeypatch.setattr(app_utils.time, "time", lambda: now + app_utils._SESSION_USER_TTL + 1)
    assert target.get("/api/export").status_code == 403


# ── 11. 导航 ────────────────────────────────────────────────────
def _hrefs(role):
    return [link["href"] for group in app_utils.nav_for_role(role) for link in group["links"]]


def test_nav_m1_follows_account_setting(world, app):
    with app.test_request_context():
        session.update(user_id=world.mine_id, role="advisor", advisor_name="Mine")
        assert "/m1" in _hrefs("advisor")
        groups = app_utils.nav_for_role("advisor")
        assert groups[-1]["key"] == "other" and groups[-1]["title"] == "其他平台"
        # T1：其他平台组的第一项改为回选择平台的「所有平台」，其后是 M1
        assert [link["label"] for link in groups[-1]["links"]] == ["所有平台", "心有灵析"]
        assert [link["href"] for link in groups[-1]["links"]] == ["/platforms", "/m1"]
        session["m1_access"] = 0
        assert "/m1" not in _hrefs("advisor")
        assert "other" not in [g["key"] for g in app_utils.nav_for_role("advisor")]
    with app.test_request_context():
        session.update(user_id=world.summary_id, role="viewer", m1_access=1)
        assert "/m1" not in _hrefs("viewer")


def test_nav_without_request_context_has_no_m1(monkeypatch):
    monkeypatch.delenv("E4_URL", raising=False)
    assert "/m1" not in _hrefs("admin")


def test_nav_e4_only_with_env(app, monkeypatch):
    monkeypatch.delenv("E4_URL", raising=False)
    with app.test_request_context():
        assert not [h for h in _hrefs("viewer") if "e4" in h]
    monkeypatch.setenv("E4_URL", "https://e4.example.test")
    with app.test_request_context():
        groups = app_utils.nav_for_role("viewer")
        link = groups[-1]["links"][-1]
        assert link["key"] == "e4" and link["href"] == "https://e4.example.test"
        assert link["blank"] is True


def test_policy_in_template_context(world, app):
    with app.test_request_context():
        session.update(user_id=world.summary_id, role="viewer")
        from flask import render_template_string
        assert render_template_string("{{ policy.detail_level }}") == "summary"
