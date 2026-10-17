# 6 A.M. 模型上线实施计划（交接规格）

> 面向对象：负责实现 6 A.M. 上线代码的 coding agent。
> 本文自包含：所需上下文、代码锚点、数据契约、模块划分、集成点、验收标准全部在本文内。
> 算法规格唯一来源：`docs/6AM_model_algorithm.md`（v0.2）。本文中的规则 ID（`R*` / `X.*` / `Q*`）与 v0.2 文档一一对应，是实现锚点。v0.2 文档本身**不得修改**。

---

## 0. 三条硬约束（先读）

1. **不改 Y4 核心评估逻辑**。`evaluation_rules.py`、`y4_questions.py`、`generate.py`、`extract.py`、`validate.py`、`data_points.py`、`prompts/` 一律只读。6AM 引擎只消费它们已产出的数据。
2. **不实现 v0.2 §11「待定与待修订清单」中未定参数之外的扩展**。清单中已标记"已关闭"的项按文执行；其余待定项只保留可配置参数位（默认值写在代码注释里标注"v0.2 暂定"），不自行发明算法。
3. **不提 E4**。6AM 是与 Y4、E4 平行的独立系统；6AM 档案（DOCX/JSON/页面）中不出现 E1–E4 概念与命名。

---

## 1. 项目上下文

### 1.1 Repo 结构（关键文件）

工作目录：`PDF_converter/`

| 文件 | 职责 |
|---|---|
| `app.py` | Flask 主应用（约 4500 行）：路由、鉴权、分片上传、子进程调度、DOCX/JSON 导出、后台任务状态 |
| `db.py` | SQLAlchemy 数据层：模型定义、`init_db()`、`_migrate_schema()`、全部 CRUD |
| `evaluation_rules.py` | Y4 有效评价规则：`build_evaluation_view` 产出 eval item；档位/排序工具函数 |
| `y4_questions.py` | Y4 原生问题研判（纯数据加工，不导入 Flask）：`im` 索引 + `_order_hit` + 判定函数 |
| `generate.py` | 18 页报告渲染与 PDF 生成，`main()` 在 L1408 |
| `extract.py` / `validate.py` / `data_points.py` | PDF 提取 → 校验 → 回填 |
| `minutes_schema.py` / `minutes_docx.py` | 会议纪要：结构化校验 + DOCX 渲染（本计划的 DOCX 模板参考） |
| `templates/` | Jinja2 模板；`templates/style.css`、`app_shell.css`、`app_shell.js` 为共享设计系统 |
| `docs/` | 规格文档（`6AM_model_algorithm.md` v0.2 在 `docs/`） |
| `data/` | 运行时数据：`report_data.json`、`y4_students.db`、`_job.json`、`_uploads/` |
| `output/` | 生成的 PDF/HTML |

### 1.2 Pipeline 流程（现状）

```
POST /api/upload/chunk          （app.py:496，逐片写 data/_uploads/<upload_id>/<KEY>.part）
POST /api/generate/start        （app.py:525，合并分片 → 写 _job_args.json
                                 → 起子进程 [sys.executable, app.py, "genjob", args]（app.py:593））
app.py genjob 入口              （app.py:4520-4527）
  └─ _run_pipeline_job(job)     （app.py:426-490）
       extract.main()           → 解析 PDF
       validate.main()          → 校验
       apply_report_data()      → 回填 data_points.USER_DATA
       generate.main()          → generate.py:1408，渲染 18 页
                                   → data/report_data.json（student + schema_124）
                                   → output/凭远Y4评测报告_<姓名>.pdf
       _find_generated_pdf()    → app.py:416
       _save_report_to_db()     → app.py:355-413：解析 report_data.json、
                                  解析/创建学生、_db.add_report()（db.py:333，返回 report id）
       _write_job(status="done")（data/_job.json）
POST /api/generate/result       （app.py:620，读 _job.json 返回 PDF）
GET  /api/progress              （app.py:657）
```

另有同步路径 `POST /api/generate`（app.py:696），在 L819 也调用 `_save_report_to_db`。

### 1.3 鉴权与页面模式（必须沿用）

- `admin_required`：app.py:74-81。未登录返回 `403 {"ok": false, "error": "需要管理员权限"}`。所有新增 **API** 用它。
- `page_login_required`：app.py:84-91。未登录 302 到 `/login?next=...`。所有新增**页面**用它。
- 登录：`/login`（app.py:241），密码来自 `ADMIN_PASSWORD`（app.py:64），会话键 `session['is_admin']`。
- 页面模板：`templates/*.html`，共享 `style.css` + `app_shell.css` + `app_shell.js`（侧边导航）。
- 前端消费范式（直接照抄 `templates/y4_signals.html`）：
  - `fetch('/api/students')`（y4_signals.html:330）
  - `fetch('/api/students/<sid>/reports')`（:343）
  - `fetch('/api/reports/<rid>/y4-signals')`（:369）
  - 页面作用域 CSS 变量（ShadCN 风格令牌，:9-28），原生 JS，无外部框架。

### 1.4 数据契约：eval item（6AM 引擎的输入）

`app.py` 中现成的数据装配链：

