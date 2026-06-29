"""检查 report_data.json 中实际存储的职业价值观数值。"""
import json
from pathlib import Path

data = json.loads(Path('data/report_data.json').read_text(encoding='utf-8'))

# 打印所有 104-118 项
print("=== 15 项职业价值观 (104-118) ===")
for item in data['schema_124']:
    code = item['code']
    if 104 <= int(code) <= 118:
        print(f"  {code} {item['label']}: {item['value']}")

# 打印 119-124（排序）
print("\n=== 6 项排序 (119-124) ===")
for item in data['schema_124']:
    code = item['code']
    if 119 <= int(code) <= 124:
        print(f"  {code} {item['label']}: {item['value']}")
