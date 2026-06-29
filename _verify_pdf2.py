from pdfminer.high_level import extract_text

text = extract_text('output/report.pdf')
lines = [l.strip() for l in text.split('\n') if l.strip()]
print(f'共 {len(lines)} 行')

# 检查所有包含中文的行
chinese_lines = [l for l in lines if any('\u4e00' <= ch <= '\u9fff' for ch in l)]
print(f'\n其中 {len(chinese_lines)} 行包含中文')

# 检查是否有乱码（Unicode 0080-00FF 区间 Latin-1 Extended，或常见替换字符）
bad_lines = []
for l in lines:
    for ch in l:
        cp = ord(ch)
        # Latin-1 Extended 或常见乱码区间
        if 0x0080 <= cp <= 0x00FF and ch not in '×÷°±':
            bad_lines.append(l)
            break
        if ch in 'ÃÄÅÆÇÈÉÊËÌÍÎÏÐÑ':
            bad_lines.append(l)
            break

print(f'\n疑似乱码行: {len(bad_lines)}')
for l in bad_lines[:10]:
    print(f'  {repr(l[:60])}')

# 打印中间章节（精力管理）的部分
print('\n=== 精力管理章节样本 ===')
for i, l in enumerate(lines):
    if '精力管理' in l or '体质健康' in l or 'BMI' in l:
        for j in range(max(0, i-1), min(len(lines), i+8)):
            print(f'  [{j}] {lines[j]}')
        break
