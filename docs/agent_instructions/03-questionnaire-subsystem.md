# Agent C 指令包：问卷子系统 —— 题库 + 识别引擎 + 任务状态机 + 学生端

> 五个实施包中的第三个，2.0 最大的新增功能。单一事实来源：`docs/superpowers/specs/2026-10-14-y4-platform-2.0-design.md`（下称 spec，第 6 节是本子系统的完整定义）。冲突时以 spec 为准并向需求方确认。

## 1. 背景与目标

业务场景：学生做完 Y4 测评（4 份 PDF 提取出 124 项指标入库）后，系统应**自动识别**该生还需要做哪些附加问卷，由顾问/Admin 确认后，通过**一次性链接**或**临时学生账号**发给学生在线填写，原始答案回写同一个学生档案库，供各部门查阅。

已确认决策（spec 1.3，不得变更）：系统内自建问卷页；固定题库（seed 导入，不可在线编题）；自动推荐 + 人工确认；链接+账号双制；**只存原始答案，不计分、不并入 124 指标**；顾问复制链接微信手动发，不做自动通知。

端到端数据流见 spec 6.1，状态机见 spec 6.5。

## 2. 前置依赖

| 依赖 | 需要的内容 | 缺位时的降级 |
|---|---|---|
| A 包 | users 表与角色装饰器；`students.student_code`；蓝图目录（本包路由进 `blueprints/questionnaires.py`）；`visible_student_filter()` | 不可缺位（A 必须先完成） |
| B 包 | `templates/layouts/admin.html` 的 block 契约（title/page_title/content/head_extra/scripts、`nav_active`、Toast） | 先用最小壳模板 `templates/layouts/_admin_stub.html`（仅含导航占位），B 完成后批量替换 extends |

**识别钩子的关键事实（已核对）**：`_save_report_to_db` 在 `app.py:487` 被 `_run_pipeline_job` 调用，而 `_run_pipeline_job` 是在**独立子进程**（`python app.py genjob <args.json>`，见 app.py:437-441 docstring）中执行的。因此：

- 钩子代码**不得依赖 Flask 请求上下文**（无 request/session 可用）
- 直接调 `db.py` 的查询函数（db.py 独立可用，进程启动时初始化 engine）
- 整个钩子调用必须 try/except 包裹，异常只 print/log，**绝不影响报告生成主流程的退出码**

## 3. 现状文件地图（已核对）

| 文件 | 关键位置 | 说明 |
|---|---|---|
| `app.py:355` | `_save_report_to_db(pdf_path, selected_sid, manual_name) -> Optional[int]` | 报告落库，返回 report id；钩子挂载在它的成功路径之后（A 包拆蓝图后在 `blueprints/reports.py`，注意 `genjob` 子进程入口在 app.py，搬迁时保持子进程可调用） |
| `app.py:437-501` | `_run_pipeline_job` | 子进程作业函数；487 行调 `_save_report_to_db` |
| `db.py:38-47` | Student 模型 | |
| `db.py:128-136` | `six_am_rule_versions` 表 | 版本管理模仿对象 |
| `db.py:1045-1052` | `publish_six_am_rule_version()` | "唯一 published"不变式实现：先把其他 published 置 archived，再发布目标 |
| `db.py:145-300` | `_migrate_schema()` | 迁移模式：列检查 + ADD COLUMN；新表 CREATE TABLE IF NOT EXISTS |
| `six_am/` | 整包 | 模块纪律范本：纯函数、不导入 Flask、不直接访问 DB；`six_am/tests/` 是全项目唯一测试目录——本包引擎照此写测试 |
| `data_points.py` | 124 项元数据 | 规则 DSL 的 `code` 引用这里的指标 code；先读它确认 code/value 的真实形态（数值型 value 多为数字，也有文本档位） |
| `templates/students.html` | 学生页 | D 包负责档案页聚合，本包只管「问卷中心」自身页面 |

## 4. 禁止事项

- 不改 OCR 管线与 `_run_pipeline_job` 的主流程行为（spec 第 2 节）；钩子只允许"追加调用"
- 不做计分、不做问卷结果并入 124 指标、不改 `data_points.py`
- 不做邮件/微信/短信等任何自动通知
- 不做在线编题（题库只能 seed 导入 + 启停）
- 不修改 `/api/v1/*` 既有端点契约（如需新增问卷相关 v1 端点，放本包末尾"可选扩展"，默认不做）
- 学生端页面不复用、不引入管理端 layout，不暴露任何管理端链接

