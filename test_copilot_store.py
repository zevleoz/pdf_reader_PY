"""Copilot 2.0 store 层契约测试（tmp SQLite，不触碰生产库）。"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import db as _db
import growth_talk_store as store


class CopilotDB:
    def __init__(self, engine):
        self.engine = engine
        self.student_id = None
        self.advisor_id = None
        self.other_advisor_id = None

    def insert_users(self):
        with Session(self.engine) as sess:
            mine = _db.User(username="advisor-a", password_hash="x", role="advisor",
                            advisor_name="Mine")
            other = _db.User(username="advisor-b", password_hash="x", role="advisor",
                             advisor_name="Other")
            sess.add_all([mine, other])
            sess.commit()
            self.advisor_id = mine.id
            self.other_advisor_id = other.id

    def insert_student(self, name="测试学生", grade="10"):
        with Session(self.engine) as sess:
            row = _db.Student(student_code="Y4-9001", name=name, grade=grade,
                              advisor_name="Mine")
            sess.add(row)
            sess.commit()
            self.student_id = row.id
        return self.student_id


@pytest.fixture()
def qdb(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'copilot_test.db'}")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables = [
        _db.Student.__table__,
        _db.User.__table__,
        _db.Report.__table__,
        store.GtSource.__table__,
        store.GtRun.__table__,
        store.GtReport.__table__,
        store.CopilotSession.__table__,
        store.CopilotPhaseEvent.__table__,
        store.CopilotCareerCalibration.__table__,
        store.CopilotInterestNote.__table__,
        store.CopilotTranscriptSupplement.__table__,
        store.CopilotChatMessage.__table__,
    ]
    _db.Base.metadata.create_all(engine, tables=tables)
    monkeypatch.setattr(_db, "engine", engine)

    helper = CopilotDB(engine)
    helper.insert_users()
    helper.insert_student()
    yield helper
    engine.dispose()


def _session(qdb, entry_mode="guided"):
    return store.create_session(qdb.student_id, qdb.advisor_id, entry_mode)


def test_create_session_idempotent_per_student(qdb):
    s1, created1 = _session(qdb, "guided")
    s2, created2 = _session(qdb, "direct")
    assert created1 is True and created2 is False and s1["id"] == s2["id"]
    assert s1["phase"] == 0
    # 每名学生只有一条 session：另一位顾问拿到同一条，不再各建一份。
    other, created3 = store.create_session(qdb.student_id, qdb.other_advisor_id)
    assert created3 is False and other["id"] == s1["id"]
    assert other["advisor_id"] == qdb.advisor_id
    assert len(store.list_sessions(qdb.student_id)) == 1


def test_direct_entry_starts_at_phase_5(qdb):
    session, _ = _session(qdb, "direct")
    assert session["phase"] == 5
    assert session["script"]["entryMode"] == "direct"
    assert session["script"]["goal"] == (
        "一起识别兴趣与擅长，为后续升学探索寻找既有目标又有真实兴趣的方向。"
    )
    assert [event["action"] for event in session["events"]] == ["created"]


def test_bump_session_revision_conflict_message(qdb):
    session, _ = _session(qdb)
    with pytest.raises(store.RevisionConflict,
                       match="会谈已更新，请保留草稿并刷新确认"):
        store.bump_session_revision(session["id"], 999, qdb.advisor_id, "phase_saved")
    revision = store.bump_session_revision(session["id"], 1, qdb.advisor_id,
                                           "phase_saved", phase=3)
    assert revision == 2
    refreshed = store.get_session(session["id"])
    assert refreshed["phase"] == 3
    assert refreshed["events"][0]["action"] == "phase_saved"
    assert refreshed["events"][0]["phase"] == 3


def test_bump_session_revision_missing_raises_not_found(qdb):
    with pytest.raises(store.NotFoundError, match="会谈不存在"):
        store.bump_session_revision(9999, 1, qdb.advisor_id, "phase_saved")


def test_replace_interests_rebuilds_notes(qdb):
    session, _ = _session(qdb)
    store.replace_session_interests(session["id"], [{
        "id": "i1", "label": "篮球", "topicType": "interest",
        "preferenceScore": 3, "competenceScore": 2, "note": "每周训练",
        "evidence": "校队训练两年",
    }])
    refreshed = store.get_session(session["id"])
    assert refreshed["interests"][0]["label"] == "篮球"
    assert refreshed["notes"] == [{
        "interest_id": "i1", "note": "每周训练",
        "updated_at": refreshed["notes"][0]["updated_at"],
    }]

    store.replace_session_interests(session["id"], [{
        "id": "i1", "label": "篮球", "topicType": "interest", "note": "",
        "evidence": "校队训练两年",
    }])
    assert store.get_session(session["id"])["notes"] == []


def test_calibration_upsert_and_supplement_lifecycle(qdb):
    session, _ = _session(qdb)
    store.upsert_calibration(session["id"], "职业兴趣", "能力倾向", "价值偏好", "备注")
    calibration = store.get_session(session["id"])["calibration"]
    assert calibration["careerInterests"] == "职业兴趣"
    store.upsert_calibration(session["id"], "职业兴趣2", "能力倾向", "价值偏好", "备注")

    source = store.create_source(qdb.student_id, "MEETING", "MEETING", "会谈", "正文")
    first = store.create_supplement(session["id"], source["id"])
    second = store.create_supplement(session["id"], source["id"])
    assert first["status"] == "PENDING_REVIEW"
    latest = store.latest_supplement(session["id"])
    assert latest["id"] == second["id"]
    store.save_supplement_analysis(second["id"], {"analysisVersion": "v1"}, "REVIEWED")
    latest = store.latest_supplement(session["id"])
    assert latest["analysis"] == {"analysisVersion": "v1"}
    assert latest["status"] == "REVIEWED"


def test_chat_caps(qdb):
    chat_ids = []
    for index in range(21):
        chat_id = store.create_chat(qdb.student_id, qdb.advisor_id)
        store.add_chat_turn(chat_id, f"问题{index}",
                            {"answer": f"回答{index}", "evidence": []}, "ANSWERED",
                            student_id=qdb.student_id)
        chat_ids.append(chat_id)

    listed = store.list_chats(qdb.student_id)
    assert len(listed) == 20
    assert chat_ids[0] not in {chat["chatId"] for chat in listed}

    latest_id = chat_ids[-1]
    for index in range(19):
        store.add_chat_turn(latest_id, f"追加{index}",
                            {"answer": "回答", "evidence": []}, "ANSWERED")
    with pytest.raises(ValueError, match="对话轮数已达上限"):
        store.add_chat_turn(latest_id, "超限", {"answer": "回答", "evidence": []},
                            "ANSWERED")

    chat = store.get_chat(latest_id)
    assert chat["turnCount"] == 20
    assert chat["turns"][0]["question"] == "问题20"
    assert len(chat["turns"]) == 20
