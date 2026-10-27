"""6 A.M. 引擎：单维判定 → state/亚型/confidence → A6 支持排序（带 trace）

纯函数层：不导入 Flask、不访问数据库。
输入为 evaluation_rules.build_evaluation_view 产出的 eval item 列表（见实施计划 §1.4）。

用法：
    from six_am import engine
    profile = engine.run(eval_items, student={...}, evidence={...}, params=None)
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional, Tuple

from . import rules as R

LEVELS = ["Secure", "Watch", "At-Risk", "Blocked"]
LEVEL_SEV = {"Secure": 0, "Watch": 1, "At-Risk": 2, "Blocked": 3}
CONF_ORDER = ["Hypothesis", "Supported", "Confirmed"]
DEFAULT_SUBS = {
    "同伴协作": ["Companion", "Group"],
    "导师督促": ["Accountability", "Structure", "Deadline", "正式 Feedback"],
    "家长陪同": ["家庭 Recognition", "陪跑", "低压力关注"],
}
DIRECTIONS = ["同伴协作", "导师督促", "家长陪同"]


# ── 求值上下文 ────────────────────────────────────────────────
class Ctx:
    def __init__(self, items: List[Dict[str, Any]], evidence: Optional[Dict[str, Any]],
                 params: Dict[str, Any]):
        self.params = params
        self.evidence = evidence or {}
        self.by_label: Dict[str, Dict[str, Any]] = {}
        self._order_map: Dict[str, int] = {}
        for it in items:
            key = _norm_label(it.get("label", ""))
            self.by_label.setdefault(key, it)
            entry = _order_entry(it)
            if entry:
                val, pos = entry
                if pos is not None and val not in self._order_map:
                    self._order_map[val] = pos
        self.top_n = int(params.get("order_top_n", 5))
        self._hits: Dict[str, Dict[str, Any]] = {}   # rule_id -> hit 记录
        self._dim_state: Dict[str, str] = {}
        self._dim_subtype: Dict[str, Optional[str]] = {}
        self.refuted: Dict[str, str] = {}            # 被追问否定的规则（移出命中集）

    # — 查询接口（谓词与条件共用）—
    def item(self, label: str) -> Optional[Dict[str, Any]]:
        return self.by_label.get(_norm_label(label))

    def eval_of(self, label: str) -> Optional[str]:
        it = self.item(label)
        if not it:
            return None
        v = it.get("eval_value")
        if v is None or str(v).strip() == "":
            return None
        return str(v).strip()

    def num_of(self, label: str) -> Optional[float]:
        it = self.item(label)
        if not it:
            return None
        for field in ("eval_value", "raw_value"):
            v = it.get(field)
            if v is None:
                continue
            try:
                return float(str(v).strip())
            except (TypeError, ValueError):
                continue
        return None

    def raw_num(self, label: str) -> Optional[float]:
        it = self.item(label)
        if not it:
            return None
        try:
            return float(str(it.get("raw_value")).strip())
        except (TypeError, ValueError):
            return None

    def tier_of(self, label: str) -> Optional[str]:
        """v0.4 证据强度：'strong' / 'mild' / None。

        Y4 档位是给报告读者的描述（如常模参照 '偏低' = 低于均分 0.5 分、
        执行功能 '偏低' = 百分位 < 60），直接当干预触发会覆盖大多数学生。
        这里把每个风险档位再分强弱；没有原始分时退回档位本身（偏低 = 弱）。
        """
        ev = self.eval_of(label)
        if ev is None:
            return None
        key = _norm_label(label)
        if key.startswith(("执行功能-", "认知能力")):
            pct = self.raw_num(label)
            if pct is None:
                return "mild" if ev in R.LOW_OR_BELOW else None
            if pct < float(self.params.get("pct_strong_max", 10)):
                return "strong"
            if pct < float(self.params.get("pct_mild_max", 25)):
                return "mild"
            return None
        if key.startswith(("自驱力-", "学习动机-", "学习方法与策略-")):
            if ev != "偏低":
                return None
            raw = self.raw_num(label)
            norm = self.num_of(key + "常模平均数")
            gap = float(self.params.get("norm_strong_gap", 1.5))
            if raw is not None and norm is not None and raw <= norm - gap:
                return "strong"
            return "mild"
        if ev in R.SEVERE:
            return "strong"
        if ev in R.MILD_RISK:
            return "mild"
        return None

    def order_pos(self, value: str) -> Optional[int]:
        return self._order_map.get(str(value))

    def order_pos_of(self, value: str) -> Optional[int]:
        return self.order_pos(value)

    def ev(self, path: str) -> Any:
        cur: Any = self.evidence
        for part in (path or "").split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        return cur

    def rule_hit(self, rule_id: str) -> bool:
        return rule_id in self._hits and rule_id not in self.refuted

    def register_hit(self, rule_id: str, rec: Dict[str, Any]) -> None:
        self._hits[rule_id] = rec

    def dim_state(self, dim: str) -> Optional[str]:
        return self._dim_state.get(dim)

    def subtype(self, dim: str) -> Optional[str]:
        return self._dim_subtype.get(dim)

    def set_dim_result(self, dim: str, state: Optional[str], subtype: Optional[str]) -> None:
        self._dim_state[dim] = state or "Secure"
        self._dim_subtype[dim] = subtype


def _norm_label(label: str) -> str:
    """与 evaluation_rules._norm_framework_label 相同的归一化（去空格、去尾部得分/百分位）。"""
    s = (label or "").replace(" ", "")
    for suf in ("得分", "百分位"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return s


def _order_pos(it: Dict[str, Any]) -> Optional[int]:
    raw = str(it.get("raw_value", "") or "")
    digits = ""
    for ch in raw:
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    return int(digits) if digits else None


def _order_entry(it: Dict[str, Any]) -> Optional[Tuple[str, Optional[int]]]:
    """排序项 → (值, 位次)。

    两种形态（与 y4_questions._build_groups 一致）：
    1. 原始排序项：label 尾部数字 = 位次（如 "职业价值观排序2" → 第 2 位），
       eval_value/raw_value = 值（如 "成就感"）；
    2. 合成位置项：code = "ORDERPOS:{值}"，raw_value = "第{pos}位/共{total}"。
    """
    code = str(it.get("code") or "")
    if code.startswith("ORDERPOS:"):
        val = code.split(":", 1)[1]
        return (val, _order_pos(it)) if val else None
    if it.get("eval_source") == "原始排序":
        val = str(it.get("eval_value") or it.get("raw_value") or "")
        label = str(it.get("label") or "")
        digits = ""
        for ch in reversed(label):
            if ch.isdigit():
                digits = ch + digits
            else:
                break
        pos = int(digits) if digits else _order_pos(it)
        if val:
            return val, pos
    return None


# ── 条件求值 ──────────────────────────────────────────────────
def _point_evidence(ctx: "Ctx", label: str, it: Dict[str, Any], evv: Optional[str]) -> Dict[str, Any]:
    """Y4 指标证据：附原始分、同龄常模与证据强度，供视图模型画判定依据。"""
    return {"point": label, "eval_value": evv, "raw_value": it.get("raw_value"),
            "norm": ctx.num_of(_norm_label(label) + "常模平均数"),
            "tier": ctx.tier_of(label),
            "source": it.get("eval_source", ""), "bias": it.get("data_bias") or ""}


def eval_cond(cond: Dict[str, Any], ctx: Ctx) -> Tuple[bool, List[Dict[str, Any]], str]:
    """返回 (是否命中, 证据列表, 描述)。"""
    if not isinstance(cond, dict):
        return False, [], ""
    if "any" in cond:
        for sub in cond.get("any") or []:
            ok, ev, desc = eval_cond(sub, ctx)
            if ok:
                return True, ev, desc
        return False, [], ""
    if "all" in cond:
        ev_all: List[Dict[str, Any]] = []
        for sub in cond.get("all") or []:
            ok, ev, _desc = eval_cond(sub, ctx)
            if not ok:
                return False, [], ""
            ev_all.extend(ev)
        return True, ev_all, "全部"
    if "not" in cond:
        ok, _ev, _desc = eval_cond(cond.get("not") or {}, ctx)
        return (not ok), [], "非"
    if "point" in cond:
        label = str(cond.get("point"))
        it = ctx.item(label)
        evv = ctx.eval_of(label)
        if it is None or evv is None:
            return False, [], f"{label} 缺失"
        if "is" in cond:
            ok = evv in [str(x) for x in cond.get("is") or []]
            ev = [_point_evidence(ctx, label, it, evv)]
            return ok, (ev if ok else []), f"{label}={evv}"
        if "num_lt" in cond or "num_gt" in cond:
            num = ctx.num_of(label)
            if num is None:
                return False, [], f"{label} 非数值"
            ok = True
            if "num_lt" in cond:
                th = _resolve_num(cond["num_lt"], ctx)
                ok = ok and th is not None and num < th
            if "num_gt" in cond:
                th = _resolve_num(cond["num_gt"], ctx)
                ok = ok and th is not None and num > th
            ev = [_point_evidence(ctx, label, it, ctx.eval_of(label))]
            return ok, (ev if ok else []), f"{label}={num}"
        if "tier" in cond:
            tier = ctx.tier_of(label)
            want = str(cond.get("tier"))
            ok = tier == "strong" if want == "strong" else tier in ("mild", "strong")
            ev = [_point_evidence(ctx, label, it, evv)]
            return ok, (ev if ok else []), f"{label}:{tier}"
        if cond.get("missing"):
            return False, [], f"{label}"
    if "order_top" in cond:
        value = str(cond.get("order_top"))
        pos = ctx.order_pos_of(value)
        ok = pos is not None and pos <= ctx.top_n
        ev = [{"order_value": value, "pos": pos, "top_n": ctx.top_n}]
        return ok, (ev if ok else []), f"ORDER:{value}"
    if "rule" in cond:
        rid = str(cond.get("rule"))
        ok = ctx.rule_hit(rid)
        return ok, ([{"rule": rid}] if ok else []), rid
    if "evidence" in cond:
        path = str(cond.get("evidence"))
        val = ctx.ev(path)
        want = cond.get("is_true", True)
        ok = bool(val) is bool(want) if want else val is None
        ev = [{"evidence": path, "value": val}]
        return ok, (ev if ok else []), path
    if "predicate" in cond:
        name = str(cond.get("predicate"))
        fn = R.PREDICATES.get(name)
        ok = bool(fn(ctx)) if fn else False
        return ok, ([{"predicate": name}] if ok else []), name
    if "dim_state" in cond:
        spec = cond.get("dim_state") or {}
        st = ctx.dim_state(str(spec.get("dim")))
        ok = st == spec.get("is")
        return ok, ([{"dim": spec.get("dim"), "state": st}] if ok else []), ""
    if "subtype" in cond:
        want = str(cond.get("subtype"))
        for d in R.DIMS:
            if ctx.subtype(d) == want:
                return True, [{"dim": d, "subtype": want}], want
        return False, [], want
    return False, [], ""


def _resolve_num(v: Any, ctx: Ctx) -> Optional[float]:
    if isinstance(v, str) and v.startswith("@"):
        v = ctx.params.get(v[1:])
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── 单维规则执行 ──────────────────────────────────────────────
class DimAcc:
    def __init__(self, dim: str):
        self.dim = dim
        self.level = 0
        self.pending_escalate = 0
        self.subtype: Optional[str] = None
        self.subtype_name: Optional[str] = None
        self.subtype_prio = -1
        self.deescalate = 0
        self.floor = "Watch"
        self.flags: List[str] = []
        self.notes: List[str] = []
        self.contrib_rules: List[Dict[str, Any]] = []   # {id, conf}
        self.trace: List[Dict[str, Any]] = []
        self.secure_confirmed = False

    def raise_to(self, state: str) -> None:
        self.level = max(self.level, LEVEL_SEV.get(state, 0))

    def add(self, n: int) -> None:
        self.level = min(3, self.level + n)


def _apply_then(rule: Dict[str, Any], ctx: Ctx, acc: DimAcc,
                hits_by_dim: Dict[str, Dict[str, Any]]) -> None:
    then = rule.get("then") or {}
    rid = rule["id"]
    effect: Dict[str, Any] = {}
    contributing = False

    def _sub(spec_sub: Optional[str], name: Optional[str], prio: int) -> None:
        nonlocal contributing
        if spec_sub and prio > acc.subtype_prio:
            acc.subtype, acc.subtype_name, acc.subtype_prio = spec_sub, name, prio
            contributing = True

    # 基础 state
    if then.get("state"):
        acc.raise_to(then["state"])
        effect["state"] = then["state"]
        contributing = True
    if then.get("escalate_if_rule") and ctx.rule_hit(str(then["escalate_if_rule"])):
        acc.pending_escalate += 1
        effect["escalate"] = f"因 {then['escalate_if_rule']} 升一级"
        contributing = True
    if then.get("escalate_if_dim"):
        th = LEVEL_SEV.get(str(then["escalate_if_dim"]), 2)
        if acc.level >= th:
            acc.pending_escalate += 1
            effect["escalate"] = f"维度已达 {then['escalate_if_dim']} 升一级"
            contributing = True
    if then.get("state_add"):
        acc.pending_escalate += int(then["state_add"])
        effect["state_add"] = then["state_add"]
        contributing = True
    # 亚型
    _sub(then.get("subtype"), then.get("subtype_name"), int(then.get("subtype_priority", 0)))
    if then.get("subtype"):
        effect["subtype"] = then["subtype"]
    st_if = then.get("subtype_if") or {}
    if st_if and st_if.get("predicate") and R.PREDICATES.get(str(st_if["predicate"])):
        if R.PREDICATES[str(st_if["predicate"])](ctx):
            _sub(st_if.get("subtype"), st_if.get("subtype_name"), int(st_if.get("subtype_priority", 0)))
            effect["subtype"] = st_if.get("subtype")
    # 去升级（R2.7）
    if then.get("deescalate"):
        acc.deescalate += int(then["deescalate"])
        acc.floor = str(then.get("floor") or "Watch")
        effect["deescalate"] = then["deescalate"]
        contributing = True
    # 置信
    rule_conf = str(then.get("confidence") or "Hypothesis")
    conf_to = then.get("confidence_to")
    conf_applied = None
    if conf_to:
        cond_ok = True
        if then.get("confidence_if") == "requires_subtype":
            cond_ok = None  # 后置判定
        if then.get("if_dim_severity"):
            cond_ok = acc.level >= LEVEL_SEV.get(str(then["if_dim_severity"]), 2)
        if cond_ok is True:
            conf_applied = str(conf_to)
            effect["confidence"] = conf_applied
            contributing = True
    # 条件效果
    for eff in then.get("effects") or []:
        ok = True
        if "if" in eff:
            ok, _ev, _d = eval_cond(eff["if"], ctx)
        if "if_any_rules" in eff:
            ok = any(ctx.rule_hit(x) for x in eff["if_any_rules"])
        if "if_no_rules" in eff:
            ok = not any(ctx.rule_hit(x) for x in eff["if_no_rules"])
        if "if_predicate" in eff:
            fn = R.PREDICATES.get(str(eff["if_predicate"]))
            ok = bool(fn(ctx)) if fn else False
        if not ok:
            continue
        if eff.get("state"):
            acc.raise_to(eff["state"])
            effect["state"] = eff["state"]
            contributing = True
        if eff.get("state_add"):
            acc.pending_escalate += int(eff["state_add"])
            effect["state_add"] = eff["state_add"]
            contributing = True
        if eff.get("subtype"):
            _sub(eff.get("subtype"), eff.get("subtype_name"), int(eff.get("subtype_priority", 0)))
            effect["subtype"] = eff.get("subtype")
        if eff.get("confidence_to"):
            conf_to = eff["confidence_to"]
            conf_applied = str(eff["confidence_to"])
            effect["confidence"] = conf_applied
            contributing = True
        for n in eff.get("notes") or []:
            acc.notes.append(n)
    if then.get("flags"):
        acc.flags.extend(then["flags"])
        effect["flags"] = list(then["flags"])
    for n in then.get("notes") or []:
        acc.notes.append(n)
    if then.get("confirmed_secure"):
        acc.secure_confirmed = True
    if then.get("noop"):
        contributing = False

    final_conf = conf_applied or rule_conf
    pending_conf = conf_to if then.get("confidence_if") == "requires_subtype" else None
    if contributing or pending_conf:
        acc.contrib_rules.append({"id": rid, "conf": final_conf,
                                  "pending_subtype_conf": pending_conf,
                                  "pending_only": bool(pending_conf) and not contributing})
    # trace 记录
    acc.trace.append({
        "id": rid,
        "title": rule.get("title", ""),
        "evidence": [],   # 由 _run_dim 填充
        "effect": effect,
        "confidence": final_conf if contributing else None,
        "contributing": contributing,
        "notes": list(then.get("notes") or []) + [n for eff in (then.get("effects") or []) for n in eff.get("notes") or []],
    })


def _run_dim(dim: str, rules_data: Dict[str, Dict[str, Any]], ctx: Ctx
             ) -> Tuple[DimAcc, List[Dict[str, Any]]]:
    acc = DimAcc(dim)
    hits: List[Dict[str, Any]] = []
    for rid in R.RULE_IDS:
        rule = rules_data.get(rid)
        if not rule or rule.get("dim") != dim:
            continue
        if rid in ctx.refuted:
            continue  # 被追问否定：不注册命中，也不产生 state/subtype/flag 写入
        ok = True
        ev_all: List[Dict[str, Any]] = []
        for cond in rule.get("when") or []:
            c_ok, c_ev, _desc = eval_cond(cond, ctx)
            if not c_ok:
                ok = False
                break
            ev_all.extend(c_ev)
        if not ok:
            continue
        ctx.register_hit(rid, {"id": rid})
        _apply_then(rule, ctx, acc, {})
        hit = {"id": rid, "title": rule.get("title", ""),
               "dim": dim,
               "evidence": ev_all,
               "effect": (acc.trace[-1]["effect"] if acc.trace else {}),
               "confidence": acc.trace[-1]["confidence"] if acc.trace else None,
               "contributing": acc.trace[-1]["contributing"] if acc.trace else False,
               "questions": list(rule.get("questions") or []),
               "text": rule.get("text", "")}
        if acc.trace:
            acc.trace[-1]["evidence"] = ev_all
        hits.append(hit)
    return acc, hits


# ── 维度终态（含升级/降级/置信）────────────────────────────────
def _finalize_dim(acc: DimAcc, ctx: Ctx, conf_overrides: Dict[str, str],
                  refuted: Dict[str, str]) -> Dict[str, Any]:
    acc.add(acc.pending_escalate)
    if acc.deescalate:
        floor = LEVEL_SEV.get(acc.floor, 1)
        acc.level = max(floor, acc.level - acc.deescalate) if acc.level > 0 else acc.level
    state = LEVELS[acc.level]
    # 亚型确诊耦合：requires_subtype 的置信提升（R4.8）
    confs: List[str] = []
    for cr in acc.contrib_rules:
        conf = cr["conf"]
        if cr.get("pending_subtype_conf"):
            if acc.subtype:
                conf = cr["pending_subtype_conf"]
            elif cr.get("pending_only"):
                continue  # 无亚型可确诊（如 R4.8 单独命中）→ 不参与置信计算
        override = conf_overrides.get(cr["id"])
        if override:
            conf = override
        confs.append(conf)
    confidence = None
    if confs:
        confidence = max(confs, key=lambda c: CONF_ORDER.index(c) if c in CONF_ORDER else 0)
    if state == "Secure" and not confs:
        confidence = None
    # v0.4：核心指标缺失时，"稳固/关注"只说明没有数据，不说明没有障碍
    missing = [l for l in (R.CORE_POINTS.get(acc.dim) or []) if ctx.eval_of(l) is None]
    if missing and state in ("Secure", "Watch"):
        acc.flags.append("Y4 数据缺失")
        acc.notes.append("核心 Y4 指标缺失（%s）：当前状态只反映已有数据，不能据此排除障碍"
                         % "、".join(missing))
    triggered = []
    for t in acc.trace:
        rec = dict(t)
        if t["id"] in refuted:
            rec["refuted"] = True
            rec["refuted_by"] = refuted[t["id"]]
        triggered.append(rec)
    return {
        "state": state,
        "subtype": acc.subtype,
        "subtype_name": acc.subtype_name,
        "confidence": confidence,
        "activation_key": R.ACTIVATION_KEYS.get(acc.dim),
        "triggered_rules": triggered,
        "cross_mods": [],
        "flags": acc.flags,
        "notes": acc.notes,
        "secure_confirmed": acc.secure_confirmed,
    }


# ── A6 支持方案（R6.* 选择器）──────────────────────────────────
# 定性适配级别（新版 §4.6：不输出数值分，优先级 避免 > 慎用 > 优先 > 可考虑；
# 冲突时以 R6.5–R6.7 的避免/慎用为准，见 X.5）
FIT_LABELS = ["优先", "可考虑", "慎用", "避免"]
FIT_RANK = {"优先": 0, "可考虑": 1, "慎用": 2, "避免": 3}
# A4 神经质背景（R4.5）下需补高压力评价 caution 的亚机制：认可 / 适度竞争
HIGH_PRESSURE_SUBS = ("Recognition", "Competition")


def _run_a6(ctx: Ctx, rules_data: Dict[str, Dict[str, Any]], hits_by_dim: Dict[str, List[Dict[str, Any]]],
            params: Dict[str, Any], dims: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    subs: Dict[str, List[str]] = {d: [] for d in DIRECTIONS}
    basis: Dict[str, List[str]] = {d: [] for d in DIRECTIONS}
    cautions: Dict[str, List[str]] = {d: [] for d in DIRECTIONS}
    supported: Dict[str, List[str]] = {d: [] for d in DIRECTIONS}   # 正向推荐依据规则
    marks: Dict[str, List[str]] = {d: [] for d in DIRECTIONS}       # 慎用/避免标记
    avoid: List[Dict[str, Any]] = []
    hits: List[Dict[str, Any]] = []
    trace: List[Dict[str, Any]] = []
    for rid in R.RULE_IDS:
        rule = rules_data.get(rid)
        if not rule or rule.get("dim") != "A6":
            continue
        ok = True
        ev_all: List[Dict[str, Any]] = []
        for cond in rule.get("when") or []:
            c_ok, c_ev, _desc = eval_cond(cond, ctx)
            if not c_ok:
                ok = False
                break
            ev_all.extend(c_ev)
        if not ok:
            continue
        ctx.register_hit(rid, {"id": rid})
        effect = {"support_ops": []}
        for op in (rule.get("then") or {}).get("support_ops") or []:
            d = str(op.get("direction"))
            if d not in subs:
                continue
            for s in op.get("sub") or []:
                if s not in subs[d]:
                    subs[d].append(s)
            if rid not in basis[d]:
                basis[d].append(rid)
            note = op.get("sub_note") or op.get("note")
            if note:
                cautions[d].append(note)
            kind = op.get("kind")
            if kind in ("慎用", "避免"):
                if kind not in marks[d]:
                    marks[d].append(kind)
                avoid.append({"direction": d, "kind": kind,
                              "basis_rules": [rid],
                              "reason": note or rule.get("title", "")})
            elif rid not in supported[d]:
                supported[d].append(rid)
            effect["support_ops"].append(op)
        hits.append({"id": rid, "title": rule.get("title", ""), "dim": "A6", "evidence": ev_all,
                     "effect": effect, "confidence": None, "contributing": True,
                     "questions": list(rule.get("questions") or []), "text": rule.get("text", "")})
        trace.append({"id": rid, "title": rule.get("title", ""), "evidence": ev_all,
                      "effect": effect, "confidence": None, "contributing": True,
                      "notes": []})
    # A4 神经质背景（R4.5 flag）：给“认可、适度竞争”亚机制补高压力评价 caution
    neuroticism = "神经质背景" in (((dims or {}).get("A4") or {}).get("flags") or [])
    ranked = []
    for d in DIRECTIONS:
        sub_list = subs[d] or list(DEFAULT_SUBS[d])
        if neuroticism and any(any(h in s for h in HIGH_PRESSURE_SUBS) for s in sub_list):
            cautions[d].append("减少高压力评价情境")
        if "避免" in marks[d]:
            fit = "避免"
        elif "慎用" in marks[d]:
            fit = "慎用"
        elif supported[d]:
            fit = "优先"
        else:
            fit = "可考虑"
        ranked.append({
            "direction": d,
            "sub_mechanisms": sub_list,
            "fit_label": fit,
            "basis_rules": basis[d],
            "cautions": "；".join(cautions[d]) if cautions[d] else "",
        })
    ranked.sort(key=lambda item: (FIT_RANK[item["fit_label"]], DIRECTIONS.index(item["direction"])))
    # 导师督促与 R6.6 冲突提示（X.5：以 R6.6 为准）
    if any(a["direction"] == "导师督促" and a["basis_rules"] == ["R6.6"] for a in avoid):
        for item in ranked:
            if item["direction"] == "导师督促" and "R6.7" in item["basis_rules"]:
                item["cautions"] = (item["cautions"] + "；" if item["cautions"] else "") + \
                    "X.5：与 R6.6 冲突时以 R6.6 慎用为准"
    dim_rec = {
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
    return dim_rec, hits


# ── 顶层入口 ─────────────────────────────────────────────────
def run(eval_items: List[Dict[str, Any]],
        student: Optional[Dict[str, Any]] = None,
        evidence: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        rule_version: Optional[Dict[str, Any]] = None,
        report_id: Optional[int] = None,
        answers: Optional[List[Dict[str, Any]]] = None,
        rule_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
        engine_version: Optional[str] = None) -> Dict[str, Any]:
    """执行 6 A.M. 全流程，返回 profile dict（结构见实施计划 §3.3）。

    v0.5（默认）：按 params["spec"] 的规则配置求值（见 evaluator）。
    v0.4：保留原规则引擎，供已固定的旧测试与历史档案复算。
    """
    from . import cross_rules, priority, questionnaire, evaluator
    raw_params = params or {}
    spec = raw_params.get("spec")
    version = engine_version
    if version is None:
        version = "v0.4" if raw_params.get("engine") == "v0.4" else "v0.5"
    params = R.merge_params({k: v for k, v in raw_params.items() if k != "spec"})
    rules_data = R.apply_rule_overrides(overrides=rule_overrides)
    answers = answers or []
    ctx = Ctx(eval_items, evidence, params)
    if version == "v0.5":
        from .spec import DEFAULT_SPEC
        spec = spec or DEFAULT_SPEC

    def _pass(refuted: Dict[str, str]) -> Tuple[Dict[str, DimAcc], Dict[str, List[Dict[str, Any]]]]:
        ctx._hits = {}
        ctx.refuted = dict(refuted)   # 被否定的规则：rule_hit() 一律返回 False
        accs: Dict[str, DimAcc] = {}
        hits: Dict[str, List[Dict[str, Any]]] = {}
        for dim in ["A1", "A2", "A3", "A4", "A5"]:
            # _run_dim 内跳过 ctx.refuted：不注册命中、不写 state/subtype/flag，维度重算
            acc, dhits = _run_dim(dim, rules_data, ctx)
            accs[dim] = acc
            hits[dim] = dhits
            # 供 A6 / X 规则读取中间态
            tmp_level = min(3, acc.level + acc.pending_escalate)
            ctx.set_dim_result(dim, LEVELS[tmp_level], acc.subtype)
        return accs, hits

    # 两遍：先无否定跑一遍，把答案映射到规则；再带否定重跑
    if version == "v0.5":
        # v0.5：信号求值两遍；否定答案移出对应信号，确认答案抬升维度置信
        dims, hits = evaluator.evaluate_dims(ctx, spec, {}, {})
        refuted: Dict[str, str] = {}
        conf_overrides: Dict[str, str] = {}
        for ans in answers:
            q = str(ans.get("q") or "")
            result = str(ans.get("result") or "")
            if not q:
                continue
            for dim, dhits in hits.items():
                for h in dhits:
                    if q not in (h.get("questions") or []):
                        continue
                    if result == "confirm":
                        conf_overrides[dim] = "Confirmed"
                    elif result == "partial" and conf_overrides.get(dim) != "Confirmed":
                        conf_overrides[dim] = "Supported"
                    elif result == "deny":
                        refuted[h["id"]] = q
        if refuted or conf_overrides:
            dims, hits = evaluator.evaluate_dims(ctx, spec, refuted, conf_overrides)
        a6_rec, a6_hits = evaluator.assign_supports(ctx, spec, dims)
        banners = evaluator.banners(ctx, spec)
    else:
        accs, hits = _pass({})
        conf_overrides, refuted = _map_answers(hits, answers)
        if refuted:
            accs, hits = _pass(refuted)

        dims = {}
        for dim in ["A1", "A2", "A3", "A4", "A5"]:
            dims[dim] = _finalize_dim(accs[dim], ctx, conf_overrides, refuted)
        a6_rec, a6_hits = _run_a6(ctx, rules_data, hits, params, dims)
        banners = {"flags": [], "safety": False}
    dims["A6"] = a6_rec
    hits["A6"] = a6_hits

    # 跨维度修正
    xres = cross_rules.apply(dims, ctx, params)
    for dim, mods in xres["mods"].items():
        dims[dim]["cross_mods"].extend(mods)
    for dim, notes in xres["notes"].items():
        dims[dim]["notes"].extend(notes)

    # 规则优先级（不使用数值权重，新版 §6）
    prio = priority.compute(dims, xres["constraints"])

    # 追问选择
    questions = questionnaire.select(dims, hits, params, prio["priority_order"])

    evidence_log = _evidence_log(evidence)
    goal = ((evidence or {}).get("ft") or {}).get("goal")
    if goal:
        evidence_log.append({"source": "FT", "kind": "goal", "detail": goal})

    profile = {
        "schema": "six-am-profile-v3" if version == "v0.5" else "six-am-profile-v2",
        "engine": version,
        "spec_version": str((spec or {}).get("version") or "") if version == "v0.5" else None,
        "flags_global": list(banners["flags"]),
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "rule_version": rule_version or {"id": None, "label": "default", "status": None},
        "student": {"name": (student or {}).get("name", ""), "grade": (student or {}).get("grade", "")},
        "report_id": report_id,
        "dimensions": dims,
        "obstacles": prio["obstacles"],
        "priority_order": prio["priority_order"],
        "deferred": prio["deferred"],
        "sequence_note": prio["sequence_note"],
        "support_plan": dims["A6"]["support_ranking"],
        "safety_review": bool(banners["safety"]) if version == "v0.5"
        else ("情绪安全复核" in (dims["A3"].get("flags") or [])),
        "questions": questions,
        "evidence_log": evidence_log,
        "gaps": _gaps(evidence),
        "answers": answers,
        "refuted": refuted,
    }
    return profile


def _map_answers(hits: Dict[str, List[Dict[str, Any]]], answers: List[Dict[str, Any]]
                 ) -> Tuple[Dict[str, str], Dict[str, str]]:
    """答案 → 规则置信升级/否定。

    语义（实施计划 §3.3）：confirm → Confirmed；partial → Supported（下限）；
    deny → refuted（移出命中集）。
    """
    conf_overrides: Dict[str, str] = {}
    refuted: Dict[str, str] = {}
    for ans in answers or []:
        q = str(ans.get("q") or "")
        result = str(ans.get("result") or "")
        if not q:
            continue
        for dim, dhits in hits.items():
            for h in dhits:
                if q in (h.get("questions") or []):
                    if result == "confirm":
                        conf_overrides[h["id"]] = "Confirmed"
                    elif result == "partial":
                        if conf_overrides.get(h["id"]) != "Confirmed":
                            conf_overrides[h["id"]] = "Supported"
                    elif result == "deny":
                        refuted[h["id"]] = q
    return conf_overrides, refuted


def _evidence_log(evidence: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    log: List[Dict[str, Any]] = []
    ev = evidence or {}
    ft = ev.get("ft") or {}
    if ft.get("schedule"):
        log.append({"source": "FT", "kind": "schedule", "detail": ft["schedule"]})
    if ft.get("standard_task"):
        log.append({"source": "FT", "kind": "standard_task", "detail": ft["standard_task"]})
    if ft.get("subject_status"):
        log.append({"source": "FT", "kind": "subject_status", "detail": ft["subject_status"]})
    if ft.get("notes"):
        log.append({"source": "FT", "kind": "notes", "detail": ft["notes"]})
    if ev.get("parent"):
        log.append({"source": "家长", "kind": "complaint", "detail": ev["parent"]})
    if ev.get("observation"):
        log.append({"source": "观察", "kind": "record", "detail": ev["observation"]})
    if ev.get("task"):
        log.append({"source": "FT", "kind": "task", "detail": ev["task"]})
    for ans in ev.get("answers") or []:
        log.append({"source": "追问", "kind": "answer", "detail": ans})
    return log


def _gaps(evidence: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    ev = evidence or {}
    ft = ev.get("ft") or {}
    parent = ev.get("parent") or {}
    return {
        "family_complaint": parent.get("complaint") or None,
        "schedule": ft.get("schedule") or None,
        "subject_status": ft.get("subject_status") or None,
        "standard_task": ft.get("standard_task") or None,
    }