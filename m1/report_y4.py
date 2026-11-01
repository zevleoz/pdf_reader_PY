"""会后报告的 Y4 评级（协议附录 A），纯规则、不经过 AI。

``rate_all(values)`` 是唯一的公开函数：``values`` 是 ``y4_evidence._values(report)``
的结果（指标编号 → 原始值）。每个附录 A 指标一条：

- ``ok``    规则评级；
- ``raw``   附录 A 要求保留原值，不评级；
- ``check`` 缺失、越界、非数字、缺均分或与报告自带档位冲突，评级为「待核实」。

未列入附录 A 的指标不评级（A14）。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import data_points
from m1 import y4_evidence

# 家庭版是否显示 Y4 数值与评级（协议 §8.3）。一处开关。
Y4_SHOW_VALUES = True

CHECK = "待核实"

# 一条区间：(下界, 下界含等号, 上界, 上界含等号, 评级)；None 表示无界
_Band = Tuple[Optional[float], bool, Optional[float], bool, str]


def _pct(top: float, mid: float, low: float) -> List[_Band]:
    """认知能力 / 执行功能百分位：≥top 高；≥mid <top 较好；≥low <mid 不低；<low 偏低。"""
    return [(top, True, None, False, "高"), (mid, True, top, False, "较好"),
            (low, True, mid, False, "不低"), (None, False, low, False, "偏低")]


_FIVE_LEVEL_3: List[_Band] = [      # A3 人格 015-019
    (4.5, False, None, False, "高"),
    (3.5, True, 4.5, True, "较好"),
    (3.0, True, 3.5, False, "不低"),
    (2.5, True, 3.0, False, "偏低"),
    (1.5, True, 2.5, False, "明显偏低"),
    (None, False, 1.5, False, "严重偏低"),
]

_EMOTION_TOTAL: List[_Band] = [     # A2 009
    (49, True, 60, True, "高"),
    (37, True, 49, False, "较好"),
    (25, True, 37, False, "不低"),
    (13, True, 25, False, "偏低"),
    (0, True, 13, False, "明显偏低"),
]

_EMOTION_ITEM: List[_Band] = [      # A2 011-014
    (None, False, 5, False, "需特殊关注"),
    (5, True, 10, True, "需关注"),
    (10, False, None, False, "相对健康"),
]

_SELF_CONCEPT: List[_Band] = [      # A6 053-058
    (8, True, 10, True, "高"),
    (6, True, 8, False, "较好"),
    (4, True, 6, False, "不低"),
    (2, True, 4, False, "偏低"),
    (0, True, 2, False, "严重偏低"),
]

_THREE_LEVEL: List[_Band] = [       # A11 073-078、A12 079-086
    (7, True, 10, True, "高"),
    (4, True, 7, False, "不低"),
    (1, True, 4, False, "偏低"),
]

_CAREER_VALUE: List[_Band] = [      # A13 095-109
    (9, True, 10, True, "高"),
    (7.5, True, 9, False, "较好"),
    (6.66, True, 7.5, False, "不低"),
    (5, True, 6.66, False, "偏低"),
    (None, False, 5, False, "明显偏低"),
]


def _attachment(high: Tuple[float, float], mid: float) -> List[_Band]:
    return [(high[0], True, high[1], True, "高"),
            (mid, True, high[0], False, "不低"),
            (1, True, mid, False, "偏低")]


# 附录 A 的固定阈值规则
RULES: Dict[str, List[_Band]] = {}
RULES["002"] = _pct(98, 80, 60)
for _n in range(3, 9):
    RULES["%03d" % _n] = _pct(95, 80, 60)
RULES["009"] = _EMOTION_TOTAL
for _n in range(11, 15):
    RULES["%03d" % _n] = _EMOTION_ITEM
for _n in range(15, 20):
    RULES["%03d" % _n] = _FIVE_LEVEL_3
for _n in (23, 24, 25):
    RULES["%03d" % _n] = _attachment((35, 50), 18)
for _n in (26, 27, 28):
    RULES["%03d" % _n] = _attachment((31, 45), 16)
for _n in (29, 30, 31):
    RULES["%03d" % _n] = _attachment((21, 30), 11)
for _n in range(53, 59):
    RULES["%03d" % _n] = _SELF_CONCEPT
for _n in range(63, 66):
    RULES["%03d" % _n] = _pct(95, 80, 60)
for _n in range(73, 87):
    RULES["%03d" % _n] = _THREE_LEVEL
for _n in range(95, 110):
    RULES["%03d" % _n] = _CAREER_VALUE

# 与报告均分比较（A7、A9、A10）：均分来自 y4_evidence._NORM_CODE
MEAN_CODES = tuple(sorted(y4_evidence._NORM_CODE))

# 附录 A 要求保留原值
RAW_CODES = tuple(["%03d" % n for n in (20, 21, 22)]
                  + ["%03d" % n for n in range(41, 51)]
                  + ["051", "059", "072"]
                  + ["%03d" % n for n in (87, 88, 89)]
                  + ["%03d" % n for n in range(110, 115)])

# 档位型指标（A2 的 010、A6 的 052）
CODE_BANDS: Dict[str, Dict[int, str]] = {
    "010": {1: "明显偏低", 2: "偏低", 3: "不低", 4: "较好", 5: "高"},
    "052": {1: "偏低", 2: "正常", 3: "偏高"},
}

# 报告自带档位：得分项 → 档位项
_CARRIED = dict(y4_evidence._LEVEL_CODE)

# 附录 A 未写出范围的指标：范围取其规则覆盖的区间
_EXTRA_RANGES: Dict[str, Tuple[float, float]] = {}
_EXTRA_RANGES.update({"%03d" % n: (1.0, 10.0) for n in range(73, 87)})
_EXTRA_RANGES.update({"%03d" % n: (0.0, 10.0) for n in range(95, 110)})


def _valid_range(code: str) -> Optional[Tuple[float, float]]:
    return y4_evidence._RANGES.get(code) or _EXTRA_RANGES.get(code)


def _in_band(num: float, band: _Band) -> bool:
    lo, lo_inc, hi, hi_inc, _label = band
    if lo is not None and not (num >= lo if lo_inc else num > lo):
        return False
    if hi is not None and not (num <= hi if hi_inc else num < hi):
        return False
    return True


def _rate_fixed(code: str, num: float) -> Optional[str]:
    for band in RULES[code]:
        if _in_band(num, band):
            return band[4]
    return None


def _rate_mean(num: float, mean: float) -> str:
    # 十进制精确比较：float 会把 3.9 对 4.4 这类边界算错（附录 A：≥ 均分 - 0.5 即不低）
    value, avg, margin = Decimal(str(num)), Decimal(str(mean)), Decimal("0.5")
    if value >= avg + margin:
        return "较好"
    if value >= avg - margin:
        return "不低"
    return "偏低"


def _fmt(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _num(value: Any) -> Optional[float]:
    return y4_evidence._number(value)


def _clean_num(num: Optional[float]):
    if num is None:
        return None
    return int(num) if float(num).is_integer() else num


def _code_band(code: str, value: Any) -> Optional[str]:
    """010 / 052 的取值 → 档位文字；无法识别返回 None。"""
    table = CODE_BANDS[code]
    if isinstance(value, str) and value.strip() in table.values():
        return value.strip()
    num = _num(value)
    if num is None or not float(num).is_integer():
        return None
    return table.get(int(num))


def _entry(code: str, value: Any, rating: str, state: str,
           mean: Optional[float] = None) -> Dict[str, Any]:
    label = y4_evidence._label(code)
    full = str((data_points.POINT_META.get(code) or {}).get("label") or code)
    shown = "缺失" if value is None or value == "" else _fmt(value)
    tail = "，%s" % rating if rating else ""
    if mean is not None:
        tail += "（均分%s）" % _fmt(mean)
    return {
        "code": code,
        "label": label,
        "value": value,
        "rating": rating,
        "mean": mean,
        "state": state,
        "line": "%s %s：%s%s" % (code, full, shown, tail),
        "family_line": "%s：%s%s" % (label, shown, tail),
    }


def _check(code: str, value: Any, mean: Optional[float] = None) -> Dict[str, Any]:
    return _entry(code, value, CHECK, "check", mean)


def _rate_one(code: str, values: Dict[str, Any]) -> Dict[str, Any]:
    raw = values.get(code)

    if code in RAW_CODES:
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return _check(code, raw)
        entry = _entry(code, raw, "", "raw")
        if code == "041":                      # A5：原始数据里有 BMI 等级就一并保留
            grade = values.get("042")
            if isinstance(grade, str) and grade.strip():
                entry["grade"] = grade.strip()
                entry["line"] += "，%s" % grade.strip()
                entry["family_line"] += "，%s" % grade.strip()
        return entry

    if code in CODE_BANDS:
        band = _code_band(code, raw)
        value = _clean_num(_num(raw)) if _num(raw) is not None else raw
        if band is None:
            return _check(code, value)
        entry = _entry(code, value, band, "ok")
        if code == "010":                      # 与 009 按 A2 算出的档位核对
            score = _rate_fixed_value("009", values)
            if score and score != band:
                return _check(code, value)
        return entry

    if code in MEAN_CODES:
        num = _num(raw)
        if num is None:
            return _check(code, raw)
        value = _clean_num(num)
        mean = _num(values.get(y4_evidence._NORM_CODE[code]))
        if mean is None:
            return _check(code, value)
        return _entry(code, value, _rate_mean(num, mean), "ok", _clean_num(mean))

    if code in RULES:
        num = _num(raw)
        if num is None:
            return _check(code, raw)
        value = _clean_num(num)
        limits = _valid_range(code)
        if limits and not (limits[0] <= num <= limits[1]):
            return _check(code, value)
        rating = _rate_fixed(code, num)
        if rating is None:
            return _check(code, value)
        if code == "009":
            carried = _code_band("010", values.get("010"))
            if carried is not None and carried != rating:
                return _check(code, value)
        elif code in _CARRIED:
            carried_text = values.get(_CARRIED[code])
            if isinstance(carried_text, str) and carried_text.strip() \
                    and carried_text.strip() != rating:
                return _check(code, value)
        return _entry(code, value, rating, "ok")

    raise KeyError(code)


def _rate_fixed_value(code: str, values: Dict[str, Any]) -> Optional[str]:
    """按 A2 规则给 009 算档位；缺失或越界返回 None（不参与核对）。"""
    num = _num(values.get(code))
    limits = _valid_range(code)
    if num is None or (limits and not (limits[0] <= num <= limits[1])):
        return None
    return _rate_fixed(code, num)


def applicable_codes() -> List[str]:
    """附录 A 涉及的全部指标编号，按编号排序。"""
    codes = set(RULES) | set(MEAN_CODES) | set(RAW_CODES) | set(CODE_BANDS)
    return sorted(codes)


def rate_all(values: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """附录 A 全部指标的评级：编号 → 评级条目。"""
    values = values or {}
    return {code: _rate_one(code, values) for code in applicable_codes()}
