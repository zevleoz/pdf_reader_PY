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
import re
import sys
import traceback
from datetime import date, timedelta
from functools import wraps
from pathlib import Path
from typing import List, Optional, Dict

from flask import (Flask, jsonify, render_template, request,
                   send_from_directory, send_file, abort, session, redirect)

import extract
import validate
import generate as _generate_module
from data_points import apply_report_data
import db as _db
import evaluation_rules as _eval_rules

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
DATA_DIR = BASE_DIR / "data"
TEMPLATE_DIR = BASE_DIR / "templates"
BRANDING_DIR = BASE_DIR / "branding"

INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
_db.init_db()

REQUIRED_KEYS: List[str] = ["A2", "B3", "B4", "B6"]

app = Flask(__name__, template_folder=str(TEMPLATE_DIR),
            static_folder=str(OUTPUT_DIR), static_url_path="/output")

app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'y4admin2026')


def admin_required(f):
    """Decorator: require admin session for mutating endpoints."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('is_admin'):
            return jsonify({"ok": False, "error": "需要管理员权限"}), 403
        return f(*args, **kwargs)
    return wrapper


def page_login_required(f):
    """Decorator: require admin session for page routes. Redirects to /login if not logged in."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect('/login?next=' + request.path)
        return f(*args, **kwargs)
    return wrapper


@app.route("/style.css")
def serve_style():
    """Serve shared design-system CSS from templates/style.css."""
    css_path = TEMPLATE_DIR / "style.css"
    return send_from_directory(str(TEMPLATE_DIR), "style.css", mimetype="text/css")


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


@app.route("/login")
def login_page():
    return render_template("login.html")


@app.route("/generate")
@page_login_required
def index():
    return render_template("index.html")


@app.route("/preview")
@page_login_required
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
# 进度查询接口（供前端进度条轮询）
# ---------------------------------------------------------------------------
@app.route("/api/progress", methods=["GET"])
@admin_required
def api_progress():
    prog_file = DATA_DIR / "_progress.json"
    if prog_file.exists():
        try:
            return jsonify(json.loads(prog_file.read_text(encoding="utf-8")))
        except Exception:
            pass
    return jsonify({"stage": "idle", "percent": 0, "message": ""})


# ---------------------------------------------------------------------------
# 核心接口：接收 4 份 PDF → 跑管道 → 返回 report.pdf
# ---------------------------------------------------------------------------
@app.route("/api/generate", methods=["POST"])
@admin_required
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
            # 保留原始文件名中的版本信息（初中/高中）
            original_name = f.filename or ""
            if key == "B6" and ("高中" in original_name or "初中" in original_name):
                # 提取版本关键词，附加到标准文件名
                version = "高中" if "高中" in original_name else "初中"
                target = INPUT_DIR / f"report_{key}_{version}.pdf"
            else:
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
        #    清理所有 report.pdf/html 以及动态命名的 凭远Y4评测报告_*.pdf/html
        for pattern in ["report.pdf", "report.html", "凭远Y4评测报告_*.pdf", "凭远Y4评测报告_*.html"]:
            for old in OUTPUT_DIR.glob(pattern):
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

        # Find the generated PDF (could be named with student name or report.pdf)
        pdf_files = sorted(OUTPUT_DIR.glob("*.pdf"))
        pdf_path = None
        if pdf_files:
            # Prefer the dynamically named file
            named = [f for f in pdf_files if "凭远Y4评测报告" in f.name]
            if named:
                pdf_path = named[0]
            else:
                pdf_path = pdf_files[0]

        if not pdf_path or not pdf_path.exists():
            import subprocess as _sp
            chrome_found = None
            for p in ["/usr/bin/chromium-browser", "/usr/bin/chromium",
                      "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"]:
                if Path(p).exists():
                    chrome_found = p
                    break
            if not chrome_found:
                for cmd in ["chromium-browser", "chromium", "google-chrome", "google-chrome-stable"]:
                    try:
                        r = _sp.run(["which", cmd], capture_output=True, text=True)
                        if r.returncode == 0 and r.stdout.strip():
                            chrome_found = r.stdout.strip()
                            break
                    except Exception:
                        pass
            return jsonify({
                "ok": False,
                "error": f"生成流程完成，但未在 output/ 下找到 PDF。Chrome 检测: {chrome_found or '未找到'}。请检查 Chrome 是否可用。",
                "chrome_path": chrome_found,
            }), 500

        # 8) Save to database (non-blocking, best-effort)
        try:
            report_data_path = DATA_DIR / "report_data.json"
            if report_data_path.exists():
                rd = json.loads(report_data_path.read_text(encoding="utf-8"))
                student_info = rd.get("student", {}) or {}
                sname = student_info.get("name", "").strip()

                # Use student_id from dropdown if provided, else manual name, else from PDF
                selected_sid = request.form.get("student_id", "").strip()
                manual_name = request.form.get("manual_student_name", "").strip()

                if selected_sid:
                    # Use the pre-selected student from booking
                    sid = int(selected_sid)
                    sname = sname or manual_name or f"学生#{sid}"
                    # Update student info from PDF if available
                    if student_info:
                        _db.update_student(sid, **{k: v for k, v in {
                            "gender": student_info.get("gender", ""),
                            "birthday": student_info.get("birthday", ""),
                            "grade": student_info.get("grade", ""),
                        }.items() if v})
                    print(f"[DB] 关联到预约学生: {sname} (id={sid})")
                elif manual_name:
                    sid = _db.find_or_create_student(name=manual_name)
                    sname = manual_name
                    print(f"[DB] 手动输入学生: {sname} (id={sid})")
                elif sname:
                    sid = _db.find_or_create_student(
                        name=sname,
                        gender=student_info.get("gender", ""),
                        birthday=student_info.get("birthday", ""),
                        grade=student_info.get("grade", ""),
                    )
                    print(f"[DB] 从PDF提取学生: {sname} (id={sid})")
                else:
                    sid = None

                if sid:
                    _db.add_report(
                        student_id=sid,
                        report_date=date.today(),
                        pdf_path=str(pdf_path),
                        data_json=report_data_path.read_text(encoding="utf-8"),
                    )
        except Exception as e:
            print(f"[DB] 保存报告失败 (非致命): {e}")

        # 9) 返回 PDF 作为附件
        download_filename = pdf_path.name
        resp = send_from_directory(
            str(OUTPUT_DIR), pdf_path.name,
            as_attachment=True,
            download_name=download_filename,
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
# AI 聊天接口：接收用户消息 + 历史对话 → 调 DashScope 文本 LLM → 返回回复
# ---------------------------------------------------------------------------
@app.route("/api/chat", methods=["POST"])
@admin_required
def api_chat():
    import urllib.request as _ureq

    data = request.get_json(force=True)
    user_message = data.get("message", "").strip()
    history = data.get("history", [])

    if not user_message and not history:
        return jsonify({"ok": False, "error": "消息不能为空"}), 400

    # 1) 读取 AI prompt
    prompt_path = BASE_DIR / "prompts" / "ai_interpreter.md"
    system_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else "你是测评解读助手。"

    # 2) 读取 report_data.json 作为上下文
    report_path = DATA_DIR / "report_data.json"
    if report_path.exists():
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
        schema_items = report_data.get("schema_124", [])
        data_text = "\n".join(
            f"{it.get('code','?')} {it.get('label','?')}：{it.get('value', '—')}"
            for it in schema_items if it.get("value")
        )
        student = report_data.get("student", {})
        student_text = f"学生：{student.get('name','—')}，{student.get('gender','—')}，{student.get('grade','—')}"
        context = f"{student_text}\n\n测评数据：\n{data_text}"
    else:
        context = "（暂无测评数据）"

    # 3) 组装 messages
    messages = [
        {"role": "system", "content": system_prompt + "\n\n以下是学生测评数据：\n" + context},
    ]
    messages.extend(history[-10:])
    if user_message:
        messages.append({"role": "user", "content": user_message})

    # 4) 调用 DashScope OpenAI 兼容接口
    dashscope_key = os.environ.get("DASHSCOPE_API_KEY", extract.DEFAULT_DASHSCOPE_KEY).strip()
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    payload = json.dumps({
        "model": os.environ.get("AI_TEXT_MODEL", "qwen-plus"),
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 8192,
    }).encode("utf-8")
    req = _ureq.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {dashscope_key}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _ureq.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        reply = result["choices"][0]["message"]["content"]
        return jsonify({"ok": True, "reply": reply})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"AI 调用失败: {exc}"}), 500


# ---------------------------------------------------------------------------
# 静态输出文件访问
# ---------------------------------------------------------------------------
@app.route("/output/<path:filename>")
@admin_required
def download(filename):
    target = OUTPUT_DIR / filename
    if not target.exists():
        abort(404)
    return send_from_directory(str(OUTPUT_DIR), filename, as_attachment=False)


# ---------------------------------------------------------------------------
# 解读会会议纪要生成
# ---------------------------------------------------------------------------
@app.route("/transcript")
@page_login_required
def transcript_page():
    """Render the transcript upload / summary generation page."""
    return render_template("transcript.html")


