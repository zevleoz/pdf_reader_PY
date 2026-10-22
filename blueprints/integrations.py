"""Yuguo / CRM 集成蓝图。

四类端点：
- 老师目录（Bearer ``FIRST_TOUCH_DIRECTORY_TOKEN``）：GET 快照 / POST 推送；
- CRM 交付（Bearer ``CRM_INTEGRATION_TOKEN``）：按 junction 1.1.0 schema
  幂等接收学生与预约；
- 预约查询（session）：Admin 全量、Advisor 只看自己；
- 学生导入与改派（session）：``/students/import-yuguo``、
  ``/api/account/assignment-sync``。

身份定位只经 ``external_identities``（``source_system='yuguo'``），
姓名/手机号不参与匹配合并；Yuguo 的 ``assignmentVersion`` 存在该行
``details`` JSON 中（本平台 students 表没有该列）。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import jsonschema
from flask import Blueprint, jsonify, request, session
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

import db as _db
import growth_talk_store as store
from app_utils import BASE_DIR, role_required
from growth_talk.yuguo_client import (YuguoError, fetch_students_for_teacher,
                                      parse_yuguo_student, push_teacher_directory)

bp = Blueprint("integrations", __name__)

_SCHEMA_PATH = (Path(BASE_DIR) / "docs" / "integrations" / "junction-2026"
                / "student-delivery.schema.json")
_SYNC_INTERVAL_SECONDS = 15.0
_last_sync_at = 0.0

_ASSIGNMENT_ACTION = "yuguo_assignment_synced"
_NOTICE_READ_ACTION = "yuguo_assignment_notice_read"
_IMPORT_ACTION = "yuguo_student_imported"
_CONFLICT_MESSAGE = "学生身份映射或宇果分配版本冲突，未覆盖已有工作区，请核对后重试"
_FAILED_MESSAGE = "本地数据库写入失败，请联系管理员检查服务日志"


# ---------------------------------------------------------------------------
# 通用助手
# ---------------------------------------------------------------------------
def _error(message: str, status: int):
    return jsonify({"ok": False, "error": message}), status


def _bearer_token() -> str:
    auth = request.headers.get("Authorization", "")
    return auth[7:].strip() if auth.startswith("Bearer ") else ""


def _json_details(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _teacher_advisor_name(user: dict) -> str:
    """平台内学生归属字段：优先 advisor_name，其次显示名/登录名。"""
    return ((user.get("advisor_name") or "").strip()
            or (user.get("display_name") or "").strip()
            or (user.get("username") or "").strip())


def _user_id_by_advisor_name(name: str):
    if not name:
        return None
    for user in _db.list_users():
        if user.get("role") == "advisor" and user.get("advisor_name") == name:
            return user["id"]
    return None


# ---------------------------------------------------------------------------
# 老师目录
# ---------------------------------------------------------------------------
def _directory_auth_error():
    token = (os.environ.get("FIRST_TOUCH_DIRECTORY_TOKEN") or "").strip()
    if not token or len(token) < 32:
        return jsonify({"error": "Yuguo 导师目录同步尚未配置"}), 503
    provided = _bearer_token()
    if not provided or not hmac.compare_digest(provided, token):
        return jsonify({"error": "Unauthorized"}), 401
    return None


def _teacher_directory() -> list[dict]:
    with Session(_db.engine) as sess:
        users = sess.execute(
            select(_db.User).where(_db.User.role == "advisor",
                                   _db.User.is_active == 1)
        ).scalars().all()
        rows = [{
            "id": user.id,
            "name": (user.display_name or user.advisor_name
                     or user.username or ""),
            "email": user.email or "",
        } for user in users]
    return sorted(rows, key=lambda item: item["name"])


@bp.route("/api/integrations/teachers", methods=["GET"])
def api_teacher_directory():
    denied = _directory_auth_error()
    if denied:
        return denied
    response = jsonify({"teachers": _teacher_directory()})
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/api/integrations/teachers", methods=["POST"])
def api_push_teacher_directory():
    denied = _directory_auth_error()
    if denied:
        return denied
    try:
        result = push_teacher_directory(_teacher_directory())
    except YuguoError as exc:
        return jsonify({"error": exc.message}), 503
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# CRM 交付契约
# ---------------------------------------------------------------------------
class DeliveryError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@lru_cache(maxsize=1)
def _validator():
    with open(_SCHEMA_PATH, encoding="utf-8") as handle:
        schema = json.load(handle)
    return jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker())


def _crm_authorized() -> bool:
    token = (os.environ.get("CRM_INTEGRATION_TOKEN") or "").strip()
    provided = _bearer_token()
    return bool(token and len(token) >= 32 and provided
                and hmac.compare_digest(provided, token))


def _text(value, maximum: int = 160) -> bool:
    return isinstance(value, str) and 0 < len(value) <= maximum


def parse_delivery(value) -> dict:
    """schema 校验 + 源仓库 parseDelivery 的语义校验。"""
    if not isinstance(value, dict):
        raise DeliveryError(400, "Invalid CRM delivery contract")
    candidate = value
    # 1.1.0 schema 把 appointment 的 recipient 固定为 sales_crm；本平台
    # 按计划也接受 first_touch 预约，因此仅在 schema 校验时把 recipient
    # 归一为 sales_crm，其余字段与语义仍按契约校验。
    if value.get("kind") == "appointment" and value.get("recipient") == "first_touch":
        candidate = dict(value, recipient="sales_crm")
    if next(_validator().iter_errors(candidate), None) is not None:
        raise DeliveryError(400, "Invalid CRM delivery contract")

    payload = value
    status = payload.get("status")
    if (payload.get("schema") != "junction.student_delivery.1.1.0"
            or payload.get("recipient") != "first_touch"
            or payload.get("kind") not in ("student", "appointment")
            or not _text(payload.get("messageId"))
            or not _text(payload.get("junctionStudentId"))
            or not _text(payload.get("teacherId"))
            or not isinstance(payload.get("revision"), int)
            or isinstance(payload.get("revision"), bool)
            or payload["revision"] < 1
            or _parse_time(payload.get("issuedAt")) is None
            or _parse_time(payload.get("expiresAt")) is None):
        raise DeliveryError(400, "Invalid CRM delivery")
    authorization = payload.get("authorization")
    if (not isinstance(authorization, dict)
            or not _text(authorization.get("grantId"))
            or authorization.get("purpose") != "service_delivery"
            or _parse_time(authorization.get("grantedAt")) is None
            or (authorization.get("expiresAt") is not None
                and _parse_time(authorization.get("expiresAt")) is None)):
        raise DeliveryError(400, "Invalid CRM delivery")

    if payload["kind"] == "student":
        if status not in ("active", "revoked"):
            raise DeliveryError(400, "Invalid CRM delivery")
        student = payload.get("student")
        if status == "active":
            if not isinstance(student, dict) or not _text(student.get("name"), 200):
                raise DeliveryError(400, "Invalid CRM delivery")
            limits = {"grade": 100, "school": 300, "contactPhone": 40,
                      "guardianName": 200}
            for key, limit in limits.items():
                item = student.get(key)
                if item is not None and (not isinstance(item, str)
                                         or len(item) > limit):
                    raise DeliveryError(400, "Invalid CRM delivery")
    else:
        appointment = payload.get("appointment")
        if status not in ("scheduled", "cancelled"):
            raise DeliveryError(400, "Invalid CRM delivery")
        if (not isinstance(appointment, dict)
                or not _text(appointment.get("taskId"))
                or _parse_time(appointment.get("startAt")) is None
                or _parse_time(appointment.get("endAt")) is None
                or _parse_time(appointment["endAt"]) <= _parse_time(appointment["startAt"])):
            raise DeliveryError(400, "Invalid CRM delivery")
    return payload


def _payload_hash(value) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _delivery_response(payload: dict, student_id: int) -> dict:
    return {
        "messageId": payload["messageId"],
        "junctionStudentId": payload["junctionStudentId"],
        "recipient": "first_touch",
        "status": "accepted",
        "revision": payload["revision"],
        "studentId": student_id,
    }


def _identity(sess: Session, junction_student_id: str):
    return sess.execute(
        select(store.ExternalIdentity).where(
            store.ExternalIdentity.source_system == "junction",
            store.ExternalIdentity.external_student_id == junction_student_id,
        )
    ).scalar_one_or_none()


def _crm_teacher(sess: Session, teacher_id: str):
    try:
        user_id = int(teacher_id)
    except (TypeError, ValueError):
        return None
    user = sess.get(_db.User, user_id)
    if not user or user.role != "advisor" or not user.is_active:
        return None
    return user


def _apply_student_delivery(sess: Session, payload: dict) -> int:
    junction_id = payload["junctionStudentId"]
    revision = int(payload["revision"])
    identity = _identity(sess, junction_id)
    if identity:
        details = _json_details(identity.details)
        if revision <= int(details.get("revision") or 0):
            raise DeliveryError(409, "Stale CRM student revision")
    student = sess.get(_db.Student, identity.student_id) if identity else None
    if identity and not student:
        raise DeliveryError(409, "Student identity unavailable in First Touch")

    if payload["status"] == "active":
        teacher = _crm_teacher(sess, payload["teacherId"])
        if not teacher:
            raise DeliveryError(422, "Assigned teacher unavailable")
        advisor_name = _teacher_advisor_name({
            "advisor_name": teacher.advisor_name,
            "display_name": teacher.display_name,
            "username": teacher.username,
        })
        master = payload["student"]
        if student is None:
            student = _db.Student(
                student_code=_db.next_student_code(sess),
                name=master["name"],
                grade=master.get("grade") or None,
                school=master.get("school") or None,
                phone=master.get("contactPhone") or None,
                advisor_name=advisor_name,
            )
            sess.add(student)
            sess.flush()
        else:
            student.name = master["name"]
            student.grade = master.get("grade") or None
            student.school = master.get("school") or None
            student.phone = master.get("contactPhone") or None
            student.advisor_name = advisor_name
        active = True
    else:
        if student is None:
            raise DeliveryError(409, "Unknown student to revoke")
        student.advisor_name = None
        active = False

    details = json.dumps({
        "grantId": payload["authorization"]["grantId"],
        "revision": revision,
        "active": active,
    }, ensure_ascii=False)
    if identity:
        identity.student_id = student.id
        identity.details = details
        identity.updated_at = datetime.utcnow()
    else:
        sess.add(store.ExternalIdentity(
            student_id=student.id, source_system="junction",
            external_student_id=junction_id, details=details,
        ))

    if not active:
        sess.execute(
            update(store.CrmAppointment)
            .where(store.CrmAppointment.junction_student_id == junction_id,
                   store.CrmAppointment.status == "SCHEDULED")
            .values(status="CANCELLED", updated_at=datetime.utcnow())
        )
    return student.id


def _apply_appointment_delivery(sess: Session, payload: dict) -> int:
    junction_id = payload["junctionStudentId"]
    revision = int(payload["revision"])
    scheduled = payload["status"] == "scheduled"
    identity = _identity(sess, junction_id)
    if not identity:
        raise DeliveryError(
            409, "Student not active under this authorization in First Touch")
    details = _json_details(identity.details)
    if scheduled and (not details.get("active")
                      or details.get("grantId") != payload["authorization"]["grantId"]):
        raise DeliveryError(
            409, "Student not active under this authorization in First Touch")

    student = sess.get(_db.Student, identity.student_id)
    if not student:
        raise DeliveryError(
            409, "Student not active under this authorization in First Touch")

    appointment = payload["appointment"]
    task_id = appointment["taskId"]
    current = sess.get(store.CrmAppointment, task_id)
    if current and current.junction_student_id != junction_id:
        raise DeliveryError(409, "Task ID conflict")
    if current and revision <= current.revision:
        raise DeliveryError(409, "Stale appointment revision")

    if scheduled:
        teacher = _crm_teacher(sess, payload["teacherId"])
        if not teacher:
            raise DeliveryError(422, "Assigned teacher unavailable")
        expected = _teacher_advisor_name({
            "advisor_name": teacher.advisor_name,
            "display_name": teacher.display_name,
            "username": teacher.username,
        })
        if (student.advisor_name or "") != expected:
            raise DeliveryError(409, "Teacher assignment changed")
        values = {
            "junction_student_id": junction_id,
            "student_id": student.id,
            "teacher_id": teacher.id,
            "revision": revision,
            "status": "SCHEDULED",
            "start_at": appointment["startAt"],
            "end_at": appointment["endAt"],
        }
    else:
        if not current:
            raise DeliveryError(409, "Unknown appointment to cancel")
        values = {
            "junction_student_id": junction_id,
            "student_id": student.id,
            "teacher_id": current.teacher_id,
            "revision": revision,
            "status": "CANCELLED",
            "start_at": appointment["startAt"],
            "end_at": appointment["endAt"],
        }
    if current:
        for key, value in values.items():
            setattr(current, key, value)
        current.updated_at = datetime.utcnow()
    else:
        sess.add(store.CrmAppointment(task_id=task_id, **values))
    return student.id


def _receive_delivery(payload) -> dict:
    parsed = parse_delivery(payload)
    digest = _payload_hash(payload)
    prior = store.get_receipt(parsed["messageId"])
    if prior:
        if prior["payload_hash"] != digest:
            raise DeliveryError(409, "Message ID conflict")
        return _delivery_response(parsed, prior["student_id"])

    now = datetime.now(timezone.utc)
    if parsed["status"] in ("active", "scheduled"):
        authorization = parsed["authorization"]
        if (_parse_time(parsed["expiresAt"]) <= now
                or (authorization.get("expiresAt")
                    and _parse_time(authorization["expiresAt"]) <= now)):
            raise DeliveryError(400, "Expired CRM delivery")
    if parsed["status"] == "scheduled":
        if _parse_time(parsed["appointment"]["startAt"]) <= now:
            raise DeliveryError(400, "Appointment has already started")

    last_error = None
    for attempt in range(3):
        try:
            with Session(_db.engine) as sess:
                with sess.begin():
                    existing = sess.get(store.CrmDeliveryReceipt,
                                        parsed["messageId"])
                    if existing:
                        if existing.payload_hash != digest:
                            raise DeliveryError(409, "Message ID conflict")
                        return _delivery_response(parsed, existing.student_id)
                    if parsed["kind"] == "student":
                        student_id = _apply_student_delivery(sess, parsed)
                    else:
                        student_id = _apply_appointment_delivery(sess, parsed)
                    sess.add(store.CrmDeliveryReceipt(
                        message_id=parsed["messageId"],
                        junction_student_id=parsed["junctionStudentId"],
                        kind=parsed["kind"],
                        task_id=(parsed.get("appointment") or {}).get("taskId"),
                        revision=parsed["revision"],
                        payload_hash=digest,
                        student_id=student_id,
                    ))
            return _delivery_response(parsed, student_id)
        except DeliveryError:
            raise
        except (IntegrityError, OperationalError) as exc:
            detail = str(exc).lower()
            if "unique" not in detail and "locked" not in detail:
                raise
            last_error = exc
            if attempt == 2:
                break
    raise DeliveryError(503, "Transaction could not complete") from last_error


@bp.route("/api/integrations/crm/deliveries", methods=["POST"])
def api_crm_deliveries():
    if not _crm_authorized():
        return jsonify({"message": "Unauthorized"}), 401
    try:
        payload = request.get_json(silent=True)
        return jsonify(_receive_delivery(payload))
    except DeliveryError as exc:
        return jsonify({"message": exc.message}), exc.status
    except Exception as exc:  # 未识别异常不泄露内部细节
        print(f"[crm delivery] failed: {exc}", flush=True)
        return jsonify({"message": "Receiver unavailable"}), 500


# ---------------------------------------------------------------------------
# 预约查询（session）
# ---------------------------------------------------------------------------
def _appointment_json(row: dict) -> dict:
    return {
        "taskId": row["task_id"],
        "junctionStudentId": row["junction_student_id"],
        "studentId": row["student_id"],
        "teacherId": str(row["teacher_id"]) if row["teacher_id"] else None,
        "revision": row["revision"],
        "status": row["status"],
        "startAt": row["start_at"],
        "endAt": row["end_at"],
        "updatedAt": row["updated_at"],
    }


@bp.route("/api/crm-appointments", methods=["GET"])
@role_required("admin", "advisor")
def api_crm_appointments():
    teacher_id = None
    if session.get("role") == "advisor":
        try:
            teacher_id = int(session.get("user_id"))
        except (TypeError, ValueError):
            teacher_id = -1
    appointments = [_appointment_json(row)
                    for row in store.list_appointments(teacher_id)]
    return jsonify({"appointments": appointments})


# ---------------------------------------------------------------------------
# 学生导入
# ---------------------------------------------------------------------------
class _ImportConflict(Exception):
    """单条学生无法安全导入（身份/版本/归属冲突）。"""


def _parse_rejected_student(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    if not all(isinstance(value.get(key), str)
               for key in ("id", "name", "reasonCode", "message")):
        return None
    return {key: value[key] for key in ("id", "name", "reasonCode", "message")}


def _master_data_changed(student, upstream: dict) -> bool:
    return (student.name != upstream["name"]
            or (student.grade or "") != upstream["grade"]
            or (student.school or None) != upstream["school"]
            or (student.phone or None) != upstream["phone"])


def _assignment_audit(student: _db.Student, upstream: dict,
                      teacher_user: dict, old_advisor_name: str) -> dict:
    teacher_name = _teacher_advisor_name(teacher_user)
    changed = (old_advisor_name or "") != teacher_name
    return {
        "source": "YUGUO",
        "upstreamStudentId": upstream["id"],
        "assignmentVersion": upstream["assignmentVersion"],
        "teacherId": str(teacher_user.get("id")),
        "teacherName": teacher_name,
        "removedTeacherId": (_user_id_by_advisor_name(old_advisor_name)
                             if changed else None),
        "removedTeacherName": old_advisor_name or None,
        "studentName": student.name,
        "ownershipChanged": changed,
    }


def _import_one(upstream: dict, teacher_user: dict) -> str:
    teacher_name = _teacher_advisor_name(teacher_user)
    source_id = upstream["id"]
    with Session(_db.engine) as sess:
        with sess.begin():
            identity = sess.execute(
                select(store.ExternalIdentity).where(
                    store.ExternalIdentity.source_system == "yuguo",
                    store.ExternalIdentity.external_student_id == source_id,
                )
            ).scalar_one_or_none()
            if identity:
                student = sess.get(_db.Student, identity.student_id)
                if not student:
                    raise _ImportConflict()
                ambiguous = sess.execute(
                    select(store.ExternalIdentity.id).where(
                        store.ExternalIdentity.student_id == student.id,
                        store.ExternalIdentity.source_system == "yuguo",
                        store.ExternalIdentity.external_student_id != source_id,
                    )
                ).first()
                if ambiguous:
                    raise _ImportConflict()
                details = _json_details(identity.details)
                stored_version = int(details.get("assignmentVersion") or 0)
                stored_teacher = str(details.get("teacherId") or "")
                if upstream["assignmentVersion"] < stored_version:
                    raise _ImportConflict()
                if (upstream["assignmentVersion"] == stored_version
                        and stored_teacher
                        and stored_teacher != upstream["teacherId"]):
                    raise _ImportConflict()
                old_name = (student.advisor_name or "").strip()
                if not old_name:
                    action = "attach"
                elif old_name != teacher_name:
                    raise _ImportConflict()
                else:
                    action = ("refresh" if _master_data_changed(student, upstream)
                              else "current")
                if action in ("attach", "refresh"):
                    student.name = upstream["name"]
                    student.grade = upstream["grade"]
                    student.school = upstream["school"]
                    student.phone = upstream["phone"]
                    if action == "attach":
                        student.advisor_name = teacher_name
                identity.student_id = student.id
                identity.details = json.dumps({
                    "assignmentVersion": upstream["assignmentVersion"],
                    "teacherId": upstream["teacherId"],
                    "teacherName": teacher_name,
                }, ensure_ascii=False)
                identity.updated_at = datetime.utcnow()
            else:
                student = _db.Student(
                    student_code=_db.next_student_code(sess),
                    name=upstream["name"],
                    grade=upstream["grade"],
                    school=upstream["school"],
                    phone=upstream["phone"],
                    advisor_name=teacher_name,
                )
                sess.add(student)
                sess.flush()
                sess.add(store.ExternalIdentity(
                    student_id=student.id, source_system="yuguo",
                    external_student_id=source_id,
                    details=json.dumps({
                        "assignmentVersion": upstream["assignmentVersion"],
                        "teacherId": upstream["teacherId"],
                        "teacherName": teacher_name,
                    }, ensure_ascii=False),
                ))
                action = "create"
                old_name = ""

            if action != "current":
                sess.add(store.AuditLog(
                    actor_id=teacher_user.get("id"), student_id=student.id,
                    action=_ASSIGNMENT_ACTION,
                    details=json.dumps(_assignment_audit(
                        student, upstream, teacher_user, old_name),
                        ensure_ascii=False),
                ))
            sess.add(store.AuditLog(
                actor_id=teacher_user.get("id"), student_id=student.id,
                action=_IMPORT_ACTION,
                details=json.dumps({"studentId": source_id, "action": action},
                                   ensure_ascii=False),
            ))
            return action


def import_yuguo_students(teacher_user: dict, payload: dict) -> dict:
    """逐条短事务导入 Yuguo 学生（单条失败不影响其他学生）。

    ``assignmentVersion`` 存于 ``external_identities.details``（JSON），
    因为本平台 students 表没有该列；身份定位只用 ``source_system='yuguo'``
    的外部 ID，姓名与手机号不参与匹配合并。
    """
    if not isinstance(payload, dict):
        raise ValueError("Yuguo 返回数据不兼容")
    raw_students = payload.get("students")
    raw_rejected = payload.get("rejectedStudents") or []
    if not isinstance(raw_students, list) or not isinstance(raw_rejected, list):
        raise ValueError("Yuguo 返回数据不兼容")
    rejected = []
    for item in raw_rejected:
        parsed_rejected = _parse_rejected_student(item)
        if parsed_rejected is None:
            raise ValueError("Yuguo 返回数据不兼容")
        rejected.append(parsed_rejected)

    created = attached = refreshed = already = conflicts = failed = 0
    for raw in raw_students:
        upstream = None
        raw_id = raw.get("id", "") if isinstance(raw, dict) else ""
        raw_name = raw.get("name", "") if isinstance(raw, dict) else ""
        try:
            upstream = parse_yuguo_student(raw)
            if upstream["teacherId"] != str(teacher_user.get("id")):
                raise _ImportConflict()
            action = _import_one(upstream, teacher_user)
        except _ImportConflict:
            conflicts += 1
            rejected.append({
                "id": upstream["id"] if upstream else str(raw_id),
                "name": upstream["name"] if upstream else str(raw_name),
                "reasonCode": "LOCAL_CONFLICT",
                "message": _CONFLICT_MESSAGE,
            })
        except Exception as exc:
            failed += 1
            print(f"[yuguo import] local write failed: {exc}", flush=True)
            rejected.append({
                "id": upstream["id"] if upstream else str(raw_id),
                "name": upstream["name"] if upstream else str(raw_name),
                "reasonCode": "LOCAL_IMPORT_FAILED",
                "message": _FAILED_MESSAGE,
            })
        else:
            if action == "create":
                created += 1
            elif action == "attach":
                attached += 1
            elif action == "refresh":
                refreshed += 1
            else:
                already += 1

    success = created + attached + refreshed + already
    if failed or conflicts or raw_rejected:
        status = "PARTIAL" if success else "FAILED"
    else:
        status = "COMPLETED"
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    fetched = summary.get("assigned")
    if not isinstance(fetched, int):
        fetched = len(raw_students) + len(raw_rejected)
    return {
        "localImport": {
            "status": status,
            "fetched": fetched,
            "eligible": len(raw_students),
            "created": created,
            "attached": attached,
            "refreshed": refreshed,
            "alreadyLocal": already,
            "conflicts": conflicts,
            "rejected": len(rejected),
        },
        "rejectedStudents": rejected,
    }


# ---------------------------------------------------------------------------
# 改派同步（15s 节流）
# ---------------------------------------------------------------------------
def _apply_upstream_assignment(upstream: dict, users_by_id: dict) -> None:
    identity = store.get_external_identity("yuguo", upstream["id"])
    if not identity:
        return
    student = _db.get_student(identity["student_id"])
    if not student:
        return
    details = _json_details(identity["details"])
    stored_version = int(details.get("assignmentVersion") or 0)
    stored_teacher = str(details.get("teacherId") or "")
    incoming_version = upstream["assignmentVersion"]
    if incoming_version < stored_version:
        return
    if (incoming_version == stored_version and stored_teacher
            and stored_teacher != upstream["teacherId"]):
        print(f"[yuguo sync] contradictory assignment for {upstream['id']}",
              flush=True)
        return
    teacher_user = users_by_id.get(str(upstream["teacherId"]))
    if not teacher_user:
        return
    new_name = _teacher_advisor_name(teacher_user)
    old_name = (student.get("advisor_name") or "").strip()
    changed = old_name != new_name
    if incoming_version == stored_version and not changed:
        return

    with Session(_db.engine) as sess:
        with sess.begin():
            sess.execute(
                update(_db.Student).where(_db.Student.id == student["id"])
                .values(advisor_name=new_name)
            )
            sess.execute(
                update(store.ExternalIdentity)
                .where(store.ExternalIdentity.id == identity["id"])
                .values(details=json.dumps({
                    "assignmentVersion": incoming_version,
                    "teacherId": str(teacher_user["id"]),
                    "teacherName": new_name,
                }, ensure_ascii=False), updated_at=datetime.utcnow())
            )
            sess.add(store.AuditLog(
                actor_id=None, student_id=student["id"],
                action=_ASSIGNMENT_ACTION,
                details=json.dumps({
                    "source": "YUGUO",
                    "upstreamStudentId": upstream["id"],
                    "assignmentVersion": incoming_version,
                    "teacherId": str(teacher_user["id"]),
                    "teacherName": new_name,
                    "removedTeacherId": (_user_id_by_advisor_name(old_name)
                                         if changed else None),
                    "removedTeacherName": old_name or None,
                    "studentName": student["name"],
                    "ownershipChanged": changed,
                }, ensure_ascii=False),
            ))


def reconcile_yuguo_assignments(force: bool = False) -> None:
    """批量核对 Yuguo 分配版本；所有异常只记录，不影响本地功能。"""
    global _last_sync_at
    now = time.monotonic()
    if not force and now - _last_sync_at < _SYNC_INTERVAL_SECONDS:
        return
    _last_sync_at = now
    try:
        teachers = [user for user in _db.list_users()
                    if user.get("role") == "advisor" and user.get("is_active")]
    except Exception as exc:
        print(f"[yuguo sync] teacher list failed: {exc}", flush=True)
        return

    current = {}
    contradictory = set()
    for index in range(0, len(teachers), 4):
        for user in teachers[index:index + 4]:
            try:
                payload = fetch_students_for_teacher(str(user["id"]))
            except Exception as exc:
                print(f"[yuguo sync] fetch failed for {user['id']}: {exc}",
                      flush=True)
                continue
            for student in payload.get("students", []):
                previous = current.get(student["id"])
                if (previous
                        and previous["assignmentVersion"] == student["assignmentVersion"]
                        and previous["teacherId"] != student["teacherId"]):
                    contradictory.add(student["id"])
                if (previous is None
                        or previous["assignmentVersion"] < student["assignmentVersion"]):
                    current[student["id"]] = student

    users_by_id = {str(user["id"]): user for user in teachers}
    for student_id, upstream in current.items():
        if student_id in contradictory:
            continue
        try:
            _apply_upstream_assignment(upstream, users_by_id)
        except Exception as exc:
            print(f"[yuguo sync] apply failed for {student_id}: {exc}",
                  flush=True)


# ---------------------------------------------------------------------------
# 改派通知
# ---------------------------------------------------------------------------
def assignment_notices_for(advisor_name: str) -> list[dict]:
    advisor_name = (advisor_name or "").strip()
    if not advisor_name:
        return []
    with Session(_db.engine) as sess:
        rows = sess.execute(text("""
            SELECT a.id, a.student_id, a.details
            FROM audit_log a
            LEFT JOIN students s ON s.id = a.student_id
            WHERE a.action = :action
              AND json_extract(a.details, '$.removedTeacherName') = :name
              AND json_extract(a.details, '$.ownershipChanged') IN (1, 'true')
              AND COALESCE(s.advisor_name, '') != :name
              AND NOT EXISTS (
                  SELECT 1 FROM audit_log r
                  WHERE r.action = :read_action
                    AND json_extract(r.details, '$.eventId') = a.id
                    AND json_extract(r.details, '$.advisorName') = :name
              )
            ORDER BY a.id ASC LIMIT 20
        """), {"action": _ASSIGNMENT_ACTION, "read_action": _NOTICE_READ_ACTION,
               "name": advisor_name}).all()
    notices = []
    for row in rows:
        details = _json_details(row.details)
        notices.append({
            "id": row.id,
            "studentId": row.student_id,
            "studentName": details.get("studentName") or "",
            "teacherName": details.get("teacherName") or "",
            "sessionIds": [],
        })
    return notices


def acknowledge_assignment_notice(notice_id: int, advisor_name: str,
                                  *, actor_id=None) -> None:
    advisor_name = (advisor_name or "").strip()
    with Session(_db.engine) as sess:
        with sess.begin():
            event = sess.get(store.AuditLog, int(notice_id))
            details = _json_details(event.details) if event else {}
            if (not event or event.action != _ASSIGNMENT_ACTION
                    or details.get("removedTeacherName") != advisor_name):
                raise store.NotFoundError("通知不存在")
            existing = sess.execute(
                select(store.AuditLog.id).where(
                    store.AuditLog.action == _NOTICE_READ_ACTION,
                    store.AuditLog.actor_id == actor_id,
                )
            ).scalars().all()
            for read_id in existing:
                row = sess.get(store.AuditLog, read_id)
                read_details = _json_details(row.details) if row else {}
                if (str(read_details.get("eventId")) == str(event.id)
                        and read_details.get("advisorName") == advisor_name):
                    return
            sess.add(store.AuditLog(
                actor_id=actor_id, student_id=event.student_id,
                action=_NOTICE_READ_ACTION,
                details=json.dumps({"eventId": str(event.id),
                                    "advisorName": advisor_name},
                                   ensure_ascii=False),
            ))


def _access_revision(advisor_name: str):
    advisor_name = (advisor_name or "").strip()
    if not advisor_name:
        return None
    with Session(_db.engine) as sess:
        row = sess.execute(text("""
            SELECT MAX(a.id) FROM audit_log a
            WHERE a.action = :action
              AND json_extract(a.details, '$.ownershipChanged') IN (1, 'true')
              AND (json_extract(a.details, '$.removedTeacherName') = :name
                   OR json_extract(a.details, '$.teacherName') = :name)
        """), {"action": _ASSIGNMENT_ACTION, "name": advisor_name}).scalar()
    return row


def _notices_payload(advisor_name: str) -> dict:
    return {"accessRevision": _access_revision(advisor_name),
            "notices": assignment_notices_for(advisor_name)}


# ---------------------------------------------------------------------------
# session 路由：导入 / 改派同步
# ---------------------------------------------------------------------------
@bp.route("/students/import-yuguo", methods=["POST"])
@role_required("advisor")
def api_import_yuguo():
    user = _db.get_user_by_id(session.get("user_id")) or {}
    teacher_user = {
        "id": user.get("id"),
        "role": user.get("role"),
        "advisor_name": user.get("advisor_name"),
        "display_name": user.get("display_name"),
        "username": user.get("username"),
    }
    if not teacher_user["id"]:
        return _error("未登录", 401)
    try:
        payload = fetch_students_for_teacher(str(teacher_user["id"]))
    except YuguoError as exc:
        return _error(exc.message, exc.status)
    try:
        result = import_yuguo_students(teacher_user, payload)
    except ValueError as exc:
        return _error(str(exc), 503)
    return jsonify(result)


@bp.route("/api/account/assignment-sync", methods=["POST"])
@role_required("admin", "advisor")
def api_assignment_sync():
    advisor_name = (session.get("advisor_name") or "").strip()
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    if "acknowledge" in body:
        event_id = body.get("acknowledge")
        if not isinstance(event_id, str) or not event_id or len(event_id) > 128:
            return _error("通知参数无效", 400)
        try:
            acknowledge_assignment_notice(int(event_id), advisor_name,
                                          actor_id=session.get("user_id"))
        except (TypeError, ValueError):
            return _error("通知参数无效", 400)
        except store.NotFoundError as exc:
            return _error(str(exc) or "通知不存在", 404)
    else:
        reconcile_yuguo_assignments()
    response = jsonify(_notices_payload(advisor_name))
    response.headers["Cache-Control"] = "no-store"
    return response
