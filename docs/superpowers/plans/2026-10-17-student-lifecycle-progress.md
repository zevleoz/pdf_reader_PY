# 学生生命周期进度双视图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将学生 360° 页顶部流程改为真实生命周期进度，同时保留列表/工作台的待办优先级视图。

**Architecture:** 继续保持零 schema 的查询推导模型，但把两种语义拆开：`compute_stages()` 服务“现在先处理谁”的待办优先级；新增 `compute_progress(student_id)` 服务“学生走到哪”的生命周期进度。Six A.M. 不作为独立阶段，只在报告生成后作为后台更新状态展示。

**Tech Stack:** Flask、Jinja、Alpine.js、SQLAlchemy、SQLite/PostgreSQL、pytest。

**Spec:** `docs/superpowers/specs/2026-10-14-y4-platform-2.0-design.md`；`docs/agent_instructions/10-student-pipeline-view.md`；本计划 additionally 固化 2026-10-17 的三条流程裁决：Six A.M. 为报告后的后台更新、会议纪要只是非强制进度节点、当前有效问卷提交后即“已就绪”。

## Global Constraints

- 不新增数据库表、不新增学生/问卷/预约/纪要字段；继续遵守 10 号指令包的零 schema 原则。
- 学生 360° 页生命周期顺序固定为：`booked 预约待测评 → report 生成报告 → minutes 会议纪要 → pending_approval 问卷待确认 → awaiting_student 等待学生作答 → ready 已就绪`。
- `minutes` 是可选进度节点：没有纪要时不阻塞问卷；一旦存在问卷任务或纪要，生命周期继续前进。
- 最新/当前有效问卷 `submitted` 后，学生进入 `ready`；历史 `expired/rejected` 不阻塞，但若没有更新的 `submitted`，仍需回到问卷处理。
- 不新增 cron/scheduler；Six A.M. 只是报告落库后的后台更新，不在 stepper 占节点，也不阻塞“报告已生成”的完成状态。
- `/students` 阶段栏、`/workspace` 最近活跃学生继续保留待办优先级语义，不改成生命周期顺序。
- OCR → 报告生成主链路不可破坏；本计划不改上传、extract、validate、generate、PDF 输出契约。
- 前端继续走 Jinja + Tailwind CDN + Alpine.js，不引入 Node 构建链。

## Review Focus

- 已 `completed` 的预约不能再把学生钉在 `booked 预约待测评`；测试固定在 Task 1 的 `_select_workbench_stage`。
- 最新问卷 `submitted` 后，即使存在报告，也必须返回 `ready`；测试固定在 Task 1 的 `_select_progress_stage` 与 `_select_workbench_stage`。
- 会议纪要缺失但已有问卷任务时，生命周期应跳到问卷阶段而不是卡在 `minutes`；测试固定在 Task 1 的 `_select_progress_stage`。
- 报告已生成但 Six A.M. profile 尚未落库时，页面只显示“后台更新中”，不把学生退回报告阶段；测试固定在 Task 2 的 context 组装。
- Advisor 数据隔离不能回归：`compute_stages(advisor_name)` 仍先过滤学生再聚合；由 Task 4 的回归检查覆盖。

---

### Task 1: 拆分待办优先级与生命周期进度模型

**Files:**
- Modify: `pipeline.py:1-129`
- Test: `test_pipeline.py`

**Interfaces:**
- Consumes: 现有 `db.Student`、`db.Booking`、`db.Report`、`questionnaire_store.Assignment` 查询结果。
- Produces:
  - `PROGRESS_STAGES: list[dict]`，key 固定为 `booked/report/minutes/pending_approval/awaiting_student/ready`。
  - `PROGRESS_STAGE_KEYS: list[str]`
  - `progress_stage_meta(key: str) -> dict`
  - `_select_workbench_stage(facts: dict, now: datetime) -> dict`，返回 `{"stage": str, "since": datetime|None}`。
  - `_select_progress_stage(facts: dict, now: datetime) -> dict`，返回 `{"stage": str, "since": datetime|None}`。
  - `compute_progress(student_id: int) -> dict`，返回 `{stage, since, days, since_label, six_am}`。

`facts` 统一形状：

```python
{
    "student_created_at": datetime,
    "pending_booking_at": datetime | None,
    "completed_booking_at": datetime | None,
    "latest_report": {"id": int, "created_at": datetime, "report_date": date} | None,
    "latest_report_minutes_at": datetime | None,
    "pending_assignment_at": datetime | None,
    "sent_assignment_at": datetime | None,
    "latest_assignment": {
        "status": "pending" | "sent" | "submitted" | "expired" | "rejected",
        "created_at": datetime,
        "confirmed_at": datetime | None,
        "submitted_at": datetime | None,
    } | None,
}
```

