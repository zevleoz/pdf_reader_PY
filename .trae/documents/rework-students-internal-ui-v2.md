# 计划：学生档案 + 内部下载页 UI 二次返工

## Summary
上一轮改动被否决。本轮做两件事：
1. **学生档案**（templates/students.html）：搜索栏现代化 + 列表改为「对齐列列表」，学校、顾问成为一眼可见的一等列。
2. **内部下载页**（templates/internal.html）：彻底放弃三栏并排，改为纵向堆叠的全宽 section；AI 解读 section 按内容动态显示/隐藏（无内容→完全不显示；有内容→可折叠，默认收起）；选择器改为「搜学生 → 自动选最新报告」的单入口流程；评价区上方控制条精简为一行。

不改动任何 API、后端逻辑、PDF/AI 生成逻辑。仅改两个模板（HTML/CSS/JS）。

## Current State
- `students.html`：工具栏 = 普通裸 `<input id="studentSearch">` + 裸 `<select id="statusFilter">`；列表 = 单行卡片，姓名为主，学校/顾问挤在姓名右侧的灰色 `sc-sub` 小字里，做不到一眼可见。JS：`loadStudents / filterStudents / renderStudents`。
- `internal.html`：`lab-topbar`（选择学生 select + 选择报告 select + 运行解读 + 状态）+ `lab-layout` 三栏 grid（AI 解读 / 有效评价 / 下载与操作）；`loadEvaluation()` 已支持回填 `currentReport.interpretation`；`onStudentChange` 只填充报告下拉不自动选择。
- 服务在 localhost:8000，改模板需重启。

## Proposed Changes

### A. templates/students.html
1. **工具栏现代化**
   - 搜索框：内联 SVG 放大镜图标（绝对定位在输入框内左侧），输入框留白 padding-left；圆角 10px、`--paper-2` 底色、聚焦时白底红边。
   - 状态筛选：`<select>` 换成三段式 segmented control（全部 / 已完成 Y4 / 未测评），active 项 = `--ink` 深底白字（复用 internal 页 `.mid-tab` 的视觉语言）；每个选项右侧带灰色计数。
   - 状态值存 JS 变量 `currentStatus`（替代 `statusFilter` select 的 value 读取）；`filterStudents()` 改读变量，函数名与搜索联动逻辑不变。
   - 搜索框下方或右侧加安静的结果计数行：「N 位学生」。
   - 保留「导出 CSV / 刷新」按钮。
2. **列表改对齐列列表**
   - 顶部列头行（小号 muted 字）：学生 ｜ 学校 ｜ 顾问 ｜ 状态 ｜ 操作。
   - 行 grid：`grid-template-columns: minmax(150px,1.1fr) minmax(0,1.3fr) minmax(90px,.6fr) 190px auto`；姓名列 = 姓名（serif 粗体）+ 年级小标签；学校列 = ink 色常规字重（一等信息）；顾问列 = ink-2 色；状态列 = 现有徽章；操作列 = 右对齐（查看报告 / 新建议程 / 重命名 / 删除，沿用现有类）。
   - hover 行为保留；`renderStudents()` 改为输出列头 + 行；内联重命名编辑器（`#rename-{id}`、Enter/Escape）原样保留。
   - 窄屏 (<860px)：隐藏列头，行退化为两行堆叠（姓名+状态 / 学校+顾问+操作）。
3. 搜索/筛选为空时显示现有空态文案。

### B. templates/internal.html
1. **布局：三栏 → 纵向全宽堆叠**（删除 `.lab-layout` 三栏 grid 及列样式）
   - 新结构 `.lab-stack`（宽 100%，padding 16px，max-width 1680px 居中）：
     - `lab-topbar`（重做，见 2）
     - `#aiSection`（动态，见 3）
     - 有效评价 section（全宽，见 4）
   - 删除 `lab-intro` 说明行。
