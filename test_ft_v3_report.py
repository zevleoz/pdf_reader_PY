"""V3b 验收：可选会议文字稿、显式 AI 草稿、一步确认报告。"""
from __future__ import annotations

import fitz
import pytest
from flask import Flask

import app_utils
import growth_talk_store as store
from blueprints import copilot as copilot_api
from blueprints import growth_talk as growth_talk_api
from growth_talk import copilot_report

from test_copilot_routes import (  # noqa: F401
    _fake_quadrant, _inline_jobs, _ready_session, login_as, qdb,
)


@pytest.fixture()
def client(qdb):
    """同时注册报告页与已确认报告下载所用的两个蓝图。"""
    app = Flask(__name__, template_folder=str(app_utils.TEMPLATE_DIR))
    app.config["SECRET_KEY"] = "test-secret"
    app.register_blueprint(copilot_api.bp)
    app.register_blueprint(growth_talk_api.bp)
    app.config["TESTING"] = True
    app_utils.register_admin_context(app)
    app.context_processor(lambda: {"csrf_token": app_utils.get_csrf_token})
    app.add_template_filter(app_utils.dt_short, "dt_short")
    return app.test_client()


SNAPSHOT = {
    "hollandCode": "SAE",
    "reportDate": "2026-10-01",
    "riasec": [
        {"key": "S", "label": "社会型", "score": 5},
        {"key": "A", "label": "艺术型", "score": 4},
        {"key": "E", "label": "事业型", "score": 3},
    ],
    "topAbilities": [{"label": "沟通", "score": 5}, {"label": "分析", "score": 4}],
    "weakestAbility": {"label": "动手", "score": 1},
    "topValues": [{"label": "成就感", "score": 5}],
    "topicSuggestions": ["志愿服务", "演讲"],
}

SUMMARY = ("本次会谈围绕篮球训练与比赛观察展开，"
           "后续会继续设计、观察和验证这些线索。")


def _interests(count: int = 3) -> list[dict]:
    rows = [
        ("i1", "篮球", 3, 2),
        ("i2", "足球", 2, 1),
        ("i3", "阅读", 2, 3),
    ]
    return [{
        "id": interest_id, "label": label, "topicType": "interest",
        "preferenceScore": preference, "competenceScore": competence,
        "note": "会谈记录", "evidence": f"{label}相关证据",
    } for interest_id, label, preference, competence in rows[:count]]


def _no_transcript_session(qdb, *, count: int = 3, summary: str = SUMMARY):
    """没有会议文字稿的会谈：只保存兴趣与总结。"""
    session = qdb.session(phase=6)
    store.replace_session_interests(session["id"], _interests(count))
    script = {"y4Snapshot": dict(SNAPSHOT)}
    if summary:
        script["nextSummary"] = summary
    store.update_session_fields(session["id"], script=script)
    return store.get_session(session["id"])


def _confirm(client, session_id: int, revision: int):
    return client.post(
        f"/api/v2/copilot/sessions/{session_id}/report-confirm",
        json={"revision": revision})


def _missing_keys(response) -> list[str]:
    return [item["key"] for item in response.get_json()["missing"]]


def _pdf_text(data: bytes) -> str:
    with fitz.open(stream=data, filetype="pdf") as document:
        return "\x0c".join(page.get_text() for page in document)


# ---------------------------------------------------------------------------
# 无文字稿的一步确认
# ---------------------------------------------------------------------------
def test_one_step_confirm_without_transcript(client, qdb, monkeypatch):
    monkeypatch.setattr(copilot_report, "_run_quadrant", _fake_quadrant)
    login_as(client, qdb)
    session = _no_transcript_session(qdb)

    response = _confirm(client, session["id"], session["revision"])

    assert response.status_code == 201
    body = response.get_json()
    report = body["report"]
    assert report["version"] == 1
    assert report["confirmedBy"] == "Alice"
    assert report["confirmedAt"]
    assert body["revision"] > session["revision"]
    current = store.get_session(session["id"])
    assert current["status"] == "COMPLETED"
    assert current["completed_at"]

    download = client.get(
        f"/api/growth-talk/reports/{report['id']}/download.pdf")
    assert download.status_code == 200
    assert download.data[:5] == b"%PDF-"
    text = _pdf_text(download.data)
    assert "职业兴趣代码 SAE" in text
    assert "沟通" in text
    assert "成就感" in text