## 5. 任务分解（按序执行，每步可验证）

### 5.1 数据表与迁移

- [ ] 新建 `questionnaire_store.py`（避免 db.py 继续膨胀）：6 张新表 + `response_drafts` 的 SQLAlchemy 模型与全部查询函数；字段严格按 spec 6.2
- [ ] 迁移入口挂进 `db.py` 的 `_migrate_schema()`（CREATE TABLE IF NOT EXISTS 模式），并提供独立脚本 `scripts/migrate_2_0_questionnaires.py`（执行前提示备份 SQLite）
- [ ] assignments 去重：`(student_id, questionnaire_id)` 活动任务唯一。SQLite 不支持部分唯一索引的 ALTER 追加——用 `CREATE UNIQUE INDEX IF NOT EXISTS ... WHERE status IN ('pending','sent')`（SQLite 与 PG 都支持部分索引）；同时在代码层先查后插兜底
- [ ] token：`secrets.token_urlsafe(24)`，DB 存原文（内部系统可接受）或 sha256——**选择 sha256 存储**，验证时 hash 比对，防库泄露后链接被伪造；在文档记录该决策
- [ ] 学生账号初始密码：`secrets.token_urlsafe(8)` 生成，**只在创建响应里明文返回一次**供顾问复制，DB 只存哈希

### 5.2 规则引擎包 `questionnaire_engine/`

- [ ] 模块纪律照 six_am：纯函数、零 Flask import、零 DB 访问
- [ ] 输入：`schema_124: list[dict]`（report 的 data_json 里的指标列表）+ `rules_json: dict`；输出：`[{"questionnaire_code": str, "reason": str}]`
- [ ] DSL 求值严格按 spec 6.4：`all`/`any` 二选一不嵌套；op ∈ `=, !=, <, <=, >, >=, in, contains`；数值比较前尝试 float 转换，失败回退字符串比较；引用不存在的 code 视为不命中（不报错）
- [ ] `questionnaire_engine/tests/`：覆盖各 op、all/any、类型对齐、无效 code、空 rules（用 pytest，对齐 six_am/tests 风格）
- [ ] 版本选择逻辑：仿 `six_am/__init__.py:53-70`——取 published 规则版；无 published 返回空命中（跳过）

### 5.3 固定题库

- [ ] `questionnaires_seed/` 目录：每问卷一个 JSON，格式按 spec 6.3（questions: single/multi/scale/text；required；options；scale 区间；max_length；预留 `visible_if` 不实现）
- [ ] 启动时 upsert：按 `code` 比对，新增/更新 `schema_json`，不删除库中已有但 seed 里消失的问卷（置 is_active=0 并记录）
- [ ] **至少内置 2 份示例 seed**（供联调；真实题库由需求方后续提供，文档注明如何新增 seed 文件）

### 5.4 识别钩子

- [ ] 在 `_run_pipeline_job` 中 `_save_report_to_db` 成功返回 report_id 之后追加：取该 report 的 schema_124 → 引擎求值（published 规则）→ 对每个命中且该生无活动任务的问卷创建 `assignment(status='pending', source='auto', reason=命中原因)`
- [ ] 整段 try/except，失败 print 到子进程 stderr（会被现有 traceback print 捕获），不改退出码
- [ ] 手动创建任务的入口（问卷中心"新建任务"）与自动推荐共用创建函数，source='manual'

### 5.5 任务确认与分发（管理端 API）

蓝图 `blueprints/questionnaires.py`（全部 admin/advisor，advisor 经 `visible_student_filter` 隔离）：