- [ ] **Step 1: Write the failing lifecycle selector tests**

```python
from datetime import datetime

NOW = datetime(2026, 10, 17, 12, 0, 0)

def test_progress_ready_when_current_assignment_submitted():
    facts = _facts(
        latest_report={"id": 9, "created_at": datetime(2026, 10, 10), "report_date": NOW.date()},
        latest_report_minutes_at=datetime(2026, 10, 11),
        latest_assignment={"status": "submitted", "created_at": datetime(2026, 10, 12),
                           "confirmed_at": datetime(2026, 10, 12),
                           "submitted_at": datetime(2026, 10, 16)},
    )
    assert _select_progress_stage(facts, NOW)["stage"] == "ready"

def test_progress_skips_optional_minutes_when_questionnaire_exists():
    facts = _facts(
        latest_report={"id": 9, "created_at": datetime(2026, 10, 10), "report_date": NOW.date()},
        latest_report_minutes_at=None,
        latest_assignment={"status": "pending", "created_at": datetime(2026, 10, 12),
                           "confirmed_at": None, "submitted_at": None},
    )
    assert _select_progress_stage(facts, NOW)["stage"] == "pending_approval"

def test_workbench_completed_booking_without_report_is_awaiting_report():
    facts = _facts(completed_booking_at=datetime(2026, 10, 15), latest_report=None)
    assert _select_workbench_stage(facts, NOW)["stage"] == "awaiting_report"

def test_workbench_submitted_assignment_beats_reported():
    facts = _facts(
        latest_report={"id": 9, "created_at": datetime(2026, 10, 10), "report_date": NOW.date()},
        latest_assignment={"status": "submitted", "created_at": datetime(2026, 10, 12),
                           "confirmed_at": datetime(2026, 10, 12),
                           "submitted_at": datetime(2026, 10, 16)},
    )
    assert _select_workbench_stage(facts, NOW)["stage"] == "ready"
```

同时覆盖这些断言：无预约无报告 → `booked`；pending 预约 → `booked`；completed 预约但无报告 → 生命周期 `report`；有报告无纪要无问卷 → `minutes`；有报告有纪要无问卷 → `pending_approval`；最新问卷 `expired/rejected` 且无更新 submitted → `pending_approval`。

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest test_pipeline.py -v`
Expected: FAIL，提示 `_select_progress_stage` / `_select_workbench_stage` 不存在。

- [ ] **Step 3: Implement the two selectors and progress metadata in `pipeline.py`**

保留现有 `STAGES` 作为待办优先级元数据，但在其中插入 `awaiting_report`：`pending_approval → awaiting_student → awaiting_report → booked → reported → ready`。新增 `PROGRESS_STAGES` 按 Global Constraints 的生命周期顺序排列，`minutes` 元数据加 `"optional": True`。

`_select_progress_stage` 规则：

1. 没有 completed booking 且没有 report → `booked`，since 取 `pending_booking_at or student_created_at`。
2. 有 completed booking 但没有 report → `report`，since 取 `completed_booking_at`。
3. 有 report、最新 report 无纪要、且没有任何问卷任务 → `minutes`，since 取 report `created_at`。
4. 最新问卷 `pending` → `pending_approval`；`sent` → `awaiting_student`；`submitted` → `ready`；`expired/rejected` → `pending_approval`。
5. 有 report、已有纪要、没有问卷任务 → `pending_approval`，since 取 report `created_at`。

`_select_workbench_stage` 规则：

1. 有 pending 问卷 → `pending_approval`。
2. 有 sent 问卷 → `awaiting_student`。
3. 最新问卷 `submitted` → `ready`。
4. 近 30 天 pending booking → `booked`。
5. 近 30 天 completed booking 且无 report → `awaiting_report`。
6. 有 report → `reported`。
7. 否则 → `ready`。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest test_pipeline.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add pipeline.py test_pipeline.py
git commit -m "feat: split student progress from workbench priority"
```

---

### Task 2: 让 `compute_stages()` 与 `compute_progress()` 分别取数

**Files:**
- Modify: `pipeline.py:58-111`
- Test: `test_pipeline.py`

