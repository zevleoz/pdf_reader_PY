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
             "indicators": [{"label": "职业兴趣-常规型"}, {"order_value": "安全稳定"},
                            {"label": "依恋关系-信任-母亲"}, {"label": "依恋关系-信任-父亲"},
                            {"label": "依恋关系-信任-同伴"}]},
        ],
    },
    {
        "dim": "E2",
        "groups": [
            {"q": None,
             "indicators": [{"label": "体质健康-睡眠习惯"}, {"label": "体质健康-饮食习惯"},
                            {"label": "体质健康-运动习惯"}, {"label": "体质健康-BMI"},
                            {"label": "自我概念-躯体外貌"}]},
        ],
    },
    {
        "dim": "E3",
        "groups": [
            {"q": "信息输入基本功能",
             "indicators": [{"label": "认知能力-感知觉"}, {"label": "认知能力-注意力"}]},
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
             "indicators": [{"label": "人格-责任心"}, {"label": "自驱力-自主性"}]},
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