@app.route("/api/transcript", methods=["POST"])
@admin_required
def api_transcript():
    import urllib.request as _ureq

    data = request.get_json(force=True)
    transcript_text = (data.get("transcript") or "").strip()
    student_name = (data.get("student_name") or "").strip()
    student_grade = (data.get("student_grade") or "").strip()
    student_gender = (data.get("student_gender") or "").strip()
    student_id = data.get("student_id")
    report_id = data.get("report_id")
    custom_prompt = (data.get("custom_prompt") or "").strip()

    if len(transcript_text) < 50:
        return jsonify({"ok": False, "error": "逐字稿太短，至少 50 字"}), 400

    # ------------------------------------------------------------------
    # 1) Resolve student + report info (if student_id/report_id given)
    # ------------------------------------------------------------------
    resolved_sid = None
    resolved_rid = None
    if student_id:
        try:
            resolved_sid = int(student_id)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "student_id 格式错误"}), 400
    if report_id:
        try:
            resolved_rid = int(report_id)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "report_id 格式错误"}), 400

    report_summary = "（暂无测评数据）"

    if resolved_rid:
        # Specific report given → use its raw data
        rec = _db.get_report_raw(resolved_rid)
        if rec:
            raw = rec.get("raw") or {}
            schema_items = raw.get("schema_124", [])
            lines = []
            for item in schema_items:
                val = item.get("value", "")
                if val and str(val).strip() not in ("", "—", None):
                    lines.append(f"  {item.get('label', item.get('code', '?'))}: {val}")
            if lines:
                report_summary = "\n".join(lines[:60])
            # Fill empty student info from report record
            if not student_name:
                student_name = rec.get("student_name", "")
            stu_info = (raw.get("student") or {}) if isinstance(raw, dict) else {}
            if not student_grade:
                student_grade = rec.get("grade") or stu_info.get("grade", "") or ""
            if not student_gender:
                student_gender = stu_info.get("gender", "") or ""
    elif resolved_sid:
        # Student only, no specific report → take the latest report for that student
        reports = _db.get_student_reports(resolved_sid)
        if reports:
            latest = reports[0]
            resolved_rid = latest.get("id")
            rec = _db.get_report_raw(resolved_rid)
            if rec:
                raw = rec.get("raw") or {}
                schema_items = raw.get("schema_124", [])
                lines = []
                for item in schema_items:
                    val = item.get("value", "")
                    if val and str(val).strip() not in ("", "—", None):
                        lines.append(f"  {item.get('label', item.get('code', '?'))}: {val}")
                if lines:
                    report_summary = "\n".join(lines[:60])
                if not student_name:
                    student_name = rec.get("student_name", "")
                stu_info = (raw.get("student") or {}) if isinstance(raw, dict) else {}
                if not student_grade:
                    student_grade = rec.get("grade") or stu_info.get("grade", "") or ""
                if not student_gender:
                    student_gender = stu_info.get("gender", "") or ""
        # If student has no reports, fallback to name from students table
        if not student_name:
            for s in _db.get_students():
                if s["id"] == resolved_sid:
                    student_name = s.get("name", "")
                    student_grade = student_grade or s.get("grade", "") or ""
                    break
    else:
        # Backward-compat: read current-session report_data.json
        report_path = DATA_DIR / "report_data.json"
        if report_path.exists():
            try:
                rd = json.loads(report_path.read_text(encoding="utf-8"))
                s124 = rd.get("schema_124", [])
                lines = []
                for item in s124:
                    val = item.get("value", "")
                    if val and str(val).strip() not in ("", "—", None):
                        lines.append(f"  {item.get('label', item.get('code', '?'))}: {val}")
                if lines:
                    report_summary = "\n".join(lines[:60])
                # Also autofill student info
                stu_info = rd.get("student", {}) or {}
                if not student_name:
                    student_name = stu_info.get("name", "")
                if not student_grade:
                    student_grade = stu_info.get("grade", "") or ""
                if not student_gender:
                    student_gender = stu_info.get("gender", "") or ""
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 2) Build system prompt (custom_prompt overrides file)
    # ------------------------------------------------------------------
    if custom_prompt:
        system_prompt = custom_prompt
    else:
        prompt_path = BASE_DIR / "prompts" / "transcript_summary.md"
        system_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else "你是解读会纪要撰写人。"

    # No string-replace on system_prompt. All dynamic context goes in user
    # message to match the user prompt's framing ("基于接下来提供的...").

    # ------------------------------------------------------------------
    # 3) Assemble messages
    # ------------------------------------------------------------------
    effective_name = student_name or "未填写"
    user_content = (
        "## 学生基本信息\n"
        f"姓名：{effective_name}\n"
        f"年级：{student_grade or '—'}\n"
        f"性别：{student_gender or '—'}\n\n"
        "## Y4 测评数据摘要（供交叉验证参考，如果和会议内容无关可以忽略）\n"
        f"{report_summary}\n\n"
        "## 解读会录音转写/会议纪要\n"
        f"{transcript_text[:12000]}\n\n"
        "请基于以上提供的录音转写/会议纪要，直接生成最终会议记录。"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    # ------------------------------------------------------------------
    # 4) Call DashScope API — prefer ITERATION_MODEL (qwen-turbo by default)
    # ------------------------------------------------------------------
    dashscope_key = os.environ.get("DASHSCOPE_API_KEY", extract.DEFAULT_DASHSCOPE_KEY).strip()
    model_name = (
        os.environ.get("ITERATION_MODEL")
        or os.environ.get("AI_TEXT_MODEL")
        or "qwen-turbo"
    )
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    payload = json.dumps({
        "model": model_name,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 8192,
    }).encode("utf-8")
    req = _ureq.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {dashscope_key}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _ureq.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        summary = result["choices"][0]["message"]["content"]
    except Exception as exc:
        return jsonify({"ok": False, "error": f"AI 调用失败: {exc}"}), 500

    # ------------------------------------------------------------------
    # 5) Fix title placeholder: 【学生姓名】 → actual name
    # ------------------------------------------------------------------
    if effective_name and effective_name != "未填写":
        summary = summary.replace("【学生姓名】", effective_name)

    # ------------------------------------------------------------------
    # 6) Persist to DB if student_id is linked
    # ------------------------------------------------------------------
    minutes_id = None
    if resolved_sid:
        try:
            minutes_id = _db.add_minutes(
                student_id=resolved_sid,
                report_id=resolved_rid,
                transcript_text=transcript_text[:50000],
                minutes_text=summary,
            )
        except Exception as e:
            print(f"[DB] 会议纪要保存失败 (非致命): {e}")

    return jsonify({
        "ok": True,
        "summary": summary,
        "minutes_id": minutes_id,
        "student_id": resolved_sid,
        "report_id": resolved_rid,
        "student_name": student_name,
        "student_grade": student_grade,
        "student_gender": student_gender,
    })


def _build_docx(summary_text: str, student_name: str = "", student_grade: str = "",
               student_gender: str = "") -> bytes:
    """Convert markdown-style meeting minutes text into a styled Word .docx file.
    Supports #/##/### ATX headings, **bold**, bullet lines (- / •), [ ]/[x] checkboxes,
    and quote lines. Preserves the old **一、xxx** bold-heading format for backward compat.
    Returns the raw bytes of the docx file.
    """
    import re
    import io
    from docx import Document
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    # ---- Page margins ----
    for section in doc.sections:
        section.top_margin = Cm(2.2)
        section.bottom_margin = Cm(2.2)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)

    # ---- Base styles ----
    style = doc.styles["Normal"]
    style.font.name = "微软雅黑"
    style.font.size = Pt(11)
    style.font.color.rgb = RGBColor(0x14, 0x14, 0x14)

    # ---- Title ----
    title_line = "凭远教育 · Y4 解读会会议纪要"
    if student_name:
        title_line += f" — {student_name}"
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_p.add_run(title_line)
    title_run.bold = True
    title_run.font.size = Pt(18)
    title_run.font.color.rgb = RGBColor(0x14, 0x14, 0x14)
    title_run.font.name = "微软雅黑"
    title_p.paragraph_format.space_after = Pt(6)

    # ---- Student info table ----
    from datetime import datetime
    info_line = f"学生：{student_name or '—'}"
    if student_grade:
        info_line += f"　｜　年级：{student_grade}"
    if student_gender:
        info_line += f"　｜　性别：{student_gender}"
    info_line += f"　｜　生成时间：{datetime.now().strftime('%Y-%m-%d')}"
    meta_p = doc.add_paragraph()
    meta_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta_run = meta_p.add_run(info_line)
    meta_run.font.size = Pt(10)
    meta_run.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
    meta_p.paragraph_format.space_after = Pt(16)

    # ---- Red divider ----
    div_p = doc.add_paragraph()
    div_run = div_p.add_run("━" * 30)
    div_run.font.color.rgb = RGBColor(0xB3, 0x3A, 0x3A)
    div_run.font.size = Pt(10)
    div_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    div_p.paragraph_format.space_after = Pt(12)

    # ---- Parse lines and build document structure ----
    # Heading patterns: **一、** legacy bold-heading; ATX # / ## / ###
    heading_legacy_re = re.compile(r"^\s*\*\*(.+?)\*\*\s*(?:（(.+?)）)?\s*$")
    atx_h1_re = re.compile(r"^\s*#\s+(.+?)\s*$")
    atx_h2_re = re.compile(r"^\s*##\s+(.+?)\s*$")
    atx_h3_re = re.compile(r"^\s*###\s+(.+?)\s*$")
    # Bullet markers
    bullet_chars = ("•", "·", "-", "*", "【")

    lines = summary_text.split("\n")

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()

        # Skip separator lines like "---"
        if re.match(r"^-+$", stripped) or re.match(r"^=+$", stripped) or re.match(r"^━+$", stripped):
            continue
        if stripped.startswith("> ") or stripped == ">":
            # Markdown quote line → treat as italic small paragraph
            if stripped == ">":
                continue
            q = stripped[2:].strip()
            if q:
                p = doc.add_paragraph()
                run = p.add_run(q)
                run.italic = True
                run.font.size = Pt(10)
                run.font.color.rgb = RGBColor(0x4A, 0x4A, 0x4A)
            continue

        # === ATX headings (new prompt format, check first so # wins over other patterns) ===
        m_h1 = atx_h1_re.match(stripped)
        if m_h1:
            hp = doc.add_paragraph()
            r = hp.add_run(m_h1.group(1).strip())
            r.bold = True
            r.font.size = Pt(16)
            r.font.color.rgb = RGBColor(0xB3, 0x3A, 0x3A)  # red (H1)
            r.font.name = "微软雅黑"
            hp.paragraph_format.space_before = Pt(14)
            hp.paragraph_format.space_after = Pt(6)
            continue
        m_h2 = atx_h2_re.match(stripped)
        if m_h2:
            hp = doc.add_paragraph()
            r = hp.add_run(m_h2.group(1).strip())
            r.bold = True
            r.font.size = Pt(14)
            r.font.color.rgb = RGBColor(0xB3, 0x3A, 0x3A)  # deep red (H2)
            r.font.name = "微软雅黑"
            hp.paragraph_format.space_before = Pt(12)
            hp.paragraph_format.space_after = Pt(4)
            continue
        m_h3 = atx_h3_re.match(stripped)
        if m_h3:
            hp = doc.add_paragraph()
            r = hp.add_run(m_h3.group(1).strip())
            r.bold = True
            r.font.size = Pt(12)
            r.font.color.rgb = RGBColor(0x14, 0x14, 0x14)  # ink (H3)
            r.font.name = "微软雅黑"
            hp.paragraph_format.space_before = Pt(10)
            hp.paragraph_format.space_after = Pt(3)
            continue

        # Legacy heading: **一、核心发现 · 3 条**（...）
        m_leg = heading_legacy_re.match(stripped)
        if m_leg:
            section_title = m_leg.group(1).strip()
            section_subtitle = m_leg.group(2).strip() if m_leg.group(2) else None
            hp = doc.add_paragraph()
            hrun = hp.add_run(section_title)
            hrun.bold = True
            hrun.font.size = Pt(14)
            hrun.font.color.rgb = RGBColor(0xB3, 0x3A, 0x3A)
            hrun.font.name = "微软雅黑"
            hp.paragraph_format.space_before = Pt(12)
            hp.paragraph_format.space_after = Pt(4)
            if section_subtitle:
                subrun = hp.add_run(f" （{section_subtitle}）")
                subrun.bold = False
                subrun.font.size = Pt(10)
                subrun.font.color.rgb = RGBColor(0x8A, 0x8A, 0x8A)
            continue

        if not stripped:
            continue  # empty line

        # Check if it's a sub-heading line (bold **...** without a bullet)
        if stripped.startswith("**") and stripped.endswith("**") and not any(stripped.startswith(b) for b in bullet_chars):
            subh = stripped[2:-2]
            hp2 = doc.add_paragraph()
            r2 = hp2.add_run(subh)
            r2.bold = True
            r2.font.size = Pt(11.5)
            r2.font.color.rgb = RGBColor(0x14, 0x14, 0x14)
            hp2.paragraph_format.space_before = Pt(8)
            hp2.paragraph_format.space_after = Pt(2)
            continue

        # Bullet lines (starts with bullet char, possibly after whitespace)
        is_bullet = False
        content = stripped
        checkbox = ""
        # Strip leading bullet marker
        lead = re.match(r"^(\s*[-•·*·]\s*(?:\[\s*[xX\s]\]\s*)?)", content)
        if lead:
            marker = lead.group(1)
            if "[ ]" in marker or "［］" in marker or "[  ]" in marker:
                checkbox = "☐"
            elif re.search(r"\[\s*[xX]\s*\]", marker):
                checkbox = "☑"
            content = content[lead.end():].strip()
            is_bullet = True

        if not is_bullet and (content.startswith("【") or content.startswith("• ") or content.startswith("· ")):
            is_bullet = True
            if content.startswith("• "):
                content = content[2:]
            elif content.startswith("· "):
                content = content[2:]

        # Strip inline **...** bold markers and convert to rich runs
        tokens = re.split(r"(\*\*[^*]+\*\*)", content)
        if is_bullet:
            bullet_prefix = f"{checkbox} • " if checkbox else "• "
            # Build paragraph with bullet marker (no List Bullet style for consistency)
            p2 = doc.add_paragraph()
            b_run = p2.add_run(bullet_prefix)
            b_run.font.color.rgb = RGBColor(0xB3, 0x3A, 0x3A)
            b_run.bold = True
            p2.paragraph_format.space_before = Pt(2)
            p2.paragraph_format.space_after = Pt(2)
            p2.paragraph_format.left_indent = Cm(0.6)
            # Append content tokens
            for tok in tokens:
                if tok.startswith("**") and tok.endswith("**"):
                    r = p2.add_run(tok[2:-2])
                    r.bold = True
                    r.font.size = Pt(11)
                else:
                    r = p2.add_run(tok)
                    r.font.size = Pt(11)
            continue

        # Plain paragraph (non-heading, non-bullet)
        pp = doc.add_paragraph()
        pp.paragraph_format.space_before = Pt(2)
        pp.paragraph_format.space_after = Pt(2)
        pp.paragraph_format.line_spacing = Pt(20)
        for tok in tokens:
            if tok.startswith("**") and tok.endswith("**"):
                r = pp.add_run(tok[2:-2])
                r.bold = True
                r.font.size = Pt(11)
            else:
                r = pp.add_run(tok)
                r.font.size = Pt(11)

    # ---- Footer divider ----
    doc.add_paragraph()
    footer_div = doc.add_paragraph()
    fd_run = footer_div.add_run("— 凭远教育 · Y4 综合测评系统 —")
    fd_run.font.size = Pt(9)
    fd_run.font.color.rgb = RGBColor(0x8A, 0x8A, 0x8A)
    footer_div.alignment = WD_ALIGN_PARAGRAPH.CENTER

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@app.route("/api/transcript/docx", methods=["POST"])
@admin_required
def api_transcript_docx():
    """Generate minutes as DOCX file.

    Two input modes:
      A) {minutes_id: N} → load from DB, auto-fills student info + minutes_text
      B) {summary, student_name, student_grade, student_gender} → legacy mode

    Returns the .docx binary as attachment download.
    """
    data = request.get_json(force=True)
    minutes_id = data.get("minutes_id")
    summary_text = ""
    student_name = ""
    student_grade = ""
    student_gender = ""

    if minutes_id:
        mrec = _db.get_minutes(int(minutes_id))
        if not mrec:
            return jsonify({"ok": False, "error": "纪要不存在"}), 404
        summary_text = mrec.get("minutes_text", "") or ""
        student_name = mrec.get("student_name", "") or ""
        student_grade = mrec.get("student_grade", "") or ""
        student_gender = mrec.get("student_gender", "") or ""
    else:
        summary_text = (data.get("summary") or "").strip()
        student_name = (data.get("student_name") or "").strip()
        student_grade = (data.get("student_grade") or "").strip()
        student_gender = (data.get("student_gender") or "").strip()

    if not summary_text:
        return jsonify({"ok": False, "error": "纪要内容为空"}), 400

    try:
        docx_bytes = _build_docx(summary_text, student_name, student_grade, student_gender)
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        return jsonify({"ok": False, "error": f"DOCX 生成失败: {exc}", "trace": tb}), 500

    filename_suffix = student_name if student_name else "纪要"
    filename = f"凭远Y4解读会纪要_{filename_suffix}.docx"
    safe_name = filename.encode("utf-8").decode("latin-1", "ignore")
    from flask import Response
    resp = Response(
        docx_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename=\"{safe_name}\"; filename*=UTF-8''{filename}"
        }
    )
    return resp


# ---------------------------------------------------------------------------
# Meeting minutes management APIs
# ---------------------------------------------------------------------------

@app.route("/api/students/<int:student_id>/minutes")
@admin_required
def api_student_minutes(student_id):
    """List all historical meeting minutes for a student (desc by created_at)."""
    items = _db.get_minutes_by_student(student_id)
    return jsonify({"ok": True, "minutes": items})


@app.route("/api/minutes/<int:minutes_id>")
@admin_required
def api_minutes_detail(minutes_id):
    """Get single meeting minutes: transcript + minutes_text + student info."""
    item = _db.get_minutes(minutes_id)
    if not item:
        return jsonify({"ok": False, "error": "纪要不存在"}), 404
    return jsonify({"ok": True, **item})


@app.route("/api/minutes/<int:minutes_id>", methods=["PUT"])
@admin_required
def api_minutes_update(minutes_id):
    """Update minutes (e.g. re-generate with new transcript / manual edits)."""
    data = request.get_json(force=True) or {}
    fields = {}
    for k in ("transcript_text", "minutes_text", "report_id"):
        if k in data and data[k] is not None:
            fields[k] = data[k]
    if not fields:
        return jsonify({"ok": True})
    try:
        _db.update_minutes(minutes_id, **fields)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/minutes/<int:minutes_id>", methods=["DELETE"])
@admin_required
def api_minutes_delete(minutes_id):
    try:
        _db.delete_minutes(minutes_id)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Student management
# ---------------------------------------------------------------------------
@app.route("/students")
@page_login_required
def students_page():
    return render_template("students.html")


@app.route("/api/students")
@admin_required
def api_students():
    students = _db.get_students()
    return jsonify({"ok": True, "students": students})


@app.route("/api/students/<int:student_id>/reports")
@admin_required
def api_student_reports(student_id):
    reports = _db.get_student_reports(student_id)
    return jsonify({"ok": True, "reports": reports})


@app.route("/dashboard")
@page_login_required
def dashboard_page():
    return render_template("dashboard.html")


@app.route("/api/dashboard/stats")
@admin_required
def api_dashboard_stats():
    stats = _db.get_dashboard_stats()
    stats["indicators"] = _db.get_indicator_aggregates()
    stats["indicator_distributions"] = _db.get_indicator_distributions()
    stats["student_profiles"] = _db.get_student_profiles()
    stats["dimension_correlations"] = _db.get_dimension_correlations()
    stats["indicator_trends"] = _db.get_indicator_trends()
    stats["cluster_patterns"] = _db.get_cluster_patterns()
    stats["dimension_balance"] = _db.get_dimension_balance()
    return jsonify({"ok": True, "stats": stats})


