# -*- coding: utf-8 -*-
"""任务 F：撤下独立的「Profiling 流程」看板。

导航不再提供 /app/flow；旧地址仍由单页接管，前端按身份转到学生名单或前台预约交接。
"""
from pathlib import Path

import app_utils
import db as _db

REPO_ROOT = Path(__file__).resolve().parent


def _hrefs(role):
    return [link["href"] for group in app_utils.nav_for_role(role) for link in group["links"]]


def test_flow_link_is_gone_for_every_role():
    for role in ("admin", "advisor", "viewer"):
        assert "/app/flow" not in _hrefs(role), role


def test_students_group_keeps_only_the_roster():
    group = next(g for g in app_utils.ADMIN_NAV if g["key"] == "students")
    assert [link["key"] for link in group["links"]] == ["students"]


def test_legacy_flow_url_redirects_by_role():
    app_tsx = (REPO_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert '<Route path="flow" element={<FlowRedirect />} />' in app_tsx
    assert 'boot.user.role === "front" ? "/handoff" : "/students"' in app_tsx


def test_legacy_flow_url_still_served_by_shell():
    import app as app_module

    application = app_module.create_app()
    application.config["TESTING"] = True
    application.secret_key = "test"

    signed_out = application.test_client().get("/app/flow")
    assert signed_out.status_code == 302
    assert "/login" in signed_out.headers["Location"]

    user_id = _db.create_user("task-f-route-check", "pw-123456", "advisor", advisor_name="Mine")
    client = application.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = "advisor"
        sess["advisor_name"] = "Mine"
    page = client.get("/app/flow")
    assert page.status_code == 200
    assert '<div id="root">' in page.get_data(as_text=True)


def test_built_app_drops_the_flow_board():
    assets = REPO_ROOT / "static" / "app" / "assets"
    built = "".join(p.read_text(encoding="utf-8") for p in assets.glob("*.js"))
    assert "Profiling 流程" not in built