def test_confirm_is_idempotent_while_completed(client, qdb, monkeypatch):
    monkeypatch.setattr(copilot_report, "_run_quadrant", _fake_quadrant)
    login_as(client, qdb)
    session = _no_transcript_session(qdb)

    first = _confirm(client, session["id"], session["revision"])
    current = store.get_session(session["id"])
    second = _confirm(client, session["id"], current["revision"])

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["report"]["id"] == first.get_json()["report"]["id"]


# ---------------------------------------------------------------------------
# 必填项守卫
# ---------------------------------------------------------------------------
def test_two_scored_interests_reports_min_interests(client, qdb):
    login_as(client, qdb)
    session = _no_transcript_session(qdb, count=2)

    response = _confirm(client, session["id"], session["revision"])

    assert response.status_code == 422
    assert "min-interests" in _missing_keys(response)
    assert store.get_session(session["id"])["status"] != "COMPLETED"


def test_missing_summary_is_reported(client, qdb):
    login_as(client, qdb)
    session = _no_transcript_session(qdb, summary="")

    response = _confirm(client, session["id"], session["revision"])

    assert response.status_code == 422
    keys = _missing_keys(response)
    assert "summary" in keys
    assert "min-interests" not in keys


def test_undecided_transcript_candidate_blocks_confirm(client, qdb):
    login_as(client, qdb)
    session = _ready_session(qdb)
    supplement = store.latest_supplement(session["id"])
    store.save_supplement_analysis(supplement["id"], {
        "analysisVersion": "v2",
        "newInterests": [{
            "label": "机器人搭建", "topicType": "interest",
            "evidence": "参加机器人社团", "preferenceScore": 2,
            "competenceScore": 2,
        }],
    }, supplement["status"])

    current = store.get_session(session["id"])
    response = _confirm(client, session["id"], current["revision"])

    assert response.status_code == 422
    assert "pending-suggestions" in _missing_keys(response)


# ---------------------------------------------------------------------------
# 确认后继续编辑
# ---------------------------------------------------------------------------
def test_edit_after_confirm_returns_to_review_and_bumps_version(
        client, qdb, monkeypatch):
    monkeypatch.setattr(copilot_report, "_run_quadrant", _fake_quadrant)
    login_as(client, qdb)
    session = _no_transcript_session(qdb)

    assert _confirm(client, session["id"], session["revision"]).status_code == 201
    completed = store.get_session(session["id"])
    assert completed["status"] == "COMPLETED"

    edited = _interests()
    edited[0]["preferenceScore"] = 1
    patched = client.patch(
        f"/api/v2/copilot/sessions/{session['id']}/interest-draft",
        json={"revision": completed["revision"], "interests": edited})

    assert patched.status_code == 200
    assert store.get_session(session["id"])["status"] == "REVIEW"

    current = store.get_session(session["id"])
    again = _confirm(client, session["id"], current["revision"])

    assert again.status_code == 201
    assert again.get_json()["report"]["version"] == 2
    assert store.get_session(session["id"])["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# 旧指纹路径与只读预览
# ---------------------------------------------------------------------------
def test_old_fingerprint_confirm_path_still_works(client, qdb, monkeypatch):
    _inline_jobs(monkeypatch)
    monkeypatch.setattr(copilot_report, "_run_quadrant", _fake_quadrant)
    login_as(client, qdb)
    session = _ready_session(qdb)

    prepared = client.post(
        f"/api/v2/copilot/sessions/{session['id']}/report-prepare",
        json={"revision": session["revision"]})
    assert prepared.status_code == 200
    job = client.get(
        f"/api/v2/copilot/jobs/{prepared.get_json()['jobId']}").get_json()
    result = job["result"]
    preview = result["preview"]

    response = client.post(
        f"/api/v2/copilot/sessions/{session['id']}/report-confirm",
        json={
            "revision": result["revision"],
            "fingerprint": preview["fingerprint"],
            "suggestionIds": [],
            "reviewedMeeting": True,
            "reviewedNarrative": True,
        })

    assert response.status_code == 201
    assert response.get_json()["report"]["version"] == 1


def test_report_preview_returns_missing_alongside_draft(
        client, qdb, monkeypatch):
    monkeypatch.setattr(copilot_report, "_run_quadrant", _fake_quadrant)
    login_as(client, qdb)
    session = _no_transcript_session(qdb, count=2)

    response = client.post(
        f"/api/v2/copilot/sessions/{session['id']}/report-preview",
        json={"revision": session["revision"]})

    assert response.status_code == 200
    body = response.get_json()
    assert body["draft"]["interests"]
    assert any(item["key"] == "min-interests" for item in body["missing"])
    assert body["preview"] is None
