"""Focused checks for the allowlisted Y4 projection and webhook transport."""
from datetime import datetime
import hashlib
import hmac
import json
import socket
from types import SimpleNamespace

import pytest

import partner_results as results


def test_snapshot_reuses_y4_and_only_emits_granted_indicator_fields():
    raw = {
        "student": {
            "name": "Synthetic Youth", "school": "Private School", "test_date": "2026-11-23",
        },
        "schema_124": [
            {"code": "068", "label": "学习动机-自我效能感", "type": "number",
             "value": "72", "note": "Internal note"},
            {"code": "071", "label": "学习方法与策略-学习自我调节", "type": "number", "value": "64"},
            {"code": "100", "label": "职业价值观-成就感", "type": "number", "value": "82"},
        ],
    }
    scope = results._approved_scope({"068": ["value"]}, False)
    expected = {"indicators": [{"code": "068", "value": 72}]}
    assert results._snapshot(raw, scope) == expected
    scope["include_assessment_date"] = True
    assert results._snapshot(raw, scope) == {**expected, "assessment_date": "2026-11-23"}
    with pytest.raises(results.ReleaseError):
        results._snapshot(raw, results._approved_scope({"100": ["value"]}, False))
    with pytest.raises(results.ReleaseError):
        results._approved_scope({"068": ["note"]}, False)


def _dns_answer(ip):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443))


@pytest.mark.parametrize("address", ["127.0.0.1", "::1", "169.254.169.254", "10.1.2.3",
                                     "::ffff:127.0.0.1", "224.0.0.1", "64:ff9b::a00:1"])
def test_callback_rejects_dns_answers_with_any_nonpublic_address(monkeypatch, address):
    monkeypatch.setattr(results.socket, "getaddrinfo",
                        lambda *args, **kwargs: [_dns_answer("8.8.8.8"), _dns_answer(address)])
    with pytest.raises(ValueError, match="non-public"):
        results._public_callback_target("https://receiver.example.test/results")


@pytest.mark.parametrize("url", ["http://receiver.example.test", "https://host:8443",
                                 "https://user@host", "https://host/path#fragment"])
def test_invalid_callback_urls_fail_before_dns(monkeypatch, url):
    def lookup(*args, **kwargs):
        pytest.fail("Callback must be rejected before DNS")
    monkeypatch.setattr(results.socket, "getaddrinfo", lookup)
    with pytest.raises(ValueError, match="Invalid HTTPS"):
        results._public_callback_target(url)


def test_callback_pins_dns_signs_raw_body_and_does_not_follow_redirect(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 23, 12, tzinfo=tz)

    requests = []

    class TestConnection:
        def __init__(self, hostname, address):
            assert hostname == "receiver.example.test"
            assert address == "8.8.8.8"

        def request(self, method, target, *, body, headers):
            requests.append((method, target, body, headers))

        def getresponse(self):
            from contextlib import nullcontext
            return nullcontext(SimpleNamespace(status=307))

        def close(self):
            pass

    monkeypatch.setattr(results, "datetime", FixedDateTime)
    monkeypatch.setattr(results.socket, "getaddrinfo", lambda *a, **k: [_dns_answer("8.8.8.8")])
    monkeypatch.setattr(results, "_PinnedHTTPSConnection", TestConnection)
    body = json.dumps({"external_reservation_id": "预约01"}, ensure_ascii=False).encode("utf-8")
    assert not results._send_callback("https://receiver.example.test/hook?channel=y4", "secret", body)
    [(method, target, transmitted, headers)] = requests
    assert (method, target, transmitted) == ("POST", "/hook?channel=y4", body)
    signed_data = headers["X-Y4-Event-Timestamp"].encode("ascii") + b"." + body
    signature = hmac.new(b"secret", signed_data, hashlib.sha256).hexdigest()
    assert headers["X-Y4-Event-Signature"] == f"sha256={signature}"
