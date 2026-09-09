# Y4 数据总览仪表盘 (Data Dashboard)

## Summary

新建一个独立的 admin 仪表盘页面 `/dashboard`,以图形化、直观的方式展示 Y4 测评系统迄今为止的全部成果。页面包含:头条数字(测试总数 = 报告数 × 4)、学生构成分布、四维趋势与跨维度共现模式、顾问报告产出排行(含相似名检测),并预留学生反馈数据位。

技术选型:**Hybrid 可视化** — 头条数字与 hero 统计用自定义 SVG/CSS;数据密集图表(雷达图、趋势线、分布柱状图)用 Chart.js (CDN)。页面 **admin-only**,复用 `page_login_required` 装饰器与现有设计系统 (`style.css` tokens)。

---

## Current State Analysis

### 数据来源(已确认)
- **数据库**:`data/y4_students.db`(SQLite),通过 `db.py` SQLAlchemy 访问
- **核心表**:
  - `students` (id, name, gender, birthday, grade, email, phone, **advisor_name**, school, single_parent, created_at)
  - `reports` (id, student_id, report_date, pdf_path, **data_json**, interpretation, created_at)
  - `bookings` (id, student_name, student_id, ..., **advisor_name**, school, single_parent, created_at)
- **报告数据结构**(`reports.data_json`):`{student: {name, gender, grade, school, test_date, teacher, archive_id, ...}, schema_124: [{code, label, value, source_pdf, score_grade, mean, ...}, ...], sections: [...4 sections...]}`
- **四维归类逻辑**:`evaluation_rules.py` 的 `dimension_of(item)` 函数,按 label 关键词或 `source_pdf` (A2→心力, B3/B4→学习力, B6→生涯力) 将指标归入 心力/精力/学习力/生涯力

### 现有 UI 系统(已确认)
- **设计 tokens** (`templates/style.css`):`--paper:#FAF7F2`, `--ink:#141414`, `--red:#B33A3A`, `--line:#D9D2C5`, `--ease`
- **字体**:Noto Serif SC (标题) + Inter (正文) + JetBrains Mono (数字)
- **组件**:`.topbar` + `.topbar-nav`、`.card`、`.btn`、`.page-title`、`.container` (max-width:1100px)、table、badge
- **导航**:每个 admin 模板各自硬编码 `.topbar-nav`,无共享 include
- **鉴权**:`page_login_required` (页面→重定向 /login) 与 `admin_required` (API→403 JSON)

### 关键发现
- 当前测试库仅 2 学生、1 报告、2 预约;生产环境数据更多,代码须健壮处理空数据
- `students.advisor_name` 当前为空,但 `bookings.advisor_name` 有值("Test Advisor"、"王顾问")。顾问聚合需同时取 students + bookings 两个来源
- `/api/generate` 接受 1-4 份 PDF,但用户明确要求头条 = 报告数 × 4(Y4 框架标准 = 4 子测验),故固定乘 4

---

## Proposed Changes

### 1. 新建 `db.py` 聚合函数

**文件**: `db.py`
**操作**: 新增 `get_dashboard_stats() -> Dict[str, Any]` 函数

逻辑:
1. **头条数字**: `SELECT COUNT(*) FROM students`、`SELECT COUNT(*) FROM reports`;`total_subtests = total_reports * 4`
2. **学生构成**: 按 `gender`、`grade`、`school` 分组聚合(从 `students` 表)
3. **顾问产出**:
   - 从 `reports JOIN students` 按 `students.advisor_name` 聚合 report_count
   - 再从 `bookings.advisor_name` 补充(以 report 关联的 student 为主,bookings 为辅)
   - 每位顾问:report_count、student_count(去重)
4. **相似名检测**:
   - 规范化: `name.lower().strip()` + 折叠内部空白 + 移除常见标点
   - 按规范键分组;若一个规范键对应多个不同原始名 → 标记 `variants`
   - 对未归并的不同规范名,计算 Levenshtein 相似度;相似度 > 0.7 且 < 1.0 → 标记 `review_needed` 并给出合并建议
   - 返回 `advisor_performance` (已归并的 canonical 列表) + `advisor_name_review` (需人工确认的疑似重复对)
