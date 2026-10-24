"""Growth Talk 报告契约（first-touch.report.v1）与确认事务。

端口自 first-touch ``lib/first-touch-report.ts``、``lib/reports.ts``。
确认后的 payload 写入 ``gt_reports`` 后不再修改；版本按学生单调递增。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

import db as _db
import growth_talk_store as store
from growth_talk_store import NotFoundError, RevisionConflict

from . import analysis, prompts
from .errors import ActionError

REPORT_SCHEMA_VERSION = "first-touch.report.v1"

# 逐字对齐 first-touch lib/first-touch-report.ts 的字段上限。
REPORT_CONTENT_LIMITS = {
    "report_id": 128,
    "yuguo_student_id": 128,
    "student_name": 200,
    "student_grade": 100,
    "student_school": 300,
    "meeting_summary": 30000,
    "interest_id": 128,
    "interest_label": 200,
    "interest_evidence": 30000,
    "interest_quadrant": 100,
    "suggestion_id": 128,
    "suggestion_title": 120,
    "suggestion_introduction": 1000,
    "suggestion_growth_value": 500,
    "suggestion_output": 1000,
    "career_field": 150,
    "narrative": 2000,
    "prompt_version": 100,
    "source_id": 128,
    "source_type": 100,
    "date": 64,
    "interests_max": 200,
    "suggestions_max": 50,
    "list_max": 200,
}

SHANGHAI = ZoneInfo("Asia/Shanghai")


# ---------------------------------------------------------------------------
# 校验原语（源 first-touch-report.ts）
# ---------------------------------------------------------------------------
def _object(value, message: str = "报告对象无效") -> dict:
    if not isinstance(value, dict):
        raise ValueError(message)
    return value


def _text(value, maximum: int = 30000,
          message: str = "报告文字字段缺失或过长") -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(message)
    return value.strip()


def _list(value, maximum: int = 200) -> list:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("报告列表无效")
    return value


def _date(value) -> str:
    result = _text(value, REPORT_CONTENT_LIMITS["date"])
    try:
        datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("报告日期无效")
    return result


def _score(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 3:
        raise ValueError("兴趣分值必须为 0–3")
    return value


def validate_report(payload: dict) -> dict:
    root = _object(payload)
    if root.get("schema") != REPORT_SCHEMA_VERSION or root.get("status") != "CONFIRMED":
        raise ValueError("只支持已确认的 first-touch.report.v1 报告")
    if (isinstance(root.get("version"), bool)
            or not isinstance(root.get("version"), int)
            or root["version"] < 1):
        raise ValueError("报告版本无效")

    limits = REPORT_CONTENT_LIMITS
    student = _object(root.get("student"))
    actor = _object(root.get("confirmedBy"))

    interests = []
    for value in _list(root.get("interests"), limits["interests_max"]):
        item = _object(value)
        _score(item.get("preferenceScore"))
        _score(item.get("competenceScore"))
        interests.append({
            "id": _text(item.get("id"), limits["interest_id"]),
            "label": _text(item.get("label"), limits["interest_label"]),
            "evidence": _text(item.get("evidence"), limits["interest_evidence"]),
            "preferenceScore": item["preferenceScore"],
            "competenceScore": item["competenceScore"],
            "quadrant": _text(item.get("quadrant"), limits["interest_quadrant"]),
        })
    interest_ids = {item["id"] for item in interests}
    if not interests or len(interest_ids) != len(interests):
        raise ValueError("报告须包含不重复的已确认兴趣")

    suggestions = []
    for value in _list(root.get("suggestions"), limits["suggestions_max"]):
        item = _object(value)
        refs = [
            _text(ref, limits["interest_id"])
            for ref in _list(item.get("interestRefs"), limits["list_max"])
        ]
        if any(ref not in interest_ids for ref in refs):
            raise ValueError("建议引用了报告外的兴趣")
        suggestions.append({
            "id": _text(item.get("id"), limits["suggestion_id"]),
            "title": _text(item.get("title"), limits["suggestion_title"]),
            "introduction": _text(item.get("introduction"), limits["suggestion_introduction"]),
            "growthValue": _text(item.get("growthValue"), limits["suggestion_growth_value"]),
            "possibleOutputs": [
                _text(output, limits["suggestion_output"])
                for output in _list(item.get("possibleOutputs"), limits["list_max"])
            ],
            "interestRefs": refs,
        })

    career = None
    if root.get("career") is not None:
        row = _object(root.get("career"))
        career = {
            "careerInterests": _text(row.get("careerInterests"), limits["career_field"]),
            "abilityTendencies": _text(row.get("abilityTendencies"), limits["career_field"]),
            "valuePreferences": _text(row.get("valuePreferences"), limits["career_field"]),
        }

    prompt_versions = {}
    for key, value in _object(root.get("promptVersions")).items():
        prompt_versions[key] = _text(value, limits["prompt_version"])

    _text(root.get("reportId"), limits["report_id"])
    _text(root.get("yuguoStudentId"), limits["yuguo_student_id"])
    _date(root.get("confirmedAt"))
    _text(actor.get("id"), limits["report_id"])
    _text(actor.get("name"), limits["student_name"])
    _text(student.get("name"), limits["student_name"])
    _text(student.get("grade"), limits["student_grade"])
    if student.get("school") is not None:
        _text(student.get("school"), limits["student_school"])
    _text(root.get("meetingSummary"), limits["meeting_summary"])
    _text(root.get("narrative"), limits["narrative"])
    for value in _list(root.get("sources"), limits["list_max"]):
        item = _object(value)
        _text(item.get("id"), limits["source_id"])
        _text(item.get("type"), limits["source_type"])
        _date(item.get("createdAt"))
    return payload


# ---------------------------------------------------------------------------
# 预览与指纹
# ---------------------------------------------------------------------------
def _student_row(student_id: int) -> dict:
    with Session(store.engine()) as sess:
        row = sess.get(_db.Student, student_id)
        if not row:
            raise NotFoundError("学生不存在")
        return {
            "id": row.id, "student_code": row.student_code,
            "name": row.name, "grade": row.grade, "school": row.school,
        }


def read_career_profile(value) -> dict | None:
    """读取已确认职业画像；兼容 snake_case（本平台）与 camelCase（源仓库）。"""
    try:
        parsed = json.loads(value or "null")
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    normalized = {
        "careerInterests": parsed.get("careerInterests", parsed.get("career_interests")),
        "abilityTendencies": parsed.get("abilityTendencies", parsed.get("ability_tendencies")),
        "valuePreferences": parsed.get("valuePreferences", parsed.get("value_preferences")),
    }
    try:
        result = analysis.validate_career_profile(normalized)
    except ValueError:
        return None
    return {
        "careerInterests": result["career_interests"],
        "abilityTendencies": result["ability_tendencies"],
        "valuePreferences": result["value_preferences"],
    }


def report_fingerprint(run: dict, career_source: dict | None, student: dict) -> str:
    canonical = json.dumps(
        {"run": run, "careerSource": career_source, "student": student},
        ensure_ascii=False, sort_keys=True, default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _format_meeting_at(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.utcnow()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local = parsed.astimezone(SHANGHAI)
    return f"{local.year}年{local.month}月{local.day}日 {local.hour}:{local.minute:02d}"


def _yuguo_student_id(student: dict) -> str:
    identities = store.list_external_identities(student["id"], source_system="yuguo")
    if identities:
        return identities[0]["external_student_id"]
    return student.get("student_code") or str(student["id"])


def build_report_preview(run_id: int, meeting_at: str | None = None,
                         career: dict | None = None) -> dict:
    run = store.get_run_full(run_id)
    if not run:
        raise NotFoundError("分析不存在")
    if not run.get("understanding") or not run.get("quadrant") \
            or run["quadrant"]["status"] == "STALE":
        raise ActionError(409, "请先完成会议理解及当前兴趣的象限分析")
    source = store.get_source(run["source_id"]) or {}
    if source.get("purpose") == "MEETING":
        latest_source = store.list_sources(
            run["student_id"], type="GROWTH_TALK", purpose="MEETING")
        if not latest_source or latest_source[0]["id"] != run["source_id"]:
            raise ActionError(409, "会议资料已替换，请分析当前版本")

    interests = [
        item for item in run["interests"]
        if item["status"] == "CONFIRMED"
        and item["preference_score"] is not None
        and item["competence_score"] is not None
        and not analysis.is_excluded_interest_topic(item["label"], item.get("subtopic"))
    ]
    if not interests:
        raise ActionError(409, "请先确认兴趣")

    try:
        points = json.loads(run["quadrant"]["points"] or "[]")
    except (TypeError, ValueError):
        points = []
    if (not isinstance(points, list) or len(points) != len(interests)
            or any(not any(
                str(point.get("interestId")) == str(item["id"])
                and point.get("preferenceScore") == item["preference_score"]
                and point.get("competenceScore") == item["competence_score"]
                for point in points
            ) for item in interests)):
        raise ActionError(409, "象限分析与兴趣评分不一致，请重新生成")

    student = _student_row(run["student_id"])
    career_sources = store.list_sources(
        student["id"], type="Y4_CAREER_PROFILE")
    career_source = career_sources[0] if career_sources else None
    career_profile = read_career_profile(
        (career_source or {}).get("key_points_confirmed")
        or (career_source or {}).get("key_points_draft")
    )
    if not career_profile and isinstance(career, dict):
        career_profile = career

    interest_ids = {str(item["id"]) for item in interests}
    suggestions = []
    for row in run["suggestions"]:
        if row["status"] != "CONFIRMED":
            continue
        try:
            outputs = json.loads(row["possible_outputs"] or "[]")
        except (TypeError, ValueError):
            outputs = []
        try:
            refs = json.loads(row["interest_refs"] or "[]")
        except (TypeError, ValueError):
            refs = []
        suggestions.append({
            "id": str(row["id"]),
            "title": row["title"],
            "introduction": row["introduction"],
            "growthValue": row["growth_value"],
            "possibleOutputs": [str(value) for value in outputs if isinstance(value, str)],
            "interestRefs": [
                str(ref) for ref in refs if str(ref) in interest_ids
            ],
        })

    fingerprint = report_fingerprint(run, career_source, student)
    meeting_at = meeting_at or run["created_at"]
    meeting_summary = analysis.meeting_summary_with_overview(
        run["understanding"]["summary"], student["name"], interests)
    payload_interests = [{
        "id": str(item["id"]),
        "label": item["label"],
        "evidence": item["evidence"],
        "preferenceScore": item["preference_score"],
        "competenceScore": item["competence_score"],
        "quadrant": analysis.quadrant_zone(
            item["preference_score"], item["competence_score"]),
    } for item in interests]

    source_summary = {
        "id": str(run["source_id"]),
        "type": source.get("type") or "GROWTH_TALK",
        "createdAt": source.get("created_at"),
    }
    career_summary = None
    if career_source:
        career_summary = {
            "id": str(career_source["id"]),
            "type": career_source["type"],
            "createdAt": career_source["created_at"],
        }

    return {
        "fingerprint": fingerprint,
        "revision": run["revision"],
        "runId": run_id,
        "meetingAt": meeting_at,
        "meetingSummary": f"访谈日期：{_format_meeting_at(meeting_at)}\n\n{meeting_summary}",
        "narrative": analysis.personalize_student_references(
            run["quadrant"]["narrative"], student["name"]),
        "career": career_profile,
        "careerSourceId": career_source["id"] if career_source else None,
        "interests": payload_interests,
        "suggestions": suggestions,
        "source": source_summary,
        "careerSource": career_summary,
    }


# ---------------------------------------------------------------------------
# 确认事务
# ---------------------------------------------------------------------------
def confirm_report(run_id: int, *, reviewed_meeting: bool,
                   reviewed_narrative: bool, suggestion_ids: list,
                   fingerprint: str, confirmed_by: str,
                   actor_id: int | str | None = None,
                   session_id: int | None = None,
                   session_revision: int | None = None,
                   career: dict | None = None) -> dict:
    run = store.get_run(run_id)
    if not run:
        raise NotFoundError("分析不存在")
    student = _student_row(run["student_id"])
    if not (student.get("grade") or "").strip():
        raise ActionError(409, "请先补充年级，再确认旧版报告")
    if (reviewed_meeting is not True or reviewed_narrative is not True
            or not isinstance(suggestion_ids, list)):
        raise ActionError(400, "请完成报告内容复核")

    preview = build_report_preview(run_id, career=career)
    if fingerprint != preview["fingerprint"]:
        raise RevisionConflict("报告内容已变化，请重新预览")

    selected = [str(value) for value in suggestion_ids]
    available = {suggestion["id"] for suggestion in preview["suggestions"]}
    if len(set(selected)) != len(selected) or any(
            suggestion_id not in available for suggestion_id in selected):
        raise ActionError(400, "只能收录已确认的建议")

    confirmed_at = datetime.utcnow().isoformat()
    yuguo_student_id = _yuguo_student_id(student)
    actor = {
        "id": str(actor_id if actor_id is not None else confirmed_by),
        "name": confirmed_by,
    }
    sources = [preview["source"]]
    if preview["career"] and preview["careerSource"]:
        sources.append(preview["careerSource"])

    def build_payload(report_id: int, version: int) -> str:
        packet = {
            "schema": REPORT_SCHEMA_VERSION,
            "reportId": str(report_id),
            "version": version,
            "yuguoStudentId": yuguo_student_id,
            "status": "CONFIRMED",
            "confirmedAt": confirmed_at,
            "confirmedBy": actor,
            "student": {
                "name": student["name"],
                "grade": student["grade"],
                "school": student["school"],
            },
            "meetingSummary": preview["meetingSummary"],
            "career": preview["career"],
            "interests": preview["interests"],
            "narrative": preview["narrative"],
            "suggestions": [
                suggestion for suggestion in preview["suggestions"]
                if suggestion["id"] in selected
            ],
            "sources": sources,
            "promptVersions": dict(prompts.PROMPT_VERSIONS),
        }
        validate_report(packet)
        return json.dumps(packet, ensure_ascii=False)

    row = store.create_report(
        student["id"], run_id, "{}", confirmed_by,
        payload_builder=build_payload,
        expected_revision=preview["revision"],
        session_id=session_id,
        session_revision=session_revision,
    )
    return {
        "id": row["id"],
        "version": row["version"],
        "confirmedAt": row["confirmed_at"],
        "confirmedBy": row["confirmed_by"],
    }
