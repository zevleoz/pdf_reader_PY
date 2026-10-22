"""出站调用 Yuguo 的 HTTP 客户端（学生导出读取、导师目录推送）。

与源仓库 ``lib/yuguo.ts`` / ``lib/yuguo-teacher-directory.ts`` 对齐：
- ``Authorization: Bearer <token>``；读取学生时额外带 ``X-First-Touch-Teacher``；
- 10 秒超时；上游 401/404/超时/连接失败映射为固定中文文案；
- 返回结构在客户端内完成形状与摘要一致性校验，不把脏数据交给导入层。

环境变量（见 docs/deployment_env.md）：
``YUGUO_BASE_URL``、``YUGUO_STUDENT_READ_TOKEN``、``FIRST_TOUCH_DIRECTORY_TOKEN``。

本模块禁止 import app / blueprints（gtjob 子进程会间接 import 本包）。
"""
from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_TIMEOUT = 10
_PHONE_RE = re.compile(r"^\+[1-9]\d{5,39}$")


class YuguoError(Exception):
    """Yuguo 出站调用失败。路由层统一映射为 503（Yuguo 不可用不影响本地功能）。"""

    def __init__(self, message: str, *, status: int = 503):
        super().__init__(message)
        self.message = message
        self.status = status


def _base_url(*, purpose: str = "Yuguo 导入尚未配置") -> str:
    base = (os.environ.get("YUGUO_BASE_URL") or "").strip()
    if not base:
        raise YuguoError(purpose)
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise YuguoError("Yuguo 导入地址配置无效，请联系管理员检查生产环境配置")
    return base.rstrip("/")


def _http_error_message(error: urllib.error.HTTPError) -> str:
    if error.code in (401, 403):
        return "Yuguo 凭证不一致"
    if error.code == 404:
        return "Yuguo 接口尚未部署"
    if error.code >= 500:
        return f"Yuguo 学生接口当前不可用（HTTP {error.code}）"
    return f"Yuguo 返回 HTTP {error.code}"


def _request_json(request: urllib.request.Request) -> Any:
    """执行请求并解析 JSON；所有网络异常统一转 ``YuguoError``。"""
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        raise YuguoError(_http_error_message(error)) from error
    except (TimeoutError, socket.timeout) as error:
        raise YuguoError("Yuguo 连接超时") from error
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", None)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise YuguoError("Yuguo 连接超时") from error
        raise YuguoError("无法连接 Yuguo") from error
    except OSError as error:
        raise YuguoError("无法连接 Yuguo") from error
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise YuguoError("Yuguo 返回数据不兼容，请联系管理员完成配套发布") from error


def parse_yuguo_student(value: Any) -> dict:
    """校验并规范化单条 Yuguo 学生 DTO（字段规则 1:1 移植源仓库）。"""
    if not isinstance(value, dict):
        raise ValueError("Invalid Yuguo student")
    student_id = str(value.get("id") or "").strip()
    name = str(value.get("name") or "").strip()
    grade = str(value.get("grade") or "").strip()
    school = str(value.get("school") or "").strip() or None
    phone_value = str(value.get("phone") or "").strip()
    phone = phone_value if _PHONE_RE.match(phone_value) else None
    teacher_id = str(value.get("teacherId") or "").strip()
    version = value.get("assignmentVersion")
    if (not student_id or len(student_id) > 128
            or not name or len(name) > 200
            or not grade or len(grade) > 100
            or (school is not None and len(school) > 300)
            or not teacher_id or len(teacher_id) > 128
            or isinstance(version, bool) or not isinstance(version, int)
            or version < 1):
        raise ValueError("Invalid Yuguo student")
    return {
        "id": student_id, "name": name, "grade": grade, "school": school,
        "phone": phone, "teacherId": teacher_id, "assignmentVersion": version,
    }


