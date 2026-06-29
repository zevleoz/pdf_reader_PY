"""查找文本层中职业价值观各标签的 PDF 坐标。"""
import fitz
from pathlib import Path

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))

# 找所有含职业价值观标签的文本
labels = ['创造发明', '独立自主', '美的追求', '智力激发', '利他助人',
           '成就感', '管理权力', '工作环境', '同事关系', '上司关系',
           '多样变化', '经济报酬', '安全稳定', '声望地位', '生活方式']

print("=== 第 14 页文本层中职业价值观标签的坐标 ===")
page = doc[13]
dict_data = page.get_text("dict")
for block in dict_data["blocks"]:
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            text = span["text"].strip()
            if any(kw in text for kw in labels):
                x0, y0, x1, y1 = span["bbox"]
                size = span["size"]
                print(f"  '{text}'  bbox=({x0:.0f},{y0:.0f})-({x1:.0f},{y1:.0f})  size={size:.1f}")

doc.close()
