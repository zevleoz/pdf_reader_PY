"""认证蓝图：登录页 / 登录 / 登出 / 会话检查。"""
from __future__ import annotations

import os

from flask import (Blueprint, jsonify, redirect, render_template, request,
                   session)

import db as _db
import app_utils

bp = Blueprint("auth", __name__)


@bp.route("/login")
def login_page():
    return render_template("login.html")
LOGIN_RATE_LIMIT = int(os.environ.get('Y4_LOGIN_RATE_LIMIT', '5'))


@bp.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    # 登录限流：同一 IP 每分钟 5 次失败，超限 429（成功登录不计入并清空失败窗口）
    if not app_utils.rate_fail_check(LOGIN_RATE_LIMIT, scope='login'):
        return jsonify({"ok": False, "error": "尝试过多，请稍后再试"}), 429
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    # 旧密码格式（只提交密码、无账号）：明确提示升级，且一律不放行
    if not username:
        app_utils.rate_fail_record(scope='login')
        return jsonify({"ok": False, "error": "系统已升级，请使用账号密码登录"}), 400
    user = _db.verify_user(username, password)
    if not user:
        app_utils.rate_fail_record(scope='login')
        return jsonify({"ok": False, "error": "用户名或密码错误"}), 401
    app_utils.rate_fail_clear(scope='login')
    session['user_id'] = user['id']
    session['role'] = user['role']
    session['advisor_name'] = user.get('advisor_name') or ''
    session['display_name'] = user.get('display_name') or user['username']
    session.permanent = True
    return jsonify({"ok": True, "role": user['role'],
                    "display_name": session['display_name']})


@bp.route("/api/admin/logout", methods=["POST"])
def api_admin_logout():
    session.clear()
    return jsonify({"ok": True})


@bp.route("/logout")
def logout():
    """GET /logout：清 session 后回登录页（用户直接敲 URL 的场景）。"""
    session.clear()
    return redirect("/login")


@bp.route("/api/admin/check")
def api_admin_check():
    u = app_utils.current_user()
    return jsonify({"ok": True, "authenticated": app_utils.is_authenticated(),
                    "user_id": u['user_id'], "role": u['role'],
                    "display_name": u['display_name'],
                    "advisor_name": u['advisor_name']})
