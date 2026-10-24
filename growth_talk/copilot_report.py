"""Copilot 2.0 报告流：会谈 session 物化为第一阶段 run 与报告预览/确认。

移植自 first-touch ``lib/copilot-report.ts`` / ``copilot-report-shared.ts``。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

import db as _db
import growth_talk_store as store
from growth_talk_store import (
    CopilotPhaseEvent,
    CopilotSession,
    GtInterest,
    GtQuadrant,
    GtReport,
    GtRun,
    GtSuggestion,
    GtUnderstanding,
    NotFoundError,
    RevisionConflict,
)

from . import analysis, report_contract
from .copilot import _sync_project_suggestions, recommendations_current
from .errors import ActionError

EVIDENCE_FALLBACK = "顾问会议评分，待核对证据。"


# ---------------------------------------------------------------------------
# 读取辅助
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.utcnow()


def _iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _student(student_id: int) -> dict:
    with Session(store.engine()) as sess:
        row = sess.get(_db.Student, student_id)
        if not row:
            raise NotFoundError("学生不存在")
        return {
            "id": row.id, "student_code": row.student_code,
            "name": row.name, "grade": row.grade,
            "school": getattr(row, "school", None),
        }


def _advisor_name(advisor_id) -> str:
    with Session(store.engine()) as sess:
        row = sess.get(_db.User, advisor_id)
        if not row:
            return ""
        return (getattr(row, "display_name", None)
                or getattr(row, "advisor_name", None)
                or getattr(row, "username", None) or "")


def _session_or_404(session_id: int) -> dict:
    session = store.get_session(session_id)
    if not session:
        raise NotFoundError("会谈不存在")
    return session


def _latest_meeting_source(student_id: int) -> dict | None:
    sources = store.list_sources(
        student_id, type="GROWTH_TALK", purpose="MEETING")
    return sources[0] if sources else None


def _confirmed_report(run_id, student_id: int | None = None) -> dict | None:
    if not run_id:
        return None
    with Session(store.engine()) as sess:
        stmt = select(GtReport).where(
            GtReport.run_id == run_id, GtReport.status == "CONFIRMED")
        if student_id is not None:
            stmt = stmt.where(GtReport.student_id == student_id)
        row = sess.execute(stmt.order_by(GtReport.id.desc())).scalars().first()
        return store._report_dict(row) if row else None


def _report_result(row: dict) -> dict:
    return {
        "id": row["id"],
        "version": row["version"],
        "confirmedAt": row.get("confirmed_at"),
        "confirmedBy": row.get("confirmed_by"),
    }


# ---------------------------------------------------------------------------
# Draft 与缺失字段
# ---------------------------------------------------------------------------
def _materialized_evidence(item: dict) -> str:
    evidence = item.get("evidence")
    note = item.get("note")
    parts = []
    if isinstance(evidence, str) and evidence.strip():
        parts.append(evidence.strip())
    if isinstance(note, str) and note.strip():
        parts.append(f"顾问 Note：{note.strip()}")
    return "；".join(parts) or EVIDENCE_FALLBACK


def missing_report_fields(draft: dict) -> list[dict]:
    missing: list[dict] = []
    student = draft.get("student") or {}
    if not str(student.get("grade") or "").strip():
        missing.append({
            "key": "grade",
            "label": "年级：未填写，请在学生资料中补充",
            "required": True,
        })
    if not draft.get("meetingSourceId"):
        missing.append({
            "key": "meeting",
            "label": "会议文字稿：未上传",
            "required": True,
        })

    interests = draft.get("interests") or []
    if not interests:
        missing.append({
            "key": "interests",
            "label": "兴趣事项：尚未确认",
            "required": True,
        })
    for item in interests:
        fields = []
        if item.get("preferenceScore") is None:
            fields.append("喜欢程度")
        if item.get("competenceScore") is None:
            fields.append("擅长程度")
        if fields:
            missing.append({
                "key": item.get("id"),
                "label": f"{item.get('label')}：{'、'.join(fields)}未填写",
                "required": True,
            })

    projects = draft.get("projects") or []
    if draft.get("projectsStale"):
        missing.append({
            "key": "projects-stale",
            "label": "项目推荐已过期：旧清单不收录报告，可返回上一阶段重新生成并审核",
            "required": (draft.get("approvedProjectCount") or 0) > 0,
        })
    elif not projects:
        missing.append({
            "key": "projects",
            "label": "项目推荐：尚未选择并保存“推荐给学生”的方案，本次报告不收录项目",
            "required": False,
        })

    if not draft.get("calibration"):
        missing.append({
            "key": "y4",
            "label": "Y4 分析：未填写，本次草稿暂不展示 Y4 画像",
            "required": False,
        })
    if not (draft.get("y4Validation") or []):
        missing.append({
            "key": "y4-validation",
            "label": "会议对 Y4 的验证：未填写",
            "required": False,
        })

    if interests and not any(
        not analysis.is_excluded_interest_topic(item.get("label"), None)
        for item in interests
    ):
        missing.append({
            "key": "eligible-interests",
            "label": "兴趣事项：尚无可参与兴趣分型的活动或兴趣，请返回核对",
            "required": True,
        })
    return missing


def report_draft(session: dict, student: dict | None = None) -> dict:
    student = student or _student(session["student_id"])
    interests = [
        dict(item) for item in (session.get("interests") or [])
        if isinstance(item, dict)
    ]
    supplements = session.get("supplements") or []
    supplement = supplements[0] if supplements else None
    analysis_data = (supplement or {}).get("analysis") or {}
    if not isinstance(analysis_data, dict):
        analysis_data = {}

    source_id = session.get("meeting_source_id")
    batch = analysis_data.get("projectRecommendations")
    batch_items = (
        batch.get("items") if isinstance(batch, dict) else []
    )
    batch_items = [
        item for item in (batch_items or []) if isinstance(item, dict)
    ]
    projects_stale = bool(batch) and not recommendations_current(
        source_id, interests, analysis_data)
    projects = [] if projects_stale else [
        item for item in batch_items if item.get("status") == "student_review"
    ]
    approved_count = sum(
        1 for item in batch_items if item.get("status") == "student_review")

    y4_validation = [
        value for value in (analysis_data.get("y4Validation") or [])
        if isinstance(value, str)
    ]
    topics = [
        item for item in interests
        if not analysis.is_excluded_interest_topic(item.get("label"), None)
    ]
    labels = "、".join(
        "".join(list(str(item.get("label") or ""))[:24])
        for item in topics[:2] if item.get("label")
    )
    summary = (
        f"会谈记录的兴趣包括{labels}。"
        "相关会议证据和顾问评分用于理解目前的兴趣与经历。"
    ) if labels else ""
    meeting_summary = analysis.meeting_summary_with_overview(
        summary, student["name"], topics)

    calibration = session.get("calibration")
    has_y4 = isinstance(calibration, dict) and any(
        str(calibration.get(key) or "").strip()
        for key in ("careerInterests", "abilityTendencies", "valuePreferences")
    )
    draft = {
        "student": {
            "name": student["name"],
            "grade": student.get("grade"),
            "school": student.get("school"),
        },
        "meetingAt": session.get("meeting_at") or session.get("created_at"),
        "meetingSourceId": source_id,
        "meetingSummary": meeting_summary,
        "interests": interests,
        "y4Validation": y4_validation,
        "calibration": calibration if has_y4 else None,
        "projects": projects,
        "projectsStale": projects_stale,
        "approvedProjectCount": approved_count,
    }
    draft["missing"] = missing_report_fields(draft)
    return draft


def report_input_fingerprint(session: dict, student: dict | None = None,
                             draft: dict | None = None) -> str:
    student = student or _student(session["student_id"])
    draft = draft or report_draft(session, student)
    payload = {
        "sourceId": session.get("meeting_source_id"),
        "student": {"name": student["name"], "grade": student.get("grade")},
        "interests": draft["interests"],
        "summary": draft["meetingSummary"],
    }
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _assert_report_ready(session: dict, student: dict) -> dict:
    draft = report_draft(session, student)
    required = [item for item in draft["missing"] if item.get("required")]
    if required:
        labels = "；".join(str(item["label"]) for item in required)
        raise ActionError(409, f"请先补充报告内容：{labels}")
    return draft


def _run_matches(run: dict | None, source_id, draft: dict) -> bool:
    if not run or run.get("source_id") != source_id:
        return False
    understanding = run.get("understanding") or {}
    if understanding.get("summary") != draft["meetingSummary"]:
        return False
    rows = run.get("interests") or []
    interests = draft["interests"]
    if len(rows) != len(interests):
        return False
    for item in interests:
        evidence = _materialized_evidence(item)
        if not any(
            row.get("label") == item.get("label")
            and row.get("status") == "CONFIRMED"
            and row.get("preference_score") == item.get("preferenceScore")
            and row.get("competence_score") == item.get("competenceScore")
            and row.get("evidence") == evidence
            for row in rows
        ):
            return False
    return True


# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------
def handoff_report(session_id: int, expected_revision: int | None = None) -> dict:
    """物化第一阶段 run；给定 ``expected_revision`` 时在同一事务内 CAS。"""
    session = _session_or_404(session_id)
    student = _student(session["student_id"])
    draft = _assert_report_ready(session, student)

    source = _latest_meeting_source(student["id"])
    if not source or source["id"] != session.get("meeting_source_id"):
        raise ActionError(
            409, "会议文字稿已变化，请返回上一阶段核对当前资料")

    fingerprint = report_input_fingerprint(session, student, draft)
    script = session.get("script") or {}
    existing_run_id = session.get("run_id")
    if existing_run_id and script.get("reportInputFingerprint") == fingerprint:
        if _run_matches(store.get_run_full(existing_run_id), source["id"], draft):
            return {"runId": existing_run_id, "revision": session["revision"]}

    actor_name = _advisor_name(session["advisor_id"])
    with Session(store.engine()) as sess:
        current = sess.get(CopilotSession, session_id)
        if not current:
            raise NotFoundError("会谈不存在")
        if current.meeting_source_id != source["id"]:
            raise ActionError(409, "会谈资料已变化，请刷新")

        run = sess.get(GtRun, current.run_id) if current.run_id else None
        if run and sess.execute(select(GtReport).where(
                GtReport.run_id == run.id,
                GtReport.status == "CONFIRMED")).scalar_one_or_none():
            raise ActionError(409, "报告已确认，请查看已确认版本")

        if run is None:
            version = (sess.execute(
                select(func.max(GtRun.version))
                .where(GtRun.student_id == student["id"])
            ).scalar() or 0) + 1
            run = GtRun(
                student_id=student["id"], source_id=source["id"],
                version=version, revision=1, status="PENDING_REVIEW",
                model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            )
            sess.add(run)
            sess.flush()
        else:
            run.source_id = source["id"]
            run.revision += 1
            run.status = "PENDING_REVIEW"
            run.error = None
            run.updated_at = _now()
            sess.execute(delete(GtQuadrant).where(GtQuadrant.run_id == run.id))
            for row in sess.execute(select(GtSuggestion).where(
                    GtSuggestion.run_id == run.id)).scalars():
                row.status = "STALE"
                row.updated_at = _now()

        topics = json.dumps([{
            "label": item.get("label"),
            "topicType": item.get("topicType") or "interest",
            "evidence": item.get("evidence") or "",
        } for item in draft["interests"]], ensure_ascii=False)
        understanding = sess.execute(select(GtUnderstanding).where(
            GtUnderstanding.run_id == run.id)).scalar_one_or_none()
        if understanding:
            understanding.summary = draft["meetingSummary"]
            understanding.topics = topics
            understanding.status = "CONFIRMED"
            understanding.model = run.model
            understanding.updated_at = _now()
        else:
            sess.add(GtUnderstanding(
                run_id=run.id, summary=draft["meetingSummary"],
                topics=topics, keywords="[]", model=run.model,
                status="CONFIRMED",
            ))

        previous = list(sess.execute(
            select(GtInterest).where(GtInterest.run_id == run.id)
        ).scalars())
        by_label = {row.label.strip(): row for row in previous}
        kept_ids: set[int] = set()
        confirmed_at = _iso(_now())
        for item in draft["interests"]:
            evidence = _materialized_evidence(item)
            row = by_label.get(str(item.get("label") or "").strip())
            preference = item.get("preferenceScore")
            competence = item.get("competenceScore")
            if row:
                kept_ids.add(row.id)
                changed = (
                    row.evidence != evidence
                    or row.preference_score != preference
                    or row.competence_score != competence
                    or row.status != "CONFIRMED"
                )
                if changed:
                    row.evidence = evidence
                    row.preference_score = preference
                    row.competence_score = competence
                    row.status = "CONFIRMED"
                    row.confirmed_at = confirmed_at
                    row.confirmed_by = actor_name
                    row.updated_at = _now()
            else:
                new_row = GtInterest(
                    run_id=run.id, label=item.get("label"),
                    evidence=evidence, source_round="顾问会谈",
                    preference_score=preference, competence_score=competence,
                    status="CONFIRMED", confirmed_at=confirmed_at,
                    confirmed_by=actor_name,
                )
                sess.add(new_row)
                sess.flush()
                kept_ids.add(new_row.id)
                by_label[new_row.label.strip()] = new_row
        for row in previous:
            if row.id not in kept_ids:
                sess.delete(row)

        current.run_id = run.id
        current.phase = 6
        current.status = "REVIEW"
        current.script = json.dumps({
            **(current.script and json.loads(current.script or "{}") or {}),
            "reportInputFingerprint": fingerprint,
        }, ensure_ascii=False)
        expected = (expected_revision if expected_revision is not None
                    else current.revision)
        claim = sess.execute(
            update(CopilotSession)
            .where(CopilotSession.id == session_id,
                   CopilotSession.revision == expected)
            .values(revision=CopilotSession.revision + 1,
                    updated_at=_now())
        )
        if not claim.rowcount:
            sess.rollback()
            raise RevisionConflict("会谈在生成期间已被修改，请刷新后重新生成。")
        sess.add(CopilotPhaseEvent(
            session_id=session_id, actor_id=current.advisor_id,
            phase=6, action="report_prepared",
        ))
        sess.commit()
        run_id = run.id
        revision = expected + 1

    latest = store.get_session(session_id) or {}
    supplement = (latest.get("supplements") or [{}])[0] or {}
    analysis_data = supplement.get("analysis") or {}
    batch = analysis_data.get("projectRecommendations")
    if isinstance(batch, dict):
        items = batch.get("items") or []
        if not recommendations_current(
                source["id"], latest.get("interests") or [], analysis_data):
            items = []
        _sync_project_suggestions(
            {"student_id": student["id"], "run_id": run_id},
            items, latest.get("interests") or [],
        )
    return {"runId": run_id, "revision": revision}


# ---------------------------------------------------------------------------
# 报告准备
# ---------------------------------------------------------------------------
def _check_report_session(session_id: int, revision: int) -> None:
    current = store.get_session(session_id)
    if (not current or current["revision"] != revision
            or current.get("phase") != 6):
        raise RevisionConflict("会谈内容已变化，请重新进入报告页")


def _run_quadrant(run_id: int) -> None:
    from . import runs
    runs._persist_outputs(
        run_id, runs._prepare_outputs(run_id, stage="quadrant"))


def _ensure_quadrant(run_id: int) -> None:
    run = store.get_run_full(run_id) or {}
    quadrant = run.get("quadrant")
    if quadrant and quadrant.get("status") != "STALE":
        return
    _run_quadrant(run_id)


def prepare_report(session_id: int, expected_revision: int) -> dict:
    session = _session_or_404(session_id)
    if expected_revision != session["revision"]:
        raise RevisionConflict("会谈在生成期间已被修改，请刷新后重新生成。")

    student = _student(session["student_id"])
    draft = report_draft(session, student)
    run_id = session.get("run_id")

    existing = _confirmed_report(run_id, student["id"])
    if existing:
        return {
            "draft": draft, "preview": None,
            "revision": session["revision"],
            "runId": run_id, "reportId": existing["id"],
        }

    if any(item.get("required") for item in draft["missing"]):
        _check_report_session(session_id, session["revision"])
        return {
            "draft": draft, "preview": None,
            "revision": session["revision"],
            "runId": run_id, "reportId": None,
        }

    prepared = handoff_report(session_id, expected_revision)
    run_id = prepared["runId"]
    revision = prepared["revision"]
    _ensure_quadrant(run_id)
    _check_report_session(session_id, revision)
    preview = report_contract.build_report_preview(
        run_id, meeting_at=session.get("meeting_at") or session.get("created_at"))
    _check_report_session(session_id, revision)

    draft["calibration"] = dict(preview["career"]) if preview.get("career") else None
    draft["missing"] = [
        item for item in draft["missing"] if item.get("key") != "y4"
    ]
    if not preview.get("career"):
        draft["missing"].append({
            "key": "y4",
            "label": "Y4 分析：暂无可收录的画像，本次报告不包含 Y4 画像",
            "required": False,
        })
    excluded = [
        item for item in draft["interests"]
        if analysis.is_excluded_interest_topic(item.get("label"), None)
    ]
    if excluded:
        draft["interests"] = [
            item for item in draft["interests"]
            if not analysis.is_excluded_interest_topic(item.get("label"), None)
        ]
        labels = "、".join(str(item.get("label")) for item in excluded)
        draft["missing"].append({
            "key": "excluded-interests",
            "label": f"以下事项不参与兴趣分型，未收录最终报告：{labels}",
            "required": False,
        })

    return {
        "draft": draft, "preview": preview, "revision": revision,
        "runId": run_id, "reportId": None,
    }


# ---------------------------------------------------------------------------
# 确认与 PDF 双检
# ---------------------------------------------------------------------------
def confirm_session_report(
    session_id: int, *, revision: int, fingerprint: str,
    suggestion_ids: list[str], confirmed_by: str,
    reviewed_meeting: bool = True, reviewed_narrative: bool = True,
) -> tuple[dict, int]:
    session = _session_or_404(session_id)
    run_id = session.get("run_id")
    existing = _confirmed_report(run_id, session["student_id"])
    if existing:
        return _report_result(existing), 200
    if not run_id or revision != session["revision"]:
        raise RevisionConflict("请先刷新会谈及报告预览")
    report = report_contract.confirm_report(
        run_id,
        reviewed_meeting=reviewed_meeting,
        reviewed_narrative=reviewed_narrative,
        suggestion_ids=suggestion_ids,
        fingerprint=fingerprint,
        confirmed_by=confirmed_by,
        actor_id=session["advisor_id"],
        session_id=session_id,
        session_revision=revision,
    )
    return report, 201


def assert_report_pdf_fresh(session_id: int, revision: int,
                            fingerprint: str) -> None:
    session = _session_or_404(session_id)
    if not session.get("run_id") or session["revision"] != revision:
        raise RevisionConflict("会谈已变化，请重新进入报告页再下载")
    preview = report_contract.build_report_preview(session["run_id"])
    if preview["fingerprint"] != fingerprint:
        raise RevisionConflict("报告内容已变化，请重新预览再下载")
