# Agent B 指令包：管理端 UI 框架 —— Tailwind + Alpine 新布局 + 工作台首页

> 五个实施包中的第二个。单一事实来源：`docs/superpowers/specs/2026-10-14-y4-platform-2.0-design.md`（下称 spec）。冲突时以 spec 为准并向需求方确认。

## 1. 背景与目标

Y4 平台 2.0 要求管理端从"自绘 vanilla JS 壳"升级为现代管理工具体验。技术决策已确认（spec 1.3）：**保留 Flask + Jinja 服务端模板，引入 Tailwind CSS + Alpine.js（均 CDN，无 Node 构建链）**。

本包产出**全部后续包依赖的 UI 地基**：

1. 新 base 模板 `templates/layouts/admin.html`（侧边栏 + 顶栏 + 内容区 + Toast）
2. **Layout 契约**：block 名称、CSS/JS 引入约定、Alpine 组件约定 —— C 包（问卷中心）与 D 包（页面迁移）照此写模板
3. 工作台首页 `/workspace`（spec 5.2）
4. 登录页视觉升级（配合 A 包的账号密码表单）
5. 设计规范（色彩/字体/间距/组件），供 C/D 遵守

## 2. 前置依赖

- **A 包**：登录 session 结构（`session['role']` / `session['display_name']` / `session['advisor_name']`）用于顶栏与导航角色过滤
- A 未完成时可先做的部分：布局骨架、设计规范、静态原型（用假数据）；角色过滤与真实登录态等 A 完成后接入

**本包对 C/D 的接口承诺**：第 5 节的 Layout 契约一经确定不得变更字段名；如需扩展，新增 block 而不是改名。

## 3. 现状文件地图（已核对）

| 文件 | 说明 |
|---|---|
| `templates/app_shell.js` | 现有壳：vanilla JS 动态注入侧边栏，`defer` 加载，挂载点 `[data-app-shell]`；NAV 定义在文件头部（现有分组：工作台/预约中心/解读/内部工具）。**本包不删不改它**（D 包迁移完、E 包才删） |
| `templates/app_shell.css` | 壳样式；品牌色：`#FAF7F2`（暖白底）、`#D25454`（品牌红）、`#161310`（墨色） |
| `templates/style.css` | 全局样式令牌，同色系 + 语义色（`#16A34A` 绿等） |
| `templates/login.html` | 单密码表单（A 包改为账号+密码，本包负责视觉） |
| `branding/` | `logo_red.png` `logo_color.png` `logo_inline.png`（横版）`watermark.jpg` |
| `static/` | `logo.png`、`logo_inline.png`、`css/`、`webfonts/`（自托管字体已存在，优先复用） |
| `templates/landing.html` | 公开落地页，**不动** |
| `templates/booking.html` | 公开预约页，**不动** |
| `app.py` → A 包后为 `blueprints/workspace.py` | `/workspace` 打桩路由（A 包建立），本包填充 |

## 4. 禁止事项

- 不引入 Node/npm/构建链；Tailwind 与 Alpine 一律 CDN
- 不改 `app_shell.js` 行为、不删它（旧页面在 D 包迁移前仍靠它）
- 不改公开页（landing / booking）与报告模板（report.html / report_en.html / report_v2.html）
- 不改任何路由的业务逻辑；本包只新增模板、静态资源和 `/workspace` 的视图函数内容
- 不改 OCR 管线与部署文件（spec 第 2 节）

## 5. 任务分解

### 5.1 CDN 引入与兜底

- [ ] Tailwind：`https://cdn.tailwindcss.com`（Play CDN）。已知其控制台有"不建议生产用"警告——接受（内部系统、体量小），在 `static/admin.css` 注释中注明决策理由
- [ ] Alpine.js 3：`https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js`，`defer`
- [ ] 兜底策略：CDN 加载失败时页面必须**可读可用**（内容为服务端渲染，Alpine 只负责增强交互；Tailwind 失败时关键布局有 `static/admin.css` 的最低限度手写 fallback——只做布局不崩，不做完整还原）
- [ ] 字体：复用 `static/webfonts/` 现有自托管字体，不新引入网络字体

### 5.2 设计规范（写进文档头部注释 + `static/admin.css`）

- [ ] 色彩令牌（Tailwind inline config 定义）：
  - 底色 `paper: #FAF7F2`，卡片面 `surface: #FFFFFF`
  - 墨色 `ink: #161310`，次级文字 `ink-soft: #6B655E` 量级
  - 品牌强调 `brand: #D25454`（克制使用：主按钮、当前导航、关键数字）
  - 语义色：success `#16A34A` / warning `#B45309` / danger `#DC2626`，配浅底（`#F0FDF4` / `#FEF3C7` / `#FEF2F2`）
