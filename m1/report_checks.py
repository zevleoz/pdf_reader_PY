"""会后报告质量检查（协议 §12）与文本定位工具。

``run_checks(report, version)`` 在生成后和每次保存后都跑一遍，返回检查项列表：

- ``block``  阻止审核通过；
- ``review`` 只提示，不阻止。

检查项格式：``{"level", "code", "message", "path"}``。
"""
from __future__ import annotations

import bisect
import re
import unicodedata
from typing import Any, Dict, Iterator, List, Optional, Tuple

from m1 import report_kb

PLACEHOLDER = "[ai填入]"
SPEAKERS = ("学生", "导师", "家长", "其他", "待确认")
EVIDENCE_TYPES = ("具体行为事件", "主观感受", "自我评价", "假设性回应",
                  "引导下表现", "其他观察")
EVIDENCE_STATUSES = ("已确认", "待核实", "不采用")

FREQUENCY_WORDS = ("经常", "反复", "通常", "总是")
DIAGNOSIS_WORDS = ("抑郁症", "焦虑症", "多动症", "ADHD", "自闭症", "人格障碍",
                   "强迫症", "双相")
META_KEYS = ("student_name", "grade", "school", "y4_date", "meeting_date",
             "report_date", "evidence_sources")

_QUOTE_RES = (re.compile("“([^”]*)”"), re.compile('"([^"]*)"'),
              re.compile("「([^」]*)」"), re.compile("‘([^’]*)’"),
              re.compile("『([^』]*)』"))
_TIME_RE = re.compile(r"(?<!\d)(\d{1,2}:\d{2}(?::\d{2})?)(?!\d)")
_LEAD_MARK_RE = re.compile(r"^\s*[【\[]\s*\d+\s*[】\]]\s*")
_ABILITY_RE = re.compile(r"(?<![A-Za-z0-9])R\d\.\d+(?![0-9])")
_E4_RE = re.compile(r"(?<![A-Za-z0-9])E4(?![A-Za-z0-9])")

NO_MEETING_TEXT = "本次会议未获得相关信息。"
PROCESS_WORDS = ("待核实", "未核实", "证据条目", "证据编号", "数据质量", "零证据",
                 "零会议证据", "quote_verified", "First Touch记录")
INFERENCE_WORDS = ("可能", "看起来", "提示", "还需要了解")


# ---------------------------------------------------------------------------
# 文本定位
# ---------------------------------------------------------------------------
def normalize(text: Any) -> str:
    """比对用：NFKC 后去掉空白、标点、符号和控制字符。"""
    out = []
    for ch in unicodedata.normalize("NFKC", str(text or "")):
        if unicodedata.category(ch)[0] in ("P", "Z", "S", "C"):
            continue
        out.append(ch.lower())
    return "".join(out)


def strip_marks(quote: Any) -> str:
    """去掉模型有时带上的行首段号标记。"""
    return _LEAD_MARK_RE.sub("", str(quote or "")).strip()


