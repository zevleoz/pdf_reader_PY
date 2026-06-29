import json
with open('data/report_data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
for item in data['schema_124']:
    code = int(item['code'])
    if 82 <= code <= 103 or 1 <= code <= 8 or 9 <= code <= 22 or 53 <= code <= 71 or 104 <= code <= 124:
        print(f"{item['code']} {item['label']}: {item['value']}")
