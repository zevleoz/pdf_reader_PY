"""V3a 验收：三步模型、从完整 Y4 开始、快照与谈话要点作业。"""
from __future__ import annotations

import json

import pytest
from flask import session as flask_session
from sqlalchemy import event
from sqlalchemy.orm import Session

import db as _db
import growth_talk_store as store
from blueprints import copilot as copilot_api
from growth_talk import copilot, jobs, y4_snapshot

from test_copilot_routes import (  # noqa: F401
    _inline_jobs, client, login_as, qdb,
)

NEEDS_Y4_ERROR = "该学生还没有完整的 Y4 报告，请先生成 Y4 报告"


def _schema_124() -> list[dict]:
    """带真实编码的完整 Y4 数据（值均为字符串，含排序题）。"""
    items = [
        {"code": "072", "label": "职业兴趣代码", "value": "SAE", "type": "string"},
    ]
    items += [
        {"code": code, "value": value, "type": "number"}
        for code, value in (
            ("073", "2"), ("074", "5"), ("075", "2"),
            ("076", "4"), ("077", "1"), ("078", "3"),
            ("079", "6"), ("080", "3"), ("081", "5"),
            ("082", "2"), ("083", "4"), ("084", "5"),
            ("085", "7"), ("086", "1"),
            ("095", "5"), ("096", "7"), ("097", "2"),
            ("098", "6"), ("099", "4"), ("100", "5"),
            ("101", "3"), ("102", "1"), ("103", "2"),
            ("104", "2"), ("105", "3"), ("106", "4"),
            ("107", "2"), ("108", "1"), ("109", "3"),
        )
    ]
    items += [
        {"code": f"{code:03d}", "value": f"排序{code}", "type": "string"}
        for code in list(range(87, 95)) + list(range(110, 125))
    ]
    return items


def _partial_schema() -> list[dict]:
    """只有三个数值项的部分测试数据。"""
    return [
        {"code": "072", "value": "IR", "type": "string"},
        {"code": "073", "value": "3", "type": "number"},
        {"code": "074", "value": "4", "type": "number"},
        {"code": "075", "value": "2", "type": "number"},
    ]


def _seed_report(qdb, student_id=None, *, schema=None, day=1) -> int:
    from datetime import date
    payload = json.dumps(
        {"student": {"name": "林同学"}, "schema_124": schema or _schema_124()},
        ensure_ascii=False)
    with Session(qdb.engine) as sess:
        report = _db.Report(
            student_id=student_id or qdb.student_id,
            report_date=date(2026, 10, day),
            pdf_path="report.pdf", data_json=payload)
        sess.add(report)
        sess.commit()
        return report.id


def _create_session(client, student_id: int):
    return client.post(
        f"/api/v2/students/{student_id}/copilot/sessions", json={})


# ---------------------------------------------------------------------------
# 快照
# ---------------------------------------------------------------------------
def test_snapshot_builder_from_real_schema(qdb):
    report_id = _seed_report(qdb)
    report = y4_snapshot.latest_complete_y4(qdb.student_id)

    assert report is not None and report.id == report_id
    snapshot = y4_snapshot.build_snapshot(report)

    assert snapshot["reportId"] == report_id
    assert snapshot["reportDate"] == "2026-10-01"
    assert snapshot["hollandCode"] == "SAE"
    assert [item["key"] for item in snapshot["riasec"]] == list("RIASEC")
    assert [item["label"] for item in snapshot["riasec"]] == [
        "现实型", "研究型", "艺术型", "社会型", "事业型", "常规型"]
    assert [item["score"] for item in snapshot["riasec"]] == [
        2.0, 5.0, 2.0, 4.0, 1.0, 3.0]
    assert snapshot["topAbilities"] == [
        {"label": "内省能力", "score": 7.0},
        {"label": "语言能力", "score": 6.0},
        {"label": "音乐能力", "score": 5.0},
    ]
    assert snapshot["weakestAbility"] == {"label": "自然能力", "score": 1.0}
    assert snapshot["topValues"] == [
        {"label": "独立自主", "score": 7.0},
        {"label": "智力激发", "score": 6.0},
        {"label": "创造发明", "score": 5.0},
    ]
    assert snapshot["topicSuggestions"] == [
        "志愿服务", "辩论", "心理话题", "绘画", "音乐", "写作"]


def test_snapshot_summary_text_uses_snapshot(qdb):
    _seed_report(qdb)
    report = y4_snapshot.latest_complete_y4(qdb.student_id)

    summary = y4_snapshot.snapshot_summary_text(
        y4_snapshot.build_snapshot(report))

    assert summary["careerInterests"].startswith("职业兴趣代码 SAE")
    assert "内省能力" in summary["abilityTendencies"]
    assert "独立自主" in summary["valuePreferences"]


