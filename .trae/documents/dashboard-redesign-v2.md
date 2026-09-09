# 仪表盘 v2 — 去 AI 化 + 数据分析深化

## Context

当前仪表盘 (`templates/dashboard.html`) 存在两个核心问题：

1. **UI 过于 AI 化**：暗色 hero + 亮黄大数字、"eyebrow + heading + lede" 三段式模板、彩色类型标签、装饰性引号、统一 scroll-reveal 渐显、交替的区块背景色 — 这些都是典型的 AI 生成模板痕迹。需要遵循现代网页设计规范：fluid（流动）、interactive（交互）、contrast（对比）、高级、清晰。

2. **数据分析维度不够**：目前只有 distribution / comparison / correlation 三类维度级分析，停留在四维汇总层面，没有触及 134 个具体指标，也没有学生群体结构分析。用户已确认要新增三类分析：**指标级趋势**、**学生聚类画像**、**维度平衡度**。

## 改动范围

三个文件：
- [db.py](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/db.py) — 新增 3 个聚合函数
- [app.py](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/app.py) — 扩展 `/api/dashboard/stats` 和 `/api/dashboard/ai-analysis`
- [templates/dashboard.html](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/dashboard.html) — 整页重写

不动：`evaluation_rules.py`、`style.css`、base 模板、其他页面。

---

## 一、数据分析深化（db.py + app.py）

### 新增 3 个聚合函数（db.py，接在 `get_dimension_correlations` 之后）

#### 1. `get_indicator_trends() -> Dict`
**目的**：直接展示 134 个具体指标中最常偏弱/偏强的 Top 项，支持悬停查看是哪些学生。

返回结构：
```python
{
  "most_frequently_weak": [
    {
      "code": "009", "label": "情绪稳定性总分", "dim": "心力",
      "weak_count": 5, "total_count": 8, "weak_pct": 62.5,
      "weak_students": ["张三", "李四", ...]  # 哪些学生弱
    }, ...  # Top 8
  ],
  "most_frequently_strong": [
    {
      "code": "002", "label": "认知能力百分位", "dim": "学习力",
      "strong_count": 6, "total_count": 8,
      "strong_students": [...]
    }, ...  # Top 5
  ],
  "total_indicators_evaluated": 134,
  "total_with_weak": 28,
}
```

**实现要点**：复用 `get_indicator_aggregates()` 的中间数据，但需要额外记录每个弱项指标对应的学生姓名列表（当前 `get_indicator_aggregates` 不存学生名）。新函数内独立遍历 reports，对每个指标维护 `weak_students` 列表。受学生数较多时截断（每指标最多展示 10 个学生名）。

#### 2. `get_cluster_patterns() -> Dict`
**目的**：按学生弱项签名（哪些维度有弱项）把学生分组，展示每组的共性和人数。

返回结构：
```python
{
  "clusters": [
    {
      "signature": "心力+学习力",     # 弱项维度组合
      "students": ["张三", "李四"],
      "count": 2,
      "overall_health_avg": 62.3,    # 该组平均健康度
      "is_common": true              # 是否为高频组合 (count >= 2)
    }, ...
  ],
  "total_students": 8,
  "balanced_count": 3,  # 无弱项的学生数
  "balanced_students": [...]
}
```

**实现要点**：基于 `get_student_profiles()` 的 `dimensions[d]["weak_count"]`，构造每个学生的弱项维度集合（frozenset），按集合分组。空集合归为 "balanced"。按 count 降序排列。

#### 3. `get_dimension_balance() -> Dict`
**目的**：计算每个学生四维健康度的方差/平衡度，识别「严重失衡型」学生。

返回结构：
```python
{
  "students": [
    {
      "student_name": "张三",
      "grade": "10年级",
      "dimensions": {"心力": 80.0, "精力": 45.0, "学习力": 75.0, "生涯力": 90.0},
      "overall_health": 72.5,
      "balance_score": 75.0,        # 1 - (std/max_std)，越高越平衡
      "is_imbalanced": true,         # balance_score < 60
      "weakest_dim": "精力",
      "strongest_dim": "生涯力",
      "gap": 45.0                    # max - min
    }, ...
  ],
  "avg_balance_score": 68.2,
  "imbalanced_count": 2
}
```

**实现要点**：基于 `get_student_profiles()`，对每个学生计算四维健康度的标准差，归一化为 0-100 的 balance_score（std 越大越不平衡）。`is_imbalanced` 阈值取 60。

### 扩展 `/api/dashboard/stats`（app.py L1027-1035）

在现有返回中追加 3 个字段：
```python
stats["indicator_trends"] = _db.get_indicator_trends()
stats["cluster_patterns"] = _db.get_cluster_patterns()
stats["dimension_balance"] = _db.get_dimension_balance()
```

### 扩展 `/api/dashboard/ai-analysis`（app.py L1038-1158）

