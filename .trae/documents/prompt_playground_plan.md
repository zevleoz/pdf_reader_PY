# AI Prompt 迭代测试台（Prompt Playground）方案

## 摘要

用户的核心痛点：当前每次测试 AI 解读 prompt，必须走完「上传 4 个 PDF → OCR → 验证 → 生成 report_data.json → 调 AI」的完整流程，耗时巨大，无法高效迭代 prompt。

解决方案：创建一个独立的 **Prompt Playground（AI 解读测试台）**，支持以下三个独立测试入口，让用户可以在不跑 OCR 流程的情况下快速测试和迭代 prompt。

## 当前状态分析

### 现有代码结构
- `app.py /api/chat`：AI 解读接口，工作流程是：
  1. 读 `prompts/ai_interpreter.md`（system prompt）
  2. 读 `data/report_data.json` → 提取 `schema_124`（124 项指标）和 `student` 信息，拼接成 context
  3. 调 DashScope qwen-plus → 返回结果
- 关键依赖：**`data/report_data.json` 的存在**
- 现有资源：
  - `fake_data.py` 的 `build_fake_report()` 可以生成一份 sections 结构的假数据
  - `data_points.py` 从 `data/report_data.json` 读取 schema_124 结构
  - 但 `data/report_data.json` 目前只有在 OCR 流程跑完才会生成

### 问题根因
- OCR 流程和 AI 解读紧耦合：AI 解读接口**只认** `data/report_data.json` 这一个输入源
- 没有"直接喂 JSON → 直接出解读结果"的独立通道
- 没有"对照多份学生档案快速试"的环境
- 没有"同一份数据反复试不同 prompt 版本"的对比机制

## 方案（三个测试入口，从快到慢，从轻到重）

### 入口 A：一键用 fake_data 生成 report_data.json（最快，0 秒准备）

用户点击页面上的一个按钮，程序自动：
1. 调 `fake_data.build_fake_report()`（sections 结构）
2. 将 sections 结构转换为 OCR 流程输出的 `{student, schema_124}` 结构
3. 写入 `data/report_data.json`（就像 OCR 真跑完了一样）
4. 然后用户回到 `/generate` 页面，AI chatbox 立刻就能工作

**成本：后端 2 个小函数 + 1 个按钮**

### 入口 B：Prompt Playground 页面（中等，核心测试台）

新建一个 `/prompt-playground` 页面（受密码保护，和 /generate 一样），提供：

- **左侧：输入区**
  - 顶部：**加载预设档案下拉菜单**
    - 选项 1：示例同学（高一，默认 fake_data，正常档）
    - 选项 2：焦虑型学生（高神经质 + 低依恋母亲沟通 + 低睡眠，用来测假焦虑/真焦虑判断）
    - 选项 3：假自尊学生（自我概念高 + 自尊低 + 行为表现高，用来测假自尊识别）
    - 选项 4：聪明但懒学生（推理>90 + 责任心低 + 深层低表面高 + 睡眠差）
    - 选项 5：假抑郁学生（抑郁低 + 睡眠饮食正常 + 能力学校低 + 自主低）
    - 选项 6：上传自定义 `report_data.json` 文件
  - 中部：**JSON 编辑器**（显示/可编辑当前加载的学生 schema_124 数据，可以手动改某个指标的值来试边界情况）
  - 底部：**初始提问文本框**（默认填"请给出这份 Y4 报告的完整解读"，可自定义）
- **右侧：输出区**
  - 「运行解读」按钮
  - AI 输出的 Markdown 渲染结果
  - 下方：**tokens 用量 / 耗时 / 原始 JSON** 元信息
- **顶部工具栏：**
  - 「重新运行（不缓存）」
  - 「保存为测试用例」（保存当前 JSON + 输出到本地，方便对比）
  - 「复制 prompt 已使用版本」（方便把 system + user 发给我做 debug）

**成本：app.py 加 2-3 个路由 + 新建 templates/prompt_playground.html**

### 入口 C：命令行单文件 CLI（最快的自动化回归）

新增 `scripts/test_prompt.py`，一个纯 Python 脚本：
```bash
# 用法：
python3 scripts/test_prompt.py --preset 焦虑型
python3 scripts/test_prompt.py --file path/to/report_data.json
python3 scripts/test_prompt.py --preset 全部
```
- 直接读 prompts/ai_interpreter.md，调 DashScope
- 输出保存到 `test_runs/{datetime}_{preset}.txt`
- 一键跑全部 5 个预设，生成对比报告
- 方便以后"改了 prompt → 一键跑 5 个典型案例"看变化

**成本：一个独立 Python 文件，不影响现有代码**

---

## 具体文件改动

### 1. `app.py`（新增 3 个路由 + 1 个工具函数）

