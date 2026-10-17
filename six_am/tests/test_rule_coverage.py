# -*- coding: utf-8 -*-
"""规则 ID 全覆盖检查（实施计划 §9 验收项 2）。

1) 注册表对照：47 条 R + 7 条 X + 29 条 Q 与 rules.py 注册表一致；
2) 逐规则最小命中 fixture：按 when 条件递归构造最小输入，断言该规则出现在
   triggered_rules（A6 规则在 A6.triggered_rules）；
3) 7 条 X 规则各自 fixture 命中，断言 cross_mods 记录出现；
4) 29 条 Q：verify 指向存在的 R 规则，且全部可从规则 questions / A6 映射触达。

运行：/opt/homebrew/bin/python3.11 -m unittest six_am.tests.test_rule_coverage -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from six_am import engine            # noqa: E402
from six_am import rules as R        # noqa: E402
from six_am import questionnaire as Q  # noqa: E402

_HOLLAND = ["职业兴趣-现实型", "职业兴趣-研究型", "职业兴趣-艺术型",
            "职业兴趣-社会型", "职业兴趣-事业型", "职业兴趣-常规型"]


# ── fixture 构造器 ─────────────────────────────────────────────
def _it(label, value):
    return {"code": "", "label": label, "raw_value": value, "eval_value": value,
            "eval_source": "规则推导", "dimension": "", "data_bias": "正常"}


def _order_it(value, pos=2, total=15):
    return {"code": "ORDERPOS:%s" % value, "label": "%s排序位置" % value,
            "raw_value": "第%d位/共%d位" % (pos, total),
            "eval_value": "第%d位/共%d位" % (pos, total),
            "eval_source": "规则推导", "dimension": "", "data_bias": "正常"}


class _Fixture:
    def __init__(self):
        self.items = {}       # key -> item（同 label 覆盖，避免重复）
        self.evidence = {}

    def add_point(self, label, value):
        self.items["P:" + label] = _it(label, value)

    def add_num(self, label, value):
        self.items["P:" + label] = _it(label, str(value))

    def add_order(self, value, pos=2):
        self.items["O:" + value] = _order_it(value, pos)

    def add_evidence(self, path, value):
        cur = self.evidence
        parts = path.split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value

    def merge(self, other):
        self.items.update(other.items)
        _deep_update(self.evidence, other.evidence)

    def finish(self):
        return list(self.items.values()), dict(self.evidence)


def _deep_update(dst, src):
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_update(dst[k], v)
        else:
            dst[k] = v


def _resolve_num(v):
    if isinstance(v, str) and v.startswith("@"):
        v = R.DEFAULT_PARAMS.get(v[1:])
    return float(v)


# 20 个命名谓词 → 最小为真 fixture
def _pf(attach):
    def fn(fx):
        fx.add_point(attach[0], attach[1])
    return fn


PREDICATE_FIXTURES = {
    "parent_attachment_safe": _pf(("依恋关系-信任-母亲", "不低")),
    "parent_attachment_asymmetry": lambda fx: (fx.add_point("依恋关系-信任-母亲", "高"),
                                               fx.add_point("依恋关系-信任-父亲", "偏低")),
    "parent_attachment_low": _pf(("依恋关系-信任-母亲", "偏低")),
    "parent_attachment_high": _pf(("依恋关系-信任-母亲", "高")),
    "peer_attachment_high": _pf(("依恋关系-亲近-同伴", "高")),
    "peer_attachment_not_low": _pf(("依恋关系-信任-同伴", "不低")),
    "holland_peak_exists": _pf(("职业兴趣-研究型", "高")),
    "holland_three_plus_notlow": lambda fx: [fx.add_point(l, "高") for l in _HOLLAND[:3]],
    "recovery_deficit_two_hits": lambda fx: (fx.add_point("体质健康-睡眠评级", "中等"),
                                             fx.add_point("体质健康-运动评级", "差")),
    "emotion_items_all_healthy": lambda fx: (fx.add_point("情绪稳定性-焦虑安详", "相对健康"),
                                             fx.add_point("情绪稳定性-抑郁愉快", "相对健康")),
    "schedule_overload": lambda fx: fx.add_evidence("ft.schedule.load_level", "高"),
    "prior_engagement_same_domain": lambda fx: fx.add_evidence(
        "observation.prior_engagement_same_domain", True),
    "parent_complaint_present": lambda fx: fx.add_evidence("parent.complaint.text", "缺乏动力"),
    "subject_mismatch": lambda fx: fx.add_evidence("ft.subject_status", [{"gap": "below"}]),
    "subject_below_actual": lambda fx: fx.add_evidence("ft.subject_status", [{"gap": "below"}]),
    "subject_above_actual": lambda fx: fx.add_evidence("ft.subject_status", [{"gap": "above"}]),
    "standard_task_done": lambda fx: fx.add_evidence(
        "ft.standard_task", {"can_split": True, "can_commit": True}),
    "standard_task_cannot_split": lambda fx: fx.add_evidence(
        "ft.standard_task", {"can_split": False}),
    "standard_task_cannot_commit": lambda fx: fx.add_evidence(
        "ft.standard_task", {"can_split": True, "can_commit": False}),
    "value_link_absent": lambda fx: fx.add_evidence("task.connect_values", ["成就感"]),
}

# 亚型 → 使其成立的最小 fixture（供 subtype 条件引用）
SUBTYPE_FIXTURES = {
    "A1-S2": lambda fx: (fx.add_order("独立自主", 2),
                         fx.add_point("情绪稳定性-无力感掌控感", "偏低")),
    "A1-S3": lambda fx: (fx.add_point("自驱力-自主性", "偏低"),
                         fx.add_point("人格-宜人性", "高"),
                         fx.add_point("依恋关系-信任-母亲", "不低")),
    "A5-S3": lambda fx: (fx.add_point("学习动机-深层动机", "较好"),
                         fx.add_point("学习方法与策略-学习自我调节", "偏低"),
                         fx.add_point("自驱力-自主性", "较好")),
}


def _satisfy(cond, fx, rules_data=None):
    """递归满足一个 when 条件（最小代价）。"""
    if not isinstance(cond, dict):
        return
    if "any" in cond:
        subs = cond.get("any") or []
        if subs:
            _satisfy(subs[0], fx, rules_data)
        return
    if "not" in cond:
        return  # 保持不满足即可
    if "subtype" in cond:
        fn = SUBTYPE_FIXTURES.get(str(cond["subtype"]))
        if fn:
            fn(fx)
        return
    if "dim_state" in cond:
        return  # 默认 Secure（R6.8 仅由父母依恋支撑）
    if "point" in cond:
        label = str(cond["point"])
        if "is" in cond:
            vals = cond.get("is") or []
            fx.add_point(label, str(vals[0]) if vals else "不低")
        elif "num_lt" in cond:
            fx.add_num(label, _resolve_num(cond["num_lt"]) - 1)
        elif "num_gt" in cond:
            fx.add_num(label, _resolve_num(cond["num_gt"]) + 1)
        return
    if "order_top" in cond:
        fx.add_order(str(cond["order_top"]))
        return
    if "rule" in cond:
        ref = (rules_data or R.RULES).get(str(cond["rule"]))
        for c in (ref or {}).get("when") or []:
            _satisfy(c, fx, rules_data)
        return
    if "evidence" in cond:
        fx.add_evidence(str(cond["evidence"]), bool(cond.get("is_true", True)))
        return
    if "predicate" in cond:
        fn = PREDICATE_FIXTURES.get(str(cond["predicate"]))
        if fn:
            fn(fx)
        return


def _collect_predicates(cond):
    out = set()
    if not isinstance(cond, dict):
        return out
    if "predicate" in cond:
        out.add(str(cond["predicate"]))
    for key in ("any",):
        for sub in cond.get(key) or []:
            out |= _collect_predicates(sub)
    if isinstance(cond.get("not"), dict):
        out |= _collect_predicates(cond["not"])
    return out


def _rule_fixture(rid):
    fx = _Fixture()
    for cond in R.RULES[rid].get("when") or []:
        _satisfy(cond, fx)
    items, evidence = fx.finish()
    return engine.run(items, evidence=evidence)


def _cross_mod_ids(profile):
    ids = set()
    for dim, rec in profile["dimensions"].items():
        for m in rec.get("cross_mods") or []:
            ids.add(m["id"])
    return ids


# ── 测试 ──────────────────────────────────────────────────────
class RegistryCoverage(unittest.TestCase):
    def test_r_rules_47(self):
        self.assertEqual(len(R.RULE_IDS), 47)
        self.assertEqual(set(R.RULE_IDS), set(R.RULES.keys()))
        for rid in R.RULE_IDS:
            self.assertTrue(R.RULES[rid].get("dim"), rid)

    def test_cross_rules_7(self):
        self.assertEqual(R.CROSS_RULE_IDS, ["X.%d" % i for i in range(1, 8)])
        self.assertEqual(set(R.CROSS_RULE_IDS), set(R.CROSS_RULES.keys()))

    def test_questions_29(self):
        self.assertEqual(len(R.QUESTION_IDS), 29)
        self.assertEqual(set(R.QUESTION_IDS), set(R.QUESTIONS.keys()))

    def test_predicates_registry(self):
        used = set()
        for r in R.RULES.values():
            then = r.get("then") or {}
            for cond in r.get("when") or []:
                used |= _collect_predicates(cond)
            for eff in then.get("effects") or []:
                if eff.get("if_predicate"):
                    used.add(str(eff["if_predicate"]))
            if (then.get("subtype_if") or {}).get("predicate"):
                used.add(str(then["subtype_if"]["predicate"]))
        self.assertLessEqual(used, set(R.PREDICATES.keys()))
        self.assertEqual(len(R.PREDICATES), 20)
        # 每个谓词 fixture 齐全
        self.assertEqual(set(PREDICATE_FIXTURES.keys()), set(R.PREDICATES.keys()))


class RuleReachability(unittest.TestCase):
    """每条 R 规则都能被最小 fixture 命中（出现在 triggered_rules）。"""

    def test_all_rules_reachable(self):
        for rid in R.RULE_IDS:
            with self.subTest(rule=rid):
                dim = R.RULES[rid]["dim"]
                profile = _rule_fixture(rid)
                ids = [t["id"] for t in profile["dimensions"][dim]["triggered_rules"]]
                self.assertIn(rid, ids, "%s 未被最小 fixture 命中" % rid)

    def test_r48_promotes_confidence_with_subtype(self):
        """R4.8（失败后放弃模式）：有 A4 亚型时 confidence → Supported。"""
        fx = _Fixture()
        fx.add_point("学习动机-自我效能感", "偏低")   # R4.1 → A4-S2
        fx.add_point("自驱力-胜任感", "偏低")         # R4.2
        fx.add_evidence("observation.first_failure_quit", True)  # R4.8
        items, evidence = fx.finish()
        a4 = engine.run(items, evidence=evidence)["dimensions"]["A4"]
        self.assertEqual(a4["subtype"], "A4-S2")
        self.assertEqual(a4["confidence"], "Supported")

    def test_r48_alone_no_confidence(self):
        """R4.8 单独命中（无亚型）：不产生置信标注。"""
        fx = _Fixture()
        fx.add_evidence("observation.first_failure_quit", True)
        items, evidence = fx.finish()
        a4 = engine.run(items, evidence=evidence)["dimensions"]["A4"]
        self.assertEqual(a4["state"], "Secure")
        self.assertIsNone(a4["confidence"])


class CrossRuleCoverage(unittest.TestCase):
    """7 条 X 规则各自 fixture 命中，cross_mods 出现对应 ID。"""

    def _run(self, builder):
        fx = _Fixture()
        builder(fx)
        items, evidence = fx.finish()
        return engine.run(items, evidence=evidence)

    def test_x1_double_lock(self):
        def b(fx):
            fx.add_point("自驱力-自主性", "偏低")                      # A1 At-Risk
            fx.add_point("学习动机-深层动机", "偏低")                  # A2 At-Risk
            fx.add_point("学习动机-表面动机", "偏低")
        p = self._run(b)
        mods = _cross_mod_ids(p)
        self.assertIn("X.1", mods)
        self.assertAlmostEqual(p["dimensions"]["A1"]["score"]["amplifier"], 1.5, places=2)

    def test_x2_signal_pollution(self):
        def b(fx):
            SUBTYPE_FIXTURES["A1-S2"](fx)
        p = self._run(b)
        a2 = p["dimensions"]["A2"]
        self.assertIn("X.2", _cross_mod_ids(p))
        self.assertTrue(any("重测" in n for n in a2["notes"]))

    def test_x3_a3_priority(self):
        def b(fx):
            fx.add_point("体质健康-睡眠评级", "差")   # A3 At-Risk
            fx.add_point("学习动机-自我效能感", "偏低")  # A4 At-Risk
        p = self._run(b)
        self.assertIn("X.3", _cross_mod_ids(p))
        self.assertAlmostEqual(p["dimensions"]["A4"]["score"]["amplifier"], 0.7, places=2)
        self.assertAlmostEqual(p["dimensions"]["A5"]["score"]["amplifier"], 0.7, places=2)

    def test_x4_constrains_a5(self):
        def b(fx):
            fx.add_point("学习动机-自我效能感", "偏低")   # A4 At-Risk
        p = self._run(b)
        self.assertIn("X.4", _cross_mod_ids(p))

    def test_x5_a6_arbitration(self):
        def b(fx):
            SUBTYPE_FIXTURES["A1-S2"](fx)   # R6.6
            SUBTYPE_FIXTURES["A5-S3"](fx)   # R6.7
        p = self._run(b)
        self.assertIn("X.5", _cross_mod_ids(p))

    def test_x6_global_disinterest(self):
        def b(fx):
            for label in _HOLLAND:
                fx.add_point(label, "偏低")            # R2.1 → A2-S3 Watch
            fx.add_evidence("parent.complaint.text", "对什么都没兴趣")  # R2.8 → At-Risk
        p = self._run(b)
        self.assertIn("X.6", _cross_mod_ids(p))
        self.assertIn("X.6", [m["id"] for m in p["dimensions"]["A1"]["cross_mods"]])

    def test_x7_parent_no_relinquish(self):
        def b(fx):
            fx.add_point("自驱力-自主性", "偏低")
            fx.add_evidence("parent.cannot_relinquish", True)
        p = self._run(b)
        self.assertIn("X.7", _cross_mod_ids(p))
        self.assertAlmostEqual(p["dimensions"]["A1"]["score"]["amplifier"], 0.5, places=2)


class QuestionCoverage(unittest.TestCase):
    def test_verify_targets_exist(self):
        for qid, q in R.QUESTIONS.items():
            for rid in q.get("verify") or []:
                self.assertIn(rid, R.RULES, "%s.verify 指向不存在的规则 %s" % (qid, rid))
            self.assertTrue(q.get("ask"), qid)

    def test_all_questions_reachable(self):
        reachable = set()
        for r in R.RULES.values():
            reachable |= set(r.get("questions") or [])
        for qs in Q.A6_RULE_QUESTIONS.values():
            reachable |= set(qs)
        reachable |= set(R.A6_FILL_ORDER)
        self.assertEqual(reachable, set(R.QUESTION_IDS))


if __name__ == "__main__":
    unittest.main(verbosity=2)