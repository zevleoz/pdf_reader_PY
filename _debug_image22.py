"""在 B6 所有页面中搜索所有两位小数的数字（x.xx 格式），看能否找到职业价值观的数值。"""
import fitz, re
from pathlib import Path

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))

# 在每个页面的文本层中，找所有 x.xx 格式的数字
known_vals = {'创造发明': 7.70, '独立自主': 8.56, '美的追求': 3.29,
              '智力激发': 5.16, '利他助人': 9.36, '成就感': 6.48,
              '管理权力': 6.73, '工作环境': 9.32, '同事关系': 6.79,
              '上司关系': 6.67, '多样变化': 9.39, '经济报酬': 5.46,
              '安全稳定': 0, '声望地位': 8.39, '生活方式': 9.39}
known_strs = {f"{v:.2f}": k for k, v in known_vals.items() if k != '安全稳定'}

print("=== B6 所有页面中 x.xx 格式数字的分布 ===\n")
all_xx = set()
for p in range(len(doc)):
    txt = doc[p].get_text("text")
    nums = re.findall(r"\b\d\.\d{2}\b", txt)
    if nums:
        known_hits = [(n, known_strs[n]) for n in nums if n in known_strs]
        print(f"  第 {p+1} 页: {set(nums)}")
        if known_hits:
            print(f"    -> 可能是职业价值观: {known_hits}")
        all_xx.update(nums)

print(f"\n总共找到 {len(all_xx)} 个不同的 x.xx 数字")
print(f"已知的 14 个职业价值观数值: {sorted(known_strs.keys())}")

# 找是否有一个 x.xx 数字，在任何页面都没有对应已知的 14 个数值
# 那可能就是安全稳定
all_known = set(known_strs.keys())
unknown = all_xx - all_known
print(f"\n未匹配的 x.xx 数字: {sorted(unknown)}")
if unknown:
    print("  这些可能是安全稳定的数值！")

doc.close()
