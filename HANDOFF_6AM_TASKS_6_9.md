# 6AM 行动卡重构：Task 6–9 交接实施计划

更新时间：2026-10-18

## 0. 必须从这里继续

**工作目录（不要换到主仓库）：**

```bash
cd /Users/jefflau/projects/pdf_report_converter/PDF_converter/.worktrees/6am-action-cards
```

- 分支：`feature/6am-action-cards`
- 当前 Task 1–5 的改动**全部在 working tree，未提交 git**。请在同一个 worktree 继续，不要从 `main` 或其他 worktree 开始。
- 不要执行 `git commit` / `git push` / `git reset` / `git rebase`，除非用户另行明确要求。
- 当前测试基线：
  - `python3.11 -m unittest discover six_am.tests -v` → 73 tests OK
  - `python3.11 -m unittest test_six_am_action_overrides -v` → 18 tests OK
- 环境没有 `pytest`。新增测试一律用 `unittest` 风格，用 `python3.11 -m unittest ...` 运行。

原始任务 brief 已拆好，可先读：

- `/.superpowers/sdd/starfire-america-chavez-thunder/task-6-brief.md`
- `/.superpowers/sdd/starfire-america-chavez-thunder/task-7-brief.md`
- `/.superpowers/sdd/starfire-america-chavez-thunder/task-8-brief.md`
- `/.superpowers/sdd/starfire-america-chavez-thunder/task-9-brief.md`

完整进度台账：`/.superpowers/sdd/starfire-america-chavez-thunder/progress.md`

## 1. 已完成状态

### Task 1：规则优先级替代 ObstacleScore（已审阅通过）

- 新增 `six_am/priority.py`。
- 删除 `six_am/scoring.py`。
- `profile["schema"] == "six-am-profile-v2"`。
- `dimensions[*]` 不再有 `score`。
- 顶层有 `priority_order` 与 `deferred`。
- `priority.compute(dims, constraints)` 返回：

```python
{
    "obstacles": [{"dim", "sequence", "priority_reason", "state", "evidence_state"}],
    "priority_order": ["A3", "..."],
    "deferred": [{"dim": "A1", "reason": "..."}],
    "sequence_note": "...",
}
```

关键语义：

- A3 过载优先。
- X.6 全局无兴趣时，A2 兴趣探索优先于 A1；A1/A5 任务级干预暂缓。
- X.7 时 A1 进入 `deferred`，标记长期目标，不进入本轮追问池。
- X.1 要求 A1 先于 A2，但不能把 X.6/X.7 已暂缓的 A1 拉回。
- 其他维度按 `Confirmed > Supported > Hypothesis/None`，再按 `Blocked > At-Risk > Watch`，最后按 A1–A5 固定顺序。

### Task 2：A6 定性适配（已审阅通过）

`support_plan.ranked[]` 现在精确为：

```python
{
    "direction": str,
    "sub_mechanisms": list[str],
    "fit_label": "优先" | "可考虑" | "慎用" | "避免",
    "basis_rules": list[str],
    "cautions": str,
}
```

不再有 `score` 或 `predicted_effectiveness`。A4 的 `神经质背景` flag 会给 Recognition / Competition 增加“减少高压力评价情境” caution。

### Task 3：行动卡视图模型（已审阅通过）

- 新增 `six_am/action_guidance.py`。
- 新增 `six_am/presentation.py`。
- `build_view_model(profile) -> {"summary": ..., "cards": [...]}`。
- cards 固定 A1–A6 顺序，字段包括：

```text
dim, title, state, state_label, evidence_state, evidence_label,
headline, y4_facts, hypotheses, confirmed_evidence,
next_actions, avoid_actions, questions, audit,
priority_rank, priority_reason, priority_label,
deferred, deferred_reason, manually_edited
```

注意：

- `action_guidance` 文案必须贴近 `docs/6AM_model_algorithm_simple.md`，不能发明术语。
- `build_view_model` 已容错 v1 profile：忽略旧 `score`，缺失 `priority_order` 时按固定顺序降级。
- v1 的旧 `sequence_note` / cross_mods / support_ranking 中含 score 或“分数 ×N”的文案已在 presentation 层屏蔽或替换成 canonical 文案。
- `summary["refuted"]` 与每张卡 `audit["refuted_rules"]` 已支持 `被排除 Refuted`。

### Task 4：行动修订 API（已审阅通过）

新增：

```python
db.update_six_am_profile_json(
    profile_id: int,
    profile_json: str,
    session: Optional[Session] = None,
) -> bool
```

- 默认自建 Session 并提交。
- 传入 `session` 时只 update、不 commit，供 Task 8 单事务迁移使用。

新增 API：

```http
POST /api/reports/<report_id>/six-am/action-overrides
```

请求：

```json
{
  "profile_id": 123,
  "dim": "A1",
  "next_actions": ["..."],
  "avoid_actions": ["..."]
}
```

规则：

- `@admin_required + @report_scoped`
- `profile_id` 必须属于当前 `report_id`
- `dim ∈ A1..A6`
- 每类最多 8 条，每条最多 300 字，非空字符串
- 就地更新当前 profile，不生成新版本，不写修订日志
- 响应 payload 顶层包含 `view_model`

