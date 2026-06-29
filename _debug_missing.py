import json
with open('data/report_data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
empty = []
for item in data['schema_124']:
    if not item.get('value'):
        empty.append((item['code'], item['label']))
print("Empty items:", empty)

# 也看一眼职业价值观部分
for item in data['schema_124']:
    if 104 <= int(item['code']) <= 133:
        print(f"{item['code']} {item['label']}: {item['value']}")