- [ ] `GET /questionnaires/assignments` 任务列表页（状态 tab：待确认/已发送/已完成/已过期/已驳回）
- [ ] `POST /questionnaires/assignments/<id>/confirm`：参数 delivery ∈ link/account/both → status='sent'，写 confirmed_by/at；按 delivery 创建 token（7 天有效期）和/或学生账号（已存在则复用，密码不重置——提供单独"重置密码"操作）
- [ ] `POST /questionnaires/assignments/<id>/reject` → rejected
- [ ] `POST /questionnaires/assignments/<id>/reissue`：expired → 新 token → sent
- [ ] `GET /questionnaires/assignments/<id>/package`：返回可复制文本块（链接 URL / 账号+初始密码+登录 URL），前端一键复制（Toast 反馈）
- [ ] `GET /questionnaires/bank` 题库列表 + 题目预览 + 启停
- [ ] `GET/POST /questionnaires/rules`：版本列表；新建 draft（JSON 编辑器 + 服务端 schema 校验）；**试算**：选任一学生 → 用其最新 schema_124 跑当前 draft → 展示命中与原因；发布走 spec 唯一 published 不变式（仿 db.py:1045）
- [ ] 规则管理仅 admin；题库启停仅 admin；任务确认/分发 admin + advisor

### 5.6 学生端（公开面，移动端优先，品牌化轻页面）

- [ ] `GET /q/<token>`：token 查 assignments（hash 比对）；无效 → "链接无效"；已用 → "问卷已提交"；过期 → "链接已过期，请联系顾问"；有效 → 渲染问卷（说明 + 题目）
- [ ] `POST /q/<token>/submit`：服务端按 schema_json 校验（必填、类型、选项值合法、max_length）→ 写 responses + token.used_at + assignment.status='submitted'；**重复提交防护**：assignment 已 submitted 则拒绝
- [ ] `GET/POST /student/login`：student_accounts 认证；session 用**独立 key**（如 `session['student_account_id']`），与管理端 session 互不通用；登录限流复用 A 的模式（5 次/分/IP）
- [ ] `GET /student/home`：待办问卷列表（delivery ∈ account/both 且 status='sent'）+ 已完成记录
- [ ] `GET /student/q/<assignment_id>` 作答页；`POST /student/q/<id>/draft`（写 response_drafts）与 `POST /student/q/<id>/submit`（同上校验与防重）
- [ ] 学生端模板独立（`templates/student/`），移动优先、纸感品牌色（参考 B 包色彩令牌：`#FAF7F2`/`#D25454`/`#161310`），单题卡片式或长页式均可（选定一种并全文一致）
- [ ] 每份问卷作答页顶部显示学生姓名+问卷标题（确认身份防填错）；不做"查看其他同学"的任何路径

### 5.7 档案页数据源（供 D 包）

- [ ] `questionnaire_store.py` 提供 `list_assignments_for_student(student_id)` 与 `get_response(assignment_id)`，返回 dict——D 包档案页「问卷」tab 直接消费；本包写完函数即可，页面归 D

## 6. 验收标准（端到端场景，逐步可执行）

1. 迁移后 6+1 张新表存在；题库 seed 导入 ≥2 份问卷
2. 引擎单测全绿：`cd PDF_converter && python -m pytest questionnaire_engine/tests/`
3. 规则管理页：发布一版规则（条件引用真实存在的 code，如学习动机相关指标），试算功能对任一已有学生返回命中/未命中结果
4. 触发识别：用测试 PDF 跑一遍完整报告生成（或直接在子进程环境模拟调用钩子函数），确认该生出现 status='pending' 任务，且重复触发不产生重复任务
5. 确认任务（delivery=both）→ 获得一次性链接与账号密码文本块
6. 无痕窗口打开 `/q/<token>` → 作答提交 → 再开显示"已提交"；responses 表有原始答案 JSON；assignment='submitted'
7. 学生账号登录 `/student/home` → 看到待办 → 存草稿 → 重进草稿还在 → 提交成功
8. token 手动改一个字符 → "链接无效"；expires_at 改到过去 → "已过期"；reissue 后新链接可用
9. advisor 登录只能看到自己学生的任务；viewer 访问确认/驳回端点被 403
10. 钩子异常注入（如临时改坏 rules_json）→ 报告生成主流程依然成功完成

## 7. 回归要求

- 报告生成全链路不变（上传→进度→v1/v2 下载→落库→学生页重生成）
- 现有全部页面与 `/api/v1/*` 不受影响
- 生成作业在 gunicorn 模式下仍走子进程（不得因本包引入线程/进程内队列）

## 8. 常见坑

