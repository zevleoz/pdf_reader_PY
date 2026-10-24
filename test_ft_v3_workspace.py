"""V4b · 三步会谈工作台：渲染与标记断言。

复用 ``test_copilot_routes.py`` 的 Flask/DB fixture，只检查服务端渲染出的
HTML/JS 是否具备新工作台的结构，不启动浏览器。
"""
from __future__ import annotations

import re

from test_copilot_routes import client, login_as, qdb  # noqa: F401


def _flat(html: str) -> str:
    return re.sub(r"\s+", "", html)


def _workspace(client, qdb, *, role="advisor", advisor_name="Alice") -> str:
    login_as(client, qdb, role=role, advisor_name=advisor_name,
             display_name="观察员" if role == "viewer" else advisor_name)
    response = client.get(f"/first-touch/students/{qdb.student_id}")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _with_session(client, qdb, **kwargs) -> str:
    qdb.add_y4()
    qdb.session()
    return _workspace(client, qdb, **kwargs)


# ---------------------------------------------------------------------------
# 三步结构与已删除的旧界面
# ---------------------------------------------------------------------------
def test_three_step_labels_and_no_removed_ui(client, qdb):
    html = _workspace(client, qdb)

    assert "会前 · Y4 速览" in html
    assert "会谈中 · 兴趣记录" in html
    assert "会后 · 整理与报告" in html

    assert "entryScreen" not in html
    assert "v2-entry-choice" not in html
    assert "修订" not in html
    for removed in ("目标说明", "Y4 结果解读", "总结与下一步",
                    "会议目标", "开场说明", "Y4 解读顺序", "职业校准"):
        assert removed not in html


def test_no_removed_endpoints_are_referenced(client, qdb):
    html = _with_session(client, qdb)

    for path in ("y4-calibrate", "career-calibration", "report-prepare",
                 "report-pdf", "/first-touch/copilot"):
        assert path not in html

    for path in ("/interest-draft", "/talking-points", "/next-steps",
                 "/report-preview", "/report-confirm", "/supplement",
                 "/sources", "/assistant", "/copilot/chats"):
        assert path in html


# ---------------------------------------------------------------------------
# 会谈中：两套 – 0 1 2 3 评分控件与 4×4 象限板
# ---------------------------------------------------------------------------
def test_score_controls_cover_waiting_and_zero_to_three(client, qdb):
    html = _with_session(client, qdb)

    # 喜欢 / 擅长 各一组：待评（–）与 0–3 点按
    assert html.count(">–</button>") == 2
    assert html.count('title="待评"') == 2
    assert html.count('x-for="value in [0, 1, 2, 3]"') == 2

    assert "'不喜欢', '一般', '喜欢', '非常喜欢'" in html
    assert "'不擅长', '一般', '擅长', '非常擅长'" in html


def test_interest_board_is_four_by_four_and_hides_unscored(client, qdb):
    html = _with_session(client, qdb)

    assert 'x-for="good in [3, 2, 1, 0]"' in html
    assert 'x-for="like in [0, 1, 2, 3]"' in html
    assert "喜欢且擅长" in html
    assert "待评事项不进图" in html
    assert "项已评分" in html


# ---------------------------------------------------------------------------
# 自动保存 / 冲突 / 计时器 / 键盘
# ---------------------------------------------------------------------------
def test_autosave_conflict_and_local_timer_markup(client, qdb):
    html = _with_session(client, qdb)

    assert "已自动保存" in html
    assert "正在保存…" in html
    assert "保存失败，点此重试" in html
    assert "saveDebounce: 800" in html
    assert "其他人刚更新了这次会谈" in html
    assert "载入最新" in html
    assert "beforeunload" in html
    assert "会谈 ' + elapsed" in html
    assert "keydown.escape.window" in html


# ---------------------------------------------------------------------------
# 日期时间 / 步进器 / 会后确认
# ---------------------------------------------------------------------------
def test_meeting_time_and_report_confirmation_markup(client, qdb):
    html = _with_session(client, qdb)

    assert 'type="datetime-local"' in html
    assert 'step="900"' in html
    assert "stepLabels" in html
    assert "确认并生成报告" in html
    assert "下载 PDF" in html and "下载 JSON" in html
    assert "在学生 360 查看" in html
    assert "已过期，需重新生成" in html


# ---------------------------------------------------------------------------
# Viewer：只读标记与空状态
# ---------------------------------------------------------------------------
def test_viewer_sees_read_only_badge_and_disabled_controls(client, qdb):
    qdb.add_y4()
    qdb.session()
    html = _workspace(client, qdb, role="viewer", advisor_name="")
    flat = _flat(html)

    assert "只读查看" in html
    assert "最近编辑" in html
    assert '"readOnly":true' in flat
    assert '"canWrite":false' in flat
    assert '"role":"viewer"' in flat
    assert '"steps":[' in flat
    assert ':disabled="readOnly"' in html
    assert "is-readonly" in html
    assert "只读账号可查看历史对话，不能发起提问。" in html


def test_workspace_without_session_shows_empty_state(client, qdb):
    login_as(client, qdb, role="viewer", advisor_name="",
             display_name="观察员", user_id=qdb.alice_id)

    response = client.get(f"/first-touch/students/{qdb.other_student_id}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "该学生尚未开始 First Touch 会谈。" in html
    assert '"sessionId":null' in _flat(html)
    assert "entryScreen" not in html
