"""M1 AI 生成管道（步骤 A–E）。

``generate(prep_id)`` 读自动来源与导师上传资料，产出 README §4 文档 JSON，
写一个 ``ai_draft`` 版本和一个新的 ``edit`` 副本，并把 prep 置为 ``review``。

所有 AI 调用都经过 :func:`_ask`；测试替换该函数即可完全离线。
"""
from __future__ import annotations

import copy
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import ai_writing
import db as _db
from growth_talk.analysis import AnalysisError, call_model
from sqlalchemy.orm import Session

import m1.sources as sources
import m1.store as store
from m1 import report_checks, report_pipeline
from m1.kb import load_kb
from m1.prompts import (_STYLE, ABILITY_PROMPT, MEETING_PLAN_PROMPT,
                        PRIORITY_PROMPT, SAFETY_CHECK_PROMPT, SAFETY_KEYWORDS,
                        SOURCE_ITEMS_PROMPT, SOURCE_SUMMARY_PROMPT)
from m1.validate_doc import redact_raw_numbers, validate_doc

SCHEMA_SOURCE = "source_items"
SCHEMA_SAFETY = "safety_check"
SCHEMA_ABILITY = "ability"
SCHEMA_PRIORITY = "priority"
SCHEMA_PLAN = "meeting_plan"
SCHEMA_SUMMARY = "source_summary"
SCHEMA_VERIFY = "fact_check"
SCHEMA_REWRITE = "fact_rewrite"

logger = logging.getLogger(__name__)

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
_KINDS = {"direct", "indirect", "context", "inference", "hypothesis", "hypothetical"}
_Y4_REF_RE = re.compile(r"Y4|测评|报告|得分|档位|分数|量表|测验|问卷")
# 导师的发言、引导性提问与学生附和、假设性回答都不是学生的真实经历
_TIME_MARK = r"(?:\d{1,2}:\d{2}(?::\d{2})?)"
_MENTOR_LINE_RE = re.compile(
    r"^\W*(?:" + _TIME_MARK + r"\W*)?(导师|老师|mentor)\s*"
    r"(?:" + _TIME_MARK + r"\s*)?[：:]", re.I)
_LEADING_RE = re.compile(r"是不是|对不对|是吗|吧[？?]")
_HYPOTHETICAL_RE = re.compile(r"如果|假如|要是|万一|下次")
# a student line that talks about something that really happened is not a supposition,
# even when the mentor's question before it began with 如果 (unless the line itself
# is worded as a supposition: 要是、如果、下次……, e.g. "上台之前先跟同学对稿，要是……")
_PAST_EVENT_WORDS = ("上个月", "上周", "上次", "那次", "有一次", "当时", "之前", "昨天", "去年", "上学期")
# 学生中途改口（“……不对，其实……”）：只留改口之后的说法；“对不对”不是改口
_CORRECTION_RE = re.compile(r"(?<!对)不对")
_LEADING_PUNCT = "，,。.、；;：:！!？?…—-~～ \u3000\"'“”‘’「」『』（）()"
# one source is cut into pieces of at most this many characters; every piece is read
_TEXT_LIMIT = 6000
# 1.2 summaries: whole sentences only, dropped from the end when too long
_SUMMARY_LIMIT = 300
SUMMARY_FALLBACK = "已取得资料，未能生成摘要，请查看原文。"
UNCHECKED_FLAG_TEXT = "部分内容未完成事实核对，请人工核对。"
# the fact check must not hold up a document for long; unfinished checks are flagged
_GUARD_BUDGET_SECONDS = 300
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


def _gender_line(gender: str) -> str:
    if gender in ("男", "女"):
        return "\n- 学生性别：%s。" % gender
    return "\n- 资料没有写明学生性别：不要用“他”“她”指代学生，写“学生”。"


def _style_for(evidence: List[Dict[str, Any]], gender: str = "") -> str:
    """_STYLE plus the list of sources this student actually has, so the model
    does not cite a Case Review or parent feedback that was never provided."""
    present = []
    for item in evidence:
        label = SOURCE_LABELS.get(item.get("source"), "")
        if label and label not in present:
            present.append(label)
    return (_STYLE + "\n- 本学生已有的资料来源只有：%s。不要提到其他来源。" % ("、".join(present) or "无")
            + _gender_line(gender))


def _student_gender(student_id) -> str:
    """The record's gender, normalised to 男 / 女 / '' (blank = not stated)."""
    try:
        with Session(store._engine()) as sess:
            student = sess.get(_db.Student, int(student_id))
            value = str(getattr(student, "gender", "") or "").strip().lower()
    except Exception:
        return ""
    if value in ("男", "男生", "male", "m", "boy"):
        return "男"
    if value in ("女", "女生", "female", "f", "girl"):
        return "女"
    return ""


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


def _split_pieces(text: str, limit: int = _TEXT_LIMIT) -> List[str]:
    """Cut a long source at line breaks into pieces of at most ``limit`` characters,
    so no part of a long meeting is silently ignored."""
    pieces: List[str] = []
    current: List[str] = []
    size = 0
    for line in str(text or "").split("\n"):
        while len(line) > limit:  # a single line longer than a piece
            if current:
                pieces.append("\n".join(current))
                current, size = [], 0
            pieces.append(line[:limit])
            line = line[limit:]
        if current and size + len(line) + 1 > limit:
            pieces.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        pieces.append("\n".join(current))
    return [piece for piece in pieces if piece.strip()]


def _quote_lines(text: str, quote: str) -> Tuple[str, str]:
    """引文所在的那一行，以及它的上一行；跨行引文返回两个空字符串。"""
    lines = [line.strip() for line in str(text or "").split("\n") if line.strip()]
    target = _norm(quote)
    for index, line in enumerate(lines):
        if target and target in _norm(line):
            return line, (lines[index - 1] if index else "")
    return "", ""


def _after_correction(quote: str) -> str:
    """The part of a quote after the student corrected themselves with 不对;
    the quote unchanged when there is no correction or nothing follows it."""
    parts = _CORRECTION_RE.split(quote)
    if len(parts) < 2:
        return quote
    return parts[-1].lstrip(_LEADING_PUNCT) or quote


