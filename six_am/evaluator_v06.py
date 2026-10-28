"""6AM v0.6 求值器：三值条件 → 维度档案 → A6 排序。

纯函数层：不导入 Flask、不访问数据库。判定规则全部来自
``six_am/model_v06.json``；本模块不写任何展示文案（文案只从模型读）。

条件三值：True / False / None（None = 数据缺失）。级别、类型、提示、关联
只在 True 时算命中。
"""

from __future__ import annotations

import copy
import datetime as _dt
from typing import Any, Dict, Iterator, List, Optional, Tuple

from . import signals
from .engine import Ctx, _norm_label

LEVELS = ("稳固", "关注", "风险", "阻塞")
NODE_LEVELS = ("稳固", "关注", "风险")
SEVERITY = {"稳固": 0, "关注": 1, "风险": 2, "阻塞": 3}

ConditionValue = Optional[bool]
Result = Tuple[ConditionValue, List[Dict[str, Any]]]


# ── 小工具 ────────────────────────────────────────────────────
def _sev(level: Optional[str]) -> Optional[int]:
    return SEVERITY.get(str(level)) if level is not None else None


def _ge(level: Optional[str], minimum: Optional[str]) -> ConditionValue:
    """level ≥ minimum；任一侧缺失 → None。"""
    a, b = _sev(level), _sev(minimum)
    if a is None or b is None:
        return None
    return a >= b


def _y4_fact(ctx: Ctx, label: str, value: Any) -> Dict[str, Any]:
    fact = {
        "label": label,
        "value": value,
        "raw": ctx.raw_num(label),
        "norm": ctx.num_of(_norm_label(label) + "常模平均数"),
    }
    return {k: v for k, v in fact.items() if v is not None}


def _worst_level(levels: List[Optional[str]]) -> Optional[str]:
    for level in ("风险", "关注", "稳固"):
        if level in levels:
            return level
    return None


# ── 条件求值 ──────────────────────────────────────────────────
def cond(c: Any, env: Dict[str, Any]) -> Result:
    """条件 → (True / False / None, 命中的叶子事实)。"""
    if not isinstance(c, dict):
        return None, []

    if "any" in c:
        facts: List[Dict[str, Any]] = []
        missing = False
        for sub in c.get("any") or []:
            value, sub_facts = cond(sub, env)
            facts.extend(sub_facts)
            if value is True:
                return True, facts
            if value is None:
                missing = True
        return (None if missing else False), facts

    if "all" in c:
        facts = []
        missing = False
        for sub in c.get("all") or []:
            value, sub_facts = cond(sub, env)
            facts.extend(sub_facts)
            if value is False:
                return False, facts
            if value is None:
                missing = True
        return (None if missing else True), facts

    if "not" in c:
        value, facts = cond(c.get("not"), env)
        if value is None:
            return None, facts
        return (not value), facts

    ctx: Ctx = env["ctx"]
    model = env.get("model") or {}

    if "y4" in c:
        label = str(c.get("y4"))
        value = ctx.eval_of(label)
        facts = [_y4_fact(ctx, label, value)]
        if value is None:
            return None, facts
        band = (model.get("bands") or {}).get(c.get("band")) or []
        return (value in band), facts

    if "y4_raw" in c:
        label = str(c.get("y4_raw"))
        raw = ctx.raw_num(label)
        facts = [_y4_fact(ctx, label, ctx.eval_of(label))]
        if raw is None:
            return None, facts
        ok = True
        for key, compare in (
                ("lt", lambda a, b: a < b), ("lte", lambda a, b: a <= b),
                ("gt", lambda a, b: a > b), ("gte", lambda a, b: a >= b)):
            if key in c:
                try:
                    threshold = float(c[key])
                except (TypeError, ValueError):
                    return None, facts
                ok = ok and compare(raw, threshold)
        return ok, facts

    if "rank" in c:
        value = str(c.get("rank"))
        pos = ctx.order_pos_of(value)
        facts = [{"label": value,
                  "value": ("第 %s 位" % pos) if pos is not None else None}]
        if pos is None:
            return None, facts
        return pos <= int(c.get("top") or 0), facts

    if "y4_rel_low" in c:
        label = str(c.get("y4_rel_low"))
        facts = [_y4_fact(ctx, label, ctx.eval_of(label))]
        items = list(model.get("self_concept_items") or [])
        own = ctx.raw_num(label)
        if not items or label not in items or own is None:
            return None, facts
        raws = [ctx.raw_num(item) for item in items]
        if any(raw is None for raw in raws):
            return None, facts
        return own <= min(raws), facts

    if "signal" in c:
        signal_id = str(c.get("signal"))
        hit = bool(signals.evaluate(signal_id, ctx, env.get("params"))["hit"])
        label = (signals.SIGNALS.get(signal_id) or {}).get("label") or signal_id
        return hit, [{"label": label, "value": "是" if hit else "否"}]

    if "ev" in c:
        path = str(c.get("ev"))
        value = ctx.ev(path)
        facts = [{"label": path, "value": value}]
        if value is None:
            return None, facts
        return value == c.get("eq"), facts

    if "self" in c:
        return (env.get("nodes") or {}).get(c.get("self")), []

    if "part" in c:
        level = (env.get("part_levels") or {}).get(c.get("part"))
        return _ge(level, c.get("min")), []

    if "dim_level" in c:
        return _ge(env.get("dim_model_level"), c.get("dim_level")), []

    if "talk" in c:
        record = env.get("talk") or {}
        return (record.get("result") == c.get("talk")), []

    if "else" in c:
        return (c.get("else") is True), []

    if "at" in c:
        spec = str(c.get("at"))
        dim_id, _, part_id = spec.partition(".")
        dim = (env.get("dims") or {}).get(dim_id) or {}
        if part_id:
            level = ((dim.get("parts") or {}).get(part_id) or {}).get("level")
        else:
            level = dim.get("level")
        return _ge(level, c.get("min")), []

    if "cause" in c:
        return _cause_value(str(c.get("cause")), env), []

    return None, []


