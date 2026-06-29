"""从 report_data.json 中提取 schema_124，生成新的 data_points.py。"""
import json
from pathlib import Path

report_path = Path(__file__).parent / "data" / "report_data.json"
with open(report_path, "r", encoding="utf-8") as f:
    report = json.load(f)

schema_124 = report.get("schema_124", [])

# 显示所有 124 项
print("=== schema_124 中的 124 个数据点 ===")
for i, item in enumerate(schema_124):
    code = str(item.get("code", ""))
    label = item.get("label", "")
    value = item.get("value", "")
    print(f"  {code:<4} {label:<35} value={value}")

print(f"\n共 {len(schema_124)} 项")
