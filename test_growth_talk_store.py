"""Growth Talk store 层契约测试（tmp SQLite，不触碰 data/y4_students.db）。"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

import db as _db
import growth_talk_store as store


class GTDB:
    def __init__(self, engine):
        self.engine = engine
        self.student_id = None

    def insert_student(self, name="测试学生", grade="10"):
        with Session(self.engine) as sess:
            row = _db.Student(student_code="Y4-9001", name=name, grade=grade,
                              advisor_name="Mine")
            sess.add(row)
            sess.commit()
            self.student_id = row.id
        return self.student_id

    def audit_actions(self):
        with Session(self.engine) as sess:
            return [row.action for row in sess.execute(select(store.AuditLog)).scalars()]


@pytest.fixture()
def qdb(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'growth_talk_test.db'}")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables = [
        _db.Student.__table__,
        store.GtSource.__table__,
        store.GtRun.__table__,
        store.GtUnderstanding.__table__,
        store.GtInterest.__table__,
        store.GtQuadrant.__table__,
        store.GtSuggestion.__table__,
        store.GtReport.__table__,
        store.ExternalIdentity.__table__,
        store.AuditLog.__table__,
        store.CrmDeliveryReceipt.__table__,
        store.CrmAppointment.__table__,
    ]
    _db.Base.metadata.create_all(engine, tables=tables)
    monkeypatch.setattr(_db, "engine", engine)

    helper = GTDB(engine)
    helper.insert_student()
    yield helper
    engine.dispose()


def _source(sid):
    return store.create_source(sid, "GROWTH_TALK", "GROWTH_TALK", "会谈记录", "正文")


def test_create_run_increments_version_per_student(qdb):
    src = _source(qdb.student_id)
    r1 = store.create_run(qdb.student_id, src["id"])
    r2 = store.create_run(qdb.student_id, src["id"])
    assert (r1["version"], r2["version"]) == (1, 2)
    assert r1["status"] == "RUNNING"
    assert r1["revision"] == 1


def test_bump_run_revision_conflict_raises(qdb):
    src = _source(qdb.student_id)
    run = store.create_run(qdb.student_id, src["id"])
    assert store.bump_run_revision(run["id"], 1) == 2
    with pytest.raises(store.RevisionConflict):
        store.bump_run_revision(run["id"], 999)


def test_create_report_unique_version_and_confirms_children(qdb):
    src = _source(qdb.student_id)
    run = store.create_run(qdb.student_id, src["id"])
    store.save_understanding(run["id"], "摘要", "[]", "[]", "deepseek-chat")
    store.save_quadrant(run["id"], "[]", "说明", "deepseek-chat")

    first = store.create_report(qdb.student_id, run["id"], json.dumps({"v": 1}), "顾问A")
    second = store.create_report(qdb.student_id, run["id"], json.dumps({"v": 2}), "顾问A")

    assert first["version"] == 1
    assert second["version"] == 2
    full = store.get_run_full(run["id"])
    assert full["understanding"]["status"] == "CONFIRMED"
    assert full["quadrant"]["status"] == "CONFIRMED"
    assert qdb.audit_actions().count("report_confirmed") == 2


def test_delete_referenced_source_blocked(qdb):
    src = _source(qdb.student_id)
    store.create_run(qdb.student_id, src["id"])
    with pytest.raises(store.RevisionConflict):
        store.delete_source(src["id"])


def test_delete_unreferenced_source_allowed(qdb):
    src = _source(qdb.student_id)
    store.delete_source(src["id"])
    assert store.get_source(src["id"]) is None


def test_delete_superseded_sources_keeps_latest(qdb):
    old = _source(qdb.student_id)
    new = _source(qdb.student_id)
    store.delete_superseded_sources(qdb.student_id, "GROWTH_TALK")
    assert store.get_source(old["id"]) is None
    assert store.get_source(new["id"]) is not None


def test_external_identity_unique_per_system(qdb):
    store.upsert_external_identity(qdb.student_id, "yuguo", "stu-1")
    assert store.find_student_by_external("yuguo", "stu-1") == qdb.student_id
    assert store.find_student_by_external("crm", "stu-1") is None
    # 幂等 upsert 不产生重复行
    store.upsert_external_identity(qdb.student_id, "yuguo", "stu-1")
    assert store.find_student_by_external("yuguo", "stu-1") == qdb.student_id


def test_replace_interests_and_mark_outputs_stale(qdb):
    src = _source(qdb.student_id)
    run = store.create_run(qdb.student_id, src["id"])
    store.replace_interests(run["id"], [
        {"label": "篮球", "evidence": "每周训练", "evidenceStrength": "强",
         "preferenceScore": 3, "competenceScore": 2},
    ])
    store.save_quadrant(run["id"], "[]", "说明", "m")
    store.replace_suggestions(run["id"], [{"title": "t", "introduction": "i",
                                           "growthValue": "g"}])
    full = store.get_run_full(run["id"])
    assert full["interests"][0]["preference_score"] == 3
    assert full["interests"][0]["evidence_strength"] == "强"
    assert len(full["suggestions"]) == 1

    store.mark_outputs_stale(run["id"])
    full = store.get_run_full(run["id"])
    assert full["quadrant"]["status"] == "STALE"
    assert full["suggestions"][0]["status"] == "STALE"


def test_confirm_interests_rejects_bad_score(qdb):
    src = _source(qdb.student_id)
    run = store.create_run(qdb.student_id, src["id"])
    store.replace_interests(run["id"], [{"label": "篮球", "evidence": "训练"}])
    iid = store.get_run_full(run["id"])["interests"][0]["id"]
    with pytest.raises(ValueError, match="分值必须是 0 到 3 的整数"):
        store.confirm_interests(run["id"], [{"interestId": iid, "preferenceScore": 4,
                                            "competenceScore": 1}], "顾问")
