# -*- coding: utf-8 -*-
"""v0.5 信号库：每条信号一个正例、一个反例。

运行：python3 -m unittest six_am.tests.test_signals -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from six_am import engine, signals  # noqa: E402
from six_am.spec import DEFAULT_SPEC  # noqa: E402

PARAMS = DEFAULT_SPEC["params"]


def item(label, eval_value, raw=None):
    return {"code": "", "label": label, "raw_value": eval_value if raw is None else raw,
            "eval_value": eval_value, "eval_source": "规则推导", "dimension": "",
            "data_bias": "正常"}


def order(value, pos):
    return {"code": "%03d" % (109 + pos), "label": "职业价值观排序%d" % pos,
            "raw_value": value, "eval_value": value, "eval_source": "原始排序",
            "dimension": "生涯力", "data_bias": "正常"}


def ctx(items, evidence=None, params=None):
    return engine.Ctx(items, evidence or {}, params or {})


def ev(signal_id, items, evidence=None, params=None):
    p = PARAMS if params is None else params
    return signals.evaluate(signal_id, ctx(items, evidence, p), p)


def missing(signal_id, items=None, evidence=None):
    rec = ev(signal_id, items or [], evidence)
    return rec["hit"] is False and rec["level"] is None and rec["evidence"] == []


class Metadata(unittest.TestCase):
    def test_every_signal_has_metadata_and_evaluator(self):
        self.assertEqual(set(signals.SIGNALS), set(signals._EVALUATORS))
        for sid, meta in signals.SIGNALS.items():
            for field in ("id", "label", "source", "kind", "dims", "questions",
                          "params", "official_labels"):
                self.assertIn(field, meta, sid)
            self.assertEqual(meta["id"], sid)
            self.assertIsInstance(meta["dims"], list)
            self.assertIsInstance(meta["questions"], list)
            self.assertIsInstance(meta["params"], list)
            self.assertIsInstance(meta["official_labels"], str)


class NormMainSignals(unittest.TestCase):
    def test_autonomy(self):
        pos = ev("autonomy", [item("自驱力-自主性", "偏低", "5.2"),
                              item("自驱力-自主性常模平均数", None, "5.9")])
        self.assertEqual(pos["level"], "Watch")
        self.assertAlmostEqual(pos["distance"], -0.7)
        neg = ev("autonomy", [item("自驱力-自主性", "较好", "6.3"),
                              item("自驱力-自主性常模平均数", None, "5.9")])
        self.assertFalse(neg["hit"])
        self.assertTrue(missing("autonomy"))

    def test_autonomy_distance(self):
        rec = ev("autonomy", [item("自驱力-自主性", "偏低", "3.3"),
                              item("自驱力-自主性常模平均数", None, "6.1")])
        self.assertAlmostEqual(rec["distance"], -2.8, places=1)

    def test_deep_motive(self):
        self.assertEqual(ev("deep_motive", [item("学习动机-深层动机", "偏低")])["level"], "Watch")
        self.assertFalse(ev("deep_motive", [item("学习动机-深层动机", "不低")])["hit"])

    def test_self_efficacy(self):
        self.assertEqual(ev("self_efficacy", [item("学习动机-自我效能感", "偏低")])["level"], "Watch")
        self.assertFalse(ev("self_efficacy", [item("学习动机-自我效能感", "较好")])["hit"])

    def test_competence(self):
        self.assertEqual(ev("competence", [item("自驱力-胜任感", "偏低")])["level"], "Watch")
        self.assertFalse(ev("competence", [item("自驱力-胜任感", "不低")])["hit"])

    def test_conscientiousness(self):
        pos = ev("conscientiousness", [item("人格-责任心", "偏低", "2.4")])
        self.assertEqual(pos["level"], "Watch")
        self.assertAlmostEqual(pos["distance"], -0.6)
        self.assertFalse(ev("conscientiousness", [item("人格-责任心", "不低", "3.2")])["hit"])


class Gates(unittest.TestCase):
    def test_sleep(self):
        self.assertEqual(ev("sleep", [item("体质健康-睡眠评级", "较差")])["level"], "At-Risk")
        self.assertEqual(ev("sleep", [item("体质健康-睡眠评级", "中等")])["level"], "Watch")
        self.assertFalse(ev("sleep", [item("体质健康-睡眠评级", "良好")])["hit"])

    def test_exercise_diet(self):
        pos = ev("exercise_diet", [item("体质健康-运动评级", "较差"),
                                   item("体质健康-饮食评级", "良好")])
        self.assertEqual(pos["level"], "Watch")
        self.assertEqual(len(pos["evidence"]), 1)
        self.assertFalse(ev("exercise_diet", [item("体质健康-运动评级", "良好"),
                                              item("体质健康-饮食评级", "优秀")])["hit"])

    def test_anxiety(self):
        self.assertEqual(ev("anxiety", [item("情绪稳定性-焦虑安详", "需特殊关注")])["level"], "At-Risk")
        self.assertEqual(ev("anxiety", [item("情绪稳定性-焦虑安详", "需关注")])["level"], "Watch")
        self.assertFalse(ev("anxiety", [item("情绪稳定性-焦虑安详", "相对健康")])["hit"])

    def test_depression(self):
        self.assertEqual(ev("depression", [item("情绪稳定性-抑郁愉快", "需特殊关注")])["level"], "At-Risk")
        self.assertEqual(ev("depression", [item("情绪稳定性-抑郁愉快", "需关注")])["level"], "Watch")
        self.assertFalse(ev("depression", [item("情绪稳定性-抑郁愉快", "相对健康")])["hit"])

    def test_schedule_full(self):
        self.assertEqual(ev("schedule_full", [], {"ft": {"schedule": {"load_level": "高"}}})["level"],
                         "At-Risk")
        self.assertEqual(ev("schedule_full", [], {"ft": {"schedule": {"load_level": "中"}}})["level"],
                         "Watch")
        self.assertEqual(ev("schedule_full", [],
                            {"ft": {"schedule": {"free_hours_per_week": 3}}})["level"], "At-Risk")
        self.assertFalse(ev("schedule_full", [],
                            {"ft": {"schedule": {"load_level": "低", "free_hours_per_week": 20}}})["hit"])
        self.assertTrue(missing("schedule_full"))


class FirstTouchSignals(unittest.TestCase):
    def test_ft_goal(self):
        self.assertEqual(ev("ft_goal", [], {"ft": {"goal": {"judgement": "不认同"}}})["level"],
                         "At-Risk")
        self.assertEqual(ev("ft_goal", [], {"ft": {"goal": {"judgement": "部分认同"}}})["level"],
                         "Watch")
        self.assertFalse(ev("ft_goal", [], {"ft": {"goal": {"judgement": "认同"}}})["hit"])

    def test_ft_task(self):
        no_split = ev("ft_task", [], {"ft": {"standard_task": {"can_split": False}}})
        self.assertEqual(no_split["level"], "At-Risk")
        self.assertEqual(no_split["subtype"], "A5-S1")
        no_commit = ev("ft_task", [], {"ft": {"standard_task": {"can_split": True,
                                                                "can_commit": False}}})
        self.assertEqual(no_commit["subtype"], "A5-S3")
        self.assertFalse(ev("ft_task", [], {"ft": {"standard_task": {"can_split": True,
                                                                     "can_commit": True}}})["hit"])


class RankSignals(unittest.TestCase):
    def test_indep_boss_top5(self):
        pos = ev("indep_boss_top5", [order("独立自主", 2), order("上司关系", 4)])
        self.assertTrue(pos["hit"])
        self.assertEqual(pos["subtype"], "A1-S2")
        self.assertFalse(ev("indep_boss_top5", [order("独立自主", 2),
                                                order("上司关系", 6)])["hit"])

    def test_safety_top3(self):
        self.assertTrue(ev("safety_top3", [order("安全稳定", 3)])["hit"])
        self.assertFalse(ev("safety_top3", [order("安全稳定", 4)])["hit"])

    def test_achieve_safety(self):
        self.assertTrue(ev("achieve_safety", [order("成就感", 2), order("安全稳定", 4)])["hit"])
        self.assertFalse(ev("achieve_safety", [order("成就感", 2),
                                               order("安全稳定", 6)])["hit"])

    def test_achieve_or_prestige_top5(self):
        self.assertTrue(ev("achieve_or_prestige_top5", [order("成就感", 2)])["hit"])
        self.assertTrue(ev("achieve_or_prestige_top5", [order("声望地位", 3)])["hit"])
        self.assertFalse(ev("achieve_or_prestige_top5", [order("成就感", 6),
                                                         order("声望地位", 8)])["hit"])


class ControlSignals(unittest.TestCase):
    def test_control_low_uses_raw(self):
        self.assertTrue(ev("control_low", [item("情绪稳定性-无力感掌控感", "需关注", "4")])["hit"])
        self.assertFalse(ev("control_low", [item("情绪稳定性-无力感掌控感", "需关注", "6")])["hit"])
        self.assertTrue(missing("control_low"))

    def test_control_high(self):
        self.assertTrue(ev("control_high", [item("情绪稳定性-无力感掌控感", "相对健康", "12")])["hit"])
        self.assertFalse(ev("control_high", [item("情绪稳定性-无力感掌控感", "需关注", "10")])["hit"])


class SecureAndTypeSignals(unittest.TestCase):
    def test_wellbeing_ok(self):
        self.assertTrue(ev("wellbeing_ok", [item("自我概念-幸福与满足", "较好")])["hit"])
        self.assertFalse(ev("wellbeing_ok", [item("自我概念-幸福与满足", "偏低")])["hit"])

    def test_surface_low(self):
        pos = ev("surface_low", [item("学习动机-深层动机", "偏低"),
                                 item("学习动机-表面动机", "偏低")])
        self.assertEqual(pos["subtype"], "A2-S4")
        self.assertFalse(ev("surface_low", [item("学习动机-表面动机", "不低")])["hit"])

    def test_surface_not_low(self):
        pos = ev("surface_not_low", [item("学习动机-深层动机", "偏低"),
                                     item("学习动机-表面动机", "不低")])
        self.assertEqual(pos["subtype"], "A2-S2")
        self.assertFalse(ev("surface_not_low", [item("学习动机-表面动机", "偏低")])["hit"])

    def test_parent_complaint(self):
        self.assertTrue(ev("parent_complaint", [], {"parent": {"complaint": {"text": "没兴趣"}}})["hit"])
        self.assertFalse(ev("parent_complaint", [], {"parent": {}})["hit"])

    def test_holland_all_low(self):
        six = [item("职业兴趣-%s" % t, "偏低") for t in
               ("现实型", "研究型", "艺术型", "社会型", "事业型", "常规型")]
        pos = ev("holland_all_low", six)
        self.assertEqual(pos["subtype"], "A2-S3")
        self.assertFalse(ev("holland_all_low", six[:5] + [item("职业兴趣-常规型", "不低")])["hit"])

    def test_holland_peak(self):
        self.assertTrue(ev("holland_peak", [item("职业兴趣-研究型", "高")])["hit"])
        self.assertFalse(ev("holland_peak", [item("职业兴趣-研究型", "不低")])["hit"])

    def test_holland_c_high(self):
        self.assertTrue(ev("holland_c_high", [item("职业兴趣-常规型", "高")])["hit"])
        self.assertFalse(ev("holland_c_high", [item("职业兴趣-常规型", "不低")])["hit"])


class EmotionAndCapacitySignals(unittest.TestCase):
    def test_emotion_total_low(self):
        self.assertEqual(ev("emotion_total_low",
                            [item("情绪稳定性总分", "明显偏低")])["level"], "Watch")
        self.assertFalse(ev("emotion_total_low", [item("情绪稳定性总分", "偏低")])["hit"])

    def test_wm_flex_low(self):
        base = [item("执行功能-工作记忆", "偏低"),
                item("情绪稳定性-焦虑安详", "相对健康"),
                item("情绪稳定性-抑郁愉快", "相对健康")]
        pos = ev("wm_flex_low", base)
        self.assertEqual(pos["level"], "Watch")
        self.assertEqual(pos["subtype"], "A3-S3")
        self.assertFalse(ev("wm_flex_low", [base[0], item("情绪稳定性-焦虑安详", "需关注"),
                                            base[2]])["hit"])

    def test_esteem_anx(self):
        pos = ev("esteem_anx", [item("情绪稳定性-自卑自尊", "需关注"),
                                item("情绪稳定性-焦虑安详", "需特殊关注")])
        self.assertEqual(pos["subtype"], "A4-S3")
        self.assertFalse(ev("esteem_anx", [item("情绪稳定性-自卑自尊", "需关注"),
                                           item("情绪稳定性-焦虑安详", "相对健康")])["hit"])

    def test_cog_vs_self(self):
        pos = ev("cog_vs_self", [item("认知能力", "较好", "88"),
                                 item("学习动机-自我效能感", "偏低")])
        self.assertEqual(pos["subtype"], "A4-S4")
        self.assertFalse(ev("cog_vs_self", [item("认知能力", "不低", "62"),
                                            item("学习动机-自我效能感", "偏低")])["hit"])

    def test_self_concept_low(self):
        self.assertTrue(ev("self_concept_low", [item("自我概念整体档位", "偏低")])["hit"])
        self.assertTrue(ev("self_concept_low", [item("自我概念-能力与学校表现", "严重偏低")])["hit"])
        self.assertFalse(ev("self_concept_low", [item("自我概念整体档位", "正常")])["hit"])

    def test_mindset_low(self):
        pos = ev("mindset_low", [item("思维模式结果", None, "30"),
                                 item("情绪稳定性-自卑自尊", "需关注")])
        self.assertEqual(pos["subtype"], "A4-S1")
        self.assertFalse(ev("mindset_low", [item("思维模式结果", None, "60")])["hit"])

    def test_neuroticism_high(self):
        self.assertTrue(ev("neuroticism_high", [item("人格-神经质", "较好", "4.0")])["hit"])
        self.assertFalse(ev("neuroticism_high", [item("人格-神经质", "不低", "3.2")])["hit"])


class LearningSignals(unittest.TestCase):
    def test_strategy_low(self):
        self.assertEqual(ev("strategy_low", [item("学习方法与策略-学习深层方法与策略", "偏低")])["level"],
                         "Watch")
        self.assertFalse(ev("strategy_low", [item("学习方法与策略-学习深层方法与策略", "不低")])["hit"])

    def test_self_reg_low(self):
        self.assertEqual(ev("self_reg_low", [item("学习方法与策略-学习自我调节", "偏低")])["level"],
                         "Watch")
        self.assertFalse(ev("self_reg_low", [item("学习方法与策略-学习自我调节", "较好")])["hit"])

    def test_openness_many(self):
        base = [item("人格-开放性", "较好")]
        three = base + [item("职业兴趣-研究型", "高"), item("职业兴趣-艺术型", "不低"),
                        item("职业兴趣-社会型", "高")]
        pos = ev("openness_many", three)
        self.assertEqual(pos["subtype"], "A5-S2")
        self.assertFalse(ev("openness_many", base + [item("职业兴趣-研究型", "高"),
                                                     item("职业兴趣-艺术型", "不低")])["hit"])

    def test_inhibition_low(self):
        self.assertEqual(ev("inhibition_low", [item("执行功能-抑制控制", "偏低")])["level"], "Watch")
        self.assertFalse(ev("inhibition_low", [item("执行功能-抑制控制", "不低")])["hit"])

    def test_attention_low(self):
        self.assertEqual(ev("attention_low", [item("认知能力-注意力", "偏低")])["level"], "Watch")
        self.assertFalse(ev("attention_low", [item("认知能力-注意力", "不低")])["hit"])


class PersonalityA6Signals(unittest.TestCase):
    def test_extraversion_low(self):
        self.assertTrue(ev("extraversion_low", [item("人格-外倾性", "明显偏低")])["hit"])
        self.assertFalse(ev("extraversion_low", [item("人格-外倾性", "不低")])["hit"])

    def test_extraversion_high(self):
        self.assertTrue(ev("extraversion_high", [item("人格-外倾性", "高")])["hit"])
        self.assertFalse(ev("extraversion_high", [item("人格-外倾性", "偏低")])["hit"])

    def test_peer_attach_high(self):
        self.assertTrue(ev("peer_attach_high", [item("依恋关系-信任-同伴", "高")])["hit"])
        self.assertFalse(ev("peer_attach_high", [item("依恋关系-信任-同伴", "不低"),
                                                 item("依恋关系-亲近-同伴", "不低")])["hit"])

    def test_peer_attach_low(self):
        self.assertTrue(ev("peer_attach_low", [item("依恋关系-亲近-同伴", "偏低")])["hit"])
        self.assertFalse(ev("peer_attach_low", [item("依恋关系-信任-同伴", "高")])["hit"])

    def test_belonging_good(self):
        self.assertTrue(ev("belonging_good", [item("自驱力-归属感", "较好")])["hit"])
        self.assertFalse(ev("belonging_good", [item("自驱力-归属感", "不低")])["hit"])

    def test_parent_high(self):
        ok = [item("依恋关系-信任-母亲", "高"), item("依恋关系-信任-父亲", "不低"),
              item("依恋关系-沟通-母亲", "高"), item("依恋关系-沟通-父亲", "不低")]
        self.assertTrue(ev("parent_high", ok)["hit"])
        self.assertFalse(ev("parent_high", [item("依恋关系-信任-母亲", "不低"),
                                            item("依恋关系-沟通-母亲", "高")])["hit"])

    def test_parent_low(self):
        self.assertTrue(ev("parent_low", [item("依恋关系-信任-父亲", "偏低")])["hit"])
        self.assertFalse(ev("parent_low", [item("依恋关系-信任-母亲", "不低"),
                                           item("依恋关系-沟通-母亲", "高")])["hit"])

    def test_parent_mid(self):
        self.assertTrue(ev("parent_mid", [item("依恋关系-信任-母亲", "不低")])["hit"])
        self.assertFalse(ev("parent_mid", [item("依恋关系-信任-母亲", "高"),
                                           item("依恋关系-沟通-母亲", "高")])["hit"])
        self.assertTrue(missing("parent_mid"))

    def test_agreeable_high(self):
        self.assertTrue(ev("agreeable_high", [item("人格-宜人性", "较好")])["hit"])
        self.assertFalse(ev("agreeable_high", [item("人格-宜人性", "偏低")])["hit"])

    def test_anxiety_flag(self):
        self.assertTrue(ev("anxiety_flag", [item("情绪稳定性-焦虑安详", "需关注")])["hit"])
        self.assertFalse(ev("anxiety_flag", [item("情绪稳定性-焦虑安详", "相对健康")])["hit"])

    def test_esteem_flag(self):
        self.assertTrue(ev("esteem_flag", [item("情绪稳定性-自卑自尊", "需特殊关注")])["hit"])
        self.assertFalse(ev("esteem_flag", [item("情绪稳定性-自卑自尊", "相对健康")])["hit"])


class BannerSignals(unittest.TestCase):
    def test_answer_state(self):
        pos = ev("answer_state", [item("自我概念整体档位", "偏低"),
                                  item("情绪稳定性总分", "明显偏低")])
        self.assertTrue(pos["hit"])
        self.assertFalse(ev("answer_state", [item("自我概念整体档位", "偏低"),
                                             item("情绪稳定性总分", "偏低")])["hit"])

    def test_safety(self):
        self.assertEqual(ev("safety", [item("情绪稳定性-焦虑安详", "需特殊关注")])["level"], "At-Risk")
        self.assertFalse(ev("safety", [item("情绪稳定性-焦虑安详", "需关注")])["hit"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