**Interfaces:**
- Consumes: Task 1 的 `_select_workbench_stage()`、`_select_progress_stage()`。
- Produces:
  - `compute_stages(advisor_name=None) -> dict`：返回结构不变 `{student_id: {stage, since, days, since_label}}`，但 stage 可新增 `awaiting_report`。
  - `compute_progress(student_id: int) -> dict`：返回 `{stage, since, days, since_label, six_am}`；`six_am` 为 `None` 或 `{status, label, version, updated_at}`。

- [ ] **Step 1: Write failing aggregation tests**

用 monkeypatch 替换 `pipeline._db` 与 `pipeline._qs` 的查询 helper，验证：

```python
def test_compute_progress_includes_six_am_pending_status(monkeypatch):
    _stub_student(student_id=1)
    _stub_completed_booking(student_id=1)
    _stub_latest_report(student_id=1, report_id=9)
    _stub_minutes(report_id=9, rows=[])
    _stub_assignments(student_id=1, rows=[])
    monkeypatch.setattr(pipeline._db, "get_latest_six_am_profile", lambda report_id: None)
    assert pipeline.compute_progress(1)["six_am"]["status"] == "pending"
```

再补一条：有最新 Six A.M. profile 时返回 `{status: "ready", version: <profile.version>}`。

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest test_pipeline.py -k compute_progress -v`
Expected: FAIL，提示 `compute_progress` 不存在。

- [ ] **Step 3: Implement aggregation in `pipeline.py`**

`compute_stages()` 继续一次请求内聚合所有学生，不引入 N+1：

- pending/sent assignment 继续用 group by 取最早时间。
- 新增 latest assignment 取数：按 `student_id, id desc` 读 `Assignment.student_id/status/created_at/confirmed_at/submitted_at`，内存保留每个学生第一条。
- booking 拆成两组聚合：`status == "pending"` 与 `status == "completed"`，都保留 30 天 lookback。
- report 继续取最新 `report_date/created_at`。

`compute_progress(student_id)` 只取单学生事实：学生、最新非 cancelled booking、最新 report、最新 report 的 minutes 时间、最新 assignment、最新 Six A.M. profile。调用 `_qs.list_assignments_for_student(student_id)` 复用惰性过期刷新。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest test_pipeline.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add pipeline.py test_pipeline.py
git commit -m "feat: derive lifecycle progress separately from priority"
```

---

### Task 3: 更新学生 360° 页进度条、建议卡与 Six A.M. 状态

**Files:**
- Modify: `blueprints/students.py:182-271`
- Modify: `templates/student_360.html:13-48`
- Modify: `templates/student_360.html:212-254`
- Modify: `templates/student_360.html:542-571`

**Interfaces:**
- Consumes: Task 2 的 `compute_progress()`、`PROGRESS_STAGES`、`progress_stage_meta()`。
- Produces: `stage` context 继续给模板使用，但语义变为 lifecycle progress；新增 `stage.six_am`。

- [ ] **Step 1: Write failing context tests**

在 `test_pipeline.py` 或新建 `test_student_360_context.py` 中，用 monkeypatch 固定 `compute_progress()` 返回值，调用 `_student_progress_context(1)`：

```python
def test_student_progress_context_ready_has_no_suggestion(monkeypatch):
    monkeypatch.setattr("blueprints.students.compute_progress", lambda sid: {
        "stage": "ready", "days": 0, "since_label": "今天", "six_am": None,
    })
    ctx = _student_progress_context(1)
    assert ctx["stage"] == "ready"
    assert ctx["suggestion"] is None
```

