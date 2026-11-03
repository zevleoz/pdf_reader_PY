"""M1 生成提示词与安全关键词（中文）。

每个提示词一个命名常量，便于单独调优。提示词只写规则与 JSON
schema，资料与证据以 JSON 附在末尾（标记见 ``pipeline``）。

Wave 3（2026-10-28）按真实模型输出调优：补上 potential / interference /
recommend / 证据核验的定义与《M1 FM会前准备框架》的勾选原则，限制字数，
禁止在正文里写证据 id，事件必须是真实发生过的具体情境。
"""
from __future__ import annotations

from ai_writing import ACCURACY_RULES, rules_block

# 安全扫描关键词：出现后由 AI 做一次是/否核实
SAFETY_KEYWORDS = (
    "自杀", "自伤", "自残", "轻生", "不想活", "活不下去", "结束生命",
    "割腕", "遗书", "虐待", "家暴", "被打", "性侵", "猥亵",
)

# 所有生成正文共用的写作要求：共用的准确性与写作规则 + M1 自己的补充
_STYLE = rules_block() + """

M1 补充要求：
- 读者是 M1 Mentor。纯文本，不用 Markdown。
- 正文里不要写证据 id（如 y4-013、src-2-1），来源用文字说明：First Touch 原话、家长反馈、老师课堂观察、Case Review 讨论、补充问卷、Y4。
- 不写任何分数或原始数值，Y4 只写指标名和档位，格式是“指标名：档位”。
- Y4 档位不是 R4 能力等级；Case Review 对 Y4 的解读只是待验证假设；6 A.M. 属于 Y4，不算第二个来源。
- Y4 的信任、沟通、亲近分数反映学生对关系的感受，不是沟通次数或频率；不要写成学生自己说的。
- 不做心理诊断，不使用病理化标签。"""

SAFETY_CHECK_PROMPT = """判断下面的资料片段是否包含需要立即人工核实的自伤、自杀、虐待或危机风险。
只做是/否判断，不写建议，不做诊断。只输出 JSON：
{"confirmed": false, "items": [{"source_ref": "", "text": "原文片段"}]}

【安全片段】
%s"""

SOURCE_ITEMS_PROMPT = """你是 M1 会前准备助手。只使用这份资料，不补充资料以外的信息。
把资料拆成证据条目，一件事一条：
- text：一句完整的中文陈述，不超过 60 字，只说 quote 里说了的内容，不增加时间、人物、次数、原因或感受；
- quote：资料原文的逐字片段，必须能在原文中原样找到；
- abilities：与之直接相关的 R4 能力编号，按能力名称判断（只从资料附带的 abilities 列表里选，可多选，可空）；
- kind：direct（学生的真实行为、经历或原话，或他人亲眼所见）| context（家庭、学校、同伴等环境与近期变化）| inference（他人的看法或推测）| indirect（测评或问卷类信息）| hypothetical（对尚未发生情境的设想，如回答“如果下次……你会怎么做”）；
- prompted：学生只是附和导师的引导性提问（如“可能吧”“对”）时为 true，否则为 false。
- independent：仅 Case Review 需要。老师亲眼观察到的具体行为为 true；基于 Y4、测评或印象的推测、建议为 false。
资料里导师的提问、解释和推测不是学生的想法；学生后来更正的，以更正后的说法为准；假设性回答不是实际发生的事。
学生中途改口时，只记录改口后的说法。
student_gender 为空表示资料没有写明性别，此时不用“他”“她”指代学生，写“学生”。
不做诊断；纯文本；只输出 JSON：
{"items": [{"text": "", "quote": "", "abilities": [], "kind": "direct", "prompted": false, "independent": false}]}

【资料】
%s"""

SOURCE_SUMMARY_PROMPT = """你是 M1 会前准备助手。下面是学生在「%s」这份资料里的证据条目。
写 2 到 4 句完整的话，说明这份资料实际讲了学生的什么情况：
- 只使用给出的证据条目，不补充条目以外的内容。
- 每句都是完整的句子，不要写成用分号连接的短语。
- 每句在 evidence_ids 里列出它依据的条目 id，id 只放在这里，不要写进句子。
- 资料是 Case Review 时，写明哪些是老师亲眼观察到的（kind 为 direct），哪些只是老师的猜测或印象（kind 为 hypothesis 或 inference），不要把猜测写成事实。
纯文本。只输出 JSON：
{"sentences": [{"text": "", "evidence_ids": []}]}

%s

【证据】
%s"""

