"""M1 会后报告的标签判断：生成期唯一的归一入口。

模型只提供候选判断；这里统一校验证据、套用中央规则、去除同事件冲突，
最终写入报告的 tags 必须经过 :func:`resolve_assessment`。
"""
from __future__ import annotations

from typing import Any, Dict, List

from m1 import report_checks, report_kb

TAGS = ("积极资源", "确认发展需求", "可能存在", "暂未发现", "信息不足")
PAIRS = ({"积极资源", "可能存在"},)
_PRIORITY = ("积极资源", "确认发展需求", "可能存在", "暂未发现")


def _usable(evidence, code: str) -> List[Dict[str, Any]]:
    return [e for e in report_checks.items_for(evidence, code)
            if report_checks.supports_judgement(e)]


def _event_of(item: Dict[str, Any]) -> str:
    return item.get("event_id") or "evt-%s" % item.get("id")


def _positive(items, ids) -> bool:
    return any(items[i].get("type") != "假设性回应" for i in ids if i in items)


def _has_m1(items, ids) -> bool:
    return any(items[i].get("source") == "M1" for i in ids if i in items)


def _decisive(items, ids) -> bool:
    return any(items[i].get("source") == "M1"
               and items[i].get("type") == "具体行为事件"
               and items[i].get("speaker") not in ("待确认", "导师")
               for i in ids if i in items)


def _candidate(row: Any, items) -> Dict[str, Any] | None:
    """一条候选判断 → 校验后的事件与证据；不合法返回 None。"""
    if not isinstance(row, dict):
        return None
    tag = row.get("tag")
    if tag not in TAGS:
        return None
    ids = [i for i in row.get("evidence_ids") or [] if isinstance(i, str)]
    ids = [i for i in ids if i in items]
    if tag != "信息不足" and not ids:
        return None
    events = {_event_of(items[i]) for i in ids}
    return {"tag": tag, "evidence_ids": ids, "events": events}


def assessment_errors(raw: Any, evidence, code: str) -> List[str]:
    """结构、证据与标签规则错误；不修改输入。没有错误时返回空列表。"""
    if not isinstance(raw, dict):
        return ["候选判断必须是对象"]
    rows = raw.get("judgements")
    if not isinstance(rows, list):
        return ["judgements 必须是数组"]
    items = {e["id"]: e for e in _usable(evidence, code)}
    errors: List[str] = []
    tags: List[str] = []
    for number, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            errors.append("第 %d 条判断不是对象" % number)
            continue
        tag = row.get("tag")
        if tag not in TAGS:
            errors.append("标签「%s」不在五种固定标签之内" % tag)
            continue
        tags.append(tag)
        if not str(row.get("rationale") or "").strip():
            errors.append("「%s」缺少判断理由" % tag)
        if tag == "信息不足":
            continue
        ids = [i for i in row.get("evidence_ids") or [] if isinstance(i, str)]
        if not ids:
            errors.append("「%s」没有给出证据编号" % tag)
            continue
        bad = [i for i in ids if i not in items]
        if bad:
            errors.append("「%s」的证据 %s 不属于本能力或不可用"
                          % (tag, "、".join(bad)))
            continue
        events = row.get("event_ids")
        if not isinstance(events, list) or not events:
            errors.append("「%s」没有给出事件编号" % tag)
        else:
            expected = {_event_of(items[i]) for i in ids}
            wrong = [e for e in events if e not in expected]
            if wrong:
                errors.append("「%s」的事件编号与证据不一致" % tag)
    if len(tags) > 2:
        errors.append("标签最多两个")
    if len(set(tags)) != len(tags):
        errors.append("标签重复")
    if "信息不足" in tags and len(tags) > 1:
        errors.append("「信息不足」不与其他判断并列")
    if len(tags) == 2 and set(tags) not in PAIRS:
        errors.append(report_kb.tags_problem(tags) or "双标签组合不合法")
    if len(set(tags)) == 2:
        chosen = {}
        for row in rows:
            candidate = _candidate(row, items)
            if candidate is not None and candidate["tag"] != "信息不足":
                chosen[candidate["tag"]] = candidate
        if len(chosen) == 2:
            first, second = list(chosen.values())
            if not first["events"].isdisjoint(second["events"]):
                errors.append("双标签的事件不能相同")
    return list(dict.fromkeys(errors))


