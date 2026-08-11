# 修复职业价值观排名（简化版）

## 问题

* 初中版 B6：职业价值观在第 12 页（索引 11）→ 当前正确

* 高中版 B6：职业价值观在第 15 页（索引 14）→ 当前不正确

* 用户只需要 1-15 排名，不需要分值

* 当前 `find_values_page()` 的多关键词评分制太复杂，在高中版上选错页面

* 当前的 `number_mapping` 校验逻辑（排名-分数倒置检查等）太复杂且不可靠

## 方案：简化

### 改动 1：简化 `find_values_page()` — 按总页数判断

**文件**：[\_vision\_values\_bar.py#L313-L363](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/_vision_values_bar.py#L313-L363)

将多关键词评分制替换为简单的页数判断：

* 总页数 ≤ 23 → 初中版（23 页）→ 返回索引 11（第 12 页）

* 总页数 > 23 → 高中版（24 页）→ 返回索引 14（第 15 页）

### 改动 2：简化视觉 API prompt — 只请求 number\_mapping

**文件**：[\_vision\_values\_bar.py#L395-L428](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/_vision_values_bar.py#L395-L428)

* 去掉 scores 相关的请求

* 只要求返回 `{ "1": "标签名", ..., "15": "标签名" }`

* prompt 更简单 → API 返回更稳定

### 改动 3：去掉复杂的校验逻辑

**文件**：[\_vision\_values\_bar.py#L460-L518](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/_vision_values_bar.py#L460-L518)

去掉：

* 排名-分数倒置检查

* matches\_default\_order 检查

* known\_hit\_count 检查

只保留最基本的校验：

* number\_mapping 有 15 个条目

* 每个值都能匹配 VALUE\_LABELS

### 改动 4：简化 main() 返回值 — 不再返回 scores

**文件**：[\_vision\_values\_bar.py#L441-L584](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/_vision_values_bar.py#L441-L584)

* `main()` 仍然返回 `{标签: 分数}` dict（保持 extract.py 接口不变）

* 但 scores 从视觉 API 的 scores 字段读取（如果有的话），不再强制要求

* number\_mapping 是主要输出，写入 `_vision_b6_values_mapping.json`

* extract.py 读 mapping 文件填 110-124（排名），读 scores 填 095-109（分数）

### 改动 5：extract.py 保持不变

**文件**：[extract.py#L1783-L1822](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/extract.py#L1783-L1822)

extract.py 的逻辑不需要改：

* mapping 文件存在 → 按编号 1-15 顺序填 110-124

* mapping 文件不存在 → 用 values\_scores 的 key 顺序做 fallback

## 确保本地版本不受影响

* 初中版 B6 总页数 ≤ 23 → 仍然返回索引 11（第 12 页）→ 和之前一样

* 视觉 API prompt 简化后，初中版仍然能正确返回 number\_mapping

* extract.py 不改

## 验证步骤

1. 本地用初中版 B6 测试 → 确认排名 110-124 正确
2. 服务器用高中版 B6 测试 → 确认排名 110-124 正确
3. 确认 095-109 分数仍然有值（从视觉 API 的 scores 读取）