```python
# app.py:2246-2267（/api/reports/<id>/y4-signals）——6AM 引擎照此装配
record  = _db.get_report_raw(report_id)                       # db.py:370，含 raw.data_json
raw     = record["raw"]
schema_items = [it for it in raw["schema_124"]
                if not _eval_rules.is_hidden_raw(it)]
student = raw.get("student", {})
items, _summary, _m, _opts = _build_qualification_view(schema_items)   # app.py:3010
```

`_build_qualification_view`（app.py:3010-3037）= `evaluation_rules.build_evaluation_view(schema_items)` + E4 指认标注 + 按维度排序。**6AM 只需要前半段**（E4 字段与 6AM 无关）。为避免 Flask 循环导入，`six_am` 包内自行实现等价的纯数据装配（见 §5.1），逻辑与上面一致。

`build_evaluation_view`（evaluation_rules.py:453-511）返回 `(items, summary)`。每个 eval item 的字段（evaluation_rules.py:359-378 + 453-511 回填）：

| 字段 | 说明 |
|---|---|
| `code` | 指标编号（字符串，如 "060"） |
| `label` | 原始指标名，如 `自驱力-自主性得分`、`情绪稳定性-无力感掌控感` |
| `raw_value` | 原始值（数值或文本，如 `"第1位"`） |
| `unit` / `source_pdf` / `note` | 单位、来源 PDF（A2/B3/B4/B6）、备注 |
| `eval_value` | **引擎判定读这个字段**：规则推导值 / 档位字段 fallback / 排序原始值 |
| `eval_source` | `规则推导` / `原始排序` / `档位字段` / `参照值` / `待判定` |
| `level_code` / `level_label` | PDF 档位字段（fallback 用） |
| `dimension` | `心力` / `精力` / `学习力` / `生涯力`（`_DIM_ORDER`，evaluation_rules.py:20） |
| `rule_note` | 仅 `规则推导` 时有 |
| `data_bias` | UI 标注 `高估`/`低估`（旧值 `偏高`/`偏低` 会被 `normalize_bias` 归一，evaluation_rules.py:1700） |

**判定规则读取约定**：
- `eval_value` 为空的项（`待判定`/`参照值`）视为缺失，缺失指标不得产生判定。
- `data_bias` 是独立标注，**不影响档位判定**，只允许出现在档案的证据展示/trace 字段中。
- 档位词集合（v0.2 §1.2）映射为谓词（见 §3.2）。

### 1.5 数据契约：`im` 索引与 `_order_hit`（排序位次判定）

`y4_questions.py` 的消费模式必须被 6AM 复用（**复制逻辑，不改原文件**）：

- `_build_groups`（y4_questions.py:332-403）构建 `im` 字典：
  - 键 = `evaluation_rules._norm_framework_label(label)`（去空格、去尾部"得分/百分位"，evaluation_rules.py:680-686），值为该 eval item；
  - 排序项（`eval_source == "原始排序"`，即能力优势排序 087-094、职业价值观排序 110-124，`is_order_item` evaluation_rules.py:435-442）合成 `ORDERPOS:{值}` 条目（y4_questions.py:355-379），`raw_value = "第{pos}位/共{total}"`，以 `by_label[f"ORDER:{值}"]` 入索引；
- `_order_hit(im, value, top_n=5)`（y4_questions.py:95-101）：`im["ORDER:{value}"]` 存在且 `evaluation_rules._order_pos(it) <= top_n`（`_order_pos` evaluation_rules.py:956-967，从 `raw_value` 提取数字）。

6AM 的 `order_top` 条件谓词必须走同一机制；`top_n` 默认 5，可被规则版本参数覆盖（§4.2）。

### 1.6 既有产物的导出范式（照抄对象）

- **DOCX**：`minutes_docx.build_minutes_docx(d: dict) -> bytes`（minutes_docx.py:16），单一入口、确定性渲染、返回字节流；字体 `微软雅黑`（:13）、品牌红 `#B33A3A`（:28）、`_set_eastasia`（:38-44）处理中文字体、内部 `_run/_body` 样式助手（:46+）。输入经 `minutes_schema.validate_minutes`（minutes_schema.py:77）归一。下载端点 `POST /api/transcript/docx`（app.py:1408-1454）。
- **JSON 下载**：`POST /api/reports/<id>/y4-json`（app.py:2301-2324），返回 `{ok, json, filename}`。
- **DB 迁移**：模型加在 db.py:37-110 区域；`init_db()`（db.py:113-117）启动时 `create_all` + `_migrate_schema()`（db.py:120-248，sqlite-only，裸 `CREATE TABLE IF NOT EXISTS` 兜底）。新表两种写法都要加（模型 + `_migrate_schema` 兜底），与 `e4_mapping`（db.py:215-242）一致。
- 生产库：`/opt/y4_report/data/y4_students.db`；部署后 `systemctl restart y4_report`；目录权限 `chown -R y4report:y4report`。

---

## 2. 算法规格边界（以 v0.2 为准）

