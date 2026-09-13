"""有效评价推导逻辑 — 复用现有档位字段 + 依据官方阈值标准推导。

纯数据加工模块：不导入 Flask，不触发 AI，不写库，不读 PDF。
供 Prompt Lab 展示与下载复用。
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple

# 有效评价词汇选项（下拉用），用户指定统一语言
EVAL_OPTIONS: List[str] = [
    "高", "较好", "不低", "偏低", "明显偏低", "严重偏低",
    "需关注", "需特殊关注", "相对健康", "正常",
]

# 档位类 label 关键词
_LEVEL_KEYWORDS = ("档位", "评级", "等级", "结果")

# Y4 四维
_DIM_ORDER = ["心力", "精力", "学习力", "生涯力"]
_DIM_LABELS = {
    "心力": "心力（情绪与动力系统）",
    "精力": "精力（精力管理与身体健康系统）",
    "学习力": "学习力（学习系统）",
    "生涯力": "生涯力（专业与职业发展系统）",
}


def _is_level_item(item: Dict[str, Any]) -> bool:
    label = item.get("label", "") or ""
    return any(k in label for k in _LEVEL_KEYWORDS)


def is_hidden_raw(item: Dict[str, Any]) -> bool:
    """是否在输出中隐藏 raw data（只保留排序）。

    职业价值观 095-109 是得分，已有 110-124 排序项，得分冗余 → 隐藏。
    """
    label = item.get("label", "") or ""
    if "职业价值观" in label and "排序" not in label:
        return True
    return False


def _base_label(label: str) -> str:
    for suffix in ("结果档位", "得分", "总分", "档位", "评级", "等级", "结果"):
        if label.endswith(suffix):
            return label[: -len(suffix)]
    return label


def dimension_of(item: Dict[str, Any]) -> str:
    """Y4 四维归类。label 关键词为主，source_pdf 兜底。"""
    label = item.get("label", "") or ""
    # 生涯力优先判断能力优势（避免"身体运动能力"被"运动"误归精力）
    if any(k in label for k in ("能力优势", "霍兰德", "职业", "多元智能", "价值观", "生涯")):
        return "生涯力"
    if any(k in label for k in ("体质", "精力", "睡眠", "饮食", "BMI", "身高", "体重")):
        return "精力"
    if any(k in label for k in ("情绪", "自尊", "自我概念", "依恋", "人格", "内驱", "自驱")):
        return "心力"
    if any(k in label for k in ("认知", "执行", "记忆", "注意", "推理", "动机", "学习方法", "策略", "自我效能", "工作记忆")):
        return "学习力"
    # 运动习惯/睡眠习惯归精力（不含"能力优势"）
    if any(k in label for k in ("运动", "睡眠")):
        return "精力"
    src = item.get("source_pdf", "") or ""
    if src == "A2":
        return "心力"
    if src == "B4":
        return "学习力"
    if src == "B3":
        return "学习力"
    if src == "B6":
        return "生涯力"
    return "学习力"


def _to_number(val) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _code_int(code) -> int:
    digits = ""
    for ch in str(code):
        if ch.isdigit():
            digits += ch
        else:
            break
    try:
        return int(digits) if digits else -1
    except ValueError:
        return -1


# ── 官方阈值规则（按 code / label 匹配）─────────────────────────

def _rule_cognitive_percentile(num: float, code: int) -> Optional[str]:
    """002 与 003-008 认知能力百分位。002 用 ≥98 高；003-008 用 ≥95 高。"""
    if code == 2:
        if num >= 98:
            return "高"
        if num >= 80:
            return "较好"
        if num >= 60:
            return "不低"
        return "偏低"
    # 003-008
    if num >= 95:
        return "高"
    if num >= 80:
        return "较好"
    if num >= 60:
        return "不低"
    return "偏低"


def _rule_emotion_total(num: float) -> Optional[str]:
    """009 情绪稳定性总分。"""
    if num >= 49:
        return "高"
    if num >= 37:
        return "较好"
    if num >= 25:
        return "不低"
    if num >= 13:
        return "偏低"
    return "明显偏低"


def _rule_emotion_subitem(num: float) -> Optional[str]:
    """011-014 情绪稳定性四分项（自尊/抑郁愉快/焦虑/无力感）。"""
    if num < 5:
        return "需特殊关注"
    if num <= 10:
        return "需关注"
    return "相对健康"


def _rule_personality(num: float) -> Optional[str]:
    """015-019 人格五项。统一标准。"""
    if num > 4.5:
        return "高"
    if num >= 3.5:
        return "较好"
    if num >= 3:
        return "不低"
    if num >= 2.5:
        return "偏低"
    if num >= 1.5:
        return "明显偏低"
    return "严重偏低"


def _rule_attachment_trust(num: float) -> Optional[str]:
    """023-025 依恋-信任得分。"""
    if num >= 35:
        return "高"
    if num >= 18:
        return "不低"
    return "偏低"


def _rule_attachment_comm(num: float) -> Optional[str]:
    """026-028 依恋-沟通得分。"""
    if num >= 31:
        return "高"
    if num >= 16:
        return "不低"
    return "偏低"


def _rule_attachment_close(num: float) -> Optional[str]:
    """029-031 依恋-亲近得分。"""
    if num >= 21:
        return "高"
    if num >= 11:
        return "不低"
    return "偏低"


def _rule_self_concept_subitem(num: float) -> Optional[str]:
    """053-058 自我概念细分。"""
    if num >= 8:
        return "高"
    if num >= 6:
        return "较好"
    if num >= 4:
        return "不低"
    if num >= 2:
        return "偏低"
    return "严重偏低"


def _rule_executive(num: float) -> Optional[str]:
    """063-065 执行功能百分位。"""
    if num >= 95:
        return "高"
    if num >= 80:
        return "较好"
    if num >= 60:
        return "不低"
    return "偏低"


def _rule_vocational_interest(num: float) -> Optional[str]:
    """073-078 职业兴趣（霍兰德）。"""
    if num >= 7:
        return "高"
    if num >= 4:
        return "不低"
    return "偏低"


def _rule_ability_advantage(num: float) -> Optional[str]:
    """079-086 能力优势（多元智能）。"""
    if num >= 7:
        return "高"
    if num >= 4:
        return "不低"
    return "偏低"


def _rule_norm_referenced(num: float, norm: Optional[float]) -> Optional[str]:
    """自驱力(060-062)/学习动机(066-068)/学习方法(069-071)：参照常模均分。

    ≥ 均分+0.5 → 较好；≥ 均分-0.5 且 < 均分+0.5 → 不低；< 均分-0.5 → 偏低
    """
    if norm is None:
        return None
    if num >= norm + 0.5:
        return "较好"
    if num >= norm - 0.5:
        return "不低"
    return "偏低"


def derive_evaluation(code: str, label: str, raw_value,
                      norm_value: Optional[float] = None) -> Tuple[Optional[str], Optional[str]]:
    """对无档位字段的得分项，依据官方阈值推导有效评价。

    返回 (eval_value, rule_note)。无匹配规则返回 (None, None)。
    """
    num = _to_number(raw_value)
    c = _code_int(code)
    if num is None:
        return None, None

    # 认知能力百分位 002-008
    if c == 2 and "百分位" in label:
        return _rule_cognitive_percentile(num, c), "认知百分位≥98高"
    if 3 <= c <= 8 and "认知能力" in label and "百分位" in label:
        return _rule_cognitive_percentile(num, c), "认知百分位≥95高"

    # 009 情绪稳定性总分
    if c == 9 and "情绪稳定性" in label and ("总分" in label or "总值" in label):
        return _rule_emotion_total(num), "情绪稳定性≥49高"

    # 011-014 情绪稳定性四分项
    if 11 <= c <= 14 and "情绪稳定性" in label and "得分" in label:
        return _rule_emotion_subitem(num), "情绪分项<5需特殊关注"

    # 015-019 人格
    if 15 <= c <= 19 and "人格" in label and "得分" in label:
        return _rule_personality(num), "人格>4.5高"

    # 023-025 依恋-信任
    if 23 <= c <= 25 and "依恋" in label and "信任" in label and "得分" in label:
        return _rule_attachment_trust(num), "信任≥35高"
    # 026-028 依恋-沟通
    if 26 <= c <= 28 and "依恋" in label and "沟通" in label and "得分" in label:
        return _rule_attachment_comm(num), "沟通≥31高"
    # 029-031 依恋-亲近
    if 29 <= c <= 31 and "依恋" in label and "亲近" in label and "得分" in label:
        return _rule_attachment_close(num), "亲近≥21高"

    # 053-058 自我概念细分
    if 53 <= c <= 58 and "自我概念" in label:
        return _rule_self_concept_subitem(num), "自我概念细分≥8高"

    # 060-062 自驱力（参照常模 125-127）
    if 60 <= c <= 62 and "自驱力" in label:
        ev = _rule_norm_referenced(num, norm_value)
        return (ev, f"自驱力≥均分+0.5较好(均分{norm_value})") if ev else (None, None)

    # 063-065 执行功能百分位
    if 63 <= c <= 65 and "执行功能" in label and "百分位" in label:
        return _rule_executive(num), "执行功能≥95高"

    # 066-068 学习动机（参照常模 128-130）
    if 66 <= c <= 68 and "学习动机" in label:
        ev = _rule_norm_referenced(num, norm_value)
        return (ev, f"学习动机≥均分+0.5较好(均分{norm_value})") if ev else (None, None)

    # 069-071 学习方法与策略（参照常模 131-133）
    if 69 <= c <= 71 and "学习方法" in label:
        ev = _rule_norm_referenced(num, norm_value)
        return (ev, f"学习方法≥均分+0.5较好(均分{norm_value})") if ev else (None, None)

    # 073-078 职业兴趣（霍兰德）
    if 73 <= c <= 78 and "职业兴趣" in label:
        return _rule_vocational_interest(num), "职业兴趣≥7高"

    # 079-086 能力优势（多元智能）
    if 79 <= c <= 86 and "能力优势" in label and "排序" not in label:
        return _rule_ability_advantage(num), "能力优势≥7高"

    return None, None


def _find_norm(schema_items: List[Dict[str, Any]], score_code: int) -> Optional[float]:
    """为自驱力/学习动机/学习方法得分项找对应常模均分。

    060-062 ↔ 125-127；066-068 ↔ 128-130；069-071 ↔ 131-133。
    """
    norm_map = {60: 125, 61: 126, 62: 127, 66: 128, 67: 129, 68: 130, 69: 131, 70: 132, 71: 133}
    target = norm_map.get(score_code)
    if not target:
        return None
    for it in schema_items:
        if _code_int(it.get("code", "")) == target:
            return _to_number(it.get("value"))
    return None


def pair_score_with_level(schema_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把得分项与档位项配对。返回得分项列表，附加 eval 字段。

    保留所有有值项，以及有规则定义但值为空的项（如体质健康、学习方法）。
    E4 框架 source of truth 引用的指标（如自我概念整体值）即使为空也保留。
    没有配对得分项的孤儿档位项（如思维模式结果）作为独立条目保留。
    """
    level_index: Dict[str, Dict[str, Any]] = {}
    for it in schema_items:
        if not _is_level_item(it):
            continue
        base = _base_label(it.get("label", "") or "")
        if base:
            level_index.setdefault(base, it)

    # 收集得分项的 base label，用于识别孤儿档位项
    score_bases = {
        _base_label(it.get("label", "") or "")
        for it in schema_items if not _is_level_item(it)
    }

    results: List[Dict[str, Any]] = []

    def _make_entry(it: Dict[str, Any]) -> Dict[str, Any]:
        base = _base_label(it.get("label", "") or "")
        level_item = level_index.get(base)
        entry = {
            "code": it.get("code", ""),
            "label": it.get("label", ""),
            "raw_value": it.get("value", ""),
            "unit": it.get("unit", "") or "",
            "source_pdf": it.get("source_pdf", "") or "",
            "eval_value": None,
            "eval_source": "待判定",
            "level_code": None,
            "level_label": None,
            "dimension": dimension_of(it),
        }
        if level_item and level_item.get("value"):
            entry["level_code"] = level_item.get("code")
            entry["level_label"] = level_item.get("label")
        return entry

    for it in schema_items:
        if is_hidden_raw(it):
            continue
        label = it.get("label", "") or ""
        if _is_level_item(it):
            # 孤儿档位项：没有对应得分项（如思维模式结果）→ 作为独立条目保留
            base = _base_label(label)
            if base and base not in score_bases:
                results.append(_make_entry(it))
            continue
        # 保留条件：有值 OR 有对应规则 OR 体质健康类 OR E4 框架引用
        has_value = bool(it.get("value"))
        c = _code_int(it.get("code", ""))
        has_rule = _has_rule_for_code(c, label)
        is_body_health = any(k in label for k in ("体质健康", "BMI", "饮食", "睡眠", "运动"))
        in_framework = _norm_framework_label(label) in FRAMEWORK_LABEL_KEYS
        if not has_value and not has_rule and not is_body_health and not in_framework:
            continue
        results.append(_make_entry(it))
    return results


