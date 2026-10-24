"""V5 · 学生 360 的 First Touch 卡片（替换 Growth Talk）。"""
from __future__ import annotations

import pytest
from flask import Flask

import app_utils
import growth_talk_store as store
from blueprints import copilot as copilot_api
from blueprints import students as students_bp

from test_copilot_routes import login_as, qdb  # noqa: F401


@pytest.fixture(autouse=True)
def _stub_progress(monkeypatch):
    """360 页头进度依赖问卷/预约等表，与本任务无关，直接打桩。"""
    monkeypatch.setattr(
        students_bp, "_student_progress_context",
        lambda _sid: {
            "stage": "ready", "label": "—", "days": 0, "since_label": "",
            "suggestion": None, "six_am": None, "show_create_task": True,
        })


@pytest.fixture()
def client(qdb):
    app = Flask(__name__, template_folder=str(app_utils.TEMPLATE_DIR))
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True
    app.register_blueprint(students_bp.bp)
    app.register_blueprint(copilot_api.bp)
    app_utils.register_admin_context(app)
    app.context_processor(lambda: {"csrf_token": app_utils.get_csrf_token})
    app.add_template_filter(app_utils.dt_short, "dt_short")
    return app.test_client()


def _page(client, code: str = "Y4-9201") -> str:
    response = client.get(f"/students/{code}")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _session_with_run(qdb, *, phase=0, confirm_reports=0):
    session = qdb.session(phase=phase)
    source = store.create_source(
        qdb.student_id, "GROWTH_TALK", "GROWTH_TALK", "会谈纪要", "内容")
    run = store.create_run(qdb.student_id, source["id"])
    store.update_session_fields(
        session["id"], run_id=run["id"],
        status="COMPLETED" if confirm_reports else "ACTIVE")
    reports = [
        store.create_report(
            qdb.student_id, run["id"], '{"schema": "test"}', "王老师")
        for _ in range(confirm_reports)
    ]
    return store.get_session(session["id"]), run, reports


def test_needs_y4_shows_disabled_action(client, qdb):
    login_as(client, qdb)

    html = _page(client)

    assert "需先完成 Y4" in html
    assert "去生成 Y4" in html
    assert 'href="/generate"' in html
    assert "开始 First Touch" not in html
    assert "继续会谈" not in html


def test_not_started_shows_start_button(client, qdb):
    login_as(client, qdb)
    qdb.add_y4()

    html = _page(client)

    assert "未开始" in html
    assert "开始 First Touch" in html
    assert f"/first-touch/students/{qdb.student_id}" in html


def test_in_progress_shows_continue_with_step(client, qdb):
    login_as(client, qdb)
    qdb.add_y4()
    qdb.session(phase=5)

    html = _page(client)

    assert "进行中 · ③" in html
    assert "继续会谈" in html
    assert "开始 First Touch" not in html


def test_completed_lists_reports_newest_first(client, qdb):
    login_as(client, qdb)
    qdb.add_y4()
    _session, _run, reports = _session_with_run(qdb, confirm_reports=2)

    html = _page(client)

    assert "已完成 · v2" in html
    assert "查看 First Touch" in html
    assert "继续会谈" not in html
    versions = [report["version"] for report in reports]
    assert sorted(versions, reverse=True) == [2, 1]

    context = students_bp._first_touch_context(qdb.student_id)
    assert context["status"] == "completed"
    assert [report["version"] for report in context["reports"]] == [2, 1]
    assert context["reports"][0]["confirmedBy"] == "王老师"
    assert context["reports"][0]["confirmedAt"]


def test_page_has_no_growth_talk_wording(client, qdb):
    login_as(client, qdb)
    qdb.add_y4()
    _session_with_run(qdb, confirm_reports=1)

    html = _page(client)

    assert "Growth Talk" not in html
    assert "进入 Growth Talk" not in html
    assert "First Touch" in html


def test_interests_top_six_scored_with_special_focus_first(qdb):
    session = qdb.session()
    items = [
        {"id": f"i{i}", "label": f"兴趣{i}", "preferenceScore": 1,
         "competenceScore": 1}
        for i in range(5)
    ]
    items += [
        {"id": "i5", "label": "低分但特别关注", "preferenceScore": 0,
         "competenceScore": 0, "specialFocus": True},
        {"id": "i6", "label": "最高分", "preferenceScore": 3,
         "competenceScore": 3},
        {"id": "i7", "label": "待评", "preferenceScore": None,
         "competenceScore": None},
    ]
    store.replace_session_interests(session["id"], items)

    context = students_bp._first_touch_context(qdb.student_id)

    labels = [item["label"] for item in context["interests"]]
    assert len(labels) == 6
    assert labels[0] == "最高分"
    assert "待评" not in labels
    assert "低分但特别关注" not in labels
    assert context["scoredCount"] == 7
    assert context["pendingCount"] == 1


def test_special_focus_sorted_first_when_in_top_six(qdb):
    session = qdb.session()
    store.replace_session_interests(session["id"], [
        {"id": "a", "label": "高分", "preferenceScore": 3, "competenceScore": 3},
        {"id": "b", "label": "关注", "preferenceScore": 2,
         "competenceScore": 2, "specialFocus": True},
    ])

    context = students_bp._first_touch_context(qdb.student_id)

    assert [item["label"] for item in context["interests"]] == ["关注", "高分"]
    assert context["interests"][0]["specialFocus"] is True


def test_viewer_has_no_start_button_but_downloads(client, qdb):
    login_as(client, qdb, role="viewer", advisor_name="",
             display_name="观察员", user_id=qdb.alice_id)
    qdb.add_y4()
    _session_with_run(qdb, confirm_reports=1)

    html = _page(client)

    assert "查看 First Touch" in html
    assert "开始 First Touch" not in html
    assert "继续会谈" not in html
    assert "/api/growth-talk/reports/" in html
    assert "/download.pdf" in html
    assert "/download.json" in html
