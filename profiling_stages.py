"""Profiling 阶段模型（C2：Stage 4 后端第 1 部分）。

学生档案 / 学生详情 / 工作台 / Profiling 流程共用的唯一阶段规则（负责人 2026-11-03 裁定）。
新代码，与 ``pipeline.py`` 并存，不改动任何现有页面；第 2 部分再切换旧页面。

阶段顺序与规则
--------------
预约（未取消的预约，或已有 Y4 报告）→ Y4 报告 → 解读会 → 补充问卷（可选）→ First Touch（可选）→ 6AM（必需，最后一步）。

- 下一步 = 按顺序第一个**必需**且未完成的阶段；必需阶段全部完成 = 已完成（无下一步）。
- 可选阶段只报告自己的状态（done / todo / not_used），不成为下一步，也不阻塞「已完成」。
- 没有「逾期」概念：模型里不放逾期标记、阈值或天数；只保留各阶段完成时间 ``at``。

本模块的分层
------------
1. ``build_progress(facts)``：纯函数，facts dict → 进度对象。
2. ``load_facts(student_ids)``：批量取数（按学生集合分块查询，不是每人每阶段一次查询）。
3. ``search_matches`` / ``list_students``：学生档案列表（过滤、计数、分页、拼音搜索）。
"""
from __future__ import annotations

import functools
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func, select

import db as _db
import growth_talk_store as _gt
import questionnaire_store as _qs

# ---------------------------------------------------------------------------
# 6AM「完成」的定义——负责人 2026-11-03 裁定「6AM finishes = 导师已评议」，默认 "reviewed"；
# 保留另一种取值，由这个常量决定：
#   "reviewed" ：该最新档案的每个 6AM 维度，最新一条评议的结论都是 agree 或 adjust（默认）；
#                evidence（证据不足，需追问）不算已评议（S4-C4，负责人 2026-11-04）
#   "profile"  ：最新报告已有 6AM 档案（报告后自动生成，界面叫「已更新」）
# ---------------------------------------------------------------------------
SIX_AM_DONE = "reviewed"

REVIEWED_VERDICTS = ("agree", "adjust")

# key, label, required —— 标签沿用 LATER-STAGES.md 的追踪器标签
STAGE_DEFS = (
    ("booking", "预约", True),
    ("y4_report", "Y4 报告", True),
    ("interpretation", "解读会", True),
    ("questionnaires", "补充问卷", False),
    ("first_touch", "First Touch", False),
    ("six_am", "6AM", True),
)
STAGE_KEYS = tuple(k for k, _l, _r in STAGE_DEFS)
DONE_LABEL = "已完成"

_CHUNK = 500  # IN (...) 分块大小，低于 SQLite 变量上限


# ---------------------------------------------------------------------------
# 1. 纯规则函数
# ---------------------------------------------------------------------------
def _iso(value) -> Optional[str]:
    if value is None or value == "":
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _parse_dt(value) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return datetime(value.year, value.month, value.day)
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _six_am_done(facts: dict):
    """按 SIX_AM_DONE 判断 6AM 是否完成，返回 (done, at)。"""
    if SIX_AM_DONE == "reviewed":
        return bool(facts.get("six_am_reviewed")), facts.get("six_am_reviewed_at")
    return bool(facts.get("six_am_profile")), facts.get("six_am_profile_at")


