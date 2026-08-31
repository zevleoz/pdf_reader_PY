# AI Prompt 迭代测试台（Prompt Iteration Loop）方案

## 摘要

用户的核心需求：用一组已有的测试数据（Cici 的 report\_data.json），跑 AI 解读 → 用户评价/评论 → 系统根据反馈自动修改 prompt → 重新跑 → 重复直到输出满意且可泛化。

这是一个**人机协作的 prompt 优化循环**，不是复杂的 playground。

## 当前状态分析

* 已有测试数据：`data/report_data.json`（Cici，初三女生，George school，完整 124 项 schema\_124）

* 已有 AI 解读接口：`app.py /api/chat`（读 prompts/ai\_interpreter.md + report\_data.json → 调 DashScope）

* 已有 prompt：`prompts/ai_interpreter.md`（475 行，Y4 四维框架 + 85 数据点规范 + 各维度判读逻辑）

* 缺失：**没有独立的"喂数据→出解读→收反馈→改prompt→重跑"的闭环**

## 方案：Prompt 迭代测试台

### 核心流程（一个页面完成全部）

```
加载测试数据 (report_data.json)
        ↓
  运行 AI 解读（用当前 prompt）
        ↓
  显示 AI 输出
        ↓
  用户评分（1-5星）+ 写评论（哪里好/哪里不好/怎么改）
        ↓
  系统调 AI 自动修改 prompt（基于用户反馈）
        ↓
  显示 prompt diff（改了哪里）
        ↓
  自动重新运行解读
        ↓
  显示新输出 vs 旧输出对比
        ↓
  用户再评分 → 循环
```

### 页面布局 `/prompt-lab`（受密码保护）

**三栏布局：**

**左栏：Prompt 编辑区（可查看可手改）**

* 显示当前 `prompts/ai_interpreter.md` 全文

* 可手动编辑

* 「保存 prompt」按钮

* 显示版本号（v1, v2, v3...每次迭代+1）

**中栏：AI 输出区**

* 顶部：「运行解读」按钮 + 模型/温度/max\_tokens 显示

* 中部：AI 输出的 Markdown 渲染

* 底部：历史输出列表（v1, v2, v3...可点击切换查看）

**右栏：反馈 + 迭代区**

* 评分（1-5 星）

* 反馈文本框（"输出太长了" / "没有用到四维框架" / "自创了术语" 等）

* 「提交反馈并迭代」按钮

* 点击后：

  1. 系统调 AI，输入「当前 prompt + 用户反馈 + 上次输出」，让 AI 修改 prompt
  2. 显示 prompt 改动 diff
  3. 自动用新 prompt 重新跑解读
  4. 新输出显示在中栏

***

## 具体文件改动

### 1. `app.py` 新增 4 个 API 路由

**a)** **`GET /prompt-lab`（加 @page\_login\_required）**

* 渲染 `prompt_lab.html`

**b)** **`POST /api/prompt-lab/run`**

* 参数：`{message?: "请给出完整解读"}`（可选，默认"请给出这份 Y4 报告的完整解读"）

* 逻辑：

  1. 读 `prompts/ai_interpreter.md`
  2. 读 `data/report_data.json`
  3. 拼 messages（和 /api/chat 逻辑一样）
  4. 调 DashScope
  5. 返回：`{ok, reply, tokens_used, time_ms, prompt_version}`

**c)** **`POST /api/prompt-lab/iterate`**

* 参数：`{feedback: "用户写的反馈", rating: 3, last_output: "上次的AI输出"}`

* 逻辑：

  1. 读当前 `prompts/ai_interpreter.md`
  2. 构造一个 meta-prompt：

     ```
     你是一个 prompt 优化专家。

     以下是当前用于 Y4 测评解读的 system prompt：
     ---
     {当前 prompt 全文}
     ---

     以下是用户对这个 prompt 生成输出的反馈：
     评分：{rating}/5
     反馈：{feedback}

     上次输出：
     ---
     {last_output}
     ---

     请根据用户反馈，修改上面的 system prompt。
     要求：
     - 只修改需要改进的部分，保留好的部分
     - 输出完整的修改后的 prompt（不是 diff）
     - 不要加任何解释，直接输出修改后的 prompt 全文
     ```
  3. 调 DashScope（用 qwen-plus）
  4. 把修改后的 prompt 写入 `prompts/ai_interpreter.md`（覆盖）
  5. 同时保存旧版本到 `prompts/versions/ai_interpreter_v{n}.md`
  6. 返回：`{ok, old_prompt, new_prompt, diff_summary}`
  7. 然后前端自动调 `/api/prompt-lab/run` 重新运行

**d)** **`POST /api/prompt-lab/save-prompt`**

* 参数：`{prompt: "手动编辑的 prompt 全文"}`

* 逻辑：直接写入 `prompts/ai_interpreter.md`

* 用途：用户手动改 prompt 后保存

### 2. `templates/prompt_lab.html`（新建）

* 三栏布局，沿用 `style.css` 设计系统

* 左栏：prompt textarea（只读/可编辑切换）+ 版本号 + 保存按钮

* 中栏：运行按钮 + AI 输出 Markdown 渲染 + 历史输出 tab

* 右栏：评分星星 + 反馈文本框 + 「提交反馈并迭代」按钮 + diff 显示区

* 前端 JS：

  * `runInterpretation()`：调 `/api/prompt-lab/run`

  * `submitFeedback()`：调 `/api/prompt-lab/iterate`，拿到新 prompt 后自动调 `runInterpretation()`

  * `savePrompt()`：调 `/api/prompt-lab/save-prompt`

  * 历史输出存储在前端 JS 数组里（不持久化，刷新清空）

### 3. `prompts/versions/` 目录（新建）

* 每次迭代自动保存旧版本：`ai_interpreter_v1.md`, `ai_interpreter_v2.md`...

* 方便回滚

## 假设与决策

**决策 1**：测试数据固定用 `data/report_data.json`（Cici 的数据）

* 不做预设档案选择器，先跑通一个案例

* 如果用户想换数据，手动替换 report\_data.json 即可

**决策 2**：迭代 prompt 用 AI 自动改，但也允许用户手动改

* AI 自动改：用户写反馈 → AI 修改 prompt → 自动重跑

* 手动改：用户直接在左栏编辑 textarea → 保存 → 手动点运行

**决策 3**：prompt 版本管理用文件系统（`prompts/versions/`），不用数据库

* 简单，够用

**决策 4**：不持久化输出历史

* 每次刷新页面清空（sessionStorage 可选保存当前会话）

* 重点是 prompt 迭代，不是输出归档

## 验证步骤

1. 打开 `/prompt-lab` → 看到三栏布局，左栏显示当前 prompt
2. 点「运行解读」→ 中栏显示 AI 对 Cici 数据的解读输出
3. 在右栏打 3 星 + 写反馈"输出太长，没有严格用四维框架，有自创术语"
4. 点「提交反馈并迭代」→ 看到 prompt diff + 自动重新运行
5. 新输出显示在中栏，对比看是否改进
6. 重复 3-5 直到满意
7. 最终 prompt 就是 `prompts/ai_interpreter.md` 的最新版本，直接可用于生产

## 风险处理

| 风险                     | 应对                       |
| ---------------------- | ------------------------ |
| AI 改 prompt 时把好的部分也改掉了 | 保存旧版本到 versions/，用户可手动回滚 |
| 迭代次数太多 token 消耗大       | 每次迭代显示 token 用量，用户有感知    |
| 手动编辑和自动迭代冲突            | 保存时加时间戳，手动保存后版本号也+1      |

