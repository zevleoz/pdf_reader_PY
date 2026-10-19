# 16 — 工作台合并问卷任务 + 学生档案重构

> 目标：把「问卷任务」并入「工作台」成为单一日程页；彻底重构两页（工作台、学生档案）的信息层级；修复学生档案骨架行常驻 bug；确立学校/顾问字段的数据规则。壳（侧栏/顶栏/`admin_v2.css` token）不动。
>
> 模式：Operate（内部管理工具）。密度、可扫读性、状态语义优先；不做营销式视觉。
>
> 已确认决策（2026-10-17，需求方）：
> 1. 工作台与问卷任务**合并为一个页面**，侧边栏只留一个入口；
> 2. 只重构这两页内容，管理端壳不动；
> 3. 学校 = YCS 报告 OCR 读取值；顾问 = 预约时手动填写值；两者都可编辑，且手动值不被后续自动流程覆盖（详见 §C 规则）。

---

## A. 先行修复（独立小步，先做先验证）

### A1. 学生档案骨架行常驻 bug（截图 2 的 "一直 load"）
根因：`templates/students.html` 的 `renderStudents()`（`:385-490`）只 `el.insertAdjacentHTML('beforeend', …)` 追加行，**从不清空容器**；`loadStudents()`（`:342-352`）注入的 4 条 `.sk-row` 骨架因此永远残留，且每次 `filterStudents()`（搜索/筛选，`:255/:310/:319`）会把全部行重复追加。
修复：
- `renderStudents()` 在拿到 `#studentList` 后、任何分支之前先 `el.innerHTML = ''`（空结果分支已有的 `innerHTML = emptyState(...)` 保留）。
- `loadStudents()` 包 try/catch：fetch 失败时渲染错误态（"加载失败，点击重试"），不让骨架无限残留。
- 验证：刷新页面→骨架消失只留真实行；搜索输入→行数不翻倍；断网刷新→出现错误态而非永久骨架。

### A2. 顺手清理（壳不动，只删垃圾）
- `templates/layouts/admin_v2.html:129` 与 `templates/layouts/_command_palette.html:58` **重复加载** `command-palette.js`，删其一（保留带 `defer` 的那处）。
- 删除过时注释：`admin_v2.html:2`「样板页试用」、`blueprints/questionnaires.py:1`、`assignments.html` 内「复用样板页…」等 agent 过程痕迹。
- 截图右下角的悬浮聊天圆钮**不在本代码库**（全库无此 fixed 元素），是截图工具/浏览器插件的悬浮层，不处理。

---

## B. 信息架构合并：问卷任务 → 工作台

现状：工作台四个区块中「待你确认」「等待学生」与问卷任务页 pending/sent tab **数据、API、审批面板完全重复**（同调 `list_assignments`，同打 `/api/questionnaires/assignments/<id>/confirm|reject|reissue|package`）。

### B1. 合并后「工作台」页面结构（自上而下）
1. **页头**：标题「工作台」+ 动态摘要「N 项待确认 · M 项等待学生」（沿用 `workspace.html:14-18`）；右侧主操作 `[新建任务]`（原 assignments 页对话框迁来）+ `[新建报告]`（链接 `/generate`）。原顶栏的 `刷新/新建任务` page_actions 移除——操作贴近它作用的表格。
2. **生成作业卡**：仅在作业进行中或 24h 内有结果时出现（沿用 `workspace.py:151-191` + `/api/progress` 轮询）。
3. **问卷任务区**（合并核心，取代两个队列 + 整个 assignments 页）：
   - 状态 tab：`待确认(n) / 等待作答(n) / 已提交(n) / 已过期(n) / 已驳回(n) / 全部`，**默认「待确认」**（收件箱语义：先处理要动作的）。数据仍走 `GET /api/questionnaires/assignments?status=…`（counts 已自带）。
   - 表格从 7 列收敛为 **5 列**：
     | 列 | 内容 |
     |---|---|
     | 学生 | 姓名（链接 `/students/<code>`）+ 下一行 mono 编号 |
     | 问卷 | 标题 + mono 问卷编号；标题前小圆点表来源（系统推荐=brand 色 / 人工=灰）；推荐理由截断为**一行**次信息（全文放展开面板） |
     | 状态 | badge，颜色语义修正（见 B2） |
     | 分发 | 方式（链接/账号/链接+账号）+ 次信息：已发送=「已等 N 天 · M月D日 到期」；待确认/已驳回显示 — |
     | 操作 | **每行仅 1 个主按钮 + 「⋯」溢出菜单**（见 B3） |
   - 行内展开确认面板保留（推荐理由全文 + 画像页链接 + 分发方式三选卡 + `[确认并分发]`），仅 pending/expired 行可展开。
   - 「新建任务 / 分发信息 / 查看答案 / 通用确认」四个对话框从 `assignments.html:208-288` 整体迁来。
   - 空态沿用：「暂无任务 / 报告生成后，命中识别规则的问卷会自动出现在这里。」
4. **最近活跃学生**：沿用现有底部区块（`workspace.py:197-226`）。