def build_progress(facts: dict) -> dict:
    """facts → ``{"stages": [...], "next": {...}|None, "done": bool, "label": str}``。

    facts 键（缺省视为「没有」）：
    ``has_booking`` / ``booking_at``；``has_report`` / ``report_at``；
    ``minutes_at``；``q_assigned``（数量）/ ``q_all_submitted`` / ``q_at``；
    ``ft_started`` / ``ft_confirmed`` / ``ft_at``；
    ``six_am_profile`` / ``six_am_profile_at`` / ``six_am_reviewed`` / ``six_am_reviewed_at``。
    """
    six_done, six_at = _six_am_done(facts)
    q_assigned = int(facts.get("q_assigned") or 0)
    ft_done = bool(facts.get("ft_confirmed"))

    raw = {
        # D6（负责人 2026-11-04）：有 Y4 报告即视为 Profiling 已开始，预约算完成。
        "booking": ((True, facts.get("booking_at")) if facts.get("has_booking")
                    else (bool(facts.get("has_report")), facts.get("report_at"))),
        "y4_report": (bool(facts.get("has_report")), facts.get("report_at")),
        "interpretation": (facts.get("minutes_at") is not None, facts.get("minutes_at")),
        "questionnaires": (q_assigned > 0 and bool(facts.get("q_all_submitted")),
                           facts.get("q_at")),
        "first_touch": (ft_done, facts.get("ft_at")),
        "six_am": (bool(six_done), six_at),
    }

    stages: List[Dict[str, Any]] = []
    next_step = None
    for key, label, required in STAGE_DEFS:
        done, at = raw[key]
        if done:
            state = "done"
        elif not required and key == "questionnaires" and q_assigned == 0:
            state = "not_used"
        elif not required and key == "first_touch" and not facts.get("ft_started"):
            state = "not_used"
        else:
            state = "todo"
        stages.append({"key": key, "label": label, "required": required,
                       "state": state, "at": _iso(at) if done else None})
        if required and not done and next_step is None:
            next_step = {"key": key, "label": label}

    all_done = next_step is None
    return {
        "stages": stages,
        "next": next_step,
        "done": all_done,
        "label": DONE_LABEL if all_done else next_step["label"],
    }


def updated_at_of(progress: dict, created_at) -> Optional[str]:
    """各阶段完成时间中最晚的一个；没有则取学生创建时间。"""
    times = [t for t in (_parse_dt(s.get("at")) for s in progress["stages"]) if t]
    if times:
        return max(times).isoformat()
    return _iso(created_at)


# ---------------------------------------------------------------------------
# 2. 事实取数（批量）
# ---------------------------------------------------------------------------
def _chunks(ids: List[int]):
    for i in range(0, len(ids), _CHUNK):
        yield ids[i:i + _CHUNK]


def six_am_dimension_ids() -> List[str]:
    """6AM 维度 id 列表：来自 ``six_am/model_v06.json`` 的 ``dims``（现为 A1–A5）。

    与 ``evaluator_v06`` 生成档案时遍历的列表相同（``for dim_spec in model["dims"]``）。
    """
    from six_am import model as _model
    return [str(d.get("id")) for d in (_model.load_model().get("dims") or []) if d.get("id")]


