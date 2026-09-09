# Y4 仪表盘重构 — 编辑式叙事 + 深度分析

## Summary

将 `/dashboard` 从模板化卡片网格重构为**编辑式叙事页面**(NYT 数据新闻风格):滚动驱动的叙事结构,大标题+嵌入式图表+非对称布局,黑白红强对比,scroll-triggered 动画。同时深化数据分析三个维度:**指标分布**(各维度内指标的得分分布)、**个体画像对比**(学生间四维侧写对比)、**维度间关联**(跨维度共现强度)。

---

## Current State Analysis

### UI 问题
- 统一卡片网格(4 列 stat row / 3 列 chart row / 2 列 grid)→ 模板感强
- 居中对齐 + 均匀 padding → 无视觉节奏
- 所有 section title 用 `::after` 分隔线 → 千篇一律
- 无滚动动画、无交互层次 → 静态死板
- hero 的 `text-transform: uppercase` + `letter-spacing` → AI 模板标签

### 数据分析问题
- **dimension_trends.weak_pct 全为 0**:因为按"学生是否有弱项"计算,仅 1 份报告 + 1 学生,dimension_of 与 derive_evaluation 逻辑不一致
- **dimension_summary 有真实数据**(心力 87% 健康 / 精力 100% / 学习力 91.7% / 生涯力 94.3%)但来源是指标级别,未在页面充分展示
- **co_weak 矩阵全为 0**:1 名学生无法计算跨维度共现
- **无指标分布**:只显示弱项数,不显示全样本中各指标的得分分布
- **无个体对比**:所有学生被聚合成一个数字,无法看个体差异
- **无关联分析**:只说"哪些维度弱",不说"哪些维度经常一起弱/强"

### 数据可用(已确认)
- `schema_124` 项只有 7 字段:code, label, value, type, unit, source_pdf, note(无 mean/percentile/score_grade 原始存储)
- `derive_evaluation(code, label, value, norm)` 推导评价,返回 (eval_value, rule_note)
- `pair_score_with_level()` 返回每项:code/label/raw_value/eval_value/dimension
- `student` 对象:name/gender/birthday/test_date/grade/school/teacher/archive_id
- `get_report_raw(report_id)` 返回单份报告完整数据
- `get_student_reports(student_id)` 返回该学生所有报告(支持纵向)

---

## Proposed Changes

### 1. db.py — 新增三个聚合函数

**文件**: `db.py`
**位置**: `get_indicator_aggregates()` 之后

#### 1.1 `get_indicator_distributions() -> Dict`
各维度内指标的**评价分布**:每个维度有多少指标高/中/低/弱,及具体弱项名称。

```python
def get_indicator_distributions() -> Dict[str, Any]:
    """各维度的指标评价分布。
    
    返回:
    {
      "心力": {
        "total": 46, "evaluated": 35,
        "distribution": {"高": 8, "不低": 20, "偏低": 5, "需关注": 2},
        "weak_indicators": [{"label": "情绪稳定性-自卑自尊", "weak_pct": 100.0}, ...],
        "strong_indicators": [{"label": "自我概念-整体", "avg_value": 12.5}, ...]
      },
      ...
    }
    """
```
- 遍历 `all_indicators`(已有),按维度分组
- 每维度:统计各评价等级的数量(distribution dict)
- weak_indicators:weak_pct > 0 的指标,按 weak_pct 降序,取 label + weak_pct(不含 code)
- strong_indicators:most_common_eval 为"高"的指标,按 avg_value 降序,取 label + avg_value

#### 1.2 `get_student_profiles() -> List[Dict]`
每个学生的四维侧写,用于个体对比。

```python
def get_student_profiles() -> List[Dict[str, Any]]:
    """每个学生的四维健康度侧写。
    
    返回:
    [
      {
        "student_name": "Zaylin", "grade": "高一", "school": "世外",
        "gender": "女", "report_date": "2026-08-10",
        "dimensions": {
          "心力": {"healthy": 87.0, "weak_count": 6, "total": 46},
          "精力": {"healthy": 100.0, "weak_count": 0, "total": 11},
          ...
        },
        "overall_health": 90.0  # 四维平均健康度
      },
      ...
    ]
    """
```
- 遍历每份报告的 `schema_124`
- 用 `derive_evaluation()` 推导每项评价
- 按维度统计:弱项数 / 总指标数 → 健康度 = (1 - weak/total) * 100
- overall_health = 四维健康度均值

