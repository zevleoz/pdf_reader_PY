# 学生列表紧凑化 + 有效评价视觉分级 实施计划

## Repository Research

### 问题 1：学生档案卡片太臃肿
`templates/students.html` 当前每个学生是 3 段式卡片（L244-272）：
- `.sc-head`：姓名 + 年级/学校/顾问 + 状态徽章
- `.sc-foot`：创建时间 + 4 个操作按钮（查看报告/新建议程/重命名/删除），带 dashed 分隔线
- `.sc-rename`：内联重命名编辑区

每生约 90-110px 高，一屏仅 3 个学生。另有噪音：空值显示"未填写年级/未填写学校"占位文字。

### 问题 2：内部下载「有效评价」眼花缭乱
`templates/internal.html` 的有效评价面板：
- **工具栏一行塞了 6 类元素**（L710-719）：搜索框、只看已调整、E4 映射（带计数）、Y4/E4 视图切换（2 按钮）、最多 6 个计数 pill（共/已评价/已调整/数据偏差/观望/备注），全部同级 flex wrap，无主次分级
- **每张 eval-card 元素过多且无对齐**（renderEvalCard L1037-1067+）：编号、名称、E4 彩签（4 色）、来源彩签（4 色）、原始值、评价 chip、3 个偏差按钮、观望按钮、备注按钮 —— 颜色多（E1-E4 四色 + 来源四色 + 偏差三色边框 + 档位三色），各列无固定宽度

### 不变的约束
- 所有 JS 函数签名、元素 ID、API 调用、功能逻辑保持不变
- 仅改两个模板文件的 CSS + DOM 结构（内部下载卡片渲染 JS 仅调整 HTML 结构/类名，不动行为）
- 用户偏好：不用彩色区分类别，主体用中性黑灰（#0f172a/#94a3b8）；档位的语义色（绿/黄/红 = 健康/关注/问题）保留，因其承载功能语义
- 无 emoji

## Files and Modules
- `templates/students.html`：卡片 CSS 改紧凑单行样式 + loadStudents() 渲染 HTML 结构调整
- `templates/internal.html`：eval-toolbar 拆两行分级；计数 pill 降噪；eval-card 内部固定列宽对齐；装饰彩签中性化

## Implementation Steps

### Step 1：学生列表改为紧凑单行
文件：`templates/students.html`

- 将 `.student-card` 改为单行 flex 行（高度约 56px），去掉 `.sc-foot` 的 dashed 分隔线和上下 padding：
  - 左侧：姓名（15px/600）+ 同行 inline muted meta（年级·学校·顾问，仅渲染非空字段，用 `·` 分隔；删除"未填写年级/学校"占位）
  - 右侧：Y4 状态徽章 + 纪要数徽章（保持现有类），然后操作区：查看报告（action-link）、新建议程（btn-sm）、重命名（ghost 小字按钮）、删除（ghost，hover 变红）
  - 创建时间移入该行 `title` 属性（hover 可见），不再占布局空间
- 行 hover 背景 `var(--paper-2)`；操作按钮常驻但弱化（颜色 muted，hover 变 ink/red），保证 easy to access
- 窄屏（<720px）允许折行：meta 换到第二行，操作区不缩
- `.sc-rename` 内联编辑区保持现有交互（Enter 确认 / Esc 取消），视觉改为行下扩展的细条（去掉重复 dashed 线，统一间距）
- 函数 `loadStudents/startRename/cancelRename/confirmRename/deleteStudent/newMinutesForStudent/showReports` 签名与 API 全部不动，只改模板字符串里的 class 与结构；`#name-{id}`、`#rename-{id}`、`#rename-input-{id}` 等 ID 保留

### Step 2：有效评价工具栏分两级
文件：`templates/internal.html`（L710-719 DOM + `.eval-toolbar` CSS）

