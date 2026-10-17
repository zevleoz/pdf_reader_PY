# Agent I 指令包：行动收件箱工作台 + 问卷行内审批 + 推荐理由透明化

> 「管线驾驶舱」 redesign 第二包。方向契约见 `08-global-interaction-layer.md` 头部（Linear 气质、密度、动效规范）。本包把**工作台从静态卡片改造成角色化行动队列**，并让问卷审批**行内完成**。

## 1. 背景与目标

需求方核心诉求（原文）："Each role lands on a prioritized action view (e.g., 'needs your approval', 'awaiting student completion') rather than static data"；"Surface why the system recommends specific assessments"。

三个改动：

1. **工作台 = 行动收件箱**：按"需要动作"排优先级，不再是数据陈列
2. **行内审批**：问卷任务在工作台和任务列表都可以就地确认/驳回，不跳页
3. **推荐理由可见**：每条任务能展开看"为什么推荐"

## 2. 前置依赖

- **08 包完成**（骨架屏/Toast 强化/按钮 loading/动效令牌/密度规范——本包全面使用）
- A–G 包完成

## 3. 现状文件地图（已核对 2026-10-16）

| 文件 | 关键位置 | 说明 |
|---|---|---|
| `blueprints/workspace.py` | 186 行；`workspace_page()` (line 40)；`_pending_questionnaire_tasks()` (54)、`_generation_job()` (89)、`_recent_students()` (135)、`_quick_entries()` (167) | 工作台视图，服务端渲染 |
| `templates/workspace.html` | 159 行 | 四区块：待确认任务表 / 生成作业 / 最近活跃学生 / 快捷入口 |
| `blueprints/questionnaires.py` | 行内审批可直接复用的 API：确认 `POST /api/questionnaires/assignments/<id>/confirm`（151）、驳回 `/reject`（168）、重新生成 `/reissue`（180）、重置密码 `/reset-password`（192）、分发信息 `/package`（204）、查看答案 `/response`（213） | 全部已存在 |
| `questionnaire_store.py` | `list_assignments(status=...)`（439）；assignment dict 含 `reason` 字段（205） | 推荐理由数据源 |
| `templates/questionnaires/assignments.html` | 任务列表页（Alpine 驱动，`/api/questionnaires/assignments` 取数） | 行内审批改造对象 |

## 4. 禁止事项

- 不改数据模型（**零 schema 变更**：`reason` 字段已存在，推荐详情就用它，不加列）
- 不改上述 API 端点的请求/响应契约（行内调用的是现有端点；如响应字段缺前端所需信息，只在**响应里加字段**，不改既有字段语义）
- 不动 OCR 管线、学生端页面、部署文件
- 遵守 08 包规范：骨架屏、按钮 loading、Toast、动效令牌、密度令牌；禁止内联 `style="transition:..."`

## 5. 任务分解

### 5.1 工作台重构为行动收件箱（`workspace.py` + `workspace.html`）

新区块结构（admin/advisor 视角；viewer 仍跳 `/students`，不在本页）：

- [ ] **队列 1「待你确认」**（最优先，顶部）：pending 任务列表。每行：学生名（链接到 360° 页）、编号、问卷名、来源徽章（系统推荐/人工创建）、创建距今。行尾操作：`确认`（brand 实心）+ `驳回`（ghost）。点击行（非按钮区）**展开行内面板**（见 5.2）
- [ ] **队列 2「等待学生完成」**：`list_assignments(status='sent')`——学生、问卷、分发方式徽章、**已等待天数**（confirmed_at 至今；≥5 天显示 warning 色）、链接过期时间（token expires_at，已过期显示 danger 徽章）。行尾操作：`分发信息`（弹层显示可复制文本，复用现有 `/package` 端点）+ `重新生成链接`（过期行高亮此操作）
- [ ] **队列 3「进行中的生成作业」**：保留现有卡片，加 Alpine 轮询——`generation_job.running` 时前端每 3s 拉一次进度（新只读端点 `GET /api/workspace/job`，返回 `_job.json` 摘要；或复用现有 `/api/progress`，先读 `blueprints/reports.py` 核对），完成后 Toast"报告已生成"+ 停止轮询。不新增写操作
- [ ] 「最近活跃学生」降级为页面底部次要区块（保留）；「快捷入口」删除（⌘K 已覆盖此职能）
- [ ] 各队列空态：区分"全部处理完"的积极空态（✓ 图标 + "没有待确认的任务"）与模块未启用态
- [ ] Advisor 视角：所有队列经 `visible_student_filter` 过滤（pending/sent 查询函数已支持 advisor_name 参数，核对后接入）

### 5.2 行内审批面板（工作台 + 任务列表页共用同一交互模式）

