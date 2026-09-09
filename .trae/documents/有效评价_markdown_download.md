# 有效评价 (Y4 Evaluation) — Markdown 下载能力

## Summary

为 Y4 系统新增一种**非 PDF 的数据输出**：把某份报告的 AI 解读（基于现有 `prompts/ai_interpreter.md` 的 Y4 四维框架提示词）连同学生信息与全部 134 条原始测评数据点，打包成一份结构化的 **Markdown (.md)** 文件，供团队内部传阅使用。

本步为「分步建设」的**第一步**：仅做**下载**能力，不包含站内数据分析看板（能力 #1）与跨域名推送（push 到其他域名），二者留待后续步骤。

产出文件名：`有效评价_{学生姓名}_{报告日期}.md`

---

## Current State Analysis

基于实际代码探索，当前系统已具备以下可复用的能力：

1. **数据库** (`db.py`)
   - `reports` 表已存储：`data_json`（134 条 schema_124 原始数据）、`interpretation`（AI 解读文本）、`pdf_path`、`student_id`、`report_date`。
   - `get_report_raw(report_id)` 返回 `{report_id, student_id, student_name, grade, report_date, raw}`，其中 `raw` 即完整 `data_json` 解析后的 dict（含 `student`、`pdf_titles`、`schema_124`、`sections`、`vision`）。
   - `save_interpretation(report_id, content)` 可写回解读结果。

2. **AI 解读已存在** (`app.py` L1219-1273)
   - `POST /api/reports/<int:report_id>/interpret`（`@admin_required`）：读取该报告 `raw`，用 `prompts/ai_interpreter.md` 作为 system prompt，调 DashScope（`qwen-plus`，可由 `AI_TEXT_MODEL` 覆盖），返回解读并 `save_interpretation` 存库。
   - `/api/chat`（L364-424）：同样使用 `prompts/ai_interpreter.md`，但读取的是 `data/report_data.json`（当前会话数据），非数据库历史报告。

3. **原始数据下载已存在** (`app.py` L1201-1216)
   - `GET /api/reports/<int:report_id>/raw?download=1`：下载**原始 JSON**（未经 AI 处理）。这不是「有效评价」，只是 raw data。

4. **CSV 导出已存在** (`app.py` L1312-1345)：`/api/export` 导出所有报告的扁平 code→value，同样是原始数据。

5. **UI** (`templates/students.html`)
   - 报告卡片按钮行（L229-233 与 L354-358 两处）已有：「AI 解读」「✎ 解读会纪要」「原始数据」「下载 JSON」「删除」。
   - `showInterpretation(reportId)` / `runInterpret(reportId)` 已能触发解读生成与展示。

6. **AI 提示词** (`prompts/ai_interpreter.md`)
   - Y4 四维框架（心力/精力/学习力/生涯力）是唯一语言体系。
   - 提示词第四节定义了 001-085 核心数据点的维度归属；第五节「有效评价转化规则」、第六节「解读流程概览」明确要求 AI 将数据点转化为「有效评价」并引导至 Potential list / Interference。
   - 即：AI 解读文本本身已内含「有效评价」与 Potential/Interference 结论。

7. **数据结构** (`data/report_data.json` 实测)
   - `schema_124` 共 134 条，每条 `{code, label, value, type, unit, source_pdf, note}`。
   - `student`：`{name, gender, birthday, test_date, grade, school, teacher, archive_id, report_code}`。
   - code 范围：001-133（外加 `050a`）。其中 001-085 共 85 条（与提示词映射一致），086-133 共 49 条（多元智能排序、价值观排序、常模平均数等），`050a` 为体质健康-饮食描述。

**结论**：生成「有效评价」所需的原料（学生信息、原始数据、AI 解读）均已落库。本步只需新增一个**打包为 Markdown 的下载端点** + 一个 UI 按钮，无需改写 PDF/AI 既有逻辑。

---

## Proposed Changes

### 1. 新增辅助函数：`_generate_interpretation_for_report(report_id)` — `app.py`

**为什么**：下载「有效评价」时若该报告尚未生成 AI 解读（`reports.interpretation` 为空），需即时生成，保证一键下载即可用。

