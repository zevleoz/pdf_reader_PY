"""极简 Web 前端：4 份 PDF (A2/B3/B4/B6) → 生成综合 PDF → 下载。

路由：
  GET  /                      → 上传页面（4 个带命名的上传槽 + 底部生成按钮）
  POST /api/generate          → 接收 4 份 PDF，顺序执行 extract → validate → generate，
                                 然后把 output/report.pdf 返回为附件
  GET  /output/<filename>     → 直接下载生成的文件
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import List, Optional

from flask import (Flask, jsonify, render_template, request,
                   send_from_directory, abort)

import extract
import validate
import generate as _generate_module
from data_points import apply_report_data

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
DATA_DIR = BASE_DIR / "data"
TEMPLATE_DIR = BASE_DIR / "templates"
BRANDING_DIR = BASE_DIR / "branding"

INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

REQUIRED_KEYS: List[str] = ["A2", "B3", "B4", "B6"]

app = Flask(__name__, template_folder=str(TEMPLATE_DIR),
            static_folder=str(OUTPUT_DIR), static_url_path="/output")

app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')


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
def index():
    return render_template("index.html")


@app.route("/preview")
def preview():
    from generate import build_view_data, render_html
    from data_points import apply_report_data
    apply_report_data()
    view_data = build_view_data()
    from pathlib import Path as P
    output_path = OUTPUT_DIR / "preview.html"
    render_html(view_data, output_path)
    return send_from_directory(str(OUTPUT_DIR), "preview.html")


# ---------------------------------------------------------------------------
# 核心接口：接收 4 份 PDF → 跑管道 → 返回 report.pdf
# ---------------------------------------------------------------------------
@app.route("/api/generate", methods=["POST"])
def api_generate():
    # 1) 接收1-4个文件，不再强制要求4个
    files_by_key = {}
    for key in REQUIRED_KEYS:
        f = request.files.get(key)
        if f and f.filename:
            files_by_key[key] = f
    
    if not files_by_key:
        return jsonify({
            "ok": False,
            "error": "请至少上传一份PDF文件"
        }), 400

    # 2) 清空 input/ 旧文件，按 report_<KEY>.pdf 保存
    try:
        for old in INPUT_DIR.glob("*.pdf"):
            old.unlink()
    except OSError:
        pass

    saved_names = {}
    try:
        for key, f in files_by_key.items():
            target = INPUT_DIR / f"report_{key}.pdf"
            f.save(str(target))
            saved_names[key] = f.filename
    except Exception as exc:
        return jsonify({"ok": False,
                         "error": f"保存上传文件失败: {exc}"}), 500

    try:
        # 3) extract：解析 4 份 PDF → data/report_data.json
        #    ⚠️  extract.py 现在强制依赖视觉 OCR API；如果 API 未配置或
        #    调用失败，extract.main() 会抛出 RuntimeError，此处直接转
        #    成 JSON 错误响应给前端（浏览器弹窗提示）。
        rc = extract.main()
        if rc != 0:
            return jsonify({
                "ok": False,
                "error": f"提取数据失败 (extract.main() 返回 {rc})。请检查输入 PDF 是否可读，或查看日志。"
            }), 500

        # 4) validate：做一次完整性校验（非阻塞，失败也继续）
        try:
            validate.main()
        except Exception:
            pass

        # 5) 关键点：让 data_points 基于新的 report_data.json 重新填充 USER_DATA
        apply_result = apply_report_data()

        # 5b) 如果用户手动输入了思维模式分值，覆盖提取的数据
        mindset_score = request.form.get('mindset_score')
        if mindset_score:
            try:
                score_val = float(mindset_score)
                if 0 <= score_val <= 100:
                    from data_points import USER_DATA
                    USER_DATA['059'] = str(score_val)
                    print(f"[思维模式] 用户手动输入分值: {score_val}")

                    # 同时更新 report_data.json，避免被 build_view_data() 中的
                    # apply_report_data() 覆盖
                    report_data_path = DATA_DIR / "report_data.json"
                    if report_data_path.exists():
                        try:
                            with open(report_data_path, 'r', encoding='utf-8') as f:
                                report_data = json.load(f)
                            for item in report_data.get('schema_124', []):
                                if item.get('code') == '059':
                                    item['value'] = str(score_val)
                                    break
                            with open(report_data_path, 'w', encoding='utf-8') as f:
                                json.dump(report_data, f, ensure_ascii=False, indent=2)
                            print(f"[思维模式] 已更新 report_data.json 中的 059 值为 {score_val}")
                        except Exception as e:
                            print(f"[思维模式] 更新 report_data.json 失败: {e}")
            except ValueError:
                pass

        # 6) 清理 output/ 旧产物，避免 chrome 基于旧文件命名出错
        for suffix in (".pdf", ".html"):
            old = OUTPUT_DIR / f"report{suffix}"
            if old.exists():
                try:
                    old.unlink()
                except OSError:
                    pass

        # 7) 重新 import generate 模块，使 build_view_data 里读取 USER_DATA 的值是最新的
        #    注：generate 的函数/常量会引用 data_points.USER_DATA（全局），
        #    在 apply_report_data 之后，值已经被更新。不需要 reload，直接跑 main 即可。
        try:
            _generate_module.main()
        except SystemExit as exc:
            if exc.code not in (None, 0):
                return jsonify({"ok": False,
                                 "error": f"生成 PDF 失败: SystemExit({exc.code})"}), 500
        except Exception as exc:
            tb = traceback.format_exc()
            return jsonify({"ok": False,
                             "error": f"生成 PDF 时异常: {exc}",
                             "trace": tb}), 500

        pdf_path = OUTPUT_DIR / "report.pdf"
        if not pdf_path.exists():
            return jsonify({
                "ok": False,
                "error": "生成流程完成，但未在 output/ 下找到 report.pdf。请检查 Chrome 是否可用（本地部署需安装 Chrome/Chromium）。"
            }), 500

        # 8) 返回 PDF 作为附件
        #    同时把摘要放到自定义响应头里，前端若需要可读取做展示
        resp = send_from_directory(
            str(OUTPUT_DIR), "report.pdf",
            as_attachment=True,
            download_name="综合测评报告.pdf",
            mimetype="application/pdf",
        )
        resp.headers["X-Applied-Items"] = str(apply_result.get("applied", 0))
        resp.headers["X-Total-Items"] = str(apply_result.get("total_items", 0))
        return resp

    except Exception as exc:
        tb = traceback.format_exc()
        return jsonify({"ok": False,
                         "error": f"服务端异常: {exc}",
                         "trace": tb}), 500


# ---------------------------------------------------------------------------
# 静态输出文件访问
# ---------------------------------------------------------------------------
@app.route("/output/<path:filename>")
def download(filename):
    target = OUTPUT_DIR / filename
    if not target.exists():
        abort(404)
    return send_from_directory(str(OUTPUT_DIR), filename, as_attachment=False)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        print("="*60)
        print("开始执行完整流程: extract → validate → generate")
        print("="*60)
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
                print(f"✅ PDF 已生成: {pdf_path}")
                print(f"   大小: {pdf_path.stat().st_size / 1024:.1f} KB")
            else:
                print("❌ PDF 生成失败")
                sys.exit(1)

        except Exception as exc:
            tb = traceback.format_exc()
            print(f"❌ 执行失败: {exc}")
            print(tb)
            sys.exit(1)

    else:
        port = int(os.environ.get("PORT", 8000))
        app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
