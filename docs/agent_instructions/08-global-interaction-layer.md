# Agent H 指令包：全局交互层 —— 密度 · 动效 · 反馈 · ⌘K 命令面板

> 「管线驾驶舱」 redesign 的第一包（08/09/10/11）。方向已定稿并获需求方批准：**Linear 系气质**（高密度、键盘优先、克制动效、状态驱动），全站收编（含洞察页）。品牌色板不动。
> 本包产出**其余三包依赖的共享组件与规范**，必须先完成。

## Direction contract（方向契约，后续包与本包共同遵守）

- **THESIS**：每一屏先回答"现在需要我做什么"，再展示数据。从档案册 → 操作台。
- **OWN-WORLD**：暖纸底 `#FAF7F2` + 墨 `#161310` + 品牌红 `#D25454`（克制）；深色侧栏保留；sans 全局（serif 只留在对外交付物）。
- **密度**：Linear 系——数据区基准 13px，表格行高 40px，卡片间距收紧；信息密度优先于留白。
- **动效**：全部功能化，150-200ms `var(--y4a-ease)`，只出现在状态变化/展开/加载；`prefers-reduced-motion` 下全部关闭。
- **FINISH**：unreviewed and undocumented is unfinished——本包完成后按验收标准逐项实测（键盘、窄屏、reduced-motion），才算交付。

## 1. 背景与目标

当前管理端（A–G 包后）功能完整、视觉连贯，但页面是"文档感"：静态卡片、大留白、无即时反馈。本包建立四个全局能力：

1. **密度规范**（Linear 化）
2. **动效令牌与过渡规范**
3. **反馈状态系统**（Toast 强化、骨架屏、按钮 loading、错误横幅）
4. **⌘K 命令面板**（全局跳转 + 学生搜索）

## 2. 前置依赖

A–G 包均已完成（当前工作树状态）。本包不改任何业务逻辑与数据模型。

## 3. 现状文件地图（已核对 2026-10-16）

| 文件 | 说明 |
|---|---|
| `static/admin.css`（569 行） | 令牌与组件库。`:root` 有 `--y4a-*` 全套（含 `--y4a-ease`）；组件：y4a-card/table/badge/btn/empty/progress/stat/quick/grid；body 基准 14px |
| `templates/layouts/admin.html` | 壳：侧边栏 + 顶栏 + Toast 容器（`window.y4Toast`）；Tailwind Play CDN inline config 在此 |
| `templates/layouts/_icons.html` | 图标 macro（lucide 风格描边 SVG），新增图标走这里 |
| `templates/workspace.html` | 工作台（159 行，服务端渲染，y4a-card 区块） |
| `app_utils.py` | `register_admin_context`（模板上下文注入）、`get_csrf_token`；新共享模板函数加在这里的 context processor |
| `blueprints/students.py` | 学生查询函数所在；本包新增学生搜索只读端点 |
| `app.py` | CSRF：GET 与未登录豁免；新端点若为 GET 无 CSRF 负担 |

## 4. 禁止事项

- 不改 OCR 红线文件（spec 第 2 节）、不改部署文件、不改数据模型（**零 schema 变更**，本包纯前端+一个只读 GET 端点）
- 不改 Tailwind CDN / Alpine CDN 的技术决策；不加任何新依赖
- 学生端页面（`templates/student/`）不在本包范围
- serif 字体移除归 11 包（洞察页收编时统一做）；本包不动 dashboard 等页面

## 5. 任务分解

### 5.1 密度规范（`static/admin.css`）

- [ ] 新增密度令牌并应用：`--y4a-table-row-h: 40px`（现 44px）；数据区（表格、列表、徽章、表单）字号 13px 基准（`.y4a-table { font-size: 13px }` 等）；卡片 `y4a-card-body` padding 从 20px 收到 16px；页面主区 padding 32→24px
- [ ] 表格行高收紧后验证：徽章仍单行（06 的 nowrap 保持）、操作按钮组不折行
- [ ] 数字列统一 `font-variant-numeric: tabular-nums`（`.is-num` 已有则确认覆盖全站表格）

### 5.2 动效令牌与过渡规范

- [ ] `admin.css` 新增：`--y4a-dur-fast: 150ms`、`--y4a-dur: 200ms`；工具类 `.y4a-t`（`transition: all var(--y4a-dur-fast) var(--y4a-ease)`）
- [ ] 应用点（只许这些）：侧边栏收起/展开、分组折叠、卡片 hover 阴影微浮（`translateY(-1px)` + 阴影一档，仅可点击卡片）、tab 切换下划线滑动、Toast 进出、行内面板展开
- [ ] 末尾加 `@media (prefers-reduced-motion: reduce)` 关闭全部过渡与动画
- [ ] **禁止**：装饰性动画、parallax、入场动画、无限循环动画

