# Y4 数据总览页面重构 — 呈现式设计

## Summary

将 `/dashboard` 从技术型数据仪表盘重构为面向学生/家长的呈现式总览页面。参考 Y4 PDF 报告的视觉风格(深色 score card + 金色数字、叙事性段落、维度介绍页风格),移除全部指标编号/逐行平均值列表,改为:大标题数字 + Y4 价值介绍 + 关键成就 + 学生画像 + 四维健康度 + AI 洞察(散文式) + 顾问产出 + 趋势 + 反馈占位。

受众:Y4 以外的学生和家长(潜在用户)。基调:项目负责人的成果汇报,内容有料但一眼看懂。

---

## Current State Analysis

### 当前页面问题
1. **四维指标表**(`dim-grid` + `ind-table`):逐行列出 58 个指标的编号(001-134)、名称、均值、评价标签、弱项比 — 这正是用户明确要求去掉的
2. **AI 分析**用 markdown 格式输出(### 单维度趋势 / ### 跨维度关联 / ### 值得关注的模式),每条末尾标注指标编号 — 过于技术化
3. **hero** 已改为显示报告总数(上一轮完成),但样式偏普通白底卡片
4. stat cards 仍有"最常见薄弱维度"等技术标签
5. 整体缺乏 Y4 品牌叙事感

### Y4 PDF 报告风格参考(已确认)
- **dark-score-card**:`#2A3B4C` 深蓝底 + `#FFD166` 金色大数字,用于 headline figures ([report.html L29-37](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/report.html#L29-L37))
- **section-intro**:编号 + 英文副标题 + 分隔线 + 叙述段落 + ● bullet points ([report.html L74-82](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/report.html#L74-L82))
- **intro-card**:白底 + 左侧 3px 红边,叙述性段落 ([report.html L27](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/report.html#L27))
- **Y4 叙事**:"Y4 是凭远从四个相互关联的成长系统出发,对青少年当前状态、发展资源和潜在困难形成的综合画像" ([generate.py L448](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/generate.py#L448))

### 数据可用(已确认)
- `get_dashboard_stats()`:headline / highlights / student_makeup / advisor_performance / timeline / dimension_trends(含 weak_pct)
- `get_indicator_aggregates()`:134 指标按维度分组,有 weak_pct — 可用于聚合到维度级别但不逐条显示
- AI 分析:`/api/dashboard/ai-analysis` 用 qwen-turbo,6 秒返回

---

## Proposed Changes

### 1. 重写 dashboard.html — 呈现式布局

**文件**: `templates/dashboard.html`
**操作**: 全文重写,保留 Chart.js CDN

**新布局(从上到下)**:

#### 1.1 Hero — 深色 score card 风格
- 背景:`#2A3B4C` 深蓝(复用 report 的 dark-score-card 配色)
- 大数字:`#FFD166` 金色,报告总数,JetBrains Mono 96px
- 副标:"Y4 综合测评完成概览",白色
- 三个子统计:学生数 / 子测验数 / 时间跨度,白色小字
- 顶部 4px 红色条(`#B33A3A`)

#### 1.2 Y4 简介 — intro-card 风格
- 白底卡片,左侧 3px 红边(复用 report 的 `.intro-card`)
- 2-3 句叙事,取自 generate.py L448-456 的核心表达:
  - "Y4 是凭远从四个相互关联的成长系统出发,对青少年当前状态、发展资源和潜在困难形成的综合画像。"
  - "Y4 不以单一分数定义学生,而是通过心力、精力、学习力、生涯力四个系统之间的联系,理解一个真实、复杂并且仍在发展中的青少年。"
- 不加 bullet points,纯段落

#### 1.3 关键数字 — 4 张 stat card
- 学生总数
- 覆盖学校数(distinct school count)
- 年级跨度(min~max grade)
- 测评月数(timeline.length)
- 移除"最常见薄弱维度"(对家长而言过于技术化)
- stat card 样式:白底,大数字用 Noto Serif SC,描述用平实中文

#### 1.4 学生画像 — 整合式可视化
- 一个 section,标题"学生画像"
- 三张并排卡片:年级 / 学校 / 性别
- 每张:小标题 + doughnut 或 bar chart,Chart.js
- 比当前更紧凑,去掉多余的 dash-card-title 套层

#### 1.5 四维健康度 — 雷达 + 叙事
- 标题"四维健康度"
- 左侧:雷达图(4 轴:心力/精力/学习力/生涯力),数据 = 各维度"健康学生占比"(100 - weak_pct)
- 右侧:AI 生成的维度总结(一段散文,无编号无 markdown 头)
- **不显示任何指标编号或逐行列表**

#### 1.6 AI 洞察 — 发现卡片
- 标题"数据洞察"
- 3-5 张"发现卡片",每张:
  - 小标题(一句话,如"精力与学习力的正向关联")
  - 正文段落(2-3 句解释)
- 卡片样式:白底,左侧 3px 红边,hover 微抬升
- **无编号,无 markdown 格式,纯散文**
- 异步加载,加载时显示简洁 loading

#### 1.7 顾问产出 — 保留但优化
- 横向 bar chart + 明细表
- 保留相似名检测警告(用户明确要求)
- 样式微调匹配新整体风格

#### 1.8 报告趋势 — 保留
- 月度 area chart,样式微调

#### 1.9 学生反馈 — 占位
- 虚线卡片,简化文字

#### 1.10 移除的元素
- `dim-grid` + `ind-table` 全部删除
- `ai-section` 的 markdown 渲染(`renderMd` 函数)删除,改为卡片渲染
- 所有英文大写副标题已在上轮移除,继续不出现

### 2. 修改 AI 分析 API — 输出结构化洞察

**文件**: `app.py` (`/api/dashboard/ai-analysis` 端点,L1039-L1105)
**操作**: 修改 system prompt 和输出解析

**新 system prompt 要点**:
- 角色:Y4 项目负责人,向学生和家长做成果汇报
- 输入:聚合指标数据(维度级别的 weak_pct 和 top 弱项)
- 任务:生成 3-5 条数据洞察 + 1 段维度总结
- 硬规则:
  1. 禁止创造新术语(保留 E4 naming rule)
  2. **禁止出现指标编号**(如 009、063),只用中文名称
  3. 禁止 markdown 标题(###),禁止 bullet 符号
  4. 用平实语言,面向非专业受众
  5. 每条洞察有明确的数据依据,但不暴露原始编号
  6. 正确示例:"精力维度表现较弱的学生,在学习力的执行功能上也普遍偏低,说明身体状态直接影响学习效率"
  7. 错误示例:"009 情绪稳定性总分偏低与 063 执行功能偏低同时出现"

**输出格式改为 JSON**:
```json
{
  "dimension_summary": "一段话总结四维整体健康度",
  "insights": [
    {"headline": "一句话标题", "detail": "2-3 句解释"},
    ...
  ]
}
```
- 后端用 `json.loads()` 解析 AI 返回(在 ```json 代码块内),容错处理
- 前端按 JSON 渲染发现卡片

### 3. 修改 AI 输入数据 — 维度级别而非逐条指标

**文件**: `app.py` (`/api/dashboard/ai-analysis`)
**操作**: 修改构建 `data_summary` 的逻辑

当前逻辑(L1049-1064):逐条列出每个指标的编号+名称+均值+评价+弱项比。

改为:只传维度级别汇总:
```
【心力】共 X 个指标,偏弱比例 Y%,常见偏弱项:情绪稳定性、自我概念
【精力】共 X 个指标,偏弱比例 Y%,常见偏弱项:睡眠习惯、运动习惯
...
```
- 用 `get_indicator_aggregates()` 的 `by_dimension` 数据
- 每维度:指标总数、偏弱指标数、偏弱比例、Top 3 弱项中文名称(不含编号)
- 跨维度:哪些维度同时偏弱的学生数

### 4. db.py — 补充 dimension summary 数据

**文件**: `db.py`
**操作**: 在 `get_indicator_aggregates()` 返回中增加 `dimension_summary` 字段

```python
"dimension_summary": {
    "心力": {"total": 30, "weak": 5, "weak_pct": 16.7, "weak_names": ["情绪稳定性总分", "自我概念", ...]},
    "精力": {...},
    ...
}
```
- `weak_names`:取 weak_pct > 0 的指标 label(不含 code),按 weak_pct 降序,最多 3 个

---

## Assumptions & Decisions

1. **受众**:学生和家长(非 Y4 内部人员),需移除所有技术细节(编号、均值、评价标签)
2. **AI 输出改为 JSON**:比 markdown 更易渲染为卡片,减少 AI 感
3. **维度级别数据**:不逐条传指标给 AI,只传维度汇总 + 弱项中文名称,AI 基于此生成散文
4. **保留雷达图**:用"健康占比"(100-weak_pct)而非"弱项占比",正向表达更适合家长
5. **Y4 叙事取自 generate.py**:直接用报告原文的核心表达,保证品牌一致性
6. **deep-score-card 配色**:复用 report.html 的 `#2A3B4C` + `#FFD166`,让页面与 Y4 报告视觉统一
7. **不修改 db.py 的 get_dashboard_stats()**:headline/student_makeup/advisor/timeline 数据结构不变,只改 indicators 的展示方式
8. **保留 Chart.js**:学生画像 + 雷达 + 顾问 + 趋势 用 Chart.js,AI 洞察用纯 HTML 卡片

---

## Verification Steps

1. 未登录访问 `/dashboard` → 重定向 `/login`
2. 登录后页面渲染:
   - Hero 深蓝底 + 金色报告总数
   - Y4 简介卡片显示叙事段落
   - 4 张 stat card 显示学生数/学校数/年级跨度/月数(无"薄弱维度"卡)
   - 学生画像 3 张 chart 正常
   - 四维健康度雷达图显示健康占比,右侧 AI 总结段落
   - AI 洞察 3-5 张卡片,无编号无 markdown 头,纯散文
   - 顾问产出 + 趋势 + 反馈占位正常
3. `/api/dashboard/ai-analysis` 返回 JSON:`{dimension_summary, insights: [{headline, detail}]}`
4. 页面无任何指标编号(001-134)出现
5. 无英文大写副标题
6. 无 emoji
7. 响应式:768px 下卡片变单列
8. AI 调用 6-10 秒内返回(qwen-turbo)
