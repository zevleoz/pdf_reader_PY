# Copilot 2.0 差距修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除 Copilot 2.0 移植版与原版 first-touch 之间的 18 项功能缺失与 12 项降级，达到用户可感知的对等。

**Architecture:** 全部改动落在既有结构上：`templates/first_touch/`（UI 保真）、`blueprints/copilot.py`（少量端点补充）、`growth_talk/copilot*.py`（校验与 payload 修正）。不引入新依赖、不改数据表结构（聊天删除走软删/硬删均可，硬删即可）。

**Tech Stack:** Flask / Jinja / Alpine（CDN）/ pytest。

**Spec:** `docs/superpowers/specs/2026-10-23-copilot-v2-gap-analysis.md`（逐项差距与 file:line 证据，**执行时必读**）；背景：`2026-10-23-copilot-v2-merge-design.md`、第一阶段 spec/plan。

**源仓库（只读参考）：** `/Users/jefflau/projects/first-touch`。UI 文案、状态标签、交互细节以实现时读原版组件为准。

## Global Constraints

- 第一、二阶段计划的 Global Constraints 全部继续生效（非流式、中文文案逐字、revision 守卫、CSRF 惯例、测试不碰生产库等）。
- 本计划的所有差距编号（M1–M18、P1–P12）以差距分析文档为准；每个任务开头列出它关闭的编号。
- UI 文案逐字对齐原版组件（如 `待审核/需补证据/顾问保留/排除/推荐给学生`、`采用会议建议`、`保留已确认评分`、`回答仅作为顾问审核草稿`、`已 finalize · 视为已推送`）。
- 原版刻意不做的仍不做：SSE 流式、localStorage 聊天、Y4 文件上传、HomeDashboard 的未使用功能。
- 模板测试用登录态 test_client GET 200 + 关键标记断言；纯前端交互用人工走查清单兜底。

## Review Focus

1. **null 分数全链路**：UI 允许"待评"（null）→ 后端 PATCH 保留 null → 象限板排除未评分项 → 报告缺失清单列出——任何一环把 null 变成 1 都是数据失真。Task 3 测试钉住。
2. **3×3 分档映射**：`0–1 低 / 2 中 / 3 高`，映射写反会误导顾问对报告的理解。Task 3 测试钉住。
3. **meetingAt 时区**：存储 ISO，展示一律 `Asia/Shanghai` 长日期格式，UTC 直出会差 8 小时。Task 1 测试钉住。
4. **手动新增项目方案的 id**：前端新建条目必须发 `recommendationId: null` 由后端分配 uuid，前端自造 id 会撞指纹校验。Task 5 测试钉住。
5. **删除对话后的深链**：`?chat=<已删 id>` 必须落到该学生最新对话或空态，不能白屏。Task 7 测试钉住。

---

### Task 1: 入口选择屏 + 会谈时间（M1、M2、M3、M4）

**Files:**
- Modify: `templates/first_touch/workspace.html`、`blueprints/copilot.py`、`growth_talk/copilot_report.py`
- Test: `test_copilot_gapfixes.py`（新建，本计划所有任务共用此文件追加）

**Interfaces:**
- Consumes: 既有 `POST /api/v2/students/<sid>/copilot/sessions`（支持 `entryMode/meetingAt`）、session GET 的 `meetingAt`。
- Produces:
  - `GET /first-touch/students/<sid>` 行为变更：**无 session 时不再自动创建**，渲染入口选择屏（两张卡片，文案逐字自 `CopilotWorkspace.tsx:222` 的 `v2-entry-choice` 区块）；点卡片才 POST 创建。`?entry=direct` 预选 direct 卡片；首页工作台卡片加"直接上传会后资料"链接（`?entry=direct`）
  - `MeetingTimePicker`（Alpine 组件）：日期 input + 15 分钟槽位 select（00:00–23:45 共 96 项）；入口屏和会话条各一处；改动标记"时间待统一保存"，随下一次 phase PATCH 的 `meetingAt` 提交
  - preview payload 与草稿 PDF 含 `meetingAt`，渲染为 `访谈日期：{zh-CN 长日期} {短时间}`（Asia/Shanghai）；`growth_talk/copilot_report.py` 的 draft 组装与 `blueprints/copilot.py:677-697` 的 PDF payload 同步补上

