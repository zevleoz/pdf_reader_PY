"""Partner credential rotation, scope isolation and fail-closed configuration."""
import hashlib
import json

import pytest
from flask import Flask, g, jsonify

import partner_auth


@pytest.fixture()
def service(monkeypatch):
    monkeypatch.delenv("Y4_PARTNERS_JSON", raising=False)
    monkeypatch.delenv("Y4_PARTNERS_FILE", raising=False)
    monkeypatch.delenv("Y4_API_KEY", raising=False)
    app = Flask(__name__)

    @app.get("/book")
    @partner_auth.require_partner("booking")
    def book():
        return jsonify(partner_id=g.partner_id, scopes=sorted(g.partner_scopes))

    @app.get("/either")
    @partner_auth.require_partner("booking", "results")
    def either():
        return jsonify(partner_id=g.partner_id, scopes=sorted(g.partner_scopes))

    return app.test_client()


def credential(token, scope):
    return {"sha256": hashlib.sha256(token.encode()).hexdigest(), "scopes": [scope]}


def partner(partner_id, *credentials):
    return {
        "id": partner_id,
        "enabled": True,
        "scopes": ["booking", "results"],
        "credentials": list(credentials),
    }


def call(service, path, token=None, secure=True):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return service.get(path, base_url="https://test.example" if secure else "http://test.example", headers=headers)


def test_each_credential_has_its_own_scope_and_partner(service, monkeypatch):
    booking, results, other = "B" * 43, "R" * 43, "O" * 43
    monkeypatch.setenv("Y4_PARTNERS_JSON", json.dumps([
        partner("one", credential(booking, "booking"), credential(results, "results")),
        partner("two", credential(other, "booking")),
    ]))
    assert call(service, "/book", booking).get_json() == {"partner_id": "one", "scopes": ["booking"]}
    assert call(service, "/book", results).status_code == 403
    assert call(service, "/either", results).get_json() == {"partner_id": "one", "scopes": ["results"]}
    assert call(service, "/book", other).get_json() == {"partner_id": "two", "scopes": ["booking"]}
    assert call(service, "/book", booking, secure=False).status_code == 400
    assert call(service, "/book", "U" * 43).status_code == 401


def test_rotating_config_file_revokes_an_old_credential_without_restart(service, tmp_path, monkeypatch):
    old, new = "B" * 43, "C" * 43
    config = tmp_path / "partners.json"
    monkeypatch.setenv("Y4_PARTNERS_FILE", str(config))

    def set_config(*credentials, enabled=True):
        update = tmp_path / "partners.next"
        row = partner("one", *credentials)
        row["enabled"] = enabled
        update.write_text(json.dumps([row]), encoding="utf-8")
        update.replace(config)

    assert call(service, "/book", old).status_code == 503
    set_config(credential(old, "booking"), credential(new, "booking"))
    assert call(service, "/book", old).status_code == 200
    assert call(service, "/book", new).status_code == 200
    set_config(credential(new, "booking"))
    assert call(service, "/book", old).status_code == 401
    assert call(service, "/book", new).status_code == 200
    set_config(credential(new, "booking"), enabled=False)
    assert call(service, "/book", new).status_code == 401
    assert partner_auth.get_partner("one") is None


def test_disabled_by_default_and_rejects_global_or_duplicate_credentials(service, monkeypatch):
    shared = "S" * 43
    assert call(service, "/book", shared).status_code == 503
    monkeypatch.setenv("Y4_API_KEY", shared)
    config = [partner("one", credential(shared, "booking"))]
    monkeypatch.setenv("Y4_PARTNERS_JSON", json.dumps(config))
    assert call(service, "/book", shared).status_code == 503
    monkeypatch.delenv("Y4_API_KEY")
    config.append(partner("two", credential(shared, "booking")))
    monkeypatch.setenv("Y4_PARTNERS_JSON", json.dumps(config))
    assert call(service, "/book", shared).status_code == 503


@pytest.mark.parametrize("callback", [
    "http://partner.example/callback",
    "https://user@partner.example/callback",
    "https://partner.example:8443/callback",
    "https://partner.example/callback#fragment",
])
def test_invalid_callback_configuration_is_unavailable(service, monkeypatch, callback):
    token = "R" * 43
    row = partner("one", credential(token, "results"))
    row.update(callback_url=callback, webhook_secret="synthetic-secret-" * 3)
    monkeypatch.setenv("Y4_PARTNERS_JSON", json.dumps([row]))
    assert call(service, "/either", token).status_code == 503
    assert partner_auth.get_partner("one") is None
