"""6 A.M. 行动指导：简明版 §4 固定行动模板 + A6 支持方案读取

纯函数层：不导入 Flask、不访问数据库。

内容规则（实施计划 Task 3）：
- 按简明版 §4 表中的 A1-S1/S2/S3、A2-S1/S2/S3/S4、A3-S1/S2/S3、A4-S1/S2/S3、
  A5-S1/S2/S3 与 A6 支持方向建立显式映射；没有亚型时用维度级默认模板；
- 行动文案只引用模型文档中的支持/避免表达、规则 title/text、Y4 指标名和值，
  不新增解释性术语；
- A6 从 support_plan.ranked 与 avoid 读取（fit_label / cautions / reason），
  不使用数值分。
"""

from __future__ import annotations

from typing import Any, Dict, List

# ── 亚型级模板（简明版 §4「确认后的支持 / 使用边界」列原文）────────────
SUBTYPE_GUIDANCE: Dict[str, Dict[str, List[str]]] = {
    "A1-S1": {"next": ["让学生参与决定 Why / What / How"], "avoid": []},
    "A1-S2": {"next": ["先恢复所有权，允许修改目标、说“不”"], "avoid": ["避免追加监督"]},
    "A1-S3": {"next": ["从小范围自主决定开始练习"], "avoid": []},
    "A2-S1": {"next": ["调整活动内容或形式，使其连接兴趣与优势"], "avoid": []},
    "A2-S2": {"next": ["建立内部意义，减少只靠升学或家长理由推进"], "avoid": []},
    "A2-S3": {"next": ["经交叉验证后，先兴趣探索，再安排具体任务"],
              "avoid": ["暂缓具体任务推进"]},
    "A2-S4": {"next": ["先寻找与学生有关的理由，不急于加任务"], "avoid": []},
    "A3-S1": {"next": ["先减负、降优先级，必要时延迟启动", "优先恢复睡眠和基本精力"],
              "avoid": []},
    "A3-S2": {"next": ["调整作息、运动和恢复安排"], "avoid": []},
    "A3-S3": {"next": ["减少并行任务，提供外部结构"], "avoid": []},
    "A4-S1": {"next": ["允许低质量初稿，建立 Draft 0，降低第一步难度"], "avoid": []},
    "A4-S2": {"next": ["设计可完成的早期成功，提供示范和陪跑"], "avoid": []},
    "A4-S3": {"next": ["私下、低压力、无即时评价的尝试"], "avoid": []},
    "A5-S1": {"next": ["拆不出时，提供任务拆分和示范"], "avoid": []},
    "A5-S2": {"next": ["帮助收敛选项，再设计第一步"], "avoid": []},
    "A5-S3": {"next": ["拆得出但不启动时，提供时间、地点、流程和陪伴"], "avoid": []},
}

# ── 维度级默认模板（无亚型时；取自 §4 表格维度首行的支持列）─────────────
DIM_DEFAULT_GUIDANCE: Dict[str, Dict[str, List[str]]] = {
    "A1": {"next": ["提供有限选择，共同确定目标和方案"], "avoid": []},
    "A2": {"next": ["连接学生重视的价值，而非成人包装意义"], "avoid": []},
    "A3": {"next": ["优先恢复睡眠和基本精力"], "avoid": []},
    "A4": {"next": ["设计可完成的早期成功，提供示范和陪跑"], "avoid": []},
    "A5": {"next": ["提供任务拆分和示范"], "avoid": []},
}

# ── 规则级附加模板（§4 表中未对应亚型的行，命中即追加）──────────────────
RULE_EXTRA_GUIDANCE: Dict[str, Dict[str, List[str]]] = {
    "R2.5": {"next": ["连接学生重视的价值，而非成人包装意义"], "avoid": []},
    "R2.6": {"next": ["调整任务形式"], "avoid": []},
    "R3.1": {"next": ["优先恢复睡眠和基本精力"], "avoid": []},
    "R5.4": {"next": ["缩短第一步时长，减少干扰"], "avoid": []},
    "R5.8": {"next": ["必要时转介"], "avoid": []},
}

SECURE_GUIDANCE: Dict[str, List[str]] = {"next": ["常规推进"], "avoid": []}