def _cause_value(spec: str, env: Dict[str, Any]) -> ConditionValue:
    """A6：会谈记录里选中，或（未选任何归因且提示 True 且该维度 ≥ 风险）。"""
    dim_id, _, cause_id = spec.partition(".")
    dims = env.get("dims") or {}
    final = dims.get(dim_id) or {}
    talks = env.get("talks") or (env.get("inputs") or {}).get("talks") or {}
    record = talks.get(dim_id) or {}
    picked = [str(cid) for cid in (record.get("causes") or [])]
    if cause_id and cause_id in picked:
        return True
    if picked:
        return False

    model = env.get("model") or {}
    dim_spec = next((d for d in model.get("dims") or [] if d.get("id") == dim_id), None)
    causes = ((dim_spec or {}).get("blocked") or {}).get("causes") or []
    cause = next((c for c in causes if (c or {}).get("id") == cause_id), None)
    if dim_spec is None or cause is None:
        return None

    level = final.get("level")
    sev = _sev(level)
    if sev is None or sev < SEVERITY["风险"]:
        return False

    sub_env = dict(env)
    sub_env.update({
        "dim": dim_spec,
        "part": None,
        "nodes": {},
        "part_levels": {pid: (p or {}).get("level")
                        for pid, p in (final.get("parts") or {}).items()},
        "dim_model_level": final.get("model_level"),
        "talk": record or None,
    })
    hint, _facts = cond(cause.get("hint"), sub_env)
    return hint


