# -*- coding: utf-8 -*-
"""6 A.M. v0.6 求值器验收测试（docs/audits/plans-6am-v06/R2-evaluator.md）。

覆盖：三值逻辑、A1–A5 级别、会谈与归因、类型、A6 排序、输入闭环。
"""

import copy
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from six_am import inputs_from_profile, merge_inputs  # noqa: E402
from six_am import evaluator_v06  # noqa: E402
from six_am.engine import Ctx  # noqa: E402
from six_am.model import load_model  # noqa: E402


def item(label, value, raw=None):
    return {"code": "", "label": label, "raw_value": value if raw is None else raw,
            "eval_value": value, "eval_source": "规则推导", "dimension": "",
            "level_code": None, "level_label": None, "data_bias": "正常"}


def order(value, pos, total=15):
    return {"code": "%03d" % (109 + pos), "label": "职业价值观排序%d" % pos,
            "raw_value": value, "eval_value": value, "eval_source": "原始排序",
            "dimension": "生涯力", "data_bias": "正常"}


def run(items, inputs=None):
    return evaluator_v06.run(items, {"name": "测试学生", "grade": "初二"},
                              inputs if inputs is not None else {"talks": {}}, 1)


def cond_env(items):
    model = load_model()
    params = dict(model["params"])
    return {"ctx": Ctx(items, {}, params), "model": model, "params": params,
            "talks": {}, "inputs": {}, "dims": None}


class ThreeValued(unittest.TestCase):
    def test_missing_label_leaves_part_unresolved(self):
        dim = run([])["dims"]["A1"]
        self.assertIsNone(dim["parts"]["main"]["level"])
        self.assertIsNone(dim["level"])
        self.assertFalse(dim["parts"]["main"]["nodes"]["风险"]["ok"])

    def test_not_of_missing_stays_missing(self):
        env = cond_env([])
        value, facts = evaluator_v06.cond(
            {"not": {"y4": "自驱力-自主性", "band": "高"}}, env)
        self.assertIsNone(value)
        self.assertEqual(facts, [{"label": "自驱力-自主性"}])

    def test_not_of_false_is_true(self):
        env = cond_env([item("自驱力-自主性", "偏低")])
        value, _facts = evaluator_v06.cond(
            {"not": {"y4": "自驱力-自主性", "band": "高"}}, env)
        self.assertIs(value, True)

    def test_any_all_three_valued(self):
        env = cond_env([item("自驱力-自主性", "偏低")])
        missing = {"y4": "不存在的标签", "band": "高"}
        false = {"y4": "自驱力-自主性", "band": "高"}
        self.assertIs(evaluator_v06.cond({"any": [false, missing]}, env)[0], None)
        self.assertIs(evaluator_v06.cond({"all": [missing, false]}, env)[0], False)
        self.assertIs(evaluator_v06.cond({"all": [missing, {"else": True}]}, env)[0], None)
        self.assertIs(evaluator_v06.cond({"any": [false, {"else": True}]}, env)[0], True)


class A1Autonomy(unittest.TestCase):
    def _level(self, items, inputs=None):
        return run(items, inputs)["dims"]["A1"]

    def test_good_is_secure(self):
        self.assertEqual(self._level([item("自驱力-自主性", "较好")])["level"], "稳固")

    def test_not_low_is_watch(self):
        self.assertEqual(self._level([item("自驱力-自主性", "不低")])["level"], "关注")

    def test_not_low_plus_rank_is_risk(self):
        dim = self._level([item("自驱力-自主性", "不低"), order("独立自主", 3)])
        self.assertEqual(dim["level"], "风险")

    def test_low_is_risk(self):
        self.assertEqual(self._level([item("自驱力-自主性", "偏低")])["level"], "风险")

    def test_talk_confirm_blocks(self):
        dim = self._level([item("自驱力-自主性", "偏低")],
                          {"talks": {"A1": {"result": "confirm"}}})
        self.assertEqual(dim["level"], "阻塞")
        self.assertEqual(dim["model_level"], "阻塞")
        self.assertTrue(dim["blocked"])

    def test_talk_set_overrides_level(self):
        dim = self._level([item("自驱力-自主性", "偏低")],
                          {"talks": {"A1": {"result": "set", "set_level": "关注"}}})
        self.assertEqual(dim["level"], "关注")
        self.assertEqual(dim["model_level"], "风险")
        self.assertTrue(dim["set_by_talk"])
        self.assertFalse(dim["blocked"])

    def test_cause_hint_pressed(self):
        dim = self._level([item("自驱力-自主性", "偏低"),
                          order("独立自主", 2), order("上司关系", 4),
                          item("情绪稳定性-无力感掌控感", "需关注", raw="4")])
        pressed = [c for c in dim["causes"] if c["id"] == "pressed"][0]
        self.assertIs(pressed["hint"], True)
        self.assertFalse(pressed["picked"])

    def test_cause_picked_from_talk(self):
        dim = self._level([item("自驱力-自主性", "偏低")],
                          {"talks": {"A1": {"result": "confirm", "causes": ["pressed"]}}})
        pressed = [c for c in dim["causes"] if c["id"] == "pressed"][0]
        self.assertTrue(pressed["picked"])


class A2Identity(unittest.TestCase):
    def _dim(self, items, inputs=None):
        return run(items, inputs)["dims"]["A2"]

    def test_not_low_plus_surface_high_is_risk(self):
        dim = self._dim([item("学习动机-深层动机", "不低"),
                        item("学习动机-表面动机", "高")])
        self.assertEqual(dim["level"], "风险")

    def test_parent_complaint_raises_to_risk(self):
        dim = self._dim([item("学习动机-深层动机", "不低")],
                        {"parent": {"complaint": {"text": "孩子不想学"}}, "talks": {}})
        self.assertEqual(dim["level"], "风险")

    def test_outside_disagreement_is_dim_risk(self):
        dim = self._dim([item("学习动机-深层动机", "高")],
                        {"ft": {"goal": {"judgement": "不认同"}}, "talks": {}})
        self.assertEqual(dim["parts"]["learning"]["level"], "稳固")
        self.assertEqual(dim["parts"]["outside"]["level"], "风险")
        self.assertEqual(dim["level"], "风险")

    def test_blocked_only_through_learning(self):
        dim = self._dim([item("学习动机-深层动机", "高")],
                        {"ft": {"goal": {"judgement": "不认同"}},
                         "talks": {"A2": {"result": "confirm"}}})
        self.assertEqual(dim["level"], "风险")
        self.assertFalse(dim["blocked"])

    def test_learning_risk_plus_talk_confirm_blocks(self):
        dim = self._dim([item("学习动机-深层动机", "偏低")],
                        {"talks": {"A2": {"result": "confirm"}}})
        self.assertEqual(dim["level"], "阻塞")

    def test_outside_type_when_time_on_unliked(self):
        dim = self._dim([item("学习动机-深层动机", "高")],
                        {"ft": {"goal": {"judgement": "部分认同",
                                         "time_on_liked": False}}, "talks": {}})
        self.assertEqual(dim["parts"]["outside"]["types"], ["兴趣错位型"])


