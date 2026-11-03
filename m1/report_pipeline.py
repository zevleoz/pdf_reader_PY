"""会后报告生成管道：每步一个函数，可单独改动（协议 §3）。

AI 只负责证据提取、能力分析和综合画像；Y4 评级、引文核验、标签规则、
附录和质量检查全部由代码完成。测试替换本模块的 ``call_model``。

日志只记录数量和 id，不记录逐字稿、引文或生成的报告文字。
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

import ai_writing
from growth_talk.analysis import AnalysisError, call_model

import m1.sources as sources
import m1.store as store
from m1 import (report_assessment, report_checks, report_display, report_kb,
                report_prompts, report_store, report_y4)
from m1 import speakers
from m1 import y4_evidence
from m1.kb import load_kb
from m1.prompts import SAFETY_CHECK_PROMPT, SAFETY_KEYWORDS

log = logging.getLogger(__name__)

STEP_DEFS = (
    ("check", "资料检查"),
    ("speakers", "发言人识别"),
    ("y4", "Y4 标准化"),
    ("mapping", "R4 Mapping"),
    ("first_touch", "First Touch 分析"),
    ("safety", "安全检查"),
    ("meeting", "会议分析"),
    ("dims", "四维分析"),
    ("profile", "综合画像与方案"),
    ("checks", "质量检查"),
)

CHUNK_LIMIT = 6000
CHUNK_OVERLAP = 400
WORKERS = 4
NO_CLUES = "暂无直接相关资料。"
NO_MEETING = report_checks.NO_MEETING_TEXT
NO_SOURCE = "（没有对应证据）"
_CLOSING = "。！？!?…：:；;”\"」』）)"

ProgressCallback = Callable[[str, str, float], None]


class ReportError(Exception):
    """可直接显示给用户的生成错误。"""


def _field(text: str = "", src: str = "ai") -> Dict[str, str]:
    return {"text": _readable(text), "src": src}


def _clean(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _ask(prompt: str) -> Dict[str, Any]:
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


def _parallel(fn, jobs: List[Any]) -> List[Any]:
    if not jobs:
        return []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(fn, jobs))


def _readable(text: Any) -> str:
    """去掉句尾的逗号、分号、顿号；没有句末标点就补句号。"""
    value = _clean(text)
    while value and value[-1] in "，；、":
        value = value[:-1].rstrip()
    if value and value[-1] not in _CLOSING:
        value += "。"
    return value


def _sentence_with(text: str, value: str) -> str:
    probe = report_checks.normalize(value)
    for piece in report_checks.split_paragraphs(text.replace("。", "\n")):
        if probe and probe in report_checks.normalize(piece):
            return piece
    parts = [p for p in text.replace("。", "。\n").splitlines() if p.strip()]
    return parts[0].strip() if parts else text.strip()


def _student_gender(student_id) -> str:
    """学生档案里的性别；取不到时返回空字符串（仍会检查“他”“她”）。"""
    try:
        import db as _db
        with _db.Session(_db.engine) as sess:
            row = sess.get(_db.Student, int(student_id))
            if row is not None:
                return _clean(getattr(row, "gender", ""))
    except Exception:
        return ""
    return ""


# ---------------------------------------------------------------------------
# 01 资料检查
# ---------------------------------------------------------------------------
def step_check(prep: Dict[str, Any], report: Dict[str, Any], today: Optional[date] = None) -> Dict[str, Any]:
    from growth_talk import y4_snapshot

    if not (report.get("transcript_text") or "").strip():
        raise ReportError("还没有 M1 会议逐字稿，请先粘贴或上传逐字稿")
    y4_report = y4_snapshot.latest_complete_y4(prep["student_id"])
    if y4_report is None:
        raise ReportError("该学生还没有完整的 Y4 测评，无法生成报告")

    auto = sources.auto_sources(prep["student_id"])
    uploads = store.list_sources(prep["id"])
    first_touch = auto.get("first_touch") or {}
    y4_date = getattr(y4_report, "report_date", None)
    y4_date = y4_date.isoformat() if hasattr(y4_date, "isoformat") else _clean(str(y4_date or ""))
    transcript = report["transcript_text"]
    meeting_date = (_clean(prep.get("meeting_date"))
                    or sources.suggested_meeting_date(transcript))

    labels = ["Y4 测评", "M1 First Meeting 逐字稿"]
    if first_touch.get("present") and _clean(first_touch.get("text")):
        labels.append("First Touch")
    if any(q.get("status") == "已完成" for q in auto.get("questionnaires") or []):
        labels.append("补充问卷")
    if uploads:
        labels.append("其他补充资料")
    meta = {
        "student_name": _clean(prep.get("student_name")),
        "grade": _clean(prep.get("grade")),
        "school": _clean(prep.get("school")),
        "y4_date": y4_date,
        "meeting_date": meeting_date,
        "report_date": (today or date.today()).isoformat(),
        "evidence_sources": "Y4 测评",
    }
    return {
        "meta": meta,
        "values": y4_evidence._values(y4_report),
        "auto": auto,
        "uploads": uploads,
        "first_touch_text": _clean(first_touch.get("text")) if first_touch.get("present") else "",
        "first_touch_date": _clean(first_touch.get("date")),
        "source_labels": labels,
    }


# ---------------------------------------------------------------------------
# 02/03 Y4 与 Mapping
# ---------------------------------------------------------------------------
def step_y4(values: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return report_y4.rate_all(values)


def step_mapping(ratings: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """每项能力：指标、已评级的行、证据缺口、补充方向和会议问题。"""
    out = {}
    for code, info in report_kb.ability_map().items():
        out[code] = {
            "indicators": list(info["indicators"]),
            "lines": [ratings[c] for c in info["indicators"] if c in ratings],
            "gap_note": info["gap_note"], "supplement": info["supplement"],
            "ask": info["ask"],
        }
    return out


# ---------------------------------------------------------------------------
# 证据提取（会议 / First Touch / 其他）
# ---------------------------------------------------------------------------
def make_chunks(paragraphs: List[str], limit: int = CHUNK_LIMIT,
                overlap: int = CHUNK_OVERLAP) -> List[str]:
    """按段落切块，每块不超过 ``limit`` 字，相邻块重叠不超过 ``overlap`` 字。"""
    pieces: List[str] = []
    for paragraph in paragraphs:
        while len(paragraph) > limit:
            pieces.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        if paragraph:
            pieces.append(paragraph)
    chunks: List[str] = []
    current: List[str] = []
    size = 0
    for piece in pieces:
        if current and size + len(piece) + 1 > limit:
            chunks.append("\n".join(current))
            keep: List[str] = []
            total = 0
            for old in reversed(current):
                if total + len(old) + 1 > overlap:
                    break
                keep.insert(0, old)
                total += len(old) + 1
            if total + len(piece) + 1 > limit:
                keep, total = [], 0
            current, size = keep, total
        current.append(piece)
        size += len(piece) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _ability_brief(codes: Optional[List[str]] = None) -> List[Dict[str, str]]:
    return [{"code": code, "name": info["name"], "description": info["description"],
             "gap_note": info["gap_note"], "supplement": info["supplement"],
             "ask": info["ask"]}
            for code, info in report_kb.ability_map().items()
            if codes is None or code in codes]


def _normalise_items(raw_items, valid_codes) -> List[Dict[str, Any]]:
    out = []
    for raw in raw_items or []:
        if not isinstance(raw, dict):
            continue
        quote = report_checks.strip_marks(raw.get("quote"))
        codes = []
        for code in raw.get("ability_codes") or []:
            if isinstance(code, str) and code in valid_codes and code not in codes:
                codes.append(code)
        if not quote or not codes:
            continue
        speaker = _clean(raw.get("speaker"))
        kind = _clean(raw.get("type"))
        out.append({
            "ability_codes": codes,
            "speaker": speaker if speaker in report_checks.SPEAKERS else "待确认",
            "type": kind if kind in report_checks.EVIDENCE_TYPES else "其他观察",
            "quote": quote,
            "interpretation": _clean(raw.get("interpretation")),
            "limits": _clean(raw.get("limits")),
            "event_key": _clean(raw.get("event_key")),
        })
    return out


_M1_LEAD_TOKENS = ("是不是", "对不对", "是吗", "吧？")
_M1_HYPOTHETICAL_TOKENS = ("如果", "假如", "要是", "万一", "下次")
_M1_REALITY_TOKENS = ("上个月", "上周", "上次", "那次", "有一次", "当时", "之前",
                      "昨天", "去年", "上学期")


def _m1_rules(item: Dict[str, Any], index: report_checks.TextIndex) -> bool:
    """S2-P6 §11 的四条证据过滤规则；返回 True 表示丢弃。"""
    quote = item["quote"]
    if "不对" in quote:
        after = quote.split("不对", 1)[1].lstrip("，,。.、：:；;！!？? \t")
        if after:
            item["quote"] = after
    where = index.position(item["quote"])
    if where is None:
        return False
    paragraph = index.paragraph(where)
    previous = index.previous(where)
    if report_checks.is_mentor_line(paragraph):
        return True
    norm = report_checks.normalize(item["quote"])
    if len(norm) <= 4:
        return True
    if (len(norm) <= 12 and report_checks.is_mentor_line(previous)
            and any(token in previous for token in _M1_LEAD_TOKENS)):
        return True
    if (report_checks.is_mentor_line(previous)
            and any(token in previous for token in _M1_HYPOTHETICAL_TOKENS)
            and not any(token in paragraph for token in _M1_REALITY_TOKENS)):
        item["type"] = "假设性回应"
    return False


_SENTENCE_END_RE = re.compile(r"(?<=[。？！?!])")


def _ellipsis_ok(quote: str, paragraph: str) -> bool:
    """带省略号的引文只有在原段落也有同样的省略号时才算原文。"""
    return all(mark not in quote or mark in paragraph for mark in ("……", "..."))


def _drop_mentor_lead(item: Dict[str, Any], index: report_checks.TextIndex) -> bool:
    """引文开头若是导师的句子，去掉；返回 False 表示整条只剩导师的话，应丢弃。"""
    if index.locate(item["quote"]) is not None:
        return True
    mentor_norms = [norm for paragraph, norm in zip(index.paragraphs, index.norms)
                    if report_checks.is_mentor_line(paragraph)]
    pieces = [p for p in _SENTENCE_END_RE.split(item["quote"]) if p]
    while pieces:
        probe = report_checks.normalize(pieces[0])
        if probe and any(probe in norm for norm in mentor_norms):
            pieces.pop(0)
        else:
            break
    rest = "".join(pieces).strip()
    if not rest:
        return False
    item["quote"] = rest
    return True


def _merge_overlaps(merged: Dict[str, Dict[str, Any]]) -> None:
    """（同一份资料里）同一发言人，短引文包含在长引文里时合并到长的一条。"""
    keys = sorted(merged, key=len, reverse=True)
    for i, short in enumerate(keys):
        for long in keys[:i]:
            if long not in merged or short not in merged or long == short:
                continue
            a, b = merged[long], merged[short]
            if a["speaker"] == b["speaker"] and short in long:
                for code in b["ability_codes"]:
                    if code not in a["ability_codes"]:
                        a["ability_codes"].append(code)
                del merged[short]
                break


_SPEAKER_LABEL_RE = re.compile(
    r"^\W*(?:\d{1,2}:\d{2}(?::\d{2})?\W*)?"
    r"(?:学生|导师|老师|家长|妈妈|爸爸|其他|待确认)(?:\s*\[[^\]]*\])?\s*[：:]\s*")


def extract_items(text: str, template: str, template_args: tuple, source: str,
                  label: str, failures: Optional[List[int]] = None,
                  roles: Optional[Callable[[str], str]] = None) -> List[Dict[str, Any]]:
    """一份资料 → 已核验、去重的证据条目（还没有 id）。

    每个资料块、每个维度各调用一次；同一引文跨块、跨维度合并。
    """
    index = report_checks.TextIndex(text)
    chunks = make_chunks(index.paragraphs)
    if not chunks:
        return []
    dims = []
    for dim_id in report_kb.dim_ids():
        codes = [code for code, info in report_kb.ability_map().items()
                 if info["dim"] == dim_id]
        dims.append((dim_id, codes, _json(_ability_brief(codes))))

    def run(job):
        number, chunk, _dim_id, codes, brief = job
        error = None
        for _attempt in range(2):
            try:
                result = _ask(template % (tuple(template_args) + (brief, chunk)))
                return number, _normalise_items(result.get("items"), codes), None
            except AnalysisError as exc:
                error = exc
        return number, [], error

    jobs = [(number, chunk, dim_id, codes, brief)
            for number, chunk in enumerate(chunks, 1)
            for dim_id, codes, brief in dims]
    failed: Dict[int, AnalysisError] = {}
    failed_counts: Counter = Counter()
    merged: Dict[str, Dict[str, Any]] = {}
    for number, items, error in _parallel(run, jobs):
        if error is not None:
            failed.setdefault(number, error)
            failed_counts[number] += 1
            continue
        for item in items:
            stripped = _SPEAKER_LABEL_RE.sub("", item["quote"], count=1).strip()
            if not stripped:
                continue
            item["quote"] = stripped
            if source == "M1":
                item["speaker"] = "待确认"     # 发言人只由逐字稿段首决定，提取模型不猜
                if not _drop_mentor_lead(item, index):
                    continue
                if _m1_rules(item, index):
                    continue
                if roles is not None:
                    item["speaker"] = roles(item["quote"])
            key = report_checks.normalize(item["quote"]) or item["quote"]
            if key in merged:                      # 重叠部分或跨维度的重复项
                for code in item["ability_codes"]:
                    if code not in merged[key]["ability_codes"]:
                        merged[key]["ability_codes"].append(code)
                if item["speaker"] != merged[key]["speaker"]:
                    merged[key]["speaker"] = "待确认"
                continue
            merged[key] = item
    _merge_overlaps(merged)
    if failures is not None:
        failures.extend(sorted(failed))
    if failed and all(failed_counts[number] >= len(dims)
                      for number in range(1, len(chunks) + 1)):
        raise failed[next(iter(failed))]
    out = []
    for item in merged.values():
        where = index.locate(item["quote"])
        quote = item["quote"]
        item["quote_verified"] = (where is not None
                                  and _ellipsis_ok(quote, index.paragraph(where[0] - 1)))
        item["source"] = source
        if where is None:
            item["location"] = ""
        elif source == "M1":
            number, mark = where
            item["location"] = "逐字稿第 %d 段%s" % (number, "（%s）" % mark if mark else "")
        else:
            item["location"] = label
        item["_order"] = where[0] if where else 10 ** 9
        if source == "M1" and where is None:
            item["status"] = "不采用"      # 找不到原文的引文自动弃用，保留追溯记录
        else:
            item["status"] = ("待核实" if source != "M1" or item["speaker"] == "待确认"
                              or not item["quote_verified"] else "已确认")
        if (source == "M1" and item["speaker"] in ("学生", "家长")
                and item["quote_verified"]
                and report_checks.mentor_labelled(index, item["quote"])):
            item["speaker"] = "待确认"
            item["limits"] = "；".join(x for x in (item.get("limits"), "逐字稿标注为导师") if x)
            item["status"] = "待核实"
        out.append(item)
    out.sort(key=lambda i: i["_order"])
    for item in out:
        item.pop("_order", None)
    return out


def step_first_touch(ctx: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """First Touch 与其他资料；一份都没有时返回 None（跳过，不算资料缺口）。"""
    groups = []
    if ctx["first_touch_text"]:
        groups.append(("FT", "First Touch", ctx["first_touch_text"], "First Touch 记录"))
    for questionnaire in ctx["auto"].get("questionnaires") or []:
        if questionnaire.get("status") != "已完成":
            continue
        lines = []
        for answers in (questionnaire.get("by_dimension") or {}).values():
            for answer in answers:
                lines.append("%s：%s" % (_clean(answer.get("question")), _clean(answer.get("answer"))))
        if lines:
            title = _clean(questionnaire.get("title")) or _clean(questionnaire.get("code"))
            groups.append(("OTHER", "补充问卷：%s" % title if title else "补充问卷",
                           "\n".join(lines), "补充问卷"))
    for upload in ctx["uploads"]:
        if _clean(upload.get("text")):
            name = _clean(upload.get("label")) or _clean(upload.get("filename")) or "资料"
            groups.append(("OTHER", "其他资料：%s" % name, upload["text"], "其他补充资料"))
    if not groups:
        return None
    items: List[Dict[str, Any]] = []
    for source, label, text, kind in groups:
        items.extend(extract_items(text, report_prompts.FIRST_TOUCH_PROMPT, (kind,),
                                   source, label))
    return items


# ---------------------------------------------------------------------------
# 安全检查
# ---------------------------------------------------------------------------
def step_safety(transcript: str) -> List[Dict[str, str]]:
    hits = []
    seen = set()
    for number, paragraph in enumerate(report_checks.split_paragraphs(transcript), 1):
        for keyword in SAFETY_KEYWORDS:
            at = paragraph.find(keyword)
            if at < 0:
                continue
            snippet = " ".join(paragraph[max(0, at - 40):at + len(keyword) + 40].split())
            key = (number, snippet)
            if key in seen:
                continue
            seen.add(key)
            hits.append({"source_ref": "逐字稿第 %d 段" % number, "text": snippet})
    if not hits:
        return []
    result = _ask(SAFETY_CHECK_PROMPT % _json(hits[:8]))
    if not result.get("confirmed"):
        return []
    confirmed = []
    for item in result.get("items") or []:
        if isinstance(item, dict) and _clean(item.get("text")):
            confirmed.append({"text": _clean(item["text"]),
                              "source_ref": _clean(item.get("source_ref"))})
    return confirmed or hits


# ---------------------------------------------------------------------------
# 会议分析
# ---------------------------------------------------------------------------
def step_meeting(transcript: str,
                 failures: Optional[List[int]] = None,
                 roles=None) -> List[Dict[str, Any]]:
    return extract_items(transcript, report_prompts.MEETING_PROMPT, (), "M1", "逐字稿",
                         failures=failures, roles=roles)


def _event_id(source: str, key: str) -> str:
    digest = hashlib.sha1(("%s\0%s" % (source, key)).encode("utf-8")).hexdigest()
    return "evt-" + digest[:12]


def assign_ids(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """证据编号 + 事件编号；event_key 跨引文共享 event_id，来源不同不合并。"""
    out = []
    for number, item in enumerate(items, 1):
        key = report_checks.normalize(item.get("event_key") or "")
        if not key:
            key = report_checks.normalize(item.get("location") or item.get("quote") or "")
        row = {"id": "e%d" % number,
               "event_id": _event_id(item.get("source") or "", key)}
        for field in ("ability_codes", "source", "location", "speaker", "type", "quote",
                      "quote_verified", "interpretation", "limits", "status"):
            row[field] = item.get(field, [] if field == "ability_codes" else "")
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# 四维分析
# ---------------------------------------------------------------------------
def _evidence_view(e: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": e["id"], "event_id": e.get("event_id") or e["id"],
            "speaker": e["speaker"], "type": e["type"], "quote": e["quote"],
            "interpretation": e["interpretation"], "limits": e["limits"]}


def _usable(evidence, code: str) -> List[Dict[str, Any]]:
    return [e for e in report_checks.items_for(evidence, code)
            if report_checks.supports_judgement(e)]


def _dim_payload(dim_id: str, mapping, evidence,
                 codes: Optional[List[str]] = None,
                 final: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """一个维度的能力与可用资料；写作层另带只读的 final_assessment。"""
    abilities = report_kb.ability_map()
    rows = []
    for code, info in abilities.items():
        if info["dim"] != dim_id or (codes is not None and code not in codes):
            continue
        usable = _usable(evidence, code)
        row = {
            "code": code, "name": info["name"], "description": info["description"],
            "gap_note": info["gap_note"], "supplement": info["supplement"], "ask": info["ask"],
            "y4_lines": [{"code": line["code"], "line": line["family_line"]}
                         for line in mapping[code]["lines"]],
            "first_touch_and_other": [dict(_evidence_view(e), source=e["source"])
                                      for e in usable if e["source"] != "M1"],
            "meeting_evidence": [_evidence_view(e) for e in usable if e["source"] == "M1"],
        }
        if final and code in final:
            row["final_assessment"] = {
                "tags": final[code]["tags"],
                "evidence_ids": final[code]["evidence_ids"],
                "internal_note": final[code]["internal_note"]}
        rows.append(row)
    return rows


def _assessment_payload(dim_id: str, evidence,
                        codes: List[str]) -> List[Dict[str, Any]]:
    """判断层只看能力说明与可用证据，不看写作文本。"""
    abilities = report_kb.ability_map()
    rows = []
    for code in codes:
        info = abilities[code]
        usable = _usable(evidence, code)
        rows.append({
            "code": code, "name": info["name"], "description": info["description"],
            "gap_note": info["gap_note"], "supplement": info["supplement"], "ask": info["ask"],
            "first_touch_and_other": [dict(_evidence_view(e), source=e["source"])
                                      for e in usable if e["source"] != "M1"],
            "meeting_evidence": [_evidence_view(e) for e in usable if e["source"] == "M1"],
        })
    return rows


def _valid_ids(evidence, code: Optional[str] = None) -> set:
    return {e["id"] for e in (report_checks.items_for(evidence, code) if code else evidence)
            if report_checks.supports_judgement(e)}


def _sentences(raw, valid_ids, path: list, adjustments: List[Dict[str, Any]],
               label: str, empty: str = "") -> Dict[str, Any]:
    """按句收下 AI 的文字（S2-P6 §10）：事实句必须有可用证据，推断句要留有余地。"""
    kept = []
    rows = raw.get("sentences") if isinstance(raw, dict) else None
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        text = _readable(item.get("text"))
        if not text:
            continue
        ids = [i for i in item.get("evidence_ids") or [] if isinstance(i, str)]
        valid = [i for i in ids if i in valid_ids]
        kind = _clean(item.get("kind")) or "fact"
        if kind == "inference":
            if not any(word in text for word in report_checks.INFERENCE_WORDS):
                adjustments.append({"message": "%s：推断句没有留有余地，已删除" % label,
                                    "path": path})
                continue
            ids = valid
        else:
            kind = "fact"
            if not valid:
                adjustments.append({"message": "%s：事实句没有有效证据，已删除" % label,
                                    "path": path})
                continue
            ids = valid
        kept.append({"text": text, "evidence_ids": ids, "kind": kind})
    text = "".join(row["text"] for row in kept) or empty
    return {"text": text, "src": "ai", "sentences": kept}


def _blank_row() -> Dict[str, Any]:
    return {"y4_selected": [], "other_clues": _field(), "meeting": _field(),
            "tags": [], "tags_src": "ai", "evidence_ids": [], "internal_note": ""}


def enforce_ability(code: str, row: Dict[str, Any], evidence, mapping,
                    adjustments: List[Dict[str, Any]], path: list) -> None:
    """按代码规则校正 AI 的输出；每次改动都记一条 review 检查。"""
    def note(message: str, sub: Optional[str] = None):
        adjustments.append({"message": "%s：%s" % (code, message),
                            "path": path + ([sub] if sub else [])})

    allowed = set(mapping[code]["indicators"])
    kept = [c for c in row["y4_selected"] if c in allowed]
    removed = [c for c in row["y4_selected"] if c not in allowed]
    if removed:
        note("所选 Y4 指标 %s 不在该能力的指定映射中，已移除" % "、".join(removed), "y4_selected")
    row["y4_selected"] = kept

    if not row["meeting"]["text"]:
        row["meeting"] = _field(NO_MEETING)
        note("会议核实情况为空，已写入固定说明", "meeting")
    if not row["other_clues"]["text"] and not row["y4_selected"]:
        row["other_clues"] = _field(NO_CLUES)
        note("没有线索也没有 Y4 指标，已写入固定说明", "other_clues")
    known = {e["id"] for e in report_checks.items_for(evidence, code)
             if report_checks.is_usable(e)}
    row["evidence_ids"] = [i for i in row["evidence_ids"] if i in known]


def _by_code(result) -> Dict[str, Dict[str, Any]]:
    out = {}
    for item in (result or {}).get("abilities") or []:
        if isinstance(item, dict) and isinstance(item.get("code"), str):
            out[item["code"]] = item
    return out


def _clues_text(evidence, code: str) -> str:
    """Y4 以外的线索：由代码按证据原文拼出，来源名取自资料本身（T7 §1）。"""
    parts = []
    for item in report_checks.items_for(evidence, code):
        if not report_checks.supports_judgement(item) or item.get("source") == "M1":
            continue
        name = _clean(item.get("location"))
        if name.startswith("其他资料："):
            name = name[len("其他资料："):]
        if name.startswith("补充问卷："):
            name = "补充问卷《%s》" % name[len("补充问卷："):]
        parts.append("%s：“%s”" % (name, item["quote"]))
    return "".join(parts)


_JUDGEMENT_RE = re.compile(
    r"，(?:说明|体现|显示出|显示|反映出|反映|提示|表明)[^。！？!?]*")


def _cut_judgements(field: Dict[str, Any], code: str, path: list,
                    adjustments: List[Dict[str, Any]]) -> None:
    """meeting 只写事实：去掉“，说明……”这类判断尾巴（T7 §4）。"""
    cut = False
    for row in field.get("sentences") or []:
        new = _JUDGEMENT_RE.sub("", row["text"])
        if new != row["text"]:
            row["text"] = new
            cut = True
            adjustments.append({"message": "%s：会议核实情况里的判断句已删除" % code,
                                "path": path})
    if cut:
        field["text"] = "".join(row["text"] for row in field["sentences"])


_CAP_SPLIT_RE = re.compile(r"(?<=[。！？!?])")


def _cap_field(field: Dict[str, Any], limit: int, label: str, path: list,
               adjustments: List[Dict[str, Any]]) -> None:
    """超过上限时保留前面完整的句子、删去后面的句子；不改任何一句的文字（M1R D6）。"""
    text = field.get("text") or ""
    if len(text) <= limit:
        return
    rows = field.get("sentences") if isinstance(field.get("sentences"), list) else None
    if rows:
        pieces = [row.get("text") or "" for row in rows]
    else:
        rows = None
        pieces = [p for p in _CAP_SPLIT_RE.split(text) if p.strip()]
    keep, total = 0, 0
    for piece in pieces:
        if keep and total + len(piece) > limit:
            break
        keep += 1
        total += len(piece)
    if rows is not None:
        field["sentences"] = rows[:keep]
    field["text"] = "".join(pieces[:keep])
    if keep < len(pieces):
        adjustments.append({"message": "%s：超过 %d 字，已删去后面的句子" % (label, limit),
                            "path": path})
    if len(field["text"]) > limit:
        adjustments.append({"message": "%s：第一句已超过 %d 字，请导师精简" % (label, limit),
                            "path": path})


def step_dims(mapping, evidence, adjustments) -> Dict[str, Dict[str, Any]]:
    dims = {d["id"]: d for d in report_kb.fixed()["dims"]}
    abilities = report_kb.ability_map()
    codes_by_dim: Dict[str, List[str]] = {dim_id: [] for dim_id in dims}
    for code, info in abilities.items():
        if info["dim"] in codes_by_dim:
            codes_by_dim[info["dim"]].append(code)

    def name_of(dim_id: str) -> str:
        return "%s %s｜%s" % (dim_id, dims[dim_id]["en"], dims[dim_id]["zh"])

    def ask_assess(dim_id: str, codes: List[str],
                   errors: List[str]) -> Dict[str, Any]:
        payload = _assessment_payload(dim_id, evidence, codes)
        prompt = report_prompts.ASSESS_PROMPT % (name_of(dim_id), _json(payload))
        if errors:
            prompt += "\n\n【上次判断的问题】\n" + "\n".join("- " + e for e in errors)
        return _ask(prompt)

    def ask_write(dim_id: str, final) -> Dict[str, Any]:
        payload = _dim_payload(dim_id, mapping, evidence, codes_by_dim[dim_id], final)
        prompt = report_prompts.DIM_PROMPT % (name_of(dim_id), report_prompts.FAMILY_STYLE,
                                              _json(payload))
        return _ask(prompt)

    def run(dim_id: str):
        codes = codes_by_dim[dim_id]
        by_code = _by_code(ask_assess(dim_id, codes, []))
        errors: List[str] = []
        bad: List[str] = []
        for code in codes:
            raw = by_code.get(code)
            if raw is None:
                errors.append("%s：模型没有返回这项能力的判断" % code)
                bad.append(code)
                continue
            found = ["%s：%s" % (code, error) for error in
                     report_assessment.assessment_errors(raw, evidence, code)]
            if found:
                errors.extend(found)
                bad.append(code)
        if bad:                     # 只把有问题的能力带错误重试一次
            by_code.update(_by_code(ask_assess(dim_id, bad, errors)))
        final = {code: report_assessment.resolve_assessment(by_code.get(code) or {},
                                                            evidence, code)
                 for code in codes}
        return dim_id, ask_write(dim_id, final), final

    out = {}
    for dim_id, result, final in _parallel(run, list(dims)):
        path_prefix = ["dims", dim_id]
        by_code = _by_code(result)
        abilities_out = {}
        for code in codes_by_dim[dim_id]:
            path = path_prefix + ["abilities", code]
            raw = by_code.get(code)
            resolved = final[code]
            row = _blank_row()
            row["tags"] = resolved["tags"]
            for message in resolved["diagnostics"]:
                adjustments.append({"message": "%s：%s" % (code, message),
                                    "path": path + ["tags"]})
            if raw is None:
                adjustments.append({"message": "%s：AI 没有返回这项能力的写作" % code,
                                    "path": path})
            else:
                row["y4_selected"] = [c for c in raw.get("y4_selected") or [] if isinstance(c, str)]
                row["other_clues"] = _field(report_display.sources_line(evidence, code), "code")
                row["meeting"] = _sentences(raw.get("meeting"), _valid_ids(evidence, code),
                                            path + ["meeting"], adjustments, code)
                _cut_judgements(row["meeting"], code, path + ["meeting"], adjustments)
                row["evidence_ids"] = [i for i in raw.get("evidence_ids") or [] if isinstance(i, str)]
                row["internal_note"] = _clean(raw.get("internal_note"))
                limit = (report_checks.LIMITS["meeting_two_tags"] if len(row["tags"]) == 2
                         else report_checks.LIMITS["meeting"])
                _cap_field(row["meeting"], limit, "%s 首次会议核实情况" % code,
                           path + ["meeting"], adjustments)
            row["evidence_ids"] = list(dict.fromkeys(
                resolved["evidence_ids"] + row["evidence_ids"]))
            if not row["internal_note"]:
                row["internal_note"] = resolved["internal_note"]
            enforce_ability(code, row, evidence, mapping, adjustments, path)
            row["y4_selected"] = row["y4_selected"][:report_checks.Y4_MAX]
            abilities_out[code] = row
        out[dim_id] = {
            "core_finding": _sentences(result.get("core_finding"), _valid_ids(evidence),
                                       path_prefix + ["core_finding"], adjustments,
                                       dim_id, NO_MEETING),
            "context_notes": _sentences(result.get("context_notes"), _valid_ids(evidence),
                                        path_prefix + ["context_notes"], adjustments, dim_id),
            "abilities": abilities_out,
        }
        _cap_field(out[dim_id]["core_finding"], report_checks.LIMITS["core_finding"],
                   "%s 本维度当前核心发现" % dim_id, path_prefix + ["core_finding"], adjustments)
        _cap_field(out[dim_id]["context_notes"], report_checks.LIMITS["context_notes"],
                   "%s 情境差异与后续观察" % dim_id, path_prefix + ["context_notes"], adjustments)
    return {d: out[d] for d in dims}


# ---------------------------------------------------------------------------
# 综合画像与方案
# ---------------------------------------------------------------------------
def step_profile(dims: Dict[str, Any], ratings, adjustments) -> Dict[str, Any]:
    names = report_kb.ability_map()
    abilities = []
    for dim in dims.values():
        for code, row in dim["abilities"].items():
            abilities.append({
                "code": code, "name": names[code]["name"], "tags": row["tags"],
                "y4": [ratings[c]["family_line"] for c in row["y4_selected"] if c in ratings],
                "other_clues": row["other_clues"]["text"], "meeting": row["meeting"]["text"]})
    findings = {d: dim["core_finding"]["text"] for d, dim in dims.items()}
    result = _ask(report_prompts.PROFILE_PROMPT % (
        report_prompts.FAMILY_STYLE, _json(abilities), _json(findings)))
    portrait_raw = result.get("portrait") if isinstance(result.get("portrait"), dict) else {}
    findings_raw = result.get("findings") if isinstance(result.get("findings"), dict) else {}
    plan = []
    for row in result.get("plan") or []:
        if not isinstance(row, dict):
            continue
        if row.get("ability") not in names:
            adjustments.append({"message": "方案中的能力编号无效，该行已移除", "path": ["plan"]})
            continue
        plan.append({"ability": row["ability"], **{k: _field(_clean(row.get(k)))
                                                    for k in ("goal", "mentor", "family", "evidence")}})
    if len(plan) > 3:
        adjustments.append({"message": "阶段发展重点超过 3 项，已保留前 3 项", "path": ["plan"]})
        plan = plan[:3]
    out = {
        "portrait": {d: _field(_clean(portrait_raw.get(d))) for d in report_kb.dim_ids()},
        "findings": {k: {s: _field(_clean((findings_raw.get(k) or {}).get(s)
                                          if isinstance(findings_raw.get(k), dict) else ""))
                         for s in ("finding", "meaning")}
                     for k in ("resources", "needs", "open")},
        "plan": plan,
        "review_advice": _field(_clean(result.get("review_advice"))),
    }
    limits = report_checks.LIMITS
    for dim_id, field in out["portrait"].items():
        _cap_field(field, limits["portrait"], "%s 当前核心观察" % dim_id,
                   ["portrait", dim_id], adjustments)
    for kind, pair in out["findings"].items():
        for part in ("finding", "meaning"):
            _cap_field(pair[part], limits[part], "关键发展发现 %s·%s" % (kind, part),
                       ["findings", kind, part], adjustments)
    for i, row in enumerate(out["plan"]):
        for cell in ("goal", "mentor", "family", "evidence"):
            _cap_field(row[cell], limits["plan_cell"], "方案第 %d 项 %s" % (i + 1, cell),
                       ["plan", i, cell], adjustments)
    _cap_field(out["review_advice"], limits["review_advice"], "阶段回顾建议",
               ["review_advice"], adjustments)
    return out


# ---------------------------------------------------------------------------
# 事实核对（S2-P6 §10）
# ---------------------------------------------------------------------------
_LINT_LABEL = {"number": "数字", "time": "时间", "person": "人物", "quote": "引文",
               "intensity": "程度或频率", "conclusion": "结论", "speaker": "导师的说法",
               "observer": "他人观察", "y4_as_speech": "测评结果", "first_person": "第一人称",
               "hypothetical": "设想写成事实", "label": "资料没有的说法"}


def _family_pairs(doc: Dict[str, Any]) -> List[tuple]:
    """家庭版里由 AI 写的字段：路径与字段本身。"""
    pairs = []
    for dim_id, dim in (doc.get("dims") or {}).items():
        for key in ("core_finding", "context_notes"):
            pairs.append((["dims", dim_id, key], dim.get(key)))
        for code, row in ((dim or {}).get("abilities") or {}).items():
            for key in ("other_clues", "meeting"):
                pairs.append((["dims", dim_id, "abilities", code, key], row.get(key)))
    for dim_id, value in (doc.get("portrait") or {}).items():
        pairs.append((["portrait", dim_id], value))
    for key, row in (doc.get("findings") or {}).items():
        for sub in ("finding", "meaning"):
            pairs.append((["findings", key, sub], row.get(sub)))
    return pairs


def _bigrams(text: str) -> set:
    probe = report_checks.normalize(text)
    return {probe[i:i + 2] for i in range(len(probe) - 1)} or ({probe} if probe else set())


def _excerpt(sentence: str, source: str) -> str:
    grams = _bigrams(sentence)
    best, best_score = "", -1
    for piece in report_checks.split_paragraphs(source):
        score = len(grams & _bigrams(piece))
        if score > best_score:
            best, best_score = piece, score
    return best[:200]


def _evidence_context(evidence, ids, index: report_checks.TextIndex) -> str:
    """这些证据各自的出处：会议证据取前一句（多是导师的提问）和所在段落（T7 §2）。"""
    by_id = {e["id"]: e for e in evidence}
    lines: List[str] = []
    for ident in ids:
        item = by_id.get(ident)
        if item is None:
            continue
        if item.get("source") == "M1":
            where = index.position(item["quote"])
            found = ([index.previous(where), index.paragraph(where)]
                     if where is not None else [item["quote"]])
        else:
            found = ["%s：%s" % (item.get("location"), item["quote"])]
        for line in found:
            if line and line not in lines:
                lines.append(line)
    return "\n".join(lines)


def _uniq(ids) -> List[str]:
    return list(dict.fromkeys(i for i in ids if isinstance(i, str)))


def _sentence_ids(field) -> List[str]:
    return [i for row in (field or {}).get("sentences") or []
            for i in row.get("evidence_ids") or []]


def guard_sources(dims: Dict[str, Any], evidence, index: report_checks.TextIndex) -> Dict[str, Any]:
    """每个字段自己的资料；必须在维度核对改写文字之前算（改写会丢掉 sentences）。"""
    def ctx(ids) -> str:
        return _evidence_context(evidence, _uniq(ids), index)

    out: Dict[Any, str] = {}
    everything: List[str] = []
    for dim_id, dim in dims.items():
        dim_ids: List[str] = []
        for code, row in dim["abilities"].items():
            ids = list(row.get("evidence_ids") or []) + _sentence_ids(row.get("meeting"))
            dim_ids += ids
            path = ("dims", dim_id, "abilities", code, "meeting")
            out[path] = ctx(ids)
            for i, sentence in enumerate((row.get("meeting") or {}).get("sentences") or []):
                own = _uniq(sentence.get("evidence_ids") or [])
                if own:
                    out[path + (i,)] = ctx(own)
        for key in ("core_finding", "context_notes"):
            out[("dims", dim_id, key)] = ctx(dim_ids + _sentence_ids(dim.get(key)))
        out[("portrait", dim_id)] = out[("dims", dim_id, "core_finding")]
        everything += (dim_ids + _sentence_ids(dim.get("core_finding"))
                       + _sentence_ids(dim.get("context_notes")))
    out["all"] = ctx(everything)
    return out


_PERSON_GROUPS = (
    ("妈妈", "母亲", "爸爸", "父亲", "父母", "家长", "外婆", "外公", "奶奶", "爷爷"),
    ("老师", "班主任"),
    ("同学", "同伴", "朋友", "同桌", "组员"),
)
_HYPOTHETICAL_MARKERS = ("设想", "如果", "假如", "要是", "打算", "想试", "可能会", "会怎么")
_HEDGE_IN_QUOTE = ("有时候", "有时", "有一次", "偶尔")
_HEDGE_IN_SENTENCE = ("有时", "有一次", "偶尔", "曾")
_LABEL_WORDS = ("焦虑", "抑郁", "反刍", "创伤", "障碍", "自卑")


def _sentence_checks(dims: Dict[str, Any], evidence, index: report_checks.TextIndex,
                     state: Dict[str, Any]) -> None:
    """会议里每一句，对照它自己引用的证据做代码检查（T8 §3）。"""
    by_id = {e["id"]: e for e in evidence}
    for dim_id, dim in dims.items():
        for code, row in dim["abilities"].items():
            field = row.get("meeting") or {}
            path = ["dims", dim_id, "abilities", code, "meeting"]
            for sentence in field.get("sentences") or []:
                text = _clean(sentence.get("text"))
                ids = _uniq(sentence.get("evidence_ids") or [])
                if not text or not ids:
                    continue
                ctx = _evidence_context(evidence, ids, index)
                items = [by_id[i] for i in ids if i in by_id]

                def flag(kind: str, problem: str) -> None:
                    state["flags"].append({
                        "path": path, "sentence": text, "kind": kind,
                        "problem": problem, "source_excerpt": ctx[:200]})

                for group in _PERSON_GROUPS:
                    word = next((w for w in group if w in text), None)
                    if word and not any(w in ctx for w in group):
                        flag("person", "这件事的资料里没有“%s”，人物可能写错了" % word)
                if (any(item.get("type") == "假设性回应" for item in items)
                        and not any(m in text for m in _HYPOTHETICAL_MARKERS)):
                    flag("hypothetical", "所引证据是设想的回答，这里写成了实际行为")
                quotes = [item.get("quote") or "" for item in items]
                if (quotes and all(any(h in q for h in _HEDGE_IN_QUOTE) for q in quotes)
                        and not any(h in text for h in _HEDGE_IN_SENTENCE)):
                    flag("intensity", "资料说的是“有时”或“有一次”，这里写成了常态")
                for word in _LABEL_WORDS:
                    if word in text and word not in ctx:
                        flag("label", "资料里没有“%s”这个说法" % word)


def _triples(pairs, sources: Dict[Any, str]) -> List[tuple]:
    """给每个字段配上它自己的资料：先按路径找，找不到的（findings、plan 等）用“全部”。"""
    # 一句证据都没有的字段也要核对：资料写“（没有对应证据）”，事实句就会被标出，
    # 而不是因为资料为空被记成“未完成核对”
    return [(path, field, sources.get(tuple(path), sources["all"]) or NO_SOURCE)
            for path, field in pairs]


def _skip_block(text: str) -> bool:
    return text in (NO_CLUES, NO_MEETING)


def _guard_pass(triples, gender: str, state: Dict[str, Any],
                sources: Optional[Dict[Any, str]] = None) -> None:
    """核对 AI 写进家庭版的话；没通过的记成标记，不删整段。

    ``triples`` 是 ``(路径, 字段, 该字段自己的资料)``。会议字段有 ``sentences`` 时，
    每一句配上它自己证据的资料，各自成块（T8 §2）。
    """
    blocks, owners = [], {}
    split: Dict[str, List[tuple]] = {}      # 字段 key → [(块 id, 句序号)]
    for path, field, source in triples:
        if not isinstance(field, dict) or field.get("src") != "ai":
            continue
        text = _clean(field.get("text"))
        if not text or _skip_block(text):
            continue
        key = "/".join(str(step) for step in path)
        rows = field.get("sentences")
        if path and path[-1] == "meeting" and isinstance(rows, list) and rows:
            for i, row in enumerate(rows):
                sentence = _clean(row.get("text")) if isinstance(row, dict) else ""
                if not sentence:
                    continue
                block_id = "%s#%d" % (key, i)
                own = (sources or {}).get(tuple(path) + (i,)) or source
                blocks.append({"id": block_id, "text": sentence, "source": own})
                owners[block_id] = (path, field)
                split.setdefault(key, []).append((block_id, i))
            continue
        blocks.append({"id": key, "text": text, "source": source})
        owners[key] = (path, field)
    if not blocks:
        return
    result = ai_writing.run_guard(blocks, call=call_model, gender=gender)
    if result.get("status") != "checked":
        state["status"] = "skipped" if result.get("status") == "skipped" else "partial"
    returned = result.get("blocks") or {}
    handled = {block_id for pieces in split.values() for block_id, _i in pieces}
    for key, text in returned.items():
        if key not in owners or key in handled:
            continue
        path, field = owners[key]
        if text != field.get("text"):
            field["text"] = text
            field.pop("sentences", None)
    for key, pieces in split.items():
        path, field = owners[pieces[0][0]]
        rows = field["sentences"]
        changed = False
        parts = []
        for i, row in enumerate(rows):
            original = _clean(row.get("text")) if isinstance(row, dict) else ""
            block_id = "%s#%d" % (key, i)
            text = returned.get(block_id) if block_id in handled else None
            if text is None:
                text = original
            elif text != original:
                changed = True
            parts.append(text)
        if changed:
            field["text"] = "".join(parts)
            field.pop("sentences", None)
    for flag in result.get("flags") or []:
        if not isinstance(flag, dict) or flag.get("id") not in owners:
            continue
        path = owners[flag["id"]][0]
        state["flags"].append({
            "path": path, "sentence": _clean(flag.get("sentence")),
            "kind": _clean(flag.get("kind")), "problem": _clean(flag.get("problem")),
            "source_excerpt": _clean(flag.get("source_excerpt")),
        })


# 方案里的目标和建议用语是提议，不是对学生的陈述；只查这几类（T7 §5）
_PROPOSAL_KINDS = ("person", "speaker", "y4_as_speech", "first_person", "observer")


def _lint_pass(triples, state: Dict[str, Any]) -> None:
    """方案和回顾建议是提议，用代码检查代替逐句核对。"""
    for path, field, source in triples:
        if not isinstance(field, dict) or field.get("src") != "ai":
            continue
        text = _clean(field.get("text"))
        if not text or _skip_block(text):
            continue
        for item in ai_writing.lint_facts(text, source):
            if item["kind"] not in _PROPOSAL_KINDS:
                continue
            state["flags"].append({
                "path": path, "sentence": _sentence_with(text, item["value"]),
                "kind": item["kind"],
                "problem": "%s“%s”在资料中找不到依据" % (
                    _LINT_LABEL.get(item["kind"], "内容"), item["value"]),
                "source_excerpt": _excerpt(item["value"], source),
            })


def _proposal_pairs(profile: Dict[str, Any]) -> List[tuple]:
    pairs = []
    for index, row in enumerate(profile.get("plan") or []):
        for sub in ("goal", "mentor", "family", "evidence"):
            pairs.append((["plan", index, sub], row.get(sub)))
    pairs.append((["review_advice"], profile.get("review_advice")))
    return pairs


def _materials_text(ctx: Dict[str, Any]) -> str:
    parts = [ctx.get("first_touch_text") or ""]
    for questionnaire in ctx["auto"].get("questionnaires") or []:
        if questionnaire.get("status") != "已完成":
            continue
        for answers in (questionnaire.get("by_dimension") or {}).values():
            for answer in answers:
                parts.append("%s：%s" % (_clean(answer.get("question")),
                                        _clean(answer.get("answer"))))
    for upload in ctx["uploads"]:
        parts.append(_clean(upload.get("text")))
    return "\n".join(part for part in parts if part)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def generate(prep_id: int, progress: Optional[ProgressCallback] = None,
             actor_id=None) -> int:
    """跑完全部步骤并保存新版本；返回版本 id。"""
    prep = store.get_prep(int(prep_id))
    if not prep:
        raise store.NotFoundError("会前准备不存在")
    report = report_store.get_report(prep["id"])
    if not report:
        raise ReportError("报告还没有创建")

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
        skipped = result is None and step == "first_touch"
        emit(step, "skipped" if skipped else "done", time.monotonic() - started)
        return result

    ctx = run("check", lambda: step_check(prep, report))
    analysis = run("speakers", lambda: speakers.for_generation(report, _ask, actor_id))
    transcript = (speakers.marked_text(analysis["turns"]) if analysis
                  else report["transcript_text"])
    meeting_text = (speakers.prompt_text(analysis["turns"]) if analysis
                    else report["transcript_text"])
    roles = speakers.role_lookup(analysis["turns"]) if analysis else None
    ratings = run("y4", lambda: step_y4(ctx["values"]))
    mapping = run("mapping", lambda: step_mapping(ratings))
    other_items = run("first_touch", lambda: step_first_touch(ctx)) or []
    safety = run("safety", lambda: step_safety(transcript))
    chunk_failed: List[int] = []
    meeting_items = run("meeting", lambda: step_meeting(meeting_text, chunk_failed,
                                                       roles=roles))
    evidence = assign_ids(meeting_items + other_items)

    adjustments: List[Dict[str, Any]] = []
    guard: Dict[str, Any] = {"status": "checked", "flags": []}
    gender = _student_gender(prep["student_id"])
    index = report_checks.TextIndex(transcript)
    held: Dict[str, Any] = {}

    def dims_step():
        dims = step_dims(mapping, evidence, adjustments)
        held["sources"] = guard_sources(dims, evidence, index)
        _sentence_checks(dims, evidence, index, guard)
        _guard_pass(_triples(_family_pairs({"dims": dims}), held["sources"]), gender, guard,
                    held["sources"])
        return dims

    dims = run("dims", dims_step)

    def profile_step():
        profile = step_profile(dims, ratings, adjustments)
        _guard_pass(_triples(_family_pairs(profile), held["sources"]), gender, guard,
                    held["sources"])
        _lint_pass(_triples(_proposal_pairs(profile), held["sources"]), guard)
        return profile

    profile = run("profile", profile_step)

    doc = {"meta": ctx["meta"], "dims": dims, **profile,
           "guard": guard, "guard_ack": []}
    manifest = _manifest(ctx, adjustments, len(evidence), chunk_failed)

    def finish():
        version = {"doc": doc, "evidence": evidence, "y4_ratings": ratings,
                   "manifest": manifest}
        shown = dict(report, transcript_text=transcript, safety=safety, safety_ack_at=None)
        return report_checks.run_checks(shown, report_display.display_version(version),
                                        first_touch_text=ctx["first_touch_text"])

    checks = run("checks", finish)
    saved = report_store.add_version(
        report["id"], y4_ratings=ratings, evidence=evidence, ai_doc=doc,
        doc=copy.deepcopy(doc), checks=checks, manifest=manifest,
        status="ai_draft", safety=safety, created_by=actor_id)
    log.info("m1 report generated: report=%s version=%s evidence=%d checks=%d safety=%d",
             report["id"], saved["id"], len(evidence), len(checks), len(safety))
    return saved["id"]


def _manifest(ctx, adjustments, evidence_count: int,
              chunk_failed: Optional[List[int]] = None) -> Dict[str, Any]:
    try:
        from growth_talk.analysis import model_name
        model = model_name()
    except Exception:
        model = ""
    meta = ctx["meta"]
    return {
        "sources": ctx["source_labels"],
        "dates": {"y4": meta["y4_date"], "first_touch": ctx["first_touch_date"],
                  "meeting": meta["meeting_date"], "report": meta["report_date"]},
        "template_file": report_kb.fixed().get("template_file", ""),
        "kb_version": str(load_kb().get("version") or ""),
        "model": model,
        "generated_at": datetime.utcnow().isoformat(),
        "evidence_count": evidence_count,
        "adjustments": adjustments,
        "chunk_failed": sorted(set(int(n) for n in chunk_failed or [])),
    }
