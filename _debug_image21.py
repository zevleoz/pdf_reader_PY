"""模拟 extract.py 中职业价值观的完整提取逻辑。"""
import fitz, re
from pathlib import Path

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))

# 读取整个 B6 的文本
b6 = ""
for p in range(len(doc)):
    b6 += doc[p].get_text("text")

# 1. 检查 anchor_idx
anchor_idx = max(b6.find("得分情况如下"),
                 b6.find("我的职业价值观   丨"),
                 b6.find("MY WORK VALUES"))
print(f"anchor_idx = {anchor_idx}")
print(f"anchor text: {repr(b6[anchor_idx:anchor_idx+50])}\n")

# 2. 检查 seg_vals
seg_vals = b6[anchor_idx: anchor_idx + 1500]
lines = [l.strip() for l in seg_vals.splitlines() if l.strip()]
print(f"seg_vals has {len(lines)} 行")
for i, ln in enumerate(lines):
    print(f"  L{i}: {repr(ln)}")
    if i > 40:
        print("  ... (truncated)")
        break

# 3. 检查 纯数字行 + 标签行 模式
print("\n\n=== 检查 '数字行 + 标签行' 模式 ===")
num_cache = None
val_labels_order = ['创造发明', '独立自主', '美的追求', '智力激发', '利他助人',
                     '成就感', '管理权力', '工作环境', '同事关系', '上司关系',
                     '多样变化', '经济报酬', '安全稳定', '声望地位', '生活方式']
for i, ln in enumerate(lines):
    if re.match(r"^[\d.]+$", ln):
        num_cache = ln
        continue
    if num_cache is not None and ln in val_labels_order:
        print(f"  MATCH: {num_cache} -> {ln}")
        num_cache = None
        continue
    if ln in ("最高分", "最低分"):
        num_cache = None
        continue
    if any("\u4e00" <= c <= "\u9fff" for c in ln):
        num_cache = None

# 4. 检查 _score_after_kw 模式（关键词后找数字）
print("\n\n=== 检查每个标签前后的数字（_score_after_kw 模式） ===")
def score_after_kw(kw, text, max_chars=400):
    i = text.find(kw)
    if i < 0: return None
    seg = text[i: i + max_chars]
    # 1) 优先 "X分"
    m = re.search(r"([\d.]+)\s*分", seg)
    if m: return m.group(1)
    # 2) 找独立数字行
    lines = [l.strip() for l in seg.splitlines() if l.strip()]
    for idx, ln in enumerate(lines[:10]):
        if re.match(r"^[\d.]+$", ln):
            prev = lines[idx - 1] if idx > 0 else ""
            if re.match(r"^NO[.:：\s]", prev):
                continue
            n = ln
            if n in ("0", "10"): continue
            return n
    # 3) 回退
    nums = re.findall(r"\b(\d+(?:\.\d+)?)\b", seg)
    for n in nums:
        if n in ("0", "10"): continue
        if n.isdigit() and 1 <= int(n) <= 10:
            return n
    if nums: return nums[0]
    return None

for kw in val_labels_order:
    v = score_after_kw(kw, b6, max_chars=400)
    print(f"  {kw}: {v}")

doc.close()
