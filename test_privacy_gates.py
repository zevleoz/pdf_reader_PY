# -*- coding: utf-8 -*-
"""C1：概要账号看不到 First Touch 内容；顾问产出 / 月度产出仅管理员可见。

用真实 Flask 入口（``app.create_app``）与独立临时 SQLite，不触碰 data/y4_students.db。
四类账号：admin、viewer（概要）、顾问 + 概要、顾问 + 完整。
"""
from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app_utils
import db as _db
import growth_talk_store as store
import questionnaire_store as qs
from growth_talk import jobs

PASSWORD = "pw-123456"
RESTRICTED = "当前账号不能查看 First Touch 内容"
CSRF = "csrf-test-token"

# 只出现在 First Touch 内容里的独特文本（学生页不得出现给概要账号）
NOTE_TEXT = "QZXV8841note"
INTEREST_LABEL = "QZXV9952interest"
SUMMARY_TEXT = "QZXV7763summary"


def _new_chat(w):
    chat_id = store.create_chat(w.student_id, w.admin_id, w.session_id)
    store.add_chat_turn(chat_id, "一个问题", {"answer": NOTE_TEXT, "evidence": []},
                        "DONE", student_id=w.student_id, session_id=w.session_id)
    return chat_id


@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/privacy_gates.db")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    _db.Base.metadata.create_all(engine)
    qs.ensure_indexes(bind=engine)
    monkeypatch.setattr(_db, "engine", engine)
    monkeypatch.setattr(qs, "engine", engine)
    monkeypatch.setattr(jobs, "COPILOT_JOB_DIR", str(tmp_path / "_copilot_jobs"))
    # 通过闸门的请求不得真的拉起子进程
    monkeypatch.setattr(jobs, "launch_copilot_job", lambda kind, payload: "job-test")
    app_utils._SESSION_USER_CACHE.clear()
    app_utils._RATE_BUCKETS.clear()

    w = SimpleNamespace(
        admin_id=_db.create_user("c1-admin", PASSWORD, "admin"),
        viewer_id=_db.create_user("c1-view", PASSWORD, "viewer"),
        adv_summary_id=_db.create_user("c1-adv-sum", PASSWORD, "advisor",
                                       advisor_name="Mine", detail_level="summary"),
        adv_full_id=_db.create_user("c1-adv-full", PASSWORD, "advisor",
                                    advisor_name="Mine", detail_level="full"),
    )
    with Session(engine) as sess:
        student = _db.Student(student_code="Y4-C101", name="隐私同学",
                              grade="10", advisor_name="Mine")
        sess.add(student)
        sess.commit()
        w.student_id = student.id
        w.student_code = student.student_code
        points = [{"code": "072", "value": "SAE", "type": "string"}] + [
            {"code": code, "value": value, "type": "number"}
            for code, value in (("073", "2"), ("074", "5"), ("075", "2"),
                                ("076", "4"), ("077", "1"), ("078", "3"))]
        sess.add(_db.Report(student_id=student.id, report_date=date(2026, 10, 1),
                            pdf_path="r.pdf",
                            data_json=json.dumps({"schema_124": points})))
        sess.commit()

    session_row, _ = store.create_session(
        w.student_id, w.admin_id, meeting_at="2026-10-02T08:00:00Z",
        script={"nextSummary": NOTE_TEXT})
    store.update_session_fields(session_row["id"], phase=1)
    store.replace_session_interests(session_row["id"], [{
        "id": "i1", "label": INTEREST_LABEL, "topicType": "interest",
        "preferenceScore": 3, "competenceScore": 2, "note": NOTE_TEXT,
        "evidence": NOTE_TEXT,
    }])
    w.session_id = session_row["id"]

    source = store.create_source(
        w.student_id, "GROWTH_TALK", "GROWTH_TALK", "会谈纪要", SUMMARY_TEXT,
        purpose="MEETING", file_name="meeting.txt")
    run = store.create_run(w.student_id, source["id"])
    report = store.create_report(
        w.student_id, run["id"], json.dumps({"schema": "legacy", "note": NOTE_TEXT}),
        "管理员")
    w.report_id = report["id"]

    w.chat_id = _new_chat(w)

    jobs_dir = tmp_path / "_copilot_jobs"
    jobs_dir.mkdir(exist_ok=True)
    (jobs_dir / "jobabc.json").write_text(json.dumps({
        "status": "done", "student_id": w.student_id,
        "result": {"text": NOTE_TEXT}}), encoding="utf-8")
    w.job_id = "jobabc"

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
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role
        sess["advisor_name"] = advisor_name
        sess["_csrf_token"] = CSRF
    return client