覆盖：`report` → 建议“去生成报告”链接 `/generate`；`minutes` → 建议“去写会议纪要”链接 `/tools/transcript`；`pending_approval` → `/workspace`；`awaiting_student` → package action。

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest test_pipeline.py test_student_360_context.py -v`
Expected: FAIL，提示 `_student_progress_context` 不存在或返回旧 priority stage。

- [ ] **Step 3: Implement context and route changes**

将现有 `_student_stage_context()` 替换/重命名为 `_student_progress_context(student_id)`：

- 数据源改为 `compute_progress(student_id)`。
- `reported` 旧建议改为两个生命周期建议：`report` → “测评后上传 PDF 生成报告” + `/generate`；`minutes` → “可补充会议纪要，也可直接处理问卷” + `/tools/transcript`。
- `ready` 不显示下一步建议卡。
- `/students/<code>` 路由传 `stage_meta=PROGRESS_STAGES`，不再传 `STAGES`。

更新模板：

- stepper 数据源仍用 `stageMeta`，但现在收到的是生命周期顺序。
- `minutes` 步骤 label 旁显示小号 `可选` badge。
- 当前阶段行下方新增 Six A.M. chip：无 report 不显示；有 report 无 profile 显示 `Six A.M. 后台更新中`；有 profile 显示 `Six A.M. 已更新 · v{version}`。
- `stepState(i)` 保持索引语义；找不到 stage key 时不要默认把第一步点亮，返回空 class 并在当前行显示 `—`。

- [ ] **Step 4: Run tests and template checks**

Run: `python -m pytest test_pipeline.py test_student_360_context.py -v`
Expected: PASS。

Run: `python -m py_compile pipeline.py blueprints/students.py`
Expected: exit 0。

- [ ] **Step 5: Commit**

```bash
git add pipeline.py blueprints/students.py templates/student_360.html test_pipeline.py test_student_360_context.py
git commit -m "feat: show lifecycle progress on student 360"
```

---

### Task 4: Six A.M. 改为报告完成后的后台更新

**Files:**
- Modify: `blueprints/reports.py:146-225`
- Modify: `blueprints/reports.py:240-304`
- Test: `test_pipeline.py` 或新建 `test_report_hooks.py`

**Interfaces:**
- Consumes: `_save_report_to_db() -> Optional[int]`。
- Produces: `_run_six_am_hook(report_id: int) -> None`；异常只记录日志，不改变 job 状态。

- [ ] **Step 1: Write failing hook test**

```python
def test_six_am_hook_swallows_errors(monkeypatch, capsys):
    import blueprints.reports as reports
    import six_am
    monkeypatch.setattr(six_am, "run_for_report", lambda rid: (_ for _ in ()).throw(RuntimeError("boom")))
    reports._run_six_am_hook(9)
    assert "生成失败" in capsys.readouterr().out
```

再加一条顺序约束测试或审查断言：`_save_report_to_db()` 内不再直接调用 `six_am.run_for_report()`。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test_report_hooks.py -v`
Expected: FAIL，提示 `_run_six_am_hook` 不存在。

- [ ] **Step 3: Move Six A.M. after report job completion**

在 `_save_report_to_db()` 中删除 `six_am.run_for_report(report_id)` 直接调用，保留报告归档与问卷识别钩子。`_run_pipeline_job()` 接收 `report_id = _save_report_to_db(...)`，先 `_write_job(status="done", percent=100, message="报告已生成", ...)`，再调用 `_run_six_am_hook(report_id)`。

实现 `_run_six_am_hook(report_id)`：try/except 包裹 `six_am.run_for_report(report_id)`，失败只打印 `[6AM] 生成失败 (非致命): ...`。

- [ ] **Step 4: Run hook and regression tests**

Run: `python -m pytest test_report_hooks.py questionnaire_engine/tests six_am/tests -q`
Expected: PASS。

Run: `python -m py_compile blueprints/reports.py app.py`
Expected: exit 0。

- [ ] **Step 5: Commit**

```bash
git add blueprints/reports.py test_report_hooks.py
git commit -m "fix: update six-am after report completion"
```

---

### Task 5: 工作台/列表兼容新阶段并更新流程文档

**Files:**
- Modify: `templates/students.html:291-304`
- Modify: `docs/agent_instructions/10-student-pipeline-view.md`
- Modify: `docs/superpowers/specs/2026-10-14-y4-platform-2.0-design.md`

**Interfaces:**
- Consumes: Task 1 的 `STAGES` 新增 `awaiting_report`。
- Produces: 列表 badge 映射支持 `awaiting_report`；文档明确“双视图”语义。

- [ ] **Step 1: Write failing documentation/badge check**

可以做成简单 pytest：

```python
def test_students_template_supports_awaiting_report_badge():
    text = Path("templates/students.html").read_text(encoding="utf-8")
    assert "awaiting_report" in text
    assert "待生成报告" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test_pipeline.py -k awaiting_report_badge -v`
Expected: FAIL。

- [ ] **Step 3: Update list badge and docs**

`templates/students.html` 的 `stageBadge()` 增加 `awaiting_report: 'badge-brand'`。`10-student-pipeline-view.md` 更新为：列表/工作台是待办优先级视图，学生 360° 是生命周期视图；列出两套顺序。设计 spec 增补 Six A.M. 非阶段、会议纪要非强制、当前问卷 submitted 即 ready 的裁决。

- [ ] **Step 4: Run focused and regression checks**

Run: `python -m pytest test_pipeline.py test_student_360_context.py test_report_hooks.py questionnaire_engine/tests six_am/tests -q`
Expected: PASS。

