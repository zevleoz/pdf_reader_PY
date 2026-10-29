# -*- coding: utf-8 -*-
"""R4 验收：6AM v0.6 页面壳、样式与五个模块脚本。

覆盖：
- ``GET /insights/six-am`` 作为 admin / viewer 各自的 200、``data-can-write`` 与 ``data-is-admin``；
- 五个 ``/js/six_am/*.js`` 标签齐备（``?v=20261101``），已删除的 profile / review / board 不再引用；
- 静态路由 ``/js/six_am/common.js``（text/javascript）与 ``/css/six_am.css``；
- ``static/js/six_am/`` 下每个文件 ``node --check`` 通过。

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
NEW_JS = ("common.js", "mindmap.js", "overview.js", "student.js", "rules.js")
OLD_JS = ("profile.js", "review.js", "board.js")
ASSET_VERSION = "20261101"

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

r = client.get("/js/six_am/mindmap.js")
out["mm_status"] = r.status_code

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
    """页面壳：视图、脚本引用与权限标记。"""

    def test_admin_page_renders_shell(self, probe):
        assert probe["admin_status"] == 200
        body = probe["admin_body"]
        assert 'id="sa2"' in body
        assert 'data-can-write="true"' in body
        assert 'data-is-admin="true"' in body
        for name in NEW_JS:
            assert "/js/six_am/%s?v=%s" % (name, ASSET_VERSION) in body
        for name in OLD_JS:
            assert "/js/six_am/%s" % name not in body
        assert 'src="/js/six_am.js' not in body
        assert "/css/six_am.css?v=%s" % ASSET_VERSION in body

    def test_viewer_page_is_read_only(self, probe):
        assert probe["viewer_status"] == 200
        body = probe["viewer_body"]
        assert 'data-can-write="false"' in body
        assert 'data-is-admin="false"' in body


class TestStaticAssets:
    """静态资源路由。"""

    def test_module_js_route(self, probe):
        assert probe["js_status"] == 200
        assert "javascript" in probe["js_ct"]

    def test_mindmap_js_route(self, probe):
        assert probe["mm_status"] == 200

    def test_css_route(self, probe):
        assert probe["css_status"] == 200


def test_js_directory_is_the_five_modules():
    names = sorted(path.name for path in JS_DIR.glob("*.js"))
    assert names == sorted(NEW_JS), names


@pytest.mark.parametrize("name", NEW_JS)
def test_new_js_files_parse(name):
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不可用，跳过语法检查")
    path = JS_DIR / name
    assert path.is_file(), "%s 缺失" % path
    res = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_every_js_file_parses():
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不可用，跳过语法检查")
    for path in sorted(JS_DIR.glob("*.js")):
        res = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
        assert res.returncode == 0, "%s\n%s" % (path.name, res.stderr)
