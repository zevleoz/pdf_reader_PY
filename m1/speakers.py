"""会后报告的发言人识别：把逐字稿切成发言段，判断每段是谁说的。

标签本身写明 导师 / 老师 / 学生 / 家长 等，或等于学生、导师姓名时，直接认定，不调用 AI。
其余段落（“发言人1”“说话人 A”、没有标签）交给 AI 按上下文判断，标签只作提示。
结果存在 ``m1_report_speakers``；生成报告时用 ``marked_text()``：每段一行，
以「角色：」开头，原话一字不改。

日志只记录数量，不记录逐字稿文字。
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)

ROLES = ("学生", "导师", "家长", "其他", "待确认")
UNSURE = "待确认"
TASK_SPEAKERS = "任务：判断逐字稿每段的发言人"
WINDOW_TURNS = 60
WINDOW_CHARS = 6000
CONTEXT_TURNS = 4
SPLIT_OVER = 200
PROMPT_TEXT_LIMIT = 300
MIN_LABEL_LINES = 3
MIN_LABEL_SHARE = 0.2
LABEL_MAJORITY = 0.8

_TIME = r"[\[(（]?\d{1,2}:\d{2}(?::\d{2})?[\])）]?"
_LABEL = r"[^\s:：\[\]()（）]{1,10}(?:\s[A-Za-z0-9]{1,3})?"
_INLINE_RE = re.compile(r"^\s*(?:(?P<t1>%s)\s*)?(?P<label>%s)\s*(?:(?P<t2>%s)\s*)?[:：]\s*(?P<text>.*)$"
                        % (_TIME, _LABEL, _TIME))
_HEADER_RE = re.compile(r"^\s*(?P<label>%s)\s+(?P<time>%s)\s*$" % (_LABEL, _TIME))
_SENTENCE_RE = re.compile(r"(?<=[。！？!?])")
_RULE_ROLES = (
    ("导师", ("导师", "老师", "顾问", "mentor")),
    ("学生", ("学生", "student")),
    ("家长", ("家长", "妈妈", "爸爸", "母亲", "父亲", "parent")),
)

SPEAKER_PROMPT = TASK_SPEAKERS + """
这是一次 M1 首次会议的逐字稿：导师与学生一对一谈话，家长有时在场。转写软件的发言人标签常常不准：同一个标签里可能混着两个人，也可能没有标签。请根据对话内容判断每一段是谁说的。

判断方法：
- 导师通常在提问、解释、复述、总结、引导、安排后续；学生通常在回答、讲自己经历的事、说自己的感受和想法。
- 看上下文：一个问题后面的回答，一般是另一个人说的。
- 称呼“老师”的，通常是学生或家长；直接称呼学生名字的，通常是导师或家长。
- 家长会用第三人称谈论学生，例如“孩子在家……”。
- label 只是转写软件给的标签，只作提示，不要只凭标签判断。
- role 已经填好的段落和 context 为 true 的段落只作参考，不用返回。
- 拿不准就写“待确认”，不要猜。

role 只能是：学生 / 导师 / 家长 / 其他 / 待确认。
role 为空、context 不为 true 的每一段都要返回，n 用给出的段号。

只输出 JSON：
{"turns": [{"n": 0, "role": "待确认"}]}

