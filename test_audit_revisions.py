"""A1 验收：revision 先抢占再写数据；阶段导航不递增 revision。"""
from __future__ import annotations

import io
import json

import pytest

import growth_talk_store as store
from growth_talk import copilot, copilot_report, jobs

from test_copilot_routes import (  # noqa: F401
    _fake_quadrant, _inline_jobs, _ready_session, client, login_as, qdb,
)
from test_copilot_gapfixes import _project_row

STALE_MESSAGE = "会谈在生成期间已被修改，请刷新后重新生成。"
CONFLICT_MESSAGE = "会谈已更新，请保留草稿并刷新确认"


def _interest(label: str = "篮球") -> dict:
    return {
        "id": "i1", "label": label, "topicType": "interest",
        "preferenceScore": 3, "competenceScore": 2,
        "note": "每周训练", "evidence": "每周训练篮球",
    }


def _snapshot(session_id: int) -> dict:
    session = store.get_session(session_id)
    supplement = store.latest_supplement(session_id) or {}
    return {
        "revision": session["revision"],
        "phase": session["phase"],
        "status": session["status"],
        "interests": json.dumps(session["interests"], ensure_ascii=False,
                                sort_keys=True),
        "script": json.dumps(session["script"], ensure_ascii=False,
                             sort_keys=True),
        "calibration": json.dumps(session["calibration"], ensure_ascii=False,
                                  sort_keys=True),
        "supplement_analysis": json.dumps(supplement.get("analysis"),
                                          ensure_ascii=False, sort_keys=True),
        "supplement_status": supplement.get("status"),
        "sources": json.dumps([
            {key: source.get(key) for key in
             ("id", "title", "content", "file_name")}
            for source in store.list_sources(session["student_id"])
        ], ensure_ascii=False, sort_keys=True),
    }


def _content_snapshot(session_id: int) -> dict:
    snapshot = _snapshot(session_id)
    snapshot.pop("revision")
    return snapshot


def _stale_launcher(monkeypatch, qdb):
    """作业启动瞬间把 revision 推到 N+1，模拟生成期间有人修改会谈。"""
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


# ---------------------------------------------------------------------------
# 过期 revision：409 且数据库内容不变
# ---------------------------------------------------------------------------
def test_stale_phase_content_409_leaves_db_unchanged(client, qdb):
    login_as(client, qdb)
    session = _ready_session(qdb)
    before = _snapshot(session["id"])

    response = client.patch(
        f"/api/v2/copilot/sessions/{session['id']}/phase",
        json={"phase": 4, "revision": session["revision"] + 1,
              "interests": [_interest("足球")]})

    assert response.status_code == 409
    assert response.get_json()["error"] == CONFLICT_MESSAGE
    assert _snapshot(session["id"]) == before


def test_stale_calibration_409_leaves_db_unchanged(client, qdb):
    login_as(client, qdb)
    session = _ready_session(qdb)
    before = _snapshot(session["id"])

    response = client.patch(
        f"/api/v2/copilot/sessions/{session['id']}/career-calibration",
        json={"revision": session["revision"] + 1,
              "careerInterests": "改变后的职业兴趣"})

    assert response.status_code == 409
    assert response.get_json()["error"] == CONFLICT_MESSAGE
    assert _snapshot(session["id"]) == before


def test_stale_interest_draft_409_leaves_db_unchanged(client, qdb):
    login_as(client, qdb)
    session = _ready_session(qdb)
    before = _snapshot(session["id"])

    response = client.patch(
        f"/api/v2/copilot/sessions/{session['id']}/interest-draft",
        json={"revision": session["revision"] + 1,
              "interests": [_interest("足球")]})

    assert response.status_code == 409
    assert response.get_json()["error"] == CONFLICT_MESSAGE
    assert _snapshot(session["id"]) == before


def test_stale_upload_source_409_leaves_db_unchanged(client, qdb):
    login_as(client, qdb)
    session = _ready_session(qdb)
    before = _snapshot(session["id"])

    response = client.post(
        f"/api/v2/copilot/sessions/{session['id']}/sources",
        data={
            "revision": str(session["revision"] + 1),
            "kind": "MEETING",
            "file": (io.BytesIO("新的会议文字稿".encode("utf-8")), "new.txt"),
        },
        content_type="multipart/form-data")

    assert response.status_code == 409
    assert response.get_json()["error"] == CONFLICT_MESSAGE
    assert _snapshot(session["id"]) == before


