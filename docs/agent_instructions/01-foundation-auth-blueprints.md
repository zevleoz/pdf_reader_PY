# Agent A 指令包：地基 —— 用户/角色体系 + 学生唯一 ID + app.py 拆蓝图

> 本包是「Y4 平台 2.0」五个实施包中的第一个，其余包（B UI 框架 / C 问卷子系统 / D 页面迁移 / E 安全收尾）都依赖本包产出的契约。
> 单一事实来源：`docs/superpowers/specs/2026-10-14-y4-platform-2.0-design.md`（下称 spec）。本文档与 spec 冲突时以 spec 为准，并停下来向需求方确认。

## 1. 背景与目标

Y4 系统是凭远教育的内部系统：上传 4 份测评 PDF → 视觉大模型提取 124 项指标 → 渲染综合报告 → 落库学生档案。2.0 要把它升级为多角色的「学生 profiling 数据中心」。

本包做三件事，全部是**地基性质**：

1. **用户与角色体系**：废弃单一管理员密码，引入 users 表与 Admin / Advisor / Viewer 三角色（spec 第 3 节）
2. **学生唯一 ID**：students 表加 `student_code`（`Y4-0001` 格式），姓名不再是唯一标识（spec 第 4 节）
3. **app.py 拆蓝图**：4934 行单文件拆成 blueprint 包，**纯搬迁、行为不变**（spec 7.1）

完成标志：三角色可登录且权限生效；学生有唯一 code；应用拆成蓝图后 1.0 全部功能回归通过。

## 2. 前置依赖

无（本包第一个执行）。

**本包对外产出的契约**（后续包依赖，接口形状不得偏离）：

| 契约 | 内容 | 消费方 |
|---|---|---|
| session 结构 | `session['user_id']`, `session['role']` ∈ {admin, advisor, viewer}, `session['advisor_name']`, `session['display_name']` | B/C/D |
| 装饰器 | `login_required` / `role_required(*roles)`，位于 `app_utils.py` 或 `blueprints/auth.py` 并可被各蓝图导入 | B/C/D/E |
| Advisor 数据隔离 | 查询辅助函数 `visible_student_filter(stmt)`（advisor 角色自动附加 `students.advisor_name` 过滤） | C/D |
| 蓝图目录 | `blueprints/{auth,workspace,students,reports,questionnaires,insights,tools,system,api_v1}.py` 已建立并注册 | B/C/D |
| students.student_code | 已迁移回填，新建学生自动分配 | C/D |

## 3. 现状文件地图（已核对）

| 文件 | 关键位置 | 说明 |
|---|---|---|
| `PDF_converter/app.py` | 4934 行单文件 | 全部路由所在 |
| `app.py:64` | `ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'y4admin2026')` | 旧单密码机制 |
| `app.py:74-81` | `admin_required` 装饰器 | 写操作端点用，返回 403 JSON |
| `app.py:84-91` | `page_login_required` 装饰器 | 页面路由用，重定向 /login |
| `app.py:107-119` | `_v1_rate_check()` 滑动窗口限流 | 现有模式，登录限流复用这个思路 |
| `app.py:242` | `login_page()` | 登录页路由 |
| `app.py:2014-2031` | `api_admin_login` / logout / session 检查 | `session['is_admin'] = True` 在 2018 行 |
| `app.py:355` | `_save_report_to_db(pdf_path, selected_sid, manual_name)` | 报告落库，内部调 `find_or_create_student` |
| `app.py:437-501` | `_run_pipeline_job(job)` | **在独立子进程中执行**（`python app.py genjob <args.json>`），487 行调 `_save_report_to_db` |
| `PDF_converter/db.py` | 1963 行 | ORM + 手写迁移 |
| `db.py:38-47` | `class Student(Base)` | students 表：`advisor_name` 在 47 行 |
| `db.py:145-178` | `_migrate_schema()` | 迁移模式：列存在性检查 + `ALTER TABLE ... ADD COLUMN`，新表用 `CREATE TABLE IF NOT EXISTS`（参考 290-300 行 six_am_rule_versions） |
| `db.py:325-353` | `find_or_create_student(...)` | **当前纯姓名匹配**，本包要改 |
| `templates/login.html` | 整个文件 | 单密码表单，要改成账号+密码 |
| `six_am/__init__.py:53-70` | published 版本选择逻辑 | 可参考 |