- 实现范围 = v0.2 全部内容：§0 定位、§1 pipeline、§2 state/亚型/confidence 体系、§3 维度总览、§4.1–4.6 单维规则、§5 X 规则、§6 Obstacle Score、§7 First Touch（流程留白处按 §11 处理）、§8 追问题库与选择算法、§9 映射总表、§10 三个 worked example。
- **规则 ID 全集（覆盖率检查清单）**：
  - 单维 R 规则 47 条：`R1.1–R1.8`（8）、`R2.1–R2.8`（8）、`R3.1–R3.6`（6）、`R4.1–R4.9`（9）、`R5.1–R5.8`（8）、`R6.1–R6.8`（8）。
  - 跨维 X 规则 7 条：`X.1–X.7`。
  - 追问题 29 条：`Q1.1–Q1.6`、`Q2.1–Q2.6`、`Q3.1–Q3.4`、`Q4.1–Q4.5`、`Q5.1–Q5.4`、`Q6.1–Q6.4`。
- 状态词表：State `Secure / Watch / At-Risk / Blocked`；Confidence `Hypothesis / Supported / Confirmed`。
- 亚型：`A1-S1/S2/S3`、`A2-S1/S2/S3/S4`、`A3-S1/S2/S3`、`A4-S1/S2/S3/S4`、`A5-S1/S2/S3`；A6 无亚型，输出三类支持方向（同伴协作 / 权威施压 / 家长陪同）。
- 待定项处理（§11）：`思维模式结果 < 40 判偏固定型`、Severity/Confidence/Amplifier 数值、Top-N 的 N、R6.6 适用边界、R2.8 采集方式、R2.3/R2.4 分布——全部做成参数（§4.1），默认值用文档现值，代码内注释标记 `v0.2 暂定`。

---

## 3. 架构：`six_am/` 包

新增包（不新增其他顶层文件），模块与职责：

| 模块 | 职责 |
|---|---|
| `six_am/__init__.py` | 对外入口：`run_for_report(report_id)`（集成胶水，见 §5.1） |
| `six_am/rules.py` | 规则表**数据化**：47 条 R 规则 + 7 条 X 规则的声明 + 参数默认值 + 追问题目录（29 条）；纯数据，无副作用 |
| `six_am/engine.py` | 单维判定：构建 `im` 索引 → 逐维跑 R 规则 → state/亚型/confidence；产出带 trace 的原始 profile |
| `six_am/cross_rules.py` | X.1–X.7 修正：调整 state/confidence/amplifier/顺序约束，写 trace |
| `six_am/scoring.py` | §6 Obstacle Score：Severity × ConfidenceFactor × Amplifier、high-priority 判定、sequence 依赖排序 |
| `six_am/questionnaire.py` | §8.2 选择算法：输出 Top-N 问题（含"怎么问"人话版与验证目标） |
| `six_am/render_docx.py` | `build_six_am_docx(profile: dict) -> bytes`，仿 `minutes_docx.py` 模式 |
| `six_am/export_json.py` | `build_six_am_json(profile: dict) -> dict`（机器可读，锚点=规则 ID） |
| `six_am/tests/` | v0.2 §10 三例 worked example 测试 + 规则 ID 全覆盖检查（见 §9） |

依赖方向：`engine → rules/scoring`，`cross_rules → rules/scoring`，`questionnaire → rules`，`render_docx/export_json → profile dict`（只读）。**全部模块不导入 Flask**（与 `y4_questions.py` 的头注释约定一致）；DB 访问只在 `six_am/__init__.py` 的集成胶水中出现。

### 3.1 规则数据化 schema（rules.py）

每条 R 规则一个 dict；X 规则同构。设计目标：**阈值、档位条件、系数都能被规则版本覆盖（§4.2），不改代码**。

```python
{
  "id": "R1.1",
  "dim": "A1",
  "source": ["Y4"],                       # Y4 / FT / 家长 / 观察
  "when": [                                # 条件列表，AND 关系
      {"point": "自驱力-自主性", "is": "偏低"}
  ],
  # 复杂规则用命名谓词（rules.py 内实现并单独可测），when 与 predicate 二选一或并用
  # 例：R1.3 → "predicate": "rebellion_dual_condition"
  "predicate": None,
  "then": {"state": "At-Risk", "subtype": None, "confidence": "Hypothesis",
           "flags": [], "note": "..."},
  "questions": ["Q1.1", "Q1.2"],           # v0.2 表格"关联问题"列
  "text": "..."                            # v0.2 表格"产出/依据"摘要，供档案与面板展示
}
```

`when` 条件操作符全集（引擎实现）：

| 操作符 | 语义 | 读取 |
|---|---|---|
| `is` | `eval_value` ∈ 给定档位词集合（档位词见 §3.2） | eval_value |
| `is_in` | 同上，值列表写法 | eval_value |
| `order_top` | `_order_hit(im, value, top_n)` 命中 | ORDER: 合成项 |
| `gt` / `lt` | 数值比较（如神经质原始分 > 3.5、思维模式 < 40） | raw_value |
| `missing` | 指标缺失（用于"数据缺口"分支，如 R2.8 无主诉时） | — |

命中即产出 `then`；多条规则同类产出时取**最高严重级**（v0.2 §2.1），亚型按规则表优先级取（同维最多一个亚型，冲突时取 v0.2 判定逻辑图靠后的更具体分支）。仅有弱信号且互相矛盾时封顶 `Watch`。

