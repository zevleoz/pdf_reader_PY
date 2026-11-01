# -*- coding: utf-8 -*-
"""S1-P3：管理员账号页与档案页的可见范围 UI。

真实 session + 真实模板渲染；不打桩 ``is_authenticated``（会话同步是被测对象）。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask, session
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app_utils
import db as _db
import growth_talk_store  # noqa: F401  —— 注册 First Touch / copilot 表，档案页渲染需要
import questionnaire_store as qs
from blueprints import students as students_bp
from blueprints import system as system_bp

from test_questionnaire_scoring import World

PHONE = "13800000000"
EMAIL = "student@example.com"
ROOT = Path(__file__).resolve().parent


@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/profile_ui.db")

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
        st = sess.get(_db.Student, w.student_id)
        st.phone, st.email = PHONE, EMAIL
        sess.commit()
    w.admin_id = 1
    w.summary_id = _db.create_user("readonly", "pw-123456", "viewer")
    yield w
    app_utils._SESSION_USER_CACHE.clear()
    engine.dispose()


@pytest.fixture()
def app(world):
    application = Flask(__name__, template_folder=str(ROOT / "templates"))
    application.secret_key = "test"
    application.config["TESTING"] = True
    for module in (students_bp, system_bp):
        application.register_blueprint(module.bp)
    application.jinja_env.filters["dt_short"] = app_utils.dt_short
    application.context_processor(lambda: {"csrf_token": lambda: "tok"})
    app_utils.register_admin_context(application)
    return application


def _client(app, user_id, role, advisor_name=""):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role
        sess["advisor_name"] = advisor_name
    return client


def _body(client, url):
    resp = client.get(url)
    assert resp.status_code == 200, url
    return resp.get_data(as_text=True)


# ── 1. 账号页控件 ────────────────────────────────────────────────
def test_account_screen_has_visibility_controls(world, app):
    body = _body(_client(app, world.admin_id, "admin"), "/system/users")
    for control in ('id="nsc"', 'id="ndl"', 'id="nm1"'):
        assert control in body
    assert "只读" in body
    assert "查阅者" not in body


# ── 2. M1 权限打开的顾问 ────────────────────────────────────────
def test_profile_shows_m1_link_when_enabled(world, app):
    uid = _db.create_user("m1-on", "pw-123456", "advisor",
                          student_scope="all", detail_level="full", m1_access=1)
    body = _body(_client(app, uid, "advisor"), "/students/Y4-9001")
    assert 'href="/m1?student=' in body
    assert "M1 会前准备" not in body
    assert ">M1</a>" in body


# ── 3. M1 关闭的顾问 / 只读 ─────────────────────────────────────
def test_profile_hides_m1_link_when_off_or_viewer(world, app):
    off = _db.create_user("m1-off", "pw-123456", "advisor",
                          student_scope="all", detail_level="full", m1_access=0)
    assert 'href="/m1?student=' not in _body(_client(app, off, "advisor"), "/students/Y4-9001")
    assert 'href="/m1?student=' not in _body(
        _client(app, world.summary_id, "viewer"), "/students/Y4-9001")


# ── 4/5. 概要 / 完整 的联系方式 ─────────────────────────────────
def test_profile_summary_hides_contact_details(world, app):
    body = _body(_client(app, world.summary_id, "viewer"), "/students/Y4-9001")
    assert PHONE not in body and EMAIL not in body
    assert "邮箱：" not in body and "电话：" not in body


def test_profile_full_shows_contact_details(world, app):
    uid = _db.create_user("full-viewer", "pw-123456", "viewer", detail_level="full")
    body = _body(_client(app, uid, "viewer"), "/students/Y4-9001")
    assert PHONE in body and EMAIL in body


# ── 6. 6AM 标签页端点 ───────────────────────────────────────────
def test_profile_sixam_uses_dash_path_and_endpoint_ok(world, app):
    text = (ROOT / "templates" / "student_360.html").read_text(encoding="utf-8")
    assert "this.get('six-am')" in text
    assert "this.get('sixam')" not in text
    resp = _client(app, world.summary_id, "viewer").get("/students/Y4-9001/api/six-am")
    assert resp.status_code == 200


# ── 7. 学生列表的导出按钮 ───────────────────────────────────────
def test_students_page_export_only_for_full(world, app):
    summary = _body(_client(app, world.summary_id, "viewer"), "/students")
    assert "/api/export" not in summary
    uid = _db.create_user("full-viewer-2", "pw-123456", "viewer", detail_level="full")
    full = _body(_client(app, uid, "viewer"), "/students")
    assert 'href="/api/export"' in full
