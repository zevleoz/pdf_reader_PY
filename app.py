"""Y4 平台瘦入口：全局配置 + 蓝图注册 + 静态资源 + 生成作业子进程入口。

路由已按功能拆分到 blueprints/ 包（纯搬迁，行为不变）：
  auth            /login /api/admin/login|logout|check
  workspace       /workspace（占位）
  students        /students*
  reports         /generate /preview /api/upload/* /api/progress
                  /api/generate* /api/chat /output /api/reports/* /api/export
  questionnaires  /questionnaires（占位）
  insights        /dashboard /y4-signals /six-am*
  tools           /admin/bookings /transcript /internal /prompt-lab /booking
  system          /system/* /api/docs
  api_v1          /api/v1/*（Bearer 鉴权，契约不变）

本文件同时提供 genjob 子进程入口（``python app.py genjob <args.json>``）。
"""
from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import timedelta
from pathlib import Path

from flask import (Flask, abort, jsonify, render_template, request,
                   send_from_directory, session)
from werkzeug.middleware.proxy_fix import ProxyFix

import db as _db
from app_utils import (BASE_DIR, INPUT_DIR, OUTPUT_DIR, DATA_DIR, TEMPLATE_DIR,
                       BRANDING_DIR, UPLOAD_DIR, JOB_FILE, JOB_LOG_FILE,
                       Y4_API_CORS_ORIGINS)

# 会话/Cookie 配置加固（F10）：
# 生产环境由 Y4_ENV=production（或 FLASK_ENV=production）标识；缺少强 SECRET_KEY 时
# 拒绝启动，避免 session / CSRF token 用公开的开发默认值签名。
DEV_SECRET_KEY = 'dev-key-change-in-production'
_TRUE_VALUES = {'1', 'true', 'yes', 'on'}
_FALSE_VALUES = {'0', 'false', 'no', 'off'}

_dev_secret_warned = False


def _is_production() -> bool:
    """生产环境判定：Y4_ENV 优先，兼容旧部署脚本写入的 FLASK_ENV。"""
    env = (os.environ.get('Y4_ENV') or os.environ.get('FLASK_ENV') or '').strip().lower()
    return env == 'production'


def _resolve_secret_key(is_production: bool) -> str:
    """解析 SECRET_KEY：生产缺失/仍为开发默认值即拒绝启动；开发环境回退并警告一次。"""
    global _dev_secret_warned
    secret = (os.environ.get('SECRET_KEY') or '').strip()
    if is_production and (not secret or secret == DEV_SECRET_KEY):
        raise RuntimeError(
            "生产环境必须设置强随机 SECRET_KEY（当前缺失或仍为开发默认值），拒绝启动。"
            " / SECRET_KEY must be set to a strong random value in production; refusing to start."
        )
    if not secret or secret == DEV_SECRET_KEY:
        if not _dev_secret_warned:
            logging.getLogger(__name__).warning(
                "SECRET_KEY 未设置或仍为开发默认值，使用开发默认值（仅限本地开发；生产环境会拒绝启动）。")
            _dev_secret_warned = True
        return DEV_SECRET_KEY
    return secret


def _resolve_cookie_secure(is_production: bool) -> bool:
    """SESSION_COOKIE_SECURE：显式 Y4_COOKIE_SECURE 优先，缺省生产 True、开发 False。"""
    raw = (os.environ.get('Y4_COOKIE_SECURE') or '').strip().lower()
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    return is_production


