"""T3：会前准备的证据类型（导师发言、引导性提问、设想）与理由、来源标注。

模型一律用固定答案，绝不访问网络；资料全部是虚构的。
"""
from __future__ import annotations

import pytest

import m1.pipeline as pipeline

TRANSCRIPT = (
    "2026-10-20 导师会谈记录。\n"
    "导师：最近数学考完，晚上睡得怎么样？\n"
    "学生：还行吧。\n"
    "导师：你会不会一直在想错了哪道题，是不是？\n"
    "学生：可能吧。\n"
    "导师：你是不是觉得整理错题很麻烦？\n"
    "学生：我有一点这样的感觉。\n"
    "导师：如果下次又考差了，你会怎么做？\n"
    "学生：我会先深呼吸，再去找老师问清楚。\n"
    "学生：嗯。\n"
    "学生：那次之后我也有点在意。\n"
    "学生：那天晚上我躺在床上，一直在想最后一道题。\n"
)
CASE_TEXT = ("2026-10-20 Case Review 记录。\n"
             "老师：他上课答错后会整节课低头。\n")


def _auto(text=""):
    return {
        "y4": {"items": []},
        "questionnaires": [],
        "first_touch": {"present": bool(text), "date": "2026-10-20",
                        "text": text, "session_id": 1},
    }


def _items(monkeypatch, items):
    def ask(prompt, schema_name):
        assert schema_name == pipeline.SCHEMA_SOURCE
        return {"items": items}
    monkeypatch.setattr(pipeline, "_ask", ask)


def _quotes(rows):
    return [row["quote"] for row in rows]


# ---------------------------------------------------------------------------
# 1–4：条目分类
# ---------------------------------------------------------------------------
def test_mentor_line_is_not_evidence(monkeypatch):
    _items(monkeypatch, [{
        "text": "导师问学生睡得好不好", "quote": "最近数学考完，晚上睡得怎么样？",
        "abilities": [], "kind": "context", "prompted": False, "independent": False}])

    rows = pipeline._source_text_items(_auto(TRANSCRIPT), [])

    assert rows == []


def test_answers_to_leading_questions_are_dropped(monkeypatch):
    _items(monkeypatch, [
        {"text": "学生可能在想错题", "quote": "可能吧", "abilities": [],
         "kind": "direct", "prompted": False, "independent": False},
        {"text": "学生说有点这样的感觉", "quote": "我有一点这样的感觉", "abilities": [],
         "kind": "direct", "prompted": False, "independent": False},
        {"text": "学生附和", "quote": "那次之后我也有点在意", "abilities": [],
         "kind": "direct", "prompted": True, "independent": False},
        {"text": "学生应了一声", "quote": "嗯", "abilities": [],
         "kind": "direct", "prompted": False, "independent": False},
    ])

    rows = pipeline._source_text_items(_auto(TRANSCRIPT), [])

    assert rows == []


def test_hypothetical_answer_becomes_a_supposition(monkeypatch):
    _items(monkeypatch, [{
        "text": "学生说会先深呼吸", "quote": "我会先深呼吸，再去找老师问清楚。",
        "abilities": [], "kind": "direct", "prompted": False, "independent": False}])

    rows = pipeline._source_text_items(_auto(TRANSCRIPT), [])

    assert len(rows) == 1
    item = rows[0]
    assert item["kind"] == "hypothetical"
    assert item["text"].startswith("学生设想")
    # 设想不能成为会议重点事件
    events = [row for row in rows
              if row["source"] in pipeline._EVENT_SOURCES
              and row["kind"] in pipeline._EVENT_KINDS]
    assert item["id"] not in {row["id"] for row in events}


def test_real_student_line_is_kept_and_case_review_teacher_line_stays(monkeypatch):
    _items(monkeypatch, [
        {"text": "那天晚上我躺在床上，一直在想最后一道题",
         "quote": "那天晚上我躺在床上，一直在想最后一道题", "abilities": [],
         "kind": "direct", "prompted": False, "independent": False},
        {"text": "老师观察到学生答错后低头", "quote": "他上课答错后会整节课低头",
         "abilities": [], "kind": "direct", "prompted": False, "independent": True},
    ])
    uploaded = [{"id": 7, "category": "case_review", "label": "Case Review",
                 "text": CASE_TEXT, "detected_date": "2026-10-20"}]

    rows = pipeline._source_text_items(_auto(TRANSCRIPT), uploaded)

    real = [row for row in rows if row["source"] == "first_touch"]
    assert len(real) == 1
    assert real[0]["kind"] == "direct"
    assert real[0]["text"] == "那天晚上我躺在床上，一直在想最后一道题"

    case = [row for row in rows if row["source"] == "case_review"]
    assert len(case) == 1 and case[0]["kind"] == "direct"
    assert "老师" in case[0]["quote"] or "低头" in case[0]["quote"]


