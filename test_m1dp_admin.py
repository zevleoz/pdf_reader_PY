"""DP9：心有灵析管理（m1_admin）账号选项。"""
from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask

import db as _db
import m1.plan_store as pstore
from app_utils import BASE_DIR
from m1 import store
from test_m1_store import m1db  # noqa: F401  pytest fixture
from test_m1dp_store import _create, _published_prep

ROOT = Path(__file__).resolve().parent


def _session(client, user_id, role, advisor_name="", m1_access=1, m1_admin=0,
             scope="all"):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role
        sess["advisor_name"] = advisor_name
        sess["student_scope"] = scope
        sess["detail_level"] = "full"
        sess["m1_access"] = m1_access
        sess["m1_admin"] = m1_admin


@pytest.fixture()
def client(m1db, monkeypatch):  # noqa: F811
    import app_utils
    from blueprints import m1 as m1_api
    from blueprints import m1_plan, system

    pstore.ensure_tables(m1db.engine)
    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.secret_key = "test-secret"
    app.register_blueprint(m1_api.bp)
    app.register_blueprint(m1_plan.bp)
    app.register_blueprint(system.bp)
    return app.test_client()


def _manager(m1db):
    """把 alice 设为心有灵析管理。"""
    assert _db.update_user(m1db.alice_id, m1_admin=1)


# ---------------------------------------------------------------------------
# 生效值
# ---------------------------------------------------------------------------
def test_effective_m1_admin_values():
    eff = _db.effective_account_settings
    assert eff("admin")["m1_admin"] == 1
    assert eff("viewer", m1_admin=1)["m1_admin"] == 0
    assert eff("advisor", m1_admin=1)["m1_admin"] == 1
    assert eff("advisor", m1_admin=None)["m1_admin"] == 0
    assert eff("advisor", m1_access=0, m1_admin=1)["m1_admin"] == 0


def test_update_user_m1_admin_roundtrip(m1db):
    assert _db.update_user(m1db.alice_id, m1_admin=1)
    assert _db.get_user_by_id(m1db.alice_id)["m1_admin"] == 1
    assert _db.update_user(m1db.alice_id, m1_access=0)
    assert _db.get_user_by_id(m1db.alice_id)["m1_admin"] == 0
    assert _db.update_user(m1db.alice_id, m1_access=1)
    assert _db.get_user_by_id(m1db.alice_id)["m1_admin"] == 1
    # 改成别的角色会清掉
    assert _db.update_user(m1db.alice_id, role="viewer")
    assert _db.update_user(m1db.alice_id, role="advisor")
    assert _db.get_user_by_id(m1db.alice_id)["m1_admin"] == 0
    with pytest.raises(ValueError):
        _db.update_user(m1db.alice_id, m1_admin="yes")


# ---------------------------------------------------------------------------
# can_edit_plan
# ---------------------------------------------------------------------------
def _plan(m1db):
    pstore.ensure_tables(m1db.engine)
    prep, report = _published_prep(m1db)
    return _create(m1db, prep, report)  # mentor = alice


def test_can_edit_plan_m1_admin(m1db):
    plan = _plan(m1db)
    bob = {"user_id": m1db.bob_id, "role": "advisor", "advisor_name": "Bob",
           "m1_access": 1, "m1_admin": 1}
    assert plan["mentor_user_id"] != m1db.bob_id
    assert pstore.can_edit_plan(bob, plan) is True
    assert pstore.can_edit_plan({**bob, "m1_admin": 0}, plan) is False
    assert pstore.can_edit_plan({**bob, "m1_access": 0}, plan) is False
    assert pstore.can_edit_plan({"user_id": m1db.viewer_id, "role": "viewer",
                                 "m1_admin": 1}, plan) is False


