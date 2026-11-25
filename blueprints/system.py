"""系统蓝图：公开 API 文档页 + 用户管理（仅 admin）。"""
from __future__ import annotations

from flask import (Blueprint, abort, jsonify, redirect, render_template,
                   request, session)

import db as _db
import app_utils
from app_utils import invalidate_session_user, role_required

bp = Blueprint("system", __name__)


def _is_full_admin() -> bool:
    return session.get("role") == "admin"


def _is_m1_manager() -> bool:
    """心有灵析管理账号（非完整管理员）：生效值，随账号设置在 TTL 内更新。"""
    from m1 import store as m1_store
    return not _is_full_admin() and m1_store.is_m1_admin(app_utils.current_user())


def _forbidden():
    return jsonify({"ok": False, "error": "无权访问"}), 403


# 心有灵析管理账号在用户页只能看到这些字段
_M1_ADMIN_USER_FIELDS = ("id", "username", "display_name", "role", "m1_access", "m1_admin")


@bp.route("/api/docs")
def api_docs():
    """公开 API 文档页面（无需登录）。"""
    return render_template("api_docs.html")
@bp.route("/system/users")
@role_required('admin', 'advisor')
def system_users_page():
    if not (_is_full_admin() or _is_m1_manager()):
        abort(403)
    return render_template("users.html", nav_active="system.users",
                           limited=not _is_full_admin())


@bp.route("/system/settings")
@app_utils.login_required
def system_settings_page():
    """旧「设置」入口：内部账号统一到个人设置（账号与密码）页。"""
    if session.get("role") == "front":
        abort(403)
    return redirect("/app/settings")


@bp.route("/api/users")
@role_required('admin', 'advisor')
def api_users_list():
    if _is_full_admin():
        return jsonify({"ok": True, "users": _db.list_users()})
    if not _is_m1_manager():
        return _forbidden()
    users = [{k: u.get(k) for k in _M1_ADMIN_USER_FIELDS}
             for u in _db.list_users() if u.get("is_active")]
    return jsonify({"ok": True, "users": users, "limited": True})


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
            student_scope=data.get("student_scope"),
            m1_admin=data.get("m1_admin"),
            detail_level=data.get("detail_level"),
            m1_access=data.get("m1_access"),
            is_assessor=data.get("is_assessor") or 0,
            office_id=data.get("office_id"),
            office_ids=data.get("office_ids"),
        )
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "id": uid})


@bp.route("/api/users/<int:user_id>", methods=["PUT"])
@role_required('admin', 'advisor')
def api_users_update(user_id):
    data = request.get_json(force=True, silent=True) or {}
    if not _is_full_admin():
        return _m1_manager_update(user_id, data)
    kwargs = {}
    if data.get("password"):
        kwargs["password"] = data["password"]
    for k in ("role", "advisor_name", "display_name"):
        if k in data:
            kwargs[k] = data[k]
    # 可见范围三项：显式传空/null 表示恢复角色默认值
    for k in ("student_scope", "detail_level", "m1_access"):
        if k in data:
            kwargs[k] = "" if data[k] is None else data[k]
    if "is_active" in data:
        kwargs["is_active"] = 1 if data["is_active"] else 0
    if "is_assessor" in data:
        kwargs["is_assessor"] = 1 if data["is_assessor"] else 0
    if "office_id" in data:
        kwargs["office_id"] = data["office_id"]
    if "office_ids" in data:
        kwargs["office_ids"] = data["office_ids"]
    if "m1_admin" in data:
        kwargs["m1_admin"] = 0 if data["m1_admin"] is None else data["m1_admin"]
    # 防锁死：不能停用自己，也不能停用/降权最后一个 admin
    if user_id == session.get('user_id') and kwargs.get('is_active') == 0:
        return jsonify({"ok": False, "error": "不能停用当前登录账号"}), 400
    target = _db.get_user_by_id(user_id)
    if not target:
        return jsonify({"ok": False, "error": "用户不存在"}), 404
    before_offices = set(_db.list_user_office_ids(user_id))
    losing_admin = target.get('role') == 'admin' and (
        kwargs.get('role') not in (None, 'admin') or kwargs.get('is_active') == 0)
    if losing_admin and _db.count_users_by_role('admin') <= 1:
        return jsonify({"ok": False, "error": "至少保留一个启用的管理员"}), 400
    try:
        ok = _db.update_user(user_id, **kwargs)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    invalidate_session_user(user_id)
    reassignments = []
    if target.get("is_assessor") and ("office_ids" in data or "office_id" in data):
        removed = before_offices - set(_db.list_user_office_ids(user_id))
        for office_id in sorted(removed):
            for item in _db.list_future_assignments_for_office(user_id, office_id):
                item["office_id"] = office_id
                reassignments.append(item)
    return jsonify({"ok": True, "updated": bool(ok), "reassignments": reassignments})


def _m1_manager_update(user_id, data):
    """心有灵析管理账号只能为其他顾问分配心有灵析角色。"""
    if (not _is_m1_manager() or user_id == session.get("user_id")
            or not isinstance(data, dict) or not data
            or not data.keys() <= {"m1_access", "m1_admin"}):
        return _forbidden()
    target = _db.get_user_by_id(user_id)
    if not target:
        return jsonify({"ok": False, "error": "用户不存在"}), 404
    if target.get("role") != "advisor" or not target.get("is_active"):
        return _forbidden()
    if any(type(value) not in (bool, int) or value not in (0, 1) for value in data.values()):
        return jsonify(ok=False, error="心有灵析权限需要开启或关闭"), 400
    if data.get("m1_admin") and not data.get("m1_access", target["m1_access"]):
        return jsonify(ok=False, error="请先开启心有灵析权限"), 400
    if data.get("m1_access") == 0:
        data = {**data, "m1_admin": 0}
    try:
        ok = _db.update_user(user_id, **data)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    invalidate_session_user(user_id)
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
    invalidate_session_user(user_id)
    return jsonify({"ok": True})


_COMMIT = None


def _deployed_commit() -> str:
    """部署的代码版本（git 短哈希），启动后只读一次；读不到返回 unknown。"""
    global _COMMIT
    if _COMMIT is None:
        import subprocess
        from pathlib import Path
        try:
            out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                 cwd=str(Path(__file__).resolve().parent.parent),
                                 capture_output=True, text=True, timeout=5)
            _COMMIT = out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else "unknown"
        except Exception:
            _COMMIT = "unknown"
    return _COMMIT


@bp.route("/healthz")
def healthz():
    """存活检查：不需登录，只说明服务和数据库是否可用，不返回任何数据。"""
    from sqlalchemy import text
    try:
        with _db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return jsonify({"ok": True})
    except Exception:
        return jsonify({"ok": False}), 503


@bp.route("/api/admin/version")
@role_required('admin')
def api_admin_version():
    return jsonify({"ok": True, "commit": _deployed_commit()})
