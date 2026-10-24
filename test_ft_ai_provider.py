"""First Touch AI provider（DashScope）测试，全程 mock urllib，不联网。"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

import extract
from growth_talk import analysis

_ENV_NAMES = ("FT_LLM_API_KEY", "FT_LLM_BASE_URL", "FT_LLM_MODEL", "DASHSCOPE_API_KEY")


def _clear_env(monkeypatch):
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


@pytest.fixture()
def requests(monkeypatch):
    captured = []

    def fake_urlopen(request, timeout=None):
        captured.append((request, timeout))
        return FakeResponse({
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": '{"ok": true}'},
            }],
        })

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return captured


def test_defaults_to_dashscope_with_builtin_key(monkeypatch, requests):
    _clear_env(monkeypatch)
    assert analysis.call_model("prompt") == {"ok": True}
    request, timeout = requests[0]
    assert request.full_url == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    body = json.loads(request.data.decode("utf-8"))
    assert body["model"] == "qwen-plus"
    assert body["temperature"] == 0.1
    assert body["response_format"] == {"type": "json_object"}
    assert request.get_header("Authorization") == "Bearer " + extract.DEFAULT_DASHSCOPE_KEY
    assert timeout == 90


def test_dashscope_key_and_ft_key_override(monkeypatch, requests):
    _clear_env(monkeypatch)

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-a")
    analysis.call_model("prompt")
    assert requests[-1][0].get_header("Authorization") == "Bearer test-a"

    monkeypatch.setenv("FT_LLM_API_KEY", "test-b")
    analysis.call_model("prompt")
    assert requests[-1][0].get_header("Authorization") == "Bearer test-b"


def test_model_and_base_url_overrides(monkeypatch, requests):
    _clear_env(monkeypatch)
    monkeypatch.setenv("FT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("FT_LLM_MODEL", "qwen-max")
    monkeypatch.setenv("FT_LLM_BASE_URL", "https://example.test/v1/")

    analysis.call_model("prompt")
    request, _timeout = requests[-1]
    assert request.full_url == "https://example.test/v1/chat/completions"
    assert json.loads(request.data.decode("utf-8"))["model"] == "qwen-max"
    assert analysis.model_name() == "qwen-max"


def test_model_name_default(monkeypatch):
    monkeypatch.delenv("FT_LLM_MODEL", raising=False)
    assert analysis.model_name() == "qwen-plus"


def test_missing_key_message(monkeypatch, requests):
    _clear_env(monkeypatch)
    monkeypatch.setattr(extract, "DEFAULT_DASHSCOPE_KEY", "")
    with pytest.raises(analysis.AnalysisError, match="AI 服务未配置"):
        analysis.call_model("prompt")
    assert requests == []


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (401, "AI 服务密钥无效或无权限（401）"),
        (403, "AI 服务密钥无效或无权限（403）"),
        (429, "AI 服务繁忙，请稍后重试"),
        (500, "画像分析服务返回 500"),
    ],
)
def test_http_error_messages(monkeypatch, code, message):
    _clear_env(monkeypatch)
    monkeypatch.setenv("FT_LLM_API_KEY", "test-key")

    def fail(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://example.test", code, "err", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(analysis.AnalysisError) as excinfo:
        analysis.call_model("prompt")
    assert str(excinfo.value) == message
