"""World Bank SEL 参考资料查询（只读，数据不入库）。

数据由 ``scripts/build_wb_library.py`` 一次性生成到 ``m1/kb/private/``：
``wb_index.json``（课程索引 + R4 分龄映射）与 ``wb_lessons.json``（课文原文）。
该目录被 git 忽略，部署时手工拷贝；缺失时本模块全部返回空结果，不报错。

路径可用环境变量 ``M1_WB_DIR`` 覆盖（测试使用小样本目录）。
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

_KB_DIR = Path(__file__).resolve().parent / "kb" / "private"

_INDEX_FILE = "wb_index.json"
_LESSONS_FILE = "wb_lessons.json"

_CN_DIGITS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}
_GRADE_WORDS = {"初一": 7, "初二": 8, "初三": 9, "高一": 10, "高二": 11, "高三": 12}
_G_PREFIX = re.compile(r"^g\s*(\d{1,2})$", re.IGNORECASE)
_GRADE_PREFIX = re.compile(r"^grade\s*(\d{1,2})$", re.IGNORECASE)
_DIGIT_GRADE = re.compile(r"^(\d{1,2})\s*年级$")
_CN_GRADE = re.compile(r"^(?:小学)?([一二三四五六七八九十]{1,3})年级$")


def _dir() -> Path:
    override = os.environ.get("M1_WB_DIR")
    return Path(override) if override else _KB_DIR


@lru_cache(maxsize=8)
def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _index() -> Optional[Dict[str, Any]]:
    return _read_json(str(_dir() / _INDEX_FILE))


def _texts() -> Optional[Dict[str, Any]]:
    return _read_json(str(_dir() / _LESSONS_FILE))


def installed() -> bool:
    """两个文件都在且可解析。"""
    index = _index()
    texts = _texts()
    return bool(index and texts and isinstance(index.get("lessons"), dict))


def lesson(wb_id: str) -> Optional[Dict[str, Any]]:
    """索引条目（不含课文原文）。"""
    index = _index() or {}
    entry = (index.get("lessons") or {}).get(wb_id)
    return dict(entry) if isinstance(entry, dict) else None


def lesson_text(wb_id: str) -> Optional[str]:
    """课文原文；未安装、无文本层或缺失时返回 None。"""
    entry = lesson(wb_id)
    if not entry or not entry.get("has_text"):
        return None
    block = (_texts() or {}).get(wb_id)
    if not isinstance(block, dict):
        return None
    text = str(block.get("text") or "").strip()
    return text or None


def cite(wb_id: str) -> str:
    """D11 展示文案，例如 ``G9 · NEGATIVE EMOTIONAL CHAIN · PDF p.59``。"""
    entry = lesson(wb_id)
    if not entry:
        return ""
    grade = entry.get("grade")
    name = str(entry.get("name") or "").strip()
    page = entry.get("pdf_page")
    prefix = "G%s" % grade if isinstance(grade, int) else ""
    parts = [part for part in (prefix, name) if part]
    if isinstance(page, int):
        parts.append("PDF p.%d" % page)
    return " · ".join(parts)


def grade_from_text(value: Any) -> Optional[int]:
    """把学生年级自由文本解析成年级数字；无法确定时返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    if text in _GRADE_WORDS:
        return _GRADE_WORDS[text]
    for pattern in (_G_PREFIX, _GRADE_PREFIX, _DIGIT_GRADE):
        match = pattern.match(text)
        if match:
            return int(match.group(1))
    match = _CN_GRADE.match(text)
    if match:
        digits = match.group(1)
        if len(digits) == 1:
            return _CN_DIGITS.get(digits)
        if digits.startswith("十") and len(digits) == 2:
            return 10 + (_CN_DIGITS.get(digits[1]) or 0)
        if digits.endswith("十") and len(digits) == 2:
            return (_CN_DIGITS.get(digits[0]) or 0) * 10
    return None


def nearest_grade(grade: int) -> int:
    """G5–G9 之外取最近年级。"""
    return min(max(int(grade), 5), 9)


def candidates(code: str, wb_grade: int, limit: int = 2) -> List[Dict[str, Any]]:
    """某个 R4 能力在该年级下可用的 WB 课程，按教材表顺序。"""
    if limit <= 0:
        return []
    index = _index() or {}
    r4 = (index.get("r4") or {}).get(code) or {}
    rows = (r4.get("by_grade") or {}).get(str(wb_grade)) or []
    out: List[Dict[str, Any]] = []
    for row in rows:
        wb_id = str(row.get("lesson") or "")
        entry = lesson(wb_id)
        if not entry or not entry.get("has_text"):
            continue
        out.append({
            "wb_id": wb_id,
            "cite": cite(wb_id),
            "skill": str(entry.get("skill") or ""),
            "match": str(row.get("match") or ""),
            "limit": str(row.get("limit") or ""),
            "objective": str(entry.get("objective") or ""),
        })
        if len(out) >= limit:
            break
    return out
