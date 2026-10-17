# Agent M 指令包：语汇 v2 工作流页面迁移（工作台转正 + 学生 + 问卷中心）

> 铺开第二包。语汇规范与迁移契约见 `12-v2-shell-foundation.md` 第 1 节与 4.5（先读 12 包的 `static/admin_v2.css` 实物与样板页 `templates/workspace_v2.html`）。
> 本包覆盖用户每天操作的四个页面：工作台、学生列表、学生 360°、问卷中心（任务/题库/规则）。

## 1. 目标

把四个高频工作流页面从旧壳（Tailwind + admin.css 暖纸系）迁移到 v2 语汇，**功能与数据流零改动**——只换模板与样式类，不碰视图函数的数据组装（模板变量名/结构不变）。

## 2. 前置依赖

- 12 包完成（组件库补全、迁移契约、⌘K 样式移植、登录页已迁）

## 3. 现状文件地图（已核对）

| 对象 | 文件 | 说明 |
|---|---|---|
| 工作台 | `templates/workspace.html` + `blueprints/workspace.py` | 旧语汇版；`templates/workspace_v2.html` 是已验收的新版内容 |
| 学生列表 | `templates/students.html`（40KB） | 含管线阶段栏（注意：旧实现有占比条溢出 bug，迁移时重写该组件）、搜索、pill 筛选、卡片行 |
| 学生 360° | `templates/student_360.html` + `blueprints/students.py` 的 tab API | 六 tab（画像/报告/问卷/预约/纪要/6AM），懒加载 |
| 问卷中心 | `templates/questionnaires/assignments.html` / `bank.html` / `rules.html` + `blueprints/questionnaires.py` | Alpine 驱动，API 取数 |

## 4. 禁止事项

- 不改视图函数输出的数据结构（模板变量名不动）；不改 API 契约；不改 Alpine 交互逻辑的数据流
- 不带 Tailwind 类进 v2 页面（v2 壳无 Tailwind 运行时）——旧模板里的 `class="flex items-center gap-4 text-[13px]"` 这类全部翻成 admin_v2.css 组件类或少量内联 style
- 不动学生端、报告模板、OCR 管线
- 样板页交互（行内审批两库 confirm/reject/reissue、复制、轮询）已经在 workspace_v2.html 里验证过，**复用其 `rowState`/`sentRow`/`jobPoll` 模式**，不重新发明

## 5. 任务分解

### 5.1 工作台转正

- [ ] `workspace_v2.html` 内容转正为 `workspace.html`（覆盖旧文件）；`/workspace-v2` 预览路由删除（`blueprints/workspace.py` 里移除 `workspace_page_v2`）；侧栏品牌链接已是 `/workspace`（12 包）
- [ ] 保留旧文件到 git 历史即可（直接覆盖，不保留 _old 副本）

### 5.2 学生列表页（`students.html` 重写为 v2）

- [ ] 页面头：`page_title` 学生档案 + `page_actions` 放「导出 CSV」「刷新」
- [ ] **管线阶段栏重做为 v2 组件**（重写，不复用旧实现）：五个阶段的横向分段条——白卡内一行：每段 [阶段名 11px muted + 计数 18px/650 tabular]，段间 1px 分隔线；下方一条 3px 分段比例条（段宽=占比，色=阶段色）。点击段筛选（URL `?stage=` 契约不变）。**验收时核对无溢出**（旧版 bug）
- [ ] 搜索框：`.input` + 搜索图标内嵌左侧；筛选 pill（全部/已完成/未测评）用 `.pills`
- [ ] 学生行改为 `.qrows/.qrow` 表格（列头带：学生/编号/学校/顾问/状态/阶段/操作）：学生名列 姓名+mono 编号；状态列保留「已完成|日期」「未测评」徽章（统一成 v2 badge 一种语法）；阶段列为印章徽章+停留天数；操作列 hover 浮现（查看档案/编辑/删除/新建议程，⋯ 菜单或图标按钮组）
- [ ] 行点击进 `/students/<code>`；行内按钮 stopPropagation
- [ ] 加载骨架屏 `.sk`、空态区分（无学生/该阶段无学生）
- [ ] 删除/编辑等既有交互逻辑保留（翻成 v2 dialog/menu 呈现）

### 5.3 学生 360°（`student_360.html`）

- [ ] 头部卡 → `.surface`：编号 mono + 姓名 20px/650 + 元信息行（性别/生日/年级/顾问/学校，`.dl` 或 meta 行）+ 右侧操作（重生成 PDF `.btn-sec`、发起问卷任务 `.btn-primary`）
- [ ] 阶段 stepper 保留逻辑、换 v2 视觉（五步横条：圆点+连线，当前 brand，完成 ok，未来 `--faint`；CSS 绘制，无图片）
- [ ] 六 tab → `.tabs` 下划线式；tab 内容区 `.surface`；各 tab 内部表格用 `.table`；问卷 tab 的答案展开用行内展开面板样式（`.qpanel`）
- [ ] 懒加载端点不变；viewer 隐藏操作按钮的逻辑不变

