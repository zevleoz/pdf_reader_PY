"""外部 /api/v1 Growth Talk 报告端点测试（Task 11）。

覆盖：
- Bearer Key 鉴权：无 token / 错 token → 401；
- 列表端点只返回 CONFIRMED 报告；
- 详情端点返回 payload 原文，DRAFT 视为不存在；
- 不存在或非法 ID → NOT_FOUND。
"""
from __future__ import annotations

import json

import pytest
from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import db as _db
import growth_talk_store as store


@pytest.fixture()
def api_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'gt_api_v1.db'}")

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
        store.AuditLog.__table__,
    ]
    _db.Base.metadata.create_all(engine, tables=tables)
    monkeypatch.setattr(_db, "engine", engine)
    with Session(engine) as sess:
        student = _db.Student(student_code="Y4-9100", name="API 学生",
                              grade="11", school="API 中学", advisor_name="Bob")
        sess.add(student)
        sess.commit()
        student_id = student.id
    yield {"engine": engine, "student_id": student_id}
    engine.dispose()


@pytest.fixture()
def client(api_db, monkeypatch):
    from blueprints import api_v1

    monkeypatch.setattr(api_v1, "Y4_API_KEY", "test-api-key-0123456789abcdef")
    monkeypatch.setattr(api_v1, "_v1_rate_check", lambda *a, **kw: True)
    app = Flask(__name__)
    app.register_blueprint(api_v1.bp)
    return app.test_client()


HEADERS = {"Authorization": "Bearer test-api-key-0123456789abcdef"}


def _new_run(student_id: int) -> int:
    source = store.create_source(student_id, "GROWTH_TALK", "GROWTH_TALK",
                                 "纪要", "正文")
    return store.create_run(student_id, source["id"])["id"]


def _confirmed_report(student_id: int, payload: dict) -> int:
    source = store.create_source(student_id, "GROWTH_TALK", "GROWTH_TALK",
                                 "纪要", "正文")
    run = store.create_run(student_id, source["id"])
    report = store.create_report(student_id, run["id"],
                                 json.dumps(payload, ensure_ascii=False), "顾问A")
    return report["id"]


def test_missing_token_rejected(client, api_db):
    resp = client.get(f"/api/v1/students/{api_db['student_id']}/growth-talk-reports")
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "UNAUTHORIZED"


def test_wrong_token_rejected(client, api_db):
    resp = client.get(f"/api/v1/students/{api_db['student_id']}/growth-talk-reports",
                      headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


def test_list_returns_only_confirmed_reports(client, api_db):
    sid = api_db["student_id"]
    first = _confirmed_report(sid, {"schema": "first-touch.report.v1"})
    draft_run_id = _new_run(sid)
    with Session(api_db["engine"]) as sess:
        sess.add(store.GtReport(student_id=sid, run_id=draft_run_id, version=2,
                                status="DRAFT", payload="{}",
                                confirmed_by="草稿"))
        sess.commit()

    resp = client.get(f"/api/v1/students/{sid}/growth-talk-reports", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert [r["id"] for r in body["reports"]] == [first]
    row = body["reports"][0]
    assert row["version"] == 1
    assert row["status"] == "CONFIRMED"
    assert row["confirmed_by"] == "顾问A"
    assert row["confirmed_at"]


def test_list_unknown_student_returns_empty(client):
    resp = client.get("/api/v1/students/999/growth-talk-reports", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.get_json()["reports"] == []


def test_detail_returns_payload(client, api_db):
    payload = {"schema": "first-touch.report.v1", "student": {"name": "API 学生"}}
    report_id = _confirmed_report(api_db["student_id"], payload)

    resp = client.get(f"/api/v1/growth-talk-reports/{report_id}", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["report"] == payload


def test_detail_draft_is_not_found(client, api_db):
    draft_run_id = _new_run(api_db["student_id"])
    with Session(api_db["engine"]) as sess:
        row = store.GtReport(student_id=api_db["student_id"], run_id=draft_run_id,
                             version=1, status="DRAFT", payload="{}",
                             confirmed_by="")
        sess.add(row)
        sess.commit()
        report_id = row.id

    resp = client.get(f"/api/v1/growth-talk-reports/{report_id}", headers=HEADERS)
    assert resp.status_code == 404
    assert resp.get_json()["code"] == "NOT_FOUND"


def test_detail_missing_report_is_not_found(client):
    resp = client.get("/api/v1/growth-talk-reports/999", headers=HEADERS)
    assert resp.status_code == 404
