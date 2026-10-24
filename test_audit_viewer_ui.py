"""B2 · Viewer 只读界面（工作台 / 首页 / 聊天 / 学生 360）。

Viewer 只有 GET 权限，前端不应渲染任何写操作入口：工作台隐藏保存 / 生成
按钮并本地切换阶段，首页隐藏导入与手动建档，聊天只保留历史记录。
"""
from __future__ import annotations

import re

import pytest
from flask import Flask, render_template

import app_utils
from blueprints import copilot as copilot_api

from test_copilot_routes import login_as, qdb  # noqa: F401

# 写操作按钮：@click 直接触发保存 / 生成 / 上传 / 删除等动作。
_WRITE_CLICK = re.compile(
    r'@click="(?:save|generate|regenerate|upload|add|remove|delete|confirm|'
    r'prepare|analyze|decide|send|stop|startSession|newChat|requestDelete)')


@pytest.fixture()
def client(qdb):
    app = Flask(__name__, template_folder=str(app_utils.TEMPLATE_DIR))
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True
    app.register_blueprint(copilot_api.bp)
    app_utils.register_admin_context(app)
    app.context_processor(lambda: {"csrf_token": app_utils.get_csrf_token})
    app.add_template_filter(app_utils.dt_short, "dt_short")
    return app.test_client()


def _login_viewer(client, qdb):
    login_as(client, qdb, role="viewer", advisor_name="",
             display_name="观察员", user_id=qdb.alice_id)


def _flat(html: str) -> str:
    return re.sub(r"\s+", "", html)


def _page(client, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200
    return response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# 工作台
# ---------------------------------------------------------------------------
def test_viewer_workspace_is_read_only(client, qdb):
    qdb.session(phase=0)
    _login_viewer(client, qdb)

    html = _page(client, f"/first-touch/students/{qdb.student_id}")
    flat = _flat(html)

    assert "只读查看" in html
    assert "最近编辑" in html
    assert '"readOnly":true' in flat
    assert '"canWrite":false' in flat
    assert '"role":"viewer"' in flat
    assert '"canStart":false' in flat
    assert '"steps":[' in flat
    assert ":disabled=\"readOnly\"" in html
    assert "is-readonly" in html
    assert "只读账号可查看历史对话，不能发起提问。" in html

    # 所有写操作按钮都必须带 x-show="canWrite" 或 :disabled，避免只读账号误触。
    for tag in re.findall(r"<button\b[^>]*>", html):
        if _WRITE_CLICK.search(tag):
            assert "canWrite" in tag or ":disabled=" in tag, tag


def test_viewer_workspace_without_session_shows_empty_state(client, qdb):
    _login_viewer(client, qdb)

    html = _page(client, f"/first-touch/students/{qdb.other_student_id}")
    flat = _flat(html)

    assert "该学生尚未开始 First Touch 会谈。" in html
    assert '"sessionId":null' in flat
    assert '"canStart":false' in flat


# ---------------------------------------------------------------------------
# 首页
# ---------------------------------------------------------------------------
def test_viewer_home_hides_management_actions(client, qdb):
    qdb.session()
    _login_viewer(client, qdb)

    html = _page(client, "/first-touch")

    assert ">查看</a>" in html
    assert "进入工作台" not in html


# ---------------------------------------------------------------------------
# 学生 360：First Touch 链接对 viewer 可见，归档仅管理员可见
# ---------------------------------------------------------------------------
def test_viewer_360_shows_first_touch_link_but_not_archive(qdb):
    app = Flask(__name__, template_folder=str(app_utils.TEMPLATE_DIR))
    app.config["SECRET_KEY"] = "test-secret"
    app_utils.register_admin_context(app)
    app.context_processor(lambda: {"csrf_token": app_utils.get_csrf_token})
    app.add_template_filter(app_utils.dt_short, "dt_short")
    profile = {
        "id": qdb.student_id, "student_code": "Y4-9201", "name": "林同学",
        "grade": "10", "school": "测试学校", "advisor_name": "Alice",
        "gender": "", "birthday": "",
    }

    with app.test_request_context("/students/Y4-9201"):
        html = render_template(
            "student_360.html", nav_active="students", profile=profile,
            can_write=False, is_admin=False, stage={}, stage_meta=[],
            gt_reports=[])

    assert "/first-touch/students/" in html
    assert "/first-touch/archive/" not in html
