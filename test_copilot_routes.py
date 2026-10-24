"""Copilot 2.0 路由测试（审核隔离、修订守卫、聊天入库、上下文截断、PDF 双检）。"""
from __future__ import annotations

import json

import pytest
from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app_utils
import db as _db
import growth_talk_store as store
from blueprints import copilot as copilot_api
from growth_talk import analysis, copilot, copilot_report, jobs


class RouteDB:
    def __init__(self, engine):
        self.engine = engine
        self.student_id = None
        self.other_student_id = None
        self.alice_id = None
        self.bob_id = None

    def seed(self):
        with Session(self.engine) as sess:
            alice = _db.User(username="alice", password_hash="x",
                             role="advisor", advisor_name="Alice")
            bob = _db.User(username="bob", password_hash="x",
                           role="advisor", advisor_name="Bob")
            student = _db.Student(student_code="Y4-9201", name="林同学",
                                  grade="10", advisor_name="Alice")
            other = _db.Student(student_code="Y4-9202", name="陈同学",
                                grade="11", advisor_name="Bob")
            sess.add_all([alice, bob, student, other])
            sess.commit()
            self.alice_id, self.bob_id = alice.id, bob.id
            self.student_id, self.other_student_id = student.id, other.id

    def session(self, *, phase=0):
        session, _ = store.create_session(
            self.student_id, self.alice_id)
        store.update_session_fields(session["id"], phase=phase)
        return store.get_session(session["id"])

    def add_y4(self, student_id=None, *, report_date=None, complete=True):
        """写入一份 Y4 报告；默认是该学生完整数据的最近报告。"""
        from datetime import date as _date
        points = [{"code": "072", "value": "SAE", "type": "string"}]
        if complete:
            points += [
                {"code": code, "value": value, "type": "number"}
                for code, value in (("073", "2"), ("074", "5"),
                                    ("075", "2"), ("076", "4"),
                                    ("077", "1"), ("078", "3"))
            ]
        payload = json.dumps({"schema_124": points}, ensure_ascii=False)
        with Session(self.engine) as sess:
            report = _db.Report(
                student_id=student_id or self.student_id,
                report_date=report_date or _date(2026, 10, 1),
                pdf_path="report.pdf", data_json=payload)
            sess.add(report)
            sess.commit()
            return report.id


@pytest.fixture()
def qdb(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'copilot_routes.db'}")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    tables = [
        _db.Student.__table__, _db.User.__table__, _db.Report.__table__,
        store.GtSource.__table__, store.GtRun.__table__,
        store.GtUnderstanding.__table__, store.GtInterest.__table__,
        store.GtQuadrant.__table__, store.GtSuggestion.__table__,
        store.GtReport.__table__,
        store.ExternalIdentity.__table__, store.AuditLog.__table__,
        store.CopilotSession.__table__, store.CopilotPhaseEvent.__table__,
        store.CopilotCareerCalibration.__table__, store.CopilotInterestNote.__table__,
        store.CopilotTranscriptSupplement.__table__, store.CopilotChatMessage.__table__,
    ]
    _db.Base.metadata.create_all(engine, tables=tables)
    monkeypatch.setattr(_db, "engine", engine)
    monkeypatch.setattr(jobs, "COPILOT_JOB_DIR", str(tmp_path / "_copilot_jobs"))
    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    helper = RouteDB(engine)
    helper.seed()
    yield helper
    engine.dispose()


@pytest.fixture()
def client(qdb):
    app = Flask(__name__, template_folder=str(app_utils.TEMPLATE_DIR))
    app.config["SECRET_KEY"] = "test-secret"
    app.register_blueprint(copilot_api.bp)
    app.config["TESTING"] = True
    app_utils.register_admin_context(app)
    app.context_processor(lambda: {"csrf_token": app_utils.get_csrf_token})
    app.add_template_filter(app_utils.dt_short, "dt_short")
    return app.test_client()


