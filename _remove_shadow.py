"""移除所有 box-shadow 声明以避免 PDF 灰色方块问题"""
import re

with open("/Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/report.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
removed = 0

for i, line in enumerate(lines):
    # 删除仅包含 box-shadow 的行
    stripped = line.strip()
    if stripped.startswith("box-shadow:") and stripped.endswith(";"):
        # 检查是否是独立行 - 跳过这一行
        removed += 1
        print(f"  移除行 {i+1}: {stripped}")
    else:
        new_lines.append(line)

with open("/Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/report.html", "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print(f"\n✓ 移除了 {removed} 个 box-shadow 声明")