def _read_piece(prompt: str) -> Tuple[Optional[Dict[str, Any]], Optional[Exception]]:
    """One piece of one source: asked, and asked once more when the call fails."""
    error: Optional[Exception] = None
    for _attempt in range(2):
        try:
            return _ask(prompt, SCHEMA_SOURCE), None
        except (AnalysisError, ValueError) as exc:
            error = exc
    return None, error


def _source_text_items(auto: Dict[str, Any],
                       uploaded: List[Dict[str, Any]],
                       gender: str = "",
                       failures: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """每个文字来源按段各一次 AI 调用；quote 不存在于全文的条目直接丢弃。

    A piece that fails twice is recorded in ``failures`` and the other pieces carry
    on; only when every piece of every source fails does this raise."""
    items: List[Dict[str, Any]] = []
    attempted = 0
    failed = 0
    last_error: Optional[Exception] = None
    valid_codes = _kb_codes()
    abilities = [{"code": row.get("code"), "name": row.get("name")}
                 for row in load_kb().get("abilities") or []]
    for row in _text_sources(auto, uploaded):
        full_norm = _norm(row["text"])
        seen_quotes = set()
        index = 0
        for number, piece in enumerate(_split_pieces(row["text"]), start=1):
            payload = {
                "source_ref": row["source_ref"],
                "label": row["label"],
                "date": row["date"],
                "student_gender": gender,
                "text": piece,
                "abilities": abilities,
            }
            attempted += 1
            result, error = _read_piece(SOURCE_ITEMS_PROMPT % _json(payload))
            if result is None:
                failed += 1
                last_error = error
                if failures is not None:
                    failures.append({"label": row["label"], "piece": number})
                continue
            for raw in result.get("items") or []:
                index += 1
                if not isinstance(raw, dict):
                    continue
                quote = _clean(raw.get("quote"))
                normalised = _norm(quote)
                if not normalised or normalised not in full_norm:
                    continue
                corrected = _after_correction(quote)
                if corrected != quote:
                    quote, normalised = corrected, _norm(corrected)
                if normalised in seen_quotes:
                    continue
                seen_quotes.add(normalised)

                # Case Review 的老师发言本身就是证据，所以只在其他来源里筛
                line, previous_line = _quote_lines(row["text"], quote)
                if row["source"] != "case_review":
                    if _MENTOR_LINE_RE.match(line):
                        continue
                    if (len(normalised) <= 4
                            or (len(normalised) <= 12
                                and bool(_MENTOR_LINE_RE.match(previous_line))
                                and bool(_LEADING_RE.search(previous_line))
                                )
                            or raw.get("prompted")):
                        continue

                kind = _clean(raw.get("kind")).lower()
                hypothetical = False
                if row["source"] == "case_review":
                    independent = bool(raw.get("independent")) and _is_first_hand(quote)
                    kind = "direct" if independent else "hypothesis"
                else:
                    hypothetical = kind == "hypothetical" or bool(
                        _MENTOR_LINE_RE.match(previous_line)
                        and _HYPOTHETICAL_RE.search(previous_line)
                        and not (any(word in line for word in _PAST_EVENT_WORDS)
                                 and not _HYPOTHETICAL_RE.search(line)))
                    if hypothetical:
                        kind = "hypothetical"
                    elif kind not in _KINDS:
                        kind = "inference"
                    elif kind == "hypothesis":
                        kind = "inference"

                codes = []
                for code in raw.get("abilities") or []:
                    code = _clean(code)
                    if code in valid_codes and code not in codes:
                        codes.append(code)

                # the summary line may only say what its quote says
                text = _clean(raw.get("text"))
                if corrected != _clean(raw.get("quote")) or not text \
                        or ai_writing.lint_facts(text, quote):
                    text = quote
                if hypothetical and not text.startswith("学生设想"):
                    text = "学生设想：" + text

                items.append({
                    "id": "%s-%d" % (row["id_prefix"], index),
                    "source": row["source"],
                    "source_ref": row["source_ref"],
                    "date": row["date"],
                    "kind": kind,
                    "group": row["source_ref"],
                    "text": text,
                    "quote": quote,
                    "abilities": codes,
                    "band": "",
                    "raw": None,
                })
    if attempted and failed == attempted:
        raise last_error or AnalysisError("资料未能读取")
    return items


def _build_evidence(auto: Dict[str, Any],
                    uploaded: List[Dict[str, Any]],
                    gender: str = "",
                    failures: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
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
    items.extend(_source_text_items(auto, uploaded, gender, failures))
    for index, item in enumerate(items, start=1):
        if not item["id"]:
            item["id"] = "ev-%d" % index
    return items


_SUMMARY_SOURCES = ("first_touch", "parent", "case_review", "other")


def _summary_rows(result: Dict[str, Any], valid_ids: set) -> List[Dict[str, Any]]:
    """摘要里通过来源核查的句子，每句带上它自己依据的条目 id。"""
    rows: List[Dict[str, Any]] = []
    for raw in (result or {}).get("sentences") or []:
        if not isinstance(raw, dict):
            continue
        text = _strip_ids(raw.get("text"), {})
        cited = [item_id for item_id in _as_list(raw.get("evidence_ids"))
                 if item_id in valid_ids]
        if not text or not cited:
            continue  # a sentence without a valid source is dropped
        rows.append({"text": text, "evidence_ids": list(dict.fromkeys(cited))})
    # never cut mid-sentence: drop whole sentences from the end instead
    while len(rows) > 1 and len("".join(row["text"] for row in rows)) > _SUMMARY_LIMIT:
        rows.pop()
    return rows


def _summary_sentences(result: Dict[str, Any],
                       valid_ids: set) -> Tuple[List[str], List[str]]:
    """摘要里通过来源核查的句子，以及它们用到的条目 id。"""
    rows = _summary_rows(result, valid_ids)
    ids: List[str] = []
    for row in rows:
        ids.extend(item_id for item_id in row["evidence_ids"] if item_id not in ids)
    return [row["text"] for row in rows], ids


def _source_summaries(evidence: List[Dict[str, Any]],
                      gender: str = "") -> Dict[str, Dict[str, Any]]:
    """1.2 「会前提取信息」: 2–4 complete sentences per text source, each tied to
    its evidence ids. A source whose call fails or yields nothing valid is left
    out, and the document shows a fixed sentence instead of a text fragment."""
    summaries: Dict[str, Dict[str, Any]] = {}
    retried = 0
    for key in _SUMMARY_SOURCES:
        rows = [item for item in evidence if item.get("source") == key]
        if not rows:
            continue
        valid_ids = {item["id"] for item in rows}
        prompt = SOURCE_SUMMARY_PROMPT % (
            SOURCE_LABELS[key], _style_for(evidence, gender),
            _json([_public_item(item) for item in rows]))
        try:
            result = _ask(prompt, SCHEMA_SUMMARY)
        except Exception:
            continue
        rows = _summary_rows(result, valid_ids)
        if not rows:
            # 没有写出依据 id 时再问一次；仍然不行就用固定句
            retried += 1
            try:
                result = _ask(prompt + "\n每一句都必须在 evidence_ids 里写出依据的 id。",
                              SCHEMA_SUMMARY)
            except Exception:
                result = {}
            rows = _summary_rows(result, valid_ids)
        if rows:
            ids: List[str] = []
            for row in rows:
                ids.extend(item_id for item_id in row["evidence_ids"] if item_id not in ids)
            # the sentences keep their own evidence ids: each is checked on its own
            summaries[key] = {"text": "".join(row["text"] for row in rows),
                              "evidence_ids": ids, "sentences": rows}
    if retried:
        logger.info("来源摘要重试次数：%d", retried)
    return summaries


# ---------------------------------------------------------------------------
# B. 逐项判断
# ---------------------------------------------------------------------------
# 推荐理由由代码按证据条件生成，模型只给 reason_code
_REASON_TEXTS = {
    "impact": "现有线索显示它已影响学习、睡眠或关系，建议优先确认。",
    "both": "同时有积极线索和干扰线索，建议优先确认。",
    "conflict": "两个来源的说法不一致，建议优先确认。",
    "concern": "学生或家长提到了这方面的担心，建议优先确认。",
    "case_review": "Case Review 提出了待验证方向，建议优先确认。",
    "none": "暂未发现需要优先确认的理由。",
}
_APPENDIX_CHOSEN = "已列入本次优先能力。"
_APPENDIX_LEFT_OUT = "本次不单列，可在相关情境中顺带了解。"


def _reason_for(code: str,
                has_cites: bool,
                potential: List[str],
                interference: List[str],
                contradictions: List[str],
                groups: set,
                cited: List[Dict[str, Any]]) -> str:
    """reason_code 对应的理由；条件不成立、代码未知或缺失时都是 none。"""
    if code == "case_review":
        ok = any(item.get("source") == "case_review" for item in cited)
    elif code == "conflict":
        ok = bool(contradictions) and len(groups) >= 2
    elif code == "both":
        ok = bool(potential) and bool(interference)
    elif code in ("impact", "concern"):
        ok = bool(has_cites)
    else:
        ok = False
    return _REASON_TEXTS[code] if ok and code in _REASON_TEXTS else _REASON_TEXTS["none"]


def _conflict_sentences(raw_pairs, by_id: Dict[str, Dict[str, Any]]) -> List[str]:
    """Conflicts written by code from pairs of real evidence. The model only names
    two ids; a pair counts when both exist, differ and come from different groups."""
    sentences: List[str] = []
    if not isinstance(raw_pairs, list):
        return sentences
    for raw in raw_pairs:
        if not isinstance(raw, dict):
            continue
        first, second = by_id.get(_clean(raw.get("a"))), by_id.get(_clean(raw.get("b")))
        if not first or not second or first["id"] == second["id"] \
                or first.get("group") == second.get("group"):
            continue
        parts = []
        for item in (first, second):
            parts.append("%s：%s" % (SOURCE_LABELS.get(item.get("source"), "资料"),
                                    _clean(item.get("text")).rstrip("。；，、 ")))
        sentence = "%s；%s。" % tuple(parts)
        if sentence not in sentences:
            sentences.append(sentence)
    return sentences


def _judge_abilities(evidence: List[Dict[str, Any]],
                     gender: str = "") -> Dict[str, Dict[str, Any]]:
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
            ABILITY_PROMPT % (_style_for(evidence, gender), dimension.get("id"), _json(ability_payload),
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
            cited = [by_id[item_id] for item_id in cites]
            # 全部依据都是设想时，等于没有可引用的证据
            has_cites = bool(cites) and any(
                item.get("kind") != "hypothetical" for item in cited)
            supported = len(groups) >= 2

            potential = [strip(x) for x in _as_list(raw.get("potential"))] if has_cites else []
            interference = [strip(x) for x in _as_list(raw.get("interference"))] if has_cites else []
            contradictions = _conflict_sentences(raw.get("contradictions"), by_id) if has_cites else []
            missing = [strip(x) for x in _as_list(raw.get("missing"))]
            check_text = strip(raw.get("check_text"))
            reason = _reason_for(_clean(raw.get("reason_code")).lower(), has_cites,
                                  potential, interference, contradictions,
                                  groups, cited)

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
                      by_id: Dict[str, Dict[str, Any]],
                      gender: str = "") -> List[Dict[str, Any]]:
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
    result = _ask(PRIORITY_PROMPT % (_style_for(list(by_id.values()), gender), _json(payload),
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


def _special_text(raw: Dict[str, Any], key: str,
                  by_id: Dict[str, Dict[str, Any]]) -> Tuple[str, List[str]]:
    """The text of special.<key> without evidence ids, and the valid ids the model
    named for it (in ``<key>_ids`` or written in the text)."""
    text = _clean(raw.get(key))
    named = list(_as_list(raw.get("%s_ids" % key))) + re.findall(_ID_ALT, text)
    ids = [i for i in dict.fromkeys(named) if i in by_id]
    return _strip_ids(text, by_id), ids


def _build_plan(prep: Dict[str, Any], evidence: List[Dict[str, Any]],
                judgements: Dict[str, Dict[str, Any]],
                priority_rows: List[Dict[str, Any]],
                insufficient: List[str],
                gender: str = "") -> Dict[str, Any]:
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
        MEETING_PLAN_PROMPT % (duration, max_events, _style_for(evidence, gender),
                               _json([_public_item(item) for item in event_pool]),
                               _json(priority_payload),
                               _json([_public_item(item) for item in evidence])),
        SCHEMA_PLAN)
    valid_codes = _kb_codes()
    events: List[Dict[str, Any]] = []
    event_ids: Dict[str, List[str]] = {}
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
        event_ids[event_id] = ids
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

    # the conflict block is written by code from checked pairs of evidence only;
    # whatever the model put in special.conflict is ignored
    contradictions: List[str] = []
    for row in judgements.values():
        for text in row.get("contradictions") or []:
            if text not in contradictions:
                contradictions.append(text)
    conflict = "\n".join(contradictions[:3]) \
        or "本次资料中未见两个独立来源之间的明显矛盾。"
    special_raw = result.get("special") if isinstance(result.get("special"), dict) else {}
    # the ids the model gave are kept as the block's cites before they are stripped
    # from the text: they decide what each sentence is checked against
    context, context_ids = _special_text(special_raw, "context", by_id)
    attention, attention_ids = _special_text(special_raw, "attention", by_id)
    context = context or "信息不足，待会议中补充。"
    attention = attention or "；".join(insufficient[:3]) or "信息不足，待会议中补充。"

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
        "event_ids": event_ids,
        "special_ids": {"c2": context_ids, "c3": attention_ids},
        "raw": result,
    }


# ---------------------------------------------------------------------------
# E. 组装
# ---------------------------------------------------------------------------
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


def _summary_text(key: str, summaries: Dict[str, Dict[str, Any]],
                  rows: List[Dict[str, Any]]) -> str:
    """1.2 text for a source: the checked summary, a fixed sentence when material
    exists but no summary could be made, or the "not received" line."""
    if key in summaries:
        return summaries[key]["text"]
    if any(_clean(row.get("text")) for row in rows):
        return SUMMARY_FALLBACK
    return "尚未取得相关资料"


def _source_entries(auto: Dict[str, Any],
                    uploaded: List[Dict[str, Any]],
                    evidence: Optional[List[Dict[str, Any]]] = None,
                    summaries: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    summaries = summaries or {}
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
        "extracted": _block("src-parent", _summary_text("parent", summaries, parent)),
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
    first_touch_rows = list(first_touch_extra)
    if first_touch.get("present"):
        first_touch_rows.append({"text": first_touch.get("text")})
    entries.append({
        "key": "first_touch",
        "label": "First Touch Meeting",
        "extracted": _block("src-first-touch",
                            _summary_text("first_touch", summaries, first_touch_rows)),
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
                            _summary_text("case_review", summaries, case_review)),
        "status_text": _upload_status(case_review),
    })

    # 其他资料
    entries.append({
        "key": "other",
        "label": "其他证据",
        "extracted": _block("src-other", _summary_text("other", summaries, other)),
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
        if code in chosen:
            reason = _clean(row.get("reason"))
            shown = reason if reason and reason != _REASON_TEXTS["none"] \
                else _APPENDIX_CHOSEN
        else:
            shown = _APPENDIX_LEFT_OUT
        check = _clean(row.get("check_text")) or "尚未取得可引用的证据。"
        rows.append({
            "code": code,
            "recommend": code in chosen,
            "reason": _block("ap-r-%s" % code, shown),
            "check": _block("ap-c-%s" % code, check),
        })
    return rows


def _longest_common(first: str, second: str) -> int:
    """Length of the longest run of characters the two texts share."""
    best = 0
    previous = [0] * (len(second) + 1)
    for char in first:
        current = [0] * (len(second) + 1)
        for index, other in enumerate(second, start=1):
            if char == other:
                current[index] = previous[index - 1] + 1
                best = max(best, current[index])
        previous = current
    return best


_NOTE_OVERLAP = 6  # normalised characters an item must share with the text it is credited for


def _source_note(cites: List[str], by_id: Dict[str, Dict[str, Any]],
                 check_text: str = "") -> str:
    """（来源：A、B），按引用顺序，每种来源只出现一次。A source is listed only when a
    cited item from it shares at least ``_NOTE_OVERLAP`` characters with the text."""
    probe = report_checks.normalize(check_text)
    labels: List[str] = []
    for item_id in cites:
        item = by_id.get(item_id) or {}
        label = SOURCE_LABELS.get(item.get("source"), "")
        if not label or label in labels:
            continue
        if any(_longest_common(probe, report_checks.normalize(item.get(key))) >= _NOTE_OVERLAP
               for key in ("text", "quote")):
            labels.append(label)
    return "（来源：%s）" % "、".join(labels) if labels else ""


_SENTENCE_PIECE_RE = re.compile(r"[^。！？!?]*[。！？!?]+|[^。！？!?]+$")
_CHECK_LIMIT = 120


def _whole_sentences(text: str, limit: int = _CHECK_LIMIT) -> str:
    """As many whole sentences as fit in ``limit`` characters; never cuts inside a
    sentence (a first sentence that is longer than the limit is kept whole)."""
    kept = ""
    for match in _SENTENCE_PIECE_RE.finditer(text):
        piece = match.group(0)
        if kept and len(kept) + len(piece) > limit:
            break
        kept += piece
    return kept


def _append_source_notes(doc: Dict[str, Any],
                         judgements: Dict[str, Dict[str, Any]],
                         by_id: Dict[str, Dict[str, Any]]) -> None:
    """After the check: keep whole sentences of each 证据核验 text, then credit
    the sources it actually uses. The check prompt never sees the note."""
    for row in doc.get("appendix") or []:
        judged = judgements.get(row.get("code")) or {}
        block = row.get("check") or {}
        text = _clean(block.get("text"))
        if not text or text in _FIXED_TEXTS:
            continue
        text = _whole_sentences(text)
        note = _source_note(judged.get("cites") or [], by_id, text)
        block["text"] = block["ai_text"] = text + note


_CLOSING = "。！？!?…”\"」』）)."
# blocks written by code, or question lists that are not sentences
_NO_PUNCT_IDS = {"src-y4", "src-questionnaire", "c1"}


def _close_sentence(text: str, title: bool = False) -> str:
    text = _clean(text)
    while text and text[-1] in "，,；;、 ":
        text = text[:-1]
    if text and not title and text[-1] not in _CLOSING:
        text += "。"
    return text


def _end_blocks_properly(doc: Dict[str, Any]) -> None:
    """Every AI block ends as a sentence: no trailing ，；、 and a closing mark."""
    for block_id, block in _blocks_by_id(doc).items():
        if block.get("origin") != "ai" or block_id in _NO_PUNCT_IDS \
                or block_id.endswith("-questions") or block_id.startswith("bk-q-"):
            continue
        text = _clean(block.get("text"))
        if not text or text in _FIXED_TEXTS:
            continue
        closed = _close_sentence(text, title=block_id.endswith("-title"))
        if closed != text:
            block["text"] = block["ai_text"] = closed


def _assemble_doc(prep: Dict[str, Any], auto: Dict[str, Any],
                  uploaded: List[Dict[str, Any]], evidence: List[Dict[str, Any]],
                  judgements: Dict[str, Dict[str, Any]],
                  priority_rows: List[Dict[str, Any]],
                  plan: Dict[str, Any],
                  safety: List[Dict[str, str]],
                  insufficient: List[str],
                  summaries: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
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
        "sources": _source_entries(auto, uploaded, evidence, summaries),
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


# ---------------------------------------------------------------------------
# F. 核对事实：每段 AI 文字对照它自己的来源
# ---------------------------------------------------------------------------
_GUARD_SOURCE_LIMIT = 20000
_BAND_WORDS = ("需关注", "需特殊关注", "偏低", "明显偏低", "严重偏低", "较低", "正常",
               "较好", "良好", "偏高", "较高", "高", "中等", "低")
# fixed sentences written by code, never by the model
_FIXED_TEXTS = {"信息不足。", "信息不足，需在会议中确认。", "尚未取得可引用的证据。",
                "证据有限，待会议中确认。", "尚未取得相关资料", SUMMARY_FALLBACK,
                "现有证据不足以形成明确假设，待会议中确认。", "证据有限，需要当面确认。",
                "待会议中确认具体细节。", "信息不足，待会议中补充。",
                "本次资料中未见两个独立来源之间的明显矛盾。",
                "信息不足，正式方向待会议中与学生讨论后确定。"}
# 推荐理由与附录理由都由代码写，不送进核对
_FIXED_TEXTS |= set(_REASON_TEXTS.values()) | {_APPENDIX_CHOSEN, _APPENDIX_LEFT_OUT}


def _guard_call(prompt: str) -> Dict[str, Any]:
    """The fact check and its one rewrite go through ``_ask`` like every other call."""
    schema = SCHEMA_VERIFY if "事实核对员" in prompt else SCHEMA_REWRITE
    return _ask(prompt, schema)


class _PrepIndex:
    """``report_pipeline._evidence_context`` wants one ``TextIndex``; a prep has one
    per text source. This answers for the sources of the items being checked."""

    def __init__(self, texts: Dict[str, str], refs: List[str], cache: Dict[str, Any],
                 labels: Optional[Dict[str, str]] = None):
        """``labels`` maps a source ref to the label put before a paragraph of a
        source that is not a transcript (a parent note speaks as 家长 without saying
        so); only the code checks pass it."""
        self._indexes = []
        self._labels = []
        for ref in dict.fromkeys(refs):
            if ref in texts:
                if ref not in cache:
                    cache[ref] = report_checks.TextIndex(texts[ref])
                self._indexes.append(cache[ref])
                self._labels.append((labels or {}).get(ref, ""))

    def position(self, quote):
        for number, index in enumerate(self._indexes):
            found = index.position(quote)
            if found is not None:
                return (number, found)
        return None

    def paragraph(self, where):
        text = self._indexes[where[0]].paragraph(where[1])
        label = self._labels[where[0]]
        return "%s：%s" % (label, text) if label and text else text

    def previous(self, where):
        return self._indexes[where[0]].previous(where[1])


def _item_head(item: Dict[str, Any]) -> str:
    label = SOURCE_LABELS.get(item.get("source"), "资料")
    return ("%s %s" % (label, item.get("date") or "")).strip()


def _context_item(item: Dict[str, Any], texts: Dict[str, str]) -> Dict[str, Any]:
    """An evidence item in the shape ``_evidence_context`` reads: a quote found in a
    text source is looked up in it; anything else is its label plus its text."""
    quote = _clean(item.get("quote"))
    in_text = bool(quote) and item.get("source_ref") in texts
    return {"id": item["id"], "source": "M1" if in_text else "其他",
            "quote": quote or _clean(item.get("text")),
            "location": _item_head(item),
            "type": "假设性回应" if item.get("kind") == "hypothetical" else ""}


def _evidence_lines(items: List[Dict[str, Any]], texts: Dict[str, str],
                    cache: Optional[Dict[str, Any]] = None) -> List[str]:
    """What a sentence citing these items may be checked against: for a transcript
    item the paragraph and the one before it, for anything else the label and the
    text. Written by ``report_pipeline._evidence_context``, shared with 会后报告."""
    cache = {} if cache is None else cache
    lines: List[str] = []
    for item in items:
        adapted = _context_item(item, texts)
        index = _PrepIndex(texts, [item.get("source_ref")], cache)
        for line in report_pipeline._evidence_context([adapted], [adapted["id"]], index).split("\n"):
            if line and line not in lines:
                lines.append(line)
    return lines


def _guard_source(items: List[Dict[str, Any]], texts: Dict[str, str],
                  cache: Optional[Dict[str, Any]] = None) -> str:
    """What a text may be checked against: only the evidence it cites, each with
    the paragraph around its quote and the one before it (usually the mentor's
    question). The model's own summary lines are not included."""
    cache = {} if cache is None else cache
    parts: List[str] = []
    seen = set()
    headed = set()
    size = 0
    for item in items:
        if item.get("kind") == "hypothetical":
            parts.append("【设想：以下内容没有实际发生】")
        for line in _evidence_lines([item], texts, cache):
            if line in seen:
                continue
            key = item.get("source_ref") or _item_head(item)
            if key not in headed:
                headed.add(key)
                parts.append("【%s】" % _item_head(item))
            seen.add(line)
            parts.append(line)
            size += len(line)
        if size > _GUARD_SOURCE_LIMIT:
            break
    return "\n".join(parts)


def _blocks_by_id(value, found: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Dict[str, Any]]:
    found = {} if found is None else found
    if isinstance(value, dict):
        if isinstance(value.get("id"), str) and isinstance(value.get("text"), str):
            found.setdefault(value["id"], value)
        for key, child in value.items():
            if key != "fact_flags":
                _blocks_by_id(child, found)
    elif isinstance(value, list):
        for child in value:
            _blocks_by_id(child, found)
    return found


def _summary_blocks(doc: Dict[str, Any],
                    summaries: Dict[str, Dict[str, Any]]) -> List[Tuple[Dict[str, Any], str, List[Dict[str, Any]]]]:
    """1.2 summaries whose sentences each carry their own evidence ids:
    ``(block, source key, sentences)``. A summary the mentor or the guard has since
    changed, so that it no longer reads as those sentences, is not split."""
    found = []
    for entry in doc.get("sources") or []:
        key = entry.get("key")
        block = entry.get("extracted") or {}
        rows = (summaries.get(key) or {}).get("sentences") or []
        if rows and _clean(block.get("text")) == "".join(row["text"] for row in rows):
            found.append((block, key, rows))
    return found


def _guard_inputs(doc: Dict[str, Any], evidence: List[Dict[str, Any]],
                  judgements: Dict[str, Dict[str, Any]], plan: Dict[str, Any],
                  texts: Dict[str, str],
                  summaries: Dict[str, Dict[str, Any]],
                  fixed: Optional[set] = None) -> List[Dict[str, str]]:
    """Every block the model wrote that states facts, with the evidence it cites
    and nothing else. A 1.2 summary becomes one block per sentence, each with the
    evidence of that sentence (ids ``<block>#<n>``). Blocks that only say what to
    find out (``w-*``, ``ev*-gap``, ``g-*``, ``bk-*``) are not fact-checked."""
    fixed = _FIXED_TEXTS | (fixed or set())
    by_id = {item["id"]: item for item in evidence}
    dim_of = {str(row.get("code")): str(row.get("dim"))
              for row in load_kb().get("abilities") or []}
    cache: Dict[str, Any] = {}

    def source_of(ids) -> str:
        return _guard_source([by_id[i] for i in ids if i in by_id], texts, cache)

    blocks: List[Dict[str, str]] = []

    def add(block, source: str, block_id: Optional[str] = None) -> None:
        text = _clean((block or {}).get("text"))
        if text and text not in fixed and source.strip():
            blocks.append({"id": block_id or block["id"], "text": text, "source": source})

    split = set()
    for block, _key, rows in _summary_blocks(doc, summaries):
        for number, row in enumerate(rows):
            add({"text": row["text"]}, source_of(row["evidence_ids"]),
                "%s#%d" % (block["id"], number))
        split.add(block["id"])
    for entry in doc.get("sources") or []:
        block = entry.get("extracted") or {}
        if entry.get("key") in summaries and block.get("id") not in split:
            add(block, _guard_source(
                [item for item in evidence if item.get("source") == entry["key"]],
                texts, cache))

    for row in doc.get("dims") or []:
        cites: List[str] = []
        for code, judged in judgements.items():
            if dim_of.get(code) == str(row.get("dim")):
                cites.extend(i for i in judged.get("cites") or [] if i not in cites)
        if cites:
            source = source_of(cites)
            add(row.get("potential"), source)
            add(row.get("interference"), source)

    for row in doc.get("appendix") or []:
        judged = judgements.get(row.get("code")) or {}
        if judged.get("cites"):
            source = source_of(judged["cites"])
            add(row.get("reason"), source)
            add(row.get("check"), source)

    for row in doc.get("priority") or []:
        judged = judgements.get(row.get("code")) or {}
        if judged.get("cites"):
            add(row.get("hypothesis"), source_of(judged["cites"]))

    for event in doc.get("events") or []:
        ids = (plan.get("event_ids") or {}).get(event.get("id")) or []
        if ids:
            add(event.get("title"), source_of(ids))

    # "conflict" (c1) is written by code from checked evidence and is not sent to the guard
    # c2/c3 are checked against the evidence the model named for them, and against
    # nothing when it named none, so a factual sentence is flagged, not passed
    for key, short in (("context", "c2"), ("attention", "c3")):
        ids = (plan.get("special_ids") or {}).get(short) or []
        add((doc.get("special") or {}).get(key),
            source_of(ids) if ids else report_pipeline.NO_SOURCE)
    return blocks


# 常 as a frequency: 时常、常常, or 常 before a verb-like character. 正常、日常、异常、
# 非常、平常、通常、常规、常见 can never match: they are excluded by the character before
# 常 or are not followed by one of these characters.
_OFTEN_RE = re.compile(r"时常|常常|(?<![正日异非平通])常(?=[写因会在到持选至])")
_HEDGE_WORDS = ("有时", "有一次", "偶尔")
_FREQUENCY_WORDS = ("经常", "总是", "一直", "每天", "每次", "每周", "天天", "往往", "常常", "时常")
# strong emotion and clinical words: only when the cited evidence uses them
_STRONG_WORDS = ("愤怒", "情绪激动", "暴躁", "崩溃", "灾难化", "情绪耗竭", "回避型", "完美主义")


def _word_flags(text: str, ctx: str) -> List[Tuple[str, str]]:
    """Words a sentence uses that its own evidence does not: ``(kind, problem)``."""
    found: List[Tuple[str, str]] = []
    if _OFTEN_RE.search(text):
        if any(word in ctx for word in _HEDGE_WORDS):
            found.append(("intensity", "资料说的是“有时”或“有一次”，这里写成了常态"))
        elif not any(word in ctx for word in _FREQUENCY_WORDS) \
                and not _OFTEN_RE.search(ctx):
            found.append(("intensity", "资料里没有表示经常的说法，这里写成了常态"))
    for word in _STRONG_WORDS:
        if word in text and word not in ctx:
            found.append(("label", "资料里没有“%s”这个说法" % word))
    return found


_HEDGED_QUOTE_WORDS = ("有时", "有一次", "偶尔", "不太多")
_HEDGE_KEPT_WORDS = ("有时", "有一次", "偶尔", "曾", "一次", "不太多")
_PARAPHRASE_RUN = 6


def _dropped_hedge(text: str, items: List[Dict[str, Any]]) -> bool:
    """A sentence that restates a hedged quote (it shares a run of at least
    ``_PARAPHRASE_RUN`` characters with it) but keeps none of the hedge words. The
    shared hedge rule only fires when every cited quote is hedged."""
    if any(word in text for word in _HEDGE_KEPT_WORDS):
        return False
    probe = report_checks.normalize(text)
    for item in items:
        quote = _clean(item.get("quote"))
        if quote and any(word in quote for word in _HEDGED_QUOTE_WORDS) \
                and _longest_common(probe, report_checks.normalize(quote)) >= _PARAPHRASE_RUN:
            return True
    return False


def _check_units(doc: Dict[str, Any], judgements: Dict[str, Dict[str, Any]],
                 plan: Dict[str, Any],
                 summaries: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every shown sentence that has cites, with the evidence ids it must be checked
    against: 1.2 sentences, each p-/i- segment, h-, the appendix check cells, the
    first sentence of w-, and c2/c3."""
    units: List[Dict[str, Any]] = []

    def add(block_id: str, text: str, ids) -> None:
        text = _clean(text)
        if text and text not in _FIXED_TEXTS and ids:
            units.append({"block_id": block_id, "text": text, "ids": list(ids)})

    for block, _key, rows in _summary_blocks(doc, summaries):
        for row in rows:
            add(block["id"], row["text"], row["evidence_ids"])
    for row in doc.get("dims") or []:
        for field in ("potential", "interference"):
            block = row.get(field) or {}
            code = ""
            for segment in _clean(block.get("text")).split("；"):
                match = re.match(r"(R\d\.\d)\s+", segment)
                if match:
                    code, segment = match.group(1), segment[match.end():]
                add(block.get("id"), segment, (judgements.get(code) or {}).get("cites"))
    for row in doc.get("priority") or []:
        cites = (judgements.get(row.get("code")) or {}).get("cites")
        add((row.get("hypothesis") or {}).get("id"), (row.get("hypothesis") or {}).get("text"), cites)
        first = _SENTENCE_PIECE_RE.match(_clean((row.get("why") or {}).get("text")))
        if first:
            add((row.get("why") or {}).get("id"), first.group(0), cites)
    for row in doc.get("appendix") or []:
        block = row.get("check") or {}
        add(block.get("id"), block.get("text"),
            (judgements.get(row.get("code")) or {}).get("cites"))
    ids_of = plan.get("special_ids") or {}
    for key, short in (("context", "c2"), ("attention", "c3")):
        block = (doc.get("special") or {}).get(key) or {}
        add(block.get("id"), block.get("text"), ids_of.get(short))
    return units


def _sentence_code_flags(doc: Dict[str, Any], evidence: List[Dict[str, Any]],
                         texts: Dict[str, str],
                         summaries: Dict[str, Dict[str, Any]],
                         judgements: Optional[Dict[str, Dict[str, Any]]] = None,
                         plan: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Code checks on each shown sentence and its own evidence, before the model
    check: the same rules 会后报告 applies (``report_pipeline._sentence_checks``),
    plus the words in ``_word_flags``."""
    by_id = {item["id"]: item for item in evidence}
    labels = {item.get("source_ref"): SOURCE_LABELS.get(item.get("source"), "")
              for item in evidence if item.get("source") != "first_touch"}
    cache: Dict[str, Any] = {}
    found: List[Dict[str, Any]] = []
    for unit in _check_units(doc, judgements or {}, plan or {}, summaries):
        items = [by_id[i] for i in unit["ids"] if i in by_id]
        if not items:
            continue
        index = _PrepIndex(texts, [item.get("source_ref") for item in items], cache, labels)
        dims = {"x": {"abilities": {unit["block_id"]: {"meeting": {
            "sentences": [{"text": unit["text"], "evidence_ids": [i["id"] for i in items]}]}}}}}
        state: Dict[str, Any] = {"flags": []}
        report_pipeline._sentence_checks(
            dims, [_context_item(item, texts) for item in items], index, state)
        for flag in state["flags"]:
            found.append({"block_id": unit["block_id"], "sentence": flag["sentence"],
                          "kind": flag["kind"], "problem": flag["problem"],
                          "source_excerpt": flag["source_excerpt"]})
        ctx = "\n".join(_evidence_lines(items, texts, cache))
        if _dropped_hedge(unit["text"], items):
            found.append({"block_id": unit["block_id"], "sentence": unit["text"],
                          "kind": "intensity",
                          "problem": "资料说的是“有时”或“有一次”，这里写成了常态",
                          "source_excerpt": ctx[:200]})
        for kind, problem in _word_flags(unit["text"], ctx):
            found.append({"block_id": unit["block_id"], "sentence": unit["text"],
                          "kind": kind, "problem": problem, "source_excerpt": ctx[:200]})
    unique, seen = [], set()
    for flag in found:
        key = (flag["block_id"], flag["sentence"], flag["kind"], flag["problem"])
        if key not in seen:
            seen.add(key)
            unique.append(flag)
    return unique


def _fact_check(doc: Dict[str, Any], evidence: List[Dict[str, Any]],
                judgements: Dict[str, Dict[str, Any]], plan: Dict[str, Any],
                texts: Dict[str, str], summaries: Dict[str, Dict[str, Any]],
                gender: str, insufficient: Optional[List[str]] = None) -> None:
    """Check every AI text against its source, keep the guard's final text, and
    store what still fails as ``doc["fact_flags"]``. Never raises: a check that
    could not run is itself flagged, so it cannot look like a pass."""
    ignore = list(SOURCE_LABELS.values()) + ["Y4", "First Touch", "Case Review"] \
        + list(_BAND_WORDS) + [_clean(item.get("band")) for item in evidence
                               if _clean(item.get("band"))]
    summary_rows = {block["id"]: (key, rows)
                    for block, key, rows in _summary_blocks(doc, summaries)}
    try:
        # the "attention" fallback is the code-written list of missing sources
        blocks = _guard_inputs(doc, evidence, judgements, plan, texts, summaries,
                               {"；".join((insufficient or [])[:3])})
        result = ai_writing.run_guard(blocks, call=_guard_call,
                                      budget_seconds=_GUARD_BUDGET_SECONDS,
                                      gender=gender, ignore=ignore)
    except Exception:
        blocks, result = [], {"blocks": {}, "flags": [], "status": "skipped"}

    holders = _blocks_by_id(doc)
    parts: Dict[str, Dict[int, str]] = {}
    for block_id, text in (result.get("blocks") or {}).items():
        if "#" in block_id:  # one sentence of a summary
            base, _sep, number = block_id.rpartition("#")
            if base in holders and number.isdigit():
                parts.setdefault(base, {})[int(number)] = text
            continue
        holder = holders.get(block_id)
        if holder is not None and text and _clean(text) != _clean(holder.get("text")):
            holder["text"] = holder["ai_text"] = _clean(text)
    final_summaries = copy.deepcopy(summaries)
    for base, pieces in parts.items():
        joined = "".join(_clean(pieces[number]) for number in sorted(pieces))
        holder = holders[base]
        if joined and joined != _clean(holder.get("text")):
            holder["text"] = holder["ai_text"] = joined
        if base in summary_rows:  # the sentences as the guard left them
            key, rows = summary_rows[base]
            final_summaries[key]["sentences"] = [
                dict(row, text=_clean(pieces.get(number, row["text"])))
                for number, row in enumerate(rows)]

    # the code checks are deterministic, so they run on the text the guard and its
    # rewrites left, not on the draft: a rewrite can drop 有时候 or add a new error
    code_ok = True
    try:
        code_flags = _sentence_code_flags(doc, evidence, texts, final_summaries,
                                          judgements, plan)
    except Exception:
        code_flags, code_ok = [], False

    rows = [dict(flag) for flag in code_flags]
    for flag in result.get("flags") or []:
        rows.append({"block_id": (flag.get("id") or "").rpartition("#")[0]
                     if "#" in (flag.get("id") or "") else flag.get("id") or "",
                     "sentence": flag.get("sentence") or "", "kind": flag.get("kind") or "",
                     "problem": flag.get("problem") or "",
                     "source_excerpt": flag.get("source_excerpt") or ""})
    fact_flags: List[Dict[str, Any]] = []
    for number, flag in enumerate(rows, start=1):
        holder = holders.get(flag["block_id"]) or {}
        fact_flags.append({
            "id": "ff%d" % number,
            "block_id": flag["block_id"],
            "sentence": flag["sentence"],
            "kind": flag["kind"],
            "problem": flag["problem"],
            "source_excerpt": flag["source_excerpt"],
            "block_text": _clean(holder.get("text")),
            "acked": False,
        })
    if result.get("status") != "checked" or not code_ok:
        fact_flags.append({
            "id": "ff-doc", "block_id": "", "sentence": UNCHECKED_FLAG_TEXT,
            "kind": "unchecked", "problem": UNCHECKED_FLAG_TEXT,
            "source_excerpt": "", "block_text": "", "acked": False,
        })
    doc["fact_flags"] = fact_flags


def _add_read_failure_flags(doc: Dict[str, Any],
                            failures: List[Dict[str, Any]]) -> None:
    """One document-level flag for each piece of a source that could not be read.
    It has no block, so only an acknowledgement closes it."""
    flags = doc.setdefault("fact_flags", [])
    for number, failure in enumerate(failures, start=1):
        text = "资料「%s」第 %d 段未能读取，请人工查看原文。" % (
            failure.get("label"), failure.get("piece"))
        flags.append({
            "id": "ff-read%d" % number, "block_id": "", "sentence": text,
            "kind": "unread", "problem": text, "source_excerpt": "",
            "block_text": "", "acked": False,
        })


def _sync_flag_texts(doc: Dict[str, Any]) -> None:
    """A flag remembers the text of its block when it was raised; a block whose text
    differs counts as edited, which closes the flag. Whatever the pipeline does to a
    block after the check, the remembered text must be the final one, or every flag
    would close the moment the document is opened."""
    holders = _blocks_by_id(doc)
    for flag in doc.get("fact_flags") or []:
        holder = holders.get(flag.get("block_id"))
        if holder is not None:
            flag["block_text"] = _clean(holder.get("text"))


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
    gender = _student_gender(prep["student_id"])
    texts = {row["source_ref"]: row["text"] for row in _text_sources(auto, uploaded)}

    safety = run("safety", lambda: _scan_safety(auto, uploaded))

    failures: List[Dict[str, Any]] = []

    def evidence_stage():
        rows = _build_evidence(auto, uploaded, gender, failures)
        return rows, _source_summaries(rows, gender)

    evidence, summaries = run("evidence", evidence_stage)
    judgements = run("abilities", lambda: _judge_abilities(evidence, gender))
    by_id = {item["id"]: item for item in evidence}

    def priority_stage():
        chosen = _choose_priorities(judgements, by_id)
        return chosen, _write_priorities(chosen, judgements, by_id, gender)

    _chosen, priority_rows = run("priority", priority_stage)
    insufficient = _insufficient(auto, uploaded)
    plan = run("plan", lambda: _build_plan(prep, evidence, judgements,
                                           priority_rows, insufficient, gender))

    def verify():
        doc = _assemble_doc(prep, auto, uploaded, evidence, judgements,
                            priority_rows, plan, safety, insufficient, summaries)
        # drop leaked Y4 scores first, so a flag is never closed by this later cleanup
        redact_raw_numbers(doc, evidence)
        _fact_check(doc, evidence, judgements, plan, texts, summaries, gender,
                    insufficient)
        _add_read_failure_flags(doc, failures)
        # 句子取整、来源标注都在核对之后做，核对提示词里看不到它们
        _end_blocks_properly(doc)
        _append_source_notes(doc, judgements, by_id)
        return doc

    doc = run("verify", verify)

    def assemble():
        # the model sometimes repeats a Y4 score next to its indicator; drop it
        # rather than failing a multi-minute generation (owner rule: bands only)
        redact_raw_numbers(doc, evidence)
        # fact_flags quote the source on purpose, so they are not scanned for placeholders
        validate_doc({key: value for key, value in doc.items() if key != "fact_flags"},
                     evidence)
        _sync_flag_texts(doc)
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
