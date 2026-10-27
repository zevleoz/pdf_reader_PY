# -*- coding: utf-8 -*-
"""证据字段测试（P1）：原始分、常模、证据强度随 trace 一起产出。

运行：python3 -m pytest -q six_am/tests/test_evidence_fields.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from six_am import engine          # noqa: E402
from six_am import rules as R      # noqa: E402


def _item(label, eval_value, raw_value=None, source="Y4"):
    return {"label": label, "eval_value": eval_value, "raw_value": raw_value,
            "eval_source": source}


class EvidenceFieldsTest(unittest.TestCase):
    def test_autonomy_evidence_has_raw_norm_and_strong_tier(self):
        items = [
            _item("自驱力-自主性", "偏低", "3.3"),
            _item("自驱力-自主性常模平均数", None, "6.1"),
        ]
        profile = engine.run(items, engine_version="v0.4")
        traces = [t for t in profile["dimensions"]["A1"]["triggered_rules"] if t["id"] == "R1.1"]
        self.assertEqual(len(traces), 1)
        ev = traces[0]["evidence"][0]
        self.assertEqual(ev["raw_value"], "3.3")
        self.assertEqual(ev["norm"], 6.1)
        self.assertEqual(ev["tier"], "strong")

    def test_anxiety_evidence_mild_without_norm(self):
        items = [_item("情绪稳定性-焦虑安详", "需关注", "8")]
        ctx = engine.Ctx(items, None, R.merge_params(None))
        ok, ev, _desc = engine.eval_cond(
            {"point": "情绪稳定性-焦虑安详", "tier": "mild"}, ctx)
        self.assertTrue(ok)
        self.assertEqual(ev[0]["tier"], "mild")
        self.assertIsNone(ev[0]["norm"])


if __name__ == "__main__":
    unittest.main()