def test_partial_report_is_skipped(qdb):
    complete_id = _seed_report(qdb, day=1)
    _seed_report(qdb, schema=_partial_schema(), day=2)

    report = y4_snapshot.latest_complete_y4(qdb.student_id)

    assert report is not None and report.id == complete_id


def test_only_partial_report_means_no_y4(qdb):
    _seed_report(qdb, qdb.other_student_id, schema=_partial_schema())

    assert y4_snapshot.latest_complete_y4(qdb.other_student_id) is None


# ---------------------------------------------------------------------------
# 从完整 Y4 开始会谈
# ---------------------------------------------------------------------------
def test_create_session_without_complete_y4_is_409(client, qdb):
    login_as(client, qdb)

    response = _create_session(client, qdb.student_id)

    assert response.status_code == 409
    body = response.get_json()
    assert body["code"] == "needs_y4"
    assert body["error"] == NEEDS_Y4_ERROR
    assert store.list_sessions(qdb.student_id) == []


def test_create_session_prefills_y4_snapshot(client, qdb):
    login_as(client, qdb)
    report_id = _seed_report(qdb)

    response = _create_session(client, qdb.student_id)

    assert response.status_code == 201
    body = response.get_json()
    session = body["session"]
    assert session["y4_report_id"] == report_id
    assert session["phase"] == 0
    assert session["meeting_at"].endswith("Z")
    assert body["y4Snapshot"]["reportId"] == report_id

    fetched = client.get(
        f"/api/v2/copilot/sessions/{session['id']}").get_json()
    assert fetched["y4Snapshot"]["hollandCode"] == "SAE"
    assert fetched["session"]["phase"] == 0


def test_session_get_rebuilds_missing_snapshot(client, qdb):
    login_as(client, qdb)
    report_id = _seed_report(qdb)
    session = qdb.session()

    fetched = client.get(
        f"/api/v2/copilot/sessions/{session['id']}").get_json()

    assert fetched["y4Snapshot"]["reportId"] == report_id
    assert store.get_session(session["id"])["script"]["y4Snapshot"]["reportId"] == report_id
    assert store.get_session(session["id"])["revision"] == session["revision"]


# ---------------------------------------------------------------------------
# 三步模型
# ---------------------------------------------------------------------------
def test_legacy_phase_five_reads_as_step_two(client, qdb):
    login_as(client, qdb)
    session = qdb.session(phase=5)

    body = client.get(f"/api/v2/copilot/sessions/{session['id']}").get_json()

    assert body["session"]["phase"] == 2


def test_removed_platform_routes(client, qdb):
    login_as(client, qdb)

    manual = client.post("/api/first-touch/students", json={"name": "王同学"})
    imported = client.post("/api/first-touch/import-y4",
                           json={"studentIds": [qdb.student_id]})

    assert manual.status_code in (404, 405)
    assert imported.status_code in (404, 405)


def test_removed_calibration_routes(client, qdb):
    login_as(client, qdb)
    session = qdb.session()

    calibrate = client.post(
        f"/api/v2/copilot/sessions/{session['id']}/y4-calibrate", json={})
    career = client.patch(
        f"/api/v2/copilot/sessions/{session['id']}/career-calibration",
        json={"careerInterests": "x"})

    assert calibrate.status_code in (404, 405)
    assert career.status_code in (404, 405)


def test_chat_pages_redirect(client, qdb):
    login_as(client, qdb)
    qdb.session()

    picker = client.get("/first-touch/copilot")
    deep = client.get(f"/first-touch/copilot/{qdb.student_id}")

    assert picker.status_code == 302
    assert picker.headers["Location"] == "/first-touch"
    assert deep.status_code == 302
    assert deep.headers["Location"] == f"/first-touch/students/{qdb.student_id}"


# ---------------------------------------------------------------------------
# 谈话要点作业
# ---------------------------------------------------------------------------
def _started_session(client, qdb) -> dict:
    _seed_report(qdb)
    body = _create_session(client, qdb.student_id).get_json()
    return body["session"]


def test_talking_points_job_persists_and_bumps_once(
        client, qdb, monkeypatch):
    _inline_jobs(monkeypatch)
    login_as(client, qdb)
    session = _started_session(client, qdb)
    points = ["你最近一次专注做一件事是什么时候？",
              "哪类问题会让你想继续查下去？",
              "在团队里你通常更愿意做什么？"]
    monkeypatch.setattr(copilot, "call_model", lambda _prompt: {"points": points})

    response = client.post(
        f"/api/v2/copilot/sessions/{session['id']}/talking-points",
        json={"revision": session["revision"]})

    assert response.status_code == 200
    job = client.get(
        f"/api/v2/copilot/jobs/{response.get_json()['jobId']}").get_json()
    assert job["status"] == "done"
    assert job["result"]["points"] == points

    current = store.get_session(session["id"])
    assert current["script"]["talkingPoints"] == points
    assert current["revision"] == session["revision"] + 1


