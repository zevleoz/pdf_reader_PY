# Copilot 2.0 移植实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 first-touch 的 Copilot 2.0（七阶段会谈工作台 + 聊天中心）移植进凭远 Flask 平台，并以 "First Touch" 独立分区形态呈现。

**Architecture:** 在第一阶段已上线的资产上扩建——`growth_talk_store.py` 加 6 张表；新增 `growth_talk/copilot.py`（状态机与校验纯逻辑）、`growth_talk/copilot_report.py`（handoff/报告流）、`blueprints/copilot.py`（路由）；`templates/first_touch/` 五个 Jinja+Alpine 页面 + 管理端导航分组。LLM 全部非流式（隧道 100s 约束）。Y4 输入打通平台已有报告，不上传 Y4 文件。

**Tech Stack:** Flask 3 / SQLAlchemy 2 / SQLite / pytest。无新增依赖。

**Spec:** `docs/superpowers/specs/2026-10-23-copilot-v2-merge-design.md`（本计划的直接依据）；背景：`docs/superpowers/specs/2026-10-22-first-touch-merge-design.md` + `docs/superpowers/plans/2026-10-22-first-touch-merge.md`（第一阶段，已完成，其接口名直接被本计划消费）。

**源仓库（只读参考）：** `/Users/jefflau/projects/first-touch`。prompt 全文、校验正则、默认话术、页面文案逐字移植，以实现时读源文件为准。

## Global Constraints

- 第一阶段全部约束继续生效（见第一阶段计划的 Global Constraints：无 url_prefix、blueprint 内 create_app 注册、`growth_talk*/db` 禁止 import app/blueprints、CSRF 惯例、`os.environ`、中文文案逐字、测试不碰生产库）。
- **非流式**：原版 SSE 端点（report-prepare、两个 assistant）一律折叠为普通 JSON 响应；不移植 `partialAnswer` 增量 JSON 提取。
- **Y4 打通**：2.0 不提供 Y4 文件上传；校准输入 = 平台该学生最新已确认 Y4 报告（`reports.data_json` + 解读文本）。
- 路由路径沿用原版 `/api/v2/...` 与 `/api/students/<sid>/copilot/assistant`（浏览器自用，保持原样降低移植出错面）；页面路径用 `/first-touch/...` 前缀。
- 会话 API 错误文案逐字：`404 会谈不存在`、`409 会谈已更新，请保留草稿并刷新确认`、`409 本地负责人已变化，本次操作未保存`、`409 请确认兴趣评分差异`、`409 请先上传当前会议文字稿`、`409 报告已确认，项目推荐只读`、`409 会议资料或兴趣已变化，请重新生成项目清单`、`409 报告内容已变化，请重新预览再下载`、`400 问题不能为空且不能超过 1000 字`、`400 聊天上下文格式无效`。
- 阶段定义逐字：`PHASES = ["会议准备", "目标说明", "Y4 结果解读", "兴趣事项", "总结与下一步", "会后补充", "报告确认"]`（0–6，自由跳转）。顾问阶段（显示浮动聊天）：`phase in (0, 5, 6)`。
- 报告相关表（`gt_runs/gt_interest_evidence/gt_quadrants/gt_suggestions/gt_reports`）与第一阶段共用，不得新建平行表。

## Review Focus

1. **confirm 重复点击/重试**：同一 run 已有 CONFIRMED 报告时必须 200 幂等返回，不能因 `UNIQUE(student_id, version)` 竞争产生 500 — Task 3 测试钉住。
2. **兴趣 label 改名后 handoff**：handoff 按 label 匹配既有 evidence 行，改名会产生重复行——只允许同 session 内改名安全，测试钉住匹配行为 — Task 3。
3. **超长上下文**：会谈记录 >30000 字时聊天上下文必须截断而非原样发给 LLM — Task 4 测试钉住。
4. **无 Y4 报告的学生**：校准生成必须返回明确错误而非空校准入库 — Task 2 测试钉住。
5. **phase PATCH 覆盖保留键**：`supplementAnalysis` 合并时 `projectRecommendations` 等保留键被客户端提交时必须忽略/拒绝，不能覆盖专属端点的数据 — Task 2 测试钉住。

---

### Task 1: Copilot 数据模型与 store 扩展

