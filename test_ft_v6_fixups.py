"""V6 · 端到端复查修复（AI 输出钳制、工作台交互、缺失项文案、360 时间）。"""
from __future__ import annotations

import re

import growth_talk_store as store
from growth_talk import copilot, copilot_report

from test_copilot_routes import (  # noqa: F401
    _inline_jobs, _ready_session, client, login_as, qdb,
)
from test_ft_v3_student360 import (  # noqa: F401
    _stub_progress, client as student360_client,
)

FIVE_LONG_ITEMS = ["验证" * 75 for _ in range(5)]


def _workspace_html(client, qdb) -> str:
    login_as(client, qdb)
    qdb.add_y4()
    qdb.session()
    response = client.get(f"/first-touch/students/{qdb.student_id}")
    assert response.status_code == 200
    return response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# 1. AI 输出钳制，而不是让整次生成失败
# ---------------------------------------------------------------------------
def test_supplement_job_clamps_ai_y4_validation(client, qdb, monkeypatch):
    _inline_jobs(monkeypatch)
    monkeypatch.setattr(copilot, "call_model", lambda _prompt: {
        "newInterests": [], "scoreConflicts": [], "questions": [],
        "y4Validation": FIVE_LONG_ITEMS,
    })
    login_as(client, qdb)
    session = _ready_session(qdb)

    response = client.post(
        f"/api/v2/copilot/sessions/{session['id']}/supplement",
        json={"revision": session["revision"]})

    assert response.status_code == 200
    job = client.get(
        f"/api/v2/copilot/jobs/{response.get_json()['jobId']}").get_json()
    assert job["status"] == "done"
    saved = store.get_session(session["id"])["supplements"][0]["analysis"]
    assert len(saved["y4Validation"]) == 3
    assert all(len(item) <= 100 for item in saved["y4Validation"])


def test_next_steps_clamps_overlong_ai_summary(qdb, monkeypatch):
    session = _ready_session(qdb)
    monkeypatch.setattr(copilot, "call_model",
                        lambda _prompt: {"summary": "后续继续观察。" * 400})

    summary = copilot.compute_next_steps(session["id"])

    assert summary.startswith("后续继续观察。")
    assert len(summary) == 1400


def _project_row(index: int) -> dict:
    return {
        "title": "很长的方案名称" * 20,
        "interestAnchor": "投篮训练" * 40,
        "interestRefs": ["i1"],
        "evidenceQuotes": ["每周训练篮球"],
        "fitType": "observation_research",
        "domains": ["运动"],
        "coreQuestion": "为什么喜欢投篮？" * 40,
        "example": "记录训练感受" * 40,
        "journeySummary": "持续观察" * 60,
        "whyThisProject": "会议证据支持",
        "minimumViableProject": "一周记录",
        "likelyOutputs": ["训练日志"],
        "expansionPath": ["分析比赛"],
        "openQuestions": ["时间安排"],
    }


def test_generated_projects_clamp_overlong_ai_fields(qdb, monkeypatch):
    session = _ready_session(qdb)
    monkeypatch.setattr(copilot, "call_model", lambda _prompt: {
        "recommendations": [_project_row(1), _project_row(2)],
    })

    batch = copilot.generate_projects(session["id"])

    item = batch["items"][0]
    assert len(item["title"]) <= 80
    assert len(item["interestAnchor"]) <= 120
    assert len(item["coreQuestion"]) <= 240
    assert len(item["example"]) <= 180
    assert len(item["journeySummary"]) <= 280


# ---------------------------------------------------------------------------
# 6. 页面只加载一次会话（Alpine 自动调用 init，不再重复 x-init）
# ---------------------------------------------------------------------------
def test_workspace_initializes_session_once(client, qdb):
    html = _workspace_html(client, qdb)

    assert 'x-init="init()"' not in html
    assert "init: function ()" in html
    assert html.count("        this.loadSession();") == 1
    assert html.count("await this.loadSession();") == 1


# ---------------------------------------------------------------------------
# 7. 第三步缺失项文案
# ---------------------------------------------------------------------------
def test_missing_report_fields_plain_labels(qdb):
    draft = {
        "student": {"grade": "10"},
        "interests": [
            {"id": f"i{index}", "label": label,
             "preferenceScore": 2, "competenceScore": 2}
            for index, label in enumerate(("篮球", "足球", "阅读"))
        ],
        "nextSummary": "本次会谈围绕兴趣展开，后续继续观察。",
        "projects": [],
        "y4Validation": [],
    }

    labels = {item["key"]: item["label"]
              for item in copilot_report.missing_report_fields(draft)}

    assert labels["meeting"] == "会议文字稿：未上传（可选）"
    assert labels["projects"] == "项目建议：未选择（可选，报告中不显示项目）"
    assert labels["y4-validation"] == "会议与 Y4 的对照：未填写（可选）"


# ---------------------------------------------------------------------------
# 2–5. 工作台交互标记
# ---------------------------------------------------------------------------
def test_workspace_step_two_focus_and_save_states(client, qdb):
    html = _workspace_html(client, qdb)
    flat = re.sub(r"\s+", " ", html)

    assert "focusAddInput" in html
    assert "this.$refs.addInput.focus()" in html

    assert "未保存 · 有冲突" in html
    assert "ft-save.warn" in html

    assert "rowClick($event, row)" in html
    assert '@dblclick.stop="beginRename(row)"' in html
    assert ':value="row.note" @click.stop' in flat

    assert "ft-pad-fab" in html
    assert "body.has-toast .ft-toastbar" in html


# ---------------------------------------------------------------------------
# 8. 学生 360 的确认时间按上海时区显示
# ---------------------------------------------------------------------------
def test_student360_confirmed_at_uses_shanghai_formatter(student360_client,
                                                         qdb, _stub_progress):
    login_as(student360_client, qdb)

    response = student360_client.get("/students/Y4-9201")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "fmtFTTime(r.confirmedAt)" in html
    assert "timeZone: 'Asia/Shanghai'" in html
