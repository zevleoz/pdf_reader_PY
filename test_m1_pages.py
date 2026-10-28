"""P4 页面契约：首页/工作台/打印页、导航可见性与学生 360 入口。"""
from __future__ import annotations

import json
from datetime import datetime

import pytest
from flask import Flask

import app_utils
import m1.store as store
from app_utils import BASE_DIR
from test_m1_api import login_as
from test_m1_store import m1db  # noqa: F401  临时库 + 学生/用户/Y4 数据
from test_copilot_routes import qdb  # noqa: F401  学生 360 用的种子库

FIXTURE = json.loads(
    (BASE_DIR / "fixtures" / "m1_doc_sample.json").read_text(encoding="utf-8"))


@pytest.fixture()
def client(m1db, monkeypatch):  # noqa: F811
    from blueprints import m1 as m1_bp

    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.secret_key = "test-secret"
    app.register_blueprint(m1_bp.bp)
    app_utils.register_admin_context(app)
    app.context_processor(lambda: {"csrf_token": app_utils.get_csrf_token})
    app.add_template_filter(app_utils.dt_short, "dt_short")
    return app.test_client()


@pytest.fixture()
def admin(client, m1db):
    login_as(client, m1db.admin_id, "admin")
    return client


@pytest.fixture()
def alice(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    return client


def _seed_doc(m1db, *, status="review"):
    prep = m1db.prep()
    store.add_version(
        prep["id"], "ai_draft", doc=FIXTURE, kb_version="2026-10-28",
        ai_generated_at=datetime(2026, 10, 28, 14, 5),
    )
    if status != "draft":
        store.set_status(prep["id"], status)
    return store.get_prep(prep["id"])


# ---------------------------------------------------------------------------
# 权限与导航
# ---------------------------------------------------------------------------
def test_home_ok_for_admin_and_advisor_403_for_viewer(client, m1db):
    login_as(client, m1db.admin_id, "admin")
    assert client.get("/m1").status_code == 200

    login_as(client, m1db.alice_id, "advisor", "Alice")
    assert client.get("/m1").status_code == 200

    login_as(client, m1db.viewer_id, "viewer")
    assert client.get("/m1").status_code == 403


def test_nav_item_visible_to_admin_and_advisor_only():
    def hrefs(role):
        return [link["href"] for group in app_utils.nav_for_role(role)
                for link in group["links"]]

    assert "/m1" in hrefs("admin")
    assert "/m1" in hrefs("advisor")
    assert "/m1" not in hrefs("viewer")


def test_home_shell_renders(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    html = client.get("/m1").get_data(as_text=True)
    assert "M1 会前准备" in html
    assert "新建会前准备" in html
    assert 'id="prepRows"' in html
    assert "/m1/assets/m1_home.js" in html


def test_home_passes_student_query_to_picker(alice, m1db):
    """360 页的 ?student=<id> 入口：ID 必须传到前端，才能跳草稿或预选学生。"""
    html = alice.get(f"/m1?student={m1db.student_id}").get_data(as_text=True)
    assert f'data-student-id="{m1db.student_id}"' in html
    assert 'id="m1ModalHost"' in html


# ---------------------------------------------------------------------------
# 工作台
# ---------------------------------------------------------------------------
def test_workspace_renders_shell_for_fixture_doc(alice, m1db):
    prep = _seed_doc(m1db)
    html = alice.get(f"/m1/preps/{prep['id']}").get_data(as_text=True)

    assert "林晓雨 · First Meeting 会前准备" in html
    assert 'id="m1doc"' in html
    assert 'class="stepper"' in html
    assert 'data-status="review"' in html
    assert "M1_CTX" in html

    detail = alice.get(f"/api/m1/preps/{prep['id']}").get_json()
    assert detail["doc"]["priority"][0]["code"] == "R2.2"
    assert len(detail["kb"]["abilities"]) == 18


def test_workspace_without_doc_still_renders(alice, m1db):
    prep = m1db.prep()
    resp = alice.get(f"/m1/preps/{prep['id']}")
    assert resp.status_code == 200
    assert 'id="m1doc"' in resp.get_data(as_text=True)


def test_workspace_hides_other_advisors_prep(alice, m1db):
    other = m1db.prep(m1db.other_student_id, m1db.bob_id)
    assert alice.get(f"/m1/preps/{other['id']}").status_code == 403


# ---------------------------------------------------------------------------
# 打印页
# ---------------------------------------------------------------------------
def test_print_page_has_footer_and_no_markers(alice, m1db):
    prep = _seed_doc(m1db, status="final")
    html = alice.get(f"/m1/preps/{prep['id']}/print").get_data(as_text=True)

    assert "M1 FM会前准备框架 · 林晓雨" in html
    assert "counter(page)" in html
    assert 'class="mk' not in html
    assert "contenteditable" not in html
    assert "已定稿" in html


def test_print_page_for_draft_is_marked(alice, m1db):
    prep = _seed_doc(m1db)
    html = alice.get(f"/m1/preps/{prep['id']}/print").get_data(as_text=True)
    assert "草稿" in html
    assert "draftmark" in html


# ---------------------------------------------------------------------------
# 静态资源
# ---------------------------------------------------------------------------
def test_m1_assets_are_served(admin):
    css = admin.get("/m1/assets/m1.css")
    assert css.status_code == 200
    assert "text/css" in css.content_type
    js = admin.get("/m1/assets/m1_doc.js")
    assert js.status_code == 200
    assert "M1Doc" in js.get_data(as_text=True)


# ---------------------------------------------------------------------------
# 学生 360 入口
# ---------------------------------------------------------------------------
@pytest.fixture()
def s360_client(qdb):  # noqa: F811
    from blueprints import copilot as copilot_bp
    from blueprints import students as students_bp

    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.register_blueprint(students_bp.bp)
    app.register_blueprint(copilot_bp.bp)
    app_utils.register_admin_context(app)
    app.context_processor(lambda: {"csrf_token": app_utils.get_csrf_token})
    app.add_template_filter(app_utils.dt_short, "dt_short")
    return app.test_client()


@pytest.fixture(autouse=True)
def _stub_progress(monkeypatch):
    from blueprints import students as students_bp

    monkeypatch.setattr(
        students_bp, "_student_progress_context",
        lambda _sid: {"stage": "ready", "label": "—", "days": 0, "since_label": "",
                      "suggestion": None, "six_am": None, "show_create_task": True})


def test_student_360_has_m1_button(s360_client, qdb):
    from test_copilot_routes import login_as as login

    login(s360_client, qdb)
    html = s360_client.get("/students/Y4-9201").get_data(as_text=True)
    assert "M1 会前准备" in html
    assert '/m1?student=' in html


def test_student_360_hides_m1_button_for_viewer(s360_client, qdb):
    from test_copilot_routes import login_as as login

    login(s360_client, qdb, role="viewer", advisor_name="",
          display_name="观察员", user_id=qdb.alice_id)
    html = s360_client.get("/students/Y4-9201").get_data(as_text=True)
    assert "M1 会前准备" not in html
