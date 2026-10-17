# Agent L 指令包：语汇 v2 地基迁移 —— 新壳转正 + 组件库补全

> 「专业 SaaS 语汇」全站铺开的第一包（12/13/14）。语汇已由需求方在 `/workspace-v2` 样板页上**验收通过**（冷中性壳 + 盾徽红唯一强调色 + 表格纪律 + mono 编号 + 印章徽章）。
> 本包把样板从"预览"变成"地基"：新壳转正、组件库补全、登录页迁移。13/14 包逐页迁移业务页面。

## 1. 语汇规范（锚点，照 `static/admin_v2.css` 实物执行）

已批准的语汇事实（不要重新发明）：

- **色板**：地面 `#F7F8FA`（冷灰）/ 表面白 / 边框 `#E5E7EB`；文字 zinc 阶（`#18181B/#3F3F46/#71717A/#A1A1AA`）；**盾徽红 `#D24949` 是唯一强调色**（主按钮、选中态、进度条、当前导航红标+红图标）；语义色 ok/warn/danger 各配 soft 底；侧栏暖墨 `#16130F`
- **高度**：border-only + 极浅投影（`0 1px 2px rgba(24,24,27,.04)`）；圆角卡片 8px / 控件 6px
- **字体**：全站 sans（系统栈）；页面标题 20px/650；区块标题 13.5px/600；数据 13px；**编号/代码/日期一律 `var(--mono)`**；数字 `tabular-nums`
- **表格纪律**：列头带（`--bg` 底 + 11px/600/.05em 疏排 muted 标签）与数据行同栅格；行高 44px；行分隔 `--line-soft`；hover `#FAFAFB`
- **徽章**：一种语法——pill + 5px 圆点 + 语义 soft 底；方形印章式（bordered 3px 圆角）只见于样板页旧版，**以现行 `admin_v2.css` 的 pill 为准**
- **细节收编**：选区色 `brand-soft`、焦点环 `0 0 0 4px var(--brand-ring)`、细滚动条、`prefers-reduced-motion` 全关动画
- **品牌锚点**：侧栏红色线稿盾徽（`/branding/logo_red.png` 40px）+「凭远教育 / Y4 · 综合测评」+ 底部 WORK HARD · DREAM BIG 低亮度格言；**不要** serif、金色、水印进管理端（那是被否掉的方向）
- **交互**：行内展开面板（grid-template-rows 0fr→1fr 过渡）、两步行内确认、Toast 黑底、按钮 `.is-loading`、骨架屏 `.sk`

## 2. 前置依赖与现状（已核对 2026-10-16）

| 文件 | 状态 |
|---|---|
| `static/admin_v2.css` | 样板页语汇完整实现（本包的基准） |
| `templates/layouts/admin_v2.html` | 新壳（侧栏/顶栏/Toast/命令面板挂载/Alpine CDN；**无 Tailwind**） |
| `templates/workspace_v2.html` + `blueprints/workspace.py` 的 `/workspace-v2` 路由 | 样板页（行内审批全真接线） |
| `static/admin.css` + `templates/layouts/admin.html` + `_tailwind_config.html` | 旧壳体系，17 个管理端模板 `extends layouts/admin.html` |
| `static/command-palette.js` + `templates/layouts/_command_palette.html` | ⌘K 面板；**样式在 admin.css 的 `.y4a-cmdk-*`**（v2 壳不加载 admin.css，必须移植样式，见 5.3） |
| `templates/login.html` | 独立模板（不 extends），暖纸旧风格 |

## 3. 禁止事项

- 不改 OCR 红线文件、数据模型、路由契约、部署文件
- 不删旧壳文件（admin.css / admin.html / _tailwind_config.html / app_shell 残留）——14 包确认全站迁移完成后才删
- 学生端（`templates/student/`）、报告模板、公开页不动
- 不改 `command-palette.js` 的交互逻辑，只移植/补齐样式
- v2 壳目前不加载 Tailwind：迁移页面时**不得把 Tailwind 工具类带进 v2 页面**（没有运行时支持），一律用 admin_v2.css 组件类

## 4. 任务分解

### 4.1 v2 组件库补全（`static/admin_v2.css` 追加，与现有风格同源）

样板页没用到的组件，业务页面迁移需要——补齐（命名沿用现有前缀风格，全部写在 admin_v2.css）：

- [ ] **表单**：`.field`（label 12px/600 muted + 控件）、`.input`/`.select`/`.textarea`（白底、1px `--line`、6px、focus 时 brand ring）、`.checkbox`/`.radio` 原生控件收编（accent-color: var(--brand)）、`.form-row` 栅格
- [ ] **筛选 pill 组**：`.pills`（容器）+ `.pill`（白底边框 pill，`.on` 态 = ink 底白字或 brand-soft 红字——选红字，与语汇一致），计数小字 muted
- [ ] **Tab 下划线**：`.tabs` + `.tab`（13.5px、底部 2px 透明边，`.on` = ink 文字 + brand 下边条）——学生 360° 页用
- [ ] **通用表格**：`.table`（th 同列头带规范、可排序 th 带箭头占位、行 hover、`.num` 右对齐 tabular）——供 dashboard 等页
- [ ] **stat 卡**：`.stat-grid` + `.stat`（白卡、28px/650 tabular 数字 + 12px muted 标签 + 可选 delta 小字 ok/danger）——dashboard 用
- [ ] **下拉菜单**：`.menu`（白底边框 8px 阴影 `0 6px 20px rgba(24,24,27,.12)`、项 30px hover `--bg`、危险项红字）——行内 ⋯ 菜单用
- [ ] **对话框**：`.dialog-backdrop`（rgba(24,24,27,.4)）+ `.dialog`（白卡 8px、max-width 480px、标题 15px/600 + 正文 13px + 按钮行右对齐）——确认类操作用（比行内两步确认重的操作才用）
- [ ] **描述列表**：`.dl`（dt 12px muted / dd 13px）——详情面板用
- [ ] **警告/信息横幅变体**：`.alert-warn`、`.alert-info`（同 .alert 结构换语义色）
- [ ] **kbd**：`.kbd`（顶栏搜索框同款抽成类）

