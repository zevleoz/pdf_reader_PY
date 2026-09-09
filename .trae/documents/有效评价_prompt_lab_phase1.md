# 有效评价 — Phase 1：Prompt Lab 有效评价交互视图（含下载 mock）

## Summary

在现有 `/prompt-lab` 页面新增一个「有效评价」视图 tab，把每个数据点展示为 `{code, label, raw_value, 有效评价(可调), 来源}`。有效评价可逐项调整（下拉选择），raw value 不可改（黄金铁律）。视图底部有「在 Markdown 中包含原始数据」复选框 + 「下载有效评价 Markdown」按钮，下载的 Markdown 使用**用户调整后的有效评价**（并按复选框决定是否附 raw data），供内部验证交互 UX 与 prompt 效果。

与 AI 解读输出并列对照，验证「有效评价推导」与「AI 解读」两者一致可用。

**本步为两阶段建设的 Phase 1**：用 `data/report_data.json`（Prompt Lab 测试数据）mock 完整交互流程（展示→调整→下载），验证 UX 与 prompt。Phase 2（连数据库真实报告、上线到学生流程、落库调整）留作后续独立计划。

**铁律**：不触碰 PDF 生成流程（`_generate_report.py`、`extract.py` PDF 解析、`generate.main()`）；raw data 只读不可改；仅复用已提取数据。

***

## Current State Analysis

1. **Prompt Lab 现状** (`templates/prompt_lab.html` + `app.py` L1578-1790)

   * 三栏布局：Prompt 编辑器（左）| AI 输出（中）| 反馈迭代（右）。

   * 读 `data/report_data.json` 作为测试数据。

   * `/api/prompt-lab/run`：用当前 prompt 跑 AI 解读。`/api/prompt-lab/iterate`：自动改 prompt。`/api/prompt-lab/save`：存 prompt。

   * 当前无有效评价视图，无法逐数据点核对或调整。

2. **数据中的档位字段**（实测 `data/report_data.json`）

   * `schema_124` 共 134 条，其中 16 条是「档位/评级/等级/结果」项，值如：高/中/低/情绪不稳定/良好/中等/偏低。

   * 配对关系：档位项 label = 得分项 label 将「得分」替换为「档位/等级/评级/结果档位」；或 code+1 邻接。

   * 例：`009 情绪稳定性总分 20` → `010 情绪稳定性结果档位: 情绪不稳定`。

3. **prompt 中的有效评价阈值规则** (`prompts/ai_interpreter.md` + `prompts/prompt_template.md`)

   * 001 情绪稳定性：36+ → Potential list；<36 → Interference

   * 002 自尊：10+ → Potentialities；<10 → 需关注；<5 → 严重关切

   * 003 抑郁愉快：<5 → 偏低

   * 自我概念总值：90+ → 偏高；<=12 → 偏低

   * 认知百分位：>=95 → 相当高；>=90 → 高；>=80 → 高

   * 霍兰德单项：>=8 → 高分值区域

   * 词汇集：偏高/高/中/低/偏低/正常/差/良好/偏差/较差/中等/情绪不稳定/Potential list/Interference/Potentialities/需关注/严重关切

4. **既有 Markdown 下载端点** (`app.py` L1373-1508，上一轮新增)

   * `GET /api/reports/<id>/evaluation`：从 DB 读报告，拼装 Markdown（学生信息 + 四维分组数据 + AI 解读）。

   * 本 Phase 1 **不改它**，但拼装逻辑思路复用。Phase 1 的下载用 `data/report_data.json`（不连 DB），且接受**用户调整后的有效评价**。

5. **铁律约束**（项目记忆）

   * 不修改 PDF 生成与 AI 逻辑核心代码。

   * `/prompt-lab` 已是 `@page_login_required`，`/api/prompt-lab/*` 是 `@admin_required`。

***

## Proposed Changes

### 1. 新增 `evaluation_rules.py` 模块（有效评价推导逻辑）

**为什么**：可复用的有效评价推导逻辑，把「复用档位 + 补全缺失项」固化，供 Prompt Lab 展示与下载复用。

**怎么做**：新建 `evaluation_rules.py`（与 `db.py` 同级，纯函数，不导入 Flask）：