def split_paragraphs(text: str) -> List[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def time_mark(paragraph: str) -> str:
    match = _TIME_RE.search(paragraph or "")
    return match.group(1) if match else ""


class TextIndex:
    """把一份文本按段落归一化后拼起来，支持定位引文所在段落。"""

    def __init__(self, text: str):
        self.paragraphs = split_paragraphs(text)
        self._starts: List[int] = []
        self.norms: List[str] = []
        parts = []
        position = 0
        for paragraph in self.paragraphs:
            norm = normalize(paragraph)
            self.norms.append(norm)
            self._starts.append(position)
            parts.append(norm)
            position += len(norm)
        self._lengths = [len(part) for part in parts]
        self.joined = "".join(parts)

    def contains(self, quote: Any) -> bool:
        needle = normalize(strip_marks(quote))
        return bool(needle) and needle in self.joined

    def position(self, quote: Any) -> Optional[int]:
        """引文所在段落的从 0 起的序号；找不到返回 None。"""
        needle = normalize(strip_marks(quote))
        if not needle:
            return None
        found = self.joined.find(needle)
        if found < 0:
            return None
        index = bisect.bisect_right(self._starts, found) - 1
        while index > 0 and self._lengths[index] == 0:
            index -= 1
        return max(index, 0)

    def locate(self, quote: Any) -> Optional[Tuple[int, str]]:
        """返回 ``(段号从 1 起, 该段时间标记)``；找不到返回 None。"""
        index = self.position(quote)
        if index is None:
            return None
        return index + 1, time_mark(self.paragraphs[index])

    def paragraph(self, index: int) -> str:
        if 0 <= index < len(self.paragraphs):
            return self.paragraphs[index]
        return ""

    def previous(self, index: int) -> str:
        return self.paragraph(index - 1)


# ---------------------------------------------------------------------------
# 文档遍历
# ---------------------------------------------------------------------------
def field_text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("text")
    return value.strip() if isinstance(value, str) else ""


def abilities_in(doc: Dict[str, Any]) -> Iterator[Tuple[str, str, Dict[str, Any]]]:
    for dim_id, dim in ((doc or {}).get("dims") or {}).items():
        for code, row in ((dim or {}).get("abilities") or {}).items():
            yield dim_id, code, (row if isinstance(row, dict) else {})


def family_fields(doc: Dict[str, Any]) -> Iterator[Tuple[list, str]]:
    """会出现在家庭版里的文字字段（不含 meta 与 internal_note）。"""
    doc = doc or {}
    for dim_id, dim in (doc.get("dims") or {}).items():
        dim = dim or {}
        for key in ("core_finding", "context_notes"):
            yield ["dims", dim_id, key], field_text(dim.get(key))
        for code, row in (dim.get("abilities") or {}).items():
            row = row if isinstance(row, dict) else {}
            for key in ("other_clues", "meeting"):
                yield ["dims", dim_id, "abilities", code, key], field_text(row.get(key))
    for dim_id, value in (doc.get("portrait") or {}).items():
        yield ["portrait", dim_id], field_text(value)
    for key, row in (doc.get("findings") or {}).items():
        row = row if isinstance(row, dict) else {}
        for sub in ("finding", "meaning"):
            yield ["findings", key, sub], field_text(row.get(sub))
    for index, row in enumerate(doc.get("plan") or []):
        row = row if isinstance(row, dict) else {}
        for sub in ("goal", "mentor", "family", "evidence"):
            yield ["plan", index, sub], field_text(row.get(sub))
    yield ["review_advice"], field_text(doc.get("review_advice"))


def quote_fields(doc: Dict[str, Any]) -> Iterator[Tuple[list, str]]:
    """引文必须可核实的字段：家庭版里的全部文字字段。"""
    yield from family_fields(doc)


def quotes_in(text: str) -> List[str]:
    found = []
    for pattern in _QUOTE_RES:
        found.extend(m.group(1).strip() for m in pattern.finditer(text or ""))
    return [q for q in found if normalize(q)]


def is_usable(item: Dict[str, Any]) -> bool:
    return item.get("status") != "不采用"


def supports_judgement(item: Dict[str, Any]) -> bool:
    """能支持综合判断：未被弃用，且引文核实过或导师已确认。"""
    if item.get("status") == "不采用":
        return False
    return bool(item.get("quote_verified")) or item.get("status") == "已确认"


_MENTOR_LABEL_RE = re.compile(
    r"^\W*(?:\d{1,2}:\d{2}(?::\d{2})?\W*)?(导师|老师|mentor)\s*"
    r"(?:\d{1,2}:\d{2}(?::\d{2})?\s*)?[：:]", re.IGNORECASE)
_EVIDENCE_ID_RE = re.compile(r"(?<![A-Za-z0-9])e\d+(?![A-Za-z0-9])")
_Y4_CODE_RE = re.compile(r"(?<!\d)\d{3}(?!\d)")


def is_mentor_line(paragraph: Any) -> bool:
    """这一段是否以导师标签开头。"""
    return bool(_MENTOR_LABEL_RE.match(str(paragraph or "")))


def mentor_labelled(index: "TextIndex", quote: Any) -> bool:
    """引文所在的逐字稿段落是否以导师标签开头（跨段返回 False）。"""
    needle = normalize(strip_marks(quote))
    if not needle:
        return False
    for paragraph, norm in zip(index.paragraphs, index.norms):
        if needle in norm:
            return is_mentor_line(paragraph)
    return False


def items_for(evidence: List[Dict[str, Any]], code: str, *, source: str = "") -> List[Dict[str, Any]]:
    return [e for e in evidence or []
            if code in (e.get("ability_codes") or [])
            and (not source or e.get("source") == source)]


def _check(level: str, code: str, message: str, path: Optional[list] = None) -> Dict[str, Any]:
    return {"level": level, "code": code, "message": message, "path": path or []}


def _first_touch_text(report: Dict[str, Any]) -> str:
    try:
        from m1 import sources, store
        prep = store.get_prep(report.get("prep_id") or 0)
        if not prep:
            return ""
        return str(sources._first_touch(prep["student_id"]).get("text") or "")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 检查
# ---------------------------------------------------------------------------
def run_checks(report: Dict[str, Any], version: Optional[Dict[str, Any]], *,
               first_touch_text: Optional[str] = None) -> List[Dict[str, Any]]:
    version = version or {}
    doc = version.get("doc") or {}
    evidence = version.get("evidence") or []
    ratings = version.get("y4_ratings") or {}
    manifest = version.get("manifest") or {}
    transcript = report.get("transcript_text") or ""
    out: List[Dict[str, Any]] = []

    ability_names = report_kb.ability_map()
    dims_in_doc = (doc.get("dims") or {}) if isinstance(doc, dict) else {}

    # --- block: 结构 -----------------------------------------------------
    for code, info in ability_names.items():
        dim = dims_in_doc.get(info["dim"]) or {}
        row = (dim.get("abilities") or {}).get(code)
        if not isinstance(row, dict):
            out.append(_check("block", "missing_ability",
                              "%s %s：报告中缺少这项能力" % (code, info["name"]),
                              ["dims", info["dim"], "abilities", code]))
            continue
        tags = row.get("tags")
        path = ["dims", info["dim"], "abilities", code, "tags"]
        if not tags:
            out.append(_check("block", "no_tag",
                              "%s %s：还没有综合判断标签" % (code, info["name"]), path))
        else:
            problem = report_kb.tags_problem(tags)
            if problem:
                out.append(_check("block", "tag_invalid",
                                  "%s：%s" % (code, problem), path))

    # --- block: 空字段与占位符 --------------------------------------------
    required: List[Tuple[list, str]] = []
    for dim_id in report_kb.dim_ids():
        required.append((["dims", dim_id, "core_finding"], "%s 本维度当前核心发现" % dim_id))
        required.append((["portrait", dim_id], "%s 四维综合画像" % dim_id))
    for code, info in ability_names.items():
        row = ((dims_in_doc.get(info["dim"]) or {}).get("abilities") or {}).get(code) or {}
        required.append((["dims", info["dim"], "abilities", code, "meeting"],
                         "%s 首次会议核实情况" % code))
        if not row.get("y4_selected"):          # 有 Y4 行时，线索栏可以只有 Y4
            required.append((["dims", info["dim"], "abilities", code, "other_clues"],
                             "%s Y4 与其他线索" % code))
    for key in ("resources", "needs", "open"):
        for sub, label in (("finding", "关键发现"), ("meaning", "发展意义")):
            required.append((["findings", key, sub], "关键发展发现·%s·%s" % (key, label)))
    required.append((["review_advice"], "阶段回顾建议"))

    def lookup(path: list) -> str:
        node: Any = doc
        for step in path:
            if isinstance(node, dict):
                node = node.get(step)
            else:
                return ""
        return field_text(node)

    for path, label in required:
        if not lookup(path):
            out.append(_check("block", "field_empty", "%s 为空" % label, path))
    plan = doc.get("plan") if isinstance(doc, dict) else None
    if not isinstance(plan, list) or not (1 <= len(plan) <= 3):
        out.append(_check("block", "field_empty", "阶段成长与支持方案需要 1 到 3 项", ["plan"]))
    else:
        for index, row in enumerate(plan):
            row = row if isinstance(row, dict) else {}
            if row.get("ability") not in ability_names:
                out.append(_check("block", "field_empty",
                                  "方案第 %d 项缺少有效的 R4 发展重点" % (index + 1),
                                  ["plan", index, "ability"]))
            for sub, label in (("goal", "阶段目标"), ("mentor", "导师支持方式"),
                               ("family", "家庭支持方式"), ("evidence", "成长证据与回顾")):
                if not field_text(row.get(sub)):
                    out.append(_check("block", "field_empty",
                                      "方案第 %d 项的%s为空" % (index + 1, label),
                                      ["plan", index, sub]))
    placeholder_paths = [path for path, text in family_fields(doc) if PLACEHOLDER in text]
    placeholder_paths += [["meta", key] for key, value in (doc.get("meta") or {}).items()
                          if PLACEHOLDER in field_text(value)]
    for path in placeholder_paths:
        out.append(_check("block", "field_empty", "仍有未处理的 %s" % PLACEHOLDER, path))

    # --- block: 逐字稿与引文 ----------------------------------------------
    if not transcript.strip():
        out.append(_check("block", "no_transcript", "没有 M1 会议逐字稿"))
    ft_text = _first_touch_text(report) if first_touch_text is None else first_touch_text
    transcript_index = TextIndex(transcript)
    ft_index = TextIndex(ft_text)
    tag_names = set(report_kb.tag_names())
    seen_quote_problem = set()
    for path, text in quote_fields(doc):
        for quote in quotes_in(text):
            norm = normalize(quote)
            if quote in tag_names:
                continue
            if not (transcript_index.contains(quote) or ft_index.contains(quote)):
                # 已核验的非会议证据（如家长补充）：证据提取时已对照它自己的资料核验过
                if norm and any(norm in normalize(e.get("quote"))
                                for e in evidence
                                if supports_judgement(e) and e.get("source") != "M1"):
                    continue
                if path[:1] in (["plan"], ["review_advice"]):
                    # 方案里的建议用语是提议，不是对学生原话的陈述
                    out.append(_check("review", "quote_unverified",
                                      "%s：建议用语带引号，请确认不是在引用学生原话"
                                      % _where(path), path))
                    continue
                out.append(_check("block", "quote_unverified",
                                  "%s：引用在逐字稿中找不到" % _where(path), path))
                continue
            key = (tuple(path), norm)
            # 证据引文被家庭版引文包含时，至少要占家庭版引文一半的长度：
            # 否则一个“你”这样的单字就能替一句导师的话挡下 quote_speaker。
            matches = [e for e in evidence
                       if normalize(e.get("quote")) and (
                           normalize(e.get("quote")) in norm
                           and len(normalize(e.get("quote"))) >= len(norm) / 2
                           or norm in normalize(e.get("quote")))]
            live = [e for e in matches if e.get("status") != "不采用"]
            problem = None
            if matches and not live:
                problem = ("block", "quote_speaker", "%s：引用的证据已标记为不采用")
            elif live and all(e.get("speaker") in ("待确认", "导师") for e in live):
                problem = ("block", "quote_speaker",
                           "%s：引用的发言人是导师或待确认，不能当作学生原话")
            elif not matches:
                if transcript_index.contains(quote) and mentor_labelled(transcript_index, quote):
                    problem = ("block", "quote_speaker",
                               "%s：引用在逐字稿中标注为导师，不能当作学生原话")
                elif _field_src(doc, path) == "edited":
                    problem = ("review", "quote_no_evidence", "%s：引用没有对应的证据条目")
                else:
                    problem = ("block", "quote_no_evidence", "%s：引用没有对应的证据条目")
            if problem:
                if key in seen_quote_problem:
                    continue
                seen_quote_problem.add(key)
                out.append(_check(problem[0], problem[1], problem[2] % _where(path), path))

    for dim_id, code, row in abilities_in(doc):
        tags = row.get("tags") or []
        if "确认发展需求" in tags:
            used = [e for e in items_for(evidence, code, source="M1") if is_usable(e)]
            if used and not any(supports_judgement(e) and e.get("speaker") not in ("待确认", "导师")
                                for e in used):
                out.append(_check("block", "need_speaker",
                                  "%s：确认发展需求只依据发言人待确认的内容" % code,
                                  ["dims", dim_id, "abilities", code, "tags"]))

    # --- block: 附录、旧模型、安全 ------------------------------------------
    for row in report_kb.appendix(doc):
        if report_kb.scene(row["code"]) is None:
            out.append(_check("block", "scene_missing",
                              "%s：附录场景原文待导入" % row["code"], ["appendix", row["code"]]))
    for path, text in family_fields(doc):
        if _E4_RE.search(text):
            out.append(_check("block", "old_model", "%s：出现 E4" % _where(path), path))
        bad = [c for c in _ABILITY_RE.findall(text) if c not in ability_names]
        if bad:
            out.append(_check("block", "old_model",
                              "%s：出现不属于 18 项的能力编号 %s" % (_where(path), "、".join(sorted(set(bad)))),
                              path))
    for index, row in enumerate(plan if isinstance(plan, list) else []):
        code = (row or {}).get("ability") if isinstance(row, dict) else None
        if isinstance(code, str) and code not in ability_names and _ABILITY_RE.fullmatch(code):
            out.append(_check("block", "old_model",
                              "方案第 %d 项的能力编号 %s 不属于 18 项" % (index + 1, code),
                              ["plan", index, "ability"]))
    if (report.get("safety") or []) and not report.get("safety_ack_at"):
        out.append(_check("block", "safety_unacked", "有安全提示尚未确认"))

    # --- review ------------------------------------------------------------
    for dim_id, code, row in abilities_in(doc):
        for y4_code in row.get("y4_selected") or []:
            entry = ratings.get(y4_code)
            if entry is None or entry.get("state") == "check":
                out.append(_check("review", "y4_check",
                                  "%s：所选 Y4 指标 %s 需要核实" % (code, y4_code),
                                  ["dims", dim_id, "abilities", code, "y4_selected"]))
        meeting = field_text(row.get("meeting"))
        if any(word in meeting for word in FREQUENCY_WORDS):
            used = [e for e in items_for(evidence, code, source="M1") if supports_judgement(e)]
            if len(used) < 2:
                out.append(_check("review", "frequency_word",
                                  "%s：会议证据不足 2 条，却使用了频率用词" % code,
                                  ["dims", dim_id, "abilities", code, "meeting"]))
    for dim_id, code, row in abilities_in(doc):
        tags = row.get("tags") or []
        apath = ["dims", dim_id, "abilities", code, "tags"]
        sup = [e for e in items_for(evidence, code) if supports_judgement(e)]
        sup_m1 = [e for e in sup if e.get("source") == "M1"]
        positive = [e for e in sup if e.get("type") != "假设性回应"]
        if len(tags) >= 2 and len(sup) < 2:
            out.append(_check("review", "double_tag_evidence",
                              "%s：双标签只有 %d 条可支持判断的证据" % (code, len(sup)), apath))
        if "确认发展需求" in tags and not any(
                e.get("type") == "具体行为事件" and e.get("speaker") not in ("待确认", "导师")
                for e in sup_m1):
            out.append(_check("review", "tag_evidence",
                              "%s：确认发展需求缺少发言人明确的会议具体行为事件" % code, apath))
        if "积极资源" in tags and not positive:
            out.append(_check("review", "tag_evidence",
                              "%s：积极资源缺少可支持判断的证据" % code, apath))
        if "暂未发现" in tags and not sup_m1:
            out.append(_check("review", "tag_evidence",
                              "%s：暂未发现缺少可支持判断的会议证据" % code, apath))
        meeting = field_text(row.get("meeting"))
        if meeting in ("", NO_MEETING_TEXT) and any(
                supports_judgement(e) and e.get("source") == "M1"
                for e in items_for(evidence, code)):
            out.append(_check("review", "meeting_unused",
                              "%s：有会议证据，但首次会议核实情况为空" % code,
                              ["dims", dim_id, "abilities", code, "meeting"]))
    for path, text in family_fields(doc):
        if _EVIDENCE_ID_RE.search(text):
            out.append(_check("block", "family_evidence_id",
                              "%s：家庭版文字里出现证据编号" % _where(path), path))
    for path, text in family_fields(doc):
        if any(c in ratings for c in _Y4_CODE_RE.findall(text)):
            out.append(_check("review", "family_code",
                              "%s：家庭版文字里出现 Y4 指标编号" % _where(path), path))
    for path, text in family_fields(doc):
        hits = [w for w in PROCESS_WORDS if w in text]
        if hits:
            out.append(_check("review", "process_word",
                              "%s：出现系统或流程用语 %s" % (_where(path), "、".join(hits)), path))
    for path, text in family_fields(doc):
        hits = [w for w in DIAGNOSIS_WORDS if w in text]
        if hits:
            out.append(_check("review", "diagnosis_word",
                              "%s：出现诊断类用词 %s" % (_where(path), "、".join(hits)), path))

    # --- block: 事实核对标记（W5 §5、S2-P6 §10） ---------------------------
    guard = doc.get("guard") if isinstance(doc, dict) else None
    guard = guard if isinstance(guard, dict) else {}
    acked = {tuple(p) for p in (doc.get("guard_ack") or []) if isinstance(p, list)}
    for flag in guard.get("flags") or []:
        path = flag.get("path") if isinstance(flag, dict) else None
        if not isinstance(path, list) or not path or tuple(path) in acked:
            continue
        if _field_src(doc, path) != "ai":
            continue
        sentence = str(flag.get("sentence") or "").strip()
        problem = str(flag.get("problem") or "这句在资料中找不到依据").strip()
        message = "%s：%s" % (_where(path), problem)
        if sentence:
            message += "（%s）" % sentence
        out.append(_check("block", "fact_unsupported", message, path))
    if guard.get("status") != "checked":
        out.append(_check("block", "fact_unchecked", "部分内容未完成事实核对，请人工核对。"))

    for number in manifest.get("chunk_failed") or []:
        try:
            number = int(number)
        except (TypeError, ValueError):
            continue
        out.append(_check("block", "chunk_failed",
                          "逐字稿第 %d 段未能读取，请查看原文或重新生成。" % number))
    meta = doc.get("meta") if isinstance(doc, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    for key in META_KEYS:
        if not field_text(meta.get(key)):
            out.append(_check("review", "meta_blank", "封面信息 %s 为空" % key, ["meta", key]))
    name = field_text(meta.get("student_name"))
    if name and transcript.strip():
        names = [name]
        if len(name) >= 3:
            names.append(name[1:])
        if not any(normalize(n) in transcript_index.joined for n in names):
            out.append(_check("review", "name_absent",
                              "逐字稿中没有出现学生姓名，请确认文件是否正确",
                              ["meta", "student_name"]))
    for item in manifest.get("adjustments") or []:
        if isinstance(item, dict):
            out.append(_check("review", "code_adjusted", item.get("message") or "",
                              item.get("path") or []))
    return out


def _field_src(doc: Dict[str, Any], path: list) -> str:
    node: Any = doc
    for step in path:
        try:
            node = node[step]
        except (KeyError, IndexError, TypeError):
            return ""
    return str(node.get("src") or "") if isinstance(node, dict) else ""


def _where(path: list) -> str:
    if path[:1] == ["dims"] and "abilities" in path:
        return str(path[path.index("abilities") + 1])
    if path[:1] == ["dims"]:
        return str(path[1])
    return ".".join(str(p) for p in path)


def blocking(checks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [c for c in checks if c.get("level") == "block"]
