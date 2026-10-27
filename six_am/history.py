"""6 A.M. 版本差异：同一学生两次 profile 之间的可见变化。

纯函数层：不导入 Flask、不访问数据库。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .presentation import EVIDENCE_LABELS, STATE_LABELS

DIMS = ["A1", "A2", "A3", "A4", "A5"]


def _zh(labels: Dict[str, str], key: Any) -> str:
    label = labels.get(str(key))
    if not label:
        return ""
    return label.split(" ")[0]


def _rule_label(profile: Dict[str, Any]) -> str:
    version = (profile or {}).get("rule_version") or {}
    return str(version.get("label") or "")


def diff_profiles(old: Optional[Dict[str, Any]],
                  new: Optional[Dict[str, Any]]) -> List[str]:
    """两次 profile 的变化行；old 为 None 表示首次构建。"""
    if old is None:
        return ["Y4 初筛"]
    old = old or {}
    new = new or {}
    lines: List[str] = []

    old_rule = _rule_label(old)
    new_rule = _rule_label(new)
    if old_rule != new_rule:
        lines.append("规则 %s → %s" % (old_rule, new_rule))

    old_dims = old.get("dimensions") or {}
    new_dims = new.get("dimensions") or {}
    for dim in DIMS:
        o = old_dims.get(dim) or {}
        n = new_dims.get(dim) or {}
        if o.get("state") != n.get("state"):
            lines.append("%s %s → %s" % (dim, _zh(STATE_LABELS, o.get("state")),
                                         _zh(STATE_LABELS, n.get("state"))))

    for dim in DIMS:
        o = old_dims.get(dim) or {}
        n = new_dims.get(dim) or {}
        # 一侧无证据等级（维度变为/来自稳固）时，状态行已说明变化，不再输出空的证据行
        if o.get("confidence") and n.get("confidence") and o.get("confidence") != n.get("confidence"):
            lines.append("%s 证据 %s → %s"
                         % (dim, _zh(EVIDENCE_LABELS, o.get("confidence")),
                            _zh(EVIDENCE_LABELS, n.get("confidence"))))

    old_refuted = old.get("refuted") or {}
    new_refuted = new.get("refuted") or {}
    for rid, q in new_refuted.items():
        if rid not in old_refuted:
            lines.append("%s 否定：%s 移出判定" % (q, rid))

    if not old.get("safety_review") and new.get("safety_review"):
        lines.append("新增情绪安全复核")
    elif old.get("safety_review") and not new.get("safety_review"):
        lines.append("解除情绪安全复核")

    return lines


def _profile(row: Dict[str, Any]) -> Dict[str, Any]:
    raw = (row or {}).get("profile_json")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _version_key(row: Dict[str, Any]):
    version = (row or {}).get("version")
    try:
        return (0, int(version))
    except (TypeError, ValueError):
        return (1, str(version))


def timeline(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按版本升序逐次对比，返回从新到旧的版本记录。"""
    ordered = sorted(rows or [], key=_version_key)
    parsed = [(_profile(row), row) for row in ordered]
    out: List[Dict[str, Any]] = []
    previous: Optional[Dict[str, Any]] = None
    for profile, row in parsed:
        changes = diff_profiles(previous, profile)
        if not changes:
            changes = ["重跑，无变化"]
        out.append({
            "profile_id": row.get("id"),
            "version": row.get("version"),
            "created_at": row.get("created_at"),
            "changes": changes,
        })
        previous = profile
    out.reverse()
    return out
