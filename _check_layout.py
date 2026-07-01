import cv2
import numpy as np
import fitz

img = cv2.imread('data/page15.png')
h, w = img.shape[:2]
print(f'图像尺寸: {w}x{h}')

scale_y = h / 842.0
scale_x = w / 595.0

doc = fitz.open('input/report_B6.pdf')
page = doc[14]
words = page.get_text('words')

rank_positions = []
for word in words:
    x0, y0, x1, y1, text, _, _, _ = word
    try:
        rank = int(text)
        if 1 <= rank <= 15:
            y_img = int(y0 * scale_y)
            x_img = int(x0 * scale_x)
            rank_positions.append((rank, x_img, y_img))
    except ValueError:
        continue

rank_positions.sort(key=lambda r: r[0])

print('\n排序编号位置（图像坐标）:')
for rank, x, y in rank_positions:
    print(f'  排名 {rank}: ({x},{y})')

margin_top = int(h * 0.15)
margin_bottom = int(h * 0.52)
margin_left = int(w * 0.05)

print(f'\n条形图区域:')
print(f'  顶部: {margin_top}')
print(f'  底部: {margin_bottom}')
print(f'  左侧: {margin_left}')

label_region = img[margin_top:margin_bottom, margin_left:margin_left+300]
lh, lw = label_region.shape[:2]

gray = cv2.cvtColor(label_region, cv2.COLOR_RGB2GRAY)
blur = cv2.GaussianBlur(gray, (5, 5), 0)
_, thresh = cv2.threshold(blur, 200, 255, cv2.THRESH_BINARY_INV)

contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

text_boxes = []
for contour in contours:
    area = cv2.contourArea(contour)
    if area < 30 or area > 1500:
        continue
    bx, by, bw, bh = cv2.boundingRect(contour)
    text_boxes.append((bx, by, bw, bh))

text_boxes.sort(key=lambda b: b[1])

grouped = []
current_group = []
for bx, by, bw, bh in text_boxes:
    if not current_group:
        current_group.append((bx, by, bw, bh))
    else:
        last_bottom = current_group[-1][1] + current_group[-1][3]
        if by - last_bottom < 30:
            current_group.append((bx, by, bw, bh))
        else:
            grouped.append(current_group)
            current_group = [(bx, by, bw, bh)]
if current_group:
    grouped.append(current_group)

labels = ['创造发明', '独立自主', '美的追求', '智力激发', '利他助人',
          '成就感', '管理权力', '工作环境', '同事关系', '上司关系',
          '多样变化', '经济报酬', '安全稳定', '声望地位', '生活方式']

print('\n条形图标签位置（图像坐标）:')
for i, group in enumerate(grouped[:15]):
    group_y = min(b[1] for b in group)
    img_y = group_y + margin_top
    print(f'  {labels[i]}: y={img_y}')

doc.close()