def test_stale_y4_calibrate_409_leaves_db_unchanged(client, qdb):
    login_as(client, qdb)
    session = _ready_session(qdb)
    before = _snapshot(session["id"])

    response = client.post(
        f"/api/v2/copilot/sessions/{session['id']}/y4-calibrate",
        json={"revision": session["revision"] + 1})

    assert response.status_code == 409
    assert response.get_json()["error"] == CONFLICT_MESSAGE
    assert _snapshot(session["id"]) == before


@pytest.mark.parametrize("method,path,payload", [
    ("post", "supplement", {}),
    ("post", "next-steps", {}),
    ("post", "projects", {}),
    ("patch", "projects", {"items": []}),
    ("post", "report-prepare", {}),
])
def test_stale_job_dispatch_409_leaves_db_unchanged(
        client, qdb, method, path, payload):
    login_as(client, qdb)
    session = _ready_session(qdb)
    before = _snapshot(session["id"])
    url = f"/api/v2/copilot/sessions/{session['id']}/{path}"
    body = {"revision": session["revision"] + 1, **payload}

    response = (client.post(url, json=body) if method == "post"
                else client.patch(url, json=body))

    assert response.status_code == 409
    assert response.get_json()["error"] == CONFLICT_MESSAGE
    assert _snapshot(session["id"]) == before


# ---------------------------------------------------------------------------
# 纯导航 / 内容写入
# ---------------------------------------------------------------------------
def test_phase_only_patch_keeps_revision(client, qdb):
    login_as(client, qdb)
    session = _ready_session(qdb)

    response = client.patch(
        f"/api/v2/copilot/sessions/{session['id']}/phase",
        json={"phase": 4, "revision": session["revision"]})

    assert response.status_code == 200
    data = response.get_json()
    assert data["revision"] == session["revision"]
    assert data["result"]["phase"] == 4
    current = store.get_session(session["id"])
    assert current["revision"] == session["revision"]
    assert current["phase"] == 4


def test_phase_only_last_phase_sets_review_without_bump(client, qdb):
    login_as(client, qdb)
    session = qdb.session(phase=5)

    response = client.patch(
        f"/api/v2/copilot/sessions/{session['id']}/phase",
        json={"phase": 6, "revision": session["revision"]})

    assert response.status_code == 200
    assert response.get_json()["revision"] == session["revision"]
    current = store.get_session(session["id"])
    assert current["revision"] == session["revision"]
    assert current["phase"] == 6
    assert current["status"] == "REVIEW"


def test_phase_content_patch_bumps_revision(client, qdb):
    login_as(client, qdb)
    session = _ready_session(qdb)

    response = client.patch(
        f"/api/v2/copilot/sessions/{session['id']}/phase",
        json={"phase": 4, "revision": session["revision"],
              "interests": [_interest("足球")]})

    assert response.status_code == 200
    assert response.get_json()["revision"] == session["revision"] + 1
    current = store.get_session(session["id"])
    assert current["revision"] == session["revision"] + 1
    assert current["interests"][0]["label"] == "足球"


def test_claim_revision_is_compare_and_swap(qdb):
    session = qdb.session()

    with pytest.raises(store.RevisionConflict, match=CONFLICT_MESSAGE):
        store.claim_revision(session["id"], session["revision"] + 1,
                             qdb.alice_id, "test")
    assert store.get_session(session["id"])["revision"] == session["revision"]

    revision = store.claim_revision(
        session["id"], session["revision"], qdb.alice_id, "test")
    assert revision == session["revision"] + 1


# ---------------------------------------------------------------------------
# 作业：生成期间 revision 变化则不落任何数据
# ---------------------------------------------------------------------------
def test_stale_supplement_job_writes_nothing(client, qdb, monkeypatch):
    login_as(client, qdb)
    session = _ready_session(qdb)
    monkeypatch.setattr(copilot, "call_model", lambda _prompt: {
        "newInterests": [{
            "label": "足球", "topicType": "interest",
            "evidence": "喜欢足球", "preferenceScore": 2,
            "competenceScore": 1,
        }],
        "scoreConflicts": [], "questions": [], "y4Validation": [],
    })
    _stale_launcher(monkeypatch, qdb)
    before = _content_snapshot(session["id"])

    response = client.post(
        f"/api/v2/copilot/sessions/{session['id']}/supplement",
        json={"revision": session["revision"]})

    assert response.status_code == 200
    job = client.get(
        f"/api/v2/copilot/jobs/{response.get_json()['jobId']}").get_json()
    assert job["status"] == "error"
    assert job["message"] == STALE_MESSAGE
    assert _content_snapshot(session["id"]) == before


