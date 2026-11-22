"""Durable M1 generation leases on the workers' shared local job volume."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import time
from threading import Event, Thread
from uuid import uuid4

import fcntl

ACTIVE = ("queued", "running")
HEARTBEAT_SECONDS = 15
LEASE_SECONDS = 90
MAX_RUN_SECONDS = 1800
_active_worker = ContextVar("m1_generation_attempt", default=None)


class AttemptConflict(RuntimeError):
    pass


def _directory():
    import db
    from m1 import jobs

    database = sha256(str(db.engine.url).encode()).hexdigest()[:16]
    folder = Path(jobs.JOB_DIR) / "attempts" / database
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@contextmanager
def _locked(scope, target):
    path = _directory() / f"{scope}-{int(target)}.json"
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield path


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


def _document(scope, target):
    if scope == "prep":
        from m1 import store
        return store.get_prep(target)
    if scope == "report":
        from m1 import report_store
        return report_store.get_report_by_id(target)
    from m1 import plan_store
    return plan_store.get_plan(target)


def _restore(attempt):
    scope = attempt["scope"]
    target = attempt["target"]
    previous = attempt["previous"]
    row = _document(scope, target)
    status_key = "parent_status" if scope == "plan_parent" else "status"
    if not row or row[status_key] != "generating":
        return
    if scope == "prep":
        from m1 import store

        store.set_status(target, previous or ("review" if row["current_version_id"] else "draft"))
    elif scope == "report":
        from m1 import report_store

        report_store.set_status(target, previous or ("reviewing" if row["current_version_id"] else "draft"),
                                from_status="generating")
    else:
        from m1 import plan_store

        part = "parent" if scope == "plan_parent" else "internal"
        plan_store.fail_generation(target, part, previous=previous)


def _recover(path, attempt):
    from m1 import jobs

    if attempt is None:
        return None
    job = jobs.read_job(attempt["id"]) or {}
    if job.get("status") == "error":
        _restore(attempt)
    if job.get("status") in ("done", "error"):
        return None
    now = time.time()
    if now - path.stat().st_mtime < LEASE_SECONDS and now - attempt["started"] < MAX_RUN_SECONDS:
        return attempt["id"]
    _restore(attempt)
    jobs.write_job(attempt["id"], **{**attempt["meta"], "status": "error",
                   "message": "生成任务已中断。已保留之前的文档，请重新生成。"})
    return None


def reserve(scope, target, begin, **meta):
    """Serialize the state change and durable job claim across web workers."""
    from m1 import jobs

    with _locked(scope, target) as path:
        if _current_locked(path, scope, target):
            raise AttemptConflict("生成任务已在进行中")
        attempt = {"id": uuid4().hex, "scope": scope, "target": int(target),
                   "previous": None, "started": time.time(), "meta": meta}
        _write(path, attempt)
        jobs.write_job(attempt["id"], **meta, status="queued", message="生成任务已排队")
        try:
            previous = begin()
        except Exception:
            jobs.write_job(attempt["id"], **meta, status="error", message="未能开始生成。")
            raise
        attempt["previous"] = previous
        _write(path, attempt)
        return attempt["id"], previous


def _legacy_job(scope, target):
    from m1 import jobs

    for path in Path(jobs.JOB_DIR).glob("*.json"):
        if not jobs.JOB_ID_RE.fullmatch(path.stem):
            continue
        try:
            updated = path.stat().st_mtime
        except FileNotFoundError:
            continue
        job = jobs.read_job(path.stem) or {}
        if job.get("status") not in ACTIVE:
            continue
        if scope == "prep":
            matches = job.get("prep_id") == target and job.get("kind") != "report"
        elif scope == "report":
            matches = job.get("report_id") == target
        else:
            kinds = ("plan_parent",) if scope == "plan_parent" else ("plan_generate", "plan_regen")
            matches = job.get("plan_id") == target and job.get("kind") in kinds
        if not matches:
            continue
        if time.time() - updated <= MAX_RUN_SECONDS:
            return path.stem
        _restore({"scope": scope, "target": target, "previous": job.get("previous_status")})
        jobs.write_job(path.stem, **{**job, "status": "error",
                       "message": "生成任务已中断。已保留之前的文档，请重新生成。"})
    return None


def current(scope, target):
    with _locked(scope, target) as path:
        return _current_locked(path, scope, target)


def _current_locked(path, scope, target):
    attempt = _read(path)
    if attempt:
        return _recover(path, attempt)
    row = _document(scope, target)
    status_key = "parent_status" if scope == "plan_parent" else "status"
    if not row or row[status_key] != "generating":
        return None
    job_id = _legacy_job(scope, target)
    if job_id:
        return job_id
    if row.get("updated_at"):
        # Older records can outlive their job files. Give an untracked worker
        # the same maximum runtime before restoring the saved document.
        updated = datetime.fromisoformat(row["updated_at"])
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        if time.time() - updated.timestamp() > MAX_RUN_SECONDS:
            _restore({"scope": scope, "target": target, "previous": None})
    return None


def cancel(scope, target, job_id):
    from m1 import jobs

    with _locked(scope, target) as path:
        attempt = _read(path)
        if attempt is None or attempt["id"] != job_id:
            return
        _restore(attempt)
        jobs.write_job(job_id, **attempt["meta"], status="error", message="生成任务未能启动，请重试。")


def _matches(path, job_id):
    from m1 import jobs

    attempt = _read(path)
    return attempt and attempt["id"] == job_id and (jobs.read_job(job_id) or {}).get("status") in ACTIVE


@contextmanager
def commit():
    """Fence the short final document write against lease recovery and retry."""
    attempt = _active_worker.get()
    if attempt is None:
        yield
        return
    scope, target, job_id = attempt
    with _locked(scope, target) as path:
        if not _matches(path, job_id) or _recover(path, _read(path)) != job_id:
            raise AttemptConflict("生成任务已经结束或已重试")
        yield


@contextmanager
def worker(job_id, identity):
    if not identity:
        yield
        return
    scope, target = identity
    token = _active_worker.set((scope, target, job_id))
    stopped = Event()

    def heartbeat():
        while not stopped.wait(HEARTBEAT_SECONDS):
            try:
                with _locked(scope, target) as path:
                    if not _matches(path, job_id):
                        return
                    os.utime(path, None)
            except OSError:
                # A short filesystem failure can recover within the lease.
                pass

    thread = Thread(target=heartbeat, daemon=True)
    try:
        with commit():
            pass
        thread.start()
        yield
    finally:
        stopped.set()
        if thread.ident is not None:
            thread.join()
        _active_worker.reset(token)
