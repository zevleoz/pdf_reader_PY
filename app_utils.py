"""共享工具层：常量、认证/授权装饰器、滑动窗口限流、session 读取、Advisor 数据隔离。

被 app.py 与各 blueprints 导入。**不得反向导入 app / blueprints**，也不得在此模块
引入任何依赖 Flask 请求上下文的模块级副作用（genjob 子进程会 import 本模块）。
"""
from __future__ import annotations

import os
import secrets
import time
from collections import deque
from functools import wraps
from pathlib import Path
from typing import List, Optional

from flask import request, session, redirect, jsonify, abort

from sqlalchemy import select

import db as _db

# ---------------------------------------------------------------------------
# 路径与全局常量（原 app.py 模块级配置，搬迁以便各蓝图共享）
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
DATA_DIR = BASE_DIR / "data"
TEMPLATE_DIR = BASE_DIR / "templates"
BRANDING_DIR = BASE_DIR / "branding"
UPLOAD_DIR = DATA_DIR / "_uploads"
JOB_FILE = DATA_DIR / "_job.json"
JOB_LOG_FILE = DATA_DIR / "_job.log"

REQUIRED_KEYS: List[str] = ["A2", "B3", "B4", "B6"]

# 外部 API 配置（供其他网站下载 Y4 报告）
Y4_API_KEY = os.environ.get('Y4_API_KEY', '')
Y4_API_CORS_ORIGINS = os.environ.get('Y4_API_CORS_ORIGINS', '*').strip()
Y4_API_RATE_LIMIT = int(os.environ.get('Y4_API_RATE_LIMIT', '60'))
# E4 协议端点会实时调用 AI 模型（成本/耗时较高），使用更严格的独立限流。
Y4_API_E4_RATE_LIMIT = int(os.environ.get('Y4_API_E4_RATE_LIMIT', '8'))


# ---------------------------------------------------------------------------
# 滑动窗口限流（沿用 app.py 既有 _v1_rate_check 的实现模式）
# ---------------------------------------------------------------------------
_RATE_BUCKETS: dict = {}


def rate_check(limit: int, scope: str = "default") -> bool:
    """每 IP 滑动窗口限流（每分钟 ``limit`` 次）。返回 True 表示通过。

    ``scope`` 用于为不同用途（外部 API / 登录 / E4）单独计数。
    """
    if limit <= 0:
        return True
    key = (request.remote_addr or "") + "|" + scope
    now = time.time()
    win = _RATE_BUCKETS.setdefault(key, deque())
    while win and win[0] < now - 60:
        win.popleft()
    if len(win) >= limit:
        return False
    win.append(now)
    return True


def rate_fail_check(limit: int, scope: str = "default") -> bool:
    """失败计数限流的检查侧：窗口内失败次数已达 ``limit`` 返回 False（应 429）。

    与 :func:`rate_fail_record` 配合：仅在认证**失败**时记账，成功登录不计入。
    """
    if limit <= 0:
        return True
    key = (request.remote_addr or "") + "|" + scope
    win = _RATE_BUCKETS.setdefault(key, deque())
    now = time.time()
    while win and win[0] < now - 60:
        win.popleft()
    return len(win) < limit


def rate_fail_record(scope: str = "default") -> None:
    """记录一次失败尝试（滑动窗口 60 秒）。"""
    key = (request.remote_addr or "") + "|" + scope
    _RATE_BUCKETS.setdefault(key, deque()).append(time.time())


def rate_fail_clear(scope: str = "default") -> None:
    """成功登录后清空该 IP 的失败窗口。"""
    _RATE_BUCKETS.pop((request.remote_addr or "") + "|" + scope, None)


# ---------------------------------------------------------------------------
# CSRF token（session 认证面；/api/v1/* Bearer 面豁免，见 app.py 的 _csrf_protect）
# ---------------------------------------------------------------------------
def get_csrf_token() -> str:
    """取（或生成）当前 session 的 CSRF token。模板经 context_processor 调用。"""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_urlsafe(32)
    return session["_csrf_token"]


