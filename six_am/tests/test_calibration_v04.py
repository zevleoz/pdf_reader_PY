# -*- coding: utf-8 -*-
"""v0.4 校准：证据强度（tier）、情绪安全复核、数据缺失、Y4 内部能力-自评落差、逆反判定修正。

背景：v0.3 直接用 Y4 报告档位触发干预，真实学生库 8 名学生里 5 名 A1 = Blocked、
中位数 3 个维度 ≥ At-Risk。v0.4 让单个弱信号只到 Watch；三级状态不变（关注/风险/阻塞），
只凭 Y4 也可判阻塞，"待证实"由证据等级（仅线索）表达，不另设状态。

运行：python3.11 -m unittest six_am.tests.test_calibration_v04 -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from six_am import engine  # noqa: E402


def item(label, eval_value, raw=None):
    return {"code": "", "label": label, "raw_value": eval_value if raw is None else raw,
            "eval_value": eval_value, "eval_source": "规则推导", "dimension": "",
            "data_bias": "正常"}


def order(value, pos):
    return {"code": "%03d" % (109 + pos), "label": "职业价值观排序%d" % pos,
            "raw_value": value, "eval_value": value, "eval_source": "原始排序",
            "dimension": "生涯力", "data_bias": "正常"}


def run(items, evidence=None):
    return engine.run(items, student={"name": "t", "grade": "g"}, evidence=evidence)


def ids(rec):
    return [t["id"] for t in rec.get("triggered_rules") or []]


class NormReferencedTier(unittest.TestCase):
    """自驱力/学习动机/学习方法：Y4 '偏低' = 低于常模 0.5 分；低于 1.5 分才是强信号。"""

    def test_slightly_below_norm_is_watch(self):
        a1 = run([item("自驱力-自主性", "偏低", "5.2"),
                  item("自驱力-自主性常模平均数", None, "5.9")])["dimensions"]["A1"]
        self.assertEqual(a1["state"], "Watch")

    def test_far_below_norm_is_at_risk(self):
        a1 = run([item("自驱力-自主性", "偏低", "3.3"),
                  item("自驱力-自主性常模平均数", None, "6.1")])["dimensions"]["A1"]
        self.assertEqual(a1["state"], "At-Risk")

    def test_band_only_defaults_to_mild(self):
        a4 = run([item("学习动机-自我效能感", "偏低")])["dimensions"]["A4"]
        self.assertEqual(a4["state"], "Watch")

    def test_two_core_mild_signals_converge(self):
        a4 = run([item("学习动机-自我效能感", "偏低"),
                  item("自驱力-胜任感", "偏低")])["dimensions"]["A4"]
        self.assertEqual(a4["state"], "At-Risk")


class NonSpecificSignals(unittest.TestCase):
    def test_low_control_escalates_autonomy(self):
        # 保留 v0.3：掌控感与自主性偏低叠加升一级
        a1 = run([item("自驱力-自主性", "偏低"),
                  item("情绪稳定性-无力感掌控感", "需关注")])["dimensions"]["A1"]
        self.assertEqual(a1["state"], "At-Risk")

    def test_low_control_alone_is_not_rebellion(self):
        p = run([order("独立自主", 2), item("自驱力-自主性", "较好"),
                 item("情绪稳定性-无力感掌控感", "需关注")])
        self.assertNotEqual(p["dimensions"]["A1"]["subtype"], "A1-S2")

    def test_inhibition_uses_y4_band(self):
        # 保留 v0.3：沿用 Y4 '偏低'（百分位 < 60）
        a5 = run([item("执行功能-抑制控制", "偏低", "45")])["dimensions"]["A5"]
        self.assertIn("R5.4", ids(a5))

    def test_mild_anxiety_is_watch_for_capacity(self):
        a3 = run([item("情绪稳定性-焦虑安详", "需关注"),
                  item("体质健康-睡眠评级", "良好")])["dimensions"]["A3"]
        self.assertEqual(a3["state"], "Watch")

    def test_cognitive_saturation_uses_y4_band(self):
        # 保留 v0.3：工作记忆 '偏低' 且情绪健康 → 风险
        base = [item("执行功能-工作记忆", "偏低", "45"),
                item("情绪稳定性-焦虑安详", "相对健康"),
                item("情绪稳定性-抑郁愉快", "相对健康")]
        self.assertEqual(run(base)["dimensions"]["A3"]["state"], "At-Risk")


class Y4OnlyBlocked(unittest.TestCase):
    """三级状态：只凭 Y4 也可判阻塞，证据等级保持"仅线索"（即待证实）。"""
    items = [item("体质健康-睡眠评级", "差"), item("情绪稳定性-焦虑安详", "需关注")]

    def test_y4_only_can_block_as_hypothesis(self):
        a3 = run(self.items)["dimensions"]["A3"]
        self.assertEqual(a3["state"], "Blocked")
        self.assertEqual(a3["subtype"], "A3-S1")
        self.assertEqual(a3["confidence"], "Hypothesis")

    def test_behavioral_evidence_allows_blocked(self):
        ev = {"ft": {"schedule": {"load_level": "高"}}}
        a3 = run(self.items, ev)["dimensions"]["A3"]
        self.assertEqual(a3["state"], "Blocked")
        self.assertEqual(a3["confidence"], "Supported")


class BodyGradeVocabulary(unittest.TestCase):
    def test_jiaocha_counts_as_problem(self):
        # Y4 PDF 实际输出"较差"，v0.3 只匹配"差/低"导致 R3.1/R3.2 漏判
        a3 = run([item("体质健康-睡眠评级", "较差")])["dimensions"]["A3"]
        self.assertIn("R3.1", ids(a3))
        a3 = run([item("体质健康-运动评级", "较差")])["dimensions"]["A3"]
        self.assertIn("R3.2", ids(a3))


class SafetyReview(unittest.TestCase):
    def test_severe_emotion_flags_safety_first(self):
        p = run([item("情绪稳定性-抑郁愉快", "需特殊关注")])
        self.assertTrue(p["safety_review"])
        self.assertIn("情绪安全复核", p["dimensions"]["A3"]["flags"])
        self.assertTrue(p["sequence_note"].startswith("情绪安全复核"))

    def test_mild_emotion_no_safety(self):
        p = run([item("情绪稳定性-抑郁愉快", "需关注")])
        self.assertFalse(p["safety_review"])


class MissingData(unittest.TestCase):
    def test_missing_core_points_flagged(self):
        a4 = run([item("自驱力-自主性", "较好")])["dimensions"]["A4"]
        self.assertEqual(a4["state"], "Secure")
        self.assertIn("Y4 数据缺失", a4["flags"])

    def test_present_core_points_not_flagged(self):
        a4 = run([item("学习动机-自我效能感", "不低"),
                  item("自驱力-胜任感", "不低")])["dimensions"]["A4"]
        self.assertNotIn("Y4 数据缺失", a4["flags"])


class Y4Miscalibration(unittest.TestCase):
    def test_high_ability_low_self_rating_hints_a4_s4(self):
        a4 = run([item("认知能力", "较好", "88"),
                  item("自我概念-能力与学校表现", "偏低")])["dimensions"]["A4"]
        self.assertIn("R4.10", ids(a4))
        self.assertEqual(a4["subtype"], "A4-S4")
        self.assertEqual(a4["state"], "Watch")

    def test_average_ability_no_hint(self):
        a4 = run([item("认知能力", "不低", "62"),
                  item("自我概念-能力与学校表现", "偏低")])["dimensions"]["A4"]
        self.assertNotIn("R4.10", ids(a4))


if __name__ == "__main__":
    unittest.main(verbosity=2)
