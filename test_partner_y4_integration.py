"""Run Plan G with two fictional partners and the real application blueprints."""
from datetime import datetime, timedelta
from hashlib import sha256
import json
import re
from zoneinfo import ZoneInfo

import pytest

import db
import y4_upload


PARTNER_API = "/api/partners/v1/y4"
INTERNAL_API = "/api/internal/partners/v1/y4"
HTTPS = "https://research.example"
FICTIONAL_NAME = "联调同名学生"


@pytest.fixture()
def integration(monkeypatch):
    import app_utils
    from app import create_app

    monkeypatch.setattr(app_utils, "_SESSION_USER_CACHE", {})
    monkeypatch.delenv("Y4_PARTNERS_FILE", raising=False)
    keys = {
        ("partner-a", "booking"): "A" * 43,
        ("partner-a", "results"): "B" * 43,
        ("partner-b", "booking"): "C" * 43,
        ("partner-b", "results"): "D" * 43,
    }
    records = [{
        "id": partner,
        "enabled": True,
        "scopes": ["booking", "results"],
        "credentials": [
            {"sha256": sha256(keys[partner, scope].encode()).hexdigest(), "scopes": [scope]}
            for scope in ("booking", "results")
        ],
        "callback_url": f"https://{partner}.example/y4",
        "webhook_secret": "synthetic-test-secret-" + partner + "-fixture",
    } for partner in ("partner-a", "partner-b")]
    monkeypatch.setenv("Y4_PARTNERS_JSON", json.dumps(records))
    application = create_app()
    application.config["TESTING"] = True
    location = db.get_default_location_id()
    admin_id = db.create_user("partner-e2e-admin", "fixture-pass", "admin")
    assessor = db.create_user("partner-e2e-assessor", "fixture-pass", "advisor",
                              advisor_name="联调测评师", is_assessor=1, office_id=location)
    staff, external = application.test_client(), application.test_client()
    with staff.session_transaction(base_url=HTTPS) as state:
        state.update(user_id=admin_id, role="admin")
    shell = staff.get("/app/workbench", base_url=HTTPS)
    csrf = re.search(r'<meta name="csrf-token" content="([^"]+)">', shell.get_data(as_text=True))
    assert csrf

    def request(method, path, partner, scope, data=None):
        return external.open(PARTNER_API + path, method=method, base_url=HTTPS, json=data,
                             headers={"Authorization": "Bearer " + keys[partner, scope]})

    return staff, {"X-CSRF-Token": csrf[1]}, request, location, assessor


def _stored_round(tmp_path, student_id, value, *, reviewed=True):
    date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    path = tmp_path / f"transport-fixture-{value}.pdf"
    path.write_bytes(b"%PDF-1.4 synthetic readiness fixture")
    raw = {
        "student": {"name": FICTIONAL_NAME, "test_date": date.isoformat()},
        "pdf_titles": ["A2"],
        "schema_124": [
            {"code": "100", "label": "联调指标", "value": value, "unit": "分", "note": "内部备注"},
            {"code": "101", "label": "未批准指标", "value": 99},
        ],
    }
    report_id = db.add_report(student_id, date, str(path), json.dumps(raw, ensure_ascii=False))
    db.save_interpretation(report_id, "虚构解读，仅供测试")
    if reviewed:
        db.add_minutes(student_id, report_id, "虚构原始纪要", "虚构解读会纪要")
    state = y4_upload._blank_state()
    state["slots"]["A2"].update(state="done", has_data=True, read_at="2026-01-01T09:00:00Z")
    state["build"].update(
        state="done", v2_path=str(path), student_name=FICTIONAL_NAME, built_at="2026-01-01T10:00:00Z",
    )
    return y4_upload.create_round(student_id, "partner-e2e", report_id, state), report_id