def dt_short(value) -> str:
    """模板过滤器 ``dt_short``：把 ISO 时间戳压到分钟（YYYY-MM-DD HH:MM）。

    列表类页面统一到分钟展示，避免秒级时间戳干扰扫读；无法解析时退回原值的
    前 16 字符（``T`` 替换为空格）。
    """
    if not value:
        return ""
    s = str(value)
    try:
        from datetime import datetime
        return datetime.fromisoformat(s.replace("Z", "")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return s[:16].replace("T", " ")


# ---------------------------------------------------------------------------
# session 读取
# ---------------------------------------------------------------------------
def current_user() -> dict:
    """当前登录用户信息（来自 session）。未登录时各字段为 None/空串。"""
    return {
        "user_id": session.get("user_id"),
        "role": session.get("role") or "",
        "advisor_name": session.get("advisor_name") or "",
        "display_name": session.get("display_name") or "",
    }


def is_authenticated() -> bool:
    return bool(session.get("user_id"))


def _is_api_request() -> bool:
    """API 与页面用不同失败语义：API 返回 JSON 状态码，页面跳转/403 页。"""
    return request.path.startswith("/api/")


# ---------------------------------------------------------------------------
# 认证/授权装饰器
# ---------------------------------------------------------------------------
def login_required(f):
    """任何已登录用户可访问。未登录：API → 401 JSON，页面 → 跳 /login?next=。"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_authenticated():
            if _is_api_request():
                return jsonify({"ok": False, "error": "未登录"}), 401
            return redirect("/login?next=" + request.path)
        return f(*args, **kwargs)
    return wrapper


def role_required(*roles):
    """限定角色访问。未登录同上；角色不符：API → 403 JSON，页面 → 403 页。"""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not is_authenticated():
                if _is_api_request():
                    return jsonify({"ok": False, "error": "未登录"}), 401
                return redirect("/login?next=" + request.path)
            if roles and session.get("role") not in roles:
                if _is_api_request():
                    return jsonify({"ok": False, "error": "无权访问"}), 403
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator


def admin_required(f):
    """兼容桥（过渡期）：登录 + 非只读角色。

    - 未登录：API 401 / 页面跳 /login（委托 auth 语义）
    - 已登录且 role==viewer、方法为写操作（非 GET/HEAD/OPTIONS）：403

    绝大多数既有写端点因此等价 role_required('admin','advisor')，读端点等价
    login_required。仅管理员可见的路由（系统/规则/日历设置）另行显式标注
    role_required('admin')。细粒度授权以各路由显式装饰器为准。
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_authenticated():
            if request.path.startswith('/api/'):
                return jsonify({"ok": False, "error": "未登录"}), 401
            return redirect('/login?next=' + request.path)
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and session.get('role') == 'viewer':
            return jsonify({"ok": False, "error": "只读账号无权执行此操作"}), 403
        return f(*args, **kwargs)
    return wrapper


def page_login_required(f):
    """兼容桥（过渡期）：页面路由要求登录（任意角色），未登录跳 /login?next=。"""
    return login_required(f)


def visible_student_filter(stmt):
    """Advisor 数据隔离：role=advisor 时自动附加 students.advisor_name 过滤。

    传入的 ``stmt`` 必须是针对 ``db.Student`` 的 select；非 advisor 角色原样返回。
    """
    if session.get("role") != "advisor":
        return stmt
    return stmt.where(_db.Student.advisor_name == (session.get("advisor_name") or ""))


# ---------------------------------------------------------------------------
# Advisor 数据隔离（2.0）：凡可定位到个体学生/报告的查询与操作，advisor 仅限名下
# ---------------------------------------------------------------------------
def _advisor_scope() -> Optional[str]:
    """advisor 角色返回其 advisor_name；其他角色返回 None（表示不隔离）。"""
    if session.get('role') == 'advisor':
        return session.get('advisor_name') or ''
    return None


def _student_forbidden(student_id):
    """advisor 访问非名下学生 → 返回 403 响应；放行返回 None。"""
    scope = _advisor_scope()
    if scope is None:
        return None
    st = _db.get_student(student_id) if student_id else None
    if not st or (st.get('advisor_name') or '') != scope:
        return jsonify({"ok": False, "error": "无权访问该学生"}), 403
    return None


def _report_forbidden(report_id):
    """advisor 访问非名下学生的报告 → 返回 403 响应；放行返回 None。"""
    scope = _advisor_scope()
    if scope is None:
        return None
    sid = _db.get_report_student_id(report_id)
    if sid is None:
        return None  # 报告不存在，交由端点自行 404
    st = _db.get_student(sid)
    if not st or (st.get('advisor_name') or '') != scope:
        return jsonify({"ok": False, "error": "无权访问该报告"}), 403
    return None


def student_scoped(f):
    """advisor 数据隔离：校验路径参数 student_id 属于当前 advisor 名下。"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        denied = _student_forbidden(kwargs.get('student_id'))
        if denied:
            return denied
        return f(*args, **kwargs)
    return wrapper


def report_scoped(f):
    """advisor 数据隔离：校验路径参数 report_id 属于当前 advisor 名下学生。"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        denied = _report_forbidden(kwargs.get('report_id'))
        if denied:
            return denied
        return f(*args, **kwargs)
    return wrapper


def _minutes_forbidden(minutes_id):
    """advisor 访问非名下学生的纪要 → 返回 403；放行返回 None。"""
    scope = _advisor_scope()
    if scope is None:
        return None
    item = _db.get_minutes(minutes_id) if minutes_id else None
    if not item:
        return None  # 纪要不存在，交由端点自行 404
    st = _db.get_student(item.get('student_id'))
    if not st or (st.get('advisor_name') or '') != scope:
        return jsonify({"ok": False, "error": "无权访问该纪要"}), 403
    return None


def minutes_scoped(f):
    """advisor 数据隔离：校验路径参数 minutes_id 所属学生属于当前 advisor 名下。"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        denied = _minutes_forbidden(kwargs.get('minutes_id'))
        if denied:
            return denied
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# 管理端导航与模板上下文（Agent B Layout 契约：02-admin-ui-framework.md 5.3/5.4）
# ---------------------------------------------------------------------------
ROLE_LABELS = {"admin": "管理员", "advisor": "顾问", "viewer": "只读"}

# 七组导航严格按 spec 5.1。key 即 ``nav_active`` 取值；子项 ``roles`` 缺省表示
# 所有已登录角色可见，显式声明时按角色过滤（过滤后无可见项的分组整组隐藏）。
ADMIN_NAV = [
    {"key": "workspace", "title": "工作台", "links": [
        {"key": "workspace", "label": "工作台", "href": "/workspace", "icon": "grid"},
    ]},
    {"key": "students", "title": "学生", "links": [
        {"key": "students", "label": "学生档案", "href": "/students", "icon": "users"},
    ]},
    {"key": "generate", "title": "报告生成", "links": [
        {"key": "generate", "label": "报告生成", "href": "/generate", "icon": "file",
         "roles": ("admin", "advisor")},
    ]},
    {"key": "insights", "title": "洞察", "links": [
        {"key": "insights.dashboard", "label": "数据总览", "href": "/insights/dashboard", "icon": "chart"},
        {"key": "insights.y4-signals", "label": "Y4 研判", "href": "/insights/y4-signals", "icon": "radar"},
        {"key": "insights.six-am", "label": "6AM 启动模型", "href": "/insights/six-am", "icon": "target"},
    ]},
    {"key": "tools", "title": "工具", "links": [
        {"key": "tools.bank", "label": "问卷题库", "href": "/questionnaires/bank",
         "icon": "book", "roles": ("admin", "advisor")},
        {"key": "tools.bookings", "label": "预约管理", "href": "/tools/bookings", "icon": "calendar",
         "roles": ("admin", "advisor")},
        {"key": "tools.transcript", "label": "解读会纪要", "href": "/tools/transcript", "icon": "mic",
         "roles": ("admin", "advisor")},
        {"key": "tools.internal", "label": "内部下载", "href": "/tools/internal", "icon": "download",
         "roles": ("admin", "advisor")},
        {"key": "tools.prompt-lab", "label": "Prompt Lab", "href": "/tools/prompt-lab", "icon": "flask",
         "roles": ("admin",)},
    ]},
    {"key": "system", "title": "系统", "links": [
        {"key": "system.users", "label": "用户管理", "href": "/system/users", "icon": "shield",
         "roles": ("admin",)},
        {"key": "system.settings", "label": "设置", "href": "/system/settings", "icon": "settings",
         "roles": ("admin",)},
        {"key": "system.docs", "label": "API 文档", "href": "/api/docs", "icon": "book",
         "roles": ("admin",), "blank": True},
    ]},
]


def nav_for_role(role: str) -> List[dict]:
    """按角色过滤管理端导航；过滤后无可见项的分组整组隐藏。

    当前页高亮与分组展开由模板依据 ``nav_active`` 计算，本函数不感知请求视图。
    """
    groups = []
    for group in ADMIN_NAV:
        links = [dict(it) for it in group["links"]
                 if not it.get("roles") or role in it["roles"]]
        if not links:
            continue
        g = dict(group)
        g["links"] = links
        groups.append(g)
    return groups


def register_admin_context(app) -> None:
    """注册管理端模板上下文（在 create_app 内调用一次，所有蓝图共享）。

    注入 ``current_role`` / ``current_role_label`` / ``current_display_name`` /
    ``nav_groups``；页面模板另需传入 ``nav_active``（缺省空串）。
    """
    @app.context_processor
    def _inject_admin_context():
        role = session.get("role") or ""
        return {
            "current_role": role,
            "current_role_label": ROLE_LABELS.get(role, role),
            "current_display_name": session.get("display_name") or "",
            "nav_groups": nav_for_role(role),
        }