def resolve_assessment(raw: Any, evidence, code: str) -> Dict[str, Any]:
    """把模型候选判断归一成最终 tags / evidence_ids / internal_note。

    规则：五种固定标签、最多两个；除「信息不足」外都要有可用证据；
    「确认发展需求」必须有发言明确的会议具体行为证据，否则降级；
    「积极资源」要有非假设性证据；「暂未发现」要有会议核实情境；
    同一事件不能同时证明资源与需求。
    """
    raw = raw if isinstance(raw, dict) else {}
    items = {e["id"]: e for e in _usable(evidence, code)}
    diagnostics: List[str] = []
    candidates: Dict[str, Dict[str, Any]] = {}
    saw_info = False
    attempted = False
    for row in raw.get("judgements") or []:
        if not isinstance(row, dict):
            continue
        tag = row.get("tag")
        if tag not in TAGS:
            attempted = True
            diagnostics.append("候选标签「%s」不在五种固定标签之内，已丢弃" % tag)
            continue
        if tag == "信息不足":
            saw_info = True
            continue
        attempted = True
        if tag in candidates:
            diagnostics.append("「%s」重复出现，已保留第一条" % tag)
            continue
        candidate = _candidate(row, items)
        if candidate is None:
            diagnostics.append("「%s」没有可用证据，已丢弃" % tag)
            continue
        candidates[tag] = candidate

    if "积极资源" in candidates and not _positive(items, candidates["积极资源"]["evidence_ids"]):
        diagnostics.append("「积极资源」没有非假设性证据，已丢弃")
        candidates.pop("积极资源")
    if "暂未发现" in candidates and not _has_m1(items, candidates["暂未发现"]["evidence_ids"]):
        diagnostics.append("「暂未发现」没有会议核实情境，已丢弃")
        candidates.pop("暂未发现")

    need = candidates.pop("确认发展需求", None)
    if need is not None:
        if _decisive(items, need["evidence_ids"]):
            candidates["确认发展需求"] = need
        elif items:
            diagnostics.append("「确认发展需求」缺少发言明确的会议具体行为证据，已降为「可能存在」")
            candidates.setdefault("可能存在", {"tag": "可能存在",
                                               "evidence_ids": need["evidence_ids"],
                                               "events": need["events"]})
        else:
            diagnostics.append("「确认发展需求」缺少发言明确的会议具体行为证据，已改为「信息不足」")

    kept: List[Dict[str, Any]] = []
    resource = candidates.get("积极资源")
    if resource is not None:
        kept.append(resource)
        for tag in ("确认发展需求", "可能存在"):
            candidate = candidates.get(tag)
            if candidate is None:
                continue
            if tag == "确认发展需求":
                diagnostics.append("「积极资源」不与「确认发展需求」并列，已只保留「积极资源」")
                continue
            if not candidate["events"].isdisjoint(resource["events"]):
                diagnostics.append("同一事件同时支持两个标签，已只保留「积极资源」")
                continue
            kept.append(candidate)
            break
    else:
        for tag in _PRIORITY:
            if tag in candidates:
                kept.append(candidates[tag])
                break

    if not kept:
        if attempted:
            diagnostics.append("没有可用的判断依据，记为「信息不足」")
        kept = [{"tag": "信息不足", "evidence_ids": [], "events": set()}]
    elif saw_info:
        diagnostics.append("「信息不足」不与其他判断并列，已移除")
    tags = [candidate["tag"] for candidate in kept]
    if report_kb.tags_problem(tags):
        diagnostics.append("标签组合不合规，已改为「信息不足」")
        kept = [{"tag": "信息不足", "evidence_ids": [], "events": set()}]
        tags = ["信息不足"]

    evidence_ids: List[str] = []
    for candidate in kept:
        for eid in candidate["evidence_ids"]:
            if eid not in evidence_ids:
                evidence_ids.append(eid)
    return {"tags": tags, "evidence_ids": evidence_ids,
            "internal_note": str(raw.get("internal_note") or "").strip(),
            "diagnostics": diagnostics}