### 3.2 档位词 → 谓词映射（引擎常量）

```
SEVERE          = {需特殊关注, 明显偏低, 严重偏低}
MILD_RISK       = {偏低, 需关注}
BODY_PROBLEM    = {差, 低}
BODY_WATCH      = {中等, 一般}
STRONG_ASSET    = {高, 较好}
NEUTRAL_HEALTHY = {不低, 相对健康, 正常}
```

判定只看 `eval_value`（build_evaluation_view 已把"规则推导 > 档位字段"的优先级解析完）；`待判定`/`参照值`/空值 = 缺失。`data_bias` 不进条件。

### 3.3 engine.run 签名与 profile 结构

```python
# six_am/engine.py
def run(eval_items, student=None, evidence=None, params=None) -> dict:
    """纯函数。evidence 为 First Touch/家长/观察/答案的结构化输入（可为 None）。
    返回 profile dict（下方 schema），全部判定带 trace。"""
```

profile（同时也是 `six_am_profiles.profile_json` 落库内容与 DOCX/JSON 的输入）：

```jsonc
{
  "schema": "six-am-profile-v1",
  "generated_at": "2026-10-13T10:00:00",
  "rule_version": {"id": 3, "label": "published-v1", "status": "published"},
  "student": {"name": "...", "grade": "..."},
  "report_id": 42,
  "dimensions": {
    "A1": {
      "state": "Blocked",                       // Secure/Watch/At-Risk/Blocked
      "subtype": "A1-S2",
      "subtype_name": "Rebellion 逆反型",
      "confidence": "Hypothesis",               // 亚型/维度级最高置信
      "activation_key": "Restore Ownership 恢复所有权",
      "triggered_rules": [                      // 证据 → 规则 → 产出，逐条可溯
        {"id": "R1.1", "evidence": [{"point": "自驱力-自主性", "eval_value": "偏低",
                                     "source": "规则推导", "bias": "正常"}],
         "effect": {"state": "At-Risk", "confidence": "Hypothesis"}},
        {"id": "R1.3", "evidence": [...], "effect": {"state": "Blocked", "subtype": "A1-S2"},
         "flags": ["高叛逆风险人群"]}
      ],
      "cross_mods": [                           // 被哪条 X 规则修正
        {"id": "X.2", "action": "A2 confidence 降一级并标注需用学生自选任务重测"}
      ],
      "score": {"severity": 3, "confidence_factor": 0.7,
                "severity_add": 0.0, "amplifier": 1.0, "total": 2.1},
      "notes": ["依恋沟通偏低 → 反抗外显化"]     // 调节因子等展示文本
    }
    // A2..A6 同构；A6 无 subtype，改为 "support_ranking"（见下）
  },
  "obstacles": [                                  // Obstacle Score 降序
    {"dim": "A1", "score": 2.1, "high_priority": true, "sequence": 1,
     "sequence_note": "X.1 先 A1 后 A2"}
  ],
  "support_plan": {                               // A6 输出（v0.2 §4.6 格式）
    "ranked": [{"direction": "同伴协作", "sub_mechanisms": ["Companion", "Group"],
                "predicted_effectiveness": "高", "basis_rules": ["R6.1", "R6.7"],
                "cautions": "Privacy 调节投递"}],
    "avoid": [{"direction": "权威施压", "basis_rules": ["R6.6"], "reason": "A1-S2"}]
  },
  "questions": [                                  // §8.2 Top-N
    {"id": "Q1.3", "ask": "要是你不想做一件事……", "verify": ["R1.3"], "priority": 1}
  ],
  "evidence_log": [                               // 四类证据源留痕
    {"source": "FT", "kind": "standard_task", "detail": {...}, "at": "..."}
  ],
  "gaps": {                                       // 未采集的数据缺口（§7）
    "family_complaint": null, "schedule": null,
    "subject_status": null, "standard_task": null
  },
  "answers": [                                    // 已录入的追问答案
    {"q": "Q1.3", "result": "confirm", "text": "...", "at": "..."}
  ]
}
```

信心升级语义（v0.2 §2.3）：
- `Hypothesis`：仅 Y4 线索；
- `Supported`：有行为证据（FT 观察 / 标准化任务 / 家长主诉 / 顾问记录）——录入页勾选或四个结构化缺口字段有值时落到对应规则；
- `Confirmed`：追问答案 `confirm` 后，该规则 confidence 升到 Confirmed；答案 `deny` 时把该规则标记 `refuted` 并从命中集移除后重算（这是录入闭环的最小必要语义，文档未展开，按此实现并在代码注释注明）。

### 3.4 cross_rules.py（X.1–X.7）

逐条照 v0.2 §5 实现；每条产出写入对应维度的 `cross_mods` 与全局 `sequence_note`：