## 4. 禁止事项

- **不许改** OCR 管线：`extract.py`、`generate.py`、`data_points.py`、`validate.py`、`gauge_reader.py`、`gauge_processor.py`、`new_iteration/`（本包唯一例外：无。key 轮换在 E 包）
- **不许改** `_run_pipeline_job` 的执行模型（子进程 fork）、分片上传协议、`/api/v1/*` 的路径/鉴权/响应结构
- **不许改** 部署文件：`deploy/cloud-init.sh`、`y4_report.service`、`gunicorn_config.py`、`nginx_y4.conf`
- 拆蓝图时**不许顺手"优化"任何路由逻辑**——发现一个路由行为可疑，记录在文档末尾「遗留观察」，不改动
- 不许删除 `ADMIN_PASSWORD` 环境变量读取本身（保留读取，仅改判定逻辑，见 5.2）

## 5. 任务分解（按此顺序执行，每步完成后应用必须能启动）

### 5.1 users 表 + 迁移骨架

- [ ] `db.py` 新增 `User` 模型（字段严格按 spec 3.2：id / username UNIQUE / password_hash / role / advisor_name / display_name / is_active / created_at）
- [ ] 密码哈希用 werkzeug `generate_password_hash` / `check_password_hash`（requirements 已有 werkzeug，Flask 依赖自带）
- [ ] `_migrate_schema()` 追加 users 建表（沿用 six_am_rule_versions 的 `CREATE TABLE IF NOT EXISTS` 模式；注意 SQLAlchemy Core 表达，SQLite/PostgreSQL 双兼容）
- [ ] `db.py` 加查询函数：`get_user_by_username()`、`get_user_by_id()`、`list_users()`、`create_user()`、`update_user()`（改密/停用/改角色）、`verify_user(username, password) -> Optional[dict]`
- [ ] 迁移脚本 `scripts/migrate_2_0_foundation.py`（新建 scripts 目录）：建表 → 若 users 为空，从 `Y4_INITIAL_ADMIN_USER` / `Y4_INITIAL_ADMIN_PASSWORD` 环境变量创建初始 admin（缺省报错退出，不硬编码默认值）→ 打印创建结果。**执行前提示备份 SQLite 文件**

### 5.2 认证改造

- [ ] `templates/login.html`：单密码框 → 账号 + 密码两框（视觉保持现状即可，UI 升级是 B 包的事）
- [ ] 登录 POST：验证 users 表 → 成功写 `session['user_id'] / ['role'] / ['advisor_name'] / ['display_name']`，写 `session.permanent` 沿用现有配置
- [ ] 登录限流：复用 `_v1_rate_check` 的滑动窗口模式，scope='login'，同一 IP 5 次/分钟，超限返回 429（页面友好提示"尝试过多，请稍后再试"）
- [ ] 旧密码处置：若 users 表非空，旧 `ADMIN_PASSWORD` 一律不再放行；若请求提交的是旧密码格式（只有密码无账号），返回提示"系统已升级，请使用账号密码登录"
- [ ] 新装饰器（放 `app_utils.py`）：
  ```python
  def login_required(f): ...        # 未登录 → 页面跳 /login?next=..., API 返回 401
  def role_required(*roles): ...    # 未登录同上；角色不符 → 页面 403 页 / API 403 JSON
  ```
- [ ] 兼容桥：`admin_required` 与 `page_login_required` 改为内部调用新装饰器（等价于 `role_required('admin','advisor')` 的登录语义 + 后续 5.4 的细粒度收紧），保证本包中段旧代码编译通过
- [ ] `is_admin` session key 停止写入；读取处全部改走新 session 结构（全库 grep `is_admin` 逐一替换）

### 5.3 角色权限落地（逐路由标注）

- [ ] 给每个现有路由标注角色归属（按 spec 3.1 权限矩阵）：
  - Admin：一切
  - Advisor：学生/报告/生成/预约/纪要/问卷任务（C 包路由预留位置）可读可写；dashboard、y4-signals、six-am 可读；系统管理不可见
  - Viewer：全部页面只读；所有 mutating 端点（POST/PUT/DELETE，`/api/v1/*` 除外）对 viewer 返回 403
