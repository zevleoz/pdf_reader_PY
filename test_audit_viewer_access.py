"""A2 · Viewer 角色对 First Touch 的只读访问。

复用 ``test_copilot_routes.py`` 的 fixture，并额外注册 growth_talk 蓝图以覆盖
报告下载路由。
"""
from __future__ import annotations

import json
import re

import pytest
from flask import Flask

import app_utils
import growth_talk_store as store
from blueprints import copilot as copilot_api
from blueprints import growth_talk as gt_routes
from growth_talk import jobs, report_contract

from test_copilot_routes import login_as, qdb  # noqa: F401
from test_growth_talk_routes import _seed_ready_run, _valid_payload


@pytest.fixture()
def app(qdb):
    application = Flask(__name__, template_folder=str(app_utils.TEMPLATE_DIR))
    application.config["SECRET_KEY"] = "test-secret"
    application.config["TESTING"] = True
    application.register_blueprint(copilot_api.bp)
    application.register_blueprint(gt_routes.bp)
    app_utils.register_admin_context(application)
    application.context_processor(
        lambda: {"csrf_token": app_utils.get_csrf_token})
    application.add_template_filter(app_utils.dt_short, "dt_short")
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def seeded(qdb):
    session = qdb.session()
    run_id, _interest_ids, _career_id = _seed_ready_run(qdb)
    store.update_session_fields(session["id"], run_id=run_id)
    session = store.get_session(session["id"])

    report = store.create_report(
        qdb.student_id, run_id,
        json.dumps(_valid_payload(), ensure_ascii=False), "管理员")

    chat_id = store.create_chat(qdb.student_id, qdb.alice_id)
    store.add_chat_turn(chat_id, "这次会谈如何收尾？",
                        {"answer": "先确认兴趣。", "evidence": []},
                        "COMPLETE", student_id=qdb.student_id)

    job_id, _args = jobs.new_copilot_job(
        "assistant", {"student_id": qdb.student_id,
                      "advisor_id": qdb.alice_id})
    jobs.write_copilot_job(job_id, status="done",
                           student_id=qdb.student_id,
                           advisor_id=qdb.alice_id)

    fingerprint = report_contract.build_report_preview(run_id)["fingerprint"]
    return {
        "session_id": session["id"],
        "revision": session["revision"],
        "run_id": run_id,
        "report_id": report["id"],
        "chat_id": chat_id,
        "job_id": job_id,
        "fingerprint": fingerprint,
    }


def _login_viewer(client, qdb):
    login_as(client, qdb, role="viewer", advisor_name="",
             display_name="观察员", user_id=qdb.alice_id)


def test_viewer_read_routes_return_200(client, qdb, seeded):
    _login_viewer(client, qdb)
    sid = qdb.student_id
    urls = [
        "/first-touch",
        f"/first-touch/students/{sid}",
        "/first-touch/copilot",
        f"/first-touch/copilot/{sid}",
        "/first-touch/guide",
        f"/api/v2/students/{sid}/copilot/sessions",
        f"/api/v2/copilot/sessions/{seeded['session_id']}",
        f"/api/v2/copilot/jobs/{seeded['job_id']}",
        f"/api/v2/copilot/sessions/{seeded['session_id']}/report-pdf"
        f"?revision={seeded['revision']}&fingerprint={seeded['fingerprint']}",
        f"/api/students/{sid}/copilot/chats",
        f"/api/copilot/chats/{seeded['chat_id']}",
        f"/api/first-touch/reports/{seeded['report_id']}/activity-hub.json",
        f"/api/growth-talk/reports/{seeded['report_id']}/download.json",
        f"/api/growth-talk/reports/{seeded['report_id']}/download.pdf",
    ]
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200, (url, response.status_code)


def test_viewer_forbidden_on_every_write_route(app, client, qdb, seeded):
    _login_viewer(client, qdb)
    values = {
        "<int:sid>": str(qdb.student_id),
        "<int:session_id>": str(seeded["session_id"]),
        "<int:report_id>": str(seeded["report_id"]),
        "<int:run_id>": str(seeded["run_id"]),
        "<int:source_id>": "1",
        "<job_id>": seeded["job_id"],
        "<chat_id>": seeded["chat_id"],
    }
    checked = 0
    for rule in app.url_map.iter_rules():
        methods = (rule.methods or set()) - {"GET", "HEAD", "OPTIONS"}
        if not methods:
            continue
        url = rule.rule
        for placeholder, value in values.items():
            url = url.replace(placeholder, value)
        assert "<" not in url, (rule.rule, url)
        for method in methods:
            response = client.open(url, method=method, json={})
            assert response.status_code == 403, (method, rule.rule)
            checked += 1
    assert checked >= 15


def test_viewer_forbidden_on_archive_page(client, qdb, seeded):
    _login_viewer(client, qdb)

    response = client.get(f"/first-touch/archive/{qdb.student_id}")

    assert response.status_code == 403


def test_viewer_workspace_without_session_is_read_only(client, qdb):
    _login_viewer(client, qdb)

    response = client.get(f"/first-touch/students/{qdb.other_student_id}")

    assert response.status_code == 200
    flat = re.sub(r"\s+", "", response.get_data(as_text=True))
    assert '"entryScreen":false' in flat
    assert '"sessionId":null' in flat
    assert '"readOnly":true' in flat
    assert '"canWrite":false' in flat
    assert '"role":"viewer"' in flat
    assert store.list_sessions(qdb.other_student_id) == []


def test_viewer_workspace_with_session_shows_it(client, qdb, seeded):
    _login_viewer(client, qdb)

    response = client.get(f"/first-touch/students/{qdb.student_id}")

    assert response.status_code == 200
    flat = re.sub(r"\s+", "", response.get_data(as_text=True))
    assert f'"sessionId":{seeded["session_id"]}' in flat
    assert '"entryScreen":false' in flat
    assert '"readOnly":true' in flat
