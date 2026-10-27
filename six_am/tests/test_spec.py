# -*- coding: utf-8 -*-
"""v0.5 默认配置：校验与可编辑字段合并。

运行：python3 -m unittest six_am.tests.test_spec -v
"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from six_am.spec import DEFAULT_SPEC, editable_view, merge_edit, validate  # noqa: E402


class DefaultSpec(unittest.TestCase):
    def test_default_spec_is_valid(self):
        self.assertEqual(validate(DEFAULT_SPEC), [])

    def test_catalogue_shape(self):
        self.assertEqual(len(DEFAULT_SPEC["a6"]), 15)
        ids = [entry["id"] for entry in DEFAULT_SPEC["a6"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(DEFAULT_SPEC["notes"],
                         {"A1": "", "A2": "", "A3": "", "A4": "", "A5": "", "A6": ""})


class ValidateErrors(unittest.TestCase):
    def test_unknown_signal_in_supporting(self):
        spec = copy.deepcopy(DEFAULT_SPEC)
        spec["dimensions"]["A1"]["supporting"].append("bogus")
        errors = validate(spec)
        self.assertTrue(errors)
        self.assertTrue(any("bogus" in e for e in errors))

    def test_supporting_on_disallowed_dimension(self):
        spec = copy.deepcopy(DEFAULT_SPEC)
        spec["dimensions"]["A1"]["supporting"].append("attention_low")
        errors = validate(spec)
        self.assertTrue(any("A1" in e and "attention_low" in e for e in errors))

    def test_bad_condition(self):
        spec = copy.deepcopy(DEFAULT_SPEC)
        spec["a6"][0]["assign"] = {"bogus": []}
        errors = validate(spec)
        self.assertTrue(any("条件语法" in e for e in errors))

    def test_empty_any(self):
        spec = copy.deepcopy(DEFAULT_SPEC)
        spec["a6"][0]["assign"] = {"any": []}
        self.assertTrue(any("非空列表" in e for e in validate(spec)))

    def test_unknown_signal_in_condition(self):
        spec = copy.deepcopy(DEFAULT_SPEC)
        spec["a6"][0]["assign"] = {"signal": "nope"}
        self.assertTrue(any("未知信号" in e for e in validate(spec)))

    def test_duplicate_a6_id(self):
        spec = copy.deepcopy(DEFAULT_SPEC)
        spec["a6"][1]["id"] = spec["a6"][0]["id"]
        self.assertTrue(any("重复" in e for e in validate(spec)))

    def test_param_range(self):
        spec = copy.deepcopy(DEFAULT_SPEC)
        spec["params"]["top_n_values"] = 20
        self.assertTrue(any("top_n_values" in e for e in validate(spec)))

        spec = copy.deepcopy(DEFAULT_SPEC)
        spec["params"]["cog_pct_min"] = "high"
        self.assertTrue(any("cog_pct_min" in e for e in validate(spec)))


class MergeEdit(unittest.TestCase):
    def test_locked_fields_are_ignored(self):
        published = copy.deepcopy(DEFAULT_SPEC)
        edited = copy.deepcopy(DEFAULT_SPEC)
        edited["dimensions"]["A1"]["main"] = ["deep_motive"]
        edited["dimensions"]["A3"]["gates"]["body"] = ["exercise_diet"]
        edited["dimensions"]["A4"]["tracks"] = {"learning": "competence"}
        edited["dimensions"]["A1"]["supporting"] = ["indep_boss_top5"]
        edited["params"]["top_n_values"] = 4
        edited["a6"][0]["note"] = "新备注"
        edited["notes"]["A1"] = "新维度备注"

        merged = merge_edit(published, edited)
        self.assertEqual(merged["dimensions"]["A1"]["main"], ["autonomy"])
        self.assertEqual(merged["dimensions"]["A3"]["gates"]["body"], ["sleep", "exercise_diet"])
        self.assertEqual(merged["dimensions"]["A4"]["tracks"],
                         {"learning": "self_efficacy", "general": "competence"})
        self.assertEqual(merged["dimensions"]["A1"]["supporting"], ["indep_boss_top5"])
        self.assertEqual(merged["params"]["top_n_values"], 4)
        self.assertEqual(merged["a6"][0]["note"], "新备注")
        self.assertEqual(merged["notes"]["A1"], "新维度备注")
        self.assertEqual(published, DEFAULT_SPEC)

    def test_edit_cannot_add_or_rename_a6(self):
        edited = {"a6": [{"id": "new_support", "name": "新方案"},
                         {"id": "peer_support", "group": "新组", "name": "改名"}]}
        merged = merge_edit(copy.deepcopy(DEFAULT_SPEC), edited)
        self.assertEqual([entry["id"] for entry in merged["a6"]],
                         [entry["id"] for entry in DEFAULT_SPEC["a6"]])
        peer = next(entry for entry in merged["a6"] if entry["id"] == "peer_support")
        self.assertEqual(peer["group"], "谁来帮")
        self.assertEqual(peer["name"], "改名")

    def test_editable_view_excludes_locked_fields(self):
        view = editable_view(DEFAULT_SPEC)
        self.assertEqual(set(view), {"params", "supporting", "a6", "notes"})
        self.assertNotIn("main", view["supporting"])
        self.assertEqual(view["a6"][0]["id"], DEFAULT_SPEC["a6"][0]["id"])
        self.assertNotIn("group", view["a6"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