def create_app() -> Flask:
    """构建 Flask app：全局配置 + 静态资源路由 + 注册全部蓝图。"""
    # 配置校验先于任何 IO（建目录 / 初始化数据库），生产配置错误直接 fail fast。
    is_production = _is_production()
    secret_key = _resolve_secret_key(is_production)

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _db.init_db()

    # static_folder=None：不注册 Flask 内置的 /output 静态路由（它会绕过鉴权、暴露
    # 全部生成产物）。/output/<filename> 统一由 reports 蓝图带鉴权的 download 处理。
    app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=None)
    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
    app.secret_key = secret_key
    app.config.update(
        # 会话 Cookie 加固：禁止 JS 读取、限制跨站携带、HTTPS 下强制 Secure。
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=_resolve_cookie_secure(is_production),
    )
    # 会话总寿命（登录时 session.permanent=True）：把 Flask 默认的 31 天收敛到 7 天，
    # 缩短被停用/删除用户既有 session 的最长残留窗口（另有 app_utils 的 DB 复核兜底）。
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

    # ProxyFix: 信任单层反向代理（Nginx）注入的 X-Forwarded-* 头，
    # 使 request.remote_addr 反映真实客户端 IP（限流/审计依赖此值）。
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    @app.after_request
    def _apply_v1_cors(resp):
        """为 /api/v1/* 路径注入 CORS 头，不影响既有页面与管理 API。"""
        from flask import request as _rq
        if _rq.path.startswith('/api/v1/'):
            resp.headers['Access-Control-Allow-Origin'] = Y4_API_CORS_ORIGINS or '*'
            resp.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
            resp.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
            resp.headers['Access-Control-Max-Age'] = '600'
        return resp

    @app.route("/style.css")
    def serve_style():
        """Serve shared design-system CSS from templates/style.css."""
        return send_from_directory(str(TEMPLATE_DIR), "style.css", mimetype="text/css")

    @app.route("/admin_v2.css")
    def serve_admin_v2_css():
        """语汇 v2 样式（static/admin_v2.css，v2 壳页面共用）。"""
        return send_from_directory(str(BASE_DIR / "static"), "admin_v2.css", mimetype="text/css")

    @app.route("/command-palette.js")
    def serve_command_palette_js():
        """Serve the ⌘K command palette script (Agent H: static/command-palette.js)."""
        return send_from_directory(str(BASE_DIR / "static"), "command-palette.js",
                                   mimetype="text/javascript")

    @app.route("/css/six_am.css")
    def serve_six_am_css():
        """6AM 主页面样式（static/css/six_am.css）。"""
        return send_from_directory(str(BASE_DIR / "static" / "css"), "six_am.css",
                                   mimetype="text/css")

    @app.route("/js/six_am/<path:filename>")
    def serve_six_am_module_js(filename):
        """6AM 2.0 模块脚本（static/js/six_am/）。"""
        return send_from_directory(str(BASE_DIR / "static" / "js" / "six_am"), filename,
                                   mimetype="text/javascript")

    @app.route("/favicon.ico")
    def favicon():
        """站点图标（浏览器默认请求 /favicon.ico）：静态品牌 logo 缩图。"""
        return send_from_directory(str(BASE_DIR / "static"), "favicon.png",
                                   mimetype="image/png")

    @app.route("/branding/<path:filename>")
    def branding(filename):
        """Serve branding assets (logo, watermark) directly from the branding/ folder.

        Needed so the topbar logo can display before generate.py has ever run
        (generate.py copies branding → output/branding/ only once a report is produced).
        """
        target = BRANDING_DIR / filename
        if not target.exists():
            abort(404)
        return send_from_directory(str(BRANDING_DIR), filename, as_attachment=False)

    @app.errorhandler(413)
    def request_entity_too_large(error):
        return jsonify({"ok": False, "error": "文件太大，单文件不超过 50MB"}), 413

    # 品牌化错误页：页面路由渲染纸感错误模板，API 路由保持 JSON 信封。
    def _render_error(code: int, title: str, message: str):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": f"{code} {title}"}), code
        return render_template("error.html", code=code, title=title,
                               message=message), code

    @app.errorhandler(403)
    def _forbidden(error):
        return _render_error(403, "无权访问", "你没有权限访问该页面，或登录状态已失效。")

    @app.errorhandler(404)
    def _not_found(error):
        return _render_error(404, "页面不存在", "你访问的页面不存在或已被移除。")

    @app.errorhandler(500)
    def _server_error(error):
        return _render_error(500, "服务异常", "服务器处理请求时出错了，请稍后重试。")

    @app.route("/")
    def landing():
        return render_template("landing.html")

    # --- 管理端模板上下文（Layout 契约，所有蓝图模板共享；须在注册蓝图前） ---
    from app_utils import register_admin_context, get_csrf_token, dt_short
    register_admin_context(app)
    # CSRF token 注入：所有模板可调用 {{ csrf_token() }}（5.4 最小实现）
    app.context_processor(lambda: {"csrf_token": get_csrf_token})
    # 时间戳过滤器：模板用 {{ iso|dt_short }} 统一到分钟（面板/学生端共用）
    app.add_template_filter(dt_short, "dt_short")

    # --- CSRF 全局校验（session 认证面；before_request 比逐路由装饰器更难漏） ---
    import hmac as _hmac
    CSRF_EXEMPT_PREFIXES = (
        "/api/v1/",           # Bearer token 面，无 cookie，豁免
        "/q/",                # 一次性 token 端点（/q/<token>/submit），靠不可枚举 token 防 CSRF
    )
    CSRF_EXEMPT_PATHS = {
        "/api/booking",      # 公开预约，无 session 可劫持
        "/student/login",    # pre-auth 提交端点（由登录限流保护）；管理端登录态下同一浏览器
                             # 提交学生登录也不应被 CSRF 误拒
    }

    @app.before_request
    def _csrf_protect():
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return
        path = request.path
        if any(path.startswith(p) for p in CSRF_EXEMPT_PREFIXES) or path in CSRF_EXEMPT_PATHS:
            return
        if not (session.get("user_id") or session.get("student_account_id")):
            # 未登录的公开端点（登录、公开预约等）不走 CSRF；登录面由限流保护
            return
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        if not sent or not _hmac.compare_digest(sent, session.get("_csrf_token", "")):
            if path.startswith("/api/"):
                return jsonify({"ok": False, "error": "CSRF 校验失败，请刷新页面重试"}), 403
            abort(403)

    # --- 注册蓝图（导入放在 create_app 内，避免与 app_utils 形成导入环） ---
    from blueprints.api_v1 import bp as api_v1_bp
    from blueprints.auth import bp as auth_bp
    from blueprints.copilot import bp as copilot_bp
    from blueprints.growth_talk import bp as growth_talk_bp
    from blueprints.insights import bp as insights_bp
    from blueprints.m1 import bp as m1_bp
    from blueprints.questionnaires import bp as questionnaires_bp
    from blueprints.reports import bp as reports_bp
    from blueprints.students import bp as students_bp
    from blueprints.system import bp as system_bp
    from blueprints.tools import bp as tools_bp
    from blueprints.workspace import bp as workspace_bp

    for _bp in (auth_bp, workspace_bp, students_bp, reports_bp,
                growth_talk_bp, copilot_bp, questionnaires_bp,
                insights_bp, m1_bp, tools_bp, system_bp, api_v1_bp):
        app.register_blueprint(_bp)

    return app


