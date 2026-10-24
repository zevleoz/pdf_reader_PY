"""Copilot 2.0 差距修复测试（M1–M18 / P1–P12）。

复用 ``test_copilot_routes.py`` 的 Flask/DB fixture；每个 Task 追加一组断言。
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import db as _db
import growth_talk_store as store
from blueprints import copilot as copilot_api
from growth_talk import copilot, copilot_report

from test_copilot_routes import (  # noqa: F401
    _fake_quadrant, _inline_jobs, _ready_session, client, login_as, qdb,
)


def _phase_patch(client, session_id: int, revision: int, **body):
    return client.patch(
        f"/api/v2/copilot/sessions/{session_id}/phase",
        json={"phase": 2, "revision": revision, **body})


# ---------------------------------------------------------------------------
# Task 1：入口选择屏 + 会谈时间
# ---------------------------------------------------------------------------
def test_workspace_get_does_not_autocreate_session(client, qdb):
    login_as(client, qdb)

    response = client.get(f"/first-touch/students/{qdb.student_id}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "v2-entry-choice" not in html
    assert "entryScreen" not in html
    assert store.list_sessions(qdb.student_id) == []


def test_meeting_at_in_preview_payload(client, qdb, monkeypatch):
    _inline_jobs(monkeypatch)
    login_as(client, qdb)
    session = _ready_session(qdb)
    meeting_at = "2026-01-01T04:00:00Z"

    patched = _phase_patch(client, session["id"], session["revision"],
                           meetingAt=meeting_at)
    assert patched.status_code == 200

    monkeypatch.setattr(copilot_report, "_run_quadrant", _fake_quadrant)
    current = store.get_session(session["id"])
    prepared = client.post(
        f"/api/v2/copilot/sessions/{session['id']}/report-prepare",
        json={"revision": current["revision"]})

    assert prepared.status_code == 200
    job_id = prepared.get_json()["jobId"]
    body = client.get(f"/api/v2/copilot/jobs/{job_id}").get_json()
    result = body["result"]
    assert result["draft"]["meetingAt"] == meeting_at
    assert "访谈日期：2026年1月1日 12:00" in result["preview"]["meetingSummary"]


# ---------------------------------------------------------------------------
# Task 2：阶段 5 审核保真
# ---------------------------------------------------------------------------
def test_session_get_exposes_score_conflicts(client, qdb):
    login_as(client, qdb)
    session = _ready_session(qdb)
    supplement = store.latest_supplement(session["id"])
    store.save_supplement_analysis(supplement["id"], {
        "analysisVersion": "v2",
        "scoreConflicts": ["篮球：会议喜欢程度低于已确认评分"],
        "newInterests": [],
    }, "PENDING_REVIEW")

    data = client.get(f"/api/v2/copilot/sessions/{session['id']}").get_json()

    analysis = data["session"]["supplements"][0]["analysis"]
    assert analysis["scoreConflicts"] == ["篮球：会议喜欢程度低于已确认评分"]


def test_y4_validation_saved_and_clamped(client, qdb):
    login_as(client, qdb)
    session = _ready_session(qdb)

    response = _phase_patch(
        client, session["id"], session["revision"],
        supplementAnalysis={"y4Validation": ["一", "二", "三", "四" * 60]})

    assert response.status_code == 200
    current = store.get_session(session["id"])
    saved = current["supplements"][0]["analysis"]["y4Validation"]
    assert saved == ["一", "二", "三"]


# ---------------------------------------------------------------------------
# Task 3：阶段 3 分组卡片 + 实时象限
# ---------------------------------------------------------------------------
def test_workspace_page_has_pending_score_option(client, qdb):
    login_as(client, qdb)
    qdb.session()

    html = client.get(f"/first-touch/students/{qdb.student_id}").get_data(as_text=True)

    assert "待评" in html
    assert "?? 1" not in html and "|| 1" not in html


# ---------------------------------------------------------------------------
# Task 4：报告阶段
# ---------------------------------------------------------------------------
def test_workspace_has_report_missing_sections(client, qdb):
    login_as(client, qdb)
    qdb.session()

    html = client.get(f"/first-touch/students/{qdb.student_id}").get_data(as_text=True)

    assert "必填" in html and "可选" in html


def test_workspace_has_confirmed_report_view(client, qdb):
    login_as(client, qdb)
    qdb.session()

    html = client.get(f"/first-touch/students/{qdb.student_id}").get_data(as_text=True)

    assert "已确认报告" in html


# ---------------------------------------------------------------------------
# Task 5：项目推荐新增方案
# ---------------------------------------------------------------------------
def _project_row(index: int, interest_id: str) -> dict:
    return {
        "title": f"方案{index}",
        "interestAnchor": "投篮训练",
        "interestRefs": [interest_id],
        "evidenceQuotes": ["每周训练篮球"],
        "fitType": "observation_research",
        "domains": ["运动"],
        "coreQuestion": "为什么喜欢投篮？",
        "example": "记录训练感受",
        "journeySummary": "持续观察",
        "whyThisProject": "会议证据支持",
        "minimumViableProject": "一周记录",
        "likelyOutputs": ["训练日志"],
        "expansionPath": ["分析比赛"],
        "openQuestions": ["时间安排"],
    }


def test_apply_project_edits_accepts_new_item(qdb, monkeypatch):
    session = _ready_session(qdb)
    monkeypatch.setattr(copilot, "call_model", lambda _prompt: {
        "recommendations": [_project_row(1, "i1"), _project_row(2, "i1")],
    })
    batch = copilot.generate_projects(session["id"])
    old_version = batch["version"]
    existing = [dict(item) for item in batch["items"]]
    new_item = {**existing[0], "recommendationId": None,
                "title": "新方案", "version": 1}

    updated = copilot.apply_project_edits(
        session["id"], existing + [new_item], "顾问")

    created = [item for item in updated["items"] if item["title"] == "新方案"]
    assert created and created[0]["recommendationId"]
    assert updated["version"] == old_version + 1
    assert len(updated["items"]) == len(existing) + 1


# ---------------------------------------------------------------------------
# Task 6：阶段 1/2/4 内容
# ---------------------------------------------------------------------------
def test_workspace_phase_one_has_no_interpretation(client, qdb):
    login_as(client, qdb)
    qdb.session()

    html = client.get(f"/first-touch/students/{qdb.student_id}").get_data(as_text=True)

    assert 'data-phase-section="interpretation"' not in html
    assert "Y4 速览" in html


def test_workspace_has_y4_cards_and_editable_next_summary(client, qdb):
    login_as(client, qdb)
    qdb.session()

    html = client.get(f"/first-touch/students/{qdb.student_id}").get_data(as_text=True)

    assert "职业兴趣" in html and "能力优势" in html and "职业价值观" in html
    assert 'data-next-summary-editor' in html


# ---------------------------------------------------------------------------
# Task 7：聊天中心与浮动聊天
# ---------------------------------------------------------------------------
def _seed_chat(qdb, question: str = "问题") -> str:
    chat_id = store.create_chat(qdb.student_id, qdb.alice_id)
    store.add_chat_turn(chat_id, question, {
        "answer": "回答", "evidence": []}, "COMPLETE",
        student_id=qdb.student_id)
    return chat_id


def test_delete_chat(client, qdb):
    login_as(client, qdb)
    chat_id = _seed_chat(qdb)

    response = client.delete(f"/api/copilot/chats/{chat_id}")

    assert response.status_code == 200
    with pytest.raises(store.NotFoundError):
        store.get_chat(chat_id)


def test_delete_chat_other_advisor_404(client, qdb):
    chat_id = _seed_chat(qdb)
    login_as(client, qdb, advisor_name="Bob", display_name="Bob")

    response = client.delete(f"/api/copilot/chats/{chat_id}")

    assert response.status_code == 404


def test_chat_page_redirects_to_student_workspace(client, qdb):
    login_as(client, qdb)
    deleted_id = _seed_chat(qdb, "已删除对话")
    _seed_chat(qdb, "最新对话")
    store.delete_chat(deleted_id)

    response = client.get(
        f"/first-touch/copilot/{qdb.student_id}?chat={deleted_id}")

    assert response.status_code == 302
    assert response.headers["Location"] == f"/first-touch/students/{qdb.student_id}"


# ---------------------------------------------------------------------------
# Task 8：首页与归档
# ---------------------------------------------------------------------------
def test_archive_has_activity_hub_download(client, qdb):
    login_as(client, qdb, role="admin", advisor_name="", display_name="Admin")

    page = client.get(f"/first-touch/archive/{qdb.student_id}")
    assert page.status_code == 200

    rules = {rule.rule for rule in client.application.url_map.iter_rules()}
    assert "/api/first-touch/reports/<int:report_id>/activity-hub.json" in rules


def test_activity_hub_payload_matches_schema(qdb):
    report = {
        "id": 9, "version": 2, "status": "CONFIRMED",
        "confirmed_at": "2026-01-01T04:00:00",
        "payload": json.dumps({
            "schema": "first-touch.report.v1",
            "reportId": "r-9",
            "student": {"name": "林同学", "grade": "10", "school": "示例学校"},
            "career": {"careerInterests": "喜欢运动科学",
                       "abilityTendencies": "动手能力强",
                       "valuePreferences": "重视自主"},
            "interests": [{"id": "i1", "label": "篮球", "evidence": "每周训练",
                           "preferenceScore": 3, "competenceScore": 2}],
        }, ensure_ascii=False),
    }
    student = {"id": qdb.student_id, "name": "林同学", "grade": "10",
               "school": "示例学校", "student_code": "Y4-9201"}

    profile = copilot_api._activity_hub_profile(report, student)

    assert profile["schema"] == "first_touch.activity_hub_import.3.0.0"
    assert profile["sourceReport"]["reportVersion"] == 2
    assert profile["interestProfile"]["items"][0]["preferenceScoreV2"] == 3
    assert profile["careerInterestProfile"]["careerInterests"]["summary"]