### B2. 状态颜色语义（现在 sent 用品牌红，"健康在途"被读成警报）
- 待确认 pending → `badge-warn`（需要你动作）
- 等待作答 sent → `badge-neutral`（在途，无需动作）
- 已提交 submitted → `badge-ok`
- 已过期 expired → `badge-danger`（需重新确认）
- 已驳回 rejected → 灰/faint（终态）
同步修改 `statusBadge()`（`assignments.html:354-357` 迁来后调整）。

### B3. 每行操作收敛（现在 sent 行一排出 4 个按钮）
| 状态 | 主按钮 | ⋯ 菜单 |
|---|---|---|
| 待确认 pending | 确认分发（展开面板） | 驳回 |
| 等待作答 sent | 分发信息（弹窗+复制） | 重新生成链接*、重置密码*、驳回 |
| 已提交 submitted | 查看答案 | — |
| 已过期 expired | 重新确认（展开面板） | 驳回 |
| 已驳回 rejected | — | — |

\* 按 `delivery` 类型条件显示：纯链接分发不显示「重置密码」，纯账号分发不显示「重新生成链接」（后端本就会报 `该学生尚无账号`，前端别给用户能点错的按钮）。
驳回只保留**一处**入口（⋯菜单），走现有通用确认对话框（`assignments.html:278-288`），删掉行内 two-step arm（`:129-132, 387-397`）和面板里的第二个驳回按钮——同一破坏性动作目前有两套确认模式，统一为一种。

### B4. 路由、导航与角色
- `blueprints/questionnaires.py`：`GET /questionnaires/assignments`（`:85-89`）改为 302 → `/workspace`；删除 `templates/questionnaires/assignments.html`。**所有 `/api/questionnaires/*` API 不动**（工作台账台共用）。
- `app_utils.py` `ADMIN_NAV`（`:302-345`）：问卷中心组移除「问卷任务」，剩「问卷题库 / 识别规则」；`static/command-palette.js:12-25` 的命令清单同步删该项。
- **Viewer 角色**：问卷任务原对 viewer 只读开放，工作台原来是 admin/advisor 专属。合并后 `/workspace` 对 viewer 开放只读：`blueprints/workspace.py:33` 的 `@role_required` 加 `"viewer"`；页面根节点加 `data-role`，JS 按角色隐藏所有写操作按钮与新建入口（沿用 assignments 页已有的 `data-role` 模式）；生成作业卡与新建报告入口对 viewer 隐藏。`_advisor_scope()` 过滤逻辑不变（viewer 见全量只读）。

### B5. 问卷 API 顺手加固（合并时同文件，成本近零）
- `questionnaire_store.py`：`list_assignments` 与 `assignment_status_counts` 各自调用 `refresh_expired()`（GET 请求写库，`:419-436`），且列表限量 500、计数不限 → 同请求内状态可能翻转、计数与行数不符。改为：一次刷新后同事务出 list + counts（合并为一个 store 方法或公共刷新入口）。
- `blueprints/questionnaires.py:117`：`int(student_id)` 未校验，非数字 query 会 500 → 捕获后 400。
- 死状态清理：`pkgNoteType`（`assignments.html:457`）设了不用，迁代码时删除；toast 文案「已有同名活动任务」（`:513`）改为「该学生已有此问卷的活动任务，已复用」。

---

## C. 学校 / 顾问字段：数据规则确立

现状（血缘已存在，方向需修）：
- `students.school` / `students.advisor_name`（`db.py:38-51`）。
- 预约表单（`templates/booking.html:165-170` 采集顾问+学校）→ `db.create_booking_with_student()`（`db.py:690-727`）写入 students ✅。
- YCS 报告 OCR：`extract.py:347-364` 正则抓「学校：」「测评老师/指导师：」→ `reports.py:_save_report_to_db()`（`:146-206`）落库 ✅。
- **问题**：现在每次生成/重生成报告，PDF 的 teacher 会无条件覆盖预约时手填的顾问（`reports.py:165,176`）——与需求相反。

### C1. 覆盖规则（改 `blueprints/reports.py:_save_report_to_db` 与 `db.find_or_create_student:442-446`）
- **学校 school**：OCR 值非空 → 写入（报告为准，需求方明确）；OCR 空/「—」→ 保留旧值（`_clean_y4` 已挡）。
- **顾问 advisor_name**：仅当现有值为空时才用 OCR teacher 回填；**预约/手动填过的顾问永不被 OCR 覆盖**。
- 手动编辑入口始终有效（`PUT /api/students/<id>`，`students.py:90-125`，已支持 name/school/advisor_name，无需改后端）。
- 已知边界（接受，不处理）：手动改过的学校在下次重生成报告时会被新 OCR 值刷新——学校以最新报告为准是预期行为。

### C2. 存量回填脚本
很多学生学校列为「—」。写 `scripts/backfill_school.py`（参考 `db.py:1390-1415` 已有的 `report.data_json → student.school` 读法）：遍历学生，school 空/「—」且其最新报告 data_json 里有 `student.school` → 回填。**默认 dry-run** 打印将改动的行，`--apply` 才落库。不碰 OCR，纯读已有 JSON。

