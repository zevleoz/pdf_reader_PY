# First Touch 融合进凭远平台 · 设计文档

> 日期：2026-10-22
> 状态：待用户评审
> 源仓库：`garytxzhang-taala-ai/first-touch`（private，Next.js 15 + React 19 + Prisma/Neon Postgres），已 clone 至 `~/projects/first-touch`，作为一次性功能来源，**不跟踪上游**。

## 1. 背景与目的

first-touch 是顾问会谈工作系统，包含两代产品：1.0 Growth Talk（素材上传 → DeepSeek AI 分析 → 人工审核 → 版本化报告）和 2.0 Copilot（四阶段会谈工作台 + 流式聊天），以及一层与兄弟系统（Yuguo/CRM/identity-center/activity-hub）的集成管道。

本平台（凭远教育 profiling 系统，Flask + Jinja + SQLite）的定位是**学生数据唯一源头**。本次融合把 first-touch 的功能移植进来，使会谈分析数据与测评数据沉淀在同一数据库、同一账号体系下。

已确认的关键决策（与用户对齐）：

- **方案 A：功能移植进 Flask**，不保留独立 Next.js 服务。
- **融合范围**：1.0 Growth Talk 管线 + 账号/权限合并 + Yuguo 集成四条链路；**不做 Copilot 2.0**。
- **PDF 渲染**：移植 first-touch 自己的排版引擎（`lib/report-pdf.ts`），不复用现有品牌化渲染器。Growth Talk 报告**仅内部使用**（顾问/管理员），不受品牌承诺约束。
- **历史数据要搬**：Neon → SQLite 一次性迁移，学生对应关系**导出对照表人工确认**后导入。
- Yuguo 是独立存活的兄弟系统，双向数据交互；**预约链路设计为通用契约**，未来其他 CRM 可参照同一方案预约 Y4。

## 2. 范围

### 2.1 移植（In scope）

| 模块 | 源位置 | 说明 |
|---|---|---|
| Growth Talk 分析管线 | `lib/growth-talk-*.ts`（约 1,000 LOC） | prompt 构建、JSON 校验、兜底主题提取、建议长度限制；一次 DeepSeek 调用 |
| 上传解析 | `lib/upload.ts`、`lib/pdf-text.ts` | PDF/DOCX/TXT → 文本，25MB 上限，错误分类法 |
| 报告契约与快照 | `lib/first-touch-report.ts`、`lib/reports.ts`、`lib/report-content-limits.ts` | 不可变版本化 JSON 报告 + 确认人身份 |
| 中文 PDF 渲染 | `lib/report-pdf.ts`（352 LOC）+ `public/fonts/NotoSansCJKsc-Regular.otf` | 移植为 Python/reportlab |
| 账号体系 | `lib/auth.ts`、`api/accounts`、`api/auth/*` | 合并进现有 `users` 表，不照搬 |
| Yuguo 链路 1：老师目录 | `api/integrations/teachers` | GET（Yuguo 拉取）+ POST（触发出站推送） |
| Yuguo 链路 2：学生导入与改派 | `api/students/import-yuguo`、`api/account/assignment-sync`、`lib/` 相关 | 显式导入 + 分配版本单调改派 |
| CRM 预约推送 | `api/integrations/crm/deliveries`、`api/crm-appointments`、`lib/` 相关 | 通用化设计（见 §6.4） |
| 报告对 Yuguo 可见 | 新增 `/api/v1` 端点 | 复用现有 Bearer API 体系 |
| 契约 schema | `docs/contracts/junction/` | 原样复制为接口校验依据与文档 |

### 2.2 不做（Out of scope）

- Copilot 2.0 全部：`CopilotSession` 系列表、四阶段工作台 UI、流式聊天（`copilot-model-stream.ts` 等）。
- Yuguo 集成层中的 identity-center、activity-hub 端点（用户未选择；代码留存于源仓库备查）。
- `IntegrationOutbox`（源仓库已废弃，契约明确不再写入）。
- `StudentModule`、`PathwayAssessment/PathwayReport`（Yuguo 侧业务，与本平台无关）。
- Neon 运维、`database-boundary.ts`、`FIRST_TOUCH_ENABLED` 切流开关、PGlite 工具。
- 深红/Arkitect 适配器（契约中明确尚未接入）。

