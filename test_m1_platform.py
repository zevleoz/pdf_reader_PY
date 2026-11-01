"""M1 作为独立平台：访问控制、导航、外壳与「部分」契约。"""
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

FIXTURE = json.loads(
    (BASE_DIR / "fixtures" / "m1_doc_sample.json").read_text(encoding="utf-8"))


@pytest.fixture()
def client(m1db, monkeypatch):  # noqa: F811
    from blueprints import m1 as m1_bp
    from blueprints import students as students_bp

    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    # /students 的阶段栏要读 Booking 表；这里只校验外壳，不需要真实阶段。
    monkeypatch.setattr("pipeline.compute_stages", lambda advisor=None: {})
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.secret_key = "test-secret"
    app.register_blueprint(m1_bp.bp)
    app.register_blueprint(students_bp.bp)
    app_utils.register_admin_context(app)
    app.context_processor(lambda: {"csrf_token": app_utils.get_csrf_token})
    app.add_template_filter(app_utils.dt_short, "dt_short")
    return app.test_client()


def _seed_doc(m1db):
    prep = m1db.prep()
    store.add_version(
        prep["id"], "ai_draft", doc=FIXTURE, kb_version="2026-10-28",
        ai_generated_at=datetime(2026, 10, 28, 14, 5),
    )
    store.set_status(prep["id"], "review")
    return store.get_prep(prep["id"])


def _login(client, user_id, role, advisor_name="", **settings):
    login_as(client, user_id, role, advisor_name)
    with client.session_transaction() as sess:
        for key, value in settings.items():
            sess[key] = value


# ---------------------------------------------------------------------------
# 1–2. 首页与 M1 导航
# ---------------------------------------------------------------------------
def test_home_is_m1_not_profiling(client, m1db):
    _login(client, m1db.admin_id, "admin")
    resp = client.get("/m1")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "<h1>M1</h1>" in html
    assert "M1 会前准备" not in html


def test_home_nav_is_m1_and_other_platforms_only(client, m1db):
    _login(client, m1db.admin_id, "admin")
    html = client.get("/m1").get_data(as_text=True)
    assert "学生 Profiling" in html
    assert ">M1<" in html
    assert "报告生成" not in html
    assert "学生档案" not in html


# ---------------------------------------------------------------------------
# 3–4. 访问控制
# ---------------------------------------------------------------------------
def test_viewer_gets_403_on_page_and_api(client, m1db):
    _login(client, m1db.viewer_id, "viewer")
    assert client.get("/m1").status_code == 403
    assert client.get("/api/m1/preps").status_code == 403


def test_advisor_without_m1_access_gets_403_on_page_and_api(client, m1db):
    _login(client, m1db.alice_id, "advisor", "Alice", m1_access=0)
    assert client.get("/m1").status_code == 403
    resp = client.get("/api/m1/preps")
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "当前账号没有 M1 权限"


# ---------------------------------------------------------------------------
# 5. 全部学生范围的顾问可以为其他顾问的学生新建准备
# ---------------------------------------------------------------------------
def test_advisor_with_all_scope_creates_prep_for_other_advisor_student(client, m1db):
    _login(client, m1db.alice_id, "advisor", "Alice", student_scope="all")
    resp = client.post("/api/m1/preps", json={"student_id": m1db.other_student_id})
    assert resp.status_code == 201
    payload = resp.get_json()
    assert payload["created"] is True
    assert payload["prep"]["student_id"] == m1db.other_student_id
    assert client.get(f"/api/m1/preps/{payload['prep']['id']}").status_code == 200


# ---------------------------------------------------------------------------
# 6. 工作台的部分条
# ---------------------------------------------------------------------------
def test_workspace_shows_report_part_link(client, m1db):
    _login(client, m1db.alice_id, "advisor", "Alice")
    prep = _seed_doc(m1db)
    html = client.get(f"/m1/preps/{prep['id']}").get_data(as_text=True)
    assert '<div class="m1-parts"' in html
    assert "会前准备" in html
    assert "会后报告" in html
    assert f'href="/m1/preps/{prep["id"]}/report"' in html
    assert ('<span class="part off" role="tab" aria-selected="false" '
            'aria-disabled="true" title="即将上线">会后报告</span>') not in html


# ---------------------------------------------------------------------------
# 7. E4 只在配置了 E4_URL 时出现在导航
# ---------------------------------------------------------------------------
def test_e4_nav_appears_only_when_configured(client, m1db, monkeypatch):
    _login(client, m1db.admin_id, "admin")

    monkeypatch.setenv("E4_URL", "https://e4.example.com")
    html = client.get("/m1").get_data(as_text=True)
    assert 'href="https://e4.example.com"' in html
    assert 'target="_blank"' in html

    monkeypatch.delenv("E4_URL", raising=False)
    html = client.get("/m1").get_data(as_text=True)
    assert "https://e4.example.com" not in html
    assert 'target="_blank"' not in html


# ---------------------------------------------------------------------------
# 8. 非 M1 页面仍是原来的外壳
# ---------------------------------------------------------------------------
def test_non_m1_page_keeps_normal_brand(client, m1db):
    _login(client, m1db.admin_id, "admin")
    html = client.get("/students").get_data(as_text=True)
    assert "凭远教育" in html
    assert "Y4 · 综合测评" in html
    assert "m1-platform" not in html


# ---------------------------------------------------------------------------
# 9. 打印页文档名不变
# ---------------------------------------------------------------------------
def test_print_keeps_framework_title(client, m1db):
    _login(client, m1db.alice_id, "advisor", "Alice")
    prep = _seed_doc(m1db)
    html = client.get(f"/m1/preps/{prep['id']}/print").get_data(as_text=True)
    assert "M1 FM会前准备框架" in html