def _clients(app, world):
    return {
        "admin": _client(app, world.admin_id, "admin"),
        "viewer": _client(app, world.viewer_id, "viewer"),
        "advisor_summary": _client(app, world.adv_summary_id, "advisor", "Mine"),
        "advisor_full": _client(app, world.adv_full_id, "advisor", "Mine"),
    }


def _call(client, method, url, body=None):
    kwargs = {"headers": {"X-CSRF-Token": CSRF}}
    if body is not None:
        kwargs["json"] = body
    return getattr(client, method.lower())(url, **kwargs)


# 每条: (名称, 方法, URL 模板, 请求体, 允许的状态)
#   允许的状态为 200 表示管理员 / 顾问+完整必须得到该状态；
#   None 表示这类端点依赖 AI 作业 / 报告新鲜度等，只断言「没被闸门挡住」。
READ_ROUTES = [
    ("session-get", "GET", "/api/v2/copilot/sessions/{session_id}", None, 200),
    ("job-status", "GET", "/api/v2/copilot/jobs/{job_id}", None, 200),
    ("chats-list", "GET", "/api/students/{student_id}/copilot/chats", None, 200),
    ("chat-get", "GET", "/api/copilot/chats/{chat_id}", None, 200),
    ("report-pdf", "GET", "/api/v2/copilot/sessions/{session_id}/report-pdf", None, None),
    ("activity-hub", "GET", "/api/first-touch/reports/{report_id}/activity-hub.json",
     None, None),
    ("gt-download-json", "GET", "/api/growth-talk/reports/{report_id}/download.json",
     None, 200),
    ("gt-download-pdf", "GET", "/api/growth-talk/reports/{report_id}/download.pdf",
     None, None),
    ("page-workspace", "GET", "/first-touch/students/{student_id}", None, 200),
    ("page-chat-redirect", "GET", "/first-touch/copilot/{student_id}", None, 302),
    ("page-gt-redirect", "GET", "/students/{student_id}/growth-talk", None, 302),
]

WRITE_ROUTES = [
    ("session-create", "POST", "/api/v2/students/{student_id}/copilot/sessions", {}, None),
    ("phase-save", "PATCH", "/api/v2/copilot/sessions/{session_id}/phase", {}, None),
    ("interest-draft", "PATCH", "/api/v2/copilot/sessions/{session_id}/interest-draft",
     {}, None),
    ("source-upload", "POST", "/api/v2/copilot/sessions/{session_id}/sources", {}, None),
    ("supplement", "POST", "/api/v2/copilot/sessions/{session_id}/supplement", {}, None),
    ("next-steps", "POST", "/api/v2/copilot/sessions/{session_id}/next-steps", {}, None),
    ("talking-points", "POST", "/api/v2/copilot/sessions/{session_id}/talking-points",
     {}, None),
    ("projects-generate", "POST", "/api/v2/copilot/sessions/{session_id}/projects",
     {}, None),
    ("projects-review", "PATCH", "/api/v2/copilot/sessions/{session_id}/projects",
     {}, None),
    ("report-prepare", "POST", "/api/v2/copilot/sessions/{session_id}/report-prepare",
     {}, None),
    ("report-preview", "POST", "/api/v2/copilot/sessions/{session_id}/report-preview",
     {}, 200),
    ("report-confirm", "POST", "/api/v2/copilot/sessions/{session_id}/report-confirm",
     {}, None),
    ("assistant-student", "POST", "/api/students/{student_id}/copilot/assistant",
     {"question": "你好"}, 200),
    ("assistant-session", "POST", "/api/v2/copilot/sessions/{session_id}/assistant",
     {"question": "你好"}, 200),
    ("chat-delete", "DELETE", "/api/copilot/chats/{chat_id}", None, 200),
]