# ---------------------------------------------------------------------------
# 5–6：设想不能当证据
# ---------------------------------------------------------------------------
def _made_up(item_id, source="first_touch", kind="direct", group=None):
    return {
        "id": item_id,
        "source": source,
        "source_ref": "ref-%s" % item_id,
        "date": "2026-10-20",
        "kind": kind,
        "group": group or "m1_source:%s" % item_id,
        "text": "资料里写到的具体情况",
        "quote": "资料里写到的具体情况",
        "abilities": [],
        "band": "",
    }


BASE_ROW = {
    "code": "R1.1",
    "potential": ["有一条积极线索"],
    "interference": ["有一条干扰线索"],
    "known": "已知线索",
    "new_clues": "",
    "contradictions": [],
    "missing": [],
    "check_text": "资料里写到的具体情况。",
    "recommend": True,
    "reason_code": "impact",
    "cites": ["s-1"],
}


def _judged(monkeypatch, row, evidence):
    def ask(prompt, schema_name):
        assert schema_name == pipeline.SCHEMA_ABILITY
        return {"abilities": [dict(row)]}

    monkeypatch.setattr(pipeline, "_ask", ask)
    return pipeline._judge_abilities(evidence)["R1.1"]


def test_cites_that_are_all_hypothetical_do_not_count(monkeypatch):
    evidence = [_made_up("s-1", kind="hypothetical")]
    row = dict(BASE_ROW)

    judged = _judged(monkeypatch, row, evidence)

    assert judged["cites"] == ["s-1"]  # 引用保留，便于核查
    assert judged["potential"] == []
    assert judged["interference"] == []
    assert judged["known"] == ""
    assert judged["recommend"] is False
    assert judged["reason"] == pipeline._REASON_TEXTS["none"]


def test_guard_source_marks_a_supposition():
    item = _made_up("s-1", kind="hypothetical")
    item["text"] = "学生设想：我会先深呼吸。"
    item["quote"] = "我会先深呼吸"
    texts = {"ref-s-1": "导师：如果下次又考差了，你会怎么做？\n"
                         "学生：我会先深呼吸，再去找老师问清楚。"}

    source = pipeline._guard_source([item], texts)

    assert "【设想：以下内容没有实际发生】" in source
    assert "我会先深呼吸" in source


# ---------------------------------------------------------------------------
# 7：推荐理由由代码写出
# ---------------------------------------------------------------------------
_REASON_EVIDENCE = [
    _made_up("s-1", group="m1_source:g1"),
    _made_up("s-1b", group="m1_source:g1"),
    _made_up("s-2", source="parent", group="m1_source:g2"),
    _made_up("s-3", source="case_review", kind="hypothesis"),
]

# T6b-4: the model only names two pieces of evidence; code writes the sentence
_CONFLICT = [{"a": "s-1", "b": "s-2"}]
_SAME_GROUP_CONFLICT = [{"a": "s-1", "b": "s-1b"}]

_REASON_CASES = [
    ("impact", ["s-1"], {}, pipeline._REASON_TEXTS["impact"]),
    ("impact", [], {}, pipeline._REASON_TEXTS["none"]),
    ("both", ["s-1"], {}, pipeline._REASON_TEXTS["both"]),
    ("both", ["s-1"], {"interference": []}, pipeline._REASON_TEXTS["none"]),
    ("conflict", ["s-1", "s-2"], {"contradictions": _CONFLICT},
     pipeline._REASON_TEXTS["conflict"]),
    ("conflict", ["s-1", "s-1b"], {"contradictions": _SAME_GROUP_CONFLICT},
     pipeline._REASON_TEXTS["none"]),
    ("concern", ["s-1"], {}, pipeline._REASON_TEXTS["concern"]),
    ("concern", [], {}, pipeline._REASON_TEXTS["none"]),
    ("case_review", ["s-3"], {}, pipeline._REASON_TEXTS["case_review"]),
    ("case_review", ["s-1"], {}, pipeline._REASON_TEXTS["none"]),
    ("none", ["s-1"], {}, pipeline._REASON_TEXTS["none"]),
    ("made_up", ["s-1"], {}, pipeline._REASON_TEXTS["none"]),
]


@pytest.mark.parametrize("code,cites,overrides,expected", _REASON_CASES)
def test_reason_code_is_checked_by_code(monkeypatch, code, cites, overrides,
                                        expected):
    row = dict(BASE_ROW, reason_code=code, cites=list(cites))
    row.update(overrides)

    judged = _judged(monkeypatch, row, _REASON_EVIDENCE)

    assert judged["reason"] == expected


