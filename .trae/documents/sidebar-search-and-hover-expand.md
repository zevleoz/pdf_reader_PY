# 侧边栏搜索框 + 悬停展开

## Context
用户反馈两个交互问题：
1. "快速导航"是一个按钮+弹窗（命令面板），多了一步操作。用户想要一个**始终可见的搜索框**，直接在侧边栏顶部点击输入即可过滤页面。
2. 折叠/展开逻辑太死板——折叠后必须点按钮才能展开。用户想要 **hover 自动展开**：折叠态下鼠标移入侧边栏区域即自动展开，移出即自动收回，折叠按钮仅控制持久化的折叠/展开偏好。

## 修改文件
- `templates/app_shell.css` — 样式调整
- `templates/app_shell.js` — 交互逻辑

不涉及其他文件。

## 方案

### 1. 内联搜索框替换命令面板按钮
- 删除 `y4-search-btn` 按钮，在品牌区下方、导航列表上方插入一个 `<input>` 搜索框
- 搜索框样式：深色背景半透明、搜索图标在左、输入文字白色、placeholder "搜索页面…"
- 输入时实时过滤下方导航项（不匹配的 `display:none`，组标题在组内无匹配项时也隐藏）
- 清空时恢复全部导航项
- 删除命令面板弹窗 DOM 及相关函数（`buildPalette`/`openPalette`/`closePalette`/`onPaletteInput`/`renderPalette`/`movePalette`/`flattenNav`）
- `Cmd+K` / `Ctrl+K` 快捷键改为直接 focus 内联搜索框
- 折叠态下搜索框隐藏（仅图标可见），hover 展开后搜索框出现可输入

### 2. 悬停自动展开（折叠态）
- 折叠按钮点击逻辑不变：切换 `body.y4-collapsed` 并持久化到 localStorage
- 新增：当 `body.y4-collapsed` 且桌面端（≥1024px）时，侧边栏监听 `mouseenter` → 添加 `y4-hover-expand` 类；`mouseleave` → 移除该类
- CSS：`body.y4-collapsed .y4-sidebar.y4-hover-expand` 宽度恢复为 `var(--y4-sidebar-w)`，显示所有文字（brand-text、group-title、item-label、footer-text）
- 展开时侧边栏 overlay 在内容上方（position:fixed 天然如此，body padding-left 不变，内容不移动）
- 加 `box-shadow` 让 overlay 态有层次感
- 移动端不受影响（移动端是抽屉模式，由 hamburger 控制）
- 添加防抖：`mouseleave` 后延迟 200ms 再收回（避免鼠标意外滑出又滑回的抖动）；`mouseenter` 时取消延迟

### 3. CSS 细节
- 搜索框：`.y4-search-box` flex row, 38px 高, 搜索图标 + input, 背景rgba(255,255,255,.06), 圆角10px, 边框1px solid rgba(255,255,255,.08), focus 时 border-color var(--y4-red-on-dark)
- 折叠态隐藏搜索框文字部分，hover-expand 时恢复
- 删除 `.y4-palette-*` 全部样式
- 保留 `:focus-visible` 焦点环覆盖新搜索框

## 验证
1. 启动本地服务，登录后：
   - 侧边栏顶部有搜索框，输入"学生"→只有"学生档案"项可见，其他隐藏
   - 清空搜索框→全部导航项恢复
   - Cmd+K → 搜索框获得焦点
2. 点击折叠按钮→侧边栏缩为 72px
3. 鼠标移入侧边栏→自动展开到 240px，文字可见，搜索框可用
4. 鼠标移出→200ms 后自动收回为 72px
5. 移动端（<1024px）仍为 hamburger 抽屉，不受 hover 逻辑影响
6. 无控制台错误
