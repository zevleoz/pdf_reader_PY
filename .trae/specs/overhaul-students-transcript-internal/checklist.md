# Checklist

- [x] `PUT /api/students/<id>` 路由存在，接受 `{"name":"..."}`，更新 DB 并返回成功 — 实测 curl PUT 返回 `{ok:true, student:{...}}`
- [x] 学生档案列表视觉现代化：卡片/精炼行，突出姓名+年级+Y4 状态，操作按钮有序 — 浏览器 snapshot 确认 student-card 布局，2 个学生 2 个卡片
- [x] Rename 按钮存在，点击弹出编辑，确认后名字更新且持久化 — API 实测改名成功并恢复；UI snapshot 确认"重命名"按钮存在
- [x] 重命名后，生成 AI 报告/下载 Y4 MD/JSON/E4 使用新姓名（因 FK 关联自动传播） — DB 层 student_id FK 设计，name 从 students 表查询，传播自动
- [x] 学生档案现有功能不变：查看报告展开、报告列表、纪要历史、CSV 导出、刷新 — JS 函数签名不变，snapshot 确认"查看报告"/"新建议程"/"删除"按钮存在
- [x] 解读会纪要页有学生下拉选择器，从 `/api/students` 加载 — snapshot 确认 `combobox "关联学生"` 含 3 个选项（手动输入 + 2 学生）
- [x] 选中学生后姓名/年级/性别自动填充，字段仍可编辑 — 三个 textbox 仍在 DOM 中，JS onStudentSelect 填充逻辑已验证
- [x] URL `?student_id=X` 自动选中对应学生 — loadStudentOptions 中读取 URL 参数并 auto-select
- [x] 从学生档案"新建议程"跳转正常关联 — 现有链接 `/transcript?student_id=X` 不变，接收端 loadStudentOptions 处理
- [x] 解读会纪要现有功能不变：逐字稿输入、纪要生成/编辑/下载/删除 — snapshot 确认逐字稿输入区、生成/下载按钮存在；JS 函数签名不变
- [x] 内部下载页有清晰步骤引导，空状态友好 — 新增 .lab-intro 介绍栏 + 步骤标签 + 改进空状态文案
- [x] 内部下载按钮/选择器/状态指示器视觉统一 — .lab-select 对齐 .field 样式，.btn-sm.primary 对齐 .btn-primary，移除粗糙内联样式
- [x] 内部下载所有工具功能不变：AI 解读、有效评价、E4 映射、Y4/E4 切换、下载 — 48 个 JS 函数字节未改，9 个 API 调用不变
- [x] 无控制台错误；现有 shell 侧边栏正常渲染 — 三页 snapshot 确认 shell 存在 + 0 应用错误
- [x] app.py 仅新增 1 个 API 路由，其余 Python 逻辑不变 — git diff +29 行新增 PUT 路由，py_compile 通过
