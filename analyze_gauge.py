import cv2
import numpy as np
import math

img = cv2.imread('/Users/jefflau/projects/pdf_report_converter/PDF_converter/pages/report_B4_vision_10.png')
print(f'图片尺寸: {img.shape}')

gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

center_x, center_y, radius = 477, 678, 298
print(f'\n分析仪表盘: 圆心=({center_x},{center_y}), 半径={radius}')

print("\n扫描整个圆内的深色像素（可能是指针）:")
dark_points = []
for r_factor in np.linspace(0.2, 0.9, 20):
    r = int(radius * r_factor)
    for angle_deg in range(360):
        angle_rad = math.radians(angle_deg)
        px = int(center_x + r * math.cos(angle_rad))
        py = int(center_y - r * math.sin(angle_rad))
        if 0 <= px < img.shape[1] and 0 <= py < img.shape[0]:
            gray_val = int(gray[py, px])
            if gray_val < 100:
                b, g, r_val = img[py, px]
                dark_points.append((angle_deg, r_factor, px, py, gray_val, b, g, r_val))

print(f'找到 {len(dark_points)} 个深色像素')
if dark_points:
    print("\n深色像素分布:")
    for dp in sorted(dark_points, key=lambda x: x[4])[:20]:
        print(f'  角度={dp[0]:3d}°, r={dp[1]:.2f}, ({dp[2]},{dp[3]}), 灰度={dp[4]:3d}, BGR=({dp[5]:3d},{dp[6]:3d},{dp[7]:3d})')

print("\n按角度统计深色像素:")
angle_counts = {}
for dp in dark_points:
    angle_counts[dp[0]] = angle_counts.get(dp[0], 0) + 1

for angle in sorted(angle_counts.keys()):
    if angle_counts[angle] > 5:
        print(f'  角度 {angle:3d}°: {angle_counts[angle]} 个深色像素')

print("\n检查角度40-50度区域（可能是指针末端）:")
for angle_deg in range(40, 51):
    angle_rad = math.radians(angle_deg)
    for r_factor in [0.7, 0.75, 0.8, 0.85]:
        r = int(radius * r_factor)
        px = int(center_x + r * math.cos(angle_rad))
        py = int(center_y - r * math.sin(angle_rad))
        if 0 <= px < img.shape[1] and 0 <= py < img.shape[0]:
            b, g, r_val = img[py, px]
            gray_val = gray[py, px]
            print(f'  角度{angle_deg}°, r={r_factor:.2f}: ({px},{py}), BGR=({b:3d},{g:3d},{r_val:3d}), 灰度={gray_val:3d}')

print("\n检查角度50度附近的线特征:")
edges = cv2.Canny(gray, 30, 100)
lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=20, minLineLength=50, maxLineGap=5)

if lines is not None:
    for line in lines:
        x1, y1, x2, y2 = line[0]
        dist1 = math.sqrt((x1-center_x)**2 + (y1-center_y)**2)
        dist2 = math.sqrt((x2-center_x)**2 + (y2-center_y)**2)
        
        if (dist1 < radius * 0.3 or dist2 < radius * 0.3) and max(dist1, dist2) > radius * 0.5:
            angle1 = math.degrees(math.atan2(center_y - y1, x1 - center_x))
            angle2 = math.degrees(math.atan2(center_y - y2, x2 - center_x))
            if angle1 < 0: angle1 += 360
            if angle2 < 0: angle2 += 360
            print(f'  线段: ({x1},{y1})-({x2},{y2}), 角度={min(angle1,angle2):.1f}°~{max(angle1,angle2):.1f}°, 长度={math.sqrt((x2-x1)**2 + (y2-y1)**2):.1f}')