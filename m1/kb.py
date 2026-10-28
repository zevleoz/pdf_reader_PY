"""M1 知识库：18 项 R4 能力 + 框架固定文字。

数据在 ``m1/kb/r4_abilities.json``，本模块只做加载、校验与按编号查询。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import data_points

_KB_PATH = Path(__file__).resolve().parent / "kb" / "r4_abilities.json"
_EXPECTED_ABILITY_COUNT = 18


@lru_cache(maxsize=1)
def load_kb() -> Dict[str, Any]:
    """加载并校验知识库（进程内缓存，只读一次磁盘）。"""
    with open(_KB_PATH, "r", encoding="utf-8") as f:
        kb = json.load(f)
    validate_kb(kb)
    return kb


def validate_kb(kb: Dict[str, Any]) -> None:
    """校验知识库结构；不合法时抛出带明确信息的 ``ValueError``。"""
    if not isinstance(kb, dict):
        raise ValueError("知识库必须是 JSON 对象")
    abilities: List[Dict[str, Any]] = kb.get("abilities") or []
    if not isinstance(abilities, list):
        raise ValueError("abilities 必须是列表")
    if len(abilities) != _EXPECTED_ABILITY_COUNT:
        raise ValueError(
            "能力数量必须是 %d，当前为 %d" % (_EXPECTED_ABILITY_COUNT, len(abilities)))

    dim_ids = {
        str(dim.get("id") or "")
        for dim in (kb.get("dims") or [])
        if isinstance(dim, dict)
    }

    seen = set()
    for ability in abilities:
        if not isinstance(ability, dict):
            raise ValueError("abilities 中存在非对象条目")
        code = str(ability.get("code") or "").strip()
        if not code:
            raise ValueError("存在缺少 code 的能力")
        if code in seen:
            raise ValueError("能力编号重复：%s" % code)
        seen.add(code)

        dim = str(ability.get("dim") or "")
        if dim not in dim_ids:
            raise ValueError("%s 的维度未知：%s" % (code, dim))

        for field in ("gap_note", "ask"):
            if not str(ability.get(field) or "").strip():
                raise ValueError("%s 缺少 %s" % (code, field))

        for indicator in ability.get("indicators") or []:
            indicator_code = str(indicator).strip()
            if indicator_code not in data_points.POINT_META:
                raise ValueError(
                    "%s 的指标编号不在 schema_124 中：%s" % (code, indicator_code))


def ability(code: str) -> Dict[str, Any]:
    """按能力编号取一条能力定义。"""
    for item in load_kb().get("abilities") or []:
        if item.get("code") == code:
            return item
    raise KeyError("未知能力编号：%s" % code)