- [ ] **Step 1: 写失败测试**

```python
def test_workspace_get_does_not_autocreate_session(client, student_without_session):
    r = client.get(f"/first-touch/students/{sid}")
    assert r.status_code == 200 and b"v2-entry-choice" in r.data  # 或对应标记
    assert list_sessions(sid) == []

def test_meeting_at_in_preview_payload(client, seeded_session):
    # PATCH meetingAt → report-prepare → draft["meetingAt"] == 该值
    # 且渲染文本含 "访谈日期："（上海时区：UTC 2026-01-01T04:00:00Z → 显示 12:00）
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**（入口屏结构逐字参考原版 `CopilotWorkspace.tsx:222-245`）
- [ ] **Step 4-5: 通过 + 回归**
- [ ] **Step 6: 人工走查**：无 session 学生 → 入口屏两卡片；guided/direct 分别落到 phase 0/5；时间选择器改动后出现"时间待统一保存"，保存后消失
- [ ] **Step 7: Commit** `git commit -m "fix(copilot): entry-mode choice screen, meeting time picker, meetingAt in report"`

---

### Task 2: 阶段 5 审核保真（M5、M6）

**Files:**
- Modify: `templates/first_touch/workspace.html`、`blueprints/copilot.py`（如需补端点）
- Test: `test_copilot_gapfixes.py`

**Interfaces:**
- Consumes: 既有 supplement analysis（`newInterests/scoreConflicts/y4Validation/questions`）、phase PATCH 的 `supplementAnalysis/interestReview` 合并。
- Produces:
  - 候选卡完整编辑：改名 input、分类 select（subject/interest/social）、喜欢/擅长 0–3 select、逐条证据展示
  - 分数冲突解决 UI：逐条冲突显示"采用会议建议 / 保留已确认评分"按钮 + 未解决计数；有未解决冲突时 phase PATCH 按原样触发 `409 请确认兴趣评分差异`（后端已有，前端需展示该 toast 并滚动到冲突区）
  - "会议对 Y4 的验证"编辑器：AI 生成列表 + 逐条编辑 + 重新生成按钮；保存进 supplement analysis 的 `y4Validation`（≤3 条 × ≤100 字，前端计数）

- [ ] **Step 1: 写失败测试**

```python
def test_session_get_exposes_score_conflicts(client, session_with_conflicts):
    data = client.get(f"/api/v2/copilot/sessions/{sid}").get_json()
    sup = data["session"]["supplements"][0]
    assert sup["analysis"]["scoreConflicts"]  # 非空透出给前端

def test_y4_validation_saved_via_phase_patch(client, ...):
    # PATCH supplementAnalysis.y4Validation 两条 → GET 回读一致；第 4 条被钳制
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**（交互逐字参考 `CopilotWorkspace.tsx:189-200, 229-230`）
- [ ] **Step 4-5: 通过 + 回归**
- [ ] **Step 6: 人工走查**：候选改名/改分→保存→刷新保持；制造分数冲突→两个解决按钮→未解决计数归零才能进阶段 6
- [ ] **Step 7: Commit** `git commit -m "fix(copilot): supplement candidate editing, score-conflict resolution, y4 validation editor"`

---

### Task 3: 阶段 3 分数保真（M13、P1、P2、P3）

**Files:**
- Modify: `templates/first_touch/workspace.html`
- Test: `test_copilot_gapfixes.py`

