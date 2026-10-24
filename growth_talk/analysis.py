"""Growth Talk 分析纯逻辑（移植自 first-touch lib/growth-talk-*.ts）。"""
from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.error
import urllib.request

from . import prompts
from .upload import UploadError

GROWTH_TALK_LIMITS = prompts.GROWTH_TALK_LIMITS

DASHSCOPE_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_DEFAULT_MODEL = "qwen-plus"

_SUBJECT_CANDIDATES = ["语文", "数学", "英语", "道法", "体育", "美术", "音乐", "艺术", "生物", "化学", "物理", "历史", "地理"]
_SOCIAL_CANDIDATES = [
    ("课业负担", re.compile(r"课太多|作业太多|课业负担")),
    ("学校饭菜", re.compile(r"饭菜太难吃|学校饭菜|食堂饭菜")),
]

_RELEVANT_TERMS = [
    "兴趣", "喜欢", "擅长", "活动", "经历", "项目", "passion project",
    "探索", "创作", "设计", "游戏", "服装", "时尚", "探店", "美食",
]
_EXCLUDED_TERMS = [
    "转学", "插班", "考试", "升学", "路径", "课程体系", "课程内容",
    "寄宿", "igcse", "ib", "alevel", "a-level", "学校选择",
]
_EXCLUDED_INTEREST_TOPIC_PATTERNS = [
    re.compile(r"(?:社交化|社交式|结伴|陪伴|同伴)学习"),
    re.compile(r"^学习(?:方式|习惯|方法|偏好)$"),
    re.compile(r"(?:学校|校园|课程)?项目经历"),
    re.compile(r"^capstone(?:项目|project)?(?:经历|经验)?$"),
    re.compile(r"(?:学业|升学|教育)(?:路径|规划|路线)"),
    re.compile(r"(?:转学|插班|升学|择校|学校选择)"),
    re.compile(r"(?:课程体系|课程选择)"),
]
_CAREER_FIELDS = (
    ("career_interests", "careerInterests", "职业兴趣"),
    ("ability_tendencies", "abilityTendencies", "能力倾向"),
    ("value_preferences", "valuePreferences", "价值偏好"),
)


class AnalysisError(RuntimeError):
    """LLM 调用或结果校验失败。"""


def character_length(value: str) -> int:
    return len(value)


def validate_suggestion_lengths(title: str, introduction: str, growth_value: str) -> None:
    if not title or not introduction or not growth_value:
        raise ValueError("建议内容不能为空")
    if len(title) > GROWTH_TALK_LIMITS["suggestion_title"]:
        raise ValueError(f"建议标题须为 1–{GROWTH_TALK_LIMITS['suggestion_title']} 字")
    if len(introduction) > GROWTH_TALK_LIMITS["suggestion_introduction"]:
        raise ValueError(f"建议内容须为 1–{GROWTH_TALK_LIMITS['suggestion_introduction']} 字")
    if len(growth_value) > GROWTH_TALK_LIMITS["suggestion_growth_value"]:
        raise ValueError(f"成长价值须为 1–{GROWTH_TALK_LIMITS['suggestion_growth_value']} 字")