5. **维度趋势**:
   - 遍历每份 `reports.data_json` → `schema_124` 数组
   - 对每个 item 调用 `evaluation_rules.dimension_of(item)` 归入四维
   - **弱项判定**(启发式):
     - `score_grade` ∈ {"偏低","明显偏低","严重偏低","需关注","需特殊关注"} → 弱
     - 或 `value`/`mean` 均为数字且 `value < mean * 0.85` → 弱
     - 或 `percentile` 为数字且 `< 40` → 弱
   - 每学生每维度:是否有至少 1 个弱项 → 该维度对该学生"偏弱"
   - 聚合:每维度偏弱学生数、Top 5 高频弱项指标(code+label+dim+count)
   - **跨维度共现**:4×4 矩阵,`co_weak[a][b]` = 同时在 a 和 b 维度有弱项的学生数(对角线 = 单维度弱项学生数)
6. **时间线**: 按 `report_date` 的年月分组,统计每月 report_count、distinct student_count
7. **反馈占位**: 返回 `{available: false, note: "学生反馈数据接入后将在此展示"}`

返回单个 JSON 对象,包含上述全部字段。空数据时返回零值/空数组,不报错。

### 2. 新增路由

**文件**: `app.py`
**操作**: 在现有路由块附近新增两个路由

```python
@app.route("/dashboard")
@page_login_required
def dashboard_page():
    return render_template("dashboard.html")


@app.route("/api/dashboard/stats")
@admin_required
def api_dashboard_stats():
    return jsonify({"ok": True, "stats": _db.get_dashboard_stats()})
```

位置:放在 `/students` 路由附近(app.py L1003 区域),保持 admin 页面路由分组一致。

### 3. 新建仪表盘页面

**文件**: `templates/dashboard.html` (新建)
**结构**:

```
<head>
  - Google Fonts (Noto Serif SC + Inter + JetBrains Mono)
  - <link rel="stylesheet" href="/style.css" />
  - <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
  - <style> 仪表盘专属样式(见下) </style>
</head>
<body>
  <div class="brand-stripe"></div>
  <header class="topbar">
    <div class="brand">凭远教育 Y4测评</div>
    <nav class="topbar-nav">
      ← 主页 / 学生档案 / 预约管理 / 报告生成 / 数据总览(active)
    </nav>
  </header>

  <div class="container container-wide">  ← max-width: 1400px

    <!-- 1. HERO 头条区 (自定义 SVG/CSS) -->
    <section class="hero">
      <div class="hero-label">Y4 测试总数</div>
      <div class="hero-number">{total_reports × 4}</div>  ← JetBrains Mono, 巨大字号
      <div class="hero-sub">
        <span>{total_students} 名学生</span>
        <span>{total_reports} 份报告</span>
        <span>每份报告 = 4 项子测验</span>
      </div>
    </section>

    <!-- 2. 要点卡片 (自定义 CSS stat cards) -->
    <section class="stat-row">
      <card>主导年级 → {most_common_grade} ({count})</card>
      <card>最活跃顾问 → {top_advisor} ({report_count} 份)</card>
      <card>最常见薄弱维度 → {weakest_dim} ({count}/{total} 学生)</card>
      <card>测评时间跨度 → {earliest} ~ {latest}</card>
    </section>

    <!-- 3. 学生构成 (Chart.js) -->
    <section class="card-grid">
      <card>性别分布 → doughnut chart</card>
      <card>年级分布 → bar chart</card>
      <card>学校分布 → horizontal bar chart</card>
    </section>

    <!-- 4. 四维趋势 (Chart.js + 自定义 SVG heatmap) -->
    <section>
      <card>四维偏弱学生占比 → radar chart (4 轴: 心力/精力/学习力/生涯力)</card>
      <card>高频弱项指标 Top 5 → horizontal bar chart (按维度着色)</card>
      <card>跨维度共现矩阵 → 自定义 SVG 4×4 heatmap</card>
    </section>

    <!-- 5. 顾问产出 (Chart.js + table) -->
    <section>
      <card>顾问报告数排行 → horizontal bar chart</card>
      <table>顾问 | 学生数 | 报告数</table>
      <div class="name-review" (if review_needed)>
        ⚠ 发现疑似重复顾问名,请确认:
        <ul>{variants} → 建议合并为 {canonical}?</ul>
      </div>
    </section>

    <!-- 6. 时间线 (Chart.js) -->
    <section>
      <card>报告生成趋势 → line/area chart (按月)</card>
    </section>

    <!-- 7. 学生反馈占位 -->
    <section class="card feedback-placeholder">
      <div class="empty">学生反馈数据接入后将在此展示</div>
    </section>

  </div>
  <script> fetch('/api/dashboard/stats') → 渲染全部 section </script>
</body>
```