**Interfaces:**
- 分数下拉必须有空选项 `待评`（value 空 → 提交 null）；**删除所有 null→1 的强制转换**（`workspace.html:702-705, 811-815`）；象限板只渲染双分数非 null 的项；报告缺失清单把未评分兴趣列为必填（后端已有，验证其出现）。
- 4×4 板补轴标签 `擅长程度 ↑` / `喜欢程度 →` 与图例 `横轴：喜欢 0–3 / 纵轴：擅长 0–3` + "N 项已评分"计数。
- 3×3 板映射修正为 `v===null→无 / v>=3→高 / v===2→中 / 其余(0–1)→低`，标签逐字 `喜欢高（3）/喜欢中（2）/喜欢低（0–1）` 等，补图例与计数。
- 兴趣列表改分类分组（subject/interest/social 三组可折叠，组头计数 + 组内"新增"按钮），参考 `CopilotWorkspace.tsx:227`。

- [ ] **Step 1: 写失败测试**

```python
def test_workspace_page_has_pending_score_option(client, seeded_session):
    html = client.get(f"/first-touch/students/{sid}").data.decode()
    assert "待评" in html
    assert "?? 1" not in html and "|| 1" not in html  # null 强转模式已移除

def test_three_level_mapping_labels(client, ...):
    html = ...
    assert "喜欢高（3）" in html and "喜欢低（0–1）" in html
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**。JS 映射函数逐字对齐 `ThreeLevelQuadrantBoard.tsx:11-14`
- [ ] **Step 4-5: 通过 + 回归**
- [ ] **Step 6: 人工走查**：新增兴趣默认"待评"→不进象限板→报告缺失清单出现该项；补分后上板；3×3 板 0 分项落入"低"行
- [ ] **Step 7: Commit** `git commit -m "fix(copilot): nullable interest scores, correct three-level bands, quadrant axes/legend, grouped interest list"`

---

### Task 4: 报告阶段完整化（M8、P4、P5）

**Files:**
- Modify: `templates/first_touch/workspace.html`
- Test: `test_copilot_gapfixes.py`

**Interfaces:**
- 进入阶段 6 自动调 `report-prepare`（带 4 步指示器：check → analyze → assemble → 完成；非流式下以任务轮询进度近似）；失败显示页内错误面板 + `重试` 按钮（不只 toast）。
- 缺失清单分必填/可选两区，必填红色 + 说明文案；每条必填带修复导航（`补充兴趣评分`→跳阶段 3、`返回补充资料`→跳阶段 5，逐字自 `CopilotReport.tsx:132`）。
- 脏检查补全（P6）：项目推荐编辑中（projectEditing）阻断阶段跳转；已打开已确认报告时再改动显示警告 `已打开已确认报告；未保存修改仍保留`（逐字自 `CopilotWorkspace.tsx:70,92-116`）。
- preview 渲染完整草稿"纸面"：会议总结、兴趣分型板（复用阶段 3 网格组件）、Y4 画像三卡、y4Validation 列表、项目推荐清单各节（结构对齐 `CopilotReport.tsx:16-46`）。
- 确认成功后页内切换为"已确认报告"视图：版本号、确认时间、确认人、PDF/JSON 下载按钮（复用一阶段下载路由），不再只有 toast。
- 移除 preview 区的裸 fingerprint 显示（PORT-ONLY 冗余）。

- [ ] **Step 1: 写失败测试**（页面含分区标记；确认后视图标记）

```python
def test_workspace_has_report_missing_sections(client, ...):
    assert "必填" in html and "可选" in html

def test_workspace_has_confirmed_report_view(client, ...):
    assert "已确认报告" in html  # 视图容器存在
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**
- [ ] **Step 4-5: 通过 + 回归**
- [ ] **Step 6: 人工走查**：缺年级学生进入阶段 6 → 自动 prepare → 必填区红色"年级"→ 点修复按钮跳对应阶段；补齐后确认 → 页内出现下载按钮
- [ ] **Step 7: Commit** `git commit -m "fix(copilot): full report draft view, auto-prepare, missing-field navigation, post-confirm downloads"`

---

### Task 5: 项目推荐卡（M7）

**Files:**
- Modify: `templates/first_touch/workspace.html`、`growth_talk/copilot.py`（`apply_project_edits` 接受新条目）
- Test: `test_copilot_gapfixes.py`

