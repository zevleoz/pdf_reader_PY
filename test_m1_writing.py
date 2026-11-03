"""W1：会前准备的写作与事实核对。模型一律用假的，绝不访问网络。"""
from __future__ import annotations

import json
import re

import pytest

import m1.pipeline as pipeline
import m1.prompts as prompts
import m1.sources as sources
import m1.store as store
from test_m1_pipeline import (FT_TEXT, PARENT_TEXT, CASE_TEXT, _auto,  # noqa: F401
                              _behavior_all, _fake_ask, _latest_draft, _login,
                              _questionnaires, api_client)
from test_m1_store import m1db  # noqa: F401  复用临时库


def _setup(m1db, monkeypatch, *, summary=None, verify=None, rewrite=None,
           priority_hypothesis=None, text_override=None):
    """Full-source student whose model answers can be overridden per schema."""
    auto = _auto(ft_text=FT_TEXT, questionnaires=_questionnaires(), six_am_state="需关注")
    monkeypatch.setattr(pipeline.sources, "auto_sources", lambda sid: auto)
    prep = m1db.prep()
    parent = sources.add_text(prep["id"], PARENT_TEXT, "parent")
    case = sources.add_text(prep["id"], CASE_TEXT, "case_review")
    behaviour = _behavior_all("m1_source:%s" % parent["id"], "m1_source:%s" % case["id"],
                              "copilot_session:3")
    if text_override:
        for items in behaviour["source_items"].values():
            for item in items:
                item["text"] = text_override
    base = _fake_ask(behaviour)

    def ask(prompt, schema_name):
        if schema_name == pipeline.SCHEMA_SUMMARY and summary is not None:
            return summary(prompt)
        if schema_name == pipeline.SCHEMA_VERIFY and verify is not None:
            return verify(prompt)
        if schema_name == pipeline.SCHEMA_REWRITE and rewrite is not None:
            return rewrite(prompt)
        result = base(prompt, schema_name)
        if schema_name == pipeline.SCHEMA_PRIORITY and priority_hypothesis:
            for row in result["items"]:
                row["hypothesis"] = priority_hypothesis
        return result

    monkeypatch.setattr(pipeline, "_ask", ask)
    return prep


def _evidence_rows(prompt):
    return json.loads(prompt.split("【证据】\n", 1)[1])


# ---------------------------------------------------------------------------
# 1. 1.2 来源摘要
# ---------------------------------------------------------------------------
def test_source_summary_is_complete_sentences(m1db, monkeypatch):
    def summary(prompt):
        rows = _evidence_rows(prompt)
        return {"sentences": [
            {"text": "学生说考完数学后晚上会一直想哪道题错了。", "evidence_ids": [rows[0]["id"]]},
            {"text": "这一句没有来源。", "evidence_ids": []},
            {"text": "这一句引用了不存在的条目。", "evidence_ids": ["no-such-id"]},
            {"text": "资料里没有提到别的情况。", "evidence_ids": [rows[0]["id"]]},
        ]}
    prep = _setup(m1db, monkeypatch, summary=summary)

    pipeline.generate(prep["id"])

    doc = _latest_draft(prep["id"])["doc"]
    by_key = {row["key"]: row["extracted"]["text"] for row in doc["sources"]}
    for key in ("parent", "first_touch", "case_review"):
        text = by_key[key]
        assert text == "学生说考完数学后晚上会一直想哪道题错了。资料里没有提到别的情况。"
        assert "；" not in text and not text.endswith("…")
        assert "没有来源" not in text and "不存在" not in text
    assert by_key["other"] == "尚未取得相关资料"


def test_source_summary_drops_whole_sentences_not_characters(m1db, monkeypatch):
    sentence = "学生说考完数学后晚上会想哪道题错了，白天上课时偶尔也会走神。"

    def summary(prompt):
        rows = _evidence_rows(prompt)
        return {"sentences": [{"text": sentence, "evidence_ids": [rows[0]["id"]]}] * 12}
    prep = _setup(m1db, monkeypatch, summary=summary)

    pipeline.generate(prep["id"])

    text = {row["key"]: row["extracted"]["text"]
            for row in _latest_draft(prep["id"])["doc"]["sources"]}["parent"]
    assert len(text) <= pipeline._SUMMARY_LIMIT
    assert text.endswith("。") and text.count(sentence) == len(text) // len(sentence)