### 2.3 历史数据迁移范围

仅 1.0 实体：Account、Student、SourceMaterial、GrowthTalkRun 及其子表（MeetingUnderstanding/InterestEvidence/QuadrantAnalysis/ExplorationSuggestion）、GrowthTalkReport、StudentExternalIdentity、AuditLog。**Copilot 历史数据不迁移**，Neon 导出文件归档备查。

## 3. 架构与模块落点

### 3.1 新增

- `blueprints/growth_talk.py` — Growth Talk 全部页面与操作路由，需 Advisor/Admin 登录。
- `blueprints/integrations.py` — Yuguo/CRM 方向的端点（Bearer token 鉴权，风格对齐 `api_v1.py`）。
- `growth_talk/` Python 包（移植 `lib/` 纯逻辑）：
  - `prompts.py` — DeepSeek prompt 构建
  - `analysis.py` — 分析结果 JSON 校验、兜底提取、长度限制
  - `report_contract.py` — 报告 payload schema 与版本化快照逻辑
  - `upload.py` — PDF/DOCX/TXT 文本提取（复用现有 PDF 提取，新增 python-docx）
  - `report_pdf.py` — reportlab 中文排版引擎（移植 `lib/report-pdf.ts`）
  - `yuguo_client.py` — 出站调用 Yuguo（学生导出读取、老师目录推送），走环境变量代理配置
- `templates/growth_talk/` — 审核工作台页面，Jinja + Tailwind/Alpine CDN，沿用 `templates/layouts/`。
- `static/fonts/NotoSansCJKsc-Regular.otf` — 从源仓库复制。

### 3.2 合并

- **账号**：`users` 表加 `email` 列（可空，不影响存量账号）。first-touch 角色映射：`TEACHER→Advisor`、`ADMIN→Admin`。注册限流复用现有进程内限流，不移植 `RegistrationRateLimit` 表。`sessionVersion` 踢人语义用现有 session 体系等价实现。
- **出站数据共享**：Yuguo 拉取本平台数据走现有 `/api/v1/*` Bearer API，新增报告端点（§6.5），不建第二套 API 体系。

### 3.3 复用

- LLM 调用模式：沿用平台现有的 LLM API 调用惯例；DeepSeek 为 OpenAI 兼容接口（`DEEPSEEK_API_KEY/BASE_URL/MODEL`，`response_format: json_object`，temperature 0.1）。
- 异步作业：沿用现有"分片上传 + 子进程异步作业 + 轮询"模式（隧道 ~100s 源站超时约束），LLM 分析在子进程中执行，前端轮询状态，AI 回复**不做流式**。
- 部署形态：不加进程、不加中间件、不引入 Node 构建链。

## 4. 数据模型

全部新表落进现有 SQLite（`data/y4_students.db`），建表方式沿用 `db.py` 的 `init_db()` 惯例（`CREATE TABLE IF NOT EXISTS` + 幂等 `ALTER TABLE` 列表）。cuid 字符串主键全部改为自增整型。JSON 字符串字段在 SQLite 中仍是 TEXT。

**不建第二张学生表**：Growth Talk 数据直接外键挂现有 `students.id`。

### 4.1 新表

