# Agent F 指令包：UI Audit 后的 Polish 清单（2.0 上线前最后一轮）

> 来源：2026-10-15 对本地运行的 2.0 全站做了一轮 impeccable audit（桌面 1280/移动 393/窄屏 820 三视口实测截图 + 代码级检查）。本文档即审计报告 + 修复指令，交给执行 agent 照单操作。
> 单一事实来源：`docs/superpowers/specs/2026-10-14-y4-platform-2.0-design.md`（spec）。本包全部是**精修（refinement）**：保留现有视觉世界与功能，不做任何 redesign。

## 审计健康分：12/20（Acceptable — 针对性修复后可达 Good）

| 维度 | 分 | 关键发现 |
|---|---|---|
| Accessibility | 2 | img alt 齐全、导航折叠按钮有 aria 状态、表单有 label；但焦点可见性弱（admin.css 仅 1 处 focus 规则）、错误页是裸 403 |
| Performance | 2→3 | 服务端渲染轻量；Tailwind Play CDN 为已接受决策；无懒加载问题 |
| Theming | 3 | `--y4a-*` CSS 变量令牌体系存在且用得不错；但 Tailwind inline config 在 admin layout 与 student base 各写一份（漂移风险） |
| Responsive | 2 | 学生端移动端**优秀**；管理端任务表在支持的 1280px 下徽章已竖排折断，窄屏无兜底 |
| Implementation Integrity | 3 | 新系统整体连贯；有双标题、双品牌区、裸 403 等局部缺陷 |

**总体判断**：骨架与品牌方向是对的，学生端（client-facing 面）质量高。问题集中在管理端的表格密度与若干一致性细节。没有 P0。

## 禁止事项

- 不改 OCR 红线文件（spec 第 2 节）；不改部署文件
- 不改任何业务逻辑/路由行为，本包只动模板与 CSS（唯一例外见 P1-2，需动 `app.py` 一处）
- **与 E 包的协调**：E 正在运行。涉及 `app.py` 的 P1-2（CSRF 豁免）**必须等 E 完成后执行**；其余模板/CSS 项与 E 无冲突，可先行
- 不改 dashboard / y4_signals 等旧页的**内部**设计语言（D 包决策：只换壳，内部样式保留）
- 不引入新依赖、不加构建链

## 发现清单与修复指令

### P1 — 上线前必须修

**[P1-1] 问卷任务列表徽章竖排折断（1280px 下即发生）**

- 位置：`static/admin.css:353` `.y4a-badge`；`templates/questionnaires/assignments.html`（状态列 line 63-65 区域）
- 现象：状态徽章「已发送/已提交/已驳回」逐字竖排；「发放方式」列「链接+账号」折成三行；学生姓名「於凌伊」折行、「Y4-0004」折成「Y4-/0004」；来源徽章「人工」竖排
- 根因：`.y4a-badge` 无 `white-space: nowrap`；表格列宽无约束，内容挤压
- 修复：
  1. `.y4a-badge` 加 `white-space: nowrap;`
  2. `.y4a-table` 的关键列加 `white-space: nowrap`（学生、编号、状态、发放方式列；原因列允许换行）
  3. 编号列（Y4-XXXX）用 `font-variant-numeric: tabular-nums` + nowrap
  4. 全表加 `min-width`（约 1080px）+ 外层容器 `overflow-x: auto`，窄屏横向滚动而不是挤碎
- 验证：1280px 与 1440px 下徽章单行显示；820px 下表格横向滚动、内容不折断

**[P1-2] 管理端已登录的浏览器里打开学生登录页 → 裸 403**

- 位置：`app.py` `_csrf_protect()`（约 line 110-124，`CSRF_EXEMPT_PATHS` 定义处）
- 现象：顾问/管理员登录态下访问 `POST /student/login` 被拒 403，页面只显示 "403 Forbidden"。真实场景会踩到：顾问发链接前自己先试、演示给客户看
- 根因：CSRF 校验在 `session['user_id']` 存在时生效，而 `/student/login` 是 pre-auth 端点，不在豁免清单
- 修复：`CSRF_EXEMPT_PATHS` 加入 `"/student/login"`（该端点本就由登录限流保护，CSRF 对 pre-auth 表单无意义）。顺手确认 `/student/logout`（若存在 POST）在学生 session 下正常
- ⚠️ **等 E 包跑完再改这一处**（E 正在动 app.py）
- 验证：管理端登录状态下，同一浏览器打开 /student/login 提交 → 302 进 /student/home

### P2 — 本轮修完

**[P2-1] 页面双标题**

- 位置：`templates/students.html`、`templates/dashboard.html` 等页内有自己的大标题（serif H1），与 `templates/layouts/admin.html` 顶栏的 `page_title` 重复
- 修复：统一策略——**顶栏已承载页面名时，页内不再重复同名 H1**；页内保留副标题/描述行即可。逐页检查：students、dashboard、y4_signals、six_am、transcript、internal、prompt_lab、admin_bookings、index(generate)
- 注意：dashboard 的 serif 大标题是其 editorial 内部风格的一部分（只换壳决策）——dashboard 保留页内标题、**从顶栏隐藏该页 page_title**，二选一，别两处都在

**[P2-2] 侧边栏单项目分组标签重复**