| ID | 动作为（v0.2 §5 原文语义） |
|---|---|
| X.1 | A1、A2 均 ≥ At-Risk → 两维 score × 1.5；处理顺序固定先 A1 后 A2 |
| X.2 | A1 亚型 = A1-S2 且 A2 证据全部来自成人安排任务（由 evidence 标记）→ A2 confidence 降一级（下限 Hypothesis），标注"需用学生自选任务重测" |
| X.3 | A3 ≥ At-Risk → A4/A5 的 Hypothesis 级结论标注"待 A3 处理后复测"；score × 0.7；obstacle 排序中 A3 强制置顶 |
| X.4 | A4 ≥ At-Risk → A5 的 First Move 约束标记（低风险：可私下完成、允许低质量、无即时评价），写入 A5.supports 或 A5.notes |
| X.5 | A6 任何推荐必须与前五维 state 兼容；冲突时以 R6.5–R6.7 的避免/慎用为准（在 A6 选择器内实现，不单列动作） |
| X.6 | A2 亚型 = A2-S3 且 state ≥ At-Risk（且已经 R2.8 交叉验证）→ 全部任务级干预暂缓；sequence 首项改为"兴趣探索 → 再评估" |
| X.7 | 家长无法让渡主导权（evidence 标记）→ A1 score × 0.5，干预降级为长期目标；重心转 A2 意义匹配 |

### 3.5 scoring.py（§6）

```
ObstacleScore(i) = Severity(state_i) × ConfidenceFactor(conf_i) × Amplifier(i)
Severity:        Secure=0  Watch=1  At-Risk=2  Blocked=3
                 （R4.5 神经质背景：A4 severity +0.5，封顶 3）
ConfFactor:      Hypothesis=0.7  Supported=1.0  Confirmed=1.2
Amplifier:       默认 1.0；X.1 ×1.5（两维）；X.3 命中 → A4/A5 ×0.7；X.7 → A1 ×0.5
high-priority:   score ≥ 2.0 且 state ≥ At-Risk
sequence:        分数排序叠加依赖约束（X.3 置顶、X.1 A1→A2、X.6 暂缓、X.7 降级）
```

所有数值出自 `params`（默认见 §4.1），不得硬编码在函数体内。

### 3.6 questionnaire.py（§8.2）

严格按 v0.2 §8.2 五步：① state ≥ Watch 的维度按 score 降序；② 前 3 维中 confidence=Hypothesis 的优先，取其关联规则标记的问题；③ 每个被标记维度至少 1 题；④ A6 固定保留 1–2 题；⑤ 去重、按对话自然度排序（先开放后具体），输出 Top-N（N 默认 8，可配置）。题目文本与"验证目标"直接取自 v0.2 §8.3 题库（29 条全量录入 rules.py）。

---

## 4. 规则版本与参数（数据化 + 可编辑）

### 4.1 参数默认值（rules.py 中 `DEFAULT_PARAMS`）

```python
DEFAULT_PARAMS = {
    "order_top_n": 5,                 # R1.3/R1.8/R2.5/R6.4 等 ORDER 条件
    "mindset_fixed_threshold": 40,    # R4.3，v0.2 暂定
    "severity": {"Secure": 0, "Watch": 1, "At-Risk": 2, "Blocked": 3},
    "confidence_factor": {"Hypothesis": 0.7, "Supported": 1.0, "Confirmed": 1.2},
    "r45_neuroticism": {"mode": "severity_add", "value": 0.5, "cap": 3},   # R4.5
    "x1_multiplier": 1.5, "x3_multiplier": 0.7, "x7_multiplier": 0.5,
    "high_priority_min_score": 2.0,
    "questionnaire": {"top_n": 8, "a6_slots": 2, "hypothesis_dim_limit": 3},
}
```

### 4.2 规则版本（DB 表 `six_am_rule_versions`）

- 存储格式：`params_json` = `{"params": {...覆盖 DEFAULT_PARAMS...}, "rule_overrides": {"R3.1": {"when": [...]}, ...}}`。
- 引擎运行时：`DEFAULT_PARAMS` ← 深合并 params ← 应用 rule_overrides；**不修改 rules.py 源码**。
- `status`：`draft`（可多个）/ `published`（任何时刻至多 1 个；publish 时把旧 published 置为 `archived`）。
- 生成档案时记录所用版本（写入 profile_json 的 `rule_version`）。无 published 版本时用 DEFAULT_PARAMS 且 `rule_version = {"id": null, "label": "default"}`。

---

## 5. 集成点

### 5.1 Pipeline 挂钩

**单点挂钩**：`_save_report_to_db`（app.py:355-413）。

1. 该函数改名为返回 `report_id`（`_db.add_report`（db.py:333-345）已返回 lastrowid；无学生时返回 `None`）。同步路径（L819）与异步路径（L476）自动同时覆盖，无需各改一次。
2. 在 `add_report` 成功后追加尽力而为调用：

```python
if report_id:
    try:
        import six_am
        six_am.run_for_report(report_id)
    except Exception as e:
        print(f"[6AM] 生成失败 (非致命): {e}")     # 与既有 [DB] 日志风格一致
```

失败不得影响报告生成/归档主流程（与现有 `_save_report_to_db` 的 try/except 风格一致）。

