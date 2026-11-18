"""DP15: explicit student reads stay separate from legacy document mutations."""
import json

import pytest
from sqlalchemy.orm import Session

import db
from app_utils import BASE_DIR
from m1 import plan_collaboration as collab, report_store, store
from test_m1_api import login_as
from test_m1_store import m1db  # noqa: F401
from test_m1dp_api import plan_client, _new_plan_with_version  # noqa: F401


@pytest.fixture
def assigned(plan_client, m1db):
    from blueprints import m1_report
    plan_client.application.register_blueprint(m1_report.bp)
    plan, _ = _new_plan_with_version(m1db)
    report = report_store.get_report(plan["prep_id"])
    doc = json.loads((BASE_DIR / "fixtures/m1_report_doc_sample.json").read_text())
    report_store.add_version(report["id"], y4_ratings={}, evidence=[], ai_doc=doc,
                             doc=doc, checks=[], manifest={}, status="needs_check")
    collab.add_team_member(m1db.student_id, m1db.bob_id,
                          {"user_id": m1db.admin_id, "role": "admin"})
    login_as(plan_client, m1db.bob_id, "advisor", "Bob")
    return plan_client, plan


@pytest.mark.parametrize("summary", [False, True])
def test_readonly_pages_payloads_and_print_edit_mode(assigned, m1db, summary):
    client, plan = assigned
    if summary:
        with client.session_transaction() as session:
            session["detail_level"] = "summary"
        with Session(m1db.engine) as session:
            session.get(db.User, m1db.bob_id).detail_level = "summary"
            session.commit()
    base = f"/api/m1/preps/{plan['prep_id']}"
    for suffix in ("", "/overview", "/report"):
        payload = client.get(base + suffix).get_json()
        assert payload["ok"] and payload["can_edit"] is False
    for suffix in ("/prep", "/report"):
        page = client.get(f"/m1/preps/{plan['prep_id']}{suffix}").get_data(as_text=True)
        assert "只读" in page
        assert "m1_workspace.js" not in page and "report_workspace.js" not in page
        assert "finalizeBtn" not in page and "r4Publish" not in page
    printed = client.get(f"/m1/preps/{plan['prep_id']}/report/print?edit=1")
    assert printed.status_code == 200
    html = printed.get_data(as_text=True)
    assert "report_edit.js" not in html and 'contenteditable="true"' not in html
    hub = client.get(f"/m1/students/{m1db.student_id}").get_data(as_text=True)
    assert "+ 直接创建教案" not in hub and "+ 新建 First Meeting" not in hub
    listing = client.get("/api/m1/preps").get_json()["preps"]
    prep = next(p for p in listing if p["id"] == plan["prep_id"])
    assert prep["assigned"] is True and prep["can_edit"] is False
    assert prep["report"]["can_edit"] is False
    eligible = client.get("/api/m1/plans/eligible").get_json()["students"]
    assert all(p["student_id"] != m1db.student_id for p in eligible)


def test_report_sources_are_readable_escaped_and_revoke_immediately(assigned, m1db):
    client, plan = assigned
    prep_id = plan["prep_id"]
    report = report_store.get_report(prep_id)
    report_store.set_transcript(report["id"], text="TRANSCRIPT <script>bad()</script>",
                                filename="fictional.txt", stored_path="/private/secret/transcript.txt")
    source = store.add_source(prep_id, category="report_other", label="Report file",
                             filename="report.txt", text="SOURCE <img src=x>",
                             stored_path="/private/secret/report.txt")
    url = f"/m1/preps/{prep_id}/report/sources"
    response = client.get(url)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "fictional.txt" in html and "report.txt" in html
    assert "TRANSCRIPT &lt;script&gt;" in html and "SOURCE &lt;img" in html
    assert "/private/secret" not in html and "<script>bad()" not in html
    assert client.delete(f"/api/m1/sources/{source['id']}").status_code == 403
    collab.remove_team_member(m1db.student_id, m1db.bob_id,
                             {"user_id": m1db.admin_id, "role": "admin"})
    assert client.get(url).status_code == 403


@pytest.mark.parametrize("field,value", [("is_active", 0), ("m1_access", 0), ("role", "viewer")])
def test_live_account_disables_assignment_grant(assigned, m1db, field, value):
    _, plan = assigned
    user = {"user_id": m1db.bob_id, "role": "advisor", "advisor_name": "Bob"}
    assert store.can_read_prep(user, plan["prep_id"])
    with Session(m1db.engine) as session:
        setattr(session.get(db.User, m1db.bob_id), field, value)
        session.commit()
    assert not store.can_read_prep(user, plan["prep_id"])
    assert m1db.student_id not in store.assigned_student_ids(user)


def test_summary_status_list_only_includes_explicit_assignments(assigned, m1db):
    client, plan = assigned
    own_prep = m1db.prep(m1db.other_student_id, m1db.bob_id)
    with client.session_transaction() as session:
        session["detail_level"] = "summary"
    response = client.get("/api/m1/report-statuses")
    assert response.status_code == 200
    assert set(response.get_json()["statuses"]) == {str(plan["prep_id"])}
    assert client.get(f"/api/m1/preps/{own_prep['id']}/report").status_code == 403


def test_nested_prep_snapshot_redacted_without_changing_storage(assigned):
    client, plan = assigned
    prep_id = plan['prep_id']
    version = store.add_version(
        prep_id, 'edit', doc={'title': 'Snapshot regression'},
        y4_snapshot={'items': [{'code': 'TEST', 'raw': 7, 'text': 'band'}]},
        evidence=[{'raw': 8, 'text': 'evidence band'}])
    for suffix in ('', '/overview'):
        payload = client.get(f'/api/m1/preps/{prep_id}{suffix}').get_json()
        nested = payload['prep']['current_version']
        assert nested['y4_snapshot']['items'] == [{'code': 'TEST', 'text': 'band'}]
        assert nested['evidence'] == [{'text': 'evidence band'}]
        if 'version' in payload:
            assert 'raw' not in payload['version']['y4_snapshot']['items'][0]
    html = client.get(f'/m1/preps/{prep_id}/prep').get_data(as_text=True)
    assert 'band' in html and '"raw"' not in html
    stored = store.get_version(version['id'])
    assert stored['y4_snapshot']['items'][0]['raw'] == 7
    assert stored['evidence'][0]['raw'] == 8


def test_readonly_questionnaire_uses_source_answer_fields(assigned, monkeypatch):
    from m1 import sources
    client, plan = assigned
    monkeypatch.setattr(sources, '_questionnaire_rows', lambda sid: [{
        'title': 'Fictional questionnaire', 'status': '已完成',
        'answers': [{'question': 'Fictional question', 'answer': 'Visible answer'}],
    }])
    html = client.get(f"/m1/preps/{plan['prep_id']}/prep").get_data(as_text=True)
    for text in ('Fictional questionnaire', 'Fictional question', 'Visible answer'):
        assert text in html
