# -*- coding: utf-8 -*-
"""任务 I：老师个人设置与本人改密。

覆盖：登录名只读展示、当前密码校验、两次新密码一致、CSRF、匿名与前台拒绝、
不能借改密接口修改他人/角色/办公室、他人账号不受影响。
"""
from __future__ import annotations

import pytest
from flask import Flask
from sqlalchemy import create_engine

import app_utils
import db as _db
from blueprints import auth as auth_bp

CSRF = "csrf-test-token"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/account.db")
    _db.Base.metadata.create_all(engine)
    monkeypatch.setattr(_db, "engine", engine)
    app_utils._SESSION_USER_CACHE.clear()
    ids = {
        "teacher": _db.create_user("teacher", "old-pass", "advisor", display_name="陈老师"),
        "other": _db.create_user("other", "other-pass", "advisor", display_name="周老师"),
        "admin": _db.create_user("boss", "boss-pass", "admin", display_name="管理员"),
        "viewer": _db.create_user("viewer", "view-pass", "viewer", display_name="只读"),
        "front": _db.create_user("front", "front-pass", "front", office_id=1),
    }
    yield ids
    app_utils._SESSION_USER_CACHE.clear()
    engine.dispose()


@pytest.fixture()
def app(world):
    application = Flask(__name__)
    application.secret_key = "test"
    application.config["TESTING"] = True
    application.register_blueprint(auth_bp.bp)
    return application


def _client(app, user_id=None, role=None):
    client = app.test_client()
    if user_id is not None:
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["role"] = role
            sess["_csrf_token"] = CSRF
    return client


def _change(client, **body):
    payload = {"current_password": body.pop("current", ""),
               "new_password": body.pop("new", ""),
               "confirm_password": body.pop("confirm", "")}
    payload.update(body)
    return client.post("/api/account/password", json=payload,
                       headers={"X-CSRF-Token": CSRF})


def test_profile_exposes_readonly_login_name(app, world):
    client = _client(app, world["teacher"], "advisor")
    resp = client.get("/api/account")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["username"] == "teacher"
    assert data["display_name"] == "陈老师"
    assert data["role_label"] == "顾问"


def test_change_password_success_and_old_password_rejected(app, world):
    client = _client(app, world["teacher"], "advisor")

    wrong = _change(client, current="nope", new="brand-new", confirm="brand-new")
    assert wrong.status_code == 400
    assert wrong.get_json()["error"] == "当前密码不正确"
    assert _db.verify_user("teacher", "old-pass") is not None

    mismatch = _change(client, current="old-pass", new="brand-new", confirm="other-new")
    assert mismatch.status_code == 400
    assert mismatch.get_json()["error"] == "两次输入的新密码不一致"
    assert _db.verify_user("teacher", "old-pass") is not None

    ok = _change(client, current="old-pass", new="brand-new", confirm="brand-new")
    assert ok.status_code == 200
    assert ok.get_json()["ok"] is True
    assert "brand-new" not in ok.get_data(as_text=True)

    assert _db.verify_user("teacher", "old-pass") is None
    assert _db.verify_user("teacher", "brand-new") is not None
    # 当前会话保持有效
    assert client.get("/api/account").status_code == 200


def test_other_teacher_account_is_untouched(app, world):
    client = _client(app, world["teacher"], "advisor")
    assert _change(client, current="old-pass", new="brand-new", confirm="brand-new").status_code == 200

    assert _db.verify_user("other", "other-pass") is not None
    other = _db.get_user_by_id(world["other"])
    assert other["is_active"] == 1
    assert other["role"] == "advisor"


def test_cannot_change_role_office_or_another_user(app, world):
    client = _client(app, world["teacher"], "advisor")
    resp = client.post("/api/account/password", json={
        "current_password": "old-pass",
        "new_password": "brand-new",
        "confirm_password": "brand-new",
        "user_id": world["other"],
        "role": "admin",
        "office_id": 2,
    }, headers={"X-CSRF-Token": CSRF})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "只能修改本人登录密码"

    teacher = _db.get_user_by_id(world["teacher"])
    assert teacher["role"] == "advisor"
    assert teacher["office_id"] is None
    assert _db.verify_user("teacher", "old-pass") is not None
    assert _db.verify_user("other", "other-pass") is not None
    assert _db.get_user_by_id(world["other"])["role"] == "advisor"


def test_csrf_token_required(app, world):
    client = _client(app, world["teacher"], "advisor")
    body = {"current_password": "old-pass", "new_password": "brand-new",
            "confirm_password": "brand-new"}

    missing = client.post("/api/account/password", json=body)
    assert missing.status_code == 403
    wrong = client.post("/api/account/password", json=body,
                        headers={"X-CSRF-Token": "wrong"})
    assert wrong.status_code == 403
    assert _db.verify_user("teacher", "old-pass") is not None


def test_anonymous_cannot_change_password(app, world):
    client = _client(app)
    assert client.get("/api/account").status_code == 401
    resp = client.post("/api/account/password", json={
        "current_password": "old-pass", "new_password": "x", "confirm_password": "x"})
    assert resp.status_code == 401
    assert _db.verify_user("teacher", "old-pass") is not None


def test_front_desk_has_no_personal_settings(app, world):
    client = _client(app, world["front"], "front")
    assert client.get("/api/account").status_code == 403
    assert _change(client, current="front-pass", new="brand-new",
                   confirm="brand-new").status_code == 403
    assert _db.verify_user("front", "front-pass") is not None


def test_admin_and_viewer_can_change_own_password(app, world):
    for username, key, role, old in (
            ("boss", "admin", "admin", "boss-pass"),
            ("viewer", "viewer", "viewer", "view-pass")):
        client = _client(app, world[key], role)
        resp = _change(client, current=old, new="brand-new", confirm="brand-new")
        assert resp.status_code == 200
        assert _db.verify_user(username, "brand-new") is not None
