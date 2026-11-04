"""会后报告的固定数据：模板固定文案、能力说明与 Mapping、4.0 场景原文。

三个 JSON 文件从 ``docs/audits/plans-hub/r4-report/`` 原样复制到 ``m1/kb/``，
本模块只读取，不改写、不补全。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

_KB_DIR = Path(__file__).resolve().parent / "kb"
_FIXED_PATH = _KB_DIR / "r4_report_fixed.json"
_MAPPING_PATH = _KB_DIR / "r4_report_mapping.json"
_SCENES_PATH = _KB_DIR / "r4_report_scenes.json"

SCENE_MISSING = "场景原文待导入"
APPENDIX_TAGS = ("确认发展需求", "可能存在")


@lru_cache(maxsize=8)
def _read(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def fixed() -> Dict[str, Any]:
    """模板固定文案与颜色（``r4_report_fixed.json``）。"""
    data = _read(str(_FIXED_PATH))
    if data is None:
        raise RuntimeError("缺少 m1/kb/r4_report_fixed.json")
    return data


def tag_names() -> List[str]:
    return [tag["key"] for tag in fixed().get("tags") or []]


def ability_map() -> Dict[str, Dict[str, Any]]:
    """能力编号 → name/description/dim/indicators/y4_text/gap_note/supplement/ask。

    名称与说明来自 fixed，其余来自 mapping；按 fixed 里的维度与能力顺序。
    """
    mapping = (_read(str(_MAPPING_PATH)) or {}).get("abilities") or {}
    out: Dict[str, Dict[str, Any]] = {}
    for dim in fixed().get("dims") or []:
        for item in dim.get("abilities") or []:
            code = item["code"]
            row = mapping.get(code) or {}
            out[code] = {
                "name": item.get("name") or "",
                "description": item.get("description") or "",
                "dim": dim.get("id") or "",
                "indicators": list(row.get("indicators") or []),
                "y4_text": row.get("y4_text") or "",
                "gap_note": row.get("gap_note") or "",
                "supplement": row.get("supplement") or "",
                "ask": row.get("ask") or "",
            }
    return out


def ability_codes() -> List[str]:
    return list(ability_map())


def dim_ids() -> List[str]:
    return [dim.get("id") or "" for dim in fixed().get("dims") or []]


def scene(code: str) -> Optional[str]:
    """能力的场景原文；文件或条目缺失返回 ``None``。"""
    scenes = (_read(str(_SCENES_PATH)) or {}).get("scenes")
    if not isinstance(scenes, dict):
        return None
    value = scenes.get(code)
    return value if isinstance(value, str) and value.strip() else None


def appendix(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """标签含「确认发展需求」或「可能存在」的能力，每项一次，按能力编号顺序。"""
    abilities = ability_map()
    found: Dict[str, List[str]] = {}
    for dim in ((doc or {}).get("dims") or {}).values():
        for code, row in ((dim or {}).get("abilities") or {}).items():
            tags = list((row or {}).get("tags") or [])
            if code in abilities and any(tag in APPENDIX_TAGS for tag in tags):
                found[code] = tags
    rows = []
    for code in abilities:              # 固定顺序
        if code in found:
            rows.append({"code": code, "name": abilities[code]["name"],
                         "tags": found[code], "scene": scene(code) or SCENE_MISSING})
    return rows


def tags_problem(tags: Any) -> str:
    """标签是否合法；合法返回空串，否则返回原因。

    必须是五种标签之一，最多两个，不重复；「信息不足」不与其他标签并列，
    「暂未发现」不与「确认发展需求」并列，「积极资源」不与「确认发展需求」并列。
    """
    if not isinstance(tags, list):
        return "标签必须是列表"
    names = tag_names()
    for tag in tags:
        if tag not in names:
            return "标签不在五种固定标签之内"
    if len(tags) > 2:
        return "标签最多两个"
    if len(set(tags)) != len(tags):
        return "标签重复"
    if len(tags) == 2:
        if "信息不足" in tags:
            return "「信息不足」不与其他判断并列"
        if "暂未发现" in tags and "确认发展需求" in tags:
            return "「暂未发现」不与「确认发展需求」并列"
        if "积极资源" in tags and "确认发展需求" in tags:
            return "「积极资源」不与「确认发展需求」并列"
        if set(tags) != {"积极资源", "可能存在"}:
            return "双标签只允许「积极资源 + 可能存在」"
    return ""
