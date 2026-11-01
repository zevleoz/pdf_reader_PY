"""ai_writing 共用模块：代码检查、核对与 run_guard。全部用假模型，不访问网络。"""
from __future__ import annotations

import time

import pytest

import ai_writing as aw

SOURCE = ("学生讲到英语小组展示，同组同学忘带资料。妈妈说最近回家话变少了。"
          "学生说“念完第一句就好一点了”。R1.1 的线索见第 2 条。")


def _kinds(text, source=SOURCE, **kwargs):
    return {(row["kind"], row["value"]) for row in aw.lint_facts(text, source, **kwargs)}


# ---------------------------------------------------------------------------
# lint_facts
# ---------------------------------------------------------------------------
def test_number_not_in_source_is_flagged():
    assert ("number", "三次") in _kinds("学生三次提到这件事。")


def test_number_in_source_passes():
    assert not _kinds("学生讲到第 2 条线索。")
    assert not _kinds("妈妈说两遍", "妈妈说2遍")  # 中文数字与阿拉伯数字等价


def test_time_not_in_source_is_flagged():
    assert ("time", "10月") in _kinds("10 月中旬开始话变少。")
    assert ("time", "上周四") not in _kinds("上周四的展示。")  # 值是“上周”和“周四”
    assert {("time", "上周"), ("time", "周四")} <= _kinds("上周四的展示。")


def test_time_in_source_passes_including_iso_dates():
    assert not _kinds("10月12日的会谈。", "2026-10-12 会谈")
    assert not _kinds("周四的展示", "学生说周四要展示")


def test_person_not_in_source_is_flagged():
    assert ("person", "爸爸") in _kinds("爸爸也说过类似的话。")


def test_person_synonyms_pass():
    assert not _kinds("母亲说最近回家话变少了。")
    assert not _kinds("爸爸说", "父亲说")


def test_r_codes_and_list_markers_are_ignored():
    assert not _kinds("R1.1 与 R3.5 需要确认。")
    assert not _kinds("1. 当时发生了什么？\n2. 后来怎样？")


def test_y4_and_six_am_labels_are_not_numbers():
    assert not _kinds("Y4 间接线索，6 A.M. 属于 Y4。")


@pytest.mark.parametrize("text", [
    "学生说“我一点也不怕”。",
    "学生说\"我一点也不怕\"。",
    "学生说「我一点也不怕」。",
    "学生说『我一点也不怕』。",
    "学生说‘我一点也不怕’。",
])
def test_made_up_quote_is_flagged_in_each_style(text):
    assert ("quote", "我一点也不怕") in _kinds(text)


def test_real_quote_passes_even_without_punctuation_match():
    assert not _kinds("学生说“念完第一句，就好一点了”。")


def test_ignore_labels_are_skipped():
    assert not _kinds("见“First Touch”记录。", ignore=["First Touch"])
    assert ("quote", "First Touch") in _kinds("见“First Touch”记录。")


def test_layout_numbering_is_not_a_fact():
    assert not _kinds("情境 1：展示之前")
    assert ("number", "第 3 次") in _kinds("这是第 3 次展示") or \
        any(kind == "number" for kind, _ in _kinds("这是第 3 次展示"))


def test_ten_fen_adverb_is_not_a_number():
    assert not _kinds("学生十分紧张。")


# ---------------------------------------------------------------------------
# lint_style / pronoun_problem
# ---------------------------------------------------------------------------
def test_lint_style_finds_phrases():
    found = aw.lint_style("学生展现出很强的能力，具备较强的沟通能力。令人欣慰。")
    assert "展现出" in found and "令人欣慰" in found
    assert any(item.startswith("具备") for item in found)
    assert aw.lint_style("学生上台讲完了。") == []


def test_pronoun_blank_gender_is_a_problem():
    assert aw.pronoun_problem("她当时很紧张。", "") is True
    assert aw.pronoun_problem("他当时很紧张。", None) is True


