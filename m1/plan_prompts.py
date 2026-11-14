"""发展计划（内部版 / 家长版）提示词。

每次只写一个部分（资料、目标字段、总览、单节课、家长版），导师可以只重做一处。
提示词只写规则和 JSON 形状，资料以 JSON 附在末尾。共用规则放在 ``SHARED_RULES``，
各提示词用 ``%s`` 引用，写法同 ``m1/report_prompts.py`` 的 ``FAMILY_STYLE``。
"""
from __future__ import annotations

TASK_INPUTS = "任务：整理发展计划的四项学生资料"
TASK_GOAL = "任务：填写一项发展目标的当前起点与阶段预期进展"
TASK_PERSONAL = "任务：整理个性化需求"
TASK_OVERVIEW = "任务：写阶段总体目标与教学策略"
TASK_SESSION = "任务：设计一节发展计划课程"
TASK_PARENT = "任务：把已批准的内部版写成家长版"

SHARED_RULES = """写作要求（所有部分都必须遵守）：
- 像一位认真、具体的导师写作：平实、具体，不写个性、口号、广告语，不用表情符号。
- 只使用下面给出的资料。不要添加资料里没有的事件、人物、地点、分数或原话；不知道的就不要写。
- 不写结果承诺（显著提升、已掌握、彻底、稳定做到、解决），不写固定特质或缺陷词（缺陷、问题孩子、严重），不写诊断词。
- 学生是中国国际学校的一对一学生，计划去美国或其他海外大学读书。活动、例子和情境要贴合这样的生活（学校项目、朋友关系、宿舍或家庭生活、申请、语言切换）和学生的年龄；不要因此假设这个学生一定有某种经历。
- 不写系统或流程用语（例如：待核实、证据条目、JSON、模型）。
- 用短句，一件事写清楚就停，不写铺垫和总结句。"""

INPUTS_PROMPT = TASK_INPUTS + """
你在为一份《情绪力阶段发展与教学计划》整理四项资料。只写对这个 Block 的教学有用的内容，每项 1 至 3 句。
- strengths：可利用的积极资源。报告里已经显示的、可以支持这个学生成长的具体资源。
- needs：主要发展需求。当前最值得在这个 Block 里支持的方面，写成需要练习的方向，不写成缺陷。
- context：关键生活情境及能力表现。在哪些具体情境里，学生现在会怎么表现。
- interests：学生兴趣及学习偏好。喜欢什么、什么样的学习方式更容易参与。

每句话都必须来自下面的报告文字。报告里没有的，这一项留空字符串。

%s

只输出 JSON：
{"strengths": "", "needs": "", "context": "", "interests": ""}

【资料】
%s"""

GOAL_PROMPT = TASK_GOAL + """
下面是一项待导师确认的发展目标，以及报告里与这项能力有关的文字和匹配的计划建议。请填写三项：
- goal：发展目标。已有非空目标时原样保留；为空时优先依据 report_plan_suggestions 中匹配能力的建议，结合报告写出具体、可观察的发展目标。资料不足时只写这项能力可支持的小步练习，不编造学生表现。
- start：当前能力表现起点。报告显示学生现在在这项能力上会怎么做，写成具体行为，1 至 2 句。
- expected：阶段预期进展。三节课里可能看到学生尝试什么，1 至 2 句，写课堂里看得到的事，不承诺结果。

只写给出的资料能支持的内容；不要新增事件、人物或评价。

%s

只输出 JSON：
{"goal": "", "start": "", "expected": ""}

【资料】
%s"""

PERSONAL_PROMPT = TASK_PERSONAL + """
下面是导师填写的个性化需求，以及上传的会议记录文字。请写 2 至 3 句总结：家长、学生或导师提出了什么、提到了哪些情境、可以怎样放进这个 Block。
不要引用原话，不要评价家庭，不要写记录里没有的内容。

%s

只输出 JSON：
{"summary": ""}

【资料】
%s"""

OVERVIEW_PROMPT = TASK_OVERVIEW + """
请为这个 Block 写 3 至 5 句“阶段总体目标与教学策略”：三节课之间怎样一步步推进，每节课主要带哪一项目标。
如果能为三节课各定一个主要目标和一个辅助目标，在 sessions 里给出；不确定就返回空数组。
primary 和 supporting 只能从给出的目标编号里选，supporting 可以是 null。

%s

只输出 JSON：
{"overview": "", "sessions": [{"n": 1, "primary": "", "supporting": null}]}

【资料】
%s"""

