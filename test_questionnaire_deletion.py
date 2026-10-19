"""问卷任务永久删除（assignment 级）的 store / API 契约测试。

运行在 ``tmp_path`` 下的独立 SQLite 上，绝不触碰 ``data/y4_students.db``。
"""
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

import app_utils
import db as _db
import questionnaire_store as qs


# ---------------------------------------------------------------------------
# 临时数据库
# ---------------------------------------------------------------------------
class QDB:
    """tmp SQLite 上的最小题库/学生/任务数据工厂。"""

    def __init__(self, engine):
        self.engine = engine
        self.student_id = None
        self.questionnaire_id = None

    def seed(self):
        with Session(self.engine) as sess:
            student = _db.Student(student_code="Y4-9001", name="测试学生",
                                  advisor_name="Mine")
            questionnaire = qs.Questionnaire(
                code="Q-TEST-01", title="测试问卷",
                schema_json='{"questions": [{"id": "q1", "type": "single"}]}')
            sess.add_all([student, questionnaire])
            sess.flush()
            sess.add(qs.StudentAccount(student_id=student.id, username="y4-9001",
                                       password_hash="x"))
            sess.commit()
            self.student_id = student.id
            self.questionnaire_id = questionnaire.id

    def make_assignment(self, status="pending", token=False, response=False,
                        draft=False, advisor_name=None):
        with Session(self.engine) as sess:
            if advisor_name is not None:
                student = sess.get(_db.Student, self.student_id)
                student.advisor_name = advisor_name
            assignment = qs.Assignment(
                student_id=self.student_id, questionnaire_id=self.questionnaire_id,
                status=status, source="manual", delivery="link")
            sess.add(assignment)
            sess.flush()
            aid = assignment.id
            if token:
                sess.add(qs.AssignmentToken(
                    assignment_id=aid,
                    token=hashlib.sha256(f"token-{aid}".encode()).hexdigest(),
                    expires_at=datetime.utcnow() + timedelta(days=7)))
            if response:
                sess.add(qs.Response(
                    assignment_id=aid, student_id=self.student_id,
                    questionnaire_id=self.questionnaire_id,
                    answers_json='{"q1": "1"}', submitted_via="link"))
            if draft:
                sess.add(qs.ResponseDraft(assignment_id=aid,
                                          answers_json='{"q1": "2"}'))
            sess.commit()
            return aid

    def child_count(self, model, aid):
        with Session(self.engine) as sess:
            return int(sess.execute(
                select(func.count()).select_from(model)
                .where(model.assignment_id == aid)).scalar() or 0)

    def questionnaire_count(self):
        with Session(self.engine) as sess:
            return int(sess.execute(
                select(func.count()).select_from(qs.Questionnaire)).scalar() or 0)

    def student_account_count(self):
        with Session(self.engine) as sess:
            return int(sess.execute(
                select(func.count()).select_from(qs.StudentAccount)).scalar() or 0)


@pytest.fixture()
def qdb(tmp_path, monkeypatch):
    path = tmp_path / "questionnaires_test.db"
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables = [
        _db.User.__table__,
        _db.Student.__table__,
        qs.Questionnaire.__table__,
        qs.Assignment.__table__,
        qs.AssignmentToken.__table__,
        qs.Response.__table__,
        qs.ResponseDraft.__table__,
        qs.StudentAccount.__table__,
    ]
    _db.Base.metadata.create_all(engine, tables=tables)
    qs.ensure_indexes(bind=engine)

    monkeypatch.setattr(qs, "engine", engine)
    monkeypatch.setattr(_db, "engine", engine)

    helper = QDB(engine)
    helper.seed()
    yield helper
    engine.dispose()


# ---------------------------------------------------------------------------
# store：delete_assignment
# ---------------------------------------------------------------------------
def test_delete_submitted_assignment_removes_only_its_data(qdb):
    aid = qdb.make_assignment(status="submitted", token=True, response=True, draft=True)
    other_id = qdb.make_assignment(status="sent", token=True, response=False, draft=True)

    assert qs.delete_assignment(aid) is True

    assert qs.get_assignment(aid) is None
    assert qs.get_response(aid) is None
    assert qs.get_draft(aid)["answers"] == {}
    assert qdb.child_count(qs.AssignmentToken, aid) == 0
    assert qdb.child_count(qs.Response, aid) == 0
    assert qdb.child_count(qs.ResponseDraft, aid) == 0

    # 无关任务、题库模板、共享学生账号都不受影响
    assert qs.get_assignment(other_id) is not None
    assert qdb.child_count(qs.AssignmentToken, other_id) == 1
    assert qdb.child_count(qs.ResponseDraft, other_id) == 1
    assert qdb.questionnaire_count() == 1
    assert qdb.student_account_count() == 1


def test_delete_missing_assignment_returns_false(qdb):
    assert qs.delete_assignment(999999) is False


@pytest.mark.parametrize("status", qs.STATUSES)
def test_delete_assignment_works_for_every_status(qdb, status):
    aid = qdb.make_assignment(status=status, token=True, response=True, draft=True)

    assert qs.delete_assignment(aid) is True
    assert qs.get_assignment(aid) is None
    assert qdb.child_count(qs.AssignmentToken, aid) == 0
    assert qdb.child_count(qs.Response, aid) == 0
    assert qdb.child_count(qs.ResponseDraft, aid) == 0
