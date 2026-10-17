"""问卷规则引擎单测（对齐 six_am/tests 风格：pytest 纯函数测试）。"""
from __future__ import annotations

import pytest

from questionnaire_engine import engine


def items(*pairs):
    """(code, value) → 指标条目；可传第 3 项为 eval_value。"""
    out = []
    for p in pairs:
        it = {"code": p[0], "value": p[1]}
        if len(p) > 2:
            it["eval_value"] = p[2]
        out.append(it)
    return out


# ── 各 op ─────────────────────────────────────────────────────
@pytest.mark.parametrize("op,raw,ref,expected", [
    ("=", 5, 5, True),
    ("=", "5", 5, True),          # 数值对齐
    ("=", "偏低", "偏低", True),
    ("=", "偏低", "偏高", False),
    ("!=", 5, 6, True),
    ("!=", 5, 5, False),
    ("<", 4, 5, True),
    ("<", 5, 5, False),
    ("<=", 5, 5, True),
    (">", 3.6, 3.5, True),
    (">=", 3.5, 3.5, True),
])
def test_scalar_ops(op, raw, ref, expected):
    idx = engine._index_items(items(("013", raw)))
    assert engine.eval_condition({"code": "013", "op": op, "value": ref}, idx) is expected


def test_in_op_numeric_alignment():
    idx = engine._index_items(items(("091", "低")))
    assert engine.eval_condition({"code": "091", "op": "in", "value": ["低", "较低"]}, idx)
    assert not engine.eval_condition({"code": "091", "op": "in", "value": ["高"]}, idx)
    assert not engine.eval_condition({"code": "091", "op": "in", "value": "低"}, idx)


def test_contains_op():
    idx = engine._index_items(items(("072", "RIA")))
    assert engine.eval_condition({"code": "072", "op": "contains", "value": "RI"}, idx)
    assert not engine.eval_condition({"code": "072", "op": "contains", "value": "SE"}, idx)


def test_numeric_op_falls_back_to_string():
    idx = engine._index_items(items(("050a", "中等")))
    # 非数值两侧都是字符串 → 字符串比较
    assert engine.eval_condition({"code": "050a", "op": "<", "value": "较重"}, idx)


def test_numeric_op_with_mixed_type_is_false():
    idx = engine._index_items(items(("050a", "中等")))
    assert not engine.eval_condition({"code": "050a", "op": "<", "value": 5}, idx)


def test_empty_value_never_hits_numeric_op():
    idx = engine._index_items(items(("068", "")))
    assert not engine.eval_condition({"code": "068", "op": "<", "value": 5}, idx)


# ── all / any ─────────────────────────────────────────────────
def test_all_group():
    idx = engine._index_items(items(("013", 4), ("054", 3)))
    assert engine.eval_when({"all": [{"code": "013", "op": "<", "value": 5},
                                     {"code": "054", "op": "<", "value": 6}]}, idx)
    idx2 = engine._index_items(items(("013", 4), ("054", 8)))
    assert not engine.eval_when({"all": [{"code": "013", "op": "<", "value": 5},
                                         {"code": "054", "op": "<", "value": 6}]}, idx2)


def test_any_group():
    idx = engine._index_items(items(("019", 4.0), ("009", 30), ("011", 6)))
    assert engine.eval_when({"any": [{"code": "019", "op": ">", "value": 3.5},
                                     {"code": "009", "op": "<", "value": 24},
                                     {"code": "011", "op": "<", "value": 5}]}, idx)


def test_empty_group_and_bad_structure_do_not_hit():
    idx = engine._index_items(items(("013", 1)))
    assert engine.eval_when({"all": []}, idx) is False
    assert engine.eval_when({"any": []}, idx) is False
    assert engine.eval_when({}, idx) is False
    assert engine.eval_when("nope", idx) is False


def test_unknown_code_does_not_hit_or_raise():
    idx = engine._index_items(items(("013", 1)))
    assert engine.eval_condition({"code": "999", "op": "<", "value": 5}, idx) is False


def test_code_alias_leading_zero():
    idx = engine._index_items(items(("013", 4)))
    assert engine.eval_condition({"code": "13", "op": "<", "value": 5}, idx)


# ── source=eval（有效评价档位）──────────────────────────────────
def test_eval_source_uses_eval_value():
    idx = engine._index_items(items(("068", 3.1, "偏低")))
    cond = {"code": "068", "op": "=", "value": "偏低", "source": "eval"}
    assert engine.eval_condition(cond, idx)
    cond2 = {"code": "068", "op": "=", "value": "偏低"}   # 默认比原值 → 不命中
    assert engine.eval_condition(cond2, idx) is False


# ── 整规则集 ──────────────────────────────────────────────────
RULES = {
    "version": 1,
    "rules": [
        {"questionnaire_code": "Q-ANX-01",
         "when": {"all": [{"code": "013", "op": "<", "value": 5}]},
         "reason": "焦虑子分数偏低"},
        {"questionnaire_code": "Q-STRESS-01",
         "when": {"all": [{"code": "013", "op": "<", "value": 10},
                          {"code": "054", "op": "<", "value": 6}]},
         "reason": "焦虑偏高且学业自我概念偏低"},
        {"questionnaire_code": "Q-STRESS-01",
         "when": {"all": [{"code": "068", "op": "=", "value": "偏低", "source": "eval"}]},
         "reason": "学习自我效能感偏低"},
    ]
}


def test_evaluate_dedupes_same_questionnaire():
    rows = items(("013", 4), ("054", 3), ("068", 2.0, "偏低"))
    hits = engine.evaluate(rows, RULES)
    codes = [h["questionnaire_code"] for h in hits]
    assert codes == ["Q-ANX-01", "Q-STRESS-01"]      # Q-STRESS-01 只出现一次
    assert hits[1]["reason"] == "焦虑偏高且学业自我概念偏低"


def test_evaluate_second_rule_for_same_questionnaire_can_win_alone():
    rows = items(("013", 12), ("054", 9), ("068", 2.0, "偏低"))
    hits = engine.evaluate(rows, RULES)
    assert [h["questionnaire_code"] for h in hits] == ["Q-STRESS-01"]
    assert hits[0]["reason"] == "学习自我效能感偏低"


def test_evaluate_no_rules_or_empty():
    assert engine.evaluate(items(("013", 1)), None) == []
    assert engine.evaluate(items(("013", 1)), {}) == []
    assert engine.evaluate(items(("013", 1)), {"rules": []}) == []
    assert engine.evaluate(None, RULES) == []


# ── validate_rules ────────────────────────────────────────────
def test_validate_rules_ok():
    assert engine.validate_rules(RULES) == []


def test_validate_rules_reports_errors():
    bad = {"rules": [{"questionnaire_code": "", "when": {"all": [{"code": "013", "op": "~", "value": 1}]}}]}
    errs = engine.validate_rules(bad)
    assert any("questionnaire_code" in e for e in errs)
    assert any("op 必须是" in e for e in errs)


def test_validate_rules_warns_unknown_code():
    known = {"013"}
    errs = engine.validate_rules(RULES, known_codes=known)
    assert any(e.startswith("警告") and "054" in e for e in errs)
