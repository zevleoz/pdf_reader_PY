"""综合测评报告 124 项基础数据点。

编号 001-124 与 extract.py 的 SCHEMA_124 定义完全一致。
每个数据点维护 (code, label, type) 三元组，并按编号自动归属到分组。

用法：
    >>> from data_points import POINT_META, USER_DATA, v
    >>> USER_DATA['001']  # 读取某个编号的值（由 report_data.json 回填）
    >>> v('001')          # 同上，更短
    >>> get_point('001')  # 读取完整条目 (code/label/type/group/value)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# 分组规则（按编号区间自动判断）
# ---------------------------------------------------------------------------
_GROUP_RULES = (
    (1,   8,   "认知能力"),
    (9,   14,  "情绪稳定性"),
    (15,  19,  "人格"),
    (20,  40,  "依恋关系"),
    (41,  50,  "体质健康"),
    (51,  58,  "自我概念"),
    (59,  62,  "思维模式与自驱力"),
    (63,  65,  "执行功能"),
    (66,  71,  "学习动机与策略"),
    (72,  78,  "职业兴趣"),
    (79,  94,  "能力优势"),
    (95,  124, "职业价值观"),
    (125, 133, "常模平均数"),
)


def _resolve_group(code: str) -> str:
    """根据编号返回所属分组；未知编号归为 '其他'。"""
    try:
        n = int(code)
    except ValueError:
        return "其他"
    for lo, hi, name in _GROUP_RULES:
        if lo <= n <= hi:
            return name
    return "其他"


# ---------------------------------------------------------------------------
# 124 项数据点元数据：code -> {code, label, type, group}
# 严格按 extract.py SCHEMA_124 的 (code, label, type) 三元组顺序定义
# ---------------------------------------------------------------------------
_SCHEMA_124_RAW: list = [
    # 001-008 认知能力
    ("001", "认知能力总得分", "number"),
    ("002", "认知能力百分位", "number"),
    ("003", "认知能力-感知觉百分位", "number"),
    ("004", "认知能力-注意力百分位", "number"),
    ("005", "认知能力-记忆力百分位", "number"),
    ("006", "认知能力-推理能力百分位", "number"),
    ("007", "认知能力-空间能力百分位", "number"),
    ("008", "认知能力-加工速度百分位", "number"),

    # 009-014 情绪稳定性
    ("009", "情绪稳定性总分", "number"),
    ("010", "情绪稳定性结果档位", "string"),
    ("011", "情绪稳定性-自卑自尊得分", "number"),
    ("012", "情绪稳定性-抑郁愉快得分", "number"),
    ("013", "情绪稳定性-焦虑安详得分", "number"),
    ("014", "情绪稳定性-无力感掌控感得分", "number"),

    # 015-019 人格
    ("015", "人格-开放性得分", "number"),
    ("016", "人格-宜人性得分", "number"),
    ("017", "人格-责任心得分", "number"),
    ("018", "人格-外倾性得分", "number"),
    ("019", "人格-神经质得分", "number"),

    # 020-040 依恋关系（3类型 + 9得分 + 9档位）
    ("020", "依恋关系-母亲类型", "string"),
    ("021", "依恋关系-父亲类型", "string"),
    ("022", "依恋关系-同伴类型", "string"),
    ("023", "依恋关系-信任-母亲得分", "number"),
    ("024", "依恋关系-信任-父亲得分", "number"),
    ("025", "依恋关系-信任-同伴得分", "number"),
    ("026", "依恋关系-沟通-母亲得分", "number"),
    ("027", "依恋关系-沟通-父亲得分", "number"),
    ("028", "依恋关系-沟通-同伴得分", "number"),
    ("029", "依恋关系-亲近-母亲得分", "number"),
    ("030", "依恋关系-亲近-父亲得分", "number"),
    ("031", "依恋关系-亲近-同伴得分", "number"),
    ("032", "依恋关系-信任-母亲档位", "string"),
    ("033", "依恋关系-信任-父亲档位", "string"),
    ("034", "依恋关系-信任-同伴档位", "string"),
    ("035", "依恋关系-沟通-母亲档位", "string"),
    ("036", "依恋关系-沟通-父亲档位", "string"),
    ("037", "依恋关系-沟通-同伴档位", "string"),
    ("038", "依恋关系-亲近-母亲档位", "string"),
    ("039", "依恋关系-亲近-父亲档位", "string"),
    ("040", "依恋关系-亲近-同伴档位", "string"),

    # 041-050 体质健康
    ("041", "体质健康-BMI得分", "number"),
    ("042", "体质健康-BMI等级", "string"),
    ("043", "体质健康-身高cm", "number"),
    ("044", "体质健康-体重kg", "number"),
    ("045", "体质健康-饮食习惯得分", "number"),
    ("046", "体质健康-饮食评级", "string"),
    ("047", "体质健康-睡眠习惯得分", "number"),
    ("048", "体质健康-睡眠评级", "string"),
    ("049", "体质健康-运动习惯得分", "number"),
    ("050", "体质健康-运动评级", "string"),
    ("050a", "体质健康-文字描述", "string"),

    # 051-058 自我概念
    ("051", "自我概念整体值", "number"),
    ("052", "自我概念整体档位", "string"),
    ("053", "自我概念-行为表现", "number"),
    ("054", "自我概念-能力与学校表现", "number"),
    ("055", "自我概念-躯体外貌", "number"),
    ("056", "自我概念-情绪状态", "number"),
    ("057", "自我概念-合群", "number"),
    ("058", "自我概念-幸福与满足", "number"),

    # 059-062 思维模式与自驱力
    ("059", "思维模式结果", "number"),
    ("060", "自驱力-自主性", "number"),
    ("061", "自驱力-胜任感", "number"),
    ("062", "自驱力-归属感", "number"),

    # 063-065 执行功能
    ("063", "执行功能-抑制控制百分位", "number"),
    ("064", "执行功能-工作记忆百分位", "number"),
    ("065", "执行功能-认知灵活性百分位", "number"),

    # 066-071 学习动机与策略
    ("066", "学习动机-深层动机", "number"),
    ("067", "学习动机-表面动机", "number"),
    ("068", "学习动机-自我效能感", "number"),
    ("069", "学习方法与策略-学习深层方法与策略", "number"),
    ("070", "学习方法与策略-学习表面方法与策略", "number"),
    ("071", "学习方法与策略-学习自我调节", "number"),

    # 072-078 职业兴趣
    ("072", "职业兴趣代码", "string"),
    ("073", "职业兴趣-现实型", "number"),
    ("074", "职业兴趣-研究型", "number"),
    ("075", "职业兴趣-艺术型", "number"),
    ("076", "职业兴趣-社会型", "number"),
    ("077", "职业兴趣-事业型", "number"),
    ("078", "职业兴趣-常规型", "number"),

    # 079-094 能力优势（8得分 + 8排序）
    ("079", "能力优势-语言能力", "number"),
    ("080", "能力优势-逻辑数学能力", "number"),
    ("081", "能力优势-音乐能力", "number"),
    ("082", "能力优势-空间能力", "number"),
    ("083", "能力优势-身体运动能力", "number"),
    ("084", "能力优势-人际关系能力", "number"),
    ("085", "能力优势-内省能力", "number"),
    ("086", "能力优势-自然能力", "number"),
    ("087", "能力优势排序1", "string"),
    ("088", "能力优势排序2", "string"),
    ("089", "能力优势排序3", "string"),
    ("090", "能力优势排序4", "string"),
    ("091", "能力优势排序5", "string"),
    ("092", "能力优势排序6", "string"),
    ("093", "能力优势排序7", "string"),
    ("094", "能力优势排序8", "string"),

    # 095-124 职业价值观（15得分 + 15排序，共30项）
    ("095", "职业价值观-创造发明", "number"),
    ("096", "职业价值观-独立自主", "number"),
    ("097", "职业价值观-美的追求", "number"),
    ("098", "职业价值观-智力激发", "number"),
    ("099", "职业价值观-利他助人", "number"),
    ("100", "职业价值观-成就感", "number"),
    ("101", "职业价值观-管理权力", "number"),
    ("102", "职业价值观-工作环境", "number"),
    ("103", "职业价值观-同事关系", "number"),
    ("104", "职业价值观-上司关系", "number"),
    ("105", "职业价值观-多样变化", "number"),
    ("106", "职业价值观-经济报酬", "number"),
    ("107", "职业价值观-安全稳定", "number"),
    ("108", "职业价值观-声望地位", "number"),
    ("109", "职业价值观-生活方式", "number"),
    ("110", "职业价值观排序1", "string"),
    ("111", "职业价值观排序2", "string"),
    ("112", "职业价值观排序3", "string"),
    ("113", "职业价值观排序4", "string"),
    ("114", "职业价值观排序5", "string"),
    ("115", "职业价值观排序6", "string"),
    ("116", "职业价值观排序7", "string"),
    ("117", "职业价值观排序8", "string"),
    ("118", "职业价值观排序9", "string"),
    ("119", "职业价值观排序10", "string"),
    ("120", "职业价值观排序11", "string"),
    ("121", "职业价值观排序12", "string"),
    ("122", "职业价值观排序13", "string"),
    ("123", "职业价值观排序14", "string"),
    ("124", "职业价值观排序15", "string"),

    # 125-133 常模平均数项（PDF中直接提供的同龄常模均值）
    ("125", "自驱力-自主性常模平均数", "number"),
    ("126", "自驱力-胜任感常模平均数", "number"),
    ("127", "自驱力-归属感常模平均数", "number"),
    ("128", "学习动机-深层动机常模平均数", "number"),
    ("129", "学习动机-表面动机常模平均数", "number"),
    ("130", "学习动机-自我效能感常模平均数", "number"),
    ("131", "学习方法与策略-学习深层方法与策略常模平均数", "number"),
    ("132", "学习方法与策略-学习表面方法与策略常模平均数", "number"),
    ("133", "学习方法与策略-学习自我调节常模平均数", "number"),
]


def _build_point_meta() -> Dict[str, Dict[str, Any]]:
    meta: Dict[str, Dict[str, Any]] = {}
    for code, label, type_ in _SCHEMA_124_RAW:
        meta[code] = {
            "code": code,
            "label": label,
            "type": type_,
            "group": _resolve_group(code),
        }
    return meta


POINT_META: Dict[str, Dict[str, Any]] = _build_point_meta()


# ---------------------------------------------------------------------------
# 用户数据值：编号 -> 值（初始为空字符串，由 apply_report_data 回填）
# ---------------------------------------------------------------------------
def _build_user_data() -> Dict[str, Any]:
    return {code: "" for code in POINT_META}


USER_DATA: Dict[str, Any] = _build_user_data()


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------
def v(code: str) -> Any:
    """读取某个编号的值。"""
    return USER_DATA.get(code, "")


def get_point(code: str) -> Dict[str, Any]:
    """读取某个编号的完整条目（元数据 + 当前值）。"""
    meta = POINT_META.get(code, {})
    return {**meta, "value": USER_DATA.get(code, "")}


def student_meta(report_data_path: Optional[Path] = None) -> Dict[str, Any]:
    """返回 report_data.json 中的学生信息（存在则返回，不存在返回 {}）。"""
    path = report_data_path or (Path(__file__).resolve().parent / "data" / "report_data.json")
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data.get("student", {}) if isinstance(data, dict) else {}


def apply_report_data(report_data_path: Optional[Path] = None) -> Dict[str, Any]:
    """从 data/report_data.json 的 schema_124 回填 USER_DATA。

    规则：遍历 schema_124 中每一项，按 code 写入 USER_DATA[code]；
    若 value 为 null/None，则写为空字符串。
    """
    if report_data_path is None:
        report_data_path = (
            Path(__file__).resolve().parent / "data" / "report_data.json"
        )
    result: Dict[str, Any] = {
        "path": str(report_data_path),
        "total_items": 0,
        "applied": 0,
        "exists": report_data_path.exists(),
    }
    if not report_data_path.exists():
        return result

    try:
        with open(report_data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        result["error"] = f"parse_error: {exc}"
        return result

    if not isinstance(data, dict):
        result["error"] = "not_object"
        return result

    schema_124 = data.get("schema_124") or []
    if not isinstance(schema_124, list):
        result["error"] = "schema_124_not_list"
        return result

    applied = 0
    for item in schema_124:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", "")).strip()
        if not code or code not in USER_DATA:
            continue
        value = item.get("value")
        if value is None:
            USER_DATA[code] = ""
        else:
            USER_DATA[code] = value
        applied += 1

    result["total_items"] = len(schema_124)
    result["applied"] = applied
    return result


# ---------------------------------------------------------------------------
# 同龄平均数据：label -> mean 值（从 clean_report_data.json 加载）
# ---------------------------------------------------------------------------
MEAN_DATA: Dict[str, Any] = {}


def load_mean_data(clean_data_path: Optional[Path] = None) -> Dict[str, Any]:
    """从 clean_report_data.json 加载同龄平均数据，按 label 索引。"""
    if clean_data_path is None:
        clean_data_path = (
            Path(__file__).resolve().parent / "data" / "clean_report_data.json"
        )
    result = {
        "path": str(clean_data_path),
        "loaded": 0,
        "exists": clean_data_path.exists(),
    }
    if not clean_data_path.exists():
        return result
    try:
        with open(clean_data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        result["error"] = f"parse_error: {exc}"
        return result

    items = data.get("items", []) if isinstance(data, dict) else []
    loaded = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        mean = item.get("mean")
        if label and mean is not None:
            MEAN_DATA[label] = mean
            loaded += 1
    result["loaded"] = loaded
    return result


def mean_val(label: str, default: Any = None) -> Any:
    """根据 label 读取同龄平均值，不存在返回 default。"""
    return MEAN_DATA.get(label, default)


# ---------------------------------------------------------------------------
# 模块加载时自动回填（如 report_data.json 存在）
# ---------------------------------------------------------------------------
try:
    apply_report_data()
except Exception:
    pass

try:
    load_mean_data()
except Exception:
    pass