| 表 | 来源模型 | 关键字段 |
|---|---|---|
| `gt_sources` | SourceMaterial | `id, student_id(FK students), type, purpose, source_kind, title, content, mime_type, file_name, original_path, file_size, source_format, external_report_id, external_student_id, external_version, external_status, external_confirmed_at, external_confirmed_by, structured_payload, extracted_text, extraction_status, key_points_draft, key_points_confirmed, confirmed_at, confirmed_by_name, created_at`；索引 `(student_id, created_at)` |
| `gt_runs` | GrowthTalkRun | `id, student_id, source_id, version, revision, status, error, model, created_at, updated_at`；`UNIQUE(student_id, version)` |
| `gt_understandings` | MeetingUnderstanding | `id, run_id UNIQUE, summary, topics, keywords, model, status, created_at, updated_at` |
| `gt_interest_evidence` | InterestEvidence | `id, run_id, label, subtopic, evidence, source_round, evidence_strength, uncertainty, preference_score(0-3), competence_score(0-3), special_focus, status, confirmed_at, confirmed_by, created_at, updated_at`；索引 `(run_id, status)` |
| `gt_quadrants` | QuadrantAnalysis | `id, run_id UNIQUE, points, narrative, status, model, created_at, updated_at` |
| `gt_suggestions` | ExplorationSuggestion | `id, run_id, title, introduction, growth_value, possible_outputs, recommendation_basis, interest_refs, exploration_tags, status, created_at, updated_at`；索引 `(run_id, status)` |
| `gt_reports` | GrowthTalkReport | `id, student_id, run_id, version, status, payload, confirmed_at, confirmed_by, created_at`；`UNIQUE(student_id, version)` |
| `external_identities` | StudentExternalIdentity | `id, student_id(FK), source_system, external_student_id, created_at, updated_at`；`UNIQUE(source_system, external_student_id)` |
| `audit_log` | AuditLog | `id, actor_id, student_id, action, details, created_at` |
| `crm_delivery_receipts` | CrmDeliveryReceipt | `message_id PK, junction_student_id, kind, task_id, revision, payload_hash, student_id, received_at`；索引 `(junction_student_id, kind, revision)` |
| `crm_appointments` | CrmPrecontractAppointment | `task_id PK, junction_student_id, student_id, teacher_id, revision, status, start_at, end_at, updated_at`；索引 `(teacher_id, status, start_at)` |

### 4.2 现有表改动

- `users` 加 `email VARCHAR(255)`（可空；后续按需加唯一索引）。

### 4.3 状态机

- `gt_sources.extraction_status`：`EXTRACTED / FAILED`（沿用源枚举值）。
- 审核状态统一三态：`PENDING_REVIEW / CONFIRMED / REJECTED`（understanding、interest evidence）与 `DRAFT / CONFIRMED`（quadrant、suggestions、reports），沿用源仓库枚举。
- `gt_reports.status`：`DRAFT → CONFIRMED`；确认后 `payload` 不可变。

## 5. Growth Talk 管线设计

### 5.1 主流程

1. **入口**：学生 360° 档案页新增"Growth Talk"区块（素材列表、历史 run、已确认报告）+「新建 Growth Talk」；学生列表页加「从 Yuguo 导入」。
2. **上传**：复用现有分片上传（绕隧道超时）；支持 PDF/DOCX/TXT，25MB 上限；提取文本写 `gt_sources`（`extraction_status`）；错误分类法移植自 `lib/upload.ts`。
3. **分析**：子进程任务调 DeepSeek（prompt 移植自 `lib/growth-talk-native.ts`）→ 产出 MeetingUnderstanding、InterestEvidence（偏好/能力 0-3）、QuadrantAnalysis、ExplorationSuggestion → JSON 校验（移植 `ajv` 校验逻辑为 Python `jsonschema`）→ 全部落库为 `DRAFT / PENDING_REVIEW`；失败时 `gt_runs.status=FAILED` + `error`，可用同一 source 重试。
4. **审核**（Jinja + Alpine）：顾问逐项 确认/修改/驳回 兴趣证据（可改 0-3 分数）、查看象限板（静态网格渲染 `points`，不做拖拽）、编辑建议文案。所有写操作带 `revision` 乐观锁（移植 revision-guard 语义）。
5. **确认**：单事务生成 `gt_reports` 不可变快照（`version` 递增，`UNIQUE(student_id, version)`）+ `audit_log` 记录确认人；finalize 语义同源契约——**本地确认即视为已推送，不自动发外部请求**。
6. **交付**：报告 JSON 下载 + PDF 下载（reportlab 渲染）；学生档案页可回看历史版本；经 `/api/v1` 对 Yuguo 可见。

### 5.2 错误处理

- DeepSeek 不可用/超时：run 标记 FAILED，不影响其他学生与其他功能；顾问可重试。
- LLM 返回非法 JSON：先走兜底主题提取（移植 `growth-talk-native.ts` 的 fallback），仍失败则该产物留空并标记需人工录入。
- 上传提取失败：`extraction_status=FAILED` + 错误信息展示，允许重新上传。
- Yuguo 不可用：导入/改派/目录推送全部降级为"稍后再试"，**本地功能与报告确认不受影响**（源契约核心语义）。