ABILITY_PROMPT = """按 R4 能力逐项整理证据，只使用给出的证据，不编造。

字段含义：
- potential：支持该能力发展的资源或积极线索，每条写成一句完整的话，不超过 50 字，自然地说明它来自哪个来源。有相关证据就要写，不要留空。只写发生了什么或谁说了什么，不写“说明具备”“反映”“机制”这类结论。
- interference：可能妨碍该能力的表现或线索，写法同上。
- known：已知证据能说明什么（不超过 60 字）。
- new_clues：Y4 以外的新增线索（不超过 60 字）。
- contradictions：只有两条证据说的是同一件事、内容确实互相矛盾时才写，格式 [{"a": "证据id", "b": "证据id"}]。两条证据来自不同来源。不同事件、不同情境的差异不算矛盾。没有就写空数组。
- missing：还缺少的关键事实，每条不超过 30 字，最多 3 条。
- check_text：“证据核验”，最多两句、不超过 80 字：用第三人称概括目前知道什么，写“学生”，不用“我”。不要照抄 quote，不要把几条证据用分号串起来，不要把不同事件混在一起。不要写“依据来自”“可信度”这类话。每句只写一件事；不要把不同事件写进同一句，也不要写资料里没有的后果（如“影响关系”）。
- recommend：是否建议本次会议优先核实。只有同时满足以下两点才为 true：
  1) 至少有一条来自学生、家长或老师的真实情境线索与该能力直接相关；
  2) 至少满足一项：对学习、睡眠或关系有现实影响；Potential 与 Interference 并存；不同来源不一致；学生或家长关注；Case Review 提出的待验证方向。
  只有 Y4 档位，或只是因为缺少资料，都不推荐。勾选只代表“建议优先确认”，不代表能力有问题。
- reason_code：推荐的理由，只能是 impact（对学习、睡眠或关系有现实影响）| both（Potential 与 Interference 并存）| conflict（两个不同来源说法不一致）| concern（学生或家长明确提到这方面的担心）| case_review（Case Review 提出的待验证方向）| none。不要自己写理由。
- cites：本条判断用到的证据 id（只放在这里）。没有可引用的证据时 cites 为空，potential、interference 也为空。
kind 为 hypothetical 的条目只是学生的设想，没有实际发生：不能写进 potential、interference、known，不能作为推荐依据；提到时必须写明“学生设想”。

%s

只输出 JSON：
{"abilities": [{"code": "R1.1", "potential": [], "interference": [], "known": "",
 "new_clues": "", "contradictions": [{"a": "", "b": ""}], "missing": [], "check_text": "",
 "recommend": false, "reason_code": "none", "cites": []}]}

维度：%s
【能力】
%s
【证据】
%s"""

PRIORITY_PROMPT = """为下列每一项优先能力写两句话，每一项都要输出：
- hypothesis：可被证据支持的初步假设，不超过 70 字。语气保持试探，用自然的措辞表达（如“可能”“看起来”“还需要了解”），不下结论，各项之间不要套用同一个句式；
- why：为什么本次会议需要确认，不超过 70 字，说明现实影响、关键缺口、来源矛盾或 Case Review 待验证方向。

%s

只输出 JSON：
{"items": [{"code": "R1.1", "hypothesis": "", "why": ""}]}

【优先能力】
%s
【证据】
%s"""

MEETING_PLAN_PROMPT = """设计本次 M1 First Meeting 的会议准备（会议 %s 分钟，最多 %s 个重点事件）。

events（重点事件）：
- 只从下方“事件证据”里选真实发生过的具体情境（资料里写到的时间、地点、发生了什么），evidence_ids 填对应 id；
- 优先选一个事件能同时核实多项优先能力的情境；尽量让每项优先能力都落在某个事件里；
- title：情境名称，不超过 20 字，只使用证据里出现过的词；证据里没有写日期，标题里就不写日期；
- abilities：只从下方“优先能力”里选；
- gap：这个事件里还需要核实的具体事实，不超过 60 字，不增加证据里没有的细节；
- questions：2–4 个开放式问题，每个不超过 35 字，围绕这个事件，按需要沿“发生了什么 → 当时的感受和想法 → 怎么应对 → 和他人怎么沟通 → 后来怎样恢复”提问；语言自然，适合中学生，不暗示学生有问题，不用“……吧？”“是不是很……”这类带预设的问法，不用比喻、画画、打分之类的练习，不连续追问“为什么”。
没有可用的真实事件时 events 为空数组，不要编造。

special：
- context：家庭、学校、同伴或近期生活变化，只描述证据里写到的情境，不评价能力；
- attention：资料时效、关键资料缺失、可能的风险信号；不要写给导师的操作建议。
- context_ids、attention_ids：这两段文字依据的证据 id，只放在这里。没有证据依据的内容不要写。

backup_questions：没有放进任何事件的优先能力，各写 1 个直接问学生的开放式问题（不超过 35 字，用“你”称呼学生），格式 {"R3.5": "……"}。

growth：
- wish：会议结尾可以问学生的 1–2 个问题，了解他希望哪里变得更轻松、希望怎样被支持；
- next：可以讨论的练习或支持方向，不超过 50 字；正式 Intervention 在会后由 Mentor 决定，不要写成作业或行动方案。

%s

只输出 JSON：
{"events": [{"title": "", "evidence_ids": [], "abilities": [], "gap": "",
 "questions": []}],
 "backup_questions": {},
 "special": {"context": "", "context_ids": [], "attention": "", "attention_ids": []},
 "growth": {"wish": "", "next": ""}}

【事件证据】
%s
【优先能力】
%s
【全部证据（用于 special）】
%s"""