@app.route("/api/dashboard/ai-analysis")
@admin_required
def api_dashboard_ai_analysis():
    """AI 跨维度关联分析:基于分布、对比、关联三个维度,生成面向学生/家长的呈现式洞察。

    输出 JSON:dimension_summary + insights[{headline, detail, type}]
    """
    indicators = _db.get_indicator_aggregates()
    stats = _db.get_dashboard_stats()
    total_reports = stats["headline"]["total_reports"]
    total_students = stats["headline"]["total_students"]

    dim_summary = indicators.get("dimension_summary", {})
    distributions = _db.get_indicator_distributions()
    profiles = _db.get_student_profiles()
    correlations = _db.get_dimension_correlations()
    indicator_trends = _db.get_indicator_trends()
    cluster_patterns = _db.get_cluster_patterns()
    dimension_balance = _db.get_dimension_balance()

    # 1. 维度分布数据
    lines = [f"共 {total_reports} 份报告, {total_students} 名学生\n"]
    lines.append("【维度指标分布】")
    for dim in ["心力", "精力", "学习力", "生涯力"]:
        ds = dim_summary.get(dim, {})
        dist = distributions.get(dim, {})
        weak_names = ds.get("weak_names", [])
        line = f"{dim}: {dist.get('evaluated', 0)}/{dist.get('total', 0)} 个指标有评价"
        dist_dict = dist.get("distribution", {})
        if dist_dict:
            line += f", 评价分布: {dist_dict}"
        if weak_names:
            line += f", 常见偏弱项: {', '.join(weak_names)}"
        lines.append(line)
        # 补充该维度有评价的具体指标及其档位
        strong_inds = dist.get("strong_indicators", [])
        weak_inds = dist.get("weak_indicators", [])
        if strong_inds or weak_inds:
            ind_list = []
            for si in strong_inds[:5]:
                ind_list.append(f"{si['label']}(强项)")
            for wi in weak_inds[:5]:
                ind_list.append(f"{wi['label']}(偏弱 {wi.get('weak_pct', 0)}%)")
            lines.append(f"  - {dim} 具体指标: {', '.join(ind_list)}")

    # 2. 学生对比数据
    if profiles:
        lines.append("\n【学生对比】")
        for p in profiles:
            dims_str = ", ".join(
                f"{d}={p['dimensions'].get(d, {}).get('healthy', 0)}%" for d in ["心力", "精力", "学习力", "生涯力"]
            )
            tag = ""
            if p.get("is_healthiest"):
                tag = " (最健康)"
            elif p.get("is_needs_attention"):
                tag = " (需关注)"
            lines.append(f"{p['student_name']} ({p['grade']}){tag}: 整体健康度 {p['overall_health']}%, {dims_str}")

    # 3. 维度关联数据
    pairs = correlations.get("pairs", [])
    if pairs:
        lines.append("\n【维度间关联】")
        for pair in pairs:
            if pair["correlation"] > 0:
                lines.append(
                    f"{pair['dim_a']} 与 {pair['dim_b']}: 关联强度 {pair['correlation']} ({pair['strength']}), "
                    f"同时偏弱 {pair['co_weak']} 人"
                )

    # 4. 指标级趋势(具体指标,非维度汇总)
    weak_inds = indicator_trends.get("most_frequently_weak", [])[:5]
    if weak_inds:
        lines.append("\n【指标级趋势 — 最常偏弱的 5 个具体指标】")
        for ind in weak_inds:
            lines.append(
                f"{ind['label']} ({ind['dim']}): {ind['weak_count']}/{ind['total_count']} 人偏弱, "
                f"涉及学生: {', '.join(ind['weak_students'][:5])}"
            )

    # 5. 学生聚类画像
    clusters = cluster_patterns.get("clusters", [])
    if clusters:
        lines.append("\n【学生聚类画像 — 按弱项维度签名分组】")
        for c in clusters[:5]:
            lines.append(
                f"弱项组合「{c['signature']}」: {c['count']} 人, 平均健康度 {c['overall_health_avg']}%, "
                f"成员: {', '.join(c['students'][:5])}"
            )
    balanced = cluster_patterns.get("balanced_count", 0)
    if balanced > 0:
        lines.append(f"无弱项(均衡型): {balanced} 人")

    # 6. 维度平衡度
    bal_students = dimension_balance.get("students", [])
    if bal_students:
        lines.append("\n【维度平衡度】")
        lines.append(f"平均平衡度 {dimension_balance.get('avg_balance_score', 0)}, "
                     f"严重失衡学生 {dimension_balance.get('imbalanced_count', 0)} 人")
        for s in bal_students:
            if s.get("is_imbalanced"):
                lines.append(
                    f"{s['student_name']}: 平衡度 {s['balance_score']}, "
                    f"最弱维度 {s['weakest_dim']}, 最强维度 {s['strongest_dim']}, 差距 {s['gap']}"
                )

    data_summary = "\n".join(lines)

    system = f"""你是 Y4 测评项目的负责人,正在向学生和家长做成果汇报。基于聚合测评数据,提炼有价值的洞察。

【硬规则】
1. 禁止创造新术语、新标签、新分类,只用 Y4 已有词汇(心力/精力/学习力/生涯力)。
2. 禁止出现指标编号(如 009、063 等),只用指标的中文名称。
3. 禁止使用 markdown 格式(无 ### 标题、无 bullet 符号、无 ** 加粗)。
4. 用平实中文,面向非专业受众(学生和家长),语气自然,像一位老师在解读数据。
5. 每条洞察必须有数据依据,但不暴露原始编号。数据中不存在的结论不得编造。
6. 禁止心理学/治疗术语,禁止连字符组合造词。
7. 正确示例:"精力维度表现较弱的学生,在学习动机上也普遍偏低,说明身体状态直接影响学习投入"
8. 错误示例:"009 情绪稳定性总分偏低与 063 执行功能偏低同时出现"
9. 每条 insight 的 detail 必须至少引用一个数据中出现过的具体指标中文名称(如"睡眠习惯""焦虑安详""执行功能-工作记忆"),禁止只用维度名概括。
10. 禁止将多个指标打包成数据中不存在的组合名(如"情绪耗竭""认知负荷"),只能用"XX 维度的 XX 指标"这种指代方式。

【输出格式】
只输出一个 JSON 对象,不要输出其他文字。格式如下:
```json
{{
  "dimension_summary": "一段话(2-3句)总结四维整体健康度,指出哪个维度最强、哪个需要关注",
  "insights": [
    {{"headline": "一句话标题(10-20字)", "detail": "2-3句解释", "type": "distribution"}},
    {{"headline": "...", "detail": "...", "type": "comparison"}},
    {{"headline": "...", "detail": "...", "type": "correlation"}}
  ]
}}
```
type 取值:
- "distribution": 关于指标分布的洞察(某维度哪些指标普遍高/低)
- "comparison": 关于学生间差异的洞察(不同学生群体或个体差异)
- "correlation": 关于维度间关联的洞察(哪些维度经常一起弱/强)
- "indicator": 关于具体指标的洞察(哪个指标最常弱,影响哪些学生,为什么重要)
- "cluster": 关于学生群体结构的洞察(某类弱项组合的共性,这群学生有何特征)
- "leverage": 关于杠杆点的洞察(改善哪个维度/指标最能提升整体健康度)
生成 4-6 条 insights,尽量覆盖至少 4 种 type。"""

    user = f"【聚合数据】\n{data_summary}"

    model = os.environ.get("DASHBOARD_AI_MODEL", "qwen-turbo")
    timeout = int(os.environ.get("DASHBOARD_AI_TIMEOUT", "60"))

    try:
        r = _dashscope_chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            model=model, timeout=timeout, max_tokens=2000,
        )
        content = r["content"].strip()
        # 提取 JSON 代码块
        import re, json as _json
        m = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
        if not m:
            m = re.search(r"(\{.*\})", content, re.DOTALL)
        if m:
            parsed = _json.loads(m.group(1))
            return jsonify({
                "ok": True,
                "analysis": parsed,
                "stats": {"tokens": r["tokens"], "time_ms": r["time_ms"], "model": model},
            })
        else:
            return jsonify({
                "ok": True,
                "analysis": {"dimension_summary": content[:300], "insights": []},
                "stats": {"tokens": r["tokens"], "time_ms": r["time_ms"], "model": model},
            })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# Admin authentication
# ---------------------------------------------------------------------------
@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    data = request.get_json(force=True)
    password = data.get("password", "")
    if password == ADMIN_PASSWORD:
        session['is_admin'] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "密码错误"}), 401


@app.route("/api/admin/logout", methods=["POST"])
def api_admin_logout():
    session.pop('is_admin', None)
    return jsonify({"ok": True})


@app.route("/api/admin/check")
def api_admin_check():
    return jsonify({"ok": True, "is_admin": bool(session.get('is_admin'))})


# ---------------------------------------------------------------------------
# Booking system
# ---------------------------------------------------------------------------
@app.route("/booking")
def booking_page():
    return render_template("booking.html")


@app.route("/api/booking", methods=["POST"])
def api_booking():
    from datetime import datetime
    data = request.get_json(force=True)
    name = (data.get("student_name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "学生姓名必填"}), 400
    appt_time_str = data.get("appointment_time", "")
    try:
        appt_time = datetime.fromisoformat(appt_time_str)
    except ValueError:
        return jsonify({"ok": False, "error": "时间格式错误"}), 400

    # Check slot capacity
    booking_date = appt_time.date()
    time_slot_str = appt_time.strftime("%H:%M")
    booking_counts = _db.get_slot_booking_counts(booking_date)
    booked = booking_counts.get(time_slot_str, 0)
    if booked >= SLOT_CAPACITY:
        return jsonify({"ok": False, "error": "该时段已满（" + str(booked) + "/" + str(SLOT_CAPACITY) + "），请选择其他时间"}), 409

    # Check admin hasn't closed this slot
    avail_entries = _db.get_availability(booking_date)
    avail_map = {e["time_slot"]: e["is_available"] for e in avail_entries}
    is_open = avail_map.get(time_slot_str, True)
    if not is_open:
        return jsonify({"ok": False, "error": "该时段已关闭，请选择其他时间"}), 409

    # Create student + booking in one transaction (auto-archive)
    student_id, booking_id = _db.create_booking_with_student(
        student_name=name,
        appointment_time=appt_time,
        advisor_name=(data.get("advisor_name") or "").strip(),
        school=(data.get("school") or "").strip(),
        single_parent=data.get("single_parent", "false"),
        notes=data.get("notes", ""),
    )
    return jsonify({"ok": True, "booking_id": booking_id, "student_id": student_id})


@app.route("/admin/bookings")
@page_login_required
def admin_bookings_page():
    return render_template("admin_bookings.html")


@app.route("/api/bookings")
@admin_required
def api_bookings():
    status = request.args.get("status")
    bookings = _db.get_bookings(status=status)
    return jsonify({"ok": True, "bookings": bookings})


@app.route("/api/booking/<int:booking_id>/complete", methods=["POST"])
@admin_required
def api_booking_complete(booking_id):
    try:
        sid = _db.complete_booking(booking_id)
        return jsonify({"ok": True, "student_id": sid})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 404


@app.route("/api/booking/<int:booking_id>/cancel", methods=["POST"])
@admin_required
def api_booking_cancel(booking_id):
    _db.update_booking_status(booking_id, "cancelled")
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Availability management
# ---------------------------------------------------------------------------
SLOT_CAPACITY = 4  # Max students per time slot


@app.route("/api/availability")
def api_get_availability():
    """Get availability for a given date. Query param: date=YYYY-MM-DD
    Returns each slot with is_available, booked_count, and capacity.
    Default: all slots available. Admin can close slots. Full slots (4/4) are unavailable.
    """
    date_str = request.args.get("date", "")
    if not date_str:
        return jsonify({"ok": False, "error": "请指定日期"}), 400
    try:
        date_val = date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"ok": False, "error": "日期格式错误"}), 400
    entries = _db.get_availability(date_val)
    booking_counts = _db.get_slot_booking_counts(date_val)
    # Build full slot list: no record = available (admin closes slots manually)
    all_slots = []
    available_map = {e["time_slot"]: e["is_available"] for e in entries}
    for ts in _db.TIME_SLOTS:
        is_open = available_map.get(ts, True)  # Default: available
        booked = booking_counts.get(ts, 0)
        is_av = is_open and booked < SLOT_CAPACITY
        all_slots.append({
            "time_slot": ts,
            "is_available": is_av,
            "is_open": is_open,
            "booked_count": booked,
            "capacity": SLOT_CAPACITY,
        })
    return jsonify({"ok": True, "date": date_str, "slots": all_slots})


@app.route("/api/availability/month")
def api_availability_month():
    """Get availability + booking counts for next 30 days (for admin calendar management)."""
    today = date.today()
    end = today + timedelta(days=29)
    range_data = _db.get_availability_range(today, end)
    booking_counts = _db.get_booking_counts_range(today, end)
    return jsonify({
        "ok": True,
        "start": today.isoformat(),
        "end": end.isoformat(),
        "data": range_data,
        "bookings": booking_counts,
    })


@app.route("/api/availability", methods=["POST"])
@admin_required
def api_set_availability():
    """Batch set availability for a date. Admin only.
    Body: {"date": "YYYY-MM-DD", "slots": [{"time_slot": "09:00", "is_available": true}, ...]}
    """
    data = request.get_json(force=True)
    date_str = data.get("date", "")
    slots = data.get("slots", [])
    if not date_str:
        return jsonify({"ok": False, "error": "请指定日期"}), 400
    try:
        date_val = date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"ok": False, "error": "日期格式错误"}), 400
    _db.batch_set_availability(date_val, slots)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# 报告原始数据取回（生成时已保存完整 report_data.json 到 reports.data_json）
# ---------------------------------------------------------------------------
@app.route("/api/reports/<int:report_id>/raw")
@admin_required
def api_report_raw(report_id):
    """Get the raw data of a report. Add ?download=1 to download as JSON file."""
    record = _db.get_report_raw(report_id)
    if not record:
        return jsonify({"ok": False, "error": "报告不存在"}), 404

    # 过滤掉职业价值观得分（095-109），只保留排序项（110-124）
    raw = dict(record.get("raw") or {})
    s124 = [it for it in (raw.get("schema_124") or []) if not _eval_rules.is_hidden_raw(it)]
    raw["schema_124"] = s124
    record = {**record, "raw": raw}

    if request.args.get("download"):
        import io as _io
        filename = f"raw_data_{record['student_name'] or record['report_id']}_{record['report_date'] or ''}.json"
        buf = _io.BytesIO(json.dumps(record["raw"], ensure_ascii=False, indent=2).encode("utf-8"))
        return send_file(buf, mimetype="application/json", as_attachment=True,
                         download_name=filename)

    return jsonify({"ok": True, **record})


@app.route("/api/reports/<int:report_id>/interpret", methods=["POST"])
@admin_required
def api_report_interpret(report_id):
    """AI 解读：用该报告已保存的 raw data 调 DashScope，结果存回 reports.interpretation。
    不重跑 OCR，不读 data/report_data.json。
    """
    import urllib.request as _ureq

    record = _db.get_report_raw(report_id)
    if not record:
        return jsonify({"ok": False, "error": "报告不存在"}), 404

    raw = record.get("raw") or {}
    schema_items = raw.get("schema_124", [])
    data_text = "\n".join(
        f"{it.get('code','?')} {it.get('label','?')}：{it.get('value', '—')}"
        for it in schema_items if it.get("value")
    )
    student = raw.get("student", {})
    student_text = f"学生：{student.get('name','—')}，{student.get('gender','—')}，{student.get('grade','—')}"
    context = f"{student_text}\n\n测评数据：\n{data_text}"

    prompt_path = BASE_DIR / "prompts" / "ai_interpreter.md"
    system_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else "你是测评解读助手。"

    messages = [
        {"role": "system", "content": system_prompt + "\n\n以下是学生测评数据：\n" + context},
        {"role": "user", "content": "请给出这份 Y4 报告的完整解读"},
    ]

    dashscope_key = os.environ.get("DASHSCOPE_API_KEY", extract.DEFAULT_DASHSCOPE_KEY).strip()
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    payload = json.dumps({
        "model": os.environ.get("AI_TEXT_MODEL", "qwen-plus"),
        "messages": messages,
        "temperature": float(os.environ.get("AI_TEMPERATURE", "0.5")),
        "max_tokens": 8192,
    }).encode("utf-8")
    req = _ureq.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {dashscope_key}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _ureq.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        reply = result["choices"][0]["message"]["content"]
        try:
            _db.save_interpretation(report_id, reply)
        except Exception as e:
            print(f"[DB] 解读结果保存失败 (非致命): {e}")
        return jsonify({"ok": True, "reply": reply})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"AI 调用失败: {exc}"}), 500


# ---------------------------------------------------------------------------
# 按报告的有效评价 qualification + 协议下载（生产版内部下载页用）
# ---------------------------------------------------------------------------
def _report_qualification_payload(report_id: int):
    """从 DB 取某报告的 raw schema_124 → 构建 qualification 视图 + report meta。

    Returns (payload_dict, error_or_None)。payload 含 items/student/summary/mapping_done/
    mapping_total/per_code_eval_options/data_bias_options/report。
    """
    record = _db.get_report_raw(report_id)
    if not record:
        return None, "报告不存在"
    raw = record.get("raw") or {}
    schema_items = [it for it in (raw.get("schema_124") or []) if not _eval_rules.is_hidden_raw(it)]
    student = raw.get("student", {}) or {}
    items, summary, mapping_done, per_code_opts = _build_qualification_view(schema_items)
    payload = {
        "items": items,
        "student": student,
        "summary": summary,
        "mapping_done": mapping_done,
        "mapping_total": len(items),
        "data_bias_options": _eval_rules.DATA_BIAS_OPTIONS,
        "per_code_eval_options": per_code_opts,
        "report": {
            "id": report_id,
            "report_date": record.get("report_date"),
            "student_name": record.get("student_name"),
            "interpretation": record.get("interpretation") or "",
        },
    }
    return payload, None


