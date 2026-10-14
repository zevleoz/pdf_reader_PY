"""报告蓝图：生成页 + 分片上传/作业/进度/结果 + 报告数据 API + 导出。"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from flask import (Blueprint, jsonify, render_template, request, redirect,
                   send_file, send_from_directory, abort)

import db as _db
import app_utils
import extract
import validate
import generate as _generate_module
from data_points import apply_report_data
import evaluation_rules as _eval_rules
import y4_questions as _y4q
from app_utils import (BASE_DIR, DATA_DIR, INPUT_DIR, JOB_FILE, JOB_LOG_FILE,
                       OUTPUT_DIR, UPLOAD_DIR, REQUIRED_KEYS,
                       admin_required, role_required, report_scoped)
from ai_client import (_build_phase1_md_text, _build_qualification_view,
                       _build_y4_interpret_context, _build_y4_payload,
                       _finalize_y4_interpretation, _generate_e4_protocol_core,
                       _generate_interpretation_for_report,
                       _report_qualification_payload, _strip_wrapping_fence)

bp = Blueprint("reports", __name__)


@bp.route("/generate")
@role_required('admin', 'advisor')
def index():
    return render_template("index.html")


@bp.route("/preview")
@role_required('admin', 'advisor')
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
# 生成任务基础设施
#
# 背景：Cloudflare 免费版代理对「源站响应」有约 100 秒超时。原先 /api/generate
# 是同步接口（上传 ~19MB + 解析 + 生成，耗时 2-3 分钟），经由隧道访问必然返回
# HTTP 524。因此把长流程拆成多个短请求：
#   1. POST /api/upload/chunk    前端分片上传（每片约 1.5MB）
#   2. POST /api/generate/start  合并输入文件，拉起**独立子进程**跑管道后立即返回
#   3. GET  /api/progress        轮询任务状态（复用现有前端轮询）
#   4. GET  /api/generate/result 取回生成的 PDF
#
# 用子进程而非线程：gunicorn_config.py 里 max_requests=10，工作进程被回收时会
# 连带杀掉其派生线程；独立进程（start_new_session=True）不受影响。
# ---------------------------------------------------------------------------
_UPLOAD_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _write_job(**fields) -> None:
    """原子地更新 data/_job.json。"""
    data: dict = {}
    if JOB_FILE.exists():
        try:
            data = json.loads(JOB_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data.update(fields)
    data["updated_at"] = time.time()
    try:
        tmp = JOB_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(JOB_FILE))
    except OSError:
        pass


def _read_job() -> dict:
    if not JOB_FILE.exists():
        return {}
    try:
        return json.loads(JOB_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _job_running() -> bool:
    """是否有正在运行的任务。超过 20 分钟无状态更新视为已卡死，不再阻塞新任务。"""
    job = _read_job()
    if job.get("status") != "running":
        return False
    updated = job.get("updated_at") or 0
    return (time.time() - updated) < 1200


def _apply_mindset_override(mindset_score: Optional[str]) -> None:
    """用户手动输入的思维模式分值覆盖提取结果（059）。"""
    if not mindset_score:
        return
    try:
        score_val = float(mindset_score)
    except (TypeError, ValueError):
        return
    if not (0 <= score_val <= 100):
        return
    from data_points import USER_DATA
    USER_DATA['059'] = str(score_val)
    print(f"[思维模式] 用户手动输入分值: {score_val}")

    # 同时更新 report_data.json，避免被 build_view_data() 中的
    # apply_report_data() 覆盖
    report_data_path = DATA_DIR / "report_data.json"
    if not report_data_path.exists():
        return
    try:
        report_data = json.loads(report_data_path.read_text(encoding="utf-8"))
        for item in report_data.get('schema_124', []):
            if item.get('code') == '059':
                item['value'] = str(score_val)
                break
        report_data_path.write_text(
            json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[思维模式] 已更新 report_data.json 中的 059 值为 {score_val}")
    except Exception as e:
        print(f"[思维模式] 更新 report_data.json 失败: {e}")


def _clean_y4(v: str) -> str:
    v = (v or "").strip()
    return "" if v in ("", "—", "-") else v


def _save_report_to_db(pdf_path: Path, selected_sid: str, manual_name: str) -> Optional[int]:
    """归档生成的报告到数据库（尽力而为，失败不影响主流程）。

    返回 report id（无学生时 None）；归档成功后尽力而为触发 6AM 档案生成（非致命）。
    """
    report_id = None
    try:
        report_data_path = DATA_DIR / "report_data.json"
        if not report_data_path.exists():
            return None
        rd = json.loads(report_data_path.read_text(encoding="utf-8"))
        student_info = rd.get("student", {}) or {}
        sname = student_info.get("name", "").strip()
        selected_sid = (selected_sid or "").strip()
        manual_name = (manual_name or "").strip()

        # 学校/顾问以 Y4 input 读取结果为准（预约时可能未填写），
        # 覆盖 students 表中的旧值；提取失败（空或"—"）时保留原值。
        y4_school = _clean_y4(student_info.get("school", ""))
        y4_advisor = _clean_y4(student_info.get("teacher", ""))

        if selected_sid:
            sid = int(selected_sid)
            sname = sname or manual_name or f"学生#{sid}"
            if student_info:
                _db.update_student(sid, **{k: v for k, v in {
                    "gender": student_info.get("gender", ""),
                    "birthday": student_info.get("birthday", ""),
                    "grade": student_info.get("grade", ""),
                    "school": y4_school,
                    "advisor_name": y4_advisor,
                }.items() if v})
            print(f"[DB] 关联到预约学生: {sname} (id={sid})")
        elif manual_name:
            sid = _db.find_or_create_student(
                name=manual_name,
                school=y4_school,
                advisor_name=y4_advisor,
            )
            sname = manual_name
            print(f"[DB] 手动输入学生: {sname} (id={sid})")
        elif sname:
            sid = _db.find_or_create_student(
                name=sname,
                gender=student_info.get("gender", ""),
                birthday=student_info.get("birthday", ""),
                grade=student_info.get("grade", ""),
                school=y4_school,
                advisor_name=y4_advisor,
            )
            print(f"[DB] 从PDF提取学生: {sname} (id={sid})")
        else:
            sid = None

        if sid:
            report_id = _db.add_report(
                student_id=sid,
                report_date=date.today(),
                pdf_path=str(pdf_path),
                data_json=report_data_path.read_text(encoding="utf-8"),
            )
    except Exception as e:
        print(f"[DB] 保存报告失败 (非致命): {e}")
    if report_id:
        try:
            import six_am
            six_am.run_for_report(report_id)
        except Exception as e:
            print(f"[6AM] 生成失败 (非致命): {e}")
    return report_id


def _find_generated_pdf() -> Optional[Path]:
    """在 output/ 下定位刚生成的 PDF。"""
    pdf_files = sorted(OUTPUT_DIR.glob("*.pdf"))
    if not pdf_files:
        return None
    # 排除并行产出的 v2 新版，主报告永远是 v1
    named = [f for f in pdf_files if "凭远Y4评测报告" in f.name and "_v2_" not in f.name]
    return named[0] if named else pdf_files[0]


def _run_pipeline_job(job: dict) -> int:
    """在无 Flask 请求上下文的环境下执行 extract → validate → generate → 归档。

    由 ``python app.py genjob <args.json>`` 在独立子进程中调用，状态写入
    data/_job.json 供 /api/progress 与 /api/generate/result 读取。
    """
    try:
        _write_job(status="running", percent=5, message="正在解析 PDF…",
                   error="", filename="", pdf_path="")

        rc = extract.main()
        if rc != 0:
            raise RuntimeError(f"提取数据失败 (extract.main() 返回 {rc})")

        _write_job(percent=90, message="正在校验数据…")
        try:
            validate.main()
        except Exception:
            pass

        apply_result = apply_report_data()
        _apply_mindset_override(job.get("mindset_score"))

        # 清理 output/ 旧产物，避免 chrome 基于旧文件命名出错
        for pattern in ["report.pdf", "report.html", "凭远Y4评测报告_*.pdf", "凭远Y4评测报告_*.html"]:
            for old in OUTPUT_DIR.glob(pattern):
                try:
                    old.unlink()
                except OSError:
                    pass

        _write_job(percent=95, message="正在生成 PDF…")
        try:
            _generate_module.main()
        except SystemExit as exc:
            if exc.code not in (None, 0):
                raise RuntimeError(f"生成 PDF 失败: SystemExit({exc.code})")

        pdf_path = _find_generated_pdf()
        if not pdf_path or not pdf_path.exists():
            raise RuntimeError("生成流程完成，但未在 output/ 下找到 PDF。请检查 Chrome 是否可用。")

        # 并行产出的 v2 新版（可选，不存在的场合不阻塞）
        filename_v2 = ""
        m = re.match(r"^凭远Y4评测报告_(.+)\.pdf$", pdf_path.name)
        if m:
            v2_candidate = OUTPUT_DIR / f"凭远Y4评测报告_v2_{m.group(1)}.pdf"
            if v2_candidate.exists():
                filename_v2 = v2_candidate.name

        _save_report_to_db(pdf_path, job.get("student_id", ""),
                           job.get("manual_student_name", ""))

        _write_job(status="done", percent=100, message="报告已生成",
                   filename=pdf_path.name, pdf_path=str(pdf_path),
                   filename_v2=filename_v2,
                   applied=apply_result.get("applied", 0),
                   total=apply_result.get("total_items", 0), error="")
        return 0
    except Exception as exc:
        tb = traceback.format_exc()
        print(tb)
        _write_job(status="error", message=f"生成失败: {exc}",
                   error=str(exc), trace=tb)
        return 1


# ---------------------------------------------------------------------------
# 分片上传：接收单片 PDF 数据，追加写入 data/_uploads/<upload_id>/<KEY>.part
# ---------------------------------------------------------------------------
@bp.route("/api/upload/chunk", methods=["POST"])
@admin_required
def api_upload_chunk():
    key = (request.form.get("key") or "").strip().upper()
    upload_id = (request.form.get("upload_id") or "").strip()
    chunk_index = request.form.get("chunk_index", type=int)
    chunk = request.files.get("chunk")

    if key not in REQUIRED_KEYS or not upload_id or chunk_index is None or chunk is None:
        return jsonify({"ok": False, "error": "上传参数不完整"}), 400
    if not _UPLOAD_ID_RE.fullmatch(upload_id):
        return jsonify({"ok": False, "error": "upload_id 非法"}), 400

    dest_dir = UPLOAD_DIR / upload_id
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        part = dest_dir / f"{key}.part"
        # 第 0 片覆盖写入（新文件），后续分片顺序追加
        with open(part, "wb" if chunk_index == 0 else "ab") as fh:
            fh.write(chunk.read())
    except OSError as exc:
        return jsonify({"ok": False, "error": f"写入分片失败: {exc}"}), 500

    return jsonify({"ok": True, "received": chunk_index})


# ---------------------------------------------------------------------------
# 启动生成任务：合并分片 → 拉起独立子进程 → 立即返回
# ---------------------------------------------------------------------------
@bp.route("/api/generate/start", methods=["POST"])
@admin_required
def api_generate_start():
    upload_id = (request.form.get("upload_id") or "").strip()
    if not upload_id or not _UPLOAD_ID_RE.fullmatch(upload_id):
        return jsonify({"ok": False, "error": "upload_id 非法"}), 400

    src_dir = UPLOAD_DIR / upload_id
    if not src_dir.is_dir():
        return jsonify({"ok": False, "error": "未找到上传数据，请重新上传"}), 400

    try:
        manifest = json.loads(request.form.get("manifest") or "{}")
    except Exception:
        manifest = {}
    if not isinstance(manifest, dict):
        manifest = {}

    if _job_running():
        return jsonify({"ok": False, "error": "已有生成任务正在运行，请稍候"}), 409

    # 清空 input/ 旧文件，按 report_<KEY>.pdf 命名落盘
    try:
        for old in INPUT_DIR.glob("*.pdf"):
            old.unlink()
    except OSError:
        pass

    saved_keys: List[str] = []
    try:
        for part in sorted(src_dir.glob("*.part")):
            key = part.stem.upper()
            if key not in REQUIRED_KEYS:
                continue
            entry = manifest.get(key)
            original_name = entry.get("filename", "") if isinstance(entry, dict) else (entry or "")
            if key == "B6" and ("高中" in original_name or "初中" in original_name):
                version = "高中" if "高中" in original_name else "初中"
                target = INPUT_DIR / f"report_{key}_{version}.pdf"
            else:
                target = INPUT_DIR / f"report_{key}.pdf"
            os.replace(str(part), str(target))
            saved_keys.append(key)
    except OSError as exc:
        return jsonify({"ok": False, "error": f"合并上传文件失败: {exc}"}), 500

    # 清理本次上传的分片目录
    import shutil as _shutil
    _shutil.rmtree(str(src_dir), ignore_errors=True)

    if not saved_keys:
        return jsonify({"ok": False, "error": "请至少上传一份 PDF"}), 400

    job = {
        "mindset_score": request.form.get("mindset_score", ""),
        "student_id": request.form.get("student_id", ""),
        "manual_student_name": request.form.get("manual_student_name", ""),
    }
    args_path = DATA_DIR / "_job_args.json"
    args_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")

    _write_job(status="running", percent=1, message="任务已启动…",
               error="", filename="", pdf_path="", started_at=time.time())

    import subprocess as _subprocess
    try:
        with open(JOB_LOG_FILE, "a", encoding="utf-8") as log:
            proc = _subprocess.Popen(
                [sys.executable, str(BASE_DIR / "app.py"), "genjob", str(args_path)],
                cwd=str(BASE_DIR),
                stdout=log, stderr=log, stdin=_subprocess.DEVNULL,
                start_new_session=True,
            )
        # 子进程若立刻退出（如导入失败），把日志尾部作为错误返回，避免任务永远 running
        time.sleep(0.3)
        if proc.poll() is not None:
            tail = ""
            try:
                tail = JOB_LOG_FILE.read_text(encoding="utf-8", errors="replace")[-2000:]
            except OSError:
                pass
            _write_job(status="error", message="生成任务启动失败",
                       error=f"生成任务启动失败 (exit {proc.returncode})")
            return jsonify({"ok": False, "error": "生成任务启动失败",
                            "log": tail}), 500
    except Exception as exc:
        _write_job(status="error", message=f"启动生成任务失败: {exc}", error=str(exc))
        return jsonify({"ok": False, "error": f"启动生成任务失败: {exc}"}), 500

    return jsonify({"ok": True, "keys": saved_keys})


# ---------------------------------------------------------------------------
# 取回生成结果 PDF
# ---------------------------------------------------------------------------
@bp.route("/api/generate/result", methods=["GET"])
@admin_required
def api_generate_result():
    job = _read_job()
    if not job:
        return jsonify({"ok": False, "error": "尚未生成报告"}), 404
    if job.get("status") != "done":
        return jsonify({"ok": False,
                        "error": job.get("error") or "报告尚未生成完成"}), 409

    name = job.get("filename") or ""
    download_name = name
    if request.args.get("v") == "2":
        name = job.get("filename_v2") or ""
        if not name:
            return jsonify({"ok": False, "error": "本次生成没有 v2 新版报告"}), 404
        # 新版为默认下载：对外用不带 _v2_ 的文件名
        download_name = job.get("filename") or name
    pdf_path = OUTPUT_DIR / name
    if not name or not pdf_path.exists():
        return jsonify({"ok": False, "error": "生成的文件已不存在，请重新生成"}), 404

    resp = send_from_directory(
        str(OUTPUT_DIR), name,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/pdf",
    )
    # RFC 5987: 浏览器对 Content-Disposition 中的中文文件名需要 filename*=UTF-8''编码
    from urllib.parse import quote
    resp.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(download_name)}"
    resp.headers["X-Applied-Items"] = str(job.get("applied", 0))
    resp.headers["X-Total-Items"] = str(job.get("total", 0))
    resp.headers["X-V2-Available"] = "1" if job.get("filename_v2") else "0"
    return resp


# ---------------------------------------------------------------------------
# 进度查询接口（供前端进度条轮询）
# ---------------------------------------------------------------------------
@bp.route("/api/progress", methods=["GET"])
@admin_required
def api_progress():
    job = _read_job()
    prog: dict = {}
    started_at = job.get("started_at") or 0
    prog_file = DATA_DIR / "_progress.json"
    if prog_file.exists():
        try:
            # 只采用本次任务启动之后写入的进度，避免上一次运行的 _progress.json 干扰
            if prog_file.stat().st_mtime >= started_at:
                prog = json.loads(prog_file.read_text(encoding="utf-8"))
        except Exception:
            prog = {}

    status = job.get("status") or "idle"
    job_percent = job.get("percent") or 0
    prog_percent = prog.get("percent") or 0
    if status == "running":
        # extract.py 会写入更细粒度的阶段进度，取较大值以获得更平滑的进度条
        percent = max(job_percent, prog_percent)
        message = prog.get("message") if prog_percent > job_percent else job.get("message")
    else:
        percent = job_percent
        message = job.get("message") or prog.get("message")

    return jsonify({
        "stage": prog.get("stage") or status,
        "percent": percent,
        "message": message or "",
        "status": status,
        "filename": job.get("filename", ""),
        "error": job.get("error", ""),
    })


# ---------------------------------------------------------------------------
# 核心接口：接收 4 份 PDF → 跑管道 → 返回 report.pdf
# ---------------------------------------------------------------------------
@bp.route("/api/generate", methods=["POST"])
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
        _apply_mindset_override(request.form.get('mindset_score'))

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
        _save_report_to_db(pdf_path,
                           request.form.get("student_id", ""),
                           request.form.get("manual_student_name", ""))

        # 9) 返回 PDF 作为附件
        download_filename = pdf_path.name
        resp = send_from_directory(
            str(OUTPUT_DIR), pdf_path.name,
            as_attachment=True,
            download_name=download_filename,
            mimetype="application/pdf",
        )
        # RFC 5987: 浏览器对 Content-Disposition 中的中文文件名需要 filename*=UTF-8''编码
        from urllib.parse import quote
        quoted = quote(download_filename)
        resp.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quoted}"
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
@bp.route("/api/chat", methods=["POST"])
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

    # 2) 读取 report_data.json，构建 Y4 有效评价上下文（含档位/评级/单位）
    report_path = DATA_DIR / "report_data.json"
    if report_path.exists():
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
        schema_items = report_data.get("schema_124", [])
        student = report_data.get("student", {})
        context = _build_y4_interpret_context(schema_items, student)
    else:
        context = "（暂无测评数据）"

    # 3) 组装 messages
    messages = [
        {"role": "system", "content": system_prompt + "\n\n以下是 Y4 有效评价数据：\n" + context},
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
        reply = _strip_wrapping_fence(result["choices"][0]["message"]["content"])
        return jsonify({"ok": True, "reply": reply})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"AI 调用失败: {exc}"}), 500


# ---------------------------------------------------------------------------
# 静态输出文件访问
# ---------------------------------------------------------------------------
# 公开可访问的输出产物白名单（仅公开落地页示例图）。其余一律需登录。
PUBLIC_OUTPUT_ASSETS = {"report_title_page.png"}


@bp.route("/output/<path:filename>")
def download(filename):
    if filename not in PUBLIC_OUTPUT_ASSETS and not app_utils.is_authenticated():
        if request.path.startswith('/api/'):
            return jsonify({"ok": False, "error": "未登录"}), 401
        return redirect('/login?next=' + request.path)
    target = OUTPUT_DIR / filename
    if not target.exists():
        abort(404)
    return send_from_directory(str(OUTPUT_DIR), filename, as_attachment=False)
@bp.route("/api/reports/<int:report_id>/regenerate", methods=["POST"])
@admin_required
@report_scoped
def api_report_regenerate(report_id):
    """从 DB 数据快照重生成报告 PDF（不调 extract/OCR，零 API 成本）。

    注意：会覆盖 data/report_data.json（全局"当前数据"）；下一次真实生成的
    extract 会重写它，不影响正确性。
    """
    if _job_running():
        return jsonify({"ok": False, "error": "已有生成任务正在运行，请稍候"}), 409

    info = _db.get_report_raw(report_id)
    if not info:
        return jsonify({"ok": False, "error": "报告记录不存在"}), 404
    raw = info.get("raw") or {}
    if not raw.get("schema_124"):
        return jsonify({"ok": False, "error": "该记录没有完整数据快照，无法重生成"}), 400

    try:
        (DATA_DIR / "report_data.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        apply_report_data()
        try:
            _generate_module.main()
        except SystemExit as exc:
            if exc.code not in (None, 0):
                raise RuntimeError(f"生成 PDF 失败: SystemExit({exc.code})")
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"重生成失败: {exc}"}), 500

    student_name = ((raw.get("student") or {}).get("name")
                    or info.get("student_name") or "").strip()
    safe_name = student_name.replace("/", "_").replace("\\", "_").replace(" ", "")
    v1_path = OUTPUT_DIR / f"凭远Y4评测报告_{safe_name}.pdf"
    if not safe_name or not v1_path.exists():
        return jsonify({"ok": False, "error": "生成流程完成，但未找到 PDF 文件"}), 500

    # 新版（v2）为默认下载，v2 缺失时回落旧版（v1）；对外统一用不带 _v2_ 的文件名
    v2_path = OUTPUT_DIR / f"凭远Y4评测报告_v2_{safe_name}.pdf"
    primary = v2_path if v2_path.exists() else v1_path
    download_name = f"凭远Y4评测报告_{safe_name}.pdf"
    resp = send_from_directory(
        str(OUTPUT_DIR), primary.name,
        as_attachment=True, download_name=download_name,
        mimetype="application/pdf",
    )
    from urllib.parse import quote
    resp.headers["Content-Disposition"] = \
        f"attachment; filename*=UTF-8''{quote(download_name)}"
    if v2_path.exists():
        resp.headers["X-V1-Filename"] = quote(v1_path.name)
    return resp
@bp.route("/api/reports/<int:report_id>/raw")
@admin_required
@report_scoped
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


@bp.route("/api/reports/<int:report_id>/interpret", methods=["POST"])
@admin_required
@report_scoped
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
    student = raw.get("student", {})

    body = request.get_json(silent=True) or {}
    # 前端可传 UI 调整后的 items（含档位覆盖/高估低估确认）；否则用规则引擎构建
    context = _build_y4_interpret_context(
        schema_items, student,
        items_override=(body.get("items") if body.get("items") else None))

    prompt_path = BASE_DIR / "prompts" / "ai_interpreter.md"
    system_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else "你是测评解读助手。"

    messages = [
        {"role": "system", "content": system_prompt + "\n\n以下是 Y4 有效评价数据：\n" + context},
        {"role": "user", "content": "请给出这份 Y4 报告的完整解读"},
    ]

    dashscope_key = os.environ.get("DASHSCOPE_API_KEY", extract.DEFAULT_DASHSCOPE_KEY).strip()
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    payload = json.dumps({
        "model": os.environ.get("AI_TEXT_MODEL", "qwen-plus"),
        "messages": messages,
        "temperature": float(os.environ.get("AI_TEMPERATURE", "0.3")),
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
        reply = _finalize_y4_interpretation(
            result["choices"][0]["message"]["content"], dashscope_key)
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
@bp.route("/api/reports/<int:report_id>/qualification")
@admin_required
@report_scoped
def api_report_qualification(report_id):
    """按报告取有效评价 qualification 视图（含 items/student/summary/E4 映射/per-code 选项）。"""
    payload, err = _report_qualification_payload(report_id)
    if err:
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True, **payload})


@bp.route("/api/reports/<int:report_id>/y4-signals")
@admin_required
@report_scoped
def api_report_y4_signals(report_id):
    """按报告取 Y4 原生问题研判结果（潜能/干预四名单 + 五维问题明细 + 分型标签）。"""
    record = _db.get_report_raw(report_id)
    if not record:
        return jsonify({"ok": False, "error": "报告不存在"}), 404
    raw = record.get("raw") or {}
    schema_items = [it for it in (raw.get("schema_124") or []) if not _eval_rules.is_hidden_raw(it)]
    student = raw.get("student", {}) or {}
    items, _summary, _mapping_done, _opts = _build_qualification_view(schema_items)
    result = _y4q.evaluate_y4_questions(items, student)
    return jsonify({
        "ok": True,
        "student": student,
        "report": {
            "id": report_id,
            "report_date": record.get("report_date"),
            "student_name": record.get("student_name"),
        },
        "result": result,
    })


@bp.route("/api/reports/<int:report_id>/protocol-md", methods=["POST"])
@admin_required
@report_scoped
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
    safe_name = student_name.replace(" ", "").replace("/", "_")
    return send_file(buf, mimetype="text/markdown", as_attachment=True,
                     download_name=f"Y4报告_{safe_name}.md")


@bp.route("/api/reports/<int:report_id>/y4-json", methods=["POST"])
@admin_required
@report_scoped
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
                    "filename": f"Y4数据_{student_name.replace(' ', '').replace('/', '_')}.json"})


@bp.route("/api/reports/<int:report_id>/e4-protocol", methods=["POST"])
@admin_required
@report_scoped
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

    result = _generate_e4_protocol_core(items, include_raw, interpretation, student, student_name)
    return jsonify(result)
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


@bp.route("/api/reports/<int:report_id>/evaluation")
@admin_required
@report_scoped
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
@bp.route("/api/reports/<int:report_id>", methods=["DELETE"])
@admin_required
@report_scoped
def api_delete_report(report_id):
    try:
        _db.delete_report(report_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
@bp.route("/api/export")
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