def _has_rule_for_code(code: int, label: str = "") -> bool:
    """判断某个 code 是否有 source-of-truth 规则可推导 eval。"""
    if 2 <= code <= 8 and "百分位" in label:
        return True
    if code == 9 and "情绪稳定性" in label and ("总分" in label or "总值" in label):
        return True
    if 11 <= code <= 14 and "情绪稳定性" in label and "得分" in label:
        return True
    if 15 <= code <= 19 and "人格" in label and "得分" in label:
        return True
    if 23 <= code <= 25 and "依恋" in label and "信任" in label and "得分" in label:
        return True
    if 26 <= code <= 28 and "依恋" in label and "沟通" in label and "得分" in label:
        return True
    if 29 <= code <= 31 and "依恋" in label and "亲近" in label and "得分" in label:
        return True
    if 53 <= code <= 58 and "自我概念" in label:
        return True
    if 60 <= code <= 62 and "自驱力" in label:
        return True
    if 63 <= code <= 65 and "执行功能" in label and "百分位" in label:
        return True
    if 66 <= code <= 68 and "学习动机" in label:
        return True
    if 69 <= code <= 71 and "学习方法" in label:
        return True
    if 73 <= code <= 78 and "职业兴趣" in label:
        return True
    if 79 <= code <= 86 and "能力优势" in label and "排序" not in label:
        return True
    return False


def is_order_item(item: Dict[str, Any]) -> bool:
    """排序项：能力优势排序(087-094)、职业价值观排序(110-124)。
    raw value 本身即结论（如"独立自主"排第1），不参与档位评价。
    """
    label = item.get("label", "") or ""
    if "排序" in label:
        return True
    return False


def is_norm_item(item: Dict[str, Any]) -> bool:
    """常模参照值(125-133)：非学生数据，是参照标准，不参与评价。"""
    label = item.get("label", "") or ""
    if "常模" in label:
        return True
    return False