# ── 单维求值 ──────────────────────────────────────────────────
def evaluate_dim(dim_spec: Dict[str, Any], env: Dict[str, Any]) -> Dict[str, Any]:
    """按 README §3 计算一个维度，返回 profile.dims.A? 的形状。"""
    dim_env = dict(env)
    dim_id = str(dim_spec.get("id"))
    talk = (env.get("talks") or {}).get(dim_id) or None
    dim_env["dim"] = dim_spec
    dim_env["talk"] = talk

    parts = [p for p in dim_spec.get("parts") or [] if isinstance(p, dict)]
    part_levels: Dict[str, Optional[str]] = {}
    parts_out: Dict[str, Any] = {}

    for part in parts:
        part_id = str(part.get("id"))
        values: Dict[str, ConditionValue] = {}
        nodes: Dict[str, Any] = {}
        for level in NODE_LEVELS:
            node = (part.get("levels") or {}).get(level)
            if not isinstance(node, dict):
                continue
            dim_env["part"] = part
            dim_env["nodes"] = dict(values)
            value, facts = cond(node.get("when"), dim_env)
            values[level] = value
            nodes[level] = {"ok": value is True, "facts": facts}
        part_level = _worst_level([lvl for lvl in NODE_LEVELS if values.get(lvl) is True])
        part_levels[part_id] = part_level
        parts_out[part_id] = {"level": part_level, "nodes": nodes, "types": []}

        part_types = [t for t in part.get("types") or [] if isinstance(t, dict)]
        if part_types and _ge(part_level, "关注") is True:
            dim_env["nodes"] = dict(values)
            names = []
            for ctype in part_types:
                if cond(ctype.get("when"), dim_env)[0] is True:
                    names.append(ctype.get("name"))
            parts_out[part_id]["types"] = names

    dim_env["part"] = None
    dim_env["nodes"] = {}
    dim_env["part_levels"] = part_levels
    model_level = _worst_level([lvl for lvl in part_levels.values() if lvl])
    dim_env["dim_model_level"] = model_level

    blocked = dim_spec.get("blocked") or {}
    blocked_value: ConditionValue = False
    if blocked.get("when") is not None:
        blocked_value = cond(blocked.get("when"), dim_env)[0]
    blocked_level = "阻塞" if blocked_value is True else model_level

    level = blocked_level
    set_by_talk = False
    if talk and talk.get("result") == "set" and talk.get("set_level") in LEVELS:
        level = talk["set_level"]
        set_by_talk = True

    types: List[str] = []
    if dim_spec.get("layout") == "types":
        if model_level is not None and _sev(model_level) >= SEVERITY["关注"]:
            types = [p.get("type_name") for p in parts
                     if part_levels.get(str(p.get("id"))) == model_level
                     and p.get("type_name")]
    elif dim_spec.get("types"):
        if blocked_level is not None and _sev(blocked_level) >= SEVERITY["关注"]:
            for ctype in dim_spec.get("types") or []:
                if not isinstance(ctype, dict):
                    continue
                if cond(ctype.get("when"), dim_env)[0] is True:
                    types = [ctype.get("name")]
                    break

    picked = set(str(cid) for cid in (talk or {}).get("causes") or [])
    causes = []
    for cause in (blocked.get("causes") or []):
        if not isinstance(cause, dict):
            continue
        hint, _facts = cond(cause.get("hint"), dim_env)
        causes.append({"id": cause.get("id"), "hint": hint,
                       "picked": cause.get("id") in picked})

    refs = []
    for ref in dim_spec.get("refs") or []:
        if not isinstance(ref, dict):
            continue
        refs.append({"name": ref.get("name"), "hint": cond(ref.get("hint"), dim_env)[0]})

    return {
        "level": level,
        "model_level": blocked_level,
        "blocked": level == "阻塞",
        "set_by_talk": set_by_talk,
        "parts": parts_out,
        "types": types,
        "causes": causes,
        "refs": refs,
        "blocked_ok": blocked_value,
    }


# ── 维度顺序 ──────────────────────────────────────────────────
def _dim_order(dims: Dict[str, Any]) -> List[str]:
    """处理顺序：最终级别降序，同级按 A1→A5。"""
    ids = [str(d) for d in dims]

    def key(dim_id: str) -> Tuple[int, int]:
        sev = _sev(dims[dim_id].get("level"))
        return (-(sev if sev is not None else -1), ids.index(dim_id))

    return sorted(ids, key=key)


# ── A6 排序 ───────────────────────────────────────────────────
def _link_leaves(node: Any) -> Iterator[Tuple[str, Dict[str, Any]]]:
    if not isinstance(node, dict):
        return
    if "at" in node:
        yield "at", node
    if "cause" in node:
        yield "cause", node
    for key in ("any", "all"):
        for sub in node.get(key) or []:
            yield from _link_leaves(sub)
    if "not" in node:
        yield from _link_leaves(node.get("not"))


def _at_level(spec: str, dims: Dict[str, Any]) -> Optional[str]:
    dim_id, _, part_id = str(spec).partition(".")
    dim = dims.get(dim_id) or {}
    if part_id:
        return ((dim.get("parts") or {}).get(part_id) or {}).get("level")
    return dim.get("level")