@app.route("/api/reports/<int:report_id>/qualification")
@admin_required
def api_report_qualification(report_id):
    """按报告取有效评价 qualification 视图（含 items/student/summary/E4 映射/per-code 选项）。"""
    payload, err = _report_qualification_payload(report_id)
    if err:
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True, **payload})


@app.route("/api/reports/<int:report_id>/protocol-md", methods=["POST"])
@admin_required
def api_report_protocol_md(report_id):
    """按报告下载 Y4 有效评价传递协议 Markdown（Phase 1）。

    body: {items: 调整后的 items, include_raw: bool, interpretation?: str(覆盖 DB)}
    student 从 DB report 取；interpretation 不传则用 DB 中已保存的解读。
    """
    import io as _io
    record = _db.get_report_raw(report_id)
    if not record:
        return jsonify({"ok": False, "error": "报告不存在"}), 404
    raw = record.get("raw") or {}
    student = raw.get("student", {}) or {}
    student_name = record.get("student_name") or student.get("name") or "测试"

    data = request.get_json(force=True) or {}
    items = data.get("items", [])
    include_raw = bool(data.get("include_raw", False))
    if "interpretation" in data and data.get("interpretation") is not None:
        interpretation = (data.get("interpretation") or "").strip()
    else:
        interpretation = (record.get("interpretation") or "").strip()

    md_text = _build_phase1_md_text(items, include_raw, interpretation, student, student_name)
    buf = _io.BytesIO(md_text.encode("utf-8"))
    return send_file(buf, mimetype="text/markdown", as_attachment=True,
                     download_name=f"有效评价_{student_name}_protocol.md")


@app.route("/api/reports/<int:report_id>/y4-json", methods=["POST"])
@admin_required
def api_report_y4_json(report_id):
    """按报告导出通用 Y4 JSON（按 Y4 四维组织全部数据点 + AI 解读 + 名单 + 问题级判定）。

    body: {items: 调整后的 items, interpretation?: str(覆盖 DB)}
    """
    record = _db.get_report_raw(report_id)
    if not record:
        return jsonify({"ok": False, "error": "报告不存在"}), 404
    raw = record.get("raw") or {}
    student = raw.get("student", {}) or {}
    student_name = record.get("student_name") or student.get("name") or "测试"

    data = request.get_json(force=True) or {}
    items = data.get("items", [])
    if "interpretation" in data and data.get("interpretation") is not None:
        interpretation = (data.get("interpretation") or "").strip()
    else:
        interpretation = (record.get("interpretation") or "").strip()

    payload = _build_y4_payload(items, interpretation, student, student_name)
    return jsonify({"ok": True, "json": payload,
                    "filename": f"{student_name.replace(' ', '')}_Y4数据.json"})


@app.route("/api/reports/<int:report_id>/e4-protocol", methods=["POST"])
@admin_required
def api_report_e4_protocol(report_id):
    """按报告一站式生成 E4 协议（step1 数据整编 + step2 跨维度分析 + step3 总览成文）。

    body: {items: 调整后的 items, include_raw: bool, interpretation?: str(覆盖 DB)}
    后端内部串行跑 step1→step2→step3，返回 content_md + stats + list_placement + student_name。
    interpretation 不传则用 DB 中已保存的解读。
    """
    record = _db.get_report_raw(report_id)
    if not record:
        return jsonify({"ok": False, "error": "报告不存在"}), 404
    raw = record.get("raw") or {}
    student = raw.get("student", {}) or {}
    student_name = record.get("student_name") or student.get("name") or "测试"

    data = request.get_json(force=True) or {}
    items = data.get("items", [])
    include_raw = bool(data.get("include_raw", False))
    if "interpretation" in data and data.get("interpretation") is not None:
        interpretation = (data.get("interpretation") or "").strip()
    else:
        interpretation = (record.get("interpretation") or "").strip()

    # Step1：数据整编（纯 Python）
    vgroups, other_items, _dims_by_code = _eval_rules.evaluate_question_verdicts(items)
    groups_payload: List[Dict[str, Any]] = []
    group_counts: Dict[str, int] = {d: 0 for d in _eval_rules.E4_DIMS}
    for g in vgroups:
        lines = [_format_e4_line(it, include_raw) for it in g["items"]]
        groups_payload.append({"dim": g["dim"], "q": g["q"], "lines": lines, "verdict": g.get("verdict")})
        group_counts[g["dim"]] += len(g["items"])
    other_lines = [_format_e4_line(it, include_raw) for it in other_items]
    list_placement = _determine_list_placement(items)

    # Step2：跨维度分析（AI）
    model2 = os.environ.get("E4_STEP2_MODEL", "qwen-turbo")
    timeout = int(os.environ.get("E4_STEP_TIMEOUT", "180"))
    all_lines: List[str] = []
    current_dim = None
    for g in groups_payload:
        dim = g.get("dim", "")
        if dim != current_dim:
            all_lines.append("")
            all_lines.append(f"## {_eval_rules.E4_LABELS.get(dim, dim)}")
            current_dim = dim
        q = g.get("q")
        if q:
            all_lines.append(f"问题：{q}")
        v = g.get("verdict")
        if v:
            cn = _eval_rules.VERDICT_LABELS_CN.get(v.get("state"), v.get("state", ""))
            all_lines.append(f"问题判定（Python 规则，须以此为准绳）：{cn} | {v.get('summary', '')}")
        all_lines.extend(g.get("lines") or [])
        all_lines.append("")
    if other_lines:
        all_lines.append("## OTHER_VARIABLES（框架未引用）")
        all_lines.extend(other_lines)
        all_lines.append("")

    analyses: Dict[str, str] = {d: "" for d in _eval_rules.E4_DIMS}
    full_analysis = ""
    stats2: List[Dict[str, Any]] = []
    if any(g.get("lines") for g in groups_payload):
        system2 = _e4_step2_system()
        user2 = ("【E4 框架数据（按维度和评估问题组织；问题下列出该问题涉及的指标数据）】\n"
                 + "\n".join(all_lines))
        try:
            r2 = _dashscope_chat(
                [{"role": "system", "content": system2},
                 {"role": "user", "content": user2}],
                model=model2, timeout=timeout, max_tokens=4000)
            full_analysis = _sanitize_e4_step2(r2["content"])
            analyses["_cross"] = _e4_step2_tail(full_analysis)
            stats2 = [{"dim": "ALL", "tokens": r2["tokens"], "time_ms": r2["time_ms"], "model": model2}]
        except Exception as exc:
            stats2 = [{"dim": "ALL", "tokens": 0, "time_ms": 0, "model": model2, "error": str(exc)}]
            full_analysis = f"（Step2 跨维度分析失败：{exc}）"

    # Step3：总览成文（AI；名单归属以 Python 规则为准，AI 不得改判）
    model3 = os.environ.get("E4_STEP3_MODEL", "qwen-plus")
    system3 = _e4_step3_system(list_placement.get("category")
                               or list_placement.get("placement") or "（未判定）")
    user3 = (f"【综合分析草稿】\n{full_analysis or analyses}\n\n"
             f"【Y4 原始 AI 解读（可选参考，非客观事实）】\n{interpretation or '（无）'}")
    try:
        r3 = _dashscope_chat(
            [{"role": "system", "content": system3},
             {"role": "user", "content": user3}],
            model=model3, timeout=timeout, max_tokens=2500)
        overview_md = r3["content"]
        stats3 = {"tokens": r3["tokens"], "time_ms": r3["time_ms"], "model": model3}
    except Exception as exc:
        overview_md = f"（总览生成失败：{exc}）"
        stats3 = {"tokens": 0, "time_ms": 0, "model": model3, "error": str(exc)}

    content_md = _assemble_e4_protocol(items, include_raw, analyses, overview_md,
                                      full_analysis, interpretation,
                                      student=student, student_name=student_name)
    return jsonify({
        "ok": True,
        "content_md": content_md,
        "stats": {"step2": stats2, "step3": stats3},
        "student_name": student_name,
        "list_placement": list_placement,
        "step1": {
            "groups": groups_payload,
            "other_lines": other_lines,
            "group_counts": group_counts,
            "unmapped_count": len(other_lines),
        },
    })


# ---------------------------------------------------------------------------
# 有效评价 (Y4 Evaluation) Markdown 下载
# ---------------------------------------------------------------------------
def _generate_interpretation_for_report(report_id: int):
    """即时为某报告生成 AI 解读并落库。加法式 helper，不修改既有 /interpret 路由。

    Returns: (reply_text, error_or_None)
    """
    import urllib.request as _ureq

    record = _db.get_report_raw(report_id)
    if not record:
        return None, "报告不存在"

    raw = record.get("raw") or {}
    schema_items = raw.get("schema_124", [])
    data_text = "\n".join(
        f"{it.get('code', '?')} {it.get('label', '?')}：{it.get('value', '—')}"
        for it in schema_items if it.get("value")
    )
    student = raw.get("student", {})
    student_text = f"学生：{student.get('name', '—')}，{student.get('gender', '—')}，{student.get('grade', '—')}"
    context = f"{student_text}\n\n测评数据：\n{data_text}"

    prompt_path = BASE_DIR / "prompts" / "ai_interpreter.md"
    system_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else "你是测评解读助手。"

    messages = [
        {"role": "system", "content": system_prompt + "\n\n以下是学生测评数据：\n" + context},
        {"role": "user", "content": "请给出这份 Y4 报告的完整解读"},
    ]

    dashscope_key = os.environ.get("DASHSCOPE_API_KEY", extract.DEFAULT_DASHSCOPE_KEY).strip()
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    payload = json.dumps({
        "model": os.environ.get("AI_TEXT_MODEL", "qwen-plus"),
        "messages": messages,
        "temperature": float(os.environ.get("AI_TEMPERATURE", "0.5")),
        "max_tokens": 8192,
    }).encode("utf-8")
    req = _ureq.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {dashscope_key}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _ureq.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        reply = result["choices"][0]["message"]["content"]
        try:
            _db.save_interpretation(report_id, reply)
        except Exception as e:
            print(f"[DB] 解读结果保存失败 (非致命): {e}")
        return reply, None
    except Exception as exc:
        return None, f"AI 调用失败: {exc}"


_DIM_ORDER = ["心力", "精力", "学习力", "生涯力"]
_DIM_LABELS = {
    "心力": "心力（情绪与动力系统）",
    "精力": "精力（精力管理与身体健康系统）",
    "学习力": "学习力（学习系统）",
    "生涯力": "生涯力（专业与职业发展系统）",
}


def _dimension_of(item: dict) -> str:
    """将一条 schema_124 数据点归类到 Y4 四维之一。

    以 label 关键词为主（实测数据 code 编号与 ai_interpreter.md 第四节的
    001-085 编号体系不同，故不按 code 区间映射），source_pdf 兜底。
    """
    label = item.get("label", "") or ""
    if any(k in label for k in ("体质", "精力", "睡眠", "饮食", "运动", "BMI", "身高", "体重")):
        return "精力"
    if any(k in label for k in ("情绪", "自尊", "自我概念", "依恋", "人格", "内驱", "自驱")):
        return "心力"
    if any(k in label for k in ("认知", "执行", "记忆", "注意", "推理", "动机", "学习方法", "策略", "自我效能", "工作记忆")):
        return "学习力"
    if any(k in label for k in ("霍兰德", "职业", "多元智能", "价值观", "能力优势", "生涯")):
        return "生涯力"

    # source_pdf 兜底
    src = item.get("source_pdf", "") or ""
    if src == "A2":
        return "心力"
    if src == "B4":
        return "学习力"
    if src == "B3":
        return "学习力"
    if src == "B6":
        return "生涯力"
    return "学习力"


@app.route("/api/reports/<int:report_id>/evaluation")
@admin_required
def api_report_evaluation(report_id):
    """下载某报告的「有效评价」Markdown 文件。

    包含：学生信息 + 全部 schema_124 数据点（按 Y4 四维分组）+ AI 解读全文。
    若解读尚未生成，则即时调 AI 生成并落库，随后打包返回。
    """
    import io as _io

    record = _db.get_report_raw(report_id)
    if not record:
        return jsonify({"ok": False, "error": "报告不存在"}), 404

    raw = record.get("raw") or {}
    student = raw.get("student", {}) or {}
    schema_items = [it for it in (raw.get("schema_124") or []) if not _eval_rules.is_hidden_raw(it)]

    student_id = record.get("student_id")
    interpretation = None
    if student_id:
        for r in _db.get_student_reports(student_id):
            if r.get("id") == report_id:
                interpretation = r.get("interpretation") or None
                break

    if not interpretation:
        interpretation, err = _generate_interpretation_for_report(report_id)
        if err:
            return jsonify({"ok": False, "error": err}), 500

    # ── 拼装 Markdown ─────────────────────────────────────────────
    md_lines = []
    student_name = student.get("name") or record.get("student_name") or str(report_id)
    report_date = record.get("report_date") or student.get("test_date") or ""

    md_lines.append(f"# Y4 有效评价 · {student_name}")
    md_lines.append("")
    md_lines.append("> 凭远教育 · Y4 综合测评系统")
    md_lines.append(f"> 报告编号：{report_id}" + (f" | 测评日期：{report_date}" if report_date else ""))
    md_lines.append("")
    md_lines.append("## 一、学生信息")
    md_lines.append("")
    md_lines.append("| 项目 | 内容 |")
    md_lines.append("|---|---|")
    info_rows = [
        ("姓名", student.get("name")),
        ("性别", student.get("gender")),
        ("出生", student.get("birthday")),
        ("年级", student.get("grade")),
        ("学校", student.get("school")),
        ("测评日期", student.get("test_date")),
        ("顾问", student.get("teacher")),
        ("档案号", student.get("archive_id")),
        ("报告代码", student.get("report_code")),
    ]
    for label, val in info_rows:
        if val:
            md_lines.append(f"| {label} | {val} |")
    md_lines.append("")

    md_lines.append("## 二、测评数据（按 Y4 四维分组）")
    md_lines.append("")
    # 分桶
    buckets: Dict[str, list] = {d: [] for d in _DIM_ORDER}
    for it in schema_items:
        if not it.get("value"):
            continue
        buckets[_dimension_of(it)].append(it)

    def _sort_key(it):
        c = str(it.get("code", ""))
        digits = ""
        for ch in c:
            if ch.isdigit():
                digits += ch
            else:
                break
        try:
            return (int(digits) if digits else 9999, c)
        except ValueError:
            return (9999, c)

    for dim in _DIM_ORDER:
        items = sorted(buckets[dim], key=_sort_key)
        if not items:
            continue
        md_lines.append(f"### {_DIM_LABELS[dim]}")
        for it in items:
            code = it.get("code", "?")
            label = it.get("label", "?")
            value = it.get("value", "—")
            unit = it.get("unit", "") or ""
            md_lines.append(f"- {code} {label}：{value}{unit}")
        md_lines.append("")

    md_lines.append("## 三、AI 有效评价解读")
    md_lines.append("")
    md_lines.append(interpretation or "（暂无解读）")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("本文件由 Y4 综合测评系统自动生成，供团队内部使用。")

    md_text = "\n".join(md_lines)

    filename = f"有效评价_{student_name}_{report_date}.md"
    buf = _io.BytesIO(md_text.encode("utf-8"))
    return send_file(buf, mimetype="text/markdown", as_attachment=True,
                     download_name=filename)