app = create_app()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "genjob":
        # 独立子进程执行生成管道：python app.py genjob <args.json>
        from blueprints.reports import _run_pipeline_job
        _args_path = sys.argv[2] if len(sys.argv) > 2 else ""
        try:
            _job_args = json.loads(Path(_args_path).read_text(encoding="utf-8"))
        except Exception:
            _job_args = {}
        sys.exit(_run_pipeline_job(_job_args))

    if len(sys.argv) > 1 and sys.argv[1] == "gtjob":
        # 独立子进程执行 Growth Talk 分析：python app.py gtjob <run_id>
        from growth_talk.jobs import run_analysis_job
        try:
            run_analysis_job(int(sys.argv[2]))
        except Exception:
            sys.exit(1)

    if len(sys.argv) > 1 and sys.argv[1] == "copilotjob":
        # 独立子进程执行 Copilot LLM 作业：python app.py copilotjob <job_id> <args.json>
        from growth_talk.jobs import run_copilot_job
        try:
            _copilot_args = json.loads(
                Path(sys.argv[3]).read_text(encoding="utf-8"))
        except Exception:
            _copilot_args = {}
        try:
            run_copilot_job(
                sys.argv[2], _copilot_args.get("kind"),
                _copilot_args.get("payload") or {})
        except Exception:
            sys.exit(1)

    if len(sys.argv) > 1 and sys.argv[1] == "run":
        import extract
        import validate
        from data_points import apply_report_data
        import generate as _generate_module

        print("=" * 60)
        print("开始执行完整流程: extract → validate → generate")
        print("=" * 60)
        print()

        try:
            print("[1/3] 提取数据 (extract)...")
            rc = extract.main()
            if rc != 0:
                print(f"提取失败 (返回 {rc})")
                sys.exit(1)
            print("提取成功")
            print()

            print("[2/3] 校验数据 (validate)...")
            try:
                validate.main()
                print("校验成功")
            except Exception as exc:
                print(f"校验警告: {exc}")
            print()

            print("[3/3] 生成 PDF (generate)...")
            apply_report_data()
            _generate_module.main()
            print("生成成功")
            print()

            pdf_path = OUTPUT_DIR / "report.pdf"
            if pdf_path.exists():
                print(f"PDF 已生成: {pdf_path}")
                print(f"   大小: {pdf_path.stat().st_size / 1024:.1f} KB")
            else:
                print("PDF 生成失败")
                sys.exit(1)

        except Exception as exc:
            tb = traceback.format_exc()
            print(f"执行失败: {exc}")
            print(tb)
            sys.exit(1)

    else:
        port = int(os.environ.get("PORT", 8000))
        app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
