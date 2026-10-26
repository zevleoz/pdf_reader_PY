"""6 A.M. 判定依据：理论、指标、信号强度与待确认问题。

纯函数层：不导入 Flask、不访问数据库，也不导入 presentation（由后者反向引用）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

SECURE_TEXT = "现有 Y4 事实未提示该维度构成启动障碍。"

STATE_ZH = {
    "Secure": "稳固",
    "Watch": "关注",
    "At-Risk": "风险",
    "Blocked": "阻塞",
}
EVIDENCE_ZH = {
    "Hypothesis": "仅线索",
    "Supported": "有佐证",
    "Confirmed": "已证实",
    "Refuted": "被排除",
}

THEORY = {
    "A1": "自我决定理论：自主需要得不到满足时，外部安排的任务只能靠外部压力推动，启动依赖监督（Deci & Ryan, 2000）。",
    "A2": "期望-价值理论：学生看不到任务对自己的价值时，投入意愿下降（Eccles & Wigfield, 2002）。",
    "A3": "资源保存理论与注意控制理论：睡眠不足和情绪消耗会占用注意与工作记忆，新增任务更易被排斥（Hobfoll, 1989；Eysenck 等, 2007）。",
    "A4": "自我效能理论：预期自己做不好的人更少开始、更早放弃（Bandura, 1997）。",
    "A5": "拖延元分析：责任心低、自我调节弱是启动困难最稳定的相关因素（Steel, 2007）。",
}

SUBTYPE_DISPLAY = {
    "A1-S1": "被动抵抗型",
    "A1-S2": "自主抗争型",
    "A1-S3": "被安排型",
    "A2-S1": "兴趣错位型",
    "A2-S2": "外部动机型",
    "A2-S3": "兴趣空白型",
    "A2-S4": "无动机型",
    "A3-S1": "过载型",
    "A3-S2": "恢复不足型",
    "A3-S3": "认知饱和型",
    "A4-S1": "完美主义回避型",
    "A4-S2": "低自我效能型",
    "A4-S3": "评价焦虑型",
    "A4-S4": "认知偏差型",
    "A5-S1": "任务拆解困难型",
    "A5-S2": "选择困难型",
    "A5-S3": "外部结构依赖型",
}

VERDICT = {
    "A1-S1": '表面配合、行动拖延，可能在用不行动表达"不"。',
    "A1-S2": "想自己做主但缺少空间，可能用对抗来争取自主。",
    "A1-S3": '习惯被安排，不反抗，但缺少"这件事是我的"的感觉。',
    "A1": "自主感低于同龄人，任务可能不是学生自己的选择。",
    "A2-S1": "不是不想做，而是当前任务和兴趣方向不对路。",
    "A2-S2": "主要靠升学、父母等外部理由在推动，自己的理由不足。",
    "A2-S3": "对各类活动都提不起兴趣，需先确认是否只是作答状态。",
    "A2-S4": "内在和外在动机都偏低，暂时找不到做这件事的理由。",
    "A2": "学生可能看不到这件事对自己的意义。",
    "A3-S1": "睡眠和情绪资源都在透支，现在加任务可能适得其反。",
    "A3-S2": "身体恢复不足，精力会慢慢被耗尽。",
    "A3-S3": "认知资源偏紧，多线任务容易混乱。",
    "A3": "当前可用的时间和精力可能不足。",
    "A4-S1": '可能用"还没准备好"推迟开始，把失败看成能力判决。',
    "A4-S2": "对自己能否做好信心不足。",
    "A4-S3": "更怕被评价，而不是怕做不到。",
    "A4-S4": "自我评价与实际能力可能不一致。",
    "A4": "学生可能不太相信自己能做好。",
    "A5-S1": "大任务可能拆不出第一步。",
    "A5-S2": "选项多、难以收敛，第一步迟迟定不下来。",
    "A5-S3": "能拆出步骤，但没人带就难以开始。",
    "A5": "学生可能不知道第一步从哪里开始。",
}


def verdict_for(dim: str, rec: Dict[str, Any]) -> Optional[str]:
    """一句话判断：Secure 用固定文本，Watch 前缀提示需要验证。"""
    if dim == "A6":
        return None
    rec = rec or {}
    state = str(rec.get("state") or "Secure")
    if state == "Secure":
        return SECURE_TEXT
    text = VERDICT.get(str(rec.get("subtype") or "")) or VERDICT.get(dim)
    if text is None:
        return None
    if state == "Watch":
        return "需要验证：" + text
    return text


def _num(value: Any) -> Optional[float]:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _indicator_max(point: str) -> Optional[int]:
    if point.startswith(("自驱力-", "学习动机-", "学习方法与策略-")):
        return 10
    if point.startswith("人格-"):
        return 5
    if point.startswith(("执行功能-", "认知能力")):
        return 100
    return None


def _indicator_cut(point: str, band: Any) -> Optional[int]:
    if not point.startswith("情绪稳定性-"):
        return None
    if band == "需特殊关注":
        return 5
    if band == "需关注":
        return 10
    return None


def _build_indicator(point: str, ev: Dict[str, Any]) -> Dict[str, Any]:
    value = _num(ev.get("raw_value"))
    norm = ev.get("norm")
    norm_num = _num(norm)
    gap = round(value - norm_num, 1) if value is not None and norm_num is not None else None
    band = ev.get("eval_value")
    return {
        "point": point,
        "value": value,
        "text": band if value is None else None,
        "norm": norm,
        "gap": gap,
        "strength": {"strong": "strong", "mild": "weak"}.get(ev.get("tier")),
        "band": band,
        "max": _indicator_max(point),
        "cut": _indicator_cut(point, band),
    }


def _indicators(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for trace in rec.get("triggered_rules") or []:
        if trace.get("refuted"):
            continue
        for ev in trace.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            if ev.get("order_value") is not None:
                point = str(ev.get("order_value"))
                if point in seen:
                    continue
                seen.add(point)
                top_n = ev.get("top_n")
                out.append({
                    "point": point,
                    "rank": ev.get("pos"),
                    "rank_total": 15,
                    "text": ("前 %d" % top_n) if isinstance(top_n, int) else "",
                })
                continue
            point = ev.get("point")
            if point is None:
                continue
            point = str(point)
            if point in seen:
                continue
            seen.add(point)
            out.append(_build_indicator(point, ev))
    return out


def _rules(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for trace in rec.get("triggered_rules") or []:
        if not trace.get("contributing") or trace.get("refuted"):
            continue
        text = str(trace.get("title") or "")
        state = (trace.get("effect") or {}).get("state")
        if state:
            text += " → " + STATE_ZH.get(str(state), str(state))
        out.append({"id": trace.get("id"), "text": text})
    return out


def _level_reason(rec: Dict[str, Any], indicators: List[Dict[str, Any]]) -> str:
    strengths = [i.get("strength") for i in indicators if i.get("strength")]
    strong = strengths.count("strong")
    weak = strengths.count("weak")
    parts = []
    if strong:
        parts.append("%d 个强信号" % strong)
    if weak:
        parts.append("%d 个弱信号" % weak)
    reason = "、".join(parts) if parts else "由规则组合判定"
    confidence = str(rec.get("confidence") or "")
    if confidence in ("Supported", "Confirmed"):
        reason += "；有 Y4 之外的证据（%s）" % EVIDENCE_ZH.get(confidence, confidence)
    else:
        reason += "；目前只有 Y4 线索"
    return reason


def _open_questions(dim: str, questions: List[Dict[str, Any]],
                    answers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    answered = {str((a or {}).get("q")) for a in (answers or [])}
    out = []
    for q in questions or []:
        q = q or {}
        if str(q.get("dim")) != dim:
            continue
        qid = q.get("id")
        out.append({"id": qid, "text": q.get("ask"),
                    "answered": str(qid) in answered})
    return out


def build_rationale(dim: str, rec: Dict[str, Any], questions: List[Dict[str, Any]],
                    answers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """单维判定依据；A6 为选择器，没有判定链，返回 None。"""
    if dim == "A6":
        return None
    rec = rec or {}
    indicators = _indicators(rec)
    return {
        "theory": THEORY.get(dim),
        "indicators": indicators,
        "level_reason": _level_reason(rec, indicators),
        "rules": _rules(rec),
        "open_questions": _open_questions(dim, questions, answers),
    }
