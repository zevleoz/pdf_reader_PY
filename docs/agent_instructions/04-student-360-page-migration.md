# Agent D 指令包：学生 360° 档案页 + 现有页面迁入新 UI

> 五个实施包中的第四个。单一事实来源：`docs/superpowers/specs/2026-10-14-y4-platform-2.0-design.md`（下称 spec；档案页定义在 5.3，导航结构在 5.1）。冲突时以 spec 为准并向需求方确认。

## 1. 背景与目标

2.0 的定位是"学生 profiling 数据中心"。当前学生相关数据散落在多个页面（students 列表、dashboard、6AM、纪要、预约），本包做两件事：

1. **学生 360° 档案页** `/students/<code>`：单页聚合一个学生的全部数据，六 tab（spec 5.3）——这是 2.0 的核心页面
2. **现有页面逐页迁入新 UI 框架**（B 包的 admin layout），完成全站视觉与导航统一

## 2. 前置依赖

| 依赖 | 内容 | 缺位降级 |
|---|---|---|
| A 包 | `student_code`；角色装饰器；Advisor 数据隔离（`visible_student_filter`） | 不可缺位 |
| B 包 | `templates/layouts/admin.html` 契约（block：title/page_title/content/head_extra/scripts；变量：nav_active；`window.y4Toast`；图标 macro `_icons.html`）；设计规范（色彩/间距/组件） | 不可缺位 |
| C 包 | `questionnaire_store.py` 的 `list_assignments_for_student(student_id)` / `get_response(assignment_id)` | C 未完成时：档案页「问卷」tab 渲染空态"问卷模块未启用"，try/except import 包裹——**这就是打桩契约**，C 完成后自然点亮 |

## 3. 现状文件地图（已核对）

| 文件 | 说明 |
|---|---|
| `templates/students.html` | 现有学生列表 + 历史报告 + 重生成 PDF（逻辑见 `REGENERATE_PDF_GUIDE.md`：从 reports.data_json 快照重渲染，不重跑 OCR） |
| `templates/dashboard.html` | 数据总览（统计逻辑在 `db.py:1181-1962`） |
| `templates/y4_signals.html` | Y4 研判四名单 |
| `templates/six_am.html` / `six_am_rules.html` | 6AM 档案与规则版本管理 |
| `templates/index.html` | 报告生成页（4 上传槽 + 分片上传 + 轮询 JS）——**只换壳，上传/轮询逻辑一行不动** |
| `templates/admin_bookings.html` | 预约管理 |
| `templates/transcript.html` | 解读会纪要 |
| `templates/internal.html` | 82KB 大模板，内部下载 |
| `templates/prompt_lab.html` | 73KB 大模板 |
| `templates/landing.html` / `booking.html` / `login.html` | 公开页/登录页：**不在本包**（login 归 B，landing/booking 仅微调，见 5.3） |
| `templates/app_shell.js` | 旧壳，挂载点 `[data-app-shell]`；本包迁移完成的页面**移除该挂载点**，文件本身 E 包才删 |
| `templates/report.html` / `report_en.html` / `new_iteration/report_v2.html` | 报告模板，**禁止改动** |
| `data_points.py` | 124 项元数据，001-133 编号分 13 组——画像 tab 的分组展示以此为准（先读文件确认组的实际结构与中文名） |
| `db.py` | reports / meeting_minutes / bookings / six_am_profiles 的查询函数所在 |
| 蓝图（A 包后） | `blueprints/students.py` / `insights.py` / `tools.py` / `reports.py` |

## 4. 禁止事项

- 不改 OCR 管线、报告模板、`data_points.py`（spec 第 2 节）
- **不改 generate 页的分片上传/轮询/下载 JS 逻辑**——只把它包进新 layout
- 不改 dashboard 的统计逻辑（db.py:1181-1962），只换页面壳
- 不重写 internal.html / prompt_lab.html 的内容结构——**只换壳**（head/block 改造 + 外层套 layout），页面内部样式允许保留原样，视觉统一留给未来
- 不改 `/api/v1/*` 与公开路由行为

## 5. 任务分解

### 5.1 学生 360° 档案页 `/students/<code>`（核心）

