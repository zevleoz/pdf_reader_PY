"""Growth Talk 页面契约测试（Task 9）。

覆盖：
- workspace 页面路由：admin / 名下 advisor 可访问，越权或只读角色不可访问；
- 页面注入学生上下文与已确认报告历史；
- student_360 的 Growth Talk 区块、students 页的 Yuguo 导入入口存在。
"""
from __future__ import annotations

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


def test_workspace_page_renders_with_student_context(client, ui_db):
    login_as(client, "admin")
    resp = client.get(f"/students/{ui_db.student_id}/growth-talk")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "gtWorkspace(" in body
    assert "界面学生" in body
    assert "Growth Talk" in body


def test_workspace_page_lists_confirmed_reports(client, ui_db):
    source = store.create_source(ui_db.student_id, "GROWTH_TALK", "GROWTH_TALK",
                                 "会谈记录", "会议正文")
    run = store.create_run(ui_db.student_id, source["id"])
    store.create_report(ui_db.student_id, run["id"], "{}", "顾问A")

    login_as(client, "admin")
    resp = client.get(f"/students/{ui_db.student_id}/growth-talk")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert '"version": 1' in body or '"version":1' in body
    assert "顾问A" in body
    assert "/api/growth-talk/reports/" in body


def test_workspace_page_advisor_scope(client, ui_db):
    login_as(client, "advisor", advisor_name="Bob")
    assert client.get(
        f"/students/{ui_db.student_id}/growth-talk").status_code == 404

    login_as(client, "advisor", advisor_name="Alice")
    assert client.get(
        f"/students/{ui_db.student_id}/growth-talk").status_code == 200


def test_workspace_page_viewer_forbidden(client, ui_db):
    login_as(client, "viewer")
    assert client.get(
        f"/students/{ui_db.student_id}/growth-talk").status_code == 403


def test_student_360_template_has_growth_talk_section():
    text = open("templates/student_360.html", encoding="utf-8").read()
    assert "Growth Talk" in text
    assert "gt_reports" in text
    assert "/growth-talk" in text
    assert "download.json" in text
    assert "download.pdf" in text


def test_students_template_has_yuguo_import_entry():
    text = open("templates/students.html", encoding="utf-8").read()
    assert "从 Yuguo 导入" in text
    assert "/students/import-yuguo" in text
    assert "rejectedStudents" in text
    assert "alreadyLocal" in text