# ---------------------------------------------------------------------------
# Mentor 更换 + /api/m1/mentors
# ---------------------------------------------------------------------------
def test_mentor_change_permissions(client, m1db):
    prep = m1db.prep()
    url = "/api/m1/preps/%d" % prep["id"]
    body = {"mentor_user_id": m1db.bob_id}

    _session(client, m1db.alice_id, "advisor", "Alice")
    res = client.patch(url, json=body)
    assert res.status_code == 403
    assert res.get_json()["error"] == "只有管理员可以更换 Mentor"
    # 其他字段照旧
    assert client.patch(url, json={"duration": 90}).status_code == 200

    _session(client, m1db.alice_id, "advisor", "Alice", m1_admin=1)
    assert client.patch(url, json=body).status_code == 200

    _session(client, m1db.admin_id, "admin", m1_admin=1)
    assert client.patch(url, json={"mentor_user_id": m1db.alice_id}).status_code == 200


def test_mentors_route(client, m1db):
    _session(client, m1db.alice_id, "advisor", "Alice")
    assert client.get("/api/m1/mentors").status_code == 403
    _db.update_user(m1db.bob_id, m1_access=0)
    for role, kw in (("admin", {}), ("advisor", {"m1_admin": 1})):
        _session(client, m1db.alice_id if role == "advisor" else m1db.admin_id,
                 role, "Alice", **kw)
        res = client.get("/api/m1/mentors")
        assert res.status_code == 200
        rows = res.get_json()["mentors"]
        assert all(set(r) == {"id", "display_name"} for r in rows)
        ids = {r["id"] for r in rows}
        assert m1db.alice_id in ids and m1db.admin_id in ids
        assert m1db.bob_id not in ids and m1db.viewer_id not in ids


# ---------------------------------------------------------------------------
# 用户 API
# ---------------------------------------------------------------------------
def test_user_api_as_m1_admin(client, m1db):
    _manager(m1db)
    _session(client, m1db.alice_id, "advisor", "Alice", m1_admin=1)
    res = client.get("/api/users")
    assert res.status_code == 200
    users = res.get_json()["users"]
    assert users
    for u in users:
        assert set(u) <= {"id", "username", "display_name", "role", "m1_access", "m1_admin"}
    assert "password_hash" not in res.get_data(as_text=True)

    bob = "/api/users/%d" % m1db.bob_id
    assert client.put(bob, json={"m1_access": 0}).status_code == 200
    assert _db.get_user_by_id(m1db.bob_id)["m1_access"] == 0
    assert client.put(bob, json={"m1_access": 1}).status_code == 200
    assert _db.get_user_by_id(m1db.bob_id)["m1_access"] == 1

    assert client.put("/api/users/%d" % m1db.admin_id, json={"m1_access": 0}).status_code == 403
    assert client.put("/api/users/%d" % m1db.alice_id, json={"m1_access": 0}).status_code == 403
    for extra in ({"role": "admin"}, {"m1_admin": 1}, {"password": "x"},
                  {"student_scope": "all"}, {"detail_level": "full"}):
        assert client.put(bob, json=extra).status_code == 403
        assert client.put(bob, json={"m1_access": 0, **extra}).status_code == 403
    assert _db.get_user_by_id(m1db.bob_id)["role"] == "advisor"
    assert client.post("/api/users", json={"username": "z", "password": "p",
                                           "role": "admin"}).status_code == 403
    assert client.delete(bob).status_code == 403
    assert _db.get_user_by_id(m1db.bob_id)


def test_user_api_plain_advisor_refused(client, m1db):
    _session(client, m1db.alice_id, "advisor", "Alice")
    assert client.get("/api/users").status_code == 403
    assert client.put("/api/users/%d" % m1db.bob_id, json={"m1_access": 0}).status_code == 403
    assert client.get("/system/users").status_code == 403
    # 心有灵析关闭后，即使存了标记也无效
    _session(client, m1db.alice_id, "advisor", "Alice", m1_access=0, m1_admin=1)
    assert client.get("/api/users").status_code == 403


