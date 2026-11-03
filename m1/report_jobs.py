"""会后报告生成作业：子进程 + JSON 状态文件（沿用 ``m1/jobs.py`` 的状态文件）。

路由拉起 ``python -m m1.report_jobs <job_id> <args.json>``；前端轮询
``GET /api/m1/jobs/<job_id>``。失败时还原报告状态并写中文错误。

另有 ``python -m m1.report_jobs --load-fixture <prep_id> <path>``：把样例文档
当作 AI 草稿载入，不调用 AI。
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

from app_utils import BASE_DIR
from m1 import jobs as m1_jobs
from m1.jobs import JOB_ID_RE, JobLaunchError, LAUNCH_GRACE_SECONDS, read_job, write_job

STEP_DEFS = (
    ("check", "资料检查"),
    ("speakers", "发言人识别"),
    ("y4", "Y4 标准化"),
    ("mapping", "R4 Mapping"),
    ("first_touch", "First Touch 分析"),
    ("safety", "安全检查"),
    ("meeting", "会议分析"),
    ("dims", "四维分析"),
    ("profile", "综合画像与方案"),
    ("checks", "质量检查"),
)


def new_steps() -> List[Dict[str, Any]]:
    return [{"step": key, "label": label, "state": "pending", "seconds": 0}
            for key, label in STEP_DEFS]


def _log_path(job_id: str) -> Path:
    return Path(m1_jobs.JOB_DIR) / ("%s.log" % job_id)


def launch_job(prep_id: int, report_id: int, *, previous_status: str = "draft",
               actor_id=None) -> str:
    job_id = uuid.uuid4().hex
    directory = Path(m1_jobs.JOB_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    args_path = directory / ("%s.args.json" % job_id)
    args_path.write_text(json.dumps({
        "prep_id": int(prep_id), "report_id": int(report_id),
        "previous_status": previous_status, "actor_id": actor_id,
    }, ensure_ascii=False), encoding="utf-8")
    base = dict(prep_id=int(prep_id), report_id=int(report_id), kind="report",
                previous_status=previous_status, actor_id=actor_id)
    write_job(job_id, status="queued", message="生成任务已排队", steps=new_steps(), **base)
    with open(_log_path(job_id), "a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "m1.report_jobs", job_id, str(args_path)],
            cwd=str(BASE_DIR), stdout=log, stderr=log, stdin=subprocess.DEVNULL,
            start_new_session=True)
    time.sleep(LAUNCH_GRACE_SECONDS)
    if process.poll() is not None:
        message = "生成任务启动失败 (exit %s)" % process.returncode
        write_job(job_id, status="error", message=message, steps=new_steps(), **base)
        raise JobLaunchError(message)
    return job_id


def run_job(job_id: str, args: Dict[str, Any]) -> int:
    from m1 import report_pipeline, report_store, store

    prep_id = int(args.get("prep_id") or 0)
    report_id = int(args.get("report_id") or 0)
    previous = str(args.get("previous_status") or "draft")
    actor_id = args.get("actor_id")
    job = read_job(job_id) or {}
    steps = job.get("steps") if isinstance(job.get("steps"), list) and job.get("steps") else new_steps()
    meta = {"prep_id": prep_id, "report_id": report_id, "kind": "report",
            "previous_status": previous, "actor_id": actor_id}

    def write(message: str, **fields: Any) -> None:
        write_job(job_id, steps=steps, message=message, **meta, **fields)

    def progress(step: str, state: str, seconds: float = 0.0) -> None:
        label = dict(STEP_DEFS).get(step, step)
        for row in steps:
            if row.get("step") == step:
                row["state"] = state
                row["seconds"] = seconds
        if state == "running":
            write("正在：%s" % label, status="running")
        elif state in ("done", "skipped"):
            write("已完成：%s" % label, status="running")

    write("生成任务运行中", status="running")
    try:
        version_id = report_pipeline.generate(prep_id, progress=progress, actor_id=actor_id)
    except Exception as exc:
        message = "生成失败：%s" % (str(exc).strip() or exc.__class__.__name__)
        message = message[:1000]
        try:
            fallback = previous if previous in report_store.STATUSES and previous != "generating" else "draft"
            report_store.set_status(report_id, fallback)
        except Exception:
            pass
        write(message, status="error")
        try:
            prep = store.get_prep(prep_id) or {}
            store.audit(actor_id, prep.get("student_id"), "m1.report_generate_failed",
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
        store.audit(actor_id, prep.get("student_id"), "m1.report_generate_done",
                    {"prep_id": prep_id, "version_id": version_id})
    except Exception:
        pass
    return version_id


# ---------------------------------------------------------------------------
# 样例载入（不调用 AI）
# ---------------------------------------------------------------------------
def _points_at_real_db() -> bool:
    import db as _db
    real = (Path(BASE_DIR) / "data" / "y4_students.db").resolve()
    url = _db.engine.url
    if not url.drivername.startswith("sqlite") or not url.database:
        return False
    return Path(url.database).resolve() == real


def load_fixture(prep_id: int, path: str) -> int:
    """把样例文档载入为 AI 草稿；返回版本 id。指向真实库时拒绝。"""
    from m1 import report_checks, report_store, store

    if _points_at_real_db():
        raise SystemExit("拒绝：DATABASE_URL 指向 data/y4_students.db（真实学生数据）。请改用沙盒库。")
    report_store.ensure_tables()
    prep = store.get_prep(int(prep_id))
    if not prep:
        raise SystemExit("会前准备 %s 不存在" % prep_id)
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    doc = raw.get("doc") if isinstance(raw.get("doc"), dict) else raw
    evidence = raw.get("evidence") if isinstance(raw.get("evidence"), list) else []
    ratings = raw.get("y4_ratings") if isinstance(raw.get("y4_ratings"), dict) else {}
    report = report_store.get_or_create_report(prep["id"])
    manifest = {"sources": ["样例文档"], "fixture": Path(path).name, "adjustments": []}
    version = {"doc": doc, "evidence": evidence, "y4_ratings": ratings, "manifest": manifest}
    checks = report_checks.run_checks(report, version)
    saved = report_store.add_version(
        report["id"], y4_ratings=ratings, evidence=evidence, ai_doc=doc,
        doc=copy.deepcopy(doc), checks=checks, manifest=manifest,
        status="ai_draft", safety=[])
    return saved["id"]


def main(argv: List[str]) -> int:
    if len(argv) >= 2 and argv[1] == "--load-fixture":
        if len(argv) != 4:
            print("usage: python -m m1.report_jobs --load-fixture <prep_id> <path>", file=sys.stderr)
            return 2
        version_id = load_fixture(int(argv[2]), argv[3])
        print("loaded version %s" % version_id)
        return 0
    if len(argv) < 3:
        print("usage: python -m m1.report_jobs <job_id> <args.json>", file=sys.stderr)
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