### 5.4 问卷中心三页

- [ ] **任务列表**（assignments.html）：状态 tab → `.pills`（含计数）；表格 → `.qrow-head`+`.qrow`；行展开复用样板页审批面板（reason + delivery radio + 确认并分发/驳回）——把 `workspace_v2.html` 的 rowState 组件抽成 `static/ws-rows.js` 或在 assignments 页内复制同款（选一个，文档注明）；行内按钮接 `.is-loading`
- [ ] **题库**（bank.html）：`.table`（问卷/编号/题量/状态/操作）；查看题目展开行（题号+题干+选项，13px）；启停按钮 `.btn-sec`/`.btn-ghost-danger`
- [ ] **规则**（rules.html）：左栏版本列表（`.surface` 内行，published = `.badge-brand` 印章）+ 右栏编辑器卡；JSON textarea 用 mono `.textarea`；校验/试算/发布按钮组；试算结果区 `.table`

## 6. 验收标准

- [ ] `/workspace` 即样板页内容与交互（行内审批全真可用），`/workspace-v2` 404/移除
- [ ] 学生列表：阶段栏无溢出、点击筛选+搜索+pill 三者叠加正确；行样式与样板页同一套 `.qrow` 语言
- [ ] 360°：六 tab 懒加载正常、viewer 只读、stepper 正确
- [ ] 问卷任务页：行内确认/驳回/重新生成/分发信息/查看答案全部可用；规则发布/试算/归档正常；题库启停正常
- [ ] 四页在 1280px 与 1440px 无横向滚动；820px 不崩（表格横向滚动或列降级）
- [ ] 回归：导出 CSV、重生成 PDF、新建任务、计时器/日期格式与 06/07 包的文案修正（时间戳分钟级、术语"系统推荐/人工创建"）不丢

## 7. 常见坑

- 旧模板里的 Tailwind 任意值（`text-[12.5px]`）必须清零——迁完一页在页面源码 grep `text-[` `bg-[` 确认无残留
- students.html 原 Alpine/JS 逻辑（搜索防抖、筛选）保留逻辑只换 class；逐函数核对别丢
- 阶段栏的分段比例条用 flex + 百分比宽度，不要绝对定位（旧 bug 就是绝对定位溢出）
- 模板缓存：改完重启进程再看

## 8. 遗留观察

（13 包执行 agent 追加，2026-10-16）

1. **5.4 rowState 抽取决策：未建 `static/ws-rows.js`，改为页内复制。** 理由：assignments 页的行内审批面板与 workspace 样板面板结构同款但字段不同（assignments 多 busyId/rowErrorId、delivery radio 键值有差异），抽象需要传参适配层，收益低于成本；且指令允许"页内复制并文档注明"。若后续第三处需要同款面板，再抽公共 JS。
2. **`page_actions` 块的 Alpine 作用域陷阱（重要）：** 壳 `admin_v2.html` 的 `page_actions` 渲染在 topbar 内，处于 `body x-data="{drawer:false}"` 作用域，**页面级 `x-data` 覆盖不到**。在该块写 `@click="load()"` / `x-show="canWrite"` 会抛 `Alpine Expression Error: xxx is not defined`（首次验收时 assignments/bank/rules 三页顶栏按钮全部中招）。正确做法：
   - 触发页面动作 → `onclick="window.dispatchEvent(new Event('v2:refresh'))"`，页面根节点挂 `@v2:refresh.window="load()"`
   - 按角色显隐 → Jinja 直接判断 `{% if current_role == 'viewer' %} style="display:none"{% endif %}`
   以后所有 v2 页的 `page_actions` 块一律按此模式写。
3. **`pipeline.STAGES` 旧壳色变量桥接：** `STAGES` 的 color 字段是 `var(--y4a-warning)` 等旧壳变量名，未改 Python 数据结构（硬约束），而是在 `admin_v2.css` 的 `:root` 加别名映射到 v2 语汇色（`--y4a-warning→--warn`、`--y4a-brand→--brand`、`--y4a-success→--ok`、`--y4a-ink-soft→--faint`）。后续新增引用旧壳色名的组件可继续沿此桥。
4. **验收方式与结论：** 静态验收（6 页 HTTP 200、无 `text-[`/`bg-[`/class 级 `y4a-` 残留、加载 admin_v2.css、`/workspace-v2` 404、360° 页正常）全过；浏览器验收六页 1440/1280/820 三档无横向滚动、阶段筛选与三筛选叠加、六 tab 懒加载、行内审批/弹窗/试算等交互可用、控制台无 JS 错误（`y4a-cmdk-*` 是壳命令面板自带类，非残留）。临时验收账号已删除。
5. **既有问题（非本包引入，未改）：** 已登录 session 下再 POST `/api/admin/login` 会被 CSRF 拦截（需先 logout）；Alpine 报错存在浏览器控制台跨页累积现象，判断"某页新增报错"须先清点再导航。