#### 1.3 `get_dimension_correlations() -> Dict`
维度间关联强度:哪些维度经常一起弱/一起强。

```python
def get_dimension_correlations() -> Dict[str, Any]:
    """维度间关联强度(基于共现)。
    
    返回:
    {
      "pairs": [
        {"dim_a": "心力", "dim_b": "学习力", "co_weak": 3, 
         "total_students": 5, "correlation": 0.6, "strength": "中"},
        ...
      ],
      "matrix": [[1.0, 0.2, 0.6, 0.1], ...],  # 4x4
      "labels": ["心力", "精力", "学习力", "生涯力"]
    }
    """
```
- 对每对学生-维度对,统计同时偏弱的学生数
- correlation = co_weak / min(weak_a, weak_b)(条件概率式)
- strength: >0.6 强 / 0.3-0.6 中 / <0.3 弱

### 2. app.py — 扩展 API

**文件**: `app.py`

#### 2.1 `/api/dashboard/stats` 增加新字段
在现有 `stats` 返回中追加:
```python
stats["indicator_distributions"] = _db.get_indicator_distributions()
stats["student_profiles"] = _db.get_student_profiles()
stats["dimension_correlations"] = _db.get_dimension_correlations()
```

#### 2.2 `/api/dashboard/ai-analysis` 增强提示词
AI 输入增加三部分新数据:
1. 各维度指标分布(高/中/低/弱各多少,哪些指标普遍弱/强)
2. 学生间差异(最健康和最需关注的学生分别弱在哪)
3. 维度关联(哪些维度经常一起偏弱)

AI 输出 JSON 格式不变,但 insights 覆盖更广:
```json
{
  "dimension_summary": "...",
  "insights": [
    {"headline": "...", "detail": "...", "type": "distribution|comparison|correlation"}
  ]
}
```
新增 `type` 字段让前端区分洞察类型,不同类型用不同视觉处理。

### 3. dashboard.html — 编辑式叙事重写

**文件**: `templates/dashboard.html`
**操作**: 全文重写

#### 设计原则
- **非对称布局**:section 左右交替,有的全宽有的半宽
- **大标题叙事**:Noto Serif SC,32-48px,每个 section 有一个叙事性标题
- **图表嵌入正文**:图表不是独立卡片,而是嵌入在文字段落之间
- **scroll-triggered 动画**:Intersection Observer 触发 fade-up,错落延迟
- **黑白红对比**:paper 背景 + ink 文字 + red 强调,某些 section 反转(ink 背景 + paper 文字)
- **无统一卡片网格**:去掉 stat-row / chart-row / dim-health / insight-grid 等模板网格

#### 页面结构(从上到下)