- **钩子在子进程**：见第 2 节——不要在钩子链里 import Flask 请求上下文相关模块；db.py 的 engine 在子进程是独立连接，注意 SQLite 文件锁（子进程写时 web 进程读，短暂锁等待正常，别用长事务）
- **Jinja vs Alpine `{{ }}`**：管理页用 Alpine 时用 `x-text`/`x-for` 或 `{% raw %}`
- **SQLite 部分唯一索引**：ORM 层声明不了 `WHERE` 子句索引，在迁移里用原生 DDL 创建，模型层注释标明
- **初始密码只显示一次**：confirm 接口的响应里带上明文，前端复制后不落任何 storage；页面刷新后只能"重置密码"不能再查看
- **试算功能**只是只读求值，不得产生 assignment
- **规则 DSL 的 code 对齐**：发布前用 data_points.py 的 code 集合做服务端校验，发现引用不存在的 code 给警告（允许发布，但列出清单）

## 9. 遗留观察

（执行 agent 追加）

### 9.1 与指令包 / spec 的偏离

- **建表入口**：问卷 7 张表由 ORM 模型经 `Base.metadata.create_all` 在 `db.init_db()` 中创建（挂载在既有 `_migrate_schema` 之后），`scripts/migrate_2_0_questionnaires.py` 只负责导入 seed 题库与 `_rules_v1.json`，不重复建表。原因：复用现有对象，避免两套 DDL 漂移。
- **部分唯一索引**：`ux_assignments_active ON assignments(student_id, questionnaire_id) WHERE status IN ('pending','sent')` 无法在 ORM 层声明 `WHERE`，由 `_migrate_schema` 以原生 DDL 创建，模型层注释标明。
- **DSL 新增 `source: "eval"`**：条件可写成 `{"code":"068","op":"<","value":130,"source":"eval"}`，取 `evaluation_rules` 算出的有效评价档位 `eval_value` 参与比较。这正是「自我效能感偏低」的判定口径——常模平均数 `130` 为阈值，档位口径沿用项目既有的有效评价体系，纯数值判定。
- **DSL 不支持嵌套**：`(A 且 B) 或 C` 用「同一 `questionnaire_code` 写多条规则」表达，首个命中 wins。spec 的 013<10 且 054<6、或 068 偏低，由此拆成两条规则。
- **`assignments.reason` 列**：spec 6.2 未把识别原因列为持久化列，实现中落库以便管理端直接展示与追溯。
- **`blueprints/questionnaires.py` 取代 A 包占位**：`/questionnaires` 现重定向到 `/questionnaires/assignments`。

### 9.2 回归修复

- **`blueprints/workspace.py`**：原 `_pending_questionnaire_tasks` 用原生 SQL 读 `assignments.due_at`，该列不存在，异常被 `except` 吞掉后工作台一直显示「问卷模块未启用」。改为调用 `questionnaire_store.list_assignments(status="pending", advisor_name=...)`；`templates/workspace.html` 列名由「截止时间」改为「创建时间」。

### 9.3 Alpine 坑（本轮实测发现，已在 C 包内修正）

- **`x-for` 模板只允许单一根节点**：Alpine 内部只克隆 `content.firstElementChild`，其余根节点被静默丢弃并在控制台报警告。`bank.html` 原先在同一 `x-for` 内并置「主行 + 展开行」两个 `<tr>`，导致「查看题目」点了没反应。现展开内容移出表格，由 `expandedRow` 驱动的独立面板承载。
- **`x-data` 对象字面量的 getter 不可靠**：在 Alpine 响应式作用域下，`get expandedQ()` 取不到值（实测 `expanded` 已更新而 getter 仍返回空）。改用普通响应式属性（`expanded` + `expandedRow`）赋值维护。

### 9.4 本地验证记录（2026-10-15）

- `questionnaire_engine/tests/` 35 passed；`/tmp/smoke_c.py`（管理端 + 学生端 HTTP 冒烟）23/23；`/tmp/smoke_c2.py`（eval 通道 / 权限 / 规则版本流程）全部通过。
- 浏览器端（`PORT=8234 python app.py`）逐页确认：任务列表表格与筛选计数、新建任务弹窗（学生 6 项 / 问卷 7 项选项、完整落在视口内）、题库表格 + 题目展开面板、识别规则页、工作台待确认列表（含真实 pending 行）、学生端登录页 / 主页（待完成 1、已完成 2）/ 一次性链接表单（9 题、进度指示、选中高亮）/ 提交成功且重复访问提示「该链接已使用过」；提交后落库 9/9，管理端「查看答案」可读。各页均无横向滚动、无控制台报错。

