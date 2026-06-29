"""精确模拟 extract.py 中 fallback 的数值生成逻辑，验证数值来源。"""
import fitz, numpy as np, json
from pathlib import Path

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))

# 模拟：y=420-680 分 15 段
page = doc[13]
zoom = 3.0
mat = fitz.Matrix(zoom, zoom)
pix = page.get_pixmap(matrix=mat, alpha=False)
img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
if img.shape[2] == 4:
    img = img[:, :, :3]
gray = np.mean(img, axis=2).astype(np.uint8)
dark_mask = gray < 150

y_min, y_max = 420, 680
n_seg = 15
seg_h = (y_max - y_min) / n_seg
x_start_pdf, x_end_pdf = 160, 450

val_labels_order = ['创造发明', '独立自主', '美的追求', '智力激发', '利他助人',
                     '成就感', '管理权力', '工作环境', '同事关系', '上司关系',
                     '多样变化', '经济报酬', '安全稳定', '声望地位', '生活方式']

# 当前 fallback 的逻辑：检测每个段的柱形条长度
bar_lengths = []
for i in range(n_seg):
    ys_img = int((y_min + i * seg_h) * zoom)
    ye_img = int((y_min + (i + 1) * seg_h) * zoom)
    xs_img = int(x_start_pdf * zoom)
    xe_img = int(x_end_pdf * zoom)
    if ye_img > gray.shape[0]: ye_img = gray.shape[0]
    if xe_img > gray.shape[1]: xe_img = gray.shape[1]
    if ys_img >= ye_img or xs_img >= xe_img:
        continue
    sub = dark_mask[ys_img:ye_img, xs_img:xe_img]
    if sub.size == 0: continue
    col_counts = sub.sum(axis=0)
    if len(col_counts) == 0 or col_counts.max() < 5:
        print(f"  段{i+1} ({val_labels_order[i]}): SKIPPED (max_col={col_counts.max() if len(col_counts) else 0})")
        continue
    max_c = col_counts.max()
    threshold = max_c * 0.15
    right_end_img = -1
    for j in range(len(col_counts) - 1, -1, -1):
        if col_counts[j] >= threshold:
            right_end_img = j
            break
    if right_end_img > 0:
        right_end_pdf = x_start_pdf + right_end_img / zoom
        length = right_end_pdf - x_start_pdf
        bar_lengths.append((i, length))
        print(f"  段{i+1} ({val_labels_order[i]}): length={length:.0f}, max_col={max_c}")
    else:
        print(f"  段{i+1} ({val_labels_order[i]}): right_end=0 SKIPPED")

doc.close()

# 当前 fallback 用 max/min 做线性校准
if bar_lengths:
    lengths = [l for _, l in bar_lengths]
    max_len, min_len = max(lengths), min(lengths)
    print(f"\nmax_len={max_len:.0f}, min_len={min_len:.0f}")
    scores = {}
    for i, length in bar_lengths:
        if max_len != min_len:
            score = 3.29 + (length - min_len) / (max_len - min_len) * (9.39 - 3.29)
        else:
            score = 5.0
        scores[val_labels_order[i]] = score
        print(f"  {val_labels_order[i]}: est={score:.2f}")

    # 与 report_data.json 中实际值比较
    data = json.loads(Path('data/report_data.json').read_text(encoding='utf-8'))
    actual = {}
    for item in data['schema_124']:
        code = item['code']
        if 104 <= int(code) <= 118:
            label = item['label'].replace('得分', '').strip()
            actual[label] = item['value']

    print(f"\n=== fallback 估计值 vs 实际值 ===")
    for label in val_labels_order:
        est = scores.get(label, "N/A")
        act = actual.get(label, "")
        diff = None
        if est != "N/A" and act:
            try: diff = abs(float(est) - float(act))
            except: pass
        print(f"  {label}: est={est:.2f if isinstance(est, float) else est}, actual={act}, diff={diff if diff is not None else 'N/A'}")
