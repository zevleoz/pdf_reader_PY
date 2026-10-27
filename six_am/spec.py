"""6 A.M. v0.5 规则板 · 默认配置与校验。

`DEFAULT_SPEC` 是发布版 v0.5 的完整配置：维度结构、参数、A6 方案目录、备注。
`validate` 返回中文错误列表（空列表 = 通过）。
`editable_view` / `merge_edit` 定义规则板可改的字段；main / gates / tracks 锁定。
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional

from .signals import SIGNALS

LEVELS = ("Secure", "Watch", "At-Risk", "Blocked")
DIMS = ("A1", "A2", "A3", "A4", "A5")
GATES = ("body", "emotion", "time")

_PARAM_RANGES = {
    "top_n_values": (1, 15),
    "top_n_safety": (1, 15),
    "control_low_max": (0, 100),
    "control_high_min": (0, 100),
    "mindset_low_max": (0, 100),
    "cog_pct_min": (0, 100),
    "schedule_free_hours_max": (0, 100),
}

_SUBTYPE_RE = re.compile(r"^A[1-6]-S\d+$")


DEFAULT_SPEC: Dict[str, Any] = {
    "version": "v0.5",
    "params": {
        "top_n_values": 5,
        "top_n_safety": 3,
        "control_low_max": 5,
        "control_high_min": 11,
        "mindset_low_max": 50,
        "cog_pct_min": 75,
        "schedule_free_hours_max": 5,
    },
    "dimensions": {
        "A1": {"main": ["autonomy"],
               "supporting": ["indep_boss_top5", "control_low"],
               "secure": ["wellbeing_ok", "control_high"]},
        "A2": {"main": ["deep_motive"], "activity": "ft_goal",
               "supporting": ["surface_low", "parent_complaint"],
               "type": ["surface_not_low", "holland_all_low"]},
        "A3": {"gates": {"body": ["sleep", "exercise_diet"],
                         "emotion": ["anxiety", "depression"],
                         "time": ["schedule_full"]},
               "supporting": ["emotion_total_low"], "extra": ["wm_flex_low"]},
        "A4": {"tracks": {"learning": "self_efficacy", "general": "competence"},
               "supporting": ["esteem_anx", "safety_top3", "cog_vs_self", "self_concept_low",
                              "control_low", "mindset_low", "neuroticism_high", "achieve_safety"]},
        "A5": {"main": ["conscientiousness"], "confirm": "ft_task", "warn": ["attention_low"],
               "supporting": ["holland_c_high", "strategy_low", "self_reg_low", "openness_many",
                              "inhibition_low", "achieve_safety"]},
    },
    "a6": [
        {"id": "mentor_reach_out", "group": "谁来帮", "name": "导师主动联系",
         "assign": {"any": [{"signal": "extraversion_low"}, {"dim_any_min": "At-Risk"}]},
         "caution": {"subtype": "A1-S2"}, "avoid": None,
         "note": "只由学生选的成人、私下进行"},
        {"id": "peer_support", "group": "谁来帮", "name": "同伴支持",
         "assign": {"any": [{"signal": "peer_attach_high"}, {"signal": "belonging_good"},
                            {"signal": "extraversion_high"}]},
         "caution": None, "avoid": {"signal": "peer_attach_low"}, "note": ""},
        {"id": "parent_accompany", "group": "谁来帮", "name": "家长陪同",
         "assign": {"any": [{"signal": "parent_high"}, {"signal": "parent_mid"}]},
         "caution": {"any": [{"signal": "parent_mid"}, {"subtype": "A1-S2"}]},
         "avoid": {"signal": "parent_low"}, "note": "只由学生选的成人、私下进行"},
        {"id": "structured_breakdown", "group": "怎么做", "name": "结构化拆解（LDF / SAFE）",
         "assign": {"any": [{"dim": "A5", "min": "Watch"}, {"signal": "holland_c_high"}]},
         "caution": None, "avoid": None, "note": ""},
        {"id": "checkpoints", "group": "怎么做", "name": "固定检查点",
         "assign": {"any": [{"signal": "agreeable_high"}, {"subtype": "A5-S3"}]},
         "caution": {"any": [{"signal": "anxiety_flag"}, {"subtype": "A1-S2"}]},
         "avoid": None, "note": "只由学生选的成人、私下进行"},
        {"id": "small_wins", "group": "怎么做", "name": "小目标 + 及时反馈",
         "assign": {"any": [{"dim": "A4", "min": "Watch"}, {"signal": "control_low"}]},
         "caution": None, "avoid": None, "note": ""},
        {"id": "limited_choice", "group": "怎么做", "name": "有限选择 / 共定目标",
         "assign": {"dim": "A1", "min": "Watch"},
         "caution": None, "avoid": None, "note": ""},
        {"id": "private_trials", "group": "环境", "name": "私下低压尝试",
         "assign": {"any": [{"signal": "esteem_anx"}, {"signal": "neuroticism_high"},
                            {"signal": "safety_top3"}]},
         "caution": None, "avoid": None, "note": ""},
        {"id": "public_commitment", "group": "环境", "name": "公开承诺 / 适度竞争",
         "assign": {"signal": "achieve_or_prestige_top5"},
         "caution": None,
         "avoid": {"any": [{"signal": "anxiety_flag"}, {"signal": "esteem_flag"}]},
         "note": ""},
        {"id": "lighten_load", "group": "环境", "name": "减负 / 优先级管理",
         "assign": {"dim": "A3", "min": "Watch"},
         "caution": None, "avoid": None, "note": ""},
        {"id": "energy_emotion", "group": "环境", "name": "精力与情绪支持",
         "assign": {"any": [{"gate": "A3.body", "min": "Watch"},
                            {"gate": "A3.emotion", "min": "Watch"}]},
         "caution": None, "avoid": None, "note": "需特殊关注 → 加转介"},
        {"id": "passion_project", "group": "动机", "name": "Passion project",
         "assign": {"any": [{"all": [{"dim": "A2", "min": "Watch"},
                                     {"signal": "holland_peak"}]},
                            {"subtype": "A1-S2"}]},
         "caution": None, "avoid": None, "note": ""},
        {"id": "meaning_link", "group": "动机", "name": "意义连接",
         "assign": {"dim": "A2", "min": "Watch"},
         "caution": None, "avoid": None, "note": ""},
        {"id": "adult_affirmation", "group": "动机", "name": "成人肯定与鼓励",
         "assign": {"any": [{"dim": "A4", "min": "Watch"}, {"signal": "self_concept_low"}]},
         "caution": None, "avoid": None, "note": "家长门槛不过 → 改由导师"},
        {"id": "external_reward", "group": "动机", "name": "外部奖励",
         "assign": {"subtype": "A2-S4"},
         "caution": None, "avoid": None, "note": "少用"},
    ],
    "notes": {"A1": "", "A2": "", "A3": "", "A4": "", "A5": "", "A6": ""},
}


# ── 校验 ──────────────────────────────────────────────────────
def _err_condition(cond: Any, where: str) -> List[str]:
    if not isinstance(cond, dict):
        return [f"{where}：条件必须是对象"]
    keys = set(cond)
    if keys == {"not"}:
        return _err_condition(cond["not"], where + ".not")
    if keys == {"any"} or keys == {"all"}:
        subs = cond[next(iter(keys))]
        if not isinstance(subs, list) or not subs:
            return [f"{where}：{next(iter(keys))} 需要非空列表"]
        errs: List[str] = []
        for i, sub in enumerate(subs):
            errs.extend(_err_condition(sub, f"{where}[{i}]"))
        return errs
    if keys == {"signal"}:
        sid = cond["signal"]
        if not isinstance(sid, str) or sid not in SIGNALS:
            return [f"{where}：未知信号 {sid!r}"]
        return []
    if keys == {"dim", "min"}:
        if cond["dim"] not in DIMS:
            return [f"{where}：未知维度 {cond['dim']!r}"]
        if cond["min"] not in LEVELS:
            return [f"{where}：未知级别 {cond['min']!r}"]
        return []
    if keys == {"gate", "min"}:
        gate = str(cond["gate"])
        parts = gate.split(".")
        if len(parts) != 2 or parts[0] not in DIMS or parts[1] not in GATES:
            return [f"{where}：未知闸门 {gate!r}"]
        if cond["min"] not in LEVELS:
            return [f"{where}：未知级别 {cond['min']!r}"]
        return []
    if keys == {"subtype"}:
        if not isinstance(cond["subtype"], str) or not _SUBTYPE_RE.match(cond["subtype"]):
            return [f"{where}：亚型格式不合法 {cond['subtype']!r}"]
        return []
    if keys == {"dim_any_min"}:
        if cond["dim_any_min"] not in LEVELS:
            return [f"{where}：未知级别 {cond['dim_any_min']!r}"]
        return []
    return [f"{where}：条件语法不合法 {sorted(keys)}"]


def _dim_signal_ids(dim_spec: Dict[str, Any]) -> List[tuple]:
    """返回 [(信号 id, 是否 supporting)]。"""
    out: List[tuple] = []
    for key in ("main", "supporting", "secure", "type", "extra", "warn"):
        for sid in dim_spec.get(key) or []:
            out.append((sid, key == "supporting"))
    for key in ("activity", "confirm"):
        if dim_spec.get(key):
            out.append((dim_spec[key], False))
    if isinstance(dim_spec.get("tracks"), dict):
        for sid in dim_spec["tracks"].values():
            out.append((sid, False))
    gates = dim_spec.get("gates")
    if isinstance(gates, dict):
        for gate in gates.values():
            for sid in gate or []:
                out.append((sid, False))
    return out


def validate(spec: Dict[str, Any]) -> List[str]:
    """返回中文错误列表；空列表表示通过。"""
    errors: List[str] = []
    if not isinstance(spec, dict):
        return ["配置必须是对象"]

    params = spec.get("params") or {}
    if not isinstance(params, dict):
        errors.append("params 必须是对象")
        params = {}
    for name, (lo, hi) in _PARAM_RANGES.items():
        if name not in params:
            continue
        value = params[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"参数 {name} 必须是数字")
        elif not (lo <= value <= hi):
            errors.append(f"参数 {name} 超出范围（{lo}–{hi}）：{value}")

    dims = spec.get("dimensions") or {}
    if not isinstance(dims, dict):
        errors.append("dimensions 必须是对象")
        dims = {}
    for dim, dim_spec in dims.items():
        if dim not in DIMS:
            errors.append(f"未知维度：{dim}")
            continue
        if not isinstance(dim_spec, dict):
            errors.append(f"维度 {dim} 的配置必须是对象")
            continue
        for sid, is_supporting in _dim_signal_ids(dim_spec):
            if sid not in SIGNALS:
                errors.append(f"维度 {dim}：未知信号 {sid!r}")
                continue
            if is_supporting and dim not in SIGNALS[sid]["dims"]:
                errors.append(f"维度 {dim} 不支持支撑信号 {sid}")

    seen_a6: List[str] = []
    for i, entry in enumerate(spec.get("a6") or []):
        if not isinstance(entry, dict):
            errors.append(f"A6 第 {i + 1} 项必须是对象")
            continue
        aid = entry.get("id")
        if not aid:
            errors.append(f"A6 第 {i + 1} 项缺少 id")
            continue
        if aid in seen_a6:
            errors.append(f"A6 方案 id 重复：{aid}")
        seen_a6.append(aid)
        for field in ("assign", "caution", "avoid"):
            cond = entry.get(field)
            if cond is not None:
                errors.extend(_err_condition(cond, f"A6 {aid}.{field}"))

    return errors


# ── 可编辑视图 ────────────────────────────────────────────────
def editable_view(spec: Dict[str, Any]) -> Dict[str, Any]:
    """返回规则板可修改的字段：supporting、params、A6（条件/名称/备注）、notes。"""
    dims = spec.get("dimensions") or {}
    return {
        "params": copy.deepcopy(spec.get("params") or {}),
        "supporting": {dim: copy.deepcopy((dims.get(dim) or {}).get("supporting") or [])
                       for dim in dims},
        "a6": [{key: copy.deepcopy(entry.get(key))
                for key in ("id", "name", "assign", "caution", "avoid", "note")}
               for entry in spec.get("a6") or []],
        "notes": copy.deepcopy(spec.get("notes") or {}),
    }


def merge_edit(published_spec: Dict[str, Any], edited_spec: Dict[str, Any]) -> Dict[str, Any]:
    """只把可编辑字段从 edited_spec 合入 published_spec 的副本。"""
    out = copy.deepcopy(published_spec)
    edited_spec = edited_spec or {}

    edited_params = edited_spec.get("params")
    if isinstance(edited_params, dict):
        params = out.setdefault("params", {})
        for name in list(params):
            if name in edited_params:
                params[name] = edited_params[name]

    edited_dims = edited_spec.get("dimensions")
    if isinstance(edited_dims, dict):
        edited_supporting = {dim: (dim_spec or {}).get("supporting")
                             for dim, dim_spec in edited_dims.items()
                             if isinstance(dim_spec, dict)}
    else:
        edited_supporting = edited_spec.get("supporting")
    if isinstance(edited_supporting, dict):
        dims = out.setdefault("dimensions", {})
        for dim, dim_spec in dims.items():
            if isinstance(edited_supporting.get(dim), list):
                dim_spec["supporting"] = copy.deepcopy(edited_supporting[dim])

    edited_notes = edited_spec.get("notes")
    if isinstance(edited_notes, dict):
        notes = out.setdefault("notes", {})
        for key in list(notes):
            if key in edited_notes:
                notes[key] = edited_notes[key]

    edited_a6 = {entry.get("id"): entry for entry in edited_spec.get("a6") or []
                 if isinstance(entry, dict)}
    for entry in out.get("a6") or []:
        edit = edited_a6.get(entry.get("id"))
        if not edit:
            continue
        for key in ("name", "assign", "caution", "avoid", "note"):
            if key in edit:
                entry[key] = copy.deepcopy(edit[key])

    return out
