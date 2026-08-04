# JSN AI (解读师 AI) 扩展方案 — Vercel 可部署版

## 摘要

在**完全不改**现有 `extract.py` / `generate.py` / `data_points.py` 核心管道的前提下，新增独立 `jsn_ai/` 模块与**左右分屏**界面（左：上传输入；右：LLM 解读输出）。JSN AI 三层架构（特征工程 → 方法论规则 → LLM 叙事）产出中文 Markdown，支持导出 MD / PDF / 复制。整套 JSN AI 流程**无状态、可上 Vercel**：PDF 提取/品牌PDF 管道保留本地运行（因依赖 Chrome + 300s 视觉API，不兼容 serverless），JSN AI 端点从请求体读 JSON 即可工作。

---

## 现状分析（Phase 1 探索结论）

### 核心管道（**禁止改动**）
| 文件 | 作用 | Vercel 兼容？ |
|------|------|---------------|
| [app.py](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/app.py) | Flask 入口；`POST /api/generate` 跑 extract→validate→generate | ❌（依赖本地文件系统 + Chrome） |
| [extract.py](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/extract.py) | 视觉 OCR 提取 133 项到 `data/report_data.json`（300s 超时） | ❌（300s 超时 + 文件系统） |
| [data_points.py](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/data_points.py) | 133 项 schema + `USER_DATA` + `apply_report_data()` | ✅（纯数据处理） |
| [generate.py](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/generate.py) | 结构化数据 → 18页品牌 PDF（Chrome headless） | ❌（无 Chrome） |
| [templates/index.html](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/index.html) | 上传 UI（4 槽 + 思维模式输入 + 生成按钮 L173） | ✅（纯静态） |
| [templates/report.html](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/report.html) | 品牌 PDF 模板 | ✅ |