# ---------------------------------------------------------------------------
# LLM 调用
# ---------------------------------------------------------------------------
def _api_key() -> str:
    key = os.environ.get("FT_LLM_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
    if key:
        return key.strip()
    # extract 是重模块，按需导入，避免拖慢应用启动
    from extract import DEFAULT_DASHSCOPE_KEY
    return (DEFAULT_DASHSCOPE_KEY or "").strip()


def model_name() -> str:
    return os.environ.get("FT_LLM_MODEL") or DASHSCOPE_DEFAULT_MODEL


def call_model(prompt: str) -> dict:
    key = _api_key()
    if not key:
        raise AnalysisError("AI 服务未配置（DASHSCOPE_API_KEY），请联系管理员")
    base_url = (os.environ.get("FT_LLM_BASE_URL") or DASHSCOPE_DEFAULT_BASE_URL).rstrip("/")
    body = {
        "model": model_name(),
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": prompts.GROWTH_TALK_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        response = urllib.request.urlopen(request, timeout=90)
        raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise AnalysisError(f"AI 服务密钥无效或无权限（{exc.code}）")
        if exc.code == 429:
            raise AnalysisError("AI 服务繁忙，请稍后重试")
        raise AnalysisError(f"画像分析服务返回 {exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AnalysisError(f"画像分析服务连接失败：{exc}") from exc

    payload = json.loads(raw.decode("utf-8"))
    choices = payload.get("choices") if isinstance(payload, dict) else None
    choice = (choices or [{}])[0]
    if isinstance(choice, dict) and choice.get("finish_reason") == "length":
        raise AnalysisError("画像分析结果超过长度限制，请缩短原始资料后重试")
    content = ""
    if isinstance(choice, dict):
        message = choice.get("message")
        if isinstance(message, dict):
            content = message.get("content") or ""
    return json.loads(content or "{}")


# ---------------------------------------------------------------------------
# 基础归一化 / 校验
# ---------------------------------------------------------------------------
def _as_text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _as_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_as_text(item) for item in value if isinstance(item, str) and _as_text(item)]


def _as_score(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and 0 <= value <= 3:
        return value
    return None


def _as_topic_type(value) -> str:
    return value if value in ("subject", "social") else "interest"


def topic_key(label: str) -> str:
    return re.sub(
        r"[\s·•_—–\-/（）()【】\[\]《》“”\"'：:，,。.!！?？]+",
        "",
        unicodedata.normalize("NFKC", label or "").lower(),
    )


def normalize_interest_topic(value) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\s·•_—–\-/（）()]+", "",
                  unicodedata.normalize("NFKC", value).lower())


def is_excluded_interest_topic(*values) -> bool:
    normalized = [normalize_interest_topic(value) for value in values]
    return any(
        pattern.search(value)
        for value in normalized if value
        for pattern in _EXCLUDED_INTEREST_TOPIC_PATTERNS
    )


def contains_excluded_growth_talk_content(*values) -> bool:
    normalized = " ".join(
        value for value in values if isinstance(value, str)
    ).lower()
    return any(term in normalized for term in _EXCLUDED_TERMS)


def validate_editable_interest_label(value) -> str:
    if not isinstance(value, str):
        raise ValueError("兴趣词条格式无效")
    label = value.strip()
    if not label or len(label) > 120:
        raise ValueError("兴趣词条须为 1–120 字")
    if is_excluded_interest_topic(label):
        raise ValueError("兴趣词条只能保留兴趣、活动经历或 Passion Project 相关主题")
    return label


def validate_editable_meeting_summary(value) -> str:
    if not isinstance(value, str):
        raise ValueError("会议整体总结格式无效")
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    limit = GROWTH_TALK_LIMITS["meeting_summary"]
    if not text or len(text) > limit:
        raise ValueError(f"会议整体总结须为 1–{limit} 字")
    if contains_excluded_growth_talk_content(text):
        raise ValueError("会议整体总结只能保留兴趣、活动经历和 Passion Project 相关内容")
    return text


# ---------------------------------------------------------------------------
# 会议总结 / 主题兜底
# ---------------------------------------------------------------------------
def interest_only_meeting_summary(value) -> str:
    if not isinstance(value, str):
        return ""
    clauses = [
        clause.strip()
        for clause in re.split(r"[。！？；\n]+", re.sub(r"\s+", " ", value))
        if clause.strip()
    ]
    clauses = [
        clause for clause in clauses
        if any(term in clause.lower() for term in _RELEVANT_TERMS)
        and not contains_excluded_growth_talk_content(clause)
    ]
    return "；".join(clauses) + "。" if clauses else "本次会议暂未整理出可确认的兴趣、活动或 Passion Project 信息。"


def meeting_summary_with_overview(value, _student_name=None, topics=None) -> str:
    topics = topics if isinstance(topics, list) else []
    summary = re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else ""
    overview = "本次会议主要围绕兴趣与经历展开。"
    if not summary:
        return overview
    detail = summary[len(overview):].strip() if summary.startswith(overview) else (
        re.sub(r"^本次会议", "", summary).strip() if summary.startswith("本次会议") else summary
    )
    if not detail:
        return overview

    clauses = [clause.strip() for clause in re.split(r"(?<=[。！？；])", detail) if clause.strip()]
    ranked = []
    for index, topic in enumerate(topics):
        if not isinstance(topic, dict):
            continue
        labels = [
            value.strip() for value in (topic.get("label"), topic.get("subtopic"))
            if isinstance(value, str) and len(value.strip()) > 1
        ]
        labels.sort(key=len, reverse=True)
        if not labels:
            continue
        evidence = topic.get("evidence")
        evidence_length = len(evidence) if isinstance(evidence, str) else 0
        mentions = sum(detail.count(label) for label in labels)
        ranked.append({"index": index, "labels": labels,
                       "score": evidence_length + mentions * 20})
    ranked.sort(key=lambda item: (-item["score"], item["index"]))
    ranked = ranked[:2]

    if not ranked or len(clauses) <= 2:
        return f"{overview}{detail}"
    focused = []
    for clause in clauses:
        if any(label in clause for topic in ranked for label in topic["labels"]):
            if clause not in focused:
                focused.append(clause)
    focused_text = "".join(focused[:4]) if focused else "".join(clauses[:2])
    if not re.search(r"[。！？]$", focused_text):
        focused_text = re.sub(r"[；，、]+$", "", focused_text) + "。"
    return f"{overview}{focused_text}"


def _topic_value(label: str, topic_type: str, evidence: str) -> dict:
    return {
        "label": label, "topicType": topic_type, "subtopic": None,
        "evidence": evidence, "sourceRound": "会议原文",
        "evidenceStrength": None, "uncertainty": None,
        "preferenceScore": None, "competenceScore": None,
    }


def _evidence_around(content: str, index: int, label: str) -> str:
    start_boundary = max(
        content.rfind("\n", 0, index + 1),
        content.rfind("。", 0, index + 1),
        content.rfind("？", 0, index + 1),
        content.rfind("！", 0, index + 1),
    )
    end_candidates = [
        position for position in (
            content.find("\n", index + len(label)),
            content.find("。", index + len(label)),
            content.find("？", index + len(label)),
            content.find("！", index + len(label)),
        ) if position >= 0
    ]
    end = min(end_candidates) if end_candidates else len(content)
    text = content[max(0, start_boundary + 1):min(len(content), end + 1)].strip()[:240]
    return text or f"会议中提到{label}"


def extract_meeting_candidate_fallbacks(content: str) -> list[dict]:
    if not content.strip():
        return []
    rows = []
    for label in _SUBJECT_CANDIDATES:
        index = content.find(label)
        if index >= 0:
            rows.append(_topic_value(label, "subject", _evidence_around(content, index, label)))
    for label, pattern in _SOCIAL_CANDIDATES:
        match = pattern.search(content)
        if match:
            rows.append(_topic_value(label, "social",
                                     _evidence_around(content, match.start(), match.group(0))))
    return rows


def _append_distinct(current, next_value, separator: str):
    if not next_value:
        return current
    if not current:
        return next_value
    values = [value.strip() for value in current.split(separator) if value.strip()]
    return current if next_value in values else f"{current}{separator}{next_value}"


def _stronger_evidence(current, next_value):
    rank = {"弱": 1, "中": 2, "强": 3}
    if not next_value:
        return current
    if not current or rank.get(next_value, 0) > rank.get(current, 0):
        return next_value
    return current


def normalize_meeting_topics(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    merged: dict[str, dict] = {}
    preference_scores: dict[str, set] = {}
    competence_scores: dict[str, set] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        row = item
        label = _as_text(row.get("label"))
        evidence = _as_text(row.get("evidence"))
        topic_type = _as_topic_type(row.get("topicType"))
        if not label or not evidence or (
            topic_type == "interest" and is_excluded_interest_topic(label, row.get("subtopic"))
        ):
            continue
        key = topic_key(label)
        if not key:
            continue
        next_value = {
            "label": label,
            "topicType": topic_type,
            "subtopic": _as_text(row.get("subtopic")) or None,
            "evidence": evidence,
            "sourceRound": _as_text(row.get("sourceRound")) or None,
            "evidenceStrength": _as_text(row.get("evidenceStrength")) or None,
            "uncertainty": _as_text(row.get("uncertainty")) or None,
            "preferenceScore": _as_score(row.get("preferenceScore")),
            "competenceScore": _as_score(row.get("competenceScore")),
        }
        if next_value["preferenceScore"] is not None:
            preference_scores.setdefault(key, set()).add(next_value["preferenceScore"])
        if next_value["competenceScore"] is not None:
            competence_scores.setdefault(key, set()).add(next_value["competenceScore"])
        current = merged.get(key)
        if not current:
            merged[key] = next_value
            continue
        current["subtopic"] = _append_distinct(current["subtopic"], next_value["subtopic"], "、")
        current["evidence"] = _append_distinct(current["evidence"], next_value["evidence"], "；") or current["evidence"]
        current["sourceRound"] = _append_distinct(current["sourceRound"], next_value["sourceRound"], "、")
        current["evidenceStrength"] = _stronger_evidence(current["evidenceStrength"], next_value["evidenceStrength"])
        current["uncertainty"] = _append_distinct(current["uncertainty"], next_value["uncertainty"], "；")

    result = []
    for key, topic in merged.items():
        preference = preference_scores.get(key, set())
        competence = competence_scores.get(key, set())
        result.append({
            **topic,
            "preferenceScore": next(iter(preference)) if len(preference) == 1 else None,
            "competenceScore": next(iter(competence)) if len(competence) == 1 else None,
        })
    return result


def select_additional_meeting_topics(existing, value) -> list[dict]:
    seen = {
        topic_key(item.get("label", "")) for item in existing
        if isinstance(item, dict)
    }
    seen.discard("")
    selected = []
    for topic in normalize_meeting_topics(value):
        key = topic_key(topic["label"])
        if not key or key in seen:
            continue
        seen.add(key)
        selected.append(topic)
    return selected


# ---------------------------------------------------------------------------
# 象限 / 建议 / 职业画像 / Copilot
# ---------------------------------------------------------------------------
def quadrant_zone(preference_score: int, competence_score: int) -> str:
    preference_labels = ["不喜欢", "一般喜欢", "喜欢", "非常喜欢"]
    competence_labels = ["不擅长", "一般擅长", "擅长", "非常擅长"]
    return f"{preference_labels[preference_score]} × {competence_labels[competence_score]}"


def personalize_student_references(value, student_name) -> str:
    text = value if isinstance(value, str) else ""
    name = student_name.strip() if isinstance(student_name, str) else ""
    if not text or not name:
        return text

    generic = re.compile(r"(?:当前学生|该学生|这名学生|这位学生|学生)")
    personalized = name.join(generic.sub(lambda _m: name, part) for part in text.split(name))
    if not re.search(r"[A-Za-z]", name):
        return personalized

    escaped = re.escape(name)
    personalized = re.sub(
        rf"([\u4e00-\u9fff])\s*({escaped})",
        lambda m: f"{m.group(1)} {name}",
        personalized,
    )
    personalized = re.sub(
        rf"({escaped})\s*([\u4e00-\u9fff])",
        lambda m: f"{name} {m.group(2)}",
        personalized,
    )
    return personalized


def validate_quadrant_narrative(text) -> str:
    if not isinstance(text, str):
        raise ValueError("兴趣分型说明格式无效")
    value = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", value) if paragraph.strip()]
    limit = GROWTH_TALK_LIMITS["quadrant_narrative"]
    if (len(value) < 80 or len(value) > limit
            or len(paragraphs) < 2 or len(paragraphs) > 3):
        raise ValueError(f"兴趣分型说明须为 80–{limit} 字的两个至三个自然段")
    if re.search(r"^(?:\s*[#>*-]|\s*\d+[.)、])", value, re.MULTILINE):
        raise ValueError("兴趣分型说明不能使用标题或列表")
    if re.search(r"(?:建议|应该|优先|下一步要|重点关注|关键差异|下一步观察)", value):
        raise ValueError("兴趣分型说明不能生成建议或行动计划")
    if re.search(r"(?:偏好|喜欢|能力|擅长)(?:程度)?\s*(?:为|是|[:：])?\s*[0-3](?:\s*分)?(?!\d)", value):
        raise ValueError("兴趣分型说明不能逐项复述分值")
    return "\n\n".join(paragraphs)


def validate_career_profile(value) -> dict:
    if not isinstance(value, dict):
        raise ValueError("分析结果格式无效，请重试")
    result = {}
    for snake_key, camel_key, label in _CAREER_FIELDS:
        text = value.get(camel_key)
        if (not isinstance(text, str) or not text.strip()
                or re.search(r"[\r\n\u2028\u2029]", text.strip())
                or len(text.strip()) > 150):
            raise ValueError(f"{label}须为不超过 150 字的单段文字，请重新分析")
        result[snake_key] = text.strip()
    return result


def analyze_career_profile(content: str) -> dict:
    if not content or not content.strip():
        raise ValueError("报告没有可分析文字，请替换报告")
    if len(content) > 80000:
        raise UploadError(422, "报告文字过长，请上传仅包含个人测评结果的版本")
    return validate_career_profile(call_model(prompts.build_career_prompt(content)))


def analyze_meeting_source(content: str) -> dict:
    result = call_model(prompts.build_meeting_prompt(content))
    model_topics = result.get("topics") if isinstance(result, dict) else []
    topics = normalize_meeting_topics([
        *(model_topics if isinstance(model_topics, list) else []),
        *extract_meeting_candidate_fallbacks(content),
    ])
    summary = meeting_summary_with_overview(
        interest_only_meeting_summary(result.get("summary") if isinstance(result, dict) else None),
        None, topics,
    )
    keywords = _as_list(result.get("keywords") if isinstance(result, dict) else None)
    return {"summary": summary, "topics": topics, "keywords": keywords}


def discover_additional_interests(content: str, existing_labels: list[str]) -> list[dict]:
    prompt_items = [
        {"label": label} if isinstance(label, str) else label
        for label in (existing_labels or [])
    ]
    result = call_model(prompts.build_interest_discovery_prompt(content, prompt_items))
    topics = result.get("topics") if isinstance(result, dict) else None
    additions = select_additional_meeting_topics(prompt_items, topics)
    return [{**item, "preferenceScore": None, "competenceScore": None} for item in additions]


def run_quadrant_analysis(input: dict) -> dict:
    student_name = ""
    student = input.get("student") if isinstance(input, dict) else None
    if isinstance(student, dict):
        student_name = student.get("name") or ""

    def _attempt(correction: str | None = None) -> str:
        result = call_model(prompts.build_quadrant_prompt(input, correction))
        narrative = result.get("narrative") if isinstance(result, dict) else None
        return validate_quadrant_narrative(personalize_student_references(narrative, student_name))

    try:
        narrative = _attempt()
    except json.JSONDecodeError:
        narrative = _attempt("未返回合法 JSON")
    except ValueError as exc:
        if not str(exc).startswith("兴趣分型说明"):
            raise
        narrative = _attempt(str(exc))
    return {"narrative": narrative}


def generate_suggestions(input: dict) -> list[dict]:
    result = call_model(prompts.build_suggestions_prompt(input))
    items = result.get("items") if isinstance(result, dict) else None
    items = items[:5] if isinstance(items, list) else []
    if not items:
        raise ValueError("未生成有效建议，已保留原有内容")
    for row in items:
        if not isinstance(row, dict):
            raise ValueError("生成的探索建议超过填写字数限制，已保留原有内容")
        try:
            validate_suggestion_lengths(
                _as_text(row.get("title")),
                _as_text(row.get("introduction")),
                _as_text(row.get("growthValue")),
            )
        except ValueError:
            raise ValueError("生成的探索建议超过填写字数限制，已保留原有内容")
    return items


def validate_copilot_answer(value) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Copilot 返回格式无效，请重试")
    answer = value.get("answer")
    answer = answer.strip() if isinstance(answer, str) else ""
    if not answer or len(answer) > 4000:
        raise ValueError("Copilot 回答为空或过长，请重试")
    evidence = []
    raw_evidence = value.get("evidence")
    if isinstance(raw_evidence, list):
        for item in raw_evidence[:8]:
            if not isinstance(item, dict):
                continue
            source = item.get("source")
            detail = item.get("detail")
            source = source.strip() if isinstance(source, str) else "资料"
            detail = detail.strip() if isinstance(detail, str) else ""
            if detail:
                evidence.append({"source": source, "detail": detail})
    return {"answer": answer, "evidence": evidence}


def ask_growth_talk_copilot(question: str, context: dict) -> dict:
    trimmed = question.strip() if isinstance(question, str) else ""
    if not trimmed or len(trimmed) > 1000:
        raise ValueError("Copilot 问题不能为空且不能超过 1000 字")
    return validate_copilot_answer(call_model(prompts.build_copilot_prompt(trimmed, context)))