ALL_ROUTES = READ_ROUTES + WRITE_ROUTES
ROUTE_IDS = [r[0] for r in ALL_ROUTES]


def _url(template, world):
    return template.format(**vars(world))


def _gated(resp):
    """被 First Touch 闸门挡下：API 为带固定文案的 403；页面为 403。"""
    if resp.status_code != 403:
        return False
    if resp.mimetype == "application/json":
        return resp.get_json().get("error") == RESTRICTED
    return True


# ── 1. 每个内容端点：admin / 顾问+完整 通过；viewer / 顾问+概要 403 ──────────
@pytest.mark.parametrize("route", ALL_ROUTES, ids=ROUTE_IDS)
def test_summary_accounts_get_403(app, world, route):
    _, method, template, body, _expect = route
    clients = _clients(app, world)
    url = _url(template, world)
    # viewer 在写端点上先被角色拦（403），读端点必须被闸门拦
    for who in ("viewer", "advisor_summary"):
        resp = _call(clients[who], method, url, body)
        assert resp.status_code == 403, (who, resp.status_code)
        if who == "advisor_summary":
            assert _gated(resp), resp.get_data(as_text=True)[:200]
        elif method == "GET":
            assert _gated(resp), resp.get_data(as_text=True)[:200]
        text = resp.get_data(as_text=True)
        assert NOTE_TEXT not in text and INTEREST_LABEL not in text


@pytest.mark.parametrize("route", ALL_ROUTES, ids=ROUTE_IDS)
def test_full_accounts_pass_the_gate(app, world, route):
    _, method, template, body, expect = route
    clients = _clients(app, world)
    for who in ("admin", "advisor_full"):
        world.chat_id = _new_chat(world)  # chat-delete 会删除聊天
        url = _url(template, world)
        resp = _call(clients[who], method, url, body)
        if expect is not None:
            assert resp.status_code == expect, (who, resp.status_code,
                                                resp.get_data(as_text=True)[:200])
        assert not _gated(resp), (who, resp.status_code)
        assert resp.status_code not in (401,), who


# ── 2. 列表端点：概要账号只得状态与日期，restricted 为真，无内容字段 ─────────
def test_sessions_list_restricted_for_summary(app, world):
    clients = _clients(app, world)
    url = f"/api/v2/students/{world.student_id}/copilot/sessions"
    for who in ("viewer", "advisor_summary"):
        resp = clients[who].get(url)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["restricted"] is True
        assert data["sessions"], "状态与日期仍应可见"
        for item in data["sessions"]:
            assert item["status"] and item["created_at"] and item["updated_at"]
            assert item["script"] == {} and item["interests"] == []
        assert NOTE_TEXT not in resp.get_data(as_text=True)
        assert INTEREST_LABEL not in resp.get_data(as_text=True)


def test_sessions_list_full_for_full_accounts(app, world):
    clients = _clients(app, world)
    url = f"/api/v2/students/{world.student_id}/copilot/sessions"
    for who in ("admin", "advisor_full"):
        data = clients[who].get(url).get_json()
        assert "restricted" not in data
        assert INTEREST_LABEL in json.dumps(data, ensure_ascii=False)


def test_first_touch_home_lists_status_but_no_links_for_summary(app, world):
    clients = _clients(app, world)
    for who in ("viewer", "advisor_summary"):
        resp = clients[who].get("/first-touch")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "隐私同学" in html  # 学生列表仍可见
        assert f"/first-touch/students/{world.student_id}" not in html
        assert "开始</button>" not in html
        assert RESTRICTED in html
    html = clients["advisor_full"].get("/first-touch").get_data(as_text=True)
    assert f"/first-touch/students/{world.student_id}" in html


