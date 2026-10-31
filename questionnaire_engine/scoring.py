"""问卷计分 —— 纯函数，零 Flask、零 DB。

计分口径全部来自 ``Profiling plus questionnaires.xlsx``：

- 题目 → 维度：Excel 每张表的勾选列，已写入题库 schema 的 ``dimension`` 字段
  （``test_questionnaire_scoring`` 逐题与 Excel 比对）；
- 维度分 = 该维度各题选项分值之和（Excel 维度列对这些题标 1）；
- 分档：Excel 只给了 焦虑、抑郁（维度分档）与 网络成瘾、学业压力（总分档）；
  其余维度 Excel 没有分档，只存原始分与取值范围，这里不自行发明阈值；
- 总分：网络成瘾、学业压力按 Excel 的总分档计算，只有总分带分档，维度分不带；
  CERQ 按负责人口径（2026-10-31）也算总分，但没有分档。CERQ 的选项量表暂无
  官方口径，沿用题库的 -3 ~ +3。

规则放在 Python 模块而非 ``questionnaires_seed/``：seed 目录被 ``.gitignore``
的 ``*.json`` 忽略，不随部署下发。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .schema import questions_of

# 规则变更时 +1：questionnaire_store.backfill_scores 会重算旧版本的分数。
SCORING_VERSION = 1

# tone 只决定界面徽标颜色（ok / neutral / warn / danger），不是 Excel 口径。
_ANXIETY_BANDS = [
    {"max": 4, "label": "无明显焦虑", "advice": "", "tone": "ok"},
    {"max": 9, "label": "轻度焦虑", "advice": "", "tone": "neutral"},
    {"max": 14, "label": "中度焦虑", "advice": "建议正式评估", "tone": "warn"},
    {"max": None, "label": "重度焦虑", "advice": "建议正式评估", "tone": "danger"},
]
_DEPRESSION_BANDS = [
    {"max": 4, "label": "无明显抑郁", "advice": "", "tone": "ok"},
    {"max": 9, "label": "有抑郁倾向", "advice": "", "tone": "neutral"},
    {"max": 14, "label": "轻度抑郁", "advice": "建议进行正式评估", "tone": "warn"},
    {"max": 19, "label": "中度抑郁", "advice": "尽快就医", "tone": "danger"},
    {"max": None, "label": "重度抑郁", "advice": "尽快就医，重视第九题得分情况", "tone": "danger"},
]
_INTERNET_BANDS = [
    {"max": 39, "label": "正常", "advice": "", "tone": "ok"},
    {"max": 59, "label": "轻度依赖", "advice": "", "tone": "neutral"},
    {"max": 79, "label": "中度依赖", "advice": "", "tone": "warn"},
    {"max": None, "label": "重度依赖", "advice": "", "tone": "danger"},
]
_STRESS_BANDS = [
    {"max": 45, "label": "几乎无压力", "advice": "", "tone": "ok"},
    {"max": 75, "label": "轻度压力", "advice": "", "tone": "neutral"},
    {"max": 120, "label": "中度压力", "advice": "", "tone": "warn"},
    {"max": None, "label": "重度压力", "advice": "", "tone": "danger"},
]


_CERQ_GROUP = "情绪调节策略（CERQ）"


def _dims(*names: str, group: str = "") -> List[Dict[str, Any]]:
    return [{"name": n, "group": group} for n in names]


RULES: Dict[str, Dict[str, Any]] = {
    "Q-ANX-01": {
        "dimensions": [{"name": "焦虑", "group": "", "bands": _ANXIETY_BANDS}],
    },
    "Q-DEP-01": {
        "dimensions": [{"name": "抑郁", "group": "", "bands": _DEPRESSION_BANDS}],
        # Excel 只写了「重视第九题得分情况」（在 20-27 档）。负责人确认（2026-10-31）：
        # 第九题是抑郁部分第 9 题（Excel 总表第 16 题）；任一非 0 即提示，不看总分。
        "flags": [{"id": "self_harm", "question": "q9", "min_value": 1,
                   "label": "第 9 题（逃避或伤害自己的念头）"}],
    },
    "Q-ERQ-CERQ-01": {
        "dimensions": (
            _dims("认知重评", "压抑表达", group="情绪调节（ERQ）")
            + _dims("自我责备", "接纳", "反刍", "积极重新关注", "重新关注",
                    "积极重新评价", "转换视角", "灾难化", "责难他人",
                    group=_CERQ_GROUP)),
        "total": {"label": "CERQ 总分", "group": _CERQ_GROUP},
    },
    "Q-SOC-01": {
        "dimensions": _dims("关系启动能力", "情绪支持能力", "自我表达能力",
                            "影响他人能力", "冲突解决能力"),
    },
    "Q-IAD-01": {
        "dimensions": _dims("行为失控", "功能损害", "戒断反应"),
        "total": {"label": "总分", "bands": _INTERNET_BANDS},
    },
    "Q-STRESS-01": {
        "dimensions": _dims("学习任务", "教师与课堂", "家庭期望", "同伴竞争", "自我要求"),
        "total": {"label": "总分", "bands": _STRESS_BANDS},
    },
}


def has_rule(code: Optional[str]) -> bool:
    return str(code or "") in RULES


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tidy(value: Optional[float]) -> Any:
    """整数分值不带小数点（JSON 与界面都显示 12 而不是 12.0）。"""
    if value is None:
        return None
    return int(value) if float(value).is_integer() else round(value, 2)


def _option_values(question: Dict[str, Any]) -> List[float]:
    values = [_number(o.get("value")) for o in (question.get("options") or [])
              if isinstance(o, dict)]
    return [v for v in values if v is not None]


def _answer_value(question: Dict[str, Any], answers: Dict[str, Any]) -> Optional[float]:
    """该题得分；未作答或不是合法选项 → None。"""
    value = _number(answers.get(str(question.get("id") or "")))
    return value if value is not None and value in _option_values(question) else None


def band_for(score: Optional[float], bands: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, str]]:
    """按上界（含）落档；``max=None`` 表示最高档。无分档或无分数 → None。"""
    if score is None or not bands:
        return None
    for band in bands:
        if band["max"] is None or score <= band["max"]:
            return {"label": band["label"], "advice": band["advice"], "tone": band["tone"]}
    return None


def _sum_block(questions: List[Dict[str, Any]], answers: Dict[str, Any]) -> Dict[str, Any]:
    """一组题的 分数 / 范围 / 作答数。有题未答时 score=None，避免把漏答算成低分。"""
    values = [_answer_value(q, answers) for q in questions]
    answered = [v for v in values if v is not None]
    options = [_option_values(q) for q in questions]
    complete = bool(questions) and len(answered) == len(questions)
    return {
        "score": _tidy(sum(answered)) if complete else None,
        "min": _tidy(sum(min(o) for o in options if o)) if questions else None,
        "max": _tidy(sum(max(o) for o in options if o)) if questions else None,
        "answered": len(answered),
        "item_count": len(questions),
    }


def _flags(rule: Dict[str, Any], questions: List[Dict[str, Any]],
           answers: Dict[str, Any]) -> List[Dict[str, Any]]:
    by_id = {str(q.get("id") or ""): q for q in questions}
    out: List[Dict[str, Any]] = []
    for flag in rule.get("flags") or []:
        question = by_id.get(flag["question"])
        if question is None:
            continue
        value = _answer_value(question, answers)
        if value is None or value < flag["min_value"]:
            continue
        answer_label = next((str(o.get("label") or "") for o in question.get("options") or []
                             if _number(o.get("value")) == value), "")
        out.append({"id": flag["id"], "label": flag["label"],
                    "question": str(question.get("title") or ""),
                    "value": _tidy(value), "answer": answer_label})
    return out


def score_response(code: Optional[str], schema: Optional[Dict[str, Any]],
                   answers: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """算出一份答卷的计分结果；该问卷没有计分规则时返回 None。"""
    rule = RULES.get(str(code or ""))
    if rule is None:
        return None
    answers = answers if isinstance(answers, dict) else {}
    questions = questions_of(schema)

    # 总分默认覆盖全卷；给了 group 时只算该分组（ERQ + CERQ 同卷，总分只算 CERQ）
    total_rule = rule.get("total")
    total_group = (total_rule or {}).get("group")

    dimensions: List[Dict[str, Any]] = []
    scored: List[Dict[str, Any]] = []
    for dim in rule["dimensions"]:
        members = [q for q in questions if str(q.get("dimension") or "").strip() == dim["name"]]
        if not total_group or dim.get("group") == total_group:
            scored.extend(members)
        block = _sum_block(members, answers)
        dimensions.append(dict(block, name=dim["name"], group=dim.get("group") or "",
                               band=band_for(block["score"], dim.get("bands"))))

    total = None
    if total_rule:
        block = _sum_block(scored, answers)
        total = dict(block, label=total_rule["label"],
                     band=band_for(block["score"], total_rule.get("bands")))

    return {
        "code": str(code),
        "version": SCORING_VERSION,
        "complete": all(d["score"] is not None for d in dimensions),
        "dimensions": dimensions,
        "total": total,
        "flags": _flags(rule, questions, answers),
    }
