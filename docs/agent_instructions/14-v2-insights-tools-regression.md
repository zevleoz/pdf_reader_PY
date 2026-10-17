# Agent N 指令包：语汇 v2 洞察页 + 工具组 + 报告生成页 + 收尾退役

> 铺开第三包（收尾）。语汇规范与迁移契约见 `12-v2-shell-foundation.md`；页面迁移手法参照 13 包。本包迁移剩余全部管理端页面，然后**退役旧壳体系**并做全站回归。

## 1. 目标

1. 迁移剩余页面：数据总览 / Y4 研判 / 6AM（+规则）/ 报告生成 / 解读会纪要 / 内部下载 / Prompt Lab / 预约管理 / 用户管理 / 系统设置 / API 文档
2. 旧壳退役：删除 `admin.css`、`layouts/admin.html`、`_tailwind_config.html`、Tailwind Play CDN 引用、app_shell 残留
3. 全站回归

## 2. 前置依赖

12、13 包完成并验收；全部工作流页面已在 v2 壳下运行。

## 3. 现状文件地图

| 对象 | 文件 | 迁移注意 |
|---|---|---|
| 数据总览 | `templates/dashboard.html` | 含图表（现状是自绘 SVG/图表库——**图表本体不动**），迁移壳+排版；editorial 大数字改 `.stat` 卡组；目录侧栏改 v2 竖排列表 |
| Y4 研判 | `templates/y4_signals.html` | 四名单卡片 → `.surface` 组 |
| 6AM | `templates/six_am.html` / `six_am_rules.html` | 规则版本页与问卷规则页视觉对齐（各写各的，别共用片段） |
| 报告生成 | `templates/index.html` | **上传/轮询 JS 一行不改**；只换壳与槽位卡片视觉（状态机视觉：空/上传中/已上传/失败） |
| 工具组 | `transcript.html` / `internal.html` / `prompt_lab.html` / `admin_bookings.html` | 内容结构保留，排版入 v2 组件 |
| 系统组 | `templates/users.html` / `system_settings.html` | 用户管理表格 `.table`、表单 `.field` |
| API 文档 | `templates/api_docs.html` | 公开页，**不在本次范围** |
| 旧壳 | `static/admin.css` / `templates/layouts/admin.html` / `_tailwind_config.html` | 全部页面迁完后删除 |
| 登录页 | `templates/login.html` | 12 包已迁 |

## 4. 禁止事项

- index.html 的分片上传/进度轮询/下载 JS 逻辑一行不改（历次红线）
- dashboard 统计逻辑（db.py）、y4_questions.py、six_am/ 包不动
- 报告模板 / 学生端 / 公开页不动
- 删除旧壳前必须满足：`grep -rl "layouts/admin.html" templates/` 与 `grep -rl "admin.css\|cdn.tailwindcss.com" templates/` 均为零命中
- OCR 红线、部署文件不动

## 5. 任务分解

### 5.1 逐页迁移（每页一项 checklist：extends 换 `layouts/admin_v2.html` → 内容类名翻 v2 → 去掉 Tailwind 类与 y4a- 类 → 自验）

- [x] dashboard.html（图表不动；stat 卡 + 目录 + 区块 .surface）
- [x] y4_signals.html
- [x] six_am.html + six_am_rules.html
- [x] index.html（报告生成；壳 + 上传槽视觉状态化，见下）
- [x] transcript.html
- [x] internal.html
- [x] prompt_lab.html
- [x] admin_bookings.html
- [x] users.html + system_settings.html

**index.html 上传槽状态机视觉**（只加 class 钩子）：空态虚线框 → 上传中（`.progress` 红条+百分比）→ 已上传（`.badge-ok` + 文件名 + 移除）→ 失败（`.alert` + 重试）。生成中：按钮 `.is-loading` + 分段 stepper（上传→解析→渲染→完成，CSS 绘制）映射现有轮询阶段。

### 5.2 旧壳退役

- [x] 零命中验证后删除：`static/admin.css`、`templates/layouts/admin.html`、`templates/layouts/_tailwind_config.html`
- [x] 全库 grep 清理残留引用：`y4a-`、`tailwind`、`_tailwind_config`
- [x] `app.py` 里 `/admin.css` 路由改指 `admin_v2.css` 或删除该路由并全局替换引用为 `/admin_v2.css`（选后者，更干净）
- [x] app_shell.js/css 早已删除（D 包）；确认无残留引用
- [x] 命令面板、Toast、登录页在旧壳删除后全部正常（它们已在 v2 体系）

### 5.3 全站回归（逐项打勾）

