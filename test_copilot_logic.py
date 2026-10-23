"""Copilot 2.0 纯逻辑测试（LLM 全部打桩）。"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import db as _db
import growth_talk_store as store
from growth_talk import copilot


class CopilotDB:
    def __init__(self, engine):
        self.engine = engine
        self.student_id = None
        self.advisor_id = None

    def seed(self):
        with Session(self.engine) as sess:
            user = _db.User(username="advisor", password_hash="x", role="advisor",
                            advisor_name="Mine")
            student = _db.Student(student_code="Y4-9001", name="林同学", grade="10",
                                  advisor_name="Mine")
            sess.add_all([user, student])
            sess.commit()
            self.student_id, self.advisor_id = student.id, user.id

    def meeting(self, content="学生每周训练篮球，非常喜欢投篮，也喜欢看比赛录像。"):
        session, _ = store.create_session(self.student_id, self.advisor_id)
        source = store.create_source(self.student_id, "MEETING", "MEETING", "会谈", content)
        store.update_session_fields(session["id"], meeting_source_id=source["id"])
        supplement = store.create_supplement(session["id"], source["id"])
        store.replace_session_interests(session["id"], [{
            "id": "i1", "label": "篮球", "topicType": "interest",
            "preferenceScore": 3, "competenceScore": 2,
            "note": "每周训练", "evidence": "每周训练篮球",
        }])
        store.save_supplement_analysis(supplement["id"], {
            "analysisVersion": "v1",
            "newInterests": [],
        }, "PENDING_REVIEW")
        return session, source, supplement


@pytest.fixture()
def qdb(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'copilot_logic.db'}")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    tables = [
        _db.Student.__table__, _db.User.__table__, _db.Report.__table__,
        store.GtSource.__table__, store.GtRun.__table__,
        store.GtUnderstanding.__table__, store.GtInterest.__table__,
        store.GtQuadrant.__table__, store.GtSuggestion.__table__,
        store.GtReport.__table__,
        store.CopilotSession.__table__, store.CopilotPhaseEvent.__table__,
        store.CopilotCareerCalibration.__table__, store.CopilotInterestNote.__table__,
        store.CopilotTranscriptSupplement.__table__, store.CopilotChatMessage.__table__,
    ]
    _db.Base.metadata.create_all(engine, tables=tables)
    monkeypatch.setattr(_db, "engine", engine)
    helper = CopilotDB(engine)
    helper.seed()
    yield helper
    engine.dispose()


def test_interest_drafts_reject_duplicate_label_case_insensitive():
    base = {"topicType": "interest", "preferenceScore": None,
            "competenceScore": None, "note": "", "evidence": ""}
    with pytest.raises(ValueError, match="不能重复"):
        copilot.validate_interest_drafts([
            {**base, "id": "a", "label": "Basketball"},
            {**base, "id": "b", "label": "basketball"},
        ])


def test_interest_drafts_score_and_length_rules():
    with pytest.raises(ValueError, match="0–3"):
        copilot.validate_interest_drafts([{
            "id": "a", "label": "篮球", "topicType": "interest",
            "preferenceScore": 4, "competenceScore": None, "note": "", "evidence": "",
        }])
    with pytest.raises(ValueError, match="备注或证据过长"):
        copilot.validate_interest_drafts([{
            "id": "a", "label": "篮球", "topicType": "interest",
            "preferenceScore": None, "competenceScore": None,
            "note": "长" * 2001, "evidence": "",
        }])


def test_merge_supplement_analysis_preserves_reserved_keys():
    existing = {"projectRecommendations": {"v": 1}, "newInterests": [1]}
    merged = copilot.merge_supplement_analysis(
        existing,
        {"projectRecommendations": {"v": 2}, "interestReview": {"x": 1}, "questions": ["q"]},
    )
    assert merged["projectRecommendations"] == {"v": 1}
    assert merged["newInterests"] == [1]
    assert "interestReview" not in merged
    assert merged["questions"] == ["q"]


def test_script_fields_limits():
    script = copilot.validate_script_fields({"goal": " 目标 ", "opening": ""})
    assert script["goal"] == "目标"
    assert script["closing"] == ""
    with pytest.raises(ValueError, match="文本格式或长度无效"):
        copilot.validate_script_fields({"goal": "长" * 3001})


def test_calibration_requires_y4():
    with pytest.raises(ValueError, match="还没有已确认的 Y4 报告"):
        copilot.generate_career_calibration({}, "")


def test_next_steps_rejects_forbidden_pattern(qdb, monkeypatch):
    session, _, _ = qdb.meeting()
    monkeypatch.setattr(
        copilot, "call_model",
        lambda _prompt: {"summary": "后续会围绕兴趣安排具体体验（活动：参加校队试训）并持续观察反馈。"},
    )
    with pytest.raises(ValueError, match="不应写出具体活动或路径"):
        copilot.generate_next_steps(session["id"])


def test_next_steps_saves_script(qdb, monkeypatch):
    session, _, _ = qdb.meeting()
    summary = "本次会谈围绕学生的篮球训练与观赛兴趣展开，顾问记录了持续投入和明确偏好。后续会通过小范围实践继续观察这些线索，并把假设放回真实活动中验证。"
    monkeypatch.setattr(copilot, "call_model", lambda _prompt: {"summary": summary})
    assert copilot.generate_next_steps(session["id"]) == summary
    assert store.get_session(session["id"])["script"]["nextSummary"] == summary


def _recommendation(title, quotes, refs=("i1",)):
    return {
        "title": title, "interestAnchor": "篮球训练中对投篮和比赛录像的兴趣",
        "interestRefs": list(refs), "evidenceQuotes": quotes,
        "fitType": "observation_research", "domains": ["体育"],
        "coreQuestion": "为什么投篮训练会带来持续投入？",
        "example": "记录一周训练中自己最投入的片段，并写下原因。",
        "journeySummary": "如果发现投入与命中率无关，可以继续观察反馈方式。",
        "whyThisProject": "会议原文显示学生持续训练并主动观看录像。",
        "minimumViableProject": "顾问需确认学生是否有可记录的训练场景。",
        "likelyOutputs": ["训练观察记录"], "expansionPath": [],
        "openQuestions": [],
    }


def test_projects_evidence_must_be_verbatim(qdb, monkeypatch):
    session, _, _ = qdb.meeting()
    monkeypatch.setattr(copilot, "call_model", lambda _prompt: {
        "recommendations": [
            _recommendation("投篮观察", ["每周训练篮球"]),
            _recommendation("战术记录", ["原文里没有这句话"]),
        ],
    })
    batch = copilot.generate_projects(session["id"])
    assert [item["status"] for item in batch["items"]] == ["draft", "needs_evidence"]
    assert batch["version"] == 1
    assert batch["sourceId"] == store.latest_supplement(session["id"])["source_id"]


def test_apply_project_edits_stale_fingerprint(qdb, monkeypatch):
    session, _, supplement = qdb.meeting()
    monkeypatch.setattr(copilot, "call_model", lambda _prompt: {
        "recommendations": [
            _recommendation("投篮观察", ["每周训练篮球"]),
            _recommendation("观赛记录", ["喜欢看比赛录像"]),
        ],
    })
    batch = copilot.generate_projects(session["id"])
    store.replace_session_interests(session["id"], [{
        "id": "i1", "label": "篮球", "topicType": "interest",
        "preferenceScore": 2, "competenceScore": 2, "note": "", "evidence": "每周训练篮球",
    }])
    with pytest.raises(store.RevisionConflict, match="会议资料或兴趣已变化"):
        copilot.apply_project_edits(session["id"], batch["items"], "顾问")


def test_quadrant_helpers():
    assert copilot.quadrant_tone(2, 2) == "strong"
    assert copilot.quadrant_tone(3, 0) == "explore"
    assert copilot.quadrant_tone(0, 2) == "capable"
    assert copilot.quadrant_tone(1, 1) == "quiet"
    assert copilot.three_level(None) is None
    assert copilot.three_level(3) == "高"
    assert copilot.three_level(2) == "中"
    assert copilot.three_level(0) == "低"