- [ ] 路由进 `blueprints/students.py`；权限：admin 全见；advisor 经 `visible_student_filter` 校验该生归属，不属自己 → 403；viewer 可见但**隐藏全部操作按钮**（模板按 `current_role` 条件渲染）
- [ ] 页头：student_code、姓名、性别、生日、年级、顾问、学校；操作区（重生成 PDF、发起问卷任务[C 完成后亮]）
- [ ] 六 tab（Alpine `x-data="{tab:'profile'}"`，切 tab 不刷新，数据首屏一次注入或按 tab 懒加载——选择**懒加载**：每 tab 一个 GET JSON 端点，避免首屏过重）：

| Tab | nav_active | 数据端点 | 内容 |
|---|---|---|---|
| 画像 | students | `GET /students/<code>/api/profile` | 最新 report 的 data_json 按 data_points.py 13 组分组渲染指标表（code/中文名/值），缺组跳过 |
| 报告 | students | `GET /students/<code>/api/reports` | 历史报告列表：日期、v1/v2 下载、重生成按钮（迁移 students.html 现有能力） |
| 问卷 | students | `GET /students/<code>/api/questionnaires` | assignments 列表（状态徽章/问卷名/时间）+ 每条的 responses 原始答案展开查看；C 缺位时空态 |
| 预约 | students | `GET /students/<code>/api/bookings` | bookings 记录 |
| 纪要 | students | `GET /students/<code>/api/minutes` | meeting_minutes 列表 + 查看渲染 |
| 6AM | students | `GET /students/<code>/api/six-am` | six_am_profiles 版本列表 + 查看 |

- [ ] 所有端点返回 JSON，权限检查与页面一致；viewer 可调只读端点
- [ ] 旧学生详情入口（students.html 里的展开/链接）改为跳转 `/students/<code>`

### 5.2 学生列表页升级

- [ ] 迁入新 layout；加 student_code 列；搜索框（姓名/code/学校）；advisor 视角自动过滤（A 包已实现查询层）；行点击进 360° 页

### 5.3 逐页迁移（每页一项 checklist；顺序即风险从低到高）

对每页：extends `layouts/admin.html` → 内容移入 `content` block → 页脚本移入 `scripts` block → 移除 `[data-app-shell]` 与 app_shell.js/css 引用 → 设 `nav_active` → 验证。