**怎么做**：在 `app.py` 新增一个**模块级私有函数**（不修改既有 `/api/reports/<id>/interpret` 路由，避免触碰 AI 既有逻辑，符合项目硬约束）：
- 调用 `_db.get_report_raw(report_id)` 取 raw。
- 用与 `api_report_interpret` 完全相同的方式构造 context（`schema_124` 拼成 `code label：value` 行）+ 学生行。
- 读取 `prompts/ai_interpreter.md` 作为 system prompt。
- 调 DashScope（`os.environ.get("AI_TEXT_MODEL", "qwen-plus")`，`temperature` 读 `AI_TEMPERATURE` 默认 0.5，`max_tokens=8192`，`timeout=120`）。
- 成功后 `_db.save_interpretation(report_id, reply)` 落库（后续下载即时可用，免重跑 AI）。
- 返回 `(reply_text, error_or_None)`。

> 注：此函数与 `api_report_interpret` 内联逻辑近似（约 15 行 DashScope 调用）。这是**有意为之的加法式轻量重复**，目的是不修改既有 AI 路由。后续步骤可统一为共享 helper，但本步不动既有路由。

### 2. 新增下载端点：`GET /api/reports/<int:report_id>/evaluation` — `app.py`

**为什么**：这是本步的核心产出——把 raw 数据 + AI 解读打包成 Markdown 下载。

**怎么做**：
- `@app.route("/api/reports/<int:report_id>/evaluation")` + `@admin_required`（与 `/raw`、`/interpret` 同属受保护路由，符合「18 条敏感路由需登录」约束）。
- 流程：
  1. `record = _db.get_report_raw(report_id)`；不存在 → 404。
  2. 取 `raw = record["raw"]`、`student = raw.get("student", {})`、`schema = raw.get("schema_124", [])`。
  3. 取解读：优先 `reports.interpretation`。`get_report_raw` 当前不返回 `interpretation`，故需用 `_db.get_student_reports(student_id)` 中匹配 `report_id` 取 `interpretation`；若为空，调用第 1 步的 `_generate_interpretation_for_report(report_id)` 即时生成。
  4. 调用下方「Markdown 文档结构」拼装 `.md` 文本。
  5. `send_file(BytesIO(text.encode("utf-8")), mimetype="text/markdown", as_attachment=True, download_name=filename)`。
  6. 文件名：`有效评价_{student_name or report_id}_{report_date or ''}.md`。

### 3. Markdown 文档结构（在端点内拼装）

```
# Y4 有效评价 · {学生姓名}

> 凭远教育 · Y4 综合测评系统
> 报告编号：{report_id} | 测评日期：{report_date}

## 一、学生信息
| 项目 | 内容 |
|---|---|
| 姓名 | {name} |
| 性别 | {gender} |
| 出生 | {birthday} |
| 年级 | {grade} |
| 学校 | {school} |
| 测评日期 | {test_date} |
| 顾问 | {teacher} |
| 档案号 | {archive_id} |
| 报告代码 | {report_code} |

（缺字段则该行省略）

## 二、测评数据（按 Y4 四维分组）

### 心力（情绪与动力系统）
- 001 情绪稳定性总值：36
- 002 自尊：12
...（该维度下所有 schema_124 项，格式 `code label：value`）

### 精力（精力管理与身体健康系统）
- 025 ...
...

### 学习力（学习系统）
- 039 认知能力总得分：124
...

### 生涯力（专业与职业发展系统）
- 056 霍兰德 ...
...

（仅输出有 value 的项；value 为空的不列）

## 三、AI 有效评价解读

{interpretation 全文，作为 Markdown 正文直接嵌入；AI 产物本身含有效评价转化与 Potential/Interference 结论}

---
本文件由 Y4 综合测评系统自动生成，供团队内部使用。
```

**维度分组函数 `dimension_of(item)`**（端点内/或模块级辅助，决策完整定义）：
- 输入：一条 schema_124 item `{code, label, ...}`。
- Step 1（code 区间，权威，来自 `ai_interpreter.md` 第四节）：
  - `001-024` → 心力
  - `025-028` → 精力
  - `029-033` → 心力
  - `034-038` → 精力
  - `039-055` → 学习力
  - `056-085` → 生涯力
- Step 2（code 不在 001-085，如 `050a`、`086-133`，用 label 关键词兜底）：
  - label 含 `体质/精力/睡眠/饮食/运动/BMI` → 精力
  - label 含 `情绪/自尊/自我概念/依恋/人格/内驱/自驱` → 心力
  - label 含 `认知/执行/记忆/注意/推理/动机/学习方法/策略/自我效能` → 学习力
  - label 含 `霍兰德/职业/多元智能/价值观/能力优势/生涯` → 生涯力