### 4.2 壳转正

- [ ] `templates/layouts/admin_v2.html` 保留为正式新壳（文件名不变也行，但建议改名 `layouts/admin.html` 的**并存期别名**：本包新建 `layouts/admin_v2.html` 已存在 → 保持，页面迁移时把 extends 指过来；14 包最后统一收编文件名）
- [ ] 侧栏品牌链接 `/workspace-v2` 改为 `/workspace`（13 包把 v2 内容转正到 /workspace）
- [ ] 检查 `admin_v2.html` 的 nav 渲染对 `nav_groups` 的依赖与旧壳一致（group.title/links/item.key/icon/blank），不缺字段
- [ ] 顶栏加**页面操作区 block**：`{% block page_actions %}{% endblock %}`（面包屑与搜索框之间），供页面放主操作按钮

### 4.3 ⌘K 面板样式移植

- [ ] 把 `static/admin.css` 中 `.y4a-cmdk-*` 全部规则移植进 `admin_v2.css`（**原样复制后改色值**：面板白底 `--line` 边、选中行 `brand-soft` 底、分组标签规范同 qrow-head）；admin.css 里的原规则保留（旧壳还在用）
- [ ] 验证：v2 壳页面（/workspace-v2）⌘K 打开面板视觉正常、搜索学生正常

### 4.4 登录页迁移（`templates/login.html`，独立模板）

- [ ] 套用语汇：冷灰底、白卡（8px、border-only）、品牌红主按钮、盾徽 logo（用 `/branding/logo_red.png`，高 56px）、标题"登录"（sans 20px/650）、副标题"凭远教育 · Y4 综合测评系统"
- [ ] 错误提示（账号密码错误/429）用 `.alert`；输入框用 `.field`/`.input`
- [ ] 保留 `?next=` 跳转逻辑与表单字段名不动

### 4.5 迁移契约文档化

- [ ] 在 `static/admin_v2.css` 头部注释追加"页面迁移契约"：extends `layouts/admin_v2.html`；block 清单（title/page_title/page_actions/content/head_extra/scripts）；禁用 Tailwind 类；常用组件速查（.surface/.qrow-head/.qrow/.badge/.btn/.pills/.tabs/.table/.stat/.field）；`v2Toast()` / `v2Logout()` 全局函数
- [ ] 13/14 包按此契约执行

## 5. 验收标准

- [ ] `/workspace-v2` 视觉与样板验收时一致（无回归）；⌘K 面板样式正常
- [ ] `/login` 为新语汇，登录/错误/429 流程正常
- [ ] 组件库新组件在测试页（可建临时路由或直接在 13 包页面里）渲染正常
- [ ] 旧壳页面（/students、/questionnaires/* 等）**完全不受影响**（旧壳文件零改动）
- [ ] reduced-motion 与 820px 窄屏在 v2 壳下正常

## 6. 常见坑

- Flask 在 debug=False 下缓存编译模板——改模板后必须重启进程才能看到变化（执行 agent 自检时牢记）
- `/admin_v2.css` 走 app.py 自定义静态路由（无 /static 前缀）；新增静态文件路由照同一模式
- Alpine 与 Jinja 的 `{{ }}` 冲突：Alpine 表达式用 `x-text`/`x-bind`，插值处 `{% raw %}`
- 侧栏盾徽在深色底上是红线稿——别加白底卡片托住它，直接放

## 7. 遗留观察

- 侧栏品牌链接已改为 `/workspace`（旧壳路由仍存在且受 role_required 保护，链接有效；13 包 v2 内容转正后自然衔接）
- 登录页在「浏览器已有登录 session」时提交会得到「CSRF 校验失败」——这是已知遗留问题（05 包 P1-2 范围外），与本次视觉迁移无关；全新 session 登录不受影响
- 本地开发库无明文 admin 密码（users 表密码为哈希），成功登录后的页面视觉验收需在 13 包迁移时一并复核；/workspace-v2 已通过无登录方式完成视觉、⌘K、820px 窄屏、reduced-motion 验收
- 工作区在本包执行前已有未提交改动（含 blueprints/workspace.py 等），13/14 包提交时注意只包含当包文件
- v2 组件库新增组件用临时测试页（/tmp，不入库）验证通过：横幅/表单/pills/tabs/stat/表格/menu/dialog/dl/badge/kbd 全部渲染正常
