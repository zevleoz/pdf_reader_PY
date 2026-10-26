# -*- coding: utf-8 -*-
"""P4 验收：6AM 2.0 页面壳、样式与共享脚本。

覆盖：
- ``GET /insights/six-am`` 作为 admin / viewer 各自的 200 与 ``data-can-write``；
- 四个 ``/js/six_am/*.js`` 标签齐备且旧 ``/js/six_am.js`` 不再引用；
- 静态路由 ``/js/six_am/common.js``（text/javascript）与 ``/css/six_am.css``；
- ``node --check`` 通过。

页面与静态路由依赖真实 Flask 入口（``app.create_app``），故在独立子进程里
``import app``，用临时 SQLite（DATABASE_URL）运行，绝不触碰 data/y4_students.db。

运行：python3 -m pytest test_six_am_v2_page.py -q
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent
JS_DIR = REPO_ROOT / "static" / "js" / "six_am"
NEW_JS = ("common.js", "overview.js", "profile.js", "review.js")

_PROBE = r'''
import json
import app as app_module
import db

db.init_db()
ids = {}
for key, role in (("admin", "admin"), ("viewer", "viewer")):
    ids[key] = db.create_user("t_" + key, "x" * 12, role, display_name="用户" + key)

client = app_module.app.test_client()
out = {}


def login(role):
    with client.session_transaction() as sess:
        sess["user_id"] = ids[role]
        sess["role"] = role
        sess["advisor_name"] = ""
        sess["display_name"] = "用户" + role


login("admin")
r = client.get("/insights/six-am")
out["admin_status"] = r.status_code
out["admin_body"] = r.get_data(as_text=True)

login("viewer")
r = client.get("/insights/six-am")
out["viewer_status"] = r.status_code
out["viewer_body"] = r.get_data(as_text=True)

r = client.get("/js/six_am/common.js")
out["js_status"] = r.status_code
out["js_ct"] = r.headers.get("Content-Type", "")

r = client.get("/css/six_am.css")
out["css_status"] = r.status_code

print(json.dumps(out))
'''


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("six_am_v2_page")
    env = os.environ.copy()
    env["DATABASE_URL"] = "sqlite:///%s" % (tmp / "page.db")
    for name in ("Y4_ENV", "FLASK_ENV", "SECRET_KEY"):
        env.pop(name, None)
    res = subprocess.run([sys.executable, "-c", _PROBE], cwd=str(REPO_ROOT), env=env,
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=300)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


class TestPageShell:
    """页面壳：字体/脚本引用与 data-can-write。"""

    def test_admin_page_renders_shell(self, probe):
        assert probe["admin_status"] == 200
        body = probe["admin_body"]
        assert 'id="sa2"' in body
        assert 'data-can-write="true"' in body
        for name in NEW_JS:
            assert "/js/six_am/%s?v=20261027" % name in body
        assert 'src="/js/six_am.js' not in body
        assert "/css/six_am.css?v=20261027" in body

    def test_viewer_page_is_read_only(self, probe):
        assert probe["viewer_status"] == 200
        assert 'data-can-write="false"' in probe["viewer_body"]


class TestStaticAssets:
    """静态资源路由。"""

    def test_module_js_route(self, probe):
        assert probe["js_status"] == 200
        assert "javascript" in probe["js_ct"]

    def test_css_route(self, probe):
        assert probe["css_status"] == 200


@pytest.mark.parametrize("name", NEW_JS)
def test_new_js_files_parse(name):
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不可用，跳过语法检查")
    path = JS_DIR / name
    assert path.is_file(), "%s 缺失" % path
    res = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr