# -*- coding: utf-8 -*-
"""6 A.M. v0.5 求值器验收测试（docs/audits/plans-6am-v05/Q2-evaluator.md）。

覆盖：A1–A5 级别规则、亚型、两遍否定、A6 目录条件、spec 可编辑、视图兼容。
"""

import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from six_am import engine, presentation, rationale  # noqa: E402
from six_am.spec import DEFAULT_SPEC  # noqa: E402


def item(label, value, raw=None):
    return {"code": "", "label": label, "raw_value": value if raw is None else raw,
            "eval_value": value, "eval_source": "规则推导", "dimension": "",
            "level_code": None, "level_label": None, "data_bias": "正常"}


def order(value, pos, total=15):
    return {"code": "%03d" % (109 + pos), "label": "职业价值观排序%d" % pos,
            "raw_value": value, "eval_value": value, "eval_source": "原始排序",
            "dimension": "生涯力", "data_bias": "正常"}


def run(items, evidence=None, answers=None, params=None):
    return engine.run(items, student={"name": "测试学生", "grade": "高二"},
                      evidence=evidence, answers=answers, params=params)


def spec_copy():
    return copy.deepcopy(DEFAULT_SPEC)


class A1Levels(unittest.TestCase):
    def test_autonomy_low_alone_is_watch(self):
        a1 = run([item("自驱力-自主性", "偏低")])["dimensions"]["A1"]
        self.assertEqual(a1["state"], "Watch")
        self.assertEqual(a1["confidence"], "Hypothesis")

    def test_supporting_escalates_and_sets_subtype(self):
        a1 = run([item("自驱力-自主性", "偏低"),
                  order("独立自主", 2), order("上司关系", 4)])["dimensions"]["A1"]
        self.assertEqual(a1["state"], "At-Risk")
        self.assertEqual(a1["subtype"], "A1-S2")

    def test_confirm_blocks(self):
        p = run([item("自驱力-自主性", "偏低"),
                 order("独立自主", 2), order("上司关系", 4)],
                answers=[{"q": "Q1.4", "result": "confirm"}])
        a1 = p["dimensions"]["A1"]
        self.assertEqual(a1["state"], "Blocked")
        self.assertEqual(a1["confidence"], "Confirmed")

    def test_deny_removes_signal_and_scales_back(self):
        p = run([item("自驱力-自主性", "偏低"),
                 order("独立自主", 2), order("上司关系", 4)],
                answers=[{"q": "Q1.4", "result": "deny"}])
        a1 = p["dimensions"]["A1"]
        self.assertEqual(a1["state"], "Watch")
        self.assertNotIn("indep_boss_top5", [t["id"] for t in a1["triggered_rules"]])
        self.assertEqual(p["refuted"].get("indep_boss_top5"), "Q1.4")


class A2Levels(unittest.TestCase):
    def test_deep_and_surface_low_is_a2_s4(self):
        a2 = run([item("学习动机-深层动机", "偏低"),
                  item("学习动机-表面动机", "偏低")])["dimensions"]["A2"]
        self.assertEqual(a2["state"], "At-Risk")
        self.assertEqual(a2["subtype"], "A2-S4")

    def test_parent_complaint_escalates_and_confirms(self):
        on = run([item("学习动机-深层动机", "偏低")],
                 evidence={})
        a2 = on["dimensions"]["A2"]
        self.assertEqual(a2["state"], "Watch")

        off = run([item("学习动机-深层动机", "偏低")],
                  evidence={"parent": {"complaint": {"text": "孩子不想学"}}})
        a2 = off["dimensions"]["A2"]
        self.assertEqual(a2["state"], "Blocked")
        self.assertEqual(a2["confidence"], "Supported")

    def test_goal_disagreement_is_at_risk(self):
        a2 = run([item("学习动机-深层动机", "不低")],
                 evidence={"ft": {"goal": {"text": "升学", "judgement": "不认同"}}}
                 )["dimensions"]["A2"]
        self.assertEqual(a2["state"], "At-Risk")


class A3Gates(unittest.TestCase):
    def test_sleep_watch_plus_severe_depression_first_gate_wins(self):
        p = run([item("体质健康-睡眠评级", "中等"),
                 item("情绪稳定性-抑郁愉快", "需特殊关注")])
        a3 = p["dimensions"]["A3"]
        self.assertEqual(a3["state"], "At-Risk")
        self.assertEqual(a3["subtype"], "A3-S2")
        self.assertTrue(p["safety_review"])
        self.assertIn("情绪安全复核", a3["flags"])

    def test_anxiety_watch_raised_by_total_low(self):
        a3 = run([item("情绪稳定性-焦虑安详", "需关注"),
                  item("情绪稳定性总分", "明显偏低")])["dimensions"]["A3"]
        self.assertEqual(a3["state"], "At-Risk")
        self.assertEqual(a3["subtype"], "A3-S1")


class A4Tracks(unittest.TestCase):
    def test_one_track_is_watch_with_disagreement(self):
        a4 = run([item("学习动机-自我效能感", "偏低")])["dimensions"]["A4"]
        self.assertEqual(a4["state"], "Watch")
        self.assertTrue(a4["track_disagreement"])

    def test_both_tracks_at_risk(self):
        a4 = run([item("学习动机-自我效能感", "偏低"),
                  item("自驱力-胜任感", "偏低")])["dimensions"]["A4"]
        self.assertEqual(a4["state"], "At-Risk")
        self.assertFalse(a4["track_disagreement"])

    def test_one_track_plus_supporting_is_at_risk(self):
        a4 = run([item("学习动机-自我效能感", "偏低"),
                  item("思维模式结果", "45")])["dimensions"]["A4"]
        self.assertEqual(a4["state"], "At-Risk")


class A5Levels(unittest.TestCase):
    def test_conscientiousness_low_is_watch(self):
        a5 = run([item("人格-责任心", "偏低")])["dimensions"]["A5"]
        self.assertEqual(a5["state"], "Watch")

    def test_failed_task_alone_is_at_risk(self):
        a5 = run([], evidence={"ft": {"standard_task": {"can_split": False}}}
                 )["dimensions"]["A5"]
        self.assertEqual(a5["state"], "At-Risk")

    def test_task_blocks_when_y4_already_at_risk(self):
        a5 = run([item("人格-责任心", "偏低"),
                  item("职业兴趣-常规型", "高")],
                 evidence={"ft": {"standard_task": {"can_split": False}}}
                 )["dimensions"]["A5"]
        self.assertEqual(a5["state"], "Blocked")


class A6Catalogue(unittest.TestCase):
    def _plan(self, items, evidence=None):
        return run(items, evidence=evidence)["support_plan"]

    def test_introvert_gets_mentor(self):
        plan = self._plan([item("人格-外倾性", "偏低")])
        self.assertIn("导师主动联系", [r["direction"] for r in plan["ranked"]])

    def test_parent_low_puts_accompany_in_avoid(self):
        plan = self._plan([item("依恋关系-信任-母亲", "偏低")])
        avoided = {a["direction"] for a in plan["avoid"]}
        self.assertIn("家长陪同", avoided)
        self.assertNotIn("家长陪同", [r["direction"] for r in plan["ranked"]])

    def test_anxiety_puts_public_commitment_in_avoid(self):
        plan = self._plan([item("情绪稳定性-焦虑安详", "需关注"),
                           order("成就感", 2)])
        avoided = {a["direction"] for a in plan["avoid"]}
        self.assertIn("公开承诺 / 适度竞争", avoided)

    def test_support_entry_shape(self):
        plan = self._plan([item("人格-外倾性", "偏低")])
        for entry in plan["ranked"]:
            self.assertEqual(set(entry.keys()),
                             {"direction", "sub_mechanisms", "fit_label",
                              "basis_rules", "cautions"})
            self.assertIn(entry["fit_label"], {"优先", "慎用"})

    def test_caution_marks_a1_s2_mentor_as_cautious(self):
        plan = self._plan([item("自驱力-自主性", "偏低"),
                           order("独立自主", 2), order("上司关系", 4)])
        mentor = [r for r in plan["ranked"] if r["direction"] == "导师主动联系"][0]
        self.assertEqual(mentor["fit_label"], "慎用")
        self.assertIn("只由学生选的成人、私下进行", mentor["cautions"])


class SpecEdits(unittest.TestCase):
    def test_removing_control_low_stops_escalation(self):
        items = [item("自驱力-自主性", "偏低"),
                 item("情绪稳定性-无力感掌控感", "需关注", raw="4")]
        default = run(items)["dimensions"]["A1"]
        self.assertEqual(default["state"], "At-Risk")

        spec = spec_copy()
        spec["dimensions"]["A1"]["supporting"] = ["indep_boss_top5"]
        edited = run(items, params={"spec": spec})["dimensions"]["A1"]
        self.assertEqual(edited["state"], "Watch")

    def test_top_n_values_three_excludes_boss_rank_4(self):
        items = [item("自驱力-自主性", "偏低"),
                 order("独立自主", 2), order("上司关系", 4)]
        default = run(items)["dimensions"]["A1"]
        self.assertEqual(default["state"], "At-Risk")

        spec = spec_copy()
        spec["params"]["top_n_values"] = 3
        edited = run(items, params={"spec": spec})["dimensions"]["A1"]
        self.assertEqual(edited["state"], "Watch")

    def test_profile_metadata(self):
        p = run([item("自驱力-自主性", "偏低")])
        self.assertEqual(p["schema"], "six-am-profile-v3")
        self.assertEqual(p["engine"], "v0.5")
        self.assertEqual(p["spec_version"], "v0.5")
        self.assertIsInstance(p["flags_global"], list)
        a1 = p["dimensions"]["A1"]
        for key in ("state", "subtype", "subtype_name", "confidence", "activation_key",
                    "triggered_rules", "cross_mods", "flags", "notes",
                    "secure_confirmed", "distance"):
            self.assertIn(key, a1)


class ViewCompat(unittest.TestCase):
    def test_view_model_and_rationale_render_signal_labels(self):
        p = run([item("自驱力-自主性", "偏低"),
                 order("独立自主", 2), order("上司关系", 4)])
        vm = presentation.build_view_model(p)
        cards = {c["dim"]: c for c in vm["cards"]}
        self.assertEqual(cards["A1"]["state"], "At-Risk")
        self.assertEqual(cards["A1"]["subtype_display"], "自主抗争型")
        self.assertEqual(cards["A1"]["verdict"], "想自己做主但缺少空间，可能用对抗来争取自主。")

        rec = rationale.build_rationale("A1", p["dimensions"]["A1"],
                                        p["questions"], p["answers"])
        blob = json.dumps(rec, ensure_ascii=False)
        self.assertIn("自驱力-自主性", blob)
        self.assertIn("独立自主 + 上司关系 同进前 N", blob)

    def test_a3_display_names(self):
        self.assertEqual(rationale.SUBTYPE_DISPLAY["A3-S1"], "情绪消耗型")
        self.assertEqual(rationale.SUBTYPE_DISPLAY["A3-S4"], "时间过满型")
        self.assertEqual(rationale.VERDICT["A3-S1"],
                         "情绪消耗在占用精力，现在加任务可能适得其反。")
        self.assertEqual(rationale.VERDICT["A3-S4"],
                         "时间已经排满，没有空间开始新的事情。")


class FirstTouchConfirmsOnlyWhenItShowsAProblem(unittest.TestCase):
    """填写过 First Touch 不等于佐证：只有目标部分/不认同、时间排满、小任务未通过才算。"""

    LOW2 = [item("学习动机-深层动机", "偏低"), item("学习动机-表面动机", "偏低")]

    def _dim(self, items, ft, dim):
        return run(items, evidence={"ft": ft})["dimensions"][dim]

    def test_a2_goal_agreed_does_not_block(self):
        a2 = self._dim(self.LOW2, {"goal": {"text": "x", "judgement": "认同"}}, "A2")
        self.assertEqual(a2["state"], "At-Risk")
        self.assertEqual(a2["confidence"], "Hypothesis")

    def test_a2_goal_disagreed_confirms_learning_risk(self):
        a2 = self._dim(self.LOW2, {"goal": {"text": "x", "judgement": "不认同"}}, "A2")
        self.assertEqual(a2["state"], "Blocked")

    def test_a2_goal_partial_with_surface_low_only_is_watch(self):
        a2 = self._dim([item("学习动机-表面动机", "偏低")],
                       {"goal": {"text": "x", "judgement": "部分认同"}}, "A2")
        self.assertEqual(a2["state"], "Watch")

    def test_a5_task_passed_does_not_block(self):
        a5 = self._dim([item("人格-责任心", "偏低"), item("职业兴趣-常规型", "高")],
                       {"standard_task": {"can_split": True, "can_commit": True}}, "A5")
        self.assertEqual(a5["state"], "At-Risk")

    def test_a3_y4_risk_plus_full_schedule_blocks(self):
        a3 = self._dim([item("体质健康-睡眠评级", "差")],
                       {"schedule": {"load_level": "高"}}, "A3")
        self.assertEqual(a3["state"], "Blocked")
        self.assertEqual(a3["subtype"], "A3-S2")

    def test_a3_light_schedule_does_not_confirm(self):
        a3 = self._dim([item("体质健康-睡眠评级", "差")],
                       {"schedule": {"load_level": "低", "free_hours_per_week": 20}}, "A3")
        self.assertEqual(a3["state"], "At-Risk")

    def test_a1_secure_signal_not_listed_as_risk_reason(self):
        a1 = run([item("自驱力-自主性", "偏低"), item("自我概念-幸福与满足", "高"),
                  order("独立自主", 2), order("上司关系", 4)])["dimensions"]["A1"]
        self.assertEqual(a1["state"], "At-Risk")
        self.assertNotIn("wellbeing_ok", [t["id"] for t in a1["triggered_rules"]])

    def test_a3_full_schedule_alone_is_risk(self):
        a3 = self._dim([], {"schedule": {"load_level": "高"}}, "A3")
        self.assertEqual(a3["state"], "At-Risk")
        self.assertEqual(a3["subtype"], "A3-S4")


if __name__ == "__main__":
    unittest.main(verbosity=2)
