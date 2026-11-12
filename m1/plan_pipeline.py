"""发展计划的 AI 流水线。

内部版分步生成（资料、目标字段、个性化需求、总览、单节课），家长版只从已批准的内部版改写。
每节课只带这一节需要的资料；逐字稿、Y4 数字、导师内部备注、报告里的原始引语不进入提示词。
返回的 ``ai_doc`` 保留 AI 原始结构，代码只做确定性的修正（编号、来源、Block Review、长度上限），
这些修正记在 ``manifest.adjustments``，并作为“需要核对”的检查项。
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from growth_talk.analysis import call_model, model_name
from m1 import plan_checks, plan_kb, plan_prompts, plan_store as pstore
from m1 import report_store as rstore
from m1 import wb

INPUT_KEYS = ("strengths", "needs", "context", "interests")
SESSION_COUNT = 3
TITLE_LIMIT = 20
FOCUS_LIMIT = 40
STEPS_LIMIT = 400
QUESTIONS_LIMIT = 200
EVIDENCE_LIMIT = 80
TASK_LIMIT = 120
OVERVIEW_LIMIT = 250

_SENTENCE_RE = re.compile(r"(?<=[。！？!?])")


class PlanError(Exception):
    """可读的生成失败原因。"""


def _ask(prompt: str) -> Dict[str, Any]:
    """调用模型并解析 JSON；解析失败重试一次，再失败抛 ``PlanError``。"""
    for attempt in range(2):
        try:
            result = call_model(prompt)
            if isinstance(result, str):
                result = json.loads(result)
        except json.JSONDecodeError:
            if attempt:
                raise PlanError("AI 返回格式无效，请重试")
            continue
        if isinstance(result, dict):
            return result
        if attempt:
            break
    raise PlanError("AI 返回格式无效，请重试")


def _text(value) -> str:
    if isinstance(value, dict):
        value = value.get("text")
    return str(value or "").strip()


def _field(value, src: str = "ai") -> Dict[str, str]:
    return {"text": _text(value), "src": src}


def _cap(field: Dict[str, str], limit: int, label: str, path: List[Any],
         adjustments: List[Dict[str, Any]]) -> None:
    text = str(field.get("text") or "")
    if len(text) <= limit:
        return
    keep = ""
    for piece in _SENTENCE_RE.split(text):
        if not piece.strip():
            continue
        if keep and len(keep) + len(piece) > limit:
            break
        keep += piece
    if keep:
        field["text"] = keep
    adjustments.append({
        "path": path,
        "label": label,
        "text": "%s：超过 %d 字，已删去后面的句子，请再精简" % (label, limit),
    })


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _inputs_payload(plan: Dict[str, Any], report_doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "student": {"name": plan.get("student_name") or "", "grade": plan.get("grade") or ""},
        "report": _report_view(report_doc),
    }


def _report_view(doc: Dict[str, Any]) -> Dict[str, Any]:
    doc = doc if isinstance(doc, dict) else {}
    findings = {}
    for key in ("resources", "needs", "open"):
        pair = (doc.get("findings") or {}).get(key) or {}
        if isinstance(pair, dict):
            findings[key] = {"finding": _text(pair.get("finding")),
                             "meaning": _text(pair.get("meaning"))}
    portrait = {}
    for key, value in (doc.get("portrait") or {}).items():
        text = _text(value)
        if text:
            portrait[key] = text
    dims = []
    for dim_id, dim in (doc.get("dims") or {}).items():
        if not isinstance(dim, dict):
            continue
        abilities = []
        for code, row in (dim.get("abilities") or {}).items():
            if not isinstance(row, dict):
                continue
            abilities.append({
                "code": code,
                "tags": [str(tag) for tag in (row.get("tags") or [])],
                "meeting": _text(row.get("meeting")),
                "other_clues": _text(row.get("other_clues")),
            })
        dims.append({
            "id": dim_id,
            "core_finding": _text(dim.get("core_finding")),
            "context_notes": _text(dim.get("context_notes")),
            "abilities": abilities,
        })
    return {"findings": findings, "portrait": portrait, "dims": dims}


def _goal_name(code: str) -> str:
    from m1 import kb
    try:
        return str(kb.ability(code).get("name") or "")
    except Exception:
        return ""


def _goal_view(goals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for goal in goals:
        rows.append({
            "code": goal.get("code"),
            "name": _goal_name(goal.get("code") or ""),
            "goal": _text(goal.get("goal")),
            "start": _text(goal.get("start")),
            "expected": _text(goal.get("expected")),
        })
    return rows


def _ability_lines(report_doc: Dict[str, Any], code: str) -> List[Dict[str, Any]]:
    rows = []
    for dim in (_report_view(report_doc).get("dims") or []):
        for row in dim["abilities"]:
            if row["code"] == code:
                rows.append({"dim": dim["id"], "core_finding": dim["core_finding"],
                             "context_notes": dim["context_notes"], "ability": row})
    return rows


def _personal_text(plan: Dict[str, Any]) -> str:
    """只取 AI 整理后的总结；导师原始备注只在个性化需求调用里使用。"""
    return _text((plan.get("personal") or {}).get("summary"))


def _file_texts(plan_id: int) -> List[str]:
    out = []
    for item in pstore.list_files(plan_id):
        row = pstore.get_file(item["id"]) or {}
        text = str(row.get("text") or "").strip()
        if text:
            out.append(text)
    return out


def _plan_with_file_texts(plan: Dict[str, Any]) -> Dict[str, Any]:
    enriched = copy.deepcopy(plan)
    enriched.setdefault("personal", {})["file_texts"] = _file_texts(plan["id"])
    return enriched


def _session_plan(goals: List[Dict[str, Any]], overview_sessions,
                  adjustments: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    codes = [g.get("code") for g in goals if g.get("code")]
    if not codes:
        raise PlanError("还没有发展目标，请先确认目标")
    given: Dict[int, Dict[str, Any]] = {}
    for item in overview_sessions or []:
        if not isinstance(item, dict):
            continue
        try:
            n = int(item.get("n"))
        except (TypeError, ValueError):
            continue
        given[n] = item
        for key in ("primary", "supporting"):
            value = item.get(key)
            if value and value not in codes and adjustments is not None:
                adjustments.append({
                    "path": [], "label": "Block Overview · 课程安排",
                    "text": "总览里的目标编号 %s 无效，已按安全规则重新安排，请核对" % value,
                })
    out = []
    for n in range(1, SESSION_COUNT + 1):
        item = given.get(n) or {}
        primary = item.get("primary") if item.get("primary") in codes else None
        supporting = item.get("supporting") if item.get("supporting") in codes else None
        if primary is None:
            if n == 1:
                primary = codes[0]
            elif n == 2:
                primary = codes[1] if len(codes) > 1 else codes[0]
            else:
                primary = codes[0]
        if supporting == primary:
            supporting = None
        out.append({"n": n, "primary": primary, "supporting": supporting})
    return out


def _want_candidates(code: str, grade) -> List[Dict[str, Any]]:
    if not code:
        return []
    try:
        return list(wb.candidates(code, grade or 9, limit=2) or [])
    except Exception:
        return []


def _candidate_map(goals: List[Dict[str, Any]], grade) -> Dict[str, List[Dict[str, Any]]]:
    if not wb.installed():
        return {}
    return {g["code"]: _want_candidates(g["code"], grade) for g in goals if g.get("code")}


def _session_candidates(entry: Dict[str, Any], n: int, goals, cmap) -> List[Dict[str, Any]]:
    codes = [entry.get("primary"), entry.get("supporting")]
    if n == SESSION_COUNT:
        codes.extend(g.get("code") for g in goals)
    seen = set()
    out = []
    for code in codes:
        if not code:
            continue
        for cand in cmap.get(code, []):
            wb_id = cand.get("wb_id")
            if not wb_id or wb_id in seen:
                continue
            seen.add(wb_id)
            out.append(cand)
            if len(out) >= 2:
                return out
    return out


def _candidate_payload(candidates: List[Dict[str, Any]]) -> str:
    rows = []
    for cand in candidates:
        text = wb.lesson_text(cand.get("wb_id")) or ""
        lesson = wb.lesson(cand.get("wb_id")) or {}
        rows.append({
            "wb_id": cand.get("wb_id"),
            "cite": cand.get("cite"),
            "match": cand.get("match"),
            "limit": cand.get("limit"),
            "objective": cand.get("objective") or lesson.get("objective") or "",
            "name": lesson.get("name") or "",
            "text": text,
        })
    return _json(rows)


def _session_prompt(n: int, plan: Dict[str, Any], overview: str, entry: Dict[str, Any],
                    candidates: List[Dict[str, Any]], previous: List[Dict[str, Any]],
                    goals: List[Dict[str, Any]]) -> str:
    data = {
        "session": n,
        "session_count": SESSION_COUNT,
        "student": {"name": plan.get("student_name") or "", "grade": plan.get("grade") or ""},
        "inputs": {key: _text((plan.get("inputs") or {}).get(key)) for key in INPUT_KEYS},
        "goals": _goal_view(goals),
        "personal_summary": _personal_text(plan),
        "overview": overview,
        "session_plan": entry,
        "previous_sessions": previous,
    }
    wb_rule = plan_prompts.WB_NONE if not candidates else plan_prompts.WB_RULE
    candidate_block = "" if not candidates else "【WB 参考课】\n" + _candidate_payload(candidates)
    return plan_prompts.SESSION_PROMPT % (
        n, plan_prompts.SHARED_RULES, wb_rule, candidate_block, _json(data))


def _report_doc_for(plan: Dict[str, Any]) -> Dict[str, Any]:
    version_id = plan.get("report_version_id")
    version = rstore.get_version(version_id) if version_id else None
    if not version:
        raise PlanError("会后报告还没有生成内容，请先完成会后报告")
    return version.get("doc") or {}


def _require_goals(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    goals = plan.get("goals") or []
    if not goals:
        raise PlanError("还没有发展目标，请先确认目标")
    return goals


def read_report(plan_id: int, *, progress=None, actor_id=None) -> Dict[str, Any]:
    """读取会后报告当前版本，提取四项资料。"""
    plan = pstore.get_plan(plan_id)
    if not plan:
        raise PlanError("发展计划不存在")
    report = rstore.get_report_by_id(plan["report_id"])
    if not report:
        raise PlanError("没有找到会后报告")
    if report.get("status") != "published":
        raise PlanError("会后报告还没有正式发布")
    version_id = report.get("current_version_id")
    if not version_id:
        raise PlanError("会后报告还没有内容")
    version = rstore.get_version(version_id)
    if not version:
        raise PlanError("会后报告版本不存在")
    if progress:
        progress("read", "done")
    pstore.mark_report_read(plan_id, version_id)
    doc = version.get("doc") or {}
    if not doc:
        pstore.save_inputs_ai(plan_id, {key: "" for key in INPUT_KEYS})
        return pstore.get_plan(plan_id) or plan
    if progress:
        progress("inputs", "active")
    prompt = plan_prompts.INPUTS_PROMPT % (
        plan_prompts.SHARED_RULES, _json(_inputs_payload(plan, doc)))
    data = _ask(prompt)
    pstore.save_inputs_ai(plan_id, {key: _text(data.get(key)) for key in INPUT_KEYS})
    if progress:
        progress("inputs", "done")
    return pstore.get_plan(plan_id) or plan


def fill_goal(plan_id: int, code: str, *, progress=None, actor_id=None) -> Dict[str, Any]:
    """为一项发展目标填写当前起点与阶段预期进展。"""
    plan = pstore.get_plan(plan_id)
    if not plan:
        raise PlanError("发展计划不存在")
    goal = next((item for item in plan.get("goals") or [] if item.get("code") == code), None)
    if not goal:
        raise PlanError("没有这项发展目标")
    doc = _report_doc_for(plan)
    data = {
        "goal": {"code": code, "name": _goal_name(code), "goal": _text(goal.get("goal"))},
        "report_lines": _ability_lines(doc, code),
    }
    if progress:
        progress("goal", "active")
    result = _ask(plan_prompts.GOAL_PROMPT % (plan_prompts.SHARED_RULES, _json(data)))
    start = _text(result.get("start"))
    expected = _text(result.get("expected"))
    if not start or not expected:
        raise PlanError("AI 没有写完这项的当前起点和阶段预期进展，请重试")
    pstore.save_goal_ai(plan_id, code, start, expected)
    if progress:
        progress("goal", "done")
    return pstore.get_plan(plan_id) or plan


def personal_summary(plan_id: int, *, progress=None, actor_id=None) -> Dict[str, Any]:
    """把个性化需求与会议记录文字整理成一段总结。"""
    plan = pstore.get_plan(plan_id)
    if not plan:
        raise PlanError("发展计划不存在")
    notes = _text((plan.get("personal") or {}).get("notes"))
    texts = []
    for item in pstore.list_files(plan_id):
        row = pstore.get_file(item["id"]) or {}
        if row.get("text_status") == "ready" and row.get("text"):
            texts.append({"filename": row.get("filename"), "text": row["text"]})
    if not notes and not texts:
        raise PlanError("请先填写个性化需求或上传会议记录")
    data = {"notes": notes, "files": texts}
    if progress:
        progress("personal", "active")
    result = _ask(plan_prompts.PERSONAL_PROMPT % (
        plan_prompts.SHARED_RULES, _json(data)))
    summary = _text(result.get("summary"))
    if not summary:
        raise PlanError("AI 没有写出个性化需求总结，请重试")
    pstore.save_personal_summary(plan_id, summary)
    if progress:
        progress("personal", "done")
    return pstore.get_plan(plan_id) or plan


def _activity(raw: Dict[str, Any], n: int, index: int, codes: List[str],
              candidate_ids: List[str],
              adjustments: List[Dict[str, Any]]) -> Dict[str, Any]:
    path = ["sessions", n - 1, "activities", index - 1]
    label_base = "Session %d · Activity %d" % (n, index)
    name = _field(raw.get("name"))
    if not name["text"]:
        raise PlanError("第 %d 节课有一个活动没有名称，请重新生成本节" % n)
    steps = _field(raw.get("steps"))
    if not steps["text"]:
        raise PlanError("第 %d 节课有一个活动缺少教学流程，请重新生成本节" % n)
    minutes = raw.get("minutes")
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
        minutes = 15
        adjustments.append({"path": path, "label": label_base,
                            "text": "%s：活动时长不是数字，已按 15 分钟处理" % label_base})
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    kind = source.get("type")
    wb_id = source.get("wb_id")
    if kind == "world_bank" and wb_id not in candidate_ids:
        kind = "ai_original"
        wb_id = None
        adjustments.append({
            "path": path, "label": label_base,
            "text": "%s：参考来源不在本次提供的 WB 参考课里，已改为 AI Original，请核对" % label_base,
        })
    elif kind == "other":
        kind = "ai_original"
        wb_id = None
        adjustments.append({"path": path, "label": label_base,
                            "text": "%s：AI 不能选择其他参考，已改为 AI Original，请核对" % label_base})
    elif kind not in ("ai_original", "world_bank"):
        if kind:
            adjustments.append({"path": path, "label": label_base,
                                "text": "%s：参考来源类型无效，已改为 AI Original，请核对" % label_base})
        kind = "ai_original"
        wb_id = None
    if kind != "world_bank":
        wb_id = None
    row = {
        "name": name,
        "minutes": int(minutes),
        "steps": steps,
        "questions": _field(raw.get("questions")),
        "materials": _field(raw.get("materials") or "无"),
        "source": {"type": kind, "wb_id": wb_id, "text": ""},
        "block_review": False,
    }
    _cap(row["steps"], STEPS_LIMIT, label_base + " · 教学流程", path + ["steps"], adjustments)
    _cap(row["questions"], QUESTIONS_LIMIT, label_base + " · 引导问题",
         path + ["questions"], adjustments)
    return row


def _practice(raw: Dict[str, Any], n: int, index: int, codes: List[str],
              adjustments: List[Dict[str, Any]]) -> Dict[str, Any]:
    path = ["sessions", n - 1, "practice", index - 1]
    label = "Session %d · 课后实践 %d" % (n, index)
    code = raw.get("code")
    if code not in codes:
        code = codes[0]
        adjustments.append({"path": path, "label": label,
                            "text": "%s：实践关联的目标编号无效，已改为 %s，请核对" % (label, code)})
    platform = raw.get("platform") if raw.get("platform") in plan_kb.platforms() else "无"
    if platform != raw.get("platform"):
        adjustments.append({"path": path, "label": label,
                            "text": "%s：平台不在可选范围内，已改为“无”，请核对" % label})
    task = _field(raw.get("task"))
    if not task["text"]:
        raise PlanError("第 %d 节课有一项课后实践缺少任务说明，请重新生成本节" % n)
    row = {
        "code": code,
        "name": _field(raw.get("name")),
        "task": task,
        "frequency": _field(raw.get("frequency")),
        "platform": platform,
        "evidence": _field(raw.get("evidence")),
    }
    if not row["name"]["text"]:
        raise PlanError("第 %d 节课有一项课后实践没有名称，请重新生成本节" % n)
    _cap(row["task"], TASK_LIMIT, label + " · 任务说明", path + ["task"], adjustments)
    _cap(row["evidence"], EVIDENCE_LIMIT, label + " · 预期证据", path + ["evidence"],
         adjustments)
    return row


def _session_doc(raw: Dict[str, Any], n: int, goals: List[Dict[str, Any]],
                 candidates: List[Dict[str, Any]],
                 adjustments: List[Dict[str, Any]]) -> Dict[str, Any]:
    codes = [g["code"] for g in goals]
    title = _field(raw.get("title"))
    if not title["text"]:
        raise PlanError("第 %d 节课没有标题，请重新生成本节" % n)
    focus_raw = raw.get("focus") if isinstance(raw.get("focus"), dict) else {}
    primary = focus_raw.get("primary")
    if primary not in codes:
        primary = codes[0]
        adjustments.append({"path": ["sessions", n - 1, "focus", "primary"],
                            "label": "Session %d · 教学重点" % n,
                            "text": "Session %d：本课主要目标编号无效，已改为 %s，请核对"
                                    % (n, primary)})
    supporting = focus_raw.get("supporting")
    if supporting not in codes:
        supporting = None
        if focus_raw.get("supporting"):
            adjustments.append({"path": ["sessions", n - 1, "focus", "supporting"],
                                "label": "Session %d · 教学重点" % n,
                                "text": "Session %d：辅助目标编号无效，已清空，请核对" % n})
    if supporting == primary:
        supporting = None
    focus = {
        "primary": primary,
        "supporting": supporting,
        "text": _field(focus_raw.get("text")),
    }
    if not focus["text"]["text"]:
        raise PlanError("第 %d 节课没有教学重点说明，请重新生成本节" % n)
    content_raw = raw.get("content") if isinstance(raw.get("content"), dict) else {}
    content = {
        "mindsets": _field(content_raw.get("mindsets")),
        "skills": _field(content_raw.get("skills")),
        "techniques": _field(content_raw.get("techniques")),
    }
    raw_activities = raw.get("activities") if isinstance(raw.get("activities"), list) else []
    candidate_ids = [cand.get("wb_id") for cand in candidates]
    activities = []
    for item in raw_activities:
        if not isinstance(item, dict):
            continue
        row = _activity(item, n, len(activities) + 1, codes, candidate_ids, adjustments)
        name_lower = row["name"]["text"].lower()
        if item.get("block_review") or "block review" in name_lower or "阶段总结" in row["name"]["text"]:
            row["block_review"] = False
            adjustments.append({
                "path": ["sessions", n - 1, "activities", len(activities)],
                "label": "Session %d · 活动 %d" % (n, len(activities) + 1),
                "text": "Session %d：AI 写了回顾活动，已保留；请确认是否与 Block Review 重复" % n,
            })
        activities.append(row)
    if not activities:
        raise PlanError("第 %d 节课没有可用活动，请重新生成本节" % n)
    evidence = _field(raw.get("evidence"))
    if not evidence["text"]:
        raise PlanError("第 %d 节课没有课堂预期表现，请重新生成本节" % n)
    raw_practices = raw.get("practice") if isinstance(raw.get("practice"), list) else []
    practices = []
    for item in raw_practices:
        if isinstance(item, dict):
            practices.append(_practice(item, n, len(practices) + 1, codes, adjustments))
    if not practices:
        raise PlanError("第 %d 节课没有课后实践，请重新生成本节" % n)
    reviews = []
    if n > 1:
        for value in raw.get("review") or []:
            text = _text(value)
            if text:
                reviews.append(text)
        reviews = reviews[:3]
        if len(reviews) < 2:
            reviews.extend(["上次的课后实践完成得怎么样？", "哪一次练习最有帮助？"][len(reviews):2])
            adjustments.append({"path": ["sessions", n - 1, "review"],
                                "label": "Session %d · 回顾" % n,
                                "text": "Session %d：上次实践回顾不足 2 个问题，已补上固定问题，请核对"
                                        % n})
    if n == SESSION_COUNT:
        next_prep = None
    else:
        next_prep = _field(raw.get("next_prep"))
        if not next_prep["text"]:
            next_prep = _field("下次课前了解课后实践的完成情况。")
            adjustments.append({"path": ["sessions", n - 1, "next_prep"],
                                "label": "Session %d · 下次课准备" % n,
                                "text": "Session %d：缺少下次课准备，已补一句固定文字，请核对" % n})
    session = {
        "n": n,
        "title": title,
        "review": reviews,
        "focus": focus,
        "content": content,
        "activities": activities,
        "evidence": evidence,
        "practice": practices,
        "next_prep": next_prep,
    }
    _cap(title, TITLE_LIMIT, "Session %d · 标题" % n,
         ["sessions", n - 1, "title"], adjustments)
    _cap(focus["text"], FOCUS_LIMIT, "Session %d · 教学重点" % n,
         ["sessions", n - 1, "focus", "text"], adjustments)
    _cap(evidence, EVIDENCE_LIMIT, "Session %d · 课堂预期表现" % n,
         ["sessions", n - 1, "evidence"], adjustments)
    return session


def _append_block_review(session: Dict[str, Any], n: int) -> Dict[str, Any]:
    review = plan_kb.block_review()
    parts = review.get("parts") or []
    steps = "\n".join("%s：%s" % (part.get("label"), part.get("text")) for part in parts)
    session["activities"].append({
        "name": _field(review.get("name")),
        "minutes": int(review.get("minutes") or 10),
        "steps": _field(steps),
        # 引导问题由导师按课情填写；固定说明只从 KB 显示，不写进文档
        "questions": {"text": "", "src": "mentor"},
        "materials": _field("无"),
        "source": {"type": "ai_original", "wb_id": None, "text": ""},
        "block_review": True,
    })
    return session


def _assign_ids(doc: Dict[str, Any]) -> None:
    for session in doc.get("sessions") or []:
        n = int(session.get("n") or 1)
        for index, activity in enumerate(session.get("activities") or [], 1):
            activity["id"] = "s%da%d" % (n, index)
        for index, practice in enumerate(session.get("practice") or [], 1):
            practice["id"] = "s%dp%d" % (n, index)


def _adjustment_items(adjustments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items = []
    for index, adj in enumerate(adjustments, 1):
        items.append({
            "id": "adj-%d" % index,
            "level": "review",
            "path": adj.get("path") or [],
            "label": adj.get("label") or "生成修正",
            "text": adj.get("text") or "",
        })
    return items


def _version_checks(plan: Dict[str, Any], doc: Dict[str, Any],
                    adjustments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return plan_checks.run_checks(plan, doc) + _adjustment_items(adjustments)


def generate(plan_id: int, *, progress=None, actor_id=None,
             use_old_report: bool = False) -> int:
    """生成完整内部版（调用方已把状态设为 generating）。"""
    plan = pstore.get_plan(plan_id)
    if not plan:
        raise PlanError("发展计划不存在")
    report = rstore.get_report_by_id(plan["report_id"])
    if (not use_old_report and report
            and plan.get("report_version_id") != report.get("current_version_id")):
        raise PlanError("会后报告已更新，请先重新读取或选择继续使用旧版本")
    _report_doc_for(plan)
    goals = _require_goals(plan)
    if progress:
        progress("read", "done")
    if progress:
        progress("wb", "active")
    cmap = _candidate_map(goals, plan.get("wb_grade"))
    if progress:
        progress("wb", "done")
    if progress:
        progress("overview", "active")
    overview_data = {
        "student": {"name": plan.get("student_name") or "", "grade": plan.get("grade") or ""},
        "goals": _goal_view(goals),
        "inputs": {key: _text((plan.get("inputs") or {}).get(key)) for key in INPUT_KEYS},
        "personal_summary": _personal_text(plan),
        "session_count": SESSION_COUNT,
    }
    overview_result = _ask(plan_prompts.OVERVIEW_PROMPT % (
        plan_prompts.SHARED_RULES, _json(overview_data)))
    overview = _text(overview_result.get("overview"))
    if not overview:
        raise PlanError("AI 没有写出阶段总体目标，请重试")
    if progress:
        progress("overview", "done")
    adjustments: List[Dict[str, Any]] = []
    session_plan = _session_plan(goals, overview_result.get("sessions"), adjustments)
    doc: Dict[str, Any] = {"overview": _field(overview), "sessions": [],
                           "mentor_notes": _field("")}
    _cap(doc["overview"], OVERVIEW_LIMIT, "Block Overview · 总体目标", ["overview"],
         adjustments)
    prompts = []
    prompt_keys = ["overview"]
    for n in range(1, SESSION_COUNT + 1):
        if progress:
            progress("sessions", "active")
        entry = session_plan[n - 1]
        candidates = _session_candidates(entry, n, goals, cmap)
        previous = [{"n": item["n"], "title": _text(item.get("title")),
                     "focus": _text((item.get("focus") or {}).get("text")),
                     "practices": [_text(p.get("name")) for p in item.get("practice") or []]}
                    for item in doc["sessions"]]
        prompt = _session_prompt(n, plan, overview, entry, candidates, previous, goals)
        prompts.append(prompt)
        prompt_keys.append("session-%d" % n)
        raw = _ask(prompt)
        session = _session_doc(raw, n, goals, candidates, adjustments)
        if n == SESSION_COUNT:
            session = _append_block_review(session, n)
        doc["sessions"].append(session)
    if progress:
        progress("sessions", "done")
    _assign_ids(doc)
    if progress:
        progress("checks", "active")
    checks = _version_checks(plan, doc, adjustments)
    version = pstore.add_version(
        plan_id, part="internal", kind="ai_draft",
        ai_doc=copy.deepcopy(doc), doc=copy.deepcopy(doc), checks=checks,
        manifest={
            "model": model_name(),
            "prompt_keys": prompt_keys,
            "wb_candidates": {str(n): [c.get("wb_id") for c in
                                       _session_candidates(session_plan[n - 1], n, goals, cmap)]
                              for n in range(1, SESSION_COUNT + 1)},
            "session_plan": session_plan,
            "inputs_hash": hashlib.sha256(_json(plan.get("inputs") or {}).encode("utf-8")).hexdigest(),
            "adjustments": adjustments,
        },
        created_by=actor_id)
    if progress:
        progress("checks", "done")
    pstore.finish_generation(plan_id, "internal", version_id=version["id"])
    return version["id"]


def regenerate(plan_id: int, section, *, progress=None, actor_id=None) -> int:
    """只重做一处（overview 或 1/2/3），其他部分保留导师当前编辑。"""
    if section not in ("overview", 1, 2, 3):
        raise PlanError("未知的重新生成范围")
    plan = pstore.get_plan(plan_id)
    if not plan:
        raise PlanError("发展计划不存在")
    current = pstore.current_version(plan_id, "internal")
    if not current or not current.get("doc"):
        raise PlanError("内部版还没有生成")
    doc = copy.deepcopy(current["doc"])
    ai_doc = copy.deepcopy(current.get("ai_doc") or current["doc"])
    manifest = copy.deepcopy(current.get("manifest") or {})
    goals = _require_goals(plan)
    _report_doc_for(plan)
    adjustments: List[Dict[str, Any]] = []
    prompt_keys = []
    if section == "overview":
        if progress:
            progress("regen", "active")
        data = {
            "student": {"name": plan.get("student_name") or "", "grade": plan.get("grade") or ""},
            "goals": _goal_view(goals),
            "inputs": {key: _text((plan.get("inputs") or {}).get(key)) for key in INPUT_KEYS},
            "personal_summary": _personal_text(plan),
            "session_count": SESSION_COUNT,
        }
        result = _ask(plan_prompts.OVERVIEW_PROMPT % (
            plan_prompts.SHARED_RULES, _json(data)))
        overview = _text(result.get("overview"))
        if not overview:
            raise PlanError("AI 没有写出阶段总体目标，请重试")
        field = _field(overview)
        _cap(field, OVERVIEW_LIMIT, "Block Overview · 总体目标", ["overview"], adjustments)
        doc["overview"] = field
        ai_doc["overview"] = copy.deepcopy(field)
        manifest["session_plan"] = _session_plan(goals, result.get("sessions"),
                                                 adjustments)
        prompt_keys.append("overview")
    else:
        n = int(section)
        if progress:
            progress("regen", "active")
        overview = _text(doc.get("overview"))
        entry = (manifest.get("session_plan") or _session_plan(goals, None))[n - 1]
        cmap = _candidate_map(goals, plan.get("wb_grade"))
        candidates = _session_candidates(entry, n, goals, cmap)
        previous = [{"n": item.get("n"), "title": _text(item.get("title")),
                     "focus": _text((item.get("focus") or {}).get("text")),
                     "practices": [_text(p.get("name")) for p in item.get("practice") or []]}
                    for item in doc.get("sessions") or [] if item.get("n") != n]
        prompt = _session_prompt(n, plan, overview, entry, candidates, previous, goals)
        prompt_keys.append("session-%d" % n)
        raw = _ask(prompt)
        session = _session_doc(raw, n, goals, candidates, adjustments)
        if n == SESSION_COUNT:
            session = _append_block_review(session, n)
        doc.setdefault("sessions", [])
        while len(doc["sessions"]) < SESSION_COUNT:
            doc["sessions"].append({})
        doc["sessions"][n - 1] = session
        ai_sessions = ai_doc.setdefault("sessions", [])
        while len(ai_sessions) < SESSION_COUNT:
            ai_sessions.append({})
        ai_sessions[n - 1] = copy.deepcopy(session)
        manifest.setdefault("wb_candidates", {})[str(n)] = [c.get("wb_id") for c in candidates]
    _assign_ids(doc)
    _assign_ids(ai_doc)
    checks = _version_checks(plan, doc, adjustments)
    manifest["prompt_keys"] = prompt_keys
    manifest["adjustments"] = adjustments
    version = pstore.add_version(
        plan_id, part="internal", kind="edit", ai_doc=ai_doc, doc=doc,
        checks=checks, manifest=manifest, created_by=actor_id)
    if progress:
        progress("checks", "done")
    pstore.finish_generation(plan_id, "internal", version_id=version["id"])
    return version["id"]


def generate_parent(plan_id: int, *, progress=None, actor_id=None) -> int:
    """从已批准的内部版生成家长版（调用方已把家长版状态设为 generating）。"""
    plan = pstore.get_plan(plan_id)
    if not plan:
        raise PlanError("发展计划不存在")
    if plan.get("status") != "approved":
        raise PlanError("请先批准内部版")
    internal = pstore.current_version(plan_id, "internal")
    if not internal or not internal.get("doc"):
        raise PlanError("内部版还没有生成")
    internal_doc = internal["doc"]
    goals = _require_goals(plan)
    sessions = internal_doc.get("sessions") or []
    practices = []
    internal_practices = []
    for session in sessions:
        for practice in session.get("practice") or []:
            internal_practices.append({
                "ref": practice.get("id"),
                "code": practice.get("code"),
                "name": _text(practice.get("name")),
                "task": _text(practice.get("task")),
                "frequency": _text(practice.get("frequency")),
                "platform": practice.get("platform"),
            })
    data = {
        "header": {
            "student": plan.get("student_name") or "",
            "grade": plan.get("grade") or "",
            "mentor": plan.get("mentor_name") or "",
            "block_no": plan.get("block_no") or 1,
            "period": {"start": plan.get("period_start") or "",
                       "end": plan.get("period_end") or ""},
            "credits": plan.get("credits") or "",
            "session_count": SESSION_COUNT,
        },
        "overview": _text(internal_doc.get("overview")),
        "goals": [{"code": goal["code"], "name": _goal_name(goal["code"]),
                   "goal": _text(goal.get("goal")), "start": _text(goal.get("start")),
                   "expected": _text(goal.get("expected"))} for goal in goals],
        "sessions": [{
            "n": session.get("n"),
            "title": _text(session.get("title")),
            "focus": _text((session.get("focus") or {}).get("text")),
            "evidence": _text(session.get("evidence")),
            "practices": [{"ref": p.get("id"), "name": _text(p.get("name")),
                           "task": _text(p.get("task"))} for p in session.get("practice") or []],
        } for session in sessions],
        "personal_summary": _personal_text(plan),
        "block_review": "本节最后有 Block Review & Summary，记录这个 Block 的成长与下一步练习。",
    }
    if progress:
        progress("parent", "active")
    result = _ask(plan_prompts.PARENT_PROMPT % dict(
        plan_kb.PARENT_LIMITS, rules=plan_prompts.SHARED_RULES, payload=_json(data)))
    ai_goals = result.get("goals") if isinstance(result.get("goals"), list) else []
    if len(ai_goals) != len(goals):
        raise PlanError("AI 返回的目标数量和已确认目标不一致，请重试")
    ai_sessions = result.get("sessions") if isinstance(result.get("sessions"), list) else []
    if len(ai_sessions) != len(sessions):
        raise PlanError("AI 返回的课程数量与内部版不一致，请重试")
    ai_family = result.get("family") if isinstance(result.get("family"), list) else []
    if len(ai_family) != 2:
        raise PlanError("AI 返回的家庭协作建议不是 2 条，请重试")
    ai_review = result.get("review") if isinstance(result.get("review"), list) else []
    if not 2 <= len(ai_review) <= 4:
        raise PlanError("AI 返回的成长观察不是 2 至 4 项，请重试")
    by_ref = {}
    for option in result.get("practice") or []:
        if isinstance(option, dict) and option.get("ref"):
            by_ref[option["ref"]] = option
    options = []
    known_refs = {practice["ref"] for practice in internal_practices}
    extra_refs = [ref for ref in by_ref if ref not in known_refs]
    for practice in internal_practices:
        option = by_ref.get(practice["ref"])
        if not option:
            raise PlanError("AI 漏掉了课后实践的家长版，请重试")
        options.append({
            "ref": practice["ref"],
            "title": _field(option.get("title")),
            "text": _field(option.get("text")),
            "frequency": _field(option.get("frequency") or practice["frequency"]),
            "platform": practice["platform"],
        })
    adjustments: List[Dict[str, Any]] = []
    for ref in extra_refs:
        adjustments.append({
            "path": ["practice_options"], "label": "家长版 · 课后实践",
            "text": "AI 返回了内部版没有的实践（%s），已忽略，请核对" % ref,
        })
    parent_doc = {
        "intro": _field(result.get("intro")),
        "goals": [{"code": goal["code"], "text": _field(ai_goals[index].get("text"))}
                  for index, goal in enumerate(goals)],
        "sessions": [{"n": session.get("n"), "title": _field(ai_sessions[index].get("title")),
                      "summary": _field(ai_sessions[index].get("summary"))}
                     for index, session in enumerate(sessions)],
        "transition": _field(result.get("transition")),
        "practice_options": options,
        "practice": [internal_practices[0]["ref"]] if len(internal_practices) == 1 else [],
        "family": [_field(value) for value in ai_family],
        "family_seen": [False, False],
        "review": [{"label": _field(point.get("label")), "text": _field(point.get("text"))}
                   for point in ai_review if isinstance(point, dict)],
    }
    limits = plan_kb.PARENT_LIMITS
    _cap(parent_doc["intro"], limits["intro"], "家长版 · 开场介绍", ["intro"], adjustments)
    for index, goal in enumerate(parent_doc["goals"]):
        _cap(goal["text"], limits["goal"], "家长版 · 目标 %s" % goal["code"],
             ["goals", index, "text"], adjustments)
    for index, session in enumerate(parent_doc["sessions"]):
        label = "家长版 · Session %d" % (index + 1)
        _cap(session["title"], limits["session_title"], label + " 标题",
             ["sessions", index, "title"], adjustments)
        _cap(session["summary"], limits["session_summary"], label + " 小结",
             ["sessions", index, "summary"], adjustments)
    _cap(parent_doc["transition"], limits["transition"], "家长版 · 过渡句",
         ["transition"], adjustments)
    for index, option in enumerate(parent_doc["practice_options"]):
        label = "家长版 · 课后实践 %d" % (index + 1)
        _cap(option["title"], limits["practice_title"], label + " 名称",
             ["practice_options", index, "title"], adjustments)
        _cap(option["text"], limits["practice_text"], label + " 说明",
             ["practice_options", index, "text"], adjustments)
        _cap(option["frequency"], limits["practice_frequency"], label + " 频率",
             ["practice_options", index, "frequency"], adjustments)
    for index, line in enumerate(parent_doc["family"]):
        _cap(line, limits["family"], "家长版 · 家庭协作 %d" % (index + 1),
             ["family", index], adjustments)
    for index, point in enumerate(parent_doc["review"]):
        label = "家长版 · 成长观察 %d" % (index + 1)
        _cap(point["label"], limits["review_label"], label + " 标签",
             ["review", index, "label"], adjustments)
        _cap(point["text"], limits["review_text"], label + " 说明",
             ["review", index, "text"], adjustments)
    checks = plan_checks.parent_blocking(
        parent_doc, _plan_with_file_texts(plan), internal_doc) + \
        _adjustment_items(adjustments)
    if progress:
        progress("parent", "done")
    version = pstore.add_version(
        plan_id, part="parent", kind="ai_draft",
        ai_doc=copy.deepcopy(parent_doc), doc=copy.deepcopy(parent_doc), checks=checks,
        manifest={"model": model_name(), "source_version_id": internal["id"],
                  "adjustments": adjustments},
        source_version_id=internal["id"], created_by=actor_id)
    pstore.finish_generation(plan_id, "parent", version_id=version["id"], status="draft")
    return version["id"]