**Interfaces:**
- 状态码 → 中文标签映射逐字：`draft→待审核`、`needs_evidence→需补证据`、`advisor_kept→顾问保留`、`advisor_excluded→排除`、`student_review→推荐给学生`。
- 卡片完整字段：证据引用列表（`evidenceQuotes`）、fitType 中文名（`observation_research→观察研究` 等，逐字自原版映射）、兴趣引用勾选、顾问版本视图。
- "新增方案"按钮 → 空卡编辑；`recommendationId` 送 `null`；后端 `apply_project_edits` 遇 null id 分配 `str(uuid4())` 并计入新批次（其余校验不变）。
- 粘贴块导入：原版支持把 JSON 块粘贴导入（`ProjectRecommendationList.tsx`），如实现成本高可降级为"新增方案"手工填写——**允许降级，需在本任务 commit message 注明**。

- [ ] **Step 1: 写失败测试**

```python
def test_apply_project_edits_accepts_new_item(qdb, session_with_batch):
    items = existing_items + [{"recommendationId": None, "title": "新方案", ...}]
    batch = apply_project_edits(sid, items, "顾问")
    new_item = [i for i in batch["items"] if i["title"] == "新方案"][0]
    assert new_item["recommendationId"]  # 后端已分配 uuid
    assert batch["version"] == old_version + 1
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**
- [ ] **Step 4-5: 通过 + 回归**
- [ ] **Step 6: Commit** `git commit -m "fix(copilot): project card fidelity — zh status labels, evidence quotes, manual add"`

---

### Task 6: 阶段 2/4 内容（M14、M15、P7、P10）

**Files:**
- Modify: `templates/first_touch/workspace.html`
- Test: `test_copilot_gapfixes.py`

**Interfaces:**
- 阶段 1 只显示 `goal + opening`（移除 interpretation）；阶段 1/2 改用演示版式（大字号居中，参考原版 `v2-present` 结构）。
- 阶段 2 增加 Y4 画像三卡（职业兴趣/能力倾向/价值偏好 + 校准 note），数据来自 session calibration。
- 阶段 4：进入时若 `script.nextSummary` 为空自动调 `next-steps`；摘要行内可编辑（随 phase PATCH 保存，≤1400 字计数）；顶部已评分兴趣 chips 行。
- 阶段 0 校准四字段各加 AI 来源徽标与逐字段"重新生成"（整体重新生成后覆盖，逐字段=重新生成后仅替换该字段）。

- [ ] **Step 1: 写失败测试**（页面标记断言：阶段 1 不含 interpretation 容器、阶段 2 含三卡容器、阶段 4 含编辑 textarea）
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**
- [ ] **Step 4-5: 通过 + 回归**
- [ ] **Step 6: Commit** `git commit -m "fix(copilot): phase 1/2 presentation mode, y4 cards, editable auto nextSummary, per-field AI badges"`

---

### Task 7: 聊天中心与浮动聊天（M9、M10、M11、M12）

**Files:**
- Modify: `templates/first_touch/chat.html`、`chat_picker.html`、`workspace.html`（浮动聊天）、`blueprints/copilot.py`、`growth_talk_store.py`
- Test: `test_copilot_gapfixes.py`

**Interfaces:**
- 新端点 `DELETE /api/copilot/chats/<chat_id>`（session 鉴权 + advisor 隔离；硬删该 chat 的全部 `copilot_chat_messages` 行）→ `{"ok": true}`；store 加 `delete_chat(chat_id: str) -> None`。
- 聊天中心：对话侧栏支持**删除**（确认弹层）；"开始聊天"新对话按钮；回答格式化渲染（`##`/`-`/`*1.*`/粗体 的最小渲染器，用 `<pre>` 换行 + CSS 即可，禁止 `x-html` 直接注入未转义 HTML）；发送中显示"停止"按钮（`AbortController` 中断 fetch，中断后轮记为 `stopped`）；达 20 轮显示"已达 20 轮，请开始新对话"并禁用输入；学生快速切换下拉；副标题 `回答仅作为顾问审核草稿`。
- 选择器：顶部搜索框（按姓名过滤）。
- 浮动聊天：历史列表（点击载入该 chat）、新对话、"展开为全页"链接（`/first-touch/copilot/<sid>?chat=<id>`）、同样的停止按钮与格式化渲染。
- 删除后深链处理：`?chat=<不存在>` → 落到该学生最新对话，无对话则空态 + "开始聊天"按钮。

