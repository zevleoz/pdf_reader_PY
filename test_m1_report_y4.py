"""会后报告 Y4 评级（协议附录 A）：每条规则、每个边界两侧。"""
from __future__ import annotations

import pytest

import data_points
from m1 import report_y4, y4_evidence


def _rate(code, value, **extra):
    values = {code: value}
    values.update(extra)
    return report_y4.rate_all(values)[code]


# (代码, 值, 期望评级)，期望值直接抄自附录 A，不从 RULES 推导
FIXED_CASES = [
    # A1 002
    ("002", 98, "高"), ("002", 97.99, "较好"), ("002", 80, "较好"), ("002", 79.99, "不低"),
    ("002", 60, "不低"), ("002", 59.99, "偏低"), ("002", 100, "高"), ("002", 0, "偏低"),
    # A1 003-008
    ("003", 95, "高"), ("003", 94.99, "较好"), ("004", 80, "较好"), ("005", 79.99, "不低"),
    ("006", 60, "不低"), ("007", 59.99, "偏低"), ("008", 97, "高"),
    # A2 009
    ("009", 60, "高"), ("009", 49, "高"), ("009", 48.99, "较好"), ("009", 37, "较好"),
    ("009", 36.99, "不低"), ("009", 25, "不低"), ("009", 24.99, "偏低"),
    ("009", 13, "偏低"), ("009", 12.99, "明显偏低"), ("009", 0, "明显偏低"),
    # A2 011-014
    ("011", 4.99, "需特殊关注"), ("011", 0, "需特殊关注"), ("012", 5, "需关注"),
    ("013", 10, "需关注"), ("014", 10.01, "相对健康"), ("011", 15, "相对健康"),
    # A3 015-019
    ("015", 5, "高"), ("015", 4.51, "高"), ("016", 4.5, "较好"), ("017", 3.5, "较好"),
    ("018", 3.49, "不低"), ("019", 3, "不低"), ("015", 2.99, "偏低"), ("016", 2.5, "偏低"),
    ("017", 2.49, "明显偏低"), ("018", 1.5, "明显偏低"), ("019", 1.49, "严重偏低"),
    ("015", 1, "严重偏低"),
    # A4 023-025
    ("023", 50, "高"), ("023", 35, "高"), ("024", 34.99, "不低"), ("025", 18, "不低"),
    ("023", 17.99, "偏低"), ("024", 1, "偏低"),
    # A4 026-028
    ("026", 45, "高"), ("026", 31, "高"), ("027", 30.99, "不低"), ("028", 16, "不低"),
    ("026", 15.99, "偏低"), ("027", 1, "偏低"),
    # A4 029-031
    ("029", 30, "高"), ("029", 21, "高"), ("030", 20.99, "不低"), ("031", 11, "不低"),
    ("029", 10.99, "偏低"), ("030", 1, "偏低"),
    # A6 053-058
    ("053", 10, "高"), ("053", 8, "高"), ("054", 7.99, "较好"), ("055", 6, "较好"),
    ("056", 5.99, "不低"), ("057", 4, "不低"), ("058", 3.99, "偏低"), ("053", 2, "偏低"),
    ("054", 1.99, "严重偏低"), ("055", 0, "严重偏低"),
    # A8 063-065
    ("063", 95, "高"), ("063", 94.99, "较好"), ("064", 80, "较好"), ("065", 79.99, "不低"),
    ("063", 60, "不低"), ("064", 59.99, "偏低"), ("065", 100, "高"),
    # A11 073-078 和 A12 079-086
    ("073", 10, "高"), ("073", 7, "高"), ("074", 6.99, "不低"), ("075", 4, "不低"),
    ("076", 3.99, "偏低"), ("077", 1, "偏低"),
    ("079", 7, "高"), ("080", 6.99, "不低"), ("084", 4, "不低"), ("085", 3.99, "偏低"),
    ("086", 10, "高"), ("086", 1, "偏低"),
    # A13 095-109
    ("095", 10, "高"), ("095", 9, "高"), ("096", 8.99, "较好"), ("097", 7.5, "较好"),
    ("098", 7.49, "不低"), ("099", 6.66, "不低"), ("100", 6.65, "偏低"), ("101", 5, "偏低"),
    ("102", 4.99, "明显偏低"), ("109", 0, "明显偏低"),
]


@pytest.mark.parametrize("code,value,expected", FIXED_CASES)
def test_fixed_threshold_boundaries(code, value, expected):
    entry = _rate(code, value)
    assert entry["rating"] == expected
    assert entry["state"] == "ok"
    assert entry["value"] == value