- 位置：`templates/layouts/admin.html` 侧边栏
- 现象：「报告生成」组标签下方紧跟同名子项「报告生成」（学生/工作台同理）
- 修复：单项目分组不渲染组标签，直接渲染该项（与多项目组视觉对齐：组标签只在有 ≥2 个子项时出现）

**[P2-3] 侧边栏品牌区双重 branding**

- 位置：`templates/layouts/admin.html` 顶部
- 现象：logo 图（本身含"凭远APP·ARK WORK HARD·DREAM BIG"字样）右侧又排了"凭远教育 / Y4 综合测评"两行文字，拥挤重复
- 修复：logo 图 + 一行文字（"Y4 综合测评"）即可；或换 `branding/logo_inline.png` 横版 logo 单独使用。选一种，保持克制

**[P2-4] 学生端作答页缺学生姓名（spec 符合性）**

- 位置：`templates/student/q_form.html`（及账号模式作答页）
- 依据：spec 6.6"每份问卷作答页顶部显示学生姓名+问卷标题（确认身份防填错）"——当前只有问卷标题
- 修复：标题区加一行"学生：{姓名}（{student_code}）"，样式低调（次级文字）

**[P2-5] 时间戳显示精度过高**

- 位置：`templates/student/` 完成记录、学生 360 问卷 tab、`questionnaires/assignments.html`
- 现象："2026/10/15 04:30:40" 秒级时间戳直接展示
- 修复：列表统一显示到分钟（`YYYY-MM-DD HH:MM`）或仅日期；提交时间类保留分钟。做一个 Jinja filter（如 `dt_short`）全局复用，不要每处各写

**[P2-6] 键盘焦点可见性弱**

- 位置：`static/admin.css`（focus 规则仅 1 处）
- 修复：加全局 `:focus-visible { outline: 2px solid var(--y4a-brand); outline-offset: 2px; }`（按钮/链接/输入/徽章点击区）；验证 Tab 键顺序走完工作台 → 学生列表 → 档案页 tab 切换 → 任务表行内按钮，焦点全程可见

**[P2-7] 画像 tab 数值可读性**

- 位置：学生 360° 档案页画像 tab（`templates/students/` 或 D 包对应模板）
- 现象：百分位类指标（如"认知能力百分位 95"）是纯数字裸表，134 项扫读困难
- 修复（轻量，不做图表库）：value 为 0-100 数值且指标名含"百分位"的行，数值旁加一条 CSS 进度条（`--y4a-brand` 填充）；其余行不动
- 边界：text 档位值（如"较低"）保持文本样式

### P3 — 顺手修

- **[P3-1] favicon 缺失**：每页请求 `/favicon.ico` 404。把品牌 logo 缩一个 32px PNG/ICO 放 `static/`，在两个 layout 的 `<head>` 加 `<link rel="icon">`
- **[P3-2] `GET /logout` 404**：现在只有 `POST /api/admin/logout`（`blueprints/auth.py:46`）。加一个 `GET /logout` 路由做登出并跳 `/login`（用户直接敲 URL 的场景）
- **[P3-3] Tailwind 令牌双份定义**：`templates/layouts/admin.html` 与 `templates/student/base.html` 各自内联 tailwind config。抽成 `templates/layouts/_tailwind_config.html` 共享 include，防止色板漂移
- **[P3-4] 403/404 裸错误页**：注册 Flask errorhandler 渲染品牌化的简洁错误页（沿用学生端纸感样式），至少覆盖 403/404/500

### 数据卫生（上线前人工核对，非代码）

- 本地库有测试残留：学生"回归改名"、"测试学生"，问卷任务原因列含"c8 待确认列表验证""冒烟测试"等字样。**确认生产迁移用的是干净库**，或上线前清理测试学生/任务记录

## 任务执行顺序

1. P1-1（纯 CSS/模板，先行）
2. P2-1 ~ P2-7（模板为主）
3. P3 各项
4. **E 包完成后**：P1-2（app.py 一处）
5. 全部完成后按下面验收走一轮

## 验收标准

- [ ] 1280px 下任务列表所有徽章单行、无竖排；820px 下表格横向滚动不挤碎
- [ ] 管理端登录态同浏览器可完成学生登录（302 到 /student/home）
- [ ] 任意页面无"双标题"；侧边栏无重复组标签、品牌区单一
- [ ] 作答页顶部显示学生姓名+编号
- [ ] 全站时间戳不再出现秒级显示
- [ ] 仅用 Tab 键能走完：登录 → 工作台 → 学生列表 → 档案页六个 tab → 任务表行内按钮，焦点可见
- [ ] 百分位指标有视觉条；文本档位不受影响
- [ ] favicon 不再 404；`GET /logout` 可用；403/404 为品牌化页面
- [ ] 回归：报告生成、问卷作答提交、规则发布、dashboard、预约——全部不受影响（本包零业务逻辑改动，理论上不该坏，坏了说明改错了地方）

## 正面清单（做得好的，保持）

- 学生端问卷作答页/登录页：移动端体验、品牌呈现、大触控目标、"提交后不可修改"预期管理——client-facing 面已达上线水准
- 识别规则页：版本管理（draft/published/archived）+ JSON 校验 + 试算，完整度超出预期
- 题库页信息架构清晰，真实题库（6 份）已导入
- 令牌体系：`--y4a-*` CSS 变量 + Tailwind 令牌方向正确
- 空状态设计统一（工作台各区块）
- token sha256 存储、CSRF before_request 统一拦截的架构选择正确
