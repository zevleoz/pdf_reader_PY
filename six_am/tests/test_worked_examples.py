# -*- coding: utf-8 -*-
"""v0.2 §10 三个 worked example 的断言测试（实施计划 §9 验收项 1）。

新版优先级（不使用数值权重）：断言状态、亚型、跨维规则、priority_order 与追问覆盖，
不再断言 ObstacleScore 数值。

运行：python3.11 -m unittest six_am.tests.test_worked_examples -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from six_am import engine  # noqa: E402


def item(label, value):
    return {"code": "", "label": label, "raw_value": value, "eval_value": value,
            "eval_source": "规则推导", "dimension": "", "level_code": None,
            "level_label": None, "data_bias": "正常"}


def order(value, pos, total=15):
    return {"code": "%03d" % (109 + pos), "label": "职业价值观排序%d" % pos,
            "raw_value": value, "eval_value": value, "eval_source": "原始排序",
            "dimension": "生涯力", "data_bias": "正常"}


def run(items, evidence=None):
    return engine.run(items, student={"name": "测试学生", "grade": "高二"},
                      evidence=evidence)


def _ids(mods):
    return [m["id"] for m in (mods or [])]


class WorkedExample1(unittest.TestCase):
    """例 1：逆反型（Rebellion）。"""

    def setUp(self):
        items = [
            item("自驱力-自主性", "偏低"),
            order("独立自主", 2),
            item("依恋关系-沟通-母亲", "偏低"),
            item("人格-宜人性", "不低"),
            item("职业兴趣-研究型", "高"),
            item("职业兴趣-现实型", "不低"),
            item("职业兴趣-艺术型", "不低"),
            item("职业兴趣-社会型", "偏低"),
            item("职业兴趣-事业型", "不低"),
            item("职业兴趣-常规型", "偏低"),
            item("学习动机-深层动机", "不低"),
            item("体质健康-睡眠评级", "良好"),
            item("学习动机-自我效能感", "不低"),
        ]
        self.p = run(items)
        self.dims = self.p["dimensions"]

    def test_a1_blocked_rebellion(self):
        a1 = self.dims["A1"]
        self.assertEqual(a1["state"], "Blocked")
        self.assertEqual(a1["subtype"], "A1-S2")
        self.assertEqual(a1["confidence"], "Hypothesis")
        self.assertIn("高叛逆风险人群", a1["flags"])
        self.assertNotIn("score", a1)

    def test_a2_watch_with_x2(self):
        a2 = self.dims["A2"]
        self.assertEqual(a2["state"], "Watch")
        self.assertIn("X.2", _ids(a2["cross_mods"]))
        self.assertTrue(any("学生自选任务重测" in n for n in a2["notes"]))

    def test_a3_a5_secure(self):
        for dim in ("A3", "A4", "A5"):
            self.assertEqual(self.dims[dim]["state"], "Secure", dim)

    def test_obstacle_a1_first(self):
        obs = {o["dim"]: o for o in self.p["obstacles"]}
        self.assertIn("A1", obs)
        self.assertEqual(obs["A1"]["sequence"], 1)
        self.assertEqual(self.p["priority_order"][0], "A1")
        self.assertTrue(obs["A1"]["priority_reason"])
        for o in self.p["obstacles"]:
            self.assertNotIn("score", o)
            self.assertNotIn("high_priority", o)

    def test_a6_authority_and_parent_caution(self):
        plan = self.p["support_plan"]
        self.assertEqual(plan["ranked"][0]["direction"], "同伴协作")
        by_dir = {r["direction"]: r for r in plan["ranked"]}
        # 定性适配：R6.6 命中 → 成人方向慎用；同伴协作有正向规则支持 → 优先
        self.assertEqual(by_dir["权威施压"]["fit_label"], "慎用")
        self.assertEqual(by_dir["家长陪同"]["fit_label"], "慎用")
        self.assertEqual(by_dir["同伴协作"]["fit_label"], "优先")
        for r in plan["ranked"]:
            self.assertNotIn("score", r)
            self.assertNotIn("predicted_effectiveness", r)
        avoid = {(a["direction"], a["kind"]) for a in plan["avoid"]}
        self.assertIn(("权威施压", "慎用"), avoid)
        self.assertIn(("家长陪同", "慎用"), avoid)

    def test_questions_contain(self):
        qs = {q["id"] for q in self.p["questions"]}
        for q in ("Q1.3", "Q1.4", "Q1.1", "Q6.3"):
            self.assertIn(q, qs)


class WorkedExample2(unittest.TestCase):
    """例 2：Capacity Overload（过载型）。"""

    def setUp(self):
        items = [
            item("体质健康-睡眠评级", "差"),
            item("体质健康-运动评级", "一般"),
            item("情绪稳定性-焦虑安详", "需关注"),
            item("情绪稳定性总分", "偏低"),
            item("学习动机-自我效能感", "偏低"),
            item("学习方法与策略-学习自我调节", "偏低"),
            item("人格-责任心", "偏低"),
        ]
        evidence = {"ft": {"schedule": {"load_level": "高", "free_hours_per_week": 2}}}
        self.p = run(items, evidence=evidence)
        self.dims = self.p["dimensions"]

    def test_a3_blocked_overload_supported(self):
        a3 = self.dims["A3"]
        self.assertEqual(a3["state"], "Blocked")
        self.assertEqual(a3["subtype"], "A3-S1")
        self.assertEqual(a3["confidence"], "Supported")
        self.assertNotIn("score", a3)

    def test_a4_a5_x3_annotated(self):
        for dim in ("A4", "A5"):
            rec = self.dims[dim]
            self.assertEqual(rec["state"], "At-Risk", dim)
            self.assertEqual(rec["confidence"], "Hypothesis", dim)
            self.assertNotIn("score", rec, dim)
            self.assertIn("X.3", _ids(rec["cross_mods"]))
            self.assertTrue(any("待 A3 处理后复测" in n for n in rec["notes"]))

    def test_a3_sequence_first(self):
        obs = {o["dim"]: o for o in self.p["obstacles"]}
        self.assertEqual(obs["A3"]["sequence"], 1)
        # X.3 置顶后，A4 与 A5 同级并列时 A4 在前
        self.assertEqual(self.p["priority_order"], ["A3", "A4", "A5"])
        self.assertIn("X.3", self.p["sequence_note"])

    def test_questions_contain(self):
        qs = {q["id"] for q in self.p["questions"]}
        for q in ("Q3.1", "Q3.2", "Q3.3"):
            self.assertIn(q, qs)


class WorkedExample3(unittest.TestCase):
    """例 3：Peer Activation（同伴启动）。"""

    def setUp(self):
        items = [
            item("人格-外倾性", "高"),
            item("依恋关系-亲近-同伴", "高"),
            item("依恋关系-信任-同伴", "高"),
            item("依恋关系-信任-母亲", "不低"),
            item("依恋关系-信任-父亲", "不低"),
            item("依恋关系-沟通-母亲", "不低"),
            item("依恋关系-沟通-父亲", "不低"),
            item("依恋关系-亲近-母亲", "不低"),
            item("依恋关系-亲近-父亲", "不低"),
            item("自驱力-自主性", "不低"),
            item("职业兴趣-社会型", "高"),
            item("职业兴趣-现实型", "偏低"),
            item("职业兴趣-研究型", "偏低"),
            item("职业兴趣-艺术型", "偏低"),
            item("职业兴趣-事业型", "偏低"),
            item("职业兴趣-常规型", "偏低"),
            item("学习动机-深层动机", "不低"),
            item("学习方法与策略-学习自我调节", "偏低"),
        ]
        evidence = {
            "ft": {"standard_task": {"can_split": True, "can_commit": False}},
            "observation": {"team_behavior_verified": True},
        }
        self.p = run(items, evidence=evidence)
        self.dims = self.p["dimensions"]

    def test_a5_structure_dependence_confirmed(self):
        a5 = self.dims["A5"]
        self.assertEqual(a5["state"], "At-Risk")
        self.assertEqual(a5["subtype"], "A5-S3")
        self.assertEqual(a5["confidence"], "Supported")
        self.assertNotIn("score", a5)

    def test_a1_a4_secure(self):
        for dim in ("A1", "A2", "A3", "A4"):
            self.assertEqual(self.dims[dim]["state"], "Secure", dim)

    def test_support_combo_peer_plus_structure(self):
        plan = self.p["support_plan"]
        top2 = [r["direction"] for r in plan["ranked"][:2]]
        self.assertIn("同伴协作", top2)
        self.assertIn("权威施压", top2)
        by_dir = {r["direction"]: r for r in plan["ranked"]}
        authority = by_dir["权威施压"]
        self.assertIn("Structure", authority["sub_mechanisms"])
        # R6.1 团队行为经观察佐证 → 同伴协作 优先
        self.assertEqual(by_dir["同伴协作"]["fit_label"], "优先")
        self.assertIn("R6.1", by_dir["同伴协作"]["basis_rules"])

    def test_obstacle_single_entry(self):
        obs = {o["dim"]: o for o in self.p["obstacles"]}
        self.assertEqual(list(obs.keys()), ["A5"])
        self.assertEqual(obs["A5"]["sequence"], 1)
        self.assertEqual(self.p["priority_order"], ["A5"])

    def test_questions_contain(self):
        qs = {q["id"] for q in self.p["questions"]}
        for q in ("Q6.1", "Q6.2", "Q5.4"):
            self.assertIn(q, qs)


if __name__ == "__main__":
    unittest.main(verbosity=2)