def test_model_written_reason_is_ignored(monkeypatch):
    row = dict(BASE_ROW, reason_code="none", reason="模型自己写的理由")

    judged = _judged(monkeypatch, row, _REASON_EVIDENCE)

    assert judged["reason"] == pipeline._REASON_TEXTS["none"]
    assert "模型自己写的理由" not in judged["reason"]


# ---------------------------------------------------------------------------
# 8–9：附录的理由与来源标注
# ---------------------------------------------------------------------------
def test_appendix_reasons_are_the_three_fixed_cases():
    judgements = {
        "R1.1": {"reason": pipeline._REASON_TEXTS["impact"],
                 "check_text": "资料里写到的具体情况。", "cites": ["s-1"]},
        "R1.2": {"reason": pipeline._REASON_TEXTS["none"],
                 "check_text": "资料里写到的具体情况。", "cites": []},
    }
    chosen = ["R1.1", "R1.2"]

    rows = pipeline._appendix(judgements, chosen)
    by_code = {row["code"]: row for row in rows}

    assert by_code["R1.1"]["reason"]["text"] == pipeline._REASON_TEXTS["impact"]
    assert by_code["R1.2"]["reason"]["text"] == pipeline._APPENDIX_CHOSEN
    assert by_code["R2.1"]["reason"]["text"] == pipeline._APPENDIX_LEFT_OUT
    assert by_code["R2.1"]["recommend"] is False
    for code, row in by_code.items():
        if code not in chosen:
            assert "建议优先确认" not in row["reason"]["text"]


def test_appendix_check_text_gets_its_sources_after_the_guard():
    doc = {"appendix": [
        {"code": "R1.1", "recommend": True,
         "reason": pipeline._block("ap-r-R1.1", pipeline._APPENDIX_CHOSEN),
         "check": pipeline._block("ap-c-R1.1", "资料里写到的具体情况。")},
        {"code": "R1.2", "recommend": False,
         "reason": pipeline._block("ap-r-R1.2", pipeline._APPENDIX_LEFT_OUT),
         "check": pipeline._block("ap-c-R1.2", "尚未取得可引用的证据。")},
    ]}
    # T6b-5: a source is credited only when a cited item shares text with the check text
    by_id = {"ft-1": {"source": "first_touch", "text": "资料里写到的具体情况", "quote": ""},
             "q-1": {"source": "parent", "text": "", "quote": "资料里写到的具体情况"},
             "q-2": {"source": "first_touch", "text": "完全无关", "quote": ""}}
    judgements = {"R1.1": {"cites": ["ft-1", "q-1", "q-2"]},
                  "R1.2": {"cites": ["ft-1"]}}

    pipeline._append_source_notes(doc, judgements, by_id)

    check = doc["appendix"][0]["check"]
    labels = (pipeline.SOURCE_LABELS["first_touch"], pipeline.SOURCE_LABELS["parent"])
    assert check["text"].endswith("（来源：%s、%s）" % labels)
    assert check["text"].startswith("资料里写到的具体情况。")
    assert check["ai_text"] == check["text"]
    assert "来源" not in doc["appendix"][1]["check"]["text"]


# ---------------------------------------------------------------------------
# 10：Case Review 摘要重试一次
# ---------------------------------------------------------------------------
_SUMMARY_EVIDENCE = [_made_up("src-1-1", source="case_review", kind="direct")]


def test_case_review_summary_retries_once(monkeypatch):
    calls = []

    def ask(prompt, schema_name):
        assert schema_name == pipeline.SCHEMA_SUMMARY
        calls.append(prompt)
        if len(calls) == 1:
            return {"sentences": [{"text": "老师观察到学生上课时低头。",
                                   "evidence_ids": []}]}
        return {"sentences": [{"text": "老师观察到学生上课时低头。",
                               "evidence_ids": ["src-1-1"]}]}

    monkeypatch.setattr(pipeline, "_ask", ask)

    summaries = pipeline._source_summaries(_SUMMARY_EVIDENCE)

    assert len(calls) == 2
    assert "每一句都必须在 evidence_ids 里写出依据的 id。" in calls[1]
    assert summaries["case_review"]["text"] == "老师观察到学生上课时低头。"
    assert summaries["case_review"]["evidence_ids"] == ["src-1-1"]


def test_case_review_summary_falls_back_after_one_retry(monkeypatch):
    calls = []

    def ask(prompt, schema_name):
        assert schema_name == pipeline.SCHEMA_SUMMARY
        calls.append(prompt)
        return {"sentences": [{"text": "老师观察到学生上课时低头。",
                               "evidence_ids": []}]}

    monkeypatch.setattr(pipeline, "_ask", ask)

    summaries = pipeline._source_summaries(_SUMMARY_EVIDENCE)

    assert len(calls) == 2
    assert "case_review" not in summaries
    assert pipeline.SUMMARY_FALLBACK == "已取得资料，未能生成摘要，请查看原文。"