def load_facts(student_ids: Iterable[int]) -> Dict[int, dict]:
    """批量取 facts：``{student_id: facts}``。查询数与学生数无关（按块 IN）。"""
    ids = sorted({int(i) for i in student_ids})
    facts: Dict[int, dict] = {i: {} for i in ids}
    if not ids:
        return facts

    dim_ids = six_am_dimension_ids() if SIX_AM_DONE == "reviewed" else []

    with _db.Session(_db.engine) as sess:
        for part in _chunks(ids):
            # 预约：非 cancelled 的预约（bookings.student_id / status / created_at）
            for sid, at in sess.execute(
                    select(_db.Booking.student_id, func.max(_db.Booking.created_at))
                    .where(_db.Booking.student_id.in_(part),
                           _db.Booking.status != "cancelled")
                    .group_by(_db.Booking.student_id)).all():
                facts[sid].update(has_booking=True, booking_at=at)

            # 最新 Y4 报告（reports：report_date 降序、id 降序，与 compute_stages 一致）
            latest_report: Dict[int, tuple] = {}
            for sid, rid, created in sess.execute(
                    select(_db.Report.student_id, _db.Report.id, _db.Report.created_at)
                    .where(_db.Report.student_id.in_(part))
                    .order_by(_db.Report.student_id.asc(), _db.Report.report_date.desc(),
                              _db.Report.id.desc())).all():
                latest_report.setdefault(sid, (rid, created))
            report_owner = {rid: sid for sid, (rid, _c) in latest_report.items()}
            for sid, (rid, created) in latest_report.items():
                facts[sid].update(has_report=True, report_at=created, _report_id=rid)

            if report_owner:
                # 解读会：meeting_minutes.report_id = 最新报告，取最晚 created_at
                for rid, at in sess.execute(
                        select(_db.MeetingMinutes.report_id,
                               func.max(_db.MeetingMinutes.created_at))
                        .where(_db.MeetingMinutes.report_id.in_(list(report_owner)))
                        .group_by(_db.MeetingMinutes.report_id)).all():
                    facts[report_owner[rid]]["minutes_at"] = at

                # 6AM 档案：最新报告的最新版本（version 最大，并列 id 最大）
                best: Dict[int, tuple] = {}
                for pid, rid, version, created in sess.execute(
                        select(_db.SixAmProfile.id, _db.SixAmProfile.report_id,
                               _db.SixAmProfile.version, _db.SixAmProfile.created_at)
                        .where(_db.SixAmProfile.report_id.in_(list(report_owner)))
                        .order_by(_db.SixAmProfile.report_id.asc(),
                                  _db.SixAmProfile.version.desc(),
                                  _db.SixAmProfile.id.desc())).all():
                    best.setdefault(rid, (pid, created))
                profile_owner = {}
                for rid, (pid, created) in best.items():
                    sid = report_owner[rid]
                    facts[sid].update(six_am_profile=True, six_am_profile_at=created)
                    profile_owner[pid] = sid

                if SIX_AM_DONE == "reviewed" and profile_owner:
                    # 评议：每维度取最新一条（id 降序）；结论为 agree/adjust 才算
                    latest_rev: Dict[tuple, tuple] = {}
                    for pid, dim, verdict, created in sess.execute(
                            select(_db.SixAmReview.profile_id, _db.SixAmReview.dim,
                                   _db.SixAmReview.verdict, _db.SixAmReview.created_at)
                            .where(_db.SixAmReview.profile_id.in_(list(profile_owner)))
                            .order_by(_db.SixAmReview.id.desc())).all():
                        latest_rev.setdefault((pid, dim), (verdict, created))
                    for pid, sid in profile_owner.items():
                        got = [latest_rev.get((pid, d)) for d in dim_ids]
                        if dim_ids and all(g and (g[0] or "").strip() in REVIEWED_VERDICTS
                                           for g in got):
                            facts[sid].update(
                                six_am_reviewed=True,
                                six_am_reviewed_at=max(g[1] for g in got if g[1]) if any(
                                    g[1] for g in got) else None)

            # 补充问卷：assignments（rejected 视为未分配；同一问卷任一 submitted 即完成）
            per_q: Dict[int, Dict[int, dict]] = {}
            for sid, qid, status, submitted in sess.execute(
                    select(_qs.Assignment.student_id, _qs.Assignment.questionnaire_id,
                           _qs.Assignment.status, _qs.Assignment.submitted_at)
                    .where(_qs.Assignment.student_id.in_(part),
                           _qs.Assignment.status != "rejected")).all():
                slot = per_q.setdefault(sid, {}).setdefault(
                    qid, {"submitted": False, "at": None})
                if status == "submitted":
                    slot["submitted"] = True
                    if submitted and (slot["at"] is None or submitted > slot["at"]):
                        slot["at"] = submitted
            for sid, qs_ in per_q.items():
                done_all = all(v["submitted"] for v in qs_.values())
                ats = [v["at"] for v in qs_.values() if v["at"]]
                facts[sid].update(q_assigned=len(qs_), q_all_submitted=done_all,
                                  q_at=max(ats) if ats else None)

            # First Touch：已确认报告 = gt_reports.status == "CONFIRMED"
            for sid, at in sess.execute(
                    select(_gt.GtReport.student_id, func.max(_gt.GtReport.confirmed_at))
                    .where(_gt.GtReport.student_id.in_(part),
                           _gt.GtReport.status == "CONFIRMED")
                    .group_by(_gt.GtReport.student_id)).all():
                facts[sid].update(ft_confirmed=True, ft_started=True, ft_at=at)
            # 已开始：有未归档的 copilot 会话，或有 First Touch 来源材料
            for (sid,) in sess.execute(
                    select(_gt.CopilotSession.student_id)
                    .where(_gt.CopilotSession.student_id.in_(part),
                           _gt.CopilotSession.status != "ARCHIVED").distinct()).all():
                facts[sid]["ft_started"] = True
            for (sid,) in sess.execute(
                    select(_gt.GtSource.student_id)
                    .where(_gt.GtSource.student_id.in_(part)).distinct()).all():
                facts[sid]["ft_started"] = True

    for f in facts.values():
        f.pop("_report_id", None)
    return facts


