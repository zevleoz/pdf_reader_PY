"""Race and snapshot coverage for report review actions on synthetic data."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy.orm import Session

from m1 import plan_store, report_store
from test_m1_report_core import (admin_login, client, doc_put, fake, generate,  # noqa: F401
                                 publish_reviewed, rdb, report_pin, url)
from test_m1_store import m1db  # noqa: F401
from test_m1dp_store import _create


PORTRAIT = ["portrait", "R1"]
PUBLISHED_TEXT = "Synthetic official portrait"
EDITED_TEXT = "Synthetic portrait in the reopened draft"


def _edit(client, rdb, report, text):
    return doc_put(client, rdb, report["rev"], [{"path": PORTRAIT, "value": text}])


def _print(client, rdb, report=None):
    path = url(rdb, "/print").replace("/api/", "/", 1)
    query = {"print": 1}
    if report:
        query.update(report_pin(report))
    return client.get(path, query_string=query)


def test_publish_and_print_require_complete_valid_pins(client, rdb, fake):
    generate(rdb)
    admin_login(client, rdb)
    report = report_store.get_report(rdb.prep_row["id"])
    pin = report_pin(report)
    path = url(rdb, "/print").replace("/api/", "/", 1)
    for malformed in ({}, {"expected_rev": pin["expected_rev"]},
                      {**pin, "version_id": True}, {**pin, "expected_rev": 0}):
        assert client.post(url(rdb, "/publish"), json=malformed).status_code == 400
    for malformed in ({"expected_rev": pin["expected_rev"]},
                      {"version_id": pin["version_id"]}, {**pin, "expected_rev": "no"}):
        denied = client.get(path, query_string=malformed)
        assert denied.status_code == 400
        assert b'id="print-error"' in denied.data and b"window.print()" not in denied.data
    assert _print(client, rdb).status_code == 200
    assert _print(client, rdb, report).status_code == 200
    assert client.post(url(rdb, "/publish"), json={
        **pin, "version_id": pin["version_id"] + 1,
    }).status_code == 409


@pytest.mark.parametrize("winner", ["publish", "document", "transcript", "version"])
def test_publish_and_competing_report_writes_have_one_winner(
        client, rdb, fake, monkeypatch, winner):
    generate(rdb)
    admin_login(client, rdb)
    prep_id = rdb.prep_row["id"]
    report = report_store.get_report(prep_id)
    reached = threading.Event()
    release = threading.Event()
    delayed_name = "save_version" if winner == "publish" else "publish"
    write = getattr(report_store, delayed_name)

    def delay(*args, **kwargs):
        reached.set()  # The delayed request has read the candidate and run checks.
        assert release.wait(10)
        return write(*args, **kwargs)

    monkeypatch.setattr(report_store, delayed_name, delay)

    def after_barrier():
        other = client.application.test_client()
        admin_login(other, rdb)
        if winner == "publish":
            return _edit(other, rdb, report, EDITED_TEXT)
        return other.post(url(rdb, "/publish"), json=report_pin(report))

    with ThreadPoolExecutor() as pool:
        loser = pool.submit(after_barrier)
        try:
            assert reached.wait(10)
            if winner == "publish":
                assert publish_reviewed(client, rdb).status_code == 200
            elif winner == "document":
                assert _edit(client, rdb, report, EDITED_TEXT).status_code == 200
            elif winner == "transcript":
                assert client.post(url(rdb, "/transcript"), json={
                    "text": "Synthetic changed transcript", "rev": report["rev"],
                }).status_code == 200
            else:
                version = report_store.current_version(report["id"])
                report_store.add_version(
                    report["id"], y4_ratings=version["y4_ratings"], evidence=version["evidence"],
                    ai_doc=version["ai_doc"], doc=version["doc"], checks=version["checks"],
                    manifest=version["manifest"], status="ai_draft", expected_rev=report["rev"])
        finally:
            release.set()
        assert loser.result().status_code == 409

    latest = report_store.get_report(prep_id)
    assert latest["rev"] == report["rev"] + 1
    assert (latest["status"] == "published") == (winner == "publish")
    with Session(rdb.engine) as sess:
        archived = sess.get(report_store.M1ReportOfficial, (report["id"], latest["rev"]))
        assert (archived is not None) == (winner == "publish")
    stale = _print(client, rdb, report)
    assert stale.status_code == 409
    assert b'id="print-error"' in stale.data and b"window.print()" not in stale.data
    shown = _print(client, rdb, latest)
    assert shown.status_code == 200
    assert (EDITED_TEXT.encode() in shown.data) == (winner == "document")


@pytest.mark.parametrize("authoritative_status", ["approved", "published"])
def test_official_archive_survives_reopen_and_plan_freshness_tracks_draft(
        client, rdb, fake, authoritative_status):
    generate(rdb)
    admin_login(client, rdb)
    prep = rdb.prep_row
    original = report_store.get_report(prep["id"])
    assert _edit(client, rdb, original, PUBLISHED_TEXT).status_code == 200
    reviewed = report_store.get_report(prep["id"])
    plan_store.ensure_tables(rdb.engine)
    plan = _create(rdb, prep, reviewed)
    fingerprint = plan["inputs"]["report_fingerprint"]
    assert fingerprint
    assert plan_store.report_state(plan)["fresh"]

    action = "publish" if authoritative_status == "published" else "approve"
    accepted = client.post(url(rdb, "/" + action), json=report_pin(reviewed))
    assert accepted.status_code == 200
    official = accepted.get_json()["report"]
    assert official["status"] == authoritative_status and official["rev"] == reviewed["rev"] + 1
    assert plan_store.report_state(plan)["fresh"]
    assert client.post(url(rdb, "/reopen"), json=report_pin(official)).status_code == 200
    reopened = report_store.get_report(prep["id"])
    assert reopened["status"] == "reviewing" and reopened["rev"] == official["rev"] + 1
    assert reopened["current_version_id"] == reviewed["current_version_id"]
    assert plan_store.report_state(plan)["fresh"]

    assert _edit(client, rdb, reopened, EDITED_TEXT).status_code == 200
    draft = report_store.get_report(prep["id"])
    assert not plan_store.report_state(plan)["fresh"]
    assert plan_store.get_plan(plan["id"])["inputs"]["report_fingerprint"] == fingerprint
    historical = _print(client, rdb, official)
    assert historical.status_code == 200 and PUBLISHED_TEXT.encode() in historical.data
    assert EDITED_TEXT.encode() not in historical.data and b'sheet draftmark' not in historical.data
    for latest in (_print(client, rdb, draft), _print(client, rdb)):
        assert latest.status_code == 200 and EDITED_TEXT.encode() in latest.data
        assert b'class="sheet draftmark"' in latest.data

    with Session(rdb.engine) as sess:
        archived = sess.get(report_store.M1ReportOfficial, (draft["id"], official["rev"]))
        assert archived.actor_id == rdb.admin_id
        stamped_at = official["published_at" if action == "publish" else "approved_at"]
        assert archived.official_at.isoformat() == stamped_at
        assert json.loads(archived.version)["doc"]["portrait"]["R1"]["text"] == PUBLISHED_TEXT
        assert json.loads(archived.print_content)["doc"]["portrait"]["R1"]["text"] == PUBLISHED_TEXT


def test_document_and_publish_compare_and_swap_after_both_read_same_revision(
        client, rdb, fake, monkeypatch):
    generate(rdb)
    prep_id = rdb.prep_row["id"]
    reviewed = report_store.get_report(prep_id)
    barrier = threading.Barrier(2)
    advance = report_store._advance

    def synchronize(sess, row, **kwargs):
        # Force both transactions to read the same revision before either UPDATE.
        assert row.rev == reviewed["rev"]
        barrier.wait(timeout=10)
        return advance(sess, row, **kwargs)

    monkeypatch.setattr(report_store, "_advance", synchronize)

    def competing_request(which):
        browser = client.application.test_client()
        admin_login(browser, rdb)
        if which == "publish":
            return browser.post(url(rdb, "/publish"), json=report_pin(reviewed))
        return _edit(browser, rdb, reviewed, EDITED_TEXT)

    with ThreadPoolExecutor() as pool:
        document = pool.submit(competing_request, "document")
        publish = pool.submit(competing_request, "publish")
        doc_status, publish_status = document.result().status_code, publish.result().status_code
    assert {doc_status, publish_status} == {200, 409}
    winner = report_store.get_report(prep_id)
    assert winner["rev"] == reviewed["rev"] + 1
    assert (winner["status"] == "published") == (publish_status == 200)
    admin_login(client, rdb)
    rendered = _print(client, rdb, winner)
    assert (EDITED_TEXT.encode() in rendered.data) == (doc_status == 200)
