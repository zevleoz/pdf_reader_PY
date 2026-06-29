from pdfminer.high_level import extract_pages, extract_text

# 页数统计
pages = list(extract_pages('output/report.pdf'))
print(f'总页数: {len(pages)}')

# 章节标题
text = extract_text('output/report.pdf')
for title in ['情绪与动力系统', '精力管理与身体健康', '学习力', '专业与职业']:
    count = text.count(title)
    print(f'  "{title}" 出现 {count} 次')

# 是否有"乱码"字符（Unicode CJK 之外的异常字符）
import re
# 只保留可打印的 ASCII 和常见 CJK 范围
bad = []
for ch in text:
    cp = ord(ch)
    # 允许: 空格\n\r\t (0-32 特殊), ASCII 可打印, 常见 CJK 区间
    is_ok = (
        ch in ' \n\r\t'
        or 0x0020 <= cp <= 0x007E   # ASCII
        or 0x4e00 <= cp <= 0x9fff   # CJK 统一汉字
        or 0x3000 <= cp <= 0x303f   # CJK 标点
        or 0xff00 <= cp <= 0xffef   # 全角形式
        or 0x2000 <= cp <= 0x206f   # 常用标点
        or cp == 0xb0              # 度数符号
        or 0x00d7 == cp or 0x00f7 == cp  # ×÷
        or cp == 0x2265 or cp == 0x2264  # ≥ ≤
    )
    if not is_ok and ch.strip():
        bad.append((ch, cp))

# 统计异常字符
from collections import Counter
bad_counter = Counter(bad)
if bad_counter:
    print(f'\n⚠ 异常字符 (前10):')
    for (ch, cp), count in bad_counter.most_common(10):
        print(f'  {repr(ch)} (U+{cp:04X}) × {count}')
else:
    print('\n✅ 没有检测到异常字符/乱码')

# 检测各 section 的数据完整性
print('\n=== 关键数值提取 ===')
import re
# 提取所有数字
nums = re.findall(r'\d+(?:\.\d+)?', text)
print(f'  数值总数: {len(nums)}')
print(f'  数值示例: {nums[:20]}')

# 提取百分比
percents = re.findall(r'\d+(?:\.\d+)?%', text)
print(f'  百分比项: {len(percents)} 个 → {percents[:10]}')
