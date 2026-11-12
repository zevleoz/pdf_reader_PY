"""T2：事实核对加固。代码检查、改写保护、保存不能抹掉标记。

全部用假模型，不访问网络。
"""
from __future__ import annotations

import pytest

import ai_writing as aw
import m1.store as store
from test_ai_writing import FakeModel, _block
from test_m1_pipeline import _login, api_client  # noqa: F401  复用临时库里的应用
from test_m1_store import _doc, m1db  # noqa: F401  复用临时库与文档构造


def _kinds(text, source):
    return {(row["kind"], row["value"]) for row in aw.lint_facts(text, source)}


# ---------------------------------------------------------------------------
# 1. 时间戳不能给数字当依据
# ---------------------------------------------------------------------------
def test_a_timestamp_cannot_supply_a_number():
    source = "[00:12:05] 学生：中午吃了一点东西。"
    assert ("number", "12点") in _kinds("学生12点才吃午饭。", source)
    # 资料里真的写了这个时间，就应该通过
    assert ("number", "12点") not in _kinds("学生12点才吃午饭。", "学生说中午12点吃饭。")


# ---------------------------------------------------------------------------
# 2. 更宽的量词、时间词、人物
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("measure,text", [
    ("点", "学生记了三点。"),
    ("人", "同组有三人。"),
    ("句", "学生只念了三句话。"),
    ("条", "学生记了三条笔记。"),
    ("张", "桌上有三张纸。"),
    ("节", "今天上了三节课。"),
])
def test_new_measures_are_flagged_and_pass_when_present(measure, text):
    assert ("number", "三" + measure) in _kinds(text, "资料写了别的事情。")
    assert ("number", "三" + measure) not in _kinds(text, text)


@pytest.mark.parametrize("word", ["前天", "后天", "明天", "下周", "下个月", "下学期", "明年"])
def test_new_time_words_are_flagged_and_pass_when_present(word):
    text = "学生%s要考试。" % word
    assert ("time", word) in _kinds(text, "资料写了别的事情。")
    assert ("time", word) not in _kinds(text, "资料里写了%s。" % word)


@pytest.mark.parametrize("word", ["叔叔", "阿姨", "舅舅", "舅妈", "姑姑", "姨妈",
                                  "校长", "家教", "室友"])
def test_new_person_words_are_flagged_and_pass_when_present(word):
    text = "%s说了一句话。" % word
    assert ("person", word) in _kinds(text, "资料写了别的事情。")
    assert ("person", word) not in _kinds(text, "资料提到%s。" % word)


# ---------------------------------------------------------------------------
# 3. 程度或频率
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("word", ["极度", "极其", "非常", "特别", "严重", "显著", "明显",
                                  "强烈", "剧烈", "一直", "总是", "经常", "常常", "反复",
                                  "多次", "长期", "每次", "每天", "从不", "从来", "始终",
                                  "频繁", "习惯"])
def test_intensity_word_is_flagged_and_passes_when_present(word):
    text = "学生%s很紧张。" % word
    assert ("intensity", word) in _kinds(text, "资料只写了那一次。")
    assert ("intensity", word) not in _kinds(text, "资料写了学生%s紧张。" % word)


# ---------------------------------------------------------------------------
# 4. 没有依据的结论
# ---------------------------------------------------------------------------
def test_conclusion_without_a_hedge_is_flagged():
    source = "资料里只有零散描述。"
    assert ("conclusion", "这说明学生具备觉察能力") in _kinds("这说明学生具备觉察能力。", source)


def test_conclusion_with_a_hedge_passes():
    source = "资料里只有零散描述。"
    assert not [row for row in aw.lint_facts("这可能说明学生有所觉察。", source)
                if row["kind"] == "conclusion"]


# ---------------------------------------------------------------------------
# 5. 导师的话写成学生的
# ---------------------------------------------------------------------------
MENTOR_SOURCE = "导师：我觉得你其实有能力表达自己的需求\n学生：嗯。"


def test_mentor_words_written_as_the_students_are_flagged():
    assert any(row["kind"] == "speaker"
               for row in aw.lint_facts("学生意识到自己有能力表达需求。", MENTOR_SOURCE))


def test_the_same_run_in_a_student_line_is_not_flagged():
    source = "导师：我觉得你其实有能力表达自己的需求\n学生：我自己也有能力表达需求。"
    assert not [row for row in aw.lint_facts("学生意识到自己有能力表达需求。", source)
                if row["kind"] == "speaker"]


def test_a_sentence_naming_the_mentor_is_not_flagged():
    assert not [row for row in aw.lint_facts("导师认为学生有能力表达需求。", MENTOR_SOURCE)
                if row["kind"] == "speaker"]


def test_a_source_without_labels_never_gives_a_speaker_finding():
    source = "家长反馈：孩子最近回家话变少了。"
    assert not [row for row in aw.lint_facts("学生意识到自己有能力表达需求。", source)
                if row["kind"] == "speaker"]


# ---------------------------------------------------------------------------
# 6. 改写不能把整段砍掉
# ---------------------------------------------------------------------------
def test_a_rewrite_to_a_two_word_stub_is_rejected():
    model = FakeModel(rewrite_to="学生。")
    bad = "学生上台讲完了。学生三次提到想放弃。"
    result = aw.run_guard([_block(bad)], call=model)
    assert result["blocks"]["b1"] == bad
    assert [flag["kind"] for flag in result["flags"]] == ["number"]


# ---------------------------------------------------------------------------
# 7. 保存不能删掉或确认标记
# ---------------------------------------------------------------------------
def _flag():
    return {"id": "ff1", "block_id": "b1", "sentence": "学生三次提到想放弃",
            "kind": "number", "problem": "数字“三次”在资料中找不到",
            "source_excerpt": "学生上台讲完了。", "block_text": "学生三次提到想放弃。",
            "acked": False}


def _flagged_doc():
    doc = _doc("学生三次提到想放弃。")
    doc["fact_flags"] = [_flag()]
    return doc


def test_save_cannot_erase_or_acknowledge_a_flag(api_client, m1db):
    prep = m1db.prep()
    first = store.save_doc(prep["id"], prep["rev"], _flagged_doc())
    _login(api_client, m1db.alice_id, "advisor", "Alice")

    # 1) 保存时把 fact_flags 整个去掉
    stripped = _doc("学生三次提到想放弃。")
    res = api_client.put("/api/m1/preps/%d/doc" % prep["id"],
                         json={"rev": first["rev"], "doc": stripped})
    assert res.status_code == 200
    stored = store.get_latest_version(prep["id"], "edit")["doc"]
    assert stored["fact_flags"] == [_flag()]

    # 2) 保存时把标记改成 acked
    tampered = _doc("学生三次提到想放弃。")
    tampered["fact_flags"] = [{**_flag(), "acked": True}]
    rev = store.get_prep(prep["id"])["rev"]
    res = api_client.put("/api/m1/preps/%d/doc" % prep["id"],
                         json={"rev": rev, "doc": tampered})
    assert res.status_code == 200
    stored = store.get_latest_version(prep["id"], "edit")["doc"]
    assert stored["fact_flags"] == [_flag()]

    # 标记仍然开着：定稿照常放行，但回报未核对数量
    res = api_client.post("/api/m1/preps/%d/finalize" % prep["id"])
    assert res.status_code == 200
    assert res.get_json()["open_flags"] == 1
