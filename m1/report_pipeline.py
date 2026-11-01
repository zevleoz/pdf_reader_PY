"""会后报告生成管道：每步一个函数，可单独改动（协议 §3）。

AI 只负责证据提取、能力分析和综合画像；Y4 评级、引文核验、标签规则、
附录和质量检查全部由代码完成。测试替换本模块的 ``call_model``。

日志只记录数量和 id，不记录逐字稿、引文或生成的报告文字。
"""
from __future__ import annotations

import copy
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

from growth_talk.analysis import AnalysisError, call_model

import m1.sources as sources
import m1.store as store
from m1 import report_checks, report_kb, report_prompts, report_store, report_y4
from m1 import y4_evidence
from m1.kb import load_kb
from m1.prompts import SAFETY_CHECK_PROMPT, SAFETY_KEYWORDS

log = logging.getLogger(__name__)

STEP_DEFS = (
    ("check", "资料检查"),
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
NO_MEETING = "本次会议未获得相关信息。"

ProgressCallback = Callable[[str, str, float], None]


class ReportError(Exception):
    """可直接显示给用户的生成错误。"""


def _field(text: str = "", src: str = "ai") -> Dict[str, str]:
    return {"text": (text or "").strip(), "src": src}


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
        "evidence_sources": "、".join(labels),
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


def _ability_brief() -> List[Dict[str, str]]:
    return [{"code": code, "name": info["name"], "description": info["description"]}
            for code, info in report_kb.ability_map().items()]


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
        })
    return out


def extract_items(text: str, template: str, template_args: tuple, source: str,
                  label: str) -> List[Dict[str, Any]]:
    """一份资料 → 已核验、去重的证据条目（还没有 id）。"""
    index = report_checks.TextIndex(text)
    chunks = make_chunks(index.paragraphs)
    brief = _json(_ability_brief())
    valid = set(report_kb.ability_map())

    def run(chunk: str):
        result = _ask(template % (template_args + (brief, chunk)))
        return _normalise_items(result.get("items"), valid)

    merged: Dict[str, Dict[str, Any]] = {}
    for items in _parallel(run, chunks):
        for item in items:
            key = report_checks.normalize(item["quote"])
            if key in merged:                      # 重叠部分的重复项
                for code in item["ability_codes"]:
                    if code not in merged[key]["ability_codes"]:
                        merged[key]["ability_codes"].append(code)
                continue
            merged[key] = item
    out = []
    for item in merged.values():
        where = index.locate(item["quote"])
        item["quote_verified"] = where is not None
        item["source"] = source
        if where is None:
            item["location"] = ""
        elif source == "M1":
            number, mark = where
            item["location"] = "逐字稿第 %d 段%s" % (number, "（%s）" % mark if mark else "")
        else:
            item["location"] = label
        item["_order"] = where[0] if where else 10 ** 9
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
def step_meeting(transcript: str) -> List[Dict[str, Any]]:
    return extract_items(transcript, report_prompts.MEETING_PROMPT, (), "M1", "逐字稿")