def test_source_summary_falls_back_to_a_fixed_sentence(m1db, monkeypatch):
    def broken(prompt):
        raise RuntimeError("model down")
    prep = _setup(m1db, monkeypatch, summary=broken)

    pipeline.generate(prep["id"])

    by_key = {row["key"]: row["extracted"]["text"]
              for row in _latest_draft(prep["id"])["doc"]["sources"]}
    for key in ("parent", "first_touch", "case_review"):
        assert by_key[key] == "已取得资料，未能生成摘要，请查看原文。"
    assert by_key["other"] == "尚未取得相关资料"
    assert not any("…" in text for text in by_key.values())


def test_summary_fallback_is_not_a_text_fragment():
    assert not hasattr(pipeline, "_join_snippets")
    assert pipeline.SUMMARY_FALLBACK == "已取得资料，未能生成摘要，请查看原文。"


# ---------------------------------------------------------------------------
# 2. 提示词里没有事实示例
# ---------------------------------------------------------------------------
def test_no_prompt_contains_example_facts():
    texts = [value for name, value in vars(prompts).items() if isinstance(value, str)]
    assert any("写作要求" in text for text in texts)
    for text in texts:
        for fact in ("期中数学", "10 月中旬", "回家不怎么说话"):
            assert fact not in text


def test_prompts_carry_the_shared_rules():
    assert "准确性要求" in prompts._STYLE and "写作要求" in prompts._STYLE
    assert "准确性要求" in prompts.SOURCE_ITEMS_PROMPT or "分清谁说的" in prompts.SOURCE_ITEMS_PROMPT or \
        "导师的提问" in prompts.SOURCE_ITEMS_PROMPT


# ---------------------------------------------------------------------------
# 3. text 只能说 quote 说了的内容
# ---------------------------------------------------------------------------
def test_text_that_adds_a_number_is_replaced_by_its_quote(m1db, monkeypatch):
    prep = _setup(m1db, monkeypatch, text_override="学生考后连续三次想起错题")

    pipeline.generate(prep["id"])

    draft = _latest_draft(prep["id"])
    ft = [item for item in draft["evidence"] if item["source"] == "first_touch"][0]
    assert ft["text"] == ft["quote"]
    assert all("三次" not in item["text"] for item in draft["evidence"])


def test_text_without_new_facts_is_kept(m1db, monkeypatch):
    prep = _setup(m1db, monkeypatch)
    pipeline.generate(prep["id"])
    ft = [item for item in _latest_draft(prep["id"])["evidence"]
          if item["source"] == "first_touch"][0]
    assert ft["text"] == "晚上一直在想错题"


# ---------------------------------------------------------------------------
# 3b. 长资料不再被截断
# ---------------------------------------------------------------------------
def test_long_source_is_read_in_pieces_and_the_late_event_is_sent(m1db, monkeypatch):
    from app_utils import BASE_DIR
    long_text = (BASE_DIR / "fixtures" / "ai_eval" / "long_tail.txt").read_text(encoding="utf-8")
    assert len(long_text) > 15000 and long_text.index("小猫卡在") > 13000
    auto = _auto()
    monkeypatch.setattr(pipeline.sources, "auto_sources", lambda sid: auto)
    prep = m1db.prep()
    row = sources.add_text(prep["id"], long_text, "other")
    seen = []

    def ask(prompt, schema_name):
        if schema_name == pipeline.SCHEMA_SOURCE:
            payload = json.loads(prompt.split("【资料】\n", 1)[1])
            seen.append(payload["text"])
            if "小猫卡在" in payload["text"]:
                line = [l for l in payload["text"].split("\n") if "小猫卡在" in l][0]
                quote = line.split("：", 1)[1][:30]
                return {"items": [{"text": "学生看到小猫被困", "quote": quote,
                                   "abilities": [], "kind": "direct", "independent": False}]}
            return {"items": []}
        return _fake_ask({})(prompt, schema_name)
    monkeypatch.setattr(pipeline, "_ask", ask)

    items = pipeline._source_text_items(auto, store.list_sources(prep["id"]))

    assert len(seen) >= 2 and all(len(piece) <= pipeline._TEXT_LIMIT for piece in seen)
    assert "".join(piece.replace("\n", "") for piece in seen) == long_text.replace("\n", "").strip()
    assert any("小猫卡在" in piece for piece in seen)
    assert len(items) == 1 and "小猫卡在" in items[0]["quote"]
    assert items[0]["source_ref"] == "m1_source:%s" % row["id"]


def test_split_pieces_handles_a_single_huge_line():
    pieces = pipeline._split_pieces("甲" * 30000)
    assert pipeline._TEXT_LIMIT == 6000
    assert [len(p) for p in pieces] == [pipeline._TEXT_LIMIT] * 5


