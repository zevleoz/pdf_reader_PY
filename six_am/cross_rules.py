"""6 A.M. 跨维度修正规则 X.1–X.7（v0.2 §5）

纯函数：不导入 Flask、不访问数据库。
engine 在单维判定（A1–A6）完成后调用 apply()，返回：

    {
      "mods":        {dim: [{"id": "X.2", "action": "..."}]},   # 写入该维 cross_mods
      "notes":       {dim: ["..."]},                             # 追加到该维 notes
      "multipliers": {dim: float},                               # scoring 的 Amplifier
      "constraints": {"x1": bool, "x3_top": bool, "x6": bool, "x7": bool, ...}
    }

X.5 按实施计划在 A6 选择器（engine R6.5–R6.7）内兼容性处理；此处只在
"R6.6 慎用 × R6.7 Structure" 真冲突时补一条裁决记录。
"""

from __future__ import annotations

from typing import Any, Dict, List

DIMS5 = ["A1", "A2", "A3", "A4", "A5"]
SEV = {"Secure": 0, "Watch": 1, "At-Risk": 2, "Blocked": 3}


def apply(dims: Dict[str, Any], ctx, params: Dict[str, Any]) -> Dict[str, Any]:
    mods: Dict[str, List[Dict[str, str]]] = {}
    notes: Dict[str, List[str]] = {}
    multipliers: Dict[str, float] = {d: 1.0 for d in DIMS5}
    constraints: Dict[str, bool] = {
        "x1": False, "x2": False, "x3": False, "x3_top": False,
        "x4": False, "x5": False, "x6": False, "x7": False,
    }

    def _add_mod(dim: str, rid: str, action: str) -> None:
        mods.setdefault(dim, []).append({"id": rid, "action": action})

    def _add_note(dim: str, text: str) -> None:
        notes.setdefault(dim, []).append(text)

    def _sev(dim: str) -> int:
        return SEV.get(str((dims.get(dim) or {}).get("state") or "Secure"), 0)

    # ── X.1 Double-Lock 双锁 ──────────────────────────────────
    if _sev("A1") >= 2 and _sev("A2") >= 2:
        x1 = float(params.get("x1_multiplier", 1.5))
        multipliers["A1"] *= x1
        multipliers["A2"] *= x1
        constraints["x1"] = True
        action = (f"Double-Lock 双锁：A1×A2 均 ≥ At-Risk，两维 obstacle score ×{x1}；"
                  "处理顺序固定为先 A1 后 A2（没有所有权时谈意义会被当成新一轮说教）")
        _add_mod("A1", "X.1", action)
        _add_mod("A2", "X.1", action)

    # ── X.2 A2 信号污染修正 ───────────────────────────────────
    if str((dims.get("A1") or {}).get("subtype") or "") == "A1-S2":
        adult_arranged = bool(ctx.ev("task.adult_arranged"))
        student_chosen = bool(ctx.ev("task.student_chosen"))
        prior_engagement = bool(ctx.ev("observation.prior_engagement_same_domain")
                                or ctx.ev("ft.prior_engagement_same_domain"))
        # 任务信息缺省视为成人安排（择校/活动由成人发起的场景）；
        # 有学生自选任务信息或既往主动投入证据时，A2 信号不被污染
        if adult_arranged or not (student_chosen or prior_engagement):
            a2 = dims.setdefault("A2", {})
            if SEV.get(str(a2.get("state") or "Secure"), 0) < 1:
                a2["state"] = "Watch"
            if a2.get("confidence") != "Confirmed":
                a2["confidence"] = "Hypothesis"
            constraints["x2"] = True
            _add_mod("A2", "X.2",
                     "A2 信号污染修正：逆反型学生对'被安排的任务'不认同，不代表对内容本身不认同；"
                     "A2 confidence 降一级（Confirmed 除外，下限 Hypothesis）")
            _add_note("A2", "需用学生自选任务重测")

    # ── X.3 A3 优先排除 ───────────────────────────────────────
    if _sev("A3") >= 2:
        x3 = float(params.get("x3_multiplier", 0.7))
        multipliers["A4"] *= x3
        multipliers["A5"] *= x3
        constraints["x3"] = True
        constraints["x3_top"] = True
        for dim in ("A4", "A5"):
            _add_mod(dim, "X.3",
                     f"A3 优先排除：疲劳与过载会伪装成低自信、低规划；obstacle 排序中 A3 强制置顶，"
                     f"{dim} score ×{x3}（其分数让位于 A3）")
            if str((dims.get(dim) or {}).get("confidence") or "") == "Hypothesis" \
                    and SEV.get(str((dims.get(dim) or {}).get("state") or "Secure"), 0) >= 1:
                _add_note(dim, "待 A3 处理后复测")

    # ── X.4 A4 约束 A5 设计 ───────────────────────────────────
    if _sev("A4") >= 2:
        constraints["x4"] = True
        _add_mod("A5", "X.4",
                 "A4 约束 A5 设计：First Move 必须满足低风险标准——可私下完成、允许低质量、无即时评价")
        _add_note("A5", "First Move 低风险约束：可私下完成、允许低质量、无即时评价")

    # ── X.5 A6 统筹约束（冲突裁决记录）────────────────────────
    if ctx.rule_hit("R6.6") and ctx.rule_hit("R6.7"):
        constraints["x5"] = True
        _add_mod("A6", "X.5",
                 "A6 统筹约束：R6.6（自主受损 → 权威施压/家长陪同慎用）与 R6.7（结构依赖 → Structure 排前）"
                 "冲突，以 R6.6 的慎用为准")

    # ── X.6 全局无兴趣优先级 ──────────────────────────────────
    a2 = dims.get("A2") or {}
    if str(a2.get("subtype") or "") == "A2-S3" and _sev("A2") >= 2:
        constraints["x6"] = True
        for dim in ("A1", "A5"):
            _add_mod(dim, "X.6",
                     "全局无兴趣：所有任务级干预暂缓（A1 选择设计、A5 First Move）；"
                     "处理顺序改为：兴趣探索 → 再评估")
        _add_note("A1", "A2 全局无兴趣（已交叉验证）：任务级干预暂缓，先做兴趣探索")
        _add_note("A5", "A2 全局无兴趣（已交叉验证）：First Move 类任务级干预暂缓")

    # ── X.7 家长无法让渡主导权 ────────────────────────────────
    if bool(ctx.ev("parent.cannot_relinquish")):
        x7 = float(params.get("x7_multiplier", 0.5))
        multipliers["A1"] *= x7
        constraints["x7"] = True
        _add_mod("A1", "X.7",
                 f"家长无法让渡主导权：A1 obstacle score ×{x7}，A1 干预降级为长期目标；"
                 "干预重心转向 A2 意义匹配（在家长划定的边界内帮学生找到'这件事跟我有关'的理由）")

    return {"mods": mods, "notes": notes, "multipliers": multipliers, "constraints": constraints}