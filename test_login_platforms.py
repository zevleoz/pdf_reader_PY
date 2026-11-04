# -*- coding: utf-8 -*-
"""T1：新登录页、选择平台页、首页分流与账号页两处修正。

用真实 Flask 入口（``app.create_app``）与独立临时 SQLite，不触碰 data/y4_students.db。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event

import app_utils
import db as _db
import questionnaire_store as qs

REPO_ROOT = Path(__file__).resolve().parent
CREST = "static/m1/login_crest_white.png"
PASSWORD = "pw-123456"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/login_platforms.db")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    _db.Base.metadata.create_all(engine)
    qs.ensure_indexes(bind=engine)
    monkeypatch.setattr(_db, "engine", engine)
    monkeypatch.setattr(qs, "engine", engine)
    monkeypatch.delenv("E4_URL", raising=False)
    app_utils._SESSION_USER_CACHE.clear()
    app_utils._RATE_BUCKETS.clear()

    w = SimpleNamespace(
        admin_id=_db.create_user("t-admin", PASSWORD, "admin"),
        advisor_id=_db.create_user("t-adv", PASSWORD, "advisor", advisor_name="Mine"),
        no_m1_id=_db.create_user("t-adv-nom1", PASSWORD, "advisor",
                                 advisor_name="Mine", m1_access=0),
        viewer_id=_db.create_user("t-view", PASSWORD, "viewer"),
    )
    yield w
    app_utils._SESSION_USER_CACHE.clear()
    app_utils._RATE_BUCKETS.clear()
    engine.dispose()


@pytest.fixture()
def app(world):
    import app as app_module
    application = app_module.create_app()
    application.config["TESTING"] = True
    application.secret_key = "test"
    return application


def _client(app, user_id, role, advisor_name=""):
    """旧 session 形态：只有 user_id / role / advisor_name，其余由账号同步。"""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role
        sess["advisor_name"] = advisor_name
    return client


# ── 1. 首页分流 ────────────────────────────────────────────────
def test_root_sends_logged_out_to_login(app):
    resp = app.test_client().get("/")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_root_sends_logged_in_to_platforms(app, world):
    resp = _client(app, world.admin_id, "admin").get("/")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/platforms")


# ── 2. 登录页 ──────────────────────────────────────────────────
def test_login_page_content(app):
    resp = app.test_client().get("/login")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "账号由管理员开通" in html
    assert "/student/login" in html
    assert "login_crest_white.png" in html
    assert "学生画像中心" not in html
    # 旧的入口链接已移除
    assert "返回主页" not in html and "预约测评" not in html


# ── 3. 选择平台需要登录 ────────────────────────────────────────
def test_platforms_requires_login(app):
    resp = app.test_client().get("/platforms")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


# ── 4. 管理员看到 Profiling 与 M1 ──────────────────────────────
def test_admin_sees_profiling_and_m1(app, world):
    resp = _client(app, world.admin_id, "admin").get("/platforms")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "学生 Profiling" in html
    assert '<span class="pf-title">M1</span>' in html
    assert "First Meeting：会前准备" in html
    assert "M1 会前准备" not in html
    assert "选择平台" in html


# ── 5. 只有一张卡片时直接落下 ──────────────────────────────────
def test_viewer_goes_straight_to_students(app, world):
    resp = _client(app, world.viewer_id, "viewer").get("/platforms")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/app/students")


def test_advisor_without_m1_goes_straight_to_workspace(app, world):
    resp = _client(app, world.no_m1_id, "advisor", "Mine").get("/platforms")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/workspace")


# ── 6. E4 只随环境变量出现 ─────────────────────────────────────
def test_e4_card_only_when_configured(app, world, monkeypatch):
    client = _client(app, world.admin_id, "admin")
    html = client.get("/platforms").get_data(as_text=True)
    assert "独立平台，有自己的账号和数据库" not in html
    assert 'target="_blank"' not in html

    monkeypatch.setenv("E4_URL", "https://e4.example.test")
    html = client.get("/platforms").get_data(as_text=True)
    assert "独立平台，有自己的账号和数据库" in html
    assert 'href="https://e4.example.test"' in html
    assert 'target="_blank"' in html
    assert 'rel="noopener"' in html


# ── 7. 登录 API 行为不变 ───────────────────────────────────────
def test_login_api_wrong_password_and_rate_limit(app, world):
    client = app.test_client()
    resp = client.post("/api/admin/login",
                       json={"username": "t-admin", "password": "bad"})
    assert resp.status_code == 401
    assert resp.get_json() == {"ok": False, "error": "用户名或密码错误"}

    # 默认限流 5 次：再失败 4 次仍得到原来的 401
    for _ in range(4):
        assert client.post("/api/admin/login",
                           json={"username": "t-admin",
                                 "password": "bad"}).status_code == 401
    # 第 6 次：窗口内已失败 5 次，触发限流
    resp = client.post("/api/admin/login", json={"username": "t-admin", "password": "bad"})
    assert resp.status_code == 429
    assert resp.get_json()["error"] == "尝试过多，请稍后再试"

    app_utils._RATE_BUCKETS.clear()
    resp = client.post("/api/admin/login",
                       json={"username": "t-admin", "password": PASSWORD})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


# ── 8. 未改动的公开路由 ───────────────────────────────────────
def test_public_routes_unchanged(app):
    client = app.test_client()
    assert client.get("/student/login").status_code == 200
    assert client.get("/q/no-such-token").status_code == 404
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "healthy"


# ── 9. 盾徽不被忽略 ───────────────────────────────────────────
def test_crest_file_exists_and_is_not_gitignored():
    assert (REPO_ROOT / CREST).exists()
    result = subprocess.run(["git", "check-ignore", CREST],
                            cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 1, result.stdout
    assert result.stdout.strip() == ""


# ── 10. 侧栏「所有平台」 ──────────────────────────────────────
def test_sidebar_all_platforms_for_admin_only(app, world, monkeypatch):
    monkeypatch.setattr("pipeline.compute_stages", lambda advisor=None: {})

    admin_students = _client(app, world.admin_id, "admin")
    assert "所有平台" in admin_students.get("/students").get_data(as_text=True)
    admin_m1 = _client(app, world.admin_id, "admin")
    assert "所有平台" in admin_m1.get("/m1").get_data(as_text=True)

    viewer = _client(app, world.viewer_id, "viewer")
    assert "所有平台" not in viewer.get("/students").get_data(as_text=True)
    assert viewer.get("/m1").status_code == 403
