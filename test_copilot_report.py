"""Copilot 2.0 报告流测试（handoff/确认/PDF 双检，LLM 打桩）。"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import db as _db
import growth_talk_store as store
from growth_talk import analysis, copilot_report


class ReportDB:
    def __init__(self, engine):
        self.engine = engine
        self.student_id = None
        self.advisor_id = None

    def seed(self):
        with Session(self.engine) as sess:
            user = _db.User(username="advisor", password_hash="x",
                            role="advisor", advisor_name="Mine")
            student = _db.Student(student_code="Y4-9101", name="林同学",
                                  grade="10", advisor_name="Mine")
            sess.add_all([user, student])
            sess.commit()
            self.student_id, self.advisor_id = student.id, user.id

    def session(self, *, note="每周训练", evidence="每周训练篮球"):
        session, _ = store.create_session(self.student_id, self.advisor_id)
        source = store.create_source(
            self.student_id, "GROWTH_TALK", "MEETING", "会谈纪要",
            "学生每周训练篮球，非常喜欢投篮，也喜欢看比赛录像。",
            purpose="MEETING",
        )
        store.update_session_fields(
            session["id"], meeting_source_id=source["id"], phase=6,
            script={"nextSummary": "本次会谈围绕篮球训练与比赛观察展开，"
                                  "后续会继续设计、观察和验证这些线索。"})
        supplement = store.create_supplement(session["id"], source["id"])
        store.replace_session_interests(session["id"], [
            {
                "id": "i1", "label": "篮球", "topicType": "interest",
                "preferenceScore": 3, "competenceScore": 2,
                "note": note, "evidence": evidence,
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
        return store.get_session(session["id"]), source


@pytest.fixture()
def qdb(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'copilot_report.db'}")

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
    helper = ReportDB(engine)
    helper.seed()
    yield helper
    engine.dispose()


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


def test_handoff_idempotent_and_materializes_evidence(qdb):
    session, _source = qdb.session()
    first = copilot_report.handoff_report(session["id"])
    second = copilot_report.handoff_report(session["id"])

    assert first["runId"] == second["runId"]
    assert first["revision"] == second["revision"]
    full = store.get_run_full(first["runId"])
    assert len(full["interests"]) == 3
    basketball = next(
        item for item in full["interests"] if item["label"] == "篮球")
    assert basketball["status"] == "CONFIRMED"
    assert basketball["evidence"] == "每周训练篮球；顾问 Note：每周训练"
    current = store.get_session(session["id"])
    assert current["phase"] == 6
    assert current["status"] == "REVIEW"
    assert current["script"]["reportInputFingerprint"]


def test_handoff_renamed_interest_reuses_run_without_duplicates(qdb):
    session, _source = qdb.session()
    first = copilot_report.handoff_report(session["id"])
    store.replace_session_interests(session["id"], [
        {
            "id": "i1", "label": "篮球训练", "topicType": "interest",
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
    second = copilot_report.handoff_report(session["id"])

    assert first["runId"] == second["runId"]
    full = store.get_run_full(first["runId"])
    labels = [item["label"] for item in full["interests"]]
    assert len(labels) == 3
    assert "篮球训练" in labels and "篮球" not in labels


def test_prepare_returns_draft_only_when_grade_missing(qdb):
    session, _source = qdb.session()
    with Session(qdb.engine) as sess:
        student = sess.get(_db.Student, qdb.student_id)
        student.grade = ""
        sess.commit()

    out = copilot_report.prepare_report(
        session["id"], store.get_session(session["id"])["revision"])

    assert out["preview"] is None
    assert any(item["key"] == "grade" for item in out["draft"]["missing"])


def test_prepare_and_confirm_idempotent(qdb, monkeypatch):
    monkeypatch.setattr(copilot_report, "_run_quadrant", _fake_quadrant)
    session, _source = qdb.session()
    prepared = copilot_report.prepare_report(
        session["id"], store.get_session(session["id"])["revision"])

    assert prepared["preview"]
    assert prepared["runId"]
    assert prepared["revision"] == store.get_session(session["id"])["revision"]
    assert not [
        item for item in prepared["draft"]["missing"] if item["required"]
    ]

    kwargs = {
        "revision": prepared["revision"],
        "fingerprint": prepared["preview"]["fingerprint"],
        "suggestion_ids": [],
        "confirmed_by": "Mine",
    }
    first, status1 = copilot_report.confirm_session_report(session["id"], **kwargs)
    second, status2 = copilot_report.confirm_session_report(session["id"], **kwargs)

    assert (status1, status2) == (201, 200)
    assert first["id"] == second["id"]
    current = store.get_session(session["id"])
    assert current["status"] == "COMPLETED"
    assert current["completed_at"]


def test_report_pdf_fresh_rejects_stale_fingerprint(qdb, monkeypatch):
    monkeypatch.setattr(copilot_report, "_run_quadrant", _fake_quadrant)
    session, _source = qdb.session()
    prepared = copilot_report.prepare_report(
        session["id"], store.get_session(session["id"])["revision"])

    copilot_report.assert_report_pdf_fresh(
        session["id"], prepared["revision"], prepared["preview"]["fingerprint"])
    with pytest.raises(store.RevisionConflict, match="重新预览再下载"):
        copilot_report.assert_report_pdf_fresh(
            session["id"], prepared["revision"], "stale-fingerprint")
    with pytest.raises(store.RevisionConflict, match="重新进入报告页"):
        copilot_report.assert_report_pdf_fresh(
            session["id"], prepared["revision"] + 1,
            prepared["preview"]["fingerprint"])
