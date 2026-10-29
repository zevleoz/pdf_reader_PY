"""6AM v0.6 模型文件：加载、校验、思维导图导出。

唯一数据源：six_am/model_v06.json。所有展示文案都来自 JSON，代码不生成。
不导入 Flask、不访问数据库。
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

LEVELS = ("稳固", "关注", "风险", "阻塞")
LEVEL_ORDER = ("稳固", "关注", "风险")
_LAYOUTS = ("single", "sides", "types")
_COMPARATORS = ("lt", "lte", "gt", "gte")

_DEFAULT_PATH = Path(__file__).with_name("model_v06.json")

_LEAF_KEYS = {
    "y4": {"y4", "band"},
    "y4_raw": {"y4_raw"},
    "rank": {"rank", "top"},
    "y4_rel_low": {"y4_rel_low"},
    "signal": {"signal"},
    "ev": {"ev", "eq"},
    "self": {"self"},
    "part": {"part", "min"},
    "dim_level": {"dim_level"},
    "talk": {"talk"},
    "else": {"else"},
    "at": {"at", "min"},
    "cause": {"cause"},
}


# ── 加载 ──────────────────────────────────────────────────────
@lru_cache(maxsize=None)
def _read_model(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_model(path: Optional[str] = None) -> Dict[str, Any]:
    """读取模型 JSON；按路径缓存，每次返回深拷贝。"""
    target = Path(path) if path else _DEFAULT_PATH
    return copy.deepcopy(_read_model(str(target.resolve())))


# ── 校验 ──────────────────────────────────────────────────────
def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _signal_ids() -> set:
    from .signals import SIGNALS
    return set(SIGNALS)


def validate(model: Dict[str, Any]) -> List[str]:
    """返回中文错误列表，空列表表示通过。"""
    if not isinstance(model, dict):
        return ["模型必须是 JSON 对象"]

    errors: List[str] = []
    for key in ("version", "levels", "bands", "params", "dims", "a6"):
        if key not in model:
            errors.append(f"缺少顶层字段：{key}")
    if model.get("levels") != list(LEVELS):
        errors.append("levels 必须是 稳固 / 关注 / 风险 / 阻塞")

    bands = model.get("bands") or {}
    dims = [d for d in (model.get("dims") or []) if isinstance(d, dict)]
    if [d.get("id") for d in dims] != ["A1", "A2", "A3", "A4", "A5"]:
        errors.append("dims 的 id 必须恰好是 A1–A5（按顺序）")

    dims_by_id: Dict[str, Dict[str, Any]] = {}
    for dim in dims:
        dim_id = str(dim.get("id") or "")
        if dim_id in dims_by_id:
            errors.append(f"dims 的 id 重复：{dim_id}")
        dims_by_id[dim_id] = dim
        errors.extend(_validate_dim(dim, bands))

    errors.extend(_validate_a6(model.get("a6") or {}, bands, dims_by_id))
    return errors


def _validate_dim(dim: Dict[str, Any], bands: Dict[str, Any]) -> List[str]:
    dim_id = str(dim.get("id") or "?")
    errors: List[str] = []

    layout = dim.get("layout")
    if layout not in _LAYOUTS:
        errors.append(f"{dim_id} 的 layout 未知：{layout}")

    parts = [p for p in (dim.get("parts") or []) if isinstance(p, dict)]
    part_ids: List[str] = []
    for part in parts:
        part_id = str(part.get("id") or "")
        if not part_id:
            errors.append(f"{dim_id} 有 part 缺少 id")
            continue
        if part_id in part_ids:
            errors.append(f"{dim_id} 的 part id 重复：{part_id}")
        part_ids.append(part_id)

    if layout == "single" and len(parts) != 1:
        errors.append(f"{dim_id} 是 single 布局，必须恰好一个 part")
    if layout == "types":
        for part in parts:
            if not str(part.get("type_name") or "").strip():
                errors.append(f"{dim_id}.{part.get('id')} 是 types 布局，缺少 type_name")
    if layout == "sides" and not parts:
        errors.append(f"{dim_id} 是 sides 布局，缺少 part")

    blocked = dim.get("blocked") or {}
    blocked_part = blocked.get("part")
    if blocked_part and blocked_part not in part_ids:
        errors.append(f"{dim_id} 的 blocked.part 不存在：{blocked_part}")

    cause_ids: List[str] = []
    for cause in blocked.get("causes") or []:
        cause_id = str((cause or {}).get("id") or "")
        if not cause_id:
            errors.append(f"{dim_id} 有 cause 缺少 id")
            continue
        if cause_id in cause_ids:
            errors.append(f"{dim_id} 的 cause id 重复：{cause_id}")
        cause_ids.append(cause_id)

    for part in parts:
        errors.extend(_validate_part_levels(dim_id, part))
        part_id = part.get("id")
        for level in LEVEL_ORDER:
            node = (part.get("levels") or {}).get(level)
            if isinstance(node, dict) and node.get("when") is not None:
                errors.extend(_check_condition(
                    node["when"], f"{dim_id}.{part_id}.{level}",
                    scope="dims", dim=dim, part=part, bands=bands))
        for idx, ctype in enumerate(part.get("types") or []):
            errors.extend(_check_condition(
                (ctype or {}).get("when"), f"{dim_id}.{part_id} 的 type {idx}",
                scope="dims", dim=dim, part=part, bands=bands))
        for idx, ref in enumerate(part.get("refs") or []):
            errors.extend(_check_condition(
                (ref or {}).get("hint"), f"{dim_id}.{part_id} 的 ref {idx}",
                scope="dims", dim=dim, part=part, bands=bands))

    if blocked.get("when") is not None:
        errors.extend(_check_condition(
            blocked["when"], f"{dim_id} 的 blocked", scope="dims", dim=dim,
            part=None, bands=bands))
    for cause in blocked.get("causes") or []:
        errors.extend(_check_condition(
            (cause or {}).get("hint"), f"{dim_id}.{cause.get('id')} 的 hint",
            scope="dims", dim=dim, part=None, bands=bands))

    for idx, ctype in enumerate(dim.get("types") or []):
        errors.extend(_check_condition(
            (ctype or {}).get("when"), f"{dim_id} 的 type {idx}",
            scope="dims", dim=dim, part=None, bands=bands))
    for idx, ref in enumerate(dim.get("refs") or []):
        errors.extend(_check_condition(
            (ref or {}).get("hint"), f"{dim_id} 的 ref {idx}",
            scope="dims", dim=dim, part=None, bands=bands))
    return errors


def _validate_part_levels(dim_id: str, part: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    part_id = part.get("id")
    levels = part.get("levels") or {}
    if not isinstance(levels, dict):
        return [f"{dim_id}.{part_id} 的 levels 必须是对象"]
    for level, node in levels.items():
        if level not in LEVEL_ORDER:
            errors.append(f"{dim_id}.{part_id} 的级别未知：{level}")
            continue
        if not isinstance(node, dict):
            errors.append(f"{dim_id}.{part_id}.{level} 必须是对象")
            continue
        if not str(node.get("text") or "").strip():
            errors.append(f"{dim_id}.{part_id}.{level} 缺少 text")
        if node.get("when") is None:
            errors.append(f"{dim_id}.{part_id}.{level} 缺少 when")
    return errors


def _validate_a6(a6: Dict[str, Any], bands: Dict[str, Any],
                 dims_by_id: Dict[str, Dict[str, Any]]) -> List[str]:
    errors: List[str] = []
    groups = a6.get("groups") or []
    dims_order = a6.get("dims_order") or []
    items = [i for i in (a6.get("items") or []) if isinstance(i, dict)]
    seen: List[str] = []
    for item in items:
        item_id = str(item.get("id") or "")
        if not item_id:
            errors.append("a6 有 item 缺少 id")
            continue
        if item_id in seen:
            errors.append(f"a6 的 item id 重复：{item_id}")
        seen.append(item_id)
        if item.get("group") not in groups:
            errors.append(f"a6 item {item_id} 的 group 不在 groups 里：{item.get('group')}")
        for key in ("fit", "avoid"):
            errors.extend(_check_condition(
                item.get(key), f"a6.{item_id} 的 {key}", scope="a6", dim=None,
                part=None, bands=bands, dims_by_id=dims_by_id))
        for idx, caution in enumerate(item.get("caution") or []):
            errors.extend(_check_condition(
                (caution or {}).get("when"), f"a6.{item_id} 的 caution {idx}",
                scope="a6", dim=None, part=None, bands=bands, dims_by_id=dims_by_id))
        for idx, link in enumerate(item.get("links") or []):
            link = link or {}
            label = link.get("label")
            if label not in dims_order:
                errors.append(f"a6.{item_id} 的 link label 不在 dims_order 里：{label}")
            errors.extend(_check_condition(
                link.get("when"), f"a6.{item_id} 的 link {idx}", scope="a6", dim=None,
                part=None, bands=bands, dims_by_id=dims_by_id))
    return errors


def _check_condition(node: Any, where: str, *, scope: str, dim: Optional[Dict[str, Any]],
                     part: Optional[Dict[str, Any]], bands: Dict[str, Any],
                     dims_by_id: Optional[Dict[str, Dict[str, Any]]] = None) -> List[str]:
    """递归检查条件节点，返回错误列表。"""
    errors: List[str] = []
    if node is None:
        return errors
    if not isinstance(node, dict):
        return [f"{where}：条件必须是对象"]

    keys = set(node)
    if keys in ({"any"}, {"all"}):
        keyword = next(iter(keys))
        value = node[keyword]
        if not isinstance(value, list) or not value:
            return [f"{where}：{keyword} 必须是非空列表"]
        for child in value:
            errors.extend(_check_condition(child, where, scope=scope, dim=dim, part=part,
                                           bands=bands, dims_by_id=dims_by_id))
        return errors
    if keys == {"not"}:
        return _check_condition(node["not"], where, scope=scope, dim=dim, part=part,
                                bands=bands, dims_by_id=dims_by_id)

    leaf = next((name for name in _LEAF_KEYS if name in keys), None)
    if leaf is None:
        return [f"{where}：未知条件类型 {sorted(keys)}"]

    extra = keys - _LEAF_KEYS[leaf]
    if leaf == "y4_raw" and extra and extra <= set(_COMPARATORS):
        extra = set()
    if extra:
        errors.append(f"{where}：{leaf} 条件带了未知键 {sorted(extra)}")

    value = node.get(leaf)
    if leaf == "y4":
        if "band" not in keys:
            errors.append(f"{where}：y4 条件缺少 band")
        elif value is None:
            errors.append(f"{where}：y4 条件的标签为空")
        elif node["band"] not in (bands or {}):
            errors.append(f"{where}：band 不存在：{node['band']}")
    elif leaf == "y4_raw":
        comps = [key for key in keys if key in _COMPARATORS]
        if not 1 <= len(comps) <= 2:
            errors.append(f"{where}：y4_raw 需要 1–2 个比较键（lt / lte / gt / gte）")
        for key in comps:
            if not _is_number(node[key]):
                errors.append(f"{where}：y4_raw 的 {key} 必须是数字")
    elif leaf == "rank":
        if "top" not in keys:
            errors.append(f"{where}：rank 条件缺少 top")
        elif not isinstance(node["top"], int) or isinstance(node["top"], bool) or node["top"] < 1:
            errors.append(f"{where}：rank.top 必须是 ≥1 的整数")
    elif leaf == "signal":
        if value not in _signal_ids():
            errors.append(f"{where}：未知信号：{value}")
    elif leaf == "self":
        if value not in set((part or {}).get("levels") or {}):
            errors.append(f"{where}：self 级别不存在：{value}")
    elif leaf == "part":
        known = {p.get("id") for p in (dim or {}).get("parts") or []}
        if value not in known:
            errors.append(f"{where}：part 不存在：{value}")
        if node.get("min") not in LEVELS:
            errors.append(f"{where}：part 的 min 不是合法级别：{node.get('min')}")
    elif leaf == "dim_level":
        if value not in LEVELS:
            errors.append(f"{where}：dim_level 不是合法级别：{value}")
    elif leaf == "talk":
        if value not in ("confirm", "deny", "set"):
            errors.append(f"{where}：talk 只能是 confirm / deny / set")
    elif leaf == "else":
        if value is not True:
            errors.append(f"{where}：else 必须是 true")
    elif leaf == "ev":
        if "eq" not in keys:
            errors.append(f"{where}：ev 条件缺少 eq")
    elif leaf == "at":
        if node.get("min") not in LEVELS:
            errors.append(f"{where}：at 的 min 不是合法级别：{node.get('min')}")
        errors.extend(_check_at(value, where, dims_by_id or {}))
    elif leaf == "cause":
        errors.extend(_check_cause(value, where, dims_by_id or {}))

    if leaf in ("at", "cause") and scope != "a6":
        errors.append(f"{where}：{leaf} 条件只能出现在 a6")
    if leaf in ("self", "part", "dim_level", "talk") and scope != "dims":
        errors.append(f"{where}：{leaf} 条件只能出现在 dims")
    return errors


def _check_at(value: Any, where: str, dims_by_id: Dict[str, Dict[str, Any]]) -> List[str]:
    if not isinstance(value, str) or not value:
        return [f"{where}：at 必须是 \"A1\" 或 \"A?.part\""]
    dim_id, _, part_id = value.partition(".")
    dim = dims_by_id.get(dim_id)
    if dim is None:
        return [f"{where}：at 的维度不存在：{value}"]
    if part_id and part_id not in {p.get("id") for p in dim.get("parts") or []}:
        return [f"{where}：at 的 part 不存在：{value}"]
    return []


def _check_cause(value: Any, where: str, dims_by_id: Dict[str, Dict[str, Any]]) -> List[str]:
    if not isinstance(value, str) or "." not in value:
        return [f"{where}：cause 必须是 \"A?.cause\""]
    dim_id, _, cause_id = value.partition(".")
    dim = dims_by_id.get(dim_id)
    if dim is None:
        return [f"{where}：cause 的维度不存在：{value}"]
    known = {c.get("id") for c in (dim.get("blocked") or {}).get("causes") or []}
    if cause_id not in known:
        return [f"{where}：cause 不存在：{value}"]
    return []


# ── 思维导图 MD 导出 ──────────────────────────────────────────
def _bullet(depth: int, text: str) -> str:
    return "  " * depth + "- " + text


def _labelled(name: Any, detail: Any = "") -> str:
    detail = "" if detail is None else str(detail).strip()
    name = "" if name is None else str(name)
    return f"{name}：{detail}" if detail else name


def _blocked_lines(blocked: Dict[str, Any], risk_depth: int) -> List[str]:
    via = str(blocked.get("via") or "").strip()
    name = str(blocked.get("name") or "").strip()
    out = [_bullet(risk_depth + 1, via)]
    out.append(_bullet(risk_depth + 2, f"阻塞：{name}" if name else "阻塞"))
    for cause in blocked.get("causes") or []:
        cause = cause or {}
        out.append(_bullet(risk_depth + 3, _labelled(cause.get("name"), cause.get("text"))))
    return out


def _level_lines(levels: Dict[str, Any], depth: int,
                 blocked: Optional[Dict[str, Any]] = None) -> List[str]:
    out: List[str] = []
    for level in LEVEL_ORDER:
        node = (levels or {}).get(level)
        if not node:
            continue
        out.append(_bullet(depth, _labelled(level, node.get("text"))))
        if level == "风险" and blocked:
            out.extend(_blocked_lines(blocked, depth))
    return out


def _type_part_lines(part: Dict[str, Any], depth: int) -> List[str]:
    out = [_bullet(depth, _labelled(part.get("type_name"), part.get("name")))]
    out.extend(_level_lines(part.get("levels") or {}, depth + 1))
    refs = [str((r or {}).get("text") or "").strip() for r in part.get("refs") or []]
    refs = [text for text in refs if text]
    if refs:
        out.append(_bullet(depth + 1, "参考：" + " · ".join(refs)))
    return out


def _dim_lines(dim: Dict[str, Any]) -> List[str]:
    layout = dim.get("layout")
    blocked = dim.get("blocked") or None
    parts = [p for p in dim.get("parts") or [] if isinstance(p, dict)]
    out: List[str] = []

    if layout == "types":
        summary = dim.get("summary") or {}
        summary_levels = {level: {"text": summary[level]}
                          for level in LEVEL_ORDER if level in summary}
        out.append(_bullet(0, "状态"))
        out.extend(_level_lines(summary_levels, 1, blocked))
        out.append(_bullet(0, "类型"))
        for part in parts:
            out.extend(_type_part_lines(part, 1))
        for ref in dim.get("refs") or []:
            ref = ref or {}
            out.append(_bullet(1, _labelled(ref.get("name"), ref.get("text"))))
        return out

    if layout == "sides":
        target = (blocked or {}).get("part")
        if blocked and not target and parts:
            target = parts[-1].get("id")
        for part in parts:
            out.append(_bullet(0, _labelled(part.get("name"), part.get("note"))))
            attach = blocked if (blocked and target == part.get("id")) else None
            out.extend(_level_lines(part.get("levels") or {}, 1, attach))
            for extra in part.get("extra") or []:
                out.append(_bullet(1, str(extra)))
            if part.get("types"):
                out.append(_bullet(1, "类型"))
                for ctype in part["types"]:
                    ctype = ctype or {}
                    out.append(_bullet(2, _labelled(ctype.get("name"), ctype.get("text"))))
        if dim.get("combine_text"):
            out.append(_bullet(0, dim["combine_text"]))
        return out

    # single
    part = parts[0] if parts else {}
    out.append(_bullet(0, "状态"))
    if dim.get("intro"):
        out.append(_bullet(1, dim["intro"]))
    out.extend(_level_lines(part.get("levels") or {}, 1, blocked))
    if dim.get("types"):
        out.append(_bullet(0, "类型"))
        for ctype in dim["types"]:
            ctype = ctype or {}
            out.append(_bullet(1, _labelled(ctype.get("name"), ctype.get("text"))))
    return out


def _a6_lines(a6: Dict[str, Any]) -> List[str]:
    items = [i for i in a6.get("items") or [] if isinstance(i, dict)]
    out = [_bullet(0, a6.get("y4_title") or "")]
    for group in a6.get("groups") or []:
        out.append(_bullet(1, str(group)))
        for item in items:
            fit_text = str(item.get("fit_text") or "").strip()
            if item.get("group") != group or not fit_text:
                continue
            detail = fit_text
            if str(item.get("avoid_text") or "").strip():
                detail += "；" + str(item["avoid_text"]).strip()
            if str(item.get("caution_text") or "").strip():
                detail += "；" + str(item["caution_text"]).strip()
            out.append(_bullet(2, _labelled(item.get("name"), detail)))

    out.append(_bullet(0, a6.get("dims_title") or ""))
    for label in a6.get("dims_order") or []:
        out.append(_bullet(1, str(label)))
        for item in items:
            link = next((one for one in item.get("links") or []
                         if (one or {}).get("label") == label), None)
            if link is None:
                continue
            out.append(_bullet(2, _labelled(item.get("name"), link.get("note"))))
        cautions = [str(item.get("name") or "") for item in items
                    if any((c or {}).get("label") == label for c in item.get("caution") or [])]
        if cautions:
            out.append(_bullet(2, "慎用：" + " · ".join(cautions)))
    return out


def export_md(model: Dict[str, Any]) -> str:
    """按 README §3 的格式规则导出思维导图 Markdown。"""
    lines = [f"# 6AM 思维导图 {model.get('version', '')}（{model.get('date', '')}）", ""]
    for dim in model.get("dims") or []:
        lines.append(f"## {dim.get('id')} {dim.get('name')}")
        lines.extend(_dim_lines(dim))
        lines.append("")
    a6 = model.get("a6") or {}
    lines.append(f"## A6 {a6.get('name') or ''}")
    lines.extend(_a6_lines(a6))
    return "\n".join(lines) + "\n"
