"""6 A.M. 展示层：profile → 行动卡视图模型（网页与 DOCX 共用）

纯函数层：不导入 Flask、不访问数据库。

内容规则（实施计划 Task 3）：
- 一句话判断（headline）使用固定模板 + Y4 原词 + 6AM 规则标题/原文，
  不发明新术语（简明版 §2 三层信息边界）；
- 主卡字段不暴露规则公式或数值分数；audit 保留原始规则链、跨维修正、
  flags 与 notes，默认收拢；
- 容错读取迁移窗口内的 v1 profile：忽略旧 score 字段，缺失 priority_rank /
  priority_order / support_plan 时按固定 A1–A6 顺序降级展示，不得抛错；
- 人工行动修订（profile["action_overrides"]）替换生成的行动建议，
  空 override 回退到生成结果；
- 被追问否定的规则（profile["refuted"]）在 summary["refuted"] 与各卡
  audit["refuted_rules"] 中以「被排除 Refuted」标签呈现（engine 重跑会把
  它们移出 trace，展示信息在此恢复）。

卡片字段：dim, title, state, state_label, evidence_state, evidence_label,
headline, verdict, subtype_display, rationale, y4_facts, hypotheses,
confirmed_evidence, next_actions, avoid_actions, questions, audit,
priority_rank, priority_reason, priority_label, deferred, deferred_reason,
manually_edited。
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Tuple

from . import action_guidance
from . import rules as R
from .rationale import SUBTYPE_DISPLAY, build_rationale, verdict_for

DIM_ORDER = ["A1", "A2", "A3", "A4", "A5", "A6"]

STATE_LABELS = {
    "Secure": "稳固 Secure",
    "Watch": "关注 Watch",
    "At-Risk": "风险 At-Risk",
    "Blocked": "阻塞 Blocked",
}
EVIDENCE_LABELS = {
    "Hypothesis": "仅线索 Hypothesis",
    "Supported": "有佐证 Supported",
    "Confirmed": "已证实 Confirmed",
    "Refuted": "被排除 Refuted",
}
REFUTED_LABEL = EVIDENCE_LABELS["Refuted"]

A6_STATE_LABEL = "支持选择器"

SECURE_HEADLINE = "现有 Y4 事实未提示该维度构成启动障碍。"


def build_view_model(profile: Dict[str, Any]) -> Dict[str, Any]:
    """把 profile 转为网页与 DOCX 共用的行动卡视图模型。

    返回 {"summary": {...}, "cards": [六张卡，固定 A1–A6 顺序]}。
    """
    profile = profile or {}
    dims = profile.get("dimensions") or {}
    a6_rec = dims.get("A6") or {}
    support_plan = copy.deepcopy(
        profile.get("support_plan") or a6_rec.get("support_ranking") or {})
    for key in ("ranked", "avoid"):
        for entry in support_plan.get(key) or []:
            if isinstance(entry, dict) and entry.get("direction") == "权威施压":
                entry["direction"] = "导师督促"
    overrides = profile.get("action_overrides") or {}
    deferred_reasons = {str(d.get("dim")): str(d.get("reason") or "")
                        for d in (profile.get("deferred") or []) if isinstance(d, dict)}
    questions = profile.get("questions") or []
    answers = profile.get("answers") or []
    refuted = _refuted_entries(profile.get("refuted") or {})

    cards = [
        _build_card(dim, dims.get(dim) or {}, support_plan,
                    overrides.get(dim) or {}, deferred_reasons, questions,
                    [r for r in refuted if r["dim"] == dim], answers)
        for dim in DIM_ORDER
    ]
    return {"summary": _summary(profile, cards, refuted), "cards": cards}


def _refuted_entries(refuted_map: Dict[str, Any]) -> List[Dict[str, str]]:
    """profile["refuted"]（{规则ID: 否定它的追问ID}）→ 可渲染「被排除 Refuted」的条目。

    engine 第二遍会把被否定的规则移出 trace，视图模型必须从这里恢复展示信息；
    规则 title/dim 取自 rules.RULES（规则版本不允许覆盖 title）。
    """
    entries: List[Dict[str, str]] = []
    for rid, by in refuted_map.items():
        rule = R.RULES.get(str(rid)) or {}
        entries.append({
            "rule": str(rid),
            "title": str(rule.get("title") or ""),
            "dim": str(rule.get("dim") or ""),
            "refuted_by": str(by or ""),
            "label": REFUTED_LABEL,
        })
    return entries


# ── 单卡 ─────────────────────────────────────────────────────────
def _build_card(dim: str, rec: Dict[str, Any], support_plan: Dict[str, Any],
                override: Dict[str, Any], deferred_reasons: Dict[str, str],
                questions: List[Dict[str, Any]],
                refuted_rules: List[Dict[str, str]],
                answers: List[Dict[str, Any]]) -> Dict[str, Any]:
    rec = rec or {}
    if dim == "A6":
        state: Optional[str] = None
        state_label = A6_STATE_LABEL
    else:
        state = str(rec.get("state") or "Secure")
        state_label = STATE_LABELS.get(state, state)
    evidence_state = rec.get("confidence") or None
    evidence_label = EVIDENCE_LABELS.get(str(evidence_state), "") if evidence_state else ""

    y4_facts = _y4_facts(rec)
    hypotheses = _hypotheses(rec)
    confirmed_evidence = _confirmed_evidence(rec)

    generated = action_guidance.guidance_for(dim, rec, support_plan)
    next_actions = override.get("next_actions") or generated["next_actions"]
    avoid_actions = override.get("avoid_actions") or generated["avoid_actions"]
    manually_edited = bool(override.get("next_actions") or override.get("avoid_actions"))

    deferred = bool(rec.get("deferred")) or dim in deferred_reasons
    deferred_reason = deferred_reasons.get(dim) or \
        (str(rec.get("priority_reason") or "") if deferred else "")
    priority_rank = rec.get("priority_rank")
    if not isinstance(priority_rank, int):
        priority_rank = None
    if deferred:
        priority_label = "长期目标"
    elif priority_rank is not None:
        priority_label = "优先处理"
    else:
        priority_label = ""

    return {
        "dim": dim,
        "title": R.DIM_NAMES.get(dim, dim),
        "state": state,
        "state_label": state_label,
        "evidence_state": evidence_state,
        "evidence_label": evidence_label,
        "headline": _headline(dim, rec, state, state_label, evidence_state,
                              y4_facts, hypotheses, confirmed_evidence,
                              support_plan),
        "verdict": verdict_for(dim, rec),
        "subtype_display": SUBTYPE_DISPLAY.get(str(rec.get("subtype") or "")),
        "rationale": build_rationale(dim, rec, questions, answers),
        "y4_facts": y4_facts,
        "hypotheses": hypotheses,
        "confirmed_evidence": confirmed_evidence,
        "next_actions": next_actions,
        "avoid_actions": avoid_actions,
        "questions": [q for q in questions if str((q or {}).get("dim")) == dim],
        "audit": _audit(dim, rec, refuted_rules),
        "priority_rank": priority_rank,
        "priority_reason": str(rec.get("priority_reason") or ""),
        "priority_label": priority_label,
        "deferred": deferred,
        "deferred_reason": deferred_reason,
        "manually_edited": manually_edited,
    }


# ── headline 固定模板（实施计划 Task 3）──────────────────────────
def _headline(dim: str, rec: Dict[str, Any], state: Optional[str],
              state_label: str, evidence_state: Optional[str],
              y4_facts: List[str], hypotheses: List[str],
              confirmed_evidence: List[str],
              support_plan: Dict[str, Any]) -> str:
    if dim == "A6":
        prefer, avoid = _a6_directions(support_plan)
        return "根据前五维结论，优先尝试：%s；需要避免：%s。" % (prefer, avoid)
    if state == "Secure":
        return SECURE_HEADLINE
    if evidence_state in ("Supported", "Confirmed"):
        subtype_name = str(rec.get("subtype_name") or "")
        verdict = state_label + ("（%s）" % subtype_name if subtype_name else "")
        basis = confirmed_evidence + [f for f in y4_facts if f not in confirmed_evidence]
        basis_text = "；".join(basis) if basis else "现有记录"
        return "根据目前证据，当前判断为：%s；依据包括：%s。" % (verdict, basis_text)
    # 仅线索（Hypothesis / 无置信）
    facts_text = "；".join(y4_facts) if y4_facts else "暂无 Y4 事实记录"
    hypo_text = "；".join(hypotheses) if hypotheses else "待验证假设"
    return "Y4 显示：%s；可能指向：%s，需要进一步确认。" % (facts_text, hypo_text)


def _a6_directions(support_plan: Dict[str, Any]) -> Tuple[str, str]:
    plan = support_plan or {}
    ranked = plan.get("ranked") or []
    prefer = [str(r.get("direction")) for r in ranked
              if str((r or {}).get("fit_label") or "") == "优先" and r.get("direction")]
    if not prefer and ranked:
        first = ranked[0] or {}
        if first.get("direction"):
            prefer = ["%s（%s）" % (first["direction"], first.get("fit_label") or "可考虑")]
    avoid = ["%s（%s）" % (a.get("direction"), a.get("kind"))
             for a in (plan.get("avoid") or []) if (a or {}).get("direction")]
    if not avoid:
        avoid = [str(r.get("direction")) + "（" + str(r.get("fit_label")) + "）"
                 for r in ranked
                 if str((r or {}).get("fit_label") or "") in ("慎用", "避免")
                 and r.get("direction")]
    return ("、".join(prefer) if prefer else "暂无",
            "、".join(avoid) if avoid else "无")


# ── 证据分层提取（简明版 §2 / §8 记录格式）───────────────────────
def _y4_facts(rec: Dict[str, Any]) -> List[str]:
    """只写 Y4 实际显示的指标和结果（指标名 + 值，或排序位次）。"""
    facts: List[str] = []
    for t in rec.get("triggered_rules") or []:
        for ev in (t or {}).get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            if "point" in ev:
                val = ev.get("eval_value")
                if val is None or str(val).strip() == "":
                    val = ev.get("raw_value")
                _append_once(facts, "%s：%s" % (ev.get("point"), val))
            elif "order_value" in ev:
                pos = ev.get("pos")
                top_n = ev.get("top_n")
                if pos is not None:
                    _append_once(facts, "%s排在前 %s（第 %s 位）"
                                 % (ev.get("order_value"), top_n, pos))
    return facts


def _hypotheses(rec: Dict[str, Any]) -> List[str]:
    """初筛假设：命中且起作用的规则标题（Hypothesis 级优先）。"""
    titles: List[str] = []
    fallback: List[str] = []
    for t in rec.get("triggered_rules") or []:
        if not (t or {}).get("contributing") or not t.get("title"):
            continue
        fallback.append(str(t["title"]))
        if str(t.get("confidence") or "Hypothesis") == "Hypothesis":
            titles.append(str(t["title"]))
    return _dedup(titles or fallback)


def _confirmed_evidence(rec: Dict[str, Any]) -> List[str]:
    """已确认依据：维度置信达 Supported/Confirmed 时收 contributing 规则标题。

    trace 内的规则置信不含追问升级，故看维度级置信。
    {"evidence": path} 条目是内部字段路径，只留在 audit.triggered_rules，
    不进主卡字段（内容规则：主卡只用 Y4 原词 / 规则原文）。
    """
    out: List[str] = []
    dim_confirmed = str(rec.get("confidence") or "") in ("Supported", "Confirmed")
    if not dim_confirmed:
        return out
    for t in rec.get("triggered_rules") or []:
        if not (t or {}).get("contributing"):
            continue
        if t.get("title"):
            _append_once(out, str(t["title"]))
    return out


# v1 旧引擎冻结在 cross_mods.action 里的打分叙事（如 "A4 score ×0.7（其分数让位于 A3）"）；
# 审前裁定：未迁移 v1 profile 也不得展示旧权重 wording。
_LEGACY_SCORE_WORDING = re.compile(r"score|分数|×\s*\d", re.IGNORECASE)


def _sanitize_cross_mods(mods: Any) -> List[Dict[str, Any]]:
    """跨维修正展示净化：含旧打分措辞的 action 回退为规则表中的现行规范文本。"""
    out: List[Dict[str, Any]] = []
    for m in mods or []:
        if not isinstance(m, dict):
            continue
        m = dict(m)
        action = str(m.get("action") or "")
        if _LEGACY_SCORE_WORDING.search(action):
            canon = R.CROSS_RULES.get(str(m.get("id") or "")) or {}
            m["action"] = str(canon.get("action") or "")
        out.append(m)
    return out


# A6 支持排序审计白名单：v1 条目带数值 score 字段（predicted_effectiveness 为定性标签，保留）
_RANKED_FIELDS = ("direction", "sub_mechanisms", "fit_label",
                  "predicted_effectiveness", "basis_rules", "cautions", "top")
_AVOID_FIELDS = ("direction", "kind", "basis_rules", "reason")


def _sanitize_support_ranking(sr: Any) -> Any:
    """A6 支持排序白名单重建：剔除 v1 数值 score 等字段，只留定性展示字段。"""
    if not isinstance(sr, dict):
        return sr
    out = dict(sr)
    out["ranked"] = [{k: r[k] for k in _RANKED_FIELDS if k in r}
                     for r in sr.get("ranked") or [] if isinstance(r, dict)]
    if "avoid" in sr:
        out["avoid"] = [{k: a[k] for k in _AVOID_FIELDS if k in a}
                        for a in sr.get("avoid") or [] if isinstance(a, dict)]
    return out


def _audit(dim: str, rec: Dict[str, Any],
           refuted_rules: List[Dict[str, str]]) -> Dict[str, Any]:
    """审计区：原始规则链、跨维修正、flags、notes、被排除规则（默认收拢，不进主卡字段）。"""
    audit = {
        "triggered_rules": rec.get("triggered_rules") or [],
        "cross_mods": _sanitize_cross_mods(rec.get("cross_mods")),
        "flags": rec.get("flags") or [],
        "notes": rec.get("notes") or [],
        "refuted_rules": refuted_rules,
    }
    if dim == "A6" and rec.get("support_ranking"):
        audit["support_ranking"] = _sanitize_support_ranking(rec["support_ranking"])
    return audit


# ── 摘要条 ───────────────────────────────────────────────────────
_OBSTACLE_FIELDS = ("dim", "sequence", "priority_reason", "state", "evidence_state")


def _summary(profile: Dict[str, Any], cards: List[Dict[str, Any]],
             refuted: List[Dict[str, str]]) -> Dict[str, Any]:
    obstacles = profile.get("obstacles") or []
    priority_order = profile.get("priority_order")
    # v2 判定锚点：engine 重算会同时写 priority_order 与规则化 sequence_note；
    # v1 legacy 无 priority_order，其 sequence_note 是旧打分叙事（如"分数 ×0.7"），
    # 不透传进视图模型（审前裁定：页面不得展示旧权重 wording）。
    has_v2_order = bool(priority_order)
    if not priority_order:
        # v1 降级：固定 A1–A5 顺序中的非 Secure、未 defer 维度
        priority_order = [c["dim"] for c in cards
                          if c["dim"] != "A6" and not c["deferred"]
                          and c["state"] not in (None, "Secure")]
    primary = None
    if obstacles and isinstance(obstacles[0], dict):
        # 白名单重建：v1 障碍条目可能带 score/high_priority，不得泄漏进视图模型
        primary = {k: obstacles[0].get(k) for k in _OBSTACLE_FIELDS}
    return {
        "student": profile.get("student") or {},
        "report_id": profile.get("report_id"),
        "schema": profile.get("schema"),
        "generated_at": profile.get("generated_at"),
        "primary_obstacle": primary,
        "priority_order": priority_order,
        "deferred": profile.get("deferred") or [],
        "sequence_note": (profile.get("sequence_note") or "") if has_v2_order else "",
        "open_question_count": len(profile.get("questions") or []),
        "evidence_states": {c["dim"]: c["evidence_state"] for c in cards},
        "refuted": refuted,
    }


def _append_once(target: List[str], text: str) -> None:
    if text and text not in target:
        target.append(text)


def _dedup(items: List[str]) -> List[str]:
    out: List[str] = []
    for x in items:
        _append_once(out, x)
    return out