3. `six_am.run_for_report(report_id)`（`six_am/__init__.py`）步骤：
   - `record = db.get_report_raw(report_id)`；取 `raw["schema_124"]`、`raw["student"]`；
   - `schema_items = [it for it in raw["schema_124"] if not evaluation_rules.is_hidden_raw(it)]`；
   - `items, _ = evaluation_rules.build_evaluation_view(schema_items)`；
   - 取当前 published 规则版本（无则 DEFAULT_PARAMS）；读取该 report 最近的 `answers/gaps`（若有旧版本档案，沿用其录入数据）；
   - `profile = six_am.engine.run(items, student, evidence, params)`；
   - `db.add_six_am_profile(student_id, report_id, json.dumps(profile, ensure_ascii=False), version=next)`。
   - 版本历史：每次重跑**插入新行**（`version` = 该学生已有档案数 + 1），不覆盖旧行。

### 5.2 DB 新增（db.py）

```python
class SixAmProfile(Base):
    __tablename__ = "six_am_profiles"
    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    profile_json = Column(Text, nullable=False)
    version = Column(Integer, nullable=False, default=1)   # 该学生档案版本号，递增
    created_at = Column(DateTime, default=datetime.utcnow)

class SixAmRuleVersion(Base):
    __tablename__ = "six_am_rule_versions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    label = Column(String(100), nullable=False)            # 如 "draft-20261013-1"
    status = Column(String(20), nullable=False, default="draft")  # draft/published/archived
    params_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime)
```

- 同时在 `_migrate_schema`（db.py:120-248）加 sqlite 兜底 `CREATE TABLE IF NOT EXISTS`（仿 e4_mapping，db.py:215-242）。
- 配套 CRUD（仿现有风格，`with Session(engine) as sess`，返回 dict）：
  - `add_six_am_profile(student_id, report_id, profile_json, version) -> int`
  - `get_latest_six_am_profile(report_id)` / `get_six_am_profiles_by_student(student_id)` / `get_six_am_profile(profile_id)`
  - `list_six_am_rule_versions()` / `get_six_am_rule_version(vid)` / `save_six_am_rule_version(label, params_json) -> int` / `publish_six_am_rule_version(vid)`（含旧 published → archived）
- 注意：6AM 档案的 rule version 引用存在 `profile_json.rule_version` 内，不额外加列（保持表结构最小）。

### 5.3 新增路由（全部沿用现有守卫）

| 方法 | 路径 | 守卫 | 作用 |
|---|---|---|---|
| GET | `/six-am` | `page_login_required` | 学生级判定可视化页（模板 `six_am.html`）：学生/报告选择、六维卡片、规则链展开、分数分解、方案与追问溯源、提问闭环录入区 |
| GET | `/six-am/rules` | `page_login_required` | 规则与参数面板 + 沙盒（模板 `six_am_rules.html`） |
| GET | `/api/reports/<int:report_id>/six-am` | `admin_required` | 取档案（`?profile_id=` 指定版本，默认最新） |
| POST | `/api/reports/<int:report_id>/six-am/generate` | `admin_required` | 手动重跑（body `{rule_version_id?, profile_id?}`，沿用旧档案录入数据） |
| POST | `/api/reports/<int:report_id>/six-am/answers` | `admin_required` | 保存追问答案 + 四类缺口字段 → 重跑 → 返回新档案 |
| GET | `/api/reports/<int:report_id>/six-am/docx` | `admin_required` | 下载 Word 档案（`send_file(BytesIO, mimetype=..., download_name=...)`，仿 app.py:1408-1454） |
| GET | `/api/reports/<int:report_id>/six-am/json` | `admin_required` | 下载 JSON 档案（仿 app.py:2301-2324），文件名 `6AM数据_<姓名>.json` |
| GET | `/api/six-am/rule-versions` | `admin_required` | 版本列表（含各版本参数） |
| POST | `/api/six-am/rule-versions` | `admin_required` | 保存 draft（body：params + rule_overrides + label） |
| POST | `/api/six-am/rule-versions/<int:vid>/publish` | `admin_required` | draft → published（旧 published → archived） |
| POST | `/api/six-am/sandbox` | `admin_required` | 沙盒：body `{rule_version_id, report_ids: [] | "all"}` → 逐份重跑 → 返回新旧 state 对比 |

页面可复用 `/api/students`、`/api/students/<sid>/reports`（app.py:1548/1555）做学生筛选。

---

## 6. 产出物规格

### 6.1 Word 档案（教师可读）

`six_am/render_docx.py: build_six_am_docx(profile: dict) -> bytes`，仿 `minutes_docx.py` 模式（单一入口、返回 bytes、无落盘）：字体 `微软雅黑`、东亚字体设置、品牌红 `#B33A3A` 标题、样式助手函数内部定义、`core properties` 写 schema 版本（`six-am-docx-v1`）便于机器解析。

章节（固定顺序，标题即解析锚点）：

1. 标题 + 学生信息表（姓名/年级/报告日期/生成时间/规则版本）；
2. **State 总表**：六维一行（维度 | state | 亚型 | confidence | ObstacleScore | 优先级标记）；
3. 六维判定详述：每维一段——证据（指标 + eval_value）→ 命中规则（ID + 产出）→ X 规则修正 → 结论；
4. 优先级与处理顺序：obstacle 降序表 + sequence 说明（含 X.3 复测提示、X.6 暂缓提示）；
5. 支持方案：排序表（方向 | 子机制 | 预测有效性 | 依据规则 | 注意事项）+ 避免/慎用清单；
6. 追问清单：Top-N，两列（"怎么问"人话版 / 验证目标内部），验证目标列含规则 ID；
7. 数据缺口：未采集的 R2.8/R3.6/R4.9/R5.7 对应字段及补录指引；
8. 附录：全部命中规则明细（ID 级，供审计）。

