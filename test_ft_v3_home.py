"""V4a 验收：Y4 驱动的学生列表、精简导航与三步指南。"""
from __future__ import annotations

import app_utils
import db as _db
import growth_talk_store as store
from sqlalchemy.orm import Session

from test_copilot_routes import (  # noqa: F401
    _inline_jobs, client, login_as, qdb,
)

REMOVED_TEXT = ("Yuguo", "手动添加学生", "从 Y4 导入", "聊天中心")


def _add_student(qdb, code: str, name: str, advisor: str = "Alice") -> int:
    with Session(qdb.engine) as sess:
        row = _db.Student(student_code=code, name=name, grade="10",
                          school="测试学校", advisor_name=advisor)
        sess.add(row)
        sess.commit()
        return row.id


def _completed_session(qdb, student_id: int, *, versions: int = 1):
    """已完成状态：会话绑定 run，并确认过报告（版本随确认次数递增）。"""
    session, _ = store.create_session(student_id, qdb.alice_id)
    source = store.create_source(
        student_id, "GROWTH_TALK", "GROWTH_TALK", "会谈纪要", "会谈内容")
    run = store.create_run(student_id, source["id"])
    store.update_session_fields(session["id"], run_id=run["id"])
    for _ in range(versions):
        store.create_report(student_id, run["id"], "{}", "Alice",
                            session_id=session["id"])
    return store.get_session(session["id"])


def _seed_four_statuses(qdb) -> dict[str, int]:
    not_started = qdb.student_id
    qdb.add_y4(not_started)

    in_progress = _add_student(qdb, "Y4-9301", "进行中学生")
    qdb.add_y4(in_progress)
    session, _ = store.create_session(in_progress, qdb.alice_id)
    store.update_session_fields(session["id"], phase=1)

    completed = _add_student(qdb, "Y4-9302", "已完成学生")
    qdb.add_y4(completed)
    _completed_session(qdb, completed, versions=2)

    needs_y4 = _add_student(qdb, "Y4-9303", "缺少 Y4 学生")
    return {
        "not_started": not_started,
        "in_progress": in_progress,
        "completed": completed,
        "needs_y4": needs_y4,
    }


def test_student_list_renders_status_and_action(client, qdb):
    login_as(client, qdb)
    _seed_four_statuses(qdb)

    html = client.get("/first-touch").get_data(as_text=True)

    assert "未开始" in html
    assert "进行中 · ②" in html
    assert "已完成 · v2" in html
    assert "需先完成 Y4" in html

    assert ">开始</button>" in html
    assert ">继续</a>" in html
    assert ">查看</a>" in html
    assert ">去生成 Y4</a>" in html
    assert 'href="/generate"' in html


def test_home_has_search_and_filter_counts(client, qdb):
    login_as(client, qdb)
    _seed_four_statuses(qdb)

    html = client.get("/first-touch").get_data(as_text=True)

    assert 'placeholder="搜索姓名 / 编号 / 学校"' in html
    assert "可开始 <span class=\"n\">1</span>" in html
    assert "进行中 <span class=\"n\">1</span>" in html
    assert "已完成 <span class=\"n\">1</span>" in html
    assert "缺少 Y4 <span class=\"n\">1</span>" in html


def test_removed_entry_points_are_gone(client, qdb):
    login_as(client, qdb)
    qdb.add_y4()

    html = client.get("/first-touch").get_data(as_text=True)
    for text in REMOVED_TEXT:
        assert text not in html

    group = next(g for g in app_utils.ADMIN_NAV if g["key"] == "first_touch")
    assert [(item["label"], item["href"]) for item in group["links"]] == [
        ("学生列表", "/first-touch"),
        ("使用指南", "/first-touch/guide"),
    ]
    for text in REMOVED_TEXT:
        assert text not in str(group)


def test_nav_keeps_role_visibility():
    for role in ("admin", "advisor", "viewer"):
        groups = app_utils.nav_for_role(role)
        group = next(g for g in groups if g["key"] == "first_touch")
        assert [item["href"] for item in group["links"]] == [
            "/first-touch", "/first-touch/guide"]


def test_viewer_has_no_start_button(client, qdb):
    login_as(client, qdb, role="viewer", advisor_name="",
             display_name="观察员", user_id=qdb.alice_id)
    qdb.add_y4(qdb.student_id)

    html = client.get("/first-touch").get_data(as_text=True)
    assert ">开始</button>" not in html
    assert ">查看</a>" not in html

    qdb.session()
    html = client.get("/first-touch").get_data(as_text=True)
    assert ">查看</a>" in html
    assert ">开始</button>" not in html


def test_start_creates_session_and_opens_workspace(client, qdb):
    login_as(client, qdb)
    qdb.add_y4(qdb.student_id)

    resp = client.post(
        f"/api/v2/students/{qdb.student_id}/copilot/sessions", json={})
    assert resp.status_code == 201

    html = client.get("/first-touch").get_data(as_text=True)
    assert "进行中 · ①" in html
    assert ">继续</a>" in html
    assert client.get(
        f"/first-touch/students/{qdb.student_id}").status_code == 200


def test_guide_describes_three_steps(client, qdb):
    login_as(client, qdb)

    html = client.get("/first-touch/guide").get_data(as_text=True)

    assert "会前" in html
    assert "会谈中" in html
    assert "会后" in html
    assert "七阶段" not in html
    for text in REMOVED_TEXT:
        assert text not in html