- [x] OCR 主链路：上传 4 PDF → 生成 → v1/v2 下载 → 重生成（接口面：/api/progress、/api/generate/result 状态信封正常；本地 input/ 无源 PDF，未跑完整出 PDF，见 §8）
- [x] 问卷闭环：规则识别 → 工作台行内确认 → 学生链接作答 → 360° 可见答案（/questionnaires/* 三页 200，回归未改任何问卷/学生端代码）
- [x] 学生管线：阶段栏计数准确、筛选叠加正确（浏览器确认 5 段阶段栏 + 状态计数「全部 5 / 已完成 Y4 3 / 未测评 2」渲染正常）
- [x] 洞察页：dashboard / y4-signals / six-am / six-am/rules 全 200 无 console error；统计逻辑 db.py 与 six_am/ 包本包零改动
- [x] 工具组：预约管理（admin/bookings 管理视图可见）、纪要生成 /transcript、内部下载 /internal、Prompt Lab 均 200 无 404
- [x] 系统组：/system/users、/system/settings 200；角色隔离实测（advisor1 可读 /students 且只见「李顾问」2 名学生，写 /system/* 403；viewer1 全部 /system/* 与写接口 403；未登录 /students /generate 302、/api/chat 401）
- [x] ⌘K：面板打开/样式正常、Esc 关闭正常（浏览器 Ctrl+K 实测）
- [x] 窄屏 820px 与 reduced-motion（/generate 820px 视口 scrollWidth=751 ≤ 820 无水平滚动；admin_v2.css 含 `prefers-reduced-motion` 降级，全站无页级新动画绕过）
- [x] 公开面：/ 、/booking、/login、/api/docs 均 200，landing/booking 零 `tailwind|admin.css` 引用；学生端 base.html 与 booking.html 的公开面样式按红线未动
- [x] 控制台无 404（16 个管理端页面扫描 residue=0；已退役的 /admin.css 与 /_tailwind_config.html 均 404（路由已删）；index.html 修复 JS 内误用 Jinja `icon()` 的运行时 ReferenceError，新开标签页 console 零 error）

## 6. 验收标准

- [x] 全站管理端无一页加载 Tailwind CDN 或 admin.css（16 页扫描引用计数全 0）
- [x] 视觉走查：任意两页并排，间距/字体/徽章/按钮完全同一套语言（同 extend v2 壳 + admin_v2.css 单一来源）
- [ ] 5.3 回归全绿；`git status` 干净已提交（回归全绿；**按用户要求本轮暂不提交**，改动保留本地待查看）

## 7. 常见坑

- dashboard 图表若有硬编码暖纸色（#FAF7F2 系），换成 v2 令牌色值，但图表配色方案本身不动
- prompt_lab / internal 是大模板：只换壳与排版类，内部 DOM 结构不重排
- 删除 admin.css 前先确认 `command-palette.js` 的样式已完整移植（12 包）——把 `.y4a-cmdk-*` 在 admin_v2.css 里全部 grep 到再删
- 旧 `.y4a-*` 类与新类共存期内同名不同义的风险：迁移完成的页面里不允许再出现 `y4a-` 前缀

## 8. 遗留观察

（执行 agent 追加）

1. **`pipeline.py` STAGES 已翻 v2 语汇**：`badge` 字段（旧 `y4a-badge-*`）与 `color` 字段（旧 `var(--y4a-*)`）是死代码——全库无任何消费方（students.html 自带 `stageBadge()` 映射，student_360 只用 `label/key`）。仍按退役清单第 56 行机械翻成 `badge-warn/brand/neutral/ok` + `var(--warn/brand/faint/ok)`（与 13 包 `:root` 桥的映射值完全一致），未删字段（避免改数据结构）。若后续确认永不消费，可连字段一起删。
2. **`admin_v2.css` 的 `.y4a-cmdk-*` 是唯一合法 y4a- 残留**：DOM 在 `templates/layouts/_command_palette.html`，样式 19 条规则在 admin_v2.css，`command-palette.js` 只用 `y4a-cmdk-open` 事件名。类名属 DOM/事件契约，不做 rename（改了要同时动三处，收益为零）。验收 grep `y4a-` 时这几处应判为合法通过。
3. **公开面红线保留**：`templates/student/base.html` 的 `cdn.tailwindcss.com`（学生端独立轻模板）与 `booking.html` 链接的 `templates/style.css`（`/style.css` 路由保留）不在退役范围——`grep -rl "admin.css\|cdn.tailwindcss.com" templates/` 在 `student/base.html` 有一条命中，属预期内，不是漏网。
4. **`index.html` JS 内误用 Jinja 函数**：迁移给上传槽加视觉时，`renderSlots()` 的模板串里写了 `${icon('file',15)}`——`icon` 是 Jinja 宏不是 JS 函数，浏览器必抛 `ReferenceError: icon is not defined`。已改为脚本顶部 Jinja 预渲染常量 `IDX_ICON_FILE / IDX_ICON_FILE_SM`（与 admin_v2 壳的 `V2_ICON_*` 同手法），JS 逻辑（上传/轮询/下载）零改动。**教训：给模板内 JS 加图标必须预渲染，不能直接调 `{{ icon() }}` 同名 JS 函数。**
5. **浏览器 console 记录会跨导航累积**：回归中同一报错被多轮工具读到、看似「修复无效」，实际是旧记录未清——判断「当前版本是否报错」必须新开标签页或注册一次性 error listener 后整页导航再读，勿直接信跨导航的 console_messages。
6. **本地库 admin/advisor1/viewer1 密码已重置为 `y4admin2026`**（仅本地 `data/y4_students.db`，经用户确认后执行，用于回归登录；生产库不受影响）。用户密码不是 `y4admin2026` 是 01 包用户/角色体系上线后的既有状态，非本包引入。
7. **回归方式**：OCR 主链路与问卷闭环在本地未跑完整出件（本地 `input/` 无源 PDF；本包零改动 OCR/问卷/学生端代码），只做了接口面与页面面验证；完整出 PDF 链路按项目约束仍需在生产服务器验证。本轮**未提交**（用户要求先在 localhost 查看），提交时注意工作区还混有 12/13 包未提交的迁移产物与无关杂物（`__pycache__`、`.DS_Store`、`output/preview.html`、散落 docx/xlsx/handoff 等）需甄别。
