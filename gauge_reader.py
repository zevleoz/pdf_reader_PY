#!/usr/bin/env python3
"""
仪表盘图像读取与复刻脚本
功能：
1. 读取思维模式仪表盘图片（B4 input PDF第11页）
2. 用OpenCV检测指针角度，映射到0-100分数
3. 用matplotlib复刻几乎一样的仪表盘图
"""

import cv2
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Arc
import math
import argparse


def detect_gauge_value(image_path: str) -> float:
    """
    读取仪表盘图片，检测指针角度并计算分数
    
    参数:
        image_path: 图片路径
    
    返回:
        0-100之间的分数
    
    角度映射:
        0分 → 186° (左下)
        50分 → 90° (正上)  
        100分 → 26° (右下)
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"无法读取图片: {image_path}")
    
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    
    if len(contours) < 2:
        raise ValueError("无法检测到足够的轮廓")
    
    gauge_contour = contours[0]
    
    ellipse = cv2.fitEllipse(gauge_contour)
    (cx, cy), (major_axis, minor_axis), angle = ellipse
    
    radius = max(major_axis, minor_axis) / 2 * 0.85
    
    pointer_contour = None
    min_area = radius * radius * 0.005
    max_area = radius * radius * 0.05
    
    for cnt in contours[1:]:
        area = cv2.contourArea(cnt)
        if min_area < area < max_area:
            pointer_contour = cnt
            break
    
    if pointer_contour is None:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower_blue = np.array([100, 50, 50])
        upper_blue = np.array([130, 255, 255])
        mask_blue = cv2.inRange(hsv, lower_blue, upper_blue)
        
        lower_cyan = np.array([80, 50, 50])
        upper_cyan = np.array([100, 255, 255])
        mask_cyan = cv2.inRange(hsv, lower_cyan, upper_cyan)
        
        mask_pointer = cv2.bitwise_or(mask_blue, mask_cyan)
        
        kernel = np.ones((3, 3), np.uint8)
        mask_pointer = cv2.morphologyEx(mask_pointer, cv2.MORPH_OPEN, kernel)
        
        contours_p, _ = cv2.findContours(mask_pointer, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours_p:
            pointer_contour = max(contours_p, key=cv2.contourArea)
    
    if pointer_contour is None:
        raise ValueError("无法检测到指针")
    
    M = cv2.moments(pointer_contour)
    if M["m00"] != 0:
        px = int(M["m10"] / M["m00"])
        py = int(M["m01"] / M["m00"])
    else:
        rect = cv2.boundingRect(pointer_contour)
        px = rect[0] + rect[2] // 2
        py = rect[1] + rect[3] // 2
    
    dx = px - cx
    dy = py - cy
    
    raw_angle = math.degrees(math.atan2(-dy, dx))
    
    if raw_angle < 0:
        raw_angle += 360
    
    print(f"检测到的原始角度: {raw_angle:.1f}°")
    print(f"圆心: ({cx:.1f}, {cy:.1f}), 指针端点: ({px:.1f}, {py:.1f})")
    
    if raw_angle >= 186 or raw_angle <= 26:
        if raw_angle >= 186:
            angle_diff = raw_angle - 186
        else:
            angle_diff = (360 - 186) + raw_angle
        
        total_range = (360 - 186) + 26
        value = (angle_diff / total_range) * 100
    else:
        value = ((186 - raw_angle) / (186 - 26)) * 100
    
    value = max(0, min(100, value))
    
    return value


def plot_gauge(value: float, output_path: str = None):
    """
    用matplotlib绘制思维模式仪表盘图
    
    参数:
        value: 0-100的分数
        output_path: 输出图片路径（可选）
    """
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
    fig, ax = plt.subplots(figsize=(10, 6), dpi=150)
    ax.set_xlim(-130, 130)
    ax.set_ylim(-40, 140)
    ax.set_aspect('equal')
    ax.axis('off')
    
    cx, cy = 0, 80
    radius = 100
    
    start_angle = 186
    end_angle = 26
    
    arc_length = (360 - start_angle) + end_angle
    angle_per_score = arc_length / 100
    
    pointer_angle = start_angle - value * angle_per_score
    if pointer_angle < 0:
        pointer_angle += 360
    
    pointer_rad = math.radians(pointer_angle)
    px = cx + radius * 0.85 * math.cos(pointer_rad)
    py = cy + radius * 0.85 * math.sin(pointer_rad)
    
    score_ratio = value / 100
    r = int(45 + score_ratio * 200)
    g = int(157 - score_ratio * 90)
    b = int(143 - score_ratio * 80)
    pointer_color = f'#{r:02x}{g:02x}{b:02x}'
    
    left_arc = Arc((cx, cy), 2*radius, 2*radius, angle=0,
                   theta1=start_angle, theta2=90,
                   color='#2A9D8F', linewidth=18)
    ax.add_patch(left_arc)
    
    right_arc = Arc((cx, cy), 2*radius, 2*radius, angle=0,
                    theta1=90, theta2=end_angle,
                    color='#E76F51', linewidth=18)
    ax.add_patch(right_arc)
    
    mid_arc = Arc((cx, cy), 2*radius, 2*radius, angle=0,
                  theta1=95, theta2=85,
                  color='#26D0CE', linewidth=18)
    ax.add_patch(mid_arc)
    
    for i in range(11):
        tick_score = i * 10
        tick_angle = start_angle - tick_score * angle_per_score
        if tick_angle < 0:
            tick_angle += 360
        
        tick_rad = math.radians(tick_angle)
        
        inner_r = radius - 22
        outer_r_long = radius - 8
        outer_r_short = radius - 14
        
        x1 = cx + inner_r * math.cos(tick_rad)
        y1 = cy + inner_r * math.sin(tick_rad)
        
        if i % 2 == 0:
            x2 = cx + outer_r_long * math.cos(tick_rad)
            y2 = cy + outer_r_long * math.sin(tick_rad)
            ax.plot([x1, x2], [y1, y2], color='white', linewidth=2.5)
            
            label_r = radius + 15
            lx = cx + label_r * math.cos(tick_rad)
            ly = cy + label_r * math.sin(tick_rad) + 4
            ax.text(lx, ly, str(tick_score), fontsize=9, fontweight='bold',
                    color='#1A1A1A', ha='center')
        else:
            x2 = cx + outer_r_short * math.cos(tick_rad)
            y2 = cy + outer_r_short * math.sin(tick_rad)
            ax.plot([x1, x2], [y1, y2], color='white', linewidth=1)
    
    ax.plot([cx, px], [cy, py], color='#1F2937', linewidth=3, solid_capstyle='round')
    
    ax.scatter(px, py, s=50, color='#1F2937', zorder=5)
    ax.scatter(px, py, s=20, color='white', zorder=6)
    
    ax.scatter(cx, cy, s=60, color='#1F2937', zorder=5)
    ax.scatter(cx, cy, s=25, color='white', zorder=6)
    
    ax.text(-95, -25, '固定型思维模式', fontsize=10, fontweight='bold', color='#2A9D8F', ha='center')
    ax.text(-95, -35, 'FIXED MINDSET', fontsize=7, color='#2A9D8F', ha='center')
    
    ax.text(95, -25, '成长型思维模式', fontsize=10, fontweight='bold', color='#E76F51', ha='center')
    ax.text(95, -35, 'GROWTH MINDSET', fontsize=7, color='#E76F51', ha='center')
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight', pad_inches=0)
        print(f"仪表盘图片已保存: {output_path}")
    
    plt.close()


def main():
    parser = argparse.ArgumentParser(description='仪表盘图像读取与复刻')
    parser.add_argument('image_path', help='输入仪表盘图片路径')
    parser.add_argument('--output', '-o', help='输出复刻图片路径', default='gauge_output.png')
    parser.add_argument('--value', '-v', type=float, help='直接指定分数（0-100），跳过图像检测')
    
    args = parser.parse_args()
    
    if args.value is not None:
        value = args.value
        print(f"使用指定分数: {value:.1f}")
    else:
        print(f"正在读取图片: {args.image_path}")
        value = detect_gauge_value(args.image_path)
        print(f"检测到的分数: {value:.1f}")
    
    plot_gauge(value, args.output)
    
    return value


if __name__ == '__main__':
    main()