def progress_for_students(student_ids: Iterable[int]) -> Dict[int, dict]:
    return {sid: build_progress(f) for sid, f in load_facts(student_ids).items()}


def progress_for_student(student_id: int) -> dict:
    return progress_for_students([student_id])[int(student_id)]


# ---------------------------------------------------------------------------
# 3. 搜索（中文子串 / 全拼无声调 / 拼音首字母）
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=8192)
def _pinyin_forms(text: str):
    """返回 (全拼无声调拼接, 首字母拼接)，均小写；非汉字原样保留。"""
    from pypinyin import Style, lazy_pinyin
    parts = [p.replace(" ", "") for p in lazy_pinyin(text or "", style=Style.NORMAL)]
    full = "".join(parts).lower()
    initials = "".join(p[0] for p in parts if p).lower()
    return full, initials


def search_matches(q: str, student: dict) -> bool:
    """student: ``code, name, school, advisor_name``。大小写不敏感。"""
    needle = (q or "").strip().lower()
    if not needle:
        return True
    compact = needle.replace(" ", "")
    for field in ("code", "name", "school", "advisor_name"):
        value = (student.get(field) or "")
        if needle in value.lower():
            return True
    for field in ("name", "school", "advisor_name"):
        full, initials = _pinyin_forms(student.get(field) or "")
        if compact and (compact in full or compact in initials):
            return True
    return False


# ---------------------------------------------------------------------------
# 4. 学生档案列表
# ---------------------------------------------------------------------------
def _stage_bucket(progress: dict) -> str:
    return "done" if progress["done"] else progress["next"]["key"]


def list_students(visible_stmt, *, q: str = "", stage: str = "", advisor: str = "",
                  page: int = 1, per_page: int = 50, sort: str = "updated") -> dict:
    """``visible_stmt``：已按账号可见范围过滤的 ``select(Student.id, ...)``。

    计数在 q 与 advisor 之后、stage 之前计算。返回 API 响应体（不含 ok）。
    """
    with _db.Session(_db.engine) as sess:
        rows = sess.execute(visible_stmt).all()
    students = [{"id": r.id, "code": r.student_code or "", "name": r.name or "",
                 "school": r.school or "", "advisor_name": r.advisor_name or "",
                 "created_at": r.created_at} for r in rows]

    if advisor:
        students = [s for s in students if s["advisor_name"] == advisor]
    if q and q.strip():
        students = [s for s in students if search_matches(q, s)]

    prog = progress_for_students(s["id"] for s in students)
    counts = {k: 0 for k in STAGE_KEYS}
    counts["done"] = 0
    for s in students:
        counts[_stage_bucket(prog[s["id"]])] += 1

    if stage:
        students = [s for s in students if _stage_bucket(prog[s["id"]]) == stage]

    for s in students:
        s["progress"] = prog[s["id"]]
        s["updated_at"] = updated_at_of(s["progress"], s["created_at"])

    if sort == "name":
        students.sort(key=lambda s: (_pinyin_forms(s["name"])[0], s["name"], s["id"]))
    else:
        students.sort(key=lambda s: (_parse_dt(s["updated_at"]) or datetime.min, s["id"]),
                      reverse=True)

    total = len(students)
    start = (page - 1) * per_page
    out = [{"code": s["code"], "name": s["name"], "school": s["school"],
            "advisor_name": s["advisor_name"], "progress": s["progress"],
            "updated_at": s["updated_at"]}
           for s in students[start:start + per_page]]
    return {"total": total, "page": page, "per_page": per_page,
            "counts": counts, "rows": out}
