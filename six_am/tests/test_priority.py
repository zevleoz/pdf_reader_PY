# -*- coding: utf-8 -*-
"""规则优先级（priority.compute）与 v2 profile 形状测试（Task 1）。

覆盖新版 §6 优先级规则（不使用数值权重）：
1. A3 过载（x3_top 或 A3 Blocked）强制第一；
2. X.6 全局无兴趣：A2 进入兴趣探索优先位（仍次于 A3），A1/A5 标注任务级干预暂缓；
3. X.7：A1 不进入常规排序，写入 deferred（长期目标），优先级转向 A2 意义连接；
4. X.1：A1 必须先于 A2；X.6 同时命中时 A2 兴趣探索仍在 A1 前（A1 任务级干预暂缓），
   X.7 已 defer 时不拉回；
5. 其余维度按证据状态 Confirmed > Supported > Hypothesis/None，
   再按状态 Blocked > At-Risk > Watch，最后按 A1–A5 固定顺序；
6. A4 与 A5 同级并列时 A4 在前；
7. A6 不进入障碍排序。

运行：python3.11 -m unittest six_am.tests.test_priority -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from six_am import engine          # noqa: E402
from six_am import priority        # noqa: E402
from six_am import questionnaire   # noqa: E402
from six_am import rules as R      # noqa: E402


def _dim(state="Secure", confidence=None):
    return {"state": state, "confidence": confidence, "subtype": None,
            "cross_mods": [], "flags": [], "notes": []}


def _item(label, value):
    return {"code": "", "label": label, "raw_value": value, "eval_value": value,
            "eval_source": "规则推导", "dimension": "", "data_bias": "正常"}


def _order_item(value, pos, total=15):
    return {"code": "ORDERPOS:%s" % value, "label": "%s排序位置" % value,
            "raw_value": "第%d位/共%d位" % (pos, total),
            "eval_value": "第%d位/共%d位" % (pos, total),
            "eval_source": "规则推导", "dimension": "", "data_bias": "正常"}


def _dims(**kw):
    dims = {d: _dim() for d in ("A1", "A2", "A3", "A4", "A5")}
    for d, spec in kw.items():
        dims[d] = _dim(*spec)
    dims["A6"] = _dim(None, None)
    return dims


class PriorityOrdering(unittest.TestCase):
    """priority.compute 纯函数排序规则。"""

    def test_a3_overload_is_first(self):
        # A3 Blocked（无 x3_top）也强制第一
        dims = _dims(A1=("At-Risk", "Confirmed"), A2=("At-Risk", "Confirmed"),
                     A3=("Blocked", "Hypothesis"))
        res = priority.compute(dims, {})
        self.assertEqual(res["priority_order"][0], "A3")
        # x3_top 命中时 A3 非 Blocked 同样置顶
        dims = _dims(A2=("Blocked", "Confirmed"), A3=("At-Risk", "Hypothesis"))
        res = priority.compute(dims, {"x3_top": True})
        self.assertEqual(res["priority_order"][0], "A3")
        self.assertIn("A3", res["obstacles"][0]["priority_reason"])

    def test_confirmed_beats_hypothesis_even_when_state_lower(self):
        dims = _dims(A1=("Watch", "Confirmed"), A2=("At-Risk", "Hypothesis"))
        res = priority.compute(dims, {})
        self.assertEqual(res["priority_order"], ["A1", "A2"])

    def test_supported_beats_hypothesis_at_same_state(self):
        dims = _dims(A1=("At-Risk", "Hypothesis"), A2=("At-Risk", "Supported"))
        res = priority.compute(dims, {})
        self.assertEqual(res["priority_order"], ["A2", "A1"])

    def test_x1_forces_a1_before_a2(self):
        # 无 X.1 时 A2（Blocked+Confirmed）应排在 A1（At-Risk+Hypothesis）前
        dims = _dims(A1=("At-Risk", "Hypothesis"), A2=("Blocked", "Confirmed"))
        res = priority.compute(dims, {})
        self.assertEqual(res["priority_order"], ["A2", "A1"])
        # X.1 命中：A1 必须先于 A2
        res = priority.compute(dims, {"x1": True})
        self.assertEqual(res["priority_order"], ["A1", "A2"])
        self.assertIn("X.1", res["obstacles"][0]["priority_reason"])

    def test_x6_beats_x1_interest_exploration_before_a1(self):
        # X.6 × X.1 同时命中：A2 兴趣探索必须排在 A1 前，X.1 不得把 A1 提到 A2 前
        dims = _dims(A1=("At-Risk", "Hypothesis"), A2=("At-Risk", "Supported"))
        dims["A2"]["subtype"] = "A2-S3"
        res = priority.compute(dims, {"x1": True, "x6": True})
        self.assertEqual(res["priority_order"], ["A2", "A1"])
        self.assertIn("兴趣探索", res["obstacles"][0]["priority_reason"])
        # X.6 命中时 A1 为任务级干预暂缓，不写 X.1 双锁文案
        a1 = [o for o in res["obstacles"] if o["dim"] == "A1"][0]
        self.assertIn("暂缓", a1["priority_reason"])
        self.assertNotIn("X.1", a1["priority_reason"])

    def test_x6_prioritizes_interest_exploration_after_a3(self):
        dims = _dims(A2=("At-Risk", "Supported"), A3=("At-Risk", "Hypothesis"),
                     A4=("Blocked", "Confirmed"), A5=("Watch", "Hypothesis"))
        dims["A2"]["subtype"] = "A2-S3"
        res = priority.compute(dims, {"x3_top": True, "x6": True})
        # A3 先于 A2；A2 兴趣探索优先位；其余按证据状态
        self.assertEqual(res["priority_order"], ["A3", "A2", "A4", "A5"])
        self.assertIn("兴趣探索", res["obstacles"][1]["priority_reason"])
        # X.6：A1/A5 写"任务级干预暂缓"原因（A1 Secure 不在排序中，A5 必须在）
        a5 = [o for o in res["obstacles"] if o["dim"] == "A5"][0]
        self.assertIn("暂缓", a5["priority_reason"])
        self.assertIn("暂缓", dims["A5"]["priority_reason"])

    def test_x6_a1_gets_deferral_reason_when_present(self):
        dims = _dims(A1=("Watch", "Hypothesis"), A2=("At-Risk", "Supported"),
                     A5=("Watch", "Hypothesis"))
        dims["A2"]["subtype"] = "A2-S3"
        res = priority.compute(dims, {"x6": True})
        self.assertEqual(res["priority_order"][0], "A2")
        for d in ("A1", "A5"):
            self.assertIn("暂缓", dims[d]["priority_reason"], d)

    def test_x7_defers_a1_and_prioritizes_a2(self):
        dims = _dims(A1=("Blocked", "Confirmed"), A2=("At-Risk", "Hypothesis"))
        res = priority.compute(dims, {"x7": True})
        self.assertNotIn("A1", res["priority_order"])
        self.assertEqual(res["priority_order"][0], "A2")
        deferred = {d["dim"]: d for d in res["deferred"]}
        self.assertIn("A1", deferred)
        self.assertIn("长期目标", deferred["A1"]["reason"])
        self.assertIn("意义", res["sequence_note"])
        # X.1 与 X.7 同时命中：不把 A1 拉回排序
        dims["A2"]["state"] = "At-Risk"
        res = priority.compute(dims, {"x7": True, "x1": True})
        self.assertNotIn("A1", res["priority_order"])
        self.assertIn("A1", {d["dim"] for d in res["deferred"]})

    def test_a4_precedes_a5_when_tied(self):
        dims = _dims(A4=("At-Risk", "Hypothesis"), A5=("At-Risk", "Hypothesis"))
        res = priority.compute(dims, {})
        self.assertEqual(res["priority_order"], ["A4", "A5"])

    def test_secure_dims_not_in_obstacles(self):
        dims = _dims(A2=("Watch", "Hypothesis"))
        res = priority.compute(dims, {})
        self.assertEqual(res["priority_order"], ["A2"])
        self.assertEqual([o["dim"] for o in res["obstacles"]], ["A2"])
        self.assertEqual(res["deferred"], [])

    def test_a6_not_in_obstacle_ordering(self):
        dims = _dims(A1=("At-Risk", "Hypothesis"))
        res = priority.compute(dims, {})
        dims_in_order = res["priority_order"] + [d["dim"] for d in res["deferred"]]
        self.assertNotIn("A6", dims_in_order)

    def test_obstacle_shape_and_writeback(self):
        dims = _dims(A1=("At-Risk", "Hypothesis"), A3=("Blocked", "Supported"))
        res = priority.compute(dims, {"x3_top": True})
        self.assertEqual(res["priority_order"], ["A3", "A1"])
        for i, o in enumerate(res["obstacles"], 1):
            self.assertEqual(o["sequence"], i)
            self.assertIn("dim", o)
            self.assertIn("priority_reason", o)
            self.assertIn("state", o)
            self.assertIn("evidence_state", o)
            self.assertNotIn("score", o)
            self.assertNotIn("high_priority", o)
        # priority_rank / priority_reason 写回每个非 Secure 维度
        self.assertEqual(dims["A3"]["priority_rank"], 1)
        self.assertEqual(dims["A1"]["priority_rank"], 2)
        self.assertTrue(dims["A1"]["priority_reason"])
        self.assertNotIn("priority_rank", dims["A2"])  # Secure 不写回
        self.assertEqual(res["obstacles"][0]["state"], "Blocked")
        self.assertEqual(res["obstacles"][0]["evidence_state"], "Supported")


class EngineV2Profile(unittest.TestCase):
    """engine 产出的 v2 profile：无 score，schema 升级，含 priority_order/deferred。"""

    def setUp(self):
        items = [
            {"code": "", "label": "体质健康-睡眠评级", "raw_value": "差",
             "eval_value": "差", "eval_source": "规则推导", "dimension": "",
             "data_bias": "正常"},
            {"code": "", "label": "学习动机-自我效能感", "raw_value": "偏低",
             "eval_value": "偏低", "eval_source": "规则推导", "dimension": "",
             "data_bias": "正常"},
        ]
        self.p = engine.run(items, student={"name": "t", "grade": "g"},
                            engine_version="v0.4")

    def test_no_score_is_written_to_dimensions(self):
        for dim, rec in self.p["dimensions"].items():
            self.assertNotIn("score", rec, dim)
        for o in self.p["obstacles"]:
            self.assertNotIn("score", o)
            self.assertNotIn("high_priority", o)

    def test_schema_v2_and_priority_fields(self):
        self.assertEqual(self.p["schema"], "six-am-profile-v2")
        self.assertIn("priority_order", self.p)
        self.assertIn("deferred", self.p)
        # X.3 命中（A3 At-Risk）：A3 置顶
        self.assertEqual(self.p["priority_order"][0], "A3")
        self.assertEqual(self.p["deferred"], [])

    def test_x7_deferred_a1_gets_no_questions(self):
        # X.7：deferred 的 A1 不进入本轮 questionnaire 维度池
        items = [
            {"code": "", "label": "自驱力-自主性", "raw_value": "偏低",
             "eval_value": "偏低", "eval_source": "规则推导", "dimension": "",
             "data_bias": "正常"},
        ]
        p = engine.run(items, evidence={"parent": {"cannot_relinquish": True}},
                       engine_version="v0.4")
        self.assertIn("A1", {d["dim"] for d in p["deferred"]})
        self.assertNotIn("A1", {q["dim"] for q in p["questions"]})
        # A6 题仍按规则保留
        self.assertIn("A6", {q["dim"] for q in p["questions"]})

    def test_default_params_no_longer_carry_score_weights(self):
        for key in ("severity", "confidence_factor", "r45_neuroticism",
                    "x1_multiplier", "x3_multiplier", "x7_multiplier",
                    "high_priority_min_score",
                    "a6_base_score", "a6_effectiveness"):
            self.assertNotIn(key, R.DEFAULT_PARAMS, key)

    def test_cross_rules_no_multipliers(self):
        from six_am import cross_rules
        import inspect
        src = inspect.getsource(cross_rules.apply)
        self.assertNotIn("multiplier", src)


class A6QualitativeFit(unittest.TestCase):
    """A6 支持方向定性适配（Task 2）：fit_label ∈ {优先, 可考虑, 慎用, 避免}，
    不再输出 score / predicted_effectiveness。"""

    FIT_LABELS = {"优先", "可考虑", "慎用", "避免"}

    def _plan(self, items, evidence=None):
        p = engine.run(items, student={"name": "t", "grade": "g"}, evidence=evidence,
                       engine_version="v0.4")
        return p["support_plan"]

    def _entry(self, plan, direction):
        return [r for r in plan["ranked"] if r["direction"] == direction][0]

    def test_ranked_shape_no_score(self):
        plan = self._plan([_item("人格-宜人性", "高")])   # R6.3
        self.assertTrue(plan["ranked"])
        for entry in plan["ranked"]:
            self.assertEqual(set(entry.keys()),
                             {"direction", "sub_mechanisms", "fit_label",
                              "basis_rules", "cautions"})
            self.assertIn(entry["fit_label"], self.FIT_LABELS)
            self.assertNotIn("score", entry)
            self.assertNotIn("predicted_effectiveness", entry)

    def test_r66_r67_conflict_authority_is_caution_with_x5(self):
        # A1-S2（逆反）→ R6.6 慎用；A5-S3（结构依赖）→ R6.7 推荐 Structure
        # v0.4：A1-S2 要求自主性偏低，与 Y4 推出的 A5-S3（要求自主性不低）互斥，
        # 冲突只会在标准化任务确认结构依赖（R5.7）时出现
        items = [
            _order_item("独立自主", 2),
            _item("自驱力-自主性", "偏低"),
        ]
        evidence = {"ft": {"standard_task": {"can_split": True, "can_commit": False}}}
        plan = self._plan(items, evidence)
        authority = self._entry(plan, "导师督促")
        # 不得显示为高分推荐：必须慎用，并保留 X.5 裁决说明
        self.assertEqual(authority["fit_label"], "慎用")
        self.assertIn("X.5", authority["cautions"])
        self.assertNotEqual(plan["ranked"][0]["direction"], "导师督促")

    def test_peer_collaboration_with_behavioral_evidence_is_preferred(self):
        # R6.1：外倾性高 + 同伴依恋高 + 团队行为经观察佐证 → 同伴协作 优先
        items = [
            _item("人格-外倾性", "高"),
            _item("依恋关系-亲近-同伴", "高"),
        ]
        evidence = {"observation": {"team_behavior_verified": True}}
        plan = self._plan(items, evidence=evidence)
        peer = self._entry(plan, "同伴协作")
        self.assertEqual(peer["fit_label"], "优先")
        self.assertIn("R6.1", peer["basis_rules"])

    def test_no_signal_direction_is_considerable(self):
        plan = self._plan([_item("人格-宜人性", "高")])   # 仅 R6.3 → 导师督促 优先
        self.assertEqual(self._entry(plan, "导师督促")["fit_label"], "优先")
        self.assertEqual(self._entry(plan, "同伴协作")["fit_label"], "可考虑")
        self.assertEqual(self._entry(plan, "家长陪同")["fit_label"], "可考虑")

    def test_neuroticism_flag_adds_high_pressure_caution(self):
        # R4.5 神经质背景 flag（较好：不触发 R6.5）+ R6.4 成就价值靠前
        items = [
            _item("人格-神经质", "较好"),
            _order_item("成就感", 2),
        ]
        plan = self._plan(items)
        peer = self._entry(plan, "同伴协作")
        parent = self._entry(plan, "家长陪同")
        authority = self._entry(plan, "导师督促")
        self.assertIn("Competition", peer["sub_mechanisms"])
        self.assertIn("Recognition", parent["sub_mechanisms"])
        # “认可、适度竞争”必须携带高压力评价 caution
        self.assertIn("高压力评价", peer["cautions"])
        self.assertIn("高压力评价", parent["cautions"])
        self.assertNotIn("高压力评价", authority["cautions"])


class QuestionnairePriorityOrder(unittest.TestCase):
    """questionnaire.select 使用 priority_order，不再读 dims[dim]['score']。"""

    def test_questionnaire_uses_priority_order_without_score(self):
        dims = _dims(A1=("Watch", "Hypothesis"), A3=("Watch", "Hypothesis"))
        # 注意：dims 中无 score 字段
        hits = {
            "A1": [{"id": "R1.1", "effect": {"state": "At-Risk"},
                    "questions": ["Q1.1"]}],
            "A3": [{"id": "R3.1", "effect": {"state": "At-Risk"},
                    "questions": ["Q3.1"]}],
            "A6": [],
        }
        params = R.merge_params(None)
        # priority_order 把 A3 排在 A1 前（与旧分数排序相反的演示）
        selected = questionnaire.select(dims, hits, params, ["A3", "A1"])
        self.assertEqual(selected[0]["dim"], "A3")
        self.assertEqual(selected[0]["id"], "Q3.1")
        dims_in_order = [q["dim"] for q in selected]
        self.assertLess(dims_in_order.index("A3"), dims_in_order.index("A1"))

    def test_hypothesis_dims_preferred_within_top_limit(self):
        dims = _dims(A1=("At-Risk", "Confirmed"), A2=("At-Risk", "Hypothesis"))
        hits = {
            "A1": [{"id": "R1.1", "effect": {"state": "At-Risk"},
                    "questions": ["Q1.1"]}],
            "A2": [{"id": "R2.3", "effect": {"state": "At-Risk"},
                    "questions": ["Q2.2"]}],
            "A6": [],
        }
        params = R.merge_params(None)
        selected = questionnaire.select(dims, hits, params, ["A1", "A2"])
        # 仅线索（Hypothesis）维度优先追问
        self.assertEqual(selected[0]["dim"], "A2")

    def test_deferred_dim_excluded_from_question_pool(self):
        dims = _dims(A1=("At-Risk", "Hypothesis"), A2=("Watch", "Hypothesis"))
        dims["A1"]["deferred"] = True   # X.7 长期目标标记
        dims["A1"]["priority_rank"] = None
        hits = {
            "A1": [{"id": "R1.1", "effect": {"state": "At-Risk"},
                    "questions": ["Q1.1"]}],
            "A2": [{"id": "R2.5", "effect": {"state": "Watch"},
                    "questions": ["Q2.4"]}],
            "A6": [],
        }
        params = R.merge_params(None)
        # priority_order 不含 deferred A1；fallback 也不得补回
        selected = questionnaire.select(dims, hits, params, ["A2"])
        selected_dims = {q["dim"] for q in selected}
        self.assertNotIn("A1", selected_dims)
        self.assertIn("A2", selected_dims)
        self.assertIn("A6", selected_dims)
        # 即使调用方误把 deferred 维度放进 priority_order，也会被过滤
        selected = questionnaire.select(dims, hits, params, ["A1", "A2"])
        self.assertNotIn("A1", {q["dim"] for q in selected})

    def test_multi_rule_verify_question_first_within_dim(self):
        dims = _dims(A1=("At-Risk", "Hypothesis"))
        hits = {
            "A1": [
                {"id": "R1.5", "effect": {"state": "Watch"}, "questions": ["Q1.6"]},
                {"id": "R1.1", "effect": {"state": "At-Risk"}, "questions": ["Q1.1"]},
            ],
            "A6": [],
        }
        params = R.merge_params(None)
        selected = questionnaire.select(dims, hits, params, ["A1"])
        # Q1.1 verify 跨 R1.1/R1.2 两条规则（能区分解释），优先于只验证 R1.5 的 Q1.6
        self.assertEqual(selected[0]["id"], "Q1.1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