# ---------------------------------------------------------------------------
# Delete operations
# ---------------------------------------------------------------------------
@app.route("/api/students/<int:student_id>", methods=["DELETE"])
@admin_required
def api_delete_student(student_id):
    try:
        _db.delete_student(student_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/reports/<int:report_id>", methods=["DELETE"])
@admin_required
def api_delete_report(report_id):
    try:
        _db.delete_report(report_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/booking/<int:booking_id>", methods=["DELETE"])
@admin_required
def api_delete_booking(booking_id):
    try:
        _db.delete_booking(booking_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------
@app.route("/api/export")
@admin_required
def api_export():
    import csv
    import io
    reports = _db.get_all_reports()
    if not reports:
        return jsonify({"ok": False, "error": "暂无数据"}), 404

    # Collect all field codes across all reports
    all_codes = set()
    for r in reports:
        all_codes.update(r["data"].keys())
    sorted_codes = sorted(all_codes)

    output = io.StringIO()
    writer = csv.writer(output)
    header = ["报告ID", "学生姓名", "性别", "年级", "报告日期", "PDF路径"] + sorted_codes
    writer.writerow(header)
    for r in reports:
        row = [
            r["report_id"], r["student_name"], r["gender"] or "",
            r["grade"] or "", r["report_date"] or "", r["pdf_path"] or "",
        ]
        row.extend(r["data"].get(c, "") for c in sorted_codes)
        writer.writerow(row)

    output.seek(0)
    from flask import Response
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment;filename=y4_students.csv"},
    )


# ---------------------------------------------------------------------------
# Prompt 迭代测试台 (Prompt Lab)
# ---------------------------------------------------------------------------
PROMPT_VERSIONS_DIR = BASE_DIR / "prompts" / "versions"
PROMPT_VERSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _get_next_prompt_version() -> int:
    """Scan prompts/versions/ and return next version number."""
    existing = sorted(PROMPT_VERSIONS_DIR.glob("ai_interpreter_v*.md"))
    if not existing:
        return 1
    nums = []
    for f in existing:
        try:
            n = int(f.stem.split("_v")[1])
            nums.append(n)
        except (ValueError, IndexError):
            pass
    return max(nums) + 1 if nums else 1


@app.route("/prompt-lab")
@page_login_required
def prompt_lab_page():
    """Prompt iteration test bench."""
    return render_template("prompt_lab.html")


@app.route("/internal")
@page_login_required
def internal_download_page():
    """内部下载页：有效评价 qualification + 协议下载（生产版，不含 prompt 迭代工具）。"""
    return render_template("internal.html")


@app.route("/api/prompt-lab/run", methods=["POST"])
@admin_required
def prompt_lab_run():
    """Run AI interpretation using current prompt + report_data.json."""
    import urllib.request as _ureq
    import time as _time

    data = request.get_json(force=True)
    user_message = (data.get("message") or "请给出这份 Y4 报告的完整解读").strip()

    # 1) Read prompt
    prompt_path = BASE_DIR / "prompts" / "ai_interpreter.md"
    system_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else "你是测评解读助手。"

    # 2) Read report data
    report_path = DATA_DIR / "report_data.json"
    if not report_path.exists():
        return jsonify({"ok": False, "error": "没有测试数据 (report_data.json 不存在)"}), 400

    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    schema_items = report_data.get("schema_124", [])
    data_text = "\n".join(
        f"{it.get('code','?')} {it.get('label','?')}：{it.get('value', '—')}"
        for it in schema_items if it.get("value")
    )
    student = report_data.get("student", {})
    student_text = f"学生：{student.get('name','—')}，{student.get('gender','—')}，{student.get('grade','—')}"
    context = f"{student_text}\n\n测评数据：\n{data_text}"

    # 3) Build messages
    messages = [
        {"role": "system", "content": system_prompt + "\n\n以下是学生测评数据：\n" + context},
        {"role": "user", "content": user_message},
    ]

    # 4) Call DashScope
    dashscope_key = os.environ.get("DASHSCOPE_API_KEY", extract.DEFAULT_DASHSCOPE_KEY).strip()
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    payload = json.dumps({
        "model": os.environ.get("AI_TEXT_MODEL", "qwen-plus"),
        "messages": messages,
        "temperature": float(os.environ.get("AI_TEMPERATURE", "0.5")),
        "max_tokens": 8192,
    }).encode("utf-8")
    req = _ureq.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {dashscope_key}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    t0 = _time.time()
    try:
        with _ureq.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        reply = result["choices"][0]["message"]["content"]
        tokens_used = result.get("usage", {}).get("total_tokens", 0)
        elapsed_ms = int((_time.time() - t0) * 1000)
        return jsonify({"ok": True, "reply": reply, "tokens": tokens_used, "time_ms": elapsed_ms})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"AI 调用失败: {exc}"}), 500


