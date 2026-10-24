"""C1 · 管理端壳：顶栏响应式、toast 位置、只读角色的 First Touch 导航。

审计条目：F7（768–1100px 面包屑/徽章逐字换行）、F8（toast 遮挡浮动聊天按钮）。
"""
from __future__ import annotations

from pathlib import Path

import app_utils
from test_copilot_routes import client, login_as, qdb  # noqa: F401

CSS = Path(__file__).with_name("static") / "admin_v2.css"


def _css() -> str:
    return CSS.read_text(encoding="utf-8")


def _crumb_block(css: str) -> str:
    start = css.index(".crumb {")
    return css[start:css.index("}", start) + 1]


def test_topbar_actions_area_precedes_search(client, qdb):
    login_as(client, qdb)
    html = client.get("/first-touch").get_data(as_text=True)
    assert '<div class="topbar-actions">' in html
    start = html.index('<div class="topbar-actions">')
    end = html.index("</div>", start)
    actions = html[start:end]
    # 已移除的导入 / 手动建档入口不再出现在顶栏
    assert "从 Y4 导入" not in actions
    assert "手动添加学生" not in actions
    # 操作区在搜索框之前、面包屑之后
    assert html.index('class="crumb"') < start < html.index('class="search-trigger"')


def test_crumb_is_single_line_with_ellipsis():
    crumb = _crumb_block(_css())
    assert "min-width: 0" in crumb
    assert "overflow: hidden" in crumb
    assert "text-overflow: ellipsis" in crumb
    assert "white-space: nowrap" in crumb


def test_role_badge_and_user_name_do_not_wrap():
    css = _css()
    pill = css[css.index(".role-pill {"):]
    pill = pill[:pill.index("}") + 1]
    who = css[css.index(".topbar .who {"):]
    who = who[:who.index("}") + 1]
    assert "white-space: nowrap" in pill
    assert "white-space: nowrap" in who


def test_search_collapses_below_1100():
    css = _css()
    start = css.index("@media (max-width: 1099px)")
    block = css[start:css.index("@media (max-width: 1023px)")]
    assert ".search-trigger" in block
    assert "display: none" in block  # 文案与 kbd 收起，只留图标按钮


def test_toast_container_clears_floating_button():
    css = _css()
    toasts = css[css.index(".toasts {"):]
    toasts = toasts[:toasts.index("}") + 1]
    assert "bottom: 88px" in toasts


def test_toast_marks_body_while_visible(client, qdb):
    login_as(client, qdb)
    html = client.get("/first-touch").get_data(as_text=True)
    assert "document.body.classList.add('has-toast')" in html
    assert "document.body.classList.remove('has-toast')" in html


def test_viewer_gets_first_touch_nav():
    groups = app_utils.nav_for_role("viewer")
    first_touch = next(g for g in groups if g["key"] == "first_touch")
    assert [link["href"] for link in first_touch["links"]] == [
        "/first-touch", "/first-touch/guide"]


def test_viewer_first_touch_pages_read_only(client, qdb):
    """A2 起 Viewer 可只读访问 First Touch 页面。"""
    login_as(client, qdb, role="viewer", display_name="Viewer")
    assert client.get("/first-touch").status_code == 200
    assert client.get(f"/first-touch/students/{qdb.student_id}").status_code == 200
