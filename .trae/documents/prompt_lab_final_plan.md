# Prompt 迭代测试台（Standalone Prompt Lab）方案

## 摘要

构建一个独立的 Prompt 测试台 `/prompt-lab`，用已有的 Cici 测试数据，跑 AI 解读 → 用户评分+评论 → AI 自动改 prompt → 重跑 → 循环直到满意。最终把迭代好的 prompt 直接用于生产。

## 当前状态

- 测试数据已就绪：`data/report_data.json`（Cici，初三，124 项 schema_124）
- 当前 prompt：`prompts/ai_interpreter.md`（475 行）
- AI 接口：`app.py /api/chat`（读 prompt + report_data.json → 调 DashScope qwen-plus）
- DashScope API Key 已配置

## 方案

### 新建文件

1. **`templates/prompt_lab.html`** — 三栏布局测试台页面
2. **`prompts/versions/`** 目录 — 自动保存 prompt 历史版本

### 修改文件

3. **`app.py`** — 新增 4 个路由

### 页面布局 `/prompt-lab`

```
┌─────────────────────────────────────────────────────┐
│  Y4 Prompt Lab     [运行解读]  v3  tokens: 2340     │
├──────────────┬──────────────────┬───────────────────┤
│  Prompt      │  AI 输出          │  反馈 + 迭代      │
│              │                  │                   │
│  (可编辑     │  Markdown 渲染   │  ★★★☆☆ (1-5)    │
│   textarea)  │                  │                   │
│              │  v1 | v2 | v3    │  反馈文本框       │
│  [保存]      │  (切换历史)       │                   │
│              │                  │  [提交并迭代]     │
│              │                  │                   │
│              │                  │  Diff 显示区      │
└──────────────┴──────────────────┴───────────────────┘
```

### API 路由

**a) `GET /prompt-lab`**（@page_login_required）
- 渲染 prompt_lab.html

**b) `POST /api/prompt-lab/run`**
- 读 `prompts/ai_interpreter.md` + `data/report_data.json`
- 调 DashScope，返回 `{ok, reply, tokens, time_ms}`

**c) `POST /api/prompt-lab/iterate`**
- 参数：`{feedback, rating, last_output}`
- 构造 meta-prompt：当前 prompt + 用户反馈 + 上次输出 → 让 AI 修改 prompt
- 保存旧版本到 `prompts/versions/ai_interpreter_v{n}.md`
- 新 prompt 写入 `prompts/ai_interpreter.md`
- 返回 `{ok, old_prompt, new_prompt, diff}`
- 前端收到后自动调 `/api/prompt-lab/run` 重跑

**d) `POST /api/prompt-lab/save`**
- 参数：`{prompt}`
- 直接写入 `prompts/ai_interpreter.md`（手动编辑后保存）

### 迭代循环

1. 用户点「运行解读」→ AI 对 Cici 数据出解读
2. 用户打分 + 写反馈（如"太长""有自创术语""没锚定四维"）
3. 点「提交并迭代」→ AI 自动改 prompt → 显示 diff → 自动重跑
4. 新输出 vs 旧输出对比
5. 重复直到满意
6. 最终 `prompts/ai_interpreter.md` 就是生产版本，直接可用

## 验证步骤

1. 打开 `/prompt-lab` → 三栏布局正常显示
2. 点「运行解读」→ AI 对 Cici 数据输出解读
3. 打 3 星 + 写反馈 → 点「提交并迭代」→ prompt 自动修改 + 重新运行
4. 历史输出可切换查看
5. 手动编辑 prompt → 保存 → 运行
6. 最终 prompt 直接用于生产（/api/chat 读的就是同一个文件）