def test_pronoun_matching_gender_is_not_a_problem():
    assert aw.pronoun_problem("她当时很紧张。", "女") is False
    assert aw.pronoun_problem("他当时很紧张。", "男") is False
    assert aw.pronoun_problem("她当时很紧张。", "男") is True


def test_pronoun_ignores_other_words_and_quotes():
    assert aw.pronoun_problem("其他同学和他人都没说话。", "") is False
    assert aw.pronoun_problem("学生说“她不在”。", "") is False


# ---------------------------------------------------------------------------
# 规则文字
# ---------------------------------------------------------------------------
def test_rules_block_has_both_parts_without_example_facts():
    block = aw.rules_block()
    assert block.index("准确性要求") < block.index("写作要求")
    for fact in ("期中数学", "10 月中旬", "回家不怎么说话"):
        assert fact not in block


# ---------------------------------------------------------------------------
# verify_blocks / run_guard（假模型）
# ---------------------------------------------------------------------------
def _block(text, block_id="b1", source=SOURCE):
    return {"id": block_id, "text": text, "source": source}


def _supported(prompt_text):
    return {"sentences": [{"text": piece, "verdict": "supported", "problem": ""}
                          for piece in aw._sentences(prompt_text)]}


class FakeModel:
    """核对 → 全部通过；重写 → 返回 rewrite_to（默认原样）。"""

    def __init__(self, verdicts=None, rewrite_to=None):
        self.verdicts = verdicts or {}
        self.rewrite_to = rewrite_to
        self.calls = []

    def __call__(self, prompt):
        self.calls.append(prompt)
        if "事实核对员" in prompt:
            text = prompt.split("【文字】\n", 1)[1].split("\n【资料】", 1)[0]
            rows = []
            for piece in aw._sentences(text):
                rows.append({"text": piece, "verdict": self.verdicts.get(piece, "supported"),
                             "problem": "没有依据" if piece in self.verdicts else ""})
            return {"sentences": rows}
        text = prompt.split("【文字】\n", 1)[1].split("\n【问题】", 1)[0]
        return {"text": self.rewrite_to if self.rewrite_to is not None else text}


def test_verify_blocks_reports_partly_and_unsupported():
    model = FakeModel({"学生很怕被笑": "unsupported"})
    result = aw.verify_blocks([_block("学生上台讲完了。学生很怕被笑。")], call=model)
    assert [(r["id"], r["sentence"], r["verdict"]) for r in result] == [
        ("b1", "学生很怕被笑", "unsupported")]


def test_verify_blocks_raises_when_the_check_cannot_run():
    def broken(prompt):
        raise TimeoutError("slow")
    with pytest.raises(aw.VerifyError):
        aw.verify_blocks([_block("学生上台讲完了。")], call=broken)


def test_verify_blocks_rejects_incomplete_answers():
    def partial(prompt):
        return {"sentences": [{"text": "无关的一句话内容", "verdict": "supported", "problem": ""}]}
    with pytest.raises(aw.VerifyError):
        aw.verify_blocks([_block("学生上台讲完了。同学忘带资料。")], call=partial)


def test_run_guard_clean_text_passes():
    model = FakeModel()
    result = aw.run_guard([_block("学生上台讲完了。")], call=model)
    assert result["status"] == "checked"
    assert result["flags"] == []
    assert result["blocks"] == {"b1": "学生上台讲完了。"}
    assert len(model.calls) == 1  # 只核对，不重写


def test_run_guard_rewrites_bad_text_once_and_passes():
    model = FakeModel(rewrite_to="学生上台讲完了自己负责的部分。")
    bad = "学生上台讲完了。学生三次提到想放弃。"
    result = aw.run_guard([_block(bad)], call=model)
    assert result["blocks"]["b1"] == "学生上台讲完了自己负责的部分。"
    assert result["flags"] == []
    assert result["status"] == "checked"
    assert sum("改正这些地方" in c or "只删除或改正" in c for c in model.calls) == 1


