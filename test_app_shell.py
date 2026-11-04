# -*- coding: utf-8 -*-
"""S3-P1：/app/ 单页、/app/assets/ 静态资源与 /api/app/boot 的启动数据。

用真实 Flask 入口（``app.create_app``）与独立临时 SQLite，不触碰 data/y4_students.db。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event

import app_utils
import db as _db
import questionnaire_store as qs

REPO_ROOT = Path(__file__).resolve().parent
CREST = "static/m1/login_crest_white.png"
PASSWORD = "pw-123456"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/login_platforms.db")

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

    w = SimpleNamespace(
        admin_id=_db.create_user("t-admin", PASSWORD, "admin"),
        advisor_id=_db.create_user("t-adv", PASSWORD, "advisor", advisor_name="Mine"),
        no_m1_id=_db.create_user("t-adv-nom1", PASSWORD, "advisor",
                                 advisor_name="Mine", m1_access=0),
        viewer_id=_db.create_user("t-view", PASSWORD, "viewer"),
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
    """旧 session 形态：只有 user_id / role / advisor_name，其余由账号同步。"""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role
        sess["advisor_name"] = advisor_name
    return client


def test_app_shell_signed_out_redirects_to_login(app):
    resp = app.test_client().get("/app/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_app_shell_serves_built_page_to_admin(app, world):
    resp = _client(app, world.admin_id, "admin").get("/app/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '<div id="root">' in html
    assert '<meta name="csrf-token" content="' in html
    assert "<!--app-boot-->" not in html
    assert resp.headers["Cache-Control"] == "no-store"


def test_app_shell_deep_link_serves_page(app, world):
    resp = _client(app, world.admin_id, "admin").get("/app/some/deep/path")
    assert resp.status_code == 200
    assert '<div id="root">' in resp.get_data(as_text=True)


def test_app_shell_no_trailing_slash_redirects(app, world):
    resp = _client(app, world.admin_id, "admin").get("/app")
    assert resp.status_code in (301, 308)
    assert resp.headers["Location"].endswith("/app/")


def test_app_shell_not_built_returns_503(app, world, tmp_path, monkeypatch):
    monkeypatch.setattr("blueprints.app_shell.APP_DIR", tmp_path)
    resp = _client(app, world.admin_id, "admin").get("/app/")
    assert resp.status_code == 503
    assert "前端尚未构建" in resp.get_data(as_text=True)


def test_app_boot_signed_out(app):
    resp = app.test_client().get("/api/app/boot")
    assert resp.status_code == 401
    assert resp.get_json()["ok"] is False


def test_app_boot_admin(app, world):
    resp = _client(app, world.admin_id, "admin").get("/api/app/boot")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["user"]["role"] == "admin"
    hrefs = [link["href"] for group in data["nav"] for link in group["links"]]
    assert "/tools/prompt-lab" in hrefs
    assert data["policy"]["detail_level"] == "full"


def test_app_boot_viewer(app, world):
    resp = _client(app, world.viewer_id, "viewer").get("/api/app/boot")
    assert resp.status_code == 200
    data = resp.get_json()
    hrefs = [link["href"] for group in data["nav"] for link in group["links"]]
    assert "/tools/prompt-lab" not in hrefs
    assert data["policy"]["detail_level"] == "summary"
    assert len(data["platforms"]) == 1


def test_app_assets_served_without_login(app):
    assets = REPO_ROOT / "static" / "app" / "assets"
    js_files = sorted(p.name for p in assets.glob("*.js"))
    assert js_files, f"no .js build output under {assets}"
    resp = app.test_client().get(f"/app/assets/{js_files[0]}")
    assert resp.status_code == 200


def test_app_build_has_no_outside_hosts():
    forbidden = ("googleapis", "gstatic", "unpkg", "jsdelivr", "cdnjs")
    for path in (REPO_ROOT / "static" / "app").rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for host in forbidden:
            assert host not in text, f"{host} found in {path}"


def test_app_build_has_design_tokens():
    """S3-P2：构建产物带着国际主义的颜色与零圆角 token。"""
    assets = REPO_ROOT / "static" / "app" / "assets"
    css_files = sorted(assets.glob("*.css"))
    assert css_files, f"no .css build output under {assets}"
    text = "".join(p.read_text(encoding="utf-8") for p in css_files)
    squashed = re.sub(r":\s+", ":", text)
    assert "--shell:353.1 100% 44.3%" in squashed
    assert "--radius:0rem" in squashed


def test_app_build_has_archivo_font():
    """S3-P2：Archivo 字体随构建产物一起发布，不从外站加载。"""
    assets = REPO_ROOT / "static" / "app" / "assets"
    names = [p.name for p in assets.glob("*.woff2")]
    assert any("archivo" in name.lower() for name in names), \
        f"no archivo .woff2 under {assets}: {names}"


def test_app_kit_route_serves_page(app, world):
    """S3-P2：组件核对页 /app/kit 由单页入口返回。"""
    resp = _client(app, world.admin_id, "admin").get("/app/kit")
    assert resp.status_code == 200
    assert '<div id="root">' in resp.get_data(as_text=True)


def test_app_build_has_shell_strings():
    """S3-P3：构建产物带着外壳的接口、CSRF 头与文案。"""
    assets = REPO_ROOT / "static" / "app" / "assets"
    js_files = sorted(assets.glob("*.js"))
    assert js_files, f"no .js build output under {assets}"
    text = "".join(p.read_text(encoding="utf-8") for p in js_files)
    for needle in ("/api/app/boot", "X-CSRF-Token", "退出登录", "选择平台", "打开导航"):
        assert needle in text, f"{needle} not found in built JS"


def test_app_build_has_no_placeholder():
    """S3-P3：构建产物里没有占位文案。"""
    assets = REPO_ROOT / "static" / "app" / "assets"
    for path in assets.glob("*.js"):
        assert "Stage 3" not in path.read_text(encoding="utf-8"), f"Stage 3 found in {path}"


def test_app_shell_mounts_page_once():
    """S3-P3b：外壳只有一个 <Outlet /> 和一个 <main>，页面不会挂载两次。"""
    text = (REPO_ROOT / "frontend" / "src" / "shell" / "AppShell.tsx").read_text(encoding="utf-8")
    assert text.count("<Outlet") == 1
    assert text.count("<main") == 1


def test_app_students_route_serves_page(app, world):
    """S4-P1：学生档案页 /app/students 由单页入口返回。"""
    resp = _client(app, world.admin_id, "admin").get("/app/students")
    assert resp.status_code == 200
    assert '<div id="root">' in resp.get_data(as_text=True)


def test_old_students_list_still_reachable(app, world):
    """S4-GL1：新页面接管后，旧版学生列表 /students 仍可访问。"""
    resp = _client(app, world.admin_id, "admin").get("/students")
    assert resp.status_code == 200


def test_app_build_has_students_page_strings():
    """S4-P1：构建产物带着学生档案的接口与文案。"""
    assets = REPO_ROOT / "static" / "app" / "assets"
    js_files = sorted(assets.glob("*.js"))
    assert js_files, f"no .js build output under {assets}"
    text = "".join(p.read_text(encoding="utf-8") for p in js_files)
    for needle in ("/api/profiling/students", "旧版学生档案", "可选，未使用"):
        assert needle in text, f"{needle} not found in built JS"


def test_frontend_pages_present_and_not_ignored():
    """S4-P1：Stage 3 的页面文件进仓库，不再被根目录 pages/ 规则忽略。"""
    for name in ("Kit.tsx", "NotFound.tsx"):
        assert (REPO_ROOT / "frontend" / "src" / "pages" / name).is_file(), f"{name} missing"
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("no .git here")
    result = subprocess.run(
        ["git", "check-ignore", "-q", "frontend/src/pages/Kit.tsx"],
        cwd=REPO_ROOT,
    )
    assert result.returncode != 0


def test_app_close_labels_are_chinese():
    """S3-P3b：关闭按钮的无障碍文案为中文。"""
    ui = REPO_ROOT / "frontend" / "src" / "components" / "ui"
    for name in ("sheet.tsx", "dialog.tsx"):
        text = (ui / name).read_text(encoding="utf-8")
        assert ">关闭<" in text, f"{name} has no 关闭 label"
        assert ">Close<" not in text, f"{name} still has a Close label"


