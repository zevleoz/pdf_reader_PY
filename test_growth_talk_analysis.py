"""Growth Talk 分析纯逻辑契约测试（全部离线）。"""
import json
import urllib.request

import pytest

from growth_talk import analysis


VALID_NARRATIVE = (
    "兴趣分型说明用喜欢与擅长两个维度，呈现林同学目前正在做的事情，"
    "帮助看见兴趣积累与可能逐渐形成的鲜明优势。\n\n"
    "林同学在机器人社团中持续搭建与调试，已经积累了把想法变成可运行作品的经验。"
    "未来或许可以把这种动手尝试延伸到更复杂的问题情境，让兴趣与能力在持续探索中相互支撑。"
)


def test_normalize_merges_duplicates_and_nulls_conflicting_scores():
    topics = [
        {"label": "篮球", "topicType": "interest", "evidence": "爱打篮球",
         "evidenceStrength": "弱", "preferenceScore": 2, "competenceScore": 1},
        {"label": "篮球 ", "topicType": "interest", "evidence": "每周训练",
         "evidenceStrength": "强", "preferenceScore": 3, "competenceScore": 1},
    ]
    [topic] = analysis.normalize_meeting_topics(topics)
    assert topic["evidence"] == "爱打篮球；每周训练"
    assert topic["evidenceStrength"] == "强"
    assert topic["preferenceScore"] is None
    assert topic["competenceScore"] == 1


def test_fallback_finds_subject_verbatim():
    topics = analysis.extract_meeting_candidate_fallbacks("他这学期数学进步很大，也提到课业负担重。")
    labels = {topic["label"] for topic in topics}
    assert "数学" in labels and "课业负担" in labels


def test_quadrant_narrative_rejects_advice_words():
    with pytest.raises(ValueError):
        analysis.validate_quadrant_narrative("第一段。\n\n建议他多尝试。")


def test_quadrant_narrative_accepts_valid_text():
    assert analysis.validate_quadrant_narrative(VALID_NARRATIVE)


def test_suggestions_over_limit_rejected(monkeypatch):
    items = [{"title": "x" * 41, "introduction": "i", "growthValue": "g",
              "possibleOutputs": [], "recommendationBasis": "r",
              "interestRefs": [], "explorationTags": []}]
    monkeypatch.setattr(analysis, "call_model", lambda prompt: {"items": items})
    with pytest.raises(ValueError, match="超过填写字数限制"):
        analysis.generate_suggestions({})


def test_suggestions_empty_rejected(monkeypatch):
    monkeypatch.setattr(analysis, "call_model", lambda prompt: {"items": []})
    with pytest.raises(ValueError, match="未生成有效建议"):
        analysis.generate_suggestions({})


def test_call_model_maps_finish_reason_length(monkeypatch):
    monkeypatch.setenv("FT_LLM_API_KEY", "test-key")

    class FakeResponse:
        def read(self):
            return json.dumps({
                "choices": [{"finish_reason": "length", "message": {"content": ""}}],
            }).encode()

    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())
    with pytest.raises(analysis.AnalysisError, match="超过长度限制"):
        analysis.call_model("prompt")


def test_call_model_success(monkeypatch):
    monkeypatch.setenv("FT_LLM_API_KEY", "test-key")

    class FakeResponse:
        def read(self):
            return json.dumps({
                "choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}],
            }).encode()

    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())
    assert analysis.call_model("prompt") == {"ok": True}


def test_validate_editable_interest_label_and_exclusions():
    assert analysis.validate_editable_interest_label(" 篮球 ") == "篮球"
    with pytest.raises(ValueError, match="1–120"):
        analysis.validate_editable_interest_label("")
    with pytest.raises(ValueError, match="兴趣词条只能保留"):
        analysis.validate_editable_interest_label("学习方式")
    assert analysis.is_excluded_interest_topic("学习习惯")
    assert analysis.is_excluded_interest_topic("Capstone 项目经历")
    assert not analysis.is_excluded_interest_topic("篮球")