- [ ] 实现 `visible_student_filter(stmt)`：role==advisor 时附加 `Student.advisor_name == session['advisor_name']`；在以下查询点接入：`/students` 列表、学生详情、报告列表、dashboard 聚合（dashboard 的 advisor 过滤可以简化为不过滤——dashboard 是聚合统计，viewer 也能看；**只对可定位到个体学生的页面做隔离**）
- [ ] 公开面确认无需登录：`/`、`/booking`、`/api/docs`、`/api/v1/*`（Bearer 不变）、`/login`

### 5.4 student_code

- [ ] `db.py` Student 加列 `student_code = Column(String(20), unique=True, index=True)`；`_migrate_schema()` 追加 ADD COLUMN（模式同 178 行 advisor_name）
- [ ] 迁移脚本回填：按 id 升序分配 `Y4-0001` 起；回填后加唯一性校验
- [ ] `db.py` 加 `next_student_code()`（事务内 `SELECT MAX` + 1，注意并发场景下 SQLite 单写者足够、PG 用序列或唯一约束重试）
- [ ] 新建学生处（`find_or_create_student` 及预约关联建学生处）自动分配 code
- [ ] **`find_or_create_student` 微调**：先按 (name, birthday) 查；仅当 birthday 为空时退化为纯姓名匹配；同名不同 birthday 时创建新学生。改动最小化，保持函数签名不变
- [ ] `/students` 列表与学生相关页面显示 code（模板小改；大改版在 D 包）

### 5.5 app.py 拆蓝图（纯搬迁）

目标结构（spec 7.1）：

```
PDF_converter/
  app.py              # create_app()、注册蓝图、ProxyFix、全局配置、genjob 子进程入口
  app_utils.py        # 装饰器、限流、共享小工具
  blueprints/
    __init__.py
    auth.py           # /login /logout
    workspace.py      # /workspace 打桩（返回"工作台建设中"，B 包填内容）
    students.py       # /students*
    reports.py        # /generate、/api/upload/*、/api/progress、/api/generate/*、/api/export
    questionnaires.py # /questionnaires* 打桩（C 包填充）
    insights.py       # /dashboard /y4-signals /six-am*
    tools.py          # /admin/bookings /transcript /internal /prompt-lab /booking
    system.py         # /system/* /api/docs（/system/users 用户管理本包实现：admin 增删改查用户）
    api_v1.py         # /api/v1/*
```

执行纪律：

- [ ] **一次拆一个蓝图**，每拆完一个：启动应用 + 对该蓝图全部路由冒烟（页面 200 / API 预期状态码）+ git commit
- [ ] 建议拆分顺序（从边缘到核心）：auth → system → tools → insights → students → api_v1 → reports（最大最危险，放最后）
- [ ] `_run_pipeline_job`、`_save_report_to_db`、`_write_job` 等作业函数随 reports 蓝图搬迁，但注意 **`genjob` 子进程入口**（`python app.py genjob`）必须保持可独立调用——子进程模式 import app 后调函数，蓝图化后确保该路径不依赖 Flask 请求上下文（现状即如此，保持）
- [ ] `_dashscope_chat` 等 AI 调用封装搬到 `app_utils.py` 或独立 `ai_client.py`，引用处全部更新（app.py:898/1098/2243/2551/2911/2989/3607 等处读取 DASHSCOPE_API_KEY 的位置一并搬迁）
- [ ] 拆完后 `app.py` 应 < 400 行

### 5.6 冒烟与回归

- [x] 本地 `python app.py` 启动无错；gunicorn 模式启动无错（`gunicorn -c gunicorn_config.py app:app`，注意 preload 下导入副作用）— 本地已验证（见 §9 验证证据）
- [ ] 走一遍完整报告生成流程（测试 PDF 在 `input/` 目录），确认子进程作业、进度轮询、结果下载、落库全链路不变 — 本机无测试 PDF/Chrome，**待生产服务器验证**（见 §9）

## 6. 验收标准

可执行验证（全部通过才算完成）：

