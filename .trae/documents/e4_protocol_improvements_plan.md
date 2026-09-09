# E4 协议改进计划

## Summary
对 E4 协议做 7 项改进：AI 深度思考、文件名含学生名、末尾干预/潜能名单判定、主结论醒目、移除所有 code、包含完整 Y4 解读、人机双友好。

## Current State Analysis
- `_format_e4_line` (app.py L2082): 每行输出 `code:XXX` 前缀
- `_assemble_e4_protocol` (app.py L2476): 协议拼装，无名单判定章节
- `_e4_step2_system` (app.py L2211): 固定四段结构（核心发现/薄弱点/低垂果实/追问建议），每个维度都走一遍 → 输出公式化
- `_e4_step3_system` (app.py L2429): 总览写三段（核心矛盾/真实优势/下一步）
- 前端 `e4State.fname` (prompt_lab.html L1381): `E4评估_protocol_${date}.md`，无学生名
- `lastOutput` (prompt_lab.html L796): Y4 解读师 output，已传给 Step3 作为 `interpretation`
- 当前 AI 分析引用指标用 `009 情绪稳定性总分` 格式（含 code 编号）

## Proposed Changes

### 1. AI 深度思考（`_e4_step2_system` + `_e4_step3_system`）
**文件**: app.py L2211-L2241 (step2 prompt), L2429-L2457 (step3 prompt)

**改什么**: 
- Step2: 去掉固定四段结构（核心发现/薄弱点/低垂果实/追问建议 per dimension），改为要求 AI 做整体分析：
  - "你不是在填表，你是在做一个有信息量的判断。对每个学生，你的分析结构应该不同。"
  - "先判断这个学生的核心矛盾是什么，再围绕它展开分析。不是每个维度都要写四段。"
  - "如果一个维度没有重要发现，一句话带过即可。如果一个维度是核心矛盾，深入展开。"
  - 保留五步任务（连结/拆分/分析/剖析/识别）但不再要求每个维度都做
  - 移除"按 E1→E2→E3→E4 顺序输出四个维度的分析"的硬格式
- Step3: 要求 AI 写一个有判断力的总览，不是机械列举

**为什么**: 当前输出公式化，每个维度都走四段，每个数据点都"可能影响XXX"。AI 没有在思考，在填表。用户要求 "AI needs to think to come up with an E4 that is not borderless. It's different for each case."

### 2. 文件名含学生名
**文件**: prompt_lab.html L1381, app.py `_assemble_e4_protocol` (从 student_name 取)

**改什么**: 
- 前端: `e4State.fname = \`${studentName}_E4协议.md\`` (如 `IrisLu_E4协议.md`)
- 需要从前端获取学生名，或从 API 返回中获取
- 简单方式: Step3 API 返回中增加 `student_name` 字段，前端用它拼文件名

### 3. 末尾干预/潜能名单判定（新章节）
**文件**: app.py `_assemble_e4_protocol` + 新增 `_determine_list_placement` 函数

**改什么**: 
- 在协议末尾（AI_USAGE_GUIDE 之前）加 `## 名单归属` 章节
- Python 规则兜底: 扫描 E1/E2 维度 items，如果 eval 值在 ["偏低","明显偏低","严重偏低","需关注","需特殊关注"] 中 → 有问题
  - E1 有问题 OR E2 有问题 → 倾向干预名单
  - E1 和 E2 都无问题 → 倾向潜能名单
- AI 主判断: Step3 prompt 增加要求，让 AI 基于全部数据判断学生归属，写出理由
- 最终协议中: 显示 AI 判断 + 规则兜底结果（如果矛盾则标注）
- 格式醒目: 大标题 + 加粗 + 可能的 emoji-free 视觉强调（如 `---` 分隔线 + blockquote）

**输出示例**:
```markdown
---

## 名单归属

> **干预名单**

**判断依据：**
- E1 情绪：情绪稳定性总分偏低，抑郁/焦虑需特殊关注 → 情绪存在问题
- E2 精力：睡眠/运动/饮食待判定 → 精力管理需关注
- 结论：情绪与精力维度均存在问题，建议进入干预名单

*规则兜底校验：E1 有偏低/需特殊关注指标 → 与 AI 判断一致*
```