## 6. Yuguo / CRM 集成设计

**原则：Yuguo/CRM 面向的 HTTP 端点路径与载荷 schema 与源契约保持一致**，Yuguo 侧零改动，只需把 `FIRST_TOUCH_BASE_URL` 指向本平台域名。本平台浏览器自用的页面路由（如导入触发、改派核对）不按此约束，遵循平台现有路由惯例。契约 schema 文件从 `docs/contracts/junction/` 复制到本平台 `docs/integrations/`，作为校验依据（用 `jsonschema` 做入站校验）。契约语义（拒绝码、版本单调性、幂等、失败分类表）以源文档为准，移植时逐条落实。

### 6.1 链路 1：老师目录（本平台为账号主数据源）

- 入站 `GET /api/integrations/teachers`（Bearer `FIRST_TOUCH_DIRECTORY_TOKEN`）：返回启用 Advisor 的 `{id, name, email}` 快照，`id` 为本平台 user id。
- 出站：顾问账号 注册/创建/启停 后 best-effort `PUT {YUGUO_BASE_URL}/api/integrations/first-touch/teachers` 推送全量快照；推送失败不回滚本地账号操作。保留管理端手动同步入口。

### 6.2 链路 2：学生导入与改派

- `POST /students/import-yuguo`（session 鉴权，Advisor）：后端带 `YUGUO_STUDENT_READ_TOKEN` + `X-First-Touch-Teacher` 头调 Yuguo 学生导出接口 → 逐条短事务 创建/关联/刷新/识别已存在 → 返回 `localImport` 明细（COMPLETED/PARTIAL/FAILED + rejectedStudents）。单条失败不回滚其他学生；Yuguo 不可用不删除本地学生；手机号不用于合并。
- 自动改派：管理端页面在线时 ~15s 调 `POST /api/account/assignment-sync` → 后端核对 Yuguo 分配版本（单调递增 `assignmentVersion`）→ 行锁原子更新负责人 + 写审计；过期版本/同版本不同老师不回退；身份歧义拒绝。原顾问下次核对收到"访问权限已移除"通知（已读状态持久化）。
- 学生定位只经 `external_identities`（`source_system='yuguo'`）或相同 Yuguo Student ID；姓名/手机号不推断身份。

### 6.3 链路 3：报告对 Yuguo 可见

- finalize 不自动推送（同 §5.1-5）。
- 新增 `/api/v1` 端点（现有 Bearer token 体系）：按学生列出已确认 Growth Talk 报告元信息 + 获取单份报告 payload。Yuguo 程序化拉取走这里；人工交接走 JSON/PDF 下载。

### 6.4 链路 4：CRM 预约推送（通用化设计）

- 入站 `POST /api/integrations/crm/deliveries`（Bearer token）：接收外部系统的预约交付（创建/改期/取消），按 `junction.student_delivery.1.1.0` schema 校验，幂等（`message_id` + `payload_hash`），单调 `revision` 防回退，写 `crm_delivery_receipts` + `crm_appointments`。
- **通用契约设计**：端点与 schema 不硬编码 Yuguo——文档化为「外部系统预约 Y4 的标准契约」，Yuguo 是第一个接入方；未来其他 CRM 参照同一契约接入。契约文档落 `docs/integrations/y4-booking-contract.md`。
- 与现有 `bookings` 体系打通：预约交付落 `crm_appointments` 后，在学生档案/工作台展示；不与家长自助 `/booking` 混库。

### 6.5 配置

环境变量：`YUGUO_BASE_URL`、`YUGUO_STUDENT_READ_TOKEN`、`FIRST_TOUCH_DIRECTORY_TOKEN`（≥32 字符，两边一致）、`DEEPSEEK_API_KEY/BASE_URL/MODEL`。token 只存服务端环境变量，不进前端、不进日志。

## 7. UI 设计

