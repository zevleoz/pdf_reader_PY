# -*- coding: utf-8 -*-
"""P2：版本差异与时间线。"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from six_am.history import diff_profiles, timeline  # noqa: E402

DIMS = ["A1", "A2", "A3", "A4", "A5", "A6"]


def profile(state="At-Risk", confidence="Hypothesis", refuted=None,
            safety=False, rule="v0.4"):
    dims = {d: {"state": "Secure", "confidence": None} for d in DIMS}
    dims["A1"] = {"state": state, "confidence": confidence}
    return {
        "rule_version": {"label": rule},
        "dimensions": dims,
        "refuted": refuted or {},
        "safety_review": safety,
    }


class DiffProfiles(unittest.TestCase):

    def test_state_change(self):
        self.assertEqual(diff_profiles(profile("At-Risk"), profile("Watch")),
                         ["A1 风险 → 关注"])

    def test_confidence_change(self):
        self.assertEqual(
            diff_profiles(profile(confidence="Hypothesis"),
                          profile(confidence="Confirmed")),
            ["A1 证据 仅线索 → 已证实"])

    def test_newly_refuted(self):
        self.assertEqual(
            diff_profiles(profile(), profile(refuted={"R1.3": "Q1.3"})),
            ["Q1.3 否定：R1.3 移出判定"])

    def test_safety_review_on_and_off(self):
        self.assertEqual(diff_profiles(profile(), profile(safety=True)),
                         ["新增情绪安全复核"])
        self.assertEqual(diff_profiles(profile(safety=True), profile()),
                         ["解除情绪安全复核"])

    def test_line_order(self):
        old = profile("At-Risk", "Hypothesis", rule="v0.3")
        new = profile("Watch", "Confirmed", refuted={"R1.3": "Q1.3"},
                      safety=True, rule="v0.4")
        self.assertEqual(diff_profiles(old, new), [
            "规则 v0.3 → v0.4",
            "A1 风险 → 关注",
            "A1 证据 仅线索 → 已证实",
            "Q1.3 否定：R1.3 移出判定",
            "新增情绪安全复核",
        ])

    def test_identical_profiles_have_no_diff(self):
        self.assertEqual(diff_profiles(profile(), profile()), [])

    def test_first_build(self):
        self.assertEqual(diff_profiles(None, profile()), ["Y4 初筛"])


class Timeline(unittest.TestCase):

    def test_newest_first_and_rerun_without_changes(self):
        rows = [
            {"id": 3, "version": 3, "created_at": "c",
             "profile_json": json.dumps(profile("Watch"))},
            {"id": 1, "version": 1, "created_at": "a",
             "profile_json": json.dumps(profile("At-Risk"))},
            {"id": 2, "version": 2, "created_at": "b",
             "profile_json": json.dumps(profile("Watch"))},
        ]
        out = timeline(rows)
        self.assertEqual([r["profile_id"] for r in out], [3, 2, 1])
        self.assertEqual([r["version"] for r in out], [3, 2, 1])
        self.assertEqual(out[-1]["changes"], ["Y4 初筛"])
        self.assertEqual(out[0]["changes"], ["重跑，无变化"])

    def test_change_between_versions(self):
        rows = [
            {"id": 1, "version": 1, "created_at": "a",
             "profile_json": json.dumps(profile("At-Risk"))},
            {"id": 2, "version": 2, "created_at": "b",
             "profile_json": json.dumps(profile("Watch"))},
        ]
        out = timeline(rows)
        self.assertEqual(out[0]["changes"], ["A1 风险 → 关注"])
        self.assertEqual(out[0]["created_at"], "b")


if __name__ == "__main__":
    unittest.main(verbosity=2)
