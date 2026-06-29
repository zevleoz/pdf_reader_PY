"""在 B6 所有页面文本层中，搜索可能的 '安全稳定' 数值（小数点后2位的数字）。"""
import fitz, re
from pathlib import Path

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))

# 策略：在每页中，搜索 "安全稳定" 前后的数字（特别是 x.xx 格式的数字）
# 也搜索其他 14 项标签附近的数字格式
labels = ['创造发明', '独立自主', '美的追求', '智力激发', '利他助人',
           '成就感', '管理权力', '工作环境', '同事关系', '上司关系',
           '多样变化', '经济报酬', '安全稳定', '声望地位', '生活方式']

# 已知数值
known = {'创造发明': '7.70', '独立自主': '8.56', '美的追求': '3.29',
         '智力激发': '5.16', '利他助人': '9.36', '成就感': '6.48',
         '管理权力': '6.73', '工作环境': '9.32', '同事关系': '6.79',
         '上司关系': '6.67', '多样变化': '9.39', '经济报酬': '5.46',
         '安全稳定': '???', '声望地位': '8.39', '生活方式': '9.39'}

for p in range(len(doc)):
    txt = doc[p].get_text("text")
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    # 找任何包含 x.xx 格式数字的行，特别是与职业价值观相关的行
    for i, line in enumerate(lines):
        # 检查是否是 x.xx 格式
        if re.match(r"^\d\.\d{2}$", line):
            # 检查前后 5 行是否有标签
            context_window = lines[max(0, i-5):min(len(lines), i+5)]
            labels_in_window = [l for l in labels if any(l in cl for cl in context_window)]
            if labels_in_window:
                print(f"  第 {p+1} 页, 行 {i}: value={line}, labels_in_window={labels_in_window}")

print("\n=== 另外，检查所有页面中 '安全稳定' 前后 300 字符 ===")
all_txt = "\n".join([doc[p].get_text("text") for p in range(len(doc))])
for m in re.finditer(r"安全稳定", all_txt):
    start = max(0, m.start() - 300)
    end = min(len(all_txt), m.end() + 300)
    print(f"--- Match at pos {m.start()} ---")
    print(all_txt[start:end])
    print()

doc.close()