### 6.2 JSON 档案（机器可读）

`six_am/export_json.py: build_six_am_json(profile) -> dict`：即 §3.3 的 profile（无需二次变换），要求：

- 每个 state/亚型/支持方向/追问项都带 `basis_rules`（规则 ID 数组）；这是"锚点=规则 ID"的落地方式；
- 顶层带 `schema` 与 `rule_version`；
- 不含 E4 字段与 E4 命名；含 `data_bias` 时仅出现在证据 trace 内。

---

## 7. 提问闭环（网站录入 → 重新出结论）

流程（对应 v0.2 §7.2 的"前置准备 → 会谈 → 会后"）：

```
引擎初筛（仅 Y4 证据）→ 出 Hypothesis 版档案 + Top-N 追问清单
   ↓
教师 First Touch 后用 /six-am 的录入区填写：
   ① 每题答案（Q 题：confirm 证实 / partial 部分 / deny 否定 + 记录文本）
   ② 四类数据缺口结构化字段（下方）
   ↓
POST /api/reports/<id>/six-am/answers
   → 更新 profile.answers / evidence_log（source=FT）
   → 对应规则 confidence：partial → Supported（下限）；confirm → Confirmed；deny → refuted（移出命中集）
   → 用同一规则版本重跑 engine（输入增加 evidence）
   → 插入新版本档案（version+1），保留旧版本
   ↓
/six-am 页面可切换版本对比；DOCX/JSON 按版本下载
```

四类数据缺口结构化输入字段（录入页表单，全部可选填）：

| 缺口 | 对应规则 | 字段 |
|---|---|---|
| 家长诉求 | R2.8 | 主诉标签（无兴趣 / 动力不足 / 其他）+ 主诉原文 + 采集来源（家长环节/顾问记录） |
| 排期 | R3.6 | 一周日程概要（每天课程/活动时段数）+ 自由时间估计（小时/周）+ 负荷评级（高/中/低） |
| 学科状态 | R4.9 | 逐学科条目：学科名 + 学生自评水平 + 实际状态（成绩/教师反馈）+ 偏差方向（自评低于/等于/高于实际） |
| 标准化任务结果 | R5.7 | 任务形式 + 能否拆出有序步骤（是/否）+ 能否承诺第一步与开始时间（是/否）+ 情绪反应（畏难/烦躁/无所谓/正常） |

字段有值即作为对应规则的行为证据：R3.6 命中 → A3 相关结论 confidence → Supported；R5.7 拆解结果 → A5-S1/A5-S3 确诊（Supported）；R4.9 自评低于实际 → A4 严重度上调一级并标 A4-S4，自评高于实际 → 只记观察（v0.2 原文）；R2.8 存在主诉 → R2.1/R2.3/R2.4 命中时升一级、confidence → Supported，无测评信号但有主诉 → 该维至少 Watch。

---

## 8. 可视化规则面板（管理员迭代工具）

页面：`/six-am`（学生级判定可视化 + 录入）+ `/six-am/rules`（规则编辑 + 沙盒）。全部数据来自 profile_json 的 trace 字段（§3.3），前端不重算。

### 8.1 学生级判定可视化页

- 学生/报告选择器（复用 `/api/students` 与 `/api/students/<sid>/reports`），版本下拉（`get_six_am_profiles_by_student`）。
- **六维卡片**：每维一张，state 颜色分级（Secure/Watch/At-Risk/Blocked 四档色阶）+ 亚型名 + confidence 徽标 + ObstacleScore。
- 卡片展开 → **规则链**：证据（指标、eval_value、来源、bias）→ 命中 R 规则（ID + 产出）→ X 规则修正（ID + 动作）；`refuted` 规则单独灰显。
- **Obstacle Score 分解**：Severity × ConfidenceFactor × Amplifier 三因子逐项可见（含 R4.5 severity_add 与 X 倍率标注）。
- **支持方案与追问清单来源追溯**：每项显示 `basis_rules`，可跳转到对应规则说明。
- **录入区**（§7）：Top-N 问题表单 + 四类缺口字段，提交后刷新档案。
- 视觉规范：无 emoji；无 AI 模板化元素；沿用 `style.css` 令牌与 `app_shell` 导航；state 用中性色阶 + 文字标签区分，不用彩色条；桌面宽屏优先。

### 8.2 规则与参数可编辑

- 面板展示 `DEFAULT_PARAMS` 全量字段 + 各规则的条件声明（可编辑项：档位条件值、`order_top_n`、`mindset_fixed_threshold`、Amplifier 系数、Severity/ConfidenceFactor、Top-N 的 N）。
- "保存为 draft"→ `POST /api/six-am/rule-versions`（生成 `label` 如 `draft-YYYYMMDD-N`）；"发布"→ publish（唯一 published 不变式）。
- 引擎读取：见 §4.2，来源是 DB 版本而非源码；**页面改参数不需要改代码发版**。