学生姓名：%s
导师姓名：%s
【段落】
%s"""


def transcript_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _clean_time(value: Optional[str]) -> str:
    return (value or "").strip("[]()（） ")


def _label_role(label: str, student_name: str, mentor_name: str) -> str:
    low = label.lower()
    for role, words in _RULE_ROLES:
        if any(word in low for word in words):
            return role
    if student_name and (label == student_name
                         or (len(student_name) >= 3 and label == student_name[1:])):
        return "学生"
    if mentor_name and label == mentor_name:
        return "导师"
    return ""


def _split_long(line: str) -> List[str]:
    if len(line) <= SPLIT_OVER:
        return [line]
    out, current = [], ""
    for piece in (p for p in _SENTENCE_RE.split(line) if p):
        if current and len(current) + len(piece) > SPLIT_OVER:
            out.append(current)
            current = ""
        current += piece
    if current:
        out.append(current)
    return out


def _match(line: str):
    header = _HEADER_RE.match(line)
    if header:
        return header.group("label").strip(), _clean_time(header.group("time")), None
    inline = _INLINE_RE.match(line)
    if inline:
        time = _clean_time(inline.group("t1") or inline.group("t2"))
        return inline.group("label").strip(), time, inline.group("text").strip()
    return "", "", None


def parse(text: str, student_name: str = "", mentor_name: str = "") -> Dict[str, Any]:
    """逐字稿 → {"format": "labelled" | "unlabelled", "turns": [...]}。

    每个 turn：{"n", "label", "time", "text", "role", "src"}；role 为空表示还要 AI 判断。
    """
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    parsed = [(line,) + _match(line) for line in lines]
    counts = Counter(label for _line, label, _time, _text in parsed
                     if label and not label.isdigit())
    accepted = {label for label, n in counts.items() if n >= MIN_LABEL_LINES}
    label_lines = sum(1 for _line, label, _t, _x in parsed if label in accepted)
    labelled = 2 <= len(accepted) <= 8 and label_lines >= MIN_LABEL_SHARE * len(lines)

    turns: List[Dict[str, Any]] = []
    if labelled:
        for line, label, time, rest in parsed:
            if label in accepted:
                turns.append({"label": label, "time": time, "text": rest or ""})
            elif turns and turns[-1]["label"]:
                turns[-1]["text"] += line
            else:
                turns.append({"label": "", "time": "", "text": line})
    else:
        for line in lines:
            for piece in _split_long(line):
                turns.append({"label": "", "time": "", "text": piece})
    turns = [t for t in turns if t["text"].strip()]
    for number, turn in enumerate(turns, 1):
        turn["n"] = number
        role = _label_role(turn["label"], student_name, mentor_name) if turn["label"] else ""
        turn["role"] = role
        turn["src"] = "rule" if role else ""
    return {"format": "labelled" if labelled else "unlabelled", "turns": turns}


def _windows(turns: List[Dict[str, Any]]) -> List[List[int]]:
    out: List[List[int]] = []
    current: List[int] = []
    size = 0
    for i, turn in enumerate(turns):
        length = min(len(turn["text"]), PROMPT_TEXT_LIMIT)
        if current and (len(current) >= WINDOW_TURNS or size + length > WINDOW_CHARS):
            out.append(current)
            current, size = [], 0
        current.append(i)
        size += length
    if current:
        out.append(current)
    return out


def _row(turn: Dict[str, Any], context: bool = False) -> Dict[str, Any]:
    row = {"n": turn["n"], "label": turn["label"], "role": turn["role"],
           "text": turn["text"][:PROMPT_TEXT_LIMIT]}
    if context:
        row["context"] = True
    return row


def assign_roles(turns: List[Dict[str, Any]], ask: Callable[[str], Dict[str, Any]],
                 student_name: str = "", mentor_name: str = "") -> Dict[str, int]:
    """给 role 为空的段落找发言人（原地修改）；返回 {"ai_set", "failed_windows"}。"""
    import json

    ai_set = 0
    failed = 0
    for window in _windows(turns):
        targets = {turns[i]["n"] for i in window if not turns[i]["role"]}
        if not targets:
            continue
        first = window[0]
        rows = [_row(turns[i], True) for i in range(max(0, first - CONTEXT_TURNS), first)]
        rows += [_row(turns[i]) for i in window]
        prompt = SPEAKER_PROMPT % (student_name or "未知", mentor_name or "未知",
                                   json.dumps(rows, ensure_ascii=False))
        try:
            result = ask(prompt)
        except Exception:
            failed += 1
            result = {}
        found: Dict[int, str] = {}
        for item in (result or {}).get("turns") or []:
            if not isinstance(item, dict):
                continue
            n, role = item.get("n"), item.get("role")
            if isinstance(n, str) and n.isdigit():
                n = int(n)
            if isinstance(n, int) and n in targets and role in ROLES:
                found[n] = role
        for i in window:
            turn = turns[i]
            if turn["n"] in targets:
                turn["role"] = found.get(turn["n"], UNSURE)
                turn["src"] = "ai"
                if turn["role"] != UNSURE:
                    ai_set += 1
    return {"ai_set": ai_set, "failed_windows": failed}


def label_roles(turns: List[Dict[str, Any]]) -> Dict[str, str]:
    """每个标签的主要角色；同一标签 80% 以上是同一角色时，用它补上该标签下的“待确认”段落。"""
    out: Dict[str, str] = {}
    for label in sorted({t["label"] for t in turns if t["label"]}):
        own = [t for t in turns if t["label"] == label]
        rule = {t["role"] for t in own if t["src"] == "rule"}
        if rule:
            out[label] = rule.pop()
            continue
        counts = Counter(t["role"] for t in own if t["role"] and t["role"] != UNSURE)
        total = sum(counts.values())
        if total >= 3:
            top, n = counts.most_common(1)[0]
            if n / total >= LABEL_MAJORITY:
                out[label] = top
                for turn in own:
                    if turn["role"] == UNSURE:
                        turn["role"] = top
                        turn["src"] = "label"
                continue
        out[label] = ""
    return out


def identify(text: str, ask: Callable[[str], Dict[str, Any]],
             student_name: str = "", mentor_name: str = "") -> Dict[str, Any]:
    """完整识别；返回可直接存库的字段。AI 一段也没认出来时 status 为 error。"""
    parsed = parse(text, student_name, mentor_name)
    turns = parsed["turns"]
    if not turns:
        return {"status": "error", "format": "", "turns": [], "labels": {},
                "message": "逐字稿没有内容"}
    needs_ai = any(not t["role"] for t in turns)
    stats = {"ai_set": 0, "failed_windows": 0}
    if needs_ai:
        stats = assign_roles(turns, ask, student_name, mentor_name)
    labels = label_roles(turns) if parsed["format"] == "labelled" else {}
    if needs_ai and stats["ai_set"] == 0:
        return {"status": "error", "format": parsed["format"], "turns": turns,
                "labels": labels, "message": "AI 没能识别发言人，本次按原逐字稿生成"}
    unsure = sum(1 for t in turns if t["role"] == UNSURE)
    message = "%d 段没能确定发言人，已标为待确认" % unsure if unsure else ""
    log.info("m1 speakers: turns=%d ai_set=%d unsure=%d failed_windows=%d format=%s",
             len(turns), stats["ai_set"], unsure, stats["failed_windows"], parsed["format"])
    return {"status": "done", "format": parsed["format"], "turns": turns,
            "labels": labels, "message": message}


def marked_text(turns: List[Dict[str, Any]]) -> str:
    """每段一行：「[时间] 角色：原话」。段号与 turn 的 n 一致。"""
    lines = []
    for turn in turns:
        head = "[%s] " % turn["time"] if turn.get("time") else ""
        lines.append("%s%s：%s" % (head, turn["role"] or UNSURE, turn["text"]))
    return "\n".join(lines)


def role_lookup(turns: List[Dict[str, Any]]) -> Callable[[str], str]:
    """引文 → 发言人：只落在一种角色的段落里时取该角色，否则“待确认”。"""
    from m1.report_checks import normalize, strip_marks

    norms = [(normalize(t["text"]), t["role"] or UNSURE) for t in turns]

    def lookup(quote: str) -> str:
        needle = normalize(strip_marks(quote))
        if not needle:
            return UNSURE
        roles = {role for norm, role in norms if needle in norm}
        return roles.pop() if len(roles) == 1 else UNSURE

    return lookup


# ---------------------------------------------------------------------------
# 与报告、数据库的衔接
# ---------------------------------------------------------------------------
def run_for_report(report: Dict[str, Any], ask: Callable[[str], Dict[str, Any]],
                   actor_id=None) -> Dict[str, Any]:
    from m1 import report_store, store

    prep = store.get_prep(int(report["prep_id"])) or {}
    text = report.get("transcript_text") or ""
    result = identify(text, ask, prep.get("student_name") or "", prep.get("mentor_name") or "")
    report_store.save_speakers(report["id"], transcript_hash=transcript_hash(text),
                               updated_by=actor_id, **result)
    return report_store.get_speakers(report["id"])


def is_current(row: Optional[Dict[str, Any]], report: Dict[str, Any]) -> bool:
    return bool(row) and row["status"] == "done" and \
        row["transcript_hash"] == transcript_hash(report.get("transcript_text") or "")


def for_generation(report: Dict[str, Any], ask: Callable[[str], Dict[str, Any]],
                   actor_id=None) -> Optional[Dict[str, Any]]:
    """生成时用：已有且与逐字稿一致就沿用（包括导师的修改），否则重新识别。失败返回 None。"""
    from m1 import report_store

    row = report_store.get_speakers(report["id"])
    if not is_current(row, report):
        row = run_for_report(report, ask, actor_id)
    return row if is_current(row, report) else None


def analysis_text(report: Dict[str, Any]) -> str:
    """质量检查用的逐字稿：有当前的识别结果就用带角色的版本，否则用原文。"""
    from m1 import report_store

    if "transcript_text" not in report:
        return ""
    row = report_store.get_speakers(report["id"])
    return marked_text(row["turns"]) if is_current(row, report) else report["transcript_text"]


def apply_edits(turns: List[Dict[str, Any]], labels: Dict[str, str],
                by_turn: Dict[int, str]) -> None:
    """导师修改：先按标签整体改，再按段改；改过的段 src 记为 edited。"""
    for turn in turns:
        if turn["label"] and turn["label"] in labels:
            turn["role"] = labels[turn["label"]]
            turn["src"] = "edited"
    for turn in turns:
        if turn["n"] in by_turn:
            turn["role"] = by_turn[turn["n"]]
            turn["src"] = "edited"


def summary(row: Optional[Dict[str, Any]], report: Dict[str, Any]) -> Dict[str, Any]:
    """给审阅页的数据。"""
    if not row:
        return {"status": "none", "format": "", "message": "", "counts": {},
                "labels": [], "turns": []}
    status = row["status"]
    if status == "done" and not is_current(row, report):
        status = "stale"
    turns = row["turns"]
    counts = Counter(t["role"] or UNSURE for t in turns)
    labels = []
    for label, role in (row.get("labels") or {}).items():
        own = [t for t in turns if t["label"] == label]
        labels.append({"label": label, "role": role, "turns": len(own),
                       "samples": [t["text"][:60] for t in own[:2]]})
    return {"status": status, "format": row["format"], "message": row["message"],
            "counts": {role: counts.get(role, 0) for role in ROLES},
            "labels": labels,
            "turns": [{"n": t["n"], "label": t["label"], "time": t.get("time", ""),
                       "role": t["role"] or UNSURE, "src": t["src"], "text": t["text"][:120]}
                      for t in turns]}