### C3. 编辑入口补全
- 列表页已有编辑（行编辑条 `students.html:460-472`；顾问列右键 `:454-455`）。把右键改为 **hover 显示铅笔图标**（右键不可发现）。
- 360° 档案页页头 meta（`student_360.html:156-157` 现只读展示）加同款行内编辑：铅笔 → 小输入框 → PUT → 局部刷新。

---

## D. 学生档案页重构（bug 修复之外的层级部分）

壳不动；页面内容自上而下：
1. **页头**：标题「学生档案」+ 一句副标题（保留现有文案）；右上 `导出 CSV / 刷新`（现有顶栏按钮，保留）。
2. **阶段条**（五卡：问卷待确认/等待学生作答/预约待测评/报告已生成/已就绪）：保留点击=筛选的交互，给**当前激活阶段**加高亮（现在激活态不明显）；每张卡 = 大号数字 + 小标签，彩色下划线只给激活卡。
3. **筛选行**：搜索框 + chips（全部/已完成 Y4/未测评）+ 右侧「共 N 位学生」，收敛为一行。
4. **表格 6 列**：学生（姓名+年级 chip+mono 编号）| 学校 | 顾问（hover 铅笔可编）| 测评状态（已完成+日期 / 未测评）| 当前阶段（badge+天数）| 操作（`进入档案` 链接 + ⋯：编辑/删除）。
5. 空态/错误态按 §A1 补齐。

---

## E. 测试残留数据清理（需需求方确认后执行）
本地库 `data/y4_students.db` 有冒烟测试残留：assignments 原因列含 `冒烟测试/c8 待确认列表验证/c8 浏览器端到端验证/账号流程测试/15 包本地预览` 等；students 含「测试学生(Y4-0002)」。
写 `scripts/cleanup_test_data.py`：默认 dry-run 列出将删的行（按 reason 模式 + 学生名匹配），`--apply` 落库。**执行前把清单给需求方过目**（「测试学生」可能还要留着做冒烟）。此为一次性脚本，不进应用代码路径。

---

## F. 执行顺序与验收

顺序（每步可独立提交）：
1. §A1 骨架 bug + §A2 清理 → 浏览器验证列表正常、不翻倍；
2. §C1 覆盖规则 + §C2 回填脚本（dry-run 先看输出）；
3. §B 合并工作台（含 B2/B3/B4/B5）→ 三种角色（admin/advisor/viewer）各验一遍；
4. §D 学生档案层级 + §C3 编辑入口；
5. §E 数据清理（确认后）。

验收清单：
- [ ] `/students` 无残留骨架；搜索/切阶段不重复追加；断网有错误态；
- [ ] `/questionnaires/assignments` 302 到 `/workspace`；侧栏只有一个入口；⌘K 无死链；
- [ ] 工作台五个状态 tab 计数与行数一致；sent 行只剩 1 主按钮 + ⋯；纯链接任务无「重置密码」；
- [ ] 待确认=琥珀、在途=中性、已提交=绿、已过期=红、已驳回=灰；
- [ ] viewer 进工作台只读，无任何写按钮；
- [ ] 生成/重生成报告后：学校被 OCR 刷新、手填顾问不被覆盖；
- [ ] 列表页与 360 页都能改学校/顾问并持久化；
- [ ] `pytest` 全绿（仓库已有测试体系）；`git status` 无模板/路由死引用。

涉及文件汇总：`templates/students.html`、`templates/workspace.html`、`templates/student_360.html`、`templates/layouts/admin_v2.html`、`templates/layouts/_command_palette.html`、`templates/questionnaires/assignments.html`（删）、`blueprints/workspace.py`、`blueprints/questionnaires.py`、`blueprints/reports.py`、`db.py`、`app_utils.py`、`static/admin_v2.css`（仅新增 ⋯菜单/激活态等少量组件类，遵守文件头「禁用 Tailwind」契约）、`static/command-palette.js`、新增 `scripts/backfill_school.py`、`scripts/cleanup_test_data.py`。

---

## G. 2026-10-19 后续交互调整：任务删除

- 工作台每一行（含 submitted / rejected）都提供「⋯」溢出菜单；五种状态都新增「删除问卷任务」。submitted / rejected 不再是无溢出菜单的状态。
- 右键任务行额外打开同一套动作的自定义上下文菜单。右键只是额外汇入，触屏/键盘用户仍可经「⋯」完成同样操作；viewer 不显示菜单且保留浏览器原生右键。
- 删除对象是**某学生的一条 assignment（问卷任务）**，不是 `questionnaires` 题库模板。永久硬删除，覆盖 `pending / sent / submitted / expired / rejected` 全部状态；同一事务清理该任务的 `responses`、`response_drafts`、`assignment_tokens` 后再删 assignment。
- 权限：仅 admin / advisor；advisor 只能删名下学生的任务，viewer 调用 API 返回 403。所有删除都必须先经过二次确认；取消确认不发 DELETE 请求。
- 不删除学生、题库模板、报告或共享 `student_accounts`，也不影响同学生的其他任务；删除后旧作答链接/账号任务不可再提交，可重新创建同卷任务。