class A3Space(unittest.TestCase):
    def _parts(self, items, inputs=None):
        return run(items, inputs)["dims"]["A3"]

    def test_body_all_good_is_secure(self):
        dim = self._parts([item("体质健康-睡眠评级", "优"),
                          item("体质健康-运动评级", "优"),
                          item("体质健康-饮食评级", "优")])
        self.assertEqual(dim["parts"]["body"]["level"], "稳固")

    def test_body_one_not_good_is_watch(self):
        dim = self._parts([item("体质健康-睡眠评级", "优"),
                          item("体质健康-运动评级", "良好"),
                          item("体质健康-饮食评级", "优")])
        self.assertEqual(dim["parts"]["body"]["level"], "关注")

    def test_body_none_good_is_risk(self):
        dim = self._parts([item("体质健康-睡眠评级", "良好"),
                          item("体质健康-运动评级", "中等"),
                          item("体质健康-饮食评级", "良好")])
        self.assertEqual(dim["parts"]["body"]["level"], "风险")

    def test_body_any_bad_is_risk(self):
        dim = self._parts([item("体质健康-睡眠评级", "优"),
                          item("体质健康-运动评级", "较差"),
                          item("体质健康-饮食评级", "优")])
        self.assertEqual(dim["parts"]["body"]["level"], "风险")

    def test_emotion_total_bands(self):
        self.assertEqual(self._parts([item("情绪稳定性总分", "偏低", raw="24")])
                         ["parts"]["emotion"]["level"], "风险")
        self.assertEqual(self._parts([item("情绪稳定性总分", "不低", raw="30")])
                         ["parts"]["emotion"]["level"], "关注")
        self.assertEqual(self._parts([item("情绪稳定性总分", "较好", raw="50")])
                         ["parts"]["emotion"]["level"], "稳固")

    def test_emotion_sub_item_severe_is_risk(self):
        dim = self._parts([item("情绪稳定性-抑郁愉快", "需特殊关注")])
        self.assertEqual(dim["parts"]["emotion"]["level"], "风险")

    def test_time_needs_confirmed_full(self):
        without = self._parts([item("体质健康-睡眠评级", "差")])
        self.assertIsNone(without["parts"]["time"]["level"])
        with_full = self._parts([item("体质健康-睡眠评级", "差")],
                                {"ft": {"schedule": {"confirmed_full": True}},
                                 "talks": {}})
        self.assertEqual(with_full["parts"]["time"]["level"], "风险")

    def test_blocked_when_emotion_risk_and_schedule_full(self):
        dim = self._parts([item("情绪稳定性总分", "偏低", raw="20")],
                          {"ft": {"schedule": {"confirmed_full": True}}, "talks": {}})
        self.assertEqual(dim["level"], "阻塞")
        self.assertTrue(dim["blocked"])

    def test_types_are_parts_at_worst_level(self):
        dim = self._parts([item("情绪稳定性总分", "偏低", raw="24")])
        self.assertEqual(dim["types"], ["情绪消耗型"])


class A4Confidence(unittest.TestCase):
    def _dim(self, items):
        return run(items)["dims"]["A4"]

    def test_both_good_is_secure(self):
        dim = self._dim([item("学习动机-自我效能感", "较好"),
                        item("自驱力-胜任感", "较好")])
        self.assertEqual(dim["level"], "稳固")

    def test_mixed_is_watch(self):
        dim = self._dim([item("学习动机-自我效能感", "较好"),
                        item("自驱力-胜任感", "不低")])
        self.assertEqual(dim["level"], "关注")

    def test_any_low_is_risk(self):
        dim = self._dim([item("学习动机-自我效能感", "偏低"),
                        item("自驱力-胜任感", "高")])
        self.assertEqual(dim["level"], "风险")

    def test_type_falls_through_to_low_efficacy(self):
        dim = self._dim([item("学习动机-自我效能感", "偏低")])
        self.assertEqual(dim["types"], ["低自我效能型"])

    def test_cognitive_bias_beats_evaluation_anxiety(self):
        dim = self._dim([item("认知能力", "高", raw="90"),
                        item("学习动机-自我效能感", "偏低"),
                        item("情绪稳定性-自卑自尊", "需关注"),
                        item("情绪稳定性-焦虑安详", "需关注")])
        self.assertEqual(dim["types"], ["认知偏差型"])


