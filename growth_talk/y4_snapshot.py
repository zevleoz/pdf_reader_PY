"""Y4 报告快照：判断“完整 Y4”、生成三步会谈所需的纯数据快照。

本模块不依赖 LLM，输出只由报告内容决定，便于在创建会谈时预填、在读取时
按需重建。Y4 报告存放在 ``reports`` 表，``data_json`` 形如
``{"student": {...}, "schema_124": [{"code": "072", "value": "SAE", ...}]}``，
其中的值均为字符串。
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

import data_points
import db as _db

RIASEC_ORDER = (
    ("R", "073", "现实型"),
    ("I", "074", "研究型"),
    ("A", "075", "艺术型"),
    ("S", "076", "社会型"),
    ("E", "077", "事业型"),
    ("C", "078", "常规型"),
)

TOPIC_TOPICS = {
    "R": ["机械", "动手制作", "户外运动"],
    "I": ["科学实验", "编程", "数学探究"],
    "A": ["绘画", "音乐", "写作"],
    "S": ["志愿服务", "辩论", "心理话题"],
    "E": ["社团组织", "商业挑战", "演讲"],
    "C": ["数据整理", "财务规划", "规划类比赛"],
}

HOLAND_LABELS = {key: label for key, _code, label in RIASEC_ORDER}
_HOLLAND_LETTERS = set(HOLAND_LABELS)


def _schema_items(report) -> list[dict]:
    raw = getattr(report, "data_json", None)
    if isinstance(raw, dict):
        payload = raw
    else:
        try:
            payload = json.loads(raw or "{}")
        except (TypeError, ValueError):
            payload = {}
    items = payload.get("schema_124") if isinstance(payload, dict) else None
    return items if isinstance(items, list) else []


def _by_code(items: list[dict]) -> dict:
    result = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", "")).strip()
        if code:
            result[code] = item.get("value")
    return result


def _number(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _is_complete(values: dict) -> bool:
    if not _text(values.get("072")):
        return False
    numeric = sum(
        1 for code in ("073", "074", "075", "076", "077", "078")
        if _number(values.get(code)) is not None
    )
    return numeric >= 4


def is_complete(report) -> bool:
    """报告是否包含完整的 Y4 数据（兴趣代码 + 至少 4 项 RIASEC 分数）。"""
    return _is_complete(_by_code(_schema_items(report)))


def latest_complete_y4(student_id: int):
    """该学生最新一份完整 Y4 报告；按报告日期、再按 id 倒序判断。"""
    with Session(_db.engine) as sess:
        rows = sess.execute(
            select(_db.Report)
            .where(_db.Report.student_id == int(student_id))
            .order_by(_db.Report.report_date.desc(), _db.Report.id.desc())
        ).scalars().all()
    for row in rows:
        if is_complete(row):
            return row
    return None


def _code_label(code: str, prefix: str) -> str:
    meta = data_points.POINT_META.get(code) or {}
    label = str(meta.get("label") or "")
    if label.startswith(prefix):
        return label[len(prefix):]
    return label


def _score_rows(items: list[dict], prefix: str, low: int, high: int) -> list[dict]:
    """按 schema 顺序取区间内的数值项（同分时顺序即 schema 顺序）。"""
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", "")).strip()
        if not code.isdigit() or not low <= int(code) <= high:
            continue
        meta = data_points.POINT_META.get(code) or {}
        if meta.get("type") != "number":
            continue
        label = _code_label(code, prefix)
        if not label or label.startswith("排序"):
            continue
        score = _number(item.get("value"))
        if score is None:
            continue
        rows.append({"label": label, "score": score})
    return rows


def _holland_code(value) -> str:
    letters = []
    for char in str(value or "").upper():
        if char in _HOLLAND_LETTERS and char not in letters:
            letters.append(char)
    return "".join(letters)


def _topic_suggestions(holland_code: str) -> list[str]:
    topics: list[str] = []
    for letter in holland_code[:2]:
        for topic in TOPIC_TOPICS.get(letter, []):
            if topic not in topics:
                topics.append(topic)
    return topics[:6]


def build_snapshot(report) -> dict:
    """由一份 Y4 报告生成确定性的快照（无 AI、无数据库写入）。"""
    items = _schema_items(report)
    values = _by_code(items)
    holland_code = _holland_code(values.get("072"))

    riasec = []
    for key, code, fallback_label in RIASEC_ORDER:
        riasec.append({
            "key": key,
            "label": _code_label(code, "职业兴趣-") or fallback_label,
            "score": _number(values.get(code)),
        })

    abilities = _score_rows(items, "能力优势-", 79, 94)
    top_abilities = sorted(
        abilities, key=lambda item: item["score"], reverse=True)[:3]
    weakest = min(abilities, key=lambda item: item["score"]) if abilities else None

    values_rows = _score_rows(items, "职业价值观-", 95, 124)
    top_values = sorted(
        values_rows, key=lambda item: item["score"], reverse=True)[:3]

    report_date = getattr(report, "report_date", None)
    if hasattr(report_date, "isoformat"):
        report_date = report_date.isoformat()

    return {
        "reportId": getattr(report, "id", None),
        "reportDate": report_date,
        "hollandCode": holland_code,
        "riasec": riasec,
        "topAbilities": [dict(item) for item in top_abilities],
        "weakestAbility": dict(weakest) if weakest else None,
        "topValues": [dict(item) for item in top_values],
        "topicSuggestions": _topic_suggestions(holland_code),
    }


def snapshot_summary_text(snapshot: dict) -> dict:
    """把快照转成报告 Y4 区可用的三句摘要（每句一行）。"""
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    code = snapshot.get("hollandCode") or ""
    labels = [HOLAND_LABELS[letter] for letter in code if letter in HOLAND_LABELS][:3]
    if code and labels:
        career = f"职业兴趣代码 {code}：{'、'.join(labels)}较突出。"
    else:
        career = "Y4 报告未提供职业兴趣代码。"

    abilities = [
        item.get("label") for item in snapshot.get("topAbilities") or []
        if item.get("label")
    ]
    if abilities:
        tendency = f"能力优势：{'、'.join(abilities)}较突出。"
    else:
        tendency = "Y4 报告未提供能力优势数据。"

    values = [
        item.get("label") for item in snapshot.get("topValues") or []
        if item.get("label")
    ]
    if values:
        preferences = f"职业价值观：{'、'.join(values)}较受重视。"
    else:
        preferences = "Y4 报告未提供职业价值观数据。"

    return {
        "careerInterests": career,
        "abilityTendencies": tendency,
        "valuePreferences": preferences,
    }