1. **丰富 `data_summary`**：在现有维度分布/学生对比/维度关联之后，追加：
   - 【指标级趋势】：Top 5 最常偏弱指标的名称 + 弱项学生数
   - 【学生聚类】：每个非空弱项组合的人数 + 平均健康度
   - 【维度平衡】：平均平衡度 + 失衡学生数 + 最失衡学生的弱项维度

2. **新增 insight type**：
   - `indicator`：关于具体指标的洞察（哪个指标最常弱，影响哪些学生）
   - `cluster`：关于学生群体的洞察（某类弱项组合的共性）
   - `leverage`：关于杠杆点的洞察（改善哪个维度/指标最能提升整体）

   在 system prompt 的 `type 取值` 列表里追加这 3 类，并要求生成 4-6 条 insights，覆盖至少 4 种 type。其他硬规则不变（无新术语、无编号、无 markdown、无心理学造词）。

---

## 二、UI 重写（dashboard.html）

### 去 AI 化原则

移除以下 AI 模板痕迹：
- 暗色 hero + 亮黄大数字 → 改为纸底大字 + 红色 accent
- "eyebrow + heading + lede" 三段式 → 改为嵌入式叙事，标题直接驱动
- 彩色类型标签（it-distribution/it-comparison/it-correlation）→ 移除，用排版区分
- 装饰性引号 → 移除
- 统一 scroll-reveal 渐显 → 改为按需的 progressive disclosure（sticky 标题、悬停展开、点击详情）
- 交替区块背景色 → 统一纸底，用细分隔线和留白做分层
- Chart.js 默认配色 → 收敛到 ink/red/灰阶，移除多色彩虹

### 现代设计要点

- **大字编辑式排版**：标题用 Noto Serif SC 48-64px，正文 16-18px，数字用 JetBrains Mono
- **流动非对称布局**：打破 4 列等分网格，用 12-col grid 做刻意的不对称（7/5、8/4、3/9）
- **交互式数据点**：指标卡片悬停展开学生名单；学生聚类卡片可点击展开成员；平衡度卡片悬停显示弱项维度
- **scroll-driven 叙事**：sticky section index（左侧固定导航），右侧滚动内容；段落进入视口时数据点高亮
- **对比强化**：黑/红/纸 三色，无渐变，无多余色块；用字重和字号做对比，不用颜色
- **清晰留白**：section 间 96-120px，段落 24px，数据点 8px

### 新页面结构（11 个 section）

1. **Hero**：纸底，左对齐大数字（报告总数）+ 一行说明，无暗色背景
2. **Context paragraph**：嵌入式数据点（X名学生、Y所学校、Z个年级），inline 而非卡片
3. **四维概览**：4 维健康度横条（横向 bar），最强/最弱维度用红字标注
4. **指标级趋势**（NEW）：Top 8 最常偏弱指标列表，每项悬停展开弱项学生名单；右侧 Top 5 强项
5. **学生聚类画像**（NEW）：按弱项签名分组的卡片，显示签名 + 人数 + 平均健康度，点击展开成员
6. **维度平衡度**（NEW）：散点图（x=整体健康度, y=平衡度），失衡学生红点高亮
7. **学生侧写对比**：保留但简化 — 单页内可滑动的雷达图列表，无彩色 tag
8. **维度间关联**：保留 heatmap 但改为纸底黑字，无暗色背景
9. **AI 洞察**：叙事段落（非卡片），insight 内嵌数据点，无类型标签
10. **顾问产出**：极简表格，移除条形图
11. **趋势时间轴**：保留月度报告数折线，简化样式

### 关键交互实现

- **指标悬停展开**：每个指标行 `data-students="张三,李四"` 存 JSON，CSS `:hover` 显示 tooltip
- **聚类点击展开**：`details/summary` 原生组件或 JS toggle
- **散点图**：用 SVG 手写（不需要 Chart.js），点悬停显示学生名
- **sticky section index**：左侧 `position: sticky; top: 80px` 的目录，高亮当前 section

---

## 三、验证

1. 重启 Flask 服务（`gunicorn` 或 `python app.py`，端口 8000）
2. 访问 `http://localhost:8000/dashboard`，确认：
   - 页面无暗色 hero，无黄色大数字
   - 无 "eyebrow + heading + lede" 三段式
   - 无彩色类型标签、无装饰引号
   - 指标级趋势 section 悬停可展开学生名单
   - 学生聚类 section 可展开看成员
   - 平衡度散点图显示且失衡学生高亮
3. 调用 `curl localhost:8000/api/dashboard/stats`（需先登录），确认返回新增 `indicator_trends` / `cluster_patterns` / `dimension_balance` 三个字段
4. 调用 `curl localhost:8000/api/dashboard/ai-analysis`，确认 AI 返回 4-6 条 insights 且覆盖至少 4 种 type
5. 视觉对比：页面应像 NYT 数据新闻，而非 AI 模板
