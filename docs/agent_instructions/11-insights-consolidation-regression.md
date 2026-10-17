# Agent K 指令包：洞察页收编 + 报告生成反馈强化 + 全站回归

> 「管线驾驶舱」 redesign 第四包（收尾）。方向契约见 `08-global-interaction-layer.md` 头部。范围决策（需求方 2026-10-16 批准）：**全站一起收编**，洞察页从 serif editorial 转入工具密度。

## 1. 背景与目标

三个改动：

1. **洞察页收编**：dashboard / Y4 研判 / 6AM 从 serif editorial 风格进入工具系统（sans、13px 数据区、40px 行高、令牌化），图表与数据内容不动
2. **报告生成页反馈强化**：上传/生成的状态机可视化（逻辑一行不动，只状态化视觉）
3. **全站回归**：redesign 三件套（08/09/10）落地后的完整核对

## 2. 前置依赖

08、09、10 包全部完成并各自验收通过。

## 3. 现状文件地图

| 文件 | 说明 |
|---|---|
| `templates/dashboard.html` | 数据总览：serif 大标题 + 目录侧栏 + editorial 数字排版；统计逻辑在 `db.py`（不许动） |
| `templates/y4_signals.html` | Y4 研判四名单 |
| `templates/six_am.html` / `six_am_rules.html` | 6AM 档案与规则版本 |
| `templates/index.html` | 报告生成页：4 上传槽 + 分片上传 JS + 轮询（**JS 逻辑不许动**） |
| `templates/transcript.html` / `internal.html` / `prompt_lab.html` / `admin_bookings.html` | 工具组页面（D 包已换壳，内部样式各立） |
| `static/admin.css` | 令牌库（08 包已加密度/动效/反馈规范） |
| `templates/layouts/admin.html` | 壳（含 Tailwind inline config 的字体栈定义） |

## 4. 禁止事项

- **不改** dashboard 统计逻辑（db.py）、y4_questions.py、six_am/ 包——只动它们的模板排版
- **不改** `index.html` 的分片上传/轮询/下载 JS 逻辑一行（D 包时已验证）；本包只在它外面套状态视觉
- 不改报告 PDF 模板（report.html / report_v2.html / report_en.html）——serif 在那里**保留**，那是对外交付物
- 不改落地页与预约公开页
- 零 schema 变更；遵守 08 规范

## 5. 任务分解

### 5.1 洞察页收编（dashboard / y4_signals / six_am / six_am_rules）

- [ ] **去 serif**：管理端模板中的 serif 字体类（核对 Tailwind config 里的 font-family 定义与各页 `font-serif`/手写 font-family）全部替换为系统 sans 栈；serif 保留范围：报告模板、落地页、学生端 H1（若学生端在用）
- [ ] **去双标题残留**：页内 serif 大标题块移除，页面标题统一由壳层顶栏承载；页内保留一句 13px muted 副标题说明
- [ ] **密度收编**：dashboard 的超大 editorial 数字（如占半屏的"5 份报告"）改为 stat 卡组（数字 28px semibold + 12px 标签）；目录侧栏保留但字号/间距进令牌；各图表区块间距统一到 `y4a-card` 体系
- [ ] **不动**：图表类型、数据端点、筛选交互逻辑
- [ ] y4_signals 四名单与 six_am 页同样收编排版；规则版本列表复用问卷规则页的卡片语言（视觉对齐即可，逻辑不动）

### 5.2 工具组页面密度统一

- [ ] transcript / internal / prompt_lab / admin_bookings：标题层级、按钮、表格、卡片全部落到 08 令牌；只换排版，内容结构不动
- [ ] 各页 mutating 按钮接 `.is-loading`；fetch 列表接骨架屏（有则）

### 5.3 报告生成页反馈状态机（视觉强化，零逻辑改动）