# ---------------------------------------------------------------------------
# 4. 事实核对
# ---------------------------------------------------------------------------
def test_made_up_date_in_hypothesis_becomes_a_flag_when_rewrite_keeps_it(m1db, monkeypatch):
    prep = _setup(m1db, monkeypatch, priority_hypothesis="可能从3月中旬起就这样，还需要了解。")

    pipeline.generate(prep["id"])

    doc = _latest_draft(prep["id"])["doc"]
    flags = [flag for flag in doc["fact_flags"] if flag["block_id"].startswith("h-")]
    assert flags and flags[0]["kind"] == "time" and "3月" in flags[0]["problem"]
    assert flags[0]["acked"] is False and flags[0]["block_text"]
    assert flags[0]["source_excerpt"]
    # the text is kept, not deleted
    holder = [row["hypothesis"] for row in doc["priority"] if row["hypothesis"]["id"] == flags[0]["block_id"]][0]
    assert "3月中旬" in holder["text"]


def test_rewrite_that_removes_the_date_leaves_no_flag(m1db, monkeypatch):
    def rewrite(prompt):
        return {"text": "可能与考试有关，还需要了解。"}
    prep = _setup(m1db, monkeypatch, rewrite=rewrite,
                  priority_hypothesis="可能从3月中旬起就这样，还需要了解。")

    pipeline.generate(prep["id"])

    doc = _latest_draft(prep["id"])["doc"]
    assert [f for f in doc["fact_flags"] if f["block_id"].startswith("h-")] == []
    assert all("3月" not in row["hypothesis"]["text"] for row in doc["priority"])
    assert all(row["hypothesis"]["ai_text"] == row["hypothesis"]["text"] for row in doc["priority"])


def test_checker_marking_a_sentence_unsupported_triggers_the_rewrite(m1db, monkeypatch):
    def verify(prompt):
        text = prompt.split("【文字】\n", 1)[1].split("\n【资料】", 1)[0]
        rows = []
        for piece in re.split(r"[。！？；;\n]+", text):
            if not piece.strip():
                continue
            bad = "初步假设待核实" in piece
            rows.append({"text": piece, "verdict": "unsupported" if bad else "supported",
                         "problem": "资料没有依据" if bad else ""})
        return {"sentences": rows}
    prep = _setup(m1db, monkeypatch, verify=verify)

    pipeline.generate(prep["id"])

    flags = _latest_draft(prep["id"])["doc"]["fact_flags"]
    assert any(f["kind"] == "unsupported" and f["block_id"].startswith("h-") for f in flags)


def test_pronoun_in_a_block_is_flagged_when_gender_is_blank(m1db, monkeypatch):
    prep = _setup(m1db, monkeypatch, priority_hypothesis="她可能很在意成绩，还需要了解。")

    pipeline.generate(prep["id"])

    flags = _latest_draft(prep["id"])["doc"]["fact_flags"]
    assert any(f["kind"] == "pronoun" for f in flags)


def test_guard_failure_adds_the_document_level_flag(m1db, monkeypatch):
    def broken(prompt):
        raise TimeoutError("fact check timed out")
    prep = _setup(m1db, monkeypatch, verify=broken)

    pipeline.generate(prep["id"])

    flags = _latest_draft(prep["id"])["doc"]["fact_flags"]
    doc_flags = [f for f in flags if f["block_id"] == ""]
    assert len(doc_flags) == 1
    assert doc_flags[0]["sentence"] == "部分内容未完成事实核对，请人工核对。"
    assert doc_flags[0]["acked"] is False


def test_clean_run_has_no_flags_and_validate_still_runs(m1db, monkeypatch):
    prep = _setup(m1db, monkeypatch)
    pipeline.generate(prep["id"])
    doc = _latest_draft(prep["id"])["doc"]
    assert doc["fact_flags"] == []


def test_verify_step_sits_between_plan_and_assemble():
    from m1.jobs import STEP_DEFS
    keys = [key for key, _label in STEP_DEFS]
    assert keys.index("plan") + 1 == keys.index("verify") == keys.index("assemble") - 1
    assert dict(STEP_DEFS)["verify"] == "核对事实"


# ---------------------------------------------------------------------------
# 5. 人工关卡：定稿
# ---------------------------------------------------------------------------
def _flagged_prep(m1db, monkeypatch):
    prep = _setup(m1db, monkeypatch, priority_hypothesis="可能从3月中旬起就这样，还需要了解。")
    pipeline.generate(prep["id"])
    return prep