def build_evaluation_view(schema_items: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """主入口：构建有效评价视图。

    优先级：
    1. 用户 source-of-truth 规则推导（最高优先）
    2. 排序项（raw 值本身即结论）
    3. PDF 档位字段（仅当没有规则时使用）
    4. 无 eval（保留 raw data）
    """
    items = pair_score_with_level(schema_items)
    summary = {"total": len(items), "with_eval": 0, "derived": 0, "pending": 0, "order": 0, "norm": 0, "level_fallback": 0}
    for entry in items:
        # 排序项：本身就是结论
        if is_order_item(entry):
            entry["eval_value"] = entry["raw_value"]
            entry["eval_source"] = "原始排序"
            summary["order"] += 1
            summary["with_eval"] += 1
            continue
        # 常模项：参照值，不参与评价
        if is_norm_item(entry):
            entry["eval_value"] = None
            entry["eval_source"] = "参照值"
            summary["norm"] += 1
            continue
        c = _code_int(entry["code"])
        norm = _find_norm(schema_items, c)
        # 优先级 1：规则推导（source of truth）
        ev, note = derive_evaluation(
            entry["code"], entry["label"], entry["raw_value"], norm
        )
        if ev:
            entry["eval_value"] = ev
            entry["eval_source"] = "规则推导"
            entry["rule_note"] = note
            summary["derived"] += 1
            summary["with_eval"] += 1
        # 优先级 2：PDF 档位字段 fallback（仅当没有规则时使用）
        elif entry.get("level_code") and entry.get("level_label"):
            # 找到对应的档位 item
            base = _base_label(entry["label"])
            level_index: Dict[str, Dict[str, Any]] = {}
            for it in schema_items:
                if not _is_level_item(it):
                    continue
                b = _base_label(it.get("label", "") or "")
                if b:
                    level_index.setdefault(b, it)
            level_item = level_index.get(base)
            if level_item and level_item.get("value"):
                entry["eval_value"] = level_item.get("value")
                entry["eval_source"] = "档位字段"
                summary["level_fallback"] += 1
                summary["with_eval"] += 1
            else:
                summary["pending"] += 1
        else:
            summary["pending"] += 1
    return items, summary


def sort_key_code(code: str) -> Tuple[int, str]:
    digits = ""
    for ch in str(code):
        if ch.isdigit():
            digits += ch
        else:
            break
    try:
        n = int(digits) if digits else 9999
    except ValueError:
        n = 9999
    return (n, str(code))


# ── E4 评估框架映射 ──────────────────────────────────────────

E4_DIMS = ["E1", "E2", "E3", "E4"]
E4_LABELS = {
    "E1": "E1 · Emotion（情绪）",
    "E2": "E2 · Energy（精力管理）",
    "E3": "E3 · Engine（引擎）",
    "E4": "E4 · Engagement（参与投入）",
}

# E4 子类别
E4_SUBCATS = {
    "E1": ["学习信心", "学校融入度", "亲子依恋", "焦虑状态", "自我概念"],
    "E2": ["睡眠", "饮食", "运动"],
    "E3": ["大脑引擎", "动力引擎"],
    "E4": ["学习策略", "多元智能与自我认知", "职业兴趣与价值观"],
}

# E4 归属不做任何推断：由用户在界面逐条指认，存 e4_mapping 表（见 db.py）。
# e4_classify 只查表，未指认返回 []，输出时归入 OTHER_VARIABLES。
# 返回列表因为一个 Y4 指标可同时映射到多个 E4 维度。

def e4_classify(item: Dict[str, Any],
                mapping: Optional[Dict[str, List[Dict[str, str]]]] = None
                ) -> List[Dict[str, str]]:
    """从用户指认的 mapping 查该指标映射到的所有 E4 维度。

    mapping 形如 {"015": [{"e4_dim": "E3", "e4_sub": "动力引擎"}, {"e4_dim": "E1", "e4_sub": ""}]}。
    code 兼容 "015" / "15" 两种形态。
    返回 [{"e4_dim": ..., "e4_sub": ...}, ...]，未指认返回 []。
    """
    if not mapping:
        return []
    code = str(item.get("code", ""))
    m = mapping.get(code)
    if not m:
        digits = "".join(ch for ch in code if ch.isdigit())
        m = mapping.get(str(int(digits))) if digits else None
    return m or []


# ── E4 框架 source of truth（用户确认的 维度→评估问题→指标 结构）────────
# 指标引用两种形态：
#   {"label": "认知能力-推理能力"}        → 按 label 匹配（自动去掉"得分/百分位"后缀）
#   {"order_value": "安全稳定"}           → 匹配排序项的值，显示"第N位/共M"

E4_FRAMEWORK: List[Dict[str, Any]] = [
    {
        "dim": "E1",
        "groups": [
            {"q": "学生对于学习的自信程度如何？（是否对于取得好的成绩有自信？）",
             "indicators": [{"label": "学习动机-自我效能感"}, {"label": "自我概念-能力与学校表现"}]},
            {"q": "学校环境对学生是否产生了负面影响？",
             "indicators": [{"label": "学习方法与策略-学习自我调节"}, {"label": "自我概念-合群"},
                            {"label": "依恋关系-信任-同伴"}, {"label": "依恋关系-沟通-同伴"},
                            {"label": "依恋关系-亲近-同伴"}]},
            {"q": "亲子关系是否对孩子的学业情绪有潜在影响？",
             "indicators": [{"label": "依恋关系-信任-母亲"}, {"label": "依恋关系-信任-父亲"},
                            {"label": "依恋关系-沟通-母亲"}, {"label": "依恋关系-沟通-父亲"},
                            {"label": "依恋关系-亲近-母亲"}, {"label": "依恋关系-亲近-父亲"}]},
            {"q": "学生是否处于整体自卑状态？",
             "indicators": [{"label": "情绪稳定性-自卑自尊"}, {"label": "自我概念整体值"},
                            {"label": "自驱力-胜任感"}]},
            {"q": "学生是否处于焦虑状态？",
             "indicators": [{"label": "情绪稳定性-焦虑安详"}, {"label": "自我概念-情绪状态"}]},
            {"q": "学生是否可能高敏感内耗？",
             "indicators": [{"label": "人格-神经质"}, {"label": "人格-外倾性"}]},
            {"q": "学生是否处在不开心的状态？",
             "indicators": [{"label": "情绪稳定性-抑郁愉快"}, {"label": "自我概念-幸福与满足"}]},
            {"q": "学生是否处在安全感中？",
             "indicators": [{"label": "依恋关系-信任-母亲"}, {"label": "依恋关系-信任-父亲"},
                            {"label": "依恋关系-信任-同伴"}]},
        ],
    },
    {
        "dim": "E2",
        "groups": [
            {"q": None,
             "indicators": [{"label": "体质健康-睡眠习惯"}, {"label": "体质健康-饮食习惯"},
                            {"label": "体质健康-运动习惯"},
                            {"label": "自我概念-躯体外貌"}]},
        ],
    },
    {
        "dim": "E3",
        "groups": [
            {"q": "信息输入基本功能",
             "indicators": [{"label": "认知能力总得分"}, {"label": "认知能力百分位"},
                            {"label": "认知能力-感知觉"}, {"label": "认知能力-注意力"}]},
            {"q": "信息存储基本功能",
             "indicators": [{"label": "认知能力-记忆力"}]},
            {"q": "信息分析基本功能",
             "indicators": [{"label": "认知能力-推理能力"}, {"label": "认知能力-空间能力"}]},
            {"q": "信息加工速度",
             "indicators": [{"label": "认知能力-加工速度"}]},
            {"q": "执行能力-专注力",
             "indicators": [{"label": "执行功能-抑制控制"}, {"label": "认知能力-感知觉"},
                            {"label": "认知能力-注意力"}]},
            {"q": "执行能力-运用记忆",
             "indicators": [{"label": "执行功能-工作记忆"}]},
            {"q": "执行能力-认知灵活性（是否会举一反三、随机应变）",
             "indicators": [{"label": "执行功能-认知灵活性"}]},
            {"q": "学习动机是否强大（无论深层还是表层，先看动机是否足够强大）",
             "indicators": [{"label": "学习动机-深层动机"}, {"label": "学习动机-表面动机"}]},
            {"q": "是否有渴望成功的动机？",
             "indicators": [{"order_value": "成就感"}, {"order_value": "声望地位"},
                            {"label": "思维模式结果"}]},
            {"q": "是否有深层学习动机？",
             "indicators": [{"label": "学习动机-深层动机"}]},
            {"q": "内驱力状态？",
             "indicators": [{"label": "自驱力-自主性"}, {"label": "自驱力-胜任感"},
                            {"label": "自驱力-归属感"}]},
        ],
    },
    {
        "dim": "E4",
        "groups": [
            {"q": "学习策略是否错配？第一组：数理逻辑",
             "indicators": [{"label": "能力优势-逻辑数学能力"}, {"label": "认知能力-推理能力"}]},
            {"q": "学习策略是否错配？第二组：空间能力",
             "indicators": [{"label": "认知能力-空间能力"}, {"label": "能力优势-空间能力"}]},
            {"q": "学习策略是否错配？第三组：基于理解的学习",
             "indicators": [{"label": "认知能力-推理能力"}, {"label": "学习方法与策略-学习深层方法与策略"}]},
            {"q": "学习策略是否错配？第四组：基于表面的学习",
             "indicators": [{"label": "学习方法与策略-学习表面方法与策略"}, {"label": "认知能力-记忆力"}]},
            {"q": "学习策略与方法的程度（两个都低意味着没有使用方法和策略）",
             "indicators": [{"label": "学习方法与策略-学习深层方法与策略"},
                            {"label": "学习方法与策略-学习表面方法与策略"}]},
            {"q": "计划性",
             "indicators": [{"label": "人格-责任心"}, {"label": "自驱力-自主性"},
                            {"label": "职业兴趣-常规型"}, {"order_value": "安全稳定"}]},
            {"q": "元认知潜力",
             "indicators": [{"label": "认知能力-推理能力"}, {"label": "能力优势-内省能力"},
                            {"label": "学习方法与策略-学习深层方法与策略"},
                            {"label": "学习方法与策略-学习自我调节"},
                            {"label": "执行功能-认知灵活性"}, {"label": "执行功能-工作记忆"}]},
        ],
    },
]

# 框架引用的全部 label key（用于数据保留判断）
FRAMEWORK_LABEL_KEYS = {
    _ref["label"] for _dim in E4_FRAMEWORK for _g in _dim["groups"]
    for _ref in _g["indicators"] if "label" in _ref
}
FRAMEWORK_ORDER_VALUES = {
    _ref["order_value"] for _dim in E4_FRAMEWORK for _g in _dim["groups"]
    for _ref in _g["indicators"] if "order_value" in _ref
}


def _norm_framework_label(label: str) -> str:
    """框架 label 归一化：去空格、去尾部"得分/百分位"。"""
    s = (label or "").replace(" ", "")
    for suf in ("得分", "百分位"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return s


def build_framework_groups(eval_items: List[Dict[str, Any]]
                           ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, set]]:
    """按 E4_FRAMEWORK 组织 eval items。

    返回 (groups, other_items, dims_by_code)：
      groups: [{"dim": "E1", "q": "问题或None", "items": [item/合成条目]}]
      other_items: 框架未引用的 items
      dims_by_code: {code: {"E1","E3"}} 每个指标被框架引用到的维度集合
    """
    # label → item 索引
    by_label: Dict[str, Dict[str, Any]] = {}
    order_items: List[Dict[str, Any]] = []
    for it in eval_items:
        if it.get("eval_source") == "原始排序":
            order_items.append(it)
        by_label.setdefault(_norm_framework_label(it.get("label", "")), it)

    # 排序项按 family 计数 + 值索引
    order_total: Dict[str, int] = {}
    order_by_value: Dict[str, Dict[str, Any]] = {}
    for it in order_items:
        label = it.get("label", "") or ""
        digits = ""
        for ch in reversed(label):
            if ch.isdigit():
                digits = ch + digits
            else:
                break
        family = label[: len(label) - len(digits)] if digits else label
        order_total[family] = order_total.get(family, 0) + 1
        val = it.get("eval_value") or it.get("raw_value") or ""
        if val:
            order_by_value.setdefault(str(val), it)

    dims_by_code: Dict[str, set] = {}
    groups: List[Dict[str, Any]] = []
    referenced: set = set()

    for dim_def in E4_FRAMEWORK:
        dim = dim_def["dim"]
        for g in dim_def["groups"]:
            entries: List[Dict[str, Any]] = []
            for ref in g["indicators"]:
                if "order_value" in ref:
                    val = ref["order_value"]
                    src = order_by_value.get(val)
                    if not src:
                        continue
                    label = src.get("label", "") or ""
                    digits = ""
                    for ch in reversed(label):
                        if ch.isdigit():
                            digits = ch + digits
                        else:
                            break
                    family = label[: len(label) - len(digits)] if digits else label
                    pos = digits or "?"
                    total = order_total.get(family, 0)
                    family_short = family.replace("排序", "")
                    synth = {
                        "code": f"ORDERPOS:{val}",
                        "label": f"{family_short}·{val}排序位置",
                        "raw_value": f"第{pos}位/共{total}",
                        "eval_value": "",
                        "unit": "",
                        "eval_source": "待判定",
                        "dimension": src.get("dimension", ""),
                        "data_bias": src.get("data_bias", "正常"),
                        "problem_status": src.get("problem_status", "CONFIRMED"),
                    }
                    entries.append(synth)
                    referenced.add(src.get("code"))
                    dims_by_code.setdefault(src.get("code"), set()).add(dim)
                else:
                    it = by_label.get(_norm_framework_label(ref["label"]))
                    if it is None:
                        continue
                    entries.append(it)
                    referenced.add(it.get("code"))
                    dims_by_code.setdefault(it.get("code"), set()).add(dim)
            groups.append({"dim": dim, "q": g.get("q"), "items": entries})

    other_items = [it for it in eval_items if it.get("code") not in referenced]
    return groups, other_items, dims_by_code


# ── 问题级 verdict 引擎（E4 guideline 已确认规则，纯 Python 数据加工）────
# 状态：PROBLEM=有问题 / WATCH=关注 / OBSERVED=观察(假问题观望) /
#       HEALTHY=健康 / NEUTRAL=证据不足(数据缺失或中性)
VERDICT_PROBLEM = "PROBLEM"
VERDICT_WATCH = "WATCH"
VERDICT_OBSERVED = "OBSERVED"
VERDICT_HEALTHY = "HEALTHY"
VERDICT_NEUTRAL = "NEUTRAL"

VERDICT_LABELS_CN = {
    VERDICT_PROBLEM: "有问题",
    VERDICT_WATCH: "关注",
    VERDICT_OBSERVED: "观察",
    VERDICT_HEALTHY: "健康",
    VERDICT_NEUTRAL: "中性",
}
_VERDICT_RANK = {
    VERDICT_PROBLEM: 4, VERDICT_WATCH: 3, VERDICT_OBSERVED: 2,
    VERDICT_NEUTRAL: 1, VERDICT_HEALTHY: 0,
}

# 认知分项相对认知总百分位（code 002）的个体内强弱特质阈值（用户拍板值，后续可调）
TRAIT_GAP = 10

# PDF 体质评级词表（未知词默认=关注，保守不妄判）
_GRADE_WEAK = ("差", "低")
_GRADE_MID = ("中等", "一般")
_GRADE_OK = ("良好", "高", "优秀", "正常")


def _worst_state(states: List[str]) -> str:
    best = VERDICT_HEALTHY
    for s in states:
        if _VERDICT_RANK.get(s, 1) > _VERDICT_RANK.get(best, 0):
            best = s
    return best


def _row(it: Optional[Dict[str, Any]], state: str, note: str = "") -> Dict[str, str]:
    return {
        "label": (it or {}).get("label", ""),
        "state": state,
        "note": note,
        "eval": (it or {}).get("eval_value") or "",
        "raw": str((it or {}).get("raw_value", "") or ""),
    }


def _it_eval(it: Optional[Dict[str, Any]]) -> str:
    return ((it or {}).get("eval_value") or "").strip()


def _label_index(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """组内 label→item 索引（含 ORDERPOS 合成项按 ORDER:{val} 索引）。"""
    idx: Dict[str, Dict[str, Any]] = {}
    for it in items:
        code = str(it.get("code", "") or "")
        if code.startswith("ORDERPOS:"):
            idx[f"ORDER:{code.split(':', 1)[1]}"] = it
            continue
        idx.setdefault(_norm_framework_label(it.get("label", "")), it)
    return idx


# 常用档位映射
def _st_self_concept(ev: str) -> str:
    """自我概念细分档（<4 有问题）。"""
    if ev in ("偏低", "严重偏低"):
        return VERDICT_PROBLEM
    if ev in ("不低", "较好", "高"):
        return VERDICT_HEALTHY
    return VERDICT_NEUTRAL


def _st_emotion_sub(ev: str) -> str:
    """情绪四分项档（<5 有问题，5-10 未达标）。"""
    if ev == "需特殊关注":
        return VERDICT_PROBLEM
    if ev == "需关注":
        return VERDICT_WATCH
    if ev == "相对健康":
        return VERDICT_HEALTHY
    return VERDICT_NEUTRAL


def _st_norm(ev: str, mid: str = VERDICT_NEUTRAL) -> str:
    """常模参照档（偏低/不低/较好）。mid 指定「不低」在当前问题下的状态。"""
    if ev == "偏低":
        return VERDICT_PROBLEM
    if ev == "较好" or ev == "高":
        return VERDICT_HEALTHY
    if ev == "不低":
        return mid
    return VERDICT_NEUTRAL


def _st_percentile(ev: str) -> str:
    """百分位档（偏低→问题，较好/高→强，不低→中性）。"""
    if ev == "偏低":
        return VERDICT_PROBLEM
    if ev in ("较好", "高"):
        return VERDICT_HEALTHY
    if ev == "不低":
        return VERDICT_NEUTRAL
    return VERDICT_NEUTRAL


def _st_personality(ev: str) -> str:
    """人格档（偏低/明显偏低/严重偏低→问题）。"""
    if ev in ("偏低", "明显偏低", "严重偏低"):
        return VERDICT_PROBLEM
    if ev in ("较好", "高"):
        return VERDICT_HEALTHY
    if ev == "不低":
        return VERDICT_NEUTRAL
    return VERDICT_NEUTRAL


def _st_pdf_grade(value: str) -> str:
    """PDF 体质评级三态（差/低=弱，中等/一般=关注，良好系=健康，未知=关注）。"""
    v = (value or "").strip()
    if not v:
        return VERDICT_NEUTRAL
    if any(k in v for k in _GRADE_WEAK):
        return VERDICT_PROBLEM
    if any(k in v for k in _GRADE_MID):
        return VERDICT_WATCH
    if any(k in v for k in _GRADE_OK):
        return VERDICT_HEALTHY
    return VERDICT_WATCH


def _order_pos(it: Optional[Dict[str, Any]]) -> Optional[int]:
    """ORDERPOS 合成项 → 排序位置数字。"""
    if not it:
        return None
    raw = str(it.get("raw_value", "") or "")
    digits = ""
    for ch in raw:
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    return int(digits) if digits else None


# ── E1 各问题规则 ─────────────────────────────────────────────

def _v_e1_confidence(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    im = _label_index(items)
    rows = []
    se = im.get("学习动机-自我效能感")
    if se is not None:
        rows.append(_row(se, _st_norm(_it_eval(se), mid=VERDICT_HEALTHY), "主维度"))
    sc = im.get("自我概念-能力与学校表现")
    if sc is not None:
        rows.append(_row(sc, _st_self_concept(_it_eval(sc))))
    state = _worst_state([r["state"] for r in rows]) if rows else VERDICT_NEUTRAL
    return {"state": state, "summary": "学习自信" if state != VERDICT_PROBLEM else "学习自信不足", "items": rows}


def _v_e1_school_env(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    im = _label_index(items)
    rows = []
    for key in ("学习方法与策略-学习自我调节", "自我概念-合群"):
        it = im.get(key)
        if it is not None:
            rows.append(_row(it, _st_norm(_it_eval(it), mid=VERDICT_HEALTHY) if "自我调节" in key else _st_self_concept(_it_eval(it))))
    for key in ("依恋关系-信任-同伴", "依恋关系-沟通-同伴", "依恋关系-亲近-同伴"):
        it = im.get(key)
        if it is None:
            continue
        ev = _it_eval(it)
        st = VERDICT_PROBLEM if ev == "偏低" else (VERDICT_WATCH if ev == "不低" else (VERDICT_HEALTHY if ev == "高" else VERDICT_NEUTRAL))
        rows.append(_row(it, st))
    state = _worst_state([r["state"] for r in rows]) if rows else VERDICT_NEUTRAL
    return {"state": state, "summary": "学校环境", "items": rows}


def _v_e1_parent(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    im = _label_index(items)
    rows = []
    # 信任-父母：不是高就关注
    for key in ("依恋关系-信任-母亲", "依恋关系-信任-父亲"):
        it = im.get(key)
        if it is not None:
            rows.append(_row(it, VERDICT_HEALTHY if _it_eval(it) == "高" else VERDICT_WATCH))
    # 沟通-父母组合：至少一个高=健康；都不低=关注；任一偏低=有问题
    comm = [im.get("依恋关系-沟通-母亲"), im.get("依恋关系-沟通-父亲")]
    comm = [c for c in comm if c is not None]
    for c in comm:
        ev = _it_eval(c)
        rows.append(_row(c, VERDICT_HEALTHY if ev == "高" else (VERDICT_PROBLEM if ev == "偏低" else VERDICT_WATCH)))
    if comm:
        evs = [_it_eval(c) for c in comm]
        if "高" in evs:
            comm_state = VERDICT_HEALTHY
        elif any(e == "偏低" for e in evs):
            comm_state = VERDICT_PROBLEM
        else:
            comm_state = VERDICT_WATCH
    else:
        comm_state = VERDICT_NEUTRAL
    # 亲近-父母：不低/高=健康，偏低=关注
    for key in ("依恋关系-亲近-母亲", "依恋关系-亲近-父亲"):
        it = im.get(key)
        if it is not None:
            rows.append(_row(it, VERDICT_WATCH if _it_eval(it) == "偏低" else VERDICT_HEALTHY))
    state = _worst_state([r["state"] for r in rows] + ([comm_state] if comm else []))
    return {"state": state, "summary": "亲子依恋", "items": rows}


def _v_e1_inferiority(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    im = _label_index(items)
    rows = []
    zz = im.get("情绪稳定性-自卑自尊")
    if zz is not None:
        rows.append(_row(zz, _st_emotion_sub(_it_eval(zz))))
    sc = im.get("自我概念整体值")
    if sc is not None:
        val = (sc.get("eval_value") or sc.get("raw_value") or "").strip()
        if not val:
            rows.append(_row(sc, VERDICT_NEUTRAL, "档位缺失"))
        elif "低" in val:
            rows.append(_row(sc, VERDICT_PROBLEM))
        elif "中" in val:
            rows.append(_row(sc, VERDICT_OBSERVED, "中等-观察"))
        elif "高" in val:
            rows.append(_row(sc, VERDICT_HEALTHY))
        else:
            rows.append(_row(sc, VERDICT_NEUTRAL, f"未知档位:{val}"))
    sv = im.get("自驱力-胜任感")
    if sv is not None:
        rows.append(_row(sv, _st_norm(_it_eval(sv), mid=VERDICT_OBSERVED), "当中=观察"))
    state = _worst_state([r["state"] for r in rows]) if rows else VERDICT_NEUTRAL
    return {"state": state, "summary": "整体自卑状态", "items": rows}


def _v_e1_anxiety(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    im = _label_index(items)
    rows = []
    ax = im.get("情绪稳定性-焦虑安详")
    if ax is not None:
        rows.append(_row(ax, _st_emotion_sub(_it_eval(ax))))
    em = im.get("自我概念-情绪状态")
    if em is not None:
        rows.append(_row(em, _st_self_concept(_it_eval(em)), "相互验证"))
    state = _worst_state([r["state"] for r in rows]) if rows else VERDICT_NEUTRAL
    summary = "焦虑状态"
    if rows and all(r["state"] == VERDICT_PROBLEM for r in rows) and len(rows) >= 2:
        summary += "（两指标相互验证成立）"
    return {"state": state, "summary": summary, "items": rows}


def _v_e1_sensitive(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    im = _label_index(items)
    rows = []
    notes: List[str] = []
    state = VERDICT_HEALTHY
    nz = im.get("人格-神经质")
    if nz is not None:
        num = _to_number(nz.get("raw_value"))
        if num is not None:
            if num > 4:
                state = VERDICT_PROBLEM
                notes.append(f"神经质{num}>4 强信号")
                rows.append(_row(nz, VERDICT_PROBLEM, "强信号(>4)"))
            elif num > 3.5:
                state = VERDICT_PROBLEM
                notes.append(f"神经质{num} 3.5-4 弱信号")
                rows.append(_row(nz, VERDICT_PROBLEM, "弱信号(3.5-4)"))
            else:
                rows.append(_row(nz, VERDICT_HEALTHY))
        else:
            rows.append(_row(nz, VERDICT_NEUTRAL, "数据缺失"))
    wq = im.get("人格-外倾性")
    if wq is not None:
        num = _to_number(wq.get("raw_value"))
        if num is not None and num < 2.5:
            rows.append(_row(wq, VERDICT_WATCH, "加重因素：内向倾向(<2.5)"))
            notes.append(f"外倾性{num}<2.5 加重因素（内向倾向）")
        else:
            rows.append(_row(wq, VERDICT_NEUTRAL))
    summary = "高敏感内耗：" + ("；".join(notes) if notes else "无显著信号")
    return {"state": state, "summary": summary, "items": rows}


def _v_e1_unhappy(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    im = _label_index(items)
    rows = []
    dp = im.get("情绪稳定性-抑郁愉快")
    if dp is not None:
        rows.append(_row(dp, _st_emotion_sub(_it_eval(dp)),
                         "可能是没时间发展兴趣爱好，并非抑郁障碍" if _it_eval(dp) == "需特殊关注" else ""))
    hf = im.get("自我概念-幸福与满足")
    if hf is not None:
        rows.append(_row(hf, _st_self_concept(_it_eval(hf))))
    state = _worst_state([r["state"] for r in rows]) if rows else VERDICT_NEUTRAL
    return {"state": state, "summary": "不开心状态", "items": rows}


def _v_e1_safety(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """安全感（Emotion 表达）：只看三个依恋信任。

    信任均为 高/不低 → 在安全感中（健康）；任一偏低 → 关注（严重依恋问题由亲子问题承担）。
    职业兴趣常规型/安全稳定排序表达的是「确定性需求」，不属于 Emotion，已移至 E4 计划性。
    """
    im = _label_index(items)
    rows = []
    low_trust: List[str] = []
    for key in ("依恋关系-信任-母亲", "依恋关系-信任-父亲", "依恋关系-信任-同伴"):
        it = im.get(key)
        if it is None:
            continue
        ev = _it_eval(it)
        if ev == "偏低":
            low_trust.append(f"{it.get('label')}偏低")
            rows.append(_row(it, VERDICT_WATCH, "信任偏低"))
        elif ev in ("高", "不低"):
            rows.append(_row(it, VERDICT_HEALTHY))
        else:
            rows.append(_row(it, VERDICT_NEUTRAL))
    if low_trust:
        state = VERDICT_WATCH
        summary = "依恋信任部分偏低，安全感需关注：" + "、".join(low_trust)
    else:
        state = VERDICT_HEALTHY
        summary = "依恋关系显示处于安全感中（父母与同伴信任均不低）"
    return {"state": state, "summary": summary, "items": rows}


# ── E2（无问题分组，逐项三态）────────────────────────────────

def _v_e2(items: List[Dict[str, Any]], full_idx: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    for it in items:
        label = it.get("label", "") or ""
        if "躯体外貌" in label:
            rows.append(_row(it, _st_self_concept(_it_eval(it))))
            continue
        # 睡眠/饮食/运动：得分项 eval 缺失时，从全量索引找对应「评级」档位项
        val = _it_eval(it)
        if not val:
            base = _base_label(label)  # 去「得分」等后缀
            if base.endswith("习惯"):
                base = base[:-2]
            lv = full_idx.get(_norm_framework_label(base + "评级"))
            val = ((lv or {}).get("raw_value") or (lv or {}).get("value") or "") if lv else ""
            if val:
                # 回写到原始 item，供协议拼装行显示「评级:优」（得分0≠行为差）
                it["pdf_grade"] = val
        rows.append(_row(it, _st_pdf_grade(val), "" if _it_eval(it) else (f"评级:{val}" if val else "")))
    state = _worst_state([r["state"] for r in rows]) if rows else VERDICT_NEUTRAL
    return {"state": state, "summary": "精力管理", "items": rows}


# ── E3 各问题规则 ─────────────────────────────────────────────

def _v_default_e3(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = [_row(it, _st_percentile(_it_eval(it))) for it in items]
    state = _worst_state([r["state"] for r in rows]) if rows else VERDICT_NEUTRAL
    if state == VERDICT_PROBLEM:
        summary = "存在弱项"
    elif any(r["state"] == VERDICT_HEALTHY for r in rows):
        summary = "无弱项，有强项"
    else:
        summary = "中性"
    return {"state": state, "summary": summary, "items": rows}


def _v_e3_input(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """信息输入：认知总得分/总百分位为参照基线行（不参与判定）；感知觉强特质 × 注意力相对弱特质=组内错位。"""
    im = _label_index(items)
    rows: List[Dict[str, str]] = []
    bs = im.get("认知能力总得分")
    if bs is not None:
        rows.append(_row(bs, VERDICT_NEUTRAL, "认知总基线（标准分，参照行，不参与判定）"))
    bp = im.get("认知能力百分位")
    if bp is not None:
        rows.append(_row(bp, VERDICT_NEUTRAL, "认知总基线（百分位，参照行，不参与判定）"))
    perc = im.get("认知能力-感知觉")
    attn = im.get("认知能力-注意力")
    sub_states: List[str] = []
    for it in (perc, attn):
        if it is None:
            continue
        st = _st_percentile(_it_eval(it))
        rows.append(_row(it, st, (it.get("trait_note") or "") if it.get("trait_label") else ""))
        sub_states.append(st)
    a_low = attn is not None and _st_percentile(_it_eval(attn)) == VERDICT_PROBLEM
    p_strong = perc is not None and perc.get("trait_label") == "强特质"
    a_weak = attn is not None and attn.get("trait_label") == "相对弱特质"
    if a_low:
        state, summary = VERDICT_PROBLEM, "注意力百分位偏低（常模弱项）"
    elif p_strong and a_weak:
        pn, an = _to_number(perc.get("raw_value")), _to_number(attn.get("raw_value"))
        gap = int(round(pn - an)) if pn is not None and an is not None else None
        state = VERDICT_WATCH
        summary = (f"组内错位：感知觉强特质 vs 注意力相对弱特质"
                   + (f"（差{gap}）" if gap is not None else "") + "，注意力值得关切")
    else:
        state = _worst_state(sub_states) if sub_states else VERDICT_NEUTRAL
        summary = ("存在弱项" if state == VERDICT_PROBLEM
                   else ("无弱项，有强项" if any(s == VERDICT_HEALTHY for s in sub_states) else "中性"))
    return {"state": state, "summary": summary, "items": rows}


def _v_e3_focus(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """专注力：高感知觉 + 相对弱注意力（抑制控制作参照）= 潜在分心/粗心组合。"""
    im = _label_index(items)
    inh = im.get("执行功能-抑制控制")
    perc = im.get("认知能力-感知觉")
    attn = im.get("认知能力-注意力")
    rows: List[Dict[str, str]] = []
    for it in (inh, perc, attn):
        if it is None:
            continue
        st = _st_percentile(_it_eval(it))
        rows.append(_row(it, st, (it.get("trait_note") or "") if it.get("trait_label") else ""))
    a_low = attn is not None and _st_percentile(_it_eval(attn)) == VERDICT_PROBLEM
    p_strong = perc is not None and perc.get("trait_label") == "强特质"
    a_weak = attn is not None and attn.get("trait_label") == "相对弱特质"
    if a_low:
        state, summary = VERDICT_PROBLEM, "注意力百分位偏低（常模弱项）"
    elif p_strong and a_weak:
        state = VERDICT_WATCH
        summary = "潜在分心组合：高感知觉+相对弱注意力，易粗心/分心，关注作业环境与电子产品管理"
    else:
        states = [r["state"] for r in rows if r["label"] != (perc or {}).get("label")] or [r["state"] for r in rows]
        state = _worst_state(states) if states else VERDICT_NEUTRAL
        summary = ("存在弱项" if state == VERDICT_PROBLEM
                   else ("无弱项，有强项" if any(s == VERDICT_HEALTHY for s in states) else "中性"))
    return {"state": state, "summary": summary, "items": rows}


def _v_e3_motivation(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """动机四象限：两高充足 / 两低不足 / 深低表高找 passion project / 深高表低降门槛。"""
    im = _label_index(items)
    deep = im.get("学习动机-深层动机")
    surf = im.get("学习动机-表面动机")

    def _band(it):
        if it is None:
            return None
        ev = _it_eval(it)
        if ev == "偏低":
            return "low"
        if ev in ("较好", "高"):
            return "high"
        return "mid"

    d, s = _band(deep), _band(surf)
    rows = []
    if deep is not None:
        rows.append(_row(deep, VERDICT_PROBLEM if d == "low" else (VERDICT_HEALTHY if d == "high" else VERDICT_NEUTRAL)))
    if surf is not None:
        rows.append(_row(surf, VERDICT_PROBLEM if s == "low" else (VERDICT_HEALTHY if s == "high" else VERDICT_NEUTRAL)))
    if d == "high" and s == "high":
        state, summary = VERDICT_HEALTHY, "动机充足（深层与表层动机都强）"
    elif d == "low" and s == "low":
        state, summary = VERDICT_PROBLEM, "动机不足（深层与表层动机都低）"
    elif d == "low" and s == "high":
        state, summary = VERDICT_WATCH, "外部驱动：深层动机低、表面动机高，建议寻找 passion project 提升深层兴趣"
    elif d == "high" and s == "low":
        state, summary = VERDICT_WATCH, "内在足但行动投入不足：建议降低启动门槛、建立外部激励/习惯机制"
    else:
        state, summary = VERDICT_NEUTRAL, "动机水平中性"
    return {"state": state, "summary": summary, "items": rows}


def _v_e3_success_drive(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    im = _label_index(items)
    rows = []
    hits: List[str] = []
    for val in ("成就感", "声望地位"):
        it = im.get(f"ORDER:{val}")
        if it is None:
            continue
        pos = _order_pos(it)
        if pos is not None and pos <= 5:
            hits.append(f"{val}第{pos}位")
            rows.append(_row(it, VERDICT_HEALTHY, f"第{pos}位/共15，命中前五"))
        else:
            rows.append(_row(it, VERDICT_NEUTRAL, f"第{pos}位/未进前五" if pos else ""))
    sw = im.get("思维模式结果")
    if sw is not None:
        val = (sw.get("eval_value") or sw.get("raw_value") or "").strip()
        rows.append(_row(sw, VERDICT_NEUTRAL, val or ""))
    state = VERDICT_HEALTHY if hits else VERDICT_NEUTRAL
    summary = "存在渴望成功的动机（" + "、".join(hits) + "）" if hits else "渴望成功动机未进前五"
    return {"state": state, "summary": summary, "items": rows}


def _v_e3_inner_drive(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = [_row(it, _st_norm(_it_eval(it))) for it in items]
    state = _worst_state([r["state"] for r in rows]) if rows else VERDICT_NEUTRAL
    return {"state": state, "summary": "内驱力状态", "items": rows}


# ── E4 各问题规则 ─────────────────────────────────────────────

def _band3(it: Optional[Dict[str, Any]]) -> Optional[str]:
    """三档化：high=较好/高，mid=不低，low=偏低系，None=缺失。"""
    if it is None:
        return None
    ev = _it_eval(it)
    if ev in ("较好", "高"):
        return "high"
    if ev == "不低":
        return "mid"
    if ev in ("偏低", "明显偏低", "严重偏低"):
        return "low"
    return None


def _v_e4_mismatch_logic(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """第一组数理逻辑：自评能力优势 × 实测推理百分位。不一致=错配。"""
    return _mismatch_self_vs_actual(items, "能力优势-逻辑数学能力", "认知能力-推理能力", "数理逻辑")


def _v_e4_mismatch_spatial(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """第二组空间：实测空间百分位 × 自评空间能力。"""
    return _mismatch_self_vs_actual(items, "能力优势-空间能力", "认知能力-空间能力", "空间能力")


def _mismatch_self_vs_actual(items, self_key, actual_key, name) -> Dict[str, Any]:
    im = _label_index(items)
    se, ac = im.get(self_key), im.get(actual_key)
    rows = []
    if se is not None:
        rows.append(_row(se, VERDICT_NEUTRAL))
    if ac is not None:
        rows.append(_row(ac, VERDICT_NEUTRAL))
    sb, ab = _band3(se), _band3(ac)
    if sb is None or ab is None:
        state, summary = VERDICT_NEUTRAL, f"{name}：数据不足，无法判定错配"
    elif sb == "low" and ab in ("mid", "high"):
        state, summary = VERDICT_WATCH, f"{name}错配：低估自己（自评偏低但实测不低）"
    elif sb in ("mid", "high") and ab == "low":
        state, summary = VERDICT_WATCH, f"{name}错配：自我认知偏差（自评不低但实测偏低，高估）"
    else:
        state, summary = VERDICT_HEALTHY, f"{name}：自评与实测匹配"
    return {"state": state, "summary": summary, "items": rows}


def _v_e4_mismatch_deep(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """第三组基于理解的学习：推理百分位 × 深层策略。"""
    im = _label_index(items)
    ac, dm = im.get("认知能力-推理能力"), im.get("学习方法与策略-学习深层方法与策略")
    rows = []
    if ac is not None:
        rows.append(_row(ac, VERDICT_NEUTRAL))
    if dm is not None:
        rows.append(_row(dm, VERDICT_NEUTRAL))
    ab, db = _band3(ac), _band3(dm)
    if ab is None or db is None:
        state, summary = VERDICT_NEUTRAL, "基于理解的学习：数据不足"
    elif ab in ("mid", "high") and db == "low":
        state, summary = VERDICT_WATCH, "错配（低垂果实）：推理实测不低但深层策略偏低——有能力却没用深层方法"
    elif ab == "low" and db in ("mid", "high"):
        state, summary = VERDICT_WATCH, "错配：深层方法超出当前推理能力支撑"
    else:
        state, summary = VERDICT_HEALTHY, "基于理解的学习：匹配"
    return {"state": state, "summary": summary, "items": rows}


def _v_e4_mismatch_surface(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """第四组基于表面的学习：表面策略 × 记忆百分位。"""
    im = _label_index(items)
    sm, mem = im.get("学习方法与策略-学习表面方法与策略"), im.get("认知能力-记忆力")
    rows = []
    if sm is not None:
        rows.append(_row(sm, VERDICT_NEUTRAL))
    if mem is not None:
        rows.append(_row(mem, VERDICT_NEUTRAL))
    sb, mb = _band3(sm), _band3(mem)
    if sb is None or mb is None:
        state, summary = VERDICT_NEUTRAL, "基于表面的学习：数据不足"
    elif mb == "low" and sb in ("mid", "high"):
        state, summary = VERDICT_WATCH, "错配（更危险）：记忆偏弱却依赖表面策略"
    elif mb in ("mid", "high") and sb == "low":
        state, summary = VERDICT_WATCH, "错配（低垂果实）：记忆能力支持表面方法但表面策略偏低——有能力却没用表面方法"
    else:
        state, summary = VERDICT_HEALTHY, "基于表面的学习：匹配"
    return {"state": state, "summary": summary, "items": rows}


def _v_e4_strategy_level(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """学习策略与方法的程度：两个都低=没有使用方法和策略。"""
    im = _label_index(items)
    dm, sm = im.get("学习方法与策略-学习深层方法与策略"), im.get("学习方法与策略-学习表面方法与策略")
    rows = []
    if dm is not None:
        rows.append(_row(dm, VERDICT_PROBLEM if _band3(dm) == "low" else VERDICT_NEUTRAL))
    if sm is not None:
        rows.append(_row(sm, VERDICT_PROBLEM if _band3(sm) == "low" else VERDICT_NEUTRAL))
    db, sb = _band3(dm), _band3(sm)
    if db == "low" and sb == "low":
        state, summary = VERDICT_PROBLEM, "深层与表面策略都低：没有使用方法和策略"
    elif db == "low" or sb == "low":
        state, summary = VERDICT_NEUTRAL, "单侧策略偏低"
    elif db is None and sb is None:
        state, summary = VERDICT_NEUTRAL, "数据不足"
    else:
        state, summary = VERDICT_HEALTHY, "有使用方法与策略"
    return {"state": state, "summary": summary, "items": rows}


def _v_e4_planning(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """计划性：责任心/自主性为判定项；常规型/安全稳定为「确定性需求」上下文行，不进问题级判定。"""
    im = _label_index(items)
    rows: List[Dict[str, str]] = []
    states: List[str] = []
    for key in ("人格-责任心", "自驱力-自主性"):
        it = im.get(key)
        if it is None:
            continue
        st = _st_personality(_it_eval(it)) if "人格" in key else _st_norm(_it_eval(it))
        rows.append(_row(it, st))
        states.append(st)
    demand: List[str] = []
    cg = im.get("职业兴趣-常规型")
    if cg is not None:
        ev = _it_eval(cg)
        if ev in ("高", "不低"):
            demand.append(f"常规型{ev}")
        rows.append(_row(cg, VERDICT_NEUTRAL, "确定性需求上下文（不参与计划性判定）"))
    aq = im.get("ORDER:安全稳定")
    if aq is not None:
        pos = _order_pos(aq)
        if pos is not None and pos <= 5:
            demand.append(f"安全稳定第{pos}位（前五）")
        rows.append(_row(aq, VERDICT_NEUTRAL, "确定性需求上下文" + (f"，第{pos}位/共15" if pos else "")))
    state = _worst_state(states) if states else VERDICT_NEUTRAL
    if state == VERDICT_PROBLEM and demand:
        summary = "计划性不足 + 高确定性需求（" + "、".join(demand) + "）→ 结构化机制切入点（如「一表人才」）"
    elif demand:
        summary = "计划性" + "（确定性需求：" + "、".join(demand) + "）"
    else:
        summary = "计划性"
    return {"state": state, "summary": summary, "items": rows}


def _v_e4_metacognition(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = [_row(it, _st_percentile(_it_eval(it)) if "百分位" in (it.get("label", "") or "") or "认知" in (it.get("label", "") or "") else _st_norm(_it_eval(it))) for it in items]
    pos = sum(1 for r in rows if r["state"] == VERDICT_HEALTHY)
    neg = sum(1 for r in rows if r["state"] == VERDICT_PROBLEM)
    if pos >= 3:
        state, summary = VERDICT_HEALTHY, f"元认知潜力好（{pos}项正向证据）"
    elif neg >= 3:
        state, summary = VERDICT_WATCH, f"多项偏弱（{neg}项），元认知潜力待观察"
    else:
        state, summary = VERDICT_NEUTRAL, "元认知潜力中性"
    return {"state": state, "summary": summary, "items": rows}


# 问题文本 → 判定规则（key 与 E4_FRAMEWORK 中 q 完全一致）
_QUESTION_VERDICTS = {
    "学生对于学习的自信程度如何？（是否对于取得好的成绩有自信？）": _v_e1_confidence,
    "学校环境对学生是否产生了负面影响？": _v_e1_school_env,
    "亲子关系是否对孩子的学业情绪有潜在影响？": _v_e1_parent,
    "学生是否处于整体自卑状态？": _v_e1_inferiority,
    "学生是否处于焦虑状态？": _v_e1_anxiety,
    "学生是否可能高敏感内耗？": _v_e1_sensitive,
    "学生是否处在不开心的状态？": _v_e1_unhappy,
    "学生是否处在安全感中？": _v_e1_safety,
    "信息输入基本功能": _v_e3_input,
    "信息存储基本功能": _v_default_e3,
    "信息分析基本功能": _v_default_e3,
    "信息加工速度": _v_default_e3,
    "执行能力-专注力": _v_e3_focus,
    "执行能力-运用记忆": _v_default_e3,
    "执行能力-认知灵活性（是否会举一反三、随机应变）": _v_default_e3,
    "学习动机是否强大（无论深层还是表层，先看动机是否足够强大）": _v_e3_motivation,
    "是否有渴望成功的动机？": _v_e3_success_drive,
    "是否有深层学习动机？": _v_default_e3,
    "内驱力状态？": _v_e3_inner_drive,
    "学习策略是否错配？第一组：数理逻辑": _v_e4_mismatch_logic,
    "学习策略是否错配？第二组：空间能力": _v_e4_mismatch_spatial,
    "学习策略是否错配？第三组：基于理解的学习": _v_e4_mismatch_deep,
    "学习策略是否错配？第四组：基于表面的学习": _v_e4_mismatch_surface,
    "学习策略与方法的程度（两个都低意味着没有使用方法和策略）": _v_e4_strategy_level,
    "计划性": _v_e4_planning,
    "元认知潜力": _v_e4_metacognition,
}


def _annotate_cognitive_traits(eval_items: List[Dict[str, Any]]) -> None:
    """以认知能力百分位总（code 002）为基线，给 003-008 六个认知分项标注个体内强/弱特质。

    强特质：有效评价=高，或百分位 ≥ 基线+TRAIT_GAP；
    相对弱特质：百分位 ≤ 基线-TRAIT_GAP。
    标注写入 item 的 trait_label/trait_note，只作识别，不改变问题级 state。
    """
    base: Optional[float] = None
    for it in eval_items:
        if str(it.get("code", "")).strip() == "002":
            base = _to_number(it.get("raw_value"))
            break
    if base is None:
        return
    for it in eval_items:
        if not (3 <= _code_int(it.get("code")) <= 8):
            continue
        if "百分位" not in (it.get("label", "") or ""):
            continue
        num = _to_number(it.get("raw_value"))
        if num is None:
            continue
        diff = int(round(num - base))
        ev = (it.get("eval_value") or "").strip()
        if ev == "高" or diff >= TRAIT_GAP:
            it["trait_label"] = "强特质"
            it["trait_note"] = f"总{base:g},{'+' if diff >= 0 else ''}{diff}"
        elif diff <= -TRAIT_GAP:
            it["trait_label"] = "相对弱特质"
            it["trait_note"] = f"总{base:g},{diff}"


def evaluate_question_verdicts(eval_items: List[Dict[str, Any]]
                               ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, set]]:
    """在 build_framework_groups 之上为每个问题产出问题级结论。

    返回 (groups, other_items, dims_by_code)，groups 中每组附带：
      verdict: {"state": PROBLEM/WATCH/OBSERVED/HEALTHY/NEUTRAL,
                "summary": 人读摘要, "items": [{label,state,note,eval,raw}]}
    E2（q=None）按逐项三态判定。
    """
    _annotate_cognitive_traits(eval_items)
    groups, other_items, dims_by_code = build_framework_groups(eval_items)
    full_idx = {_norm_framework_label(it.get("label", "")): it for it in eval_items}
    for g in groups:
        if g["dim"] == "E2":
            g["verdict"] = _v_e2(g["items"], full_idx)
        elif g.get("q"):
            fn = _QUESTION_VERDICTS.get(g["q"], _v_default_e3)
            g["verdict"] = fn(g["items"])
        else:
            g["verdict"] = None
    return groups, other_items, dims_by_code


DATA_BIAS_OPTIONS = ["正常", "偏高", "偏低"]


def eval_options_for(code: str, label: str = "") -> List[str]:
    """返回某个 code 对应的有效档位选项（source-of-truth 规则）。

    前端用这个替代统一的 EVAL_OPTIONS 下拉——每个数据点有自己的档位体系。
    """
    c = _code_int(code)
    # 认知能力百分位 002
    if c == 2 and "百分位" in label:
        return ["高", "较好", "不低", "偏低"]
    # 认知能力百分位 003-008
    if 3 <= c <= 8 and "百分位" in label:
        return ["高", "较好", "不低", "偏低"]
    # 009 情绪稳定性总分
    if c == 9 and "情绪稳定性" in label and ("总分" in label or "总值" in label):
        return ["高", "较好", "不低", "偏低", "明显偏低"]
    # 011-014 情绪四分项
    if 11 <= c <= 14 and "情绪稳定性" in label and "得分" in label:
        return ["需特殊关注", "需关注", "相对健康"]
    # 015-019 人格
    if 15 <= c <= 19 and "人格" in label and "得分" in label:
        return ["高", "较好", "不低", "偏低", "明显偏低", "严重偏低"]
    # 023-025 依恋信任
    if 23 <= c <= 25 and "依恋" in label and "信任" in label and "得分" in label:
        return ["高", "不低", "偏低"]
    # 026-028 依恋沟通
    if 26 <= c <= 28 and "依恋" in label and "沟通" in label and "得分" in label:
        return ["高", "不低", "偏低"]
    # 029-031 依恋亲近
    if 29 <= c <= 31 and "依恋" in label and "亲近" in label and "得分" in label:
        return ["高", "不低", "偏低"]
    # 053-058 自我概念细分
    if 53 <= c <= 58 and "自我概念" in label:
        return ["高", "较好", "不低", "偏低", "严重偏低"]
    # 060-062 自驱力（常模参照）
    if 60 <= c <= 62 and "自驱力" in label:
        return ["较好", "不低", "偏低"]
    # 063-065 执行功能百分位
    if 63 <= c <= 65 and "执行功能" in label and "百分位" in label:
        return ["高", "较好", "不低", "偏低"]
    # 066-068 学习动机（常模参照）
    if 66 <= c <= 68 and "学习动机" in label:
        return ["较好", "不低", "偏低"]
    # 069-071 学习方法（常模参照）
    if 69 <= c <= 71 and "学习方法" in label:
        return ["较好", "不低", "偏低"]
    # 073-078 职业兴趣
    if 73 <= c <= 78 and "职业兴趣" in label:
        return ["高", "不低", "偏低"]
    # 079-086 能力优势
    if 79 <= c <= 86 and "能力优势" in label and "排序" not in label:
        return ["高", "不低", "偏低"]
    # 052 自我概念整体档位
    if c == 52 and "自我概念整体档位" in label:
        return ["偏低", "正常", "偏高"]
    # 其他没有规则的，返回通用选项（来自 PDF 档位字段的词汇）
    return ["高", "较好", "不低", "偏低", "明显偏低", "严重偏低",
            "需关注", "需特殊关注", "相对健康", "正常", "低", "中"]
