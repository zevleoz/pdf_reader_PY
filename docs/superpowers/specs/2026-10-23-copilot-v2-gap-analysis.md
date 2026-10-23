# Copilot 2.0 移植差距分析（原版 Next.js vs Flask 移植版）

> 日期：2026-10-23 · 对比双方：`~/projects/first-touch`（原版）与 `PDF_converter/templates/first_touch/` + `blueprints/copilot.py` + `growth_talk/copilot*.py`（移植版）
> 图例：**MISSING** = 用户可见功能缺失 · **PARTIAL** = 有但降级 · **OK** = 已移植 · **PORT-ONLY** = 移植版新增
> 已确认的刻意降级（不算差距）：LLM 非流式、聊天历史入库替代 localStorage、Y4 来自平台报告而非上传、管理端无 Tailwind。

## MISSING（用户可见）

- **M1 入口选择屏**（"使用会谈流程" vs "直接上传会后资料"卡片）：原版 `components/CopilotWorkspace.tsx:222`；移植版 `blueprints/copilot.py:947-950` 每次 GET 自动建 guided session，无入口屏。
- **M2 MeetingTimePicker**（日期 + 96 个 15 分钟槽位，入口屏和会话条都有，"时间待统一保存"状态）：原版 `CopilotWorkspace.tsx:242-245, 222`；移植版 `meeting_at` 静默默认 utcnow（`blueprints/copilot.py:182`），API 支持 `meetingAt` 但无 UI 发送。
- **M3 报告里的访谈日期**（草稿头 + 确认报告 + PDF）：原版 `CopilotReport.tsx:21,35`；移植版 preview 不渲染（`workspace.html:538-573`）、PDF payload 丢弃（`blueprints/copilot.py:677-697`）。
- **M4 direct 入口不可达**：后端支持 `?entry=direct`（`blueprints/copilot.py:176,947`）但无任何模板链接（grep `entry=direct` = 0 命中）。
- **M5 补充候选编辑**：改名、分类、喜欢/擅长打分、逐条证据、**分数冲突解决**（"采用会议建议"/"保留已确认评分" + 未解决计数）：原版 `CopilotWorkspace.tsx:229, 189-200`；移植版只有 label+evidence+纳入/排除（`workspace.html:421-437`），冲突数据后端有（`growth_talk/copilot.py:347`）但从未展示。
- **M6 "会议对 Y4 的验证"编辑器**（AI 字段 + 重新生成 + 来源摘录）：原版 `CopilotWorkspace.tsx:230`；移植版只算进报告（`growth_talk/copilot.py:413,350`），无展示无编辑。
- **M7 项目推荐丰富度**：中文状态标签（待审核/需补证据/顾问保留/排除/推荐给学生）、顾问版本视图（证据引用+fit 类型+兴趣引用勾选）、手动"新增方案"+粘贴块导入、按字段重新生成徽标：原版 `ProjectRecommendationList.tsx:23-25,58-94`；移植版 5 字段平卡 + 英文状态码下拉（`workspace.html:460-499`）。
- **M8 报告阶段完整度**：完整草稿"纸面"（象限板/Y4 画像/y4Validation/项目清单各节）、确认后视图、**确认后 PDF/JSON 下载链接**、缺失字段修复导航按钮（"补充兴趣评分"→阶段 3 / "返回补充资料"→阶段 5）、错误重试按钮：原版 `CopilotReport.tsx:16-46,128-138`；移植版 preview 只有 meetingSummary+narrative+裸指纹，确认后只有 toast，下载只能去归档页。
- **M9 浮动聊天**：历史侧栏（选择/删除）、"开始聊天"新对话、展开全页链接、停止生成按钮、复制项目块按钮、格式化回答（标题/列表/粗体）：原版 `CopilotFloating.tsx:10-16`、`CopilotAssistant.tsx:49-57,66,84,12-25`；移植版单临时对话，回答裸 `x-text`（`workspace.html:577-614`）。
- **M10 聊天中心删除对话**（UI + 端点）：原版 `CopilotAssistant.tsx:54`；移植版无 DELETE 路由。
- **M11 聊天中心**：停止按钮、复制项目块、格式化回答、MAX_TURNS=20 上限与"已达 20 轮"状态、学生快速切换、"回答仅作为顾问审核草稿"副标题：原版 `CopilotAssistant.tsx:36,66,84`、`lib/copilot-chat-shared.ts:7`。
- **M12 聊天选择器搜索框**：原版 `CopilotStudentPicker.tsx:8-10`。
- **M13 阶段 3"待评"分数**：原版分数下拉有空选项（`CopilotWorkspace.tsx:227`），未评分不进象限板且报告中列为必填缺失；移植版 null 被强制为 1（`workspace.html:702-705,811-815`），下拉无空选项——**数据保真回归**。
- **M14 阶段 2 的 Y4 画像卡**（职业兴趣/能力倾向/价值偏好 + 校准 note 展示模式）：原版 `CopilotWorkspace.tsx:226`；移植版阶段 1/2 只渲染话术字段。
- **M15 阶段 4**：nextSummary 行内可编辑（AI 字段+重新生成+状态）、**进入阶段 4 自动生成**、已评分兴趣 chips 行：原版 `CopilotWorkspace.tsx:228,183`；移植版只读 + 手动按钮。
- **M16 归档：Activity Hub JSON 下载 + "已 finalize · 视为已推送"徽标**：原版 `ReportOutput.tsx:32,35`；移植版只有 JSON/PDF。
- **M17 手动添加学生的联系电话字段**：原版 `CopilotStudentList.tsx:97`；移植版只有姓名/年级/学校。
- **M18 Yuguo 导入拒绝指引**（按 reasonCode 的纠正文案）：原版 `CopilotStudentList.tsx:16-20,63`；移植版只显示原始 message（`home.html:389-393`）。