def test_user_page_as_m1_admin_is_limited(client, m1db):
    _session(client, m1db.alice_id, "advisor", "Alice", m1_admin=1)
    page = client.get("/system/users").get_data(as_text=True)
    assert "LIMITED = true" in page and 'id="createMsg"' not in page
    _session(client, m1db.admin_id, "admin")
    page = client.get("/system/users").get_data(as_text=True)
    assert "LIMITED = false" in page and 'id="createMsg"' in page and "心有灵析管理" in page


def test_user_api_as_admin_sets_m1_admin(client, m1db):
    _session(client, m1db.admin_id, "admin")
    url = "/api/users/%d" % m1db.alice_id
    assert client.put(url, json={"m1_admin": 1}).status_code == 200
    users = {u["id"]: u for u in client.get("/api/users").get_json()["users"]}
    assert users[m1db.alice_id]["m1_admin"] == 1
    assert client.put(url, json={"m1_access": 0}).status_code == 200
    assert _db.get_user_by_id(m1db.alice_id)["m1_admin"] == 0  # 心有灵析关闭 → 0
    assert users[m1db.admin_id]["m1_admin"] == 1
    assert client.put(url, json={"m1_admin": "bad"}).status_code == 400


# ---------------------------------------------------------------------------
# 页面 / 列表
# ---------------------------------------------------------------------------
def test_lists_default_to_all_for_managers(client, m1db):
    js = (ROOT / "static/m1/m1_lists.js").read_text(encoding="utf-8")
    assert "root.dataset.defaultWho === 'all' ? 'all' : 'mine'" in js
    for kind in ("preps", "reports", "plans"):
        _session(client, m1db.alice_id, "advisor", "Alice")
        page = client.get("/m1/%s" % kind).get_data(as_text=True)
        assert 'data-default-who="mine"' in page and "账号" not in page.split("who")[0][-2000:]
        _session(client, m1db.alice_id, "advisor", "Alice", m1_admin=1)
        page = client.get("/m1/%s" % kind).get_data(as_text=True)
        assert 'data-default-who="all"' in page
        assert 'href="/system/users"' in page
        _session(client, m1db.admin_id, "admin")
        assert 'data-default-who="all"' in client.get("/m1/%s" % kind).get_data(as_text=True)


# ---------------------------------------------------------------------------
# DP9-b：受限用户页脚本 / 列表「全部」默认
# ---------------------------------------------------------------------------
def test_limited_user_page_has_no_create_form_and_guarded_script(client, m1db):
    import re
    _session(client, m1db.alice_id, "advisor", "Alice", m1_admin=1)
    page = client.get("/system/users").get_data(as_text=True)
    form_ids = ("nu", "np", "nr", "na", "nd", "nsc", "ndl", "nm1", "naField", "createMsg")
    for fid in form_ids:
        assert 'id="%s"' % fid not in page
    # 脚本中每个读取表单字段的函数，开头都有「表单不存在则返回」的守卫
    for fn in ("onRoleChange", "syncAdvisorField", "createUser"):
        body = re.search(r"function %s\(\) \{\n(.*?)\n" % fn, page).group(1)
        assert "if (!document.getElementById(" in body and "return" in body, fn
    assert "if (!LIMITED) onRoleChange();" in page
    assert "if (!el) return;" in page  # setMsg 容忍缺失节点
    # 页面启动只读 /api/admin/check 和 /api/users（其余为点击后的写入 / 退出）
    startup = page.split("(async function () {")[1]
    assert "loadMe()" in startup and "loadUsers()" in startup
    assert "fetch(" not in startup


def test_lists_who_saved_only_on_click_with_new_key():
    js = (ROOT / "static/m1/m1_lists.js").read_text(encoding="utf-8")
    assert js.count("localStorage.setItem") == 1
    assert "'.who2'" in js and "'.who')" not in js and "'.who'," not in js
    # setItem 只在 setWho 的 persist 分支内
    assert "if (persist) {\n      try { window.localStorage.setItem('m1.' + kind + '.who2'" in js
    # 启动路径的 setWho 调用不带 persist；点击调用带 persist
    assert js.count("setWho(state.who);") == 2
    assert "setWho(button.dataset.who, true)" in js