### 结构化数据（JSN AI 唯一数据源）
`data/report_data.json`：
```json
{
  "student": {"name","gender","birthday","test_date","grade","school","teacher","archive_id","report_code"},
  "pdf_titles": ["A2","B3","B4","B6"],
  "schema_124": [{"code":"001","label":"认知能力总得分","value":"115","type":"number","source_pdf":"B4","note":"..."}],
  "sections": [...],
  "vision": {...}
}
```
编号分组见 [data_points.py#L22-L36](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/data_points.py#L22-L36)（020-040 依恋、059-062 思维模式/自驱力、125-133 常模均值）。

### 现有 LLM 调用模式（可复用）
- 环境变量：`DASHSCOPE_API_KEY` / `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `VISION_MODEL_NAME`（[extract.py#L67-L140](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/extract.py#L67-L140)）。
- 最简 `urllib` HTTP 调用范例：[_vision_values_bar.py#L26-L60](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/_vision_values_bar.py#L26-L60)。
- JSN AI 用**文本** LLM，复用同一套 key，默认模型 `qwen-plus`（`JSN_AI_TEXT_MODEL` 可覆盖）。
- 依赖：`requirements.txt` 已含 `openai`、`Jinja2`、`WeasyPrint`、`Flask`、`PyMuPDF`。**不新增依赖**。

### Vercel 部署约束
- Python serverless 函数默认 10s 超时（Pro 60s，max 300s）；JSN AI 文本 LLM 调用约 15-30s → 需 `maxDuration: 60`。
- 仅 `/tmp` 可写；JSN AI 端点须**无状态**：从请求体读 JSON，不依赖本地 `data/` 目录。
- 无 Chrome → 品牌 PDF 生成不可用（本地专属）。
- Flask 可经 `@vercel/python` 运行时部署（`vercel.json` 指向 app.py）。

---

## 拟定改动

### A. 新增独立模块 `jsn_ai/`（核心交付物，零耦合）

```
PDF_converter/
├── jsn_ai/
│   ├── __init__.py            # 公共 API：analyze(report_data: dict) -> {markdown, features, findings}
│   ├── config.py              # 配置：模型名、温度、端点、知识库路径
│   ├── features.py            # 第 1 层：特征工程（纯计算）
│   ├── methodology.py         # 第 2 层：方法论规则引擎
│   ├── knowledge_base.py      # 知识库：规则/范例/风格指南加载与检索
│   ├── llm.py                 # 第 3 层：文本 LLM 调用 + 叙事生成
│   ├── prompts.py             # JSN 风格 system prompt 与 prompt 组装
│   ├── exporter.py            # Markdown → PDF 导出（WeasyPrint，无 Chrome）
│   ├── markdown_lite.py       # 极简 MD→HTML 转换（无外部依赖）
│   └── knowledge/
│       ├── rules.json         # 方法论规则（可编辑、可扩展）
│       ├── examples.json      # 解读范例片段
│       └── style_guide.md     # JSN 写作风格指南
├── templates/
│   └── jsn_ai_report.html     # JSN 解读 PDF 模板（独立于 report.html）
├── vercel.json                # Vercel 部署配置
└── api/                       # Vercel serverless 入口（可选，见 B3）
    └── jsn_ai.py
```

#### A1. `jsn_ai/config.py`
- 读取 `DASHSCOPE_API_KEY` / `OPENAI_API_KEY` / `OPENAI_BASE_URL`（与 extract.py 同源）。
- 新增 `JSN_AI_TEXT_MODEL`（默认 `qwen-plus`）、`JSN_AI_TEMPERATURE`（0.4）、`JSN_AI_MAX_TOKENS`（4096）。
- `KNOWLEDGE_DIR` 指向 `jsn_ai/knowledge/`。
- `IS_VERCEL`：检测 `os.environ.get("VERCEL")` 是否存在，用于禁用本地文件系统依赖。

#### A2. `jsn_ai/features.py` — 第 1 层：特征工程
- 输入：`report_data` dict（含 `schema_124` + `student`）。
- 输出 `FeatureSet` dict：
  - **normalized_indicators**：
    - 有常模均值（125-133 对应 060-062、066-071）→ `个人 - 常模` 差值与方向。
    - 百分位项（002-008、063-065）→ 强弱档（>75 优势 / 25-75 中等 / <25 待提升）。
    - 依恋得分（023-031）→ 按满分（信任50/沟通45/亲近30）转百分比。
    - 思维模式（059）→ <40 固定型 / 40-60 混合 / >60 成长型。
  - **strengths** / **gaps** / **risks** / **protective_factors**：列表。
  - **personality_profile**：大五（015-019）高低排序与组合类型。
  - **career_profile**：Holland 代码（072）+ 前3能力（087-089）+ 前3价值观（110-112）。
- **纯计算**，不调 LLM；可序列化为 JSON。

#### A3. `jsn_ai/methodology.py` — 第 2 层：规则引擎
- 从 `knowledge/rules.json` 加载规则，`evaluate(features) -> List[Finding]`。
- Finding：`{rule_id, name, severity, category, evidence, hint, related_codes}`。
- 内置 8 条规则（全在 `rules.json`，改规则无需改代码）：
  1. 能力-执行落差（认知百分位 002-008 vs 执行功能 063-065）
  2. 情绪稳定性 vs 自我概念（009 vs 051）
  3. 家庭支持 vs 动机（依恋 023-031 vs 自驱力 060-062）
  4. 职业清晰度 vs 开放性（Holland 072+073-778 vs 开放性 015）
  5. 人格交互（大五组合：高神经质+低外倾→内化风险 等）
  6. 保护/风险因子组合（059 思维模式 + 依恋 + 068 自我效能感）
  7. 学习动机深度 vs 表层（066 vs 067 比值）
  8. 体质健康对心理的支撑（042 BMI + 047-048 睡眠 + 049-050 运动）

#### A4. `jsn_ai/knowledge_base.py` — 知识库
- `load_rules()` / `load_examples()` / `load_style_guide()`。
- `retrieve_examples(categories) -> List[dict]`：按 Finding category 检索范例（关键词匹配，预留向量化扩展）。
- `ingest_transcript(text) -> List[dict]`：stub，预留逐字稿摄入（当前仅分句占位存储，不过度工程）。
- `examples.json` 初始 3-5 条示范范例（每个 category 一条）。

#### A5. `jsn_ai/prompts.py` — Prompt 组装
- `SYSTEM_PROMPT`：JSN 人设（资深教育心理学家、Y4 顾问）；强调"基于给定特征与发现做连接与解释，不得编造数据或泛泛人格描述"。
- `build_user_prompt(features, findings, examples, style_guide, student) -> str`：组装三层输出 + 范例 + 风格指南；要求 Markdown 分节（总体印象 / 心力系统 / 精力系统 / 学习力系统 / 生涯力系统 / 保护因子与风险 / 行动建议雏形）。

#### A6. `jsn_ai/llm.py` — 第 3 层：LLM 叙事
- `generate_narrative(report_data: dict) -> str`：`features` → `methodology.evaluate()` → `knowledge_base.retrieve_examples()` → `prompts.build_user_prompt()` → 文本 LLM HTTP 调用（`urllib`，复用 `_vision_values_bar.py` 模式）→ Markdown。
- **离线降级**：API 未配置/调用失败 → 用 Finding hint 拼接结构化 Markdown，文末标注"(离线模式·未经 LLM 润色)"。
- **无状态**：不写本地缓存（Vercel 无持久文件系统）；本地运行时可选缓存到 `data/jsn_ai_cache/`。

#### A7. `jsn_ai/exporter.py` + `jsn_ai/markdown_lite.py`
- `to_markdown(text) -> bytes`：UTF-8 文本。
- `to_pdf(markdown, output_path) -> Path`：`markdown_lite.md_to_html()` 极简转换 → 套 `templates/jsn_ai_report.html` → WeasyPrint 出 PDF（无 Chrome，Vercel/本地通用）。
- `markdown_lite.py`：处理标题/列表/加粗/段落/分隔线，无外部依赖。

#### A8. `jsn_ai/__init__.py` — 公共 API
```python
def analyze(report_data: dict) -> dict:
    """主入口：接收 report_data dict（从请求体或本地JSON）→ 三层处理 → {markdown, features, findings, student}"""
def analyze_from_file(path: Path) -> dict:
    """本地便捷入口：从 data/report_data.json 读取后调 analyze()"""
def export_pdf(markdown: str, output_path: Path) -> Path
```
- 关键：`analyze()` 接收 **dict**（不依赖文件系统），保证 Vercel 可用。

---

### B. 现有文件改动（最小化，纯新增）

#### B1. [app.py](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/app.py) — 新增 3 个 JSN AI 路由（不动现有路由）
在 `if __name__ == "__main__"` 之前新增：
```python
@app.route("/api/jsn_ai/status", methods=["GET"])
def jsn_ai_status():
    """本地模式：检查 data/report_data.json 是否存在；Vercel 模式：返回 {ready:true, mode:'vercel'}"""

@app.route("/api/jsn_ai", methods=["POST"])
def jsn_ai_analyze():
    """无状态：优先从请求体读 report_data JSON；本地若未传则回落到 data/report_data.json
       → jsn_ai.analyze(report_data) → {ok, markdown, features, findings}"""

@app.route("/api/jsn_ai/export_pdf", methods=["POST"])
def jsn_ai_export_pdf():
    """接收 markdown → jsn_ai.export_pdf() 写 /tmp → 返回 PDF 附件"""
```
- lazy `import jsn_ai`（路由函数内），不影响启动。
- 不改 `api_generate` / `index` / `preview` / `download` 任何已有路由与逻辑。
- `/api/jsn_ai` 既支持前端上传 JSON（Vercel 模式），也支持本地自动读 `data/report_data.json`（本地模式）。

#### B2. [templates/index.html](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/index.html) — 改为**左右分屏**布局
**重构 UI 结构**（保留所有现有功能，改为两栏）：
```
┌─────────────────────┬──────────────────────────┐
│   左侧：输入区       │   右侧：JSN AI 输出区     │
│                     │                          │
│  [模式切换 Tab]      │  [Markdown 渲染区]        │
│  · 上传 PDF（本地）  │                          │
│  · 上传 JSON（通用） │                          │
│                     │                          │
│  PDF模式：4个上传槽   │                          │
│  + 思维模式输入       │                          │
│  + [生成并下载PDF]   │                          │
│                     │                          │
│  JSON模式：          │                          │
│  + 拖拽/选择json     │  [下载MD] [下载PDF] [复制] │
│  + [生成解读]        │                          │
└─────────────────────┴──────────────────────────┘
```
- 顶部 `<h1>` + 说明保留。
- `.wrap` 改为 `display:flex; gap:24px;`，左 `.panel-input`（flex:1）、右 `.panel-output`（flex:1.2）。
- **左侧**保留现有 4 个 PDF 上传槽 + 思维模式输入 + "生成并下载综合报告 PDF" 按钮（现有 `SLOTS`/`renderSlots()`/`generate()` 逻辑不变）；新增 Tab 切换到 "上传 JSON" 模式（一个文件选择器接受 `.json` + "生成 JSN AI 解读" 按钮）。
- **右侧**新增 `#jsnPanel`：Markdown 渲染区 + 三个导出按钮（下载 .md / 下载 .pdf / 复制）+ 空状态提示。
- 新增 JS：`switchTab()` / `generateJsnAi()` / `exportJsnMd()` / `exportJsnPdf()` / `copyJsn()` / 极简 `renderMarkdown()`（标题/列表/加粗/段落，无外部库）。
- 页面加载时调 `/api/jsn_ai/status`：本地有 `report_data.json` → 自动启用右侧"生成解读"；Vercel 模式 → 提示用户上传 JSON。
- 现有 `generate()`（PDF 生成）行为完全不变。

#### B3. `vercel.json` — Vercel 部署配置（新增）
```json
{
  "version": 2,
  "builds": [
    { "src": "app.py", "use": "@vercel/python" }
  ],
  "routes": [
    { "src": "/(.*)", "dest": "app.py" }
  ],
  "functions": {
    "app.py": { "maxDuration": 60 }
  }
}
```
- `maxDuration: 60` 确保 JSN AI 的 LLM 调用（15-30s）不会超时。
- Vercel 上 `/api/generate`（PDF 提取）会因无 Chrome/超时而失败 → 前端在 Vercel 模式下隐藏"上传 PDF"Tab，仅显示"上传 JSON"Tab（通过 `/api/jsn_ai/status` 返回的 `mode` 判断）。

---

## 假设与决策

1. **Vercel 部署范围**：JSN AI（结构化数据→文本LLM→Markdown）可上 Vercel；PDF 提取/品牌PDF 管道保留本地运行（Chrome + 300s 视觉API 不兼容 serverless）。前端按环境自动切换可用 Tab。
2. **文本 LLM 模型**：默认 `qwen-plus`（DashScope 中文叙事好且便宜），`JSN_AI_TEXT_MODEL` 可覆盖；复用现有 key。
3. **无新依赖**：MD→HTML 自写极简转换器；PDF 用已有 WeasyPrint；HTTP 用 `urllib`。
4. **JSN AI 无状态**：`analyze(report_data: dict)` 接收内存 dict，不依赖文件系统 → Vercel/本地通用。本地额外提供 `analyze_from_file()` 便捷入口。
5. **左右分屏**：左输入（PDF 模式 / JSON 模式 Tab 切换）、右 LLM 输出。现有 PDF 上传与生成逻辑保留在左侧。
6. **知识库可扩展**：规则全在 `knowledge/rules.json`，新增规则无需改代码。
7. **离线降级**：LLM 不可用时用规则层 Finding 拼接 Markdown，功能不中断。
8. **未来扩展点**：`knowledge_base.ingest_transcript()` stub 预留逐字稿摄入；`__init__.py` 预留 `chat()` / `parent_recommendations()` 接口注释。

---

## 验证步骤

1. **不破坏现有管道（本地）**：
   - `python app.py run` 仍能从 PDF 生成 `output/report.pdf`。
   - 浏览器 `/` 左侧"上传 PDF"Tab，现有"生成并下载综合报告 PDF"行为不变。
2. **左右分屏 UI**：左侧可切 Tab（PDF / JSON），右侧空状态有提示。
3. **JSN AI（本地模式）**：跑过一次 PDF 生成后，点右侧"生成解读"→ `/api/jsn_ai` 读 `data/report_data.json` → 返回中文 Markdown 并渲染到右侧。
4. **JSN AI（JSON 模式）**：左侧"上传 JSON"Tab，上传 `report_data.json` → `/api/jsn_ai` 从请求体读 → 返回 Markdown。**此模式可在 Vercel 工作**。
5. **JSN AI 状态接口**：`GET /api/jsn_ai/status` 本地返回 `{ready:true, mode:'local', student_name:...}`；Vercel 返回 `{ready:true, mode:'vercel'}`。
6. **离线降级**：清空 `DASHSCOPE_API_KEY`，`POST /api/jsn_ai` 仍返回规则版 Markdown（文末标注离线）。
7. **导出**：右侧"下载 .md"得 UTF-8 MD；"下载 .pdf"得可打开 PDF（WeasyPrint）；"复制"复制 Markdown。
8. **知识库扩展**：`knowledge/rules.json` 加一条规则，重启后 `findings` 出现对应 Finding。
9. **Vercel 部署**：`vercel --prod` 部署成功；访问首页只显示"上传 JSON"Tab；上传 JSON → 右侧出 Markdown。
10. **模块隔离**：`grep -r "jsn_ai" extract.py generate.py data_points.py validate.py` 无匹配。
