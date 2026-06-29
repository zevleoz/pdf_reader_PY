"""查看文本层已抓到的职业价值观数值，确定标签-段映射。"""
import json
from pathlib import Path

data = json.loads(Path('data/report_data.json').read_text(encoding='utf-8'))

# 职业价值观的 15 项 code 是 104-118
val_codes = {
    '创造发明': '104', '独立自主': '105', '美的追求': '106',
    '智力激发': '107', '利他助人': '108', '成就感': '109',
    '管理权力': '110', '工作环境': '111', '同事关系': '112',
    '上司关系': '113', '多样变化': '114', '经济报酬': '115',
    '安全稳定': '116', '声望地位': '117', '生活方式': '118',
}

print("=== 文本层提取的 15 项职业价值观数值 ===")
for label in val_codes:
    code = val_codes[label]
    val = ''
    for item in data['schema_124']:
        if item['code'] == code:
            val = item['value']
            break
    print(f"  {label} ({code}) -> {val}")