### 5.3 反馈状态系统

- [ ] **Toast 强化**（`templates/layouts/admin.html` 现有 `y4aToast`）：加类型图标（success ✓ / error ✕ / info ⓘ，用 `_icons.html` 风格）、队列（最多 3 条堆叠）、4s 自动消失、`aria-live="polite"` 容器；API 不变（`window.y4aToast(msg, type)`）
- [ ] **骨架屏**：`.y4a-skeleton`（`background: linear-gradient(90deg, var(--y4a-paper-2) 25%, #EDE7DA 50%, var(--y4a-paper-2) 75%)` 200% 动画，reduced-motion 下静态）；变体 `.y4a-skeleton-row`（表格行高 40px 的条）。用法约定：所有 fetch 加载的列表，先渲染 3-5 条骨架再替换
- [ ] **按钮 loading 态**：`.y4a-btn.is-loading`——文字透明度 0.6、左侧 16px spinner（CSS border spinner）、`pointer-events:none`；约定：所有 mutating fetch 的按钮在请求期间加 `.is-loading`
- [ ] **错误横幅**：`.y4a-alert`（danger-soft 底 + danger 左边条 + 图标）；约定：fetch 失败在内容区顶部内联显示，不只靠 Toast

### 5.4 ⌘K 命令面板

- [ ] 新组件 `templates/layouts/_command_palette.html`（include 进 admin.html body 末尾）+ `static/command-palette.js`（Alpine 组件 `commandPalette()`）
- [ ] 快捷键：`⌘K` / `Ctrl+K` 打开；`Esc` 关闭；↑↓ 导航、Enter 执行；点击遮罩关闭；打开时焦点进搜索框
- [ ] 命令源两类：
  1. **静态页面命令**（前端常量数组）：新建报告生成 / 去工作台 / 学生档案 / 问卷任务 / 问卷题库 / 识别规则 / 数据总览 / Y4 研判 / 6AM / 预约管理 / 解读会纪要 / 用户管理（admin 才显示）——每项带分组名与图标
  2. **学生搜索**：输入 ≥1 字符时防抖 250ms 调 `GET /api/students/search?q=<kw>`（**本包新建此只读端点**，`blueprints/students.py`：`@login_required`，返回 name/student_code/school/advisor_name 前 8 条；Advisor 角色必须经 `visible_student_filter` 过滤）；结果选中跳 `/students/<code>`
- [ ] 面板视觉：居中浮层、宽 560px、surface 底、1px `line-strong` 边、顶部搜索框（无边框、16px）、结果分组标题 12px muted、选中行 brand-soft 底；reduced-motion 下无缩放动画
- [ ] 顶栏加一个触发入口（搜索图标 + `⌘K` 提示文案的按钮），点击同效

### 5.5 规范文档化

- [ ] 在 `static/admin.css` 头部注释追加"四、密度与动效规范 / 五、反馈状态用法约定"（骨架屏/loading/alert/Toast 的使用场景规则），供 09/10/11 包遵守

## 6. 验收标准

- [ ] 表格行高 40px、数据区 13px，全站表格统一；无布局破裂
- [ ] ⌘K 打开面板，输入"陈"能搜到学生并跳转其 360° 页；纯键盘可完成全流程；Advisor 登录只搜到自己学生
- [ ] 任意 fetch 列表页能看到骨架屏 → 内容替换（可在问卷任务页验证，若该页已按 09 改造）
- [ ] 按钮 `.is-loading` 在一次 mutating 操作上可视（可用节流复现）
- [ ] `y4aToast('测试','success')` 有图标、4s 消失、多条堆叠正常
- [ ] 系统级 `prefers-reduced-motion` 开启后，全部过渡消失
- [ ] 回归：所有现有页面功能不变；旧浏览器无 Alpine 时内容仍可读（面板不可用但页面完整）

## 7. 常见坑

- Tailwind Play CDN 的任意值与自定义 CSS 变量共存没问题，但**别在模板里再写内联 `style="transition:..."`**，统一走工具类
- ⌘K 面板在 `content` block 内会被 stacking context 困住——必须挂在 body 末尾（include 位置在 admin.html 的 Toast 容器旁）
- 学生搜索端点是 GET，CSRF 豁免天然成立；但**必须登录 + Advisor 过滤**，这是泄露面
- 防抖别用 `setTimeout` 裸写——Alpine 里用 `x-on:input.debounce.250ms`
- reduced-motion 检测：`window.matchMedia('(prefers-reduced-motion: reduce)')` 同时管 JS 侧（面板动画）

