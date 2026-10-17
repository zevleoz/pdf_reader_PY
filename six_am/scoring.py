"""6 A.M. 评分层：Obstacle Score（v0.2 §6）与处理顺序（sequence）

纯函数：不导入 Flask、不访问数据库。
输入为 engine 汇总后的 dims（A1–A5 五维终态）+ cross_rules 产出的
multipliers / constraints + params。

公式（v0.2 §6.1）：
    ObstacleScore(i) = Severity(state_i) × ConfidenceFactor(conf_i) × Amplifier(i)
    - Severity：Secure=0 / Watch=1 / At-Risk=2 / Blocked=3
    - R4.5 神经质背景：A4 severity +0.5（封顶 3，仅在已有风险时叠加，不独立判风险）
    - ConfidenceFactor：Hypothesis=0.7 / Supported=1.0 / Confirmed=1.2
    - Amplifier：X.1 ×1.5（A1/A2 两维）、X.3 ×0.7（A4/A5）、X.7 ×0.5（A1）

所有数值来自 params（默认见 rules.DEFAULT_PARAMS），不硬编码。
本模块同时把分数分解写回 dims[dim]["score"]（页面/档案的分数分解视图）。
"""

from __future__ import annotations

from typing import Any, Dict, List

DIM_ORDER = ["A1", "A2", "A3", "A4", "A5"]
_R45_FLAG = "神经质背景"


def compute(dims: Dict[str, Any],
            multipliers: Dict[str, float],
            constraints: Dict[str, Any],
            params: Dict[str, Any]) -> Dict[str, Any]:
    """返回 {"obstacles": [...], "sequence_note": str}；并写回 dims[dim]["score"]。"""
    sev_map = params.get("severity") or {"Secure": 0, "Watch": 1, "At-Risk": 2, "Blocked": 3}
    conf_map = params.get("confidence_factor") or {"Hypothesis": 0.7, "Supported": 1.0, "Confirmed": 1.2}
    r45 = params.get("r45_neuroticism") or {}
    hp_min = float(params.get("high_priority_min_score", 2.0))

    obstacles: List[Dict[str, Any]] = []
    for dim in DIM_ORDER:
        rec = dims.get(dim) or {}
        state = str(rec.get("state") or "Secure")
        conf = rec.get("confidence")
        severity = float(sev_map.get(state, 0))

        severity_add = 0.0
        if dim == "A4" and _R45_FLAG in (rec.get("flags") or []) and severity > 0 and r45:
            severity_add = float(r45.get("value", 0.5))
            cap = float(r45.get("cap", 3))
            severity = min(cap, severity + severity_add)

        if conf in conf_map:
            cf = float(conf_map[conf])
        else:
            # 有风险但无置信标注（理论不应出现）：按最低置信计
            cf = float(conf_map.get("Hypothesis", 0.7)) if severity > 0 else 0.0
        amplifier = float((multipliers or {}).get(dim, 1.0))
        total = round(severity * cf * amplifier, 2)

        rec["score"] = {
            "severity": severity,
            "severity_add": severity_add,
            "confidence_factor": cf,
            "amplifier": amplifier,
            "total": total,
        }
        if total > 0:
            obstacles.append({
                "dim": dim,
                "score": total,
                "high_priority": bool(total >= hp_min and state in ("At-Risk", "Blocked")),
                "sequence": None,
                "sequence_note": "",
            })

    # 列表按 Obstacle Score 降序（同分按维度顺序）
    obstacles.sort(key=lambda o: (-o["score"], DIM_ORDER.index(o["dim"])))

    # 处理顺序：分数排序叠加依赖约束（X.3 置顶 / X.1 先 A1 后 A2 / X.6 暂缓 / X.7 降级）
    x1 = bool((constraints or {}).get("x1"))
    x3_top = bool((constraints or {}).get("x3_top"))
    x6 = bool((constraints or {}).get("x6"))
    x7 = bool((constraints or {}).get("x7"))

    def _seq_key(o: Dict[str, Any]) -> tuple:
        d = o["dim"]
        pri = 0
        if x7 and d == "A1":
            pri = 2          # X.7：A1 干预降级为长期目标 → 排到最后
        elif x3_top and d == "A3":
            pri = -2         # X.3：A3 强制置顶
        elif x1 and d == "A1":
            pri = -1         # X.1：先 A1 后 A2（同 pri 时按分数）
        return (pri, -o["score"], DIM_ORDER.index(d))

    ordered = sorted(obstacles, key=_seq_key)
    for i, o in enumerate(ordered, 1):
        o["sequence"] = i
        o["sequence_note"] = _seq_note(o["dim"], x1, x3_top, x6, x7)

    obstacles.sort(key=lambda o: (-o["score"], DIM_ORDER.index(o["dim"])))

    notes: List[str] = []
    if x3_top:
        notes.append("X.3 命中：A3 强制置顶；A4/A5 分数 ×0.7（让位于 A3），其 Hypothesis 级结论待 A3 处理后复测。")
    if x1:
        notes.append("X.1 命中：A1×A2 双锁，两维分数 ×1.5；处理顺序固定为先 A1 后 A2。")
    if x6:
        notes.append("X.6 命中：A2 全局无兴趣，所有任务级干预（A1 选择设计、A5 First Move）暂缓；处理顺序改为：兴趣探索 → 再评估。")
    if x7:
        notes.append("X.7 命中：家长无法让渡主导权，A1 干预降级为长期目标（分数 ×0.5）；干预重心转向 A2 意义匹配。")

    return {"obstacles": obstacles, "sequence_note": " ".join(notes)}


def _seq_note(dim: str, x1: bool, x3_top: bool, x6: bool, x7: bool) -> str:
    parts: List[str] = []
    if x3_top and dim == "A3":
        parts.append("X.3 强制置顶")
    if x1 and dim in ("A1", "A2"):
        parts.append("X.1 先 A1 后 A2")
    if x6 and dim in ("A1", "A5"):
        parts.append("X.6 任务级干预暂缓")
    if x7 and dim == "A1":
        parts.append("X.7 降级为长期目标")
    return "；".join(parts)