- Step 3（仍无法判定）按 `source_pdf` 兜底：`A2→心力`，`B4→学习力`，`B3→学习力`，`B6→生涯力`。
- 维度内按 code 升序排列。

> 此分组为「可读性导向」的最佳努力分组；权威的维度结论以第三节 AI 解读为准。086-133 多为排序值与常模平均数，落入兜底分支，不影响解读正确性。

### 4. UI：新增「下载 有效评价」按钮 — `templates/students.html`

**为什么**：让用户从报告卡片直接一键下载，与既有「下载 JSON」「AI 解读」并列。

**怎么做**：在两处报告卡片按钮行（L231-233 区块 与 L356-358 区块，「下载 JSON」按钮之后）各加一行：
```html
<a class="btn btn-sm btn-secondary" href="/api/reports/${r.id}/evaluation" download>下载 有效评价</a>
```
- `download` 属性触发浏览器下载。
- 无需新 JS：浏览器直接请求端点，端点返回 `.md` 附件。
- 若希望按钮在「未生成解读」时也能点（端点会自动生成），保持按钮恒可用即可——这与现有「下载 JSON」一致。如需加载提示，可后续增强，本步从简。

> 注：用户偏好「无 emoji」与极简风格，按钮文案不加 emoji，沿用现有 `btn-sm btn-secondary` 样式，保持与「下载 JSON」视觉一致。

---

## Assumptions & Decisions

1. **格式**：Markdown (.md)。用户确认。理由：纯文本、有结构、可在任意编辑器/Git/Slack 渲染，便于团队内部传阅与粘贴，符合「更高效、更易用」诉求。
2. **内容**：Full structured report（学生信息 + 全部 134 条原始数据按四维分组 + AI 解读全文）。用户确认。Potential/Interference 不单列一节，因其已内含于 AI 解读文本（提示词第六节强制 AI 输出），单列需解析 AI 散文，脆弱，留待后续步骤。
3. **范围**：本步仅交付「下载」端点 + UI 按钮。站内数据分析看板（能力 #1）与跨域名推送（push）留待后续。用户确认。
4. **AI 解读缺失时**：端点自动调用新增 `_generate_interpretation_for_report` 即时生成并落库，保证一键下载可用。该函数为**加法**，不修改既有 `/api/reports/<id>/interpret` 路由（遵守「不修改 AI 逻辑」硬约束）。
5. **鉴权**：新端点加 `@admin_required`，与 `/raw`、`/interpret` 一致，纳入现有 18 条敏感路由保护体系。
6. **维度分组**：code 区间 001-085 权威映射 + label 关键词兜底 + source_pdf 兜底。分组仅服务于可读性，权威结论以 AI 解读为准。
7. **不改动 PDF 生成与既有 AI 路由**：所有变更为新增端点/函数/UI 行，不触碰 `_generate_report.py` 与既有 `/api/reports/<id>/interpret`、`/api/chat` 逻辑。

---

## Verification Steps

1. **启动服务**：本地或服务器重启 Gunicorn，确认无语法错误（`python -c "import app"` 通过）。
2. **登录**：访问 `/login`，登录后进入 `/students`。
3. **选一份已有报告**：点「AI 解读」确认解读已生成（或直接进行下一步）。
4. **点「下载 有效评价」**：
   - 浏览器下载 `有效评价_{姓名}_{日期}.md`。
   - 用 Markdown 预览打开，核对：
     - 一、学生信息表完整（姓名/年级/学校/测评日期等）。
     - 二、四个维度小节齐全，每条 `code label：value`；维度归类合理（001 情绪稳定性在心力；025 精力基础在精力；039 认知在学习力；056 霍兰德在生涯力）。
     - 三、AI 解读全文在列，含 Potential/Interference 表述。
5. **解读缺失场景**：对一份未生成解读的报告直接点「下载 有效评价」，确认端点自动调 AI 生成（约 10-30s）后返回 .md，且再次下载即时返回（已落库）。
6. **未登录访问**：无 session 直接 `GET /api/reports/<id>/evaluation` 应重定向至 `/login` 或返回 403。
7. **文件名中文**：确认中文文件名在浏览器正确编码下载（Safari/Chrome）。