def login_as(client, qdb, *, role="advisor", advisor_name="Alice",
             display_name="Alice", user_id=None):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id if user_id is not None else (
            qdb.bob_id if advisor_name == "Bob" else qdb.alice_id)
        sess["role"] = role
        sess["advisor_name"] = advisor_name
        sess["display_name"] = display_name


def _inline_jobs(monkeypatch):
    def fake_launch(kind, payload):
        job_id, _args = jobs.new_copilot_job(kind, payload)
        jobs.run_copilot_job(job_id, kind, payload)
        return job_id

    monkeypatch.setattr(jobs, "launch_copilot_job", fake_launch)


def _fake_quadrant(run_id: int) -> None:
    full = store.get_run_full(run_id)
    confirmed = [
        item for item in full["interests"]
        if item["status"] == "CONFIRMED"
        and item["preference_score"] is not None
        and item["competence_score"] is not None
        and not analysis.is_excluded_interest_topic(
            item["label"], item.get("subtopic"))
    ]
    points = [{
        "interestId": item["id"],
        "preferenceScore": item["preference_score"],
        "competenceScore": item["competence_score"],
        "quadrant": analysis.quadrant_zone(
            item["preference_score"], item["competence_score"]),
    } for item in confirmed]
    store.save_quadrant(
        run_id, json.dumps(points, ensure_ascii=False), "兴趣分型说明。", "test")


def _ready_session(qdb):
    """已准备到报告阶段的会谈：会议稿 + 兴趣 + 补充材料。"""
    session = qdb.session(phase=6)
    source = store.create_source(
        qdb.student_id, "GROWTH_TALK", "GROWTH_TALK", "会谈纪要",
        "学生每周训练篮球，非常喜欢投篮，也喜欢看比赛录像。",
        purpose="MEETING", file_name="meeting.txt")
    store.update_session_fields(
        session["id"], meeting_source_id=source["id"],
        script={"nextSummary": "本次会谈围绕篮球训练与比赛观察展开，"
                              "后续会继续设计、观察和验证这些线索。"})
    supplement = store.create_supplement(session["id"], source["id"])
    store.replace_session_interests(session["id"], [
        {
            "id": "i1", "label": "篮球", "topicType": "interest",
            "preferenceScore": 3, "competenceScore": 2,
            "note": "每周训练", "evidence": "每周训练篮球",
        },
        {
            "id": "i2", "label": "足球", "topicType": "interest",
            "preferenceScore": 2, "competenceScore": 1,
            "note": "周末踢球", "evidence": "周末和朋友踢球",
        },
        {
            "id": "i3", "label": "阅读", "topicType": "interest",
            "preferenceScore": 2, "competenceScore": 3,
            "note": "爱看传记", "evidence": "常读人物传记",
        },
    ])
    store.save_supplement_analysis(supplement["id"], {
        "analysisVersion": "v1", "newInterests": [],
    }, "PENDING_REVIEW")
    return store.get_session(session["id"])


