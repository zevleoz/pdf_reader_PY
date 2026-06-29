"""从 B6 PDF 第 14 页（职业价值观横条图）提取 15 个得分。

策略：
1. 用 fitz.get_text("dict") 得到已识别的标签（生活方式、美的追求）和数字
2. 用 PIL 渲染 PDF 为图像
3. 对每一水平行，估计横向填充率（柱宽度）
4. 用已知 2 个锚点校准

关键已知：
- "生活方式" label x=420 y=220 → 数字 9.39 x=414 y=189
- "美的追求" label x=499 y=220 → 数字 3.29 x=493 y=189
- 这些标签在页面右侧（x>400），表明柱形图是纵向的
- 实际上我看到的是：这 2 个数字是"最大/最小"，不是 15 个项目的值

另一个思路：B6 第 15 页 "我的职业价值观一览表" 有 15 个编号（1..15）
或许需要让用户看到完整的价值观得分。

让我用另一个方法：扫描 B6 PDF 所有页面找所有数字；
然后看是否某个位置有类似 15 个 0..10 的数字序列
"""
import json
import re
from pathlib import Path
import fitz

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
TARGET_LABELS = ["创造发明", "独立自主", "美的追求", "智力激发", "利他助人",
                 "成就感", "管理权力", "工作环境", "同事关系", "上司关系",
                 "多样变化", "经济报酬", "安全稳定", "声望地位", "生活方式"]

doc = fitz.open(str(pdf_path))

# 扫描全部页面：输出所有看起来像得分的数字
print("==== 全部页面的 0..10 数字（含小数点） ====")
for page_idx in range(len(doc)):
    page = doc[page_idx]
    blocks = page.get_text("dict")["blocks"]
    for block in blocks:
        for line in block.get("lines", []):
            for span in line["spans"]:
                t = span["text"].strip()
                if not t: continue
                # 匹配数字（可能带小数点）
                m = re.match(r"^\d+\.?\d*$", t)
                if not m: continue
                try:
                    val = float(t)
                except ValueError:
                    continue
                # 只关注 0..10 的数字，且字体较大（score 数字一般较大）
                if 0 <= val <= 10 and span["size"] >= 9:
                    bbox = span["bbox"]
                    print(f"  p{page_idx+1:2d} x={bbox[0]:.0f} y={bbox[1]:.0f} size={span['size']:.1f} val={t}")

print("\n==== 目标标签的位置 ====")
for page_idx in range(len(doc)):
    page = doc[page_idx]
    blocks = page.get_text("dict")["blocks"]
    for block in blocks:
        for line in block.get("lines", []):
            for span in line["spans"]:
                t = span["text"].strip()
                if t in TARGET_LABELS:
                    bbox = span["bbox"]
                    print(f"  p{page_idx+1:2d} x={bbox[0]:.0f} y={bbox[1]:.0f} size={span['size']:.1f} label={t}")
doc.close()
