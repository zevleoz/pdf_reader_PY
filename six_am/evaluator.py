"""6 A.M. v0.5 求值器：按可编辑 spec 计算 A1–A5 与 A6。

与 v0.4 规则引擎的区别：判定链由 `spec["dimensions"]` 的 main / supporting /
gates / tracks 结构驱动，参数取自 `spec["params"]`；信号本身由 signals 模块求值。
输出与 `engine._finalize_dim` 的字段保持一致，额外给出 `distance`（同级别排序用）
与 A4 的 `track_disagreement`。

纯函数层：不导入 Flask、不访问数据库。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import rules as R
from . import signals as S

SEV = {"Secure": 0, "Watch": 1, "At-Risk": 2, "Blocked": 3}
_LEVELS = ("Secure", "Watch", "At-Risk", "Blocked")
_DIMS = ("A1", "A2", "A3", "A4", "A5")


def _miss() -> Dict[str, Any]:
    return {"hit": False, "level": None, "evidence": [], "distance": None, "subtype": None}


def _sev(level: Optional[str]) -> int:
    return SEV.get(str(level or "Secure"), 0)


def _level_at_least(level: Optional[str], minimum: str) -> bool:
    return _sev(level) >= _sev(minimum)


def _worst(levels: List[Optional[str]]) -> Optional[str]:
    out: Optional[str] = None
    for level in levels:
        if level and _sev(level) > _sev(out):
            out = level
    return out


def _first(levels: List[Optional[str]]) -> Optional[str]:
    for level in levels:
        if level:
            return level
    return None


# ── 求值入口 ──────────────────────────────────────────────────
def _evaluate_all(ctx, spec: Dict[str, Any],
                  refuted_signals: Optional[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    refuted = refuted_signals or {}
    params = spec.get("params") or {}
    out: Dict[str, Dict[str, Any]] = {}
    for sid in S.SIGNALS:
        if sid in refuted:
            out[sid] = _miss()
        else:
            out[sid] = S.evaluate(sid, ctx, params)
    return out


def _dim_signal_ids(dim_spec: Dict[str, Any]) -> List[str]:
    ids: List[str] = []
    for key in ("main", "supporting", "secure", "type", "extra", "warn"):
        ids.extend(dim_spec.get(key) or [])
    for key in ("activity", "confirm"):
        if dim_spec.get(key):
            ids.append(str(dim_spec[key]))
    tracks = dim_spec.get("tracks")
    if isinstance(tracks, dict):
        ids.extend(str(v) for v in tracks.values())
    gates = dim_spec.get("gates")
    if isinstance(gates, dict):
        for gate_ids in gates.values():
            ids.extend(gate_ids or [])
    out: List[str] = []
    for sid in ids:
        if sid not in out:
            out.append(sid)
    return out


def _hit_ids(ids: List[str], results: Dict[str, Dict[str, Any]]) -> List[str]:
    return [sid for sid in ids if (results.get(sid) or {}).get("hit")]


def _distance(results: Dict[str, Dict[str, Any]], ids: List[str]) -> Optional[float]:
    vals = [(results.get(sid) or {}).get("distance") for sid in ids]
    nums = [float(v) for v in vals if isinstance(v, (int, float))]
    return round(min(nums), 2) if nums else None


def _gate_levels(spec: Dict[str, Any],
                 results: Dict[str, Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """闸门级别（A3.body 等）；情绪闸门 Watch 由 emotion_total_low 抬到 At-Risk。"""
    out: Dict[str, Optional[str]] = {}
    dims_spec = spec.get("dimensions") or {}
    for dim, dim_spec in dims_spec.items():
        gates = (dim_spec or {}).get("gates") or {}
        for gate, ids in gates.items():
            level = _worst([(results.get(sid) or {}).get("level") for sid in ids or []])
            if dim == "A3" and gate == "emotion" and level == "Watch" \
                    and (results.get("emotion_total_low") or {}).get("hit"):
                level = "At-Risk"
            out["%s.%s" % (dim, gate)] = level
    return out


# 只有"显示出问题"的 Y4 之外证据才算佐证：目标部分/不认同、家长主诉、
# 时间排满、规划小任务未通过。仅"填写过"First Touch 不算。
_CONFIRM_SIGNALS = {
    "A2": ("ft_goal", "parent_complaint"),
    "A3": ("schedule_full",),
    "A5": ("ft_task",),
}


def _evidence_confirm(dim: str, results: Dict[str, Dict[str, Any]]) -> bool:
    return any((results.get(sid) or {}).get("hit") for sid in _CONFIRM_SIGNALS.get(dim, ()))


def _confidence(dim: str, results: Dict[str, Dict[str, Any]],
                conf_overrides: Optional[Dict[str, str]],
                any_hit: bool) -> Optional[str]:
    override = (conf_overrides or {}).get(dim)
    if override in ("Confirmed", "Supported"):
        return override
    if _evidence_confirm(dim, results):
        return "Supported"
    return "Hypothesis" if any_hit else None


def _traces(ids: List[str], results: Dict[str, Dict[str, Any]],
            confidence: Optional[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for sid in ids:
        res = results.get(sid) or {}
        if not res.get("hit"):
            continue
        effect: Dict[str, Any] = {"state": res.get("level")}
        if res.get("subtype"):
            effect["subtype"] = res["subtype"]
        out.append({
            "id": sid,
            "title": S.SIGNALS[sid]["label"],
            "evidence": res.get("evidence") or [],
            "effect": effect,
            "confidence": confidence,
            "contributing": True,
        })
    return out


def _record(dim: str, state: str, subtype: Optional[str],
            confidence: Optional[str], ids: List[str],
            results: Dict[str, Dict[str, Any]], distance: Optional[float],
            flags: Optional[List[str]] = None,
            notes: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "state": state,
        "subtype": subtype,
        "subtype_name": R.SUBTYPE_NAMES.get(subtype) if subtype else None,
        "confidence": confidence,
        "activation_key": R.ACTIVATION_KEYS.get(dim),
        "triggered_rules": _traces(ids, results, confidence),
        "cross_mods": [],
        "flags": list(flags or []),
        "notes": list(notes or []),
        "secure_confirmed": False,
        "distance": distance,
    }


# ── A1 ───────────────────────────────────────────────────────
def _eval_a1(dim_spec: Dict[str, Any], results, conf) -> Dict[str, Any]:
    main = _hit_ids(dim_spec.get("main") or [], results)
    supporting = _hit_ids(dim_spec.get("supporting") or [], results)
    level = "Secure"
    escalated = False
    if main:
        level = "Watch"
        if supporting:
            level = "At-Risk"
            escalated = True
    if escalated and conf in ("Supported", "Confirmed"):
        level = "Blocked"
    subtype = None
    for sid in main + supporting:
        st = (results.get(sid) or {}).get("subtype")
        if st:
            subtype = st
            break
    ids = _dim_signal_ids(dim_spec)
    if level != "Secure":   # 稳固确认信号（幸福与满足等）只在稳固时作为依据列出
        ids = [sid for sid in ids if sid not in (dim_spec.get("secure") or [])]
    return _record("A1", level, subtype, conf if level != "Secure" else None,
                   ids, results, _distance(results, ids + main + supporting))


# ── A2 ───────────────────────────────────────────────────────
_A2_SUBTYPE_ORDER = ("A2-S3", "A2-S4", "A2-S2", "A2-S1")


def _eval_a2(dim_spec: Dict[str, Any], results, conf) -> Dict[str, Any]:
    # 学习场景：深层动机 → +辅助 → +佐证；活动场景（First Touch 目标）单独定级，取较重者
    learning = None
    if _hit_ids(dim_spec.get("main") or [], results):
        learning = "Watch"
        if _hit_ids(dim_spec.get("supporting") or [], results):
            learning = "At-Risk"
            if conf in ("Supported", "Confirmed"):
                learning = "Blocked"
    activity = dim_spec.get("activity")
    activity_level = (results.get(activity) or {}).get("level") if activity else None
    level = _worst([learning, activity_level]) or "Secure"
    subtypes = [(results.get(sid) or {}).get("subtype") for sid in _dim_signal_ids(dim_spec)]
    subtype = None
    for wanted in _A2_SUBTYPE_ORDER:
        if wanted in subtypes:
            subtype = wanted
            break
    ids = _dim_signal_ids(dim_spec)
    return _record("A2", level, subtype, conf if level != "Secure" else None,
                   ids, results, _distance(results, ids))


# ── A3 ───────────────────────────────────────────────────────
def _eval_a3(dim_spec: Dict[str, Any], results, conf,
             gate_levels: Dict[str, Optional[str]], safety_hit: bool) -> Dict[str, Any]:
    gates = dim_spec.get("gates") or {}
    body = gate_levels.get("A3.body")
    emotion = gate_levels.get("A3.emotion")
    time = gate_levels.get("A3.time")
    wm = None
    for sid in dim_spec.get("extra") or []:
        if (results.get(sid) or {}).get("hit"):
            wm = (results.get(sid) or {}).get("level")
            break
    level = _worst([body, emotion, time, wm]) or "Secure"
    # 阻塞 = Y4 闸门（身体 / 情绪）已到风险 + 佐证（时间排满或追问证实）
    if _sev(_worst([body, emotion])) >= 2 and conf in ("Supported", "Confirmed"):
        level = "Blocked"
    subtype = None
    if _sev(body) >= 1:
        subtype = "A3-S2"
    elif _sev(emotion) >= 1:
        subtype = "A3-S1"
    elif _sev(time) >= 1:
        subtype = "A3-S4"
    elif _sev(wm) >= 1:
        subtype = "A3-S3"
    flags = ["情绪安全复核"] if safety_hit else []
    ids = _dim_signal_ids(dim_spec)
    return _record("A3", level, subtype, conf if level != "Secure" else None,
                   ids, results, _distance(results, ids), flags=flags)


# ── A4 ───────────────────────────────────────────────────────
_A4_SUBTYPE_ORDER = ("A4-S4", "A4-S3", "A4-S1", "A4-S2")


def _eval_a4(dim_spec: Dict[str, Any], results, conf) -> Dict[str, Any]:
    tracks = dim_spec.get("tracks") or {}
    low = [sid for sid in tracks.values() if (results.get(sid) or {}).get("hit")]
    supporting = _hit_ids(dim_spec.get("supporting") or [], results)
    level = "Secure"
    if len(low) == 1:
        level = "Watch"
        if supporting:
            level = "At-Risk"
    elif len(low) >= 2:
        level = "At-Risk"
    if level == "At-Risk" and conf in ("Supported", "Confirmed"):
        level = "Blocked"
    subtypes = [(results.get(sid) or {}).get("subtype") for sid in _dim_signal_ids(dim_spec)]
    subtype = None
    for wanted in _A4_SUBTYPE_ORDER:
        if wanted in subtypes:
            subtype = wanted
            break
    if subtype is None and low:
        subtype = "A4-S2"
    flags = ["学习 / 通用不一致"] if len(low) == 1 else []
    ids = _dim_signal_ids(dim_spec)
    rec = _record("A4", level, subtype, conf if level != "Secure" else None,
                  ids, results, _distance(results, ids), flags=flags)
    rec["track_disagreement"] = len(low) == 1
    return rec


# ── A5 ───────────────────────────────────────────────────────
def _eval_a5(dim_spec: Dict[str, Any], results, conf) -> Dict[str, Any]:
    main = _hit_ids(dim_spec.get("main") or [], results)
    supporting = _hit_ids(dim_spec.get("supporting") or [], results)
    level = "Secure"
    if main:
        level = "Watch"
        if supporting:
            level = "At-Risk"
    if level == "At-Risk" and conf in ("Supported", "Confirmed"):
        level = "Blocked"   # 追问证实，或规划小任务未通过（见下）
    confirm = dim_spec.get("confirm")
    task = results.get(confirm) if confirm else None
    if task and task.get("hit"):
        level = "Blocked" if _sev(level) >= 2 else "At-Risk"
    subtype = (task or {}).get("subtype") if task and task.get("hit") else None
    if subtype is None:
        for sid in _dim_signal_ids(dim_spec):
            st = (results.get(sid) or {}).get("subtype")
            if st:
                subtype = st
                break
    flags = []
    for sid in dim_spec.get("warn") or []:
        if (results.get(sid) or {}).get("hit"):
            flags.append(S.SIGNALS[sid]["label"])
    ids = _dim_signal_ids(dim_spec)
    return _record("A5", level, subtype, conf if level != "Secure" else None,
                   ids, results, _distance(results, ids), flags=flags)


# ── 汇总 ─────────────────────────────────────────────────────
def evaluate_dims(ctx, spec: Dict[str, Any], refuted_signals=None,
                  conf_overrides=None) -> Tuple[Dict[str, Any], Dict[str, List[Dict[str, Any]]]]:
    """按 spec 计算 A1–A5，返回 (dims, hits)。"""
    results = _evaluate_all(ctx, spec, refuted_signals)
    dims_spec = spec.get("dimensions") or {}
    gate_levels = _gate_levels(spec, results)
    safety_hit = bool((results.get("safety") or {}).get("hit"))

    dims: Dict[str, Any] = {}
    hits: Dict[str, List[Dict[str, Any]]] = {}
    for dim in _DIMS:
        dim_spec = dims_spec.get(dim) or {}
        ids = _dim_signal_ids(dim_spec)
        any_hit = any((results.get(sid) or {}).get("hit") for sid in ids)
        conf = _confidence(dim, results, conf_overrides, any_hit)
        if dim == "A1":
            rec = _eval_a1(dim_spec, results, conf)
        elif dim == "A2":
            rec = _eval_a2(dim_spec, results, conf)
        elif dim == "A3":
            rec = _eval_a3(dim_spec, results, conf, gate_levels, safety_hit)
        elif dim == "A4":
            rec = _eval_a4(dim_spec, results, conf)
        else:
            rec = _eval_a5(dim_spec, results, conf)
        dims[dim] = rec
        if rec["state"] != "Secure":
            ids = [sid for sid in ids if sid not in (dim_spec.get("secure") or [])]
        hits[dim] = [_hit_dict(dim, sid, results[sid], rec["confidence"]) for sid in ids
                     if (results.get(sid) or {}).get("hit")]
    return dims, hits


def _hit_dict(dim: str, sid: str, res: Dict[str, Any],
              confidence: Optional[str]) -> Dict[str, Any]:
    effect: Dict[str, Any] = {"state": res.get("level")}
    if res.get("subtype"):
        effect["subtype"] = res["subtype"]
    return {
        "id": sid,
        "title": S.SIGNALS[sid]["label"],
        "dim": dim,
        "evidence": res.get("evidence") or [],
        "effect": effect,
        "confidence": confidence,
        "contributing": True,
        "questions": list(S.SIGNALS[sid].get("questions") or []),
        "text": S.SIGNALS[sid]["label"],
    }


# ── 全局提示 ─────────────────────────────────────────────────
def banners(ctx, spec: Dict[str, Any]) -> Dict[str, Any]:
    """answer_state / safety → profile.flags_global；safety 同时进 A3 flags。"""
    params = spec.get("params") or {}
    flags: List[str] = []
    answer_state = bool(S.evaluate("answer_state", ctx, params).get("hit"))
    safety = bool(S.evaluate("safety", ctx, params).get("hit"))
    if answer_state:
        flags.append(S.SIGNALS["answer_state"]["label"])
    if safety:
        flags.append(S.SIGNALS["safety"]["label"])
    return {"answer_state": answer_state, "safety": safety, "flags": flags}


# ── A6 ───────────────────────────────────────────────────────
def _fired_in_dim(dims: Dict[str, Any], dim: str, minimum: str) -> List[str]:
    rec = dims.get(dim) or {}
    out: List[str] = []
    for trace in rec.get("triggered_rules") or []:
        state = (trace.get("effect") or {}).get("state")
        if _level_at_least(state, minimum):
            out.append(str(trace.get("id")))
    return out


def _cond(cond: Any, ctx, results, dims, gate_levels) -> Tuple[bool, List[str]]:
    if not isinstance(cond, dict):
        return False, []
    keys = set(cond)
    if keys == {"not"}:
        ok, fired = _cond(cond["not"], ctx, results, dims, gate_levels)
        return (not ok), fired
    if keys == {"signal"}:
        sid = str(cond["signal"])
        return bool((results.get(sid) or {}).get("hit")), [sid]
    if keys == {"any"} or keys == {"all"}:
        subs = cond[next(iter(keys))] or []
        fired: List[str] = []
        oks: List[bool] = []
        for sub in subs:
            ok, sub_fired = _cond(sub, ctx, results, dims, gate_levels)
            oks.append(ok)
            if ok:
                fired.extend(sub_fired)
        ok = any(oks) if "any" in keys else bool(oks) and all(oks)
        return ok, fired if ok else []
    if keys == {"dim", "min"}:
        dim = str(cond["dim"])
        ok = _level_at_least((dims.get(dim) or {}).get("state"), str(cond["min"]))
        return ok, _fired_in_dim(dims, dim, str(cond["min"])) if ok else []
    if keys == {"gate", "min"}:
        gate = str(cond["gate"])
        ok = _level_at_least(gate_levels.get(gate), str(cond["min"]))
        return ok, []
    if keys == {"subtype"}:
        want = str(cond["subtype"])
        for dim in _DIMS:
            if str((dims.get(dim) or {}).get("subtype") or "") == want:
                return True, []
        return False, []
    if keys == {"dim_any_min"}:
        minimum = str(cond["dim_any_min"])
        ok = False
        fired: List[str] = []
        for dim in _DIMS:
            if _level_at_least((dims.get(dim) or {}).get("state"), minimum):
                ok = True
                fired.extend(_fired_in_dim(dims, dim, minimum))
        return ok, fired
    return False, []


def assign_supports(ctx, spec: Dict[str, Any],
                    dims: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """按 A6 目录求值 assign / caution / avoid，输出 support_ranking。"""
    results = _evaluate_all(ctx, spec, {})
    gate_levels = _gate_levels(spec, results)
    ranked: List[Dict[str, Any]] = []
    avoid: List[Dict[str, Any]] = []
    trace: List[Dict[str, Any]] = []
    hits: List[Dict[str, Any]] = []

    for entry in spec.get("a6") or []:
        name = entry.get("name") or entry.get("id") or ""
        fired: List[str] = []
        if entry.get("avoid") is not None:
            avoid_ok, avoid_fired = _cond(entry["avoid"], ctx, results, dims, gate_levels)
        else:
            avoid_ok, avoid_fired = False, []
        if avoid_ok:
            avoid.append({
                "direction": name,
                "kind": "避免",
                "basis_rules": _dedupe(avoid_fired),
                "reason": entry.get("note") or "命中避免条件",
            })
            continue
        if entry.get("assign") is None:
            continue
        assign_ok, fired = _cond(entry["assign"], ctx, results, dims, gate_levels)
        if not assign_ok:
            continue
        caution_ok, caution_fired = (False, []) if entry.get("caution") is None else \
            _cond(entry["caution"], ctx, results, dims, gate_levels)
        fit = "慎用" if caution_ok else "优先"
        ranked.append({
            "direction": name,
            "sub_mechanisms": [entry.get("group") or ""],
            "fit_label": fit,
            "basis_rules": _dedupe(fired),
            "cautions": entry.get("note") or "",
        })
        effect: Dict[str, Any] = {"state": None, "fit_label": fit,
                                  "support": name}
        trace.append({
            "id": entry.get("id"), "title": name,
            "evidence": [], "effect": effect, "confidence": None,
            "contributing": True,
        })
        hits.append({
            "id": entry.get("id"), "title": name, "dim": "A6",
            "evidence": [], "effect": effect, "confidence": None,
            "contributing": True, "questions": [], "text": entry.get("note") or "",
        })

    rec = {
        "state": None,
        "subtype": None,
        "subtype_name": None,
        "confidence": None,
        "support_ranking": {"ranked": ranked, "avoid": avoid},
        "activation_key": R.ACTIVATION_KEYS.get("A6"),
        "triggered_rules": trace,
        "cross_mods": [],
        "flags": [],
        "notes": [],
    }
    return rec, hits


def _dedupe(items: List[str]) -> List[str]:
    out: List[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out