- [ ] 气质：克制的暖纸感管理台 —— 无大面积渐变、无重阴影；卡片 1px 浅边 + 极轻阴影；圆角 8-10px
- [ ] 间距尺度：页面左右 padding 32px，卡片间距 16-24px，表格行高 44px 量级
- [ ] 管理端桌面优先（最小适配 1280px 宽）；学生端页面（C 包）才是移动端优先
- [ ] 组件约定：按钮（primary 用 brand、secondary 白底灰边）、徽章（角色/状态 pill）、卡片、表格、空状态（统一插画位 + 一句说明 + 主操作按钮）、Toast

### 5.3 base 模板 `templates/layouts/admin.html`（Layout 契约）

结构：

```
<!doctype html>
<html lang="zh-CN">
<head>
  {% block head_meta %}{% endblock %}
  <title>{% block title %}Y4 平台{% endblock %} · 凭远</title>
  tailwind CDN + inline config + static/admin.css + alpine defer
  {% block head_extra %}{% endblock %}
</head>
<body class="bg-paper text-ink">
  <aside>  侧边栏：logo(横版 branding logo_inline) + 分组导航 + 底部用户卡
  <main>
    <header> 顶栏：{% block page_title %} + 右侧用户菜单(display_name/角色徽章/退出)
    <div class="content"> {% block content %}{% endblock %}
  </main>
  <div x-data toast 容器>
  {% block scripts %}{% endblock %}
</body>
```

**契约条款（C/D 包必须照用）：**

| 契约 | 名称 | 说明 |
|---|---|---|
| block | `title` / `page_title` / `content` / `head_extra` / `scripts` | 页面只填这些 block |
| 模板变量 | `nav_active`（字符串，如 `'students'`、`'questionnaires.assignments'`），视图渲染时传入，侧边栏据此高亮 |
| 模板变量 | `current_role` / `current_display_name`（由 context processor 从 session 注入，视图不用传） |
| Alpine 约定 | 页面级组件 `x-data="pageXxx()"`，函数定义在 `{% block scripts %}` 内的 `<script>` 里；**Jinja 与 Alpine 都用 `{{ }}` —— Alpine 模板里一律改写 `x-text`/`x-for`，或用 `{% raw %}` 包裹** |
| Toast | 全局函数 `window.y4Toast(message, type)`（type: success/error/info），任意页面可调用 |
| 图标 | 复用 app_shell.js 现有 lucide 风格描边 SVG 集合（抽取成 Jinja macro `templates/layouts/_icons.html`），新增图标走同一风格 |

### 5.4 侧边栏导航（分组严格按 spec 5.1）

```
工作台        /workspace
学生          /students
报告生成      /generate
问卷中心      /questionnaires/assignments（任务）/questionnaires/bank（题库）/questionnaires/rules（规则）  ← 二级分组
洞察          /insights/dashboard（数据总览）/insights/y4-signals（Y4 研判）/insights/six-am（6AM 启动模型）
工具          /tools/bookings（预约管理）/tools/transcript（解读会纪要）/tools/internal（内部下载）/tools/prompt-lab（Prompt Lab）
系统          /system/users（用户管理）/api/docs（API 文档，新标签页）/system/settings（设置，打桩即可）
```

- [ ] **新路径与旧路径并存**：导航一律指向新路径；旧路径（/dashboard /y4-signals /six-am /admin/bookings /transcript /internal /prompt-lab）由 D 包做双注册保持可用（见 D 包 5.3）
- [ ] `/system/settings` 打桩页本包顺手建（extends admin layout，内容"设置模块建设中"），避免导航死链

- [ ] 角色过滤（模板读 `current_role`）：
  - viewer：隐藏「报告生成」「问卷中心（除任务列表只读视图外）」「工具」中的写操作页、「系统」整组
  - advisor：隐藏「系统」整组
  - 折叠分组用 Alpine `x-data="{open: ...}"`，当前所在分组默认展开
- [ ] 侧边栏可收起（存 localStorage）；移动端（<1024px）抽屉式

### 5.5 工作台首页 `/workspace`（spec 5.2）

A 包的 `blueprints/workspace.py` 打桩路由填充为真实视图，模板 `templates/workspace.html` extends admin layout。四个区块：

1. **待确认问卷任务**：查 C 包的 assignments 表 `status='pending'`。**C 包表尚不存在**——本包用 try/except 包裹查询，表不存在时显示空态"问卷模块未启用"（C 包完成后自然点亮，**这就是契约**：C 包建表即接入，无需再改本页）
2. **进行中的生成作业**：读 `data/_progress.json` 与 `data/_job.json`（先读代码核对真实字段，`_job.json` 结构见 `_run_pipeline_job` 的 `_write_job` 调用：status/percent/message/filename 等）
3. **最近活跃学生**：reports 表最近更新的 5 个学生（含 student_code、姓名、最新报告日期、顾问）
4. **快捷入口**：报告生成 / 预约管理 / 问卷题库 三张大卡片
- [ ] 权限：admin/advisor 可见工作台；viewer 登录后重定向 `/students`（在登录成功跳转处实现）
- [ ] 初始密码提醒：session 标记（A 包提供 `password_is_initial` 标志，若无则本包跳过此条并在文档记录）→ 顶部横幅提示改密

