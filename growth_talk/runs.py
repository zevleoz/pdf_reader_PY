"""Growth Talk run 生命周期与顾问审核动作。

移植自 first-touch ``app/api/students/[id]/profiling/growth-talk/route.ts``
与 ``lib/growth-talk-native.ts``。所有写操作在同一个 SQLAlchemy Session 内
完成，revision 乐观锁与业务变更一起提交或回滚。
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

import db as _db
from growth_talk_store import (
    AuditLog,
    GtInterest,
    GtQuadrant,
    GtRun,
    GtSuggestion,
    GtUnderstanding,
    NotFoundError,
    RevisionConflict,
)

from . import analysis
from .errors import ActionError
import growth_talk_store as store

MANUAL_EVIDENCE = "顾问手动添加，待补充证据。"
MANUAL_ROUND = "顾问手动添加"

MEETING_TOPIC_TYPES = (
    ("subject", "学校学科"),
    ("interest", "课外兴趣"),
    ("social", "社会话题"),
)
_TOPIC_TYPE_VALUES = {value for value, _label in MEETING_TOPIC_TYPES}

_SUGGESTION_STATUSES = ("DRAFT", "CONFIRMED", "STALE")


# ---------------------------------------------------------------------------
# 会话与序列化
# ---------------------------------------------------------------------------
@contextmanager
def _unit():
    sess = Session(store.engine())
    try:
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def _now() -> datetime:
    return datetime.utcnow()


def _iso(value: datetime) -> str:
    return value.isoformat()


def _runner(sess: Session, run_id: int) -> GtRun:
    row = sess.get(GtRun, run_id)
    if not row:
        raise NotFoundError("分析不存在")
    return row


def _understanding_row(sess: Session, run_id: int) -> GtUnderstanding | None:
    return sess.execute(
        select(GtUnderstanding).where(GtUnderstanding.run_id == run_id)
    ).scalar_one_or_none()


def _quadrant_row(sess: Session, run_id: int) -> GtQuadrant | None:
    return sess.execute(
        select(GtQuadrant).where(GtQuadrant.run_id == run_id)
    ).scalar_one_or_none()


def _interest_rows(sess: Session, run_id: int) -> list[GtInterest]:
    return list(sess.execute(
        select(GtInterest).where(GtInterest.run_id == run_id)
        .order_by(GtInterest.created_at.asc(), GtInterest.id.asc())
    ).scalars().all())


def _suggestion_rows(sess: Session, run_id: int) -> list[GtSuggestion]:
    return list(sess.execute(
        select(GtSuggestion).where(GtSuggestion.run_id == run_id)
        .order_by(GtSuggestion.created_at.asc(), GtSuggestion.id.asc())
    ).scalars().all())


def _interest_json(row: GtInterest) -> dict:
    return {
        "id": row.id, "run_id": row.run_id, "label": row.label,
        "subtopic": row.subtopic, "evidence": row.evidence,
        "source_round": row.source_round,
        "evidence_strength": row.evidence_strength,
        "uncertainty": row.uncertainty,
        "preference_score": row.preference_score,
        "competence_score": row.competence_score,
        "special_focus": bool(row.special_focus), "status": row.status,
        "confirmed_at": row.confirmed_at, "confirmed_by": row.confirmed_by,
    }


def _suggestion_json(row: GtSuggestion) -> dict:
    return {
        "id": row.id, "run_id": row.run_id, "title": row.title,
        "introduction": row.introduction, "growth_value": row.growth_value,
        "possible_outputs": row.possible_outputs,
        "recommendation_basis": row.recommendation_basis,
        "interest_refs": row.interest_refs,
        "exploration_tags": row.exploration_tags, "status": row.status,
    }


def _understanding_json(row: GtUnderstanding) -> dict:
    return {
        "id": row.id, "run_id": row.run_id, "summary": row.summary,
        "topics": row.topics, "keywords": row.keywords, "model": row.model,
        "status": row.status,
    }


def _quadrant_json(row: GtQuadrant) -> dict:
    return {
        "id": row.id, "run_id": row.run_id, "points": row.points,
        "narrative": row.narrative, "status": row.status, "model": row.model,
    }


def _field(data, *names, default=None):
    for name in names:
        if isinstance(data, dict) and name in data:
            return data[name]
    return default


def _coerce_id(value):
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value


def _score(value, *, allow_none: bool):
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 3:
        raise ActionError(400, "分值必须是 0 到 3 的整数")
    return value


def _bump(sess: Session, run_id: int, expected) -> int:
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise RevisionConflict("内容已更新，请刷新后重试")
    result = sess.execute(
        update(GtRun)
        .where(GtRun.id == run_id, GtRun.revision == expected)
        .values(revision=GtRun.revision + 1, updated_at=_now())
    )
    if result.rowcount != 1:
        raise RevisionConflict("内容已更新，请刷新后重试")
    return expected + 1


def _stale_outputs(sess: Session, run_id: int) -> None:
    quadrant = _quadrant_row(sess, run_id)
    if quadrant:
        quadrant.status = "STALE"
        quadrant.updated_at = _now()
    for row in _suggestion_rows(sess, run_id):
        row.status = "STALE"
        row.updated_at = _now()


def _write_audit(sess: Session, *, actor_id, student_id, action: str, details: dict) -> None:
    sess.add(AuditLog(
        actor_id=actor_id, student_id=student_id, action=action,
        details=json.dumps(details, ensure_ascii=False),
    ))


# ---------------------------------------------------------------------------
# 会议事项元数据（源 lib/growth-talk-meeting.ts）
# ---------------------------------------------------------------------------
def validate_meeting_topic_type(value) -> str:
    if value in _TOPIC_TYPE_VALUES:
        return value
    raise ValueError("标签须为学校学科、课外兴趣或社会话题")


def _read_topic_metadata(topics) -> list:
    if isinstance(topics, list):
        return topics
    try:
        parsed = json.loads(topics or "[]")
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def read_meeting_topic_types(topics) -> dict[str, str]:
    types: dict[str, str] = {}
    for item in _read_topic_metadata(topics):
        if not isinstance(item, dict) or isinstance(item, list):
            continue
        label = item.get("label")
        if isinstance(label, str):
            topic_type = item.get("topicType")
            types[label.strip()] = topic_type if topic_type in _TOPIC_TYPE_VALUES else "interest"
    return types


def edit_meeting_topic_metadata(topics, previous_label, label, topic_type, evidence) -> str:
    matched = False
    result = []
    for item in _read_topic_metadata(topics):
        if (not previous_label or not isinstance(item, dict)
                or not isinstance(item.get("label"), str)
                or analysis.topic_key(item["label"]) != analysis.topic_key(previous_label)):
            result.append(item)
            continue
        matched = True
        result.append({**item, "label": label, "topicType": topic_type})
    if not matched:
        result.append({"label": label, "topicType": topic_type, "evidence": evidence})
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 兴趣审核区（源 lib/growth-talk-interest-section.ts）
# ---------------------------------------------------------------------------
def _section_input(run: dict, body: dict) -> dict:
    understanding = run.get("understanding")
    if not understanding:
        raise ActionError(409, "请先完成会议理解")
    items = _field(body, "items")
    removed_ids = _field(body, "removedInterestIds", "removed_interest_ids")
    select_candidates = _field(body, "selectCandidates", "select_candidates")
    if (not isinstance(items, list) or not isinstance(removed_ids, list)
            or not isinstance(select_candidates, bool)):
        raise ActionError(400, "兴趣审核数据无效")

    rows = {item["id"]: item for item in run["interests"]}
    seen_ids: set[int] = set()
    seen_labels: set[str] = set()
    parsed_items = []
    for raw in items:
        if not isinstance(raw, dict):
            raise ActionError(400, "兴趣审核数据无效")
        interest_id = _coerce_id(_field(raw, "interestId", "interest_id"))
        if interest_id is not None and not isinstance(interest_id, int):
            raise ActionError(400, "兴趣编号无效")
        special_focus = _field(raw, "specialFocus", "special_focus")
        if not isinstance(special_focus, bool):
            raise ActionError(400, "特别关注标记无效")
        preference = _field(raw, "preferenceScore", "preference_score")
        competence = _field(raw, "competenceScore", "competence_score")
        for score in (preference, competence):
            if score is not None and (
                    isinstance(score, bool) or not isinstance(score, int)
                    or score < 0 or score > 3):
                raise ActionError(400, "喜欢和擅长分值必须为 0–3 或待选")
        try:
            label = analysis.validate_editable_interest_label(raw.get("label"))
            topic_type = validate_meeting_topic_type(_field(raw, "topicType", "topic_type"))
        except ValueError as exc:
            raise ActionError(400, str(exc))
        key = analysis.normalize_interest_topic(label)
        if key in seen_labels:
            raise ActionError(400, "同一分析中不能有重复的兴趣词条")
        seen_labels.add(key)
        if interest_id is not None:
            current = rows.get(interest_id)
            if (not current or current["status"] == "DISMISSED"
                    or analysis.is_excluded_interest_topic(current["label"], current.get("subtopic"))
                    or (current["status"] == "PENDING_SELECTION" and not select_candidates)
                    or interest_id in seen_ids):
                raise ActionError(400, "兴趣不存在、重复或尚未选择")
            seen_ids.add(interest_id)
        parsed_items.append({
            "interest_id": interest_id, "label": label,
            "topic_type": topic_type, "special_focus": special_focus,
            "preference_score": preference, "competence_score": competence,
        })

    removed: set[int] = set()
    for raw_id in removed_ids:
        interest_id = _coerce_id(raw_id)
        current = rows.get(interest_id) if isinstance(interest_id, int) else None
        if (not isinstance(interest_id, int) or not current
                or current["status"] in ("DISMISSED", "PENDING_SELECTION")
                or analysis.is_excluded_interest_topic(current["label"], current.get("subtopic"))
                or interest_id in seen_ids or interest_id in removed):
            raise ActionError(400, "删除兴趣数据无效")
        removed.add(interest_id)

    for current in run["interests"]:
        editable = (
            current["status"] not in ("DISMISSED", "PENDING_SELECTION")
            and not analysis.is_excluded_interest_topic(
                current["label"], current.get("subtopic"))
        )
        if editable and current["id"] not in seen_ids and current["id"] not in removed:
            raise ActionError(400, "请提交完整的兴趣审核区")
        if (current["id"] not in seen_ids and current["id"] not in removed
                and analysis.normalize_interest_topic(current["label"]) in seen_labels):
            raise ActionError(400, "同一分析中不能有重复的兴趣词条")

    untouched_focus = sum(
        1 for item in run["interests"]
        if item.get("special_focus") and item["id"] not in seen_ids
        and item["id"] not in removed
    )
    if sum(1 for item in parsed_items if item["special_focus"]) + untouched_focus > 1:
        raise ActionError(400, "只能特别关注一项兴趣")

    return {
        "items": parsed_items, "removed_ids": removed,
        "select_candidates": select_candidates,
    }


def _persist_section(sess: Session, run: dict, input_data: dict, actor_name: str) -> dict:
    understanding = _understanding_row(sess, run["id"])
    rows = {row.id: row for row in _interest_rows(sess, run["id"])}
    types = read_meeting_topic_types(understanding.topics if understanding else "[]")
    removed_labels = {
        rows[interest_id].label.strip() for interest_id in input_data["removed_ids"]
        if interest_id in rows
    }
    changed = bool(input_data["removed_ids"])
    for interest_id in input_data["removed_ids"]:
        row = rows.get(interest_id)
        if row:
            sess.delete(row)
            rows.pop(interest_id, None)

    focus_changed = any(
        item["special_focus"] != bool(rows[item["interest_id"]].special_focus)
        for item in input_data["items"] if item["interest_id"] in rows
    )
    if focus_changed:
        for row in rows.values():
            row.special_focus = False

    replacements: dict[str, dict] = {}
    for item in input_data["items"]:
        current = rows.get(item["interest_id"])
        if current:
            replacements[current.label.strip()] = item
        complete = item["preference_score"] is not None and item["competence_score"] is not None
        status = "CONFIRMED" if complete else "PENDING_REVIEW"
        modified = (
            current is None or current.label != item["label"]
            or types.get(current.label.strip(), "interest") != item["topic_type"]
            or bool(current.special_focus) != item["special_focus"]
            or current.preference_score != item["preference_score"]
            or current.competence_score != item["competence_score"]
            or current.status != status
        )
        if not modified and not (focus_changed and item["special_focus"]):
            continue
        changed = True
        if current:
            current.label = item["label"]
            current.preference_score = item["preference_score"]
            current.competence_score = item["competence_score"]
            current.special_focus = item["special_focus"]
            current.status = status
            current.confirmed_at = (current.confirmed_at or _iso(_now())) if complete else None
            current.confirmed_by = actor_name if complete else None
            current.updated_at = _now()
        else:
            sess.add(GtInterest(
                run_id=run["id"], label=item["label"],
                evidence=MANUAL_EVIDENCE, source_round=MANUAL_ROUND,
                preference_score=item["preference_score"],
                competence_score=item["competence_score"],
                special_focus=item["special_focus"], status=status,
                confirmed_at=_iso(_now()) if complete else None,
                confirmed_by=actor_name if complete else None,
            ))
            changed = True

    if input_data["select_candidates"]:
        selected = {
            item["interest_id"] for item in input_data["items"]
            if item["interest_id"] is not None
        }
        for row in rows.values():
            if row.status == "PENDING_SELECTION" and row.id not in selected:
                row.status = "DISMISSED"
                row.updated_at = _now()
                changed = True

    metadata = []
    try:
        parsed = json.loads(understanding.topics or "[]") if understanding else []
        metadata = parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        metadata = []
    matched: set[str] = set()
    next_metadata = []
    for row in metadata:
        if not isinstance(row, dict):
            next_metadata.append(row)
            continue
        key = str(row.get("label", "")).strip()
        if key in removed_labels:
            changed = True
            continue
        replacement = replacements.get(key)
        if replacement:
            matched.add(key)
            next_metadata.append({
                **row, "label": replacement["label"],
                "topicType": replacement["topic_type"],
            })
            continue
        next_metadata.append(row)
    topics = json.dumps(next_metadata, ensure_ascii=False)
    for item in input_data["items"]:
        current = rows.get(item["interest_id"])
        if not current or current.label.strip() not in matched:
            topics = edit_meeting_topic_metadata(
                topics, None, item["label"], item["topic_type"],
                current.evidence if current else MANUAL_EVIDENCE,
            )
    if understanding and topics != understanding.topics:
        understanding.topics = topics
        understanding.updated_at = _now()
        changed = True
    if changed:
        _stale_outputs(sess, run["id"])
    return {"understanding": understanding, "changed": changed}


# ---------------------------------------------------------------------------
# 生成象限与建议
# ---------------------------------------------------------------------------
def _student_brief(student_id: int) -> dict:
    with Session(store.engine()) as sess:
        row = sess.get(_db.Student, student_id)
        if not row:
            raise NotFoundError("学生不存在")
        return {"id": row.id, "name": row.name, "grade": row.grade,
                "school": getattr(row, "school", None)}


def _confirmed_interests(run: dict, *, require_scores: bool) -> list[dict]:
    rows = [
        item for item in run["interests"]
        if item["status"] == "CONFIRMED"
        and not analysis.is_excluded_interest_topic(item["label"], item.get("subtopic"))
    ]
    if require_scores:
        rows = [
            item for item in rows
            if item["preference_score"] is not None and item["competence_score"] is not None
        ]
    return rows


def _prepare_outputs(run_id: int, *, stage: str = "all") -> dict:
    """只调用模型并组装结果，不写库（源 runQuadrantAnalysis + generateSuggestions）。"""
    run = store.get_run_full(run_id)
    if not run:
        raise NotFoundError("分析不存在")
    if not run.get("understanding"):
        raise ActionError(409, "请先完成会议理解")
    student = _student_brief(run["student_id"])
    prepared = {"quadrant": None, "suggestions": None, "model": run.get("model")}

    if stage in ("all", "quadrant"):
        confirmed = _confirmed_interests(run, require_scores=True)
        if not confirmed:
            raise ActionError(409, "请先确认至少一条带完整分值的兴趣")
        summary = analysis.meeting_summary_with_overview(
            analysis.interest_only_meeting_summary(run["understanding"]["summary"]),
            student["name"], confirmed,
        )
        input_data = {
            "student": {"name": student["name"], "grade": student["grade"]},
            "meetingSummary": summary,
            "interests": [{
                "id": item["id"], "label": item["label"],
                "subtopic": item.get("subtopic"), "evidence": item["evidence"],
                "uncertainty": item.get("uncertainty"),
                "preferenceScore": item["preference_score"],
                "competenceScore": item["competence_score"],
            } for item in confirmed],
        }
        narrative = analysis.run_quadrant_analysis(input_data)["narrative"]
        points = [{
            "interestId": item["id"],
            "preferenceScore": item["preference_score"],
            "competenceScore": item["competence_score"],
            "quadrant": analysis.quadrant_zone(
                item["preference_score"], item["competence_score"]),
        } for item in confirmed]
        prepared["quadrant"] = (points, narrative)

    if stage in ("all", "suggestions", "suggestion"):
        confirmed = _confirmed_interests(run, require_scores=False)
        if not confirmed:
            raise ActionError(409, "请先确认至少一条兴趣")
        items = analysis.generate_suggestions({
            "interests": [{
                "id": item["id"], "label": item["label"],
                "subtopic": item.get("subtopic"), "evidence": item["evidence"],
                "uncertainty": item.get("uncertainty"),
                "preferenceScore": item["preference_score"],
                "competenceScore": item["competence_score"],
            } for item in confirmed],
            "understanding": {
                "summary": run["understanding"]["summary"],
                "keywords": run["understanding"]["keywords"],
            },
        })
        prepared["suggestions"] = [{
            **item,
            "interest_refs": [
                ref for ref in (item.get("interestRefs") or [])
                if any(str(interest["id"]) == str(ref) for interest in confirmed)
            ],
        } for item in items]
    return prepared


def _persist_outputs(run_id: int, prepared: dict) -> None:
    if prepared.get("quadrant"):
        points, narrative = prepared["quadrant"]
        store.save_quadrant(
            run_id, json.dumps(points, ensure_ascii=False), narrative,
            prepared.get("model"),
        )
    if prepared.get("suggestions") is not None:
        store.replace_suggestions(run_id, prepared["suggestions"])


def _generate_outputs(run_id: int, *, stage: str = "all") -> None:
    _persist_outputs(run_id, _prepare_outputs(run_id, stage=stage))


# ---------------------------------------------------------------------------
# 分析作业入口（Task 7 子进程调用）
# ---------------------------------------------------------------------------
def create_and_run_analysis(run_id: int) -> None:
    """同步执行会议理解 + 兴趣候选落库，status 改为 PENDING_REVIEW。"""
    run = store.get_run(run_id)
    if not run:
        raise NotFoundError("分析不存在")
    source = store.get_source(run["source_id"])
    if not source:
        raise NotFoundError("Growth Talk 资料不存在")
    try:
        store.set_run_status(run_id, "RUNNING", None)
        result = analysis.analyze_meeting_source(source["content"])
        store.save_understanding(
            run_id, result["summary"],
            json.dumps(result["topics"], ensure_ascii=False),
            json.dumps(result["keywords"], ensure_ascii=False),
            run.get("model"),
        )
        store.replace_interests(run_id, [{
            **topic, "status": "PENDING_SELECTION",
        } for topic in result["topics"]])
        store.set_run_status(run_id, "PENDING_REVIEW", None)
    except Exception as exc:
        store.set_run_status(run_id, "FAILED", str(exc))
        raise


def career_analysis(source_id: int) -> dict:
    """分析最新 Y4 职业兴趣报告并写回 key_points_confirmed。"""
    source = store.get_source(source_id)
    if not source:
        raise NotFoundError("资料不存在")
    latest = store.list_sources(source["student_id"], type="Y4_CAREER_PROFILE")
    if not latest or latest[0]["id"] != source_id:
        raise ActionError(409, "请使用当前职业兴趣报告")
    payload = analysis.analyze_career_profile(source["content"])
    store.set_source_key_points(
        source_id, json.dumps(payload, ensure_ascii=False), "CONFIRMED")
    return {"sourceId": source_id, "analysis": payload, "status": "CONFIRMED"}


# ---------------------------------------------------------------------------
# 本地编辑动作（无 LLM 调用）
# ---------------------------------------------------------------------------
def _action_save_interest_section(sess, run, body, actor_name) -> dict:
    full = store.get_run_full(run.id)
    input_data = _section_input(full, body)
    _persist_section(sess, full, input_data, actor_name)
    rows = _interest_rows(sess, run.id)
    understanding = _understanding_row(sess, run.id)
    quadrant = _quadrant_row(sess, run.id)
    suggestions = _suggestion_rows(sess, run.id)
    return {
        "interests": [_interest_json(row) for row in rows],
        "understanding": _understanding_json(understanding) if understanding else None,
        "quadrant": _quadrant_json(quadrant) if quadrant else None,
        "suggestions": [_suggestion_json(row) for row in suggestions],
        "outputs_stale": True,
    }, None


def _action_edit_understanding(sess, run, body, actor_name) -> dict:
    understanding = _understanding_row(sess, run.id)
    if not understanding:
        raise ActionError(409, "会议理解尚未生成")
    try:
        summary = analysis.validate_editable_meeting_summary(body.get("summary"))
    except ValueError as exc:
        raise ActionError(400, str(exc))
    understanding.summary = summary
    understanding.status = "CONFIRMED"
    understanding.updated_at = _now()
    _stale_outputs(sess, run.id)
    quadrant = _quadrant_row(sess, run.id)
    return {
        "understanding": _understanding_json(understanding),
        "quadrant": _quadrant_json(quadrant) if quadrant else None,
        "suggestions": [_suggestion_json(row) for row in _suggestion_rows(sess, run.id)],
    }, None


def _action_edit_quadrant_narrative(sess, run, body, actor_name) -> dict:
    quadrant = _quadrant_row(sess, run.id)
    if not quadrant or quadrant.status == "STALE":
        raise ActionError(409, "兴趣分型说明已失效，请重新生成")
    student = _student_brief(run.student_id)
    try:
        narrative = analysis.validate_quadrant_narrative(
            analysis.personalize_student_references(
                body.get("narrative"), student["name"]))
    except ValueError as exc:
        raise ActionError(400, str(exc))
    quadrant.narrative = narrative
    quadrant.status = "DRAFT"
    quadrant.updated_at = _now()
    return {"quadrant": _quadrant_json(quadrant)}, None


def _action_edit_suggestions(sess, run, body, actor_name) -> dict:
    current = [row for row in _suggestion_rows(sess, run.id) if row.status != "STALE"]
    items = body.get("items")
    if not isinstance(items, list):
        raise ActionError(400, "探索建议编辑数据无效")
    submitted = []
    for raw in items:
        if not isinstance(raw, dict):
            raise ActionError(400, "探索建议编辑数据无效")
        suggestion_id = _coerce_id(_field(raw, "suggestionId", "suggestion_id"))
        if suggestion_id is not None and not isinstance(suggestion_id, int):
            raise ActionError(400, "探索建议编辑数据无效")
        submitted.append((suggestion_id, raw))
    submitted_ids = [sid for sid, _raw in submitted if sid is not None]
    if len(set(submitted_ids)) != len(submitted_ids):
        raise ActionError(400, "探索建议编辑数据无效")
    current_ids = {row.id for row in current}
    if any(sid not in current_ids for sid in submitted_ids):
        raise ActionError(400, "探索建议编辑数据无效")
    for row in current:
        if row.id not in submitted_ids:
            sess.delete(row)
    current_map = {row.id: row for row in current if row.id in submitted_ids}
    for suggestion_id, raw in submitted:
        title = str(raw.get("title") or "").strip()
        introduction = str(raw.get("introduction") or "").strip()
        growth_value = str(raw.get("growthValue", raw.get("growth_value")) or "").strip()
        try:
            analysis.validate_suggestion_lengths(title, introduction, growth_value)
        except ValueError as exc:
            raise ActionError(400, str(exc))
        row = current_map.get(suggestion_id)
        if row is None:
            sess.add(GtSuggestion(
                run_id=run.id, title=title, introduction=introduction,
                growth_value=growth_value, recommendation_basis=MANUAL_ROUND,
                status="DRAFT",
            ))
        elif (title != row.title or introduction != row.introduction
              or growth_value != row.growth_value):
            row.title = title
            row.introduction = introduction
            row.growth_value = growth_value
            row.status = "DRAFT"
            row.updated_at = _now()
    return {"suggestions": [_suggestion_json(row) for row in _suggestion_rows(sess, run.id)]}, None


def _suggestion_or_409(sess, run_id: int, body: dict) -> GtSuggestion:
    suggestion_id = _coerce_id(_field(body, "suggestionId", "suggestion_id"))
    row = sess.get(GtSuggestion, suggestion_id) if isinstance(suggestion_id, int) else None
    if not row or row.run_id != run_id or row.status == "STALE":
        raise ActionError(409, "建议已失效，请重新生成")
    return row


def _action_edit_suggestion(sess, run, body, actor_name) -> dict:
    row = _suggestion_or_409(sess, run.id, body)
    title = str(body.get("title") or "").strip()
    introduction = str(body.get("introduction") or "").strip()
    growth_value = str(body.get("growthValue", body.get("growth_value")) or "").strip()
    try:
        analysis.validate_suggestion_lengths(title, introduction, growth_value)
    except ValueError as exc:
        raise ActionError(400, str(exc))
    row.title = title
    row.introduction = introduction
    row.growth_value = growth_value
    row.status = "DRAFT"
    row.updated_at = _now()
    return {"suggestions": [_suggestion_json(row) for row in _suggestion_rows(sess, run.id)]}, None


def _action_confirm_suggestion(sess, run, body, actor_name) -> dict:
    row = _suggestion_or_409(sess, run.id, body)
    if not row.title.strip() or not row.introduction.strip() or not row.growth_value.strip():
        raise ActionError(400, "建议不完整")
    row.status = "CONFIRMED"
    row.updated_at = _now()
    return {"suggestions": [_suggestion_json(row) for row in _suggestion_rows(sess, run.id)]}, None


def _action_confirm_suggestions(sess, run, body, actor_name) -> dict:
    current = [row for row in _suggestion_rows(sess, run.id) if row.status != "STALE"]
    drafts = [row for row in current if row.status == "DRAFT"]
    if not current or not drafts:
        raise ActionError(409, "没有待确认的探索建议")
    if any(not row.title.strip() or not row.introduction.strip()
           or not row.growth_value.strip() for row in current):
        raise ActionError(400, "建议不完整")
    for row in drafts:
        row.status = "CONFIRMED"
        row.updated_at = _now()
    return {"suggestions": [_suggestion_json(row) for row in _suggestion_rows(sess, run.id)]}, None


def _action_add_interest(sess, run, body, actor_name) -> dict:
    understanding = _understanding_row(sess, run.id)
    if not understanding:
        raise ActionError(409, "请先完成会议理解")
    try:
        label = analysis.validate_editable_interest_label(body.get("label"))
        topic_type = ("interest" if _field(body, "topicType", "topic_type") is None
                      else validate_meeting_topic_type(_field(body, "topicType", "topic_type")))
    except ValueError as exc:
        raise ActionError(400, str(exc))
    if any(analysis.normalize_interest_topic(row.label)
           == analysis.normalize_interest_topic(label)
           for row in _interest_rows(sess, run.id)):
        raise ActionError(400, "同一分析中不能有重复的兴趣词条")
    row = GtInterest(
        run_id=run.id, label=label, evidence=MANUAL_EVIDENCE,
        source_round=MANUAL_ROUND, preference_score=None,
        competence_score=None, status="PENDING_REVIEW",
    )
    sess.add(row)
    understanding.topics = edit_meeting_topic_metadata(
        understanding.topics, None, label, topic_type, MANUAL_EVIDENCE)
    understanding.updated_at = _now()
    _stale_outputs(sess, run.id)
    quadrant = _quadrant_row(sess, run.id)
    return {
        "interests": [_interest_json(row) for row in _interest_rows(sess, run.id)],
        "understanding": _understanding_json(understanding),
        "quadrant": _quadrant_json(quadrant) if quadrant else None,
        "suggestions": [_suggestion_json(row) for row in _suggestion_rows(sess, run.id)],
    }, None


def _action_edit_interest(sess, run, body, actor_name) -> dict:
    interest_id = _coerce_id(_field(body, "interestId", "interest_id"))
    row = sess.get(GtInterest, interest_id) if isinstance(interest_id, int) else None
    if (not row or row.run_id != run.id
            or analysis.is_excluded_interest_topic(row.label, row.subtopic)):
        raise ActionError(404, "兴趣不存在")
    understanding = _understanding_row(sess, run.id)
    if not understanding:
        raise ActionError(409, "请先完成会议理解")
    raw_type = _field(body, "topicType", "topic_type")
    try:
        label = analysis.validate_editable_interest_label(body.get("label"))
        topic_type = (
            read_meeting_topic_types(understanding.topics).get(row.label.strip(), "interest")
            if raw_type is None else validate_meeting_topic_type(raw_type)
        )
    except ValueError as exc:
        raise ActionError(400, str(exc))
    if any(candidate.id != row.id
           and analysis.normalize_interest_topic(candidate.label)
           == analysis.normalize_interest_topic(label)
           for candidate in _interest_rows(sess, run.id)):
        raise ActionError(400, "同一分析中不能有重复的兴趣词条")
    previous_label = row.label
    row.label = label
    row.updated_at = _now()
    understanding.topics = edit_meeting_topic_metadata(
        understanding.topics, previous_label, label, topic_type,
        row.evidence or MANUAL_EVIDENCE)
    understanding.updated_at = _now()
    _stale_outputs(sess, run.id)
    return {
        "interests": [_interest_json(item) for item in _interest_rows(sess, run.id)],
        "understanding": _understanding_json(understanding),
        "quadrant": _quadrant_json(_quadrant_row(sess, run.id))
        if _quadrant_row(sess, run.id) else None,
        "suggestions": [_suggestion_json(item) for item in _suggestion_rows(sess, run.id)],
    }, None


def _action_delete_interest(sess, run, body, actor_name) -> dict:
    interest_id = _coerce_id(_field(body, "interestId", "interest_id"))
    row = sess.get(GtInterest, interest_id) if isinstance(interest_id, int) else None
    if not row or row.run_id != run.id:
        raise ActionError(404, "兴趣不存在")
    sess.delete(row)
    _stale_outputs(sess, run.id)
    quadrant = _quadrant_row(sess, run.id)
    return {
        "removed_interest_id": row.id,
        "interests": [_interest_json(item) for item in _interest_rows(sess, run.id)],
        "quadrant": _quadrant_json(quadrant) if quadrant else None,
        "suggestions": [_suggestion_json(item) for item in _suggestion_rows(sess, run.id)],
        "outputs_stale": True,
    }, None


def _action_select_interests(sess, run, body, actor_name) -> dict:
    raw_ids = _field(body, "interestIds", "interest_ids")
    if (not isinstance(raw_ids, list)
            or any(isinstance(value, bool) or _coerce_id(value) is None
                   for value in raw_ids)):
        raise ActionError(400, "候选事项选择数据无效")
    selected = [_coerce_id(value) for value in raw_ids]
    if len(set(selected)) != len(selected):
        raise ActionError(400, "候选事项选择数据无效")
    rows = _interest_rows(sess, run.id)
    candidates = {row.id for row in rows if row.status == "PENDING_SELECTION"}
    if any(interest_id not in candidates for interest_id in selected):
        raise ActionError(400, "候选事项不存在或已选择")
    for row in rows:
        if row.status != "PENDING_SELECTION":
            continue
        row.status = "PENDING_REVIEW" if row.id in selected else "DISMISSED"
        row.updated_at = _now()
    return {"interests": [_interest_json(row) for row in _interest_rows(sess, run.id)]}, None


def _action_set_special_focus(sess, run, body, actor_name) -> dict:
    raw_id = _field(body, "interestId", "interest_id")
    interest_id = _coerce_id(raw_id)
    if raw_id is not None and (
            isinstance(raw_id, bool) or not isinstance(interest_id, int)):
        raise ActionError(400, "特别关注的兴趣无效")
    rows = _interest_rows(sess, run.id)
    selected = next((row for row in rows if row.id == interest_id), None) if interest_id is not None else None
    if interest_id is not None and (
            not selected or selected.status in ("PENDING_SELECTION", "DISMISSED")
            or analysis.is_excluded_interest_topic(selected.label, selected.subtopic)):
        raise ActionError(400, "特别关注的兴趣不存在")
    for row in rows:
        row.special_focus = bool(selected and row.id == selected.id)
    return {"interests": [_interest_json(row) for row in _interest_rows(sess, run.id)]}, None


_LOCAL_ACTIONS = {
    "save-interest-section": _action_save_interest_section,
    "edit-understanding": _action_edit_understanding,
    "edit-quadrant-narrative": _action_edit_quadrant_narrative,
    "edit-suggestions": _action_edit_suggestions,
    "edit-suggestion": _action_edit_suggestion,
    "confirm-suggestion": _action_confirm_suggestion,
    "confirm-suggestions": _action_confirm_suggestions,
    "add-interest": _action_add_interest,
    "edit-interest": _action_edit_interest,
    "delete-interest": _action_delete_interest,
    "select-interests": _action_select_interests,
    "set-special-focus": _action_set_special_focus,
}

# 需要 LLM 的动作由独立流程处理，避免在数据库事务内等待模型响应。
_LLM_ACTIONS = {"discover-interests", "confirm-interests", "regenerate"}


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------
def apply_action(run_id: int, action: str, body: dict, actor_name: str,
                 *, actor_id: int | None = None) -> dict:
    if action not in _LOCAL_ACTIONS and action not in _LLM_ACTIONS:
        raise ActionError(400, "不支持的操作")
    expected = body.get("expected_revision")
    if action == "discover-interests":
        return _run_discover(run_id, expected, body, actor_name, actor_id)
    if action == "confirm-interests":
        return _run_confirm_interests(run_id, expected, body, actor_name, actor_id)
    if action == "regenerate":
        return _run_regenerate(run_id, expected, body, actor_name, actor_id)

    with _unit() as sess:
        run = _runner(sess, run_id)
        revision = _bump(sess, run_id, expected)
        patch, _post = _LOCAL_ACTIONS[action](sess, run, body, actor_name)
        _write_audit(
            sess, actor_id=actor_id, student_id=run.student_id, action=action,
            details={"run_id": run_id, "actor": actor_name},
        )
    return {"ok": True, "revision": revision, "patch": patch}


def _run_confirm_interests(run_id, expected, body, actor_name, actor_id) -> dict:
    run = store.get_run_full(run_id)
    if not run:
        raise NotFoundError("分析不存在")
    items = body.get("items")
    if not isinstance(items, list) or not items:
        raise ActionError(400, "兴趣确认数据无效")
    ids = [_coerce_id(_field(item, "interestId", "interest_id")) for item in items]
    if (any(not isinstance(interest_id, int) for interest_id in ids)
            or len(set(ids)) != len(ids)):
        raise ActionError(400, "兴趣确认数据无效")

    with _unit() as sess:
        run_row = _runner(sess, run_id)
        revision = _bump(sess, run_id, expected)
        rows = {row.id: row for row in _interest_rows(sess, run_id)}
        for item in items:
            interest_id = _coerce_id(_field(item, "interestId", "interest_id"))
            row = rows.get(interest_id)
            if (not row or row.status in ("PENDING_SELECTION", "DISMISSED")
                    or analysis.is_excluded_interest_topic(row.label, row.subtopic)):
                raise ActionError(400, "兴趣候选不存在或不属于兴趣主题")
            preference = _score(_field(item, "preferenceScore", "preference_score"),
                                allow_none=False)
            competence = _score(_field(item, "competenceScore", "competence_score"),
                                allow_none=False)
            row.preference_score = preference
            row.competence_score = competence
            row.status = "CONFIRMED"
            row.confirmed_at = _iso(_now())
            row.confirmed_by = actor_name
            row.updated_at = _now()
        _stale_outputs(sess, run_id)
        _write_audit(
            sess, actor_id=actor_id, student_id=run_row.student_id,
            action="confirm-interests",
            details={"run_id": run_id, "actor": actor_name, "interest_ids": ids},
        )

    _generate_outputs(run_id, stage="all")
    full = store.get_run_full(run_id)
    return {
        "ok": True, "revision": revision,
        "patch": {
            "interests": full["interests"],
            "quadrant": full["quadrant"],
            "suggestions": full["suggestions"],
        },
    }


def _run_discover(run_id, expected, body, actor_name, actor_id) -> dict:
    run = store.get_run_full(run_id)
    if not run:
        raise NotFoundError("分析不存在")
    if not run.get("understanding"):
        raise ActionError(409, "请先完成会议理解")
    source = store.get_source(run["source_id"])
    if not source:
        raise ActionError(409, "请先上传会议纪要")
    existing = [{
        "label": item["label"], "subtopic": item.get("subtopic"),
        "evidence": item["evidence"],
    } for item in run["interests"]]
    additions = analysis.discover_additional_interests(source["content"], existing)
    if not additions:
        if expected != run["revision"]:
            raise RevisionConflict("内容已更新，请刷新后重试")
        return {"ok": True, "revision": run["revision"], "patch": {},
                "added_count": 0}

    with _unit() as sess:
        run_row = _runner(sess, run_id)
        revision = _bump(sess, run_id, expected)
        understanding = _understanding_row(sess, run_id)
        for item in additions:
            sess.add(GtInterest(
                run_id=run_id, label=item["label"],
                subtopic=item.get("subtopic"), evidence=item["evidence"],
                source_round=item.get("sourceRound"),
                evidence_strength=item.get("evidenceStrength"),
                uncertainty=item.get("uncertainty"),
                preference_score=item.get("preferenceScore"),
                competence_score=item.get("competenceScore"),
                status="PENDING_SELECTION",
            ))
        if understanding:
            understanding.topics = json.dumps(
                [*_read_topic_metadata(understanding.topics), *additions],
                ensure_ascii=False,
            )
            understanding.updated_at = _now()
        _stale_outputs(sess, run_id)
        _write_audit(
            sess, actor_id=actor_id, student_id=run_row.student_id,
            action="interests_discovered",
            details={"run_id": run_id, "actor": actor_name,
                     "added_count": len(additions)},
        )
    full = store.get_run_full(run_id)
    return {
        "ok": True, "revision": revision, "added_count": len(additions),
        "patch": {
            "interests": full["interests"],
            "understanding": full["understanding"],
            "quadrant": full["quadrant"],
            "suggestions": full["suggestions"],
        },
    }


def _run_regenerate(run_id, expected, body, actor_name, actor_id) -> dict:
    run = store.get_run_full(run_id)
    if not run:
        raise NotFoundError("分析不存在")
    stage = body.get("stage") or body.get("target") or "suggestions"
    if stage not in ("quadrant", "suggestions", "all"):
        raise ActionError(400, "不支持的操作")
    prepared = _prepare_outputs(run_id, stage=stage)
    with _unit() as sess:
        run_row = _runner(sess, run_id)
        revision = _bump(sess, run_id, expected)
        _write_audit(
            sess, actor_id=actor_id, student_id=run_row.student_id,
            action="regenerate", details={"run_id": run_id, "stage": stage},
        )
    _persist_outputs(run_id, prepared)
    full = store.get_run_full(run_id)
    return {
        "ok": True, "revision": revision,
        "patch": {"quadrant": full["quadrant"],
                  "suggestions": full["suggestions"]},
    }
