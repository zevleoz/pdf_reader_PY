# Copilot 2.0 移植 · 设计增补

> 日期：2026-10-23
> 状态：用户已批准第 1 段（数据模型与状态机），并指示直接进入计划编写；第 2–4 段设计决策由本文档记录。
> 前置：`2026-10-22-first-touch-merge-design.md`（第一阶段：1.0 Growth Talk 管线、账号合并、Yuguo/CRM 集成——已实施完毕）。
> 源仓库：`~/projects/first-touch`（只读参考）。

## 1. 范围

将 first-touch 的 Copilot 2.0 完整移植进本平台，并以独立分区形态呈现：

- **七阶段会谈工作台**（原版 PHASES：`会议准备 / 目标说明 / Y4 结果解读 / 兴趣事项 / 总结与下一步 / 会后补充 / 报告确认`，索引 0–6，自由跳转、无强制流转图，门控按功能而非阶段）
- **Copilot 聊天中心**（学生选择器 + 按学生对话）
- **独立分区外壳**：管理端导航新增 "First Touch" 分组——工作台首页（学生列表）/ 聊天中心 / 归档 / 使用指南

依赖第一阶段资产（已上线）：`growth_talk_store.py`（gt_* 表）、`growth_talk/analysis.py`（DeepSeek 客户端）、`growth_talk/report_contract.py`（报告契约与确认事务）、`growth_talk/report_pdf.py`、上传解析、异步作业模式。

## 2. 数据模型（新增 6 表，进 `growth_talk_store.py`）

| 表 | 关键字段 |
|---|---|
| `copilot_sessions` | `id, student_id(FK students), advisor_id(FK users), y4_report_id(FK reports, 可空), meeting_source_id(FK gt_sources), run_id(FK gt_runs), phase INTEGER 默认 0, revision INTEGER 默认 1, status 默认 "ACTIVE", script TEXT(JSON), interests TEXT(JSON), meeting_at, created_at, updated_at, completed_at`；索引 `(student_id, created_at)` |
| `copilot_phase_events` | `id, session_id(FK 级联), actor_id, phase, action, created_at`；索引 `(session_id, created_at)` |
| `copilot_career_calibration` | `id, session_id UNIQUE, career_interests, ability_tendencies, value_preferences, notes, updated_at`（各字段 ≤4000 字） |
| `copilot_interest_notes` | `id, session_id, interest_id, note, updated_at`；`UNIQUE(session_id, interest_id)`（`interests` JSON 是真相源，本表供查询） |
| `copilot_transcript_supplements` | `id, session_id, source_id, status 默认 PENDING_REVIEW, analysis TEXT(JSON), created_at`；索引 `(session_id, created_at)` |
| `copilot_chat_messages` | `id, chat_id VARCHAR(36), student_id, session_id 可空, role(question/answer), content, evidence TEXT(JSON), status, created_at`；索引 `(student_id, created_at)` |

**与原版差异**：原版聊天历史存浏览器 localStorage（`first-touch-copilot:v2:{accountId}:{studentId}`，上限 20 对话 × 20 轮）；移植版入库（本平台"数据是资产"原则），`chat_id` 分组对话，保留同样上限。

**`script` JSON**：`{entryMode: "guided"|"direct", goal, opening, interpretation, transition, closing（各 ≤3000）, nextSummary?（≤1400）, reportInputFingerprint?: sha256hex}`；新建 session 写入五个固定中文默认话术（逐字移植自源 `sessions` POST 路由）。

**`interests` JSON**（InterestDraft[]，≤120 条）：`{id: uuid, label ≤80（大小写不敏感去重）, topicType: subject|interest|social, preferenceScore/competenceScore: 0-3 整数或 null, note ≤2000, evidence ≤4000}`。

**`supplements.analysis` JSON**：`{analysisVersion: uuid, newInterests: [{label ≤24（括号前）, topicType, evidence ≤500, preferenceScore, competenceScore}] ≤30, scoreConflicts: ≤20×≤500字, y4Validation: ≤3×≤100字, questions: ≤20×≤500字, interestReview?, interestBindings?, projectRecommendations?: RecommendationBatch, projectRecommendationHistory?: RecommendationBatch[]}`。保留键 `projectRecommendations/projectRecommendationHistory/newInterests/analysisVersion/interestReview/interestBindings` 归专属端点所有，phase PATCH 不得覆盖。

## 3. 七阶段流程

- **0 会议准备**：Y4 校准 + 五段话术编辑。**Y4 打通**：读取该学生最新已确认的平台 Y4 报告（`reports.data_json` 124 指标 + 解读文本），一次 DeepSeek 调用生成职业校准（兴趣/能力/价值三段，各 ≤150 字单行），可人工编辑（PATCH career-calibration）；`y4_report_id` 记录引用。学生无 Y4 报告时该阶段提示"请先完成 Y4 测评报告"，不阻塞其他阶段查看。**不上传 Y4 文件**（与原版差异，用户已确认）。
- **1 目标说明 / 2 Y4 结果解读**：只读展示话术 + 校准。
- **3 兴趣事项**：兴趣草稿手工 CRUD + 0–3 打分 + QuadrantBoard（4×4 纯 CSS 网格：行=擅长 3→0、列=喜欢 0→3；双 ≥2→strong、喜欢 ≥2→explore、擅长 ≥2→capable、余→quiet；图例 `横轴：喜欢 0–3 / 纵轴：擅长 0–3`）。
- **4 总结与下一步**：进入时自动生成下一步 AI 摘要（`next-steps` 端点）；ThreeLevelQuadrantBoard（3×3，level: null→无、≥3 高、=2 中、≤1 低；高×高→strong、低×低→quiet、余→middle）。
- **5 会后补充**：上传会谈记录（MEETING source + 自动建 PENDING_REVIEW supplement）→ `supplement` 端点 AI 审核（newInterests/scoreConflicts/y4Validation/questions，全部带长度钳制）→ 候选逐条 保留/应用/编辑/排除 → `projects` 端点生成 Passion Project 推荐（2–5 条，证据引用必须是会谈原文逐字子串，否则标 `needs_evidence`）；顾问编辑后新版本批次（`inputFingerprint` 防过期），通过的条目同步进 `gt_suggestions`（tag `passion-project.v1`）。
- **6 报告确认**：进入置 `status="REVIEW"`；prepare → preview → confirm → PDF。