### 5.6 登录页视觉

- [ ] `login.html` 重做：居中卡片、纸感底色、品牌 logo、账号+密码（A 包已给字段）、错误提示样式统一；保留 `?next=` 跳转逻辑
- [ ] 不套 admin layout（独立页），但用同一套色彩令牌

### 5.7 共存验证

- [ ] 新旧壳并存：已迁移页（workspace/login）用新壳，未迁移页仍用 app_shell.js，两者互不干扰
- [ ] app_shell.js 的挂载点是 `[data-app-shell]`：新 layout **不含**此属性，天然不触发旧壳

## 6. 验收标准

1. 登录页为新版式设计，登录/错误/429 提示均正常（配合 A 包账号体系）
2. 登录后进入 `/workspace`：四区块渲染；问卷任务区块在 C 包表不存在时显示空态而非报错
3. 侧边栏七组导航齐全，当前页高亮正确；admin 见全部，advisor 不见「系统」，viewer 只见只读项
4. 侧边栏可收起且刷新后状态保留（localStorage）
5. 任一页面调用 `window.y4Toast('测试','success')` 出现 toast
6. 未迁移旧页面（如 /dashboard）仍用旧壳正常打开，无样式/脚本冲突
7. 断网（或屏蔽 CDN）时：布局不崩、内容可读
8. 1280px 与 1440px 宽度下无横向滚动、无元素重叠

## 7. 回归要求

- 未迁移页面（dashboard / y4-signals / six-am / generate / students / admin/bookings / transcript / internal / prompt-lab）保持现状可用
- 公开页（/ /booking /api/docs）零变化
- 报告模板与 PDF 生成零影响

## 8. 常见坑

- **Jinja vs Alpine `{{ }}` 冲突**：见 5.3 契约——Alpine 表达式优先用 `x-text` / `x-bind:` / `x-for`，必须插值处用 `{% raw %}`
- **Tailwind CDN 与 CSP**：若将来加 CSP 头，Play CDN 需要 `unsafe-eval`——本期不加 CSP，记录在案（E 包知悉）
- **app_shell.js 的样式泄漏**：旧壳 CSS（app_shell.css）只在其挂载页加载；新 layout 不引入它，避免互相污染
- **context processor**：在 create_app 里注册一次，所有蓝图模板共享；注意别与现有模板的同名变量冲突（先 grep）
- **viewer 重定向死循环**：登录跳转逻辑里 viewer → /students，/students 必须对 viewer 可见（A 包权限矩阵已含）

## 9. 遗留观察

1. **初始密码提醒未实现**：5.5 要求登录后提示修改初始密码，但 A 包未提供
   `password_is_initial` 之类的标志位，无法判断当前密码是否为初始密码。本期不改
   认证逻辑，待后续包补标志位后再接入提醒。
2. **新导航目标多为占位路径**：`/questionnaires/assignments|bank|rules`、
   `/insights/dashboard|y4-signals|six-am`、`/tools/bookings|transcript|internal|prompt-lab`
   在 B 包中尚未建页，点击当前返回 404。需由后续包（导航位新建或旧路径双注册）补齐，
   本期仅保证侧边栏结构完整、链接可点、不报错。
3. **工作台问卷任务依赖 C 包字段**：`_pending_questionnaire_tasks()` 假设 assignments
   表结构为 `id / student_id / status='pending' / due_at`，且与 students 以 advisor_name
   做顾问隔离。C 包建表时需对齐该假设，否则工作台「待确认问卷任务」持续走空态。
4. **文本字体改用系统栈**：指令包 5.1 设想「复用自托管字体」，但 `static/webfonts`
   实为 FontAwesome 图标字体，非文本字体，无法用于正文。本期不新引入网络字体，
   统一使用系统字体栈（serif 回退系统 serif），保持离线可用与加载速度。
5. **断网降级下多分组无法展开**：CDN 被阻断时 Alpine 缺席，带子项的分组
   （问卷中心 / 洞察 / 工具 / 系统）保持折叠且点不开。这是设计内的降级——保证
   「不崩、可读、可点」，分组内链接在真实环境下才展开。单层可点链接不受影响。
6. **Play CDN 与未来 CSP**：Tailwind Play CDN 若将来加内容安全策略，需要
   `unsafe-eval`。本期不加 CSP，记录在案供 E 包知悉。
7. **无头渲染测量说明（非缺陷）**：用无头 Chrome 在 `--virtual-time-budget` 下测量
   侧边栏收起时，`.y4a-sidebar` 的 CSS 过渡不会随虚拟时间推进，`offsetWidth` 会停在
   收起前的 248px，属测量假象；禁用过渡后实测为 72px。真实浏览器中收起交互与
   `localStorage`（键 `y4a.collapsed`）持久化均正常。