2. **顶部操作栏重做（单入口选择器 + 下载区）**
   - 左侧：**学生选择器** = 一个 combobox 按钮（显示「选择学生…」或「姓名 · 年级」）；点击弹出绝对定位面板：搜索输入 + 学生列表（姓名 + 年级 + 学校，muted），选中后关闭面板。
   - **自动选最新报告**：选中学生后 `onStudentChange(sid)` 拉取报告列表，客户端按 id 降序取最新一条自动调用 `onReportChange(id)` 并加载有效评价 —— 用户不再需要点第二个下拉。
   - **报告切换 chip**：选择器右侧出现小 chip「报告 2026-06-01 ▾」，点开列出该生全部报告（最新在前，标「最新」），点击切换。无学生时隐藏。
   - 右侧：`☐ 包含原始数据`（小号 checkbox，id=includeRaw 保留）+ 三个紧凑下载按钮（Y4 报告 MD / Y4 数据 JSON / E4 协议；id 保留）+ 主按钮「运行解读」（无解读时）/「重新解读」（已有解读时动态改 label）+ 状态点。
   - 删除两个 `<select>`（`studentSelect`/`reportSelect` 改为隐藏 state 或直接由 JS 变量承担，重写 `loadStudentOptions`/`onStudentChange`/`onReportChange` 内部实现，保留函数名）。
3. **AI 解读 section 动态显示**
   - 包一层 `#aiSection`（white 卡片、可折叠）：
     - 无解读内容（未运行且报告无 `interpretation`）→ 整个 section `display:none`，页面上完全不存在。
     - 有内容 → 显示，**默认收起**为一条细头栏（约 44px）：「AI 解读 · 完成 · N 字 · 用时 Xs」+ 展开/收起箭头；展开后显示 `outputArea` 正文（保留 id：outputArea / outputMetaBar / metaTokens / metaTime，JS 不用大改）。
     - 点击「运行解读」→ section 立即出现，头栏状态「解读中…」；成功后保持收起并更新完成态；失败自动展开显示错误。
     - 编辑功能本轮不做（用户明确低优先级）。
4. **有效评价 section（主角，全宽）**
   - Section 头：左「有效评价」+ 当前学生/报告上下文；右：Y4 四维 / E4 框架切换（保留）。
   - **控制条合并为一行**（解决"名目繁杂"）：搜索框（带图标样式，同学生档案）+ 「只看已调整」+「E4 映射 n」靠左，计数（共/已评价/已调整/数据偏差/观望/备注）靠右同一行，quiet 文本。窄屏允许换行。
   - `evalArea` 全宽；`.eval-dim-body` 的 minmax 由 520px 提到 600px，让卡片列更宽更少；eval-card 固定列 grid、E4 中性灰标签等上一轮已确认的部分全部保留。
   - `filterEval / toggleFilterAdjusted / openMappingModal / switchEvalView / renderEvalCounts` 逻辑不动；空 `switchTab` 函数及残留引用一并清掉。
5. **弹层不动**：评价选择弹层、E4 映射弹层、modal 样式全部保留。

## Assumptions & Decisions
- 用户已确认：第 2 点 = 内部下载页整体控制区重做；学生档案 = 对齐列列表。
- AI 解读默认收起：用户原话「我不太需要看它」，收起不等于不可见。
- 自动选最新报告的"最新" = 报告列表中 id 最大者（与创建时间递增一致）。
- 不做 AI 解读编辑功能。
- 不改 app.py / API / AI / PDF 逻辑；`runE4Workflow`、下载按钮 id、`includeRaw` 全部原样保留。
- 无 emoji；配色沿用既有令牌（--ink/--muted/--red/--paper/--line），类别区分只用中性黑灰。

## Verification
1. `pkill -f "python3 app.py"` 后重启 `python3 app.py`（模板改动必须重启）。
2. 浏览器（MCP integrated_code_mode）：
   - 学生档案：搜索「Zay」过滤正确；segmented 三个状态切换计数正确；行内学校/顾问列文字可见且对齐；重命名/删除/新建议程可用；控制台零报错。
   - 内部下载：combobox 选学生 → 自动加载最新报告（无需点第二下拉）；报告 chip 可切换历史报告；无解读时 AI section 不存在；点运行解读 → 细头栏出现并显示「解读中→完成·N字」；有效评价全宽、控制条单行、卡片正常；三个下载按钮 + includeRaw 可用；<1100px 响应式正常；控制台零报错。
3. browser_use 视觉抽查两页。