**Files:**
- Modify: `growth_talk_store.py`
- Test: `test_copilot_store.py`

**Interfaces:**
- Consumes: 第一阶段 `growth_talk_store.py`（`Base`/`engine`/Session 模式、`RevisionConflict`、`write_audit`）。
- Produces（Task 2–4 消费）：
  - ORM：`CopilotSession, CopilotPhaseEvent, CopilotCareerCalibration, CopilotInterestNote, CopilotTranscriptSupplement, CopilotChatMessage`（表结构按 spec §2，含全部索引与 UNIQUE）
  - `create_session(student_id: int, advisor_id: int, entry_mode: str = "guided", meeting_at: str | None = None) -> tuple[dict, bool]`：幂等——该 (student_id, advisor_id) 已存在 session（ACTIVE/REVIEW/COMPLETED 任一状态）即返回 `(existing, True)`；否则按 spec §2 默认 script 创建（phase: guided→0 / direct→5）返回 `(session, False)`；写 phase event `created`
  - `get_session(session_id: int) -> dict | None`（含 `calibration/notes/supplements/events` 子键，supplements created_at 降序、events 取 30 条）；`list_sessions(student_id: int, advisor_id: int | None) -> list[dict]`（≤30，updated_at 降序；advisor_id None=admin 看全部）
  - `bump_session_revision(session_id: int, expected_revision: int, actor_id: int, action: str, phase: int | None = None) -> int`：revision 不匹配 → `RevisionConflict("会谈已更新，请保留草稿并刷新确认")`；成功 revision+1 + 写 `copilot_phase_events`
  - `update_session_fields(session_id: int, **fields) -> None`（限白名单：`phase, status, script, interests, meeting_source_id, y4_report_id, run_id, completed_at, meeting_at`）
  - `upsert_calibration(session_id: int, career_interests: str, ability_tendencies: str, value_preferences: str, notes: str) -> None`
  - `replace_session_interests(session_id: int, interests: list[dict]) -> None`：写 `interests` JSON + 重建 `copilot_interest_notes`
  - `create_supplement(session_id: int, source_id: int) -> dict`；`latest_supplement(session_id: int) -> dict | None`；`save_supplement_analysis(supplement_id: int, analysis: dict, status: str) -> None`
  - 聊天：`create_chat(student_id: int, advisor_id: int, session_id: int | None = None) -> str`（返回 uuid chat_id；该学生已有 20 个 chat 时删最旧）；`add_chat_turn(chat_id: str, question: str, answer: dict | None, status: str) -> None`（answer 存 evidence JSON + content；单 chat 超 20 轮拒绝新增并抛 `ValueError("对话轮数已达上限")`）；`list_chats(student_id: int) -> list[dict]`；`get_chat(chat_id: str) -> dict`（含 turns）
- 状态枚举逐字：session `ACTIVE/REVIEW/COMPLETED`；supplement `PENDING_REVIEW/REVIEWED`。

- [ ] **Step 1: 写失败测试** `test_copilot_store.py`（fixture 沿用 `test_growth_talk_store.py` 模式）

```python
def test_create_session_idempotent_per_student_advisor(qdb):
    s1, created1 = create_session(sid, aid, "guided")
    s2, created2 = create_session(sid, aid, "direct")
    assert created1 is True and created2 is False and s1["id"] == s2["id"]
    assert s1["phase"] == 0
    other, created3 = create_session(sid, other_advisor_id)
    assert created3 is True and other["id"] != s1["id"]

def test_direct_entry_starts_at_phase_5(qdb): ...

def test_bump_session_revision_conflict_message(qdb):
    with pytest.raises(RevisionConflict, match="会谈已更新，请保留草稿并刷新确认"):
        bump_session_revision(sid_session, 999, actor, "phase_saved")

def test_replace_interests_rebuilds_notes(qdb):
    replace_session_interests(sid_session, [{"id": "i1", "label": "篮球", "note": "每周训练", ...}])
    session = get_session(sid_session)
    assert session["notes"] == [{"interest_id": "i1", "note": "每周训练", ...}]

def test_chat_caps(qdb):
    # 第 21 个 chat 创建后最旧被删；单 chat 第 21 轮抛 ValueError
```

