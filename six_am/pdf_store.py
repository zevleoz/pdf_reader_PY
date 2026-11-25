"""6 A.M. PDF 成品存储：按学生与档案版本保存、去重、取件。

纯文件存储层：不导入 Flask、不访问数据库。调用方传入存储根目录与档案内容；
同一 ``profile_id`` 只保留一份 PDF，重复生成直接复用已有文件。

状态机（status item 的 ``state``）：
    missing  模型已生成，PDF 尚未生成
    running  另一进程/请求正在生成
    ready    PDF 可预览、可下载
    stale    PDF 早于当前档案内容（档案被就地修订），需重新生成
    failed   上次生成失败，可重试
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

LOCK_STALE_SECONDS = 300


def fingerprint(profile: Dict[str, Any]) -> str:
    """档案内容的稳定指纹：用于判断已存 PDF 是否对应当前档案。"""
    payload = json.dumps(profile or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _student_dir(root: Path, student_id: int) -> Path:
    return Path(root) / str(int(student_id))


def artifact_path(root: Path, student_id: int, profile_id: int) -> Path:
    return _student_dir(root, student_id) / ("profile_%d.pdf" % int(profile_id))


def _status_path(root: Path, student_id: int, profile_id: int) -> Path:
    return _student_dir(root, student_id) / ("profile_%d.status.json" % int(profile_id))


def _lock_path(root: Path, student_id: int, profile_id: int) -> Path:
    return _student_dir(root, student_id) / ("profile_%d.lock" % int(profile_id))


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    os.replace(str(tmp), str(path))


def _item(student_id: int, profile_id: int, *, version: Optional[int] = None,
          report_id: Optional[int] = None, created_at: Optional[str] = None,
          state: str = "missing", size: int = 0, generated_at: Optional[str] = None,
          error: str = "") -> Dict[str, Any]:
    return {
        "profile_id": int(profile_id),
        "student_id": int(student_id),
        "version": version,
        "report_id": report_id,
        "created_at": created_at,
        "state": state,
        "size": size,
        "generated_at": generated_at,
        "error": error,
    }


def _lock_is_stale(path: Path) -> bool:
    try:
        return (time.time() - path.stat().st_mtime) > LOCK_STALE_SECONDS
    except OSError:
        return False


def status(root: Path, student_id: int, profile_id: int, profile: Dict[str, Any], *,
           version: Optional[int] = None, report_id: Optional[int] = None,
           created_at: Optional[str] = None) -> Dict[str, Any]:
    """当前 PDF 状态（只读，不生成）。"""
    path = artifact_path(root, student_id, profile_id)
    meta = _read_json(_status_path(root, student_id, profile_id))
    item = _item(student_id, profile_id, version=version, report_id=report_id, created_at=created_at)
    fp = fingerprint(profile)

    if path.exists():
        if meta.get("fingerprint") and meta.get("fingerprint") != fp:
            item.update(state="stale", size=path.stat().st_size,
                        generated_at=meta.get("generated_at"))
            return item
        item.update(state="ready", size=path.stat().st_size,
                    generated_at=meta.get("generated_at"))
        return item

    lock = _lock_path(root, student_id, profile_id)
    if lock.exists() and not _lock_is_stale(lock):
        item.update(state="running", generated_at=meta.get("generated_at"))
        return item
    if meta.get("state") == "failed" and meta.get("fingerprint") == fp:
        item.update(state="failed", error=str(meta.get("error") or ""),
                    generated_at=meta.get("generated_at"))
        return item
    return item


def read_artifact(root: Path, student_id: int, profile_id: int) -> Optional[bytes]:
    path = artifact_path(root, student_id, profile_id)
    if not path.exists():
        return None
    return path.read_bytes()


def generate(root: Path, student_id: int, profile_id: int, profile: Dict[str, Any], *,
             student: Optional[Dict[str, Any]] = None, version: Optional[int] = None,
             report_id: Optional[int] = None, created_at: Optional[str] = None,
             renderer=None) -> Dict[str, Any]:
    """生成（或复用）该档案版本的 PDF，返回最新状态。

    - 已 ready：直接返回，不重复生成；
    - 正在生成：返回 running，由调用方告知稍后再取；
    - 失败：记录 failed 与错误，可再次调用重试；
    - 并发生成用 O_EXCL 锁去重，锁超过 5 分钟视为残留并接管。
    """
    from . import render_pdf

    render = renderer or render_pdf.build_six_am_pdf
    item = status(root, student_id, profile_id, profile,
                  version=version, report_id=report_id, created_at=created_at)
    if item["state"] == "ready":
        return item
    if item["state"] == "running":
        return item

    path = artifact_path(root, student_id, profile_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_path(root, student_id, profile_id)
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if not _lock_is_stale(lock):
            return _item(student_id, profile_id, version=version, report_id=report_id,
                         created_at=created_at, state="running")
        try:
            lock.unlink()
        except OSError:
            pass
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return _item(student_id, profile_id, version=version, report_id=report_id,
                         created_at=created_at, state="running")

    try:
        os.write(fd, ("%d %s" % (os.getpid(), time.time())).encode("ascii"))
        os.close(fd)
        blob = render(profile, student=student, version=version)
        tmp = path.with_name(path.name + ".tmp%d" % os.getpid())
        tmp.write_bytes(blob)
        os.replace(str(tmp), str(path))
        _write_json(_status_path(root, student_id, profile_id), {
            "state": "ready",
            "fingerprint": fingerprint(profile),
            "version": version,
            "report_id": report_id,
            "size": len(blob),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "error": "",
        })
    except Exception as exc:  # 记录失败原因，交由 UI 重试
        try:
            if path.exists() and path.stat().st_size == 0:
                path.unlink()
        except OSError:
            pass
        _write_json(_status_path(root, student_id, profile_id), {
            "state": "failed",
            "fingerprint": fingerprint(profile),
            "version": version,
            "report_id": report_id,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "error": str(exc),
        })
    finally:
        try:
            lock.unlink()
        except OSError:
            pass

    return status(root, student_id, profile_id, profile,
                  version=version, report_id=report_id, created_at=created_at)


def pdf_filename(student_name: str, version: Optional[int]) -> str:
    safe = (student_name or "").replace("/", "_").replace("\\", "_").replace(" ", "")
    suffix = ("_v%s" % version) if version else ""
    return "凭远6AM六维启动档案_%s%s.pdf" % (safe, suffix)