@app.route("/api/prompt-lab/iterate", methods=["POST"])
@admin_required
def prompt_lab_iterate():
    """Auto-modify prompt based on user feedback, then return new prompt."""
    import urllib.request as _ureq

    data = request.get_json(force=True)
    feedback = (data.get("feedback") or "").strip()
    rating = data.get("rating", 3)
    last_output = (data.get("last_output") or "").strip()

    if not feedback:
        return jsonify({"ok": False, "error": "反馈不能为空"}), 400

    # 1) Read current prompt
    prompt_path = BASE_DIR / "prompts" / "ai_interpreter.md"
    current_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""

    # 2) Save current version
    version_num = _get_next_prompt_version()
    old_version_path = PROMPT_VERSIONS_DIR / f"ai_interpreter_v{version_num}.md"
    old_version_path.write_text(current_prompt, encoding="utf-8")

    # 3) Build meta-prompt for AI to improve the prompt
    meta_prompt = f"""你是一个 prompt 优化专家。你需要根据用户的反馈，修改 Y4 测评解读的 system prompt。

以下是当前用于 Y4 测评解读的 system prompt：
---
{current_prompt}
---

以下是用户对这个 prompt 生成输出的反馈：
评分：{rating}/5
反馈：{feedback}

上次 AI 的输出（供参考）：
---
{last_output[:3000]}
---

请根据用户反馈，修改上面的 system prompt。
要求：
- 只修改需要改进的部分，保留好的部分
- 输出完整的修改后的 prompt（不是 diff，不是解释，直接输出 prompt 全文）
- 保持 Y4 四维框架（心力/精力/学习力/生涯力）作为唯一语言体系
- 保持指标编号引用规范
- 不要加任何前缀说明或后缀解释"""

    messages = [{"role": "user", "content": meta_prompt}]

    # 4) Call DashScope to get improved prompt
    dashscope_key = os.environ.get("DASHSCOPE_API_KEY", extract.DEFAULT_DASHSCOPE_KEY).strip()
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    payload = json.dumps({
        "model": os.environ.get("AI_TEXT_MODEL", "qwen-plus"),
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 8192,
    }).encode("utf-8")
    req = _ureq.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {dashscope_key}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _ureq.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        new_prompt = result["choices"][0]["message"]["content"].strip()

        # 5) Write new prompt
        prompt_path.write_text(new_prompt, encoding="utf-8")

        # 6) Simple diff: find first and last differing lines
        old_lines = current_prompt.split("\n")
        new_lines = new_prompt.split("\n")
        diff_parts = []
        max_compare = min(len(old_lines), len(new_lines))
        first_diff = None
        last_diff = None
        for i in range(max_compare):
            if old_lines[i] != new_lines[i]:
                if first_diff is None:
                    first_diff = i
                last_diff = i
        if first_diff is not None:
            start = max(0, first_diff - 2)
            end = min(max_compare, last_diff + 3)
            diff_parts.append(f"改动区域（第 {start+1}-{end} 行附近）：")
            for i in range(start, end):
                marker = "→" if old_lines[i] != new_lines[i] else " "
                if old_lines[i] != new_lines[i]:
                    diff_parts.append(f"  {marker} 旧: {old_lines[i][:80]}")
                    diff_parts.append(f"  {marker} 新: {new_lines[i][:80]}")
        if len(new_lines) != len(old_lines):
            diff_parts.append(f"\n行数变化：{len(old_lines)} → {len(new_lines)}")
        diff_summary = "\n".join(diff_parts) if diff_parts else "无明显差异"

        return jsonify({
            "ok": True,
            "old_prompt": current_prompt,
            "new_prompt": new_prompt,
            "diff": diff_summary,
            "version": version_num,
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Prompt 迭代失败: {exc}"}), 500


@app.route("/api/prompt-lab/save", methods=["POST"])
@admin_required
def prompt_lab_save():
    """Manually save edited prompt."""
    data = request.get_json(force=True)
    prompt_text = data.get("prompt", "").strip()
    if not prompt_text:
        return jsonify({"ok": False, "error": "Prompt 不能为空"}), 400

    # Save old version first
    prompt_path = BASE_DIR / "prompts" / "ai_interpreter.md"
    if prompt_path.exists():
        version_num = _get_next_prompt_version()
        old_version_path = PROMPT_VERSIONS_DIR / f"ai_interpreter_v{version_num}.md"
        old_version_path.write_text(prompt_path.read_text(encoding="utf-8"), encoding="utf-8")

    prompt_path.write_text(prompt_text, encoding="utf-8")
    return jsonify({"ok": True})


@app.route("/api/prompt-lab/prompt", methods=["GET"])
@admin_required
def prompt_lab_get_prompt():
    """Get current prompt text."""
    prompt_path = BASE_DIR / "prompts" / "ai_interpreter.md"
    content = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
    return jsonify({"ok": True, "prompt": content})


# ---------------------------------------------------------------------------
# Prompt Lab 有效评价视图（Phase 1：交互 + 下载 mock）
# ---------------------------------------------------------------------------
def _build_qualification_view(schema_items: List[Dict[str, Any]]):
    """从 schema_124 构建 qualification 视图。

    返回 (items, summary, mapping_done, per_code_opts)。items 已附 e4_dims/e4_dim/e4_sub
    并按 Y4 维度排序。与数据来源解耦，供 prompt-lab（report_data.json）和按 report_id
    的生产接口（DB raw）共用。
    """
    items, summary = _eval_rules.build_evaluation_view(schema_items)
    # 附加用户指认的 E4 分类（无推断，未指认为空列表）
    mapping = _db.get_e4_mapping()
    for it in items:
        e4_maps = _eval_rules.e4_classify(it, mapping)
        it["e4_dims"] = e4_maps  # [{e4_dim, e4_sub}, ...]
        # 兼容前端：e4_dim/e4_sub 取第一个（用于 Y4 视图标注）
        it["e4_dim"] = e4_maps[0]["e4_dim"] if e4_maps else None
        it["e4_sub"] = e4_maps[0]["e4_sub"] if e4_maps else ""
    # 按维度分组排序
    items.sort(key=lambda it: (_eval_rules._DIM_ORDER.index(it["dimension"])
                               if it["dimension"] in _eval_rules._DIM_ORDER else 99,
                               _eval_rules.sort_key_code(it["code"])[0],
                               it["code"]))
    mapping_done = sum(1 for it in items if it["e4_dims"])
    # 构建 per-code eval_options（每个数据点有自己的档位体系）
    per_code_opts = {}
    for it in items:
        opts = _eval_rules.eval_options_for(it.get("code", ""), it.get("label", ""))
        per_code_opts[it.get("code", "")] = opts
    return items, summary, mapping_done, per_code_opts


@app.route("/api/prompt-lab/evaluation")
@admin_required
def prompt_lab_evaluation():
    """返回 report_data.json 的有效评价视图数据点。"""
    report_path = DATA_DIR / "report_data.json"
    if not report_path.exists():
        return jsonify({"ok": False, "error": "没有测试数据 (report_data.json 不存在)"}), 400
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    schema_items = report_data.get("schema_124", [])
    student = report_data.get("student", {}) or {}
    items, summary, mapping_done, per_code_opts = _build_qualification_view(schema_items)
    return jsonify({"ok": True, "items": items, "student": student, "summary": summary,
                    "mapping_done": mapping_done, "mapping_total": len(items),
                    "data_bias_options": _eval_rules.DATA_BIAS_OPTIONS,
                    "per_code_eval_options": per_code_opts})


def _build_phase1_md_text(items: List[Dict[str, Any]], include_raw: bool,
                          interpretation: str, student: Dict[str, Any],
                          student_name: str = "", now: str = "") -> str:
    """拼装 Y4 有效评价传递协议 v1.0 Markdown 文本。

    与具体数据来源（report_data.json 或 DB report）解耦：调用方传入 items、
    interpretation、student。expert_judgments 从 items 内的 adjusted/note 字段提取。
    """
    from datetime import datetime as _dt
    if not student_name:
        student_name = student.get("name") or "测试"
    if not now:
        now = _dt.now().strftime("%Y-%m-%d %H:%M")

    expert_judgments = []
    for it in items:
        note = (it.get("note") or "").strip()
        adjusted = it.get("adjusted", False)
        if note or adjusted:
            expert_judgments.append({
                "code": it.get("code"),
                "label": it.get("label"),
                "original": it.get("original_eval"),
                "adjusted": it.get("eval_value"),
                "note": note or None,
            })

    md: List[str] = []
    md.append("# Y4 有效评价传递协议 v1.0")
    md.append("")
    md.append("## META")
    md.append(f"student: {student_name} | date: {student.get('test_date','')} | protocol: v1.0 | generated: {now}")
    md.append(f"gender: {student.get('gender','')} | grade: {student.get('grade','')} | school: {student.get('school','')}")
    md.append(f"archive_id: {student.get('archive_id','')} | report_code: {student.get('report_code','')}")
    md.append("")
    md.append("## HIERARCHY_RULES")
    md.append("```")
    md.append("RAW_DATA → EFFECTIVE_EVALUATION → INTERPRETATION")
    md.append("")
    md.append("RAW_DATA: 原始测量值，仅作证据源")
    md.append("  - 下游 AI 禁止基于 raw 自行重新判断学生（Error 1）")
    md.append("  - raw 仅在 include_raw=true 时附在 [EVAL] 行")
    md.append("")
    md.append("EFFECTIVE_EVALUATION: 已确认评价，LOCKED")
    md.append("  - source=档位字段/规则推导: 自动生成")
    md.append("  - source=原始排序: 排序结果本身即结论，无需再评价")
    md.append("  - source=人工判断: 经人工调整，具最高权威，不可覆盖（Error 5）")
    md.append("  - 下游 AI 不可重新计算或覆盖任何 EFFECTIVE_EVALUATION")
    md.append("")
    md.append("INTERPRETATION: 基于有效评价的 AI 推理")
    md.append("  - 非客观事实，可参考但不可当事实引用（Error 2/3）")
    md.append("")
    md.append("EXPERT_JUDGMENT: 人工补充说明")
    md.append("  - 明确区分于客观测量，下游 AI 须标注来源")
    md.append("")
    md.append("EVIDENCE_TRACE: 结论→证据追溯")
    md.append("  - 下游 AI 须基于 trace 中的证据推理，不可超出边界（Error 6）")
    md.append("```")
    md.append("")
    md.append("## STUDENT_INFO")
    md.append(f"name: {student_name}")
    md.append(f"gender: {student.get('gender','')}")
    md.append(f"birthday: {student.get('birthday','')}")
    md.append(f"grade: {student.get('grade','')}")
    md.append(f"school: {student.get('school','')}")
    md.append(f"test_date: {student.get('test_date','')}")
    md.append("")
    md.append("## EFFECTIVE_EVALUATIONS")
    md.append("")
    buckets: Dict[str, list] = {d: [] for d in _eval_rules._DIM_ORDER}
    for it in items:
        dim = it.get("dimension") or _eval_rules.dimension_of(it)
        if dim not in buckets:
            dim = "学习力"
        buckets[dim].append(it)
    for dim in _eval_rules._DIM_ORDER:
        dim_items = sorted(buckets[dim], key=lambda it: _eval_rules.sort_key_code(it.get("code", "")))
        if not dim_items:
            continue
        md.append(f"### [{dim}] {_eval_rules._DIM_LABELS[dim]}")
        md.append("")
        for it in dim_items:
            code = it.get("code", "?")
            label = it.get("label", "?")
            raw_v = it.get("raw_value", "")
            eval_v = it.get("eval_value") or ""
            unit = it.get("unit", "") or ""
            src = it.get("eval_source", "待判定") or "待判定"
            adjusted = it.get("adjusted", False)
            original = it.get("original_eval", "")
            note = (it.get("note") or "").strip()
            if src == "参照值":
                md.append(f"[NORM] code:{code} | label:{label} | value:{raw_v}{unit} | source:参照值 | status:REFERENCE_ONLY")
                continue
            if src == "原始排序":
                md.append(f"[ORDER] code:{code} | label:{label} | value:{eval_v} | source:原始排序 | status:CONFIRMED | adjusted:NO")
                continue
            parts = [f"[EVAL] code:{code}", f"label:{label}"]
            if include_raw:
                parts.append(f"raw:{raw_v}{unit}")
            parts.append(f"eval:{eval_v}")
            parts.append(f"source:{src}")
            rn = it.get("rule_note")
            if rn:
                parts.append(f"rule:{rn}")
            parts.append("status:CONFIRMED")
            parts.append(f"adjusted:{'YES' if adjusted else 'NO'}")
            if adjusted and original:
                parts.append(f"original:{original}")
            md.append(" | ".join(parts))
        md.append("")
    md.append("## INTERPRETATION")
    md.append("")
    md.append("<!-- 以下为 AI 基于 EFFECTIVE_EVALUATIONS 的推理，非客观事实。下游 AI 引用时须标注 INTERPRETATION 来源 -->")
    md.append("")
    md.append(interpretation or "（未提供）")
    md.append("")
    md.append("## EXPERT_JUDGMENTS")
    md.append("")
    if expert_judgments:
        for j in expert_judgments:
            parts = [f"[JUDGE] code:{j['code']}", f"label:{j['label']}"]
            if j.get("original"):
                parts.append(f"original:{j['original']}")
            parts.append(f"adjusted:{j['adjusted']}")
            if j.get("note"):
                parts.append(f"note:{j['note']}")
            md.append(" | ".join(parts))
    else:
        md.append("（无人工调整）")
    md.append("")
    md.append("---")
    md.append("凭远教育 · Y4 综合测评系统 | 本文件为 AI→AI 传递协议，非人类报告")
    return "\n".join(md)


@app.route("/api/prompt-lab/evaluation/download", methods=["POST"])
@admin_required
def prompt_lab_evaluation_download():
    """下载 AI→AI 传递协议 Markdown（Phase 1）。

    入参: {items: [{code,label,raw_value,eval_value,dimension,unit,eval_source,note}],
           include_raw: bool, interpretation: str(可选)}
    """
    import io as _io
    data = request.get_json(force=True)
    items = data.get("items", [])
    include_raw = bool(data.get("include_raw", False))
    interpretation = (data.get("interpretation") or "").strip()

    # 取 student 信息
    report_path = DATA_DIR / "report_data.json"
    student = {}
    if report_path.exists():
        student = json.loads(report_path.read_text(encoding="utf-8")).get("student", {}) or {}
    student_name = student.get("name") or "测试"

    md_text = _build_phase1_md_text(items, include_raw, interpretation, student, student_name)
    buf = _io.BytesIO(md_text.encode("utf-8"))
    return send_file(buf, mimetype="text/markdown", as_attachment=True,
                     download_name=f"有效评价_{student_name}_protocol.md")


def _format_e4_line(it: Dict[str, Any], include_raw: bool, is_ref: bool = False) -> str:
    """格式化 E4 输出中的单行。

    精简版：无 code 前缀，默认值不显示，人机双友好。
    is_ref=True 时只输出引用行（多维度映射的第二次出现）。
    """
    label = it.get("label", "?")

    if is_ref:
        return f"[REF] {label} → 见首次出现维度"

    raw_v = it.get("raw_value", "")
    eval_v = it.get("eval_value") or ""
    unit = it.get("unit", "") or ""
    src = it.get("eval_source", "待判定") or "待判定"
    adjusted = it.get("adjusted", False)
    original = it.get("original_eval", "")
    note = (it.get("note") or "").strip()
    bias = it.get("data_bias", "正常") or "正常"
    problem = it.get("problem_status", "CONFIRMED") or "CONFIRMED"

    if src == "参照值":
        return f"[NORM] {label} | {raw_v}{unit}"

    if src == "原始排序":
        parts = [f"[ORDER] {label}", eval_v]
        if bias != "正常":
            parts.append(f"bias:{bias}")
        if problem == "OBSERVATION":
            parts.append("problem:OBSERVATION")
        return " | ".join(parts)

    parts = [f"[EVAL] {label}"]
    if include_raw and raw_v:
        parts.append(f"{raw_v}{unit}")
    # raw 与档位同值时（如思维模式结果 78.4|78.4）不重复显示
    if eval_v and str(eval_v).strip() != str(raw_v).strip():
        parts.append(eval_v)
    # 认知分项个体内强/弱特质标注（相对认知总百分位）
    trait = (it.get("trait_label") or "").strip()
    if trait:
        tn = (it.get("trait_note") or "").strip()
        parts.append(f"{trait}（{tn}）" if tn else trait)
    # 体质习惯得分行：得分无档位时显示 PDF 评级，避免「饮食0」被误读
    pdf_grade = (it.get("pdf_grade") or "").strip()
    if pdf_grade:
        parts.append(f"评级:{pdf_grade}")
    if src not in ("规则推导", "待判定"):
        parts.append(f"source:{src}")
    if bias != "正常":
        parts.append(f"bias:{bias}")
    if problem == "OBSERVATION":
        parts.append("problem:OBSERVATION")
    if adjusted and original:
        parts.append(f"adjusted:{original}→{eval_v}")
    if note:
        parts.append(f"note:{note}")
    return " | ".join(parts)


def _mapping_for(code, mapping: Dict[str, List[Dict[str, str]]]) -> List[Dict[str, str]]:
    """按 code 查映射（可多维度），兼容 "015" / "15" 两种形态。返回 [{e4_dim, e4_sub}, ...]。"""
    code = str(code)
    if code in mapping:
        return mapping[code]
    digits = "".join(ch for ch in code if ch.isdigit())
    return mapping.get(str(int(digits)), []) if digits else []


def _build_mapping_snapshot_md(mapping: Dict[str, List[Dict[str, str]]],
                               items: List[Dict[str, Any]]) -> str:
    """生成 MAPPING_SNAPSHOT：人工指认的 code → E4 维度/子类（Y4 原名，可多维度）。"""
    lines: List[str] = []
    for d in _eval_rules.E4_DIMS:
        lines.append(_eval_rules.E4_LABELS[d])
        rows = []
        for it in items:
            maps = _mapping_for(it.get("code", ""), mapping)
            dim_maps = [m for m in maps if m.get("e4_dim") == d]
            if dim_maps:
                sub = dim_maps[0].get("e4_sub", "") or "（未指定子类别）"
                rows.append(f"  {it.get('code','')} {it.get('label','')} → {sub}")
        lines.extend(sorted(rows) if rows else ["  （未指认任何指标）"])
        lines.append("")
    # 列出跨维度映射的指标
    multi = []
    for it in items:
        maps = _mapping_for(it.get("code", ""), mapping)
        if len(maps) > 1:
            dims_str = " + ".join(m.get("e4_dim", "") for m in maps)
            multi.append(f"  {it.get('code','')} {it.get('label','')} → {dims_str}")
    if multi:
        lines.append("【跨维度映射指标】")
        lines.extend(multi)
        lines.append("")
    return "\n".join(lines)


# ── E4 三步 AI 工作流 ─────────────────────────────────────────

_E4_NAMING_RULE = ("NAMING_RULE（硬约束）: Y4 报告的 label（指标名称）是唯一权威命名。"
                   "引用任何指标必须使用该原始名称，禁止改写、缩写、翻译或创造新术语。"
                   "E4 维度/子类仅为人工指认的分组标签，不是数据名称。")


def _dashscope_chat(messages: List[Dict[str, str]], model: str,
                    timeout: int = 180, max_tokens: int = 3000,
                    temperature: float = 0.4) -> Dict[str, Any]:
    """调用 DashScope chat completions。返回 {content, tokens, time_ms}，失败抛异常。"""
    import urllib.request as _ureq
    import time as _time

    dashscope_key = os.environ.get("DASHSCOPE_API_KEY", extract.DEFAULT_DASHSCOPE_KEY).strip()
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    req = _ureq.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {dashscope_key}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    t0 = _time.time()
    with _ureq.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return {
        "content": result["choices"][0]["message"]["content"],
        "tokens": result.get("usage", {}).get("total_tokens", 0),
        "time_ms": int((_time.time() - t0) * 1000),
    }


def _e4_step2_system() -> str:
    """Step2 system prompt：基于 E4 框架问题的 contextual 分析。

    数据按「维度→评估问题→指标」组织。AI 逐一回答框架问题，再做三段式综合（显著问题/可能失真·先观察/跟进线索与切入点）。
    """
    return f"""你是 Y4 测评 E4 评估框架的分析员。E4 框架是工作草稿工具，用于识别学生薄弱点与低垂果实（low-hanging fruits），非最终评估结论。

【数据结构】
数据按 E1（情绪）、E2（精力）、E3（引擎）、E4（参与投入）四个维度组织。
每个维度下有若干「评估问题」（以"问题："开头），问题下列出回答该问题所需的指标数据。
每个问题下还有一行「问题判定（Python 规则）」——规则引擎基于已确认阈值算出的问题级结论
（有问题/关注/观察/健康/中性）。这些判定行和数据行是给你看的输入，**严禁抄写进你的输出**
（后端会自动清洗回显行）。你的回答须与判定方向一致：可补充细节、证据和跨问题连结，
但不得推翻判定。

【你的任务】
1. 逐一回答评估问题：基于该问题下的指标数据，给出有信息量的判断。回答要直接回应问题本身。
2. 核心问题（有问题/关注）深入展开；健康/中性问题只写一句平实结论。
3. 逐问题判断完成后，按下方三段式做综合：先找最显著问题，再甄别可能失真、只需观察的数据，最后给跟进线索与切入点。

【去重硬规则（与术语规则同级，违反即重写）】
1. 禁止回显输入：输出中不得出现「问题判定」字样的行、不得出现任何 [EVAL]/[ORDER]/[NORM]/[REF] 开头的数据行、不得照抄数据清单。读者已在数据区看到全部数值，你的任务是给判断，不是搬运数据。
2. 健康/中性问题：保留 #### 问题标题，判断**限一句**平实结论，**不写任何数值**（例：「判断：该方面无异常」）。
3. 同一指标全文只展开一次：在它首次出现的问题下给出数值与完整解释；之后的问题只写与本问题相关的新角度，用指标名称引用、禁止重复数值和已说过的解释。
4. 末尾三个综合段是「索引与行动」，不是逐问题段落的缩写：显著问题每条一行（问题+处置类型+指标名称，不写数值、不复述原话）；跟进线索只写要做什么。

【思考方式】
你不是在填表，你是在做判断。对每个学生，分析的详略应该不同。
不要对每个数据点都写"可能影响XXX"——只写有信息量的关联。
看完后读者应该清楚：这个学生的问题在哪、哪些先观察、先做什么。

【硬规则】
1. {_E4_NAMING_RULE}
2. 只使用 Y4/E4 已有词汇，禁止创造新术语、新标签、新分类。具体禁止：心理学/治疗术语（如"情绪耗竭"、"负向耦合"、"恶性循环"）、连字符组合造词、为模式取新名字。正确方式：用指标名称直接描述状态和关联，如"情绪稳定性总分低与人格-外倾性得分低同时出现，可能相互影响"。
3. bias=偏高/偏低：数据可信度偏差，须询证验证，不可直接当客观事实。
4. problem:OBSERVATION：假问题（测评状态失真），观望处理，不可直接当结论。
5. 所有结论须标注依据指标名称；数据行中不存在的结论不得编造。
6. 同一指标可能出现在多个问题/维度中，不要重复相同描述，后续出现时简述关联即可。
7. 排序位置类数据（如"安全稳定排序位置 第10位/共15"）：位置数字越小排序越靠前（越重要）。
8. 体质健康习惯行的「得分」与「评级」并存时以评级为准：如「饮食习惯得分 0 | 评级:优」表示营养认知题答错但饮食行为健康，不是饮食问题，禁止据此建议干预饮食。
9. 认知百分位行上的「强特质/相对弱特质」标注是该生与自身认知能力总百分位的个体内比较，不是常模判定，只作识别参考；两者错位才产生判断（如感知觉强特质+注意力相对弱特质=潜在分心/粗心组合）。

【跟进线索映射】
数据命中对应特征时采用以下线索，没有命中不得生搬；允许点名凭远内部工具：
- 学习方法与策略-学习自我调节偏低 → 了解学生对各科老师的看法（尤其自己不喜欢的老师及沟通方式），可与三级象限图中学科投入的位置交叉验证。
- 依恋关系-亲近偏低（尤其母亲）→ 与测评解读师确认做测评解读时是否提及过该点。
- E2 睡眠/饮食/运动 → 向 Gary/Jeff 核实并更新数据（得分与评级冲突时以评级为准）；运动关注具体项目类型，可对照三级象限图中的运动类投入记录。
- 渴望成功动机成立（职业价值观·成就感排序前五）→ 访谈「过去一年学习中有成就感的时刻」，学习动机从成就感来源切入，鼓励家庭一起在学习过程中积累成就感，数据化记录是重要方式。
- 分心组合（高感知觉+相对弱注意力）→ 关注电子产品使用与做作业时的环境管理。
- 高确定性需求（职业兴趣-常规型不低/高，或职业价值观·安全稳定排前五）+ 计划性不足 + 学习策略使用少 → 用「一表人才」（结构化计划表/学习机制工具）帮学生搭建结构化学习过程，并在过程中逐步养成习惯。
- 执行功能弱项（如工作记忆、认知灵活性）若为施测末段题目、可能受疲劳影响 → 先观察，通过与学生/家长交流确认（如老师是否反馈过缺少举一反三的能力）。

【输出格式】markdown，按 E1→E2→E3→E4 顺序。
每个维度用 ### 标题，每个评估问题用 #### 开头（保留问题原文作为锚点），下面以「判断：」起头写回答。
有问题/关注可写 2-4 句并在首次展开处给关键数值；健康/中性严格一句、不写数值。
全部问题判断完成后，必须依次输出以下三个段落（标题逐字使用，不得改名）：

### 显著问题
按干预优先级逐行列出：一行一个，格式「问题名 — 直接干预/需询证 — 依据指标名称」。
不写数值、不复述前面段落原话；判定为中性/健康的问题不得列入。

### 可能失真·先观察
列出表面数据是问题、但存在失真可能的点；只要存在失真可能就先观察、不进直接干预，并说明需要向谁/用什么方式核实。没有则写「无」。

### 跟进线索与切入点
按优先级逐行写数据支持的具体操作方向（动作优先，不重复数值），可点名凭远内部工具（如「一表人才」）并说明用法。"""


def _sanitize_e4_step2(content: str) -> str:
    """清洗 Step2 AI 输出中的输入回显（数据行/问题判定行在数据区已存在）。

    只删确定性前缀的整行，不做语义删改；压缩多余空行。
    """
    if not content:
        return content
    echo = re.compile(r"^\s*(?:\*{0,2}\s*)?"
                      r"(问题判定|\[EVAL\]|\[ORDER\]|\[NORM\]|\[REF\]|\[JUDGE\])")
    kept = [ln for ln in content.splitlines() if not echo.match(ln)]
    out = "\n".join(kept)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip() + "\n"


def _e4_step2_tail(full_analysis: str) -> str:
    """从 Step2 输出截取三段式综合段（从「显著问题」所在标题行开始）。"""
    marker = "显著问题"
    if marker not in (full_analysis or ""):
        return ""
    idx = full_analysis.index(marker)
    line_start = full_analysis.rfind("\n", 0, idx)
    return full_analysis[line_start + 1:].strip()


def _strip_y4_data_section(interpretation: str) -> str:
    """裁掉 Y4 解读中的「数据呈现」段（原始数据 E4_EVALUATIONS 已有，避免重复）。

    匹配 markdown 标题（#{1,6}）含「数据呈现」的行，删除该标题至下一个同级或更高级标题之前；
    兼容 **一、数据呈现** 粗体行形态。找不到匹配则原样返回（安全兜底）。
    只作用于下载拼装，不修改 DB 原文。
    """
    if not interpretation or "数据呈现" not in interpretation:
        return interpretation
    lines = interpretation.splitlines()
    start = -1
    start_level = None
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{1,6})\s*.*数据呈现.*$", ln)
        if m:
            start, start_level = i, len(m.group(1))
            break
        if re.match(r"^\s*(?:\*\*)?#?\s*[一二三四五六七八九十0-9]+[、.．]\s*\**\s*.*数据呈现", ln):
            start, start_level = i, 99  # 粗体序号行：下一个同级粗体序号或任意标题都终止
            break
    if start < 0:
        return interpretation
    end = len(lines)
    heading_re = re.compile(r"^(#{1,%d})\s+" % start_level)
    bold_sec_re = re.compile(r"^\s*\*{0,2}\s*[一二三四五六七八九十0-9]+[、.．]")
    for j in range(start + 1, len(lines)):
        ln = lines[j]
        if (heading_re.match(ln) or (start_level == 99 and bold_sec_re.match(ln))):
            end = j
            break
    return "\n".join(lines[:start] + lines[end:]).strip()


def _e4_step3_system(rule_category: str) -> str:
    """Step3 system prompt：AI 只写「真实优势」与「名单归属」；结论/行动已由 Step2 三段承载。"""
    return f"""你是 Y4 测评 E4 评估框架的主笔。基于综合分析草稿，撰写「总览」段。

综合分析草稿已包含逐问题判断、显著问题、可能失真·先观察、跟进线索与切入点。
你的任务**不是再总结一遍**：问题清单和行动计划已经存在，禁止复述、禁止再写问题与建议。
你只补两块草稿中没有成段承载的内容：真实优势、名单归属理由。

【硬规则】
1. {_E4_NAMING_RULE}
2. 禁止创造新术语，只使用 Y4/E4 已有词汇。
3. 只依据分析草稿内容，不编造数据；不得为指标组合取新名字。
4. 禁止输出「核心矛盾」「下一步」「问题」「建议」类小节——它们在综合分析中已存在，重复即重写。
5. 行文简洁：真实优势 3-5 条，每条一句；名单理由 2-3 句。允许引用关键数值，但禁止在句尾用
   （）堆叠一长串指标名称清单；指标名自然写进句子里。

【禁止的术语类型（硬约束，违反即重写）】
- 心理学/治疗术语：如"情绪耗竭"、"神经可塑性"、"负向耦合"、"恶性循环"等
- 连字符组合造词、自创概念标签、学术化包装

【名单归属（硬约束，不得改判）】
Python 规则引擎已判定本学生的名单归属为：**{rule_category}**。
这是最终归属：禁止改判、禁止写成其他三类、禁止输出与该归属矛盾的表述。
「### 名单归属」一节只准写：该归属名称逐字出现一次 + 2-3 句支持该归属的数据理由。
四类含义仅供你理解，不得据此自行改判：
- 干预名单·强特质：E1/E2 存在严重「有问题」判定（重度档位或多个问题同时成立）
- 干预名单·弱特质：E1/E2 有「有问题」判定但程度较轻（单一问题、程度有限）
- 潜能名单·强特质：E1/E2 均无问题，且认知能力百分位总≥95、执行功能平均≥90
- 潜能名单·弱特质：E1/E2 均无问题，但学习力潜力或动力不充分

【输出格式】markdown，且只有两个小节（标题逐字使用）：
### 真实优势
跨维度归纳学生的真实优势（认知/情绪/关系等，标注维度），3-5 条，每条一句。
### 名单归属
第一句逐字写「{rule_category}」，随后 2-3 句数据理由。不得出现其他三类名称。"""


@app.route("/api/prompt-lab/e4-mapping", methods=["GET"])
@admin_required
def prompt_lab_e4_mapping_get():
    """返回用户指认的 Y4→E4 映射及框架常量。"""
    return jsonify({
        "ok": True,
        "mapping": _db.get_e4_mapping(),
        "dims": _eval_rules.E4_LABELS,
        "subcats": _eval_rules.E4_SUBCATS,
    })


@app.route("/api/prompt-lab/e4-mapping", methods=["POST"])
@admin_required
def prompt_lab_e4_mapping_save():
    """保存映射指认。body: {entries: [{code, e4_dims: [{e4_dim, e4_sub}, ...]}]}。

    e4_dims 为空列表表示清除该 code 的全部映射。
    e4_sub 可空（子类别为可选）。
    """
    data = request.get_json(force=True)
    entries = data.get("entries") or []
    cleaned = []
    for e in entries:
        code = str(e.get("code", "")).strip()
        if not code:
            continue
        dims = e.get("e4_dims") or []
        clean_dims = []
        for d in dims:
            dim = (d.get("e4_dim") or "").strip()
            if not dim:
                continue
            if dim not in _eval_rules.E4_DIMS:
                return jsonify({"ok": False, "error": f"未知 E4 维度: {dim}"}), 400
            sub = (d.get("e4_sub") or "").strip()
            # 子类别可选：如果填了，校验是否在预设列表里；不填也允许
            if sub and sub not in _eval_rules.E4_SUBCATS.get(dim, []):
                # 允许用户新建子类别（在 E4 框架线内），不报错
                pass
            clean_dims.append({"e4_dim": dim, "e4_sub": sub})
        cleaned.append({"code": code, "e4_dims": clean_dims})
    mapping = _db.save_e4_mapping(cleaned)
    return jsonify({"ok": True, "mapping": mapping})


@app.route("/api/prompt-lab/e4/step1", methods=["POST"])
@admin_required
def prompt_lab_e4_step1():
    """E4 工作流 Step1：数据整编（纯 Python，无 AI）。

    按 E4 框架 source of truth（维度→评估问题→指标）分组。
    框架未引用的指标归入 OTHER。
    """
    data = request.get_json(force=True)
    items = data.get("items", [])
    include_raw = bool(data.get("include_raw", False))

    vgroups, other_items, _dims_by_code = _eval_rules.evaluate_question_verdicts(items)

    groups: List[Dict[str, Any]] = []
    group_counts: Dict[str, int] = {d: 0 for d in _eval_rules.E4_DIMS}
    for g in vgroups:
        lines = [_format_e4_line(it, include_raw) for it in g["items"]]
        groups.append({"dim": g["dim"], "q": g["q"], "lines": lines, "verdict": g.get("verdict")})
        group_counts[g["dim"]] += len(g["items"])
    other_lines = [_format_e4_line(it, include_raw) for it in other_items]

    # 四类名单预览（干预/潜能 × 强/弱特质）
    list_placement = _determine_list_placement(items)

    return jsonify({
        "ok": True,
        "groups": groups,
        "other_lines": other_lines,
        "group_counts": group_counts,
        "unmapped_count": len(other_lines),
        "list_placement": list_placement,
    })


@app.route("/api/prompt-lab/e4/step2", methods=["POST"])
@admin_required
def prompt_lab_e4_step2():
    """E4 工作流 Step2：基于框架问题的 contextual 分析。

    数据按 E4 框架 source of truth 的「维度→评估问题→指标」组织。
    AI 的任务是逐一回答框架问题，并输出三段式综合（显著问题/可能失真·先观察/跟进线索与切入点）。
    """
    data = request.get_json(force=True)
    groups = data.get("groups") or []
    other_lines = data.get("other_lines") or []
    model = os.environ.get("E4_STEP2_MODEL", "qwen-turbo")
    timeout = int(os.environ.get("E4_STEP_TIMEOUT", "180"))

    # 按维度+问题拼装数据（附 Python 规则的问题级判定）
    all_lines: List[str] = []
    current_dim = None
    for g in groups:
        dim = g.get("dim", "")
        if dim != current_dim:
            all_lines.append("")
            all_lines.append(f"## {_eval_rules.E4_LABELS.get(dim, dim)}")
            current_dim = dim
        q = g.get("q")
        if q:
            all_lines.append(f"问题：{q}")
        v = g.get("verdict")
        if v:
            cn = _eval_rules.VERDICT_LABELS_CN.get(v.get("state"), v.get("state", ""))
            all_lines.append(f"问题判定（Python 规则，须以此为准绳）：{cn} | {v.get('summary', '')}")
        all_lines.extend(g.get("lines") or [])
        all_lines.append("")
    if other_lines:
        all_lines.append("## OTHER_VARIABLES（框架未引用）")
        all_lines.extend(other_lines)
        all_lines.append("")

    if not any(g.get("lines") for g in groups):
        return jsonify({"ok": True, "analyses": {d: "（无数据）" for d in _eval_rules.E4_DIMS},
                        "stats": [], "failed": [], "model": model, "full_analysis": ""})

    system = _e4_step2_system()
    user = ("【E4 框架数据（按维度和评估问题组织；问题下列出该问题涉及的指标数据）】\n"
            + "\n".join(all_lines))

    try:
        r = _dashscope_chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            model=model, timeout=timeout, max_tokens=4000)
        full_analysis = _sanitize_e4_step2(r["content"])
        analyses: Dict[str, str] = {d: "" for d in _eval_rules.E4_DIMS}
        analyses["_cross"] = _e4_step2_tail(full_analysis)

        stats = [{"dim": "ALL", "tokens": r["tokens"], "time_ms": r["time_ms"], "model": model}]
        return jsonify({"ok": True, "analyses": analyses,
                        "stats": stats, "failed": [], "model": model,
                        "full_analysis": full_analysis})
    except Exception as exc:
        return jsonify({"ok": False, "analyses": {}, "stats": [], "failed": ["ALL"],
                        "model": model, "error": str(exc)})


