# 学生档案 / 解读会纪要 / 内部下载 UI 改版 Spec

## Why
这三个页面随着功能增加已变得杂乱、不够现代化、难以使用。学生档案只是一个基本表格缺乏组织；解读会纪要需要手动输入学生信息而非从档案中选择；内部下载仍像工程原型不够直观。需要 UI 改版提升可用性，并新增学生重命名功能。

## What Changes
- **学生档案**：重新设计列表为卡片式布局（或精炼表格），减少杂乱，增加 Rename 功能
- **学生重命名**：新增 `PUT /api/students/<id>` API，更新 `students.name`；因 reports/minutes 均通过 FK `student_id` 关联，改名自动传播到 AI 报告生成和 Y4/E4 下载
- **解读会纪要**：新增学生选择器（从 `/api/students` 拉取下拉列表），选中后自动填充学生姓名、年级、性别；不再需要手动输入
- **内部下载**：UI 打磨，清晰化操作流程，去掉工程原型感

## Impact
- Affected specs: redesign-app-shell-navigation（shell 已就绪，本次改版在 shell 内容区内进行）
- Affected code:
  - `templates/students.html` — 列表 UI 重写 + rename UI
  - `templates/transcript.html` — 新增学生选择器
  - `templates/internal.html` — UI 打磨
  - `app.py` — 新增 `PUT /api/students/<id>` 路由（仅此一个新 API）
  - `templates/style.css` — 可能新增少量共享组件类
- Protected: PDF 生成逻辑、AI 解读逻辑、E4 映射逻辑、所有现有 API 行为不变

## ADDED Requirements

### Requirement: 学生重命名
系统 SHALL 提供学生重命名功能，通过 `PUT /api/students/<id>` 接受 `{"name": "新姓名"}`，更新 `students` 表的 `name` 字段。

#### Scenario: 重命名后传播
- **WHEN** 管理员在学生档案页点击 Rename，输入新姓名并确认
- **THEN** 学生记录的 name 更新；后续生成 AI 报告、下载 Y4 MD/JSON、E4 协议时均使用新姓名（因这些操作通过 student_id 查询学生信息）

#### Scenario: 重命名 UI
- **WHEN** 管理员点击学生行/卡片的 Rename 按钮
- **THEN** 弹出内联编辑或小弹窗，显示当前姓名、输入新姓名、确认/取消

### Requirement: 解读会纪要学生选择器
解读会纪要页 SHALL 提供学生下拉选择器，从 `/api/students` 加载学生列表；选中后自动填充学生姓名、年级、性别，无需手动输入。

#### Scenario: 从学生档案跳转
- **WHEN** 在学生档案页点击某学生的"新建议程"链接
- **THEN** 跳转到 `/transcript?student_id=X`，选择器自动选中该学生并填充信息

#### Scenario: 手动选择
- **WHEN** 在解读会纪要页从下拉选择某学生
- **THEN** 姓名、年级、性别字段自动填充，仍可手动修改

### Requirement: 学生档案列表 UI 现代化
学生档案 SHALL 以更清晰的布局呈现，减少视觉杂乱，突出关键信息（姓名、年级、Y4 状态），操作按钮分组清晰。

#### Scenario: 列表浏览
- **WHEN** 管理员打开学生档案页
- **THEN** 学生以卡片或精炼行呈现，关键信息一目了然，操作（查看报告、新建议程、重命名、删除）排列有序

### Requirement: 内部下载 UI 打磨
内部下载页 SHALL 清晰呈现操作流程，降低首次使用门槛。

#### Scenario: 首次使用
- **WHEN** 新用户打开内部下载页
- **THEN** 能直观理解：选学生 → 选报告 → 运行解读 / 查看 Y4/E4 数据 → 下载；各步骤有清晰标题和引导

## MODIFIED Requirements

### Requirement: 解读会纪要页布局
解读会纪要页的表单区域从手动输入学生信息改为选择器优先，保留逐字稿输入和纪要生成/编辑/下载流程不变。

### Requirement: 学生档案详情视图
点击"查看报告"后的展开区域保持现有报告列表和纪要历史，但视觉上与新的列表布局保持一致。
