"""T6a：代码检查只报该报的。全部离线，不调用模型。"""
from __future__ import annotations

from pathlib import Path

import ai_writing as aw

SOURCE = (Path(__file__).with_name("fixtures") / "ai_eval" / "first_meeting.txt").read_text(
    encoding="utf-8")
_LINES = SOURCE.splitlines()
STUDENT_LINE = _LINES[7]        # [00:02:12] 学生：……手心全是汗，喉咙也发紧
MENTOR_QUESTION = _LINES[8]     # [00:02:50] 导师：你说手心出汗、喉咙发紧……
STUDENT_ANSWER = _LINES[9]      # [00:03:00] 学生：有一秒钟想过……
SHORT_SOURCE = "\n".join([STUDENT_LINE, MENTOR_QUESTION, STUDENT_ANSWER])


def _kinds(text, source=SOURCE):
    return {(row["kind"], row["value"]) for row in aw.lint_facts(text, source)}


def _has(kind, text, source=SOURCE):
    return any(found == kind for found, _ in _kinds(text, source))


# ---------------------------------------------------------------------------
# 新增的四类真实错误
# ---------------------------------------------------------------------------
def test_observer_not_in_source_is_flagged():
    # 学生说的犯困，被写成了老师的观察
    assert ("observer", "老师观察到") in _kinds("老师观察到学生犯困。")


def test_observer_in_source_passes():
    assert not _has("observer", "老师看到学生上课低下头。", "老师：我看到他上课低下头。")


def test_y4_score_as_student_speech_is_flagged():
    assert _has("y4_as_speech", "学生表示同伴亲近得分偏低。")


def test_first_person_outside_quotes_is_flagged():
    # 附录把学生的话直接写成文档自己的话
    assert _has("first_person", "我上次上台前很紧张，手心全是汗。")


def test_first_person_inside_quotes_passes():
    assert not _has("first_person", "学生说“我上次上台前很紧张”。")


def test_frequency_words_are_flagged_and_pass_when_in_source():
    assert _has("intensity", "学生与父母沟通频率低。")
    assert _has("intensity", "这种状态持续性很强。")
    assert not _has("intensity", "学生与父母沟通频率比较低。", "妈妈问过沟通频率")


# ---------------------------------------------------------------------------
# 去掉的误报
# ---------------------------------------------------------------------------
def test_line_nine_mentor_question_no_longer_counts_as_speaker():
    assert not _has("speaker", "轮到自己之前，学生手心出汗、喉咙发紧。", SHORT_SOURCE)


def test_mentor_view_still_counts_as_speaker():
    # 第 27 行导师自己的看法，仍然不能写成学生的
    assert _has("speaker", "学生认为自己其实有能力表达需求。")


def test_geometry_proof_is_not_a_conclusion():
    assert not _has("conclusion", "学生做几何证明题时卡住了。")


def test_open_question_is_not_a_conclusion():
    assert not _has("conclusion", "学生是否具备识别能力。")
    assert not _has("conclusion", "学生需要确认是否具备识别能力。")


def test_pronoun_after_named_role_is_not_a_problem():
    assert aw.pronoun_problem("与父亲话比较多，他会问学生。", "") is False


def test_pronoun_without_named_role_is_still_a_problem():
    assert aw.pronoun_problem("母亲会煮鸡蛋给他。", "") is True


# ---------------------------------------------------------------------------
# 新类型要能显示在标记里
# ---------------------------------------------------------------------------
def test_new_kinds_carry_a_problem_text():
    def echo(prompt):
        if "事实核对员" in prompt:
            text = prompt.split("【文字】\n", 1)[1].split("\n【资料】", 1)[0]
            return {"sentences": [{"text": piece, "verdict": "supported", "problem": ""}
                                  for piece in aw._sentences(text)]}
        return {"text": prompt.split("【文字】\n", 1)[1].split("\n【问题】", 1)[0]}

    text = "学生表示同伴亲近得分偏低。老师观察到学生犯困。"
    result = aw.run_guard([{"id": "b1", "text": text, "source": SOURCE}], call=echo)
    kinds = {flag["kind"] for flag in result["flags"]}
    assert {"y4_as_speech", "observer"} <= kinds
    assert all(flag["problem"] for flag in result["flags"])
