"""Y4 → M1 证据条目（只用档位，不经过 AI）。

规则来源：
- 报告自带档位字段（如 023 信任得分对应 032 信任档位）优先；
- 其余用 ``evaluation_rules.derive_evaluation``；
- M1 专属规则（职业价值观分档、越界/缺常模 → 无法判读）只放在本文件，
  ``evaluation_rules.py`` 是红线，不改。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.exc import OperationalError

import data_points
import db as _db
import evaluation_rules
from growth_talk import y4_snapshot
from m1.kb import load_kb

GROUP = "Y4"
UNREADABLE = "无法判读"

# 得分项 → 报告自带档位项
_LEVEL_CODE = {"009": "010", "051": "052",
               **{f"{n:03d}": f"{n + 9:03d}" for n in range(23, 32)}}

# 得分项 → 常模平均数项（060-062↔125-127，066-068↔128-130，069-071↔131-133）
_NORM_CODE: Dict[str, str] = {}
_NORM_CODE.update({f"{n:03d}": f"{n + 65:03d}" for n in range(60, 63)})
_NORM_CODE.update({f"{n:03d}": f"{n + 62:03d}" for n in range(66, 72)})

# 框架 p.19 的有效取值范围（区间内才判读）
_RANGES: Dict[str, Tuple[float, float]] = {}
_RANGES.update({f"{n:03d}": (0.0, 100.0) for n in range(2, 9)})      # 认知能力百分位
_RANGES["009"] = (0.0, 60.0)                                        # 情绪稳定性总分
_RANGES.update({f"{n:03d}": (0.0, 15.0) for n in range(11, 15)})     # 情绪稳定性分项
_RANGES.update({f"{n:03d}": (1.0, 5.0) for n in range(15, 20)})      # 人格
_RANGES.update({f"{n:03d}": (1.0, 50.0) for n in (23, 24, 25)})      # 依恋-信任
_RANGES.update({f"{n:03d}": (1.0, 45.0) for n in (26, 27, 28)})      # 依恋-沟通
_RANGES.update({f"{n:03d}": (1.0, 30.0) for n in (29, 30, 31)})      # 依恋-亲近
_RANGES.update({f"{n:03d}": (0.0, 10.0) for n in range(51, 59)})     # 自我概念
_RANGES.update({f"{n:03d}": (0.0, 100.0) for n in range(63, 66)})    # 执行功能百分位

_ATTACHMENT_TYPE = {"020", "021", "022"}

# 报告里呈现的指标名（框架 Appendix 的写法，不含原始分）
_DISPLAY_LABELS = {
    "004": "认知能力—注意力",
    "011": "自卑/自尊",
    "012": "抑郁/愉快",
    "013": "焦虑/安详",
    "014": "无力感/掌控感",
    "016": "宜人性",
    "017": "责任心",
    "019": "神经质",
    "022": "依恋—同伴类型",
    "023": "依恋—母亲信任",
    "025": "依恋—同伴信任",
    "026": "依恋—母亲沟通",
    "027": "父亲沟通",
    "028": "同伴沟通",
    "030": "同伴亲近",
    "053": "自我概念—行为表现",
    "054": "自我概念—能力与学校表现",
    "056": "自我概念—情绪状态",
    "060": "自驱力—自主性",
    "061": "自驱力—胜任感",
    "062": "自驱力—归属感",
    "063": "执行功能—抑制控制",
    "065": "认知灵活性",
    "068": "学习自我效能感",
    "071": "学习方法—学习自我调节",
    "079": "能力优势—语言能力",
    "084": "能力优势—人际关系能力",
    "085": "能力优势—内省能力",
}


def _schema_items(report) -> List[Dict[str, Any]]:
    raw = getattr(report, "data_json", None)
    if isinstance(raw, dict):
        payload = raw
    else:
        try:
            payload = json.loads(raw or "{}")
        except (TypeError, ValueError):
            payload = {}
    items = payload.get("schema_124") if isinstance(payload, dict) else None
    return items if isinstance(items, list) else []


def _values(report) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    for item in _schema_items(report):
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", "")).strip()
        if code:
            values[code] = item.get("value")
    return values


def _number(value) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _label(code: str) -> str:
    if code in _DISPLAY_LABELS:
        return _DISPLAY_LABELS[code]
    return str((data_points.POINT_META.get(code) or {}).get("label") or code)


def _career_value_band(num: float) -> str:
    """职业价值观 095-109：框架给分档，Y4 不存（spec §8a Gap 1）。"""
    if num >= 9:
        return "高"
    if num >= 7.5:
        return "较好"
    if num >= 6.66:
        return "不低"
    if num >= 5:
        return "偏低"
    return "明显偏低"


def band_for(code: str, values: Dict[str, Any]) -> str:
    """单个指标的有效档位；无法判读时返回「无法判读」。"""
    code = str(code)
    raw = values.get(code)

    if code in _ATTACHMENT_TYPE:
        text = raw.strip() if isinstance(raw, str) else ""
        return text or UNREADABLE

    level_code = _LEVEL_CODE.get(code)
    level = values.get(level_code) if level_code else None
    if isinstance(level, str) and level.strip():
        return level.strip()

    num = _number(raw)
    if num is None:
        return UNREADABLE

    if code.isdigit() and 95 <= int(code) <= 109:
        return _career_value_band(num)

    limits = _RANGES.get(code)
    if limits and not (limits[0] <= num <= limits[1]):
        return UNREADABLE

    label = str((data_points.POINT_META.get(code) or {}).get("label") or "")

    norm_code = _NORM_CODE.get(code)
    if norm_code:
        norm = _number(values.get(norm_code))
        if norm is None:
            return UNREADABLE
        band, _note = evaluation_rules.derive_evaluation(code, label, raw, norm)
        return band or UNREADABLE

    band, _note = evaluation_rules.derive_evaluation(code, label, raw)
    return band or UNREADABLE


def _used_codes() -> Dict[str, List[str]]:
    """指标编号 → 引用它的能力编号（按知识库顺序）。"""
    used: Dict[str, List[str]] = {}
    for ability in load_kb().get("abilities") or []:
        for code in ability.get("indicators") or []:
            used.setdefault(str(code), []).append(ability.get("code"))
    return used


def _raw_value(code: str, values: Dict[str, Any]):
    raw = values.get(code)
    if code in _ATTACHMENT_TYPE:
        return raw
    num = _number(raw)
    if num is None:
        return raw
    return int(num) if num.is_integer() else num


def _six_am_summary(report) -> Optional[Dict[str, Any]]:
    """同一报告的最新 6AM 档案摘要；与 insights._six_am_pick_profile 的默认分支一致。"""
    try:
        record = _db.get_latest_six_am_profile(report.id)
    except OperationalError:
        # 6AM 是选配来源：精简库（如只建部分表的测试库）里没有该表时视为无档案
        return None
    if not record:
        return None
    try:
        profile = json.loads(record.get("profile_json") or "{}")
    except (TypeError, ValueError):
        profile = {}
    dimensions = profile.get("dimensions") if isinstance(profile, dict) else None
    states = {
        dim: str((rec or {}).get("state") or "")
        for dim, rec in (dimensions or {}).items()
        if isinstance(rec, dict)
    }
    return {
        "profile_id": record.get("id"),
        "report_id": record.get("report_id"),
        "version": record.get("version"),
        "created_at": record.get("created_at"),
        "group": GROUP,
        "label": "6 A.M. 档案 v%s" % record.get("version"),
        "note": "由 Y4 衍生，只随 Y4 一起参考，不单独计为证据",
        "states": states,
    }


def build_y4_evidence(student_id: int) -> Dict[str, Any]:
    """学生最新完整 Y4 → M1 证据条目；没有完整报告时 complete=False 且无条目。"""
    report = y4_snapshot.latest_complete_y4(student_id)
    if report is None:
        return {
            "report_id": None,
            "date": None,
            "items": [],
            "six_am": None,
            "complete": False,
        }

    values = _values(report)
    used = _used_codes()
    report_date = getattr(report, "report_date", None)
    if hasattr(report_date, "isoformat"):
        report_date = report_date.isoformat()

    items = []
    for code in sorted(used, key=lambda c: (int(c) if c.isdigit() else 999, c)):
        band = band_for(code, values)
        items.append({
            "id": "y4-%s" % code,
            "source": "y4",
            "source_ref": "report:%s" % report.id,
            "date": report_date,
            "kind": "indirect",
            "group": GROUP,
            "text": "%s：%s" % (_label(code), band),
            "quote": "",
            "abilities": list(used[code]),
            "band": band,
            "raw": _raw_value(code, values),
        })

    return {
        "report_id": report.id,
        "date": report_date,
        "items": items,
        "six_am": _six_am_summary(report),
        "complete": True,
    }