def test_stale_next_steps_job_writes_nothing(client, qdb, monkeypatch):
    login_as(client, qdb)
    session = _ready_session(qdb)
    summary = ("本次会谈围绕学生的篮球训练与观赛兴趣展开，顾问记录了持续投入和明确偏好。"
               "后续会通过小范围实践继续观察这些线索，并把假设放回真实活动中验证。")
    monkeypatch.setattr(copilot, "call_model", lambda _prompt: {"summary": summary})
    _stale_launcher(monkeypatch, qdb)
    before = _content_snapshot(session["id"])

    response = client.post(
        f"/api/v2/copilot/sessions/{session['id']}/next-steps",
        json={"revision": session["revision"]})

    assert response.status_code == 200
    job = client.get(
        f"/api/v2/copilot/jobs/{response.get_json()['jobId']}").get_json()
    assert job["status"] == "error"
    assert job["message"] == STALE_MESSAGE
    assert _content_snapshot(session["id"]) == before


def test_stale_projects_generate_job_writes_nothing(client, qdb, monkeypatch):
    login_as(client, qdb)
    session = _ready_session(qdb)
    monkeypatch.setattr(copilot, "call_model", lambda _prompt: {
        "recommendations": [_project_row(1, "i1"), _project_row(2, "i1")],
    })
    _stale_launcher(monkeypatch, qdb)
    before = _content_snapshot(session["id"])

    response = client.post(
        f"/api/v2/copilot/sessions/{session['id']}/projects",
        json={"revision": session["revision"]})

    assert response.status_code == 200
    job = client.get(
        f"/api/v2/copilot/jobs/{response.get_json()['jobId']}").get_json()
    assert job["status"] == "error"
    assert job["message"] == STALE_MESSAGE
    assert _content_snapshot(session["id"]) == before


def test_stale_projects_review_job_writes_nothing(client, qdb, monkeypatch):
    login_as(client, qdb)
    session = _ready_session(qdb)
    monkeypatch.setattr(copilot, "call_model", lambda _prompt: {
        "recommendations": [_project_row(1, "i1"), _project_row(2, "i1")],
    })
    batch = copilot.generate_projects(session["id"])
    _stale_launcher(monkeypatch, qdb)
    before = _content_snapshot(session["id"])

    response = client.patch(
        f"/api/v2/copilot/sessions/{session['id']}/projects",
        json={"revision": session["revision"], "items": batch["items"]})

    assert response.status_code == 200
    job = client.get(
        f"/api/v2/copilot/jobs/{response.get_json()['jobId']}").get_json()
    assert job["status"] == "error"
    assert job["message"] == STALE_MESSAGE
    assert _content_snapshot(session["id"]) == before


def test_stale_report_prepare_job_writes_nothing(client, qdb, monkeypatch):
    login_as(client, qdb)
    session = _ready_session(qdb)
    monkeypatch.setattr(copilot_report, "_run_quadrant", _fake_quadrant)
    _stale_launcher(monkeypatch, qdb)
    before = _content_snapshot(session["id"])

    response = client.post(
        f"/api/v2/copilot/sessions/{session['id']}/report-prepare",
        json={"revision": session["revision"]})

    assert response.status_code == 200
    job = client.get(
        f"/api/v2/copilot/jobs/{response.get_json()['jobId']}").get_json()
    assert job["status"] == "error"
    assert job["message"] == STALE_MESSAGE
    assert _content_snapshot(session["id"]) == before


def test_inline_supplement_job_succeeds_and_bumps(client, qdb, monkeypatch):
    login_as(client, qdb)
    session = _ready_session(qdb)
    monkeypatch.setattr(copilot, "call_model", lambda _prompt: {
        "newInterests": [], "scoreConflicts": [], "questions": [],
        "y4Validation": [],
    })
    _inline_jobs(monkeypatch)

    response = client.post(
        f"/api/v2/copilot/sessions/{session['id']}/supplement",
        json={"revision": session["revision"]})

    assert response.status_code == 200
    job = client.get(
        f"/api/v2/copilot/jobs/{response.get_json()['jobId']}").get_json()
    assert job["status"] == "done"
    assert job["revision"] == session["revision"] + 1
    assert store.get_session(session["id"])["revision"] == session["revision"] + 1
