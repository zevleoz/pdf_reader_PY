# E4 映射指认 + UI 流体重写 + AI 三步工作流 实施计划

## Summary

三件事：

1. **评价 UI 重写**：取消横向滚动 pillstrip 和两列卡片，改为「当前值 chip + 居中弹层选择」的流体重交互；评价面板在激活时占满整个内容区宽度。
2. **Y4→E4 映射指认界面**：删除 `evaluation_rules.py` 里 AI 自行推断的 `E4_CODE_MAP`，改为用户在界面里逐条/批量指认（存数据库），未指认的进 OTHER\_VARIABLES。
3. **E4 协议 AI 三步工作流**：点「下载 E4 协议」→ 每次自动跑 ①数据整编 → ②E1-E4 分维度分析（4 路并行） → ③综合成文，界面逐步显示进度并给总览，完成后直接下载。**不做 E4 结果存储**（用户已确认取消）。**Y4 原始 code/label 全程不改名，是唯一权威命名。**

## Current State（已核实）

* 数据流：[prompt\_lab.html](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/prompt_lab.html) → `/api/prompt-lab/evaluation`（[app.py L1795](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/app.py#L1795)）读 `data/report_data.json` → `evaluation_rules.build_evaluation_view()` 生成 items，附加 `e4_classify()` 推断分类。

* 现有 E4 分类：[evaluation\_rules.py L472-533](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/evaluation_rules.py#L472-L533) `E4_CODE_MAP` 全部是推断值（要废弃），`E4_DIMS/E4_LABELS/E4_SUBCATS`（L455-469）是框架常量（保留）。

* 现有 E4 下载：[app.py L2026](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/app.py#L2026) 纯 Markdown 拼接直接下载，无 AI、无存储；行格式 `_format_e4_line()`（L1987）已保留 Y4 原名（保留复用）。

* 前端卡片：`renderEvalCard`（[prompt\_lab.html L713](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/prompt_lab.html#L713)）+ pillstrip 滚动条（CSS L415-431）+ `adjustEval`（L836）；下载按钮 `downloadEvalMd`（L855）。

* 数据库：[db.py](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/db.py) SQLAlchemy，SQLite（`data/y4_students.db`）或 `DATABASE_URL` 切 Postgres；`init_db()` + `_migrate_schema()` 已有迁移机制（L100-186）。

* AI 调用模式：各 route 内联 urllib POST `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`，key 来自 `DASHSCOPE_API_KEY`（缺省 `extract.DEFAULT_DASHSCOPE_KEY`），迭代用 `ITERATION_MODEL`（qwen-turbo），解读用 `AI_TEXT_MODEL`（qwen-plus），timeout 120s（[app.py L1628-1644](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/app.py#L1628-L1644)）。

## 已确认决策

| 决策点    | 结论                                                             |
| ------ | -------------------------------------------------------------- |
| 映射方式   | 做映射指认界面，用户逐条/批量指认，存数据库                                         |
| 工作流    | 三步：数据整编 → 分维度分析（并行）→ 综合成文                                      |
| 评价选项交互 | 当前值 chip，点击弹居中浮层选择（用户偏好：弹层居中于视口、完整可见）                          |
| 数据命名   | Y4 报告 code/label 是 source of truth，传给下游 AI 一律原名，E4 维度/子类只是分组标签 |

***

## Proposed Changes

### 1. db.py — 新增映射表 + CRUD

新增模型（加在 `Availability` 之后）：

```python
class E4Mapping(Base):
    __tablename__ = "e4_mapping"
    code = Column(String(20), primary_key=True)   # Y4 指标编号，如 "015"
    e4_dim = Column(String(4), nullable=False)    # E1/E2/E3/E4
    e4_sub = Column(String(50), nullable=False)   # 子类别，取 E4_SUBCATS
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

新增函数：

* `get_e4_mapping() -> Dict[str, Dict[str, str]]`（`{code: {e4_dim, e4_sub}}`）

* `save_e4_mapping(entries: List[Dict])`（逐条 upsert，支持 `e4_dim=None` 表示删除该条）

* `_migrate_schema()`：为 SQLite 补 `CREATE TABLE IF NOT EXISTS e4_mapping`（沿用 L166-184 的写法）；Postgres 由 `create_all` 覆盖。

不建 E4 结果表——E4 协议每次现生成，不落库。

### 2. evaluation\_rules.py — 废弃推断映射

* **删除** `E4_CODE_MAP`（L472-533）和现有 `e4_classify`。

* **保留** `E4_DIMS / E4_LABELS / E4_SUBCATS / DATA_BIAS_OPTIONS / EVAL_OPTIONS`。

* 新增：

```python
def e4_classify(item, mapping: Dict[str, Dict[str, str]]) -> Tuple[Optional[str], Optional[str]]:
    """从用户指认的 mapping 查 (e4_dim, e4_sub)。未指认返回 (None, None)。"""
    m = mapping.get(str(item.get("code", "")))
    return (m["e4_dim"], m["e4_sub"]) if m else (None, None)
```

* 不再有任何兜底归类——未指认 = 未指认，输出进 OTHER\_VARIABLES。

### 3. app.py — 接口层

#### 3.1 修改 `/api/prompt-lab/evaluation`（L1795）

加载 DB mapping，用新 `e4_classify(it, mapping)` 附加 `e4_dim/e4_sub`（可为 `null`）；响应里加 `"mapping_done": n, "mapping_total": len(items)` 供前端显示指认进度。

#### 3.2 新增映射接口

* `GET /api/prompt-lab/e4-mapping` → `{ok, mapping, subcats: E4_SUBCATS, dims: E4_LABELS}`

* `POST /api/prompt-lab/e4-mapping` body `{entries: [{code, e4_dim, e4_sub|null}]}` → 校验 `e4_dim ∈ E4_DIMS`、`e4_sub ∈ E4_SUBCATS[dim]` 后落库，返回最新 mapping。

#### 3.3 新增 E4 工作流接口（三步，前端逐步调用）

公共辅助 `_dashscope_chat(messages, model, timeout, max_tokens)`（抽自现有内联写法，仅供新端点使用，不动既有 route）：

* `POST /api/prompt-lab/e4/step1` body `{items, include_raw}` → 纯 Python 无 AI：

  * 用 DB mapping 分组（未指认 → OTHER\_VARIABLES）；

  * 返回 `{ok, dataset_lines: [...], mapping_snapshot_md, group_counts, unmapped_count}`；

  * `dataset_lines` 用现 `_format_e4_line()` 生成（Y4 原名）。

* `POST /api/prompt-lab/e4/step2` body `{dataset_lines, mapping_snapshot_md}` → 用 `ThreadPoolExecutor` 并行 4 次调用，每个维度一个 prompt：

  * system：E4 框架定义 + 该维度子类 + 该维度映射快照 + 硬规则（**引用指标必须带 Y4 原始编号与名称；禁止改名、造新词；CONFIRMED/OBSERVATION 语义；bias 含义**）；

  * user：该维度 dataset\_lines + 对应 EXPERT 备注（note/偏差/观望）；

  * 输出：该维度分析 markdown（核心发现 / 薄弱点 / 低垂果实 / 追问建议）；

  * 模型 `E4_STEP2_MODEL`（默认 `qwen-turbo`，防超时），单次 timeout 180s；

  * 返回 `{ok, analyses: {E1..E4: text}, stats: [{dim, tokens, time_ms, model}], failed: [...]}`（单个维度失败不阻塞，标注 failed）。

* `POST /api/prompt-lab/e4/step3` body `{items, include_raw, analyses, interpretation}` →：

  * AI 只写「总览」段（跨维度核心矛盾 / 真实优势 / 下一步，锚定 E4 框架），模型 `E4_STEP3_MODEL`（默认 `qwen-plus`），timeout 180s；

  * **最终协议 md 由 Python 确定性拼装**（AI 永远不碰数据行，保证 Y4 原名不被改写）：
    `META(工作草稿) → E4_FRAMEWORK → MAPPING_SNAPSHOT(人工指认) → STUDENT_INFO → E4_EVALUATIONS(分组数据行) → OTHER_VARIABLES → E1-E4 分析(step2) → OVERVIEW(step3) → EXPERT_JUDGMENTS → AI_USAGE_GUIDE(含"Y4 命名为唯一权威，禁止改名") → 页脚`；

  * 不落库，直接返回 `{ok, content_md, stats}`，前端据此触发下载并展示总览。

* 删除现有 `download-e4` 端点（[app.py L2026](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/app.py#L2026)），由上述工作流取代；`download`（默认协议，L1821）不动。

### 4. templates/prompt\_lab.html — UI 重写

#### 4.1 评价面板占满宽度

* 切到「有效评价」tab 时，`lab-layout` 加 `mode-eval` class：中间面板展开为 100%（左右两栏隐藏），`tabEval` 内部自带顶栏（tab 切换按钮 + 工具栏），可随时切回 AI 解读。

#### 4.2 卡片重构（去掉 pillstrip/横向滚动）

单列流式卡片列表（宽屏下 `grid-template-columns: repeat(auto-fill, minmax(560px, 1fr))` 允许自然换列，卡片内部永不横向滚动）：

```
┌──────────────────────────────────────────────────────────┐
│ 015 人格-责任心        [较好]   正常|偏高|偏低   观望  备注 │
│ raw: 4.2 · 规则推导: 人格>4.5高                            │
└──────────────────────────────────────────────────────────┘
```

* 评价值是一个 chip 按钮（按档位配色，沿用现有 L428-431 配色语义），点击弹**居中弹层**；

* 偏差三态按钮组、观望 toggle、备注按钮保持卡内（沿用现有 `setBias/setNote/toggleProblem` 逻辑，只改渲染壳）；

* 删除 `.eval-pillstrip` 相关 CSS 与 `scrollIntoView` 逻辑。

#### 4.3 居中选择弹层（复用组件）

`openEvalPicker(code)`：固定居中于视口（`position: fixed; inset: 0` + flex center），标题 = `code + label`，10 个选项按「正面 / 负面」两组换行 chips 全展示，当前值高亮，点击即保存关闭；Esc/点遮罩关闭。弹层内容完整可见，不随页面滚动。

#### 4.4 E4 映射指认编辑器

* E4 视图模式工具栏新增「指认映射 (x/y)」按钮 → 全宽映射编辑面板（同 4.1 的全宽模式）：

  * 列表行：`code | label | Y4维度 | 当前E4指认(或"未指认"灰标)` + 多选 checkbox；

  * 单击行 → 居中弹层：E1/E2/E3/E4 四个大按钮 → 选中后显示该维度子类按钮 → 确认；

  * 勾选多行 → 「批量指认」走同一弹层；

  * 「保存映射」→ POST 全量 entries；顶栏显示已指认/总数进度；

  * 数据源：`GET /api/prompt-lab/e4-mapping` + `/api/prompt-lab/evaluation` 的 items。

#### 4.5 E4 工作流进度 UI

`downloadEvalMd('e4')` 改为 `startE4Flow()`，每次点击都跑完整工作流（不查存档）：

1. 打开**居中工作流弹窗**；若存在未指认指标，先提示「有 N 条未指认，将归入 OTHER\_VARIABLES」，可继续或先去指认；
2. 三步 stepper：

```
① 数据整编  ✓ 3.2s · 已分组 102 条 · 未指认 4 条
② 分维度分析  ● E1 ✓ E2 ✓ E3 进行中… E4 排队
③ 综合成文  ○
```

1. 每步 fetch 完成即更新状态（step2 内逐维度点亮）；全部完成 → **总览页**：生成时间、各步 tokens/耗时、AI 总览段渲染、内容预览（可滚动），并自动触发 .md 下载；
2. 「重新生成」在总览页一键重跑三步；关闭弹窗即放弃，不留任何存档。

#### 4.6 视觉规范

沿用 style.css tokens（`--paper/--ink/--red`），无 emoji，弹层一律居中视口、完整可见；chip/stepper 用现有圆角+细边框语言，动画 `0.15s ease`。

***

## 数据命名规则（写入协议与 AI prompt 的硬约束）

* 所有数据行保持 `code:{Y4编号} | label:{Y4原始名称}`，与 Y4 报告逐字一致；

* E4 维度/子类仅作为分组标题出现，标注「分组标签（人工指认），非数据名称」；

* `AI_USAGE_GUIDE` 新增条目：`NAMING_RULE: Y4 报告的 code+label 是唯一权威命名。下游 AI 引用任何指标必须使用该原名，禁止改写、缩写、翻译或创造新术语。`

* step2/step3 的 system prompt 同样写入该规则。

## Assumptions

* E4 协议不存储（用户已确认）：每次点击现生成，学生信息（META/STUDENT\_INFO 段）仍取自 `report_data.json`。

* 映射指认结果存 `e4_mapping` 表，跨会话保留。

* step2 用 qwen-turbo（4 路并行，速度优先，沿用 ITERATION\_MODEL 的经验）；step3 用 qwen-plus（综合质量）；均可用环境变量 `E4_STEP2_MODEL` / `E4_STEP3_MODEL` 覆盖。

* 单维度 step2 失败不阻塞整体（该段标注生成失败，可重新生成）。

## Verification

1. 语法检查：`python3 -c "import ast; ast.parse(open('app.py').read()); ast.parse(open('db.py').read()); ast.parse(open('evaluation_rules.py').read())"`。
2. 表迁移：`python3 -c "from db import init_db; init_db()"` 后用 sqlite3 确认 `e4_mapping` 已创建。
3. 接口冒烟（重启 8000 端口服务后，带登录 cookie curl）：

   * `GET /api/prompt-lab/e4-mapping` 返回空 mapping；

   * `POST /api/prompt-lab/e4-mapping` 写入一条，再 GET 验证；

   * `POST /api/prompt-lab/e4/step1` 返回分组统计（未指认计数正确）。
4. UI 手动验收：评价卡片无横向滚动、弹层居中完整可见；映射指认保存后 E4 视图分组随之变化；点「下载 E4 协议」触发三步工作流且进度逐步点亮，完成后自动下载 + 总览；step2/step3 输出中所有指标引用均为 Y4 原始 code+label。