def test_validate_editable_meeting_summary_rejects_excluded_content():
    assert analysis.validate_editable_meeting_summary("他喜欢机器人。") == "他喜欢机器人。"
    with pytest.raises(ValueError, match="只能保留兴趣"):
        analysis.validate_editable_meeting_summary("讨论了转学安排。")


def test_career_profile_validation():
    payload = {"careerInterests": "喜欢动手实践。" * 3,
               "abilityTendencies": "空间感较好。" * 3,
               "valuePreferences": "重视自主。" * 3}
    result = analysis.validate_career_profile(payload)
    assert set(result) == {"career_interests", "ability_tendencies", "value_preferences"}
    with pytest.raises(ValueError, match="须为不超过 150 字"):
        analysis.validate_career_profile({**payload, "careerInterests": "x" * 151})
    with pytest.raises(ValueError, match="须为不超过 150 字"):
        analysis.validate_career_profile({**payload, "careerInterests": "第一行\n第二行"})


def test_analyze_career_profile_empty_and_oversize():
    with pytest.raises(ValueError, match="没有可分析文字"):
        analysis.analyze_career_profile("   ")
    with pytest.raises(Exception, match="报告文字过长"):
        analysis.analyze_career_profile("x" * 80001)


def test_analyze_meeting_source_merges_fallbacks(monkeypatch):
    monkeypatch.setattr(analysis, "call_model", lambda prompt: {
        "summary": "本次会议主要围绕兴趣与经历展开。他喜欢机器人。",
        "topics": [{"label": "机器人", "topicType": "interest", "evidence": "参加社团",
                    "preferenceScore": 3, "competenceScore": 2}],
        "keywords": [" 机器人 ", ""],
    })
    result = analysis.analyze_meeting_source("他喜欢机器人，数学也不错。")
    labels = {topic["label"] for topic in result["topics"]}
    assert "机器人" in labels and "数学" in labels
    assert result["keywords"] == ["机器人"]
    assert result["summary"].startswith("本次会议主要围绕兴趣与经历展开。")


def test_discover_additional_interests_dedupes(monkeypatch):
    monkeypatch.setattr(analysis, "call_model", lambda prompt: {
        "topics": [
            {"label": "篮球", "topicType": "interest", "evidence": "训练"},
            {"label": "戏剧", "topicType": "interest", "evidence": "演出"},
        ],
    })
    result = analysis.discover_additional_interests("正文", ["篮球"])
    assert [item["label"] for item in result] == ["戏剧"]
    assert result[0]["preferenceScore"] is None


def test_run_quadrant_analysis_retries_with_correction(monkeypatch):
    calls = []

    def fake_call(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return {"narrative": "太短"}
        return {"narrative": VALID_NARRATIVE}

    monkeypatch.setattr(analysis, "call_model", fake_call)
    result = analysis.run_quadrant_analysis({
        "student": {"name": "林同学", "grade": "10"},
        "meetingSummary": "背景",
        "interests": [],
    })
    assert result["narrative"] == VALID_NARRATIVE
    assert "上一次输出不符合要求" in calls[1]


def test_ask_copilot_question_length():
    with pytest.raises(ValueError, match="1000 字"):
        analysis.ask_growth_talk_copilot("x" * 1001, {})
    with pytest.raises(ValueError, match="不能为空"):
        analysis.ask_growth_talk_copilot("   ", {})


def test_ask_copilot_validates_answer(monkeypatch):
    monkeypatch.setattr(analysis, "call_model", lambda prompt: {
        "answer": "  建议先观察。  ",
        "evidence": [{"source": "会议纪要", "detail": " 学生提到机器人 "}, {"bad": "x"}],
    })
    result = analysis.ask_growth_talk_copilot("下一步做什么？", {})
    assert result["answer"] == "建议先观察。"
    assert result["evidence"] == [{"source": "会议纪要", "detail": "学生提到机器人"}]
