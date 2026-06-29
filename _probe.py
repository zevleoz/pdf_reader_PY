import fitz
from pathlib import Path

pdfs = [
    'A2 核心素养_Samson_2026031415314850446(1).pdf',
    'B3 核心学习能力_Samson_2026031417084772022(1).pdf',
    'B4 核心认知能力和成长型思维_Samson_2026031416112834275(1).pdf',
    'B6 职业发展_Samson_2026031417271196372(1).pdf',
]

for pdf in pdfs:
    print("\n" + "="*60)
    print(f"=== {pdf}")
    print("="*60)
    doc = fitz.open(f'input/{pdf}')
    for i, page in enumerate(doc):
        txt = page.get_text().strip()
        if not txt:
            continue
        lines = [l.strip() for l in txt.splitlines() if l.strip()]
        score_lines = [l for l in lines if '得分' in l or '平均' in l or l.rstrip().endswith('分') or '%' in l]
        print(f"\n  [页 {i+1}] 标题: {lines[0]}")
        print(f"         关键: {score_lines[:6]}")