def rank_supports(model: Dict[str, Any], dims: Dict[str, Any],
                  env: Dict[str, Any]) -> Dict[str, Any]:
    """D8：最差的关联维度在前 → 有归因 → 慎用靠后 → Y4 适配在前 → 目录顺序。"""
    a6 = model.get("a6") or {}
    top_n = int(a6.get("top_n") or 4)
    item_env = {k: v for k, v in env.items() if k != "dim"}
    item_env["dims"] = dims

    ranked: List[Tuple[Tuple[int, int, int, int, int], Dict[str, Any]]] = []
    avoid: List[Dict[str, Any]] = []

    for index, item in enumerate(a6.get("items") or []):
        if not isinstance(item, dict):
            continue
        if cond(item.get("avoid"), item_env)[0] is True:
            avoid.append({"id": item.get("id"), "name": item.get("name"),
                          "why": item.get("avoid_text") or ""})
            continue

        fit_ok = cond(item.get("fit"), item_env)[0] is True
        matched: List[Dict[str, Any]] = []
        link_sev = 0
        cause_hit = 0
        for link in item.get("links") or []:
            if not isinstance(link, dict):
                continue
            when = link.get("when")
            if cond(when, item_env)[0] is not True:
                continue
            matched.append(link)
            for kind, leaf in _link_leaves(when):
                if cond(leaf, item_env)[0] is not True:
                    continue
                if kind == "at":
                    target = _at_level(leaf.get("at"), dims)
                else:
                    target = (dims.get(str(leaf.get("cause")).partition(".")[0]) or {}).get("level")
                sev = _sev(target)
                if sev is not None and sev > link_sev:
                    link_sev = sev
                if kind == "cause":
                    cause_hit = 1

        if not matched and not fit_ok:
            continue

        caution_labels = []
        for caution in item.get("caution") or []:
            if not isinstance(caution, dict):
                continue
            if cond(caution.get("when"), item_env)[0] is True:
                caution_labels.append(str(caution.get("label") or ""))

        why = [str(link.get("label") or "") for link in matched]
        if fit_ok and str(item.get("fit_text") or "").strip():
            why.append("Y4：" + str(item["fit_text"]).strip())
        why.extend("慎用：" + label for label in caution_labels if label)

        entry = {
            "id": item.get("id"),
            "name": item.get("name"),
            "group": item.get("group"),
            "fit_label": "慎用" if caution_labels else "推荐",
            "top": False,
            "why": why,
        }
        key = (-link_sev, -cause_hit, 1 if caution_labels else 0,
               0 if fit_ok else 1, index)
        ranked.append((key, entry))

    ranked.sort(key=lambda pair: pair[0])
    out = []
    for position, (_key, entry) in enumerate(ranked):
        entry["top"] = position < top_n
        out.append(entry)
    return {"ranked": out, "avoid": avoid}


# ── 顶层入口 ──────────────────────────────────────────────────
def run(items: List[Dict[str, Any]], student: Optional[Dict[str, Any]],
        inputs: Optional[Dict[str, Any]], report_id: Optional[int],
        model: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """装配 → A1–A5 → order → A6 → flags，返回 README §4 的 profile。"""
    if model is None:
        from .model import load_model
        model = load_model()

    inputs = copy.deepcopy(inputs or {})
    talks = inputs.get("talks") or {}
    evidence: Dict[str, Any] = {}
    for key in ("ft", "parent"):
        if inputs.get(key) is not None:
            evidence[key] = inputs[key]
    params = dict(model.get("params") or {})

    ctx = Ctx(items, evidence, params)
    base_env: Dict[str, Any] = {
        "ctx": ctx,
        "model": model,
        "params": params,
        "inputs": inputs,
        "talks": talks,
        "dims": None,
    }

    dims: Dict[str, Any] = {}
    for dim_spec in model.get("dims") or []:
        env = dict(base_env)
        dims[str(dim_spec.get("id"))] = evaluate_dim(dim_spec, env)
    base_env["dims"] = dims

    a6 = rank_supports(model, dims, base_env)
    flags = {
        "safety": bool(signals.evaluate("safety", ctx, params)["hit"]),
        "answer_state": bool(signals.evaluate("answer_state", ctx, params)["hit"]),
    }

    return {
        "schema": "6am.v0.6",
        "model_version": str(model.get("version") or ""),
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "report_id": report_id,
        "student": {"name": (student or {}).get("name", ""),
                    "grade": (student or {}).get("grade", "")},
        "inputs": inputs,
        "dims": dims,
        "order": _dim_order(dims),
        "a6": a6,
        "flags": flags,
    }