- 工具栏拆为两行（包在现有工具栏容器内，用两个子区 div）：
  - **主操作行**：搜索框（flex 增长，min-width 200px）→ spacer → "只看已调整" toggle → "E4 映射 (n)" 按钮 → 细分隔线 → Y4 四维/E4 框架 segmented 切换
  - **元信息行**：计数条，改为安静的文字 meta 样式（11px muted，数字 semibold ink），格式 `共 N · 已评价 N · 已调整 N`，条件项（数据偏差/观望/备注）追加在后；仅"已调整"数字保留红色。去掉 pill 的胶囊底色/边框
- 两行之间用 hairline 或背景色差区分（主行白底，元信息行 paper-2），不再 wrap 混排
- 所有 ID（evalSearch/filterAdjustedToggle/mappingToggle/mappingCount/evalCounts）和 onclick 不变

### Step 3：eval-card 固定列对齐 + 降噪
文件：`templates/internal.html` CSS + `renderEvalCard()` 模板（L1037 起）

- 卡片内行改为固定 zone 的 flex grid，所有卡片列对齐：
  - 编号：固定宽 62px，mono 10px muted
  - 指标名：flex 填充，12.5px ink
  - 来源签：中性灰（统一灰底灰字，移除推导红/排序蓝等装饰色；文字保留 档位/推导/排序/参照/待判定）
  - 原始值：固定宽右对齐 mono
  - 评价 chip：固定宽度居中（语义色保留）
  - 操作区：偏差三按钮 + 观望 + 备注，统一为 ghost 小按钮（默认灰、无实底色），仅 active/hover 显色；tooltip 保留
- E4 彩签：E4 视图下才渲染（Y4 视图不显示），统一为中性深灰 chip（移除 E1-E4 四色），因为视图切换本身已提供框架语境
- 卡片网格 minmax 从 280px 调到 ~360px，保证单行容纳不折行；窄屏自适应
- 保留功能性的左边框语义：adjusted 红 / bias-high 琥珀 / bias-low 蓝（这是状态不是分类装饰），宽度收到 2.5px
- 备注展开行 `.eval-note-row` 逻辑不动
- renderEvalCard 内仅调整 HTML 包裹结构与 class 名称的使用方式，所有 onclick/data 属性/函数调用原样保留

### Step 4：整体微调
- eval-dim-head 分组标题与新卡片左内边距对齐（编号列起始位置一致）
- 工具栏与卡片区在视觉上连成清晰的"筛选 → 列表 → 底部下载"三段
- 内部下载其余区域（topbar、AI 解读 tab、modal、下载 footer）不动

## Dependencies and Considerations
- 纯前端模板改动，无后端/DB/API 变更，无需重启逻辑之外的部署步骤（Flask debug 自动加载模板；当前本地服务已在跑）
- 内部下载页 JS 体量大（函数多），改 renderEvalCard 模板时须逐条保留事件绑定，风险点在漏带 onclick；实施后用浏览器逐一点验
- E4 标签中性化后，在 E4 视图中同指标多维度归属仍靠 chip 文字（E1/E2…）区分，可接受

## Validation
1. 浏览器登录后访问 `/students`：
   - 一屏可见学生数明显增加（单行约 56px，目标 8+ 行/屏）
   - 空字段不再显示"未填写"占位；年级学校顾问非空时 inline 显示
   - 查看报告/新建议程/重命名/删除均可点；重命名内联编辑 Enter/Esc 正常；改名持久化
   - 展开报告列表 + 纪要历史正常
2. `/internal` 选学生→选报告→切到「有效评价」：
   - 工具栏分两级：主操作行 + 安静计数行，无混排
   - 卡片各列（编号/名称/来源/原值/评价/操作）跨卡片垂直对齐
   - Y4 视图无 E4 签；切 E4 视图出现中性 E4 chip
   - 点评价 chip 弹层、偏差三按钮、观望、备注展开、只看已调整、搜索、E4 映射、三个下载按钮全部功能正常
3. 三页无控制台错误；窄屏下无横向滚动

## Risks
- **renderEvalCard 结构改动导致事件丢失**：实施时保持所有 onclick/data-* 原样，完成后按 Validation 第 2 条逐项手测；如有问题即时回退该卡片模板片段
- **紧凑行在数据字段很长时挤压**：meta 区设 min-width:0 + ellipsis，操作区 flex-shrink:0 保证按钮始终可用