# 简明版 §4 A3 处理原则 / §5 联动：A3 过载时先处理容量，再复评 A4/A5
A3_REASSESS_NOTE = "先处理容量问题，再复评 A4/A5"
# 简明版 §4 A4 R4.5 行：神经质背景为高压力评价场景的 caution 输入
A4_HIGH_PRESSURE_NOTE = "减少高压力评价情境"
# cross_rules X.4：A4 信心问题约束 A5 First Move 低风险设计
X4_FIRST_MOVE_NOTE = "First Move 低风险约束：可私下完成、允许低质量、无即时评价"


def _append(target: List[str], text: str) -> None:
    if text and text not in target:
        target.append(text)


def guidance_for(dim: str, rec: Dict[str, Any],
                 support_plan: Dict[str, Any]) -> Dict[str, List[str]]:
    """返回 {"next_actions": [...], "avoid_actions": [...]}。

    dim 为 A1–A6；rec 为该维度记录（可缺字段）；support_plan 仅 A6 使用。
    """
    dim = str(dim or "")
    rec = rec or {}
    if dim == "A6":
        return _a6_guidance(support_plan)

    state = str(rec.get("state") or "Secure")
    if state == "Secure":
        return {"next_actions": list(SECURE_GUIDANCE["next"]), "avoid_actions": []}

    subtype = str(rec.get("subtype") or "")
    tpl = SUBTYPE_GUIDANCE.get(subtype) or DIM_DEFAULT_GUIDANCE.get(dim) \
        or {"next": [], "avoid": []}
    next_actions = list(tpl["next"])
    avoid_actions = list(tpl["avoid"])

    # A3 过载处理原则：At-Risk 及以上先恢复容量，再复评 A4/A5
    if dim == "A3" and state in ("At-Risk", "Blocked"):
        _append(next_actions, A3_REASSESS_NOTE)
    # A4 神经质背景（R4.5 flag）：补高压力评价提示
    if dim == "A4" and "神经质背景" in (rec.get("flags") or []):
        _append(next_actions, A4_HIGH_PRESSURE_NOTE)
    # X.4：A4 存在信心问题时，A5 的 First Move 必须低风险
    if any(str(m.get("id")) == "X.4" for m in (rec.get("cross_mods") or [])):
        _append(next_actions, X4_FIRST_MOVE_NOTE)
    # 规则级附加模板
    for t in rec.get("triggered_rules") or []:
        extra = RULE_EXTRA_GUIDANCE.get(str((t or {}).get("id")))
        if not extra:
            continue
        for a in extra["next"]:
            _append(next_actions, a)
        for a in extra["avoid"]:
            _append(avoid_actions, a)
    return {"next_actions": next_actions, "avoid_actions": avoid_actions}


def _a6_guidance(support_plan: Dict[str, Any]) -> Dict[str, List[str]]:
    """A6：从 support_plan.ranked / avoid 读取定性适配结果。

    avoid 列表带规则依据原文，优先展示；ranked 中已被 avoid 覆盖的
    （方向, 适配级别）组合不重复追加。
    """
    plan = support_plan or {}
    next_actions: List[str] = []
    avoid_actions: List[str] = []
    avoid_covered = set()
    for a in plan.get("avoid") or []:
        direction = str((a or {}).get("direction") or "")
        kind = str((a or {}).get("kind") or "")
        reason = str((a or {}).get("reason") or "")
        if not direction:
            continue
        avoid_covered.add((direction, kind))
        entry = "%s%s" % (direction, kind)
        if reason:
            entry += "：" + reason
        _append(avoid_actions, entry)
    for r in plan.get("ranked") or []:
        direction = str((r or {}).get("direction") or "")
        fit = str((r or {}).get("fit_label") or "")
        if not direction:
            continue
        subs = "、".join(str(s) for s in (r.get("sub_mechanisms") or []))
        cautions = str(r.get("cautions") or "")
        if fit in ("优先", "可考虑"):
            entry = "%s（%s）" % (direction, fit)
            if subs:
                entry += "：" + subs
            _append(next_actions, entry)
            if cautions:
                _append(next_actions, "%s注意：%s" % (direction, cautions))
        elif fit in ("慎用", "避免") and (direction, fit) not in avoid_covered:
            entry = "%s%s" % (direction, fit)
            if cautions:
                entry += "：" + cautions
            _append(avoid_actions, entry)
    return {"next_actions": next_actions, "avoid_actions": avoid_actions}