def test_finalize_is_blocked_by_an_open_flag_and_allowed_after_ack(api_client, m1db, monkeypatch):
    prep = _flagged_prep(m1db, monkeypatch)
    _login(api_client, m1db.alice_id, "advisor", "Alice")

    res = api_client.post("/api/m1/preps/%d/finalize" % prep["id"])
    assert res.status_code == 409
    body = res.get_json()
    assert body["error"] == "还有未核对的内容" and body["flags"]

    for flag in body["flags"]:
        ack = api_client.post("/api/m1/preps/%d/fact-flags/%s/ack" % (prep["id"], flag["id"]))
        assert ack.status_code == 200 and ack.get_json()["ok"]

    res = api_client.post("/api/m1/preps/%d/finalize" % prep["id"])
    assert res.status_code == 200, res.get_json()
    final = store.get_current_version(prep["id"])
    assert final["kind"] == "final"
    assert all(f["acked"] for f in final["doc"]["fact_flags"])  # the trail is kept


def test_finalize_is_allowed_after_the_flagged_block_is_edited(api_client, m1db, monkeypatch):
    prep = _flagged_prep(m1db, monkeypatch)
    _login(api_client, m1db.alice_id, "advisor", "Alice")
    res = api_client.post("/api/m1/preps/%d/finalize" % prep["id"])
    assert res.status_code == 409
    block_ids = {flag["block_id"] for flag in res.get_json()["flags"]}

    edit = store.get_latest_version(prep["id"], "edit")
    doc = edit["doc"]
    for row in doc["priority"]:
        if row["hypothesis"]["id"] in block_ids:
            row["hypothesis"]["text"] = "还需要了解她在这件事上的实际经历。".replace("她", "学生")
    saved = api_client.put("/api/m1/preps/%d/doc" % prep["id"],
                           json={"rev": store.get_prep(prep["id"])["rev"], "doc": doc})
    assert saved.status_code == 200

    res = api_client.post("/api/m1/preps/%d/finalize" % prep["id"])
    assert res.status_code == 200, res.get_json()


def test_ack_route_needs_a_known_flag_and_access(api_client, m1db, monkeypatch):
    prep = _flagged_prep(m1db, monkeypatch)
    _login(api_client, m1db.alice_id, "advisor", "Alice")
    assert api_client.post("/api/m1/preps/%d/fact-flags/nope/ack" % prep["id"]).status_code == 404
    _login(api_client, m1db.bob_id, "advisor", "Bob")
    assert api_client.post("/api/m1/preps/%d/fact-flags/ff1/ack" % prep["id"]).status_code == 403
    _login(api_client, m1db.viewer_id, "viewer")
    assert api_client.post("/api/m1/preps/%d/fact-flags/ff1/ack" % prep["id"]).status_code in (401, 403)


def test_document_level_flag_closes_only_by_ack(api_client, m1db, monkeypatch):
    def broken(prompt):
        raise TimeoutError("down")
    prep = _setup(m1db, monkeypatch, verify=broken)
    pipeline.generate(prep["id"])
    _login(api_client, m1db.alice_id, "advisor", "Alice")

    res = api_client.post("/api/m1/preps/%d/finalize" % prep["id"])
    assert res.status_code == 409
    assert [f["id"] for f in res.get_json()["flags"]] == ["ff-doc"]
    api_client.post("/api/m1/preps/%d/fact-flags/ff-doc/ack" % prep["id"])
    assert api_client.post("/api/m1/preps/%d/finalize" % prep["id"]).status_code == 200


# ---------------------------------------------------------------------------
# 6. 打印页不含标记，也不含 Y4 原始分值
# ---------------------------------------------------------------------------
def test_print_page_has_no_fact_flags_and_no_raw_y4_numbers(api_client, m1db, monkeypatch):
    prep = _flagged_prep(m1db, monkeypatch)
    assert _latest_draft(prep["id"])["doc"]["fact_flags"]
    _login(api_client, m1db.alice_id, "advisor", "Alice")

    res = api_client.get("/m1/preps/%d/print" % prep["id"])

    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "fact_flags" not in html and "block_text" not in html
    assert "source_excerpt" not in html and "部分内容未完成事实核对" not in html
    from m1.validate_doc import check_no_raw_numbers
    draft = _latest_draft(prep["id"])
    assert check_no_raw_numbers(draft["doc"], draft["evidence"]) == []
    assert '"raw"' not in html


def test_workspace_detail_still_carries_the_flags(api_client, m1db, monkeypatch):
    prep = _flagged_prep(m1db, monkeypatch)
    _login(api_client, m1db.alice_id, "advisor", "Alice")
    body = api_client.get("/api/m1/preps/%d" % prep["id"]).get_json()
    assert body["doc"]["fact_flags"]
