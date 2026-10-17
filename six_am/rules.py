"""6 A.M. 六维启动模型 · 规则数据层（v0.2 落地）

算法规格唯一来源：docs/6AM_model_algorithm.md（v0.2，只读）。
本模块为纯数据 + 纯函数，不导入 Flask、不访问数据库。

结构：
  BANDS          档位词集合（v0.2 §1.2）
  QUESTIONS      29 条追问题 Q1.1–Q6.4（v0.2 §8.3 原文）
  RULES          47 条单维规则 R1.1–R6.8（数据化，条件可被规则版本覆盖）
  CROSS_RULES    7 条跨维度规则 X.1–X.7（条件求值在 cross_rules.py）
  DEFAULT_PARAMS 可配置参数默认值（v0.2 §4.1；标 "v0.2 暂定" 的为文档待定项现值）

条件（when）语法（engine.py 求值）：
  {"point": "<指标名>", "is": [档位词…]}        eval_value ∈ 集合
  {"point": "…", "num_lt": n} / {"num_gt": n}   eval_value（或 raw_value）数值比较
  {"order_top": "<排序值>"}                      该值进入排序前 order_top_n 位
  {"rule": "R1.1"}                               另一条规则命中
  {"evidence": "observation.xxx", "is_true": True} 证据字段为真（FT/家长/观察）
  {"predicate": "name"}                          命名谓词（本文件实现，单独可测）
  {"dim_state": {"dim": "A1", "is": "Secure"}}   某维度当前 state 等于
  {"subtype": "A5-S3"}                           某维度亚型命中
  {"any": [cond, …]} / {"not": cond}             组合子（默认同级 AND）

规则 questions 字段 = 追问选择锚点（用于 questionnaire.py 选择算法）；
QUESTIONS[id].verify = v0.2 §8.3 表格的"验证目标"标注（条目级对照）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ── 档位词集合（v0.2 §1.2）─────────────────────────────────────
SEVERE = ["需特殊关注", "明显偏低", "严重偏低"]
MILD_RISK = ["偏低", "需关注"]
LOW_OR_BELOW = ["偏低", "需关注", "需特殊关注", "明显偏低", "严重偏低"]  # 偏低及以下
BODY_PROBLEM = ["差", "低"]
BODY_WATCH = ["中等", "一般"]
STRONG_ASSET = ["高", "较好"]
NEUTRAL_HEALTHY = ["不低", "相对健康", "正常"]
NOT_LOW = ["高", "较好", "不低"]  # ≥ 不低

DIMS = ["A1", "A2", "A3", "A4", "A5", "A6"]
DIM_NAMES = {
    "A1": "Autonomy 自主感",
    "A2": "Alignment 认同感",
    "A3": "Availability 可用空间",
    "A4": "Assurance 胜任信心",
    "A5": "Accessibility 可起步性",
    "A6": "Activation Support 启动支持",
}
ACTIVATION_KEYS = {
    "A1": "Restore Ownership 恢复所有权",
    "A2": "Find My Why 找到属于自己的理由",
    "A3": "Make Room 腾出空间",
    "A4": "Create Early Success 创造早期成功",
    "A5": "Design the First Move 设计第一步",
    "A6": "支持方式有效性排序（A6 为选择器，不判风险）",
}

# ── 追问题库（v0.2 §8.3，29 条全量）───────────────────────────
# verify = 文档"验证目标"标注（内部使用，不对学生展示）
QUESTIONS: Dict[str, Dict[str, Any]] = {
    "Q1.1": {"id": "Q1.1", "dim": "A1", "verify": ["R1.1", "R1.2"],
             "ask": "这个项目最开始是谁的主意呀？你当时第一反应是啥？"},
    "Q1.2": {"id": "Q1.2", "dim": "A1", "verify": ["R1.2"],
             "ask": "假如明天老师说这事儿不用做了，你是偷偷松口气，还是有点可惜？"},
    "Q1.3": {"id": "Q1.3", "dim": "A1", "verify": ["R1.3"],
             "ask": "要是你不想做一件事，你会直接说出来，还是先答应着再说？"},
    "Q1.4": {"id": "Q1.4", "dim": "A1", "verify": ["R1.3"],
             "ask": "你爸妈给你安排的那些事儿，里头有多少是你自己本来也想做的？"},
    "Q1.5": {"id": "Q1.5", "dim": "A1", "verify": ["R1.4"],
             "ask": "如果给你一整个周末，完全没人管你，你想干点啥？"},
    "Q1.6": {"id": "Q1.6", "dim": "A1", "verify": ["R1.5"],
             "ask": "你每天的时间，大概有多少是你自己能说了算的？"},
    "Q2.1": {"id": "Q2.1", "dim": "A2", "verify": ["R2.2"],
             "ask": "如果这事跟升学一点关系都没有，你还会想弄吗？哪块你觉得还挺有意思，哪块纯属折磨？"},
    "Q2.2": {"id": "Q2.2", "dim": "A2", "verify": ["R2.3", "R2.4"],
             "ask": "你做这件事图啥？这个理由是别人告诉你的，还是你自己真这么觉得？"},
    "Q2.3": {"id": "Q2.3", "dim": "A2", "verify": ["R2.7"],
             "ask": "有没有什么事是没人催你、你自己就一直捣鼓下去的？给我讲讲呗。"},
    "Q2.4": {"id": "Q2.4", "dim": "A2", "verify": ["R2.5"],
             "ask": "这事要是真做成了，你觉得自己能得到啥？"},
    "Q2.5": {"id": "Q2.5", "dim": "A2", "verify": ["R2.1"],
             "ask": "最近有没有啥时候，你突然觉得'哎，这个有点意思'？不一定非得是学习上的。"},
    "Q2.6": {"id": "Q2.6", "dim": "A2", "verify": ["R2.1"],
             "ask": "要是让你自己设计一个项目，干啥都行，没人限制你——你想搞点啥？"},
    "Q3.1": {"id": "Q3.1", "dim": "A3", "verify": ["R3.1", "R3.3"],
             "ask": "你最近一般几点睡？第二天上课扛得住吗？"},
    "Q3.2": {"id": "Q3.2", "dim": "A3", "verify": ["R3.3"],
             "ask": "如果我这时候跟你说'咱再加个新任务'，你心里的第一反应是啥？说实话哈。"},
    "Q3.3": {"id": "Q3.3", "dim": "A3", "verify": ["R3.6"],
             "ask": "你们学校一天排到晚，你一般啥时候能喘口气？那点时间你一般干嘛？"},
    "Q3.4": {"id": "Q3.4", "dim": "A3", "verify": ["R3.6"],
             "ask": "要真开始做这件事，你觉得得先把啥事儿放一放？"},
    "Q4.1": {"id": "Q4.1", "dim": "A4", "verify": ["R4.1", "R4.3"],
             "ask": "如果这事最后没做好，你脑子里第一个蹦出来的念头会是啥？"},
    "Q4.2": {"id": "Q4.2", "dim": "A4", "verify": ["R4.3", "R4.8"],
             "ask": "上次你试了个新东西结果搞砸了，是啥时候的事？后来你还碰它了吗？"},
    "Q4.3": {"id": "Q4.3", "dim": "A4", "verify": ["R4.3"],
             "ask": "你有没有跟自己说过'等我再准备准备就开始'？后来真开始了吗？"},
    "Q4.4": {"id": "Q4.4", "dim": "A4", "verify": ["R4.4"],
             "ask": "假如前三次尝试谁都看不见，只有你自己知道结果，你会不会更敢上手？"},
    "Q4.5": {"id": "Q4.5", "dim": "A4", "verify": ["R4.9"],
             "ask": "你觉得自己最强的学科是哪个？咱拿最近几次成绩对对，看跟你说的是不是一回事儿。"},
    "Q5.1": {"id": "Q5.1", "dim": "A5", "verify": ["R5.1"],
             "ask": "要是明天就得开工，你猜你第一个小时会干啥？"},
    "Q5.2": {"id": "Q5.2", "dim": "A5", "verify": ["R5.1", "R5.5"],
             "ask": "让你把这事儿拆成几小步，你会咋拆？卡在哪儿了？"},
    "Q5.3": {"id": "Q5.3", "dim": "A5", "verify": ["R5.2"],
             "ask": "现在摆在你面前这几个方向，你是挑花眼了不知道选哪个，还是其实都不太想选？"},
    "Q5.4": {"id": "Q5.4", "dim": "A5", "verify": ["R5.3"],
             "ask": "以前有没有人带着你做过类似的事？有人带和自己一个人搞，感觉差在哪儿？"},
    "Q6.1": {"id": "Q6.1", "dim": "A6", "verify": ["R6.1"],
             "ask": "你干得最顺的那些事，是自己一个人闷头干的，还是跟别人一起的？"},
    "Q6.2": {"id": "Q6.2", "dim": "A6", "verify": ["R6.2", "R6.3"],
             "ask": "有没有那么一个人——TA 在等你的结果，你就不好意思不干？这人是谁？"},
    "Q6.3": {"id": "Q6.3", "dim": "A6", "verify": ["R6.4", "R6.5"],
             "ask": "你努力的时候，是希望别人看见给你点赞，还是别盯着你、等出结果了再说？"},
    "Q6.4": {"id": "Q6.4", "dim": "A6", "verify": ["R6.5", "R6.7"],
             "ask": "DDL 对你是真管用，还是只会让你焦虑到躺平？"},
}

# A6 追问补充顺序（当命中规则未给出候选时按此顺序补足；v0.2 §8.2 步骤④的落地）
A6_FILL_ORDER = ["Q6.2", "Q6.1", "Q6.4", "Q6.3"]

# ── 单维规则（47 条）──────────────────────────────────────────
# then 字段语义见文件头；subtype_priority 用于同维多亚型命中时取更具体分支。

RULES: Dict[str, Dict[str, Any]] = {}


def _rule(**kw: Any) -> Dict[str, Any]:
    rid = kw["id"]
    kw.setdefault("source", ["Y4"])
    kw.setdefault("when", [])
    kw.setdefault("then", {})
    kw.setdefault("questions", [])
    kw.setdefault("text", "")
    RULES[rid] = kw
    return kw


# ── A1 Autonomy 自主感 ──
_rule(
    id="R1.1", dim="A1", title="自主性偏低",
    when=[{"point": "自驱力-自主性", "is": ["偏低"]}],
    then={"state": "At-Risk", "confidence": "Hypothesis"},
    questions=["Q1.1"],
    text="习惯从自身目标出发行动的程度低，是自主空间不足的核心信号（→Q1.1）",
)
_rule(
    id="R1.2", dim="A1", title="被动抵抗型分型",
    when=[{"rule": "R1.1"}, {"point": "人格-宜人性", "is": STRONG_ASSET}],
    then={"subtype": "A1-S1", "subtype_name": "Passive Resistance 被动抵抗型", "subtype_priority": 1,
          "confidence": "Hypothesis",
          "notes": ["高宜人性学生更易配合、不愿制造冲突，'表面答应、行为拒绝'风险升高，需验证"]},
    questions=["Q1.1", "Q1.2"],
    text="表面配合、行为拒绝；不制造冲突，用拖延表达'不'",
)
_rule(
    id="R1.3", dim="A1", title="高叛逆风险（双条件）",
    when=[{"order_top": "独立自主"},
          {"any": [{"point": "自驱力-自主性", "is": LOW_OR_BELOW},
                   {"point": "情绪稳定性-无力感掌控感", "is": LOW_OR_BELOW}]}],
    then={"state": "Blocked", "subtype": "A1-S2", "subtype_name": "Rebellion 逆反型（高叛逆风险）",
          "subtype_priority": 3, "confidence": "Hypothesis", "flags": ["高叛逆风险人群"],
          "notes": ["自主需求强 × 无自主空间 → 以反抗权威索取自主感",
                    "亲子依恋为调节因子：信任/沟通偏低 → 反抗外显化（顶撞、对着干）；依恋正常 → 反抗隐性化（消极、疏离）"]},
    questions=["Q1.3", "Q1.4"],
    text="自主选择对学生重要（独立自主前 5）且当前无自主选择空间（自主性偏低 或 掌控感偏低及以下）",
)
_rule(
    id="R1.4", dim="A1", title="压抑顺从型分型",
    when=[{"rule": "R1.1"}, {"point": "人格-宜人性", "is": STRONG_ASSET},
          {"predicate": "parent_attachment_safe"}],
    then={"subtype": "A1-S3", "subtype_name": "Suppressed Compliance 压抑顺从型", "subtype_priority": 2,
          "confidence": "Hypothesis",
          "notes": ["关系安全但自主性低：学生不反抗，只是从未被要求'自己做主'"]},
    questions=["Q1.5"],
    text="习惯被安排，不反抗，但也没有'这件事是我的'的主人翁感",
)
_rule(
    id="R1.5", dim="A1", title="掌控感偏低",
    when=[{"point": "情绪稳定性-无力感掌控感", "is": LOW_OR_BELOW}],
    then={"state": "Watch", "confidence": "Hypothesis", "escalate_if_rule": "R1.1",
          "notes": ["低掌控感提示学生感到生活安排主要由外界决定"]},
    questions=["Q1.6"],
    text="A1 至少 Watch；与 R1.1 叠加时升一级",
)
_rule(
    id="R1.6", dim="A1", title="自主感稳固",
    when=[{"point": "自驱力-自主性", "is": ["较好", "不低"]},
          {"predicate": "parent_attachment_safe"},
          {"point": "自我概念-幸福与满足", "is": ["高", "较好", "不低"]}],
    then={"noop": True, "confirmed_secure": True,
          "notes": ["自主性高 + 亲子关系好 + 对现状满意 → 自主感自然稳固（针对整体生活而非单一任务）"]},
    text="A1 = Secure",
)
_rule(
    id="R1.7", dim="A1", title="父母依恋差异",
    when=[{"predicate": "parent_attachment_asymmetry"}],
    then={"noop": True, "flags": ["支持来源不对称"],
          "notes": ["母亲与父亲同子项档位相差 ≥ 2 档：学生可能只接受一方父母的参与方式（供 A6 使用）"]},
    text="标记'支持来源不对称'，供 A6 使用",
)
_rule(
    id="R1.8", dim="A1", title="分层干预：无预警",
    when=[{"not": {"order_top": "独立自主"}},
          {"point": "自驱力-自主性", "is": ["较好", "不低"]}],
    then={"noop": True,
          "notes": ["自主需求低的人群对'被安排'不敏感：无特殊预警，无需额外干预；选择权干预集中投放在自主需求高的学生身上"]},
    text="无特殊预警，无需额外干预",
)

# ── A2 Alignment 认同感 ──
_rule(
    id="R2.1", dim="A2", title="霍兰德六型全低",
    when=[{"point": "职业兴趣-现实型", "is": ["偏低"]},
          {"point": "职业兴趣-研究型", "is": ["偏低"]},
          {"point": "职业兴趣-艺术型", "is": ["偏低"]},
          {"point": "职业兴趣-社会型", "is": ["偏低"]},
          {"point": "职业兴趣-事业型", "is": ["偏低"]},
          {"point": "职业兴趣-常规型", "is": ["偏低"]}],
    then={"state": "Watch", "subtype": "A2-S3", "subtype_name": "Global Disinterest 全局无兴趣型",
          "subtype_priority": 2, "confidence": "Hypothesis",
          "notes": ["活动场景不设强制预警；单独命中时只到 Watch，测评全低可能是填答状态问题，需交叉验证（R2.8）后再升级"]},
    questions=["Q2.5", "Q2.6"],
    text="对各类活动都提不起兴趣；需家长主诉或行为证据交叉确认",
)
_rule(
    id="R2.2", dim="A2", title="任务错位",
    when=[{"predicate": "holland_peak_exists"},
          {"evidence": "task.mismatch", "is_true": True}],
    then={"state": "At-Risk", "subtype": "A2-S1", "subtype_name": "Task Misalignment 任务错位型",
          "subtype_priority": 1, "confidence": "Hypothesis",
          "notes": ["存在兴趣高峰但当前任务类型不匹配 → 输出适配活动方向引导，不设强制预警"]},
    questions=["Q2.1"],
    text="有明确的兴趣高峰，但当前任务的内容/形式与之不匹配（需【观察】任务信息）",
)
_rule(
    id="R2.3", dim="A2", title="动力缺失",
    when=[{"point": "学习动机-深层动机", "is": ["偏低"]},
          {"point": "学习动机-表面动机", "is": ["偏低"]}],
    then={"state": "At-Risk", "subtype": "A2-S4", "subtype_name": "Motivation Absent 动力缺失型",
          "subtype_priority": 4, "confidence": "Hypothesis",
          "notes": ["深层、表层动机双低 → 内外动机同时缺席，触发学习场景预警"]},
    questions=["Q2.2"],
    text="深层、表层动机双低：内外动机同时缺席，学习场景整体预警",
)
_rule(
    id="R2.4", dim="A2", title="动机绷断风险",
    when=[{"point": "学习动机-深层动机", "is": ["偏低"]},
          {"point": "学习动机-表面动机", "is": ["较好", "不低"]}],
    then={"state": "Watch", "subtype": "A2-S2", "subtype_name": "Motivation Snapping 动机绷断型",
          "subtype_priority": 3, "confidence": "Hypothesis",
          "notes": ["深层动机低、表层动机高：完全靠外部理由硬撑，外部压力撤走或反噬时动机可能瞬间绷断",
                    "state 范围为 Watch~At-Risk（v0.2）：外部压力证据充分时升为 At-Risk"]},
    questions=["Q2.2"],
    text="靠'为了大学/为了爸妈'硬撑，外部理由一旦失效，动机会快速崩解",
)
_rule(
    id="R2.5", dim="A2", title="价值连接缺失",
    when=[{"predicate": "value_link_absent"}],
    then={"state": "Watch", "confidence": "Hypothesis",
          "notes": ["当前任务可连接的价值观均不在前 5 位：任务与学生重视的价值无连接点"]},
    questions=["Q2.4"],
    text="任务与学生重视的价值（成就感/创造发明/利他助人/智力激发……）无连接点（需任务信息）",
)
_rule(
    id="R2.6", dim="A2", title="开放性低：任务形式约束",
    when=[{"point": "人格-开放性", "is": ["偏低", "明显偏低"]}],
    then={"noop": True, "notes": ["开放性低 ≠ 不能启动：更明确、更熟悉、更确定的任务形式更适合（记录为任务形式约束）"]},
    text="不判风险；记录为任务形式约束",
)
_rule(
    id="R2.7", dim="A2", title="既往主动投入（支持性证据）",
    when=[{"predicate": "prior_engagement_same_domain"}],
    then={"deescalate": 1, "floor": "Watch", "confidence_to": "Supported",
          "notes": ["既往主动投入是最有价值的行为证据之一（与当前任务同域）"]},
    questions=["Q2.3"],
    text="A2 支持性证据（降一级，不低于 Watch）；confidence → Supported（【FT】/【观察】）",
)
_rule(
    id="R2.8", dim="A2", title="家长主诉交叉验证",
    when=[{"predicate": "parent_complaint_present"}],
    then={"effects": [
        {"if_any_rules": ["R2.1", "R2.3", "R2.4"], "state_add": 1, "confidence_to": "Supported",
         "notes": ["家长主诉交叉验证命中：state 升一级、confidence → Supported"]},
        {"if_no_rules": ["R2.1", "R2.3", "R2.4"], "state": "Watch",
         "notes": ["无测评信号但有家长主诉 → A2 至少 Watch"]},
    ]},
    text="家长存在'学生无兴趣、动力不足'类主诉：不单一依赖测评结果，需交叉确认家长侧观察",
)

# ── A3 Availability 可用空间 ──
_rule(
    id="R3.1", dim="A3", title="睡眠不足",
    when=[{"point": "体质健康-睡眠评级", "is": BODY_PROBLEM}],
    then={"state": "At-Risk", "confidence": "Hypothesis"},
    questions=["Q3.1"],
    text="睡眠是最直接的 Capacity Evidence",
)
_rule(
    id="R3.2", dim="A3", title="恢复空间不足",
    when=[{"any": [{"point": "体质健康-睡眠评级", "is": BODY_WATCH},
                   {"point": "体质健康-运动评级", "is": BODY_PROBLEM},
                   {"point": "体质健康-饮食评级", "is": BODY_PROBLEM}]}],
    then={"state": "Watch", "confidence": "Hypothesis",
          "subtype_if": {"predicate": "recovery_deficit_two_hits", "subtype": "A3-S2",
                         "subtype_name": "Recovery Deficit 恢复不足型", "subtype_priority": 2},
          "notes": ["恢复空间不足会慢慢侵蚀启动能力；两项以上命中 → 亚型 A3-S2"]},
    text="A3 至少 Watch；两项以上命中 → 亚型 A3-S2 Recovery Deficit",
)
_rule(
    id="R3.3", dim="A3", title="情绪资源占用",
    when=[{"any": [{"point": "情绪稳定性-焦虑安详", "is": ["需关注", "需特殊关注"]},
                   {"point": "情绪稳定性-抑郁愉快", "is": ["需关注", "需特殊关注"]}]}],
    then={"state": "At-Risk", "confidence": "Hypothesis",
          "effects": [{"if": {"rule": "R3.1"}, "state_add": 1,
                       "subtype": "A3-S1", "subtype_name": "Capacity Overload 过载型",
                       "subtype_priority": 4,
                       "notes": ["与 R3.1 叠加 → 亚型 A3-S1 Capacity Overload，state → Blocked"]}]},
    questions=["Q3.1", "Q3.2"],
    text="持续情绪压力占用大量认知资源（与 R3.1 叠加时 state → Blocked）",
)
_rule(
    id="R3.4", dim="A3", title="情绪整体低水位",
    when=[{"point": "情绪稳定性总分", "is": ["偏低", "明显偏低"]}],
    then={"state": "Watch", "confidence": "Hypothesis", "escalate_if_dim": "At-Risk",
          "notes": ["整体情绪资源处于低水位；与 R3.1/R3.3 叠加时升一级"]},
    text="A3 至少 Watch；与上述叠加时升一级",
)
_rule(
    id="R3.5", dim="A3", title="认知饱和",
    when=[{"any": [{"point": "执行功能-工作记忆", "is": ["偏低"]},
                   {"point": "执行功能-认知灵活性", "is": ["偏低"]}]},
          {"predicate": "emotion_items_all_healthy"}],
    then={"state": "At-Risk", "subtype": "A3-S3", "subtype_name": "Cognitive Saturation 认知饱和型",
          "subtype_priority": 3, "confidence": "Hypothesis",
          "notes": ["执行功能已高负荷时，新增任务产生明显启动摩擦"]},
    text="执行功能资源（工作记忆/认知灵活性）占用过高，情绪与身体尚可",
)
_rule(
    id="R3.6", dim="A3", title="排期与负荷（FT）",
    when=[{"predicate": "schedule_overload"}],
    then={"confidence_to": "Supported", "if_dim_severity": "At-Risk",
          "notes": ["作为放大因子叠加；与 R3.1/R3.3 叠加时 confidence → Supported"]},
    questions=["Q3.3", "Q3.4"],
    text="First Touch 排期问询：当前课程与活动负荷高、自由时间极少",
)

# ── A4 Assurance 胜任信心 ──
_rule(
    id="R4.1", dim="A4", title="自我效能偏低",
    when=[{"point": "学习动机-自我效能感", "is": ["偏低"]}],
    then={"state": "At-Risk", "subtype": "A4-S2", "subtype_name": "Low Self-Efficacy 低自我效能型",
          "subtype_priority": 1, "confidence": "Hypothesis"},
    questions=["Q4.1"],
    text="自我效能是胜任信心最直接的指标",
)
_rule(
    id="R4.2", dim="A4", title="胜任感互证",
    when=[{"point": "自驱力-胜任感", "is": ["偏低"]}],
    then={"escalate_if_rule": "R4.1", "notes": ["胜任感与自我效能互证，与 R4.1 叠加时 state 升一级"]},
    text="与 R4.1 叠加时 state 升一级",
)
_rule(
    id="R4.3", dim="A4", title="完美主义回避",
    when=[{"point": "情绪稳定性-自卑自尊", "is": ["需关注", "需特殊关注"]},
          {"point": "思维模式结果", "num_lt": "@mindset_fixed_threshold"}],
    then={"state": "At-Risk", "subtype": "A4-S1",
          "subtype_name": "Perfectionist Avoidance 完美主义回避型", "subtype_priority": 3,
          "confidence": "Hypothesis",
          "notes": ["低自尊 + Fixed Mindset：失败被解释为'这证明我不行'，尝试意愿下降",
                    "思维模式阈值 < 40 为 v0.2 暂定（见算法文档 §11）"]},
    questions=["Q4.2", "Q4.3"],
    text="用'还没准备好'无限推迟开始；把失败解释为能力判决",
)
_rule(
    id="R4.4", dim="A4", title="评价焦虑",
    when=[{"point": "情绪稳定性-焦虑安详", "is": ["需关注", "需特殊关注"]},
          {"point": "情绪稳定性-自卑自尊", "is": ["需关注", "需特殊关注"]}],
    then={"state": "At-Risk", "subtype": "A4-S3", "subtype_name": "Evaluation Anxiety 评价焦虑型",
          "subtype_priority": 2, "confidence": "Hypothesis"},
    questions=["Q4.4"],
    text="核心恐惧是被评价：作品被看、父母失望、老师批评",
)
_rule(
    id="R4.5", dim="A4", title="神经质背景放大因子",
    when=[{"any": [{"point": "人格-神经质", "is": ["高", "较好"]},
                   {"point": "人格-神经质", "num_gt": 3.5}]}],
    then={"noop": True, "flags": ["神经质背景"], "confidence": "Hypothesis",
          "notes": ["不独立判风险；作为 A4 放大因子（severity +0.5，封顶 3）"]},
    text="对潜在负面结果更敏感，不等于胜任信心不足（计分见 §6）",
)
_rule(
    id="R4.6", dim="A4", title="掌控感缺失预期",
    when=[{"point": "情绪稳定性-无力感掌控感", "is": LOW_OR_BELOW}],
    then={"state": "Watch", "confidence": "Hypothesis"},
    text="'做了也没有用'的预期 → A4 至少 Watch",
)
_rule(
    id="R4.7", dim="A4", title="整体自我评价低",
    when=[{"any": [{"point": "自我概念整体档位", "is": ["偏低"]},
                   {"point": "自我概念-能力与学校表现", "is": ["偏低", "严重偏低"]}]}],
    then={"state": "Watch", "confidence": "Hypothesis", "escalate_if_rule": "R4.1"},
    text="A4 至少 Watch；与 R4.1 叠加升一级",
)
_rule(
    id="R4.8", dim="A4", title="失败后放弃模式（FT/观察）",
    when=[{"evidence": "observation.first_failure_quit", "is_true": True}],
    then={"confidence_to": "Supported", "confidence_if": "requires_subtype",
          "notes": ["既往'第一次尝试失败后放弃'的行为模式：任意 A4 亚型 confidence → Supported"]},
    questions=["Q4.2"],
    text="Y4 无直接指标，由追问或顾问记录提供",
)
_rule(
    id="R4.9", dim="A4", title="学科状态校准（FT）",
    when=[{"predicate": "subject_mismatch"}],
    then={"effects": [
        {"if_predicate": "subject_below_actual", "state_add": 1, "subtype": "A4-S4",
         "subtype_name": "Miscalibration 认知偏差型", "subtype_priority": 4,
         "notes": ["自评低于实际 → A4 严重度上调一级"]},
        {"if_predicate": "subject_above_actual",
         "notes": ["自评高于实际 → 标注'A4 之外的风险'（不修正 A4，记入观察）"]},
    ]},
    questions=["Q4.5"],
    text="校准能力与自我认知的偏差：低估自己的学生问题在信心，高估自己的问题不在本维度",
)

# ── A5 Accessibility 可起步性 ──
_rule(
    id="R5.1", dim="A5", title="疑似规划瘫痪",
    when=[{"point": "人格-责任心", "is": ["偏低", "明显偏低"]},
          {"point": "学习方法与策略-学习自我调节", "is": ["偏低"]}],
    then={"state": "At-Risk", "subtype": "A5-S1", "subtype_name": "Planning Paralysis 规划瘫痪型（疑似）",
          "subtype_priority": 2, "confidence": "Hypothesis",
          "notes": ["任务组织与自我监控能力双低，大目标无法落地"]},
    questions=["Q5.1", "Q5.2"],
    text="面对大目标拆不出来，迟迟无法转化为行动（规划障碍）",
)
_rule(
    id="R5.2", dim="A5", title="选择过载",
    when=[{"point": "人格-开放性", "is": STRONG_ASSET},
          {"predicate": "holland_three_plus_notlow"},
          {"evidence": "task.direction_undecided", "is_true": True}],
    then={"state": "Watch", "subtype": "A5-S2", "subtype_name": "Choice Overload 选择过载型",
          "subtype_priority": 1, "confidence": "Hypothesis",
          "notes": ["兴趣宽 + 高开放性 → Choice Overload 风险（需任务方向未定证据）"]},
    questions=["Q5.3"],
    text="方向和选项过多，无法收敛出第一步",
)
_rule(
    id="R5.3", dim="A5", title="疑似结构依赖",
    when=[{"point": "学习动机-深层动机", "is": ["较好", "不低"]},
          {"point": "学习方法与策略-学习自我调节", "is": ["偏低"]},
          {"point": "自驱力-自主性", "is": ["较好", "不低"]}],
    then={"state": "At-Risk", "subtype": "A5-S3", "subtype_name": "Structure Dependence 结构依赖型（疑似）",
          "subtype_priority": 3, "confidence": "Hypothesis",
          "notes": ["不是不想做，是没有外部结构时不知如何开始"]},
    questions=["Q5.4"],
    text="拆得出、有意愿，但没有外部结构就不动（启动障碍）",
)
_rule(
    id="R5.4", dim="A5", title="抑制控制偏低",
    when=[{"point": "执行功能-抑制控制", "is": ["偏低"]}],
    then={"state": "Watch", "confidence": "Hypothesis",
          "notes": ["启动后维持聚焦的风险，影响 First Move 的时长设计"]},
    text="A5 至少 Watch",
)
_rule(
    id="R5.5", dim="A5", title="深层策略缺失",
    when=[{"point": "学习方法与策略-学习深层方法与策略", "is": ["偏低"]}],
    then={"state": "Watch", "confidence": "Hypothesis", "escalate_if_rule": "R5.1",
          "notes": ["缺少把抽象目标转成具体步骤的工具；与 R5.1 叠加升一级"]},
    questions=["Q5.2"],
    text="A5 至少 Watch；与 R5.1 叠加升一级",
)
_rule(
    id="R5.6", dim="A5", title="低尽责性单独命中不判风险",
    when=[{"point": "人格-责任心", "is": ["偏低", "明显偏低"]}],
    then={"noop": True, "notes": ["低尽责性 ≠ 不会启动，只是提示需要进一步看任务结构"]},
    text="不判风险",
)
_rule(
    id="R5.7", dim="A5", title="标准化任务测试（FT 确诊）",
    when=[{"predicate": "standard_task_done"}],
    then={"effects": [
        {"if_predicate": "standard_task_cannot_split", "subtype": "A5-S1",
         "subtype_name": "Planning Paralysis 规划瘫痪型（确诊）", "subtype_priority": 5,
         "confidence_to": "Supported", "notes": ["拆不出步骤 → 确诊规划障碍（规划瘫痪型）"]},
        {"if_predicate": "standard_task_cannot_commit", "subtype": "A5-S3",
         "subtype_name": "Structure Dependence 结构依赖型（确诊）", "subtype_priority": 5,
         "confidence_to": "Supported", "notes": ["拆得出但无法承诺开始时间/第一步 → 确诊启动障碍（结构依赖型）"]},
    ]},
    questions=["Q5.1", "Q5.2"],
    text="现场让学生把一个大任务拆成步骤：用于区分规划障碍与启动障碍",
)
_rule(
    id="R5.8", dim="A5", title="注意力风险预警",
    when=[{"point": "认知能力-注意力", "is": ["偏低"]}],
    then={"noop": True, "flags": ["仅风险预警"],
          "notes": ["仅做风险预警，不输出深度解决方案；标注后转介相应支持渠道"]},
    text="仅做风险预警，不输出深度解决方案",
)

# ── A6 Activation Support 启动支持（选择器：输出支持方向排序）──
_rule(
    id="R6.1", dim="A6", title="同伴协作适配",
    when=[{"point": "人格-外倾性", "is": STRONG_ASSET},
          {"predicate": "peer_attachment_high"},
          {"evidence": "observation.team_behavior_verified", "is_true": True}],
    then={"support_ops": [{"direction": "同伴协作", "delta": 2, "sub": ["Companion", "Group"],
                           "note": "经日常行为描述交叉验证"}]},
    questions=["Q6.1"],
    text="团队适配判定不单一依赖外倾性/宜人性，需行为描述交叉验证",
)
_rule(
    id="R6.2", dim="A6", title="家长陪同慎用",
    when=[{"predicate": "parent_attachment_low"},
          {"predicate": "peer_attachment_not_low"}],
    then={"support_ops": [{"direction": "家长陪同", "delta": -2, "kind": "慎用"},
                          {"direction": "同伴协作", "delta": 1},
                          {"direction": "权威施压", "delta": 1,
                           "note": "导师方向（非家庭权威）"}]},
    questions=["Q6.2"],
    text="关键不是'需不需要别人'，而是'谁、以什么方式出现才有效'",
)
_rule(
    id="R6.3", dim="A6", title="责任机制有效",
    when=[{"point": "人格-宜人性", "is": STRONG_ASSET}],
    then={"support_ops": [{"direction": "权威施压", "delta": 2, "sub": ["Accountability"]}]},
    questions=["Q6.2"],
    text="对他人期待敏感，责任机制有效",
)
_rule(
    id="R6.4", dim="A6", title="成就/声望价值靠前",
    when=[{"any": [{"order_top": "成就感"}, {"order_top": "声望地位"}]}],
    then={"support_ops": [{"direction": "同伴协作", "delta": 1, "sub": ["Competition"]},
                          {"direction": "家长陪同", "delta": 1, "sub": ["Recognition"]}]},
    questions=["Q6.3"],
    text="被看见与被比较都能转化为行动能量",
)
_rule(
    id="R6.5", dim="A6", title="评价焦虑：高压避免",
    when=[{"any": [{"point": "人格-神经质", "is": ["高"]},
                   {"point": "情绪稳定性-焦虑安详", "is": ["需关注", "需特殊关注"]}]}],
    then={"support_ops": [
        {"direction": "权威施压", "delta": -1, "kind": "避免",
         "sub_note": "高压 Accountability 避免；Feedback 改为私密、高频、低 stakes"},
        {"direction": "同伴协作", "delta": -1, "kind": "避免", "sub_note": "公开 Competition 避免"},
    ]},
    questions=["Q6.3", "Q6.4"],
    text="高评价焦虑下，公开承诺与竞争会反向提高启动门槛",
)
_rule(
    id="R6.6", dim="A6", title="自主受损：成人方向慎用",
    when=[{"any": [{"subtype": "A1-S2"}, {"subtype": "A1-S3"}]}],
    then={"support_ops": [
        {"direction": "权威施压", "delta": -2, "kind": "慎用"},
        {"direction": "家长陪同", "delta": -2, "kind": "慎用"},
        {"direction": "同伴协作", "delta": 1, "note": "Privacy 调节投递"},
    ]},
    text="对自主感受损的学生，来自成人方向的监督本身就是新的阻力；权威施压方向仅对 A1 安全的学生开放",
)
_rule(
    id="R6.7", dim="A6", title="结构依赖：Structure 排前",
    when=[{"subtype": "A5-S3"}],
    then={"support_ops": [{"direction": "权威施压", "delta": 2, "sub": ["Structure"],
                           "note": "与 R6.6 冲突时以 R6.6 为准"}]},
    questions=["Q6.2"],
    text="结构依赖型学生需要外部脚手架",
)
_rule(
    id="R6.8", dim="A6", title="家庭支持合法资源",
    when=[{"predicate": "parent_attachment_high"},
          {"dim_state": {"dim": "A1", "is": "Secure"}}],
    then={"support_ops": [{"direction": "家长陪同", "delta": 2, "sub": ["陪跑", "低压力关注"]}]},
    text="关系安全且自主感完好时，家庭支持是合法资源",
)

# ── 跨维度规则 X.1–X.7（条件求值在 cross_rules.py）───────────
CROSS_RULES: Dict[str, Dict[str, str]] = {
    "X.1": {"id": "X.1", "title": "Double-Lock 双锁",
            "action": "两维 obstacle score × 1.5；处理顺序固定为先 A1 后 A2"},
    "X.2": {"id": "X.2", "title": "A2 信号污染修正",
            "action": "A2 confidence 降一级（下限 Hypothesis），标注'需用学生自选任务重测'"},
    "X.3": {"id": "X.3", "title": "A3 优先排除",
            "action": "A4/A5 所有 Hypothesis 级结论标注'待 A3 处理后复测'；score × 0.7；obstacle 排序中 A3 强制置顶"},
    "X.4": {"id": "X.4", "title": "A4 约束 A5 设计",
            "action": "A5 的 First Move 必须满足低风险标准：可私下完成、允许低质量、无即时评价"},
    "X.5": {"id": "X.5", "title": "A6 统筹约束",
            "action": "任何 A6 支持推荐必须与前五维 state 兼容；冲突时以 R6.5–R6.7 的避免/慎用为准"},
    "X.6": {"id": "X.6", "title": "全局无兴趣优先级",
            "action": "所有任务级干预（A1 选择设计、A5 First Move）暂缓；处理顺序改为：兴趣探索 → 再评估"},
    "X.7": {"id": "X.7", "title": "家长无法让渡主导权",
            "action": "A1 obstacle score × 0.5，A1 干预降级为长期目标；干预重心转向 A2 意义匹配"},
}

# ── 参数默认值（v0.2 §4.1 + 落地补充）────────────────────────
DEFAULT_PARAMS: Dict[str, Any] = {
    "order_top_n": 5,                 # R1.3/R1.8/R2.5/R6.4 的 ORDER 条件
    "mindset_fixed_threshold": 40,    # R4.3：v0.2 暂定
    "severity": {"Secure": 0, "Watch": 1, "At-Risk": 2, "Blocked": 3},
    "confidence_factor": {"Hypothesis": 0.7, "Supported": 1.0, "Confirmed": 1.2},
    "r45_neuroticism": {"mode": "severity_add", "value": 0.5, "cap": 3},  # R4.5
    "x1_multiplier": 1.5,             # X.1
    "x3_multiplier": 0.7,             # X.3
    "x7_multiplier": 0.5,             # X.7
    "high_priority_min_score": 2.0,
    "confidence_order": ["Hypothesis", "Supported", "Confirmed"],
    "questionnaire": {"top_n": 8, "a6_slots": 2, "hypothesis_dim_limit": 3},
    # v0.2 暂定：排期"自由时间极少"判定阈值（小时/周）与负荷评级字段配合使用
    "schedule_free_hours_max": 5,
    # v0.2 待定：任务可连接价值默认列表为空（需任务信息才评估 R2.5）
    "value_link_defaults": [],
    # A6 支持方向评分基础分与有效性分档（v0.2 §4.6 输出格式的落地量化）
    "a6_base_score": 1.0,
    "a6_effectiveness": {"high": 3.0, "mid": 2.0},
}

# ── 规则 ID 全集（覆盖检查对照）──────────────────────────────
RULE_IDS: List[str] = [
    "R1.1", "R1.2", "R1.3", "R1.4", "R1.5", "R1.6", "R1.7", "R1.8",
    "R2.1", "R2.2", "R2.3", "R2.4", "R2.5", "R2.6", "R2.7", "R2.8",
    "R3.1", "R3.2", "R3.3", "R3.4", "R3.5", "R3.6",
    "R4.1", "R4.2", "R4.3", "R4.4", "R4.5", "R4.6", "R4.7", "R4.8", "R4.9",
    "R5.1", "R5.2", "R5.3", "R5.4", "R5.5", "R5.6", "R5.7", "R5.8",
    "R6.1", "R6.2", "R6.3", "R6.4", "R6.5", "R6.6", "R6.7", "R6.8",
]
CROSS_RULE_IDS: List[str] = ["X.1", "X.2", "X.3", "X.4", "X.5", "X.6", "X.7"]
QUESTION_IDS: List[str] = [
    "Q1.1", "Q1.2", "Q1.3", "Q1.4", "Q1.5", "Q1.6",
    "Q2.1", "Q2.2", "Q2.3", "Q2.4", "Q2.5", "Q2.6",
    "Q3.1", "Q3.2", "Q3.3", "Q3.4",
    "Q4.1", "Q4.2", "Q4.3", "Q4.4", "Q4.5",
    "Q5.1", "Q5.2", "Q5.3", "Q5.4",
    "Q6.1", "Q6.2", "Q6.3", "Q6.4",
]

SUBTYPE_NAMES = {
    "A1-S1": "Passive Resistance 被动抵抗型",
    "A1-S2": "Rebellion 逆反型（高叛逆风险）",
    "A1-S3": "Suppressed Compliance 压抑顺从型",
    "A2-S1": "Task Misalignment 任务错位型",
    "A2-S2": "Motivation Snapping 动机绷断型",
    "A2-S3": "Global Disinterest 全局无兴趣型",
    "A2-S4": "Motivation Absent 动力缺失型",
    "A3-S1": "Capacity Overload 过载型",
    "A3-S2": "Recovery Deficit 恢复不足型",
    "A3-S3": "Cognitive Saturation 认知饱和型",
    "A4-S1": "Perfectionist Avoidance 完美主义回避型",
    "A4-S2": "Low Self-Efficacy 低自我效能型",
    "A4-S3": "Evaluation Anxiety 评价焦虑型",
    "A4-S4": "Miscalibration 认知偏差型",
    "A5-S1": "Planning Paralysis 规划瘫痪型",
    "A5-S2": "Choice Overload 选择过载型",
    "A5-S3": "Structure Dependence 结构依赖型",
}

# ── 命名谓词（engine 传入 ctx；每个单独可测）──────────────────
# ctx 接口：eval_of(label) / num_of(label) / order_pos(value) / top_n / ev(path) /
#          rule_hit(id) / dim_state(dim) / subtype(dim)

_PARENT_ATTACH_ITEMS = [
    "依恋关系-信任-母亲", "依恋关系-信任-父亲",
    "依恋关系-沟通-母亲", "依恋关系-沟通-父亲",
    "依恋关系-亲近-母亲", "依恋关系-亲近-父亲",
]
_ATTACH_RANK = {"高": 3, "不低": 2, "偏低": 1}
_HOLLAND_ITEMS = ["职业兴趣-现实型", "职业兴趣-研究型", "职业兴趣-艺术型",
                  "职业兴趣-社会型", "职业兴趣-事业型", "职业兴趣-常规型"]


def _p_parent_attachment_safe(ctx) -> bool:
    """亲子依恋（父母六项）现存项全部 ≥ 不低，且至少存在一项。"""
    vals = [ctx.eval_of(l) for l in _PARENT_ATTACH_ITEMS]
    vals = [v for v in vals if v]
    return bool(vals) and all(v in ("高", "不低") for v in vals)


def _p_parent_attachment_asymmetry(ctx) -> bool:
    """父母依恋同子项档位相差 ≥ 2 档（信任/沟通/亲近 任一）。"""
    for sub in ("信任", "沟通", "亲近"):
        m = ctx.eval_of(f"依恋关系-{sub}-母亲")
        f = ctx.eval_of(f"依恋关系-{sub}-父亲")
        if m in _ATTACH_RANK and f in _ATTACH_RANK:
            if abs(_ATTACH_RANK[m] - _ATTACH_RANK[f]) >= 2:
                return True
    return False


def _p_parent_attachment_low(ctx) -> bool:
    """父母依恋存在子项偏低。"""
    vals = [ctx.eval_of(l) for l in _PARENT_ATTACH_ITEMS]
    return any(v == "偏低" for v in vals)


def _p_parent_attachment_high(ctx) -> bool:
    """父母依恋（信任/沟通）存在子项 = 高。"""
    vals = [ctx.eval_of(l) for l in ("依恋关系-信任-母亲", "依恋关系-信任-父亲",
                                     "依恋关系-沟通-母亲", "依恋关系-沟通-父亲")]
    return any(v == "高" for v in vals)


def _p_peer_attachment_high(ctx) -> bool:
    vals = [ctx.eval_of(l) for l in ("依恋关系-亲近-同伴", "依恋关系-信任-同伴")]
    return any(v == "高" for v in vals)


def _p_peer_attachment_not_low(ctx) -> bool:
    vals = [ctx.eval_of(l) for l in ("依恋关系-亲近-同伴", "依恋关系-信任-同伴")]
    vals = [v for v in vals if v]
    return bool(vals) and all(v in ("高", "不低") for v in vals)


def _p_holland_peak_exists(ctx) -> bool:
    return any(ctx.eval_of(l) == "高" for l in _HOLLAND_ITEMS)


def _p_holland_three_plus_notlow(ctx) -> bool:
    return sum(1 for l in _HOLLAND_ITEMS if ctx.eval_of(l) in ("高", "不低")) >= 3


def _p_recovery_deficit_two_hits(ctx) -> bool:
    hits = 0
    if ctx.eval_of("体质健康-睡眠评级") in BODY_WATCH:
        hits += 1
    if ctx.eval_of("体质健康-运动评级") in BODY_PROBLEM:
        hits += 1
    if ctx.eval_of("体质健康-饮食评级") in BODY_PROBLEM:
        hits += 1
    return hits >= 2


def _p_emotion_items_all_healthy(ctx) -> bool:
    vals = [ctx.eval_of(l) for l in ("情绪稳定性-焦虑安详", "情绪稳定性-抑郁愉快")]
    vals = [v for v in vals if v]
    return bool(vals) and all(v == "相对健康" for v in vals)


def _p_schedule_overload(ctx) -> bool:
    level = str(ctx.ev("ft.schedule.load_level") or "").strip()
    if level in ("高", "high"):
        return True
    hours = ctx.ev("ft.schedule.free_hours_per_week")
    try:
        if hours is not None and float(hours) <= float(ctx.params.get("schedule_free_hours_max", 5)):
            return True
    except (TypeError, ValueError):
        pass
    return False


def _p_prior_engagement_same_domain(ctx) -> bool:
    return bool(ctx.ev("observation.prior_engagement_same_domain")
                or ctx.ev("ft.prior_engagement_same_domain"))


def _p_parent_complaint_present(ctx) -> bool:
    tags = ctx.ev("parent.complaint.tags")
    text = ctx.ev("parent.complaint.text")
    if isinstance(tags, (list, tuple)) and len(tags) > 0:
        return True
    return bool(str(text or "").strip())


def _subject_gaps(ctx) -> List[str]:
    entries = ctx.ev("ft.subject_status") or []
    gaps = []
    if isinstance(entries, list):
        for e in entries:
            if isinstance(e, dict) and e.get("gap") in ("below", "above"):
                gaps.append(e["gap"])
    return gaps


def _p_subject_mismatch(ctx) -> bool:
    return bool(_subject_gaps(ctx))


def _p_subject_below_actual(ctx) -> bool:
    return "below" in _subject_gaps(ctx)


def _p_subject_above_actual(ctx) -> bool:
    return "above" in _subject_gaps(ctx)


def _p_standard_task_done(ctx) -> bool:
    st = ctx.ev("ft.standard_task")
    return isinstance(st, dict) and st.get("can_split") is not None


def _p_standard_task_cannot_split(ctx) -> bool:
    st = ctx.ev("ft.standard_task") or {}
    return isinstance(st, dict) and st.get("can_split") is False


def _p_standard_task_cannot_commit(ctx) -> bool:
    st = ctx.ev("ft.standard_task") or {}
    return isinstance(st, dict) and st.get("can_split") is True and st.get("can_commit") is False


def _p_value_link_absent(ctx) -> bool:
    """当前任务可连接的价值观均不在前 N 位（无任务信息时不判，v0.2 待定）。"""
    connect = ctx.ev("task.connect_values")
    if connect is None:
        connect = ctx.params.get("value_link_defaults") or []
    if not connect:
        return False
    for v in connect:
        pos = ctx.order_pos(str(v))
        if pos is not None and pos <= int(ctx.params.get("order_top_n", 5)):
            return False
    return True


PREDICATES = {
    "parent_attachment_safe": _p_parent_attachment_safe,
    "parent_attachment_asymmetry": _p_parent_attachment_asymmetry,
    "parent_attachment_low": _p_parent_attachment_low,
    "parent_attachment_high": _p_parent_attachment_high,
    "peer_attachment_high": _p_peer_attachment_high,
    "peer_attachment_not_low": _p_peer_attachment_not_low,
    "holland_peak_exists": _p_holland_peak_exists,
    "holland_three_plus_notlow": _p_holland_three_plus_notlow,
    "recovery_deficit_two_hits": _p_recovery_deficit_two_hits,
    "emotion_items_all_healthy": _p_emotion_items_all_healthy,
    "schedule_overload": _p_schedule_overload,
    "prior_engagement_same_domain": _p_prior_engagement_same_domain,
    "parent_complaint_present": _p_parent_complaint_present,
    "subject_mismatch": _p_subject_mismatch,
    "subject_below_actual": _p_subject_below_actual,
    "subject_above_actual": _p_subject_above_actual,
    "standard_task_done": _p_standard_task_done,
    "standard_task_cannot_split": _p_standard_task_cannot_split,
    "standard_task_cannot_commit": _p_standard_task_cannot_commit,
    "value_link_absent": _p_value_link_absent,
}


def merge_params(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """DEFAULT_PARAMS ← 深合并覆盖（规则版本 params）。不修改本模块数据。"""
    import copy
    base = copy.deepcopy(DEFAULT_PARAMS)
    if overrides:
        _deep_merge(base, overrides)
    return base


def _deep_merge(dst: Dict[str, Any], src: Dict[str, Any]) -> None:
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v


def apply_rule_overrides(rules: Optional[Dict[str, Dict[str, Any]]] = None,
                         overrides: Optional[Dict[str, Dict[str, Any]]] = None
                         ) -> Dict[str, Dict[str, Any]]:
    """规则版本覆盖：仅允许覆盖 when / then / questions（不改动 id/dim/text）。"""
    import copy
    data = copy.deepcopy(rules if rules is not None else RULES)
    for rid, ov in (overrides or {}).items():
        if rid not in data or not isinstance(ov, dict):
            continue
        for key in ("when", "then", "questions"):
            if key in ov:
                data[rid][key] = copy.deepcopy(ov[key])
    return data


def rules_for_dim(dim: str, rules: Optional[Dict[str, Dict[str, Any]]] = None
                  ) -> List[Dict[str, Any]]:
    data = rules if rules is not None else RULES
    return [r for r in data.values() if r.get("dim") == dim]