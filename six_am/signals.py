"""6 A.M. v0.5 信号库。

每条信号 = 一个小的判定函数，返回：
    {"hit": bool, "level": "Watch" | "At-Risk" | None,
     "evidence": [point evidence…], "distance": float | None, "subtype": str | None}

约定：
- 缺失数据 → hit False、level None。
- `level` 只看信号自身含义：风险信号给 Watch / At-Risk；
  保护性 / 类型 / A6 匹配 / banner 信号给 None（命中即代表条件成立）。
- `distance` = 原始分与参照的落差（越负越远），仅用于同级别内排序：
  常模参照 raw − norm；情绪分项 raw − 10；人格 raw − 3.0；其余 None。

`SIGNALS` 保存展示用元数据（board 读），`evaluate` 负责求值。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import rules as R
from .engine import Ctx, _point_evidence

_LEVELS = ("Watch", "At-Risk")

_NORM_LABELS = "较好 / 不低 / 偏低（常模 ±0.5）"
_PERSON_LABELS = "高 / 较好 / 不低 / 偏低 / 明显偏低 / 严重偏低"
_BODY_LABELS = "优秀 / 良好 / 中等 / 一般 / 较差 / 差"
_EMO_LABELS = "需特殊关注 / 需关注 / 相对健康（原始分 5–15）"
_EMO_TOTAL_LABELS = "高 / 较好 / 不低 / 偏低 / 明显偏低"
_PCT_LABELS = "高 / 较好 / 不低 / 偏低（百分位 ≥95 / ≥80 / ≥60）"
_HOLLAND_LABELS = "高 / 不低 / 偏低（7–10 / 4–6 / 0–3）"
_SELF_LABELS = "高 / 较好 / 不低 / 偏低 / 严重偏低"
_ATTACH_LABELS = "高 / 不低 / 偏低"
_ORDER_LABELS = "职业价值观排序位次"
_SEVERE_EMO = ("需特殊关注",)
_WATCH_EMO = ("需关注",)
_EMO_RISK = ("需关注", "需特殊关注")

SIGNALS: Dict[str, Dict[str, Any]] = {
    "autonomy": {
        "id": "autonomy", "label": "自驱力-自主性", "source": "Y4 测评",
        "kind": "main", "dims": ["A1"], "questions": ["Q1.1"],
        "params": [], "official_labels": _NORM_LABELS,
    },
    "deep_motive": {
        "id": "deep_motive", "label": "学习动机-深层动机", "source": "Y4 测评",
        "kind": "main", "dims": ["A2"], "questions": ["Q2.2"],
        "params": [], "official_labels": _NORM_LABELS,
    },
    "self_efficacy": {
        "id": "self_efficacy", "label": "学习动机-自我效能感", "source": "Y4 测评",
        "kind": "track", "dims": ["A4"], "questions": ["Q4.1"],
        "params": [], "official_labels": _NORM_LABELS,
    },
    "competence": {
        "id": "competence", "label": "自驱力-胜任感", "source": "Y4 测评",
        "kind": "track", "dims": ["A4"], "questions": ["Q4.1"],
        "params": [], "official_labels": _NORM_LABELS,
    },
    "conscientiousness": {
        "id": "conscientiousness", "label": "人格-责任心", "source": "Y4 测评",
        "kind": "main", "dims": ["A5"], "questions": ["Q5.1", "Q5.2"],
        "params": [], "official_labels": _PERSON_LABELS,
    },
    "sleep": {
        "id": "sleep", "label": "体质健康-睡眠评级", "source": "Y4 测评",
        "kind": "gate body", "dims": ["A3"], "questions": ["Q3.1"],
        "params": [], "official_labels": _BODY_LABELS,
    },
    "exercise_diet": {
        "id": "exercise_diet", "label": "运动评级 / 饮食评级", "source": "Y4 测评",
        "kind": "gate body", "dims": ["A3"], "questions": ["Q3.1"],
        "params": [], "official_labels": _BODY_LABELS,
    },
    "anxiety": {
        "id": "anxiety", "label": "情绪稳定性-焦虑安详", "source": "Y4 测评",
        "kind": "gate emotion", "dims": ["A3"], "questions": ["Q3.2"],
        "params": [], "official_labels": _EMO_LABELS,
    },
    "depression": {
        "id": "depression", "label": "情绪稳定性-抑郁愉快", "source": "Y4 测评",
        "kind": "gate emotion", "dims": ["A3"], "questions": ["Q3.2"],
        "params": [], "official_labels": _EMO_LABELS,
    },
    "schedule_full": {
        "id": "schedule_full", "label": "时间是否排满（First Touch）", "source": "First Touch",
        "kind": "gate time", "dims": ["A3"], "questions": ["Q3.3", "Q3.4"],
        "params": ["schedule_free_hours_max"], "official_labels": "排满程度 高 / 中 / 低；每周自由小时数",
    },
    "ft_goal": {
        "id": "ft_goal", "label": "当前目标认同（First Touch）", "source": "First Touch",
        "kind": "activity", "dims": ["A2"], "questions": ["Q2.1", "Q2.3", "Q2.4"],
        "params": [], "official_labels": "认同 / 部分认同 / 不认同",
    },
    "ft_task": {
        "id": "ft_task", "label": "规划小任务（First Touch）", "source": "First Touch",
        "kind": "confirm", "dims": ["A5"], "questions": ["Q5.4"],
        "params": [], "official_labels": "能否拆出步骤 / 能否承诺（是 / 否）",
    },
    "indep_boss_top5": {
        "id": "indep_boss_top5", "label": "独立自主 + 上司关系 同进前 N", "source": "Y4 职业价值观",
        "kind": "supporting", "dims": ["A1"], "questions": ["Q1.3", "Q1.4"],
        "params": ["top_n_values"], "official_labels": _ORDER_LABELS,
    },
    "control_low": {
        "id": "control_low", "label": "无力感掌控感 1–5", "source": "Y4 测评",
        "kind": "supporting", "dims": ["A1", "A4"], "questions": ["Q1.6"],
        "params": ["control_low_max"], "official_labels": "1–15 分（≤5 为低）",
    },
    "control_high": {
        "id": "control_high", "label": "无力感掌控感 11–15", "source": "Y4 测评",
        "kind": "secure", "dims": ["A1"], "questions": [],
        "params": ["control_high_min"], "official_labels": "1–15 分（≥11 为高）",
    },
    "wellbeing_ok": {
        "id": "wellbeing_ok", "label": "自我概念-幸福与满足", "source": "Y4 测评",
        "kind": "secure", "dims": ["A1"], "questions": [],
        "params": [], "official_labels": _SELF_LABELS,
    },
    "surface_low": {
        "id": "surface_low", "label": "学习动机-表面动机 偏低", "source": "Y4 测评",
        "kind": "supporting", "dims": ["A2"], "questions": ["Q2.2"],
        "params": [], "official_labels": _NORM_LABELS,
    },
    "surface_not_low": {
        "id": "surface_not_low", "label": "学习动机-表面动机 不低", "source": "Y4 测评",
        "kind": "type", "dims": ["A2"], "questions": ["Q2.2"],
        "params": [], "official_labels": _NORM_LABELS,
    },
    "parent_complaint": {
        "id": "parent_complaint", "label": "家长主诉", "source": "家长主诉",
        "kind": "supporting", "dims": ["A2"], "questions": [],
        "params": [], "official_labels": "有 / 无",
    },
    "holland_all_low": {
        "id": "holland_all_low", "label": "霍兰德六型全低", "source": "Y4 职业兴趣",
        "kind": "type", "dims": ["A2"], "questions": ["Q2.5", "Q2.6"],
        "params": [], "official_labels": _HOLLAND_LABELS,
    },
    "holland_peak": {
        "id": "holland_peak", "label": "霍兰德有高峰", "source": "Y4 职业兴趣",
        "kind": "a6", "dims": [], "questions": [],
        "params": [], "official_labels": _HOLLAND_LABELS,
    },
    "holland_c_high": {
        "id": "holland_c_high", "label": "霍兰德常规型高", "source": "Y4 职业兴趣",
        "kind": "supporting", "dims": ["A5"], "questions": [],
        "params": [], "official_labels": _HOLLAND_LABELS,
    },
    "emotion_total_low": {
        "id": "emotion_total_low", "label": "情绪稳定性总分 明显偏低", "source": "Y4 测评",
        "kind": "supporting", "dims": ["A3"], "questions": [],
        "params": [], "official_labels": _EMO_TOTAL_LABELS,
    },
    "wm_flex_low": {
        "id": "wm_flex_low", "label": "工作记忆 / 认知灵活性 偏低", "source": "Y4 测评",
        "kind": "extra", "dims": ["A3"], "questions": [],
        "params": [], "official_labels": _PCT_LABELS,
    },
    "esteem_anx": {
        "id": "esteem_anx", "label": "自卑自尊 + 焦虑", "source": "Y4 测评",
        "kind": "supporting", "dims": ["A4"], "questions": ["Q4.4"],
        "params": [], "official_labels": _EMO_LABELS,
    },
    "safety_top3": {
        "id": "safety_top3", "label": "安全稳定 进前 N", "source": "Y4 职业价值观",
        "kind": "supporting", "dims": ["A4"], "questions": [],
        "params": ["top_n_safety"], "official_labels": _ORDER_LABELS,
    },
    "cog_vs_self": {
        "id": "cog_vs_self", "label": "认知能力 vs 自评", "source": "Y4 测评",
        "kind": "supporting", "dims": ["A4"], "questions": ["Q4.5"],
        "params": ["cog_pct_min"], "official_labels": "认知能力百分位 vs 自评档位",
    },
    "self_concept_low": {
        "id": "self_concept_low", "label": "自我概念偏低", "source": "Y4 测评",
        "kind": "supporting", "dims": ["A4"], "questions": [],
        "params": [], "official_labels": "偏高 / 正常 / 偏低；能力与学校表现 " + _SELF_LABELS,
    },
    "mindset_low": {
        "id": "mindset_low", "label": "思维模式 < N", "source": "Y4 测评",
        "kind": "supporting", "dims": ["A4"], "questions": ["Q4.2", "Q4.3"],
        "params": ["mindset_low_max"], "official_labels": "固定型思维得分（数值越低越固定）",
    },
    "neuroticism_high": {
        "id": "neuroticism_high", "label": "人格-神经质 较好 / 高", "source": "Y4 测评",
        "kind": "supporting", "dims": ["A4"], "questions": [],
        "params": [], "official_labels": _PERSON_LABELS,
    },
    "achieve_safety": {
        "id": "achieve_safety", "label": "成就感 + 安全稳定 同进前 N", "source": "Y4 职业价值观",
        "kind": "supporting", "dims": ["A4", "A5"], "questions": [],
        "params": ["top_n_values"], "official_labels": _ORDER_LABELS,
    },
    "strategy_low": {
        "id": "strategy_low", "label": "学习深层方法与策略 偏低", "source": "Y4 测评",
        "kind": "supporting", "dims": ["A5"], "questions": [],
        "params": [], "official_labels": _NORM_LABELS,
    },
    "self_reg_low": {
        "id": "self_reg_low", "label": "学习自我调节 偏低", "source": "Y4 测评",
        "kind": "supporting", "dims": ["A5"], "questions": [],
        "params": [], "official_labels": _NORM_LABELS,
    },
    "openness_many": {
        "id": "openness_many", "label": "开放性高 + ≥3 兴趣", "source": "Y4 测评",
        "kind": "supporting", "dims": ["A5"], "questions": ["Q5.3"],
        "params": [], "official_labels": _PERSON_LABELS + "；职业兴趣 " + _HOLLAND_LABELS,
    },
    "inhibition_low": {
        "id": "inhibition_low", "label": "执行功能-抑制控制 偏低", "source": "Y4 测评",
        "kind": "supporting", "dims": ["A5"], "questions": [],
        "params": [], "official_labels": _PCT_LABELS,
    },
    "attention_low": {
        "id": "attention_low", "label": "认知能力-注意力 偏低", "source": "Y4 测评",
        "kind": "warn", "dims": ["A5"], "questions": [],
        "params": [], "official_labels": _PCT_LABELS,
    },
    "extraversion_low": {
        "id": "extraversion_low", "label": "人格-外倾性 偏低 or lower", "source": "Y4 测评",
        "kind": "a6", "dims": [], "questions": ["Q6.1"],
        "params": [], "official_labels": _PERSON_LABELS,
    },
    "extraversion_high": {
        "id": "extraversion_high", "label": "人格-外倾性 较好 / 高", "source": "Y4 测评",
        "kind": "a6", "dims": [], "questions": ["Q6.1"],
        "params": [], "official_labels": _PERSON_LABELS,
    },
    "peer_attach_high": {
        "id": "peer_attach_high", "label": "同伴信任 or 亲近 高", "source": "Y4 测评",
        "kind": "a6", "dims": [], "questions": ["Q6.1"],
        "params": [], "official_labels": _ATTACH_LABELS,
    },
    "peer_attach_low": {
        "id": "peer_attach_low", "label": "同伴信任 or 亲近 偏低", "source": "Y4 测评",
        "kind": "a6", "dims": [], "questions": [],
        "params": [], "official_labels": _ATTACH_LABELS,
    },
    "belonging_good": {
        "id": "belonging_good", "label": "自驱力-归属感 较好", "source": "Y4 测评",
        "kind": "a6", "dims": [], "questions": [],
        "params": [], "official_labels": _NORM_LABELS,
    },
    "parent_high": {
        "id": "parent_high", "label": "亲子信任与沟通 高", "source": "Y4 测评",
        "kind": "a6", "dims": [], "questions": ["Q6.2"],
        "params": [], "official_labels": _ATTACH_LABELS,
    },
    "parent_low": {
        "id": "parent_low", "label": "亲子信任或沟通 偏低", "source": "Y4 测评",
        "kind": "a6", "dims": [], "questions": [],
        "params": [], "official_labels": _ATTACH_LABELS,
    },
    "parent_mid": {
        "id": "parent_mid", "label": "亲子信任与沟通 不低", "source": "Y4 测评",
        "kind": "a6", "dims": [], "questions": [],
        "params": [], "official_labels": _ATTACH_LABELS,
    },
    "agreeable_high": {
        "id": "agreeable_high", "label": "人格-宜人性 较好 / 高", "source": "Y4 测评",
        "kind": "a6", "dims": [], "questions": ["Q6.2", "Q6.4"],
        "params": [], "official_labels": _PERSON_LABELS,
    },
    "anxiety_flag": {
        "id": "anxiety_flag", "label": "焦虑安详 需关注+", "source": "Y4 测评",
        "kind": "a6", "dims": [], "questions": ["Q6.4"],
        "params": [], "official_labels": _EMO_LABELS,
    },
    "esteem_flag": {
        "id": "esteem_flag", "label": "自卑自尊 需关注+", "source": "Y4 测评",
        "kind": "a6", "dims": [], "questions": ["Q6.3"],
        "params": [], "official_labels": _EMO_LABELS,
    },
    "achieve_or_prestige_top5": {
        "id": "achieve_or_prestige_top5", "label": "成就感或声望地位 进前 N", "source": "Y4 职业价值观",
        "kind": "a6", "dims": [], "questions": ["Q6.3"],
        "params": ["top_n_values"], "official_labels": _ORDER_LABELS,
    },
    "answer_state": {
        "id": "answer_state", "label": "答题状态提示", "source": "Y4 测评",
        "kind": "global", "dims": [], "questions": [],
        "params": [], "official_labels": "自我概念整体档位 / 情绪稳定性总分",
    },
    "safety": {
        "id": "safety", "label": "情绪安全", "source": "Y4 测评",
        "kind": "global", "dims": [], "questions": [],
        "params": [], "official_labels": _EMO_LABELS,
    },
}


# ── 结果与取值辅助 ────────────────────────────────────────────
def _miss() -> Dict[str, Any]:
    return {"hit": False, "level": None, "evidence": [], "distance": None, "subtype": None}


def _res(hit: bool, level: Optional[str] = None, evidence: Optional[List[Dict[str, Any]]] = None,
         distance: Optional[float] = None, subtype: Optional[str] = None) -> Dict[str, Any]:
    if not hit:
        return _miss()
    return {"hit": True, "level": level, "evidence": evidence or [],
            "distance": distance, "subtype": subtype}


def _num(params: Optional[Dict[str, Any]], name: str, default: float) -> float:
    v = (params or {}).get(name)
    if isinstance(v, bool) or v is None:
        return float(default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _evidence_of(ctx: Ctx, label: str) -> Optional[Dict[str, Any]]:
    it = ctx.item(label)
    if it is None:
        return None
    return _point_evidence(ctx, label, it, ctx.eval_of(label))


def _evidence_list(ctx: Ctx, labels: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for label in labels:
        ev = _evidence_of(ctx, label)
        if ev is not None:
            out.append(ev)
    return out


def _norm_distance(ctx: Ctx, label: str) -> Optional[float]:
    raw = ctx.raw_num(label)
    norm = ctx.num_of(label + "常模平均数")
    if raw is None or norm is None:
        return None
    return round(raw - norm, 2)


def _person_distance(ctx: Ctx, label: str) -> Optional[float]:
    raw = ctx.raw_num(label)
    return None if raw is None else round(raw - 3.0, 2)


def _emotion_distance(ctx: Ctx, label: str) -> Optional[float]:
    raw = ctx.raw_num(label)
    return None if raw is None else round(raw - 10.0, 2)


def _band_hit(ctx: Ctx, label: str) -> Optional[str]:
    """返回档位；缺失数据返回 None。"""
    return ctx.eval_of(label)


def _low_band_signal(ctx: Ctx, label: str, level: str, distance=None,
                     subtype: Optional[str] = None) -> Dict[str, Any]:
    ev = _band_hit(ctx, label)
    if ev is None:
        return _miss()
    hit = ev in R.LOW_OR_BELOW
    return _res(hit, level, _evidence_list(ctx, [label]), distance, subtype)


def _emotion_signal(ctx: Ctx, label: str) -> Dict[str, Any]:
    ev = _band_hit(ctx, label)
    if ev is None:
        return _miss()
    if ev in _SEVERE_EMO:
        level = "At-Risk"
    elif ev in _WATCH_EMO:
        level = "Watch"
    else:
        return _miss()
    return _res(True, level, _evidence_list(ctx, [label]), _emotion_distance(ctx, label))


def _label_flag(ctx: Ctx, label: str, wanted: tuple) -> Dict[str, Any]:
    ev = _band_hit(ctx, label)
    if ev is None or ev not in wanted:
        return _miss()
    return _res(True, None, _evidence_list(ctx, [label]))


def _rank_order(ctx: Ctx, values: List[str], top_n: float) -> Dict[str, Any]:
    evidence: List[Dict[str, Any]] = []
    hit = True
    for value in values:
        pos = ctx.order_pos_of(value)
        evidence.append({"order_value": value, "pos": pos, "top_n": int(top_n)})
        if pos is None or pos > top_n:
            hit = False
    return _res(hit, "Watch" if hit else None, evidence)


# ── 各信号判定 ────────────────────────────────────────────────
def _sig_autonomy(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    return _low_band_signal(ctx, "自驱力-自主性", "Watch", _norm_distance(ctx, "自驱力-自主性"))


def _sig_deep_motive(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    return _low_band_signal(ctx, "学习动机-深层动机", "Watch", _norm_distance(ctx, "学习动机-深层动机"))


def _sig_self_efficacy(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    return _low_band_signal(ctx, "学习动机-自我效能感", "Watch", _norm_distance(ctx, "学习动机-自我效能感"))


def _sig_competence(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    return _low_band_signal(ctx, "自驱力-胜任感", "Watch", _norm_distance(ctx, "自驱力-胜任感"))


def _sig_conscientiousness(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    return _low_band_signal(ctx, "人格-责任心", "Watch", _person_distance(ctx, "人格-责任心"))


def _sig_sleep(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    ev = _band_hit(ctx, "体质健康-睡眠评级")
    if ev is None:
        return _miss()
    if ev in R.BODY_PROBLEM:
        return _res(True, "At-Risk", _evidence_list(ctx, ["体质健康-睡眠评级"]))
    if ev in R.BODY_WATCH:
        return _res(True, "Watch", _evidence_list(ctx, ["体质健康-睡眠评级"]))
    return _miss()


def _sig_exercise_diet(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    labels = ["体质健康-运动评级", "体质健康-饮食评级"]
    bad = [label for label in labels if ctx.eval_of(label) in R.BODY_PROBLEM]
    if not bad:
        return _miss()
    return _res(True, "Watch", _evidence_list(ctx, bad))


def _sig_anxiety(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    return _emotion_signal(ctx, "情绪稳定性-焦虑安详")


def _sig_depression(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    return _emotion_signal(ctx, "情绪稳定性-抑郁愉快")


def _sig_schedule_full(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    load = str(ctx.ev("ft.schedule.load_level") or "").strip()
    hours = ctx.ev("ft.schedule.free_hours_per_week")
    max_hours = _num(p, "schedule_free_hours_max", 5)
    try:
        hours_num = float(hours) if hours is not None else None
    except (TypeError, ValueError):
        hours_num = None

    evidence: List[Dict[str, Any]] = []
    if load:
        evidence.append({"evidence": "ft.schedule.load_level", "value": load})
    if hours_num is not None:
        evidence.append({"evidence": "ft.schedule.free_hours_per_week", "value": hours_num})

    if load == "高" or (hours_num is not None and hours_num <= max_hours):
        return _res(True, "At-Risk", evidence)
    if load == "中":
        return _res(True, "Watch", evidence)
    return _miss()


def _sig_ft_goal(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    judgement = str(ctx.ev("ft.goal.judgement") or "").strip()
    evidence = [{"evidence": "ft.goal.judgement", "value": judgement}]
    if judgement == "不认同":
        return _res(True, "At-Risk", evidence)
    if judgement == "部分认同":
        return _res(True, "Watch", evidence)
    return _miss()


def _sig_ft_task(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    st = ctx.ev("ft.standard_task")
    if not isinstance(st, dict) or st.get("can_split") is None:
        return _miss()
    evidence = [{"evidence": "ft.standard_task", "value": dict(st)}]
    if st.get("can_split") is False:
        return _res(True, "At-Risk", evidence, subtype="A5-S1")
    if st.get("can_split") is True and st.get("can_commit") is False:
        return _res(True, "At-Risk", evidence, subtype="A5-S3")
    return _miss()


def _sig_indep_boss_top5(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    top_n = _num(p, "top_n_values", 5)
    a = ctx.order_pos_of("独立自主")
    b = ctx.order_pos_of("上司关系")
    evidence = [{"order_value": "独立自主", "pos": a, "top_n": int(top_n)},
                {"order_value": "上司关系", "pos": b, "top_n": int(top_n)}]
    if a is None or b is None or a > top_n or b > top_n:
        return _miss()
    return _res(True, "Watch", evidence, subtype="A1-S2")


def _sig_control_low(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    raw = ctx.raw_num("情绪稳定性-无力感掌控感")
    if raw is None:
        return _miss()
    hit = raw <= _num(p, "control_low_max", 5)
    return _res(hit, "Watch", _evidence_list(ctx, ["情绪稳定性-无力感掌控感"]))


def _sig_control_high(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    raw = ctx.raw_num("情绪稳定性-无力感掌控感")
    if raw is None:
        return _miss()
    hit = raw >= _num(p, "control_high_min", 11)
    return _res(hit, None, _evidence_list(ctx, ["情绪稳定性-无力感掌控感"]))


def _sig_wellbeing_ok(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    return _label_flag(ctx, "自我概念-幸福与满足", tuple(R.NOT_LOW))


def _sig_surface_low(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    ev = _band_hit(ctx, "学习动机-表面动机")
    if ev is None:
        return _miss()
    hit = ev in R.LOW_OR_BELOW
    subtype = "A2-S4" if hit and ctx.eval_of("学习动机-深层动机") in R.LOW_OR_BELOW else None
    return _res(hit, "Watch", _evidence_list(ctx, ["学习动机-表面动机"]),
                _norm_distance(ctx, "学习动机-表面动机"), subtype)


def _sig_surface_not_low(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    ev = _band_hit(ctx, "学习动机-表面动机")
    if ev is None:
        return _miss()
    hit = ev in R.NOT_LOW
    subtype = "A2-S2" if hit and ctx.eval_of("学习动机-深层动机") in R.LOW_OR_BELOW else None
    return _res(hit, None, _evidence_list(ctx, ["学习动机-表面动机"]), subtype=subtype)


def _sig_parent_complaint(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    tags = ctx.ev("parent.complaint.tags")
    text = ctx.ev("parent.complaint.text")
    if not (tags or text):
        return _miss()
    return _res(True, None, [{"evidence": "parent.complaint",
                              "value": {"tags": tags, "text": text}}])


_HOLLAND = ["职业兴趣-现实型", "职业兴趣-研究型", "职业兴趣-艺术型",
            "职业兴趣-社会型", "职业兴趣-事业型", "职业兴趣-常规型"]


def _sig_holland_all_low(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    values = [ctx.eval_of(label) for label in _HOLLAND]
    if any(v is None for v in values) or any(v != "偏低" for v in values):
        return _miss()
    return _res(True, None, _evidence_list(ctx, _HOLLAND), subtype="A2-S3")


def _sig_holland_peak(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    high = [label for label in _HOLLAND if ctx.eval_of(label) == "高"]
    if not high:
        return _miss()
    return _res(True, None, _evidence_list(ctx, high))


def _sig_holland_c_high(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    return _label_flag(ctx, "职业兴趣-常规型", ("高",))


def _sig_emotion_total_low(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    ev = ctx.eval_of("情绪稳定性总分")
    if ev not in ("明显偏低", "严重偏低"):
        return _miss()
    return _res(True, "Watch", _evidence_list(ctx, ["情绪稳定性总分"]))


def _sig_wm_flex_low(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    low = [label for label in ("执行功能-工作记忆", "执行功能-认知灵活性")
           if ctx.eval_of(label) == "偏低"]
    healthy = (ctx.eval_of("情绪稳定性-焦虑安详") == "相对健康"
               and ctx.eval_of("情绪稳定性-抑郁愉快") == "相对健康")
    if not low or not healthy:
        return _miss()
    return _res(True, "Watch", _evidence_list(ctx, low), subtype="A3-S3")


def _sig_esteem_anx(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    est = ctx.eval_of("情绪稳定性-自卑自尊")
    anx = ctx.eval_of("情绪稳定性-焦虑安详")
    if est not in _EMO_RISK or anx not in _EMO_RISK:
        return _miss()
    return _res(True, "Watch",
                _evidence_list(ctx, ["情绪稳定性-自卑自尊", "情绪稳定性-焦虑安详"]),
                subtype="A4-S3")


def _sig_safety_top3(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    pos = ctx.order_pos_of("安全稳定")
    top_n = _num(p, "top_n_safety", 3)
    hit = pos is not None and pos <= top_n
    return _res(hit, None, [{"order_value": "安全稳定", "pos": pos, "top_n": int(top_n)}])


def _sig_cog_vs_self(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    raw = ctx.raw_num("认知能力")
    if raw is None or not raw > _num(p, "cog_pct_min", 75):
        return _miss()
    labels = ["认知能力"]
    hit = False
    if ctx.eval_of("学习动机-自我效能感") == "偏低":
        labels.append("学习动机-自我效能感")
        hit = True
    if ctx.eval_of("自我概念-能力与学校表现") in ("偏低", "严重偏低"):
        labels.append("自我概念-能力与学校表现")
        hit = True
    if not hit:
        return _miss()
    return _res(True, "Watch", _evidence_list(ctx, labels), subtype="A4-S4")


def _sig_self_concept_low(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    labels: List[str] = []
    if ctx.eval_of("自我概念整体档位") == "偏低":
        labels.append("自我概念整体档位")
    if ctx.eval_of("自我概念-能力与学校表现") in ("偏低", "严重偏低"):
        labels.append("自我概念-能力与学校表现")
    if not labels:
        return _miss()
    return _res(True, "Watch", _evidence_list(ctx, labels))


def _sig_mindset_low(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    raw = ctx.raw_num("思维模式结果")
    if raw is None or not raw < _num(p, "mindset_low_max", 50):
        return _miss()
    subtype = "A4-S1" if ctx.eval_of("情绪稳定性-自卑自尊") in _EMO_RISK else None
    return _res(True, "Watch", _evidence_list(ctx, ["思维模式结果"]), subtype=subtype)


def _sig_neuroticism_high(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    ev = ctx.eval_of("人格-神经质")
    if ev is None or ev not in R.STRONG_ASSET:
        return _miss()
    return _res(True, None, _evidence_list(ctx, ["人格-神经质"]),
                _person_distance(ctx, "人格-神经质"))


def _sig_achieve_safety(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    return _rank_order(ctx, ["成就感", "安全稳定"], _num(p, "top_n_values", 5))


def _sig_strategy_low(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    return _low_band_signal(ctx, "学习方法与策略-学习深层方法与策略", "Watch",
                            _norm_distance(ctx, "学习方法与策略-学习深层方法与策略"))


def _sig_self_reg_low(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    return _low_band_signal(ctx, "学习方法与策略-学习自我调节", "Watch",
                            _norm_distance(ctx, "学习方法与策略-学习自我调节"))


def _sig_openness_many(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    if ctx.eval_of("人格-开放性") not in R.STRONG_ASSET:
        return _miss()
    many = [label for label in _HOLLAND if ctx.eval_of(label) in tuple(R.NOT_LOW)]
    if len(many) < 3:
        return _miss()
    return _res(True, None, _evidence_list(ctx, ["人格-开放性"] + many), subtype="A5-S2")


def _sig_inhibition_low(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    return _low_band_signal(ctx, "执行功能-抑制控制", "Watch")


def _sig_attention_low(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    return _low_band_signal(ctx, "认知能力-注意力", "Watch")


def _sig_extraversion_low(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    ev = ctx.eval_of("人格-外倾性")
    if ev is None or ev not in R.LOW_OR_BELOW:
        return _miss()
    return _res(True, None, _evidence_list(ctx, ["人格-外倾性"]),
                _person_distance(ctx, "人格-外倾性"))


def _sig_extraversion_high(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    ev = ctx.eval_of("人格-外倾性")
    if ev is None or ev not in R.STRONG_ASSET:
        return _miss()
    return _res(True, None, _evidence_list(ctx, ["人格-外倾性"]),
                _person_distance(ctx, "人格-外倾性"))


def _sig_peer_attach_high(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    labels = [label for label in ("依恋关系-信任-同伴", "依恋关系-亲近-同伴")
              if ctx.eval_of(label) == "高"]
    if not labels:
        return _miss()
    return _res(True, None, _evidence_list(ctx, labels))


def _sig_peer_attach_low(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    labels = [label for label in ("依恋关系-信任-同伴", "依恋关系-亲近-同伴")
              if ctx.eval_of(label) == "偏低"]
    if not labels:
        return _miss()
    return _res(True, None, _evidence_list(ctx, labels))


def _sig_belonging_good(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    return _label_flag(ctx, "自驱力-归属感", ("较好",))


_PARENT_SUBS = ("信任", "沟通")


def _parent_evals(ctx: Ctx) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for sub in _PARENT_SUBS:
        out[sub] = [v for v in (ctx.eval_of(f"依恋关系-{sub}-母亲"),
                                ctx.eval_of(f"依恋关系-{sub}-父亲")) if v is not None]
    return out


def _parent_high(ctx: Ctx) -> bool:
    evals = _parent_evals(ctx)
    return all(evals[sub] and "高" in evals[sub] for sub in _PARENT_SUBS)


def _parent_low(ctx: Ctx) -> bool:
    return any("偏低" in vals for vals in _parent_evals(ctx).values())


def _sig_parent_high(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    if not _parent_high(ctx):
        return _miss()
    labels = [f"依恋关系-{sub}-{who}" for sub in _PARENT_SUBS for who in ("母亲", "父亲")
              if ctx.eval_of(f"依恋关系-{sub}-{who}") is not None]
    return _res(True, None, _evidence_list(ctx, labels))


def _sig_parent_low(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    labels = [f"依恋关系-{sub}-{who}" for sub in _PARENT_SUBS for who in ("母亲", "父亲")
              if ctx.eval_of(f"依恋关系-{sub}-{who}") == "偏低"]
    if not labels:
        return _miss()
    return _res(True, None, _evidence_list(ctx, labels))


def _sig_parent_mid(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    evals = _parent_evals(ctx)
    if not any(evals.values()):
        return _miss()
    if _parent_high(ctx) or _parent_low(ctx):
        return _miss()
    labels = [f"依恋关系-{sub}-{who}" for sub in _PARENT_SUBS for who in ("母亲", "父亲")
              if ctx.eval_of(f"依恋关系-{sub}-{who}") is not None]
    return _res(True, None, _evidence_list(ctx, labels))


def _sig_agreeable_high(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    ev = ctx.eval_of("人格-宜人性")
    if ev is None or ev not in R.STRONG_ASSET:
        return _miss()
    return _res(True, None, _evidence_list(ctx, ["人格-宜人性"]),
                _person_distance(ctx, "人格-宜人性"))


def _sig_anxiety_flag(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    ev = ctx.eval_of("情绪稳定性-焦虑安详")
    if ev not in _EMO_RISK:
        return _miss()
    return _res(True, None, _evidence_list(ctx, ["情绪稳定性-焦虑安详"]))


def _sig_esteem_flag(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    ev = ctx.eval_of("情绪稳定性-自卑自尊")
    if ev not in _EMO_RISK:
        return _miss()
    return _res(True, None, _evidence_list(ctx, ["情绪稳定性-自卑自尊"]))


def _sig_achieve_or_prestige_top5(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    top_n = _num(p, "top_n_values", 5)
    evidence: List[Dict[str, Any]] = []
    for value in ("成就感", "声望地位"):
        pos = ctx.order_pos_of(value)
        evidence.append({"order_value": value, "pos": pos, "top_n": int(top_n)})
        if pos is not None and pos <= top_n:
            return _res(True, None, evidence)
    return _miss()


def _sig_answer_state(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    overall = ctx.eval_of("自我概念整体档位")
    total = ctx.eval_of("情绪稳定性总分")
    if overall != "偏低" or total not in ("明显偏低", "严重偏低"):
        return _miss()
    return _res(True, None, _evidence_list(ctx, ["自我概念整体档位", "情绪稳定性总分"]))


def _sig_safety(ctx: Ctx, p: Dict[str, Any]) -> Dict[str, Any]:
    labels = [label for label in ("情绪稳定性-焦虑安详", "情绪稳定性-抑郁愉快")
              if ctx.eval_of(label) in _SEVERE_EMO]
    if not labels:
        return _miss()
    return _res(True, "At-Risk", _evidence_list(ctx, labels),
                _emotion_distance(ctx, labels[0]))


_EVALUATORS = {
    "autonomy": _sig_autonomy,
    "deep_motive": _sig_deep_motive,
    "self_efficacy": _sig_self_efficacy,
    "competence": _sig_competence,
    "conscientiousness": _sig_conscientiousness,
    "sleep": _sig_sleep,
    "exercise_diet": _sig_exercise_diet,
    "anxiety": _sig_anxiety,
    "depression": _sig_depression,
    "schedule_full": _sig_schedule_full,
    "ft_goal": _sig_ft_goal,
    "ft_task": _sig_ft_task,
    "indep_boss_top5": _sig_indep_boss_top5,
    "control_low": _sig_control_low,
    "control_high": _sig_control_high,
    "wellbeing_ok": _sig_wellbeing_ok,
    "surface_low": _sig_surface_low,
    "surface_not_low": _sig_surface_not_low,
    "parent_complaint": _sig_parent_complaint,
    "holland_all_low": _sig_holland_all_low,
    "holland_peak": _sig_holland_peak,
    "holland_c_high": _sig_holland_c_high,
    "emotion_total_low": _sig_emotion_total_low,
    "wm_flex_low": _sig_wm_flex_low,
    "esteem_anx": _sig_esteem_anx,
    "safety_top3": _sig_safety_top3,
    "cog_vs_self": _sig_cog_vs_self,
    "self_concept_low": _sig_self_concept_low,
    "mindset_low": _sig_mindset_low,
    "neuroticism_high": _sig_neuroticism_high,
    "achieve_safety": _sig_achieve_safety,
    "strategy_low": _sig_strategy_low,
    "self_reg_low": _sig_self_reg_low,
    "openness_many": _sig_openness_many,
    "inhibition_low": _sig_inhibition_low,
    "attention_low": _sig_attention_low,
    "extraversion_low": _sig_extraversion_low,
    "extraversion_high": _sig_extraversion_high,
    "peer_attach_high": _sig_peer_attach_high,
    "peer_attach_low": _sig_peer_attach_low,
    "belonging_good": _sig_belonging_good,
    "parent_high": _sig_parent_high,
    "parent_low": _sig_parent_low,
    "parent_mid": _sig_parent_mid,
    "agreeable_high": _sig_agreeable_high,
    "anxiety_flag": _sig_anxiety_flag,
    "esteem_flag": _sig_esteem_flag,
    "achieve_or_prestige_top5": _sig_achieve_or_prestige_top5,
    "answer_state": _sig_answer_state,
    "safety": _sig_safety,
}


def evaluate(signal_id: str, ctx: Ctx,
             params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """求值单条信号。未知 id 抛 KeyError。"""
    fn = _EVALUATORS.get(signal_id)
    if fn is None:
        raise KeyError(f"未知信号：{signal_id}")
    if signal_id not in SIGNALS:
        raise KeyError(f"信号缺少元数据：{signal_id}")
    return fn(ctx, params or {})