**a) 工具函数 `_convert_sections_to_schema124(sections_report: Dict) -> Dict`**
- 输入：fake_data.build_fake_report() 的结构（{student, sections}）
- 输出：OCR 流程的标准结构（{student, schema_124}）
- 逻辑：遍历 sections → 每个 group → 每个 item → 打平成 schema_124 的 list of dict
- 同时提供反向兼容：如果传入的是 schema_124 结构就直接用

**b) `POST /api/playground/load-preset`**
- 参数：`{preset: "焦虑型"/"假自尊"/... 或 "fake_default"}`
- 返回：`{ok: true, student: {...}, schema_124: [...]}`
- 逻辑：根据 preset 生成对应档案的 sections/schema_124

**c) `POST /api/playground/interpret`**
- 参数：`{student, schema_124, message, history}`
- 逻辑：完全复用 `/api/chat` 的 DashScope 调用代码，但**不从磁盘读 report_data.json**，而是用请求参数里的 schema_124
- 返回：`{ok: true, reply, tokens, time_ms}`
- 这是整个 Playground 的核心接口：输入任意 JSON → 立刻出 AI 解读

**d) `GET /prompt-playground`（加 @page_login_required）**
- 渲染 playground 页面

### 2. `templates/prompt_playground.html`（新建）

- 左右两栏布局（输入 / 输出），沿用 style.css 的设计系统
- 顶部：预设选择下拉菜单 + 重新运行按钮
- 左栏：JSON 编辑（用 textarea + 美化样式即可，不必引入编辑器库）+ 初始提问
- 右栏：AI 输出 Markdown 渲染（复用 transcript.html 的 Markdown 渲染函数）
- 底部：元信息（tokens / 耗时 / 模型名）

### 3. `scripts/test_prompt.py`（新建）

- 独立 Python 脚本，可直接命令行运行
- 内置 5 个预设档案的生成逻辑（复用 `_convert_sections_to_schema124`）
- 输出到 `test_runs/` 目录
- `--preset 全部` 时，依次跑 5 个预设 + 汇总对比表输出

### 4. `fake_data.py`（可选小增）
- 新增 4-5 个预设档案生成函数：`build_anxious_report()`、`build_fake_esteem_report()` 等，每个对关键指标值做针对性的修改（在默认 fake_data 的基础上覆写关键项）
- 也可以不修改 fake_data.py，改在 playground/preset 逻辑里做覆写（更隔离，不污染演示用的 fake_data）

## 假设与决策

**决策 1**：`/api/playground/interpret` 不写磁盘的 report_data.json，从内存里用请求参数生成 messages
- 原因：A/B 两个用户同时玩 playground 时不会互相覆盖对方的 report_data.json

**决策 2**：预设档案的「定制化」在入口 B 和 C 里做，不污染 fake_data.py 本体
- fake_data.py 里仍然只保留 1 份默认示例数据
- 5 个测试档案 = 默认 fake_data + 关键指标覆写（例如焦虑型 = 默认 + 神经质调到>4 + 母亲沟通调到"低" + 睡眠调到"差"）

**决策 3**：JSON 编辑用 textarea，不上 Monaco/CodeMirror 等重型编辑器库
- 原因：保持轻量，用户只是偶尔改一两个值，没必要加几百 KB 的编辑器依赖

## 验证步骤

1. **入口 A 验证**：点 Playground 页的「加载示例同学」→「写入 report_data.json」→ 回到 `/generate` 页面 AI chatbox 能正常聊
2. **入口 B 验证**：选「焦虑型」预设 → 运行解读 → 看到 AI 正确输出「心力 × 精力连结：焦虑值高 + 母亲信任沟通低 + 睡眠差 = 真焦虑（来源于父母关系+精力）」等符合 prompt 要求的内容
3. **入口 B 手动改值验证**：把焦虑值手动改低 → 重新运行 → AI 输出从「真焦虑」正确切换为「无明显情绪异常」
4. **入口 C 验证**：`python3 scripts/test_prompt.py --preset 焦虑型` 命令行成功输出，`test_runs/` 目录下生成了 .txt 文件
5. **不影响生产流程验证**：生成 report 的 OCR 流程完全不受影响（API 没改，只是加了新 API）

## 风险处理

| 风险 | 应对 |
|---|---|
| Playground 泄露，未登录用户可访问 | `@page_login_required` 加在 `/prompt-playground` 路由上，和 `/generate` 同一道门 |
| 大量测试导致 DashScope token 用太多 | 在入口 C 脚本里加 `--dry-run` 模式，只打印 prompt 不调 API；页面上显示 tokens 用量让用户感知 |
| 预设档案和真实学生档案差距太大 | 预设档案的「修改幅度」贴近真实边界（如焦虑型不是调到极端，而是调到中等偏高的常见值） |
| prompt 改了后老测试结果失效 | `scripts/test_prompt.py` 每次保存输出时把 prompts/ai_interpreter.md 的 md5 一起存入文件名，方便对比 prompt 版本变化 |