- [ ] `dashboard.html`（nav_active='insights.dashboard'）——统计图表库现状是什么就保留什么
- [ ] `y4_signals.html`（'insights.y4-signals'）
- [ ] `six_am.html` + `six_am_rules.html`（'insights.six-am'）
- [ ] `admin_bookings.html`（'tools.bookings'）
- [ ] `transcript.html`（'tools.transcript'）
- [ ] `internal.html`（'tools.internal'）——只换壳
- [ ] `prompt_lab.html`（'tools.prompt-lab'）——只换壳
- [ ] `index.html` /generate 页（'reports.generate'）——只换壳，上传 JS 不动
- [ ] 旧路由兼容：spec 5.1 的新分组 URL（/insights/*、/tools/*）用**双注册**实现（同一视图函数挂两个 rule），旧路径不 302、直接可用，避免书签断裂；导航一律指向新路径
- [ ] 公开页：`landing.html` / `booking.html` **不动结构**；仅当它们的导航链接指向管理端旧路径时更新链接
- [ ] `system/settings` 打桩页（B 包已建则跳过）

### 5.4 收尾标注

- [ ] 全部页面迁完后，在 `templates/app_shell.js` 文件头加注释：`已退役，由 templates/layouts/admin.html 替代；删除在 E 包执行`
- [ ] 确认全站不再有 `[data-app-shell]` 挂载点残留（grep 验证），结果写进交付说明供 E 包删除文件

## 6. 验收标准

1. `/students/<code>` 六 tab 全部可用；切 tab 懒加载正常；viewer 看不到任何操作按钮；advisor 访问他人学生 403
2. 画像 tab 指标按 13 组正确分组，值与 reports.data_json 一致
3. 报告 tab 可下载 v1/v2、可重生成（与 1.0 行为一致）
4. 问卷 tab 在 C 完成前显示空态不报错，C 完成后显示任务与原始答案
5. 迁移页清单每一页：新 layout 内正常渲染、导航高亮正确、页面原有功能（dashboard 筛选、six-am 规则发布、generate 上传生成等）逐项可用
6. 旧 URL（/dashboard 等）与新 URL（/insights/dashboard 等）都可达
7. `grep -r "data-app-shell" templates/` 无结果
8. 公开页（/ /booking /api/docs）零变化

## 7. 回归要求

- 报告生成全流程（上传→进度→下载→重生成）不受影响——generate 页只换了壳
- dashboard / y4-signals / six-am 的数据与操作不变
- 预约公开页与管理页不变
- `/api/v1/*` 不变

## 8. 常见坑

- **Jinja vs Alpine `{{ }}`**：tab 组件用 `x-show`/`x-text`，插值冲突处 `{% raw %}`
- **大模板换壳**：internal/prompt_lab 不要试图重排内部 DOM——只动 head、body 外层与导航挂载点；它们的 `<style>` 块原样保留在 content block 里
- **懒加载端点的权限**：别忘了每个 `/students/<code>/api/*` 都要过 `visible_student_filter`，不能只在页面路由拦
- **双注册 URL**：Flask 允许同一函数多个 @route；注意 url_for 用 endpoint 默认取第一个 rule，统一用新路径调用 url_for
- **students.html 旧交互**：重生成 PDF 的 JS 依赖现有 API（先读 students.html 与对应路由确认），迁移时保持 API 路径不变
- **app_shell.js 残留**：页面移除挂载点后若仍引用 app_shell.css，局部样式可能塌——逐页目检

## 9. 遗留观察

（执行 agent 追加）

- 5.3 迁移清单 9 页全部完成：`dashboard.html`、`y4_signals.html`、`six_am.html`、`six_am_rules.html`、`admin_bookings.html`、`transcript.html`、`internal.html`、`prompt_lab.html`、`index.html`（+ 5.2 `students.html`）。均改为 `extends layouts/admin.html`，原 `<head>`（字体 + `/style.css` + 页内 `<style>`）移入 `head_extra`，body 移入 `content`，页脚本移入 `scripts`，删除 `[data-app-shell]` 与 app_shell.css/js 引用。
- 额外迁移 `users.html`（`/system/users`，侧栏「系统 → 用户管理」）：5.3 清单未列，但为满足验收标准 7 与「全站导航统一」，做同样机械换壳，逻辑零改动。
- 双注册路由此包涉及：`insights.py` 加 `/insights/dashboard`、`/insights/y4-signals`、`/insights/six-am`、`/insights/six-am/rules`；`tools.py` 加 `/tools/transcript`、`/tools/bookings`、`/tools/internal`、`/tools/prompt-lab`。旧路径不 302、直接可用。新路径 rule 紧贴视图函数，`url_for` 默认取新路径。
- `nav_active` 实取值：`insights.dashboard` / `insights.y4-signals` / `insights.six-am` / `tools.bookings` / `tools.transcript` / `tools.internal` / `tools.prompt-lab` / `system.users`；generate 页为 **`generate`**（`app_utils.ADMIN_NAV` 中该项 item key 即 `generate`，指令 5.3 写的 `reports.generate` 与导航 key 不符，已按实际 key 设置）。
- 旧链接更新：`landing.html`（`/admin/bookings`→`/tools/bookings`、`/transcript`→`/tools/transcript`）、`students.html`（6 处 `/transcript?student_id=`→`/tools/transcript?student_id=`）、`six_am.html`↔`six_am_rules.html` 互链改 `/insights/six-am*`。
- `app_shell.js` 文件头已加退役注释（删除在 E 包）。
- grep 验证：`templates/` 中 `[data-app-shell]` 挂载点仅剩**公开页 `booking.html`**（本包明确不动结构）；`layouts/admin.html`、`app_shell.js` 内的命中均为注释/实现代码。
- 本地验证（Flask `test_client`，admin/advisor/viewer 三角色）：22 条 管理端路由（含全部新旧双路径）均 200、渲染新壳、导航高亮正确；360 页 admin 200 + 操作按钮可见、viewer 200 + 按钮隐藏、advisor 名下 200 / 他人 403 / 不存在 404；公开页 `/`、`/booking`、`/api/docs` 零变化（`/booking` 仍用旧壳）。