Run: `python -m py_compile pipeline.py blueprints/students.py blueprints/reports.py app.py`
Expected: exit 0。

手动冒烟：启动 `python app.py`，打开 `/students`、`/workspace`、任一 `/students/<code>`，确认列表阶段栏仍可筛选，学生 360° 顶部显示新生命周期顺序。

- [ ] **Step 5: Commit**

```bash
git add templates/students.html docs/agent_instructions/10-student-pipeline-view.md docs/superpowers/specs/2026-10-14-y4-platform-2.0-design.md test_pipeline.py
git commit -m "docs: record dual student pipeline views"
```

---

### Task 6: 已审批的页面整体优化

**Files:**
- Modify: `templates/student_360.html:50-85`
- Modify: `templates/student_360.html:146-254`
- Modify: `templates/student_360.html:542-571`
- Modify: `templates/students.html:229-249`
- Test: `test_student_360_context.py`
- Test: `test_pipeline.py`

**Interfaces:**
- Consumes: Task 3 的 `stage.suggestion`；Task 5 的待办视图命名。
- Produces: 学生 360° 页头只出现一个上下文主按钮；学生资料行使用紧凑 chips；`/students` 阶段栏明确命名为“待办视图”。

- [ ] **Step 1: Write failing UI contract tests**

```python
def test_student_360_template_uses_contextual_primary_action():
    text = Path("templates/student_360.html").read_text(encoding="utf-8")
    assert "stage.suggestion.action_label" in text
    assert "重生成 PDF" in text
    assert "stage-primary" in text

def test_students_page_names_stage_rail_as_todo_view():
    text = Path("templates/students.html").read_text(encoding="utf-8")
    assert "待办视图" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest test_student_360_context.py test_pipeline.py -k "contextual_primary_action or todo_view" -v`
Expected: FAIL。

- [ ] **Step 3: Implement contextual primary action**

学生 360° 页头操作区改为：

- 主按钮复用 `stage.suggestion`：`link` 渲染 `<a>`，`create` 打开发起问卷弹窗，`package` 打开分发信息弹窗。
- `重生成 PDF` 保留为 secondary button，只在有报告时可用。
- `发起问卷任务` 不再无条件作为主按钮；仅在 `ready` 或没有活动 pending/sent 问卷时作为 secondary 出现。
- 下一步建议卡保留说明文字；主行动只出现一次，过期任务的“重新生成链接”作为卡内 secondary。

- [ ] **Step 4: Implement compact meta row**

把 `.stu-meta` 从四列 grid 改为 flex-wrap chips：每项显示 `标签：值`；空值显示 muted `未填写`；`advisor_name` 与 `school` 保留 hover pencil 编辑；移动端自然换行，不再保留四个高空白网格。

- [ ] **Step 5: Rename the list stage rail**

`/students` 阶段栏 `aria-label` 与可见小标题改为“待办视图”，并在旁边加一行说明：“按当前需要处理的事项排序；学生生命周期进度见 360° 档案页。”筛选行为不变。

- [ ] **Step 6: Run UI contract and regression checks**

Run: `python -m pytest test_pipeline.py test_student_360_context.py test_report_hooks.py questionnaire_engine/tests six_am/tests -q`
Expected: PASS。

Run: `python -m py_compile pipeline.py blueprints/students.py blueprints/reports.py app.py`
Expected: exit 0。

手动冒烟：打开任一 `/students/<code>`，确认页头主按钮随阶段变化；空顾问/学校显示 `未填写`；`/students` 阶段栏显示“待办视图”。

- [ ] **Step 7: Commit**

```bash
git add templates/student_360.html templates/students.html test_student_360_context.py test_pipeline.py
git commit -m "feat: streamline student page actions and meta layout"
```

## Self-Review

- Spec coverage：生命周期重排、双视图、会议纪要可选、当前问卷提交即 ready、Six A.M. 后台化、工作台兼容，以及已审批的上下文主按钮、紧凑资料行、待办视图命名均有任务覆盖。
- Step scan：每个任务都有独立测试、实现和验证；没有把实现整段写成代码 transcript。
- Type consistency：`compute_progress()`、`PROGRESS_STAGES`、`_run_six_am_hook()`、`stage.suggestion` 在 Task 2–6 的名字保持一致。
- Review Focus：五个风险点均映射到 Task 1–4 的测试或手动冒烟；UI 变更由 Task 6 的契约测试和手动冒烟覆盖。
- Proportion：本计划只锁接口、规则、文件与验收命令；具体查询写法由实施 agent 按现有 SQLAlchemy 风格完成。
