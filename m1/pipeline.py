"""M1 AI 生成管道（步骤 A–E）。

``generate(prep_id)`` 读自动来源与导师上传资料，产出 README §4 文档 JSON，
写一个 ``ai_draft`` 版本和一个新的 ``edit`` 副本，并把 prep 置为 ``review``。

所有 AI 调用都经过 :func:`_ask`；测试替换该函数即可完全离线。
"""
from __future__ import annotations

import copy
import json
import re
from concurrent.futures import ThreadPoolExecutor
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from growth_talk.analysis import AnalysisError, call_model

import m1.sources as sources
import m1.store as store
from m1.kb import load_kb
from m1.prompts import (_STYLE, ABILITY_PROMPT, MEETING_PLAN_PROMPT,
                        PRIORITY_PROMPT, SAFETY_CHECK_PROMPT, SAFETY_KEYWORDS,
                        SOURCE_ITEMS_PROMPT)
from m1.validate_doc import redact_raw_numbers, validate_doc

SCHEMA_SOURCE = "source_items"
SCHEMA_SAFETY = "safety_check"
SCHEMA_ABILITY = "ability"
SCHEMA_PRIORITY = "priority"
SCHEMA_PLAN = "meeting_plan"

SOURCE_LABELS = {
    "y4": "Y4",
    "six_am": "6 A.M. 档案",
    "questionnaire": "补充问卷",
    "first_touch": "First Touch",
    "parent": "家长初始反馈",
    "case_review": "Case Review",
    "other": "其他资料",
}
# Case Review counts only for first-hand observations (kind "direct"); its
# interpretations of Y4 are "hypothesis" and never become events
_EVENT_SOURCES = {"first_touch", "parent", "other", "case_review"}
_EVENT_KINDS = {"direct", "context"}
_KINDS = {"direct", "indirect", "context", "inference", "hypothesis"}
_Y4_REF_RE = re.compile(r"Y4|测评|报告|得分|档位|分数|量表|测验|问卷")
_TEXT_LIMIT = 12000
_MAX_EVENT_QUESTIONS = 4


