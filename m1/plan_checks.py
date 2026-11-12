"""发展计划的检查项。

内部版检查与家长版检查都是对文档的纯函数，每次保存都重新跑一遍（DP1 §7）。
每个检查项形状固定：``{"id", "level", "path", "label", "text"}``；
``level`` 为 ``review``（需要核对，可跳转）或 ``hint``（其他提示，只看不改）。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from m1 import plan_kb, wb

PROMISE_WORDS = (
    "已经掌握", "显著提升", "稳定做到", "已掌握", "彻底", "解决",
    "问题孩子", "缺陷", "严重", "诊断", "抑郁症", "焦虑症", "多动症", "自闭症",
)
COPY_TEXT = "有一段和 WB 教材原文很像，请改写或确认"

_NAME_STOP = {
    "Lesson", "Student", "Students", "Teacher", "Teachers", "Activity", "Activities",
    "Time", "Materials", "Objective", "Objectives", "Note", "Notes", "Step", "Steps",
    "Guide", "Guides", "Tips", "Summary", "Review", "Practice", "Class", "Classes",
    "Home", "Page", "Pages", "Reference", "References", "Session", "Sessions",
    "The", "This", "That", "These", "Those", "When", "What", "Why", "How",
    "If", "Then", "And", "But", "For", "With", "From", "Your", "Their",
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]*")
_NAME_RE = re.compile(r"\b[A-Z][a-z]{2,}\b")


def _text(value) -> str:
    if isinstance(value, dict):
        value = value.get("text")
    return str(value or "").strip()


def _items() -> List[Dict[str, Any]]:
    return []


def _add(items: List[Dict[str, Any]], level: str, key: str, path: List[Any],
         label: str, text: str) -> None:
    used = {item["id"] for item in items}
    item_id = key
    suffix = 2
    while item_id in used:
        item_id = "%s-%d" % (key, suffix)
        suffix += 1
    items.append({"id": item_id, "level": level, "path": path,
                  "label": label, "text": text})


def _english_words(text: str) -> List[str]:
    return [match.group(0).lower() for match in _WORD_RE.finditer(text or "")]


def _grams(words: List[str], size: int = 6) -> set:
    if len(words) < size:
        return set()
    return {" ".join(words[index:index + size]) for index in range(len(words) - size + 1)}


def _names(text: str) -> List[str]:
    out = []
    for match in _NAME_RE.finditer(text or ""):
        token = match.group(0)
        if token in _NAME_STOP or token.lower() in {word.lower() for word in _NAME_STOP}:
            continue
        if token not in out:
            out.append(token)
    return out


def _copy_hit(activity_text: str, lesson_text: str, lesson_name: str = "") -> bool:
    grams = _grams(_english_words(activity_text))
    if grams and grams & _grams(_english_words(lesson_text)):
        return True
    for name in _names(lesson_text):
        if re.search(r"\b%s\b" % re.escape(name), activity_text or ""):
            return True
    if lesson_name and len(lesson_name) >= 4 and lesson_name.lower() in (activity_text or "").lower():
        return True
    return False


def _session_lessons(plan: Dict[str, Any], session: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not wb.installed():
        return []
    codes = []
    focus = session.get("focus") or {}
    for key in ("primary", "supporting"):
        code = focus.get(key)
        if code:
            codes.append(code)
    wb_ids = []
    for code in codes:
        try:
            for cand in wb.candidates(code, plan.get("wb_grade") or 9) or []:
                if cand.get("wb_id"):
                    wb_ids.append(cand["wb_id"])
        except Exception:
            continue
    for activity in session.get("activities") or []:
        source = activity.get("source") or {}
        if source.get("type") == "world_bank" and source.get("wb_id"):
            wb_ids.append(source["wb_id"])
    lessons = []
    seen = set()
    for wb_id in wb_ids:
        if wb_id in seen:
            continue
        seen.add(wb_id)
        lesson = wb.lesson(wb_id) or {}
        text = wb.lesson_text(wb_id) or ""
        if text:
            lessons.append({"wb_id": wb_id, "text": text, "name": lesson.get("name") or ""})
    return lessons


def _promise_word(text: str) -> Optional[str]:
    for word in PROMISE_WORDS:
        if word in (text or ""):
            return word
    return None


def _activity_text(activity: Dict[str, Any]) -> str:
    return " ".join(_text(activity.get(key)) for key in ("name", "steps", "questions"))


def run_checks(plan: Dict[str, Any], doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """内部版全部检查项：需要核对 + 其他提示。"""
    return internal_review(plan, doc) + internal_hints(plan, doc)


def internal_review(plan: Dict[str, Any], doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = _items()
    if not isinstance(doc, dict):
        return items
    sessions = doc.get("sessions") if isinstance(doc.get("sessions"), list) else []

    for index, session in enumerate(sessions):
        if not isinstance(session, dict):
            continue
        n = int(session.get("n") or index + 1)
        activities = session.get("activities") or []
        lessons = _session_lessons(plan, session)
        for a_index, activity in enumerate(activities):
            if not isinstance(activity, dict):
                continue
            label = "Session %d · Activity %d" % (n, a_index + 1)
            path = ["sessions", index, "activities", a_index]
            text = _activity_text(activity)
            if text and lessons and any(
                    _copy_hit(text, lesson["text"], lesson["name"]) for lesson in lessons):
                _add(items, "review", "copy-s%da%d" % (n, a_index + 1), path, label, COPY_TEXT)

        focus = session.get("focus") if isinstance(session.get("focus"), dict) else {}
        _promise_field(items, focus.get("text"), "Session %d · 教学重点" % n,
                       ["sessions", index, "focus", "text"], "focus-s%d" % n)
        _promise_field(items, session.get("evidence"), "Session %d · 课堂预期表现" % n,
                       ["sessions", index, "evidence"], "evidence-s%d" % n)
        for p_index, practice in enumerate(session.get("practice") or []):
            if not isinstance(practice, dict):
                continue
            _promise_field(items, practice.get("evidence"),
                           "Session %d · 实践 %d 预期证据" % (n, p_index + 1),
                           ["sessions", index, "practice", p_index, "evidence"],
                           "practice-evidence-s%dp%d" % (n, p_index + 1))

    _promise_field(items, doc.get("overview"), "Block Overview · 总体目标",
                   ["overview"], "evidence-overview")
    for goal in plan.get("goals") or []:
        _promise_field(items, goal.get("expected"), "目标 %s · 阶段预期进展" % goal.get("code"),
                       [], "goal-expected-%s" % goal.get("code"))

    for index, session in enumerate(sessions):
        if not isinstance(session, dict):
            continue
        n = int(session.get("n") or index + 1)
        for a_index, activity in enumerate(session.get("activities") or []):
            if not isinstance(activity, dict):
                continue
            # Block Review 的名称、流程与来源都来自 KB 固定内容，不参与缺失/来源核对
            if activity.get("block_review"):
                continue
            source = activity.get("source") if isinstance(activity.get("source"), dict) else {}
            kind = source.get("type")
            wb_id = source.get("wb_id")
            path = ["sessions", index, "activities", a_index, "source"]
            if kind == "world_bank" and not wb.lesson(wb_id):
                _add(items, "review", "wb-missing-s%da%d" % (n, a_index + 1), path,
                     "Session %d · Activity %d · 参考来源" % (n, a_index + 1),
                     "参考来源的 WB 参考课不在资料库里，请重新选择")
            if kind == "other" and not _text(source.get("text")):
                _add(items, "review", "other-empty-s%da%d" % (n, a_index + 1), path,
                     "Session %d · Activity %d · 参考来源" % (n, a_index + 1),
                     "选了其他参考，需要填写来源")

    for index, session in enumerate(sessions):
        if not isinstance(session, dict):
            continue
        n = int(session.get("n") or index + 1)
        if not _text(session.get("title")):
            _add(items, "review", "empty-title-s%d" % n, ["sessions", index, "title"],
                 "Session %d · 标题" % n, "还没有写标题")
        focus = session.get("focus") if isinstance(session.get("focus"), dict) else {}
        if not _text(focus.get("text")):
            _add(items, "review", "empty-focus-s%d" % n,
                 ["sessions", index, "focus", "text"], "Session %d · 教学重点" % n,
                 "还没有写教学重点")
        for a_index, activity in enumerate(session.get("activities") or []):
            if not isinstance(activity, dict):
                continue
            # Block Review 只核对分钟与引导问题；引导问题可以为空
            if activity.get("block_review"):
                continue
            path = ["sessions", index, "activities", a_index]
            if not _text(activity.get("name")):
                _add(items, "review", "empty-activity-name-s%da%d" % (n, a_index + 1), path,
                     "Session %d · Activity %d" % (n, a_index + 1), "活动还没有名称")
            if not _text(activity.get("steps")):
                _add(items, "review", "empty-activity-steps-s%da%d" % (n, a_index + 1), path,
                     "Session %d · Activity %d" % (n, a_index + 1), "活动还没有教学流程")
        if not _text(session.get("evidence")):
            _add(items, "review", "empty-evidence-s%d" % n, ["sessions", index, "evidence"],
                 "Session %d · 课堂预期表现" % n, "还没有写课堂预期表现")
        if not (session.get("practice") or []):
            _add(items, "review", "empty-practice-s%d" % n, ["sessions", index, "practice"],
                 "Session %d · 课后实践" % n, "至少需要一项课后实践")
    return items


def _promise_field(items: List[Dict[str, Any]], value, label: str, path: List[Any],
                   key: str) -> None:
    word = _promise_word(_text(value))
    if word:
        _add(items, "review", "promise-%s" % key, path, label,
             "写了“%s”，只能写课堂里看得到的表现" % word)


def internal_hints(plan: Dict[str, Any], doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = _items()
    if not isinstance(doc, dict):
        return items
    sessions = doc.get("sessions") if isinstance(doc.get("sessions"), list) else []
    primaries = set()
    for session in sessions:
        if not isinstance(session, dict):
            continue
        focus = session.get("focus") if isinstance(session.get("focus"), dict) else {}
        if focus.get("primary"):
            primaries.add(focus.get("primary"))
    for goal in plan.get("goals") or []:
        code = goal.get("code")
        if code and code not in primaries:
            _add(items, "hint", "hint-goal-unused-%s" % code, [],
                 "目标 %s" % code, "没有作为任何一节课的主要目标。")
    for index, session in enumerate(sessions):
        if not isinstance(session, dict):
            continue
        n = int(session.get("n") or index + 1)
        focus = session.get("focus") if isinstance(session.get("focus"), dict) else {}
        if not focus.get("supporting"):
            _add(items, "hint", "hint-supporting-s%d" % n, [],
                 "Session %d" % n, "没有关联辅助目标。")
        total = sum(int(activity.get("minutes") or 0)
                    for activity in session.get("activities") or []
                    if isinstance(activity, dict))
        if total > 90:
            _add(items, "hint", "hint-minutes-s%d" % n, [],
                 "Session %d · 活动时长" % n, "活动总时长 %d 分钟，超过 90 分钟。" % total)
    return items


def _practice_ids(internal_doc: Dict[str, Any]) -> set:
    ids = set()
    for session in (internal_doc or {}).get("sessions") or []:
        for practice in session.get("practice") or []:
            if isinstance(practice, dict) and practice.get("id"):
                ids.add(practice["id"])
    return ids


def _parent_texts(doc: Dict[str, Any]) -> List[str]:
    texts = [_text(doc.get("intro")), _text(doc.get("transition"))]
    for goal in doc.get("goals") or []:
        texts.append(_text(goal.get("text")))
    for session in doc.get("sessions") or []:
        texts.extend([_text(session.get("title")), _text(session.get("summary"))])
    for option in doc.get("practice_options") or []:
        texts.extend([_text(option.get("title")), _text(option.get("text")),
                      _text(option.get("frequency"))])
    for value in doc.get("family") or []:
        texts.append(_text(value))
    for point in doc.get("review") or []:
        texts.extend([_text(point.get("label")), _text(point.get("text"))])
    return [text for text in texts if text]


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _shares_run(outputs: List[str], sources: List[str], size: int = 8) -> bool:
    normalized_sources = [_normalize_space(source) for source in sources]
    for source in normalized_sources:
        if len(source) < size:
            continue
        grams = {source[index:index + size] for index in range(len(source) - size + 1)}
        for text in outputs:
            out = _normalize_space(text)
            if any(out[index:index + size] in grams
                   for index in range(max(0, len(out) - size + 1))):
                return True
    return False


def _parent_sources(plan: Dict[str, Any], internal_doc: Dict[str, Any]) -> List[str]:
    sources = []
    personal = plan.get("personal") or {}
    notes = _text(personal.get("notes"))
    if notes:
        sources.append(notes)
    for item in personal.get("file_texts") or []:
        if isinstance(item, dict):
            sources.append(_text(item.get("text")))
        else:
            sources.append(_text(item))
    mentor = _text((internal_doc or {}).get("mentor_notes"))
    if mentor:
        sources.append(mentor)
    return [source for source in sources if source]


def _parent_limit_items(items: List[Dict[str, Any]], doc: Dict[str, Any]) -> None:
    """家长版超字数的阻断项；上限只来自 ``plan_kb.PARENT_LIMITS``。"""
    limits = plan_kb.PARENT_LIMITS
    sections = plan_kb.parent().get("sections") or []

    def section_name(index: int) -> str:
        if index >= len(sections):
            return ""
        section = sections[index]
        return ("%s %s" % (section.get("no") or "", section.get("title") or "")).strip()

    def over(value, limit: int, section: str, number: int, path: List[Any],
             label: str) -> None:
        text = _text(value)
        if not text or len(text) <= limit:
            return
        _add(items, "blocking",
             "parent-long-%s" % "-".join(str(part) for part in path), path, label,
             "%s · 第 %d 项 · 超过 %d 字，请缩短" % (section, number, limit))

    over(doc.get("intro"), limits["intro"], "开场介绍", 1, ["intro"],
         "家长版 · 开场介绍")
    goals = doc.get("goals") if isinstance(doc.get("goals"), list) else []
    for index, goal in enumerate(goals):
        if isinstance(goal, dict):
            over(goal.get("text"), limits["goal"], section_name(0), index + 1,
                 ["goals", index, "text"],
                 "家长版 · 目标 %s" % (goal.get("code") or index + 1))
    sessions = doc.get("sessions") if isinstance(doc.get("sessions"), list) else []
    for index, session in enumerate(sessions):
        if not isinstance(session, dict):
            continue
        n = session.get("n") or index + 1
        over(session.get("title"), limits["session_title"], section_name(1), index + 1,
             ["sessions", index, "title"], "家长版 · Session %d 标题" % n)
        over(session.get("summary"), limits["session_summary"], section_name(1), index + 1,
             ["sessions", index, "summary"], "家长版 · Session %d 小结" % n)
    over(doc.get("transition"), limits["transition"], section_name(1), len(sessions) + 1,
         ["transition"], "家长版 · 过渡句")
    options = doc.get("practice_options") if isinstance(doc.get("practice_options"), list) else []
    for index, option in enumerate(options):
        if not isinstance(option, dict):
            continue
        for key, label, limit in (("title", "名称", limits["practice_title"]),
                                  ("text", "说明", limits["practice_text"]),
                                  ("frequency", "频率", limits["practice_frequency"])):
            over(option.get(key), limit, section_name(2), index + 1,
                 ["practice_options", index, key],
                 "家长版 · 课后实践 %d %s" % (index + 1, label))
    family = doc.get("family") if isinstance(doc.get("family"), list) else []
    for index, line in enumerate(family):
        over(line, limits["family"], section_name(3), index + 1, ["family", index],
             "家长版 · 家庭协作")
    review = doc.get("review") if isinstance(doc.get("review"), list) else []
    for index, point in enumerate(review):
        if not isinstance(point, dict):
            continue
        over(point.get("label"), limits["review_label"], section_name(4), index + 1,
             ["review", index, "label"], "家长版 · 成长观察")
        over(point.get("text"), limits["review_text"], section_name(4), index + 1,
             ["review", index, "text"], "家长版 · 成长观察")


def parent_blocking(doc: Dict[str, Any], plan: Dict[str, Any],
                    internal_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """家长版必须修完才能确认的检查项。"""
    items = _items()
    if not isinstance(doc, dict):
        _add(items, "blocking", "parent-empty", [], "家长版", "家长版还没有内容")
        return items

    for key, label in (("intro", "开场介绍"), ("transition", "过渡句")):
        if not _text(doc.get(key)):
            _add(items, "blocking", "parent-empty-%s" % key, [key], "家长版 · %s" % label,
                 "还没有写%s" % label)

    goals = plan.get("goals") or []
    doc_goals = doc.get("goals") if isinstance(doc.get("goals"), list) else []
    codes = [goal.get("code") for goal in goals]
    got = [goal.get("code") if isinstance(goal, dict) else None for goal in doc_goals]
    if got != codes:
        _add(items, "blocking", "parent-goal-codes", ["goals"], "家长版 · 目标",
             "家长版目标和已确认目标不一致，请重新生成")
    for index, goal in enumerate(doc_goals):
        if isinstance(goal, dict) and not _text(goal.get("text")):
            _add(items, "blocking", "parent-empty-goal-%d" % index,
                 ["goals", index, "text"], "家长版 · 目标 %s" % (goal.get("code") or ""),
                 "目标说明是空的")

    sessions = doc.get("sessions") if isinstance(doc.get("sessions"), list) else []
    expected_sessions = len((internal_doc or {}).get("sessions") or [])
    if len(sessions) != expected_sessions:
        _add(items, "blocking", "parent-session-count", ["sessions"], "家长版 · 课程小结",
             "课程小结数量和内部版不一致，请重新生成")
    for index, session in enumerate(sessions):
        if not isinstance(session, dict):
            continue
        n = session.get("n") or index + 1
        if not _text(session.get("title")):
            _add(items, "blocking", "parent-empty-session-title-%d" % index,
                 ["sessions", index, "title"], "家长版 · Session %s" % n, "课程标题是空的")
        if not _text(session.get("summary")):
            _add(items, "blocking", "parent-empty-session-summary-%d" % index,
                 ["sessions", index, "summary"], "家长版 · Session %s" % n, "课程小结是空的")

    practice_ids = _practice_ids(internal_doc)
    options = doc.get("practice_options") if isinstance(doc.get("practice_options"), list) else []
    option_by_ref = {}
    for index, option in enumerate(options):
        if not isinstance(option, dict):
            continue
        ref = option.get("ref")
        option_by_ref[ref] = option
        if ref not in practice_ids:
            _add(items, "blocking", "parent-practice-%d" % index,
                 ["practice_options", index], "家长版 · 课后实践",
                 "这项实践不是来自已批准的内部版")
        for key, label in (("title", "实践名称"), ("text", "实践说明"), ("frequency", "频率")):
            if not _text(option.get(key)):
                _add(items, "blocking", "parent-empty-practice-%d-%s" % (index, key),
                     ["practice_options", index, key], "家长版 · %s" % label,
                     "%s是空的" % label)
    picks = doc.get("practice") if isinstance(doc.get("practice"), list) else []
    if not 1 <= len(picks) <= 2:
        _add(items, "blocking", "parent-picks", ["practice"], "家长版 · 已选实践",
             "需要选择 1 至 2 项课后实践")
    for index, ref in enumerate(picks):
        if ref not in practice_ids:
            _add(items, "blocking", "parent-pick-%d" % index, ["practice", index],
                 "家长版 · 已选实践", "选中的实践不是来自已批准的内部版")

    family = doc.get("family") if isinstance(doc.get("family"), list) else []
    if len(family) != 2:
        _add(items, "blocking", "parent-family-count", ["family"], "家长版 · 家庭协作",
             "需要 2 条家庭协作建议")
    for index, value in enumerate(family):
        if not _text(value):
            _add(items, "blocking", "parent-empty-family-%d" % index, ["family", index],
                 "家长版 · 家庭协作", "家庭协作建议是空的")
    seen = doc.get("family_seen") if isinstance(doc.get("family_seen"), list) else []
    for index in range(len(family)):
        if index < len(seen) and seen[index]:
            continue
        _add(items, "blocking", "parent-family-unseen-%d" % index,
             ["family_seen", index], "04 家庭协作 · 第 %d 条" % (index + 1),
             "AI 新写的建议，导出前要导师看过")

    review = doc.get("review") if isinstance(doc.get("review"), list) else []
    if not 2 <= len(review) <= 4:
        _add(items, "blocking", "parent-review-count", ["review"], "家长版 · 成长观察",
             "需要 2 至 4 项成长观察")
    for index, point in enumerate(review):
        if not isinstance(point, dict):
            continue
        for key, label in (("label", "观察标签"), ("text", "观察说明")):
            if not _text(point.get(key)):
                _add(items, "blocking", "parent-empty-review-%d-%s" % (index, key),
                     ["review", index, key], "家长版 · 成长观察", "%s是空的" % label)

    _parent_limit_items(items, doc)

    texts = _parent_texts(doc)
    if _shares_run(texts, _parent_sources(plan, internal_doc), 8):
        _add(items, "blocking", "parent-copied-notes", [], "家长版 · 个性化需求",
             "有一段和个性化需求原文相同，请改写或确认")
    for text in texts:
        word = _promise_word(text)
        if word:
            _add(items, "blocking", "parent-promise-%s" % word, [], "家长版 · 用词",
                 "写了“%s”，请改成课堂里看得到的表现" % word)
    if plan.get("parent_stale"):
        _add(items, "blocking", "parent-stale", [], "家长版",
             "内部版已更改，请先重新生成家长版")
    return items


def _bigrams(text: str) -> set:
    clean = "".join(ch for ch in (text or "") if ch.isalnum())
    return {clean[index:index + 2] for index in range(len(clean) - 1)}


def parent_hints(doc: Dict[str, Any], plan: Dict[str, Any],
                 internal_doc: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """家长版的其他提示：成长观察不要和目标原文重复。"""
    items = _items()
    if not isinstance(doc, dict):
        return items
    goal_grams = []
    for goal in plan.get("goals") or []:
        grams = _bigrams(_text(goal.get("goal")))
        if grams:
            goal_grams.append((goal.get("code"), grams))
    for index, point in enumerate(doc.get("review") or []):
        if not isinstance(point, dict):
            continue
        grams = _bigrams(_text(point.get("text")))
        if not grams:
            continue
        for code, goal in goal_grams:
            if len(grams & goal) / float(len(grams)) > 0.6:
                _add(items, "hint", "hint-review-%d" % index, ["review", index],
                     "家长版 · 成长观察 %d" % (index + 1),
                     "这项成长观察和阶段目标“%s”文字太接近，可以换一个观察角度。" % code)
                break
    return items
