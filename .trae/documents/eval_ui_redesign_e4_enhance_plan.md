# 有效评价 UI 设计优化 + E4 输出增强 实施计划

## Repository Research

### 当前状态

**UI ([templates/prompt\_lab.html](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/prompt_lab.html))**

* 有效评价面板使用卡片式布局，但每项的有效评价选择用 `<select>` 下拉框

* 操作区有三个按钮组：偏高/偏低 bias 切换、真假问题切换、备注展开

* 顶部工具栏：搜索、只看已调整、Y4/E4 视图切换、计数 pill

* 底部：包含原始数据复选框 + 两个下载按钮（默认协议 / E4 协议）

* E4 视图按 E1-E4 分组，每个数据点右上角有彩色 E4 标签

**数据规则 ([evaluation\_rules.py](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/evaluation_rules.py))**

* `E4_CODE_MAP`: 133 个 code → (E4\_dim, subcat) 映射

* `E4_SUBCATS`: E1(5子项) / E2(3子项) / E3(2子项) / E4(3子项)

* Y4 四维: 心力/精力/学习力/生涯力

**下载端点 ([app.py](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/app.py))**

* `/api/prompt-lab/evaluation/download` — 默认协议 Markdown（Y4 四维分组）

* `/api/prompt-lab/evaluation/download-e4` — E4 协议 Markdown（E1-E4 分组，含子类别）

### 用户反馈的核心问题

1. 下拉框不直观，应改为可点击按钮，充分利用桌面宽度
2. E4 输出必须包含所有变量，不能只含 E4 特有的（可在 E1-E4 后追加其他变量段）
3. 数据点上的 flags（bias/problem）含义不清晰，下游 AI 不知道如何在 MD 中使用这些数据
4. E4 不是 Y4 框架的穷尽映射，只是最小子集，AI 应能看出 Y4↔E4 的连接关系及其对提问的启发
5. E4 报告是"工作草稿"，用于与学生沟通迭代找薄弱点和低垂果实

## Files and Modules

* `templates/prompt_lab.html` — UI 重构（卡片布局、按钮选择器、清晰 flags、桌面宽度利用）

* `app.py` — E4 下载端点增强（含全部变量、Y4↔E4 连接说明、AI 使用指引、工作草稿定位）

* `evaluation_rules.py` — 可能新增 Y4↔E4 连接说明数据结构

## Implementation Steps

### Step 1: UI — 替换下拉框为横向滚动按钮选择器

* 将有效评价的 `<select>` 替换为水平滚动的药丸按钮带（scrollable pill strip）

* 10 个选项以紧凑药丸按钮排列在一个横向滚动容器中

* 容器左右两侧用 CSS 渐变 mask（`mask-image: linear-gradient(to right, transparent, black 12px, black calc(100% - 12px), transparent)`）实现边缘渐隐效果，提示可滚动

* 选中态按钮用颜色编码（与现有 `.eval-card-eval` 颜色一致：绿=高/较好，蓝=不低/正常，黄=偏低/需关注，红=明显偏低/需特殊关注/严重偏低，灰=待判定）

* 点击即选，无需展开下拉；容器宽度自适应卡片宽度，超出部分横向滚动

* 排序项/参照值仍显示为只读彩色标签

### Step 2: UI — 卡片布局优化（桌面宽度）

* 在宽屏（>1200px）下，卡片改为两列网格（`.eval-dim-body { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }`）

* 卡片内部结构更清晰：

  * 第一行：code + label + E4 标签（右侧）

  * 第二行：原始值 + 有效评价滚动按钮带 + 来源标签

  * 第三行（操作行）：偏高/偏低切换 + 真假问题切换 + 备注按钮

* 操作行用 icon + label 形式，hover 有 tooltip 说明每个 flag 的含义

### Step 3: UI — Flags 语义清晰化

* 偏高/偏低切换改为带 icon 的三段按钮，并加 tooltip："通过访谈发现该数据可能偏高/偏低（非学生真实水平）"

* 真假问题切换："已确认"= 真问题（CONFIRMED），"观望"= 假问题（测评状态失真，待验证）

