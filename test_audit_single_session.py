"""A2 · 每名学生一条 First Touch 会谈 + 旧重复会谈合并脚本。

复用 ``test_copilot_routes.py`` 的 Flask/DB fixture（``client`` / ``login_as`` /
``qdb``）。
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import db as _db
import growth_talk_store as store

from test_copilot_routes import client, login_as, qdb  # noqa: F401


def _create_user(engine, username: str, role: str,
                 display_name: str | None = None) -> int:
    with Session(engine) as sess:
        user = _db.User(username=username, password_hash="x", role=role,
                        display_name=display_name)
        sess.add(user)
        sess.commit()
        return user.id


def _login_admin(client, qdb) -> int:
    admin_id = _create_user(qdb.engine, "root", "admin", "管理员")
    login_as(client, qdb, role="admin", advisor_name="",
             display_name="管理员", user_id=admin_id)
    return admin_id


def test_admin_created_session_is_shared_with_advisor(client, qdb):
    admin_id = _login_admin(client, qdb)

    created = client.post(
        f"/api/v2/students/{qdb.student_id}/copilot/sessions",
        json={"entryMode": "guided"})
    assert created.status_code == 201
    session = created.get_json()["session"]
    assert session["advisor_id"] == admin_id

    login_as(client, qdb)  # Alice，该学生的顾问
    listed = client.get(
        f"/api/v2/students/{qdb.student_id}/copilot/sessions")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.get_json()["sessions"]] == [session["id"]]

    again = client.post(
        f"/api/v2/students/{qdb.student_id}/copilot/sessions",
        json={"entryMode": "direct"})
    assert again.status_code == 200
    assert again.get_json()["existing"] is True
    assert again.get_json()["session"]["id"] == session["id"]
    assert len(store.list_sessions(qdb.student_id)) == 1

    detail = client.get(f"/api/v2/copilot/sessions/{session['id']}")
    assert detail.status_code == 200
    body = detail.get_json()
    assert body["session"]["advisor_id"] == admin_id
    assert body["lastEditor"]["name"] == "管理员"
    assert body["lastEditor"]["at"]


def test_advisor_can_patch_admin_created_session(client, qdb):
    _login_admin(client, qdb)
    session = client.post(
        f"/api/v2/students/{qdb.student_id}/copilot/sessions",
        json={"entryMode": "guided"}).get_json()["session"]

    login_as(client, qdb)
    response = client.patch(
        f"/api/v2/copilot/sessions/{session['id']}/phase",
        json={"phase": 2, "revision": session["revision"]})

    assert response.status_code == 200
    # 纯导航不递增 revision（FT-01），但阶段确实写入。
    assert response.get_json()["revision"] == session["revision"]
    assert store.get_session(session["id"])["phase"] == 2

    bumped = client.patch(
        f"/api/v2/copilot/sessions/{session['id']}/phase",
        json={"phase": 2, "revision": session["revision"],
              "meetingAt": "2026-10-20T10:00:00"})
    assert bumped.status_code == 200
    assert bumped.get_json()["revision"] == session["revision"] + 1


def test_advisor_of_another_student_gets_404(client, qdb):
    _login_admin(client, qdb)
    session = client.post(
        f"/api/v2/students/{qdb.student_id}/copilot/sessions",
        json={"entryMode": "guided"}).get_json()["session"]

    login_as(client, qdb, advisor_name="Bob", display_name="Bob")

    assert client.get(
        f"/api/v2/copilot/sessions/{session['id']}").status_code == 404
    assert client.get(
        f"/api/v2/students/{qdb.student_id}/copilot/sessions").status_code == 404
    assert client.get(
        f"/first-touch/students/{qdb.student_id}").status_code == 404


def test_archived_session_is_404(client, qdb):
    login_as(client, qdb)
    session = qdb.session()
    with Session(qdb.engine) as sess:
        row = sess.get(store.CopilotSession, session["id"])
        row.status = "ARCHIVED"
        sess.commit()

    assert client.get(
        f"/api/v2/copilot/sessions/{session['id']}").status_code == 404
    assert store.list_sessions(qdb.student_id) == []


# ---------------------------------------------------------------------------
# 合并脚本
# ---------------------------------------------------------------------------
def _seed_duplicates(engine) -> dict:
    with Session(engine) as sess:
        student = _db.Student(student_code="Y4-9301", name="重复学生",
                              grade="10", advisor_name="Alice")
        users = [
            _db.User(username=f"dup-{index}", password_hash="x",
                     role="advisor", advisor_name=f"顾问{index}")
            for index in range(4)
        ]
        sess.add(student)
        sess.add_all(users)
        sess.commit()

        run = store.GtRun(student_id=student.id, source_id=1, version=1,
                          revision=1, status="DONE")
        sess.add(run)
        sess.flush()
        sess.add(store.GtReport(
            student_id=student.id, run_id=run.id, version=1,
            status="CONFIRMED", payload=json.dumps({"schema": "x"}),
        ))
        sess.commit()

        sessions = [
            store.CopilotSession(
                student_id=student.id, advisor_id=users[0].id, phase=6,
                revision=1, status="ACTIVE", script="{}", interests="[]",
                updated_at=datetime(2026, 1, 5),
            ),
            store.CopilotSession(
                student_id=student.id, advisor_id=users[1].id, phase=1,
                revision=1, status="ACTIVE", script="{}", interests="[]",
                run_id=run.id, updated_at=datetime(2026, 1, 1),
            ),
            store.CopilotSession(
                student_id=student.id, advisor_id=users[2].id, phase=0,
                revision=1, status="ACTIVE", script="{}", interests="[]",
                updated_at=datetime(2026, 1, 3),
            ),
        ]
        sess.add_all(sessions)
        sess.commit()
        return {
            "student_id": student.id,
            "spare_advisor_id": users[3].id,
            "sessions": [row.id for row in sessions],
            "confirmed_session": sessions[1].id,
        }


def test_migration_archives_duplicates_and_adds_index(tmp_path, monkeypatch):
    from scripts.merge_duplicate_copilot_sessions import merge_duplicates

    engine = create_engine(f"sqlite:///{tmp_path / 'dup_sessions.db'}")
    _db.Base.metadata.create_all(engine)
    monkeypatch.setattr(_db, "engine", engine)
    seeded = _seed_duplicates(engine)

    summary = merge_duplicates(engine, apply=True, out=lambda *_args: None)

    assert summary["students"] == 1
    assert len(summary["archived"]) == 2
    statuses = {
        session_id: store.get_session(session_id)["status"]
        for session_id in seeded["sessions"]
    }
    assert statuses[seeded["confirmed_session"]] != "ARCHIVED"
    assert sum(1 for status in statuses.values()
               if status == "ARCHIVED") == 2
    assert [row["id"] for row in store.list_sessions(
        seeded["student_id"])] == [seeded["confirmed_session"]]

    audits = store.list_audit(
        seeded["student_id"], action="copilot_session_archived_duplicate")
    assert len(audits) == 2
    assert {json.loads(item["details"])["keptSessionId"]
            for item in audits} == {seeded["confirmed_session"]}

    with engine.connect() as conn:
        index = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='uq_copilot_session_student_active'").first()
    assert index

    # 部分唯一索引拦住第二条非归档会话
    with Session(engine) as sess:
        sess.add(store.CopilotSession(
            student_id=seeded["student_id"],
            advisor_id=seeded["spare_advisor_id"], phase=0, revision=1,
            status="ACTIVE", script="{}", interests="[]",
        ))
        with pytest.raises(IntegrityError):
            sess.commit()
    engine.dispose()


def test_migration_dry_run_writes_nothing(tmp_path, monkeypatch):
    from scripts.merge_duplicate_copilot_sessions import merge_duplicates

    engine = create_engine(f"sqlite:///{tmp_path / 'dup_dry.db'}")
    _db.Base.metadata.create_all(engine)
    monkeypatch.setattr(_db, "engine", engine)
    seeded = _seed_duplicates(engine)

    lines = []
    summary = merge_duplicates(engine, apply=False, out=lines.append)

    assert summary["applied"] is False
    assert summary["archived"] == []
    assert lines and "归档" in lines[0]
    assert len(store.list_sessions(seeded["student_id"])) == 3
    with engine.connect() as conn:
        index = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='uq_copilot_session_student_active'").first()
    assert index is None
    engine.dispose()