# ---------------------------------------------------------------------------
# 通用助手
# ---------------------------------------------------------------------------
def _clean(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _strip_ids(value, by_id) -> str:
    """Remove evidence ids the model copied into reader-facing text."""
    text = _clean(value)
    if not text:
        return text
    pattern = r"[（(\[【]?\s*(?:%s)(?:\s*[、,，/／]\s*(?:%s))*\s*[）)\]】]?" % (
        _ID_ALT, _ID_ALT)
    text = re.sub(pattern, "", text)
    return re.sub(r"\s{2,}", " ", text).strip(" ，,、；;")


# evidence ids look like y4-013, src-2-1, ft-3-2, q-9-1, 6am-0, ev-4 (or typos like y-019)
_ID_ALT = r"(?:y4|y|src|ft|q|6am|ev)-\d+(?:-\d+)?"


def _style_for(evidence: List[Dict[str, Any]]) -> str:
    """_STYLE plus the list of sources this student actually has, so the model
    does not cite a Case Review or parent feedback that was never provided."""
    present = []
    for item in evidence:
        label = SOURCE_LABELS.get(item.get("source"), "")
        if label and label not in present:
            present.append(label)
    return _STYLE + "\n- 本学生已有的资料来源只有：%s。不要提到其他来源。" % ("、".join(present) or "无")


# a 2.3 conflict must name at least one source outside Y4
_NON_Y4_WORDS = ("家长", "妈妈", "爸爸", "父亲", "母亲反馈", "老师", "First Touch", "Case Review",
                 "问卷", "学生", "原话", "观察", "记录")


def _as_list(value) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        text = _clean(item)
        if text and text not in out:
            out.append(text)
    return out


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _date(value) -> str:
    if hasattr(value, "isoformat"):
        value = value.isoformat()
    return _clean(str(value or ""))[:10]


def _block(block_id: str, text: str) -> Dict[str, str]:
    text = _clean(text)
    return {"id": block_id, "text": text, "origin": "ai", "ai_text": text}


def _ask(prompt: str, schema_name: str) -> Dict[str, Any]:
    """调用模型并解析 JSON；解析失败重试一次。"""
    for attempt in range(2):
        try:
            result = call_model(prompt)
            if isinstance(result, str):
                result = json.loads(result)
        except json.JSONDecodeError:
            if attempt:
                raise
            continue
        if isinstance(result, dict):
            return result
        if attempt:
            break
    raise AnalysisError("AI 返回格式无效，请重试")


def _public_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """证据条目的提示词/接口视图：永不包含 ``raw``。"""
    return {key: item.get(key) for key in (
        "id", "source", "source_ref", "date", "kind", "group", "text",
        "quote", "abilities", "band")}


def _kb_codes() -> set:
    return {str(row.get("code")) for row in load_kb().get("abilities") or []}


def _kb_ability(code: str) -> Dict[str, Any]:
    for row in load_kb().get("abilities") or []:
        if row.get("code") == code:
            return row
    return {}


# ---------------------------------------------------------------------------
# 来源读取 / 安全扫描
# ---------------------------------------------------------------------------
def _text_sources(auto: Dict[str, Any], uploaded: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """需要 AI 抽条目的文字来源（First Touch + 导师上传）。"""
    rows: List[Dict[str, Any]] = []
    first_touch = auto.get("first_touch") or {}
    if first_touch.get("present") and _clean(first_touch.get("text")):
        session_id = first_touch.get("session_id") or "0"
        rows.append({
            "source": "first_touch",
            "source_ref": "copilot_session:%s" % session_id,
            "label": "First Touch",
            "date": _date(first_touch.get("date")),
            "text": _clean(first_touch.get("text")),
            "id_prefix": "ft-%s" % session_id,
        })
    category_map = {
        "parent": "parent",
        "case_review": "case_review",
        "other": "other",
        "first_touch_extra": "first_touch",
    }
    for row in uploaded or []:
        source = category_map.get(_clean(row.get("category")), "other")
        rows.append({
            "source": source,
            "source_ref": "m1_source:%s" % row.get("id"),
            "label": _clean(row.get("label")) or SOURCE_LABELS[source],
            "date": _date(row.get("detected_date") or row.get("created_at")),
            "text": _clean(row.get("text")),
            "id_prefix": "src-%s" % row.get("id"),
        })
    return [row for row in rows if row["text"]]


def _safety_texts(auto: Dict[str, Any], uploaded: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """所有可扫描正文（Y4 档位文字、6AM、问卷回答、上传资料）。"""
    rows: List[Dict[str, str]] = []
    y4 = auto.get("y4") or {}
    for item in y4.get("items") or []:
        if isinstance(item, dict) and _clean(item.get("text")):
            rows.append({
                "source_ref": _clean(item.get("source_ref")) or "y4",
                "text": _clean(item.get("text")),
            })
    six_am = y4.get("six_am") or {}
    states = six_am.get("states") if isinstance(six_am, dict) else None
    if isinstance(states, dict) and states:
        rows.append({
            "source_ref": "six_am:%s" % six_am.get("profile_id"),
            "text": "；".join("%s：%s" % (key, value) for key, value in states.items()),
        })
    for questionnaire in auto.get("questionnaires") or []:
        if questionnaire.get("status") != "已完成":
            continue
        for dimension, answers in (questionnaire.get("by_dimension") or {}).items():
            text = "；".join(
                "%s %s" % (_clean(answer.get("question")), _clean(answer.get("answer")))
                for answer in answers if isinstance(answer, dict))
            if _clean(text):
                rows.append({
                    "source_ref": "assignment:%s" % questionnaire.get("assignment_id"),
                    "text": text,
                })
    for row in _text_sources(auto, uploaded):
        rows.append({"source_ref": row["source_ref"], "text": row["text"]})
    return rows


def _scan_safety(auto: Dict[str, Any], uploaded: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """关键词命中后由 AI 做一次是/否核实；确认的片段进入 flags.safety。"""
    hits: List[Dict[str, str]] = []
    seen = set()
    for row in _safety_texts(auto, uploaded):
        for keyword in SAFETY_KEYWORDS:
            index = row["text"].find(keyword)
            if index < 0:
                continue
            snippet = row["text"][max(0, index - 40):index + len(keyword) + 40]
            snippet = re.sub(r"\s+", " ", snippet).strip()
            key = (row["source_ref"], snippet)
            if key in seen:
                continue
            seen.add(key)
            hits.append({"keyword": keyword, "source_ref": row["source_ref"],
                         "text": snippet})
    if not hits:
        return []

    payload = [{"source_ref": hit["source_ref"], "text": hit["text"]}
               for hit in hits[:8]]
    result = _ask(SAFETY_CHECK_PROMPT % _json(payload), SCHEMA_SAFETY)
    if not result.get("confirmed"):
        return []

    confirmed: List[Dict[str, str]] = []
    for item in result.get("items") or []:
        if not isinstance(item, dict):
            continue
        text = _clean(item.get("text"))
        if not text:
            continue
        confirmed.append({"text": text, "source_ref": _clean(item.get("source_ref"))})
    if confirmed:
        return confirmed
    return [{"text": hit["text"], "source_ref": hit["source_ref"]} for hit in hits]


# ---------------------------------------------------------------------------
# A. 证据
# ---------------------------------------------------------------------------
def _is_first_hand(quote: str) -> bool:
    """第一手观察：有实际内容，且不是对 Y4/测评结果的转述。"""
    return len(_norm(quote)) >= 6 and not _Y4_REF_RE.search(quote)


def _questionnaire_items(auto: Dict[str, Any]) -> List[Dict[str, Any]]:
    """补充问卷：每个维度一条，不经过 AI。"""
    items: List[Dict[str, Any]] = []
    for questionnaire in auto.get("questionnaires") or []:
        if questionnaire.get("status") != "已完成":
            continue
        assignment = questionnaire.get("assignment_id") or questionnaire.get("code") or "0"
        title = _clean(questionnaire.get("title")) or _clean(questionnaire.get("code"))
        for index, (dimension, answers) in enumerate(
                (questionnaire.get("by_dimension") or {}).items(), start=1):
            text = "；".join(
                "%s：%s" % (_clean(answer.get("question")), _clean(answer.get("answer")))
                for answer in answers if isinstance(answer, dict) and _clean(answer.get("answer")))
            if not _clean(text):
                continue
            items.append({
                "id": "q-%s-%d" % (assignment, index),
                "source": "questionnaire",
                "source_ref": "assignment:%s" % assignment,
                "date": _date(questionnaire.get("date")),
                "kind": "indirect",
                "group": "assignment:%s" % assignment,
                "text": "%s／%s：%s" % (title, dimension, text),
                "quote": "",
                "abilities": [],
                "band": "",
                "raw": None,
            })
    return items


def _six_am_items(auto: Dict[str, Any]) -> List[Dict[str, Any]]:
    """6 A.M. 摘要条目：与 Y4 同组，永不单独计为第二来源。"""
    six_am = (auto.get("y4") or {}).get("six_am")
    if not isinstance(six_am, dict):
        return []
    states = six_am.get("states") or {}
    if not isinstance(states, dict):
        return []
    items = []
    for index, (dimension, state) in enumerate(states.items()):
        items.append({
            "id": "6am-%d" % index,
            "source": "six_am",
            "source_ref": "six_am:%s" % six_am.get("profile_id"),
            "date": _date(six_am.get("created_at")),
            "kind": "inference",
            "group": "Y4",
            "text": "6 A.M. %s：%s" % (dimension, state),
            "quote": "",
            "abilities": [],
            "band": _clean(str(state)),
            "raw": None,
        })
    return items


def _source_text_items(auto: Dict[str, Any],
                       uploaded: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """每个文字来源一次 AI 调用；quote 不存在的条目直接丢弃。"""
    items: List[Dict[str, Any]] = []
    valid_codes = _kb_codes()
    for row in _text_sources(auto, uploaded):
        payload = {
            "source_ref": row["source_ref"],
            "label": row["label"],
            "date": row["date"],
            "text": row["text"][:_TEXT_LIMIT],
            "abilities": [{"code": row.get("code"), "name": row.get("name")}
                          for row in load_kb().get("abilities") or []],
        }
        result = _ask(SOURCE_ITEMS_PROMPT % _json(payload), SCHEMA_SOURCE)
        seen_quotes = set()
        for index, raw in enumerate(result.get("items") or [], start=1):
            if not isinstance(raw, dict):
                continue
            quote = _clean(raw.get("quote"))
            normalised = _norm(quote)
            if not normalised or normalised not in _norm(row["text"]):
                continue
            if normalised in seen_quotes:
                continue
            seen_quotes.add(normalised)

            kind = _clean(raw.get("kind")).lower()
            if row["source"] == "case_review":
                independent = bool(raw.get("independent")) and _is_first_hand(quote)
                kind = "direct" if independent else "hypothesis"
            elif kind not in _KINDS:
                kind = "inference"
            elif kind == "hypothesis":
                kind = "inference"

            abilities = []
            for code in raw.get("abilities") or []:
                code = _clean(code)
                if code in valid_codes and code not in abilities:
                    abilities.append(code)

            items.append({
                "id": "%s-%d" % (row["id_prefix"], index),
                "source": row["source"],
                "source_ref": row["source_ref"],
                "date": row["date"],
                "kind": kind,
                "group": row["source_ref"],
                "text": _clean(raw.get("text")) or quote,
                "quote": quote,
                "abilities": abilities,
                "band": "",
                "raw": None,
            })
    return items


def _build_evidence(auto: Dict[str, Any],
                    uploaded: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    y4 = auto.get("y4") or {}
    for raw in y4.get("items") or []:
        if not isinstance(raw, dict):
            continue
        items.append({
            "id": _clean(raw.get("id")),
            "source": "y4",
            "source_ref": _clean(raw.get("source_ref")),
            "date": _date(raw.get("date")),
            "kind": "indirect",
            "group": "Y4",
            "text": _clean(raw.get("text")),
            "quote": "",
            "abilities": [code for code in raw.get("abilities") or []
                          if _clean(code)],
            "band": _clean(raw.get("band")),
            "raw": raw.get("raw"),
        })
    items.extend(_six_am_items(auto))
    items.extend(_questionnaire_items(auto))
    items.extend(_source_text_items(auto, uploaded))
    for index, item in enumerate(items, start=1):
        if not item["id"]:
            item["id"] = "ev-%d" % index
    return items


# ---------------------------------------------------------------------------
# B. 逐项判断
# ---------------------------------------------------------------------------
def _judge_abilities(evidence: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    kb = load_kb()
    by_id = {item["id"]: item for item in evidence}
    public = [_public_item(item) for item in evidence]
    judgements: Dict[str, Dict[str, Any]] = {}

    def ask_dimension(dimension):
        abilities = [row for row in kb.get("abilities") or []
                     if row.get("dim") == dimension.get("id")]
        codes = {str(row.get("code")) for row in abilities}
        # Y4 items are tagged by the KB mapping (reliable) and filtered per
        # dimension; real-situation items are few and AI-tagged, so every
        # dimension sees all of them
        relevant = [
            item for item in public
            if item.get("group") != "Y4"
            or not item.get("abilities") or codes & set(item.get("abilities") or [])
        ]
        ability_payload = [{
            "code": row.get("code"),
            "name": row.get("name"),
            "gap_note": row.get("gap_note"),
            "ask": row.get("ask"),
            "indicator_note": row.get("indicator_note"),
        } for row in abilities]
        result = _ask(
            ABILITY_PROMPT % (_style_for(evidence), dimension.get("id"), _json(ability_payload),
                              _json(relevant)),
            SCHEMA_ABILITY)
        return codes, result

    dims = list(kb.get("dims") or [])
    with ThreadPoolExecutor(max_workers=max(1, len(dims))) as pool:
        answers = list(pool.map(ask_dimension, dims))

    for codes, result in answers:
        for raw in result.get("abilities") or []:
            if not isinstance(raw, dict):
                continue
            code = _clean(raw.get("code"))
            if code not in codes:
                continue
            cites = [item_id for item_id in _as_list(raw.get("cites"))
                     if item_id in by_id]
            strip = lambda value: _strip_ids(value, by_id)
            groups = {by_id[item_id]["group"] for item_id in cites}
            has_cites = bool(cites)
            supported = len(groups) >= 2

            potential = [strip(x) for x in _as_list(raw.get("potential"))] if has_cites else []
            interference = [strip(x) for x in _as_list(raw.get("interference"))] if has_cites else []
            contradictions = [strip(x) for x in _as_list(raw.get("contradictions"))] if has_cites else []
            missing = [strip(x) for x in _as_list(raw.get("missing"))]
            check_text = strip(raw.get("check_text"))
            reason = strip(raw.get("reason"))

            judgements[code] = {
                "code": code,
                "potential": potential,
                "interference": interference,
                "known": _clean(raw.get("known")) if has_cites else "",
                "new_clues": _clean(raw.get("new_clues")) if has_cites else "",
                "contradictions": contradictions,
                "missing": missing,
                "check_text": check_text or "尚未取得可引用的证据。",
                "recommend": bool(raw.get("recommend")) and has_cites,
                "reason": reason or "证据有限，待会议中确认。",
                "cites": cites,
                "supported": supported,
            }
    return judgements


# ---------------------------------------------------------------------------
# C. 优先能力
# ---------------------------------------------------------------------------
_CONCERN_BANDS = {"偏低", "明显偏低", "严重偏低", "需关注", "需特殊关注"}


def _direct_items(row: Dict[str, Any], by_id: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Real-situation evidence (student, parent, teacher) that the extraction step
    itself tagged with this ability; citing more items does not add weight."""
    code = row.get("code")
    return [by_id[item_id] for item_id in row.get("cites") or []
            if by_id[item_id]["group"] != "Y4"
            and by_id[item_id]["kind"] == "direct"
            and (not by_id[item_id].get("abilities")
                 or code in by_id[item_id]["abilities"])]


def _y4_concern(row: Dict[str, Any], by_id: Dict[str, Dict[str, Any]]) -> bool:
    return any(by_id[item_id]["source"] == "y4"
               and by_id[item_id].get("band") in _CONCERN_BANDS
               for item_id in row.get("cites") or [])


def _priority_score(row: Dict[str, Any], by_id: Dict[str, Dict[str, Any]]) -> int:
    cited = [by_id[item_id] for item_id in row.get("cites") or []]
    direct = _direct_items(row, by_id)
    direct_groups = len({item["group"] for item in direct})
    pi = 1 if row.get("potential") and row.get("interference") else 0
    conflict = 1 if row.get("contradictions") else 0
    parent = 1 if any(item["source"] == "parent" for item in direct) else 0
    case_hypothesis = 1 if any(
        item["source"] == "case_review" and item["kind"] == "hypothesis"
        and row.get("code") in (item.get("abilities") or [])
        for item in cited) else 0
    concern = 1 if _y4_concern(row, by_id) else 0
    return (min(len(direct), 2) * 2 + direct_groups * 2 + pi * 2 + conflict * 2
            + parent + case_hypothesis + concern)


def _choose_priorities(judgements: Dict[str, Dict[str, Any]],
                       by_id: Dict[str, Dict[str, Any]]) -> List[str]:
    """按代码分数取 3–5 个 recommend 能力；证据不足时允许更少。"""
    order = {str(row.get("code")): index
             for index, row in enumerate(load_kb().get("abilities") or [])}
    # framework: never pick by Y4 bands alone. Abilities with real-situation
    # evidence come first; Y4-only abilities need a concern band and fill at
    # most 2 slots, so a Y4-only student gets 0–2 priorities, not 5.
    with_direct, y4_only = [], []
    for code, row in judgements.items():
        if not row.get("recommend"):
            continue
        scored = (code, _priority_score(row, by_id))
        if _direct_items(row, by_id):
            with_direct.append(scored)
        elif _y4_concern(row, by_id):
            y4_only.append(scored)
    rank = lambda item: (-item[1], order.get(item[0], 999))
    # at most 2 per R dimension: one setback story should not fill every slot
    # with near-duplicate Recover abilities
    chosen: List[str] = []
    per_dim: Dict[str, int] = {}
    for code, _score in sorted(with_direct, key=rank):
        dim = code.split(".")[0]
        if len(chosen) < 5 and per_dim.get(dim, 0) < 2:
            chosen.append(code)
            per_dim[dim] = per_dim.get(dim, 0) + 1
    if len(chosen) < 3:
        chosen += [code for code, _ in sorted(y4_only, key=rank)[:min(2, 3 - len(chosen))]]
    return chosen


def _evidence_line(item: Dict[str, Any]) -> str:
    label = SOURCE_LABELS.get(item.get("source"), "资料")
    date = item.get("date") or ""
    quote = _clean(item.get("quote"))
    prefix = ("%s %s" % (label, date)).strip()
    if quote:
        text = "%s：「%s」" % (prefix, quote)
    else:
        text = "%s：%s" % (prefix, _clean(item.get("text")))
    if item.get("source") in ("y4", "six_am"):
        text += "；VERDICT 无直接对应"
    return text


def _priority_evidence_lines(row: Dict[str, Any],
                             by_id: Dict[str, Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    cites = [item_id for item_id in row.get("cites") or [] if item_id in by_id]
    # real quotes first, then Y4 bands (framework 2.2: 原始 Evidence / VERDICT)
    cites.sort(key=lambda item_id: (by_id[item_id]["group"] == "Y4",
                                    by_id[item_id]["kind"] not in ("direct", "context")))
    for item_id in cites:
        item = by_id.get(item_id)
        if not item:
            continue
        line = _evidence_line(item)
        if line not in lines:
            lines.append(line)
    return lines[:3] or ["尚未取得可引用的证据。"]


def _write_priorities(chosen: List[str], judgements: Dict[str, Dict[str, Any]],
                      by_id: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not chosen:
        return []
    payload = [{
        "code": code,
        "potential": judgements[code]["potential"],
        "interference": judgements[code]["interference"],
        "missing": judgements[code]["missing"],
        "cites": judgements[code]["cites"],
    } for code in chosen]
    cited_items = []
    for code in chosen:
        for item_id in judgements[code]["cites"]:
            item = by_id.get(item_id)
            if item and _public_item(item) not in cited_items:
                cited_items.append(_public_item(item))
    result = _ask(PRIORITY_PROMPT % (_style_for(list(by_id.values())), _json(payload),
                                     _json(cited_items)),
                  SCHEMA_PRIORITY)
    texts: Dict[str, Dict[str, str]] = {}
    for raw in result.get("items") or []:
        if isinstance(raw, dict) and _clean(raw.get("code")):
            texts[_clean(raw.get("code"))] = raw

    rows: List[Dict[str, Any]] = []
    for code in chosen:
        raw = texts.get(code) or {}
        hypothesis = _strip_ids(raw.get("hypothesis"), by_id) \
            or "现有证据不足以形成明确假设，待会议中确认。"
        why = _strip_ids(raw.get("why"), by_id) or judgements[code].get("reason") \
            or "证据有限，需要当面确认。"
        rows.append({
            "code": code,
            "evidence": _priority_evidence_lines(judgements[code], by_id),
            "hypothesis": _block("h-%s" % code, hypothesis),
            "why": _block("w-%s" % code, why),
        })
    return rows


# ---------------------------------------------------------------------------
# D. 会议流程
# ---------------------------------------------------------------------------
def _question_lines(raw_questions, abilities: List[str]) -> str:
    lines = _as_list(raw_questions)
    kb = load_kb()
    fallback: List[str] = []
    for code in abilities:
        ask = _clean(_kb_ability(code).get("ask"))
        if ask and ask not in fallback:
            fallback.append(ask)
    for row in (kb.get("fixed") or {}).get("quick_check") or []:
        question = _clean(row.get("question"))
        if question and question not in fallback:
            fallback.append(question)
    for candidate in fallback:
        if len(lines) >= 2:
            break
        if candidate not in lines:
            lines.append(candidate)
    lines = lines[:_MAX_EVENT_QUESTIONS]
    return "\n".join("%d. %s" % (index, line)
                     for index, line in enumerate(lines, start=1))


def _open_topic(priority_codes: List[str]) -> Dict[str, Any]:
    kb = load_kb()
    questions = [
        _clean(row.get("question"))
        for row in (kb.get("fixed") or {}).get("quick_check") or []
        if _clean(row.get("question"))
    ][:3]
    return {
        "id": "ev1",
        "title": _block("ev1-title", "开放探索主题：近期情绪与关系体验"),
        "clue": "未取得可引用的真实事件，按开放问题了解近期情况。",
        "abilities": priority_codes[:3],
        "gap": _block("ev1-gap", "待会议中了解具体事件、情绪与关系体验。"),
        "questions": _block("ev1-questions",
                            "\n".join("%d. %s" % (index, question)
                                      for index, question in enumerate(questions, start=1))),
    }


def _build_plan(prep: Dict[str, Any], evidence: List[Dict[str, Any]],
                judgements: Dict[str, Dict[str, Any]],
                priority_rows: List[Dict[str, Any]],
                insufficient: List[str]) -> Dict[str, Any]:
    kb = load_kb()
    by_id = {item["id"]: item for item in evidence}
    event_pool = [item for item in evidence
                  if item["source"] in _EVENT_SOURCES and item["kind"] in _EVENT_KINDS]
    valid_event_ids = {item["id"] for item in event_pool}
    priority_codes = [row["code"] for row in priority_rows]

    priority_payload = [{
        "code": row["code"],
        "hypothesis": row["hypothesis"]["text"],
        "why": row["why"]["text"],
        "missing": judgements[row["code"]]["missing"],
        "cites": judgements[row["code"]]["cites"],
    } for row in priority_rows]
    duration = int(prep.get("duration") or 60)
    max_events = 2 if duration <= 60 else 3
    result = _ask(
        MEETING_PLAN_PROMPT % (duration, max_events, _style_for(evidence),
                               _json([_public_item(item) for item in event_pool]),
                               _json(priority_payload),
                               _json([_public_item(item) for item in evidence])),
        SCHEMA_PLAN)
    valid_codes = _kb_codes()
    events: List[Dict[str, Any]] = []
    for raw in result.get("events") or []:
        if len(events) >= max_events:
            break
        if not isinstance(raw, dict):
            continue
        ids = [item_id for item_id in _as_list(raw.get("evidence_ids"))
               if item_id in valid_event_ids]
        cited = [by_id[item_id] for item_id in ids]
        if not cited:
            continue
        # the 3.2 column is 「关联的 Priority R4 能力」: keep priority codes first
        named = [code for code in _as_list(raw.get("abilities")) if code in valid_codes]
        abilities = [code for code in named if code in priority_codes] or named
        if not abilities:
            abilities = [code for code in cited[0].get("abilities") or []
                         if code in priority_codes]
        event_id = "ev%d" % (len(events) + 1)
        title = _strip_ids(raw.get("title"), by_id) or _clean(cited[0].get("text"))
        clue = "；".join(_evidence_line(item) for item in cited[:2])
        gap = _strip_ids(raw.get("gap"), by_id) or "待会议中确认具体细节。"
        events.append({
            "id": event_id,
            "title": _block("%s-title" % event_id, title),
            "clue": clue,
            "abilities": abilities,
            "gap": _block("%s-gap" % event_id, gap),
            "questions": _block("%s-questions" % event_id,
                                _question_lines(raw.get("questions"), abilities)),
        })
    if not events:
        events = [_open_topic(priority_codes)]

    backup_questions = result.get("backup_questions") \
        if isinstance(result.get("backup_questions"), dict) else {}
    covered = set()
    for event in events:
        covered.update(event.get("abilities") or [])
    backups = []
    for row in priority_rows:
        code = row["code"]
        if code in covered:
            continue
        defined = _kb_ability(code)
        missing = "；".join(judgements[code]["missing"]) or _clean(defined.get("gap_note"))
        backups.append({
            "code": code,
            "missing": _block("bk-g-%s" % code, missing or "信息不足。"),
            "question": _block("bk-q-%s" % code,
                               _strip_ids(backup_questions.get(code), by_id)
                               or ("导师参考：" + _clean(defined.get("ask"))
                                   if _clean(defined.get("ask")) else "还有什么想补充的？")),
            "timing": "第 4 环节；如已回答则跳过",
        })

    contradictions = []
    for code, row in judgements.items():
        for text in row.get("contradictions") or []:
            contradictions.append("%s：%s" % (code, text))
    special_raw = result.get("special") if isinstance(result.get("special"), dict) else {}
    conflict = _strip_ids(special_raw.get("conflict"), by_id) or "；".join(contradictions[:2])
    if not any(word in conflict for word in _NON_Y4_WORDS):
        # two Y4 scales disagreeing is one source, not an evidence conflict
        conflict = "本次资料中未见两个独立来源之间的明显矛盾。"
    context = _strip_ids(special_raw.get("context"), by_id) or "信息不足，待会议中补充。"
    attention = _strip_ids(special_raw.get("attention"), by_id) \
        or "；".join(insufficient[:3]) or "信息不足，待会议中补充。"

    growth_raw = result.get("growth") if isinstance(result.get("growth"), dict) else {}
    wish = _strip_ids(growth_raw.get("wish"), by_id) \
        or "如果接下来有一个地方能变得更轻松，你最希望是什么？"
    next_step = _strip_ids(growth_raw.get("next"), by_id) \
        or "信息不足，正式方向待会议中与学生讨论后确定。"

    return {
        "events": events,
        "backups": backups,
        "special": {
            "conflict": _block("c1", conflict),
            "context": _block("c2", context),
            "attention": _block("c3", attention),
        },
        "growth": {
            "wish": _block("gw", wish),
            "next": _block("nd", next_step),
        },
        "raw": result,
    }


# ---------------------------------------------------------------------------
# E. 组装
# ---------------------------------------------------------------------------
def _snippet(text: str, limit: int = 90) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _join_snippets(values, limit: int = 180) -> str:
    parts: List[str] = []
    for value in values:
        snippet = _snippet(value)
        if snippet and snippet not in parts:
            parts.append(snippet)
    joined = "；".join(parts)
    return joined if len(joined) <= limit else joined[:limit] + "…"


_STATUS_CN = {"ok": "完整", "partial": "部分信息", "unreadable": "无法识别"}


def _upload_status(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "未取得"
    rank = {"ok": 0, "partial": 1, "unreadable": 2}
    worst = max(rows, key=lambda row: rank.get(row.get("status"), 1))
    status = _STATUS_CN.get(worst.get("status"), "部分信息")
    date = _date(worst.get("detected_date") or worst.get("created_at"))
    label = _clean(worst.get("label")) or "资料"
    text = "%s；%s，%s" % (status, date, label) if date else "%s；%s" % (status, label)
    if len(rows) > 1:
        text += " 等 %d 条" % len(rows)
    return text


def _extracted(evidence, source: str, fallback: str) -> str:
    """1.2 「会前提取信息」: what was extracted from the source (the evidence
    texts), not the first lines of the raw document."""
    texts = []
    for item in evidence or []:
        if item.get("source") == source and item.get("text") and item["text"] not in texts:
            texts.append(item["text"])
    joined = "；".join(texts[:5])
    if len(joined) > 160:
        joined = joined[:159].rstrip("；") + "…"
    return joined or fallback


def _source_entries(auto: Dict[str, Any],
                    uploaded: List[Dict[str, Any]],
                    evidence: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    y4 = auto.get("y4") or {}
    first_touch = auto.get("first_touch") or {}
    questionnaires = auto.get("questionnaires") or []

    def by_category(category: str) -> List[Dict[str, Any]]:
        return [row for row in uploaded if row.get("category") == category]

    parent = by_category("parent")
    case_review = by_category("case_review")
    other = by_category("other")
    first_touch_extra = by_category("first_touch_extra")

    entries = []

    # 家长初始反馈
    entries.append({
        "key": "parent",
        "label": "家长初始反馈",
        "extracted": _block("src-parent",
                            _extracted(evidence, "parent", _join_snippets([row.get("text") for row in parent]))
                            or "尚未取得相关资料"),
        "status_text": _upload_status(parent),
    })

    # Y4
    if y4.get("complete"):
        y4_text = "与 R4 相关的指标及标准化档位；6 A.M. 为 Y4 衍生分析，不重复作为独立证据"
        y4_status = "完整" + ("；测评 %s" % _date(y4.get("date")) if y4.get("date") else "")
    else:
        y4_text = "尚未取得完整 Y4 报告"
        y4_status = "未完成"
    entries.append({
        "key": "y4",
        "label": "Y4 Assessment",
        "extracted": _block("src-y4", y4_text),
        "status_text": y4_status,
    })

    # 补充问卷
    if questionnaires:
        status_parts = []
        for row in questionnaires:
            code = _clean(row.get("code")) or _clean(row.get("title"))
            status = _clean(row.get("status")) or "未取得"
            date = _date(row.get("date"))
            status_parts.append("%s %s%s" % (code, status,
                                             "（%s）" % date
                                             if date and status == "已完成" else ""))
        done = [_clean(row.get("code")) for row in questionnaires
                if row.get("status") == "已完成" and _clean(row.get("code"))]
        pending = [_clean(row.get("code")) for row in questionnaires
                   if row.get("status") == "未取得" and _clean(row.get("code"))]
        idle = [_clean(row.get("code")) for row in questionnaires
                if row.get("status") == "未触发" and _clean(row.get("code"))]
        pieces = []
        if done:
            pieces.append("%s 已按维度整理原始回答" % "、".join(done))
        if pending:
            pieces.append("%s 未取得" % "、".join(pending))
        if idle:
            pieces.append("%s 未触发" % "、".join(idle))
        questionnaire_text = "；".join(pieces) or "尚未取得相关资料"
        questionnaire_status = "；".join(status_parts)
    else:
        questionnaire_text = "尚未取得相关资料"
        questionnaire_status = "未取得"
    entries.append({
        "key": "questionnaire",
        "label": "补充问卷",
        "extracted": _block("src-questionnaire", questionnaire_text),
        "status_text": questionnaire_status,
    })

    # First Touch
    first_touch_texts = []
    if first_touch.get("present"):
        first_touch_texts.append(first_touch.get("text"))
    first_touch_texts.extend(row.get("text") for row in first_touch_extra)
    entries.append({
        "key": "first_touch",
        "label": "First Touch Meeting",
        "extracted": _block("src-first-touch",
                            _extracted(evidence, "first_touch", _join_snippets(first_touch_texts))
                            or "尚未取得相关资料"),
        "status_text": ("完整；%s" % _date(first_touch.get("date"))
                        if first_touch.get("present") and first_touch.get("date")
                        else ("完整" if first_touch.get("present")
                              else _upload_status(first_touch_extra))),
    })

    # Case Review
    entries.append({
        "key": "case_review",
        "label": "Case Review Meetings",
        "extracted": _block("src-case-review",
                            _extracted(evidence, "case_review", _join_snippets([row.get("text") for row in case_review]))
                            or "尚未取得相关资料"),
        "status_text": _upload_status(case_review),
    })

    # 其他资料
    entries.append({
        "key": "other",
        "label": "其他证据",
        "extracted": _block("src-other",
                            _extracted(evidence, "other", _join_snippets([row.get("text") for row in other]))
                            or "尚未取得相关资料"),
        "status_text": _upload_status(other),
    })
    return entries


def _insufficient(auto: Dict[str, Any], uploaded: List[Dict[str, Any]]) -> List[str]:
    y4 = auto.get("y4") or {}
    first_touch = auto.get("first_touch") or {}
    questionnaires = auto.get("questionnaires") or []
    categories = {row.get("category") for row in uploaded}
    rows: List[str] = []

    if not y4.get("complete"):
        rows.append("Y4：未完成")
    if not first_touch.get("present") and "first_touch_extra" not in categories:
        rows.append("First Touch：未取得")
    if "parent" not in categories:
        rows.append("家长初始反馈：未取得")
    if not questionnaires:
        rows.append("补充问卷：未取得")
    for row in questionnaires:
        if row.get("status") == "未取得":
            title = _clean(row.get("title")) or _clean(row.get("code")) or "问卷"
            rows.append("%s：已发送未作答" % title)
    if "case_review" not in categories:
        rows.append("Case Review：未取得")
    if "other" not in categories:
        rows.append("其他资料：未取得")

    for category, label in (("parent", "家长初始反馈"),
                            ("case_review", "Case Review"),
                            ("other", "其他资料"),
                            ("first_touch_extra", "First Touch")):
        for row in uploaded:
            if row.get("category") != category:
                continue
            if row.get("status") == "partial":
                rows.append("%s：部分信息" % label)
                break
            if row.get("status") == "unreadable":
                rows.append("%s：无法识别" % label)
                break
    return rows


def _dim_entries(judgements: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    kb = load_kb()
    rows = []
    for dimension in kb.get("dims") or []:
        dim_id = str(dimension.get("id"))
        codes = [str(row.get("code")) for row in kb.get("abilities") or []
                 if row.get("dim") == dim_id]

        potential_parts = []
        interference_parts = []
        gap_parts = []
        for code in codes:
            row = judgements.get(code)
            if not row:
                continue
            # one line per ability keeps the 2.1 cells readable on A4
            if row.get("potential"):
                potential_parts.append("%s %s" % (code, row["potential"][0]))
            if row.get("interference"):
                interference_parts.append("%s %s" % (code, row["interference"][0]))
            if row.get("missing"):
                gap_parts.append("%s %s" % (code, row["missing"][0]))

        rows.append({
            "dim": dim_id,
            "potential": _block("p-%s" % dim_id,
                                "；".join(potential_parts[:3]) or "信息不足。"),
            "interference": _block("i-%s" % dim_id,
                                   "；".join(interference_parts[:3]) or "信息不足。"),
            "gap": _block("g-%s" % dim_id,
                          "；".join(gap_parts[:3]) or "信息不足，需在会议中确认。"),
        })
    return rows


def _appendix(judgements: Dict[str, Dict[str, Any]],
              chosen: List[str]) -> List[Dict[str, Any]]:
    """☑ 推荐 follows the final 2.2 list, so the Appendix never contradicts Part 2."""
    rows = []
    for defined in load_kb().get("abilities") or []:
        code = str(defined.get("code"))
        row = judgements.get(code) or {}
        reason = _clean(row.get("reason")) \
            or ("建议优先确认" if code in chosen else "信息不足，暂不单独验证。")
        check = _clean(row.get("check_text")) or "尚未取得可引用的证据。"
        rows.append({
            "code": code,
            "recommend": code in chosen,
            "reason": _block("ap-r-%s" % code, reason),
            "check": _block("ap-c-%s" % code, check),
        })
    return rows


def _assemble_doc(prep: Dict[str, Any], auto: Dict[str, Any],
                  uploaded: List[Dict[str, Any]], evidence: List[Dict[str, Any]],
                  judgements: Dict[str, Dict[str, Any]],
                  priority_rows: List[Dict[str, Any]],
                  plan: Dict[str, Any],
                  safety: List[Dict[str, str]],
                  insufficient: List[str]) -> Dict[str, Any]:
    return {
        "meta": {
            "student": prep.get("student_name") or "",
            "grade": prep.get("grade") or "",
            "school": prep.get("school") or "",
            "meeting_date": prep.get("meeting_date") or "",
            "mentor": prep.get("mentor_name") or "",
            "duration": int(prep.get("duration") or 60),
            "people": prep.get("attendees") or [],
        },
        "sources": _source_entries(auto, uploaded, evidence),
        "dims": _dim_entries(judgements),
        "priority": priority_rows,
        "special": plan["special"],
        "events": plan["events"],
        "backups": plan["backups"],
        "growth": plan["growth"],
        "appendix": _appendix(judgements, [row["code"] for row in priority_rows]),
        "flags": {
            "safety": safety,
            "insufficient": insufficient,
        },
    }


def _y4_snapshot(auto: Dict[str, Any]) -> Dict[str, Any]:
    y4 = auto.get("y4") or {}
    return {
        "report_id": y4.get("report_id"),
        "date": _date(y4.get("date")),
        "complete": bool(y4.get("complete")),
        "items": y4.get("items") or [],
        "six_am": y4.get("six_am"),
    }


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
ProgressCallback = Callable[[str, str, float], None]


def generate(prep_id: int, progress: Optional[ProgressCallback] = None) -> int:
    """跑完 A–E，保存版本并把 prep 置为 review；返回 ``ai_draft`` 版本 id。"""
    prep = store.get_prep(int(prep_id))
    if not prep:
        raise store.NotFoundError("会前准备不存在")

    def emit(step: str, state: str, seconds: float = 0.0) -> None:
        if progress is None:
            return
        try:
            progress(step, state, round(float(seconds), 1))
        except Exception:
            pass

    def run(step: str, fn):
        started = time.monotonic()
        emit(step, "running")
        try:
            result = fn()
        except Exception:
            emit(step, "error", time.monotonic() - started)
            raise
        emit(step, "done", time.monotonic() - started)
        return result

    auto = sources.auto_sources(prep["student_id"])
    uploaded = store.list_sources(prep["id"])

    safety = run("safety", lambda: _scan_safety(auto, uploaded))
    evidence = run("evidence", lambda: _build_evidence(auto, uploaded))
    judgements = run("abilities", lambda: _judge_abilities(evidence))
    by_id = {item["id"]: item for item in evidence}

    def priority_stage():
        chosen = _choose_priorities(judgements, by_id)
        return chosen, _write_priorities(chosen, judgements, by_id)

    _chosen, priority_rows = run("priority", priority_stage)
    insufficient = _insufficient(auto, uploaded)
    plan = run("plan", lambda: _build_plan(prep, evidence, judgements,
                                           priority_rows, insufficient))

    def assemble():
        doc = _assemble_doc(prep, auto, uploaded, evidence, judgements,
                            priority_rows, plan, safety, insufficient)
        # the model sometimes repeats a Y4 score next to its indicator; drop it
        # rather than failing a multi-minute generation (owner rule: bands only)
        redact_raw_numbers(doc, evidence)
        validate_doc(doc, evidence)
        return doc

    doc = run("assemble", assemble)

    draft = store.add_version(
        prep["id"], "ai_draft", doc=doc, y4_snapshot=_y4_snapshot(auto),
        kb_version=str(load_kb().get("version") or ""), evidence=evidence,
        ai_output={"abilities": judgements,
                   "priority": [row["code"] for row in priority_rows],
                   "plan": plan.get("raw") or {}},
        ai_generated_at=datetime.utcnow(), created_by=prep.get("created_by"),
    )
    store.add_version(
        prep["id"], "edit", doc=copy.deepcopy(doc), y4_snapshot=_y4_snapshot(auto),
        kb_version=str(load_kb().get("version") or ""), evidence=evidence,
        ai_output=draft.get("ai_output") or {},
        ai_generated_at=datetime.utcnow(), created_by=prep.get("created_by"),
    )
    store.set_status(prep["id"], "review")
    return draft["id"]
