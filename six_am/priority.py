"""6 A.M. 优先级层：不使用权重的规则优先级（新版 §6）

纯函数：不导入 Flask、不访问数据库。

本模型不使用数值公式计算"障碍分数"。处理顺序按以下确定性规则确定：

1. constraints["x3_top"] 或 A3 = Blocked → A3 第一（与 X.6 同时命中仍 A3 先于 A2）；
2. constraints["x6"]（A2 全局无兴趣）→ A2 进入兴趣探索优先位，
   A1/A5 写"任务级干预暂缓"原因；X.6 与 X.1 同时命中时 A2 仍排在 A1 前；
3. constraints["x7"] → A1 不进入常规障碍排序，写入 deferred
   （长期目标：家长无法或不愿让渡主导权），当前优先级转向 A2 意义连接；
4. constraints["x1"] → A1 必须先于 A2；但 X.6 命中时 A1 为任务级干预暂缓，
   X.1 不得把 A1 提到 A2 前；X.7 已 defer A1 时不拉回；
5. 其余维度：证据状态 Confirmed > Supported > Hypothesis/None，
   再按状态 Blocked > At-Risk > Watch，最后按 A1–A5 固定顺序；
6. A4 与 A5 同级并列时 A4 在前（由固定顺序保证：先低风险第一步，再增加任务要求）；
7. A6 不进入障碍排序，只跟随 A1–A5 输出支持方案；
8. v0.4：R3.7 情绪安全复核命中时，sequence_note 以安全复核开头（先于一切启动推进）。

compute() 同时把 priority_rank / priority_reason 写回每个非 Secure 维度，
供追问选择（questionnaire）与页面标记使用。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

DIM_ORDER = ["A1", "A2", "A3", "A4", "A5"]
_EVIDENCE_RANK = {"Confirmed": 0, "Supported": 1, "Hypothesis": 2, None: 2}
_STATE_RANK = {"Blocked": 0, "At-Risk": 1, "Watch": 2, "Secure": 3}

X7_DEFER_REASON = ("长期目标：家长无法或不愿让渡主导权；"
                   "当前优先级转向 A2 意义连接（在家长划定的边界内帮学生找到"
                   "'这件事跟我有关'的理由）")


def compute(dims: Dict[str, Any], constraints: Dict[str, Any]) -> Dict[str, Any]:
    """返回 {"obstacles": [...], "priority_order": [...], "deferred": [...],
    "sequence_note": str}；并写回 dims[dim]["priority_rank"/"priority_reason"]。"""
    constraints = constraints or {}
    x1 = bool(constraints.get("x1"))
    x3_top = bool(constraints.get("x3_top"))
    x6 = bool(constraints.get("x6"))
    x7 = bool(constraints.get("x7"))
    safety = "情绪安全复核" in (((dims.get("A3") or {}).get("flags")) or [])

    def _state(dim: str) -> str:
        return str((dims.get(dim) or {}).get("state") or "Secure")

    def _evidence(dim: str) -> Optional[str]:
        return (dims.get(dim) or {}).get("confidence")

    # 关注维度：state ≥ Watch
    cands = [d for d in DIM_ORDER if _STATE_RANK.get(_state(d), 3) < 3]

    deferred: List[Dict[str, str]] = []
    if x7 and "A1" in cands:
        cands.remove("A1")
        deferred.append({"dim": "A1", "reason": X7_DEFER_REASON})
        rec = dims.get("A1")
        if rec is not None:
            rec["priority_rank"] = None
            rec["priority_reason"] = X7_DEFER_REASON
            rec["deferred"] = True

    def _group(dim: str) -> int:
        if dim == "A3" and (x3_top or _state("A3") == "Blocked"):
            return 0                       # 规则 1：A3 过载优先排除
        if dim == "A2" and x6:
            return 1                       # 规则 2：兴趣探索优先位（先于 X.1 的 A1）
        if dim == "A1" and x1:
            return 2                       # 规则 4：X.1 双锁，先 A1 后 A2（X.6 未命中时）
        return 3

    ordered = sorted(cands, key=lambda d: (
        _group(d),
        _EVIDENCE_RANK.get(_evidence(d), 2),
        _STATE_RANK.get(_state(d), 3),
        DIM_ORDER.index(d),
    ))

    obstacles: List[Dict[str, Any]] = []
    for i, dim in enumerate(ordered, 1):
        reason = _reason(dim, dims, x1, x3_top, x6, x7)
        obstacles.append({
            "dim": dim,
            "sequence": i,
            "priority_reason": reason,
            "state": _state(dim),
            "evidence_state": _evidence(dim),
        })
        rec = dims.get(dim)
        if rec is not None:
            rec["priority_rank"] = i
            rec["priority_reason"] = reason

    return {
        "obstacles": obstacles,
        "priority_order": [o["dim"] for o in obstacles],
        "deferred": deferred,
        "sequence_note": _sequence_note(x1, x3_top, x6, x7, safety),
    }


def _reason(dim: str, dims: Dict[str, Any],
            x1: bool, x3_top: bool, x6: bool, x7: bool) -> str:
    state = str((dims.get(dim) or {}).get("state") or "Secure")
    if dim == "A3" and (x3_top or state == "Blocked"):
        return ("A3 过载优先排除：容量不足时先腾出空间，再复评其他维度"
                + ("（X.3 命中）" if x3_top else "（A3 Blocked）"))
    if dim == "A2" and x6:
        return "X.6 命中：A2 全局无兴趣，兴趣探索优先，再谈任务启动"
    if dim == "A2" and x7:
        return "X.7 命中：家长无法让渡主导权，当前优先级转向 A2 意义连接"
    if x6 and dim in ("A1", "A5"):
        return "X.6 命中：A2 全局无兴趣，任务级干预暂缓（先兴趣探索，再评估）"
    if dim == "A1" and x1:
        return "X.1 双锁：A1×A2 同时受阻，先恢复所有权再谈意义（先 A1 后 A2）"
    evidence = (dims.get(dim) or {}).get("confidence") or "Hypothesis"
    return "证据状态 %s · 状态 %s" % (evidence, state)


SAFETY_NOTE = ("情绪安全复核：Y4 情绪指标落在最严重档。先由顾问了解学生近况，"
               "必要时建议家长寻求专业评估；评估前不新增任务、不做启动推进。")


def _sequence_note(x1: bool, x3_top: bool, x6: bool, x7: bool, safety: bool = False) -> str:
    notes: List[str] = []
    if safety:
        notes.append(SAFETY_NOTE)
    if x3_top:
        notes.append("X.3 命中：A3 过载优先排除，先处理容量问题；"
                     "A4/A5 的 Hypothesis 级结论待 A3 处理后复测。")
    if x1:
        notes.append("X.1 命中：A1×A2 双锁，处理顺序固定为先 A1 后 A2。")
    if x6:
        notes.append("X.6 命中：A2 全局无兴趣，所有任务级干预（A1 选择设计、"
                     "A5 First Move）暂缓；处理顺序改为：兴趣探索 → 再评估。")
    if x7:
        notes.append("X.7 命中：家长无法或不愿让渡主导权，A1 干预调整为长期目标；"
                     "当前优先在家长边界内建立 A2 意义连接。")
    return " ".join(notes)
