"""删除第 10 页（第三板块标题）和第 11 页（3-1 认知能力）"""

with open("/Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/report.html", "r", encoding="utf-8") as f:
    content = f.read()

# 找到要删除的区域
# 开始标记: "<!-- ==================== 第三板块：学习力 ==================== -->"
start_tag = "<!-- ==================== 第三板块：学习力 ==================== -->"
start_idx = content.find(start_tag)

# 找到认知能力页的结束标记
# 在认知能力页之后是 "<!-- 3-2 认知能力详情"
cognitive_detail_tag = "<!-- 3-2 认知能力详情"
end_idx = content.find(cognitive_detail_tag, start_idx)

# 如果找不到认知详情标记，就找下一个页面注释
if end_idx == -1:
    end_idx = content.find("<!-- 3-", start_idx + 10)

print(f"开始位置: {start_idx}")
print(f"结束位置: {end_idx}")
print(f"将删除 {end_idx - start_idx} 字符")

# 检查要删除的内容
deleted_content = content[start_idx:end_idx]
lines_in_deleted = deleted_content.count('\n')
print(f"将删除约 {lines_in_deleted} 行内容")

# 构建新内容 - 确保保留正确的标签
# 我们需要在删除后，让后面的"认知能力详情"的前一个标签更新
new_content = content[:start_idx] + content[end_idx:]

# 还需要更新后面页面的编号（3-2, 3-3 等需要重新编号）
# 但是因为我们只删除了一页内容，后面的页面编号不影响功能
# 重要：还要移除 generate.py 中不再需要的部分，但先只删除 HTML

with open("/Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/report.html", "w", encoding="utf-8") as f:
    f.write(new_content)

print("✓ HTML 已更新")
