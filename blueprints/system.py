"""系统蓝图：公开 API 文档页 + 用户管理（仅 admin）。"""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request, session

import db as _db
from app_utils import role_required

bp = Blueprint("system", __name__)


@bp.route("/api/docs")
def api_docs():
    """公开 API 文档页面（无需登录）。"""
    return render_template("api_docs.html")
@bp.route("/system/users")
@role_required('admin')
def system_users_page():
    return render_template("users.html", nav_active="system.users")


@bp.route("/system/settings")
@role_required('admin')
def system_settings_page():
    """设置模块打桩页（B 包 5.4）：避免侧边栏「系统」组出现死链。"""
    return render_template("system_settings.html", nav_active="system.settings")


@bp.route("/api/users")
@role_required('admin')
def api_users_list():
    return jsonify({"ok": True, "users": _db.list_users()})


@bp.route("/api/users", methods=["POST"])
@role_required('admin')
def api_users_create():
    data = request.get_json(force=True, silent=True) or {}
    try:
        uid = _db.create_user(
            (data.get("username") or "").strip(),
            data.get("password") or "",
            (data.get("role") or "viewer").strip(),
            (data.get("advisor_name") or "").strip(),
            (data.get("display_name") or "").strip(),
        )
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "id": uid})


@bp.route("/api/users/<int:user_id>", methods=["PUT"])
@role_required('admin')
def api_users_update(user_id):
    data = request.get_json(force=True, silent=True) or {}
    kwargs = {}
    if data.get("password"):
        kwargs["password"] = data["password"]
    for k in ("role", "advisor_name", "display_name"):
        if k in data:
            kwargs[k] = data[k]
    if "is_active" in data:
        kwargs["is_active"] = 1 if data["is_active"] else 0
    # 防锁死：不能停用自己，也不能停用/降权最后一个 admin
    if user_id == session.get('user_id') and kwargs.get('is_active') == 0:
        return jsonify({"ok": False, "error": "不能停用当前登录账号"}), 400
    target = _db.get_user_by_id(user_id)
    if not target:
        return jsonify({"ok": False, "error": "用户不存在"}), 404
    losing_admin = target.get('role') == 'admin' and (
        kwargs.get('role') not in (None, 'admin') or kwargs.get('is_active') == 0)
    if losing_admin and _db.count_users_by_role('admin') <= 1:
        return jsonify({"ok": False, "error": "至少保留一个启用的管理员"}), 400
    try:
        ok = _db.update_user(user_id, **kwargs)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "updated": bool(ok)})


@bp.route("/api/users/<int:user_id>", methods=["DELETE"])
@role_required('admin')
def api_users_delete(user_id):
    if user_id == session.get('user_id'):
        return jsonify({"ok": False, "error": "不能删除当前登录账号"}), 400
    target = _db.get_user_by_id(user_id)
    if not target:
        return jsonify({"ok": False, "error": "用户不存在"}), 404
    if target.get('role') == 'admin' and _db.count_users_by_role('admin') <= 1:
        return jsonify({"ok": False, "error": "至少保留一个启用的管理员"}), 400
    _db.delete_user(user_id)
    return jsonify({"ok": True})
