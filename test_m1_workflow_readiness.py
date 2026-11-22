"""Cross-page and generation recovery checks using synthetic M1 records."""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy.orm import Session

from m1 import job_attempts, jobs, plan_store, report_store, store
from test_m1_roster import client, login_as, m1db, plan_client  # noqa: F401
from test_m1dp_store import _create, _drafted_prep


def test_open_report_stays_visible_across_student_surfaces(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    prep, report = _drafted_prep(m1db)
    plan = _create(m1db, prep, report)
    plan_store.finish_generation(plan["id"], "internal", status="review")
    plan_store.approve(plan["id"], m1db.alice_id)
    plan_store.finish_generation(plan["id"], "parent", status="draft")
    plan_store.confirm_parent(plan["id"], m1db.alice_id)
    plan_store.export_parent(plan["id"], m1db.alice_id)

    sid = m1db.student_id
    roster = client.get("/api/m1/roster").get_json()["students"]
    row = next(row for row in roster if row["student_id"] == sid)
    hub = client.get(f"/api/m1/students/{sid}/overview").get_json()["work"]
    meeting = client.get(f"/api/m1/preps/{prep['id']}/overview").get_json()["work"]
    assert row["workflow_state"] == "todo"
    assert row["next"] == hub["next"] == meeting["next"]
    assert row["next"]["href"].endswith("/report#step=review")


def test_first_meeting_intent_preselects_and_reuses_even_if_final(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    sid = m1db.student_id
    hub = client.get(f"/api/m1/students/{sid}/overview").get_json()
    assert hub["meeting_creation"]["href"] == f"/m1?create_meeting={sid}"
    response = client.get(hub["meeting_creation"]["href"])
    assert 'data-create-meeting="1"' in response.get_data(as_text=True)
    created = client.post("/api/m1/preps", json={"student_id": sid})
    assert created.status_code == 201
    prep_id = created.get_json()["prep"]["id"]
    store.set_status(prep_id, "final")
    existing = client.post("/api/m1/preps", json={"student_id": sid})
    assert existing.status_code == 200
    assert existing.get_json()["prep"]["id"] == prep_id
    assert client.get(hub["meeting_creation"]["href"]).location.endswith(f"/m1/students/{sid}#meetings")


def test_prep_generation_lease_resumes_and_fences_expired_worker(client, m1db, monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "JOB_DIR", tmp_path)
    monkeypatch.setattr(jobs, "launch_job", lambda prep_id, **kwargs: kwargs["job_id"])
    login_as(client, m1db.alice_id, "advisor", "Alice")
    prep = m1db.prep()
    prep_id = prep["id"]
    draft = store.add_version(prep_id, "edit", doc={"fictional": "previous draft"})
    store.set_status(prep_id, "review")
    endpoint = f"/api/m1/preps/{prep_id}"
    start = Barrier(2)

    def generate():
        request_client = client.application.test_client()
        login_as(request_client, m1db.alice_id, "advisor", "Alice")
        start.wait(timeout=5)
        return request_client.post(endpoint + "/generate")

    with ThreadPoolExecutor(max_workers=2) as threads:
        responses = [threads.submit(generate) for _ in range(2)]
        result = [response.result(timeout=10) for response in responses]
    assert sorted(response.status_code for response in result) == [200, 409]
    first = next(response.get_json()["job_id"] for response in result if response.status_code == 200)
    assert client.get(endpoint).get_json()["job_id"] == first
    with job_attempts.worker(first, ("prep", prep_id)):
        with job_attempts._locked("prep", prep_id) as path:
            stale = time.time() - job_attempts.LEASE_SECONDS - 1
            os.utime(path, (stale, stale))

        assert client.get(f"/api/m1/jobs/{first}").get_json()["job"]["status"] == "error"
        assert store.get_prep(prep_id)["status"] == "review"
        assert store.get_current_version(prep_id)["id"] == draft["id"]
        second = client.post(endpoint + "/generate").get_json()["job_id"]
        assert second != first
        with pytest.raises(job_attempts.AttemptConflict):
            with job_attempts.commit():
                pytest.fail("Expired worker could overwrite the document")
    assert client.get(endpoint).get_json()["job_id"] == second


def test_stale_pre_upgrade_generation_without_job_recovers_saved_draft(
        client, m1db, monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "JOB_DIR", tmp_path)
    login_as(client, m1db.alice_id, "advisor", "Alice")
    prep_id = m1db.prep()["id"]
    draft = store.add_version(prep_id, "edit", doc={"fictional": "previous draft"})
    with Session(m1db.engine) as session:
        prep = session.get(store.M1Prep, prep_id)
        prep.status = "generating"
        prep.updated_at = datetime.utcnow() - timedelta(seconds=job_attempts.MAX_RUN_SECONDS + 1)
        session.commit()

    detail = client.get(f"/api/m1/preps/{prep_id}").get_json()
    assert detail["prep"]["status"] == "review"
    assert not detail["job_id"]
    assert store.get_current_version(prep_id)["id"] == draft["id"]