- [ ] **Step 1: 写失败测试**

```python
def test_delete_chat(client, seeded_chat):
    r = client.delete(f"/api/copilot/chats/{chat_id}")
    assert r.status_code == 200
    assert get_chat(chat_id) is None

def test_delete_chat_other_advisor_404(client, ...): ...

def test_chat_page_fallback_on_deleted_deep_link(client, ...):
    # GET /first-touch/copilot/<sid>?chat=<deleted> → 200 且不包含已删 chat_id
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**
- [ ] **Step 4-5: 通过 + 回归**
- [ ] **Step 6: 人工走查**：格式化回答渲染、停止按钮中断、20 轮上限、删除后深链回退、浮动聊天三入口
- [ ] **Step 7: Commit** `git commit -m "fix(copilot): chat center delete/format/stop/cap, picker search, floating chat history"`

---

### Task 8: 首页与归档收尾（M16、M17、M18、P8、P9）

**Files:**
- Modify: `templates/first_touch/home.html`、`archive.html`、`blueprints/copilot.py`
- Test: `test_copilot_gapfixes.py`

**Interfaces:**
- 手动添加弹层加`联系电话`字段；后端学生创建端点接受 `phone`（可空）。
- 创建成功显示提示（学生姓名）再跳工作台，不静默重定向。
- requestId 幂等：前端每次打开弹层生成 UUID 随表单提交；后端进程内保存最近 10 分钟 `(advisor_id, request_id)` 集合，重复提交返回首次创建的学生（`{"existing": true}`）。
- Yuguo 导入按钮对所有登录角色可见（对齐原版）；导入结果弹层加 PARTIAL/FAILED/COMPLETED 标题区分 + 按 reasonCode 的指引文案（逐字自 `CopilotStudentList.tsx:16-20`：`LOCAL_CONFLICT→…`、`INVALID_STUDENT_FIELDS→…` 等）。
- 归档报告行加"Activity Hub JSON"下载（格式按 `docs/integrations/junction/first-touch-activity-hub/api-profile.schema.json` 生成）+ 已确认报告显示 `已 finalize · 视为已推送` 徽标。
- 移除归档的原始 payload `<pre>`（PORT-ONLY 冗余）。

- [ ] **Step 1: 写失败测试**

```python
def test_manual_add_accepts_phone(client): ...
def test_manual_add_request_id_idempotent(client):
    r1 = post_manual({"name": "张三", "requestId": "u-1"})
    r2 = post_manual({"name": "张三", "requestId": "u-1"})
    assert r2.get_json().get("existing") is True
    assert student_count("张三") == 1

def test_archive_has_activity_hub_download(client, admin): ...
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**
- [ ] **Step 4-5: 通过 + 回归**
- [ ] **Step 6: Commit** `git commit -m "fix(first-touch): phone field, request-id idempotency, import guidance, activity-hub download"`

---

## 任务依赖图

```
T1（入口/时间）──┐
T2（阶段5）─────┤
T3（阶段3）─────┼── 全部独立，可任意顺序；T4 依赖 T1 的 meetingAt payload
T4（报告阶段）───┤（T4 需 T1 先完成）
T5（项目卡）─────┤
T6（阶段2/4）────┤
T7（聊天）───────┤  T7 的 delete_chat 是 store 改动，与其他任务无耦合
T8（首页/归档）──┘
```

除 T4 依赖 T1 外全部可并行。每个任务结束跑 `python -m pytest -q` 全量回归。
