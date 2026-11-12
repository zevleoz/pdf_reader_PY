# -*- coding: utf-8 -*-
"""Y4 单文件上传：按槽位（A2/B3/B4/B6）逐份读取，合并进学生当前 Y4 记录。

设计见 docs/audits/plans-hub/S4-U-proposal.md 与 S4-U1-backend.md。

- 学生的「当前 Y4 记录」= 其最新一条 ``reports`` 行；每份资料的状态存在该行
  ``data_json["slots"]``，从未上传的槽位对应的 schema_124 值为 ``null``（不是 0 / 空串）。
- 读取任务只跑该槽位的视觉读取，在自己的临时目录里完成（不碰 ``input/`` 与
  ``data/report_data.json``），结果只替换该槽位的编号，其它槽位原样保留。
- 任务进 ``y4_jobs`` 表排队；单个后台进程（``python app.py y4worker``）按序执行，
  执行期间持有 ``data/_job.json`` 锁，所以不会与旧的批量流水线重叠；批量任务在跑时 worker 等待。
- 旧批量流程（``/api/generate/start`` 等）完全不受影响。
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import (Column, DateTime, Integer, String, Text, select,
                        update)
from sqlalchemy.orm import Session, aliased

import db as _db
from app_utils import BASE_DIR, DATA_DIR, JOB_FILE, OUTPUT_DIR

SLOTS: Tuple[str, ...] = ("A2", "B3", "B4", "B6")
STALE_SECONDS = 1200  # 与 reports._job_running 同一条 20 分钟规则

SLOT_STATES = ("empty", "queued", "reading", "done", "failed")
NA = "—"  # 与 extract.extract_student_info 的「读不到」占位一致


# ---------------------------------------------------------------------------
# y4_jobs 表
# ---------------------------------------------------------------------------
class Y4Round(_db.Base):
    """一轮 Y4 上传。第一次读取成功时才建 reports 行（report_id 在此之前为空），
    所以读取失败/排队中不会留下空报告。槽位与生成状态存在 state_json。"""
    __tablename__ = "y4_rounds"
    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, index=True, nullable=False)
    report_id = Column(Integer, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String(100))
    state_json = Column(Text)


class Y4Job(_db.Base):
    __tablename__ = "y4_jobs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    round_id = Column(Integer, index=True)
    # 不加外键；report_id 在首次读取成功前为 0
    report_id = Column(Integer, index=True, nullable=False, default=0)
    student_id = Column(Integer, index=True, nullable=False)
    kind = Column(String(10), nullable=False)       # read | build
    slot = Column(String(4))                        # build 为 NULL
    status = Column(String(10), nullable=False, index=True)  # queued|running|done|failed
    error = Column(Text)
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)


def ensure_schema() -> None:
    """给已存在的 y4_jobs 表补 round_id 列（create_all 不会改旧表）。"""
    from sqlalchemy import inspect, text
    try:
        cols = {c["name"] for c in inspect(_db.engine).get_columns("y4_jobs")}
        if "round_id" not in cols:
            with _db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE y4_jobs ADD COLUMN round_id INTEGER"))
    except Exception as exc:  # noqa: BLE001
        print(f"[DB] y4_jobs 补列失败 (非致命): {exc}")


def _now() -> datetime:
    return datetime.utcnow()


def _iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _job_dict(j: Y4Job) -> Dict[str, Any]:
    return {
        "id": j.id, "round_id": j.round_id, "report_id": j.report_id,
        "student_id": j.student_id,
        "kind": j.kind, "slot": j.slot, "status": j.status,
        "error": j.error or "", "created_by": j.created_by or "",
        "created_at": j.created_at, "started_at": j.started_at,
        "finished_at": j.finished_at,
    }


# ---------------------------------------------------------------------------
# 编号 ↔ 槽位
# ---------------------------------------------------------------------------
def _schema_entries() -> List[Dict[str, Any]]:
    import extract
    return extract.SCHEMA_124


def slot_codes(slot: str) -> List[str]:
    return [e["code"] for e in _schema_entries() if e.get("source_pdf") == slot]


def code_slot(code: str) -> str:
    code = str(code)
    if code.startswith("b3d."):
        return "B3"
    for e in _schema_entries():
        if e["code"] == code:
            return e.get("source_pdf") or ""
    return ""


def _blank_item(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "code": entry["code"], "label": entry["label"], "value": None,
        "type": entry["type"], "unit": entry.get("unit", "") or "",
        "source_pdf": entry["source_pdf"], "note": entry.get("note", ""),
    }


def _blank_slot() -> Dict[str, Any]:
    return {"state": "empty", "file_name": "", "file_path": "", "read_at": "",
            "name_in_pdf": "", "name_mismatch": False, "error": "",
            "has_data": False}


# ---------------------------------------------------------------------------
# 记录（reports 行）读写
# ---------------------------------------------------------------------------
def _loads(text: Optional[str]) -> Dict[str, Any]:
    try:
        raw = json.loads(text) if text else {}
    except Exception:
        raw = {}
    return raw if isinstance(raw, dict) else {}


def _new_raw(student: Dict[str, Any], started_at: str = "") -> Dict[str, Any]:
    def pick(k: str) -> str:
        return (student.get(k) or "").strip() or NA
    return {
        "student": {
            "name": (student.get("name") or "").strip() or NA,
            "gender": pick("gender"), "birthday": pick("birthday"),
            "test_date": NA, "grade": pick("grade"), "school": pick("school"),
            "teacher": NA, "archive_id": NA, "report_code": NA,
        },
        "pdf_titles": [],
        "schema_124": [_blank_item(e) for e in _schema_entries()],
        "sections": [],
        "vision": {},
        "round_started_at": started_at or _iso(),
        "edits": [],
    }


def _adopt_legacy(raw: Dict[str, Any]) -> Dict[str, Any]:
    """批量流程生成的旧记录没有轮次状态：按 pdf_titles（或有值的槽位）推断哪些槽位已有数据，
    没有的槽位值改成 null（显示「未上传」）。就地改 raw，返回轮次 state。"""
    items = [it for it in (raw.get("schema_124") or []) if isinstance(it, dict)]
    titles = {t for t in (raw.get("pdf_titles") or []) if t in SLOTS}
    if not titles:
        for it in items:
            if str(it.get("code")) != "059" and str(it.get("value") or "").strip():
                sl = code_slot(it.get("code"))
                if sl in SLOTS:
                    titles.add(sl)
    have = {str(it.get("code")) for it in items}
    for e in _schema_entries():
        if e["code"] not in have:
            items.append(_blank_item(e))
    for it in items:
        sl = code_slot(it.get("code"))
        if sl in SLOTS and sl not in titles and it.get("value") in ("", None):
            it["value"] = None
    raw["schema_124"] = items
    raw.setdefault("edits", [])
    state = _blank_state()
    for sl in SLOTS:
        if sl in titles:
            state["slots"][sl].update(state="done", has_data=True)
    return state


def _blank_state() -> Dict[str, Any]:
    return {"slots": {s: _blank_slot() for s in SLOTS}, "build": {"state": "none"}}


def _round_dict(r: Y4Round) -> Dict[str, Any]:
    st = _loads(r.state_json)
    blank = _blank_state()
    slots = st.get("slots") if isinstance(st.get("slots"), dict) else {}
    st["slots"] = {s: {**blank["slots"][s], **(slots.get(s) or {})} for s in SLOTS}
    if not isinstance(st.get("build"), dict):
        st["build"] = blank["build"]
    return {"id": r.id, "student_id": r.student_id, "report_id": r.report_id,
            "started_at": r.started_at, "state": st}


def get_round(round_id: int) -> Optional[Dict[str, Any]]:
    with Session(_db.engine) as sess:
        r = sess.get(Y4Round, int(round_id))
        return _round_dict(r) if r else None


def latest_round(student_id: int) -> Optional[Dict[str, Any]]:
    with Session(_db.engine) as sess:
        r = sess.execute(select(Y4Round).where(Y4Round.student_id == int(student_id))
                         .order_by(Y4Round.id.desc()).limit(1)).scalar_one_or_none()
        return _round_dict(r) if r else None


def create_round(student_id: int, created_by: str = "", report_id: Optional[int] = None,
                 state: Optional[Dict[str, Any]] = None) -> int:
    with Session(_db.engine) as sess:
        r = Y4Round(student_id=int(student_id), report_id=report_id,
                    created_by=created_by or "", started_at=_now(),
                    state_json=json.dumps(state or _blank_state(), ensure_ascii=False))
        sess.add(r)
        sess.commit()
        return r.id


def current_round(student_id: int, created_by: str = "",
                  persist: bool = False) -> Dict[str, Any]:
    """学生当前的一轮 = 其最新的一轮。没有轮次时：有批量流程的报告就沿用最新那条
    （persist=True 时把它登记成一轮），否则给一个空轮（persist=True 时建出来）。
    persist=False 时返回 id 为 None 的临时视图，不写库。"""
    rd = latest_round(student_id)
    if rd:
        return rd
    with Session(_db.engine) as sess:
        rep = sess.execute(
            select(_db.Report).where(_db.Report.student_id == int(student_id))
            .order_by(_db.Report.created_at.desc(), _db.Report.id.desc()).limit(1)
        ).scalar_one_or_none()
        if rep is not None:
            raw = _loads(rep.data_json)
            state = _adopt_legacy(raw)
            rid = rep.id
            if persist:
                rep.data_json = json.dumps(raw, ensure_ascii=False)
                sess.commit()
        else:
            state, rid = _blank_state(), None
    if persist:
        return get_round(create_round(student_id, created_by, rid, state))
    return {"id": None, "student_id": int(student_id), "report_id": rid,
            "started_at": None, "state": state}


def load_raw(report_id: int) -> Optional[Dict[str, Any]]:
    with Session(_db.engine) as sess:
        r = sess.get(_db.Report, int(report_id))
        if r is None:
            return None
        raw = _loads(r.data_json)
        raw.setdefault("edits", [])
        return raw


@contextmanager
def _edit_raw(report_id: int):
    """读-改-写 reports.data_json（单事务）。"""
    with Session(_db.engine) as sess:
        r = sess.get(_db.Report, int(report_id))
        if r is None:
            raise LookupError(f"报告 {report_id} 不存在")
        raw = _loads(r.data_json)
        yield raw, r
        r.data_json = json.dumps(raw, ensure_ascii=False)
        sess.commit()


@contextmanager
def _edit_round(round_id: int):
    with Session(_db.engine) as sess:
        r = sess.get(Y4Round, int(round_id))
        if r is None:
            raise LookupError(f"轮次 {round_id} 不存在")
        state = _round_dict(r)["state"]
        yield state, r
        r.state_json = json.dumps(state, ensure_ascii=False)
        sess.commit()


def _set_slot(round_id: int, slot: str, **fields: Any) -> None:
    with _edit_round(round_id) as (state, _r):
        state["slots"][slot].update(fields)


def _set_build(round_id: int, **fields: Any) -> None:
    with _edit_round(round_id) as (state, _r):
        state["build"].update(fields)


# ---------------------------------------------------------------------------
# 手改记录
# ---------------------------------------------------------------------------
def edited_codes_by_slot(raw: Dict[str, Any]) -> Dict[str, List[str]]:
    """每个槽位里「最近一次改动是人手改的」编号（用于重传前的警告）。
    最近一次改动是 upload:* 的（已被新读取覆盖）不算。"""
    latest: Dict[str, Dict[str, Any]] = {}
    for e in raw.get("edits") or []:
        if isinstance(e, dict) and e.get("code"):
            latest[str(e["code"])] = e
    out: Dict[str, List[str]] = {s: [] for s in SLOTS}
    for code, e in latest.items():
        if str(e.get("by") or "").startswith("upload:"):
            continue
        s = code_slot(code)
        if s in out:
            out[s].append(code)
    for s in out:
        out[s].sort()
    return out


def _b3d_flat(detail: Any) -> Dict[str, str]:
    """b3_detail 里可手改的值，展平成 {b3d.* 编号: 文本}。"""
    out: Dict[str, str] = {}
    if not isinstance(detail, dict):
        return out
    for k in ("motivation_type", "method_type"):
        if k in detail:
            out[f"b3d.{k}"] = "" if detail[k] is None else str(detail[k])
    for k in ("practice_dims", "practice_items", "exec_dims", "exec_items"):
        rows = detail.get(k)
        if isinstance(rows, list):
            for i, row in enumerate(rows):
                if isinstance(row, dict):
                    sc = row.get("score")
                    out[f"b3d.{k}.{i}"] = "" if sc is None else f"{sc:g}" \
                        if isinstance(sc, (int, float)) else str(sc)
    return out


# ---------------------------------------------------------------------------
# 合并读取结果
# ---------------------------------------------------------------------------
def _recompute_cross_slot(raw: Dict[str, Any], state: Dict[str, Any]) -> None:
    """合并后重算跨槽位的值。Step 0 的结论：extract.py 里没有任何编号由多个槽位共同算出；
    唯一跨槽位的是 pdf_titles（v2 用它决定出哪些页）和 student 元信息，在这里刷新 pdf_titles。"""
    raw["pdf_titles"] = [s for s in SLOTS if state["slots"][s].get("has_data")]


def _names_match(a: str, b: str) -> bool:
    n = lambda s: re.sub(r"\s+", "", s or "")
    return n(a) == n(b)


def merge_read(round_id: int, slot: str, result: Dict[str, Any], *,
               student_name: str, file_name: str = "") -> int:
    """把一次读取结果并进本轮的报告：替换该槽位的编号，其它槽位不动。
    本轮还没有 reports 行时，在这里（第一次读取成功）才建，并写回 round.report_id。
    返回 report id。"""
    values: Dict[str, Any] = result.get("values") or {}
    pdf_student = result.get("student") or {}
    name_in_pdf = str(pdf_student.get("name") or "").strip()
    if name_in_pdf == NA:
        name_in_pdf = ""
    mismatch = bool(name_in_pdf) and not _names_match(name_in_pdf, student_name)
    now = _iso()
    with Session(_db.engine) as sess:
        rd = sess.get(Y4Round, int(round_id))
        state = _round_dict(rd)["state"]
        if rd.report_id is None:
            stu = sess.get(_db.Student, rd.student_id)
            raw = _new_raw({"name": stu.name, "gender": stu.gender,
                            "birthday": stu.birthday, "grade": stu.grade,
                            "school": stu.school},
                           rd.started_at.isoformat(timespec="seconds")
                           if rd.started_at else "")
            report = _db.Report(student_id=rd.student_id, report_date=date.today(),
                                pdf_path="", data_json="{}")
            sess.add(report)
            sess.flush()
            rd.report_id = report.id
        else:
            report = sess.get(_db.Report, rd.report_id)
            raw = _loads(report.data_json)

        items = raw.setdefault("schema_124", [])
        by_code = {str(it.get("code")): it for it in items if isinstance(it, dict)}
        for e in _schema_entries():
            if e["code"] not in by_code:
                it = _blank_item(e)
                items.append(it)
                by_code[e["code"]] = it
        edits_log = raw.get("edits")
        if not isinstance(edits_log, list):
            edits_log = []
            raw["edits"] = edits_log
        had_edit = {str(e.get("code")) for e in edits_log if isinstance(e, dict)}

        for code in slot_codes(slot):
            item = by_code[code]
            new = values.get(code)
            new_text = "" if new is None else str(new)
            old = item.get("value")
            old_text = "" if old is None else str(old)
            item["value"] = new_text
            if code in had_edit:
                edits_log.append({"code": code, "old": old_text, "new": new_text,
                                  "by": f"upload:{slot}", "at": now})

        if slot == "B3":
            old_flat = _b3d_flat(raw.get("b3_detail"))
            detail = result.get("b3_detail")
            if detail:
                raw["b3_detail"] = detail
            else:
                raw.pop("b3_detail", None)
            new_flat = _b3d_flat(detail)
            for code in sorted(had_edit):
                if code.startswith("b3d."):
                    edits_log.append({"code": code, "old": old_flat.get(code, ""),
                                      "new": new_flat.get(code, ""),
                                      "by": "upload:B3", "at": now})

        # student 元信息：PDF 里读到的非空项补空（姓名始终以档案为准，不被 PDF 改写）
        st = raw.setdefault("student", {})
        for k, v in pdf_student.items():
            v = (str(v) if v is not None else "").strip()
            if k == "name" or not v or v == NA:
                continue
            if (st.get(k) or NA) == NA:
                st[k] = v
        if not st.get("name") or st.get("name") == NA:
            st["name"] = student_name

        vision = result.get("vision")
        if isinstance(vision, dict) and vision:
            raw.setdefault("vision", {})[slot] = vision

        slot_state = state["slots"][slot]
        slot_state.update(state="done", read_at=now, name_in_pdf=name_in_pdf,
                          name_mismatch=mismatch, error="", has_data=True)
        if file_name:
            slot_state["file_name"] = file_name
        _recompute_cross_slot(raw, state)
        report.data_json = json.dumps(raw, ensure_ascii=False)
        rd.state_json = json.dumps(state, ensure_ascii=False)
        sess.commit()
        return report.id


# ---------------------------------------------------------------------------
# 目录
# ---------------------------------------------------------------------------
def inputs_dir(round_id: int) -> Path:
    return DATA_DIR / "y4_inputs" / f"round{int(round_id)}"


def original_path(round_id: int, slot: str) -> Path:
    return inputs_dir(round_id) / f"{slot}.pdf"


def builds_dir(report_id: int) -> Path:
    return DATA_DIR / "y4_builds" / str(int(report_id))


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(BASE_DIR))
    except ValueError:
        return str(p)


def _abs(p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else BASE_DIR / q


# ---------------------------------------------------------------------------
# 队列
# ---------------------------------------------------------------------------
def enqueue(round_id: int, report_id: Optional[int], student_id: int, kind: str,
            slot: Optional[str], created_by: str) -> int:
    with Session(_db.engine) as sess:
        j = Y4Job(round_id=int(round_id), report_id=int(report_id or 0),
                  student_id=int(student_id), kind=kind, slot=slot, status="queued",
                  created_by=created_by or "", created_at=_now())
        sess.add(j)
        sess.commit()
        return j.id


def get_job(job_id: int) -> Optional[Dict[str, Any]]:
    with Session(_db.engine) as sess:
        j = sess.get(Y4Job, int(job_id))
        return _job_dict(j) if j else None


def pending_jobs() -> List[Dict[str, Any]]:
    """排队中和运行中的任务，按 id 升序。"""
    with Session(_db.engine) as sess:
        rows = sess.execute(
            select(Y4Job).where(Y4Job.status.in_(("queued", "running")))
            .order_by(Y4Job.id)).scalars().all()
        return [_job_dict(j) for j in rows]


def last_failed_read_jobs(round_id: int) -> Dict[str, int]:
    """每个槽位最近一次读取任务若是失败的，给出它的 id（供 重试 用）。"""
    with Session(_db.engine) as sess:
        rows = sess.execute(
            select(Y4Job).where(Y4Job.round_id == int(round_id), Y4Job.kind == "read")
            .order_by(Y4Job.id)).scalars().all()
    latest: Dict[str, Y4Job] = {j.slot: j for j in rows}
    return {s: j.id for s, j in latest.items() if j.status == "failed"}


def queue_position(job_id: int) -> int:
    """1 = 正在运行或下一个；0 = 已不在队列里。"""
    for i, j in enumerate(pending_jobs(), 1):
        if j["id"] == int(job_id):
            return i
    return 0


def _fail_job(job_id: int, error: str, only_status: Optional[str] = None) -> bool:
    with Session(_db.engine) as sess:
        cond = [Y4Job.id == int(job_id)]
        cond.append(Y4Job.status == only_status if only_status
                    else Y4Job.status.in_(("queued", "running")))
        res = sess.execute(update(Y4Job).where(*cond).values(
            status="failed", error=error, finished_at=_now()))
        sess.commit()
        return bool(res.rowcount)


def _mark_target_failed(job: Dict[str, Any], error: str) -> None:
    try:
        if job["kind"] == "read" and job["slot"]:
            _set_slot(job["round_id"], job["slot"], state="failed", error=error)
        elif job["kind"] == "build":
            _set_build(job["round_id"], state="failed", error=error)
    except Exception:
        pass


def fail_stale_jobs() -> List[int]:
    """running 超过 20 分钟的任务算失败（同 _job_running 的规则）。"""
    cutoff = _now() - timedelta(seconds=STALE_SECONDS)
    failed: List[int] = []
    with Session(_db.engine) as sess:
        rows = sess.execute(select(Y4Job).where(
            Y4Job.status == "running", Y4Job.started_at < cutoff)).scalars().all()
        stale = [_job_dict(j) for j in rows]
    for j in stale:
        if _fail_job(j["id"], "任务超过 20 分钟没有完成，已按失败处理", "running"):
            _mark_target_failed(j, "任务超过 20 分钟没有完成，已按失败处理")
            failed.append(j["id"])
    return failed


def has_queued() -> bool:
    with Session(_db.engine) as sess:
        return sess.execute(select(Y4Job.id).where(
            Y4Job.status == "queued").limit(1)).first() is not None


def claim_next() -> Optional[Dict[str, Any]]:
    """原子领取最早的 queued 任务；已有 running 任务时不领。"""
    with Session(_db.engine) as sess:
        cand = sess.execute(select(Y4Job.id).where(Y4Job.status == "queued")
                            .order_by(Y4Job.id).limit(1)).scalar()
        if cand is None:
            return None
        other = aliased(Y4Job)
        res = sess.execute(
            update(Y4Job)
            .where(Y4Job.id == cand, Y4Job.status == "queued",
                   ~select(other.id).where(other.status == "running").exists())
            .values(status="running", started_at=_now()))
        sess.commit()
        if res.rowcount != 1:
            return None
        return _job_dict(sess.get(Y4Job, cand))


# ---------------------------------------------------------------------------
# data/_job.json 锁（与旧批量流水线互斥）
# ---------------------------------------------------------------------------
def _read_job_file() -> Optional[Dict[str, Any]]:
    try:
        d = json.loads(Path(JOB_FILE).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _write_job_file(data: Dict[str, Any]) -> None:
    try:
        Path(JOB_FILE).parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(JOB_FILE).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(JOB_FILE))
    except OSError:
        pass


def batch_running() -> bool:
    """旧批量流水线是否在跑（不含本 worker 自己写的标记）。"""
    job = _read_job_file() or {}
    if job.get("status") != "running" or job.get("y4_worker"):
        return False
    return (time.time() - (job.get("updated_at") or 0)) < STALE_SECONDS


@contextmanager
def _hold_job_lock(message: str):
    prev = _read_job_file()
    _write_job_file({"status": "running", "y4_worker": True, "message": message,
                     "percent": 1, "updated_at": time.time(),
                     "started_at": time.time()})
    stop = threading.Event()

    def beat() -> None:
        while not stop.wait(60):
            cur = _read_job_file() or {}
            cur["updated_at"] = time.time()
            _write_job_file(cur)

    t = threading.Thread(target=beat, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join(timeout=2)
        if prev and not prev.get("y4_worker"):
            # 还给旧流水线它上次留下的状态（/api/generate/result 仍能取到上次的结果）
            _write_job_file(prev)
        else:
            _write_job_file({"status": "idle", "y4_worker": False,
                             "updated_at": time.time()})


# ---------------------------------------------------------------------------
# worker 进程
# ---------------------------------------------------------------------------
_WORKER_LOCK = DATA_DIR / "_y4worker.lock"
_sleep = time.sleep  # 测试里替换


def _try_lock():
    import fcntl
    _WORKER_LOCK.parent.mkdir(parents=True, exist_ok=True)
    fh = open(_WORKER_LOCK, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def _unlock(fh) -> None:
    import fcntl
    try:
        fcntl.flock(fh, fcntl.LOCK_UN)
    finally:
        fh.close()


def worker_alive() -> bool:
    fh = _try_lock()
    if fh is None:
        return True
    _unlock(fh)
    return False


def spawn_worker() -> bool:
    """没有 worker 在跑就拉起一个（与 genjob 同样的独立会话子进程）。"""
    if worker_alive():
        return False
    import subprocess
    log_path = DATA_DIR / "_y4worker.log"
    try:
        with open(log_path, "a", encoding="utf-8") as log:
            subprocess.Popen(
                [sys.executable, str(BASE_DIR / "app.py"), "y4worker"],
                cwd=str(BASE_DIR), stdout=log, stderr=log,
                stdin=subprocess.DEVNULL, start_new_session=True)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[y4] 拉起 worker 失败: {exc}", flush=True)
        return False


def run_worker(poll_seconds: float = 5.0) -> int:
    """依次执行队列里的任务。批量流水线在跑时等待；队列空了退出。"""
    while True:
        fh = _try_lock()
        if fh is None:
            return 0  # 已有 worker
        try:
            while True:
                fail_stale_jobs()
                if not has_queued():
                    break
                if batch_running():
                    _sleep(poll_seconds)
                    continue
                job = claim_next()
                if job is None:
                    _sleep(poll_seconds)  # 还有 running 任务（别的进程）占着
                    continue
                run_job(job)
        finally:
            _unlock(fh)
        # 释放锁之后再看一眼：入队方发现锁被占就不会拉起新 worker，
        # 这里补上「入队发生在退出之前」的缺口。
        if not has_queued():
            return 0


class ReadError(Exception):
    """有意抛出、可直接给工作人员看的中文提示。"""


MSG_CONFIG = "读取服务暂时不可用，请联系管理员"
MSG_UNEXPECTED = "读取失败，请重试；如果仍然失败，请联系管理员"
_CONFIG_HINTS = ("api key", "api_key", "apikey", "dashscope", "openai", "siliconflow",
                 "unauthorized", "arrearage", "未设置视觉", "invalidapikey",
                 "access denied", "quota")


def friendly_error(exc: BaseException) -> str:
    """工作人员看得到的错误文案：不含异常类名或配置说明；完整信息只进 worker 日志。"""
    if isinstance(exc, ReadError):
        return str(exc)
    low = f"{type(exc).__name__} {exc}".lower()
    if any(h in low for h in _CONFIG_HINTS):
        return MSG_CONFIG
    return MSG_UNEXPECTED


def run_job(job: Dict[str, Any]) -> None:
    label = "Y4 资料读取中" if job["kind"] == "read" else "Y4 报告生成中"
    with _hold_job_lock(label):
        try:
            if job["kind"] == "read":
                _run_read(job)
            else:
                _run_build(job)
        except Exception as exc:  # noqa: BLE001
            print(f"[y4] job {job['id']} ({job['kind']} {job.get('slot')}) 失败:", flush=True)
            traceback.print_exc()
            sys.stdout.flush()
            msg = friendly_error(exc)
            if _fail_job(job["id"], msg, "running"):
                _mark_target_failed(job, msg)


def _finish_job(job_id: int) -> bool:
    """running → done。已被判失败（超时）则返回 False。"""
    with Session(_db.engine) as sess:
        res = sess.execute(update(Y4Job).where(
            Y4Job.id == int(job_id), Y4Job.status == "running"
        ).values(status="done", finished_at=_now(), error=""))
        sess.commit()
        return bool(res.rowcount)


def _still_running(job_id: int) -> bool:
    j = get_job(job_id)
    return bool(j and j["status"] == "running")


# ---------------------------------------------------------------------------
# 读取任务
# ---------------------------------------------------------------------------
def _work_pdf_name(slot: str, file_name: str) -> str:
    if slot == "B6" and ("高中" in file_name or "初中" in file_name):
        return f"report_B6_{'高中' if '高中' in file_name else '初中'}.pdf"
    return f"report_{slot}.pdf"


_EXTRACT_LOCK = threading.Lock()


def extract_slot(pdf: Path, slot: str, workdir: Path, file_name: str = "") -> Dict[str, Any]:
    """只读这一份 PDF，全程在 workdir 里做（视觉读取 + 文本兜底，与批量流程同一套代码）。

    做法：把 extract 模块的 INPUT_DIR/DATA_DIR/PAGES_DIR（以及 B6 价值观条形图读取的
    base_dir）临时指到 workdir，复用 extract.main()；批量流程的行为与输出不变。
    返回 {"values": {编号: 文本}, "student": {...}, "b3_detail": dict|None, "vision": {...}}。
    """
    import _vision_values_bar
    import extract

    in_dir, data_dir, pages_dir = workdir / "input", workdir / "data", workdir / "pages"
    for d in (in_dir, data_dir, pages_dir):
        d.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(pdf), str(in_dir / _work_pdf_name(slot, file_name)))

    with _EXTRACT_LOCK:
        saved = (extract.INPUT_DIR, extract.DATA_DIR, extract.PAGES_DIR)
        saved_bar = _vision_values_bar.main
        extract.INPUT_DIR, extract.DATA_DIR, extract.PAGES_DIR = in_dir, data_dir, pages_dir
        _vision_values_bar.main = lambda: saved_bar(base_dir=workdir)
        try:
            rc = extract.main()
        finally:
            extract.INPUT_DIR, extract.DATA_DIR, extract.PAGES_DIR = saved
            _vision_values_bar.main = saved_bar
    if rc != 0:
        raise RuntimeError(f"读取失败 (extract.main() 返回 {rc})")
    out = data_dir / "report_data.json"
    if not out.exists():
        raise RuntimeError("读取失败：没有产出数据")
    rd = json.loads(out.read_text(encoding="utf-8"))
    mine = set(slot_codes(slot))
    values = {str(it["code"]): ("" if it.get("value") is None else str(it["value"]))
              for it in rd.get("schema_124") or [] if str(it.get("code")) in mine}
    return {"values": values, "student": rd.get("student") or {},
            "b3_detail": rd.get("b3_detail") if slot == "B3" else None,
            "vision": rd.get("vision") or {}}


def _run_read(job: Dict[str, Any]) -> None:
    rnd, slot = job["round_id"], job["slot"]
    rd = get_round(rnd)
    if rd is None:
        raise ReadError(MSG_UNEXPECTED)
    pdf = original_path(rnd, slot)
    if not pdf.exists():
        raise ReadError("找不到已上传的原文件，请重新上传")
    file_name = rd["state"]["slots"][slot].get("file_name") or ""
    stu = _db.get_student(rd["student_id"]) or {}
    student_name = stu.get("name") or ""
    _set_slot(rnd, slot, state="reading", error="")

    workdir = DATA_DIR / "_y4_work" / f"job{job['id']}"
    try:
        result = extract_slot(pdf, slot, workdir, file_name)
    finally:
        shutil.rmtree(str(workdir), ignore_errors=True)

    if not any(str(v).strip() for v in (result.get("values") or {}).values()):
        raise ReadError("没有从这份资料里读到任何数据，请确认上传的是正确的报告")
    if not _still_running(job["id"]):
        return  # 已被判超时失败，丢弃结果
    report_id = merge_read(rnd, slot, result, student_name=student_name,
                           file_name=file_name)
    _finish_job(job["id"])
    _recognize_questionnaires(report_id)
    _six_am(report_id)


def _recognize_questionnaires(report_id: int) -> None:
    """与 reports._save_report_to_db 同样的问卷识别钩子（非致命）。"""
    try:
        import questionnaire_store as _qstore
        print(f"[问卷] 识别结果: {_qstore.recognize_for_report(report_id)}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[问卷] 识别失败 (非致命): {exc}", flush=True)


def _six_am(report_id: int) -> None:
    try:
        from blueprints.reports import _run_six_am_hook
        _run_six_am_hook(report_id)
    except Exception as exc:  # noqa: BLE001
        print(f"[6AM] 更新失败 (非致命): {exc}", flush=True)


# ---------------------------------------------------------------------------
# 生成任务（只用库里已存的值，不调 AI）
# ---------------------------------------------------------------------------
def build_snapshot(raw: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    """出报告用的快照：null 一律当「未上传」（空串），pdf_titles 只含已有数据的槽位，
    v2 据此整页不出未上传槽位的页。"""
    snap = copy.deepcopy(raw)
    for it in snap.get("schema_124") or []:
        if isinstance(it, dict) and it.get("value") is None:
            it["value"] = ""
    snap["pdf_titles"] = [s for s in SLOTS if state["slots"][s].get("has_data")]
    return snap


def _render_pdfs(snapshot: Dict[str, Any]) -> Tuple[Optional[Path], Optional[Path]]:
    """与 /api/reports/<id>/regenerate 同一路径：写 data/report_data.json →
    apply_report_data → generate.main()。返回 (v1, v2) 的 output/ 路径。
    调用方已持有 _job.json 锁，所以不会和批量流水线抢这些共享文件。"""
    import generate as _gen
    from data_points import apply_report_data
    (BASE_DIR / "data").mkdir(exist_ok=True)
    (BASE_DIR / "data" / "report_data.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    apply_report_data()
    try:
        _gen.main()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise RuntimeError(f"生成 PDF 失败: SystemExit({exc.code})")
    name = ((snapshot.get("student") or {}).get("name") or "").strip()
    safe = name.replace("/", "_").replace("\\", "_").replace(" ", "")
    v1 = OUTPUT_DIR / f"凭远Y4评测报告_{safe}.pdf"
    v2 = OUTPUT_DIR / f"凭远Y4评测报告_v2_{safe}.pdf"
    return (v1 if v1.exists() else None), (v2 if v2.exists() else None)


def _run_build(job: Dict[str, Any]) -> None:
    rnd = job["round_id"]
    rd = get_round(rnd)
    if rd is None or rd["report_id"] is None or not any(
            s.get("has_data") for s in rd["state"]["slots"].values()):
        raise ReadError("还没有读取过任何资料，不能生成报告")
    rid = rd["report_id"]
    raw = load_raw(rid)
    if raw is None:
        raise ReadError(MSG_UNEXPECTED)
    _set_build(rnd, state="running", error="")
    snap = build_snapshot(raw, rd["state"])
    v1, v2 = _render_pdfs(snap)
    if v2 is None:
        raise ReadError("新版报告生成失败，请重试；如果仍然失败，请联系管理员")
    dest = builds_dir(rid)
    dest.mkdir(parents=True, exist_ok=True)
    out2 = dest / v2.name
    shutil.copyfile(str(v2), str(out2))
    out1 = ""
    if v1 is not None:
        shutil.copyfile(str(v1), str(dest / v1.name))
        out1 = _rel(dest / v1.name)
    if not _still_running(job["id"]):
        return
    with _edit_raw(rid) as (_raw2, report):
        report.pdf_path = _rel(out2)
    _set_build(rnd, state="done", job_id=job["id"], built_at=_iso(), error="",
               v2_path=_rel(out2), v1_path=out1)
    _finish_job(job["id"])


# ---------------------------------------------------------------------------
# 对外：状态
# ---------------------------------------------------------------------------
def status_payload(student: Dict[str, Any]) -> Dict[str, Any]:
    fail_stale_jobs()
    rd = current_round(student["id"], persist=False)
    rnd, rid, state = rd["id"], rd["report_id"], rd["state"]
    raw = load_raw(rid) if rid else None
    pend = [j for j in pending_jobs()]
    pos = {j["id"]: i for i, j in enumerate(pend, 1)}
    by_slot: Dict[str, Dict[str, Any]] = {}
    build_job: Optional[Dict[str, Any]] = None
    for j in pend:
        if rnd is None or j["round_id"] != rnd:
            continue
        if j["kind"] == "read":
            by_slot[j["slot"]] = j
        else:
            build_job = j
    failed_ids = last_failed_read_jobs(rnd) if rnd else {}
    slots: Dict[str, Any] = {}
    for s in SLOTS:
        st = dict(state["slots"][s])
        j = by_slot.get(s)
        st["job_id"] = j["id"] if j else (
            failed_ids.get(s) if st.get("state") == "failed" else None)
        st["position"] = pos[j["id"]] if j else 0
        if j:  # 以队列为准：任务在跑/排队，状态就是 reading/queued
            st["state"] = "reading" if j["status"] == "running" else "queued"
        st.pop("file_path", None)
        st["has_file"] = bool(rnd) and original_path(rnd, s).exists()
        slots[s] = st
    b = state.get("build") or {}
    pdf = ""
    if rid:
        with Session(_db.engine) as sess:
            rep = sess.get(_db.Report, rid)
            pdf = (rep.pdf_path or "").strip() if rep else ""
    ready = bool(pdf) and _abs(pdf).exists()
    built_at = b.get("built_at") or ""
    reads = [slots[s]["read_at"] for s in SLOTS if slots[s].get("read_at")]
    bstate = b.get("state") or "none"
    if build_job:
        bstate = "running" if build_job["status"] == "running" else "queued"
    started = rd.get("started_at")
    return {
        "round_id": rnd,
        "report_id": rid if (raw is not None and any(
            s.get("has_data") for s in state["slots"].values())) else None,
        "round_started_at": (started.isoformat(timespec="seconds") + "Z"
                             if started else (raw or {}).get("round_started_at") or ""),
        "slots": slots,
        "build": {"state": bstate, "job_id": build_job["id"] if build_job else None,
                  "position": pos[build_job["id"]] if build_job else 0,
                  "pdf_ready": ready, "built_at": built_at,
                  "stale": bool(ready and built_at and any(r > built_at for r in reads)),
                  "error": b.get("error") or ""},
        "edited_codes_by_slot": edited_codes_by_slot(raw or {}),
    }


# ---------------------------------------------------------------------------
# 对外：入队
# ---------------------------------------------------------------------------
class Conflict(Exception):
    pass


def start_read(student: Dict[str, Any], slot: str, source_parts: List[Path],
               file_name: str, created_by: str) -> Tuple[int, int]:
    """保存上传的原文件，登记 slot 状态并入队。返回 (job_id, position)。
    这里不建 reports 行；第一次读取成功才建。"""
    rd = current_round(student["id"], created_by, persist=True)
    rnd = rd["id"]
    for j in pending_jobs():
        if j["round_id"] == rnd and j["kind"] == "read" and j["slot"] == slot:
            raise Conflict("这份资料正在排队或读取中，请等它完成后再上传")
    dest = original_path(rnd, slot)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".uploading")
    with open(tmp, "wb") as out:
        for part in source_parts:
            with open(part, "rb") as fh:
                shutil.copyfileobj(fh, out, 1024 * 1024)
    with open(tmp, "rb") as fh:
        head = fh.read(5)
    if head != b"%PDF-":
        tmp.unlink()
        raise ValueError("上传的文件不是 PDF")
    os.replace(str(tmp), str(dest))
    _set_slot(rnd, slot, state="queued", error="", file_name=file_name or f"{slot}.pdf",
              file_path=_rel(dest))
    job_id = enqueue(rnd, rd["report_id"], student["id"], "read", slot, created_by)
    spawn_worker()
    return job_id, queue_position(job_id)


def retry_read(job_id: int, student: Dict[str, Any], created_by: str) -> Tuple[int, int]:
    j = get_job(job_id)
    if not j or j["student_id"] != student["id"] or j["kind"] != "read":
        raise LookupError("任务不存在")
    if j["status"] != "failed":
        raise Conflict("只有读取失败的任务可以重试")
    rnd, slot = j["round_id"], j["slot"]
    for p in pending_jobs():
        if p["round_id"] == rnd and p["kind"] == "read" and p["slot"] == slot:
            raise Conflict("这份资料正在排队或读取中")
    if not original_path(rnd, slot).exists():
        raise FileNotFoundError("找不到已上传的原文件，请重新上传")
    rd = get_round(rnd)
    _set_slot(rnd, slot, state="queued", error="")
    new_id = enqueue(rnd, rd["report_id"], student["id"], "read", slot, created_by)
    spawn_worker()
    return new_id, queue_position(new_id)


def start_build(student: Dict[str, Any], created_by: str) -> Tuple[int, int]:
    rd = current_round(student["id"], created_by, persist=False)
    if rd["report_id"] is None or not any(
            s.get("has_data") for s in rd["state"]["slots"].values()):
        raise ValueError("还没有读取过任何资料，不能生成报告")
    if rd["id"] is None:
        rd = current_round(student["id"], created_by, persist=True)
    rnd = rd["id"]
    for j in pending_jobs():
        if j["round_id"] == rnd and j["kind"] == "build":
            return j["id"], queue_position(j["id"])
    _set_build(rnd, state="queued", error="")
    job_id = enqueue(rnd, rd["report_id"], student["id"], "build", None, created_by)
    spawn_worker()
    return job_id, queue_position(job_id)


def new_round(student: Dict[str, Any], created_by: str = "") -> int:
    """新一轮测评：只建一个空轮次，不建 reports 行（旧报告仍是学生的最新报告，
    直到新一轮第一次读取成功）。"""
    return create_round(student["id"], created_by)