- [ ] 展开内容（手风琴，动效走 08 令牌）：
  1. **推荐理由区**：`reason` 全文 + 来源徽章 + "查看该生画像"链接（`/students/<code>` 新标签页）。reason 为空时显示"人工创建，无规则依据"
  2. **分发方式选择**：三个 radio 卡片（一次性链接 / 临时账号 / 两者都要），各带一句说明（"免登录直达，提交后作废，7 天有效" / "学生登录后可分次作答、自动保存进度" / "两种都生成"）
  3. 操作行：`确认并分发`（brand，`.is-loading` 规范）+ `驳回`（danger ghost，二次确认用行内确认态而非浏览器 confirm：点击后按钮变"确认驳回？"2 秒超时还原）
- [ ] 确认成功：fetch POST → Toast 成功 → 该行以 200ms 过渡从"待确认"消失 → 「等待学生完成」队列插入该行（同页状态迁移）；分发信息弹层自动打开（含链接/账号文本 + 一键复制）
- [ ] 失败：行内错误横幅（`.y4a-alert`），不丢展开状态
- [ ] 任务列表页 `/questionnaires/assignments` 同样改造：状态 tab 保留；行展开面板复用同一 Alpine 组件模式；列表加载用骨架屏；所有行内按钮接 `.is-loading`

### 5.3 推荐详情的诚实边界

- [ ] reason 来自规则引擎命中时写的文本（如"情绪稳定性-焦虑子分数 < 5，建议补充焦虑自评问卷"）。**不虚构实测值**：当前数据模型不存触发时刻的指标值；面板里 reason 下方加一行 muted 小字"指标实测值见该生画像页"并链接过去。若执行中发现 C 包已在 assignments 存了结构化命中详情，则在文档末尾"遗留观察"记录，并把它展示出来

## 6. 验收标准

- [ ] 管理员工作台首屏：待确认队列在最上，可直接行内确认（选链接）→ Toast + 行迁移到"等待学生完成"+ 分发弹层打开可复制链接，**全程无页面刷新**
- [ ] 驳回走行内二次确认（无浏览器 confirm 弹窗）
- [ ] 等待 ≥5 天的任务显示 warning 色等待天数；过期链接有 danger 徽章且"重新生成链接"可用
- [ ] 发起一次真实生成作业，工作台进度 3s 轮询实时更新，完成后 Toast 提示
- [ ] Advisor 登录：两个队列只见自己学生的任务
- [ ] 推荐理由展开可见；reason 为空的任务显示兜底文案
- [ ] 回归：任务列表页状态 tab/计数/查看答案/重置密码/题库/规则页全部不变

## 7. 常见坑

- `/package` 端点的响应结构先读代码核对（token 只存哈希，明文只能在 confirm/reissue 的响应里出现一次）——"分发信息"弹层对旧任务可能只有账号信息没有链接明文，此时显示"链接已失效，请重新生成"引导 reissue
- 行内展开面板里嵌表单时注意 CSRF：fetch POST 带 `X-CSRF-Token` 头（模板有 `csrf_token()`）
- 手风琴展开如果用了 `x-show`，高度动画用 `max-height` 过渡或 Alpine collapse 插件思路手写，别引入插件
- 轮询要在页面隐藏时暂停（`document.visibilitychange`），2G 小内存服务器经不起僵尸轮询

## 8. 遗留观察

- `reason` 目前是规则引擎写入的**纯字符串**，未存触发时刻的结构化命中详情（指标实测值）。面板按 5.3 的诚实边界处理：reason 全文 + 来源徽章 + 「指标实测值见该生画像页」链接，**不虚构数值**。若日后 C 包在 assignments 存了结构化命中详情，可在此展示。
- 队列 3 轮询直接**复用现有 `GET /api/progress`**（未新建 `/api/workspace/job`）：其响应已含 `status/percent/message/filename/error`，足以驱动进度条与完成 Toast。
- 「等待学生完成」队列要展示链接有效期，而 `list_assignments` 响应不含 token 过期时间，故新增**只读批量查询** `questionnaire_store.token_expiry_map()`（零 schema，未改任何端点请求/响应契约）。
- 任务列表页的行内审批**替代**了原先的「确认发送」弹窗（`openConfirm`/`doConfirm`/`confirmTarget` 已移除）；驳回的浏览器原生 confirm 改为行内按钮态二次确认（点击 → 「确认驳回？」2 秒超时还原）。驳回按钮对 `sent` 任务保留，避免丢失既有能力。
- 工作台与任务列表页共用同一「行展开面板」交互模式（点击行展开 / 点按钮 `.stop`），但各自独立实现（两个页面分别是 SSR+Alpine 与纯 Alpine fetch 架构，未强行抽公共组件）。

