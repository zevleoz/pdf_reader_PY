# 内部下载页（/internal）实施计划

## 目标

把 Prompt Lab 中的生产可用功能搬到一个新的内部页面 `/internal`（导航名「内部下载」）：
保留下载前对每个维度数据点的 qualification（有效评价档位调整、E4 映射、三个下载入口、E4 工作流），
隐藏 prompt 本身与 prompt 迭代工具。本地版 `/prompt-lab` 原样保留（不加入口、不限制访问）。

## Repository Research

### 现状

- `/prompt-lab` 由 [app.py:1782](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/app.py#L1782-L1786) 提供，`@page_login_required` 保护；当前无任何页面导航链接到它（已是「隐藏页」）。
- [prompt_lab.html](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/prompt_lab.html) 为三栏布局（约 700 行自含 CSS + JS）：
  - 左栏：Prompt 可编辑 textarea + 保存按钮 → **生产页移除**
  - 中栏：两个 tab
    - tabAi：运行解读按钮 + AI 解读输出（`runInterpretation` → POST `/api/prompt-lab/run`，读 `data/report_data.json`）→ **保留**（Y4 JSON 的 `ai_interpretation` 依赖它）
    - tabEval：qualification 卡片列表、搜索、只看已调整、E4 映射入口、包含原始数据勾选、三个下载按钮（默认协议 / Y4 JSON / E4 协议）→ **全部保留**
  - 右栏：星级评分 + 反馈 textarea + 提交反馈自动迭代 + diff → **生产页移除**
  - 弹层 3 个：`evalPickerModal`（档位选择）、`mappingModal`（E4 映射编辑器）、`e4WorkflowModal`（E4 三步工作流进度/预览）→ **全部保留**
- 共享 API（新页面直接复用，URL 不改）：
  - GET `/api/prompt-lab/evaluation`、POST `/api/prompt-lab/evaluation/download`
  - GET/POST `/api/prompt-lab/e4-mapping`
  - POST `/api/prompt-lab/e4/step1|step2|step3`、POST `/api/prompt-lab/y4-export/json`
  - POST `/api/prompt-lab/run`
  - 仅 prompt 专属 API（`/prompt` GET、`/save`、`/iterate`）新页面不调用；按用户决策**不做限制**，随 /prompt-lab 保留。
- 数据源与 lab 相同：`data/report_data.json`（/generate 流程产出的当前工作数据），E4 映射存 DB 全局表。
- 生产/本地同一套代码（systemd gunicorn + `.env.production`），本次不引入环境开关。
- 导航结构：各页 `<nav class="topbar-nav">`，需加入口的三个页面：
  - [students.html:137](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/students.html#L137-L144)
  - [index.html:513](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/index.html#L513-L519)（/generate）
  - [transcript.html](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/transcript.html)（待定位 nav）

## Files and Modules

- `templates/internal.html`：**新建**，由 prompt_lab.html 裁剪改造（自含 CSS/JS，不引入构建工具）
- `app.py`：**新增 1 个路由** `GET /internal`（`@page_login_required`，渲染 internal.html）；不改任何现有 API
- `templates/students.html`、`templates/index.html`、`templates/transcript.html`：各加一个 `<a href="/internal">内部下载</a>` 导航项

## 实施步骤

1. **app.py 加路由**（prompt_lab_page 旁边）：
   ```python
   @app.route("/internal")
   @page_login_required
   def internal_download_page():
       return render_template("internal.html")
   ```

2. **新建 templates/internal.html**，以 prompt_lab.html 为底本：
   - `<title>` 改「内部下载 — Y4 综合测评系统」；顶部改为与其他页面一致的 topbar + `<nav class="topbar-nav">`（主页/预约/预约管理/学生档案/报告生成/解读会纪要/数据总览 + 当前项「内部下载」）
   - 布局 CSS：`.lab-layout` 由三栏 `1fr 1.2fr 1fr` 改为两栏 `1fr 1.4fr`（窄屏 ≤1024px 堆叠为单列）
   - 删除 DOM：左栏 prompt 编辑列整段、右栏「反馈 & 迭代」整段、顶栏 versionLabel、star rating 相关
   - 中栏两个 tab 保留；tabAi 去掉 historyTabs（版本历史仅服务迭代），保留输出区、运行按钮、tokens/耗时 meta
   - 保留：evalToolbar（搜索/只看已调整/E4 映射计数）、evalCounts、evalArea、下载栏（含原始数据勾选 + 三个按钮）、三个 modal 全部
   - JS 保留：`loadE4Meta / loadEvaluation / renderEval* / picker 全套 / mapping 全套 / collectEvalPayload / downloadBlob / downloadEvalMd / downloadY4Json / runE4Workflow 及 e4* 辅助 / downloadE4Content / renderMarkdown / setStatus / open|closeModal`
   - JS 删除：`currentRating`、`outputs/outputVersion/updateHistoryTabs`、`submitFeedback`、`savePrompt`、初始化里对 `/api/prompt-lab/prompt` 的拉取
   - `runInterpretation` 简化：去掉 iterateBtn/history 相关行，仅保留 运行 → 渲染输出/meta → 写 `lastOutput`（E4/Y4 下载仍需读取）
   - 初始化 IIFE 只调 `loadE4Meta()` + `loadEvaluation()`
   - 所有 fetch URL 保持 `/api/prompt-lab/*` 不变

3. **三处导航加入口**：students.html、index.html、transcript.html 的 topbar-nav 内追加
   `<a href="/internal">内部下载</a>`（transcript.html 先读取确认 nav 结构再改）。

4. **不改动**：evaluation_rules.py、db.py、任何 API 实现、/prompt-lab 页面与路由。

## Dependencies and Considerations

- internal.html 与 prompt_lab.html 存在大段 CSS/JS 复制。这是有意的：prompt_lab 是迭代试验台、internal 是冻结的生产 UI，两页独立演进；后续若 internal 稳定可再抽共享静态文件，本次不做。
- 数据是「当前工作数据」语义（report_data.json），与 lab 一致，不做学生选择器；使用流程：/generate 处理某学生 → /internal 确认档位/映射 → 下载。
- 页面与 API 均已有登录保护（页面未登录跳 /login，API 返回 403），无需新增鉴权。
- 生产部署走现有 git pull + systemctl restart 流程，无新依赖、无环境变量。

## Validation

1. `python3 -m py_compile app.py`
2. 本地起服务，未登录访问 /internal → 跳转 /login?next=/internal
3. 登录后 /internal：
   - qualification 列表加载（Iris 数据）、搜索/筛选、档位 picker 修改、恢复默认
   - E4 映射弹层打开、指认、保存、计数刷新
   - 运行解读 → 输出渲染、tokens/耗时显示
   - 「下载默认协议」「下载 Y4 JSON」内容正确（Y4 JSON 含 list_placement/question_verdicts/ai_interpretation）
   - 「下载 E4 协议」三步工作流：Step1 名单预览行显示「干预名单·强特质」，完成后协议含 [VERDICT] 行与名单归属章节并自动下载
4. 三个导航页（/generate、/students、/transcript）均出现「内部下载」链接且可跳转
5. /prompt-lab 仍可直接访问，功能不变
6. 窄屏视口下两栏堆叠、无横向滚动；modal 居中且不超出视口

## Risks

- 裁剪 prompt_lab.html 时误删共享 JS 函数导致 qualification/E4 报错 → 按函数清单逐项保留，用浏览器 console + 全流程点击验证兜底。
- E4 工作流产生真实 AI 调用（费用/耗时）→ 验证时 Step1 为纯 Python 可反复测；完整链路只跑一次确认。
- 复制页 CSS 与共享 style.css token 已对齐（var(--ink)/--red 等），视觉风险低。
