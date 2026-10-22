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
from datetime import datetime
from pathlib import Path
from typing import Any

from app_utils import BASE_DIR, DATA_DIR

JOB_DIR = Path(DATA_DIR) / "_gt_jobs"
LAUNCH_GRACE_SECONDS = 0.3


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
