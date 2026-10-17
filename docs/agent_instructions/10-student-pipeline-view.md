# Agent J 指令包：学生管线视图 + 学生 360° 阶段化

> 「管线驾驶舱」 redesign 第三包。方向契约见 `08-global-interaction-layer.md` 头部。本包落地签名动作：**学生管线**——让每个学生在哪个阶段、卡了多久，一眼可见。

## 1. 背景与目标

需求方核心诉求（原文）："Visualize the student pipeline stages and each student's status"。

两个改动：

1. **学生列表页升级**：顶部管线阶段栏（计数 + 点击筛选），每行带阶段 chip 与停留时长
2. **学生 360° 档案页**：头部加阶段进度指示 + "下一步建议"行动区

## 2. 前置依赖

- **08 包完成**（密度/动效/反馈规范）；09 包完成后接入更佳（工作台队列与本包阶段共用同一套推导函数）
- A–G 包完成

## 3. 阶段模型（核心设计，零 schema 变更，纯查询层推导）

**2026-10-17 裁决：拆成两套语义**——「现在先处理谁」（待办优先级）与「学生走到哪」（生命周期进度）不再共用一个顺序。

### 3.1 待办优先级视图（`compute_stages()`）

`/students` 阶段栏、`/workspace` 最近活跃学生使用。一个学生同一时刻只属于一个阶段，取**最靠前的未完成动作**：

| 阶段 | key | 判定（按优先级从上到下，命中即归） | 颜色 |
|---|---|---|---|
| 问卷待确认 | `pending_approval` | 有 status='pending' 的 assignment | warning 黄 |
| 等待学生作答 | `awaiting_student` | 有 status='sent' 的 assignment | brand 红 |
| 待生成报告 | `awaiting_report` | 近 30 天有 completed booking 且无任何 report | brand 红 |
| 预约待测评 | `booked` | 近 30 天有 pending booking | 中性 ink-soft |
| 报告已生成 | `reported` | 有 report，无 pending/sent 任务、也无近期待处理预约 | success 绿 |
| 已就绪 | `ready` | 其余（新建学生、全部流程走完） | 中性 |

### 3.2 生命周期进度视图（`compute_progress(student_id)`）

学生 360° 档案页顶部 stepper 使用。学生沿固定顺序单向推进：

`booked 预约待测评 → report 生成报告 → minutes 会议纪要 → pending_approval 问卷待确认 → awaiting_student 等待学生作答 → ready 已就绪`

- `minutes` 是**可选**节点：没有纪要时不阻塞问卷；一旦存在问卷任务或纪要，生命周期继续前进。stepper 上该节点带「可选」badge。
- 最新/当前有效问卷 `submitted` 后进入 `ready`；历史 `expired/rejected` 不阻塞，但若没有更新的 `submitted`，仍需回到问卷处理。
- **Six A.M. 不是独立阶段**：不占 stepper 节点，只在报告落库后作为后台更新，以 chip 展示（未落库显示「后台更新中」，落库显示「已更新 · v{version}」）。

- "停留时长"：待办视图按 3.1 取对应动作时间；生命周期视图取该阶段起始动作时间（booked 取预约时间，report 取 completed booking 时间，minutes/pending_approval 取 report 创建时间，awaiting_student 取最早 sent 时间，ready 取 submit/学生创建时间）。≥5 天在 chip 旁显示天数（warning 色）
- 推导函数在 `pipeline.py`：`compute_stages() -> {student_id: {stage, since, days, since_label}}` 与 `compute_progress(student_id) -> {stage, since, days, since_label, six_am}`——**一次聚合查询**（join bookings/reports/assignments 各取所需聚合值后内存推导），禁止 N+1
- Advisor 视角：先经 `visible_student_filter` 过滤学生集再算阶段

## 4. 现状文件地图

| 文件 | 说明 |
|---|---|
| `templates/students.html`（40KB） | 学生列表（D 包迁移后：搜索框、状态筛选 pill、卡片式行） |
| `blueprints/students.py` | 学生路由 + 360° 页 + tab 懒加载 API（`/students/<code>/api/*`）+ 08 包加的 `/api/students/search` |
| `templates/` 学生 360° 模板 | D 包所建（六 tab：画像/报告/问卷/预约/纪要/6AM），文件名以实际为准（`student_profile.html` 或 students/ 下） |
| `db.py` | students/reports/bookings 查询函数；assignments 查询在 `questionnaire_store.py` |

## 5. 禁止事项

- 零 schema 变更；不改 OCR 红线；不改学生端页面
- 不新增图表库（阶段栏/进度条全部 CSS/HTML）
- 遵守 08 规范（骨架屏/loading/Toast/动效/密度）
- 列表页现有功能（搜索、筛选 pill、导出 CSV、编辑、删除、新建议程）一个不能丢

## 6. 任务分解

### 6.1 学生列表页管线化

- [ ] 页面顶部加**阶段栏**：五个阶段的横向 rail——每段：阶段名 + 大号计数 + 占比细条（brand/语义色）。点击某段 = 筛选列表到该阶段（与现有搜索框、状态 pill 叠加生效，URL query 保持可分享 `?stage=awaiting_student`）
- [ ] 每行加**阶段 chip**（阶段名 + 停留天数 ≥5 天时显示"· N 天"）；chip 颜色按上表
- [ ] 行 hover 浮现快捷操作（淡入 150ms）：查看档案 / 重生成 PDF / 发起问卷任务（链到该生 360° 页对应操作）
- [ ] 列表加载骨架屏（08 规范）
- [ ] 空态区分：无学生（"还没有学生，去生成第一份报告"）/ 该阶段无学生（"这个阶段目前没有学生" + 清除筛选链接）
- [ ] 服务端：列表端点支持 `stage` 参数过滤；阶段栏计数一次性随页返回