def _parse_rejected_student(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    if not all(isinstance(value.get(key), str)
               for key in ("id", "name", "reasonCode", "message")):
        return None
    return {key: value[key] for key in ("id", "name", "reasonCode", "message")}


def _parse_summary(value: Any, students: list[dict],
                   rejected: list[dict]) -> dict:
    if not isinstance(value, dict):
        return {"assigned": len(students) + len(rejected),
                "exportable": len(students), "rejected": len(rejected)}
    numbers = (value.get("assigned"), value.get("exportable"),
               value.get("rejected"))
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0
           for item in numbers):
        raise ValueError("Invalid Yuguo summary")
    if (numbers[1] != len(students) or numbers[2] != len(rejected)
            or numbers[0] != len(students) + len(rejected)):
        raise ValueError("Invalid Yuguo summary")
    return {"assigned": numbers[0], "exportable": numbers[1],
            "rejected": numbers[2]}


def fetch_students_for_teacher(teacher_key: str) -> dict:
    """拉取某位导师在 Yuguo 名下可导入的学生。

    ``teacher_key`` 为本平台 user id 的字符串形式，通过
    ``X-First-Touch-Teacher`` 传给 Yuguo。返回
    ``{students, rejectedStudents, summary}``，所有学生都已通过 DTO 校验。
    """
    teacher_key = str(teacher_key or "").strip()
    if not teacher_key or len(teacher_key) > 128:
        raise YuguoError("Yuguo 导入参数无效")
    token = (os.environ.get("YUGUO_STUDENT_READ_TOKEN") or "").strip()
    if not token:
        raise YuguoError("Yuguo 导入尚未配置")
    base = _base_url()
    request = urllib.request.Request(
        f"{base}/api/integrations/first-touch/students",
        headers={"Authorization": f"Bearer {token}",
                 "X-First-Touch-Teacher": teacher_key},
        method="GET",
    )
    result = _request_json(request)
    if not isinstance(result, dict):
        raise YuguoError("Yuguo 的学生导入数据版本不兼容，请联系管理员完成配套发布")
    raw_students = result.get("students")
    raw_rejected = result.get("rejectedStudents")
    if not isinstance(raw_students, list) or not isinstance(raw_rejected, list):
        raise YuguoError("Yuguo 的学生导入数据版本不兼容，请联系管理员完成配套发布")
    try:
        students = [parse_yuguo_student(item) for item in raw_students]
        if any(item["teacherId"] != teacher_key for item in students):
            raise ValueError("Teacher mismatch")
        rejected = [_parse_rejected_student(item) for item in raw_rejected]
        if any(item is None for item in rejected):
            raise ValueError("Invalid rejected student")
        summary = _parse_summary(result.get("summary"), students, rejected)
    except ValueError as error:
        raise YuguoError("Yuguo 的学生导入数据版本不兼容，请联系管理员完成配套发布") from error
    return {"students": students, "rejectedStudents": rejected,
            "summary": summary}


def push_teacher_directory(teachers: list[dict]) -> dict:
    """全量推送启用 Advisor 快照到 Yuguo，返回 ``{active, deactivated, reconciled}``。"""
    base = _base_url(purpose="Yuguo 导师目录同步尚未配置")
    token = (os.environ.get("FIRST_TOUCH_DIRECTORY_TOKEN") or "").strip()
    if not token or len(token) < 32:
        raise YuguoError("Yuguo 导师目录同步尚未配置")
    body = json.dumps({"teachers": teachers}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/api/integrations/first-touch/teachers",
        data=body, method="PUT",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    result = _request_json(request)
    if not isinstance(result, dict):
        raise YuguoError("Yuguo 返回数据不兼容，请联系管理员完成配套发布")
    values = (result.get("active"), result.get("deactivated"),
              result.get("reconciled"))
    if any(isinstance(item, bool) or not isinstance(item, int) for item in values):
        raise YuguoError("Yuguo 返回数据不兼容，请联系管理员完成配套发布")
    return {"active": values[0], "deactivated": values[1],
            "reconciled": values[2]}