def test_talking_points_rejects_short_output(client, qdb, monkeypatch):
    login_as(client, qdb)
    session = _started_session(client, qdb)
    monkeypatch.setattr(copilot, "call_model",
                        lambda _prompt: {"points": ["只有一个问题"]})

    def fake_launch(kind, payload):
        job_id, _args = jobs.new_copilot_job(kind, payload)
        try:
            jobs.run_copilot_job(job_id, kind, payload)
        except Exception:
            pass
        return job_id

    monkeypatch.setattr(jobs, "launch_copilot_job", fake_launch)

    response = client.post(
        f"/api/v2/copilot/sessions/{session['id']}/talking-points",
        json={"revision": session["revision"]})

    assert response.status_code == 200
    job = client.get(
        f"/api/v2/copilot/jobs/{response.get_json()['jobId']}").get_json()
    assert job["status"] == "error"
    assert store.get_session(session["id"])["script"]["talkingPoints"] == []


def test_stale_talking_points_writes_nothing(client, qdb, monkeypatch):
    login_as(client, qdb)
    session = _started_session(client, qdb)
    monkeypatch.setattr(copilot, "call_model",
                        lambda _prompt: {"points": ["一", "二", "三"]})

    def fake_launch(kind, payload):
        job_id, _args = jobs.new_copilot_job(kind, payload)
        store.bump_session_revision(
            int(payload["session_id"]), int(payload["revision"]),
            qdb.alice_id, "test_bump")
        try:
            jobs.run_copilot_job(job_id, kind, payload)
        except Exception:
            pass
        return job_id

    monkeypatch.setattr(jobs, "launch_copilot_job", fake_launch)

    response = client.post(
        f"/api/v2/copilot/sessions/{session['id']}/talking-points",
        json={"revision": session["revision"]})

    assert response.status_code == 200
    job = client.get(
        f"/api/v2/copilot/jobs/{response.get_json()['jobId']}").get_json()
    assert job["status"] == "error"
    current = store.get_session(session["id"])
    assert current["script"]["talkingPoints"] == []
    assert current["revision"] == session["revision"] + 1


# ---------------------------------------------------------------------------
# 首页卡片数据
# ---------------------------------------------------------------------------
def test_home_cards_use_constant_queries(client, qdb):
    login_as(client, qdb, role="admin", advisor_name="", display_name="Admin")
    _seed_report(qdb)
    qdb.session()

    statements: list[str] = []

    def _count(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(qdb.engine, "before_cursor_execute", _count)
    try:
        with client.application.test_request_context("/first-touch"):
            flask_session["role"] = "admin"
            flask_session["user_id"] = qdb.alice_id
            flask_session["advisor_name"] = ""
            one = copilot_api._first_touch_students()
            one_queries = len(statements)

            for index in range(9):
                with Session(qdb.engine) as sess:
                    sess.add(_db.Student(
                        student_code=f"Y4-93{index:02d}",
                        name=f"学生{index}", grade="10",
                        advisor_name="Alice"))
                    sess.commit()
            statements.clear()

            ten = copilot_api._first_touch_students()
            ten_queries = len(statements)
    finally:
        event.remove(qdb.engine, "before_cursor_execute", _count)

    assert len(one) == 2
    assert len(ten) == 11
    assert one_queries == ten_queries
    card = next(item for item in one if item["id"] == qdb.student_id)
    assert card["name"] == "林同学"
    assert card["canStart"] is True
    assert card["status"] == "in_progress"
    assert card["step"] == 0
    assert card["reportVersion"] is None
    assert card["y4Date"] == "2026-10-01"
    assert card["advisorName"] == "Alice"


def test_home_card_statuses(client, qdb):
    login_as(client, qdb, role="admin", advisor_name="", display_name="Admin")
    no_y4 = qdb.other_student_id

    with client.application.test_request_context("/first-touch"):
        flask_session["role"] = "admin"
        flask_session["user_id"] = qdb.alice_id
        flask_session["advisor_name"] = ""
        cards = {card["id"]: card
                 for card in copilot_api._first_touch_students()}

        assert cards[no_y4]["status"] == "needs_y4"
        assert cards[no_y4]["canStart"] is False

        _seed_report(qdb, no_y4)
        cards = {card["id"]: card
                 for card in copilot_api._first_touch_students()}
        assert cards[no_y4]["status"] == "not_started"
        assert cards[no_y4]["canStart"] is True
        assert cards[no_y4]["step"] is None