- [ ] **Step 2: 跑测试确认失败** → 函数不存在
- [ ] **Step 3: 实现**。默认话术五段逐字从源 `app/api/v2/students/[id]/copilot/sessions/route.ts` 复制。
- [ ] **Step 4-5: 通过 + 回归**（含第一阶段测试全绿）
- [ ] **Step 6: Commit** `git commit -m "feat(copilot): session/phase-event/calibration/supplement/chat store"`

---

### Task 2: 状态机与校验纯逻辑 `growth_talk/copilot.py`

**Files:**
- Create: `growth_talk/copilot.py`
- Test: `test_copilot_logic.py`

**Interfaces:**
- Consumes: Task 1 store、第一阶段 `analysis.call_model`。
- Produces（Task 3/4 消费）：
  - `validate_interest_drafts(items: list[dict]) -> list[dict]`：spec §2 InterestDraft 全规则（≤120 条、label ≤80 且大小写不敏感去重、topicType ∈ subject/interest/social、分数 0–3 整数或 None、note ≤2000、evidence ≤4000）；失败抛 `ValueError`（中文原因）
  - `validate_script_fields(script: dict) -> dict`：五段各 ≤3000、nextSummary ≤1400
  - `merge_supplement_analysis(existing: dict, patch: dict) -> dict`：保留键 `{"projectRecommendations","projectRecommendationHistory","newInterests","analysisVersion","interestReview","interestBindings"}` 不被 patch 覆盖
  - `validate_interest_review_save(interests, interest_review) -> None`：评分差异未确认 → `ValueError("请确认兴趣评分差异")`（逻辑移植自源 `copilot-v2.ts`）
  - `generate_career_calibration(y4_payload: dict, interpretation: str) -> dict`：DeepSeek 一次调用，输入 = 平台 Y4 报告 124 指标 + 解读（截断 30000 字），输出 `{careerInterests, abilityTendencies, valuePreferences}` 各单行 ≤150 字；y4_payload 为空 → `ValueError("该学生还没有已确认的 Y4 报告，请先生成 Y4 报告")`。prompt 改写自 `lib/career-profile.ts`（输入从"原始文件文本"改为"Y4 结构化指标 JSON + 解读"）
  - `run_supplement_analysis(session_id: int) -> dict`：校验最新 supplement 的 source == 当前 meeting_source（否则 `RevisionConflict("请先上传当前会议文字稿")`）；LLM prompt 移植自源 supplement 路由；钳制（newInterests ≤30、label 括号前 ≤24、evidence ≤500、scoreConflicts/questions 各 ≤20 条 ≤500 字、y4Validation ≤3×≤100 字超限抛 502 语义错误）；新 `analysisVersion = uuid4`；保留既有 recommendations；写 supplement `PENDING_REVIEW`；返回 analysis
  - `generate_next_steps(session_id: int) -> str`：prompt 移植 `buildNextStepsPrompt`；校验 20–1400 字且拒绝正则 `[（(](?:活动|项目|课程|学校|专业|职业)[：:]`；写入 `script.nextSummary`
  - `generate_projects(session_id: int) -> dict`（RecommendationBatch）：守卫（session 非 COMPLETED 且无 CONFIRMED 报告 → `RevisionConflict("报告已确认，项目推荐只读")`；supplement 对应当前 source；newInterests 已分析且 ≥1 条兴趣）；LLM 2–5 条；`evidenceQuotes` 逐字是会谈原文子串，否则该条 `status="needs_evidence"`；`inputFingerprint = sha256({sourceId, interests, analysisVersion, newInterests, y4Validation})`；写入 `projectRecommendations` + append `projectRecommendationHistory`
  - `apply_project_edits(session_id: int, items: list[dict], actor: str) -> dict`：指纹不匹配 → `RevisionConflict("会议资料或兴趣已变化，请重新生成项目清单")`；`validateRecommendationEdits` 规则（条目不可删只能改 status、id 不可变、`student_review` 必须有 evidenceQuotes）移植自源；生成新批次（`reviewedAt/reviewedBy`）；`student_review` 条目同步进 `gt_suggestions`（`exploration_tags=["passion-project.v1", fitType]`、`growth_value` 固定文案 `通过这个方向验证自己的兴趣与探索方式，过程中可以调整或停止。`）
  - 象限辅助（纯函数）：`quadrant_tone(p, c) -> str`（双 ≥2→`strong`、p ≥2→`explore`、c ≥2→`capable`、余→`quiet`）；`three_level(v) -> str | None`（None→None、≥3→`高`、=2→`中`、≤1→`低`）