@app.route("/api/prompt-lab/e4/step3", methods=["POST"])
@admin_required
def prompt_lab_e4_step3():
    """E4 工作流 Step3：综合成文。

    AI 只写「总览」段；最终协议由 Python 确定性拼装（AI 不碰数据行，保证 Y4 原名）。
    不落库，直接返回 content_md。
    """
    data = request.get_json(force=True)
    items = data.get("items", [])
    include_raw = bool(data.get("include_raw", False))
    analyses = data.get("analyses") or {}
    full_analysis = (data.get("full_analysis") or "").strip()
    interpretation = (data.get("interpretation") or "").strip()
    model = os.environ.get("E4_STEP3_MODEL", "qwen-plus")
    timeout = int(os.environ.get("E4_STEP_TIMEOUT", "180"))

    # 规则兜底名单判定（AI 只写理由，不得改判）
    list_placement = _determine_list_placement(items, mapping=None)

    # 1) AI 写总览（名单归属以 Python 规则为准）
    system = _e4_step3_system(list_placement.get("category")
                              or list_placement.get("placement") or "（未判定）")
    user = (f"【综合分析草稿】\n{full_analysis or analyses}\n\n"
            f"【Y4 原始 AI 解读（可选参考，非客观事实）】\n{interpretation or '（无）'}")
    try:
        r = _dashscope_chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            model=model, timeout=timeout, max_tokens=2500)
        overview_md = r["content"]
        stats = {"tokens": r["tokens"], "time_ms": r["time_ms"], "model": model}
    except Exception as exc:
        overview_md = f"（总览生成失败：{exc}）"
        stats = {"tokens": 0, "time_ms": 0, "model": model, "error": str(exc)}

    # 2) Python 确定性拼装最终协议
    student_name = _get_student_name_from_items(items)
    content_md = _assemble_e4_protocol(items, include_raw, analyses, overview_md, full_analysis, interpretation)
    return jsonify({"ok": True, "content_md": content_md, "stats": stats,
                    "student_name": student_name, "list_placement": list_placement})


@app.route("/api/prompt-lab/y4-export/json", methods=["POST"])
@admin_required
def prompt_lab_y4_export_json():
    """Generalized Y4 JSON 导出（非 E4）：涵盖全部数据点 + AI 解读。

    不含 code、不含 E4 框架分组；按 Y4 四维组织。
    """
    data = request.get_json(force=True)
    items = data.get("items", [])
    interpretation = (data.get("interpretation") or "").strip()

    report_path = DATA_DIR / "report_data.json"
    student: Dict[str, Any] = {}
    if report_path.exists():
        student = json.loads(report_path.read_text(encoding="utf-8")).get("student", {}) or {}
    student_name = student.get("name") or "测试"

    payload = _build_y4_payload(items, interpretation, student, student_name)
    return jsonify({"ok": True, "json": payload,
                    "filename": f"{student_name.replace(' ', '')}_Y4数据.json"})


def _build_y4_payload(items: List[Dict[str, Any]], interpretation: str,
                      student: Dict[str, Any], student_name: str = "") -> Dict[str, Any]:
    """构建通用 Y4 JSON payload（按 Y4 四维组织全部数据点 + AI 解读 + 名单 + 问题级判定）。

    与数据来源解耦：调用方传入 items、interpretation、student。
    """
    from datetime import datetime as _dt
    if not student_name:
        student_name = student.get("name") or "测试"

    list_placement = _determine_list_placement(items, mapping=None)

    def _rank_of(label: str) -> str:
        digits = ""
        for ch in reversed(label or ""):
            if ch.isdigit():
                digits = ch + digits
            else:
                break
        return digits

    data_points = []
    for it in sorted(items, key=lambda x: _eval_rules.sort_key_code(x.get("code", ""))):
        dp: Dict[str, Any] = {
            "name": it.get("label", ""),
            "y4_dimension": it.get("dimension", ""),
        }
        src = it.get("eval_source", "")
        if src == "参照值":
            dp["type"] = "norm_reference"
            dp["value"] = it.get("raw_value", "")
            data_points.append(dp)
            continue
        if src == "原始排序":
            dp["type"] = "ranking"
            rank = _rank_of(it.get("label", ""))
            dp["rank"] = int(rank) if rank else None
            dp["value"] = it.get("eval_value") or it.get("raw_value") or ""
        else:
            dp["type"] = "evaluation"
            dp["raw_value"] = it.get("raw_value", "")
            if it.get("unit"):
                dp["unit"] = it.get("unit")
            if it.get("eval_value"):
                dp["eval"] = it.get("eval_value")
            if src and src not in ("规则推导", "待判定"):
                dp["eval_source"] = src
        if it.get("adjusted") and it.get("original_eval"):
            dp["adjusted_from"] = it.get("original_eval")
        bias = it.get("data_bias") or "正常"
        if bias != "正常":
            dp["data_bias"] = bias
        if (it.get("problem_status") or "CONFIRMED") == "OBSERVATION":
            dp["problem_status"] = "OBSERVATION"
        if (it.get("note") or "").strip():
            dp["note"] = it.get("note").strip()
        data_points.append(dp)

    # 问题级判定汇总（E4 框架全部问题）
    vgroups, _v_other, _v_dims = _eval_rules.evaluate_question_verdicts(items)
    question_verdicts = []
    for g in vgroups:
        v = g.get("verdict")
        if not v:
            continue
        question_verdicts.append({
            "dim": g["dim"],
            "question": g.get("q") or "E2 精力管理",
            "state": v["state"],
            "verdict": _eval_rules.VERDICT_LABELS_CN.get(v["state"], v["state"]),
            "summary": v["summary"],
        })

    return {
        "meta": {
            "protocol": "Y4-v1.0",
            "student": student_name,
            "gender": student.get("gender", ""),
            "grade": student.get("grade", ""),
            "school": student.get("school", ""),
            "test_date": student.get("test_date", ""),
            "generated": _dt.now().strftime("%Y-%m-%d %H:%M"),
        },
        "list_placement": {
            "list": list_placement.get("placement", ""),
            "strength": list_placement.get("strength", ""),
            "category": list_placement.get("category", ""),
            "traits": list_placement.get("traits", []),
        },
        "question_verdicts": question_verdicts,
        "data_points": data_points,
        "ai_interpretation": interpretation,
    }