class A5Start(unittest.TestCase):
    def _dim(self, items, inputs=None):
        return run(items, inputs)["dims"]["A5"]

    def test_openness_low_is_try_watch(self):
        dim = self._dim([item("人格-开放性", "偏低", raw="3.2")])
        self.assertEqual(dim["parts"]["try"]["level"], "关注")

    def test_openness_low_plus_safety_top_is_try_risk(self):
        dim = self._dim([item("人格-开放性", "偏低", raw="3.2"),
                        order("安全稳定", 2)])
        self.assertEqual(dim["parts"]["try"]["level"], "风险")

    def test_plan_watch_plus_low_conscientiousness_is_risk(self):
        dim = self._dim([item("学习方法与策略-学习自我调节", "不低"),
                        item("学习方法与策略-学习深层方法与策略", "不低"),
                        item("人格-责任心", "偏低")])
        self.assertEqual(dim["parts"]["plan"]["level"], "风险")

    def test_distract_low_is_risk(self):
        dim = self._dim([item("执行功能-抑制控制", "偏低")])
        self.assertEqual(dim["parts"]["distract"]["level"], "风险")

    def test_cannot_split_blocks_a_risk_dim(self):
        dim = self._dim([item("学习方法与策略-学习自我调节", "不低"),
                        item("学习方法与策略-学习深层方法与策略", "不低"),
                        item("人格-责任心", "偏低")],
                        {"ft": {"standard_task": {"can_split": False}}, "talks": {}})
        self.assertEqual(dim["level"], "阻塞")

    def test_cannot_split_does_not_block_a_watch_dim(self):
        dim = self._dim([item("执行功能-抑制控制", "不低")],
                       {"ft": {"standard_task": {"can_split": False}}, "talks": {}})
        self.assertEqual(dim["level"], "关注")


class RelativeLow(unittest.TestCase):
    LABELS = load_model()["self_concept_items"]
    TARGET = "自我概念-能力与学校表现"

    def _value(self, items):
        return evaluator_v06.cond({"y4_rel_low": self.TARGET}, cond_env(items))[0]

    def _items(self, target_raw, others_raw):
        items = [item(self.TARGET, "偏低", raw=str(target_raw))]
        for label, raw in zip([l for l in self.LABELS if l != self.TARGET], others_raw):
            items.append(item(label, "不低", raw=str(raw)))
        return items

    def test_lowest_is_true(self):
        self.assertIs(self._value(self._items(2, [3, 4, 5, 6, 7])), True)

    def test_not_lowest_is_false(self):
        self.assertIs(self._value(self._items(5, [3, 4, 5, 6, 7])), False)

    def test_tie_counts(self):
        self.assertIs(self._value(self._items(2, [2, 4, 5, 6, 7])), True)

    def test_missing_item_is_none(self):
        items = self._items(2, [3, 4, 5, 6, 7])
        del items[-1]["eval_value"]
        items[-1]["raw_value"] = ""
        self.assertIsNone(self._value(items))


