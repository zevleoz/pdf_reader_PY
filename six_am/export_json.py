"""6 A.M. JSON 档案导出（实施计划 §6.2）

build_six_am_json(profile) -> dict：以 profile 为主体（无需二次变换），
补齐"锚点=规则 ID"的 basis_rules 字段，输出机器可读 JSON。

纯函数：不导入 Flask、不访问数据库。
约定：档案内不出现 Y4/E4 并行体系的概念与命名；data_bias 仅出现在证据 trace 内（engine 已保证）。
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List

EXPORT_SCHEMA = "six-am-json-v1"


def build_six_am_json(profile: Dict[str, Any]) -> Dict[str, Any]:
    """返回可直接 json.dumps 的档案 dict（顶层含 schema 与 rule_version）。"""
    data = copy.deepcopy(profile or {})
    data.setdefault("schema", "six-am-profile-v1")
    data["export_schema"] = EXPORT_SCHEMA
    data.setdefault("rule_version", {"id": None, "label": "default", "status": None})

    # 每维补 basis_rules / subtype_basis_rules（锚点=规则 ID）
    for _dim, rec in (data.get("dimensions") or {}).items():
        if not isinstance(rec, dict):
            continue
        rec["basis_rules"] = _dim_basis(rec)
        subtype = rec.get("subtype")
        if subtype:
            rec["subtype_basis_rules"] = [
                str(t.get("id")) for t in rec.get("triggered_rules") or []
                if (t.get("effect") or {}).get("subtype") == subtype and not t.get("refuted")
            ]

    # 追问项：basis_rules 非空（缺失时回退 verify）
    for q in data.get("questions") or []:
        basis = [str(x) for x in (q.get("basis_rules") or []) if x]
        if not basis:
            basis = [str(x) for x in (q.get("verify") or []) if x]
        q["basis_rules"] = basis

    # 支持方案：规范化为列表
    for item in ((data.get("support_plan") or {}).get("ranked") or []):
        item["basis_rules"] = [str(x) for x in (item.get("basis_rules") or []) if x]

    return data


def _dim_basis(rec: Dict[str, Any]) -> List[str]:
    """维度 basis_rules：优先有贡献且未被否定的规则；退一步取全部未被否定的命中规则。"""
    traces = rec.get("triggered_rules") or []
    basis = [t.get("id") for t in traces
             if t.get("contributing") and not t.get("refuted")]
    if not basis:
        basis = [t.get("id") for t in traces if not t.get("refuted")]
    return [str(x) for x in basis if x]