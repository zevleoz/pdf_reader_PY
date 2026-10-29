# -*- coding: utf-8 -*-
"""v0.6 模型文件：加载、校验、思维导图导出。"""

import copy
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from six_am.model import export_md, load_model, validate  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MINDMAP = ROOT / "docs" / "audits" / "6am-mindmap.md"


class ModelFile(unittest.TestCase):
    def test_model_is_valid(self):
        self.assertEqual(validate(load_model()), [])

    def test_load_returns_fresh_copy(self):
        first = load_model()
        first["dims"][0]["name"] = "改过的名字"
        self.assertNotEqual(load_model()["dims"][0]["name"], "改过的名字")

    def test_export_matches_file(self):
        self.assertEqual(export_md(load_model()), MINDMAP.read_text(encoding="utf-8"))

    def test_display_text_appears_in_export(self):
        model = load_model()
        md = export_md(model)
        for dim in model["dims"]:
            for part in dim["parts"]:
                for node in part["levels"].values():
                    self.assertIn(node["text"], md)
            for cause in (dim.get("blocked") or {}).get("causes") or []:
                self.assertIn(cause["name"], md)
        for item in model["a6"]["items"]:
            self.assertIn(item["name"], md)


class ValidateErrors(unittest.TestCase):
    def test_unknown_leaf(self):
        model = copy.deepcopy(load_model())
        model["dims"][0]["parts"][0]["levels"]["稳固"]["when"] = {"bogus": []}
        self.assertTrue(any("未知条件类型" in error for error in validate(model)))

    def test_unknown_band(self):
        model = copy.deepcopy(load_model())
        model["dims"][0]["parts"][0]["levels"]["稳固"]["when"] = {
            "y4": "自驱力-自主性", "band": "没有这个档"}
        self.assertTrue(any("band 不存在" in error for error in validate(model)))

    def test_unknown_signal(self):
        model = copy.deepcopy(load_model())
        model["dims"][0]["blocked"]["causes"][0]["hint"] = {"signal": "no_such_signal"}
        self.assertTrue(any("未知信号：no_such_signal" in error for error in validate(model)))

    def test_bad_self_level(self):
        model = copy.deepcopy(load_model())
        when = model["dims"][0]["parts"][0]["levels"]["风险"]["when"]
        when["any"][1]["all"][0] = {"self": "阻塞"}
        self.assertTrue(any("self 级别不存在：阻塞" in error for error in validate(model)))

    def test_at_outside_a6(self):
        model = copy.deepcopy(load_model())
        model["dims"][0]["parts"][0]["levels"]["稳固"]["when"] = {
            "at": "A1", "min": "关注"}
        self.assertTrue(any("at 条件只能出现在 a6" in error for error in validate(model)))

    def test_duplicate_a6_id(self):
        model = copy.deepcopy(load_model())
        model["a6"]["items"][1]["id"] = model["a6"]["items"][0]["id"]
        self.assertTrue(any("a6 的 item id 重复" in error for error in validate(model)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