class A6Supports(unittest.TestCase):
    def _a6(self, items, inputs=None):
        return run(items, inputs)["a6"]

    def test_avoid_removes_item(self):
        plan = self._a6([item("情绪稳定性-焦虑安详", "需关注"), order("成就感", 2)])
        avoided = {entry["id"] for entry in plan["avoid"]}
        self.assertIn("public_commitment", avoided)
        self.assertNotIn("public_commitment", [entry["id"] for entry in plan["ranked"]])
        entry = [e for e in plan["avoid"] if e["id"] == "public_commitment"][0]
        self.assertEqual(entry["why"], "焦虑或自卑需关注不用")

    def test_caution_sorts_after_equal_severity_recommendation(self):
        plan = self._a6([item("执行功能-抑制控制", "不低"),
                        item("学习动机-自我效能感", "不低"),
                        item("自驱力-胜任感", "不低"),
                        item("情绪稳定性-焦虑安详", "需关注")])
        ranked = {entry["id"]: entry for entry in plan["ranked"]}
        self.assertEqual(ranked["checkpoints"]["fit_label"], "慎用")
        self.assertIn("慎用：焦虑需关注", ranked["checkpoints"]["why"])
        order_ids = [entry["id"] for entry in plan["ranked"]]
        self.assertLess(order_ids.index("small_wins"), order_ids.index("checkpoints"))

    def test_risk_link_beats_y4_only_fit(self):
        plan = self._a6([item("自驱力-自主性", "偏低"),
                        item("人格-外倾性", "偏低")])
        ids = [entry["id"] for entry in plan["ranked"]]
        self.assertLess(ids.index("limited_choice"), ids.index("mentor_reach_out"))
        mentor = [entry for entry in plan["ranked"]
                  if entry["id"] == "mentor_reach_out"][0]
        self.assertEqual(mentor["why"], ["Y4：外倾性 偏低"])

    def test_top_marks_first_four(self):
        plan = self._a6([item("自驱力-自主性", "偏低"), item("人格-外倾性", "偏低"),
                        item("职业兴趣-常规型", "高"), item("人格-责任心", "偏低"),
                        item("学习方法与策略-学习自我调节", "不低"),
                        item("学习方法与策略-学习深层方法与策略", "不低"),
                        item("学习动机-自我效能感", "不低"),
                        item("自驱力-胜任感", "不低")])
        self.assertGreater(len(plan["ranked"]), 4)
        self.assertEqual([entry["top"] for entry in plan["ranked"][:4]], [True] * 4)
        self.assertFalse(plan["ranked"][4]["top"])

    def test_passion_project_needs_holland_peak(self):
        without = self._a6([item("学习动机-深层动机", "不低")])
        self.assertNotIn("passion_project", [entry["id"] for entry in without["ranked"]])

        with_peak = self._a6([item("学习动机-深层动机", "不低"),
                              item("职业兴趣-现实型", "高")])
        self.assertIn("passion_project", [entry["id"] for entry in with_peak["ranked"]])

    def test_cause_link_uses_hint_when_nothing_picked(self):
        plan = self._a6([item("自驱力-自主性", "偏低"),
                        order("独立自主", 2), order("上司关系", 4),
                        item("情绪稳定性-无力感掌控感", "需关注", raw="4")])
        ids = [entry["id"] for entry in plan["ranked"]]
        self.assertIn("passion_project", ids)
        passion = [entry for entry in plan["ranked"] if entry["id"] == "passion_project"][0]
        self.assertEqual(passion["why"], ["A1 被强压"])


class ProfileShape(unittest.TestCase):
    def test_keys_match_readme(self):
        profile = run([item("自驱力-自主性", "偏低")])
        self.assertEqual(set(profile), {
            "schema", "model_version", "generated_at", "report_id", "student",
            "inputs", "dims", "order", "a6", "flags"})
        self.assertEqual(profile["schema"], "6am.v0.6")
        self.assertEqual(profile["model_version"], "v0.6")
        self.assertEqual(profile["student"], {"name": "测试学生", "grade": "初二"})
        self.assertEqual(set(profile["flags"]), {"safety", "answer_state"})

        dim = profile["dims"]["A1"]
        self.assertEqual(set(dim), {
            "level", "model_level", "blocked", "set_by_talk", "parts", "types",
            "causes", "refs", "blocked_ok"})
        self.assertEqual(set(dim["parts"]["main"]), {"level", "nodes", "types"})
        self.assertEqual(set(dim["parts"]["main"]["nodes"]["风险"]), {"ok", "facts"})

    def test_order_is_worst_level_first_then_ax(self):
        profile = run([item("自驱力-自主性", "不低"),
                       item("学习方法与策略-学习自我调节", "不低"),
                       item("学习方法与策略-学习深层方法与策略", "不低"),
                       item("人格-责任心", "偏低")])
        self.assertEqual(profile["dims"]["A5"]["level"], "风险")
        self.assertEqual(profile["dims"]["A1"]["level"], "关注")
        self.assertEqual(profile["order"][:2], ["A5", "A1"])
        self.assertEqual(profile["order"][2:], ["A2", "A3", "A4"])

    def test_safety_flag_from_severe_emotion(self):
        profile = run([item("情绪稳定性-抑郁愉快", "需特殊关注")])
        self.assertTrue(profile["flags"]["safety"])

    def test_inputs_are_kept_in_profile(self):
        inputs = {"ft": {"goal": {"judgement": "认同"}}, "talks": {}}
        self.assertEqual(run([], inputs)["inputs"], inputs)