- [ ] **Step 1: 写失败测试**（LLM 打桩）

```python
def test_interest_drafts_reject_duplicate_label_case_insensitive(): ...
def test_merge_supplement_analysis_preserves_reserved_keys():
    existing = {"projectRecommendations": {"v": 1}, "newInterests": [1]}
    merged = merge_supplement_analysis(existing, {"projectRecommendations": {"v": 2}, "interestReview": {...}})
    assert merged["projectRecommendations"] == {"v": 1}

def test_calibration_requires_y4(qdb):
    with pytest.raises(ValueError, match="还没有已确认的 Y4 报告"):
        generate_career_calibration({}, "")

def test_next_steps_rejects_forbidden_pattern(monkeypatch, ...):
    # 打桩 call_model 返回 {"summary": "下一步（活动：xxx）..."} → ValueError

def test_projects_evidence_must_be_verbatim(monkeypatch, seeded_session):
    # 打桩返回 evidenceQuotes 不在原文中 → 该条 status == "needs_evidence"

def test_apply_project_edits_stale_fingerprint(seeded_session_with_batch):
    with pytest.raises(RevisionConflict, match="会议资料或兴趣已变化"):
        apply_project_edits(sid, tampered_items, "顾问")
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**（先读源 `lib/copilot-v2.ts`、`lib/copilot-interest-review.ts`、`lib/career-profile.ts` 及 projects/next-steps 相关 lib）
- [ ] **Step 4-5: 通过 + 回归**
- [ ] **Step 6: Commit** `git commit -m "feat(copilot): phase logic, validators, supplement/next-steps/projects analysis"`

---

### Task 3: Handoff 与报告流 `growth_talk/copilot_report.py`

**Files:**
- Create: `growth_talk/copilot_report.py`
- Test: `test_copilot_report.py`

**Interfaces:**
- Consumes: Task 1/2、第一阶段 `report_contract.build_report_preview / confirm_report / report_fingerprint`、`runs.apply_action`、`analysis.run_quadrant_analysis`、store。
- Produces（Task 4 消费）：
  - `handoff_report(session_id: int) -> dict`：按 spec §4 物化 gt_run（幂等：`script.reportInputFingerprint == sha256({sourceId, student{name,grade}, interests, summary})` 且 run 内容一致 → 直接返回既有 `{"runId", "revision"}`）；兴趣逐条转 `gt_interest_evidence`（CONFIRMED，evidence 拼接规则按 spec）；understanding summary 由 top-2 兴趣合成（移植 `meetingSummaryWithOverview`）；置 session `phase=6, status="REVIEW"`，指纹写回 script
  - `missing_report_fields(draft: dict) -> list[dict]`：必填 `grade/meeting/interests/逐兴趣评分/eligible-interests/projects-stale`，可选 `projects/y4/y4-validation`（规则移植 `copilot-report-shared.ts`）
  - `prepare_report(session_id: int, expected_revision: int) -> dict`：**非流式**——revision 校验 → 组 draft → 必填缺失 → `{"draft", "preview": None, "revision"}` → 否则 handoff → quadrant 缺失/STALE 时跑一次 `run_quadrant_analysis` → `build_report_preview(run_id)` → draft.calibration 回填 → `{"draft", "preview", "revision", "runId", "reportId"}`
  - `confirm_session_report(session_id: int, *, revision: int, fingerprint: str, suggestion_ids: list[str], confirmed_by: str) -> tuple[dict, int]`：该 run 已有 CONFIRMED 报告 → `(report, 200)`；否则 `confirm_report(...)` + session revision 守卫 + 置 `COMPLETED/completedAt` → `(report, 201)`
  - `assert_report_pdf_fresh(session_id: int, revision: int, fingerprint: str) -> None`：不匹配 → `RevisionConflict("报告内容已变化，请重新预览再下载")`

- [ ] **Step 1: 写失败测试**

```python
def test_handoff_idempotent(qdb, seeded_session_with_interests):
    r1 = handoff_report(sid)
    r2 = handoff_report(sid)
    assert r1["runId"] == r2["runId"]
    # gt_interest_evidence 行数不变

