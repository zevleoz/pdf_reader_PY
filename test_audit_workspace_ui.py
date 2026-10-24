"""B1 · Workspace UI 正确性与打磨（F1 / F3 客户端 / F5 客户端 / F8 / F9）。

复用 ``test_copilot_routes.py`` 的 Flask/DB fixture，仅对渲染出的 HTML/JS 断言。
"""
from __future__ import annotations

import re

from test_copilot_routes import client, login_as, qdb  # noqa: F401


def _workspace(client, qdb) -> str:
    login_as(client, qdb)
    qdb.session()
    response = client.get(f"/first-touch/students/{qdb.student_id}")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _array_block(html: str, marker: str) -> str:
    start = html.index(marker)
    end = html.index('],', start)
    return html[start:end]


# ---------------------------------------------------------------------------
# F1：0–3 四档评分 + 共享标签
# ---------------------------------------------------------------------------
def test_score_options_cover_all_four_levels(client, qdb):
    html = _workspace(client, qdb)
    preference = _array_block(html, "preferenceOptions: [")
    competence = _array_block(html, "competenceOptions: [")

    for value in range(4):
        assert f"value: {value}" in preference
        assert f"value: {value}" in competence

    assert "一般喜欢" in preference and "非常喜欢" in preference
    assert "一般擅长" in competence and "非常擅长" in competence


def test_three_level_band_labels_only_on_summary_board(client, qdb):
    html = _workspace(client, qdb)
    preference = _array_block(html, "preferenceOptions: [")
    competence = _array_block(html, "competenceOptions: [")

    assert "中（2）" not in preference
    assert "中（2）" not in competence
    assert "低（0–1）" not in preference
    assert "低（0–1）" not in competence

    # 三档横纵轴只在阶段 5 的 threeLevelCells 里出现一次
    assert html.count("喜欢低（0–1）") == 1
    assert html.count("喜欢中（2）") == 1
    assert html.count("喜欢高（3）") == 1
    assert html.count("擅长低（0–1）") == 1
    assert html.count("擅长中（2）") == 1
    assert html.count("擅长高（3）") == 1
    assert "threeLevelCells() {" in html


def test_both_score_tabs_reuse_shared_options(client, qdb):
    html = _workspace(client, qdb)

    assert html.count('x-for="opt in preferenceOptions"') == 2
    assert html.count('x-for="opt in competenceOptions"') == 2
    # 待评（空值）保留在两个标签页
    assert html.count('<option value="">待评</option>') >= 2


# ---------------------------------------------------------------------------
# F3：切阶段不阻塞、不制造版本号变化
# ---------------------------------------------------------------------------
def test_phase_navigation_syncs_in_background(client, qdb):
    html = _workspace(client, qdb)
    assert "syncPhase(target)" in html

    sync = html[html.index("syncPhase(target) {"):]
    sync = sync[:sync.index("\n    },")]

    assert "busy" not in sync
    assert "await" not in sync
    assert "phase: target" in sync and "revision: this.revision" in sync
    assert "!this.nextStepsAttempted" in html
    assert "this.nextStepsAttempted = true;" in html


# ---------------------------------------------------------------------------
# F5：无时区 ISO 按 UTC 解析，非整刻时间向下取整
# ---------------------------------------------------------------------------
def test_meeting_time_naive_iso_treated_as_utc(client, qdb):
    html = _workspace(client, qdb)

    assert "_normalizeMeetingIso" in html
    assert "return text + 'Z';" in html
    assert "_slotFloor" in html
    assert "this.meetingDirty = !!slot && slot !== parsed.time;" in html


# ---------------------------------------------------------------------------
# F9：保存状态、术语与标签打磨
# ---------------------------------------------------------------------------
def test_save_status_shown_once_without_revision_jargon(client, qdb):
    html = _workspace(client, qdb)

    visible_bindings = re.findall(r'x-text="([^"]*)"', html)
    assert all("修订" not in expr for expr in visible_bindings)

    assert "'已保存'" in html
    assert "'内容待保存'" in html
    assert "'正在保存…'" in html
    # 版本号只留在 title tooltip
    assert "'revision ' + revision" in html
    # 旧的右侧重复状态已移除
    assert html.count('class="ft-status" x-text="meetingStatus"') == 1


def test_note_renamed_and_delete_button_stays_on_one_line(client, qdb):
    html = _workspace(client, qdb)

    assert 'class="ft-note">Note' not in html
    assert 'class="ft-note">备注' in html
    assert "white-space: nowrap" in html
    assert "removeInterest(item.id)" in html


def test_presentation_kickers_match_tab_numbers(client, qdb):
    html = _workspace(client, qdb)

    assert "02 / FIRST TALK" in html
    assert "03 / Y4 REPORT" in html
    assert "01 / FIRST TALK" not in html
    assert "02 / Y4 REPORT" not in html


# ---------------------------------------------------------------------------
# F8：toast 显示时抬升浮动聊天按钮
# ---------------------------------------------------------------------------
def test_chat_fab_lifts_above_toast(client, qdb):
    html = _workspace(client, qdb)

    assert "body.has-toast .ft-chat" in html
    assert "translateY(-72px)" in html


# ---------------------------------------------------------------------------
# 字号下限：正文/控件 ≥12px，仅坐标轴刻度与计数可保持更小
# ---------------------------------------------------------------------------
def test_font_floor_for_body_and_control_text(client, qdb):
    html = _workspace(client, qdb)
    style = html[html.index("[x-cloak] { display: none !important; }"):]
    style = style[:style.index("</style>")]

    sizes = re.findall(r"font-size:\s*(\d+(?:\.\d+)?)px", style)
    assert sizes
    allowed_small = {"10", "10.5", "11"}
    assert all(float(size) >= 12 or size in allowed_small for size in sizes)
    assert "11.5px" not in style