class InputsLoop(unittest.TestCase):
    def test_inputs_from_v06_profile_is_a_deep_copy(self):
        prev = {"schema": "6am.v0.6",
                "inputs": {"ft": {"goal": {"judgement": "认同"}},
                           "talks": {"A1": {"result": "confirm"}}}}
        inputs = inputs_from_profile(prev)
        self.assertEqual(inputs, prev["inputs"])
        inputs["talk"] = "x"
        del inputs["talks"]
        self.assertIn("talks", prev["inputs"])

    def test_inputs_from_legacy_profile_keeps_only_ft_and_parent(self):
        prev = {"schema": "six-am-profile-v3",
                "evidence_log": [
                    {"source": "FT", "kind": "goal",
                     "detail": {"text": "x", "judgement": "认同"}},
                    {"source": "家长", "kind": "complaint",
                     "detail": {"complaint": {"text": "不想学"}}},
                    {"source": "观察", "kind": "record", "detail": {"a": 1}}],
                "answers": [{"q": "Q1.1", "result": "confirm"}]}
        self.assertEqual(inputs_from_profile(prev), {
            "ft": {"goal": {"text": "x", "judgement": "认同"}},
            "parent": {"complaint": {"text": "不想学"}},
            "talks": {}})

    def test_inputs_from_none(self):
        self.assertEqual(inputs_from_profile(None), {"talks": {}})

    def test_merge_replaces_talk_whole(self):
        base = {"ft": {"goal": {"judgement": "认同"}, "notes": "旧"},
                "talks": {"A1": {"result": "confirm", "causes": ["pressed"],
                                 "note": "旧"}}}
        merged = merge_inputs(base, {"talks": {"A1": {"result": "deny"}}})
        self.assertEqual(merged["talks"]["A1"], {"result": "deny"})
        self.assertEqual(merged["ft"]["notes"], "旧")

    def test_merge_null_deletes_talk(self):
        merged = merge_inputs({"talks": {"A1": {"result": "confirm"}}},
                              {"talks": {"A1": None}})
        self.assertEqual(merged["talks"], {})

    def test_merge_deep_merges_ft(self):
        merged = merge_inputs({"ft": {"goal": {"judgement": "认同"},
                                      "standard_task": {"can_split": True}}},
                              {"ft": {"goal": {"time_on_liked": False}}})
        self.assertEqual(merged["ft"]["standard_task"], {"can_split": True})
        self.assertEqual(merged["ft"]["goal"],
                         {"judgement": "认同", "time_on_liked": False})


SMOKE_SCRIPT = r"""
import sys
import db
from six_am import build_v06_profile

failed = []
ids = [row["report_id"] for row in db.get_all_reports()]
for report_id in ids:
    try:
        build_v06_profile(report_id)
    except Exception as exc:  # noqa: BLE001
        failed.append((report_id, repr(exc)))
if failed:
    print(failed)
    sys.exit(1)
print("ok", len(ids))
"""


@unittest.skipUnless(os.environ.get("SIX_AM_SMOKE_DB"),
                     "set SIX_AM_SMOKE_DB to a DB copy to run")
class RealDataSmoke(unittest.TestCase):
    def test_every_report_runs(self):
        db_path = os.path.abspath(os.environ["SIX_AM_SMOKE_DB"])
        env = dict(os.environ)
        env["DATABASE_URL"] = "sqlite:///" + db_path
        proc = subprocess.run([sys.executable, "-c", SMOKE_SCRIPT], cwd=str(ROOT),
                              env=env, capture_output=True, text=True, timeout=600)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
