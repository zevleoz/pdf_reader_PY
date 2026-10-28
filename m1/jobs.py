"""M1 生成作业：子进程 + JSON 状态文件（与 ``growth_talk/jobs.py`` 同模式）。

路由只负责拉起 ``python -m m1.jobs <job_id> <args.json>``；前端轮询
``data/_m1_jobs/<job_id>.json``。失败时把 prep 状态还原并写可读错误。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from app_utils import BASE_DIR, DATA_DIR

JOB_DIR = Path(DATA_DIR) / "_m1_jobs"
LAUNCH_GRACE_SECONDS = 0.3
JOB_ID_RE = re.compile(r"[a-f0-9]{32}")

STEP_DEFS = (
    ("safety", "安全检查"),
    ("evidence", "整理证据"),
    ("abilities", "逐项判断"),
    ("priority", "确定优先能力"),
    ("plan", "设计会议流程"),
    ("assemble", "生成文档"),
)


class JobLaunchError(RuntimeError):
    """子进程在启动窗口内立即退出。"""


def _job_path(job_id: str) -> Path:
    return Path(JOB_DIR) / ("%s.json" % job_id)


def _log_path(job_id: str) -> Path:
    return Path(JOB_DIR) / ("%s.log" % job_id)


def new_steps() -> List[Dict[str, Any]]:
    return [{"step": key, "label": label, "state": "pending", "seconds": 0}
            for key, label in STEP_DEFS]


def write_job(job_id: str, **fields: Any) -> Dict[str, Any]:
    """原子写状态文件，避免前端读到半截 JSON。"""
    directory = Path(JOB_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    payload = dict(fields)
    payload["updated_at"] = datetime.utcnow().isoformat()
    target = _job_path(job_id)
    temporary = target.with_suffix(".%s.tmp" % os.getpid())
    temporary.write_text(json.dumps(payload, ensure_ascii=False),
                         encoding="utf-8")
    os.replace(temporary, target)
    return payload


def read_job(job_id: str) -> Dict[str, Any] | None:
    try:
        raw = _job_path(job_id).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def launch_job(prep_id: int, *, previous_status: str = "draft",
               actor_id=None) -> str:
    """拉起生成子进程；启动窗口内退出则抛 :class:`JobLaunchError`。"""
    job_id = uuid.uuid4().hex
    directory = Path(JOB_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    args_path = directory / ("%s.args.json" % job_id)
    args_path.write_text(json.dumps({
        "prep_id": int(prep_id),
        "previous_status": previous_status,
        "actor_id": actor_id,
    }, ensure_ascii=False), encoding="utf-8")

    write_job(job_id, status="queued", message="生成任务已排队",
              prep_id=int(prep_id), previous_status=previous_status,
              actor_id=actor_id, steps=new_steps())

    with open(_log_path(job_id), "a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "m1.jobs", job_id, str(args_path)],
            cwd=str(BASE_DIR),
            stdout=log, stderr=log, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    time.sleep(LAUNCH_GRACE_SECONDS)
    if process.poll() is not None:
        tail = ""
        try:
            tail = _log_path(job_id).read_text(
                encoding="utf-8", errors="replace")[-2000:]
        except OSError:
            pass
        message = "生成任务启动失败 (exit %s)" % process.returncode
        write_job(job_id, status="error",
                  message=message + (("\n%s" % tail) if tail else ""),
                  prep_id=int(prep_id), previous_status=previous_status,
                  actor_id=actor_id, steps=new_steps())
        raise JobLaunchError(message)
    return job_id


def run_job(job_id: str, args: Dict[str, Any]) -> int:
    """子进程入口：执行生成并维护状态文件与 prep 状态。"""
    from m1 import pipeline, store

    prep_id = int(args.get("prep_id") or 0)
    previous_status = str(args.get("previous_status") or "draft")
    actor_id = args.get("actor_id")
    job = read_job(job_id) or {}
    steps = job.get("steps") if isinstance(job.get("steps"), list) else new_steps()
    if not steps:
        steps = new_steps()
    meta = {"prep_id": prep_id, "previous_status": previous_status,
            "actor_id": actor_id}

    def write(message: str, **fields: Any) -> None:
        write_job(job_id, steps=steps, message=message, **meta, **fields)

    def progress(step: str, state: str, seconds: float = 0.0) -> None:
        label = dict(STEP_DEFS).get(step, step)
        for row in steps:
            if row.get("step") != step:
                continue
            row["state"] = state
            row["seconds"] = seconds
            break
        if state == "running":
            write("正在：%s" % label, status="running")
        elif state == "done":
            write("已完成：%s" % label, status="running")

    write("生成任务运行中", status="running")
    try:
        version_id = pipeline.generate(prep_id, progress=progress)
    except Exception as exc:
        message = "生成失败：%s" % (str(exc).strip() or exc.__class__.__name__)
        message = message[:1000]
        try:
            store.set_status(prep_id, previous_status
                             if previous_status in store.STATUSES else "draft")
        except Exception:
            pass
        write(message, status="error")
        try:
            prep = store.get_prep(prep_id) or {}
            store.audit(actor_id, prep.get("student_id"), "m1.generate_failed",
                        {"prep_id": prep_id, "error": message})
        except Exception:
            pass
        raise

    for row in steps:
        if row.get("state") in ("pending", "running"):
            row["state"] = "done"
    write("生成完成", status="done", result={"version_id": version_id})
    try:
        prep = store.get_prep(prep_id) or {}
        store.audit(actor_id, prep.get("student_id"), "m1.generate_done",
                    {"prep_id": prep_id, "version_id": version_id})
    except Exception:
        pass
    return version_id


def main(argv: List[str]) -> int:
    if len(argv) < 3:
        print("usage: python -m m1.jobs <job_id> <args.json>", file=sys.stderr)
        return 2
    job_id = argv[1]
    if not JOB_ID_RE.fullmatch(job_id):
        print("invalid job id", file=sys.stderr)
        return 2
    try:
        args = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print("cannot read args: %s" % exc, file=sys.stderr)
        return 2
    try:
        run_job(job_id, args if isinstance(args, dict) else {})
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