def test_handoff_materializes_confirmed_evidence(qdb, seeded_session):
    handoff_report(sid)
    full = growth_talk_store.get_run_full(run_id)
    assert all(i["status"] == "CONFIRMED" for i in full["interests"])
    assert "顾问 Note：" in full["interests"][0]["evidence"] or full["interests"][0]["evidence"] == "顾问会议评分，待核对证据。"

def test_prepare_returns_draft_only_when_required_missing(qdb, session_no_grade):
    out = prepare_report(sid, rev)
    assert out["preview"] is None and any(m["key"] == "grade" for m in out["draft"]["missing"])

def test_confirm_idempotent(qdb, prepared_session):
    r1, s1 = confirm_session_report(sid, ...)
    r2, s2 = confirm_session_report(sid, ...)
    assert (s1, s2) == (201, 200) and r1["id"] == r2["id"]
    assert get_session(sid)["status"] == "COMPLETED"
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**（源参考：`lib/copilot-report.ts`、`lib/copilot-report-shared.ts`）
- [ ] **Step 4-5: 通过 + 回归**
- [ ] **Step 6: Commit** `git commit -m "feat(copilot): handoff to gt run and report prepare/confirm flow"`

---

### Task 4: 路由 `blueprints/copilot.py`（含聊天）

**Files:**
- Create: `blueprints/copilot.py`
- Modify: `app.py`（注册）
- Test: `test_copilot_routes.py`

**Interfaces:**
- Consumes: Task 1–3 全部；第一阶段 `app_utils` 鉴权、`advisor_name` 隔离惯例。
- Produces（Task 5 页面消费这些 JSON 形状）：
  - `GET /api/v2/students/<int:sid>/copilot/sessions` → `{sessions}`；`POST` 同路径 `{entryMode?, meetingAt?}` → 201 `{session}` 或 200 `{session, existing: true}`
  - `GET /api/v2/copilot/sessions/<int:id>` → `{session（含 calibration/notes/supplements/events）, entryMode, student, reportId, hasGeneratedReport, sourceFileNames, projectsCurrent}`
  - `PATCH /api/v2/copilot/sessions/<int:id>/phase` `{phase 0-6, revision, interests?, interestReview?, supplementAnalysis?, script?, entryMode?, meetingAt?}` → `{revision, result: session + savedSupplement?}`；phase 5/6 带 interests 时跑 `validate_interest_review_save`；phase 6 → `status="REVIEW"`；event `phase_saved`
  - `PATCH .../career-calibration` `{revision, 四字段}` → upsert + event `calibration_saved`
  - `PATCH .../interest-draft` `{revision, interests}` → `validate_interest_drafts` → `replace_session_interests` + 重算最新 supplement `interestBindings` + event `interests_saved`
  - `POST .../sources`（multipart：`file`, `kind="MEETING"`, `revision`）→ 第一阶段 `extract_upload` → `create_source` → 更新 `meeting_source_id` + 建 `PENDING_REVIEW` supplement → 201 `{revision, result: {sourceId, fileName}}`；扩展名白名单 `.pdf/.docx/.txt/.md`
  - `POST .../y4-calibrate` `{revision}`：读学生最新 CONFIRMED Y4 报告 → `generate_career_calibration` → `upsert_calibration` → `{revision, analysis}`；无报告 → `422 {"error": "该学生还没有已确认的 Y4 报告，请先生成 Y4 报告"}`
  - `POST .../supplement` `{revision}` → `run_supplement_analysis` → `{revision, analysis}`
  - `POST .../next-steps` `{revision}` → `{revision, result: {summary}}`
  - `POST .../projects` `{revision}` → `{revision, batch}`；`PATCH .../projects` `{revision, items}` → `{revision, batch}`
  - `POST .../report-prepare` `{revision}` → `prepare_report` 的 JSON（非流式）
  - `POST .../report-preview` → 需 `run_id`（否则 `409 请先将会谈资料送入报告审核`）→ 第一阶段 preview
  - `POST .../report-confirm` `{revision, fingerprint, reviewedMeeting: true, reviewedNarrative: true, suggestionIds}` → 201/200 `{report: {id, version, confirmedAt}}`
  - `GET .../report-pdf?revision=&fingerprint=` → 前后双检（`assert_report_pdf_fresh`）→ 草稿 PDF；`Content-Disposition` 含 `filename*=UTF-8''{姓名}-会谈报告-草稿.pdf`；`Cache-Control: no-store`、`X-Content-Type-Options: nosniff`
  - 聊天：`POST /api/students/<int:sid>/copilot/assistant` 与 `POST /api/v2/copilot/sessions/<int:id>/assistant`：请求校验（question 1–1000 / history ≤6 轮逐字文案）；上下文装配（会议记录与 Y4 各截断 30000 字；无 session 时回退到最新 MEETING source + gt run 上下文）；`call_model` 非流式；答案校验（answer 1–4000、evidence ≤8）；写 `copilot_chat_messages`（`create_chat`/`add_chat_turn`，`chat_id` 由前端传入或新建）；返回 `{"answer": "...", "evidence": [...], "chatId": "..."}`
  - `GET /api/students/<int:sid>/copilot/chats` → `{chats}`；`GET /api/copilot/chats/<chat_id>` → `{chat}`

