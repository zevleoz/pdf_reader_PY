"""发展计划固定文字：家长版 PDF 的固定段落、内部版 Block Review、参考来源标签。

数据在 ``m1/kb/plan_fixed.json``（公司自己的文字，不含 World Bank 内容）。
导入时即校验，缺键或空值直接报错，避免页面渲染出空段落。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

_FIXED_PATH = Path(__file__).resolve().parent / "kb" / "plan_fixed.json"

# 家长版每个字段的建议长度（DP13-A）。只用于编辑页计数和提示，不阻断确认/导出，
# 也不截断生成内容；页数随内容自然延续。数值为家长快速阅读的编辑参考。
PARENT_LIMITS = {
    "intro": 90,
    "goal": 40,
    "session_title": 20,
    "session_summary": 35,
    "transition": 60,
    "practice_title": 30,
    "practice_text": 90,
    "practice_frequency": 20,
    "review_label": 10,
    "review_text": 65,
    "family": 45,
}

# 技术载荷上限：与编辑建议无关，只防止异常超大的文档进入存储/渲染。
PARENT_PAYLOAD_LIMIT = 50000

_PARENT_TEXT_KEYS = ("title", "title_en", "kicker", "header_left", "header_right_p1",
                     "header_right_p2", "footer_p1", "footer_p2", "quote", "closing",
                     "approach_lead")
_INTERNAL_TEXT_KEYS = ("module", "title_suffix")
_SOURCE_TYPES = ("ai_original", "world_bank", "other")


def validate_fixed(data: Dict[str, Any]) -> None:
    """校验固定文字结构；不合法时抛出带明确信息的 ``ValueError``。"""
    if not isinstance(data, dict):
        raise ValueError("固定文字必须是 JSON 对象")
    parent = data.get("parent")
    if not isinstance(parent, dict):
        raise ValueError("缺少 parent")
    for key in _PARENT_TEXT_KEYS:
        if not str(parent.get(key) or "").strip():
            raise ValueError("parent.%s 不能为空" % key)
    sections = parent.get("sections")
    if not isinstance(sections, list) or len(sections) != 5:
        raise ValueError("parent.sections 必须是 5 个板块")
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            raise ValueError("parent.sections 第 %d 项必须是对象" % (index + 1))
        for key in ("no", "title", "tag"):
            if not str(section.get(key) or "").strip():
                raise ValueError("parent.sections 第 %d 项缺少 %s" % (index + 1, key))

    internal = data.get("internal")
    if not isinstance(internal, dict):
        raise ValueError("缺少 internal")
    for key in _INTERNAL_TEXT_KEYS:
        if not str(internal.get(key) or "").strip():
            raise ValueError("internal.%s 不能为空" % key)
    review = internal.get("block_review")
    if not isinstance(review, dict):
        raise ValueError("缺少 internal.block_review")
    if not str(review.get("name") or "").strip():
        raise ValueError("internal.block_review.name 不能为空")
    minutes = review.get("minutes")
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        raise ValueError("internal.block_review.minutes 必须是正整数")
    parts = review.get("parts")
    if not isinstance(parts, list) or len(parts) != 4:
        raise ValueError("internal.block_review.parts 必须是 4 项")
    for index, part in enumerate(parts):
        if not isinstance(part, dict):
            raise ValueError("block_review.parts 第 %d 项必须是对象" % (index + 1))
        for key in ("label", "text"):
            if not str(part.get(key) or "").strip():
                raise ValueError("block_review.parts 第 %d 项缺少 %s" % (index + 1, key))
    if not str(review.get("note") or "").strip():
        raise ValueError("internal.block_review.note 不能为空")

    labels = internal.get("source_labels")
    if not isinstance(labels, dict):
        raise ValueError("缺少 internal.source_labels")
    for key in _SOURCE_TYPES:
        if not str(labels.get(key) or "").strip():
            raise ValueError("internal.source_labels.%s 不能为空" % key)

    platforms = data.get("platforms")
    if not isinstance(platforms, list) or not platforms:
        raise ValueError("platforms 必须是非空列表")
    for value in platforms:
        if not str(value or "").strip():
            raise ValueError("platforms 里不能有空值")


@lru_cache(maxsize=1)
def fixed() -> Dict[str, Any]:
    """加载并校验固定文字（进程内缓存，只读一次磁盘）。"""
    with open(_FIXED_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    validate_fixed(data)
    return data


def platforms() -> List[str]:
    return list(fixed()["platforms"])


def source_labels() -> Dict[str, str]:
    return dict(fixed()["internal"]["source_labels"])


def source_label(kind: str) -> str:
    """参考来源标签；未知类型按 AI Original 显示，不抛错。"""
    return source_labels().get(kind) or source_labels()["ai_original"]


def block_review() -> Dict[str, Any]:
    return dict(fixed()["internal"]["block_review"])


def parent() -> Dict[str, Any]:
    return dict(fixed()["parent"])


# 导入即校验：缺键或空值在启动时就暴露，不留到渲染时。
fixed()


# DP16-A：教学目标与活动字段不设字数上限；导师可保存完整长文。
# INTERNAL_RESPONSE_LIMIT 只是整份文档的技术预算提示，不是字段保存限制。
INTERNAL_RESPONSE_LIMIT = 50000
RICH_ACTIVITY_FIELDS = ("purpose", "personalization", "student_action",
                        "expected_attempt", "support", "extension")

def timing_budget(n, duration):
    """Non-overlapping segments; fixed Block Review is an activity, counted once."""
    review = 5 if n > 1 else 0
    summary = int(block_review()["minutes"]) if n == 3 else 0
    transition = 2
    return {"duration_minutes": duration, "review_minutes": review,
            "transition_minutes": transition, "block_review_minutes": summary,
            "teaching_minutes": duration - review - transition - summary}