def test_two_partner_reservation_release_and_revocation(integration, tmp_path, monkeypatch):
    import partner_reservations
    import partner_results

    staff, csrf, request, location, assessor = integration
    tomorrow = (datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(days=1)).date()
    payload = {
        "external_reservation_id": "ext-0001", "external_student_id": "external-student-1",
        "student_name": FICTIONAL_NAME, "location_id": location,
        "appointment_time": f"{tomorrow}T09:00:00+08:00",
    }
    path = "/reservations"
    a = request("POST", path, "partner-a", "booking", payload)
    b = request("POST", path, "partner-b", "booking", {
        **payload, "appointment_time": f"{tomorrow}T09:30:00+08:00",
    })
    assert a.status_code == b.status_code == 201
    a_id, b_id = a.json["id"], b.json["id"]
    assert request("POST", path, "partner-a", "booking", payload).json["id"] == a_id
    assert request("POST", path, "partner-a", "booking", {**payload, "student_name": "改名"}).status_code == 409
    assert request("POST", path, "partner-a", "results", payload).status_code == 403
    assert a.headers["Cache-Control"] == "no-store"

    first = partner_reservations.get_reservation("partner-a", a_id)
    second = partner_reservations.get_reservation("partner-b", b_id)
    assert first["student_id"] != second["student_id"]
    code = db.get_student(first["student_id"])["student_code"]
    queue = staff.get("/api/profiling/workbench", base_url=HTTPS).json["upcoming"]
    matching = next(item for item in queue if item["booking_id"] == first["booking_id"])
    assert matching["student_code"] == code and matching["source"] == "partner"
    assigned = staff.post(f"/api/booking/{first['booking_id']}/assign", base_url=HTTPS,
                          headers=csrf, json={"assessor_id": assessor})
    assert assigned.status_code == 200, assigned.json
    assigned_b = staff.post(f"/api/booking/{second['booking_id']}/assign", base_url=HTTPS,
                            headers=csrf, json={"assessor_id": assessor})
    assert assigned_b.status_code == 200, assigned_b.json
    schedule = staff.get(f"/api/profiling/students/{code}/schedule", base_url=HTTPS)
    assert schedule.status_code == 200 and schedule.json["bookings"][0]["assessor_id"] == assessor
    assert request("GET", f"{path}/{a_id}", "partner-a", "results").json["current_result_version"] is None
    assert request("GET", f"{path}/{a_id}/results/unreleased", "partner-a", "results").status_code == 404

    round_id, report_id = _stored_round(tmp_path, first["student_id"], 7, reviewed=False)
    approval = {
        "partner_id": "partner-a", "round_id": round_id, "report_id": report_id,
        "approval_reference": "SYNTHETIC-GRANT-0001", "fields": {"100": ["value"]},
        "include_assessment_date": False,
    }
    releases = f"{INTERNAL_API}/reservations/{a_id}/releases"
    assert staff.post(releases, base_url=HTTPS, json=approval).status_code == 403
    unready = staff.post(releases, base_url=HTTPS, headers=csrf, json=approval)
    assert unready.status_code == 409 and unready.json["code"] == "RESULT_NOT_READY"
    db.add_minutes(first["student_id"], report_id, "虚构原始纪要", "虚构解读会纪要")
    published = staff.post(releases, base_url=HTTPS, headers=csrf, json=approval)
    assert published.status_code == 201, published.json
    v1 = published.json["version"]
    replay = staff.post(releases, base_url=HTTPS, headers=csrf, json=approval)
    assert replay.status_code == 200 and replay.json["version"] == v1
    result_uri = f"{path}/{a_id}/results/{v1}"
    assert request("GET", result_uri, "partner-b", "results").status_code == 404
    assert request("GET", result_uri, "partner-a", "booking").status_code == 403
    result = request("GET", result_uri, "partner-a", "results")
    assert result.status_code == 200 and result.json["result"]["indicators"] == [{"code": "100", "value": 7}]

    b_releases = f"{INTERNAL_API}/reservations/{b_id}/releases"
    b_approval = {**approval, "partner_id": "partner-b", "approval_reference": "SYNTHETIC-GRANT-B"}
    assert staff.post(b_releases, base_url=HTTPS, headers=csrf, json=b_approval).status_code == 404
    b_round, b_report = _stored_round(tmp_path, second["student_id"], 9)
    b_approval.update(round_id=b_round, report_id=b_report)
    b_published = staff.post(b_releases, base_url=HTTPS, headers=csrf, json=b_approval)
    assert b_published.status_code == 201, b_published.json
    b_version = b_published.json["version"]
    b_result = request("GET", f"{path}/{b_id}/results/{b_version}", "partner-b", "results")
    assert b_result.json["result"]["indicators"] == [{"code": "100", "value": 9}]
    assert request("GET", f"{path}/{b_id}/results/{b_version}", "partner-a", "results").status_code == 404

    third = request("POST", path, "partner-a", "booking", {
        **payload, "external_reservation_id": "ext-0002", "appointment_time": f"{tomorrow}T11:00:00+08:00",
    })
    assert third.status_code == 201
    c_id = third.json["id"]
    assert partner_reservations.get_reservation("partner-a", c_id)["student_id"] == first["student_id"]
    next_round, next_report = _stored_round(tmp_path, first["student_id"], 8)
    c_releases = f"{INTERNAL_API}/reservations/{c_id}/releases"
    next_approval = {**approval, "round_id": next_round, "report_id": next_report,
                     "approval_reference": "SYNTHETIC-GRANT-0002"}
    assert staff.post(releases, base_url=HTTPS, headers=csrf, json=next_approval).status_code == 409
    published = staff.post(c_releases, base_url=HTTPS, headers=csrf, json=next_approval)
    assert published.status_code == 201, published.json
    v2 = published.json["version"]
    assert request("GET", f"{path}/{a_id}/results/{v2}", "partner-a", "results").status_code == 404
    result = request("GET", f"{path}/{c_id}/results/{v2}", "partner-a", "results")
    assert result.json["result"]["indicators"] == [{"code": "100", "value": 8}]
    assert request("GET", result_uri, "partner-a", "results").json["result"]["indicators"][0]["value"] == 7

    with db.Session(db.engine) as session:
        report = session.get(db.Report, report_id)
        raw = json.loads(report.data_json)
        raw["schema_124"][0]["value"] = 12
        report.data_json = json.dumps(raw, ensure_ascii=False)
        session.commit()
    correction = staff.post(releases, base_url=HTTPS, headers=csrf,
                            json={**approval, "approval_reference": "SYNTHETIC-GRANT-CORRECTED"})
    assert correction.status_code == 201, correction.json
    corrected = correction.json["version"]
    assert request("GET", f"{path}/{a_id}/results/{corrected}", "partner-a", "results").json["result"]["indicators"] == [
        {"code": "100", "value": 12},
    ]
    assert request("GET", result_uri, "partner-a", "results").json["result"]["indicators"][0]["value"] == 7
    assert staff.delete(releases + "/" + corrected, base_url=HTTPS, headers=csrf,
                        json={"partner_id": "partner-a"}).status_code == 200

    # Fail the first callback for A's first release, then retry the same immutable event.
    sent = []
    now = partner_results._now()

    def send(url, _secret, body):
        event = json.loads(body)
        expected = "partner-b" if event["version"] == b_version else "partner-a"
        assert url == f"https://{expected}.example/y4"
        assert set(event) == {"type", "event_id", "reservation_id", "external_reservation_id", "version"}
        sent.append(event)
        if event["version"] == v1 and sum(item["version"] == v1 for item in sent) == 1:
            raise TimeoutError("synthetic timeout")
        return True

    monkeypatch.setattr(partner_results, "_send_callback", send)
    partner_results.deliver_due()
    monkeypatch.setattr(partner_results, "_now", lambda: now + timedelta(minutes=2))
    partner_results.deliver_due()
    first_attempts = [item["event_id"] for item in sent if item["version"] == v1]
    assert len(first_attempts) == 2 and first_attempts[0] == first_attempts[1]
    assert sum(item["version"] == b_version for item in sent) == 1
    assert all(item["version"] != corrected for item in sent)
    revoked = staff.delete(releases + "/" + v1, base_url=HTTPS, headers=csrf,
                           json={"partner_id": "partner-a"})
    assert revoked.status_code == 200, revoked.json
    assert request("GET", result_uri, "partner-a", "results").status_code == 404
    assert request("GET", f"{path}/{a_id}", "partner-a", "results").json["current_result_version"] is None