## 8. 遗留观察

（执行 agent 追加，2026-10-16）

### 落地清单（与本包 5.1–5.5 对应）
- 5.1 密度：`--y4a-table-row-h: 40px`；`.y4a-table` 基准 13px 且 th/td 行高走令牌；`.y4a-card-head`/`.y4a-card-body` 水平内边距统一 16px；`.y4a-content`/`.y4a-topbar` 左右 24px；`.y4a-grid` gap 16px。`workspace.html` 的 `px-5 pb-5` 同步收成 `px-4 pb-4` 以保持与卡片内边距对齐。
- 5.2 动效：新增 `--y4a-dur-fast(150ms)`/`--y4a-dur(200ms)` 与 `.y4a-t`；侧边栏、分组折叠、可点击卡片（`.y4a-quick` 现带 `translateY(-1px)`）、tab、Toast 全部改用令牌；文件末尾 `@media (prefers-reduced-motion: reduce)` 统一关闭过渡与动画。
- 5.3 反馈：Toast 加类型图标（`check-circle`/`x-circle`/`info`）、队列上限 3、4s 自动消失、容器已有 `aria-live="polite"`；新增 `.y4a-skeleton`/`.y4a-skeleton-row`、`.y4a-btn.is-loading`、`.y4a-alert`。
- 5.4 ⌘K：新增 `templates/layouts/_command_palette.html` + `static/command-palette.js` + 顶栏触发入口；新增只读端点 `GET /api/students/search`（`blueprints/students.py`，`@login_required` + `visible_student_filter`）。
- 5.5 规范：`admin.css` 头部已追加「四、密度与动效规范」「五、反馈状态用法约定」。

### 有意的范围取舍（供 09/10/11 参考）
- `.y4a-skeleton` / `.y4a-alert` / `.y4a-panel` 本包只**定义规范与用法约定**，未改造既有页面：骨架屏按验收标准「若该页已按 09 改造」执行，故留给 09 在问卷任务页首用。
- **按钮 `.is-loading` 已应用**：`student_360.html` 顶部「重生成 PDF」与报告行内「生成 PDF」两处 mutating 按钮（`regenBusy` 期间），用于验证态可视。
- **tab 下划线**：`student_360.html` tab 按钮加 `.y4a-tab`。当前实现是 border/color 的令牌化过渡，**非 JS 测量的位移动画**——站点内没有滑动的下划线组件，如需真·滑动留待后续包。
- Toast 退场沿用既有的 260ms 淡出延迟（与 `.y4a-toast` 的 `--y4a-dur` 入场不同步，肉眼无碍）；未改动该常量。
- 新增路由 `GET /command-palette.js`（`app.py`，与 `/admin.css` 同模式）。本包文件地图未列出此项，因 CDN 之外没有通用静态目录服务。
- `window.y4aToast` 作为 `window.y4Toast` 的等价别名（Layout 契约名是 `y4Toast`，08 验收标准写的是 `y4aToast`），两个名字都可用。

### 本地实测结果（localhost，2026-10-16）
- 数据区：`.y4a-table td` 实测 height 40px / font-size 13px；`.y4a-card-body` padding 16px；`.y4a-content` 桌面左右 24px（<1024px 走既有移动端覆盖 16px）。
- ⌘K：点触发按钮与 Ctrl+K / ⌘K 均可打开，Esc 关闭，打开即聚焦搜索框；输入「陈」→ 出现学生「陈昱彤（Y4-0003）」→ Enter 跳转 `/students/Y4-0003`（纯键盘完成）。
- 学生搜索端点：admin 搜索「Y4」返回 5 条、搜索「陈」返回 1 条；advisor（李顾问）搜索「Y4」仅返回其名下 2 条（Y4-0001/Y4-0003），未登录 401。
- Toast：连发 4 条只保留 3 条、每条带 svg 图标、约 5s 后清空；`typeof window.y4aToast === 'function'`。
- 窄屏 900px：汉堡按钮出现、侧边栏移出画布、无横向溢出；页面无 Alpine/commandPalette 未定义报错。
- 全站 11 个管理页 + `student_360` 均 200，命令面板随 `admin.html` 注入全部管理页（09/10/11 自动获得）。
- reduced-motion 未在真机 Emulation 下实测（浏览器代理不支持 media emulate），仅确认 CSS 媒体查询已就位；如条件允许请在浏览器 devtools 手动切一次。