# 与均分比较：060-062、066-071
MEAN_CASES = [
    (7.0, 6.5, "较好"),       # 等于均分+0.5
    (6.99, 6.5, "不低"),      # 刚好低于均分+0.5
    (6.0, 6.5, "不低"),       # 等于均分-0.5
    (5.99, 6.5, "偏低"),      # 刚好低于均分-0.5
    (9, 6.5, "较好"),
    (6.5, 6.5, "不低"),
    (1, 6.5, "偏低"),
]


@pytest.mark.parametrize("code", sorted(y4_evidence._NORM_CODE))
@pytest.mark.parametrize("value,mean,expected", MEAN_CASES)
def test_mean_compared_boundaries(code, value, mean, expected):
    entry = _rate(code, value, **{y4_evidence._NORM_CODE[code]: mean})
    assert entry["rating"] == expected
    assert entry["mean"] == mean
    assert entry["state"] == "ok"
    assert "（均分%s）" % mean in entry["line"]


def test_mean_line_matches_protocol_example():
    entry = _rate("060", 7.4, **{"125": 5.9})
    assert entry["line"] == "060 自驱力-自主性：7.4，较好（均分5.9）"
    assert entry["family_line"] == "自驱力—自主性：7.4，较好（均分5.9）"


@pytest.mark.parametrize("code", sorted(y4_evidence._NORM_CODE))
def test_missing_or_bad_mean_is_check(code):
    for norm in (None, "", "无"):
        values = {code: 7, y4_evidence._NORM_CODE[code]: norm}
        entry = report_y4.rate_all(values)[code]
        assert entry["state"] == "check"
        assert entry["rating"] == "待核实"


# 有效范围外、缺失、非数字
OUT_OF_RANGE = [
    ("002", 100.01), ("002", -0.01), ("003", 101), ("009", 60.01), ("009", -1),
    ("011", 15.01), ("011", -0.5), ("015", 5.01), ("015", 0.99),
    ("023", 50.01), ("023", 0.99), ("026", 45.01), ("026", 0), ("029", 30.01),
    ("029", 0.5), ("053", 10.01), ("053", -0.01), ("063", 100.01), ("063", -1),
    ("073", 10.01), ("073", 0.99), ("084", 11), ("084", 0),
    ("095", 10.01), ("095", -0.01), ("109", 11),
]


@pytest.mark.parametrize("code,value", OUT_OF_RANGE)
def test_out_of_range_is_check(code, value):
    entry = _rate(code, value)
    assert entry["state"] == "check"
    assert entry["rating"] == "待核实"


@pytest.mark.parametrize("code", ["002", "009", "013", "016", "023", "053", "063",
                                  "073", "084", "095", "060", "070", "010", "052"])
@pytest.mark.parametrize("bad", [None, "", "abc", True])
def test_missing_or_not_a_number_is_check(code, bad):
    entry = _rate(code, bad, **{"125": 5, "126": 5, "127": 5, "128": 5, "129": 5,
                                 "130": 5, "131": 5, "132": 5, "133": 5})
    assert entry["state"] == "check"
    assert entry["rating"] == "待核实"


def test_absent_code_is_check_not_invented():
    entry = report_y4.rate_all({})["013"]
    assert entry["state"] == "check"
    assert entry["value"] is None
    assert "缺失" in entry["line"]


# 保留原值
RAW = (["020", "021", "022", "051", "059", "072"]
       + ["%03d" % n for n in range(41, 51)]
       + ["087", "088", "089"] + ["%03d" % n for n in range(110, 115)])


@pytest.mark.parametrize("code", RAW)
def test_raw_codes_are_kept_without_rating(code):
    entry = _rate(code, "原始结果" if code in ("020", "072", "087") else 7)
    assert entry["state"] == "raw"
    assert entry["rating"] == ""


def test_bmi_grade_kept_when_source_has_it():
    entry = _rate("041", 21.4, **{"042": "正常"})
    assert entry["state"] == "raw"
    assert entry["grade"] == "正常"
    assert "正常" in entry["line"]
    assert "grade" not in _rate("041", 21.4)


def test_codes_outside_appendix_a_have_no_entry():
    ratings = report_y4.rate_all({"001": "x", "032": "高", "125": 5,
                                  "134": 3})
    for code in ("001", "032", "125", "134", "050a"):
        assert code not in ratings


# 档位型
@pytest.mark.parametrize("value,expected", [(1, "明显偏低"), (2, "偏低"), (3, "不低"),
                                            (4, "较好"), (5, "高"), ("4", "较好"),
                                            ("高", "高")])
def test_010_bands(value, expected):
    entry = _rate("010", value)
    assert entry["rating"] == expected