### 4. 主结论醒目
**文件**: app.py `_assemble_e4_protocol`

**改什么**: 名单归属章节放在最末尾，用大标题 + blockquote + 加粗让它非常醒目
- 在协议开头 META 之后也加一个简短提示行: `归属: 干预名单 / 潜能名单`，让人一眼看到

### 5. 移除所有 code
**文件**: app.py `_format_e4_line`, `_assemble_e4_protocol`, `_e4_step2_system`, `_e4_step3_system`, `_E4_NAMING_RULE`

**改什么**:
- `_format_e4_line`: 移除 `code:{code}` 前缀
  - `[EVAL] code:009 | label:情绪稳定性总分 | raw:20 | eval:偏低` → `[EVAL] 情绪稳定性总分 | raw:20 | eval:偏低`
  - `[REF] code:047 | label:...` → `[REF] 体质健康-睡眠习惯得分 → 见首次出现维度`
  - `[NORM] code:128 | label:...` → `[NORM] 学习动机-深层动机常模平均数 | value:7.4`
  - `[ORDER] code:087 | label:...` → `[ORDER] 能力优势排序1 | value:内省能力`
  - `[JUDGE] code:009 | label:...` → `[JUDGE] 情绪稳定性总分 | ...`
- `_e4_step2_system` prompt: 
  - 移除 "用 Y4 指标原始编号+名称直接描述状态，如'009 情绪稳定性总分低'" 
  - 改为 "用 Y4 指标名称直接描述状态，如'情绪稳定性总分低'"
  - 移除 "所有结论须标注依据指标的原始编号+名称"
  - 改为 "所有结论须标注依据指标名称"
  - 示例中的 `(009 情绪稳定性总分)` → `(情绪稳定性总分)`
- `_e4_step3_system` prompt: 同上
- `_E4_NAMING_RULE`: 从 "code+label 是唯一权威命名" 改为 "label 是唯一权威命名"
- `AI_USAGE_GUIDE`: 移除 code 引用
- `_assemble_e4_protocol` 中 `seen_codes` 逻辑: 仍用 code 做去重判断（内部用），但输出不显示 code

### 6. 包含完整 Y4 解读
**文件**: app.py `_assemble_e4_protocol` L2597-L2602

**改什么**: 
- 当前: `if interpretation:` 才显示 Y4_INTERPRETATION 章节
- 改为: 如果有 interpretation，完整包含；如果没有，显示提示"（未提供 Y4 解读，请先运行 Y4 解读师）"
- 确保 Y4 解读和 E4 分析在同一 Markdown 中并存

### 7. 人机双友好
**文件**: app.py `_assemble_e4_protocol` + `_format_e4_line`

**改什么**:
- 数据行: 移除 code 后更简洁，`[EVAL] 情绪稳定性总分 | 20 | 偏低` 比 `[EVAL] code:009 | label:情绪稳定性总分 | raw:20 | eval:偏低` 更易读
- 考虑移除 `raw:` 和 `eval:` 前缀，用 `|` 分隔即可
- AI 分析段落: 去掉固定四段结构后更自然
- 名单归属: 用 blockquote + 加粗，人眼一目了然

## Assumptions & Decisions
- 名单判定: AI 主判断 + Python 规则兜底（用户确认）
- "有问题"标准: 偏低/明显偏低/严重偏低 + 需关注/需特殊关注（用户确认）
- code 在内部逻辑中仍用于去重和引用匹配，只是输出时不显示
- Y4 解读师 output 通过 `lastOutput` 变量传入，已有机制无需改动
- 不修改原始 PDF 生成和 AI 解读师逻辑（用户要求）

## Verification Steps
1. 启动服务器，运行 E4 工作流
2. 检查输出文件名含学生名
3. 检查输出中无 `code:XXX` 字样
4. 检查末尾有名单归属章节且醒目
5. 检查 Y4 解读完整包含
6. 检查 AI 分析不再公式化（每个维度都四段）
7. 检查协议人眼可读性
