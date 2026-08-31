# 学生档案 AI 解读（精简版：用已存数据解读 + 结果存在报告上）

## Summary

在学生档案页每份报告新增「AI 解读」：

* 数据源 = 数据库里已保存的 raw data（`reports.data_json`），不重跑 OCR、不依赖 report\_data.json 文件

* 解读结果直接存到 `reports` 表新列 `interpretation`，重新解读即覆盖

* 不建新表、不做历史版本、不做删除接口 —— 最小实现

## Current State Analysis

* raw data 已按报告存于 `reports.data_json`；`db.get_report_raw(report_id)`（db.py:252-268）可直接复用取数

* DashScope 调用模式（app.py:1123-1146 prompt-lab 同款）：OpenAI 兼容接口 + `qwen-plus` + 120s timeout，system = `prompts/ai_interpreter.md` + schema\_124 逐行上下文（app.py:383-390 格式）

* SQLite 列迁移沿用 `_migrate_schema()` 现有模式（db.py:94-137，PRAGMA 检查 + ALTER TABLE）

* students.html 报告行已有「原始数据/下载 JSON/删除」按钮，AI 输出渲染复用 prompt\_lab.html:404-421 轻量 markdown 函数

## Proposed Changes

### 1. db.py（3 处小改动）

* `Report` 模型加一列：`interpretation = Column(Text)`

* `_migrate_schema()` 加一条迁移：`("interpretation", "ALTER TABLE reports ADD COLUMN interpretation TEXT")`

* 新增 `save_interpretation(report_id, content, model)`（UPDATE 那一行）

* `get_student_reports()` 返回结果中加 `"interpretation"` 字段，前端列表直接可读

### 2. app.py — 仅 1 个新路由

`POST /api/reports/<int:report_id>/interpret`（`@admin_required`）：

1. `get_report_raw(report_id)` 取数据（404 if 无）
2. 复用 schema\_124 → 文本上下文格式
3. DashScope 调用（与 prompt-lab 同模式），成功后 `save_interpretation(...)` 存列
4. 返回 `{ok, reply, model}`
5. `/api/chat`、prompt-lab 代码零改动

### 3. templates/students.html

* 报告行加「AI 解读」按钮

* 点击：该行数据里已有 `interpretation` 就直接展示（markdown 渲染 + 白底卡片）；无则自动触发解读

* 卡片内「重新解读」按钮 → POST 后覆盖显示（按钮置灰"解读中..."，10-30s）

* 不做历史切换、不做删除

## Verification

1. 语法检查 app.py / db.py
2. 本地启动实测：未登录 403；登录后对现有报告触发解读 → 返回内容且存入列；刷新页面仍在
3. 确认 /api/chat、prompt-lab diff 为零
4. commit + push

