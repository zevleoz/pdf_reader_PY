"""对比 extract.py 中 SCHEMA 的编号和 data_points.py 中 _reg 的编号。"""
import re
from pathlib import Path

# 读取 extract.py 中的 SCHEMA 定义
extract_path = Path(__file__).parent / "extract.py"
extract_content = extract_path.read_text(encoding="utf-8")

# 提取所有 {"code": "xxx", "label": "yyy"
schema_pattern = r'"code":\s*"(\d+)",\s*"label":\s*"([^"]+)"'
schema_items = re.findall(schema_pattern, extract_content)
schema_map = {code: label for code, label in schema_items}

# 读取 data_points.py 中的 _reg 定义
dp_path = Path(__file__).parent / "data_points.py"
dp_content = dp_path.read_text(encoding="utf-8")
reg_pattern = r'_reg\("(\d+)",\s*"([^"]+)"'
reg_items = re.findall(reg_pattern, dp_content)
meta_map = {code: label for code, label in reg_items}

# 对比
print("=" * 80)
print(f"{'编号':<6} {'extract.py SCHEMA':<40} {'data_points.py _reg':<40}")
print("=" * 80)

all_codes = sorted(set(list(schema_map.keys()) + list(meta_map.keys())))
for code in all_codes:
    s_label = schema_map.get(code, "—")
    m_label = meta_map.get(code, "—")
    mismatch = "" if s_label == m_label else "⚠️"
    print(f"{code:<6} {s_label:<40} {m_label:<40} {mismatch}")

print()
print("=== 编号范围 ===")
print(f"extract.py SCHEMA: {min(schema_map.keys())} - {max(schema_map.keys())} (共{len(schema_map)}项)")
print(f"data_points.py _reg: {min(meta_map.keys())} - {max(meta_map.keys())} (共{len(meta_map)}项)")

# 检查错位
print("\n=== 检查错位：如果某编号 extract 的 label 等于其他编号 meta 的 label ===")
for code1, label1 in schema_map.items():
    for code2, label2 in meta_map.items():
        if code1 != code2 and label1 == label2:
            print(f"  extract[{code1}] = '{label1}' 与 data_points[{code2}] 相同")

# 显示 report_data.json 中的实际内容
import json
report_path = Path(__file__).parent / "data" / "report_data.json"
with open(report_path, "r", encoding="utf-8") as f:
    report = json.load(f)

schema_124 = report.get("schema_124", [])
print(f"\n=== report_data.json 中 schema_124（共{len(schema_124)}项）===")
for item in schema_124:
    code = str(item.get("code", ""))
    label = item.get("label", "")
    value = item.get("value", "")
    m_label = meta_map.get(code, "—")
    mismatch = "" if label == m_label or m_label.startswith(label) else "⚠️"
    print(f"  {code} {label:<35} value={str(value):<20} meta={m_label} {mismatch}")
