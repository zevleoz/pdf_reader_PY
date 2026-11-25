"""认证蓝图：登录页 / 登录 / 登出 / 会话检查 / 本人账号与改密。"""
from __future__ import annotations

import os
from functools import wraps
from hmac import compare_digest

from flask import (Blueprint, jsonify, redirect, render_template, request,
                   session)

import db as _db
import app_utils

bp = Blueprint("auth", __name__)


@bp.route("/login")
def login_page():
    return render_template("login.html")


def _platform_cards() -> list:
    """选择平台的卡片：Profiling 恒有，M1 按账号权限，E4 按环境变量。"""
    from blueprints.m1 import M1_PARTS

    cards = [{
        "key": "profiling",
        "title": "PY Family Institute",
        "desc": "预约、Y4 报告、解读会、补充问卷、First Touch、6AM",
        "href": ("/app/handoff" if session.get("role") == "front"
                 else "/app/students" if session.get("role") == "viewer"
                 else "/app/workbench"),
        "blank": False,
    }]
    if session.get("role") == "front":
        return cards
    if app_utils.can_use_m1():
        labels = "、".join(part["label"] for part in M1_PARTS if part["enabled"])
        cards.append({
            "key": "m1",
            "title": "心有灵析",
            "desc": f"First Meeting：{labels}",
            "href": "/m1",
            "blank": False,
        })
    e4_url = os.environ.get("E4_URL", "").strip()
    if e4_url:
        cards.append({
            "key": "e4",
            "title": "E4",
            "desc": "独立平台，有自己的账号和数据库",
            "href": e4_url,
            "blank": True,
        })
    return cards


@bp.route("/platforms")
@app_utils.page_login_required
def platforms_page():
    cards = _platform_cards()
    if len(cards) == 1:
        return redirect(cards[0]["href"])
    return render_template("platforms.html", cards=cards)


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
    session['student_scope'] = user['student_scope']
    session['detail_level'] = user['detail_level']
    session['m1_access'] = user['m1_access']
    session['m1_admin'] = user.get('m1_admin') or 0
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


def _csrf_required(view):
    """校验与登录/Cookie 同源的 CSRF token（前端 api.ts 统一带 X-CSRF-Token）。"""
    @wraps(view)
    def checked(*args, **kwargs):
        expected = session.get("_csrf_token") or ""
        supplied = request.headers.get("X-CSRF-Token", "")
        if not expected or not compare_digest(expected.encode("utf-8"),
                                               supplied.encode("utf-8")):
            return jsonify({"ok": False, "error": "请求校验失败，请刷新页面后重试"}), 403
        return view(*args, **kwargs)
    return checked


def _is_internal_staff() -> bool:
    """个人设置只给内部老师与管理员；前台只处理预约交接。"""
    return session.get("role") in ("admin", "advisor", "viewer")


@bp.route("/api/account")
@app_utils.login_required
def api_account_profile():
    """当前登录账号（供个人设置页显示只读登录名）。"""
    if not _is_internal_staff():
        return jsonify({"ok": False, "error": "无权访问"}), 403
    user = _db.get_user_by_id(session["user_id"])
    if not user:
        return jsonify({"ok": False, "error": "用户不存在"}), 404
    return jsonify({
        "ok": True,
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "role": user["role"],
        "role_label": app_utils.ROLE_LABELS.get(user["role"], user["role"]),
    })


@bp.route("/api/account/password", methods=["POST"])
@app_utils.login_required
@_csrf_required
def api_account_password():
    """本人修改登录密码：用户取自会话，校验当前密码后一次性更新哈希。"""
    if not _is_internal_staff():
        return jsonify({"ok": False, "error": "无权访问"}), 403
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "请求格式不正确"}), 400
    allowed = {"current_password", "new_password", "confirm_password"}
    if set(data) - allowed:
        return jsonify({"ok": False, "error": "只能修改本人登录密码"}), 400
    current = data.get("current_password") or ""
    new = data.get("new_password") or ""
    confirm = data.get("confirm_password") or ""
    if not current or not new or not confirm:
        return jsonify({"ok": False, "error": "请填写当前密码、新密码和确认新密码"}), 400
    if new != confirm:
        return jsonify({"ok": False, "error": "两次输入的新密码不一致"}), 400
    user = _db.get_user_by_id(session["user_id"])
    if not user:
        return jsonify({"ok": False, "error": "用户不存在"}), 404
    if not _db.verify_user(user["username"], current):
        return jsonify({"ok": False, "error": "当前密码不正确"}), 400
    if not _db.update_user(user["id"], password=new):
        return jsonify({"ok": False, "error": "密码未更新，请稍后重试"}), 500
    app_utils.invalidate_session_user(user["id"])
    return jsonify({
        "ok": True,
        "message": "密码已修改。当前登录状态保持有效，下次登录请使用新密码。",
    })


@bp.route("/api/admin/check")
def api_admin_check():
    u = app_utils.current_user()
    return jsonify({"ok": True, "authenticated": app_utils.is_authenticated(),
                    "user_id": u['user_id'], "role": u['role'],
                    "display_name": u['display_name'],
                    "advisor_name": u['advisor_name']})