* 每个 flag 在卡片上有明确的视觉标识（左边框颜色 + 文字标签）

* 备注展开后输入框有 placeholder 指引可填什么

### Step 4: E4 输出 — 包含所有变量

* E4 下载端点在 E1-E4 四段后，追加 `## OTHER_VARIABLES` 段

* 该段包含所有未被 E4\_CODE\_MAP 明确映射的变量（兜底到 E4 的也算，但如果有些变量不属于任何 E4 子类别则单独列出）

* 实际：所有变量都会被映射（兜底到 E4），所以改为：E4 输出中每个 EVAL/ORDER/NORM 行必须包含完整字段（code/label/raw/eval/source/bias/problem/adjusted/note），不因属于 E4 而省略

### Step 5: E4 输出 — Y4↔E4 连接说明段

* 在 `E4_FRAMEWORK` 段后新增 `## Y4_E4_MAPPING` 段

* 说明四个 Y4 维度如何映射到 E4 四个维度，以及为什么这样映射：

  * Y4 心力 → E1 情绪（情绪稳定性/依恋/自我概念）+ E3 动力引擎（自驱力/学习动机/人格开放性）

  * Y4 精力 → E2 精力管理（睡眠/运动）

  * Y4 学习力 → E3 大脑引擎（认知/执行功能）+ E4 参与投入（学习策略）

  * Y4 生涯力 → E4 参与投入（职业兴趣/能力优势/价值观）

* 每个连接说明它如何帮助提问（如：神经质高 + 外倾性低 → 焦虑易内耗 → 追问"焦虑对你学习的杀伤力有多大"）

### Step 6: E4 输出 — AI 使用指引段

* 新增 `## AI_USAGE_GUIDE` 段，明确告诉下游 AI：

  * 如何解析每行（`[EVAL]`/`[ORDER]`/`[NORM]`/`[JUDGE]` 的字段含义）

  * 各字段的 authority 等级（EFFECTIVE\_EVALUATION > EXPERT\_JUDGMENT > INTERPRETATION > HYPOTHESIS）

  * bias 字段的使用方式（偏高/偏低 → 数据可信度打折，需询证验证）

  * problem=OBSERVATION 的含义（假问题，不可直接当结论，需后续验证）

  * 工作草稿定位：本文件是沟通迭代基础，非确定性指导

### Step 7: E4 输出 — 工作草稿定位

* 在 META 段标注 `status: WORKING_DRAFT`

* 在文件头说明："本文件为 E4 工作草稿，用于与学生沟通迭代，识别薄弱点和低垂果实，非最终评估结论"

## Dependencies and Considerations

* 按钮选择器需要在 10 个选项间保持可读性，可用 flex-wrap 让其自动换行

* 两列网格在小屏需回退为单列（已有 `@media` 断点）

* E4 输出的 OTHER\_VARIABLES 段需确保不重复（已在 E1-E4 出现的不再列出）

* AI\_USAGE\_GUIDE 中的 authority 等级需与默认协议的 HIERARCHY\_RULES 保持一致

* 不改 PDF 生成流程（铁律）

* 不改现有数据规则，只增强输出结构

## Validation

* 启动服务器，访问 /prompt-lab，验证：

  * 有效评价改为按钮组，点击可切换，选中态颜色正确

  * 宽屏下卡片两列排列，窄屏单列

  * flags 有 tooltip，含义清晰

  * 下载 E4 协议：包含 Y4\_E4\_MAPPING、AI\_USAGE\_GUIDE、OTHER\_VARIABLES 段

  * 所有变量在 E4 输出中都有出现（无遗漏）

  * E4 输出每行包含完整字段

* 未登录访问返回 403

## Risks

* 横向滚动按钮带需要确保当前选中项可见：选中时自动 `scrollIntoView` 至容器内

* 边缘渐变在不同浏览器可能表现不同：用 `mask-image` + `-webkit-mask-image` 双写兼容

* E4 输出变长：这是预期的，因为要包含全部变量和说明

* 两列布局可能导致操作区拥挤：用 `gap` 和 `flex-wrap` 控制

