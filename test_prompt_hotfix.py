"""H1：实时提示词热修复。

覆盖三件事：删掉写在提示词里的示例学生数据、降低两处温度、保证
提示词格式化仍然可用。全程不联网。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from flask import Flask

import app_utils
from blueprints import reports as reports_bp
from blueprints import tools as tools_bp
from m1.prompts import MEETING_PLAN_PROMPT

BASE_DIR = Path(__file__).resolve().parent
INTERPRETER_PROMPT = BASE_DIR / "prompts" / "ai_interpreter.md"
M1_PROMPTS = BASE_DIR / "m1" / "prompts.py"

FORMAT_SLOT_LINE = (
    "以上只说明数据格式。解读中出现的每个数值、类型和排序，"
    "都必须来自下方“Y4 有效评价数据”；数据里没有的指标不要写。"
)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _capture_requests(monkeypatch, module):
    captured = []

    def fake_urlopen(req, timeout=None):
        captured.append(req)
        return FakeResponse({
            "choices": [{"message": {"content": "ok"}}],
        })

    monkeypatch.setattr(module, "urlopen_with_retry", fake_urlopen)
    return captured


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    app = Flask(__name__, template_folder=str(app_utils.TEMPLATE_DIR))
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True
    app.register_blueprint(tools_bp.bp)
    app.register_blueprint(reports_bp.bp)
    with app.test_client() as test_client:
        with test_client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "admin"
        yield test_client


def test_interpreter_prompt_has_no_example_values():
    text = INTERPRETER_PROMPT.read_text(encoding="utf-8")
    for forbidden in ("9.5", "8.6", "工作环境", "7.1", "感知觉 99"):
        assert forbidden not in text
    assert FORMAT_SLOT_LINE in text


def test_m1_prompts_have_no_example_student_facts():
    text = M1_PROMPTS.read_text(encoding="utf-8")
    for forbidden in ("期中数学", "10 月中旬", "回家不怎么说话"):
        assert forbidden not in text


def test_api_transcript_sends_temperature_0_2(client, monkeypatch):
    captured = _capture_requests(monkeypatch, tools_bp)
    resp = client.post(
        "/api/transcript",
        json={"transcript": "这是一段用于测试的会议转写内容，" * 10},
    )
    assert resp.status_code == 200
    body = json.loads(captured[0].data.decode("utf-8"))
    assert body["temperature"] == 0.2


def test_api_chat_sends_temperature_0_2(client, monkeypatch):
    captured = _capture_requests(monkeypatch, reports_bp)
    resp = client.post("/api/chat", json={"message": "你好"})
    assert resp.status_code == 200
    body = json.loads(captured[0].data.decode("utf-8"))
    assert body["temperature"] == 0.2


def test_meeting_plan_prompt_formats_with_expected_arguments():
    rendered = MEETING_PLAN_PROMPT % (60, 2, "写作风格", "[]", "[]", "[]")
    assert "%s" not in rendered