@pytest.mark.parametrize("value", [0, 6, 2.5, "x"])
def test_010_invalid(value):
    assert _rate("010", value)["state"] == "check"


@pytest.mark.parametrize("value,expected", [(1, "偏低"), (2, "正常"), (3, "偏高"),
                                            ("正常", "正常")])
def test_052_bands(value, expected):
    assert _rate("052", value)["rating"] == expected


@pytest.mark.parametrize("value", [0, 4, "x"])
def test_052_invalid(value):
    assert _rate("052", value)["state"] == "check"


# 报告自带档位冲突
def test_009_agrees_with_010():
    ratings = report_y4.rate_all({"009": 50, "010": 5})
    assert ratings["009"]["state"] == "ok" and ratings["010"]["state"] == "ok"


def test_009_conflicts_with_010():
    ratings = report_y4.rate_all({"009": 50, "010": 2})
    assert ratings["009"]["state"] == "check"
    assert ratings["010"]["state"] == "check"


def test_009_without_010_is_unaffected():
    assert report_y4.rate_all({"009": 50})["009"]["rating"] == "高"
    assert report_y4.rate_all({"010": 4})["010"]["rating"] == "较好"


@pytest.mark.parametrize("score,level", [(23, 32), (24, 33), (25, 34), (26, 35),
                                         (27, 36), (28, 37), (29, 38), (30, 39),
                                         (31, 40)])
def test_attachment_carried_band(score, level):
    code, carried = "%03d" % score, "%03d" % level
    value = {23: 36, 24: 36, 25: 36, 26: 32, 27: 32, 28: 32, 29: 22, 30: 22, 31: 22}[score]
    assert _rate(code, value, **{carried: "高"})["state"] == "ok"
    assert _rate(code, value, **{carried: "偏低"})["state"] == "check"
    assert _rate(code, value, **{carried: ""})["state"] == "ok"
    assert _rate(code, value)["state"] == "ok"


# 与 y4_evidence.band_for 一致
def _sweep(low, high):
    points = {low, high}
    for base in range(int(low) - 1, int(high) + 2):
        for delta in (-0.01, 0, 0.01, 0.5):
            points.add(round(base + delta, 2))
    for edge in (0.5, 1.5, 2.5, 3.5, 4.5, 6.66, 6.65, 7.5, 6.67):
        points.add(edge)
    return sorted(p for p in points if low <= p <= high)


FIXED_CODES = sorted(report_y4.RULES)


@pytest.mark.parametrize("code", FIXED_CODES)
def test_agrees_with_y4_evidence_band_for(code):
    limits = report_y4._valid_range(code)
    assert limits is not None, code
    checked = 0
    for value in _sweep(*limits):
        mine = _rate(code, value)
        theirs = y4_evidence.band_for(code, {code: value})
        assert mine["state"] == "ok", (code, value)
        assert mine["rating"] == theirs, (code, value, mine["rating"], theirs)
        checked += 1
    assert checked > 10


def test_every_rule_code_is_in_the_y4_schema():
    for code in report_y4.applicable_codes():
        assert code in data_points.POINT_META


def test_rate_all_covers_every_applicable_code():
    ratings = report_y4.rate_all({})
    assert set(ratings) == set(report_y4.applicable_codes())
    for code, entry in ratings.items():
        assert entry["code"] == code
        assert set(entry) >= {"code", "label", "value", "rating", "mean", "state",
                              "line", "family_line"}


def test_show_values_switch_exists():
    assert report_y4.Y4_SHOW_VALUES is True


def _exact_mean_rating(value, mean):
    # 独立的十进制计算（不调用被测代码）：≥ 均分 + 0.5 较好；≥ 均分 - 0.5 不低；否则偏低
    from decimal import Decimal
    v, m, half = Decimal(str(value)), Decimal(str(mean)), Decimal("0.5")
    if v >= m + half:
        return "较好"
    if v >= m - half:
        return "不低"
    return "偏低"


# 刻意不用 band_for：它用 float 比较，在 3.9/4.4 这类边界上与附录 A 不一致
def test_mean_compared_agrees_with_band_for():
    tenths = [n / 10 for n in range(0, 101)]
    for value in tenths:
        for mean_tenths in range(1, 101):
            mean = mean_tenths / 10
            assert report_y4._rate_mean(value, mean) == _exact_mean_rating(value, mean), (value, mean)
    for value, mean in [(3.9, 4.4), (7.8, 8.3), (0.3, 0.8), (0.6, 1.1), (1.7, 2.2)]:
        assert report_y4._rate_mean(value, mean) == "不低", (value, mean)
