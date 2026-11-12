"""M1P-P2 页面契约：新外壳、ark.css 字体资产、学生页与工作台分址。"""
from __future__ import annotations

import pytest
from flask import Flask

import app_utils
from app_utils import BASE_DIR
from test_m1_api import login_as
from test_m1_store import m1db  # noqa: F401  临时库 + 学生/用户/Y4 数据


@pytest.fixture()
def client(m1db, monkeypatch):  # noqa: F811
    from blueprints import m1 as m1_bp
    from blueprints import m1_report

    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.secret_key = "test-secret"
    app.register_blueprint(m1_bp.bp)
    app.register_blueprint(m1_report.bp)
    app_utils.register_admin_context(app)
    app.context_processor(lambda: {"csrf_token": app_utils.get_csrf_token})
    app.add_template_filter(app_utils.dt_short, "dt_short")
    return app.test_client()


def test_m1_home_uses_new_shell_and_stylesheet(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    resp = client.get("/m1")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert 'data-platform="m1"' in html
    assert 'class="nav"' in html
    assert 'href="/m1" aria-current="page"' in html
    assert "/m1/assets/ark.css" in html
    assert 'id="addStudent"' in html
    assert 'id="addDlg"' in html

    assert "admin_v2.css" not in html
    assert "unpkg.com" not in html
    assert "fonts.googleapis" not in html
    assert "新建学生档案" not in html


def test_ark_css_and_fonts_are_served(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    resp = client.get("/m1/assets/ark.css")
    assert resp.status_code == 200
    css = resp.get_data(as_text=True)

    assert "@font-face" in css
    assert "/m1/assets/fonts/archivo-700.woff2" in css
    assert ".lr" in css
    assert "base64" not in css
    assert "fonts.googleapis" not in css

    for weight in (400, 600, 700, 800):
        font = client.get("/m1/assets/fonts/archivo-%d.woff2" % weight)
        assert font.status_code == 200


def test_student_page_and_prep_workspace_have_separate_urls(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    prep = m1db.prep()

    student = client.get("/m1/preps/%d" % prep["id"])
    assert student.status_code == 200
    html = student.get_data(as_text=True)
    assert 'id="m1Student"' in html
    assert 'data-prep-id="%d"' % prep["id"] in html

    workspace = client.get("/m1/preps/%d/prep" % prep["id"])
    assert workspace.status_code == 200
    assert 'id="m1Workspace"' in workspace.get_data(as_text=True)

    login_as(client, m1db.viewer_id, "viewer")
    for tail in ("", "/prep", "/report"):
        assert client.get("/m1/preps/%d%s" % (prep["id"], tail)).status_code == 403


def test_page_scripts_carry_the_screen_contract(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    home = client.get("/m1/assets/m1_home.js").get_data(as_text=True)
    student = client.get("/m1/assets/m1_student.js").get_data(as_text=True)

    for text in ("未开始", "我添加的", "已开过的会议", "/api/m1/students",
                 "m1.list.who"):
        assert text in home
    for text in ("/overview", "开始会后报告"):
        assert text in student
