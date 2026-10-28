"""M1 资料来源装配：自动来源（Y4 / First Touch / 补充问卷）与导师上传。

自动来源不落 ``m1_sources``，每次读取现算；导师上传/粘贴的家长反馈、Case
Review、其他资料与补充 First Touch 才入表并保存文件。

会议日期不自动写入 prep：文字里出现会议日期时只作为
``suggested_meeting_date`` 提示返回，由导师在界面确认。
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

import db as _db
import growth_talk_store as _gt
import questionnaire_store as _qs
from app_utils import BASE_DIR, DATA_DIR
from growth_talk.upload import UploadError, extract_upload

import m1.store as store

UPLOAD_ROOT = DATA_DIR / "m1_uploads"

_ISO_DATE_RE = re.compile(r"(20\d{2})[-/.年]\s?(\d{1,2})[-/.月]\s?(\d{1,2})")
_CN_DATE_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
_MEETING_HINT_RE = re.compile(r"(会议|会谈|面谈|会面|First\s*Meeting|沟通|访谈)")
_HINT_WINDOW = 12


# ---------------------------------------------------------------------------
# 自动来源
# ---------------------------------------------------------------------------
def _y4(student_id: int) -> Dict[str, Any]:
    """Y4 证据（P1）。P1 尚未落地时返回不完整快照，不让页面崩。"""
    try:
        from m1.y4_evidence import build_y4_evidence
    except ImportError:
        return {"report_id": None, "date": "", "items": [], "six_am": None,
                "complete": False}
    return build_y4_evidence(int(student_id))


def _first_touch(student_id: int) -> Dict[str, Any]:
    """最近一次 First Touch 会谈记录：日期 + 供生成用的原文摘要。"""
    with Session(store._engine()) as sess:
        row = sess.execute(
            select(_gt.CopilotSession)
            .where(_gt.CopilotSession.student_id == int(student_id),
                   _gt.CopilotSession.status != "ARCHIVED")
            .order_by(_gt.CopilotSession.updated_at.desc(),
                      _gt.CopilotSession.id.desc())
        ).scalars().first()
        session_id = row.id if row else None
    if not session_id:
        return {"present": False, "date": "", "text": "", "session_id": None}

    data = _gt.get_session(session_id) or {}
    lines: List[str] = []
    meeting_at = data.get("meeting_at") or ""
    if meeting_at:
        lines.append("会谈时间：%s" % meeting_at)
    script = data.get("script") if isinstance(data.get("script"), dict) else {}
    for key, value in script.items():
        if isinstance(value, list):
            value = "；".join(str(item) for item in value if str(item).strip())
        if str(value or "").strip():
            lines.append("会前要点（%s）：%s" % (key, str(value).strip()))
    for item in data.get("interests") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        extra = [str(item.get(key) or "").strip()
                 for key in ("evidence", "note") if str(item.get(key) or "").strip()]
        lines.append("兴趣事项：%s%s" % (label, ("（%s）" % "；".join(extra)) if extra else ""))
    calibration = data.get("calibration") or {}
    if isinstance(calibration, dict):
        for key, label in (("careerInterests", "职业兴趣"), ("abilityTendencies", "能力倾向"),
                           ("valuePreferences", "价值偏好"), ("notes", "校准备注")):
            value = str(calibration.get(key) or "").strip()
            if value:
                lines.append("%s：%s" % (label, value))
    for note in data.get("notes") or []:
        if isinstance(note, dict) and str(note.get("note") or "").strip():
            lines.append("兴趣备注：%s" % str(note["note"]).strip())
    for supplement in data.get("supplements") or []:
        if not isinstance(supplement, dict):
            continue
        analysis = supplement.get("analysis")
        if isinstance(analysis, dict):
            summary = (analysis.get("summary") or analysis.get("text")
                       or json.dumps(analysis, ensure_ascii=False))
        else:
            summary = analysis
        if str(summary or "").strip():
            lines.append("补充材料：%s" % str(summary).strip())

    return {
        "present": True,
        "date": (data.get("meeting_at") or data.get("created_at") or "")[:10],
        "text": "\n".join(lines),
        "session_id": session_id,
    }


def _answer_text(question: dict, value) -> str:
    if value is None or value == "" or value == []:
        return ""
    qtype = question.get("type") or "single"
    options = {str(opt.get("value")): str(opt.get("label") or opt.get("value"))
               for opt in (question.get("options") or []) if isinstance(opt, dict)}
    if qtype == "multi":
        values = value if isinstance(value, list) else [value]
        return "、".join(options.get(str(v), str(v)) for v in values)
    if qtype == "single" and options:
        return options.get(str(value), str(value))
    return str(value)


def _questionnaire_rows(student_id: int) -> List[Dict[str, Any]]:
    """题库逐份问卷一行：已完成 / 未取得 / 未触发，答案按 dimension 分组。"""
    assignments = _qs.list_assignments_for_student(int(student_id))
    by_qid: Dict[int, Dict[str, Any]] = {}
    for assignment in assignments:
        qid = assignment.get("questionnaire_id")
        if qid is not None and qid not in by_qid:
            by_qid[int(qid)] = assignment

    rows: List[Dict[str, Any]] = []
    for questionnaire in _qs.list_questionnaires(active_only=True):
        qid = int(questionnaire["id"])
        assignment = by_qid.get(qid)
        row = {
            "code": questionnaire.get("code") or "",
            "title": questionnaire.get("title") or "",
            "status": "未触发",
            "status_text": "未触发",
            "date": "",
            "assignment_id": assignment.get("id") if assignment else None,
            "answers": [],
            "by_dimension": {},
        }
        if not assignment:
            rows.append(row)
            continue
        response = (_qs.get_response(assignment["id"])
                    if assignment.get("status") == "submitted" else None)
        if not response:
            row["status"] = "未取得"
            row["status_text"] = "未取得"
            row["date"] = (assignment.get("submitted_at")
                           or assignment.get("created_at") or "")[:10]
            rows.append(row)
            continue

        full = _qs.get_questionnaire(qid, with_schema=True) or {}
        schema = full.get("schema") or {}
        answers = response.get("answers") or {}
        by_dimension: Dict[str, List[Dict[str, str]]] = {}
        collected: List[Dict[str, str]] = []
        for question in schema.get("questions") or []:
            if not isinstance(question, dict):
                continue
            qid_text = str(question.get("id") or "")
            text = _answer_text(question, answers.get(qid_text))
            if not text:
                continue
            item = {"question": str(question.get("title") or qid_text), "answer": text}
            dimension = str(question.get("dimension") or "").strip() or "未分类"
            by_dimension.setdefault(dimension, []).append(item)
            collected.append(dict(item, dimension=dimension))
        row.update({
            "status": "已完成",
            "status_text": "已完成",
            "date": (response.get("created_at") or "")[:10],
            "answers": collected,
            "by_dimension": by_dimension,
        })
        rows.append(row)
    return rows


def auto_sources(student_id: int) -> Dict[str, Any]:
    """自动来源汇总：``y4`` / ``first_touch`` / ``questionnaires``。"""
    return {
        "y4": _y4(student_id),
        "first_touch": _first_touch(student_id),
        "questionnaires": _questionnaire_rows(student_id),
    }


# ---------------------------------------------------------------------------
# 日期识别
# ---------------------------------------------------------------------------
def detect_date(*texts) -> str:
    """从文件名/正文里找第一个日期，返回 ``YYYY-MM-DD``（找不到返回空串）。"""
    for text in texts:
        blob = str(text or "")
        match = _ISO_DATE_RE.search(blob)
        if match:
            year, month, day = (int(x) for x in match.groups())
            try:
                return date(year, month, day).isoformat()
            except ValueError:
                continue
        match = _CN_DATE_RE.search(blob)
        if match:
            month, day = (int(x) for x in match.groups())
            try:
                return date(date.today().year, month, day).isoformat()
            except ValueError:
                continue
    return ""


def suggested_meeting_date(*texts) -> str:
    """正文里「会议/会谈 + 日期」的提示，供界面预填（不自动写入 prep）。"""
    for text in texts:
        blob = str(text or "")
        for hint in _MEETING_HINT_RE.finditer(blob):
            tail = blob[hint.end():hint.end() + 24]
            found = detect_date(tail)
            if found:
                return found
            head = blob[max(0, hint.start() - _HINT_WINDOW):hint.start()]
            found = detect_date(head)
            if found:
                return found
    return ""


def _text_status(text: str) -> str:
    return "ok" if len((text or "").strip()) >= 60 else "partial"


# ---------------------------------------------------------------------------
# 上传 / 粘贴
# ---------------------------------------------------------------------------
def prep_upload_dir(prep_id: int) -> Path:
    return UPLOAD_ROOT / str(int(prep_id))


def _safe_extension(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix or "") else ""


def _assert_outside_static(path: Path) -> None:
    try:
        path.resolve().relative_to((BASE_DIR / "static").resolve())
    except ValueError:
        return
    raise ValueError("上传目录不能位于 static 下")


def add_upload(prep_id: int, filename: str, data: bytes, category: str,
               user=None) -> Dict[str, Any]:
    """提取文本并保存上传文件（``data/m1_uploads/<prep_id>/``，不在 static 下）。"""
    text = extract_upload(filename or "", data)       # 失败抛 UploadError（保留原文案）
    target_dir = prep_upload_dir(prep_id)
    _assert_outside_static(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    stored = target_dir / ("%s%s" % (uuid.uuid4().hex[:16], _safe_extension(filename)))
    stored.write_bytes(data)

    detected = detect_date(filename, text)
    source = store.add_source(
        prep_id, category=category, label=(Path(filename or "").stem or "资料"),
        filename=filename or "", stored_path=str(stored), text=text,
        detected_date=detected, status=_text_status(text),
        uploaded_by=_user_id(user),
    )
    source["suggested_meeting_date"] = suggested_meeting_date(text)
    return source


def add_text(prep_id: int, text: str, category: str, user=None) -> Dict[str, Any]:
    """粘贴文字存为一条资料。"""
    cleaned = (text or "").strip()
    if not cleaned:
        raise UploadError(400, "请先粘贴资料内容")
    source = store.add_source(
        prep_id, category=category, label="粘贴文字",
        filename="", stored_path="", text=cleaned,
        detected_date=detect_date(cleaned), status=_text_status(cleaned),
        uploaded_by=_user_id(user),
    )
    source["suggested_meeting_date"] = suggested_meeting_date(cleaned)
    return source


def remove_upload_file(stored_path: str) -> None:
    """删除资料时清理其落盘文件（仅限上传根目录内）。"""
    if not stored_path:
        return
    path = Path(stored_path)
    try:
        path.resolve().relative_to(UPLOAD_ROOT.resolve())
    except ValueError:
        return
    try:
        path.unlink()
    except OSError:
        pass


def _user_id(user) -> Optional[int]:
    if user is None:
        return None
    if isinstance(user, dict):
        return user.get("user_id")
    return getattr(user, "id", None)