`POST /answers` 仍生成新版本；新 profile 会从解析出的上一版继承 `action_overrides`。

### Task 5：主页面（已审阅通过）

- `templates/six_am.html` 已拆成语义容器。
- 新增 `static/css/six_am.css`。
- 新增 `static/js/six_am.js`。
- `app.py` 新增 `/css/six_am.css` 与 `/js/six_am.js` 路由；这是因为 app 使用 `static_folder=None`，沿用现有 `/admin_v2.css` 模式。
- 页面已实现：控制条 → 紧凑摘要 → 固定六维地图 → 右侧行动面板。
- 页面不显示 ObstacleScore / 公式 / Severity / ConfidenceFactor / Amplifier。
- 审计在 `<details>` 折叠区。
- 行动修订保存不生成新版本；追问/缺口保存生成新版本并继承修订。

## 2. 全局约束（后续任务必须遵守）

- 不把 `ObstacleScore`、公式分解或数值权重作为 6AM 结论展示；网页与 Word 均不得出现。
- 六维顺序固定 `A1 → A2 → A3 → A4 → A5 → A6`，不能按优先级重排卡片位置。
- 主要场景是顾问会谈后整理，优先内部团队交接；暂不做完整家长版。
- 一句话判断使用“固定模板 + Y4 原词 + 6AM 规则原文”，不得发明术语。
- 中文为主、英文小字：稳固 Secure / 关注 Watch / 风险 At-Risk / 阻塞 Blocked；仅线索 Hypothesis / 有佐证 Supported / 已证实 Confirmed / 被排除 Refuted。
- 审计信息默认收拢。
- 不重设计 JSON 导出、学生 360° tab、规则管理页（Task 7 只做最小清理）。
- 历史 profile 要自动重算并覆盖原记录，但覆盖前必须备份数据库。
- 不执行 git commit/push。

## 3. Task 6：Word 档案镜像行动卡结构

### 目标

把 `six_am/render_docx.py` 从旧的 State 总表 + Score 章节改成与网页一致的六维行动卡档案。

### 文件

- 修改：`six_am/render_docx.py`
- 修改/新增测试：`six_am/tests/test_action_cards.py`

### 必须做

1. `render_docx` 优先消费 `presentation.build_view_model(profile)`。
2. 删除旧结构中的：
   - `ObstacleScore`
   - `ConfidenceFactor`
   - `Amplifier`
   - Score 公式、数值权重、旧“高优先”表
3. Word 章节改为：
   - 一、紧凑摘要
   - 二、六维行动卡（A1–A6 固定顺序）
   - 三、待确认问题与数据缺口
   - 四、附录：规则审计
4. 每维字段与网页一致：
   - 当前判断
   - 证据状态
   - Y4 事实
   - 初筛假设
   - 补充证据
   - 下一步
   - 避免事项
   - 待确认问题
5. A6 使用 `fit_label`，不显示数值有效性。
6. 审计附录可保留规则链、跨维修正、refuted 条目，但不得在正文首屏堆审计。

### 测试

新增或扩展 `six_am/tests/test_action_cards.py`：

- `test_docx_contains_action_card_sections_and_no_obstacle_score`
- 用 `python-docx` 读取生成文档文本，断言包含：
  - `当前判断`
  - `证据状态`
  - `下一步`
  - `避免事项`
  - `待确认问题`
- 断言不包含：
  - `ObstacleScore`
  - `ConfidenceFactor`
  - `Amplifier`
  - `分数 ×`

运行：

```bash
python3.11 -m unittest six_am.tests.test_action_cards -v
python3.11 -m unittest discover six_am.tests -v
```

### 验收

用真实 profile 生成一份 DOCX，人工打开确认：

- 表格不溢出
- 中文/英文标签正确
- 行动内容可读
- 旧 v1 profile 也不会把 score 文案带进 Word

## 4. Task 7：规则管理页最小一致性清理

### 目标

只清理规则页中已经失效的数值权重参数，不重设计页面。

### 文件

- 修改：`templates/six_am_rules.html`
- 修改：`six_am/rules.py`（如仍有遗留废弃参数）

### 必须做

删除或隐藏这些失效配置项：

- `severity`
- `confidence_factor`
- `r45_neuroticism`
- `x1_multiplier`
- `x3_multiplier`
- `x7_multiplier`
- `high_priority_min_score`
- `a6_base_score`
- `a6_effectiveness`

保留仍有效参数，例如：

- `questionnaire.top_n`
- `questionnaire.a6_slots`
- `questionnaire.hypothesis_dim_limit`
- `schedule_free_hours_max`
- `value_link_defaults`

加载旧规则版本时，前端要过滤历史 `params_json` 里的废弃键，避免旧参数重新出现在编辑界面。

规则页副标题改为：

```text
管理规则开关、阈值与追问数量；优先级由固定规则决定，不使用数值权重
```

### 验收

打开：

```text
/insights/six-am/rules
```

确认：

- 不再出现 Score 权重配置
- 旧规则版本仍可加载
- 页面功能不被重写

