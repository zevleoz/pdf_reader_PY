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
import os
import sys
import traceback
from pathlib import Path

from flask import Flask, jsonify, render_template, send_from_directory, abort
from werkzeug.middleware.proxy_fix import ProxyFix

import db as _db
from app_utils import (BASE_DIR, INPUT_DIR, OUTPUT_DIR, DATA_DIR, TEMPLATE_DIR,
                       BRANDING_DIR, UPLOAD_DIR, JOB_FILE, JOB_LOG_FILE,
                       Y4_API_CORS_ORIGINS)

# 保留旧环境变量读取（迁移期不再用于放行；仅保留读取，见 app_utils 装饰器）。
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'y4admin2026')


def create_app() -> Flask:
    """构建 Flask app：全局配置 + 静态资源路由 + 注册全部蓝图。"""
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _db.init_db()

    # static_folder=None：不注册 Flask 内置的 /output 静态路由（它会绕过鉴权、暴露
    # 全部生成产物）。/output/<filename> 统一由 reports 蓝图带鉴权的 download 处理。
    app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=None)
    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
    app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')

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

    @app.route("/app_shell.css")
    def serve_app_shell_css():
        """Serve shared app-shell CSS (sidebar navigation)."""
        return send_from_directory(str(TEMPLATE_DIR), "app_shell.css", mimetype="text/css")

    @app.route("/app_shell.js")
    def serve_app_shell_js():
        """Serve shared app-shell JS (sidebar navigation, command palette)."""
        return send_from_directory(str(TEMPLATE_DIR), "app_shell.js", mimetype="application/javascript")

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

    @app.route("/")
    def landing():
        return render_template("landing.html")

    # --- 注册蓝图（导入放在 create_app 内，避免与 app_utils 形成导入环） ---
    from blueprints.api_v1 import bp as api_v1_bp
    from blueprints.auth import bp as auth_bp
    from blueprints.insights import bp as insights_bp
    from blueprints.questionnaires import bp as questionnaires_bp
    from blueprints.reports import bp as reports_bp
    from blueprints.students import bp as students_bp
    from blueprints.system import bp as system_bp
    from blueprints.tools import bp as tools_bp
    from blueprints.workspace import bp as workspace_bp

    for _bp in (auth_bp, workspace_bp, students_bp, reports_bp,
                questionnaires_bp, insights_bp, tools_bp, system_bp, api_v1_bp):
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