```python
# 有效评价词汇选项（下拉用），按 Y4 语境分组
EVAL_OPTIONS = [
    "偏高", "高", "中", "偏低", "低", "正常",
    "良好", "偏差", "较差", "中等", "情绪不稳定",
    "Potential list", "Interference", "Potentialities", "需关注", "严重关切",
]

def pair_score_with_level(schema_items):
    """把得分项与档位项配对。
    返回 [{code, label, raw_value, eval_value, eval_source, level_code, level_label}]
    - eval_source: "档位字段" | "规则推导" | "待判定"
    - 配对：label 将「得分」替换为「档位/等级/评级/结果档位」查找；或 code+1 邻接。
    """

def derive_evaluation(code, label, raw_value):
    """对无档位字段的得分项，按 prompt 阈值规则推导。
    返回 (eval_value, rule_note) 或 (None, None)。
    编码 prompt 明确阈值（见 Current State 第 3 点）。
    """

def dimension_of(item):
    """Y4 四维归类（label 关键词 + source_pdf 兜底），与 app._dimension_of 同逻辑。"""

def build_evaluation_view(schema_items):
    """主入口：构建有效评价视图。
    1. pair_score_with_level 找出有档位的。
    2. 对剩余得分项调 derive_evaluation。
    3. 纯档位项不单独列（其值并入对应得分项）。
    返回 [{code, label, raw_value, eval_value, eval_source, dimension, level_code}]
    """
```

* 阈值规则表用常量定义在文件顶部，便于审视。

* 纯数据加工，不触发 AI、不写库、不读 PDF。

### 2. 新增 API：`GET /api/prompt-lab/evaluation` — `app.py`

**为什么**：Prompt Lab 前端拉取结构化数据点渲染可调整表格。

**怎么做**：

* `@app.route("/api/prompt-lab/evaluation")` + `@admin_required`。

* 读 `data/report_data.json`（与 `/api/prompt-lab/run` 同源）。

* 调 `evaluation_rules.build_evaluation_view(schema_items)`。

* 返回 `{ok, items:[...], student:{...}, summary:{total, with_eval, derived, pending}}`。

### 3. 新增 API：`POST /api/prompt-lab/evaluation/download` — `app.py`

**为什么**：下载使用**用户调整后有效评价**的 Markdown，并按复选框决定是否附 raw data。这是 Phase 1 交互下载 mock 的核心。

**怎么做**：

* `@app.route("/api/prompt-lab/evaluation/download", methods=["POST"])` + `@admin_required`。

* 入参 JSON：`{items: [{code, label, raw_value, eval_value}], include_raw: bool, interpretation: str(可选)}`

  * `items`：前端表格当前状态（含用户调整后的 eval\_value）。

  * `include_raw`：复选框状态，决定 Markdown 是否附 raw\_value 列。

  * `interpretation`：可选，前端可粘贴最近一次 AI 解读文本一同写入 Markdown 第三节。

* 读 `data/report_data.json` 取 student 信息（姓名/年级等表头）。

* 拼装 Markdown（复用既有 `_DIM_ORDER`/`_DIM_LABELS` 分组逻辑，但数据来自前端 items 而非 DB）：

  ```
  # Y4 有效评价 · {student_name}
  > 凭远教育 · Y4 综合测评系统
  ## 一、学生信息
  (student 表格)
  ## 二、有效评价（按 Y4 四维分组）
  ### 心力（…）
  - 009 情绪稳定性总分：20（有效评价：情绪不稳定）  ← eval 来自前端
  ...（include_raw=true 时显示 raw_value；false 时只显示有效评价）
  ## 三、AI 解读（可选）
  {interpretation 或 "（未提供）"}
  ---
  本文件由 Y4 Prompt Lab 生成（测试），供团队内部使用。
  ```

* 返回 `send_file(BytesIO, mimetype="text/markdown", as_attachment=True, download_name="有效评价_test.md")`。

* **不落库**（Phase 1 仅 mock，不写 reports 表）。

### 4. 前端：Prompt Lab 中栏新增「有效评价」交互视图 — `templates/prompt_lab.html`

**为什么**：让用户逐数据点查看/调整有效评价，并 mock 下载，验证线上将用的交互 UX。

**怎么做**：中栏顶部加 tab 切换「AI 解读 | 有效评价」。

**「AI 解读」tab**：现有输出（不变）。

**「有效评价」tab**（交互表格）：

* 顶部 summary 条：`共 N 项 | 有效评价 M 项 | 推导 K 项 | 待判定 J 项`。

