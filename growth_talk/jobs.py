"""Growth Talk 异步分析作业（子进程 + 状态文件轮询）。

对齐现有 ``app.py genjob`` 模式：路由只负责拉起独立进程，
前端轮询 ``data/_gt_jobs/<run_id>.json``，避免隧道源站超时。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app_utils import BASE_DIR, DATA_DIR

JOB_DIR = Path(DATA_DIR) / "_gt_jobs"
COPILOT_JOB_DIR = Path(DATA_DIR) / "_copilot_jobs"
LAUNCH_GRACE_SECONDS = 0.3
STALE_JOB_MESSAGE = "会谈在生成期间已被修改，请刷新后重新生成。"


class JobLaunchError(RuntimeError):
    """子进程在启动窗口内立即退出。"""


def _job_path(run_id: int) -> Path:
    return Path(JOB_DIR) / f"{int(run_id)}.json"


def _log_path(run_id: int) -> Path:
    return Path(JOB_DIR) / f"{int(run_id)}.log"


def write_gt_job(run_id: int, **fields: Any) -> dict:
    """原子写状态文件，避免前端读到半截 JSON。"""
    directory = Path(JOB_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    payload = dict(fields)
    payload["updated_at"] = datetime.utcnow().isoformat()
    target = _job_path(run_id)
    temporary = target.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False),
                         encoding="utf-8")
    os.replace(temporary, target)
    return payload


def read_gt_job(run_id: int) -> dict | None:
    try:
        raw = _job_path(run_id).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def run_analysis_job(run_id: int) -> None:
    """子进程入口：执行分析并落状态文件，失败后重新抛出供退出码使用。"""
    from growth_talk import runs

    write_gt_job(run_id, status="running", message="分析任务运行中")
    try:
        runs.create_and_run_analysis(run_id)
    except Exception as exc:
        write_gt_job(run_id, status="error", message=str(exc)[:1000])
        raise
    write_gt_job(run_id, status="done", message="分析完成")


def launch_analysis(run_id: int) -> None:
    """拉起 ``python app.py gtjob <run_id>`` 子进程（会话独立、日志落盘）。"""
    directory = Path(JOB_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    with open(_log_path(run_id), "a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(BASE_DIR) / "app.py"),
             "gtjob", str(int(run_id))],
            cwd=str(BASE_DIR),
            stdout=log, stderr=log, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    time.sleep(LAUNCH_GRACE_SECONDS)
    if process.poll() is not None:
        tail = ""
        try:
            tail = _log_path(run_id).read_text(
                encoding="utf-8", errors="replace")[-2000:]
        except OSError:
            pass
        message = f"分析任务启动失败 (exit {process.returncode})"
        write_gt_job(run_id, status="error",
                     message=message + (f"\n{tail}" if tail else ""))
        raise JobLaunchError(message)


# ---------------------------------------------------------------------------
# Copilot 2.0 通用作业（LLM 耗时端点）
# ---------------------------------------------------------------------------
def _copilot_job_path(job_id: str) -> Path:
    return Path(COPILOT_JOB_DIR) / f"{job_id}.json"


def _copilot_log_path(job_id: str) -> Path:
    return Path(COPILOT_JOB_DIR) / f"{job_id}.log"


def write_copilot_job(job_id: str, **fields: Any) -> dict:
    """原子写 Copilot 作业状态文件。"""
    directory = Path(COPILOT_JOB_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    payload = dict(fields)
    payload["updated_at"] = datetime.utcnow().isoformat()
    target = _copilot_job_path(job_id)
    temporary = target.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False),
                         encoding="utf-8")
    os.replace(temporary, target)
    return payload


def read_copilot_job(job_id: str) -> dict | None:
    try:
        raw = _copilot_job_path(job_id).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def new_copilot_job(kind: str, payload: dict) -> tuple[str, Path]:
    """生成作业 id 并落参数文件（子进程只按文件读取，避免命令行超长）。"""
    job_id = uuid.uuid4().hex
    directory = Path(COPILOT_JOB_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    args_path = directory / f"{job_id}.args.json"
    args_path.write_text(
        json.dumps({"kind": kind, "payload": payload}, ensure_ascii=False),
        encoding="utf-8")
    return job_id, args_path


def launch_copilot_job(kind: str, payload: dict) -> str:
    """拉起 ``python app.py copilotjob <job_id> <args.json>`` 子进程。"""
    job_id, args_path = new_copilot_job(kind, payload)
    write_copilot_job(
        job_id, status="queued", message="任务已排队", kind=kind,
        student_id=payload.get("student_id"),
        advisor_id=payload.get("advisor_id"),
    )
    with open(_copilot_log_path(job_id), "a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(BASE_DIR) / "app.py"),
             "copilotjob", job_id, str(args_path)],
            cwd=str(BASE_DIR),
            stdout=log, stderr=log, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    time.sleep(LAUNCH_GRACE_SECONDS)
    if process.poll() is not None:
        tail = ""
        try:
            tail = _copilot_log_path(job_id).read_text(
                encoding="utf-8", errors="replace")[-2000:]
        except OSError:
            pass
        message = f"任务启动失败 (exit {process.returncode})"
        write_copilot_job(job_id, status="error", kind=kind,
                          student_id=payload.get("student_id"),
                          advisor_id=payload.get("advisor_id"),
                          message=message + (f"\n{tail}" if tail else ""))
        raise JobLaunchError(message)
    return job_id


def run_copilot_job(job_id: str, kind: str, payload: dict) -> dict:
    """子进程入口：执行作业并落状态文件，失败后重新抛出供退出码使用。"""
    meta = {
        "kind": kind,
        "student_id": payload.get("student_id"),
        "advisor_id": payload.get("advisor_id"),
    }
    write_copilot_job(job_id, status="running", message="任务运行中", **meta)
    try:
        result = _dispatch_copilot_job(kind, payload)
    except Exception as exc:
        write_copilot_job(job_id, status="error", message=str(exc)[:1000], **meta)
        raise
    revision = result.get("revision") if isinstance(result, dict) else None
    write_copilot_job(job_id, status="done", message="任务完成",
                      result=result, revision=revision, **meta)
    return result


def _dispatch_copilot_job(kind: str, payload: dict) -> dict:
    from growth_talk import copilot, copilot_report
    import growth_talk_store as store

    session_id = payload.get("session_id")
    expected_revision = payload.get("revision")
    actor_id = payload.get("advisor_id")

    def claim(action: str) -> int:
        """LLM 计算完成后再抢占 revision；失败时作业不落任何数据。"""
        try:
            return store.claim_revision(
                int(session_id), int(expected_revision), actor_id, action)
        except store.RevisionConflict as exc:
            raise store.RevisionConflict(STALE_JOB_MESSAGE) from exc

    if kind == "supplement":
        analysis = copilot.compute_supplement_analysis(int(session_id))
        revision = claim("supplement_analyzed")
        copilot.persist_supplement_analysis(int(session_id), analysis)
        return {"revision": revision, "analysis": analysis}

    if kind == "next_steps":
        summary = copilot.compute_next_steps(int(session_id))
        revision = claim("next_steps_generated")
        copilot.persist_next_steps(int(session_id), summary)
        return {"revision": revision, "result": {"summary": summary}}

    if kind == "projects_generate":
        batch, supplement, saved = copilot.compute_projects(int(session_id))
        revision = claim("project_recommendations_generated")
        copilot.persist_projects(supplement, saved)
        return {"revision": revision, "batch": batch}

    if kind == "projects_review":
        batch, session_row, supplement, validated, interests, saved = \
            copilot.compute_project_edits(
                int(session_id), payload.get("items") or [],
                payload.get("actor") or "")
        revision = claim("project_recommendations_reviewed")
        copilot.persist_project_edits(
            session_row, supplement, validated, interests, saved)
        return {"revision": revision, "batch": batch}

    if kind == "report_prepare":
        return copilot_report.prepare_report(
            int(session_id), int(expected_revision))

    if kind == "assistant":
        student_id = int(payload["student_id"])
        chat_id = str(payload["chat_id"])
        question = str(payload["question"])
        history = copilot.validate_chat_context(payload.get("history"))
        current = (store.get_session(int(session_id))
                   if session_id is not None else None)
        context = copilot.build_assistant_context(student_id, current)
        try:
            answer = copilot.ask_copilot_assistant(question, context, history)
        except Exception:
            try:
                store.add_chat_turn(
                    chat_id, question, None, "ERROR",
                    student_id=student_id,
                    session_id=int(session_id) if session_id else None)
            except Exception:
                pass
            raise
        store.add_chat_turn(
            chat_id, question, answer, "COMPLETE",
            student_id=student_id,
            session_id=int(session_id) if session_id else None)
        return {"answer": answer["answer"], "evidence": answer["evidence"],
                "chatId": chat_id}

    raise ValueError("不支持的任务类型")
