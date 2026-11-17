"""Assigned-student discovery and raw-source isolation, using temporary data only."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

import app_utils
import db
from m1 import plan_collaboration as collab, plan_store as plans, report_store, store
from test_m1_api import login_as
from test_m1_store import m1db  # noqa: F401
from test_m1dp_api import plan_client  # noqa: F401
from test_m1dp_store import _create, _drafted_prep

ROOT = Path(__file__).resolve().parent


@pytest.fixture
def client(plan_client):
    from blueprints import m1_report
    plan_client.application.register_blueprint(m1_report.bp)
    return plan_client


def _admin(database):
    return {"user_id": database.admin_id, "role": "admin"}


def _direct(database, sid=None, block=1, **extra):
    return plans.create_plan(sid or database.student_id, source_mode="mentor_inputs",
                             mentor_user_id=database.alice_id, block_no=block,
                             period_start="2026-11-17", period_end="2026-12-17", **extra)


def _roster(client):
    response = client.get("/api/m1/roster")
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert set(payload) == {"ok", "me", "students"}
    return payload["students"]


def _shared_report(client, database):
    prep, report = _drafted_prep(database)
    plan = _create(database, prep, report)
    collab.add_team_member(database.student_id, database.bob_id, _admin(database))
    # Reproduce an assigned co-mentor with no Profiling students of their own.
    with Session(database.engine) as session:
        session.get(db.Student, database.other_student_id).advisor_name = "Unrelated"
        session.commit()
    login_as(client, database.bob_id, "advisor", "Bob")
    return prep, report, plan


def test_shared_report_plan_discovers_student_without_raw_metadata(client, m1db):
    prep, report, plan = _shared_report(client, m1db)
    # The report need only have a draft, not publication, to supply a shared plan.
    assert report["status"] == "ai_draft"
    report_store.set_transcript(report["id"], text="PRIVATE_TRANSCRIPT")
    with Session(m1db.engine) as session:
        source = store.M1Source(prep_id=prep["id"], category="parent",
                                label="PRIVATE_LABEL", text="PRIVATE_SOURCE")
        session.add(source)
        session.get(store.M1Prep, prep["id"]).meeting_date = "2091-02-03"
        session.commit()
        source_id = source.id
    rows = _roster(client)
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {"student_id", "student_name", "student_code", "grade", "hub_url",
                        "participating", "roles", "prep", "plan", "next", "workflow_state"}
    assert row["student_id"] == m1db.student_id
    assert row["roles"] == ["co_mentor"] and row["participating"] is True
    assert row["prep"] is None
    assert set(row["plan"]) == {"id", "block_no", "label", "tone", "step_url"}
    assert row["plan"]["id"] == plan["id"]
    serialized = json.dumps(rows)
    for forbidden in ("prep_id", "report_id", "report_version_id", "meeting_date",
                      "current_version_id", "ai_draft", "2091-02-03", "PRIVATE_",
                      "school", "advisor_name", "transcript", "materials", "y4", "notes"):
        assert forbidden not in serialized
    assert client.get(row["hub_url"]).status_code == 200
    assert client.get(f"/api/m1/students/{m1db.student_id}/overview").status_code == 200
    assert client.get(f"/m1/plans/{plan['id']}").status_code == 200
    assert client.get(f"/api/m1/plans/{plan['id']}").status_code == 200
    for path in (f"/api/m1/preps/{prep['id']}", f"/api/m1/preps/{prep['id']}/overview",
                 f"/m1/preps/{prep['id']}/prep", f"/api/m1/preps/{prep['id']}/report",
                 f"/m1/preps/{prep['id']}/report"):
        assert client.get(path).status_code == 403, path
    assert client.patch(f"/api/m1/sources/{source_id}", json={"text": "changed"}).status_code == 403
    assert client.get("/api/m1/preps").get_json()["preps"] == []
    assert client.get("/api/m1/students").get_json()["students"] == []
    # Discovery does not grant the legacy Add Meeting operation either.
    assert client.post("/api/m1/preps", json={"student_id": m1db.student_id}).status_code == 403


@pytest.mark.parametrize("team_role", ["co_mentor", "primary"])
def test_team_before_any_plan_has_real_row_and_hub(client, m1db, team_role):
    with Session(m1db.engine) as session:
        session.add(collab.PlanTeamMember(student_id=m1db.student_id,
                                         user_id=m1db.bob_id, role=team_role))
        session.commit()
    login_as(client, m1db.bob_id, "advisor", "Bob")
    row, = _roster(client)
    assert row["prep"] is row["plan"] is row["next"] is None
    assert row["workflow_state"] == "todo"
    assert row["roles"] == [team_role] and row["participating"]
    assert client.get(row["hub_url"]).status_code == 200
    assert not store.can_access_student({"role": "advisor", "advisor_name": "Bob"}, m1db.student_id)


def test_direct_plan_without_meeting_and_creator_mentor_mismatch(client, m1db):
    plan = _direct(m1db, created_by=m1db.admin_id)
    login_as(client, m1db.alice_id, "advisor", "Alice")
    row, = _roster(client)
    assert row["prep"] is None and row["plan"]["id"] == plan["id"]
    assert row["participating"] and "primary" in row["roles"]
    assert "creator" not in row["roles"]
    assert client.get(row["hub_url"]).status_code == 200


def test_deduplicates_preps_and_blocks_and_uses_all_assignments_for_participation(client, m1db):
    prep, report = _drafted_prep(m1db)
    older = _create(m1db, prep, report)
    newest = _create(m1db, prep, report, block_no=3, mentor_user_id=m1db.admin_id)
    later_prep = m1db.prep(m1db.student_id, m1db.admin_id)
    # Make the lower Block newer in time: highest Block must still win.
    with Session(m1db.engine) as session:
        from datetime import datetime
        session.get(plans.M1Plan, older["id"]).updated_at = datetime(2090, 1, 1)
        session.get(store.M1Prep, later_prep["id"]).meeting_date = "2030-06-01"
        session.commit()
    login_as(client, m1db.alice_id, "advisor", "Alice")
    row, = _roster(client)
    assert row["prep"]["id"] == later_prep["id"]
    assert row["prep"]["meeting_date"] == "2030-06-01"
    assert row["plan"]["id"] == newest["id"] and row["plan"]["block_no"] == 3
    assert "primary" in row["roles"]  # earlier visible assignment still counts
    assert set(row["prep"]) == {"id", "meeting_date", "mentor_name", "status", "has_doc", "report"}


def test_prep_assignment_gets_narrow_hub_access_without_student_or_other_prep_access(client, m1db):
    assigned = m1db.prep(m1db.student_id, m1db.bob_id)
    hidden = m1db.prep()
    login_as(client, m1db.bob_id, "advisor", "Bob")
    row, = _roster(client)
    assert row["prep"]["id"] == assigned["id"] and row["participating"]
    assert client.get(row["hub_url"]).status_code == 200
    overview = client.get(f"/api/m1/students/{m1db.student_id}/overview").get_json()
    assert [p["id"] for p in overview["preps"]] == [assigned["id"]]
    assert overview["can_create_direct"] is False
    assert client.get(f"/api/m1/preps/{hidden['id']}").status_code == 403


def test_report_plan_reached_via_prep_assignment_opens_hub(client, m1db):
    prep, report = _drafted_prep(m1db)
    store.update_prep(prep["id"], mentor_user_id=m1db.bob_id)
    plan = _create(m1db, prep, report, mentor_user_id=m1db.bob_id)
    login_as(client, m1db.bob_id, "advisor", "Bob")
    row, = _roster(client)
    assert row["plan"]["id"] == plan["id"]
    assert client.get(row["hub_url"]).status_code == 200
    assert client.get(f"/m1/plans/{plan['id']}").status_code == 200


@pytest.mark.parametrize("role,name,uid", [("admin", "", "admin_id"), ("advisor", "Alice", "alice_id")])
def test_raw_scope_does_not_enroll_profiling_students_without_m1(client, m1db, role, name, uid):
    login_as(client, getattr(m1db, uid), role, name)
    assert _roster(client) == []
    assert client.get("/api/m1/students").get_json()["students"]  # picker unchanged
    m1db.prep()
    assert [r["student_id"] for r in _roster(client)] == [m1db.student_id]


def test_creator_alone_never_grants_visibility(client, m1db):
    store.create_prep(m1db.student_id, mentor_user_id=m1db.alice_id, created_by=m1db.bob_id)
    _direct(m1db, created_by=m1db.bob_id)
    login_as(client, m1db.bob_id, "advisor", "Bob")
    assert _roster(client) == []
    assert client.get(f"/m1/students/{m1db.student_id}").status_code == 404


def test_latest_block_is_selected_only_from_readable_plans(client, m1db):
    prep, report = _drafted_prep(m1db)
    store.update_prep(prep["id"], mentor_user_id=m1db.bob_id)
    visible = _create(m1db, prep, report, mentor_user_id=m1db.bob_id)
    hidden_prep, hidden_report = _drafted_prep(m1db)
    _create(m1db, hidden_prep, hidden_report, block_no=2)
    _direct(m1db, block=3)
    login_as(client, m1db.bob_id, "advisor", "Bob")
    row, = _roster(client)
    assert row["plan"]["id"] == visible["id"] and row["plan"]["block_no"] == 1
    assert row["prep"]["id"] == prep["id"]


def test_creator_participates_only_with_independent_visibility(client, m1db):
    _direct(m1db, created_by=m1db.bob_id)
    login_as(client, m1db.bob_id, "advisor", "Bob")
    with client.session_transaction() as session:
        session["student_scope"] = "all"
    row, = _roster(client)
    assert row["roles"] == ["creator"] and row["participating"]


@pytest.mark.parametrize("status,parent,expected", [
    ("inputs", "none", "todo"), ("review", "none", "todo"),
    ("approved", "draft", "todo"), ("approved", "confirmed", "todo"),
    ("approved", "exported", "done"), ("review", "exported", "todo"),
])
def test_workflow_completion_is_independent_of_open_plan_link(client, m1db, status, parent, expected):
    plan = _direct(m1db)
    with Session(m1db.engine) as session:
        row = session.get(plans.M1Plan, plan["id"])
        row.status, row.parent_status = status, parent
        session.commit()
    login_as(client, m1db.alice_id, "advisor", "Alice")
    row, = _roster(client)
    assert row["workflow_state"] == expected
    assert row["next"]["href"].startswith(f"/m1/plans/{plan['id']}")


@pytest.mark.parametrize("fresh", [False, True])
def test_exported_parent_must_match_current_internal_version_to_count_done(client, m1db, fresh):
    plan = _direct(m1db)
    internal = plans.add_version(plan["id"], part="internal", kind="ai_draft", doc={})
    parent = plans.add_version(plan["id"], part="parent", kind="ai_draft", doc={},
                               source_version_id=internal["id"])
    replacement = plans.add_version(plan["id"], part="internal", kind="ai_draft", doc={})
    with Session(m1db.engine) as session:
        row = session.get(plans.M1Plan, plan["id"])
        row.status, row.parent_status = "approved", "exported"
        row.parent_version_id = parent["id"]
        row.current_version_id = internal["id"] if fresh else replacement["id"]
        session.commit()
    login_as(client, m1db.alice_id, "advisor", "Alice")
    row, = _roster(client)
    assert row["workflow_state"] == ("done" if fresh else "todo")
    assert row["next"] is not None
    assert row["plan"]["label"] == ("已导出" if fresh else "家长版 已过期")


def test_revocation_removes_discovery_and_keeps_independent_prep_access(client, m1db):
    prep, report, plan = _shared_report(client, m1db)
    assert _roster(client)
    collab.remove_team_member(m1db.student_id, m1db.bob_id, _admin(m1db))
    assert _roster(client) == []
    assert client.get(f"/m1/students/{m1db.student_id}").status_code == 404
    assert client.get(f"/api/m1/plans/{plan['id']}").status_code == 404
    store.update_prep(prep["id"], mentor_user_id=m1db.bob_id)
    row, = _roster(client)
    assert row["roles"] == ["primary"]
    assert client.get(row["hub_url"]).status_code == 200


@pytest.mark.parametrize("disabled", ["account", "m1", "viewer", "anonymous"])
def test_rejects_ineffective_accounts(client, m1db, monkeypatch, disabled):
    _shared_report(client, m1db)
    if disabled == "account":
        with Session(m1db.engine) as session:
            session.get(db.User, m1db.bob_id).is_active = 0
            session.commit()
        assert _roster(client) == []
    elif disabled == "m1":
        with client.session_transaction() as session:
            session["m1_access"] = 0
        assert client.get("/api/m1/roster").status_code == 403
    elif disabled == "viewer":
        login_as(client, m1db.viewer_id, "viewer")
        assert client.get("/api/m1/roster").status_code == 403
    else:
        monkeypatch.setattr(app_utils, "is_authenticated", lambda: False)
        assert client.get("/api/m1/roster").status_code == 401


def test_roster_query_count_does_not_grow_per_student(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    _direct(m1db)

    def queries():
        statements = []
        def capture(conn, cursor, statement, params, context, many):
            statements.append(statement)
        event.listen(m1db.engine, "before_cursor_execute", capture)
        try:
            rows = _roster(client)
        finally:
            event.remove(m1db.engine, "before_cursor_execute", capture)
        return rows, statements

    _, initial = queries()
    with Session(m1db.engine) as session:
        for n in range(25):
            student = db.Student(student_code=f"FAKE-{n}", name=f"Fictional {n}", advisor_name="Alice")
            session.add(student)
            session.flush()
            session.add(store.M1Prep(student_id=student.id, mentor_user_id=m1db.alice_id))
        session.commit()
    rows, expanded = queries()
    # One bulk report overview is added when visible preps first appear.
    assert len(rows) == 26 and len(expanded) <= len(initial) + 1
    assert len(expanded) <= 6


@pytest.mark.skipif(shutil.which("node") is None, reason="Node unavailable")
def test_home_executes_with_real_shared_roster_response(client, m1db):
    _shared_report(client, m1db)
    payload = client.get("/api/m1/roster").get_json()
    subprocess.run(["node", str(ROOT / "test_m1_roster_home.cjs")],
                   input=json.dumps(payload), capture_output=True, text=True, check=True, cwd=ROOT)
    html = client.get("/m1").get_data(as_text=True)
    assert 'data-who="mine" aria-pressed="true">我参与的' in html
    assert "此处添加 First Meeting" in html