WB_RULE = """WB 参考课规则：
下面最多提供 2 节 World Bank SEL 课作为背景思路。你可以改编其中一个想法，也可以忽略它们、自己设计。
- 绝不照抄步骤、学习单、故事、情境、人物姓名或问题清单，也不要翻译教材段落。
- 每个活动都必须是为这个学生重新设计的，贴合一对一课堂和他的年龄。
- 对每个活动设置 source.type：如果这个活动改编自下面某一节课，写 world_bank 并在 wb_id 里填那节课的编号；否则写 ai_original。绝不使用 other。"""

WB_NONE = "本次没有提供 WB 参考课。所有活动的 source.type 都写 ai_original。"

SESSION_PROMPT = TASK_SESSION + """
你在为第 %s 节课写教学计划。只写这一节，不要写其他课。
请按模板写 A 至 F：
- A 本节教学重点：focus.primary 是本课主要目标（必须是给出的目标编号之一），focus.supporting 是另一项给出目标或 null，focus.text 是一句话重点。
- B 核心学习内容：mindsets（需要时写）、skills、techniques，各一句。
- C 教学活动：数量不固定；每个活动写 name、minutes、steps（导师照着做的分步说明）、questions（导师可以直接说出口的引导问题）、materials（没有就写“无”）、source。活动总时长要符合一对一课堂的时长。
- D 课堂预期表现：1 至 2 件在这节课里就能看到的事，不写真实生活中的掌握。
- E 课后成长实践：1 至 2 项，每项写 code（给出的目标编号）、name、task、frequency、platform（只能是 StoryMap、Echo、无）、evidence（之后能看到的证据）。
- F 下次课准备：1 至 2 句，只在第 1、2 节写；第 3 节没有 F。

第 2、3 节要写 2 至 3 个“上次课后实践回顾”问题（review），问上一节练习的完成情况；第 1 节 review 返回空数组。
第 3 节不要自己写 Block Review，代码会在最后加上；第 3 节的实践可以延续前面的实践。

%s

%s

%s

只输出 JSON：
{"title": "", "review": [""], "focus": {"primary": "", "supporting": null, "text": ""},
 "content": {"mindsets": "", "skills": "", "techniques": ""},
 "activities": [{"name": "", "minutes": 15, "steps": "", "questions": "", "materials": "", "source": {"type": "ai_original", "wb_id": null}}],
 "evidence": "", "practice": [{"code": "", "name": "", "task": "", "frequency": "", "platform": "StoryMap", "evidence": ""}],
 "next_prep": ""}

【资料】
%s"""

PARENT_PROMPT = TASK_PARENT + """
下面是已批准的内部教学计划。请把它写成给家长看的两页文字，只使用这里的内容，不重新判断能力，不添加新目标。
- intro：开场介绍，60 至 %(intro)d 字。
- goals：每个目标一条，顺序和编号与内部版一致，每条 1 至 2 句，不超过 %(goal)d 字，不写新能力。
- sessions：三节课各一条，title 沿用内部版标题（只做轻微措辞调整，不超过 %(session_title)d 字），summary 30 至 %(session_summary)d 字；第 3 节要提到阶段回顾。
- transition：一句过渡，不超过 %(transition)d 字。
- practice：内部版每一项课后实践都要有一条家长版，ref 照抄内部版编号，title、text、frequency 写家长能懂的说法（分别不超过 %(practice_title)d、%(practice_text)d、%(practice_frequency)d 字），platform 照抄。不要自己挑选、合并或新增实践。
- family：2 条家庭协作建议，每条不超过 %(family)d 字。不指责家长，不下命令，不要求家长查看孩子的记录。
- review：2 至 4 项成长观察，每项一个短标签（不超过 %(review_label)d 字）和一句说明（不超过 %(review_text)d 字）；角度各不相同，用“可以观察”这样的未来说法，不重复目标原文。

%(rules)s

只输出 JSON：
{"intro": "", "goals": [{"code": "", "text": ""}],
 "sessions": [{"n": 1, "title": "", "summary": ""}], "transition": "",
 "practice": [{"ref": "", "title": "", "text": "", "frequency": "", "platform": ""}],
 "family": ["", ""], "review": [{"label": "", "text": ""}]}

【内部版】
%(payload)s"""