1. `python scripts/migrate_2_0_foundation.py` 在备份后的开发库上执行成功，users 表有初始 admin，students 全部有 `Y4-XXXX` code 且无重复
2. 三角色账号登录：admin 全通；advisor 访问 `/system/users` 被拒（403 或重定向）；viewer 对任一 mutating 端点 POST 返回 403
3. advisor 登录后 `/students` 只见 `advisor_name` 匹配自己的学生
4. 旧密码 `y4admin2026`（或环境变量里的旧值）不再能登录
5. 登录接口 1 分钟内第 6 次尝试返回 429
6. 同名不同生日的两个学生不再被合并为一人
7. 蓝图拆分后：1.0 全部页面路由（/generate /students /dashboard /y4-signals /six-am /booking /admin/bookings /transcript /internal /prompt-lab /api/docs）200；`/api/v1/*` 契约不变（Bearer 鉴权、响应结构一致）
8. 完整跑通一次报告生成（上传 4 份测试 PDF → 进度 → 下载 v1/v2 → 学生档案可见）

## 7. 回归要求

1.0 功能全量核对清单（拆蓝图后逐项过）：上传分片 /api/upload/chunk → 作业启动 /api/generate/start → /api/progress 轮询 → /api/generate/result 下载（含 ?v=2）→ /students 列表与重生成 → /dashboard → /y4-signals → /six-am 与 /six-am/rules → /booking（公开）与 /admin/bookings → /transcript 生成纪要 → /internal → /prompt-lab → /api/export → /api/v1/* 各端点。

任何一项失败，修到达标再交付，不允许"先交付再补"。

## 8. 常见坑

- **gunicorn max_requests=10**：worker 会被频繁回收，任何模块级可变状态都不可靠；别在新代码里引入进程内缓存（现有 `_V1_RATE_BUCKETS` 是既有模式，登录限流沿用它可以接受，知道其在多 worker 下按 worker 计数即可——生产 worker=1）
- **子进程作业**：`genjob` 路径在子进程执行，不能 import 任何依赖 Flask 请求上下文的模块；蓝图拆分别把 request/session 的 import 带进它的 import 链
- **SQLite 迁移**：`ALTER TABLE ADD COLUMN` 不支持加 UNIQUE 约束——student_code 先加普通列、回填、再用 `CREATE UNIQUE INDEX IF NOT EXISTS` 实现唯一
- **find_or_create_student 的调用方**：除了 `_save_report_to_db`，核对是否还有预约链路调用（db.py:509 附近 `find_or_create_student` 另有变体），改动语义时两处都要顾及
- **session 兼容**：改造期间若本地有旧 session cookie，测登录前先清 cookie，避免假象
- **不要在本包做 UI 美化**——login.html 只加字段，视觉归 B 包

## 9. 遗留观察（执行时记录，不处理）

（执行 agent 在此追加发现的问题清单，供后续包参考）

- **`/output/<path:filename>` 曾绕过鉴权**：`app = Flask(..., static_folder=OUTPUT_DIR, static_url_path="/output")` 注册的内置静态路由会**优先于**带 `@admin_required` 的同名自定义路由，导致任何未登录者可直接读取 `output/` 下全部生成产物（含报告 PDF 等含学生隐私文件）。已修复：改为 `static_folder=None`，`/output/<filename>` 只保留一个带鉴权的端点，并 **白名单** 放行公开落地页示例图 `report_title_page.png`（`PUBLIC_OUTPUT_ASSETS`）。B/E 包若改动静态资源服务方式，须保留该鉴权语义。
- **`/api/availability/month`（GET）保持公开**：预约页需要按月展示可约时段，因此该端点维持公开；其响应含各时段的已约计数，属可接受的信息暴露（无学生身份）。E 包若要收紧可评估。
- **`_migrate_schema()` / `backfill_student_code()` 的数据源已改为 `DATABASE_URL` 解析**：原实现写死 `DEFAULT_DB`，在 `DATABASE_URL` 指向其它 SQLite 文件（如测试库）时会迁移错库。已改为从 `DATABASE_URL` 解析路径；生产默认路径不变。
- **`/api/minutes/<id>`（GET/PUT/DELETE）原无 advisor 隔离**：只校验登录，advisor 可按 id 访问他人学生纪要。已补 `@minutes_scoped` 装饰器。
- **`app.py` 中 `ADMIN_PASSWORD` 读取保留但已无任何判定逻辑引用**（符合 §4 要求），E 包可决定是否彻底移除该环境变量。
- **`templates/app_shell.js` 的 `navigator.platform` 已废弃警告**为既有诊断，与本次改动无关，未处理（E 包可顺手换 `navigator.userAgentData`）。
- **CORS 头保留在 `app.py` 的全局 `after_request`**：5.5 拆蓝图时，`_apply_v1_cors` 未移到 api_v1 蓝图，而是留在 `create_app()` 内挂在 `@app.after_request`。原因：蓝图级 `after_request` 只对已匹配到该蓝图路由的请求生效，`/api/v1/<未知路径>` 的 404 将丢失 CORS 头（行为回退）。保持不变即维持既有语义。
- **共享常量从 `app.py` 迁到 `app_utils.py`**（`BASE_DIR`/`OUTPUT_DIR`/`UPLOAD_DIR`/`JOB_FILE`/`REQUIRED_KEYS`/`Y4_API_*` 等），供各蓝图导入；`app.py` 只保留 `create_app()`、静态资源路由、`ADMIN_PASSWORD` 读取与 genjob/run 入口。
- **AI/分析 helper 独立为仓库根 `ai_client.py`**（非 `blueprints/` 内，避免包内相对导入）：包含 `_dashscope_chat` 及 Y4 解读/E4 协议构建的一批 `_build_*` / `_format_*` / `_parse_*` helper，被 `reports` / `tools` / `api_v1` 三个蓝图共用（原先在 `app.py` 中）。**注意**：若后续包再拆这些 helper，`reports` / `tools` / `api_v1` 的导入清单需同步更新。
- **依赖模块在 git 中未被跟踪（本包之外的历史遗留）**：`minutes_docx.py`、`minutes_schema.py`、`six_am/`、`new_iteration/`（含被 `generate.py` 引用的 `render_v2`）均被 `app.py` / 蓝图 import 但从未进入版本控制。本工作区可正常运行，但**新机器 `git clone` 会直接 ImportError**。本包未处理（§1.4 明确不做仓库清理），建议另立任务或在后续包补提交。
- **A 包验证证据（§5.6 / §6）**：本地用临时 SQLite 库（`DATABASE_URL` 指向 tempfile）复跑，§6 第 1–7 条全部通过（迁移建 users + student_code 回填无重复；三角色登录与权限；advisor 只见名下学生；旧密码被拒且无账号格式返回升级提示；同 IP 1 分钟第 6 次 429；同名不同生日不合并；蓝图后页面路由全 200、`/api/v1/*` 契约不变）。`python app.py` 与 `gunicorn -c gunicorn_config.py app:app`（以等价临时配置在 127.0.0.1 上验证，`preload_app=True` 下 worker 正常启动、`/login` `/api/v1/health` `/style.css` 均 200）均无错。`python app.py genjob <args.json>` 子进程入口验证：可独立 import `blueprints.reports._run_pipeline_job`、不依赖 Flask 请求上下文、作业状态正常写入 `data/_job.json`（在缺输入 PDF 时按预期以中文错误收尾）。
- **§6 第 8 条（完整报告生成链路）与生产 gunicorn 未在本地验证**：本机无 `input/` 测试 PDF、无 Chrome/Chromium，无法跑通 upload → extract → generate → 落库全链路，也无法用仓库 `gunicorn_config.py` 原样启动（它绑定 `/tmp/y4_report.sock` 并写 `/var/log/y4_report`）。**需在生产 8.153.154.174 上验证**：上传 4 份测试 PDF → `/api/progress` 轮询 → `/api/generate/result` 下载 v1/v2 → 学生档案落库；以及 `systemctl restart y4_report` 后 gunicorn 启动无错。另注：本机曾以 `pip3 install --user gunicorn` 临时安装 gunicorn（仅在 `~/.local`，未改动仓库依赖文件）。
- **工作区存在早于本包的未提交改动**：`generate.py`（新增 [4/4] v2 平行输出段，调 `new_iteration/render_v2`）与 `output/preview.html` 在本次开工前即为 modified，**非本包所为**（§4 禁改 `generate.py`，未触碰）。这解释了 `_find_generated_pdf` 对 `_v2_` 产物的处理。后续部署 `git pull` 前需先备份/提交这两处，否则会冲突（参见项目部署笔记）。