**S1. 开篇 — 全宽暗色 hero**
- 深色背景(#1a1a1a),左对齐(非居中)
- 大数字 96px 金色,右侧叙事文字
- 底部一行小字:学生数 · 子测验数 · 时间跨度
- scroll 进入时数字 count-up 动画

**S2. Y4 是什么 — 编辑式段落**
- 左侧 1/3 空白,右侧 2/3 文字
- 大标题"Y4 是什么" + 两段叙事(取自 generate.py 原文)
- 无卡片边框,纯排版

**S3. 关键数字 — 非对称 bento**
- 4 个数字以非对称方式排布(非 4 列等宽)
- 大数字 + 小描述,数字用 Noto Serif SC 48px
- hover 时数字微缩放

**S4. 学生画像 — 嵌入式图表**
- 标题 + 一段引言文字
- 三个图表(年级/学校/性别)横向排列但宽度不等
- 图表无卡片边框,直接嵌在 paper 背景上

**S5. 四维指标分布 — 核心分析 1**
- 标题"四维指标分布"
- 4 个维度横向排列,每个维度一个**堆叠条形图**:
  - 横轴 = 评价等级(高/不低/偏低/需关注)
  - 纵轴 = 指标数量
  - 底部小字列出该维度 Top 3 弱项名称(无编号)
- 维度间用细线分隔,非卡片

**S6. 个体画像对比 — 核心分析 2**
- 标题"学生侧写对比"
- 每个学生一个**迷你雷达图**(四维健康度)
- 横向排列,可滚动
- 雷达下方:学生姓名 + 年级 + 整体健康度
- 最健康和最需关注的学生高亮(红边框)

**S7. 维度间关联 — 核心分析 3**
- 标题"维度关联"
- 4×4 矩阵热力图(已有 SVG,样式升级)
- 右侧:AI 生成的关联解读段落
- 关联强的维度对用红色连线标注

**S8. AI 洞察 — 叙事式卡片**
- 标题"数据洞察"
- insight 卡片非对称排列(非 2 列等宽)
- 每张卡片:大引号 + headline + detail
- type 区分:分布洞察用一种样式,对比洞察另一种,关联洞察第三种
- scroll-triggered 错落进入

**S9. 顾问产出 — 保留优化**
- 横向 bar chart + 表格
- 去掉卡片边框,直接嵌入

**S10. 报告趋势 — 全宽**
- 月度 area chart,全宽,无卡片
- 顶部一行标题

**S11. 学生反馈 — 占位**
- 全宽虚线区,简约文字

#### CSS 关键改动
- 删除所有 `.stat-row` / `.chart-row` / `.dim-health` / `.insight-grid` / `.advisor-grid` 网格
- 新增 `.narrative-section`:max-width 1100px,margin 0 auto,padding 80px 0
- 新增 `.reveal`:opacity 0 → 1,translateY(40px) → 0,Intersection Observer 触发
- 新增 `.stagger-1` / `.stagger-2` / `.stagger-3`:transition-delay 错落
- hero 改为左对齐 + 右侧文字
- section 交替使用 paper 和 ink 背景
- 删除所有 `text-transform: uppercase`
- 删除所有 `::after` 分隔线
- 图表容器无 border,直接嵌在背景上

#### JS 关键改动
- 新增 `IntersectionObserver` 实现 scroll reveal
- 新增 `countUp()` 动画 hero 数字
- `renderIndicatorDistributions()`:4 个堆叠条形图
- `renderStudentProfiles()`:迷你雷达图(Chart.js radar,小尺寸)
- `renderCorrelations()`:升级版 SVG 热力图 + 连线标注
- `renderInsights()`:按 type 分组,非对称排列
- AI 加载完成后,维度总结直接嵌入关联 section 右侧

### 4. Chart.js 配置升级

- 去掉所有图例 border
- tooltip 样式:暗色背景 + 白字 + 圆角
- 网格线更淡(#EDE8DE)
- 字体大小微调:labels 11px → 12px,更易读
- 堆叠条形图:4 色阶梯(高=绿/不低=灰/偏低=橙/需关注=红)

---

## Assumptions & Decisions

1. **数据稀疏处理**:当前仅 1 份报告,分布/对比/关联都会是单点。代码健壮处理,渲染时显示"数据积累中"而非空图表。随报告增加自然丰富。
2. **编辑式叙事**:参考 NYT 数据新闻,非 Linear/Vercel 暗色仪表盘。scroll-driven,非交互式仪表盘。
3. **无新外部库**:不引入 GSAP/ScrollTrigger,用原生 IntersectionObserver + CSS transition。Chart.js 保留。
4. **三个分析维度**:指标分布(堆叠条) + 个体对比(迷你雷达) + 维度关联(热力图),覆盖用户全部需求。
5. **AI 洞察 type 字段**:让前端按类型差异化渲染,减少模板感。
6. **不修改 get_dashboard_stats() 现有字段**:只追加新字段,不破坏已有。
7. **count-up 动画**:hero 数字从 0 增长到目标值,2 秒 ease-out。

---

## Verification Steps

1. 未登录 → 重定向 `/login`
2. 登录后页面渲染:
   - hero 左对齐,数字 count-up 动画
   - scroll 时各 section 错落 fade-up
   - 四维指标分布:4 个堆叠条形图,底部弱项名称
   - 个体画像:学生迷你雷达图横向排列
   - 维度关联:4×4 热力图 + AI 解读
   - AI 洞察:非对称卡片,按 type 分样式
3. `/api/dashboard/stats` 返回 indicator_distributions / student_profiles / dimension_correlations
4. `/api/dashboard/ai-analysis` 返回 insights 含 type 字段
5. 页面无统一卡片网格,无 uppercase,无 ::after 分隔线
6. 响应式:768px 下 section 变单列,图表不溢出
7. 空数据(0 报告):显示"数据积累中"而非崩溃
