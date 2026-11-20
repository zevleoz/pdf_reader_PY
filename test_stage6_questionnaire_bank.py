# -*- coding: utf-8 -*-
"""Stage6 Brief A：问卷题库壳页。

页面组件本身没有前端测试运行器，因此这里做两件事：
1. 用隔离的临时 SQLite 验证页面依赖的题库接口契约（列表带 schema、启停、旧页权限）。
2. 对页面源码做最少量的契约检查（接口地址、角色门槛、分组文案、失败不改状态）。

不触碰 data/y4_students.db，不启动服务器，不发真实 AI 请求。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event

import app_utils
import db as _db
import questionnaire_store as qs

REPO_ROOT = Path(__file__).resolve().parent
PAGE = REPO_ROOT / "frontend" / "src" / "pages" / "QuestionnaireBank.tsx"
PASSWORD = "pw-123456"
CSRF = "csrf-test-token"

SCHEMA = {
    "version": 1,
    "sections": [
        {"id": "part_a", "title": "第一部分"},
        {"id": "part_b", "title": "第二部分"},
    ],
    "questions": [
        {"id": "q1", "title": "第一题", "section": "part_a", "dimension": "焦虑"},
        {"id": "q2", "title": "第二题", "section": "part_b"},
        {"id": "q3", "title": "未分段题", "dimension": "抑郁"},
        {"id": "q4", "title": "未知分段题", "section": "missing"},
    ],
}


@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/stage6_bank.db")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    _db.Base.metadata.create_all(engine)
    qs.ensure_indexes(bind=engine)
    monkeypatch.setattr(_db, "engine", engine)
    monkeypatch.setattr(qs, "engine", engine)
    monkeypatch.delenv("E4_URL", raising=False)
    app_utils._SESSION_USER_CACHE.clear()
    app_utils._RATE_BUCKETS.clear()

    with qs.Session(engine) as sess:
        sess.add(qs.Questionnaire(
            code="Q-STAGE6-DEMO",
            title="演示问卷",
            description="用于题库壳页核对的临时问卷",
            schema_json=json.dumps(SCHEMA, ensure_ascii=False),
            is_active=1,
        ))
        sess.commit()

    w = SimpleNamespace(
        admin_id=_db.create_user("s6-admin", PASSWORD, "admin"),
        advisor_id=_db.create_user("s6-adv", PASSWORD, "advisor", advisor_name="Mine"),
        viewer_id=_db.create_user("s6-view", PASSWORD, "viewer"),
    )
    yield w
    app_utils._SESSION_USER_CACHE.clear()
    app_utils._RATE_BUCKETS.clear()
    engine.dispose()


@pytest.fixture()
def app(world):
    import app as app_module
    application = app_module.create_app()
    application.config["TESTING"] = True
    application.secret_key = "test"
    return application


def _client(app, user_id, role, advisor_name=""):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role
        sess["advisor_name"] = advisor_name
        sess["_csrf_token"] = CSRF
    return client


def _toggle(client, qid, active):
    return client.post(
        f"/api/questionnaires/bank/{qid}/toggle",
        json={"active": active},
        headers={"X-CSRF-Token": CSRF},
    )


def test_page_source_contract():
    """页面只读自己那份源码：接口、角色门槛、分组与失败回滚顺序。"""
    text = PAGE.read_text(encoding="utf-8")

    for needle in (
        "/api/questionnaires/bank?with_schema=1",
        "/toggle",
        "查看题目",
        "收起题目",
        "其他题目",
        "旧版题库",
        'href="/questionnaires/bank"',
        "boot.policy.role",
        'role === "admin"',
        'role === "advisor"',
        "问卷题库仅对管理员与顾问开放",
    ):
        assert needle in text, f"缺少：{needle}"

    assert "dangerouslySetInnerHTML" not in text

    # 只读角色在发起任何题库请求之前就返回。
    assert text.index("if (!allowed) return;") < text.index("getJSON<BankResp>")

    # 刷新先清空展开行，避免保留过期预览。
    refresh_src = text[text.index("function refresh()"):text.index("function closePreview")]
    assert "setExpandedId(null)" in refresh_src

    # 启停：先确认 ok，再改状态；并挡住重复点击。
    toggle_src = text[text.index("async function toggleActive"):text.index("if (!allowed) {")]
    assert toggle_src.index("if (busyId !== null) return;") < toggle_src.index("setRows(")
    assert toggle_src.index("if (!body.ok) throw") < toggle_src.index("setRows(")


def test_bank_list_returns_schema_for_page_roles(app, world):
    for user_id, role in ((world.admin_id, "admin"), (world.advisor_id, "advisor")):
        resp = _client(app, user_id, role).get("/api/questionnaires/bank?with_schema=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        row = data["questionnaires"][0]
        assert row["title"] == "演示问卷"
        assert row["description"] == "用于题库壳页核对的临时问卷"
        assert row["code"] == "Q-STAGE6-DEMO"
        assert row["is_active"] == 1
        assert len(row["schema"]["questions"]) == 4
        assert [s["id"] for s in row["schema"]["sections"]] == ["part_a", "part_b"]


def test_bank_list_api_still_allows_viewer_but_page_denies_client_side(app, world):
    """接口授权保持原样；新页面的只读拒绝由页面角色门槛完成。"""
    resp = _client(app, world.viewer_id, "viewer").get("/api/questionnaires/bank?with_schema=1")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_toggle_is_admin_only_and_confirms_server_state(app, world):
    advisor = _client(app, world.advisor_id, "advisor")
    viewer = _client(app, world.viewer_id, "viewer")
    admin = _client(app, world.admin_id, "admin")

    assert _toggle(advisor, 1, False).status_code == 403
    assert _toggle(viewer, 1, False).status_code == 403

    resp = _toggle(admin, 1, False)
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "is_active": 0}
    rows = admin.get("/api/questionnaires/bank?with_schema=1").get_json()["questionnaires"]
    assert rows[0]["is_active"] == 0

    resp = _toggle(admin, 1, True)
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "is_active": 1}


def test_toggle_missing_questionnaire_returns_404(app, world):
    resp = _toggle(_client(app, world.admin_id, "admin"), 9999, True)
    assert resp.status_code == 404
    assert resp.get_json()["ok"] is False


def test_old_bank_page_remains_admin_advisor_only(app, world):
    assert _client(app, world.admin_id, "admin").get("/questionnaires/bank").status_code == 200
    assert _client(app, world.advisor_id, "advisor").get("/questionnaires/bank").status_code == 200
    assert _client(app, world.viewer_id, "viewer").get("/questionnaires/bank").status_code == 403
