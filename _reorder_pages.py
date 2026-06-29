"""1. 调整页面顺序：自驱力移到依恋关系之后
   2. 压缩依恋关系页面内容"""
import re

with open("/Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/report.html", "r", encoding="utf-8") as f:
    content = f.read()

# 找到所有页面的起始和结束位置
# 页面标记: <!-- 1-X ... -->
page_markers = [
    ("1-1", "情绪稳定性"),
    ("1-2", "自我概念"),
    ("1-3", "依恋关系"),
    ("1-4", "人格"),
    ("1-5", "体质健康"),
    ("1-6", "思维模式"),
    ("1-7", "自驱力"),
]

# 提取每个页面的HTML块
pages_html = {}
page_starts = {}
page_ends = {}

for i, (num, title) in enumerate(page_markers):
    start_pattern = f"<!-- {num} {title} -->"
    start_idx = content.find(start_pattern)
    page_starts[num] = start_idx
    print(f"{num} {title}: 起始位置 = {start_idx}")
    
    # 找到下一个页面标记或section分界
    if i < len(page_markers) - 1:
        next_pattern = f"<!-- {page_markers[i+1][0]} {page_markers[i+1][1]} -->"
        end_idx = content.find(next_pattern, start_idx + 10)
    else:
        # 最后一个页面，找到下一个 section 标记
        end_idx = content.find("<!-- ====================", start_idx + 10)
        if end_idx == -1:
            end_idx = content.find('<div class="page"', start_idx + 50)
    
    page_ends[num] = end_idx
    pages_html[num] = content[start_idx:end_idx].strip()
    print(f"  结束位置 = {end_idx}, 内容长度 = {len(pages_html[num])}")

# 重新排序
new_order = ["1-1", "1-2", "1-3", "1-7", "1-4", "1-5", "1-6"]
new_titles = {
    "1-1": "情绪稳定性",
    "1-2": "自我概念",
    "1-3": "依恋关系",
    "1-4": "人格",
    "1-5": "体质健康",
    "1-6": "思维模式",
    "1-7": "自驱力",
}

# 重命名编号
renamed = []
for new_idx, old_num in enumerate(new_order):
    new_num = f"1-{new_idx + 1}"
    html_block = pages_html[old_num]
    # 更新HTML中的标题标记
    old_title = new_titles[old_num]
    html_block = html_block.replace(f"<!-- {old_num} {old_title} -->", f"<!-- {new_num} {old_title} -->")
    renamed.append(html_block)

# 拼接重新排序后的页面
before_pages = content[:page_starts["1-1"]]
after_pages = content[page_ends["1-7"]:]

new_middle = "\n\n".join(renamed) + "\n\n"

new_content = before_pages + new_middle + after_pages

# 压缩依恋关系页面 - 减小间距和尺寸
# 找到attachment相关的CSS
# 调整 .attachment-type-card-big 的padding
new_content = new_content.replace(
    ".attachment-type-card-big {\n    background: #FFFFFF;\n    padding: 6mm 4mm;",
    ".attachment-type-card-big {\n    background: #FFFFFF;\n    padding: 4mm 3mm;"
)

# 调整attachment类型的字号
new_content = new_content.replace(
    ".attachment-type-card-big .type {\n    font-size: 14pt;",
    ".attachment-type-card-big .type {\n    font-size: 12pt;"
)

# 调整att-group-label的margin
new_content = new_content.replace(
    ".att-group-label {\n    font-size: 10pt;\n    font-weight: 700;\n    color: #2A9D8F;\n    margin-bottom: 3mm;",
    ".att-group-label {\n    font-size: 10pt;\n    font-weight: 700;\n    color: #2A9D8F;\n    margin-bottom: 2mm;"
)

# 调整att-bar-row的margin-bottom
new_content = new_content.replace(
    ".att-bar-row {\n    margin-bottom: 4mm;",
    ".att-bar-row {\n    margin-bottom: 3mm;"
)

# 调整attachment-detail-title margin
new_content = new_content.replace(
    ".attachment-detail-title {\n    text-align: center;\n    font-size: 11pt;\n    font-weight: 700;\n    color: #1F2937;\n    letter-spacing: 3px;\n    margin-bottom: 5mm;\n    padding: 2mm 0;",
    ".attachment-detail-title {\n    text-align: center;\n    font-size: 10pt;\n    font-weight: 700;\n    color: #1F2937;\n    letter-spacing: 3px;\n    margin-bottom: 4mm;\n    padding: 1.5mm 0;"
)

# 减小attachment-intro
new_content = new_content.replace(
    "font-size: 10pt;\n    color: #6B7280;\n    line-height: 1.75;\n    margin-bottom: 6mm;\n    text-align: left;\n    padding: 4mm 5mm;",
    "font-size: 9.5pt;\n    color: #6B7280;\n    line-height: 1.7;\n    margin-bottom: 4mm;\n    text-align: left;\n    padding: 3mm 4mm;"
)

# 减小attachment-types-big gap
new_content = new_content.replace(
    ".attachment-types-big {\n    display: flex;\n    gap: 5mm;\n    margin-bottom: 7mm;",
    ".attachment-types-big {\n    display: flex;\n    gap: 4mm;\n    margin-bottom: 5mm;"
)

# 减小attachment-group-big margin-bottom
new_content = new_content.replace(
    ".attachment-group-big {\n    margin-bottom: 5mm;",
    ".attachment-group-big {\n    margin-bottom: 3mm;"
)

with open("/Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/report.html", "w", encoding="utf-8") as f:
    f.write(new_content)

print(f"\n✓ 页面已重新排序: 情绪稳定性 → 自我概念 → 依恋关系 → 自驱力 → 人格 → 体质健康 → 思维模式")
print(f"✓ 依恋关系页面CSS已压缩")
