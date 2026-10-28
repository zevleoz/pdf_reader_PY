"""/api/v1/reports/<id>/e4-protocol 的缓存：AI 步骤失败的协议不缓存。

背景：qwen-turbo 在项目 Key 上持续 429，Step2 失败后协议里没有「判断：」，
E4 会前准备第三列全空；这份残缺协议还被缓存 10 分钟，重试也拿到同一份。
"""
from __future__ import annotations

import pytest
from flask import Flask

HEADERS = {"Authorization": "Bearer test-api-key-0123456789abcdef"}


@pytest.fixture()
def api(monkeypatch):
    from blueprints import api_v1

    monkeypatch.setattr(api_v1, "Y4_API_KEY", "test-api-key-0123456789abcdef")
    monkeypatch.setattr(api_v1, "_v1_rate_check", lambda *a, **kw: True)
    monkeypatch.setattr(api_v1, "_report_qualification_payload", lambda rid: (
        {"items": [], "student": {"name": "测"}, "report": {"student_name": "测", "interpretation": ""}},
        None,
    ))
    api_v1._E4_CACHE.clear()
    calls = {"n": 0, "step2_error": None}

    def fake_core(*_a, **_kw):
        calls["n"] += 1
        step2 = {"dim": "ALL", "model": "m"}
        if calls["step2_error"]:
            step2["error"] = calls["step2_error"]
        return {"ok": True, "content_md": f"# 协议 {calls['n']}",
                "stats": {"step2": [step2], "step3": {"model": "m"}}}

    monkeypatch.setattr(api_v1, "_generate_e4_protocol_core", fake_core)
    app = Flask(__name__)
    app.register_blueprint(api_v1.bp)
    yield app.test_client(), calls
    api_v1._E4_CACHE.clear()


def test_step2_failure_is_not_cached(api):
    client, calls = api
    calls["step2_error"] = "HTTP Error 429: Too Many Requests"
    first = client.get("/api/v1/reports/7/e4-protocol", headers=HEADERS)
    second = client.get("/api/v1/reports/7/e4-protocol", headers=HEADERS)
    assert first.status_code == 200
    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "MISS"
    assert calls["n"] == 2


def test_successful_protocol_is_cached(api):
    client, calls = api
    first = client.get("/api/v1/reports/7/e4-protocol", headers=HEADERS)
    second = client.get("/api/v1/reports/7/e4-protocol", headers=HEADERS)
    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"
    assert second.data.decode("utf-8") == "# 协议 1"
    assert calls["n"] == 1


def test_step2_default_model_is_not_the_blocked_qwen_turbo():
    import inspect
    import ai_client

    src = inspect.getsource(ai_client._generate_e4_protocol_core)
    assert '"E4_STEP2_MODEL", "qwen-flash"' in src