# ── 3. 写入：顾问+概要 与 viewer 一律 403 ─────────────────────────────────────
@pytest.mark.parametrize("route", WRITE_ROUTES, ids=[r[0] for r in WRITE_ROUTES])
def test_write_endpoints_blocked_for_summary(app, world, route):
    _, method, template, body, _expect = route
    clients = _clients(app, world)
    url = _url(template, world)
    for who in ("viewer", "advisor_summary"):
        resp = _call(clients[who], method, url, body)
        assert resp.status_code == 403, (who, resp.status_code)
    # 被拦下时不得产生任何写入
    assert store.get_session(world.session_id)["script"]["nextSummary"] == NOTE_TEXT


def test_summary_advisor_cannot_start_or_save(app, world):
    """顾问+概要即使用 PATCH 直接写，也不得改动会谈。"""
    client = _clients(app, world)["advisor_summary"]
    before = store.get_session(world.session_id)["revision"]
    resp = _call(client, "PATCH",
                 f"/api/v2/copilot/sessions/{world.session_id}/phase",
                 {"revision": before, "script": {"nextSummary": "被篡改"}})
    assert resp.status_code == 403
    after = store.get_session(world.session_id)
    assert after["revision"] == before
    assert after["script"]["nextSummary"] == NOTE_TEXT


# ── 4. 学生页：概要账号的 HTML 里没有 First Touch 内容 ─────────────────────────
def test_student_page_hides_first_touch_content_for_summary(app, world):
    clients = _clients(app, world)
    url = f"/students/{world.student_code}"
    for who in ("admin", "advisor_full"):
        html = clients[who].get(url).get_data(as_text=True)
        assert INTEREST_LABEL in html, "对照：完整账号应能看到兴趣标签"
        assert f"/api/growth-talk/reports/' + r.id" in html  # 报告表仍渲染
    for who in ("viewer", "advisor_summary"):
        resp = clients[who].get(url)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert INTEREST_LABEL not in html
        assert NOTE_TEXT not in html
        assert SUMMARY_TEXT not in html
        assert "download.pdf" not in html and "download.json" not in html
        assert f"/first-touch/students/{world.student_id}" not in html
        assert RESTRICTED in html


# ── 5. 仪表盘：顾问产出 / 月度产出仅管理员 ─────────────────────────────────────
def test_dashboard_page_sections_admin_only(app, world):
    clients = _clients(app, world)
    admin_html = clients["admin"].get("/insights/dashboard").get_data(as_text=True)
    assert "顾问产出" in admin_html and "月度产出" in admin_html
    for who in ("viewer", "advisor_summary", "advisor_full"):
        html = clients[who].get("/insights/dashboard").get_data(as_text=True)
        assert "顾问产出" not in html, who
        assert "月度产出" not in html, who
        assert "chartTimeline" not in html, who


def test_dashboard_stats_api_withholds_staff_output(app, world):
    clients = _clients(app, world)
    admin = clients["admin"].get("/api/dashboard/stats").get_json()["stats"]
    assert admin["advisor_performance"], "对照：管理员应得到顾问产出数据"
    assert "timeline" in admin and "advisor_name_review" in admin
    assert "top_advisor" in admin["highlights"]
    for who in ("viewer", "advisor_summary", "advisor_full"):
        resp = clients[who].get("/api/dashboard/stats")
        assert resp.status_code == 200
        stats = resp.get_json()["stats"]
        for key in ("advisor_performance", "advisor_name_review", "timeline"):
            assert key not in stats, (who, key)
        assert "top_advisor" not in stats["highlights"]
        assert "top_advisor_count" not in stats["highlights"]
        assert "Mine" not in resp.get_data(as_text=True), who


# ── 6. 不变：/api/v1/* 仍按 Bearer 令牌工作，不受闸门影响 ───────────────────────
def test_api_v1_growth_talk_not_gated(app, world, monkeypatch):
    monkeypatch.setattr(app_utils, "Y4_API_KEY", "test-key", raising=False)
    import blueprints.api_v1 as v1
    monkeypatch.setattr(v1, "Y4_API_KEY", "test-key", raising=False)
    client = app.test_client()  # 无 session，只带 Bearer
    resp = client.get(f"/api/v1/students/{world.student_id}/growth-talk-reports",
                      headers={"Authorization": "Bearer test-key"})
    assert resp.status_code != 403