**入口模式**：创建 session 时 `guided`（phase 0）或 `direct`（直接 phase 5）。**幂等创建**：一个学生一个顾问一条 session，重复 POST 返回 `{session, existing: true}`（200）。

**revision 守卫**：所有变更带 `revision ≥ 1`；不匹配 → `409 会谈已更新，请保留草稿并刷新确认`；负责人变更 → `409 本地负责人已变化，本次操作未保存`；成功后 revision+1 并写 phase event。顾问隔离沿用 `advisor_name` 机制，非本人 → `404 会谈不存在`。

## 4. 报告流（复用第一阶段）

- `handoff`：把 session 物化为 `gt_runs`（复用 `session.run_id` 或新版本；兴趣草稿逐条转为 `gt_interest_evidence` CONFIRMED 行，evidence 拼接 `；顾问 Note：{note}` 或 `顾问会议评分，待核对证据。`，按 label 匹配；understanding summary 由 top-2 兴趣标签合成；`script.reportInputFingerprint = sha256({sourceId, student{name,grade}, interests, summary})` 命中则幂等返回既有 run）。
- `prepare`（**非流式 JSON**，折叠原版 SSE）：校验 → draft（含 `missing` 必填检查：grade/meeting/interests/逐兴趣评分/eligible-interests/projects-stale）→ 必填缺失则只回 draft → handoff → quadrant 缺失或 STALE 时跑一次象限分析（唯一 LLM 调用）→ 第一阶段 `build_report_preview` → `{draft, preview, revision, runId, reportId}`。
- `confirm`：幂等（该 run 已有 CONFIRMED 报告 → 200 返回）；否则第一阶段 `confirm_report` + session revision 守卫 + 置 session `COMPLETED/completedAt` → 201。
- `report-pdf`：下载前后双检 revision+fingerprint（`409 报告内容已变化，请重新预览再下载`）；草稿 PDF 文件名 `{姓名}-会谈报告-草稿.pdf`；确认报告走第一阶段 `render_report_pdf`。
- 报告落入同一 `gt_reports` 表 → 学生 360、归档页、`/api/v1` 全部自动可见。

## 5. 聊天中心（非流式降级）

- 端点：`POST /api/students/<sid>/copilot/assistant`（学生级，自动挂最新 session 上下文）与 `POST /api/v2/copilot/sessions/<id>/assistant`（session 级）。
- 请求 `{question: 1–1000 字（否则 400 问题不能为空且不能超过 1000 字）, history?: ≤6 轮（question ≤1000、answer ≤8000，否则 400 聊天上下文格式无效）}`。
- 上下文装配：学生姓名/年级、会议记录（≤30000 字）、Y4 报告内容（≤30000 字）、session 兴趣（evidence+note 拼接）。LLM 为第一阶段 DeepSeek 客户端，非流式，`response_format: json_object`，温度 0.1；期望 `{"answer": 1–4000 字, "evidence": [{source: 会议纪要|Y4报告|当前分析|方法论, detail}] ≤8 条}`，校验失败/截断按原版文案报错。
- 原版 SSE 增量 JSON 提取（`partialAnswer`）不移植——非流式一次性返回完整答案。
- 页内浮动聊天：仅在顾问阶段（0/5/6）显示。

## 6. 独立分区外壳

管理端导航新增 "First Touch" 分组（`register_admin_context` 的 `nav_groups`），四个页面：

- `/first-touch`——工作台首页：当前顾问的学生卡片（素材/run/报告计数、session 阶段徽标、updated 降序）、「手动添加学生」弹层（`requestId` UUID 幂等）、「从 Yuguo 导入」（复用第一阶段端点与明细弹层）。
- `/first-touch/students/<sid>`——七阶段工作台：阶段导航条自由跳转、每阶段独立 Alpine 表单提交对应端点、脏检查 + `beforeunload`、阶段 0/5/6 显示浮动聊天。
- `/first-touch/copilot` + `/first-touch/copilot/<sid>`——聊天中心：学生选择器、按学生对话列表（DB 历史）、`?chat=<chatId>` 深链。
- `/first-touch/guide`——使用指南静态页，文案逐字复制自 `app/guide/page.tsx`。
- `/first-touch/archive/<sid>`——Admin 限定：学生全部素材/run/报告详情列表，写 audit `archive_viewed`，确认报告下载链接。

## 7. 测试与上线

- pytest 沿用第一阶段 fixture 模式。重点覆盖：session 幂等创建、revision/负责人 409 双文案、兴趣草稿校验全规则、supplement 钳制与保留键隔离、next-steps 字数与禁用模式正则、projects 证据逐字校验与批次指纹、handoff/confirm 幂等、报告 PDF 双检、聊天请求校验。
- 原版 `FIRST_TOUCH_V2_ENABLED` 开关不移植（SQLite 下 schema 随 `init_db` 一次就绪）。
- 上线：随 `init_db()` 幂等建表，无额外迁移步骤；红线文件零接触。
