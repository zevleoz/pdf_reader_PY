# -*- coding: utf-8 -*-
"""P2：判定依据链、一句话判断、亚型显示名与行动卡字段。"""

import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from six_am import engine, presentation  # noqa: E402
from six_am import rationale  # noqa: E402


def item(label, value, raw=None):
    return {"code": "", "label": label,
            "raw_value": value if raw is None else raw,
            "eval_value": value, "eval_source": "规则推导", "dimension": "",
            "level_code": None, "level_label": None, "data_bias": "正常"}


def order(value, pos, total=15):
    return {"code": "%03d" % (109 + pos), "label": "职业价值观排序%d" % pos,
            "raw_value": value, "eval_value": value, "eval_source": "原始排序",
            "dimension": "生涯力", "data_bias": "正常"}


def run(items):
    return engine.run(items, student={"name": "测试学生", "grade": "高二"})


def cards_by_dim(profile):
    return {c["dim"]: c for c in presentation.build_view_model(profile)["cards"]}


def autonomy_items():
    """自主性 3.3 / 常模 6.1（强信号）+ 独立自主第 2 位 → A1-S2。"""
    return [
        item("自驱力-自主性", "偏低", raw=3.3),
        item("自驱力-自主性常模平均数", 6.1),
        order("独立自主", 2),
    ]


class RationaleCard(unittest.TestCase):

    def setUp(self):
        self.profile = run(autonomy_items())
        self.cards = cards_by_dim(self.profile)

    def test_subtype_display_and_verdict(self):
        a1 = self.cards["A1"]
        self.assertEqual(a1["subtype_display"], "自主抗争型")
        self.assertTrue(a1["verdict"].startswith("想自己做主"), a1["verdict"])

    def test_indicator_gap_strength_and_max(self):
        a1 = self.cards["A1"]["rationale"]
        self.assertEqual(a1["theory"], rationale.THEORY["A1"])
        ind = next(i for i in a1["indicators"] if i["point"] == "自驱力-自主性")
        self.assertEqual(ind["gap"], -2.8)
        self.assertEqual(ind["strength"], "strong")
        self.assertEqual(ind["max"], 10)

    def test_order_indicator(self):
        indicators = self.cards["A1"]["rationale"]["indicators"]
        ind = next(i for i in indicators if i["point"] == "独立自主")
        self.assertEqual(ind["rank"], 2)
        self.assertEqual(ind["rank_total"], 15)
        self.assertEqual(ind["text"], "前 5")

    def test_level_reason_uses_y4_only(self):
        self.assertIn("目前只有 Y4 线索", self.cards["A1"]["rationale"]["level_reason"])

    def test_secure_verdict_matches_headline(self):
        self.assertEqual(self.cards["A3"]["state"], "Secure")
        self.assertEqual(self.cards["A3"]["verdict"], presentation.SECURE_HEADLINE)

    def test_a6_has_no_rationale(self):
        self.assertIsNone(self.cards["A6"]["rationale"])


class OldSupportPlanName(unittest.TestCase):

    def test_authority_pressure_renders_as_mentor(self):
        stored = copy.deepcopy(run(autonomy_items()))
        plan = stored.get("support_plan") or {}
        for entry in plan.get("ranked") or []:
            if entry.get("direction") == "导师督促":
                entry["direction"] = "权威施压"
        for entry in plan.get("avoid") or []:
            if entry.get("direction") == "导师督促":
                entry["direction"] = "权威施压"

        a6 = cards_by_dim(stored)["A6"]
        rendered = {k: a6[k] for k in ("headline", "next_actions", "avoid_actions")}
        blob = json.dumps(rendered, ensure_ascii=False)
        self.assertNotIn("权威施压", blob)
        self.assertIn("导师督促", blob)
        # 视图模型只读：原 profile 不被改写
        directions = [e["direction"] for e in plan.get("ranked") or []]
        self.assertIn("权威施压", directions)


if __name__ == "__main__":
    unittest.main(verbosity=2)
