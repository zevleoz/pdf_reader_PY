# Y4 AI Prompt 投入使用计划

## 摘要
将用户填写的 prompt_template.md 内容完善后替换为正式的 ai_interpreter.md，并调整 app.py 参数适配新 prompt。

## 当前状态分析
- `prompts/prompt_template.md`（499 行）：包含用户提供的完整 Y4 85 个数据点输出规范、11 个维度的判读逻辑、8 条跨指标关联原则。仍有 9 个 TODO 标记未填（主要是风格/调性/输出格式等定制化区域）
- `prompts/ai_interpreter.md`（163 行）：旧的简短 prompt，需被替换
- `app.py:407`：`max_tokens=4096`，新 prompt 更详细，输出会更长，需提到 8192

## 方案

### Step 1: 完善 prompt_template.md 中的 TODO 区域

对 9 个 TODO 标记，用以下默认值填充（基于用户 profile 和已有信息）：

1. **解读风格与调性**：专业但不生硬，像资深顾问跟家长聊天；目标读者=家长+顾问；输出 500 字左右
2. **解读思维模式**：不贴标签找杠杆点；5 步思维流程已预填，保留
3. **硬规则**：已预填，保留
4. **依恋关系补充**：补充分开解读规则的细节
5. **精力维度补充**：补充 BMI/睡眠/运动的具体判读档位
6. **输出格式**：用户说 500 字左右，调整为精简版结构
7. **禁忌事项**：已预填，保留
8. **Potential List vs Interference**：已预填，保留
9. 去掉所有 `<!-- TODO -->` 标记和填写指引注释

### Step 2: 替换 ai_interpreter.md

将完善后的内容写入 `prompts/ai_interpreter.md`（完全覆盖旧内容）

### Step 3: 调整 app.py 参数

- `max_tokens`: 4096 → 8192（新 prompt 输出更长，避免截断）
- `temperature`: 0.4 → 0.5（稍微增加表达多样性，避免过于机械）

### Step 4: 向用户展示最终 prompt 内容

在回复中展示完整的 ai_interpreter.md 内容供用户审阅

## 涉及文件
1. `prompts/ai_interpreter.md` — 完全重写（163 行 → ~450 行）
2. `app.py` — 修改 2 个参数（max_tokens, temperature）

## 假设与决策
- 用户说"500 字左右"，输出格式调整为精简版（不用 6 段式，改为 3 段式但内容更密集）
- 用户的 Y4 解读规则（85 数据点、真假区分、五大焦虑来源等）全部保留
- 去掉模板的元信息（填写说明、TODO 标记），只保留 AI 需要的指令内容

## 验证步骤
1. 检查 ai_interpreter.md 无 TODO 标记残留
2. 检查 app.py 参数已更新
3. 展示最终内容给用户确认