- 鉴权：全部 `@login_required` + advisor 隔离（非 admin 且非本人学生 → `404 {"error": "会谈不存在"}`/`学生不存在或未分配至你的本地工作区`）。
- LLM 耗时端点（supplement/next-steps/projects/report-prepare/assistant）一律走第一阶段 `growth_talk/jobs.py` 的子进程+状态文件模式，路由只负责投递与轮询状态返回；同步等待禁止超过隧道超时。

- [ ] **Step 1: 写失败测试**（沿用第一阶段路由测试模式；LLM 打桩）

```python
def test_create_session_idempotent_200(client): ...      # 重复 POST → 200 existing
def test_phase_patch_revision_conflict_409(client): ...  # 文案断言
def test_other_advisor_gets_404(client): ...
def test_assistant_question_validation(client):
    r = post_assistant({"question": ""})
    assert r.status_code == 400 and "问题不能为空且不能超过 1000 字" in r.get_json()["error"]
def test_assistant_history_limit(client):
    r = post_assistant({"question": "q", "history": [{"question": "x", "answer": "y"}] * 7})
    assert r.status_code == 400 and "聊天上下文格式无效" in r.get_json()["error"]
def test_chat_persisted(client): ...                     # 回答后 get_chat 有 turns
def test_assistant_context_truncated(client, monkeypatch):
    # 构造 40000 字会谈记录；打桩 call_model 捕获 prompt → 断言会议记录部分 ≤30000 字
def test_report_pdf_double_fence(client): ...            # 过期 fingerprint → 409
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现 + 注册**
- [ ] **Step 4-5: 通过 + 全量回归**
- [ ] **Step 6: Commit** `git commit -m "feat(copilot): v2 session routes, phase endpoints, non-streaming assistant chat"`

---

### Task 5: 工作台页面 `templates/first_touch/workspace.html`

**Files:**
- Create: `templates/first_touch/workspace.html`
- Modify: `blueprints/copilot.py`（加页面路由 `GET /first-touch/students/<int:sid>`）
- Test: 路由 200 冒烟 + 人工走查

**Interfaces:**
- Consumes: Task 4 全部端点；`layouts/admin_v2.html` blocks、`v2Toast`、CSRF fetch wrapper。
- 页面结构：`x-data='ftWorkspace({{ ctx | tojson }})'`；顶部阶段导航条（7 按钮自由跳转，当前 phase 高亮）；每阶段一个 Alpine 子表单：
  - 阶段 0：Y4 校准卡（「从 Y4 报告生成校准」按钮 → 轮询任务 → 三字段可编辑保存）+ 五段话术编辑（每段 ≤3000 字计数器）
  - 阶段 1/2：只读渲染
  - 阶段 3：兴趣草稿表格（行内编辑 label/topicType/双分数下拉 0–3/note/evidence；增删行；「保存兴趣」PATCH interest-draft）+ QuadrantBoard 4×4 网格（`quadrant_tone` 着色）
  - 阶段 4：「生成下一步摘要」（loading 轮询）+ ThreeLevelQuadrantBoard 3×3
  - 阶段 5：会谈记录上传（复用分片上传组件）→「分析补充材料」→ 候选审核列表（keep/apply/edit/exclude 按钮）→「生成项目推荐」→ 推荐卡编辑
  - 阶段 6：「准备报告」→ missing 清单展示（必填红标）→ preview 摘要 → 两个确认 checkbox（reviewedMeeting/reviewedNarrative）→「确认报告」→ 下载链接
  - 浮动聊天：`phase in (0,5,6)` 时右下角 launcher + 面板（调 assistant 端点，展示 evidence 引用）
- 脏检查：未保存改动时 `beforeunload` 提示；所有 PATCH 携带当前 `revision`，409 时 `v2Toast` + 重拉 session。

- [ ] **Step 1: 实现页面 + 路由**
- [ ] **Step 2: 冒烟测试**（登录态 test_client GET 200，页面含 `ftWorkspace`）
- [ ] **Step 3: 人工走查清单**：guided 全流程 0→6 各阶段保存/跳转/刷新恢复；direct 入口直达 5；浮动聊天仅在 0/5/6 出现
- [ ] **Step 4: Commit** `git commit -m "feat(copilot): seven-phase workspace page"`

---

### Task 6: 分区外壳（首页 / 聊天中心 / 指南 / 归档 / 导航）

**Files:**
- Create: `templates/first_touch/home.html`、`chat_picker.html`、`chat.html`、`guide.html`、`archive.html`
- Modify: `blueprints/copilot.py`（页面路由）、`app_utils.py`（`register_admin_context` 的 `nav_groups` 加 "First Touch" 分组）
- Modify: `templates/student_360.html`（Growth Talk 标签页加「进入会谈工作台」链接 → `/first-touch/students/<id>`）
- Test: `test_first_touch_pages.py`

**Interfaces:**
- Consumes: Task 4 端点 + 第一阶段学生/导入端点。
- 页面契约：
  - `GET /first-touch`：当前顾问学生卡片（`list_sessions` 的 phase 徽标 + gt 计数）；「手动添加学生」弹层（`POST` 第一阶段学生创建端点 + 前端生成 `requestId` UUID 幂等）；「从 Yuguo 导入」复用第一阶段明细弹层组件
  - `GET /first-touch/copilot`：学生选择器（该顾问有 session 的学生）
  - `GET /first-touch/copilot/<int:sid>?chat=<chat_id>`：全页聊天（对话列表侧栏 + 消息流 + 输入框；evidence 折叠展示）
  - `GET /first-touch/guide`：静态页，文案逐字复制 `app/guide/page.tsx`
  - `GET /first-touch/archive/<int:sid>`：`@role_required('admin')`；全部 sources/runs（含子实体）/reports 的 `<details>` 列表；写 audit `archive_viewed`；报告下载链接复用第一阶段下载路由
- 导航：`nav_groups` 新增 `{"key": "first_touch", "label": "First Touch", "items": [工作台, 聊天中心, 使用指南]}`（归档无导航项，从学生 360 进）。

- [ ] **Step 1: 写失败测试**（各页面登录态 200、archive 非 admin 403、audit 写入断言）
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现五个页面 + 导航**
- [ ] **Step 4-5: 通过 + 回归**
- [ ] **Step 6: Commit** `git commit -m "feat(first-touch): section shell — home, chat center, guide, archive, nav"`

---

### Task 7: 收尾

**Files:**
- Modify: `PRODUCT.md`（Capabilities 加 Copilot 2.0 一段）、`docs/deployment_env.md`（如无新变量则注明）
- Test: 无新测试

- [ ] **Step 1: 文档更新**
- [ ] **Step 2: 全量回归** `python -m pytest -q`（含第一阶段全部测试）
- [ ] **Step 3: Commit** `git commit -m "docs: copilot v2 capabilities"`

---

## 任务依赖图

```
T1 store ──→ T2 logic ──→ T3 report flow ──→ T4 routes ──→ T5 workspace 页
                                                    └──────→ T6 外壳页 ──→ T7 收尾
```

严格串行（每任务消费上一任务接口）。T5/T6 可在 T4 完成后并行（不同 implementer 时，T6 只消费 T4 的会话/聊天端点）。
