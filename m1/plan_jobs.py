"""发展计划的后台生成子进程。

与 ``m1/jobs.py`` 同一套做法：状态文件放在 ``_m1_jobs``，子进程按步骤推进，
失败时把计划状态还原到生成前。一次只写一个部分，导师可以只重做一处。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from app_utils import BASE_DIR
from m1.jobs import (JOB_DIR, JOB_ID_RE, LAUNCH_GRACE_SECONDS, JobLaunchError,
                     read_job, write_job)

KINDS = ("plan_inputs", "plan_goal", "plan_personal",
         "plan_generate", "plan_regen", "plan_parent")

STEP_DEFS: Dict[str, List[tuple]] = {
    "plan_inputs": [("read", "读取会后报告"), ("inputs", "提取学生资料")],
    "plan_goal": [("goal", "填写当前起点与预期进展")],
    "plan_personal": [("personal", "整理个性化需求")],
    "plan_generate": [
        ("read", "读取会后报告、目标与个性化需求"),
        ("wb", "查找 WB 参考课"),
        ("overview", "阶段总体目标与教学策略"),
        ("sessions", "第 1–3 节课（每节一次调用）"),
        ("checks", "检查"),
    ],
    "plan_regen": [("regen", "重新生成这一部分"), ("checks", "检查")],
    "plan_parent": [("parent", "生成家长版"), ("checks", "检查")],
}


def new_steps(kind: str) -> List[Dict[str, Any]]:
    return [{"step": key, "label": label, "state": "pending", "seconds": 0}
            for key, label in STEP_DEFS.get(kind) or []]


def launch_job(plan_id: int, kind: str, *, actor_id=None, code=None,
               section=None, use_old_report: bool = False,
               previous_status: Optional[str] = None) -> str:
    """拉起生成子进程；启动窗口内退出则抛 :class:`JobLaunchError`。"""
    if kind not in KINDS:
        raise ValueError("未知的发展计划任务：%s" % kind)
    import uuid
    import subprocess
    import time

    job_id = uuid.uuid4().hex
    directory = Path(JOB_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    args = {
        "plan_id": int(plan_id),
        "kind": kind,
        "code": code,
        "section": section,
        "use_old_report": bool(use_old_report),
        "previous_status": previous_status,
        "actor_id": actor_id,
    }
    args_path = directory / ("%s.args.json" % job_id)
    args_path.write_text(json.dumps(args, ensure_ascii=False), encoding="utf-8")
    write_job(job_id, status="queued", message="生成任务已排队",
              plan_id=int(plan_id), kind=kind, code=code, section=section,
              previous_status=previous_status, actor_id=actor_id,
              steps=new_steps(kind))
    log_path = directory / ("%s.log" % job_id)
    with open(log_path, "a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "m1.plan_jobs", job_id, str(args_path)],
            cwd=str(BASE_DIR),
            stdout=log, stderr=log, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    time.sleep(LAUNCH_GRACE_SECONDS)
    if process.poll() is not None:
        tail = ""
        try:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        except OSError:
            pass
        message = "生成任务启动失败 (exit %s)" % process.returncode
        write_job(job_id, status="error",
                  message=message + (("\n%s" % tail) if tail else ""),
                  plan_id=int(plan_id), kind=kind, section=section,
                  previous_status=previous_status, actor_id=actor_id,
                  steps=new_steps(kind))
        raise JobLaunchError(message)
    return job_id


def run_job(job_id: str, args: Dict[str, Any]) -> int:
    """子进程入口：执行生成并维护状态文件与计划状态。"""
    from m1 import plan_pipeline, plan_store

    plan_id = int(args.get("plan_id") or 0)
    kind = str(args.get("kind") or "")
    previous_status = args.get("previous_status")
    actor_id = args.get("actor_id")
    section = args.get("section")
    job = read_job(job_id) or {}
    steps = job.get("steps") if isinstance(job.get("steps"), list) else new_steps(kind)
    if not steps:
        steps = new_steps(kind)
    meta = {"plan_id": plan_id, "kind": kind, "section": section,
            "previous_status": previous_status, "actor_id": actor_id}

    def write(message: str, **fields: Any) -> None:
        write_job(job_id, steps=steps, message=message, **meta, **fields)

    def progress(step: str, state: str, seconds: float = 0.0) -> None:
        label = dict(STEP_DEFS.get(kind) or []).get(step, step)
        for row in steps:
            if row.get("step") != step:
                continue
            row["state"] = state
            row["seconds"] = seconds
            break
        if state == "active":
            write("正在：%s" % label, status="running")
        elif state == "done":
            write("已完成：%s" % label, status="running")

    write("生成任务运行中", status="running")
    try:
        if kind == "plan_inputs":
            result = plan_pipeline.read_report(plan_id, progress=progress, actor_id=actor_id)
        elif kind == "plan_goal":
            result = plan_pipeline.fill_goal(plan_id, str(args.get("code") or ""),
                                             progress=progress, actor_id=actor_id)
        elif kind == "plan_personal":
            result = plan_pipeline.personal_summary(plan_id, progress=progress, actor_id=actor_id)
        elif kind == "plan_generate":
            result = plan_pipeline.generate(plan_id, progress=progress, actor_id=actor_id,
                                            use_old_report=bool(args.get("use_old_report")))
        elif kind == "plan_regen":
            result = plan_pipeline.regenerate(plan_id, section, progress=progress,
                                              actor_id=actor_id)
        elif kind == "plan_parent":
            result = plan_pipeline.generate_parent(plan_id, progress=progress,
                                                   actor_id=actor_id)
        else:
            raise ValueError("未知的发展计划任务：%s" % kind)
    except Exception as exc:
        message = "生成失败：%s" % (str(exc).strip() or exc.__class__.__name__)
        message = message[:1000]
        part = "parent" if kind == "plan_parent" else "internal"
        if kind in ("plan_generate", "plan_regen", "plan_parent"):
            try:
                plan_store.fail_generation(plan_id, part, previous=previous_status)
            except Exception:
                pass
        write(message, status="error")
        raise

    for row in steps:
        row["state"] = "done"
    write("生成完成", status="done",
          version_id=result if isinstance(result, int) else None)
    if kind == "plan_generate":
        try:
            from m1 import store
            plan = plan_store.get_plan(plan_id) or {}
            store.audit(actor_id, plan.get("student_id"), "m1.plan_generate_done",
                        {"plan_id": plan_id, "prep_id": plan.get("prep_id"),
                         "block_no": plan.get("block_no")})
        except Exception:
            pass
    return 0


def load_fixture(plan_id: int, path: str) -> int:
    """把样例内部版写入数据库（DP7 走查用，不调用模型）。"""
    from m1 import plan_checks as checks
    from m1 import plan_store as pstore

    _refuse_real_db()
    pstore.ensure_tables()
    plan = pstore.get_plan(plan_id)
    if not plan:
        raise ValueError("发展计划不存在")
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    doc = raw.get("doc") if isinstance(raw, dict) and "doc" in raw else raw
    if not isinstance(doc, dict):
        raise ValueError("样例不是内部版 JSON")
    import copy
    version = pstore.add_version(
        plan_id, part="internal", kind="ai_draft", ai_doc=copy.deepcopy(doc),
        doc=copy.deepcopy(doc), checks=checks.run_checks(plan, doc),
        manifest={"fixture": Path(path).name})
    pstore.finish_generation(plan_id, "internal", version_id=version["id"])
    return version["id"]


def _refuse_real_db() -> None:
    url = os.environ.get("DATABASE_URL", "")
    if url and not any(word in url for word in ("sqlite", "tmp", "local", "file:")):
        raise SystemExit("拒绝写入真实数据库：%s" % url)


def main(argv: List[str]) -> int:
    if len(argv) >= 4 and argv[1] == "--load-fixture":
        version_id = load_fixture(int(argv[2]), argv[3])
        print("loaded version %s" % version_id)
        return 0
    if len(argv) < 3 or not JOB_ID_RE.fullmatch(argv[1]):
        print("usage: python -m m1.plan_jobs <job_id> <args.json>")
        return 2
    job_id, args_path = argv[1], Path(argv[2])
    args = json.loads(args_path.read_text(encoding="utf-8"))
    return run_job(job_id, args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
