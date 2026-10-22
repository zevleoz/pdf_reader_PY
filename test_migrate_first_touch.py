# -*- coding: utf-8 -*-
"""Task 12：first-touch 历史数据迁移脚本测试。

覆盖：
- preview：姓名+年级命中 → link；无命中 → create；CSV 列与内容正确；
- run：导入 Account/Student/SourceMaterial/Run/子表/Report/ExternalIdentity/AuditLog；
- 幂等：重复 run 不新增任何数据；
- 导入账号使用不可用随机密码（源 bcrypt 哈希与 werkzeug 不兼容）。
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

import db as _db  # noqa: E402
import growth_talk_store as store  # noqa: E402
import migrate_first_touch as mig  # noqa: E402


@pytest.fixture()
def mdb(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    _db.Base.metadata.create_all(engine, tables=[
        _db.User.__table__, _db.Student.__table__,
        store.GtSource.__table__, store.GtRun.__table__,
        store.GtUnderstanding.__table__, store.GtInterest.__table__,
        store.GtQuadrant.__table__, store.GtSuggestion.__table__,
        store.GtReport.__table__, store.ExternalIdentity.__table__,
        store.AuditLog.__table__,
    ])
    monkeypatch.setattr(_db, "engine", engine)
    with Session(engine) as sess:
        student = _db.Student(student_code="Y4-0001", name="张三",
                              grade="11年级", school="复旦附中")
        sess.add(student)
        sess.commit()
        local_id = student.id
    yield {"engine": engine, "local_id": local_id}
    engine.dispose()


def _write_export(export_dir: Path) -> None:
    export_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "Account.json": [{
            "id": "acc-1", "name": "王老师", "email": "wang@example.com",
            "passwordHash": "$2b$12$abcdefghijklmnopqrstuv",
            "role": "TEACHER", "active": True, "sessionVersion": 3,
            "createdAt": "2026-01-02T03:04:05.000Z",
        }],
        "Student.json": [
            {"id": "ft-1", "name": "张三", "grade": "11年级", "school": "复旦附中",
             "phone": "13800000000", "assignedTeacherId": "acc-1",
             "assignmentVersion": 2, "updatedAt": "2026-02-01T00:00:00.000Z"},
            {"id": "ft-2", "name": "李四", "grade": "10年级", "school": "上海中学",
             "assignedTeacherId": None, "assignmentVersion": 1,
             "updatedAt": "2026-02-02T00:00:00.000Z"},
        ],
        "SourceMaterial.json": [{
            "id": "src-1", "studentId": "ft-1", "type": "GROWTH_TALK",
            "purpose": "UNKNOWN", "sourceKind": "GROWTH_TALK",
            "title": "首次会谈", "content": "学生喜欢计算机",
            "createdAt": "2026-02-03T00:00:00.000Z",
        }],
        "GrowthTalkRun.json": [{
            "id": "run-1", "studentId": "ft-1", "sourceId": "src-1",
            "version": 1, "revision": 3, "status": "READY",
            "model": "deepseek-chat",
            "createdAt": "2026-02-03T01:00:00.000Z",
            "updatedAt": "2026-02-03T02:00:00.000Z",
        }],
        "MeetingUnderstanding.json": [{
            "id": "u-1", "runId": "run-1", "summary": "学生偏好计算机",
            "topics": "[\"专业方向\"]", "keywords": "[\"计算机\"]",
            "model": "deepseek-chat", "status": "CONFIRMED",
        }],
        "InterestEvidence.json": [{
            "id": "i-1", "runId": "run-1", "label": "计算机",
            "evidence": "长期自学编程", "preferenceScore": 3,
            "competenceScore": 2, "specialFocus": True,
            "status": "CONFIRMED", "confirmedBy": "王老师",
        }],
        "QuadrantAnalysis.json": [{
            "id": "q-1", "runId": "run-1", "points": "[]",
            "narrative": "兴趣集中在计算机", "status": "CONFIRMED",
        }],
        "ExplorationSuggestion.json": [{
            "id": "s-1", "runId": "run-1", "title": "参加编程营",
            "introduction": "系统学习", "growthValue": "验证兴趣",
            "status": "CONFIRMED",
        }],
        "GrowthTalkReport.json": [{
            "id": "rep-1", "studentId": "ft-1", "runId": "run-1",
            "version": 1, "status": "CONFIRMED",
            "payload": json.dumps({"schema": "first-touch.report.v1"},
                                  ensure_ascii=False),
            "confirmedAt": "2026-02-04T00:00:00.000Z", "confirmedBy": "王老师",
        }],
        "StudentExternalIdentity.json": [{
            "id": "ext-1", "studentId": "ft-1", "sourceSystem": "yuguo",
            "externalStudentId": "yg-9",
        }],
        "AuditLog.json": [{
            "id": "aud-1", "actorId": "acc-1", "studentId": "ft-1",
            "action": "report_confirmed", "details": "{}",
            "createdAt": "2026-02-04T00:00:01.000Z",
        }],
    }
    for name, rows in files.items():
        (export_dir / name).write_text(json.dumps(rows, ensure_ascii=False),
                                       encoding="utf-8")


def test_preview_links_match_and_creates_unmatched(mdb, tmp_path):
    export_dir = tmp_path / "export"
    _write_export(export_dir)
    out = tmp_path / "mapping.csv"

    rows = mig.preview(export_dir, out)

    by_ft = {row["ft_student_id"]: row for row in rows}
    assert by_ft["ft-1"]["y4_student_id"] == str(mdb["local_id"])
    assert by_ft["ft-1"]["y4_code"] == "Y4-0001"
    assert by_ft["ft-1"]["match_confidence"] == "high"
    assert by_ft["ft-1"]["action"] == "link"
    assert by_ft["ft-2"]["y4_student_id"] == ""
    assert by_ft["ft-2"]["match_confidence"] == "none"
    assert by_ft["ft-2"]["action"] == "create"

    with out.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == [
            "ft_student_id", "ft_name", "ft_grade", "y4_student_id",
            "y4_name", "y4_code", "match_confidence", "action",
        ]
        assert len(list(reader)) == 2


def test_run_imports_entities_and_is_idempotent(mdb, tmp_path):
    export_dir = tmp_path / "export"
    _write_export(export_dir)
    mapping = tmp_path / "mapping.csv"
    mig.preview(export_dir, mapping)

    summary = mig.run(export_dir, mapping)
    assert summary["students"]["linked"] == 1
    assert summary["students"]["created"] == 1
    assert summary["accounts"]["imported"] == 1
    assert summary["sources"] == 1
    assert summary["runs"] == 1
    assert summary["reports"] == 1

    engine = mdb["engine"]
    with Session(engine) as sess:
        users = sess.execute(select(_db.User)).scalars().all()
        assert len(users) == 1
        assert users[0].username == "wang@example.com"
        assert users[0].email == "wang@example.com"
        assert users[0].role == "advisor"
        assert users[0].advisor_name == "王老师"
        # bcrypt 哈希不能直接沿用，迁移后必须重置密码。
        assert users[0].password_hash != "$2b$12$abcdefghijklmnopqrstuv"

        lisi = sess.execute(
            select(_db.Student).where(_db.Student.name == "李四")
        ).scalar_one()
        assert lisi.student_code == "Y4-0002"

        source = sess.execute(select(store.GtSource)).scalar_one()
        assert source.student_id == mdb["local_id"]
        assert source.title == "首次会谈"
        run = sess.execute(select(store.GtRun)).scalar_one()
        assert run.status == "READY" and run.revision == 3
        assert run.source_id == source.id
        understanding = sess.execute(select(store.GtUnderstanding)).scalar_one()
        assert understanding.summary == "学生偏好计算机"
        interest = sess.execute(select(store.GtInterest)).scalar_one()
        assert (interest.preference_score, interest.competence_score) == (3, 2)
        report = sess.execute(select(store.GtReport)).scalar_one()
        assert report.status == "CONFIRMED"
        assert json.loads(report.payload) == {"schema": "first-touch.report.v1"}

    assert store.find_student_by_external("yuguo", "yg-9") == mdb["local_id"]
    assert store.find_student_by_external(
        "first-touch-migration", "ft-1") == mdb["local_id"]
    assert store.find_student_by_external("first-touch-migration", "ft-2")

    actions = [row["action"] for row in store.list_audit(student_id=mdb["local_id"])]
    assert "report_confirmed" in actions
    assert "migration_import" in actions

    counts_before = _table_counts(engine)
    again = mig.run(export_dir, mapping)
    assert again["students"]["skipped"] == 2
    assert _table_counts(engine) == counts_before


def _table_counts(engine) -> dict:
    with Session(engine) as sess:
        return {
            "users": sess.query(_db.User).count(),
            "students": sess.query(_db.Student).count(),
            "sources": sess.query(store.GtSource).count(),
            "runs": sess.query(store.GtRun).count(),
            "reports": sess.query(store.GtReport).count(),
            "identities": sess.query(store.ExternalIdentity).count(),
        }
