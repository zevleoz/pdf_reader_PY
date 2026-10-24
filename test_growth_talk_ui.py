"""Growth Talk 旧入口与模板清理测试。

覆盖：
- ``GET /students/<sid>/growth-talk`` 302 跳转到 First Touch；
- Advisor 仍只能访问自己名下的学生，只读角色被拒绝；
- student_360 保留报告下载入口，students 页不再有 Yuguo 导入入口；
- 集成蓝图下线后 ``POST /api/integrations/crm/deliveries`` 返回 404。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app_utils
import db as _db
import growth_talk_store as store


class UiDB:
    def __init__(self, engine):
        self.engine = engine
        self.student_id = None


@pytest.fixture()
def ui_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'gt_ui.db'}")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables = [
        _db.Student.__table__,
        store.GtSource.__table__,
        store.GtRun.__table__,
        store.GtUnderstanding.__table__,
        store.GtInterest.__table__,
        store.GtQuadrant.__table__,
        store.GtSuggestion.__table__,
        store.GtReport.__table__,
        store.ExternalIdentity.__table__,
        store.AuditLog.__table__,
        store.CrmDeliveryReceipt.__table__,
        store.CrmAppointment.__table__,
    ]
    _db.Base.metadata.create_all(engine, tables=tables)
    monkeypatch.setattr(_db, "engine", engine)
    helper = UiDB(engine)
    with Session(engine) as sess:
        row = _db.Student(student_code="Y4-9010", name="界面学生",
                          grade="10", school="界面中学", advisor_name="Alice")
        sess.add(row)
        sess.commit()
        helper.student_id = row.id
    yield helper
    engine.dispose()


@pytest.fixture()
def client(ui_db, monkeypatch):
    from blueprints import growth_talk as gt_routes

    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app_utils.register_admin_context(app)
    app.context_processor(lambda: {"csrf_token": lambda: "test-token"})
    app.register_blueprint(gt_routes.bp)
    return app.test_client()


def login_as(client, role="admin", advisor_name=None):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["role"] = role
        sess["display_name"] = "顾问A"
        if advisor_name is not None:
            sess["advisor_name"] = advisor_name


def test_growth_talk_page_redirects_to_first_touch(client, ui_db):
    login_as(client, "admin")
    resp = client.get(f"/students/{ui_db.student_id}/growth-talk")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(
        f"/first-touch/students/{ui_db.student_id}")


def test_growth_talk_page_advisor_scope(client, ui_db):
    login_as(client, "advisor", advisor_name="Bob")
    assert client.get(
        f"/students/{ui_db.student_id}/growth-talk").status_code == 404

    login_as(client, "advisor", advisor_name="Alice")
    assert client.get(
        f"/students/{ui_db.student_id}/growth-talk").status_code == 302


def test_growth_talk_page_viewer_forbidden(client, ui_db):
    login_as(client, "viewer")
    assert client.get(
        f"/students/{ui_db.student_id}/growth-talk").status_code == 403


def test_growth_talk_page_missing_student_404(client):
    login_as(client, "admin")
    assert client.get("/students/9999/growth-talk").status_code == 404


def test_student_360_template_has_first_touch_section():
    text = open("templates/student_360.html", encoding="utf-8").read()
    assert "First Touch" in text
    assert "first_touch" in text
    assert "Growth Talk" not in text
    assert "download.json" in text
    assert "download.pdf" in text


def test_students_template_has_no_yuguo_import_entry():
    text = open("templates/students.html", encoding="utf-8").read()
    assert "从 Yuguo 导入" not in text
    assert "/students/import-yuguo" not in text
    assert "yuguoImport" not in text


def test_integrations_route_removed(tmp_path):
    """全量 app 中不再注册集成蓝图：CRM 投递端点应 404。"""
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{tmp_path / 'app.db'}"
    env.pop("SECRET_KEY", None)
    probe = (
        "import json\n"
        "import app as app_module\n"
        "client = app_module.app.test_client()\n"
        "resp = client.post('/api/integrations/crm/deliveries', json={})\n"
        "print(json.dumps({'status': resp.status_code}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=".",
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["status"] == 404