### 8.3 沙盒预览

- 选择 draft 版本 + 目标（单学生 / 全部有档案的学生）→ `POST /api/six-am/sandbox`。
- 服务端逐份：取 `get_report_raw` → 重跑 engine（draft 参数 + 沿用既有录入 evidence）→ 与 baseline（当前 published 重算或最新已存档案）对比。
- 返回结构：`[{report_id, student_name, old_states: {A1:"Watch",...}, new_states: {...}, changed_dims: ["A1","A5"], details: {dim: {old_rules, new_rules}}}]`。
- 页面并排表格呈现"哪些学生/哪些维度的 state 变了"；团队确认后再发布。沙盒只读，**不落库**（不写 six_am_profiles）。

### 8.4 权限

页面 `page_login_required`，API `admin_required`。无新增角色。

---

## 9. 验收标准

1. **v0.2 §10 三个 worked example 作为测试用例**（`six_am/tests/test_worked_examples.py`，用 pytest 或纯 `python -m unittest` 均可）：
   - 按 v0.2 §10 各例的"Y4 输入"构造 eval items（label/eval_value 直接构造，走 `build_evaluation_view` 或直接喂 items），逐条断言：
     - 例 1（逆反型）：A1 `Blocked` / 亚型 `A1-S2` / confidence `Hypothesis` / score `2.1` / high-priority；A2 `Watch` 且带 X.2 标注；A3–A5 `Secure`；A6 输出"权威施压 + 家长陪同慎用、同伴协作排前"；追问含 `Q1.3, Q1.4, Q1.1, Q6.3`。
     - 例 2（过载型）：A3 `Blocked` / `A3-S1` / confidence `Supported`（R3.6）、score `3.0` 且序列置顶；A4/A5 带 X.3 标注且 score `0.98`；追问含 `Q3.1, Q3.2, Q3.3`。
     - 例 3（同伴启动）：A5 `At-Risk` / `A5-S3` / `Supported`（R5.7 确诊）、score `2.0`；支持组合为"同伴协作 + Structure"；追问含 `Q6.1, Q6.2, Q5.4`。
   - 数值断言用容差比较（浮点）。
2. **规则 ID 全覆盖检查**（`six_am/tests/test_rule_coverage.py`）：
   - 47 条 R + 7 条 X 全部存在于 `rules.py` 注册表，且每条至少被一个测试 fixture 或断言路径触达（可用"逐规则构造最小命中输入"的参数化测试）；
   - 29 条 Q 全部进入题库，且每条的 `verify` 指向存在且已实现的 R 规则 ID；
   - 测试内断言 ID 全集常量与 v0.2 列出的清单一致（把清单硬编码进测试作为对照）。
3. 集成不回归：跑一次现有分片生成流程，报告生成/下载不受影响；`six_am_profiles` 有新行；`_job.json` 状态流与现在一致。
4. 档案可解析：DOCX 能被 `python-docx` 打开且章节标题齐全；JSON `json.loads` 通过、每项 `basis_rules` 非空。
5. 沙盒只读：调用 `/api/six-am/sandbox` 后 `six_am_profiles` 无新增行。

---

## 10. 非目标（明确不做）

- 不改 Y4 核心评估逻辑：不改 `evaluation_rules.py` / `y4_questions.py` / `generate.py` / `data_points.py` / AI 解读链（`prompts/`、`_build_y4_interpret_context`）。
- 不实现 v0.2 §11 待定清单未定参数之外的扩展（不新造规则、不发明阈值、不给 §11 第 3/4/7/8/9/10 项拍板默认值，只留参数位）。
- 不修改 `docs/6AM_model_algorithm.md`。
- 不做外部 API（`/api/v1/*`）的 6AM 暴露（后续按需，另立任务）。
- 不改动现有页面的功能（仅允许在 `app_shell` 导航追加 6AM 入口）。

---

## 11. 执行顺序（里程碑）

| 里程碑 | 内容 | 可验证点 |
|---|---|---|
| M1 | `six_am/rules.py`（47R+7X+29Q 数据化 + DEFAULT_PARAMS）、`six_am/engine.py`、`six_am/scoring.py` | 验收项 1：三个 worked example 的单维判定 + 评分通过 |
| M2 | `six_am/cross_rules.py`、`six_am/questionnaire.py`、`six_am/export_json.py` | v0.2 §10 三例全量断言通过（含 X 修正、追问清单） |
| M3 | `db.py` 两表 + CRUD + 迁移；`app.py` 路由 + `_save_report_to_db` 挂钩 | 分片生成后档案落库；验收项 3 |
| M4 | `six_am/render_docx.py` + DOCX/JSON 下载端点 | 验收项 4 |
| M5 | `/six-am` 页面（可视化 + 录入闭环）、`answers` 端点 | 手工问答一轮：confidence 升级、新版本档案生成且旧版本可查 |
| M6 | `/six-am/rules` 页面（参数编辑 + draft/publish + 沙盒对比） | 验收项 5；改参数不改代码即可影响重跑结果 |

M1–M2 是纯算法层，全部可用测试驱动先完成；M3 之后才触碰 web 层。