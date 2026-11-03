"""新前端（Stage 3）：/app/* 返回构建好的单页，/app/assets/* 返回静态资源，
/api/app/boot 返回当前账号、可见范围、导航和平台卡片。"""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, make_response, send_from_directory
from markupsafe import escape

import app_utils

bp = Blueprint("app_shell", __name__)

APP_DIR = Path(__file__).resolve().parent.parent / "static" / "app"
BOOT_MARK = "<!--app-boot-->"


@bp.route("/app/assets/<path:filename>")
def app_assets(filename):
    """构建产物（JS/CSS/字体）。文件名带内容哈希，可以长期缓存；不含学生数据，不需登录。"""
    return send_from_directory(str(APP_DIR / "assets"), filename, max_age=31536000)


@bp.route("/app/", defaults={"rest": ""})
@bp.route("/app/<path:rest>")
@app_utils.page_login_required
def app_page(rest):
    index = APP_DIR / "index.html"
    if not index.is_file():
        return "前端尚未构建：请在 frontend/ 运行 npm run build", 503
    html = index.read_text(encoding="utf-8")
    meta = '<meta name="csrf-token" content="%s">' % escape(app_utils.get_csrf_token())
    resp = make_response(html.replace(BOOT_MARK, meta, 1))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/app/boot")
def api_app_boot():
    if not app_utils.is_authenticated():
        return jsonify({"ok": False, "error": "未登录"}), 401
    from blueprints.auth import _platform_cards

    user = app_utils.current_user()
    role = user["role"]
    return jsonify({
        "ok": True,
        "user": {
            "display_name": user["display_name"],
            "role": role,
            "role_label": app_utils.ROLE_LABELS.get(role, role),
        },
        "policy": app_utils.account_policy(),
        "nav": app_utils.nav_for_role(role),
        "platforms": _platform_cards(),
    })
