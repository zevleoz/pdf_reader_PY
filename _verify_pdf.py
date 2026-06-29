from pdfminer.high_level import extract_text
import os

p = 'output/report.pdf'
print(f'文件大小: {os.path.getsize(p)} bytes')
print()

text = extract_text(p)
lines = [l.strip() for l in text.split('\n') if l.strip()]
print(f'共提取 {len(lines)} 行非空文本')
print('=' * 60)
# 打印前 60 行样例
for l in lines[:60]:
    # 检查是否有乱码特征
    has_chinese = any('\u4e00' <= ch <= '\u9fff' for ch in l)
    has_mojibake = any(('\u0080' <= ch <= '\u00ff' and ch not in '×÷') for ch in l)
    marker = ' [中文]' if has_chinese else (' [乱码?]' if has_mojibake else '')
    print(f'  {l[:80]}{marker}')