* 表格按 Y4 四维分组（心力/精力/学习力/生涯力），分组头 sticky，可折叠。

* 列：code | label | raw\_value(只读) | 有效评价(下拉) | 来源(标签)

* **有效评价单元格**：`<select>` 下拉，options 来自 `EVAL_OPTIONS`；默认选中推导值；用户改后高亮标记「已调整」。

  * raw\_value 列只读，不可编辑（黄金铁律 UI 体现）。

  * 来源标签三色：`档位字段`(灰) / `规则推导`(红描边) / `待判定`(虚线)。

* 底部操作栏（sticky bottom）：

  * `<input type="checkbox" id="includeRaw"> 在 Markdown 中包含原始数据`

  * `<button class="btn-sm primary">下载有效评价 Markdown</button>` → POST 当前 items + checkbox + (可选)最近 AI 解读到 `/api/prompt-lab/evaluation/download`，触发浏览器下载。

* 流畅交互：行 hover 高亮；分组折叠动画；调整后单元格淡红底色提示；下载按钮 loading 态。

* 样式沿用 design tokens（`--paper/--ink/--red/--line`），无 emoji，极简。窄屏表格横向滚动。

**数据流**：

* 页面加载并行 fetch `/api/prompt-lab/prompt`（现有）+ `/api/prompt-lab/evaluation`（新）。

* 用户调整下拉 → 更新内存 items 数组。

* 点下载 → POST items + includeRaw → 收 .md 文件。

### 5. 不改动项（明确边界）

* `prompts/ai_interpreter.md`：不改（用户通过 Prompt Lab「迭代」按钮自行 refine）。

* `_generate_report.py` / `extract.py` / `generate.main()`：不触碰（铁律）。

* `GET /api/reports/<id>/evaluation`（上一轮 DB 版下载端点）：不改。

* `db.py`：不改（Phase 1 不落库）。

***

## Assumptions & Decisions

1. **有效评价来源**：复用现有档位字段 + 规则推导补全缺失项。用户确认。
2. **Phase 1 形态**：增强 `/prompt-lab`，含交互调整 + 下载 mock（用 report\_data.json 测试数据）。用户确认并补充「mock 里也要测线上将用的 interactive interface before download」。
3. **本次范围**：仅 Phase 1。Phase 2（连 DB 真实报告、上线学生流程、落库调整）留作后续独立计划。
4. **推导规则**：仅编码 prompt 中明确写出数值阈值的规则（情绪稳定性 36、自尊 10/5、抑郁 5、自我概念 90/12、认知百分位 95/90/80、霍兰德 8）。无明确阈值的标「待判定」，由用户在 UI 手动选或通过 prompt 迭代让 AI 覆盖。
5. **raw data 不可改**：UI 上 raw\_value 列只读；下载复选框控制是否包含 raw\_value 列，但不改其值。黄金铁律。
6. **有效评价可调**：下拉选，默认推导值，用户可改。下载用调整后的值。
7. **不落库**：Phase 1 调整与下载都是前端内存态 + 即时拼装，不写 reports 表。落库留 Phase 2。
8. **数据源**：`data/report_data.json`（与现有 Prompt Lab 一致）。
9. **铁律**：PDF 生成流程完全不触碰。

***

## Verification Steps

1. **语法**：`python -c "import app; import evaluation_rules"` 通过。
2. **推导单测**：对 `data/report_data.json` 跑 `build_evaluation_view`，核对：

   * 009 情绪稳定性总分 20 → eval `情绪不稳定`（来源：档位字段）

   * summary `with_eval + derived + pending == total`。
3. **API**：`GET /api/prompt-lab/evaluation`（登录）返回 200 + items + summary。
4. **下载 API**：POST 调整后 items + include\_raw=true → 返回 .md，含 raw\_value 与有效评价；include\_raw=false → 仅有效评价。
5. **页面**：`/prompt-lab` 中栏出现「AI 解读 | 有效评价」tab：

   * 点「有效评价」展示交互表格，四维分组，下拉可改，raw 只读。

   * 勾选复选框 + 点下载 → 浏览器下载 .md，内容反映调整后的有效评价与复选框状态。

   * 切回「AI 解读」功能不受影响。
6. **未登录**：无 session 访问两 API → 403。
7. **铁律自查**：`git diff --name-only` 确认未改 `_generate_report.py`、`extract.py`、`prompts/ai_interpreter.md`、`db.py`。

