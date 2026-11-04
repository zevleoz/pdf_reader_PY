# -*- coding: utf-8 -*-
"""S4-C6b：/app/questionnaires 由单页壳提供（页面本身是前端路由）。"""
from __future__ import annotations

from test_app_shell import _client, app, world  # noqa: F401  (fixtures)


def test_questionnaires_page_serves_spa(app, world):
    resp = _client(app, world.admin_id, "admin").get("/app/questionnaires")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '<div id="root">' in html
    assert '<meta name="csrf-token" content="' in html