## PARTIAL

- **P1 阶段 4 三档象限分档映射错误**：移植版 `≤0低/1中/≥2高`（`workspace.html:852`）；原版 `0–1低/2中/3高`（`ThreeLevelQuadrantBoard.tsx:11-14`）。另缺图例与已评分计数。
- **P2 阶段 3 四象限板**：缺轴标签（"擅长程度 ↑ / 喜欢程度 →"）与"N 项已评分"图例（`QuadrantBoard.tsx:7,10`）。
- **P3 阶段 3 兴趣列表**：原版按分类可折叠分组 + 组内新增按钮 + 计数；移植版平铺表格。
- **P4 报告缺失清单**：缺必填/可选分区、说明文案、修复导航。
- **P5 报告生成进度/失败 UX**：缺 4 步指示器、页内错误面板 + 重试按钮；进入阶段 6 不自动 prepare（原版自动）。
- **P6 脏检查**：缺 projectEditing 阻断、会谈时间独立脏跟踪、"已打开已确认报告"警告。
- **P7 阶段 0 校准**：缺逐字段 AI 来源徽标（tooltip/摘录）与逐字段重新生成。
- **P8 手动添加幂等**：原版 requestId UUID 防网络重试双建；移植版 busy-flag + 名称去重近似。另缺创建成功提示。
- **P9 Yuguo 导入弹层**：缺拒绝指引（M18）与 PARTIAL/FAILED/COMPLETED 标题区分；移植版按钮仅顾问可见，原版所有角色可见。
- **P10 阶段 1/2 展示模式**：原版是学生面向的演示版式（v2-present）；移植版为平铺字段列表，且阶段 1 多显示了 interpretation。
- **P11 浮动聊天证据与续聊**：证据列表 + chatId 续聊 OK，外壳功能见 M9。
- **P12 归档报告行**：缺 Activity Hub 格式与 finalize 徽标；移植版多了原始 payload `<pre>`（PORT-ONLY）。

## OK（已验证移植）

阶段导航条（激活态+忙碌禁用）；阶段 0 话术五字段与校准字段；阶段 5 会谈上传（类型/替换语义/文件名徽标）；补充分析触发+任务轮询+审核保存（含撤销已采纳项）；项目生成/保存+过期检测；报告确认（双 checkbox）+ 指纹防过期；确认前草稿 PDF 下载；聊天深链 `?chat=`；聊天证据折叠列表；**指南页逐字保真**；首页学生卡（计数+阶段徽标+空态，超过原版）；归档 collapsible 列表 + admin 限定 + audit；revision/409 冲突重载。

## PORT-ONLY（移植版新增）

"从 Y4 导入"批量建 session 对话框；360 档案互链；聊天选择器计数卡；阶段条 revision 号与报告预览裸指纹；归档附加信息（topics/keywords/special-focus/错误块/原始 payload）；管理员手动添加时可指定 advisorName；聊天框 Ctrl/Cmd+Enter 发送+字数计数；`pollJob` 轮询基建。

## 备注

- 原版 `HomeDashboard.tsx` 未被任何页面引用（仅测试用），其独有功能（搜索/筛选/指标卡）不计为差距。
- 原版 1.0 历史工作区入口（"历史报告工作区"链接）未移植；平台的 growth_talk 模块已覆盖该功能，如需导航对等可补链接。

## 推荐修复顺序

1. 入口选择屏 + MeetingTimePicker（M1–M4）
2. 阶段 5 审核保真（M5、M6）
3. 阶段 3 分数保真（M13、P1）
4. 报告阶段（M8、P4、P5）
5. 项目推荐卡（M7）
6. 阶段 2/4 内容（M14、M15）
7. 聊天中心与浮动聊天（M9–M12）
8. 首页与归档（M16–M18、P8、P9）

## 视觉走查补遗（2026-10-23，localhost:8799 实测截图）

代码级分析之后的实际浏览器走查（admin 登录，Eric/Y4-0008）：

- **V1（新发现，严重）：阶段 4 的 4×4 象限板渲染破损**——行轴标签（擅长 3/2/1/0）横向排成一行叠在列轴（0 1 2 3）下方，网格区域整块消失。空数据态下即破版，有数据时格子布局同样可疑。P2 升级为必修。
- **V2：阶段 7 报告确认页过于单薄**——整页仅一个"报告准备"卡 + 一个按钮，无自动 prepare、无缺失清单、无草稿预览（M8/P5 的视觉实证）。
- **V3：阶段 6 空态可接受但"保存项目审核"按钮在零条目时以禁用粉色显示**，观感似按钮坏了，建议零条目时隐藏。
- 观感良好的页面：工作台首页、阶段 1（校准 + 话术）、阶段 6 上传卡、聊天中心选择器与聊天页空态——与 admin_v2 壳视觉统一。
- 浏览器视口 ≤930px 时侧边栏正确折叠为汉堡菜单，无破版。