def assign_ids(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for number, item in enumerate(items, 1):
        row = {"id": "e%d" % number}
        for key in ("ability_codes", "source", "location", "speaker", "type", "quote",
                    "quote_verified", "interpretation", "limits", "status"):
            row[key] = item.get(key, [] if key == "ability_codes" else "")
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# 四维分析
# ---------------------------------------------------------------------------
def _dim_payload(dim_id: str, mapping, evidence) -> List[Dict[str, Any]]:
    abilities = report_kb.ability_map()
    rows = []
    for code, info in abilities.items():
        if info["dim"] != dim_id:
            continue
        usable = [e for e in report_checks.items_for(evidence, code) if report_checks.is_usable(e)]

        def view(e):
            return {"id": e["id"], "speaker": e["speaker"], "type": e["type"],
                    "quote": e["quote"], "quote_verified": e["quote_verified"],
                    "interpretation": e["interpretation"], "limits": e["limits"],
                    "status": e["status"], "location": e["location"]}
        rows.append({
            "code": code, "name": info["name"], "description": info["description"],
            "gap_note": info["gap_note"], "supplement": info["supplement"], "ask": info["ask"],
            "y4_lines": [{"code": line["code"], "line": line["family_line"]}
                         for line in mapping[code]["lines"]],
            "first_touch_and_other": [dict(view(e), source=e["source"])
                                      for e in usable if e["source"] != "M1"],
            "meeting_evidence": [view(e) for e in usable if e["source"] == "M1"],
        })
    return rows


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

    # 标签：不合法则只留第一个合法标签
    names = report_kb.tag_names()
    tags = [t for t in row["tags"] if t in names]
    if tags != row["tags"] or report_kb.tags_problem(tags):
        first = [t for t in row["tags"] if t in names][:1]
        note("标签不合规（须为五种标签之一、最多两个且符合并列规则），已保留第一个有效标签", "tags")
        tags = first
    usable = [e for e in report_checks.items_for(evidence, code)
              if report_checks.supports_judgement(e)]
    usable_m1 = [e for e in usable if e["source"] == "M1"]

    def replace(old: str, reason: str, fallback: str):
        nonlocal tags
        if old not in tags:
            return
        rest = [t for t in tags if t != old]
        new = rest if rest else [fallback]
        note("%s，标签由「%s」改为「%s」" % (reason, old, "、".join(new)), "tags")
        tags = new

    if "确认发展需求" in tags and not any(
            e["type"] == "具体行为事件" and e["speaker"] != "待确认" for e in usable_m1):
        if "可能存在" in tags:
            note("缺少发言人已确认的会议具体行为事件，已去掉「确认发展需求」", "tags")
            tags = [t for t in tags if t != "确认发展需求"]
        else:
            tags = ["可能存在" if t == "确认发展需求" else t for t in tags]
            note("缺少发言人已确认的会议具体行为事件，「确认发展需求」改为「可能存在」", "tags")
    if "积极资源" in tags and not any(True for e in usable):
        replace("积极资源", "没有可用的非 Y4 证据", "信息不足")
    if "暂未发现" in tags and not usable_m1:
        replace("暂未发现", "没有可用的会议证据", "信息不足")
    row["tags"] = tags

    if not row["meeting"]["text"]:
        row["meeting"] = _field(NO_MEETING)
        note("会议核实情况为空，已写入固定说明", "meeting")
    if not row["other_clues"]["text"] and not row["y4_selected"]:
        row["other_clues"] = _field(NO_CLUES)
        note("没有线索也没有 Y4 指标，已写入固定说明", "other_clues")
    known = {e["id"] for e in report_checks.items_for(evidence, code)
             if report_checks.is_usable(e)}
    row["evidence_ids"] = [i for i in row["evidence_ids"] if i in known]


def step_dims(mapping, evidence, adjustments) -> Dict[str, Dict[str, Any]]:
    dims = {d["id"]: d for d in report_kb.fixed()["dims"]}

    def run(dim_id: str):
        payload = _dim_payload(dim_id, mapping, evidence)
        name = "%s %s｜%s" % (dim_id, dims[dim_id]["en"], dims[dim_id]["zh"])
        result = _ask(report_prompts.DIM_PROMPT % (name, report_prompts.FAMILY_STYLE, _json(payload)))
        return dim_id, result

    out = {}
    for dim_id, result in _parallel(run, list(dims)):
        by_code = {}
        for item in result.get("abilities") or []:
            if isinstance(item, dict) and isinstance(item.get("code"), str):
                by_code[item["code"]] = item
        abilities = {}
        for code, info in report_kb.ability_map().items():
            if info["dim"] != dim_id:
                continue
            path = ["dims", dim_id, "abilities", code]
            raw = by_code.get(code)
            row = _blank_row()
            if raw is None:
                adjustments.append({"message": "%s：AI 没有返回这项能力的分析" % code, "path": path})
            else:
                row["y4_selected"] = [c for c in raw.get("y4_selected") or [] if isinstance(c, str)]
                row["other_clues"] = _field(_clean(raw.get("other_clues")))
                row["meeting"] = _field(_clean(raw.get("meeting")))
                row["tags"] = [t for t in raw.get("tags") or [] if isinstance(t, str)]
                row["evidence_ids"] = [i for i in raw.get("evidence_ids") or [] if isinstance(i, str)]
                row["internal_note"] = _clean(raw.get("internal_note"))
            enforce_ability(code, row, evidence, mapping, adjustments, path)
            abilities[code] = row
        out[dim_id] = {"core_finding": _field(_clean(result.get("core_finding"))),
                       "context_notes": _field(_clean(result.get("context_notes"))),
                       "abilities": abilities}
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
    return {
        "portrait": {d: _field(_clean(portrait_raw.get(d))) for d in report_kb.dim_ids()},
        "findings": {k: {s: _field(_clean((findings_raw.get(k) or {}).get(s)
                                          if isinstance(findings_raw.get(k), dict) else ""))
                         for s in ("finding", "meaning")}
                     for k in ("resources", "needs", "open")},
        "plan": plan,
        "review_advice": _field(_clean(result.get("review_advice"))),
    }


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
    ratings = run("y4", lambda: step_y4(ctx["values"]))
    mapping = run("mapping", lambda: step_mapping(ratings))
    other_items = run("first_touch", lambda: step_first_touch(ctx)) or []
    safety = run("safety", lambda: step_safety(report["transcript_text"]))
    meeting_items = run("meeting", lambda: step_meeting(report["transcript_text"]))
    evidence = assign_ids(meeting_items + other_items)

    adjustments: List[Dict[str, Any]] = []
    dims = run("dims", lambda: step_dims(mapping, evidence, adjustments))
    profile = run("profile", lambda: step_profile(dims, ratings, adjustments))

    doc = {"meta": ctx["meta"], "dims": dims, **profile}
    manifest = _manifest(ctx, adjustments, len(evidence))

    def finish():
        version = {"doc": doc, "evidence": evidence, "y4_ratings": ratings,
                   "manifest": manifest}
        shown = dict(report, safety=safety, safety_ack_at=None)
        return report_checks.run_checks(shown, version,
                                        first_touch_text=ctx["first_touch_text"])

    checks = run("checks", finish)
    needs_check = bool(checks) or any(e["status"] == "待核实" for e in evidence)
    saved = report_store.add_version(
        report["id"], y4_ratings=ratings, evidence=evidence, ai_doc=doc,
        doc=copy.deepcopy(doc), checks=checks, manifest=manifest,
        status="needs_check" if needs_check else "ai_draft",
        safety=safety, created_by=actor_id)
    log.info("m1 report generated: report=%s version=%s evidence=%d checks=%d safety=%d",
             report["id"], saved["id"], len(evidence), len(checks), len(safety))
    return saved["id"]


def _manifest(ctx, adjustments, evidence_count: int) -> Dict[str, Any]:
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
    }