### 6.2 学生 360° 页头部阶段化

- [ ] 档案页头部卡下方加**阶段 stepper**：六段水平步骤条（顺序见 3.2），当前阶段高亮（brand 实心圆点 + 连线进度），已完成阶段 ✓，未来阶段灰色；`minutes` 节点带「可选」badge；stepper 下方一行 muted 小字："当前：等待学生作答 · 已 3 天"，其后可跟 Six A.M. 状态 chip
- [ ] stepper 右侧（或下方）**下一步建议卡**：按生命周期阶段给出主行动：
  - report → "测评后上传 PDF 生成报告" + 按钮 `去生成报告`（`/generate`）
  - minutes → "可补充会议纪要，也可直接处理问卷" + 按钮 `去写会议纪要`（`/tools/transcript`）
  - pending_approval → "有 N 份问卷待确认" + 按钮 `去确认`（09 工作台队列 `/workspace`）
  - awaiting_student → "等待学生完成《问卷名》" + 按钮 `分发信息` / 过期时 `重新生成链接`
  - booked → "已预约 {最近时段}，测评后上传 PDF" + 按钮 `去生成报告`
  - ready → 不显示该卡
- [ ] 数据源：360° 页视图函数调 `compute_progress()` 取该生生命周期阶段（`stage_meta` 传 `PROGRESS_STAGES`）；建议卡的数据从既有 tab 端点复用（不新增写端点）

### 6.3 工作台联动（若 09 已完成）

- [ ] 工作台"最近活跃学生"表格加阶段 chip 列（复用同一徽章组件样式）

## 7. 验收标准

- [ ] `/students` 顶部五段阶段栏计数正确（与数据库手工核对一次）；点击"等待学生作答"只剩该阶段学生，URL 带 `?stage=awaiting_student` 可分享
- [ ] 每行阶段 chip 正确；造一个 ≥5 天的 sent 任务显示"· N 天"warning 色
- [ ] Advisor 登录：阶段栏计数与列表都只有自己学生
- [ ] 360° 页 stepper 与当前阶段一致；各阶段建议卡的按钮链接可用
- [ ] 搜索 + 状态 pill + 阶段筛选三者叠加正确
- [ ] 回归：导出 CSV、编辑、删除、新建议程、重生成 PDF 不变

## 8. 常见坑

- 阶段推导的边界：学生同时有 pending 和 sent 任务时归 pending_approval（更靠前）；booking 只看未过期/最近的，别把一年前的旧预约算成"预约待测评"——取最近一次 booking 且其日期不早于 30 天前（在推导函数注释里写明这个启发式）
- 聚合查询注意 SQLite/PG 双兼容（用 SQLAlchemy Core 表达式）
- 阶段栏计数与列表筛选必须同源（同一次 `compute_stages()` 结果），别分两次查导致数字对不上
- 360° 页是懒加载 tab 架构——stepper 数据随首屏注入即可，不要塞进某个 tab 的 API

## 9. 遗留观察

- **推导函数落在新文件 `pipeline.py`**：`compute_stages()` 需要同时读业务表（pending/sent 任务、booking、report）与问卷子系统的 token，若放进 `blueprints/students.py` 会与 `questionnaire_store` 形成反向依赖；单开一个无蓝图依赖的推导模块，`blueprints/students.py` 只调用，保持查询层与路由层分离。
- **booked 阶段取近 30 天启发式**：按指令包 §8「常见坑」的要求，booking 只取最近一次且 `created_at` 不早于 30 天前、状态非 cancelled 的记录，避免一年前的旧预约把学生错误归入「预约待测评」。常量 `_BOOKING_LOOKBACK_DAYS=30` 已在 `pipeline.py` 内注释说明，后续若要调整窗口只改这一处。
- **行 hover 快捷操作复用既有操作组**：指令包要求行级 hover 露出快捷入口，实现上是对既有 `.sc-actions` 操作组整体加 `y4a-row-actions` 类做淡入（150ms，`@media(hover:none)` 常显），未新增任何按钮或写端点——核心功能零改动。
- **阶段 chip 放在「状态 / 阶段」列**：学生列表是 5 轨 grid（`minmax(140px,1.05fr) / minmax(0,1.25fr) / minmax(110px,.7fr) / minmax(196px,224px) / 264px`），若为阶段单独加轨会挤压既有列。做法是把阶段 chip 与状态 pill 同列堆叠，表头由「状态」改为「状态 / 阶段」，栅格定义不变。
- **阶段栏计数服务端注入 + 客户端过滤**：计数由 `stage_counts()` 在服务端算好随首屏注入（保证与列表同源），点击只看客户端 `s => s.stage === currentStage` 即时过滤并把 `?stage=` 同步进 URL（`history.replaceState`，不整页刷新）；`/api/students` 亦支持服务端 `?stage=` 供独立取数，两条路径共用同一 `compute_stages()`。
- **360° 建议卡复用既有写端点**：`action_kind` 为 `package` 时复用问卷子系统的 `/package`、`/reissue`（过期时「重新生成链接」），未新增任何写端点，`link`/`create` 两种仅做前端跳转。