- 全部 Jinja + Tailwind/Alpine CDN，沿用管理端 `templates/layouts/` 布局与既有色彩事实（暖纸底 `#FAF7F2`、品牌红 `#D25454`、墨色 `#161310`）。
- 页面：学生档案页 Growth Talk 区块、Growth Talk 审核工作台（理解摘要、兴趣证据可编辑列表、象限静态网格、建议编辑、确认按钮与版本历史）、学生列表「从 Yuguo 导入」入口及导入结果明细展示。
- 交互上限：Alpine 可覆盖 可编辑列表 + 分步表单 + fetch 轮询；不移植 React 的拖拽象限与流式聊天（1.0 不需要）。

## 8. PDF 渲染

- `lib/report-pdf.ts`（pdfkit 流式排版 + 字体测量，352 LOC）移植为 `growth_talk/report_pdf.py`（reportlab）。
- 中文字体 `NotoSansCJKsc-Regular.otf` 复制到 `static/fonts/`，reportlab 注册嵌入。
- 报告仅内部使用，原排版原样移植，不加品牌元素。
- 验收标准：同一份报告 payload，移植后 PDF 与源系统输出 版式一致（分页、行距、中文字形正常）。

## 9. 历史数据迁移（Neon → SQLite）

一次性脚本 `scripts/migrate_first_touch.py`，三步：

1. **导出**：从 Neon 导出 Account、Student、SourceMaterial、GrowthTalkRun 及子表、GrowthTalkReport、StudentExternalIdentity、AuditLog 为 JSON/CSV 中间文件（导出文件归档，含 Copilot 全量，备查）。
2. **对照表**：生成学生匹配预览（first-touch 学生 ↔ 本平台学生，按 姓名+年级 候选匹配），导出表格交用户**人工确认**；账号对照（email/姓名 → users）同样人工确认。
3. **导入**：按确认后的对照表执行。cuid 全部丢弃重映射为本平台自增 id；无匹配学生创建新记录（按现有规则生成 Y4 编码）；导入结果写 `audit_log`；可重复执行（幂等：以外部来源标记识别已导入记录）。

## 10. 测试策略

- 框架：pytest，文件落 `PDF_converter/test_growth_talk_*.py`（沿用现有 `test_*.py` 根目录惯例）。
- 方式：TDD——先把源仓库 21 个测试文件中的相关行为规格翻成 pytest，再实现。覆盖：
  - 上传提取：PDF/DOCX/TXT、超限、损坏文件的错误分类
  - 分析校验：合法/非法 LLM JSON、兜底提取、分数边界（0-3）
  - 报告契约：版本唯一、确认后不可变、长度限制
  - 学生导入：新增/关联/刷新/已存在/冲突/拒绝 全分支；手机号不合并
  - 改派：版本单调、过期不回退、身份歧义拒绝、审计写入
  - 老师目录：token 鉴权、只返回启用 Advisor
  - CRM 预约：幂等重放、revision 回退拒绝、schema 校验拒绝
- PDF 渲染：生成样例 PDF 后人工比对版式（自动测试只断言"能生成、非空、页数合理"）。

## 11. 上线顺序与红线

1. 在 git worktree 隔离分支开发（不污染主工作区）。
2. 测试全绿后部署生产，先跑 `init_db()` 建表（幂等，不影响存量数据）。
3. 执行历史数据迁移（含人工确认环节）。
4. 配置生产环境变量（DeepSeek、Yuguo 两个 token）。
5. 真实链路冒烟：登录 → Yuguo 导入测试学生 → 上传素材 → 分析 → 审核 → finalize → 下载 JSON/PDF → `/api/v1` 拉取验证 → 模拟 Yuguo 不可用确认本地功能不受影响。
6. 通知 Yuguo 侧把 `FIRST_TOUCH_BASE_URL` 切到本平台域名。

**红线**（对照 `docs/superpowers/specs/2026-10-14-y4-platform-2.0-design.md` 第 2 节）：OCR → 报告生成主链路文件、`data_points.py`、`report.html/report_v2.html` 模板一律不碰；新功能全部在新 blueprint/新包内，可整体下线。

## 12. 源仓库处置

`~/projects/first-touch` 保留为只读参考与迁移数据来源，不作为 submodule、不跟踪上游。移植完成后其 Neon 库按用户与对方协商处置（本设计不覆盖）。
