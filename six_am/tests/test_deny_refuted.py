# -*- coding: utf-8 -*-
"""追问答案 deny → refuted 规则移出命中集并重算维度的回归测试。

覆盖实施计划 §3.3 语义：答案 deny 后该规则必须从命中集移除，其 state/subtype/flag
贡献一并回退，且不得再作为依赖规则的命中来源（rule_hit → False）。

场景（来自独立复核）：
  1) 仅 R1.1 触发 A1=At-Risk；deny Q1.1 后 A1 应回落为 Secure。
  2) R4.1 直接触发 + R4.2 条件升级 → A4=Blocked；deny Q4.1 后 A4 应回落，R4.2
     的升级依据消失（R4.1 不再是命中）。

运行：python -m pytest six_am/tests -q
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


def run(items, answers=None):
    return engine.run(items, student={"name": "测试学生", "grade": "高二"},
                      answers=answers, engine_version="v0.4")


def _ids(rec):
    return [t["id"] for t in rec.get("triggered_rules") or []]


class DenyScalesBackSingleRule(unittest.TestCase):
    """场景 1：A1 仅由 R1.1 触发，deny Q1.1 后维度必须重算。"""

    items = [item("自驱力-自主性", "偏低")]

    def test_baseline_watch(self):
        # v0.4：自主性单项略低 = 弱信号 → Watch
        a1 = run(self.items)["dimensions"]["A1"]
        self.assertEqual(a1["state"], "Watch")
        self.assertIn("R1.1", _ids(a1))

    def test_deny_q1_1_reverts_a1(self):
        profile = run(self.items, answers=[{"q": "Q1.1", "result": "deny"}])
        a1 = profile["dimensions"]["A1"]
        # R1.1 的 state 贡献必须回退：不再 Watch
        self.assertEqual(a1["state"], "Secure")
        # 规则被移出命中集
        self.assertNotIn("R1.1", _ids(a1))
        self.assertEqual(profile["refuted"], {"R1.1": "Q1.1"})


class DenyBlocksDependentRule(unittest.TestCase):
    """场景 2：A4 由 R4.1 触发 + R4.2 依赖升级，deny Q4.1 后两者贡献都必须消失。"""

    items = [item("学习动机-自我效能感", "偏低"),
             item("自驱力-胜任感", "偏低")]

    def test_baseline_at_risk(self):
        # v0.4：自我效能感 + 胜任感两个弱信号互证 → At-Risk
        a4 = run(self.items)["dimensions"]["A4"]
        self.assertEqual(a4["state"], "At-Risk")
        self.assertEqual(a4["subtype"], "A4-S2")
        self.assertIn("R4.1", _ids(a4))
        self.assertIn("R4.2", _ids(a4))

    def test_deny_q4_1_reverts_a4(self):
        profile = run(self.items, answers=[{"q": "Q4.1", "result": "deny"}])
        a4 = profile["dimensions"]["A4"]
        trace = {t["id"]: t for t in a4["triggered_rules"]}
        # R4.1 的 state/subtype 贡献必须回退
        self.assertEqual(a4["state"], "Secure")
        self.assertIsNone(a4["subtype"])
        self.assertNotIn("R4.1", trace)
        # R4.2 仍因自身 when 命中，但不得再通过 rule_hit("R4.1") 触发升级
        self.assertNotIn("escalate", (trace.get("R4.2", {}).get("effect") or {}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