- [ ] 四个上传槽（A2/B3/B4/B6）状态化视觉：空态（虚线框+图标）→ 上传中（进度条+百分比+文件名）→ 已上传（success 描边+文件名+大小+移除按钮）→ 失败（danger 描边+错误横幅+重试）。**只给现有 JS 的状态变化加 class 钩子**——先读 index.html 现有 JS 的状态变量，class 切换挂在既有状态赋值处，一行逻辑不改
- [ ] 生成按钮按下后：`.is-loading` + 分阶段进度条（上传→解析→渲染→完成四段 stepper，读现有轮询返回的阶段字段映射；若现有进度只有百分比无阶段名，按百分比区间映射并在代码注释注明是视觉映射）
- [ ] 完成态：成功横幅 + 下载按钮组（v1/v2）高亮 + Toast

### 5.4 全站回归（redesign 总收口）

逐项打勾（每项记录实测结果）：

- [ ] **OCR 主链路**：上传 4 份测试 PDF → 进度实时可见 → v1/v2 下载 → 学生档案可见 → 重生成 PDF
- [ ] **问卷闭环**：规则识别 → 工作台行内确认（选链接）→ 学生无痕窗口打开链接作答提交 → 360° 问卷 tab 可见原始答案
- [ ] **管线**：/students 阶段栏计数与各阶段抽查一致；360° stepper 正确
- [ ] **⌘K**：纯键盘完成"搜学生 → 进档案 → 回工作台"
- [ ] **角色矩阵**：advisor 只见自己学生/任务；viewer 全只读且无写按钮
- [ ] **洞察页**：dashboard 各图表数据与收编前一致（截图对比）；y4_signals / six_am 功能不变
- [ ] **窄屏与 reduced-motion**：820px 管理端不崩（表格横向滚动）；reduced-motion 下无动画
- [ ] **公开面**：落地页 / 预约页 / 学生端 / /api/v1/* 零变化

## 6. 验收标准

- [ ] 管理端任何页面不再出现 serif 字体（grep 管理端模板验证）；报告 PDF 视觉零变化（生成一份对比）
- [ ] dashboard 首屏为 stat 卡 + 图表区，无占半屏的 editorial 大数字
- [ ] 生成页上传槽四状态可视；生成中 stepper 分段推进
- [ ] 5.4 回归清单全绿
- [ ] `git status` 干净、改动全部提交（遵循仓库提交习惯）

## 7. 常见坑

- dashboard 的 editorial 排版可能由该模板内联 CSS 驱动——改排版时只动模板与其内联样式，别碰数据计算 JS
- 上传槽状态钩子：index.html 的 JS 若在多处直接改 DOM，用 MutationObserver 或最小侵入地在既有状态赋值行加 classList 切换——**选择后者**，但要数清楚所有状态出口（成功/失败/重试），漏一个就会出现卡住的状态
- six_am_rules 与问卷规则页视觉对齐时，别共用模板片段——两套后端不同，各写各的，只对齐视觉语言
- serif 移除后检查字重层级：sans 下标题需要更明确的字重对比（600/500/400）来维持层级感

## 8. 遗留观察

**5.1 洞察页收编**
- dashboard 的「占半屏大数字」来自 `renderHero()`（144px serif 英雄区），已改写为 4 张 stat 卡（报告份数 / 参与学生 / 覆盖学校 / 年级跨度，数字 28px/600/tabular-nums）。同时删除了与之数字重复的「概览」`renderContext()` 区块、其 TOC 条目与 `countUp()` 计数动画，避免同一组数字出现两次。
- 区块密度用 CSS 完成而非逐段改 JS：`.sec` 直接改为卡片观感（surface + 1px line + 10px 圆角 + 20/24px 内边距），`.sec-title` 44px serif → 16px/600，`.sec-kicker` → 11px 等宽，`.sec-lede` → 13px muted；数据区基准降到 13px。图表 JS（makeDoughnut/makeBar/makeRadar/makeLine/makeDistChart/renderHeatmap/drawScatter/renderCharts/loadAI）一行未动，仅把 `FONT` 常量由 `'Inter'` 换成系统 sans 栈。
- `.dash-page` 左内边距 40→24px、`.dash-layout` gap 64→32px、`.dash-content` 改为纵向 flex gap 16px；1024/768 断点同步清理（删掉 hero/context 相关规则，stat-grid 降为 2 列/1 列）。

**全站去 serif**
- 管理端壳内模板（extends `layouts/admin.html` 的 17 个模板）已零 serif：统一删除 Google Fonts 网络字体 `<link>`（Noto Serif SC / Inter / JetBrains Mono），serif 声明换成系统 sans 栈，数字等宽改用系统 `ui-monospace, SFMono-Regular, Menlo, monospace`。
- `templates/style.css` 是公共页共用（landing / booking / api_docs / 报告模板），其 `.page-title` / `.card-title` / `.brand-name` 的 serif **不能删**；处理方式是管理端模板不再使用这些类。`users.html` 原先用了 `.card-title`，改为在本页作用域内 override（只改本页，不动 style.css）。
- 允许保留 serif 的范围（未改）：`report.html` / `report_v2` / `report_en.html`（对外交付物）、`landing.html` / `booking.html`（公开页）、`api_docs.html` 与 `prompt_lab_standalone.html`（独立 `<!DOCTYPE html>`，不经管理端壳；后者由 `prompt_lab_app.py` 单独渲染）。

**其余页面**
- `y4_signals.html` 页面自带一套 ShadCN scoped 令牌（`--ink #0f172a` / `--muted #94a3b8`），符合既定偏好，保留不动；本页实际 serif 为 0，改动只有：删掉与顶栏重复的 `.ys-title` H1、把 `.ys-sub` 留作 13px 副标题、删除未使用的字体 link、基准 14→13px。
- `six_am_rules.html` 的规则版本列表由表格改为卡片式列表以「视觉对齐」问卷规则页（`templates/questionnaires/rules.html`），但**未共用/未 import** 对方模板（两套后端不同，按 §7 要求各写各的）。
- `transcript` / `internal` / `prompt_lab`：只换排版（去 serif、去重复页头、卡片间距入令牌）+ 给既有 mutating 按钮补 `.is-loading` + fetch 列表首屏补 4 条 `.y4a-skeleton-row`。三页均无 `<table>`，故 `--y4a-table-row-h: 40px` 无适用对象，内部高密度卡片行保持原紧凑间距（信息密度优先，不强行拉高）。

**5.3 报告生成页状态机（零逻辑改动）**
- 四槽四态（空 / 上传中 / 已上传 / 失败重试）与生成四段 stepper 全部为「在既有状态赋值点旁追加 classList 切换」的钩子，未新增任何 `fetch` / 端点 / 请求参数（已用 diff 核对新增行无 `fetch(`、`api/`、`form.append`）。
- 后端轮询只返回 `percent/message/status`、没有阶段名，所以 stepper 的「上传→解析→渲染→完成」按百分比区间 0–30 / 30–60 / 60–95 / 95–100 做**视觉映射**（已在代码注释注明非后端阶段）。
- 后端也不存在「每槽独立上传百分比 / 每槽独立失败」，因此槽内上传态是「上传中…」文本、百分比只在全局进度条；失败是流程级（容器 `.is-error` + 横幅「重试」= 重跑 `generate()`）。`sessionStorage` 恢复路径刻意不加「报告已生成」横幅与 Toast，避免文案失实与二次提示。

**5.4 全站回归（已实测 / 未实测）**
- 已实测（Flask test client）：管理端 17 个页面 + `/api/students` 全部 200 且 `Noto Serif` 计数为 0；角色矩阵 viewer 对 `/workspace` `/generate` 返回 403（只读），advisor 全通；公开面 `/login` `/` `/booking` `/api/v1/health` 均 200；报告 PDF 模板未改动。
- 需人工/浏览器实测（本次未跑）：真实 4 份 PDF 上传 → 进度 → v1/v2 下载 → 落库 → 重生成；问卷「识别→行内确认→无痕窗口作答→360° 可见原文」闭环；⌘K 纯键盘流；820px 窄屏与 reduced-motion 目视；dashboard 各图表数据与收编前截图对比。
- `git status`：本仓库已累积大量早前包（08/09/10 及更早）的未提交改动与 untracked 文件，**未做混合提交**，以免把无关改动卷进同一 commit——提交策略待与需求方确认后再执行。