def test_create_session_idempotent_200(client, qdb):
    login_as(client, qdb)
    qdb.add_y4()
    payload = {"meetingAt": "2026-10-20T10:00:00"}

    first = client.post(
        f"/api/v2/students/{qdb.student_id}/copilot/sessions", json=payload)
    second = client.post(
        f"/api/v2/students/{qdb.student_id}/copilot/sessions", json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["existing"] is True
    assert (first.get_json()["session"]["id"]
            == second.get_json()["session"]["id"])


def test_phase_patch_revision_conflict_409(client, qdb):
    login_as(client, qdb)
    session = qdb.session()

    response = client.patch(
        f"/api/v2/copilot/sessions/{session['id']}/phase",
        json={"phase": 2, "revision": session["revision"] + 5})

    assert response.status_code == 409
    assert response.get_json()["error"] == "会谈已更新，请保留草稿并刷新确认"


def test_other_advisor_gets_404(client, qdb):
    login_as(client, qdb)
    session = qdb.session()
    login_as(client, qdb, advisor_name="Bob", display_name="Bob")

    response = client.get(f"/api/v2/copilot/sessions/{session['id']}")

    assert response.status_code == 404
    assert response.get_json()["error"] == "会谈不存在"


def test_assistant_question_validation(client, qdb, monkeypatch):
    _inline_jobs(monkeypatch)
    login_as(client, qdb)

    empty = client.post(
        f"/api/students/{qdb.student_id}/copilot/assistant",
        json={"question": "   "})
    too_long = client.post(
        f"/api/students/{qdb.student_id}/copilot/assistant",
        json={"question": "问" * 1001})

    for response in (empty, too_long):
        assert response.status_code == 400
        assert response.get_json()["error"] == "问题不能为空且不能超过 1000 字"


def test_assistant_history_limit(client, qdb, monkeypatch):
    _inline_jobs(monkeypatch)
    login_as(client, qdb)

    response = client.post(
        f"/api/students/{qdb.student_id}/copilot/assistant",
        json={
            "question": "下一步怎么安排？",
            "history": [{"question": "问", "answer": "答"}] * 7,
        })

    assert response.status_code == 400
    assert response.get_json()["error"] == "聊天上下文格式无效"


def test_chat_persisted(client, qdb, monkeypatch):
    _inline_jobs(monkeypatch)
    monkeypatch.setattr(copilot, "call_model",
                        lambda _prompt: {"answer": "先确认兴趣。", "evidence": []})
    login_as(client, qdb)

    response = client.post(
        f"/api/students/{qdb.student_id}/copilot/assistant",
        json={"question": "这次会谈如何收尾？"})

    assert response.status_code == 200
    body = response.get_json()
    chat = client.get(f"/api/copilot/chats/{body['chatId']}")

    assert chat.status_code == 200
    turns = chat.get_json()["chat"]["turns"]
    assert len(turns) == 1
    assert turns[0]["question"] == "这次会谈如何收尾？"
    assert turns[0]["answer"] == "先确认兴趣。"
    assert turns[0]["status"] == "COMPLETE"


def test_assistant_context_truncated(client, qdb, monkeypatch):
    _inline_jobs(monkeypatch)
    captured = {}

    def fake_model(prompt):
        captured["prompt"] = prompt
        return {"answer": "已读取资料。", "evidence": []}

    monkeypatch.setattr(copilot, "call_model", fake_model)
    store.create_source(
        qdb.student_id, "GROWTH_TALK", "GROWTH_TALK", "超长纪要",
        "A" * 40000, purpose="MEETING")
    login_as(client, qdb)

    response = client.post(
        f"/api/students/{qdb.student_id}/copilot/assistant",
        json={"question": "资料里有哪些线索？"})

    assert response.status_code == 200
    assert "A" * 30000 in captured["prompt"]
    assert "A" * 30001 not in captured["prompt"]


def test_report_pdf_double_fence(client, qdb, monkeypatch):
    _inline_jobs(monkeypatch)
    monkeypatch.setattr(copilot_report, "_run_quadrant", _fake_quadrant)
    login_as(client, qdb)
    session = _ready_session(qdb)

    prepared = client.post(
        f"/api/v2/copilot/sessions/{session['id']}/report-prepare",
        json={"revision": session["revision"]})

    assert prepared.status_code == 200
    current = store.get_session(session["id"])
    response = client.get(
        f"/api/v2/copilot/sessions/{session['id']}/report-pdf",
        query_string={"revision": current["revision"],
                      "fingerprint": "stale-fingerprint"})

    assert response.status_code == 409
    assert response.get_json()["error"] == "报告内容已变化，请重新预览再下载"


def test_workspace_page_renders(client, qdb):
    login_as(client, qdb)

    response = client.get(f"/first-touch/students/{qdb.student_id}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "ftWorkspace" in body
    assert "会议准备" in body
