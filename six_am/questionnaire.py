"""6 A.M. 追问选择（v0.2 §8.2 选择算法）

纯函数：不导入 Flask、不访问数据库。

五步：
1. 收集所有 state ≥ Watch 的维度，按 ObstacleScore 降序；
2. 前 N 个维度（hypothesis_dim_limit，默认 3）中 confidence = Hypothesis 的优先；
3. 每个被标记维度至少保留 1 题（逐轮轮询，避免高分维度挤占全部名额）；
4. A6 固定保留 1–2 题（a6_slots，默认 2）；
5. 去重、输出 Top-N（top_n，默认 8）。题目文本与验证目标取自 rules.QUESTIONS。
"""

from __future__ import annotations

from typing import Any, Dict, List

from . import rules as R

DIM_ORDER = ["A1", "A2", "A3", "A4", "A5"]
SEV = {"Secure": 0, "Watch": 1, "At-Risk": 2, "Blocked": 3}

# A6 规则 → 关联追问。R6.6（自主受损，成人方向慎用）补 Q6.3：
# 该题区分 Recognition（被看见）与 Privacy（别盯着），是慎用方向的直接验证。
# 校准依据：v0.2 §10 例 1 期望追问含 Q6.3。
A6_RULE_QUESTIONS: Dict[str, List[str]] = {
    "R6.1": ["Q6.1"],
    "R6.2": ["Q6.2"],
    "R6.3": ["Q6.2"],
    "R6.4": ["Q6.3"],
    "R6.5": ["Q6.3", "Q6.4"],
    "R6.6": ["Q6.3"],
    "R6.7": ["Q6.2"],
    "R6.8": [],
}


def select(dims: Dict[str, Any], hits: Dict[str, List[Dict[str, Any]]],
           params: Dict[str, Any]) -> List[Dict[str, Any]]:
    qcfg = params.get("questionnaire") or {}
    top_n = int(qcfg.get("top_n", 8))
    a6_slots = int(qcfg.get("a6_slots", 2))
    h_limit = int(qcfg.get("hypothesis_dim_limit", 3))

    pools: Dict[str, List[Dict[str, Any]]] = {}
    for dim in DIM_ORDER:
        pools[dim] = _dim_queue(hits.get(dim) or [])
    pools["A6"] = _a6_queue(hits.get("A6") or [], a6_slots)

    # 步骤 1：state ≥ Watch；步骤 2：前 N 维中 Hypothesis 优先
    def _score_of(dim: str) -> float:
        rec = dims.get(dim) or {}
        return float(((rec.get("score") or {}).get("total")) or 0.0)

    cands = [d for d in DIM_ORDER
             if SEV.get(str((dims.get(d) or {}).get("state") or "Secure"), 0) >= 1]
    ranked = sorted(cands, key=lambda d: (-_score_of(d), DIM_ORDER.index(d)))
    top_n_dims = ranked[:h_limit]
    pri = [d for d in top_n_dims
           if str((dims.get(d) or {}).get("confidence") or "") == "Hypothesis"]
    rest = [d for d in top_n_dims if d not in pri] + ranked[h_limit:]
    dim_order = pri + rest + ["A6"]

    # 步骤 3–5：逐轮轮询（每维每轮 1 题），A6 上限 a6_slots，去重后取 Top-N
    selected: List[Dict[str, Any]] = []
    a6_taken = 0
    while len(selected) < top_n:
        progressed = False
        for dim in dim_order:
            if len(selected) >= top_n:
                break
            if dim == "A6" and a6_taken >= a6_slots:
                continue
            pool = pools.get(dim) or []
            if not pool:
                continue
            rec = pool.pop(0)
            selected.append(_item(rec, dim, len(selected) + 1))
            progressed = True
            if dim == "A6":
                a6_taken += 1
        if not progressed:
            break
    return selected


def _dim_queue(dhits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """维度内：规则按效果严重级降序、再按规则 ID 升序；问题去重并记录依据规则。"""
    ordered = sorted(dhits, key=lambda h: (-_rule_sev(h), _rule_idx(h.get("id"))))
    by_q: Dict[str, List[str]] = {}
    for h in ordered:
        for q in h.get("questions") or []:
            by_q.setdefault(str(q), []).append(str(h.get("id")))
    return [{"q": q, "basis": basis} for q, basis in by_q.items()]


def _a6_queue(a6_hits: List[Dict[str, Any]], slots: int) -> List[Dict[str, Any]]:
    """A6：规则关联题 + 不足 slots 时按 A6_FILL_ORDER 补足。"""
    by_q: Dict[str, List[str]] = {}
    for h in sorted(a6_hits, key=lambda x: _rule_idx(x.get("id"))):
        rid = str(h.get("id"))
        for q in A6_RULE_QUESTIONS.get(rid, []) or []:
            by_q.setdefault(q, []).append(rid)
    for q in R.A6_FILL_ORDER:
        if len(by_q) >= max(1, slots):
            break
        by_q.setdefault(q, [])
    return [{"q": q, "basis": basis} for q, basis in by_q.items()]


def _rule_sev(h: Dict[str, Any]) -> int:
    eff = h.get("effect") or {}
    sev = SEV.get(str(eff.get("state") or ""), 0)
    try:
        sev += int(eff.get("state_add") or 0)
    except (TypeError, ValueError):
        pass
    if eff.get("escalate"):
        sev += 1
    return sev


def _rule_idx(rid: Any) -> int:
    rid = str(rid)
    return R.RULE_IDS.index(rid) if rid in R.RULE_IDS else 99


def _item(rec: Dict[str, Any], dim: str, priority: int) -> Dict[str, Any]:
    qid = str(rec["q"])
    q = R.QUESTIONS.get(qid) or {}
    verify = list(q.get("verify") or [])
    basis = list(rec.get("basis") or []) or list(verify)
    return {
        "id": qid,
        "ask": q.get("ask", ""),
        "verify": verify,
        "priority": priority,
        "dim": dim,
        "basis_rules": basis,
    }