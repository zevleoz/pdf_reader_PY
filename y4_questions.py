"""Y4 原生问题研判引擎 — 四维问题集 + 干预/潜能名单。

与 E4 平行、独立的产物：问题锚定 Y4 自己的四维语言
（心力/精力/学习力/生涯力 + 跨维度连结），不出现 E1-E4 概念。

纯数据加工：不导入 Flask，不触发 AI，不写库。
复用 evaluation_rules 的档位→状态映射等纯函数，不改动 E4 任何逻辑。

题型（kind）：
  risk    单极风险题：PROBLEM/WATCH → 干预侧；HEALTHY → 潜能侧
  bipolar 双极题：同一题含风险分支与资产分支，单个学生只落一个名单
  asset   资产题：只可能进强/弱潜能，永不进干预
  label   分型/表达/杠杆题：产出标签，永不进任何名单

名单（四个，不设第五桶；OBSERVED 归入弱潜能）：
  强干预 / 弱干预 / 强潜能 / 弱潜能
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple

import evaluation_rules as er

# ── 状态与名单常量（沿用 E4 口径）──────────────────────────────────
PROBLEM = er.VERDICT_PROBLEM
WATCH = er.VERDICT_WATCH
OBSERVED = er.VERDICT_OBSERVED
HEALTHY = er.VERDICT_HEALTHY
NEUTRAL = er.VERDICT_NEUTRAL

LIST_STRONG_I = er.LIST_STRONG_INTERVENTION   # 强干预
LIST_WEAK_I = er.LIST_WEAK_INTERVENTION       # 弱干预
LIST_STRONG_P = er.LIST_STRONG_POTENTIAL      # 强潜能
LIST_WEAK_P = er.LIST_WEAK_POTENTIAL          # 弱潜能

SEVERE_EVALS = er._QUESTION_SEVERE_EVALS      # 需特殊关注/明显偏低/严重偏低
STRONG_EVALS = er._STRONG_POTENTIAL_EVALS     # 高/较好

KIND_RISK = "risk"
KIND_BIPOLAR = "bipolar"
KIND_ASSET = "asset"
KIND_LABEL = "label"

Y4_DIMS = ["心力", "精力", "学习力", "生涯力", "跨维度"]

DIM_LABELS = {
    "心力": "心力（情绪与动力系统）",
    "精力": "精力（精力管理与身体健康系统）",
    "学习力": "学习力（学习系统）",
    "生涯力": "生涯力（专业与职业发展系统）",
    "跨维度": "跨维度连结",
}


# ── 行构造与小工具 ────────────────────────────────────────────────
def _row(it: Optional[Dict[str, Any]], state: str, note: str = "") -> Dict[str, str]:
    r = er._row(it, state, note)
    if it is not None:
        src = it.get("eval_source") or ""
        if src:
            r["source"] = src
        bias = er.normalize_bias(it.get("data_bias"))
        if bias and bias != "正常":
            r["bias"] = bias
    return r


def _ev(it: Optional[Dict[str, Any]]) -> str:
    return er._it_eval(it)


def _num(it: Optional[Dict[str, Any]]) -> Optional[float]:
    return er._to_number((it or {}).get("raw_value"))


def _band3(it: Optional[Dict[str, Any]]) -> Optional[str]:
    return er._band3(it)


def _grade_state(word: str) -> str:
    return er._st_pdf_grade(word)


def _grade_word_of(im: Dict[str, Dict[str, Any]], score_key: str) -> str:
    """从体质得分项取评级词（规则缺失时档位字段会回填到 eval_value）。"""
    it = im.get(score_key)
    if it is None:
        return ""
    ev = (it.get("eval_value") or "").strip()
    if any(k in ev for k in ("优", "良", "中", "差", "一般", "正常")):
        return ev
    return ""


def _order_hit(im: Dict[str, Dict[str, Any]], value: str, top_n: int = 5) -> Optional[int]:
    """价值观/能力排序：value 命中前 top_n 位时返回位次，否则 None。"""
    it = im.get(f"ORDER:{value}")
    if it is None:
        return None
    pos = er._order_pos(it)
    return pos if pos is not None and pos <= top_n else None


def _v(state: str, summary: str, rows: List[Dict[str, str]],
        tags: Optional[List[str]] = None,
        asset_strong: Optional[bool] = None,
        force_strong: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {"state": state, "summary": summary, "items": rows}
    if tags:
        out["tags"] = tags
    if asset_strong is not None:
        out["asset_strong"] = asset_strong
    if force_strong:
        out["force_strong"] = True
    return out


# ── Y4 问题框架（source of truth）────────────────────────────────
# indicators 两种引用：{"label": ...}（自动去 得分/百分位 后缀匹配）
#                    {"order_value": ...}（匹配排序项值）
Y4_FRAMEWORK: List[Dict[str, Any]] = [
    {"dim": "心力", "groups": [
        {"id": "X01", "kind": KIND_RISK, "fn": "anxiety",
         "q": "学生是否处于焦虑状态？",
         "indicators": [{"label": "情绪稳定性-焦虑安详"}, {"label": "自我概念-情绪状态"}]},
        {"id": "X02", "kind": KIND_LABEL, "fn": "anxiety_sources",
         "q": "如果焦虑成立，焦虑可能来自哪里？",
         "indicators": [{"label": "自我概念-行为表现"}, {"label": "自我概念-能力与学校表现"},
                        {"label": "学习动机-自我效能感"}, {"label": "体质健康-BMI得分"},
                        {"label": "自我概念-躯体外貌"}, {"label": "自我概念-合群"},
                        {"label": "依恋关系-信任-同伴"}, {"label": "依恋关系-沟通-同伴"},
                        {"label": "依恋关系-亲近-同伴"}, {"label": "依恋关系-信任-母亲"},
                        {"label": "依恋关系-信任-父亲"}, {"label": "依恋关系-沟通-母亲"},
                        {"label": "依恋关系-沟通-父亲"}]},
        {"id": "X03", "kind": KIND_BIPOLAR, "fn": "emotional_outlets",
         "q": "情绪有没有可用的排解通道？",
         "indicators": [{"label": "依恋关系-信任-母亲"}, {"label": "依恋关系-信任-父亲"},
                        {"label": "依恋关系-信任-同伴"}, {"label": "依恋关系-沟通-母亲"},
                        {"label": "依恋关系-沟通-父亲"}, {"label": "依恋关系-沟通-同伴"},
                        {"label": "依恋关系-亲近-母亲"}, {"label": "依恋关系-亲近-父亲"},
                        {"label": "依恋关系-亲近-同伴"},
                        {"label": "人格-外倾性"}, {"label": "人格-宜人性"}]},
        {"id": "X04", "kind": KIND_BIPOLAR, "fn": "depression",
         "q": "是抑郁风险，还是兴趣被挤占的「不愉快」？",
         "indicators": [{"label": "情绪稳定性-抑郁愉快"}, {"label": "体质健康-睡眠习惯"},
                        {"label": "体质健康-饮食习惯"},
                        {"label": "职业兴趣-现实型"}, {"label": "职业兴趣-研究型"},
                        {"label": "职业兴趣-艺术型"}, {"label": "职业兴趣-社会型"},
                        {"label": "职业兴趣-事业型"}, {"label": "职业兴趣-常规型"},
                        {"label": "自我概念-能力与学校表现"}, {"label": "学习动机-自我效能感"},
                        {"label": "自驱力-自主性"}]},
        {"id": "X05", "kind": KIND_RISK, "fn": "inferiority",
         "q": "学生是否处于整体自卑状态？",
         "indicators": [{"label": "情绪稳定性-自卑自尊"}, {"label": "自我概念整体档位"},
                        {"label": "自驱力-胜任感"}]},
        {"id": "X06", "kind": KIND_BIPOLAR, "fn": "self_esteem",
         "q": "自尊是否真实、抗挫承载如何？",
         "indicators": [{"label": "情绪稳定性-自卑自尊"}, {"label": "自我概念整体档位"},
                        {"label": "自我概念-行为表现"}]},
        {"id": "X07", "kind": KIND_RISK, "fn": "parent_attachment",
         "q": "亲子关系具体卡在谁的哪一环？",
         "indicators": [{"label": "依恋关系-信任-母亲"}, {"label": "依恋关系-信任-父亲"},
                        {"label": "依恋关系-沟通-母亲"}, {"label": "依恋关系-沟通-父亲"},
                        {"label": "依恋关系-亲近-母亲"}, {"label": "依恋关系-亲近-父亲"}]},
        {"id": "X08", "kind": KIND_BIPOLAR, "fn": "sensitivity",
         "q": "是否高敏感内耗？能否靠自己想通？",
         "indicators": [{"label": "人格-神经质"}, {"label": "人格-外倾性"},
                        {"label": "能力优势-内省能力"}, {"label": "认知能力-推理能力"}]},
        {"id": "X09", "kind": KIND_LABEL, "fn": "helplessness",
         "q": "无力感更接近哪一型？",
         "indicators": [{"label": "情绪稳定性-焦虑安详"}, {"label": "自我概念整体档位"},
                        {"label": "情绪稳定性-自卑自尊"}, {"label": "学习动机-自我效能感"},
                        {"label": "自驱力-自主性"}, {"label": "人格-责任心"},
                        {"label": "依恋关系-信任-母亲"}, {"label": "依恋关系-信任-父亲"},
                        {"label": "依恋关系-沟通-母亲"}, {"label": "依恋关系-沟通-父亲"},
                        {"label": "思维模式结果"}]},
    ]},
    {"dim": "精力", "groups": [
        {"id": "E01", "kind": KIND_RISK, "fn": "body_behaviors",
         "q": "睡眠、饮食、运动行为是否健康？",
         "indicators": [{"label": "体质健康-睡眠习惯"}, {"label": "体质健康-饮食习惯"},
                        {"label": "体质健康-运动习惯"}, {"label": "自我概念-躯体外貌"}]},
        {"id": "E02", "kind": KIND_BIPOLAR, "fn": "body_capacity",
         "q": "身体状态能否支撑白天的学习与情绪承载？",
         "indicators": [{"label": "体质健康-睡眠习惯"}, {"label": "体质健康-饮食习惯"},
                        {"label": "体质健康-运动习惯"}]},
    ]},
    {"dim": "学习力", "groups": [
        {"id": "L01", "kind": KIND_RISK, "fn": "cog_input",
         "q": "认知 · 信息输入基本功能（感知觉 × 注意力）",
         "indicators": [{"label": "认知能力总得分"}, {"label": "认知能力百分位"},
                        {"label": "认知能力-感知觉"}, {"label": "认知能力-注意力"}]},
        {"id": "L02", "kind": KIND_RISK, "fn": "cog_default",
         "q": "认知 · 信息存储基本功能（记忆力）",
         "indicators": [{"label": "认知能力-记忆力"}]},
        {"id": "L03", "kind": KIND_RISK, "fn": "cog_default",
         "q": "认知 · 信息分析基本功能（推理 × 空间）",
         "indicators": [{"label": "认知能力-推理能力"}, {"label": "认知能力-空间能力"}]},
        {"id": "L04", "kind": KIND_RISK, "fn": "cog_default",
         "q": "认知 · 信息加工速度",
         "indicators": [{"label": "认知能力-加工速度"}]},
        {"id": "L05", "kind": KIND_BIPOLAR, "fn": "focus_combo",
         "q": "抑制控制 × 感知觉 × 注意力：粗心分心组合还是稳定专注？",
         "indicators": [{"label": "执行功能-抑制控制"}, {"label": "认知能力-感知觉"},
                        {"label": "认知能力-注意力"}]},
        {"id": "L06", "kind": KIND_RISK, "fn": "fatigue_wm",
         "q": "执行 · 运用记忆（工作记忆）是真弱项还是施测疲劳？",
         "indicators": [{"label": "执行功能-工作记忆"}]},
        {"id": "L07", "kind": KIND_RISK, "fn": "fatigue_flex",
         "q": "执行 · 认知灵活性是真弱项还是施测疲劳？",
         "indicators": [{"label": "执行功能-认知灵活性"}]},
        {"id": "L08", "kind": KIND_BIPOLAR, "fn": "confidence_gap",
         "q": "学习自信与在校表现是否脱钩？",
         "indicators": [{"label": "学习动机-自我效能感"}, {"label": "自我概念-能力与学校表现"}]},
        {"id": "L09", "kind": KIND_BIPOLAR, "fn": "motivation_quad",
         "q": "学习动机是否强大（深层 × 表层四象限）？",
         "indicators": [{"label": "学习动机-深层动机"}, {"label": "学习动机-表面动机"}]},
        {"id": "L10", "kind": KIND_LABEL, "fn": "success_drive",
         "q": "是否有渴望成功的动机（成就认可导向）？",
         "indicators": [{"order_value": "成就感"}, {"order_value": "声望地位"},
                        {"label": "思维模式结果"}]},
        {"id": "L11", "kind": KIND_RISK, "fn": "deep_motivation",
         "q": "是否有深层学习动机？",
         "indicators": [{"label": "学习动机-深层动机"}]},
        {"id": "L12", "kind": KIND_RISK, "fn": "inner_drive",
         "q": "内驱力三成分（自主性 / 胜任感 / 归属感）状态？",
         "indicators": [{"label": "自驱力-自主性"}, {"label": "自驱力-胜任感"},
                        {"label": "自驱力-归属感"}]},
        {"id": "L13", "kind": KIND_RISK, "fn": "mm_logic",
         "q": "学习策略错配 · 第一组：数理逻辑（自评 × 实测推理）",
         "indicators": [{"label": "能力优势-逻辑数学能力"}, {"label": "认知能力-推理能力"}]},
        {"id": "L14", "kind": KIND_RISK, "fn": "mm_spatial",
         "q": "学习策略错配 · 第二组：空间能力（自评 × 实测空间）",
         "indicators": [{"label": "能力优势-空间能力"}, {"label": "认知能力-空间能力"}]},
        {"id": "L15", "kind": KIND_RISK, "fn": "mm_deep",
         "q": "学习策略错配 · 第三组：基于理解的学习（推理 × 深层方法）",
         "indicators": [{"label": "认知能力-推理能力"},
                        {"label": "学习方法与策略-学习深层方法与策略"}]},
        {"id": "L16", "kind": KIND_RISK, "fn": "mm_surface",
         "q": "学习策略错配 · 第四组：基于表面的学习（表面方法 × 记忆力）",
         "indicators": [{"label": "学习方法与策略-学习表面方法与策略"},
                        {"label": "认知能力-记忆力"}]},
        {"id": "L17", "kind": KIND_RISK, "fn": "strategy_level",
         "q": "学习策略与方法的整体水平（两类都低＝基本没用方法）",
         "indicators": [{"label": "学习方法与策略-学习深层方法与策略"},
                        {"label": "学习方法与策略-学习表面方法与策略"}]},
        {"id": "L18", "kind": KIND_BIPOLAR, "fn": "planning",
         "q": "计划性：责任心 × 自主性",
         "indicators": [{"label": "人格-责任心"}, {"label": "自驱力-自主性"}]},
        {"id": "L19", "kind": KIND_ASSET, "fn": "metacognition",
         "q": "元认知潜力（自我监控 / 反思 / 迁移的基础）",
         "indicators": [{"label": "认知能力-推理能力"}, {"label": "能力优势-内省能力"},
                        {"label": "学习方法与策略-学习深层方法与策略"},
                        {"label": "学习方法与策略-学习自我调节"},
                        {"label": "执行功能-认知灵活性"}, {"label": "执行功能-工作记忆"}]},
    ]},
    {"dim": "生涯力", "groups": [
        {"id": "C01", "kind": KIND_BIPOLAR, "fn": "interest_structure",
         "q": "职业兴趣有没有鲜明的高分方向？",
         "indicators": [{"label": "职业兴趣-现实型"}, {"label": "职业兴趣-研究型"},
                        {"label": "职业兴趣-艺术型"}, {"label": "职业兴趣-社会型"},
                        {"label": "职业兴趣-事业型"}, {"label": "职业兴趣-常规型"}]},
        {"id": "C02", "kind": KIND_ASSET, "fn": "interest_triangle",
         "q": "兴趣有没有能力与人格的三角印证？",
         "indicators": [{"label": "职业兴趣-现实型"}, {"label": "职业兴趣-研究型"},
                        {"label": "职业兴趣-艺术型"}, {"label": "职业兴趣-社会型"},
                        {"label": "职业兴趣-事业型"}, {"label": "职业兴趣-常规型"},
                        {"label": "能力优势-逻辑数学能力"}, {"label": "能力优势-空间能力"},
                        {"label": "能力优势-音乐能力"}, {"label": "能力优势-身体运动能力"},
                        {"label": "能力优势-人际关系能力"},
                        {"label": "人格-开放性"}, {"label": "人格-宜人性"},
                        {"label": "人格-外倾性"}, {"label": "人格-责任心"}]},
        {"id": "C03", "kind": KIND_ASSET, "fn": "creativity",
         "q": "创造表达是否有充足的资产支撑？",
         "indicators": [{"label": "人格-开放性"}, {"label": "职业兴趣-艺术型"},
                        {"label": "能力优势-音乐能力"},
                        {"order_value": "创造发明"}, {"order_value": "美的追求"}]},
        {"id": "C04", "kind": KIND_LABEL, "fn": "value_orientation",
         "q": "职业价值观导向分型（前五排序）",
         "indicators": [{"order_value": v} for v in
                        ("创造发明", "独立自主", "美的追求", "智力激发", "利他助人",
                         "成就感", "管理权力", "工作环境", "同事关系", "上司关系",
                         "多样变化", "经济报酬", "安全稳定", "声望地位", "生活方式")]},
        {"id": "C05", "kind": KIND_ASSET, "fn": "career_alignment",
         "q": "兴趣 × 能力 × 价值观三者是否对齐？",
         "indicators": [{"label": "职业兴趣-研究型"}, {"label": "职业兴趣-艺术型"},
                        {"label": "职业兴趣-社会型"}, {"label": "职业兴趣-事业型"},
                        {"label": "职业兴趣-常规型"},
                        {"label": "能力优势-逻辑数学能力"}, {"label": "能力优势-音乐能力"},
                        {"label": "能力优势-人际关系能力"},
                        {"label": "人格-开放性"}, {"label": "人格-宜人性"},
                        {"label": "人格-外倾性"}, {"label": "人格-责任心"},
                        {"order_value": "智力激发"}, {"order_value": "创造发明"},
                        {"order_value": "美的追求"}, {"order_value": "多样变化"},
                        {"order_value": "利他助人"}, {"order_value": "同事关系"},
                        {"order_value": "成就感"}, {"order_value": "声望地位"},
                        {"order_value": "管理权力"}, {"order_value": "安全稳定"},
                        {"order_value": "工作环境"}]},
    ]},
    {"dim": "跨维度", "groups": [
        {"id": "K01", "kind": KIND_RISK, "fn": "body_drag",
         "q": "身体状态是否在拖垮情绪或学习？",
         "indicators": [{"label": "体质健康-睡眠习惯"}, {"label": "体质健康-饮食习惯"},
                        {"label": "体质健康-运动习惯"},
                        {"label": "情绪稳定性-焦虑安详"}, {"label": "自我概念-情绪状态"},
                        {"label": "认知能力-注意力"}, {"label": "认知能力-加工速度"}]},
        {"id": "K02", "kind": KIND_BIPOLAR, "fn": "support_system",
         "q": "社会支持系统能否承接这个孩子？",
         "indicators": [{"label": "依恋关系-信任-母亲"}, {"label": "依恋关系-信任-父亲"},
                        {"label": "依恋关系-信任-同伴"}, {"label": "依恋关系-沟通-母亲"},
                        {"label": "依恋关系-沟通-父亲"}, {"label": "依恋关系-沟通-同伴"},
                        {"label": "依恋关系-亲近-母亲"}, {"label": "依恋关系-亲近-父亲"},
                        {"label": "依恋关系-亲近-同伴"},
                        {"label": "人格-外倾性"}, {"label": "人格-宜人性"}]},
        {"id": "K03", "kind": KIND_LABEL, "fn": "structure_tool",
         "q": "结构化工具（如「一表人才」）对此生是否对路？",
         "indicators": [{"label": "人格-责任心"}, {"label": "自驱力-自主性"},
                        {"label": "职业兴趣-常规型"}, {"order_value": "安全稳定"}]},
        {"id": "K04", "kind": KIND_RISK, "fn": "disengagement",
         "q": "是否接近「投入不足 / 躺平」模型？",
         "indicators": [{"label": "情绪稳定性-抑郁愉快"},
                        {"label": "自我概念-能力与学校表现"},
                        {"label": "自驱力-自主性"}, {"label": "学习动机-深层动机"}]},
    ]},
]

FRAMEWORK_FNS = {g["id"]: g["fn"]
                 for dim in Y4_FRAMEWORK for g in dim["groups"]}


# ── 分组构建（与 E4 build_framework_groups 同构）──────────────────
def _build_groups(eval_items: List[Dict[str, Any]]
                  ) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    order_items = [it for it in eval_items if it.get("eval_source") == "原始排序"]
    by_label: Dict[str, Dict[str, Any]] = {}
    for it in eval_items:
        by_label.setdefault(er._norm_framework_label(it.get("label", "")), it)

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

    def _synth_order(val: str) -> Optional[Dict[str, Any]]:
        src = order_by_value.get(val)
        if not src:
            return None
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
        return {
            "code": f"ORDERPOS:{val}",
            "label": f"{family_short}·{val}排序位置",
            "raw_value": f"第{pos}位/共{total}",
            "eval_value": "",
            "unit": "",
            "eval_source": "待判定",
            "dimension": src.get("dimension", ""),
            "data_bias": er.normalize_bias(src.get("data_bias", "正常")),
        }

    # 共享索引补 ORDER:值 → 合成位置项（判定函数与分组解析共用）
    for val in order_by_value:
        synth = _synth_order(val)
        if synth:
            by_label[f"ORDER:{val}"] = synth

    groups: List[Dict[str, Any]] = []
    for dim_def in Y4_FRAMEWORK:
        dim = dim_def["dim"]
        for g in dim_def["groups"]:
            entries: List[Dict[str, Any]] = []
            for ref in g["indicators"]:
                if "order_value" in ref:
                    synth = by_label.get(f"ORDER:{ref['order_value']}")
                    if synth is not None:
                        entries.append(synth)
                else:
                    it = by_label.get(er._norm_framework_label(ref["label"]))
                    if it is not None:
                        entries.append(it)
            groups.append({"dim": dim, "id": g["id"], "kind": g["kind"],
                           "q": g["q"], "items": entries})
    return groups, by_label


# ── 共享信号 ──────────────────────────────────────────────────────
def _anxiety_signal(im: Dict[str, Dict[str, Any]]) -> Tuple[str, List[Dict[str, str]]]:
    """焦虑互验：两项同时成立=PROBLEM；单项=WATCH；都无=NEUTRAL。"""
    rows: List[Dict[str, str]] = []
    states: List[str] = []
    ax = im.get("情绪稳定性-焦虑安详")
    if ax is not None:
        st = er._st_emotion_sub(_ev(ax))
        rows.append(_row(ax, st))
        states.append(st)
    em = im.get("自我概念-情绪状态")
    if em is not None:
        st = er._st_self_concept(_ev(em))
        rows.append(_row(em, st, "相互验证"))
        states.append(st)
    if not states:
        return NEUTRAL, rows
    if all(s == PROBLEM for s in states):
        return PROBLEM, rows
    if PROBLEM in states:
        return WATCH, rows
    return HEALTHY, rows


def _body_grade_states(im: Dict[str, Dict[str, Any]]
                       ) -> Dict[str, Tuple[str, str, Dict[str, Any]]]:
    """睡眠/饮食/运动 → (状态, 评级词, item)。"""
    out: Dict[str, Tuple[str, str, Dict[str, Any]]] = {}
    for key, name in (("体质健康-睡眠习惯", "睡眠"),
                      ("体质健康-饮食习惯", "饮食"),
                      ("体质健康-运动习惯", "运动")):
        it = im.get(key)
        word = _grade_word_of(im, key)
        st = _grade_state(word) if word else NEUTRAL
        out[name] = (st, word, it)
    return out


# ── 心力判定 ──────────────────────────────────────────────────────
def _fn_anxiety(items, im, ctx):
    state, rows = _anxiety_signal(im)
    summary = "焦虑状态（两项指标相互验证成立）" if state == PROBLEM else \
              ("有焦虑信号，需另一指标验证" if state == WATCH else "未见焦虑状态")
    return _v(state, summary, rows)


def _fn_anxiety_sources(items, im, ctx):
    rows: List[Dict[str, str]] = []
    tags: List[str] = []

    beh = im.get("自我概念-行为表现")
    if beh is not None:
        st = er._st_self_concept(_ev(beh))
        rows.append(_row(beh, st))
        if st == PROBLEM:
            tags.append("行为表现焦虑（常被批评/否定的可能）")

    school = im.get("自我概念-能力与学校表现")
    se = im.get("学习动机-自我效能感")
    for it in (school, se):
        if it is not None:
            st = er._st_self_concept(_ev(it)) if it is school else er._st_norm(_ev(it))
            rows.append(_row(it, st))
    if (school is not None and er._st_self_concept(_ev(school)) == PROBLEM) or \
       (se is not None and er._st_norm(_ev(se)) == PROBLEM):
        tags.append("学业焦虑（在校表现评价或学习自信偏低）")

    bmi = im.get("体质健康-BMI")
    body = im.get("自我概念-躯体外貌")
    bmi_word = _grade_word_of(im, "体质健康-BMI")
    body_st = er._st_self_concept(_ev(body)) if body is not None else NEUTRAL
    if body is not None:
        rows.append(_row(body, body_st))
    if bmi is not None:
        bmi_bad = bool(bmi_word) and not any(k in bmi_word for k in ("正常", "标准", "健康", "理想"))
        rows.append(_row(bmi, WATCH if bmi_bad else NEUTRAL, bmi_word or ""))
    if body_st == PROBLEM or (bool(bmi_word)
                              and not any(k in bmi_word for k in ("正常", "标准", "健康", "理想"))):
        tags.append("容貌 / 躯体焦虑（身体意象或 BMI 评级偏离）")

    peer_keys = ("依恋关系-信任-同伴", "依恋关系-沟通-同伴", "依恋关系-亲近-同伴",
                 "自我概念-合群")
    peer_low = False
    for key in peer_keys:
        it = im.get(key)
        if it is None:
            continue
        if "合群" in key:
            st = er._st_self_concept(_ev(it))
        else:
            st = PROBLEM if _ev(it) == "偏低" else (HEALTHY if _ev(it) == "高" else NEUTRAL)
        rows.append(_row(it, st))
        if st == PROBLEM:
            peer_low = True
    if peer_low:
        tags.append("同伴关系焦虑（合群或同伴依恋有偏低项）")

    parent_low = False
    for key in ("依恋关系-信任-母亲", "依恋关系-信任-父亲",
                "依恋关系-沟通-母亲", "依恋关系-沟通-父亲"):
        it = im.get(key)
        if it is None:
            continue
        st = PROBLEM if _ev(it) == "偏低" else (HEALTHY if _ev(it) == "高" else NEUTRAL)
        rows.append(_row(it, st))
        if st == PROBLEM:
            parent_low = True
    if parent_low:
        tags.append("父母关系焦虑（对父母的信任或沟通有偏低项）")

    premise = "前置：焦虑状态成立时再按这些方向访谈确认" if not tags else ""
    summary = "焦虑源候选：" + "；".join(tags) if tags else "未见明确的焦虑源指标组合"
    if premise:
        summary += "（" + premise + "）"
    return _v(NEUTRAL, summary, rows, tags=tags or ["暂无命中：焦虑源需访谈确认"])


def _fn_emotional_outlets(items, im, ctx):
    rows: List[Dict[str, str]] = []
    channel_keys = [f"依恋关系-{part}-{who}"
                    for who in ("母亲", "父亲", "同伴")
                    for part in ("信任", "沟通", "亲近")]
    low = high = 0
    for key in channel_keys:
        it = im.get(key)
        if it is None:
            continue
        ev = _ev(it)
        st = PROBLEM if ev == "偏低" else (HEALTHY if ev == "高" else NEUTRAL)
        rows.append(_row(it, st))
        if ev == "偏低":
            low += 1
        elif ev == "高":
            high += 1

    personality_high = False
    for key in ("人格-外倾性", "人格-宜人性"):
        it = im.get(key)
        if it is None:
            continue
        ev = _ev(it)
        st = er._st_personality(ev)
        rows.append(_row(it, st, "外倾高=适合主动倾诉；宜人高=容易有人主动找他聊"
                              if key.endswith("外倾性") else ""))
        if ev in ("高", "较好"):
            personality_high = True

    ax_state, _ = ctx["anxiety"]
    if ax_state in (PROBLEM, WATCH):
        if low >= 4 and high == 0 and not personality_high:
            return _v(PROBLEM,
                     "焦虑成立且父母、同伴通道普遍偏低，又缺少主动求助的人格通道：情绪缺少排解对象",
                     rows, force_strong=False)
        if high >= 1:
            who = [r["label"] for r in rows if r["state"] == HEALTHY]
            return _v(WATCH, "焦虑成立，但仍有可用的排解通道：" + "、".join(who[:3]), rows)
        return _v(WATCH, "焦虑成立，排解通道偏弱，需要顾问协助建立表达场景", rows)
    # 风险侧不成立 → 资产侧
    if high >= 3:
        return _v(HEALTHY, "依恋通道普遍畅通，社会支持是明确的韧性资产",
                  rows, asset_strong=True)
    return _v(NEUTRAL, "未见焦虑，排解通道无明显异常", rows)


def _fn_depression(items, im, ctx):
    rows: List[Dict[str, str]] = []
    dp = im.get("情绪稳定性-抑郁愉快")
    dp_ev = _ev(dp)
    dp_raw = _num(dp)
    dp_state = er._st_emotion_sub(dp_ev) if dp is not None else NEUTRAL
    if dp is not None:
        note = ""
        if dp_raw is not None and dp_raw >= 9:
            note = "原始分接近量表顶端，档位标签不放大解读"
        rows.append(_row(dp, dp_state, note))

    body = _body_grade_states(im)
    body_bad = False
    body_ok = True
    for name in ("睡眠", "饮食"):
        st, word, it = body[name]
        if it is not None:
            rows.append(_row(it, st, f"评级:{word}" if word else ""))
            if st == PROBLEM:
                body_bad = True
            if st in (PROBLEM, WATCH):
                body_ok = False

    holland_states: List[str] = []
    holland_high = False
    for t in ("现实型", "研究型", "艺术型", "社会型", "事业型", "常规型"):
        it = im.get(f"职业兴趣-{t}")
        if it is None:
            continue
        ev = _ev(it)
        st = er._st_norm(ev)
        rows.append(_row(it, st))
        holland_states.append(st)
        if ev == "高":
            holland_high = True

    academic_low = 0
    for key in ("自我概念-能力与学校表现", "学习动机-自我效能感", "自驱力-自主性"):
        it = im.get(key)
        if it is None:
            continue
        st = er._st_norm(_ev(it)) if "自驱力" in key or "动机" in key \
            else er._st_self_concept(_ev(it))
        rows.append(_row(it, st))
        if st == PROBLEM:
            academic_low += 1

    cond_dp = dp_state == PROBLEM and (dp_raw is None or dp_raw < 9)
    cond_no_interest = not holland_high
    hits = sum([cond_dp, body_bad, cond_no_interest])

    if cond_dp and hits >= 2:
        return _v(PROBLEM,
                  "三条风险证据命中两条以上，提示风险并建议专业评估（不做病理判断）",
                  rows, force_strong=True)
    if body_bad and cond_no_interest and not cond_dp:
        return _v(PROBLEM, "身体行为评级偏弱且兴趣无高分段，情绪基础需要支持", rows)
    if dp_state in (PROBLEM, WATCH) and body_ok and holland_high:
        tail = "；同时学业自评三项均偏低，更可能是学业占满、兴趣被挤占的「不愉快」" \
            if academic_low >= 3 else ""
        return _v(OBSERVED,
                  "情绪分偏低但睡眠饮食评级正常、兴趣有高分段：优先按「不愉快/假抑郁」理解" + tail,
                  rows)
    if dp_state == HEALTHY:
        return _v(HEALTHY, "情绪状态不低，睡眠饮食与兴趣共同支撑", rows)
    return _v(NEUTRAL, "证据不足或互相矛盾，暂不下结论", rows)


def _overall_level(im: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """自我概念整体档位（052，归一化后键为「自我概念整体」），兼容 051 原值。"""
    return im.get("自我概念整体") or im.get("自我概念整体档位") \
        or im.get("自我概念整体值")


def _fn_inferiority(items, im, ctx):
    rows: List[Dict[str, str]] = []
    zz = im.get("情绪稳定性-自卑自尊")
    zz_state = NEUTRAL
    if zz is not None:
        zz_raw = _num(zz)
        zz_state = er._st_emotion_sub(_ev(zz))
        note = ""
        if zz_raw is not None and zz_raw >= 9 and zz_state == PROBLEM:
            zz_state = NEUTRAL
            note = "原始分接近量表顶端，不构成自卑证据"
        rows.append(_row(zz, zz_state, note))

    sc = _overall_level(im)
    sc_state = NEUTRAL
    if sc is not None:
        val = ((sc.get("eval_value") or sc.get("raw_value") or "") + "").strip()
        if "低" in val:
            sc_state = PROBLEM
        elif "中" in val:
            sc_state = OBSERVED
        elif "高" in val:
            sc_state = HEALTHY
        rows.append(_row(sc, sc_state))

    sv = im.get("自驱力-胜任感")
    sv_state = NEUTRAL
    if sv is not None:
        sv_state = er._st_norm(_ev(sv), mid=OBSERVED)
        rows.append(_row(sv, sv_state))

    low_hits = sum(s == PROBLEM for s in (zz_state, sc_state, sv_state))
    if low_hits >= 2:
        severe = zz is not None and _ev(zz) == "需特殊关注" and (_num(zz) or 9) < 5
        return _v(PROBLEM, "多项低档同时成立，整体自卑证据成立", rows,
                  force_strong=severe)
    if low_hits == 1:
        return _v(WATCH, "单一指标偏低，整体自卑证据不足，先关注", rows)
    return _v(NEUTRAL, "未见整体自卑证据", rows)


def _fn_self_esteem(items, im, ctx):
    rows: List[Dict[str, str]] = []
    zz = im.get("情绪稳定性-自卑自尊")
    sc = _overall_level(im)
    beh = im.get("自我概念-行为表现")

    zz_raw = _num(zz)
    zz_ev = _ev(zz)
    sc_word = ((sc.get("eval_value") or sc.get("raw_value") or "") if sc else "") or ""
    beh_st = er._st_self_concept(_ev(beh)) if beh is not None else NEUTRAL

    for it, st, note in (
        (zz, er._st_emotion_sub(zz_ev) if zz is not None else NEUTRAL, ""),
        (sc, (PROBLEM if "低" in sc_word else HEALTHY if "高" in sc_word else NEUTRAL)
            if sc is not None else NEUTRAL, ""),
        (beh, beh_st, "行为表现是锚定值，用于验证自我评价是否落地"),
    ):
        if it is not None:
            rows.append(_row(it, st, note))

    zz_high = zz_raw is not None and zz_raw >= 9.5
    zz_low = zz_ev in ("需关注", "需特殊关注") and (zz_raw is None or zz_raw < 9)
    sc_high = "高" in sc_word
    sc_low = "低" in sc_word

    if zz_high and sc_high and beh_st in (HEALTHY,):
        return _v(HEALTHY, "高自尊与整体自我评价、行为锚定一致，是需要保护的扎实基础",
                  rows, asset_strong=True)
    if zz_low and sc_high:
        return _v(WATCH, "自尊偏低但整体自我评价偏高：可能因「乖 / 听话」获得高评价，需当面核实",
                  rows)
    if zz_high and beh_st == PROBLEM:
        return _v(WATCH, "高自尊但行为表现锚定偏低：关注抗挫承载，避免盲目自信", rows)
    if zz_low and sc_low:
        severe = zz_ev == "需特殊关注" and (zz_raw is None or zz_raw < 5)
        return _v(PROBLEM, "自尊与整体自我评价双低", rows, force_strong=severe)
    return _v(NEUTRAL, "自尊结构无明显错位", rows)


def _fn_parent_attachment(items, im, ctx):
    return er._v_e1_parent(items)


def _fn_sensitivity(items, im, ctx):
    rows: List[Dict[str, str]] = []
    nz = im.get("人格-神经质")
    wq = im.get("人格-外倾性")
    intro = im.get("能力优势-内省能力")
    reason = im.get("认知能力-推理能力")

    nz_raw, wq_raw = _num(nz), _num(wq)
    if nz is not None:
        if nz_raw is not None and nz_raw > 4:
            rows.append(_row(nz, PROBLEM, f"强信号（{nz_raw:g}>4）"))
            nz_state = PROBLEM
        elif nz_raw is not None and nz_raw > 3.5:
            rows.append(_row(nz, PROBLEM, f"弱信号（{nz_raw:g}，3.5-4）"))
            nz_state = PROBLEM
        else:
            rows.append(_row(nz, HEALTHY))
            nz_state = HEALTHY
    else:
        nz_state = NEUTRAL
    introvert = wq_raw is not None and wq_raw < 2.5
    if wq is not None:
        rows.append(_row(wq, WATCH if introvert else NEUTRAL,
                         f"内向倾向（{wq_raw:g}<2.5），加重因素" if introvert else ""))

    intro_b = _band3(intro)
    reason_b = _band3(reason)
    for it, b in ((intro, intro_b), (reason, reason_b)):
        if it is None:
            continue
        rows.append(_row(it, HEALTHY if b == "high" else NEUTRAL))
    resolve_ok = intro_b == "high" and reason_b == "high"

    if nz_state == PROBLEM and nz_raw is not None and nz_raw > 4:
        return _v(PROBLEM, "神经质强信号，高敏感内耗风险高", rows, force_strong=True)
    if nz_state == PROBLEM:
        if introvert:
            return _v(PROBLEM, "弱信号叠加内向倾向，高敏感内耗可能成立", rows)
        if resolve_ok:
            return _v(WATCH, "弱信号成立，但内省与推理双高：能靠逻辑想通，内耗可解", rows)
        return _v(WATCH, "神经质弱信号，保留「可能」，结合访谈确认", rows)
    if resolve_ok:
        return _v(HEALTHY, "无高敏感信号，且内省与推理双高：反思能力是突出资产",
                  rows, asset_strong=True)
    return _v(NEUTRAL, "无显著高敏感信号", rows)


def _fn_helplessness(items, im, ctx):
    rows: List[Dict[str, str]] = []
    tags: List[str] = []

    ax = im.get("情绪稳定性-焦虑安详")
    sc = _overall_level(im)
    zz = im.get("情绪稳定性-自卑自尊")
    se = im.get("学习动机-自我效能感")
    a_hits = 0
    for it, kind in ((ax, "emo"), (sc, "sc"), (zz, "emo"), (se, "norm")):
        if it is None:
            continue
        if kind == "emo":
            st = er._st_emotion_sub(_ev(it))
        elif kind == "sc":
            word = str(it.get("eval_value") or it.get("raw_value") or "")
            st = PROBLEM if "低" in word else NEUTRAL
        else:
            st = er._st_norm(_ev(it))
        rows.append(_row(it, st))
        if st == PROBLEM:
            a_hits += 1
    if a_hits >= 2:
        tags.append("努力无回报型：焦虑、低自我评价、低效能感多项同时成立")

    auto = im.get("自驱力-自主性")
    resp = im.get("人格-责任心")
    auto_b = _band3(auto)
    resp_b = _band3(resp)
    for it, b in ((auto, auto_b), (resp, resp_b)):
        if it is not None:
            rows.append(_row(it, PROBLEM if b == "low" else NEUTRAL))
    if auto_b == "low" and resp_b == "low":
        tags.append("生活被安排型：自主性与责任心双低，时间被外部结构占满")

    parent_low = 0
    for key in ("依恋关系-信任-母亲", "依恋关系-信任-父亲",
                "依恋关系-沟通-母亲", "依恋关系-沟通-父亲"):
        it = im.get(key)
        if it is None:
            continue
        st = PROBLEM if _ev(it) == "偏低" else (HEALTHY if _ev(it) == "高" else NEUTRAL)
        rows.append(_row(it, st))
        if st == PROBLEM:
            parent_low += 1
    if parent_low >= 1:
        tags.append("关系层面无力：对父母的信任/沟通有偏低项，缺少 ownership 基础")

    mindset = im.get("思维模式") or im.get("思维模式结果")
    if mindset is not None:
        word = str(mindset.get("raw_value") or mindset.get("eval_value") or "")
        fixed = "固定" in word
        rows.append(_row(mindset, WATCH if fixed else NEUTRAL, word))
        if fixed:
            tags.append("思维模式偏固定型（背景信号，常见于高压或抗争关系）")

    summary = "无力感分型：" + "；".join(tags) if tags else "未见典型无力感组合"
    return _v(NEUTRAL, summary, rows, tags=tags or ["暂无命中：结合访谈判断"])


# ── 精力判定 ──────────────────────────────────────────────────────
def _body_rows(im: Dict[str, Any], include_appearance: bool
               ) -> Tuple[List[Dict[str, str]], List[str], List[str], List[str]]:
    rows: List[Dict[str, str]] = []
    bad, mid, excellent = [], [], []
    body = _body_grade_states(im)
    for name in ("睡眠", "饮食", "运动"):
        st, word, it = body[name]
        if it is None:
            continue
        rows.append(_row(it, st, f"评级:{word}" if word else ""))
        if st == PROBLEM:
            bad.append(name)
        elif st == WATCH:
            mid.append(name)
        elif word and ("优" in word or "高" in word):
            excellent.append(name)
    if include_appearance:
        ap = im.get("自我概念-躯体外貌")
        if ap is not None:
            st = er._st_self_concept(_ev(ap))
            rows.append(_row(ap, st))
    return rows, bad, mid, excellent


def _fn_body_behaviors(items, im, ctx):
    rows, bad, mid, excellent = _body_rows(im, True)
    if bad:
        strong = len(bad) >= 2
        return _v(PROBLEM, f"{'、'.join(bad)}评级偏弱，身体行为需要支持", rows,
                  force_strong=strong)
    if mid:
        return _v(WATCH, f"{'、'.join(mid)}评级中等：频率、强度、持续性或愉悦感某一环偏弱", rows)
    if not rows:
        return _v(NEUTRAL, "体质健康数据不足", rows)
    strong = len(excellent) >= 2
    return _v(HEALTHY, "睡眠、饮食、运动行为整体健康", rows, asset_strong=strong)


def _fn_body_capacity(items, im, ctx):
    rows, bad, mid, excellent = _body_rows(im, False)
    if bad:
        return _v(PROBLEM, f"{'、'.join(bad)}评级偏弱，白天精力与情绪稳定的基础不足", rows)
    if mid:
        return _v(WATCH, f"{'、'.join(mid)}评级中等，白天承载可能受限", rows)
    if not rows:
        return _v(NEUTRAL, "体质健康数据不足", rows)
    if len(excellent) >= 2:
        return _v(HEALTHY, "身体储备充足，是学习承载与情绪稳定的扎实基础",
                  rows, asset_strong=True)
    return _v(NEUTRAL, "身体行为基本健康，未构成突出资产或问题", rows)


# ── 学习力判定（认知/执行类复用 E4 成熟规则）────────────────────
def _wrap_er(v: Dict[str, Any], asset: Optional[bool] = None,
             force_strong: bool = False) -> Dict[str, Any]:
    """把 E4 verdict 转为 Y4 verdict，统一名单语义。"""
    out = _v(v["state"], v["summary"], v.get("items") or [],
             force_strong=force_strong)
    if asset is not None:
        out["asset_strong"] = asset
    elif v["state"] == HEALTHY:
        # 与 E4 强潜能同口径：≥2 项高/较强，或单项「高」
        strong_rows = [r for r in v.get("items", [])
                       if r.get("state") == HEALTHY and r.get("eval") in STRONG_EVALS]
        out["asset_strong"] = len(strong_rows) >= 2 or \
            (len(v.get("items", [])) == 1 and
             (v["items"][0].get("eval") or "") == "高")
    return out


def _fn_cog_input(items, im, ctx):
    return _wrap_er(er._v_e3_input(items))


def _fn_cog_default(items, im, ctx):
    return _wrap_er(er._v_default_e3(items))


def _fn_focus_combo(items, im, ctx):
    inh = im.get("执行功能-抑制控制")
    perc = im.get("认知能力-感知觉")
    attn = im.get("认知能力-注意力")
    rows: List[Dict[str, str]] = []
    for it in (inh, perc, attn):
        if it is None:
            continue
        st = er._st_percentile(_ev(it))
        note = it.get("trait_note") if it.get("trait_label") else ""
        rows.append(_row(it, st, note or ""))

    a_low = attn is not None and er._st_percentile(_ev(attn)) == PROBLEM
    p_strong = perc is not None and perc.get("trait_label") == "强特质"
    a_weak = attn is not None and attn.get("trait_label") == "相对弱特质"
    highs = [it for it in (inh, perc, attn)
             if it is not None and _ev(it) in ("高", "较好")]

    if a_low:
        return _v(PROBLEM, "注意力常模百分位偏低，专注力本身是弱项", rows)
    if p_strong and a_weak:
        return _v(WATCH, "组内错位：输入端敏锐但注意力相对跟不上，易分心/粗心，需管理学习环境",
                  rows)
    if len(highs) == 3 and not p_strong and not a_weak:
        return _v(HEALTHY, "抑制控制、感知觉、注意力三项都强：专注稳定、不易粗心",
                  rows, asset_strong=True)
    if not rows:
        return _v(NEUTRAL, "数据不足", rows)
    return _v(NEUTRAL, "无明显粗心分心组合，也未构成突出优势", rows)


def _fatigue_verdict(im: Dict[str, Any], key: str, name: str) -> Dict[str, Any]:
    it = im.get(key)
    if it is None:
        return _v(NEUTRAL, f"{name}数据不足", [])
    bias = er.normalize_bias(it.get("data_bias", "正常"))
    st = er._st_percentile(_ev(it))
    if st == PROBLEM and bias == "低估":
        return _v(NEUTRAL, f"{name}偏低但专家确认为低估，真实水平更好，不按弱项处理",
                  [_row(it, NEUTRAL, "专家确认：低估")])
    if st != PROBLEM and bias == "高估":
        return _v(WATCH, f"{name}档位不低但专家确认为高估，需要按更低的真实水平理解",
                  [_row(it, WATCH, "专家确认：高估")])
    if st == PROBLEM:
        return _v(OBSERVED,
                  f"{name}百分位偏低；该题处于施测末段，可能受疲劳影响，建议与老师/家长确认后定性",
                  [_row(it, OBSERVED, "末段疲劳，把握度说明")])
    if st == HEALTHY:
        strong = _ev(it) == "高"
        return _v(HEALTHY, f"{name}百分位{_ev(it)}", [_row(it, HEALTHY)],
                  asset_strong=strong)
    return _v(NEUTRAL, f"{name}百分位{_ev(it) or '缺失'}", [_row(it, NEUTRAL)])


def _fn_fatigue_wm(items, im, ctx):
    return _fatigue_verdict(im, "执行功能-工作记忆", "工作记忆")


def _fn_fatigue_flex(items, im, ctx):
    return _fatigue_verdict(im, "执行功能-认知灵活性", "认知灵活性")


def _fn_confidence_gap(items, im, ctx):
    se = im.get("学习动机-自我效能感")
    sc = im.get("自我概念-能力与学校表现")
    rows: List[Dict[str, str]] = []
    sb = _band3(se)
    cb = _band3(sc)
    for it, b in ((se, sb), (sc, cb)):
        if it is None:
            continue
        st = PROBLEM if b == "low" else (HEALTHY if b == "high" else NEUTRAL)
        rows.append(_row(it, st))
    if sb is None or cb is None:
        return _v(NEUTRAL, "数据不足，无法判断自信与表现是否脱钩", rows)
    if sb == "low" and cb == "low":
        return _v(PROBLEM, "学习自信与在校表现评价双低", rows)
    if sb == "low" and cb in ("mid", "high"):
        return _v(WATCH, "低估自己：对取得好成绩没信心，但在校表现评价并不低", rows)
    if sb in ("mid", "high") and cb == "low":
        return _v(WATCH, "自我认知偏差：效能感不低但在校表现评价偏低（高估）", rows)
    if sb == "high" and cb == "high":
        return _v(HEALTHY, "学习自信与在校表现相互印证且都强", rows, asset_strong=True)
    return _v(NEUTRAL, "自信与表现基本匹配，无明显脱钩", rows)


def _fn_motivation_quad(items, im, ctx):
    v = er._v_e3_motivation(items)
    asset = v["state"] == HEALTHY
    return _wrap_er(v, asset=asset)


def _fn_success_drive(items, im, ctx):
    v = er._v_e3_success_drive(items)
    tags = []
    for r in v.get("items", []):
        if r.get("state") == HEALTHY and "第" in (r.get("note") or ""):
            tags.append(f"{r['label'].split('·')[0]}进入前五（{r['note']}）")
    return _v(NEUTRAL, v["summary"], v.get("items") or [],
              tags=tags or ["成就感 / 声望地位未进入价值观前五"])


def _fn_deep_motivation(items, im, ctx):
    it = im.get("学习动机-深层动机")
    if it is None:
        return _v(NEUTRAL, "深层动机数据不足", [])
    b = _band3(it)
    if b == "low":
        return _v(PROBLEM, "深层动机偏低，对学习本身的兴趣不足", [_row(it, PROBLEM)])
    if b == "high":
        return _v(HEALTHY, "深层动机强", [_row(it, HEALTHY)], asset_strong=True)
    return _v(NEUTRAL, f"深层动机{b and '中等' or '数据不足'}", [_row(it, NEUTRAL)])


def _fn_inner_drive(items, im, ctx):
    return _wrap_er(er._v_e3_inner_drive(items))


def _fn_mm_logic(items, im, ctx):
    v = er._v_e4_mismatch_logic(items)
    return _mm_asset_wrap(v, items)


def _fn_mm_spatial(items, im, ctx):
    v = er._v_e4_mismatch_spatial(items)
    return _mm_asset_wrap(v, items)


def _fn_mm_deep(items, im, ctx):
    return _wrap_er(er._v_e4_mismatch_deep(items))


def _fn_mm_surface(items, im, ctx):
    return _wrap_er(er._v_e4_mismatch_surface(items))


def _mm_asset_wrap(v: Dict[str, Any], items: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = _wrap_er(v)
    if v["state"] == HEALTHY and len(items) == 2 and all(_band3(it) == "high" for it in items):
        out["asset_strong"] = True
    return out


def _fn_strategy_level(items, im, ctx):
    v = er._v_e4_strategy_level(items)
    asset = False
    if v["state"] == HEALTHY:
        dm = im.get("学习方法与策略-学习深层方法与策略")
        sm = im.get("学习方法与策略-学习表面方法与策略")
        asset = _band3(dm) == "high" and _band3(sm) == "high"
    return _wrap_er(v, asset=asset if v["state"] == HEALTHY else None)


def _fn_planning(items, im, ctx):
    rows: List[Dict[str, str]] = []
    resp = im.get("人格-责任心")
    auto = im.get("自驱力-自主性")
    rb, ab = _band3(resp), _band3(auto)
    for it, b, is_personality in ((resp, rb, True), (auto, ab, False)):
        if it is None:
            continue
        st = er._st_personality(_ev(it)) if is_personality else er._st_norm(_ev(it))
        rows.append(_row(it, st))
    if rb is None or ab is None:
        return _v(NEUTRAL, "计划性数据不足", rows)
    if rb == "low" or ab == "low":
        severe = rb == "low" and _ev(resp) in ("明显偏低", "严重偏低")
        if rb != "low" and ab == "low":
            return _v(WATCH, "有责任感但缺乏主动规划（不等同于计划性差）", rows)
        return _v(PROBLEM, "责任心与自主性至少一项偏低，计划性缺少支撑", rows,
                  force_strong=severe)
    if rb == "high" and ab == "high":
        return _v(HEALTHY, "既负责任又能自主规划", rows, asset_strong=True)
    return _v(NEUTRAL, "计划性中等，无明显错位", rows)


def _fn_metacognition(items, im, ctx):
    v = er._v_e4_metacognition(items)
    return _wrap_er(v, asset=(v["state"] == HEALTHY))


# ── 生涯力判定 ────────────────────────────────────────────────────
_HOLLAND = ("现实型", "研究型", "艺术型", "社会型", "事业型", "常规型")

# 霍兰德类型 → (能力优势 key, 人格 keys)
_TRIANGLE_MAP = {
    "事业型": ("能力优势-人际关系能力", ("人格-外倾性", "人格-宜人性")),
    "研究型": ("能力优势-逻辑数学能力", ()),
    "现实型": ("能力优势-空间能力", ()),
    "艺术型": ("能力优势-音乐能力", ("人格-开放性",)),
    "社会型": ("能力优势-人际关系能力", ("人格-宜人性",)),
    "常规型": (None, ("人格-责任心",)),
}


def _holland_rows(im: Dict[str, Dict[str, Any]]) -> Tuple[List[Dict[str, str]], Dict[str, str]]:
    # 霍兰德低分只代表「不感兴趣」，不是弱项：高=健康，其余一律中性展示
    rows: List[Dict[str, str]] = []
    highs: Dict[str, str] = {}
    for t in _HOLLAND:
        it = im.get(f"职业兴趣-{t}")
        if it is None:
            continue
        ev = _ev(it)
        st = HEALTHY if ev == "高" else NEUTRAL
        rows.append(_row(it, st))
        if ev == "高":
            highs[t] = ev
    return rows, highs


def _fn_interest_structure(items, im, ctx):
    rows: List[Dict[str, str]] = []
    standout = []
    high = []
    for t in _HOLLAND:
        it = im.get(f"职业兴趣-{t}")
        if it is None:
            continue
        raw = _num(it)
        ev = _ev(it)
        st = HEALTHY if ev == "高" else NEUTRAL  # 兴趣低分不是弱项
        note = f"原始分{raw:g}" if raw is not None else ""
        rows.append(_row(it, st, note))
        if raw is not None and raw >= 8:
            standout.append(t)
        elif ev == "高":
            high.append(t)
    if not rows:
        return _v(NEUTRAL, "职业兴趣数据不足", rows)
    if standout:
        return _v(HEALTHY,
                  f"兴趣方向鲜明：{'、'.join(standout)}进入高分段（8分以上），属于突出优势",
                  rows, asset_strong=True)
    if high:
        return _v(HEALTHY, f"有高分兴趣方向（{'、'.join(high)}），但未到突出水平", rows)
    scope = ctx.get("scope")
    if scope == "career":
        return _v(NEUTRAL, "六个类型无高分段、兴趣弥散；高中阶段建议尽快安排结构化探索", rows)
    return _v(NEUTRAL, "兴趣广泛但未聚焦，适合通过课外活动与兴趣班继续广泛探索", rows)


def _triangle_confirm(im: Dict[str, Dict[str, Any]], t: str) -> Tuple[bool, List[str]]:
    ability_key, personality_keys = _TRIANGLE_MAP[t]
    confirm: List[str] = []
    ok = True
    if ability_key:
        ab = _band3(im.get(ability_key))
        if ab == "high":
            confirm.append("能力强匹配")
        elif ab == "low":
            ok = False
        else:
            ok = False
    if personality_keys:
        ph = [_band3(im.get(k)) for k in personality_keys]
        if any(b == "high" for b in ph):
            confirm.append("人格匹配")
        elif all(b != "low" for b in ph) and any(b == "mid" for b in ph):
            ok = False
        elif any(b == "low" for b in ph):
            ok = False
    return ok and bool(confirm), confirm


def _fn_interest_triangle(items, im, ctx):
    rows, highs = _holland_rows(im)
    confirmed = []
    for t in highs:
        ok, confirm = _triangle_confirm(im, t)
        if ok:
            confirmed.append(f"{t}（{'、'.join(confirm)}）")
    # 补行：被印证涉及的能力/人格
    for t in highs:
        ability_key, personality_keys = _TRIANGLE_MAP[t]
        for key in ([ability_key] if ability_key else []) + list(personality_keys):
            it = im.get(key)
            if it is not None and not any(r["label"] == it.get("label") for r in rows):
                rows.append(_row(it, er._st_norm(_ev(it)) if "能力" in key
                                 else er._st_personality(_ev(it))))
    if confirmed:
        return _v(HEALTHY, "兴趣—能力—人格三角印证成立：" + "、".join(confirmed),
                  rows, asset_strong=True)
    if highs:
        return _v(NEUTRAL, "有高分兴趣，但能力或人格佐证不足，保持探索、暂不重投入", rows)
    return _v(NEUTRAL, "无高分兴趣可做三角印证", rows)


def _fn_creativity(items, im, ctx):
    rows: List[Dict[str, str]] = []
    hits = []
    op = im.get("人格-开放性")
    if op is not None:
        b = _band3(op)
        rows.append(_row(op, HEALTHY if b == "high" else NEUTRAL))
        if b == "high":
            hits.append("开放性高")
    art = im.get("职业兴趣-艺术型")
    if art is not None:
        st = er._st_norm(_ev(art))
        rows.append(_row(art, st))
        if _ev(art) == "高":
            hits.append("艺术型兴趣高")
    music = im.get("能力优势-音乐能力")
    if music is not None:
        b = _band3(music)
        rows.append(_row(music, HEALTHY if b == "high" else NEUTRAL))
        if b == "high":
            hits.append("音乐能力强")
    for value in ("创造发明", "美的追求"):
        pos = _order_hit(im, value)
        it = im.get(f"ORDER:{value}")
        if it is not None:
            rows.append(_row(it, HEALTHY if pos else NEUTRAL,
                             f"第{pos}位" if pos else "未进前五"))
            if pos:
                hits.append(f"{value}第{pos}位")
    if len(hits) >= 3:
        return _v(HEALTHY, "创造表达资产充分（" + "、".join(hits) + "）",
                  rows, asset_strong=True)
    if len(hits) == 2:
        return _v(HEALTHY, "有创造力基础但证据不充分：" + "、".join(hits), rows)
    return _v(NEUTRAL, "未见集中的创造表达资产", rows)


_VALUE_TAGS = [
    ("成就认可", ("成就感", "声望地位")),
    ("商业管理", ("经济报酬", "管理权力", "声望地位")),
    ("安全确定", ("安全稳定", "工作环境")),
    ("创造求变", ("创造发明", "多样变化", "美的追求")),
    ("学术智识", ("智力激发",)),
    ("利他服务", ("利他助人",)),
    ("关系归属", ("同事关系", "上司关系")),
    ("独立自主", ("独立自主",)),
    ("生活平衡", ("生活方式",)),
]


def _fn_value_orientation(items, im, ctx):
    rows: List[Dict[str, str]] = []
    for it in items:
        pos = er._order_pos(it) if str(it.get("code", "")).startswith("ORDERPOS:") else None
        top5 = bool(pos and pos <= 5)
        rows.append(_row(it, HEALTHY if top5 else NEUTRAL,
                         f"第{pos}位 · 前五" if top5 else (f"第{pos}位" if pos else "")))
    tags = []
    for tag_name, values in _VALUE_TAGS:
        hits = [v for v in values if _order_hit(im, v)]
        if hits:
            tags.append(f"{tag_name}（{'、'.join(hits)}）")
    return _v(NEUTRAL,
              "价值观导向：" + "；".join(tags) if tags else "职业价值观排序数据不足",
              rows, tags=tags or ["前五排序数据不足"])


# 类型 → 对齐的价值观
_ALIGN_VALUES = {
    "研究型": ("智力激发",),
    "艺术型": ("创造发明", "美的追求", "多样变化"),
    "社会型": ("利他助人", "同事关系"),
    "事业型": ("成就感", "声望地位", "管理权力"),
    "常规型": ("安全稳定", "工作环境"),
}


def _fn_career_alignment(items, im, ctx):
    rows, highs = _holland_rows(im)
    aligned = []
    for t in ("研究型", "艺术型", "社会型", "事业型", "常规型"):
        if t not in highs:
            continue
        ok, _ = _triangle_confirm(im, t)
        if not ok:
            continue
        value_hit = [v for v in _ALIGN_VALUES[t] if _order_hit(im, v)]
        for it in [im.get(f"ORDER:{v}") for v in _ALIGN_VALUES[t]]:
            if it is not None and not any(r["label"] == it.get("label") for r in rows):
                rows.append(_row(it, NEUTRAL))
        if value_hit:
            aligned.append(f"{t} × {'、'.join(value_hit)}")
    scope = ctx.get("scope")
    if aligned:
        tail = "" if scope == "career" else "（初中阶段可直接转化为课外活动 / 兴趣班选择）"
        return _v(HEALTHY, "兴趣、能力与价值观三方对齐：" + "、".join(aligned) + tail,
                  rows, asset_strong=True)
    if scope == "career":
        return _v(NEUTRAL, "三方尚未对齐，生涯方向需要进一步面谈澄清", rows)
    return _v(NEUTRAL, "暂未出现三方对齐，先按兴趣与能力探索课外活动方向", rows)


# ── 跨维度判定 ────────────────────────────────────────────────────
def _fn_body_drag(items, im, ctx):
    rows: List[Dict[str, str]] = []
    body = _body_grade_states(im)
    sleep_bad = body["睡眠"][0] == PROBLEM
    diet_bad = body["饮食"][0] == PROBLEM
    ex_state = body["运动"][0]
    for name in ("睡眠", "饮食", "运动"):
        st, word, it = body[name]
        if it is not None:
            rows.append(_row(it, st, f"评级:{word}" if word else ""))

    ax_state, ax_rows = _anxiety_signal(im)
    rows.extend(ax_rows)

    learn_bad = False
    for key in ("认知能力-注意力", "认知能力-加工速度"):
        it = im.get(key)
        if it is None:
            continue
        st = er._st_percentile(_ev(it))
        rows.append(_row(it, st))
        if st == PROBLEM:
            learn_bad = True

    body_bad = sleep_bad or diet_bad
    if body_bad and (ax_state in (PROBLEM, WATCH) or learn_bad):
        return _v(PROBLEM,
                  "睡眠或饮食评级偏弱，同时情绪或学习端已有信号：身体很可能在拖垮状态，支持顺序应先身体",
                  rows, force_strong=True)
    if body_bad:
        return _v(WATCH, "身体行为评级偏弱，但情绪与认知端暂无联动信号", rows)
    if ex_state == WATCH:
        return _v(NEUTRAL, "睡眠饮食正常、运动评级中等，暂无拖累证据", rows)
    return _v(NEUTRAL, "身体与情绪/学习之间未见拖累关系", rows)


def _fn_support_system(items, im, ctx):
    rows: List[Dict[str, str]] = []
    low = high = trust_high = 0
    for who in ("母亲", "父亲", "同伴"):
        for part in ("信任", "沟通", "亲近"):
            it = im.get(f"依恋关系-{part}-{who}")
            if it is None:
                continue
            ev = _ev(it)
            st = PROBLEM if ev == "偏低" else (HEALTHY if ev == "高" else NEUTRAL)
            rows.append(_row(it, st))
            if ev == "偏低":
                low += 1
            if ev == "高":
                high += 1
                if part == "信任":
                    trust_high += 1

    personality_ok = False
    for key in ("人格-外倾性", "人格-宜人性"):
        it = im.get(key)
        if it is None:
            continue
        b = _band3(it)
        rows.append(_row(it, HEALTHY if b == "high" else NEUTRAL))
        if b == "high":
            personality_ok = True

    if low >= 4 and high == 0 and not personality_ok:
        return _v(PROBLEM,
                  "依恋全面偏低且无主动求助的人格通道：现有支持系统难以承接，需要顾问作为第三方介入",
                  rows, force_strong=True)
    if low >= 2:
        return _v(WATCH, "依恋多个环节偏低，支持系统有缺口", rows)
    if trust_high >= 2 and low == 0:
        return _v(HEALTHY, "父母与同伴信任稳固，支持系统是重要资产",
                  rows, asset_strong=True)
    return _v(NEUTRAL, "支持系统无明显缺口，也未构成突出资产", rows)


def _fn_structure_tool(items, im, ctx):
    rows: List[Dict[str, str]] = []
    tags: List[str] = []
    resp = im.get("人格-责任心")
    auto = im.get("自驱力-自主性")
    cg = im.get("职业兴趣-常规型")
    rb, ab = _band3(resp), _band3(auto)
    cg_b = _band3(cg)
    for it, b in ((resp, rb), (auto, ab), (cg, cg_b)):
        if it is not None:
            rows.append(_row(it, PROBLEM if b == "low" else (HEALTHY if b == "high" else NEUTRAL)))
    safe_pos = _order_hit(im, "安全稳定")
    safe_it = im.get("ORDER:安全稳定")
    if safe_it is not None:
        rows.append(_row(safe_it, HEALTHY if safe_pos else NEUTRAL,
                         f"第{safe_pos}位" if safe_pos else "未进前五"))

    structure_pref = (cg_b in ("high", "mid")) or bool(safe_pos)
    planning_weak = (rb == "low" or ab == "low")
    if rb != "low" and ab == "low" and structure_pref:
        tags.append("结构化工具高度匹配：有责任感、缺主动规划，且偏好可预测结构——「一表人才」类计划表对路")
    elif rb != "low" and ab == "low":
        tags.append("计划性弱的经典型（有责任感、缺主动规划），但结构偏好证据不足，可先试用结构化工具观察接受度")
    elif planning_weak and structure_pref:
        tags.append("计划性薄弱且偏好确定结构：结构化工具可用，但责任心也偏低，需要顾问或家长托底执行")
    elif structure_pref:
        tags.append("确定性需求明显，但计划性不弱：结构化安排是偏好而非干预点")
    else:
        tags.append("未见结构化工具的强匹配证据")
    return _v(NEUTRAL, "；".join(tags), rows, tags=tags)


def _fn_disengagement(items, im, ctx):
    rows: List[Dict[str, str]] = []
    dp = im.get("情绪稳定性-抑郁愉快")
    school = im.get("自我概念-能力与学校表现")
    auto = im.get("自驱力-自主性")
    deep = im.get("学习动机-深层动机")

    dp_raw = _num(dp)
    school_raw = _num(school)
    auto_b = _band3(auto)
    deep_b = _band3(deep)

    for it in (dp, school, auto, deep):
        if it is None:
            continue
        rows.append(_row(it, NEUTRAL))

    happy = dp_raw is not None and dp_raw >= 10
    school_low = (school_raw is not None and school_raw < 6) or \
                 (school is not None and er._st_self_concept(_ev(school)) == PROBLEM
                  and school_raw is None)

    if happy and school_low and auto_b == "high" and deep_b == "low":
        return _v(WATCH,
                  "愉快值高 + 在校表现评价低 + 自主性高 + 深层动机低：接近投入不足模型，"
                  "可能课外活动多、学习投入少", rows)
    if not rows:
        return _v(NEUTRAL, "数据不足", rows)
    return _v(NEUTRAL, "投入不足模型未命中", rows)


_EVALUATORS = {
    "anxiety": _fn_anxiety,
    "anxiety_sources": _fn_anxiety_sources,
    "emotional_outlets": _fn_emotional_outlets,
    "depression": _fn_depression,
    "inferiority": _fn_inferiority,
    "self_esteem": _fn_self_esteem,
    "parent_attachment": _fn_parent_attachment,
    "sensitivity": _fn_sensitivity,
    "helplessness": _fn_helplessness,
    "body_behaviors": _fn_body_behaviors,
    "body_capacity": _fn_body_capacity,
    "cog_input": _fn_cog_input,
    "cog_default": _fn_cog_default,
    "focus_combo": _fn_focus_combo,
    "fatigue_wm": _fn_fatigue_wm,
    "fatigue_flex": _fn_fatigue_flex,
    "confidence_gap": _fn_confidence_gap,
    "motivation_quad": _fn_motivation_quad,
    "success_drive": _fn_success_drive,
    "deep_motivation": _fn_deep_motivation,
    "inner_drive": _fn_inner_drive,
    "mm_logic": _fn_mm_logic,
    "mm_spatial": _fn_mm_spatial,
    "mm_deep": _fn_mm_deep,
    "mm_surface": _fn_mm_surface,
    "strategy_level": _fn_strategy_level,
    "planning": _fn_planning,
    "metacognition": _fn_metacognition,
    "interest_structure": _fn_interest_structure,
    "interest_triangle": _fn_interest_triangle,
    "creativity": _fn_creativity,
    "value_orientation": _fn_value_orientation,
    "career_alignment": _fn_career_alignment,
    "body_drag": _fn_body_drag,
    "support_system": _fn_support_system,
    "structure_tool": _fn_structure_tool,
    "disengagement": _fn_disengagement,
}


# ── 名单归属 ──────────────────────────────────────────────────────
def _assign_list(kind: str, v: Dict[str, Any]) -> Optional[str]:
    if kind == KIND_LABEL:
        return None
    state = v["state"]
    if state == PROBLEM:
        severe = v.get("force_strong") or \
            any((r.get("eval") or "") in SEVERE_EVALS for r in v.get("items", []))
        return LIST_STRONG_I if severe else LIST_WEAK_I
    if state == WATCH:
        return LIST_WEAK_I
    if state == OBSERVED:
        return LIST_WEAK_P
    if state == HEALTHY:
        return LIST_STRONG_P if v.get("asset_strong") else LIST_WEAK_P
    return LIST_WEAK_P


def _state_label_cn(kind: str, v: Dict[str, Any]) -> str:
    if kind == KIND_LABEL:
        return "分型标签"
    return er.verdict_label_cn(v["state"], v.get("items"))


def analysis_scope(student: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    grade = ((student or {}).get("grade") or "").strip()
    is_high_school = ("高中" in grade) or grade.startswith("高") or grade[:2] in ("高一", "高二", "高三")
    if is_high_school:
        return "career", "高中阶段：生涯分析权重提高，兴趣—能力—价值观对齐直接服务于专业与选课方向。"
    return "learning", ("非高中阶段：生涯部分统一面向「未来学习」解读——"
                        "兴趣与能力信号用于课外活动、兴趣班与学习投入方向，不预设未来职业。")


# ── 公开入口 ──────────────────────────────────────────────────────
def evaluate_y4_questions(eval_items: List[Dict[str, Any]],
                          student: Optional[Dict[str, Any]] = None
                          ) -> Dict[str, Any]:
    """Y4 问题研判主入口。

    返回 {scope, scope_note, groups, lists, label_questions, answered, missing}。
    groups: [{dim, dim_label, questions: [...]}]
    """
    er._annotate_cognitive_traits(eval_items)
    groups_raw, im = _build_groups(eval_items)
    scope, scope_note = analysis_scope(student)
    ctx: Dict[str, Any] = {"scope": scope, "im": im}
    ctx["anxiety"] = _anxiety_signal(im)

    groups_out: List[Dict[str, Any]] = []
    lists: Dict[str, Any] = {
        LIST_STRONG_I: [], LIST_WEAK_I: [], LIST_STRONG_P: [], LIST_WEAK_P: []}
    label_questions: List[Dict[str, Any]] = []
    answered = missing = 0

    # groups_raw 是扁平的（每题一项，带 dim），按 Y4_DIMS 重组输出
    by_dim: Dict[str, List[Dict[str, Any]]] = {d: [] for d in Y4_DIMS}
    for g in groups_raw:
        fn = _EVALUATORS[FRAMEWORK_FNS[g["id"]]]
        if not g["items"]:
            verdict = _v(NEUTRAL, "本题所需指标在本报告中缺失，无法判定", [])
            missing += 1
        else:
            verdict = fn(g["items"], im, ctx)
            answered += 1
        assignment = _assign_list(g["kind"], verdict)
        entry = {
            "id": g["id"],
            "kind": g["kind"],
            "q": g["q"],
            "state": verdict["state"],
            "state_label": _state_label_cn(g["kind"], verdict),
            "list_assignment": assignment,
            "summary": verdict["summary"],
            "tags": verdict.get("tags", []),
            "rows": verdict.get("items", []),
        }
        by_dim[g["dim"]].append(entry)
        if assignment:
            lists[assignment].append({"id": g["id"], "dim": g["dim"],
                                      "q": g["q"], "summary": verdict["summary"]})
        else:
            label_questions.append({"id": g["id"], "kind": g["kind"], "dim": g["dim"],
                                    "q": g["q"],
                                    "state_label": _state_label_cn(g["kind"], verdict),
                                    "summary": verdict["summary"],
                                    "tags": verdict.get("tags", []),
                                    "rows": verdict.get("items", [])})

    for d in Y4_DIMS:
        groups_out.append({"dim": d, "dim_label": DIM_LABELS[d], "questions": by_dim[d]})

    return {
        "scope": scope,
        "scope_note": scope_note,
        "groups": groups_out,
        "lists": lists,
        "label_questions": label_questions,
        "answered": answered,
        "missing": missing,
        "total": len(groups_raw),
    }