def _get_student_name_from_items(items: List[Dict[str, Any]]) -> str:
    """从 report_data.json 获取学生名。"""
    report_path = DATA_DIR / "report_data.json"
    if report_path.exists():
        student = json.loads(report_path.read_text(encoding="utf-8")).get("student", {}) or {}
        return student.get("name") or "测试"
    return "测试"


_SEVERE_EVALS = {"需特殊关注", "明显偏低", "严重偏低"}


def _determine_list_placement(items: List[Dict[str, Any]],
                              mapping: Optional[Dict] = None) -> Dict[str, Any]:
    """四类名单判定（基于问题级 verdict 引擎，已确认规则）。

    名单分配：E1 情绪 或 E2 精力 任一问题 verdict=PROBLEM → 干预名单；否则 → 潜能名单。
    干预名单强/弱 = 按问题严重度：有重度问题（需特殊关注/明显偏低/严重偏低）
                    或 ≥2 个问题级 PROBLEM → 强特质（重点干预）；否则弱特质（轻量干预/观望）。
    潜能名单强/弱 = 强特质线：认知能力百分位总（code 002）≥95 且 执行功能三项平均≥90
                    （心力/精力无问题已由名单分配保证）；霍兰德有维度≥7 作加分标注。
    """
    vgroups, _other, _dims = _eval_rules.evaluate_question_verdicts(items)
    P = _eval_rules.VERDICT_PROBLEM

    e1_problems: List[Dict[str, str]] = []
    e2_problems: List[Dict[str, str]] = []
    problem_items: List[Dict[str, str]] = []
    severe_hit = False

    for g in vgroups:
        if g["dim"] not in ("E1", "E2"):
            continue
        v = g.get("verdict")
        if not v:
            continue
        if v["state"] == P:
            entry = {"dim": g["dim"], "q": g.get("q") or "E2 精力管理", "summary": v["summary"]}
            (e1_problems if g["dim"] == "E1" else e2_problems).append(entry)
        for r in v["items"]:
            if r["state"] == P:
                problem_items.append({"dim": g["dim"], "label": r["label"], "eval": r["eval"]})
                if r["eval"] in _SEVERE_EVALS:
                    severe_hit = True

    is_interference = bool(e1_problems or e2_problems)
    placement = "干预名单" if is_interference else "潜能名单"

    result: Dict[str, Any] = {
        "placement": placement,
        "e1_has_problem": bool(e1_problems),
        "e2_has_problem": bool(e2_problems),
        "problem_items": problem_items,
    }

    if is_interference:
        strong = severe_hit or (len(e1_problems) + len(e2_problems)) >= 2
        traits = [f"{p['q']}：{p['summary']}" for p in e1_problems + e2_problems]
        result["strength"] = "强" if strong else "弱"
        result["traits"] = traits
        result["detail"] = {"severe_hit": severe_hit,
                            "problem_groups": len(e1_problems) + len(e2_problems)}
    else:
        # 潜能名单强特质线（用户定义阈值）：认知能力百分位总（code 002）≥95
        # 且执行功能三项（063-065）平均 ≥90；心力/精力无问题由名单分配保证
        cog_total: Optional[float] = None
        exec_vals: List[float] = []
        holland_hits: List[str] = []
        for it in items:
            label = it.get("label", "") or ""
            code = str(it.get("code", "") or "")
            num = _eval_rules._to_number(it.get("raw_value"))
            if num is None:
                continue
            if code == "002" or (label == "认知能力百分位"):
                cog_total = num
            elif "执行功能" in label and "百分位" in label:
                exec_vals.append(num)
            elif "职业兴趣" in label and "排序" not in label and num >= 7:
                holland_hits.append(f"{label}({num:g})")
        exec_avg = sum(exec_vals) / len(exec_vals) if exec_vals else None
        cog_ok = cog_total is not None and cog_total >= 95
        exec_ok = exec_avg is not None and exec_avg >= 90
        strong = cog_ok and exec_ok  # 心力/精力无问题由名单分配保证

        strong_traits: List[str] = []
        weak_traits: List[str] = []
        if cog_total is not None:
            strong_traits.append(f"认知能力百分位总 {cog_total:g}（{'≥95 达标' if cog_ok else '<95 未达标'}）")
        if exec_avg is not None:
            strong_traits.append(f"执行功能平均 {exec_avg:.1f}（{'≥90 达标' if exec_ok else '<90 未达标'}，{len(exec_vals)}项）")
        if holland_hits:
            strong_traits.append("霍兰德兴趣优势：" + "、".join(holland_hits))
        # 潜能名单弱特质证据：E3/E4 的问题级结论（学习力潜力/动力不充分）
        for g in vgroups:
            if g["dim"] not in ("E3", "E4"):
                continue
            v = g.get("verdict")
            if not v or v["state"] not in (P, _eval_rules.VERDICT_WATCH):
                continue
            weak_traits.append(f"{g.get('q') or 'E3'}：{v['summary']}")

        result["strength"] = "强" if strong else "弱"
        result["traits"] = strong_traits if strong else weak_traits
        result["strong_traits"] = strong_traits
        result["weak_traits"] = weak_traits
        result["detail"] = {"cog_total": cog_total, "exec_avg": exec_avg,
                            "cog_ok": cog_ok, "exec_ok": exec_ok,
                            "holland_hits": holland_hits}

    result["category"] = f"{placement}·{'强特质' if result['strength'] == '强' else '弱特质'}"
    return result


def _assemble_e4_protocol(items: List[Dict[str, Any]], include_raw: bool,
                          analyses: Dict[str, str], overview_md: str,
                          full_analysis: str = "", interpretation: str = "",
                          student: Optional[Dict[str, Any]] = None,
                          student_name: str = "") -> str:
    """确定性拼装 E4 工作草稿协议。数据行不经过 AI，Y4 原名逐字保留。

    可选 student/student_name：调用方（如按 report_id 的一站式接口）传入从 DB 取的
    学生信息；不传则 fallback 读 data/report_data.json（兼容 prompt-lab）。
    """
    from datetime import datetime as _dt

    mapping = _db.get_e4_mapping()
    if student is None:
        report_path = DATA_DIR / "report_data.json"
        if report_path.exists():
            student = json.loads(report_path.read_text(encoding="utf-8")).get("student", {}) or {}
        else:
            student = {}
    if not student_name:
        student_name = student.get("name") or "测试"
    now = _dt.now().strftime("%Y-%m-%d %H:%M")

    md: List[str] = []
    md.append("# E4 评估框架传递协议 v1.1")
    md.append("")
    md.append("> 本文件为 E4 **工作草稿**，基于 Y4 测评输出构建，用于与学生沟通迭代，")
    md.append("> 识别薄弱点和低垂果实（low-hanging fruits），非最终评估结论。")
    md.append("")
    md.append("## META")
    # 规则兜底名单判定 — 在 META 中显示归属，让人一眼看到
    list_placement = _determine_list_placement(items, mapping)
    placement_str = list_placement["placement"]
    md.append(f"student: {student_name} | date: {student.get('test_date','')} | protocol: E4-v1.1 | generated: {now}")
    md.append(f"gender: {student.get('gender','')} | grade: {student.get('grade','')} | school: {student.get('school','')}")
    md.append(f"status: WORKING_DRAFT | purpose: 沟通迭代基础，找薄弱点与低垂果实")
    md.append(f"**名单归属: {list_placement.get('category', placement_str)}**")
    md.append("")

    md.append("## E4_FRAMEWORK")
    md.append("```")
    fw_groups, _fw_other, _ = _eval_rules.evaluate_question_verdicts(items)
    for dim in _eval_rules.E4_DIMS:
        md.append(_eval_rules.E4_LABELS[dim])
        for g in fw_groups:
            if g["dim"] == dim and g.get("q"):
                md.append(f"  - {g['q']}")
    md.append("RULES: 一个指标可出现在多个问题/维度 | bias=偏高/偏低须询证 | OBSERVATION=假问题观望")
    md.append("排序位置: 位置数字越小排序越靠前（越重要）")
    md.append("```")
    md.append("")

    md.append("## STUDENT_INFO")
    md.append(f"name: {student_name} | gender: {student.get('gender','')} | grade: {student.get('grade','')} | school: {student.get('school','')} | test_date: {student.get('test_date','')}")
    md.append("")

    # 按 E4 框架 source of truth（维度→评估问题→指标）分组
    # 同一指标多次出现时，首次完整显示，后续用 [REF] 引用
    md.append("## E4_EVALUATIONS")
    md.append("")
    seen_codes: set = set()
    for dim in _eval_rules.E4_DIMS:
        dim_groups = [g for g in fw_groups if g["dim"] == dim]
        if not any(g["items"] for g in dim_groups):
            continue
        md.append(f"### {_eval_rules.E4_LABELS[dim]}")
        md.append("")
        for g in dim_groups:
            if not g["items"]:
                continue
            if g.get("q"):
                md.append(f"#### {g['q']}")
            v = g.get("verdict")
            if v:
                md.append(f"[VERDICT] {_eval_rules.VERDICT_LABELS_CN.get(v['state'], v['state'])} | {v['summary']}")
            for it in g["items"]:
                code = it.get("code", "")
                is_ref = code in seen_codes
                md.append(_format_e4_line(it, include_raw, is_ref=is_ref))
                seen_codes.add(code)
            md.append("")

    if _fw_other:
        md.append("## OTHER_VARIABLES")
        md.append("")
        for it in sorted(_fw_other, key=lambda x: _eval_rules.sort_key_code(x.get("code", ""))):
            md.append(_format_e4_line(it, include_raw))
        md.append("")

    # 综合分析（step2 产物）：逐问题判断 + 显著问题/可能失真·先观察/跟进线索与切入点
    md.append("## E4_ANALYSIS")
    md.append("")
    if full_analysis:
        md.append(full_analysis)
    else:
        for d in _eval_rules.E4_DIMS:
            md.append(f"### {_eval_rules.E4_LABELS[d]}")
            md.append("")
            md.append(analyses.get(d) or "（未生成）")
            md.append("")
        cross = analyses.get("_cross", "")
        if cross:
            md.append("### 综合判断（显著问题 / 可能失真·先观察 / 跟进线索与切入点）")
            md.append("")
            md.append(cross)
            md.append("")

    # 总览（step3 产物）
    md.append("## OVERVIEW")
    md.append("")
    md.append(overview_md or "（未生成）")
    md.append("")

    # Y4 四维解读 — 直接用 AI Y4 解读师的 output，与 E4 并存
    md.append("## Y4_INTERPRETATION")
    md.append("")
    if interpretation:
        # 裁掉 Y4 解读中的「数据呈现」段：原始数据在 E4_EVALUATIONS 已完整存在
        md.append(_strip_y4_data_section(interpretation))
    else:
        md.append("（未提供 Y4 解读，请先在 Prompt Lab 运行 Y4 解读师生成解读后再下载 E4 协议）")
    md.append("")

    # 人工判断汇总 — 只在有调整时才显示
    expert_notes = [it for it in items if (it.get("note") or "").strip() or it.get("adjusted") or it.get("data_bias","正常") != "正常"]
    if expert_notes:
        md.append("## EXPERT_JUDGMENTS")
        md.append("")
        for it in expert_notes:
            parts = [f"[JUDGE] {it.get('label')}"]
            if it.get("adjusted") and it.get("original_eval"):
                parts.append(f"adjusted:{it.get('original_eval')}→{it.get('eval_value')}")
            bias = it.get("data_bias", "正常")
            if bias != "正常":
                parts.append(f"bias:{bias}")
            problem = it.get("problem_status")
            if problem == "OBSERVATION":
                parts.append("problem:OBSERVATION")
            note = (it.get("note") or "").strip()
            if note:
                parts.append(f"note:{note}")
            md.append(" | ".join(parts))
        md.append("")

    # AI 使用指南 — 精简版
    md.append("## AI_USAGE_GUIDE")
    md.append("```")
    md.append("NAMING: 指标名称（label）是唯一权威命名，禁止改写或创造新术语")
    md.append("AUTHORITY: EXPERT_JUDGMENT > EVALUATION(规则推导) > AI_ANALYSIS(可参考非客观事实)")
    md.append("BIAS: 偏高/偏低 → 须询证 | OBSERVATION → 假问题，须后续验证")
    md.append("MULTI_DIM: 一个指标可出现在多个 E4 维度；[REF] 行指向首次出现的完整数据")
    md.append("名单归属: E1/E2 问题级判定「有问题」→ 干预名单(强/弱按问题严重度)；否则 → 潜能名单(强/弱按 认知能力百分位总≥95 且 执行功能平均≥90)")
    md.append("```")
    md.append("")

    # 名单归属章节 — 协议末尾，醒目（四类：干预/潜能 × 强特质/弱特质）
    md.append("---")
    md.append("")
    md.append("## 名单归属")
    md.append("")
    md.append(f"> **{list_placement.get('category', placement_str)}**")
    md.append("")
    # 规则兜底详情
    if list_placement["problem_items"]:
        md.append("**规则判定依据（E1/E2 问题级结论）：**")
        for p in list_placement["problem_items"]:
            md.append(f"- {p['dim']} {p['label']}: {p['eval']}")
        md.append("")
        e1 = "有问题" if list_placement["e1_has_problem"] else "无问题"
        e2 = "有问题" if list_placement["e2_has_problem"] else "无问题"
        md.append(f"E1 情绪: {e1} | E2 精力: {e2} → 归入{placement_str}")
    else:
        md.append("E1 情绪和 E2 精力问题级判定均无「有问题」→ 归入潜能名单")
    md.append("")
    traits = list_placement.get("traits") or []
    if traits:
        md.append(f"**{list_placement.get('category', placement_str)}依据：**")
        for t in traits:
            md.append(f"- {t}")
        md.append("")
    md.append("*AI 总览中的名单归属判断见上方 OVERVIEW 章节。如与规则兜底矛盾，以规则为准。*")
    md.append("")

    md.append("---")
    md.append("凭远教育 · Y4 综合测评系统 | 本文件为 E4 工作草稿 AI→AI 传递协议")
    return "\n".join(md)


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