**专属样式**(在 `<style>` 块内,复用 tokens):
- `.container-wide { max-width: 1400px; }` — 仪表盘更宽
- `.hero` — 大留白居中区,`.hero-number` 用 JetBrains Mono,`font-size: 72px`,`color: var(--ink)`,下方红色细分隔线
- `.stat-row` — `display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px;`
- `.stat-card` — 白底卡片,大数字 + 小标签,hover 微抬升
- `.card-grid` — `display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px;`
- `.chart-wrap` — 固定高度容器 `height: 280px;` 内放 `<canvas>`
- `.heatmap` — SVG 网格,色阶从 `--paper-2`(弱)到 `--red`(强)
- `.feedback-placeholder` — 虚线边框,灰字提示
- 响应式:`@media (max-width: 1024px)` → stat-row 2 列;`@media (max-width: 768px)` → 单列
- Chart.js 全局默认:font family = Inter,色板 = `[--red, --ink, #8A8A8A, #D9D2C5]`,grid color = `--line-soft`

**JS 逻辑**:
- `fetch('/api/dashboard/stats')` 一次性拉取
- 渲染 hero 数字 → stat cards → 6 个 Chart.js 实例 → heatmap SVG → name review
- 加载态:spinner + "加载中…"
- 错误态:`.status.error` 提示
- Chart.js 配置:禁用动画过度、tooltip 样式匹配设计系统、legend 用 Inter 字体

### 4. 导航链接注入

**文件**: `templates/students.html`、`templates/admin_bookings.html`、`templates/transcript.html`、`templates/index.html`
**操作**: 在各自 `.topbar-nav` 中新增一条链接,匹配现有格式:

- students.html: `<a href="/dashboard">数据总览</a>` (无 data-path 模式)
- admin_bookings.html: `<a href="/dashboard" data-path="/dashboard">数据总览</a>` (有 data-path 模式)
- index.html: `<a href="/dashboard" data-path="/dashboard">数据总览</a>`
- transcript.html: `<a href="/dashboard">数据总览</a>`

位置:放在 `.topbar-nav` 最后一条 `<a>` 之后,`</nav>` 之前。保持各模板原有格式(有/无 data-path)。

---

## Assumptions & Decisions

1. **×4 固定**:用户明确要求头条 = 报告数 × 4(Y4 框架标准 4 子测验),即使部分报告由 <4 份 PDF 生成也按 4 计。后续如需精确可改为按 `source_pdf` 去重计数。
2. **鉴权**:admin-only,`page_login_required` + `admin_required`,与 `/students`、`/generate` 一致。
3. **弱项判定为启发式**:基于 `score_grade` + `value<mean*0.85` + `percentile<40`。指标原始 `score_grade` 可能为空(当前测试数据如此),此时靠 `value/mean` 兜底。该阈值可在后续迭代调整,不影响页面结构。
4. **顾问来源**:以 `reports JOIN students.advisor_name` 为主,`bookings.advisor_name` 为辅(用于顾问名规范化与去重检测)。
5. **相似名检测**:规范化(小写+去空白)捕获大小写/空格变体;Levenshtein 相似度 >0.7 捕获书写差异(如"王顾问" vs "Wang顾问")。疑似重复仅标注提示,不自动合并(需用户人工确认)。
6. **学生反馈占位**:仅渲染空状态卡片,不创建数据表或接入逻辑。待用户后续提供反馈数据结构后再实现。
7. **可视化**:Chart.js 4.x via CDN(jsdelivr),自定义 SVG/CSS 用于 hero 数字、stat cards、heatmap。不引入其他库。
8. **不修改**:PDF 生成逻辑、AI 逻辑、E4 工作流、现有路由行为。

---

## Verification Steps

1. **启动服务器**后,未登录访问 `/dashboard` → 重定向到 `/login?next=/dashboard`
2. 登录后访问 `/dashboard` → 页面正常渲染,hero 数字 = `reports.count × 4`
3. `GET /api/dashboard/stats` 返回完整 JSON,包含 `headline`、`student_makeup`、`advisor_performance`、`advisor_name_review`、`dimension_trends`、`timeline`、`feedback_placeholder`
4. 各 Chart.js 图表正常渲染(doughnut/bar/radar/line),无 console 报错
5. SVG heatmap 4×4 矩阵正常显示,对角线为单维度弱项数
6. 顾问排行表与柱状图数据一致;若有疑似重复名,`.name-review` 警告框可见
7. 空数据库场景:`stats` 返回零值,页面显示空状态而非崩溃
8. 导航栏在 students/admin_bookings/transcript/index 四个页面均出现"数据总览"链接,点击跳转正确
9. 响应式:窗口缩至 768px 时,stat-row 与 card-grid 变单列,图表不溢出
