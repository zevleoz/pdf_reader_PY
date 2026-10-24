"""A3 数据修复测试：手动建档隔离、会议时间归一、Activity Hub topicType 映射。"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import jsonschema
from sqlalchemy import select
from sqlalchemy.orm import Session

import db as _db
import growth_talk_store as store
from growth_talk import copilot_report

from test_copilot_routes import (  # noqa: F401
    _fake_quadrant, _inline_jobs, _ready_session, client, login_as, qdb,
)

ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "docs" / "integrations" / "first-touch-activity-hub" / "api-profile.schema.json"
NORMALIZER = ROOT / "scripts" / "normalize_meeting_at.py"


# ---------------------------------------------------------------------------
# F5：会议时间统一存 UTC
# ---------------------------------------------------------------------------
def test_naive_meeting_at_is_stored_as_utc_and_reported_local(
        client, qdb, monkeypatch):
    _inline_jobs(monkeypatch)
    login_as(client, qdb)
    session = _ready_session(qdb)

    patched = client.patch(
        f"/api/v2/copilot/sessions/{session['id']}/phase",
        json={"phase": 2, "revision": session["revision"],
              "meetingAt": "2026-01-01T12:00"})
    assert patched.status_code == 200
    assert store.get_session(session["id"])["meeting_at"] == \
        "2026-01-01T04:00:00Z"

    monkeypatch.setattr(copilot_report, "_run_quadrant", _fake_quadrant)
    current = store.get_session(session["id"])
    prepared = client.post(
        f"/api/v2/copilot/sessions/{session['id']}/report-prepare",
        json={"revision": current["revision"]})
    assert prepared.status_code == 200

    body = client.get(
        f"/api/v2/copilot/jobs/{prepared.get_json()['jobId']}").get_json()
    result = body["result"]
    assert result["draft"]["meetingAt"] == "2026-01-01T04:00:00Z"
    assert "访谈日期：2026年1月1日 12:00" in result["preview"]["meetingSummary"]


def test_default_meeting_at_rounds_down_to_quarter_hour(client, qdb):
    login_as(client, qdb)
    qdb.add_y4()

    response = client.post(
        f"/api/v2/students/{qdb.student_id}/copilot/sessions", json={})

    assert response.status_code == 201
    value = response.get_json()["session"]["meeting_at"]
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    assert value.endswith("Z")
    assert parsed.minute % 15 == 0
    assert parsed.second == 0


def _meeting_values(db_path: Path) -> list:
    conn = sqlite3.connect(db_path)
    try:
        return [row[0] for row in conn.execute(
            "SELECT meeting_at FROM copilot_sessions ORDER BY id")]
    finally:
        conn.close()


def test_normalize_meeting_at_script_converts_once(tmp_path):
    db_path = tmp_path / "meeting.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE copilot_sessions (id INTEGER PRIMARY KEY, meeting_at TEXT)")
        conn.executemany(
            "INSERT INTO copilot_sessions (id, meeting_at) VALUES (?, ?)", [
                (1, "2026-10-23T15:23:33"),
                (2, "2026-10-24T03:00:00.000Z"),
                (3, "2026-10-24T11:00:00Z"),
                (4, None),
            ])
        conn.commit()
    finally:
        conn.close()

    dry = subprocess.run(
        [sys.executable, str(NORMALIZER), "--db", str(db_path)],
        capture_output=True, text=True)
    assert dry.returncode == 0, dry.stderr
    assert _meeting_values(db_path) == [
        "2026-10-23T15:23:33", "2026-10-24T03:00:00.000Z",
        "2026-10-24T11:00:00Z", None]

    applied = subprocess.run(
        [sys.executable, str(NORMALIZER), "--db", str(db_path), "--apply"],
        capture_output=True, text=True)
    assert applied.returncode == 0, applied.stderr
    expected = ["2026-10-23T15:23:33Z", "2026-10-24T03:00:00Z",
                "2026-10-24T11:00:00Z", None]
    assert _meeting_values(db_path) == expected

    again = subprocess.run(
        [sys.executable, str(NORMALIZER), "--db", str(db_path), "--apply"],
        capture_output=True, text=True)
    assert again.returncode == 0, again.stderr
    assert "无需改写" in again.stdout
    assert _meeting_values(db_path) == expected


# ---------------------------------------------------------------------------
# F6：Activity Hub topicType 映射
# ---------------------------------------------------------------------------
def _seed_confirmed_report(qdb, topic_types: list[str]) -> dict:
    source = store.create_source(
        qdb.student_id, "GROWTH_TALK", "GROWTH_TALK", "会谈纪要",
        "学生谈到了学科、兴趣与社交活动。", purpose="MEETING",
        file_name="meeting.txt")
    run = store.create_run(qdb.student_id, source["id"])
    labels = {"subject": "物理", "interest": "篮球", "social": "朋友聚会"}
    payload = {
        "schema": "first-touch.report.v1",
        "reportId": "r-a3",
        "student": {"name": "林同学", "grade": "10", "school": None},
        "career": {"careerInterests": "", "abilityTendencies": "",
                   "valuePreferences": ""},
        "interests": [
            {"id": f"i-{topic}", "label": labels[topic], "topicType": topic,
             "evidence": f"{labels[topic]}相关证据",
             "preferenceScore": 2, "competenceScore": 1}
            for topic in topic_types
        ],
    }
    return store.create_report(
        qdb.student_id, run["id"], "{}", "Alice",
        payload_builder=lambda _report_id, _version: json.dumps(
            payload, ensure_ascii=False))


def test_activity_hub_export_maps_topic_types_and_validates(client, qdb):
    login_as(client, qdb)
    report = _seed_confirmed_report(qdb, ["subject", "interest", "social"])

    response = client.get(
        f"/api/first-touch/reports/{report['id']}/activity-hub.json")
    assert response.status_code == 200
    profile = json.loads(response.get_data(as_text=True))

    items = profile["interestProfile"]["items"]
    assert len(items) == 3
    mapping = {item["label"]: (item["sourceType"], item["topicType"])
               for item in items}
    # schema 只允许 sourceType ∈ {interest, subject}、topicType ∈ {hobby, subject}，
    # 无法表达三种互异的输出；social 取最接近的 interest/hobby。
    assert mapping == {
        "物理": ("subject", "subject"),
        "篮球": ("interest", "hobby"),
        "朋友聚会": ("interest", "hobby"),
    }
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(profile, schema)