## 5. Task 8：历史档案备份、重算与覆盖迁移

### 重要数据警告

当前 worktree 的 `data/y4_students.db` 是 Task 5 冒烟用过的副本，里面可能已有测试新增 profile。**开始 Task 8 前必须重新从主仓库复制一份干净数据库：**

```bash
cp /Users/jefflau/projects/pdf_report_converter/PDF_converter/data/y4_students.db \
   /Users/jefflau/projects/pdf_report_converter/PDF_converter/.worktrees/6am-action-cards/data/y4_students.db
```

不要把 Task 5 的冒烟数据当作正式迁移输入。

### 文件

- 新建：`scripts/migrate_six_am_v2.py`
- 新建：`test_migrate_six_am_v2.py`（unittest 风格）
- 修改：`db.py`（已有 `update_six_am_profile_json(..., session=None)`，Task 4 已实现）
- 运行时数据：`data/y4_students.db`

### CLI

```bash
python3.11 scripts/migrate_six_am_v2.py --dry-run
python3.11 scripts/migrate_six_am_v2.py --apply --backup data/backups/y4_students_before_sixam_v2_<timestamp>.db
```

### 必须做

1. 参照 `scripts/migrate_2_0_foundation.py` 的 `sys.path` 与 DB 初始化方式。
2. `--dry-run`：
   - 枚举所有 `six_am_profiles`
   - 逐行用该行 profile 作为 `source_profile`
   - 调 `six_am.build_profile(...)`
   - 输出 `profile_id/report_id/version`、是否可迁移、主要障碍前后差异
   - 不写数据库
3. `--apply`：
   - 先创建二进制 SQLite 备份
   - 备份失败则退出，不写任何 profile
   - 创建单个 `Session(engine)`
   - 每行调用 `db.update_six_am_profile_json(profile_id, new_profile_json, session=sess)`
   - 保留原 `id/version/created_at`
   - 全部成功才 `commit`
   - 任一失败 `rollback`
4. 迁移后验证：
   - 行数与迁移前一致
   - 所有 profile `schema == "six-am-profile-v2"`
   - `dimensions[*]` 无 `score`
   - `obstacles` 无 `score`
   - `support_plan.ranked[*]` 无 `score` / `predicted_effectiveness`

### 测试（unittest）

`test_migrate_six_am_v2.py` 至少覆盖：

- dry-run 不写库
- 备份失败即中止
- apply 后无 `score` 残留
- 行数与 `id/version` 保持不变
- 模拟中途失败会 rollback

运行：

```bash
python3.11 -m unittest test_migrate_six_am_v2 -v
python3.11 -m unittest discover six_am.tests -v
```

## 6. Task 9：端到端回归与验收

### 必跑命令

```bash
python3.11 -m unittest discover six_am.tests -v
python3.11 -m unittest test_six_am_action_overrides -v
python3.11 -m unittest test_migrate_six_am_v2 -v
```

如测试运行导致已跟踪的 `__pycache__/*.pyc` 变化，清理这些生成物，不要把它们当作源码改动。

### 页面冒烟

```bash
PORT=8011 python3.11 app.py
```

打开：

```text
/insights/six-am
```

检查：

- 学生/报告/版本切换
- 六维地图固定 A1–A6
- 中文状态与证据状态
- 右侧行动面板
- 行动修订保存后版本不变
- 追问保存后版本 +1
- 行动修订被新版本继承
- 被排除 Refuted 展示
- Word 下载

### API 冒烟

检查：

- `GET /api/reports/<id>/six-am`
- `POST /api/reports/<id>/six-am/action-overrides`
- `POST /api/reports/<id>/six-am/answers`
- `GET /api/reports/<id>/six-am/docx`
- `GET /api/reports/<id>/six-am/json`（只确认不破坏，不重设计）

### 最终人工验收

用真实学生档案检查首屏能否不看规则链就回答：

1. 当前主要障碍是什么？
2. 证据是否足够？
3. 下一步做什么？
4. 不要做什么？
5. 还要确认什么？

## 7. 已知 deferred minors（不阻塞继续，但最终 review 要知道）

- 页面状态/证据徽章还没有把英文部分单独渲染成 `<small>`，目前中文主标签正确。
- 每维度面板独立保存；切换维度前未保存的编辑会丢失，暂无 dirty-check。
- A6 headline 在没有 `优先` 方向时可能用第一个方向兜底，文案可再优化。
- X.7 且 A1 Secure 时不会产生 `deferred` 条目。
- `_run_a6` 的 `params` 形参目前未使用。
- R6.* 规则数据里仍有无害的 `delta` 残留，引擎不读取。
- 规则管理页 Task 7 之前仍可能显示旧参数。
- DOCX Task 6 之前仍可能显示旧 Score 字段。

## 8. 建议给其他 agent 的执行方式

按顺序执行：

1. Task 6（Word）
2. Task 7（规则页清理）
3. Task 8（迁移）
4. Task 9（验收）

每个任务完成后至少跑一次相关测试；Task 8 前必须重新复制干净 DB。不要把这些任务并行给多个 agent，因为 Task 6/7/8 都依赖当前 working tree 中的未提交改动。