def test_run_guard_text_that_stays_bad_becomes_a_flag_and_is_kept():
    model = FakeModel()  # 重写原样返回 → 仍然不合格
    bad = "学生上台讲完了。学生三次提到想放弃。"
    result = aw.run_guard([_block(bad)], call=model)
    assert result["blocks"]["b1"] == bad
    assert [f["kind"] for f in result["flags"]] == ["number"]
    flag = result["flags"][0]
    assert flag["id"] == "b1" and "三次" in flag["sentence"] and flag["problem"]
    assert flag["source_excerpt"]
    assert sum("只删除或改正" in c for c in model.calls) == 1  # 只重写一次


def test_run_guard_rewrite_that_adds_text_is_rejected():
    model = FakeModel(rewrite_to="学生上台讲完了。学生三次提到想放弃。后来还哭了很久。")
    bad = "学生上台讲完了。学生三次提到想放弃。"
    result = aw.run_guard([_block(bad)], call=model)
    assert result["blocks"]["b1"] == bad
    assert result["flags"]


def test_run_guard_never_deletes_a_whole_block():
    model = FakeModel(rewrite_to="")
    bad = "学生三次提到想放弃。"
    result = aw.run_guard([_block(bad)], call=model)
    assert result["blocks"]["b1"] == bad
    assert result["flags"]


def test_run_guard_unsupported_sentence_from_the_checker_is_rewritten():
    model = FakeModel({"学生很怕被笑": "unsupported"},
                      rewrite_to="学生上台讲完了自己负责的部分。")
    result = aw.run_guard([_block("学生上台讲完了。学生很怕被笑。")], call=model)
    assert result["blocks"]["b1"] == "学生上台讲完了自己负责的部分。"
    assert result["flags"] == []


def test_run_guard_failing_call_gives_skipped_and_does_not_raise():
    def broken(prompt):
        raise RuntimeError("boom")
    result = aw.run_guard([_block("学生上台讲完了。")], call=broken)
    assert result["status"] == "skipped"
    assert result["blocks"] == {"b1": "学生上台讲完了。"}


def test_run_guard_failed_check_is_never_reported_as_checked():
    calls = {"n": 0}

    def flaky(prompt):
        calls["n"] += 1
        raise RuntimeError("down")
    result = aw.run_guard([_block("学生上台讲完了。", "a", "资料甲"),
                           _block("同学忘带资料。", "b", "资料乙")], call=flaky)
    assert result["status"] == "skipped"
    assert sorted(result["unchecked"]) == ["a", "b"]


def test_run_guard_budget_exceeded_gives_partial():
    def slow(prompt):
        time.sleep(0.15)
        return _supported(prompt.split("【文字】\n", 1)[1].split("\n【资料】", 1)[0])
    blocks = [_block("学生上台讲完了。", "a", "资料甲"), _block("同学忘带资料。", "b", "资料乙")]
    result = aw.run_guard(blocks, call=slow, budget_seconds=0.05, workers=1)
    assert result["status"] == "partial"
    assert result["unchecked"] == ["b"]
    assert result["blocks"] == {"a": "学生上台讲完了。", "b": "同学忘带资料。"}


def test_run_guard_block_without_source_is_unchecked():
    result = aw.run_guard([_block("学生上台讲完了。", source="")], call=FakeModel())
    assert result["status"] == "skipped"
    assert result["unchecked"] == ["b1"]


def test_run_guard_pronoun_with_blank_gender_is_rewritten():
    model = FakeModel(rewrite_to="学生上台讲完了整个展示。")
    result = aw.run_guard([_block("她上台讲完了整个展示。")], call=model, gender="")
    assert result["blocks"]["b1"] == "学生上台讲完了整个展示。"
    # 不传 gender 时不检查人称
    result = aw.run_guard([_block("她上台讲完了整个展示。")], call=FakeModel())
    assert result["flags"] == []
