# -*- coding: utf-8 -*-
"""generate.py —— 综合测评报告 PDF 生成（18 页版本）。

严格按照 output/reference.pdf 的页面结构与版式输出。页面结构：
  P01 封面
  P02 Y4 | Youth Profile in Four Dimensions （介绍页）
  P03 1. 心力｜情绪与动力系统
  P04 情绪稳定性
  P05 自我概念
  P06 依恋关系
  P07 内驱力 / 思维模式
  P08 人格 / Big Five
  P09 2. 精力｜精力管理与身体健康系统
  P10 体质健康
  P11 3. 学习力｜学习系统
  P12 认知能力
  P13 执行功能
  P14 学习动机与策略
  P15 4. 生涯力｜专业与职业发展系统
  P16 职业兴趣 / Holland
  P17 能力优势 / Multiple Intelligences
  P18 职业价值观 / Work Values

输出：
  - output/report.html
  - output/report.pdf
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from data_points import POINT_META, USER_DATA, apply_report_data, student_meta, mean_val


# ======================================================================
# 便捷函数：读取某个数据点的值
# ======================================================================

def v(code: str) -> Any:
    """取某个编号的学生值。"""
    return USER_DATA.get(code, "")


def m(label: str, default: Any = None) -> Any:
    """取同龄平均值，按 label 查找。"""
    return mean_val(label, default)


def label(code: str) -> str:
    """取某个编号的中文标签。"""
    meta = POINT_META.get(code, {})
    return meta.get("label", code)


def fmt(val: Any) -> str:
    """把任意值格式化成字符串；空值占位为 -。"""
    if val is None or val == "":
        return "-"
    if isinstance(val, float):
        if val.is_integer():
            return str(int(val))
        return f"{val:g}"
    return str(val)


def to_float(val: Any, default: float = 0.0) -> float:
    """把任意值转成 float，失败返回 default。"""
    try:
        if val is None or val == "":
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def row(code: str) -> Dict[str, str]:
    """构建通用的 {label, value} 字典。"""
    return {"label": label(code), "value": fmt(v(code))}


# ======================================================================
# SVG 坐标预计算（避免在 Jinja 模板中做三角函数运算）
# ======================================================================

def gauge_svg(value: float, max_value: float) -> Dict[str, Any]:
    """生成仪表盘 SVG 数据 (半圆 180 度)。"""
    cx, cy, radius = 200, 160, 120
    try:
        value = float(value) if value not in (None, "") else 0.0
    except (TypeError, ValueError):
        value = 0.0
    try:
        max_value = float(max_value) if max_value not in (None, "") else 100.0
    except (TypeError, ValueError):
        max_value = 100.0
    ratio = max(0.0, min(1.0, value / max_value)) if max_value > 0 else 0.0
    start_x = cx - radius
    start_y = cy
    angle = math.pi - ratio * math.pi
    end_x = cx + radius * math.cos(angle)
    end_y = cy - radius * math.sin(angle)
    large_arc = 0
    arc_path = (f"M {start_x:.1f} {start_y:.1f} "
                f"A {radius} {radius} 0 {large_arc} 1 {end_x:.1f} {end_y:.1f}")
    full_path = f"M {start_x:.1f} {start_y:.1f} A {radius} {radius} 0 0 1 {cx + radius:.1f} {cy:.1f}"
    return {
        "cx": cx, "cy": cy, "radius": radius,
        "arc_path": arc_path, "full_path": full_path,
        "needle_x": end_x, "needle_y": end_y,
        "value": fmt(value), "max": fmt(max_value),
    }


def circular_gauge_svg(value: float, max_value: float) -> Dict[str, Any]:
    """生成圆形仪表盘 SVG 数据。"""
    cx, cy = 60, 60
    radius = 50
    try:
        value = float(value) if value else 0.0
    except (ValueError, TypeError):
        value = 0.0
    try:
        max_value = float(max_value) if max_value else 100.0
    except (ValueError, TypeError):
        max_value = 100.0
    ratio = max(0.0, min(1.0, value / max_value)) if max_value > 0 else 0.0
    start_angle = -math.pi / 2
    end_angle = start_angle + ratio * 2 * math.pi
    start_x = cx + radius * math.cos(start_angle)
    start_y = cy + radius * math.sin(start_angle)
    end_x = cx + radius * math.cos(end_angle)
    end_y = cy + radius * math.sin(end_angle)
    large_arc = 1 if ratio > 0.5 else 0
    arc_path = (f"M {start_x:.1f} {start_y:.1f} "
                f"A {radius} {radius} 0 {large_arc} 1 {end_x:.1f} {end_y:.1f}")
    full_circle_path = f"M {cx + radius} {cy} A {radius} {radius} 0 1 1 {cx - radius} {cy} A {radius} {radius} 0 1 1 {cx + radius} {cy}"
    return {
        "cx": cx, "cy": cy, "radius": radius,
        "arc_path": arc_path, "full_path": full_circle_path,
        "value": fmt(value), "max": fmt(max_value),
        "needle_x": end_x, "needle_y": end_y,
    }


def mindset_gauge_svg(value: float) -> Dict[str, Any]:
    """生成思维模式半圆仪表盘 SVG 数据，99%还原参考图片。
    
    参考图片特点：
    - 半圆弧形，刻度0-100
    - 刻度线：每10一个大刻度，中间有小刻度
    - 颜色渐变：左侧青色(#2A9D8F) → 中间黄色(#F4A261) → 右侧橙色(#E76F51)
    - 指针：从底部中心向上指，指向刻度线附近
    - 底部文字：固定型思维模式(左侧青色)，成长型思维模式(右侧橙色)
    """
    cx, cy = 200, 160
    radius = 130
    inner_radius = 100
    tick_short_r = 118
    tick_long_r = 112
    
    ratio = max(0.0, min(1.0, value / 100.0))
    
    angle = math.pi - ratio * math.pi
    
    # 指针指向刻度线附近（inner_radius - 8）
    needle_r = inner_radius - 8
    needle_x = cx + needle_r * math.cos(angle)
    needle_y = cy - needle_r * math.sin(angle)
    
    ticks = []
    labels = []
    for i in range(0, 11):
        tick_ratio = i / 10.0
        tick_angle = math.pi - tick_ratio * math.pi
        x1 = cx + inner_radius * math.cos(tick_angle)
        y1 = cy - inner_radius * math.sin(tick_angle)
        
        if i % 2 == 0:
            x2 = cx + tick_long_r * math.cos(tick_angle)
            y2 = cy - tick_long_r * math.sin(tick_angle)
            ticks.append({
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "long": True
            })
            labels.append({
                "x": cx + (radius + 18) * math.cos(tick_angle),
                "y": cy - (radius + 18) * math.sin(tick_angle) + 4,
                "text": str(i * 10)
            })
        else:
            x2 = cx + tick_short_r * math.cos(tick_angle)
            y2 = cy - tick_short_r * math.sin(tick_angle)
            ticks.append({
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "long": False
            })
    
    arc_segments = []
    segment_angle = math.pi / 10
    for i in range(10):
        start_angle = math.pi - i * segment_angle
        end_angle = math.pi - (i + 1) * segment_angle
        sx = cx + inner_radius * math.cos(start_angle)
        sy = cy - inner_radius * math.sin(start_angle)
        ex = cx + inner_radius * math.cos(end_angle)
        ey = cy - inner_radius * math.sin(end_angle)
        
        if i < 4:
            color = "#2A9D8F"
        elif i < 7:
            color = "#F4A261"
        else:
            color = "#E76F51"
        
        large_arc = 0
        path = (f"M {sx:.1f} {sy:.1f} "
                f"A {inner_radius} {inner_radius} 0 {large_arc} 1 {ex:.1f} {ey:.1f}")
        arc_segments.append({"path": path, "color": color})
    
    return {
        "cx": cx, "cy": cy,
        "radius": radius, "inner_radius": inner_radius,
        "needle_x": needle_x, "needle_y": needle_y,
        "needle_start_x": cx, "needle_start_y": cy,
        "ticks": ticks,
        "labels": labels,
        "arc_segments": arc_segments,
        "value": fmt(value),
    }


def radar_svg(items: List[Dict[str, Any]],
              max_value: float,
              radius: int = 140,
              cx: int = 200,
              cy: int = 200,
              color: str = "#2A9D8F",
              ring_count: int = 4,
              label_padding: int = 40) -> Dict[str, Any]:
    """生成雷达图（N 边形）SVG 数据。在 Python 中预计算所有坐标。
    
    确保 viewBox 起始点为正数，所有标签都在 viewBox 范围内。
    """
    num = len(items)
    
    # 计算需要的顶部空间，确保 cy 足够大
    label_height = 35  # 标签文字高度（标签+英文+数值）
    top_space_needed = radius + label_padding + label_height + 10
    
    # 自动调整 cy，确保顶部标签在正数区域
    actual_cy = max(cy, top_space_needed)
    
    rings = []
    for r in range(1, ring_count + 1):
        rr = radius * r / ring_count
        pts = []
        for i in range(num):
            ang = math.pi / 2 - (2 * math.pi / num) * i
            px = cx + rr * math.cos(ang)
            py = actual_cy - rr * math.sin(ang)
            pts.append(f"{px:.1f},{py:.1f}")
        rings.append(" ".join(pts))
    val_pts = []
    dots = []
    labels = []
    for i, it in enumerate(items):
        val = to_float(it.get("value", 0), 0)
        ratio = max(0.0, min(1.0, val / max_value)) if max_value > 0 else 0.0
        rr = radius * ratio
        ang = math.pi / 2 - (2 * math.pi / num) * i
        px = cx + rr * math.cos(ang)
        py = actual_cy - rr * math.sin(ang)
        val_pts.append(f"{px:.1f},{py:.1f}")
        dots.append({"x": f"{px:.1f}", "y": f"{py:.1f}"})
        lx = cx + (radius + label_padding) * math.cos(ang)
        ly = actual_cy - (radius + label_padding) * math.sin(ang)
        labels.append({
            "x": f"{lx:.1f}", "y": f"{ly:.1f}",
            "label": it.get("label", ""),
            "en": it.get("en", ""),
            "letter": it.get("letter", ""),
            "value": fmt(val),
        })
    axes = []
    for i in range(num):
        ang = math.pi / 2 - (2 * math.pi / num) * i
        ax = cx + radius * math.cos(ang)
        ay = actual_cy - radius * math.sin(ang)
        axes.append({"x1": cx, "y1": actual_cy, "x2": f"{ax:.1f}", "y2": f"{ay:.1f}"})
    
    # viewBox 从 (0, 0) 开始，确保 PDF 兼容
    margin = 20
    min_x = max(0, cx - radius - label_padding - margin)
    max_x = cx + radius + label_padding + margin
    min_y = 0
    max_y = actual_cy + radius + label_padding + 30
    
    viewBox_w = max_x - min_x
    viewBox_h = max_y - min_y
    
    # 确保最小尺寸
    viewBox_w = max(viewBox_w, 400)
    viewBox_h = max(viewBox_h, 400)
    
    return {
        "cx": cx, "cy": actual_cy, "radius": radius,
        "rings": rings, "axes": axes,
        "polygon_points": " ".join(val_pts),
        "dots": dots, "labels": labels,
        "color": color,
        "viewBox": f"0 0 {viewBox_w:.1f} {viewBox_h:.1f}",
    }


def normal_dist_svg(percentile: float) -> Dict[str, Any]:
    """生成正态分布柱状图 SVG 数据。"""
    # 13 根柱子组成钟形
    heights = [5, 12, 22, 35, 50, 65, 72, 65, 50, 35, 22, 12, 5]
    bars = []
    bar_width = 32
    start_x = 20
    base_y = 110  # 基线 y 位置，柱高从这里向上
    for i, h in enumerate(heights):
        x = start_x + i * bar_width
        h_px = h * 1.0
        bars.append({
            "x": x, "y": base_y - h_px,
            "w": bar_width - 6, "h": h_px,
        })
    # 用户标记的 x 位置：percentile% 在整个宽度
    idx = (percentile / 100.0) * (len(heights) - 1)
    idx_int = int(round(idx))
    mark_x = start_x + idx_int * bar_width + (bar_width - 6) / 2
    return {
        "bars": bars,
        "marker_x": mark_x,
        "base_y": base_y,
        "percentile": fmt(percentile),
    }


def body_figure_svg(level: str, active: bool,
                    color: str = "#2A9D8F") -> Dict[str, Any]:
    """生成人形 SVG（BMI 等级）。"""
    body_profiles = {
        "偏瘦": {"w": 10, "h": 55, "arm_w": 3, "leg_w": 3, "leg_spread": 1, "waist": 8},
        "Low": {"w": 10, "h": 55, "arm_w": 3, "leg_w": 3, "leg_spread": 1, "waist": 8},
        "正常": {"w": 15, "h": 52, "arm_w": 4, "leg_w": 4, "leg_spread": 3, "waist": 12},
        "Normal": {"w": 15, "h": 52, "arm_w": 4, "leg_w": 4, "leg_spread": 3, "waist": 12},
        "超重": {"w": 22, "h": 48, "arm_w": 5, "leg_w": 5, "leg_spread": 5, "waist": 18},
        "Overweight": {"w": 22, "h": 48, "arm_w": 5, "leg_w": 5, "leg_spread": 5, "waist": 18},
        "肥胖": {"w": 30, "h": 45, "arm_w": 6, "leg_w": 6, "leg_spread": 8, "waist": 26},
        "Obesity": {"w": 30, "h": 45, "arm_w": 6, "leg_w": 6, "leg_spread": 8, "waist": 26},
    }
    bp = body_profiles.get(level, body_profiles["正常"])
    cx = 30
    head_r = 8
    head_y = 12
    body_top = head_y + head_r + 3
    if active:
        color = "#E76F51"
    return {
        "cx": cx, "head_r": head_r, "head_y": head_y,
        "body_w": bp["w"], "body_h": bp["h"],
        "body_top": body_top, "body_bottom": body_top + bp["h"],
        "arm_w": bp["arm_w"], "leg_w": bp["leg_w"],
        "leg_spread": bp["leg_spread"], "waist": bp["waist"],
        "color": color,
    }


# ======================================================================
# 构建每页的视图字典
# ======================================================================

def _page_dict(layout: str,
               page_title: str = "",
               subtitle: str = "",
               page_en: str = "",
               intro: str = "",
               rows: Optional[List[Dict[str, Any]]] = None,
               **extra: Any) -> Dict[str, Any]:
    """构造统一的页面字典结构（避免使用 items/keys/values 等与 dict 内置方法冲突的键名）。"""
    data: Dict[str, Any] = {
        "layout": layout,
        "page_title": page_title,
        "subtitle": subtitle,
        "subtitle_en": page_en.upper() if page_en else "",
        "page_en": page_en,
        "intro": intro,
        "rows": rows or [],
    }
    data.update(extra)
    return data


# ---------------- P01 封面 ----------------
def build_page_1(student: Dict[str, Any]) -> Dict[str, Any]:
    info_items = [
        {"label": "姓名", "value": student.get("name", "") or "-"},
        {"label": "性别", "value": student.get("gender", "") or "-"},
        {"label": "生日", "value": student.get("birthday", "") or "-"},
        {"label": "年级", "value": student.get("grade", "") or "-"},
        {"label": "学校", "value": student.get("school", "") or "-"},
        {"label": "测评日期", "value": student.get("test_date", "") or "-"},
        {"label": "老师", "value": student.get("teacher", "") or "-"},
        {"label": "档案编号", "value": student.get("archive_id", "") or "-"},
    ]
    return _page_dict("cover",
                      page_title="综合测评报告",
                      subtitle="COMPREHENSIVE ASSESSMENT REPORT",
                      rows=info_items)


# ---------------- P02 Y4 Intro ----------------
def build_page_2() -> Dict[str, Any]:
    paragraphs = [
        "Y4 是凭远从四个相互关联的成长系统出发，对青少年当前状态、发展资源和潜在困难形成的综合画像。",
        "Y 代表 Youth，也呼应 Why。Y4 不只描述一个学生“是什么样”，也试图进一步回答：",
        "● 他为什么会产生这样的情绪和行为；",
        "● 他为什么在某些环境中充满动力，在另一些环境中难以行动；",
        "● 他为什么在某些学习任务中表现突出，却在另一些任务中频繁受阻；",
        "● 他为什么被某些方向吸引；",
        "● 什么样的成长支持，能够真正帮助他把潜能转化为未来。",
        "Y4 不以单一分数定义学生，也不把学生简单归类为某一种类型。它通过四个系统之间的联系，理解一个真实、复杂并且仍在发展中的青少年。",
    ]
    return _page_dict("y4_intro",
                      page_title="Y4 | Youth Profile in Four Dimensions",
                      subtitle="凭远教育 · 四个成长系统的综合画像",
                      paragraphs=paragraphs)


# ---------------- P03 心力系统介绍 ----------------
def build_page_3() -> Dict[str, Any]:
    return _page_dict("section_intro",
                      page_title="心力｜情绪与动力系统",
                      subtitle="EMOTIONAL & MOTIVATIONAL SYSTEM",
                      section_num="1.",
                      paragraphs=[
                          "心力，是一个青少年理解自己、稳定自己、连接他人并启动行动的内在基础。",
                          "这一系统关注的不是学生是否“情绪好”或者“性格好”，而是：",
                          "● 他是否能够在压力、失败和变化中保持基本稳定；",
                          "● 他如何评价自己、理解自己；",
                          "● 他是否相信自己有能力面对挑战；",
                          "● 他是否拥有值得信任和依靠的关系；",
                          "● 他能否表达需要，并在困难时寻求帮助；",
                          "● 他行动的动力来自哪里；",
                          "● 他如何与环境、他人和任务建立关系。",
                      ])


# ---------------- P04 情绪稳定性（009-014） ----------------
def build_page_4() -> Dict[str, Any]:
    polarity_items = [
        {"left": "自卑", "left_en": "INFERIORITY",
         "right": "自尊", "right_en": "SELF-ESTEEM",
         "value": fmt(v("011")), "code": "011",
         "max": 15},
        {"left": "抑郁", "left_en": "DEPRESSION",
         "right": "愉快", "right_en": "PLEASURE",
         "value": fmt(v("012")), "code": "012",
         "max": 15},
        {"left": "焦虑", "left_en": "ANXIETY",
         "right": "安详", "right_en": "SERENITY",
         "value": fmt(v("013")), "code": "013",
         "max": 15},
        {"left": "无力感", "left_en": "HELPLESSNESS",
         "right": "掌控感", "right_en": "CONTROLLABILITY",
         "value": fmt(v("014")), "code": "014",
         "max": 15},
    ]
    for item in polarity_items:
        s = to_float(item["value"], 7.5)
        item["pct"] = max(0, min(100, int(s / item["max"] * 100)))
    total = fmt(v("009"))
    level = fmt(v("010"))
    try:
        gauge = gauge_svg(to_float(v("009"), 30), 60.0)
    except Exception:
        gauge = gauge_svg(30.0, 60.0)
    peer_avg_val = m("情绪稳定性总分", 40)
    return _page_dict("emotional_stability",
                      page_title="情绪稳定性",
                      subtitle="EMOTIONAL STABILITY",
                      page_en="Emotional Stability Assessment",
                      intro="情绪稳定性是指人的情绪状态受外界或内部心理变化影响，情绪波动大小、强弱的情况。情绪稳定性的调查基于运用最多的艾森克情绪稳定性测验。心理学家艾森克认为，自卑、抑郁、焦虑、依赖他人的人，情绪更敏感、脆弱，易受到外部环境影响而情绪化。相反自尊、愉快、安详和自主的人，情绪更稳定，即使有情绪，也更容易恢复平静。",
                      total_score=total,
                      total_max=60,
                      level=level,
                      gauge=gauge,
                      peer_avg=peer_avg_val,
                      polarity_items=polarity_items)


# ---------------- P05 自我概念（051-058） ----------------
def build_page_5() -> Dict[str, Any]:
    sub_items_raw = [
        {"label": "行为表现", "en": "Behavioral Adjustment", "code": "053", "max": 10},
        {"label": "能力与学校表现", "en": "Intellectual and School Status", "code": "054", "max": 10},
        {"label": "躯体外貌", "en": "Physical Appearance and Attributes", "code": "055", "max": 10},
        {"label": "情绪状态", "en": "Freedom from Anxiety", "code": "056", "max": 10},
        {"label": "合群", "en": "Popularity", "code": "057", "max": 10},
        {"label": "幸福与满足", "en": "Happiness and Satisfaction", "code": "058", "max": 10},
    ]
    sub_items = []
    for it in sub_items_raw:
        val = to_float(v(it["code"]), 5)
        sub_items.append({
            "label": it["label"], "en": it["en"],
            "value": fmt(val), "max": it["max"],
            "pct": max(0, min(100, int(val / it["max"] * 100))),
        })
    overall = to_float(v("051"), 80)
    try:
        gauge = gauge_svg(overall, 100.0)
    except Exception:
        gauge = gauge_svg(60.0, 100.0)
    return _page_dict("self_concept",
                      page_title="自我概念",
                      subtitle="SELF CONCEPT",
                      page_en="Self-Concept Dimensions",
                      intro="自我概念是个体对自己认识的集合，个体认为的“我是谁，我是一个怎样的人”。也可以理解为个人心中对自己的印象，包括对身体、能力、性格、态度等。比如“我是聪明的”、“我是漂亮的”、“我学习好”。自我概念的发展过程是一个人个性形成和社会化发展的关键。",
                      overall_value=fmt(overall),
                      overall_range="/ 100",
                      gauge=gauge,
                      sub_items=sub_items)


# ---------------- P06 依恋关系（020-040） ----------------
def build_page_6() -> Dict[str, Any]:
    types = [
        {"role": "母亲", "type": fmt(v("020"))},
        {"role": "父亲", "type": fmt(v("021"))},
        {"role": "同伴", "type": fmt(v("022"))},
    ]
    dimensions = [
        {
            "name": "信任",
            "en": "Trust",
            "dim_items": [
                {"label": "信任", "who": "母亲", "value": fmt(v("023")), "level": fmt(v("032")), "code": "023"},
                {"label": "信任", "who": "父亲", "value": fmt(v("024")), "level": fmt(v("033")), "code": "024"},
                {"label": "信任", "who": "同伴", "value": fmt(v("025")), "level": fmt(v("034")), "code": "025"},
            ]
        },
        {
            "name": "沟通",
            "en": "Communication",
            "dim_items": [
                {"label": "沟通", "who": "母亲", "value": fmt(v("026")), "level": fmt(v("035")), "code": "026"},
                {"label": "沟通", "who": "父亲", "value": fmt(v("027")), "level": fmt(v("036")), "code": "027"},
                {"label": "沟通", "who": "同伴", "value": fmt(v("028")), "level": fmt(v("037")), "code": "028"},
            ]
        },
        {
            "name": "亲近",
            "en": "Closeness",
            "dim_items": [
                {"label": "亲近", "who": "母亲", "value": fmt(v("029")), "level": fmt(v("038")), "code": "029"},
                {"label": "亲近", "who": "父亲", "value": fmt(v("030")), "level": fmt(v("039")), "code": "030"},
                {"label": "亲近", "who": "同伴", "value": fmt(v("031")), "level": fmt(v("040")), "code": "031"},
            ]
        },
    ]
    for dim in dimensions:
        for item in dim["dim_items"]:
            s = to_float(item["value"], 5)
            item["pct"] = max(0, min(100, int(s / 50.0 * 100)))
    return _page_dict("attachment",
                      page_title="依恋关系",
                      subtitle="SOCIAL ATTACHMENT",
                      page_en="Social Attachment Dimensions",
                      intro="依恋类型，是个体早期与主要抚养者之间形成的一种最初的社会性联结，是个体与重要他人保持亲密关系的倾向。依恋类型分为安全型依恋（Secure Attachment）、回避型依恋（Avoidant Attachment）和焦虑-矛盾型依恋（Anxious-Ambivalent Attachment）。安全型依恋的个体容易与人亲近，对人表现出信任和依赖；回避型依恋的个体回避与人亲近；焦虑-矛盾型依恋的个体，期待与人亲密但又害怕与人亲密，容易纠结、矛盾。",
                      types=types,
                      dimensions=dimensions)


# ---------------- P07 内驱力（059-062） ----------------
def build_page_7() -> Dict[str, Any]:
    mindset_raw = v("059")
    # 思维模式可能是文本描述（无具体数字），需要从描述判断类型和数值
    try:
        mindset_val = float(mindset_raw)
        mindset_pct = max(0, min(100, int(mindset_val)))
        # 如果值为0，说明数据提取失败，使用默认值50（混合型）
        if mindset_val == 0:
            mindset_val = 50.0
            mindset_pct = 50
    except:
        mindset_val = 50.0
        mindset_pct = 50
    
    # 判断思维模式类型（支持文本描述）
    text_lower = str(mindset_raw).lower()
    if "成长" in str(mindset_raw) or "growth" in text_lower:
        mindset_type = "成长型思维模式"
        mindset_type_en = "Growth Mindset"
        if mindset_val == 50.0:
            mindset_val = 75.0
            mindset_pct = 75
    elif "固定" in str(mindset_raw) or "fixed" in text_lower:
        mindset_type = "固定型思维模式"
        mindset_type_en = "Fixed Mindset"
        if mindset_val == 50.0:
            mindset_val = 25.0
            mindset_pct = 25
    elif mindset_val >= 60:
        mindset_type = "成长型思维模式"
        mindset_type_en = "Growth Mindset"
    elif mindset_val <= 40:
        mindset_type = "固定型思维模式"
        mindset_type_en = "Fixed Mindset"
    else:
        mindset_type = "混合型思维模式"
        mindset_type_en = "Mixed Mindset"
    
    # 计算思维模式半圆仪表盘数据（99%还原参考图片）
    mindset_gauge = mindset_gauge_svg(mindset_val)
    
    # 三个核心维度，添加同龄平均值
    core_items_raw = [
        {"label": "自主性", "en": "Autonomy", "code": "060", "mean_label": "自主性"},
        {"label": "胜任感", "en": "Competence", "code": "061", "mean_label": "胜任感"},
        {"label": "归属感", "en": "Relatedness", "code": "062", "mean_label": "归属感"},
    ]
    core_items = []
    for it in core_items_raw:
        val = to_float(v(it["code"]), 5)
        mean_val = m(it["mean_label"], 6.0)
        pct = max(0, min(100, int(val / 10.0 * 100)))
        try:
            gauge = circular_gauge_svg(val, 10.0)
        except Exception:
            gauge = circular_gauge_svg(5.0, 10.0)
        core_items.append({
            "label": it["label"], "en": it["en"],
            "value": fmt(val), "max": 10.0,
            "pct": pct, "mean": mean_val,
            "gauge": gauge,
        })
    
    return _page_dict("inner_drive",
                      page_title="内驱力",
                      subtitle="INNER DRIVE",
                      page_en="Inner Drive Dimensions",
                      intro="",
                      mindset_value=fmt(mindset_val),
                      mindset_max=100,
                      mindset_pct=mindset_pct,
                      mindset_type=mindset_type,
                      mindset_type_en=mindset_type_en,
                      mindset_gauge=mindset_gauge,
                      core_items=core_items,
                      core_range="/ 10.0")


# ---------------- P08 人格（大五，015-019） ----------------
def build_page_8() -> Dict[str, Any]:
    big_five_items = [
        {"label": "开放性", "en": "Openness", "value": fmt(v("015"))},
        {"label": "宜人性", "en": "Agreeableness", "value": fmt(v("016"))},
        {"label": "责任心", "en": "Conscientiousness", "value": fmt(v("017"))},
        {"label": "外倾性", "en": "Extraversion", "value": fmt(v("018"))},
        {"label": "神经质", "en": "Neuroticism", "value": fmt(v("019"))},
    ]
    radar = radar_svg(big_five_items, 5.0,
                      radius=120, cy=180, color="#2A9D8F",
                      label_padding=45)
    return _page_dict("big_five",
                      page_title="人格",
                      subtitle="PERSONALITY",
                      page_en="Big Five Personality Dimensions",
                      intro="人格，是指一个人对自己、他人和外界事物所表现出的相对稳定的态度、思维方式和行为倾向。比如有人内向，有人外向；有人开放，有人保守。人格受遗传因素影响，也与能力、兴趣、理想和价值观等密切相关。它不仅关系到个体的身心健康，也与学业适应和职业发展息息相关。本测评基于大五人格理论，从内外向（外倾性）、人际相处方式（宜人性）、规则意识与自我管理（责任心）、情绪稳定程度（神经质）以及对新知识新经验的开放程度（开放性）五个方面进行评估。",
                      big_five_items=big_five_items,
                      radar=radar,
                      range_text="/ 5.0")


# ---------------- P09 精力系统介绍 ----------------
def build_page_9() -> Dict[str, Any]:
    return _page_dict("section_intro",
                      page_title="精力｜精力管理与身体健康系统",
                      subtitle="VITALITY & PHYSICAL WELLBEING SYSTEM",
                      section_num="2.",
                      paragraphs=[
                          "成长不仅发生在心理和认知层面，也建立在身体提供的能量基础之上。",
                          "一个学生可能拥有很强的认知能力和明确的目标，但如果长期睡眠不足、运动不足、饮食失衡或身体状态欠佳，他所拥有的能力就可能无法稳定表现出来。",
                          "精力系统的核心问题：",
                          "● 这个学生是否拥有持续前进所需要的身体能量和生活节律；",
                          "● 他的饮食、睡眠和运动习惯，是否在支撑而不是消耗他；",
                          "● 他是否具备基本的身体管理意识和能力。",
                      ])


# ---------------- P10 体质健康（041-050） ----------------
def build_page_10() -> Dict[str, Any]:
    health_items = [
        {"label": "饮食习惯", "en": "Diet", "score": fmt(v("045")), "level": fmt(v("046"))},
        {"label": "睡眠习惯", "en": "Sleep", "score": fmt(v("047")), "level": fmt(v("048"))},
        {"label": "运动习惯", "en": "Exercise", "score": fmt(v("049")), "level": fmt(v("050"))},
    ]
    # BMI 四格
    bmi_level_val = fmt(v("042"))
    figures = []
    level_map = [("偏瘦", "Low", "#F4A261", 0.9), ("正常", "Normal", "#2A9D8F", 1.0),
                 ("超重", "Overweight", "#E76F51", 1.05), ("肥胖", "Obesity", "#B33A3A", 1.1)]
    for lvl, lvl_en, color, scale in level_map:
        active = (lvl == bmi_level_val)
        figures.append({
            "level": lvl,
            "level_en": lvl_en,
            "color": color,
            "active": active,
            "scale": scale,
        })
    # 给 health_items 加 pct 用作进度条（基于 10.0 分制）
    for item in health_items:
        s = to_float(item["score"], 5)
        item["pct"] = max(0, min(100, int(s / 10.0 * 100)))
    return _page_dict("physical_health",
                      page_title="体质健康",
                      subtitle="PHYSICAL HEALTH",
                      page_en="Physical Health Assessment",
                      intro="健康身体对我们每个人的重要性不言而喻。没有健康，一切无从谈起。体质，是人身体的形态和功能，通常也指人的身体素质。",
                      bmi_score=fmt(v("041")),
                      bmi_level=bmi_level_val,
                      height_cm=fmt(v("043")),
                      weight_kg=fmt(v("044")),
                      figures=figures,
                      health_items=health_items,
                      health_description=v("050a"))


# ---------------- P11 学习力介绍 ----------------
def build_page_11() -> Dict[str, Any]:
    return _page_dict("section_intro",
                      page_title="学习力｜学习系统",
                      subtitle="LEARNING POWER SYSTEM",
                      section_num="3.",
                      paragraphs=[
                          "学习力不等于考试成绩，也不等于一个学生聪不聪明。",
                          "它是学生将认知资源、执行功能、学习动力和学习策略整合起来，持续理解、完成和迁移学习任务的能力。",
                          "学习力系统的核心问题：",
                          "● 这个学生在认知层面是否具备稳定而多样的信息处理能力；",
                          "● 他在学习过程中能否有效地管理自己的注意力、记忆和思维方式；",
                          "● 他学习的动力来自哪里，是出于兴趣还是外部压力；",
                          "● 他是否掌握了有效和可迁移的学习策略。",
                      ])


# ---------------- P12 认知能力（001-008） ----------------
def build_page_12() -> Dict[str, Any]:
    cognitive_items = [
        {"label": "感知觉", "en": "Perception", "value": fmt(v("003"))},
        {"label": "注意力", "en": "Attention", "value": fmt(v("004"))},
        {"label": "记忆力", "en": "Memory", "value": fmt(v("005"))},
        {"label": "推理能力", "en": "Reasoning", "value": fmt(v("006"))},
        {"label": "空间能力", "en": "Spatial Ability", "value": fmt(v("007"))},
        {"label": "加工速度", "en": "Processing Speed", "value": fmt(v("008"))},
    ]
    # 为每个认知项计算 gauge 数据
    for item in cognitive_items:
        p = to_float(item["value"], 50)
        item["pct"] = max(0, min(100, int(p)))
        try:
            cx_small, cy_small, radius_small = 70, 50, 38
            ratio = max(0.0, min(1.0, p / 100.0)) if p > 0 else 0.0
            start_x = cx_small - radius_small
            start_y = cy_small
            angle = math.pi - ratio * math.pi
            end_x = cx_small + radius_small * math.cos(angle)
            end_y = cy_small - radius_small * math.sin(angle)
            arc_path = (f"M {start_x:.1f} {start_y:.1f} "
                        f"A {radius_small} {radius_small} 0 0 1 {end_x:.1f} {end_y:.1f}")
            full_path = f"M {start_x:.1f} {start_y:.1f} A {radius_small} {radius_small} 0 0 1 {cx_small + radius_small:.1f} {cy_small:.1f}"
            item["gauge"] = {
                "cx": cx_small, "cy": cy_small, "radius": radius_small,
                "arc_path": arc_path, "full_path": full_path,
                "needle_x": end_x, "needle_y": end_y,
                "value": fmt(p), "max": "100",
            }
        except Exception:
            item["gauge"] = {
                "cx": 70, "cy": 50, "radius": 38,
                "arc_path": "M 32 50 A 38 38 0 0 1 108 50",
                "full_path": "M 32 50 A 38 38 0 0 1 108 50",
                "needle_x": 70, "needle_y": 12,
                "value": "50", "max": "100",
            }
    percentile = to_float(v("002"), 50)
    dist_svg = normal_dist_svg(percentile)
    return _page_dict("cognitive",
                      page_title="认知资源",
                      subtitle="COGNITIVE ABILITY",
                      page_en="Cognitive Resource Overview",
                      intro="认知能力是大脑加工、处理信息，认知客观事物内部逻辑，并运用知识、经验等解决问题的能力。认知的过程包括感知、记忆、想象、思考、判断等。",
                      total_score=fmt(v("001")),
                      percentile=fmt(percentile),
                      cognitive_items=cognitive_items,
                      dist_svg=dist_svg)


# ---------------- P13 执行功能（063-065） ----------------
def build_page_13() -> Dict[str, Any]:
    executive_items = [
        {"label": "抑制控制", "en": "Inhibitory Control", "value": fmt(v("063")), "color": "teal"},
        {"label": "工作记忆", "en": "Working Memory", "value": fmt(v("064")), "color": "red"},
        {"label": "认知灵活性", "en": "Cognitive Flexibility", "value": fmt(v("065")), "color": "amber"},
    ]
    for item in executive_items:
        p = to_float(item["value"], 50)
        item["pct"] = max(0, min(100, int(p)))
    radar = radar_svg(executive_items, 100.0,
                      radius=130, cx=210, cy=180,
                      color="#2A9D8F",
                      label_padding=55)
    return _page_dict("executive",
                      page_title="执行功能",
                      subtitle="EXECUTIVE FUNCTIONS",
                      page_en="Executive Functions Overview",
                      intro="执行功能是指个体协调多个认知加工过程，以达成目标的大脑高级功能。",
                      exec_items=executive_items,
                      radar=radar,
                      unit="%")


# ---------------- P14 学习动机与策略（066-071） ----------------
def build_page_14() -> Dict[str, Any]:
    mot_raw = [
        ("深层动机", "Deep Motivation", "066"),
        ("表面动机", "Surface Motivation", "067"),
        ("自我效能感", "Self-Efficacy", "068"),
    ]
    str_raw = [
        ("学习深层方法与策略", "Deep Methods and Strategies", "069"),
        ("学习表面方法与策略", "Surface Methods and Strategies", "070"),
        ("学习自我调节", "Self-Regulation", "071"),
    ]

    def _mk(items_raw):
        out = []
        for label_cn, label_en, code in items_raw:
            val = to_float(v(code), 5)
            out.append({
                "label": label_cn, "en": label_en,
                "value": fmt(val), "unit": "/10.0",
                "pct": max(0, min(100, int(val / 10.0 * 100))),
            })
        return out

    motivation_items = _mk(mot_raw)
    strategy_items = _mk(str_raw)
    return _page_dict("learning_motivation",
                      page_title="学习动机与策略",
                      subtitle="LEARNING MOTIVATION & STRATEGIES",
                      page_en="Learning Motivation and Strategies",
                      intro="学习动机是激发并维持个体不断学习的基本动力，有时也称之为学习动力。",
                      motivation_items=motivation_items,
                      strategy_items=strategy_items)


# ---------------- P15 生涯力系统介绍 ----------------
def build_page_15() -> Dict[str, Any]:
    return _page_dict("section_intro",
                      page_title="生涯力｜专业与职业发展系统",
                      subtitle="MAJOR & CAREER DEVELOPMENT SYSTEM",
                      section_num="4.",
                      paragraphs=[
                          "生涯力不是要求青少年过早确定一个终身不变的职业，而是帮助学生逐渐理解：",
                          "● 我会被什么问题吸引；",
                          "● 我擅长做什么；",
                          "● 我希望通过未来的学习和工作获得什么；",
                          "● 哪些方向能够同时承载我的兴趣、能力和价值追求。",
                          "生涯力系统的核心问题：",
                          "这个学生的兴趣、能力和价值观可以在哪里形成交汇，并逐渐发展为适合自己的专业与职业方向？",
                      ])


# ---------------- P16 职业兴趣 Holland（072-078） ----------------
def build_page_16() -> Dict[str, Any]:
    holland_items = [
        {"letter": "R", "label": "现实型", "en": "Realistic", "value": fmt(v("073"))},
        {"letter": "I", "label": "研究型", "en": "Investigative", "value": fmt(v("074"))},
        {"letter": "A", "label": "艺术型", "en": "Artistic", "value": fmt(v("075"))},
        {"letter": "S", "label": "社会型", "en": "Social", "value": fmt(v("076"))},
        {"letter": "E", "label": "事业型", "en": "Enterprising", "value": fmt(v("077"))},
        {"letter": "C", "label": "常规型", "en": "Conventional", "value": fmt(v("078"))},
    ]
    for item in holland_items:
        s = to_float(item["value"], 5)
        item["pct"] = max(0, min(100, int(s / 10.0 * 100)))
    radar = radar_svg(holland_items, 10.0,
                      radius=130, color="#2A9D8F")
    return _page_dict("holland",
                      page_title="职业兴趣",
                      subtitle="VOCATIONAL INTEREST",
                      page_en="HOLLAND VOCATIONAL INTEREST TYPES",
                      intro="",
                      code=fmt(v("072")),
                      radar=radar,
                      holland_items=holland_items)


# ---------------- P17 能力优势（079-094） ----------------
def build_page_17() -> Dict[str, Any]:
    raw_intell = [
        {"label": "语言能力", "en": "Linguistic", "short": "语言", "code": "079"},
        {"label": "逻辑数学能力", "en": "Logical-Mathematical", "short": "逻辑", "code": "080"},
        {"label": "音乐能力", "en": "Musical", "short": "音乐", "code": "081"},
        {"label": "空间能力", "en": "Spatial", "short": "空间", "code": "082"},
        {"label": "身体运动能力", "en": "Bodily-Kinesthetic", "short": "身体", "code": "083"},
        {"label": "人际关系能力", "en": "Interpersonal", "short": "人际", "code": "084"},
        {"label": "内省能力", "en": "Intrapersonal", "short": "内省", "code": "085"},
        {"label": "自然能力", "en": "Naturalist", "short": "自然", "code": "086"},
    ]
    # 计算分数并排序（从高到低）
    items_with_score = []
    for it in raw_intell:
        s = to_float(v(it["code"]), 5)
        items_with_score.append({
            "label": it["label"], "en": it["en"], "short": it["short"],
            "value": fmt(s), "score": s,
            "pct": max(0, min(100, int(s / 10.0 * 100))),
        })
    # 按分数从高到低排序
    items_sorted = sorted(items_with_score, key=lambda x: x["score"], reverse=True)
    # 标记最高分和最低分
    if items_sorted:
        items_sorted[0]["is_max"] = True
        items_sorted[-1]["is_min"] = True
    return _page_dict("intelligences",
                      page_title="能力优势",
                      subtitle="MULTIPLE INTELLIGENCES",
                      page_en="GARDNER'S MULTIPLE INTELLIGENCES",
                      intro="每个人都有自己的天赋和能力优势。当你运用自身优势学习或工作时，往往能更高效、更专注，也更容易获得成就感与愉悦感。心理学家霍华德·加德纳提出人的能力可以划分八大类。",
                      intelligence_items=items_sorted,
                      max_score=items_sorted[0]["score"] if items_sorted else 10,
                      min_score=items_sorted[-1]["score"] if items_sorted else 0)


# ---------------- P18 职业价值观（095-124） ----------------
def build_page_18() -> Dict[str, Any]:
    value_scores_raw = [
        ("创造发明", "Creativity", "095"),
        ("美的追求", "Aesthetic Pursuit", "096"),
        ("利他助人", "Altruism", "097"),
        ("管理权力", "Management Power", "098"),
        ("同事关系", "Colleague Relations", "099"),
        ("多样变化", "Variety", "100"),
        ("安全稳定", "Security", "101"),
        ("生活方式", "Lifestyle", "102"),
        ("经济报酬", "Economic Reward", "103"),
        ("声望地位", "Social Status", "104"),
        ("独立自主", "Independence", "105"),
        ("智力激发", "Intellectual Stimulation", "106"),
        ("成就满足", "Achievement", "107"),
        ("工作环境", "Work Environment", "108"),
        ("上司关系", "Supervisor Relations", "109"),
    ]

    def _to_rows(raw):
        out = []
        for cn, en, code in raw:
            val = to_float(v(code), 5)
            out.append({
                "label": cn, "en": en,
                "value": fmt(val),
                "pct": max(0, min(100, int(val / 10.0 * 100))),
            })
        return out

    score_rows = _to_rows(value_scores_raw)
    score_rows_sorted = sorted(score_rows, key=lambda x: to_float(x["value"], 0), reverse=True)
    top_values = score_rows_sorted[:5]
    for idx, item in enumerate(top_values):
        item["rank"] = idx + 1

    remaining_values = score_rows_sorted[5:]
    for idx, item in enumerate(remaining_values):
        item["rank"] = idx + 6

    columns = [
        {"title": "价值观得分（第 6-15 名）", "rows": remaining_values},
    ]

    return _page_dict("values_two_col",
                      page_title="职业价值观",
                      subtitle="WORK VALUES",
                      page_en="TOP WORK VALUES & PRIORITIES",
                      intro="",
                      top_items=top_values,
                      columns=columns)


# ======================================================================
# 构建整体视图数据
# ======================================================================

def build_view_data() -> Dict[str, Any]:
    # 回填 USER_DATA
    try:
        result = apply_report_data()
        print(f"  [数据加载] applied={result.get('applied', 0)}/{result.get('total_items', 0)}")
    except Exception as exc:
        print(f"  [警告] apply_report_data() 失败: {exc}")

    student = student_meta()
    
    # 打印关键数据点值（调试）
    key_codes = ["009", "051", "059", "060", "001", "002"]
    print(f"  [数据检查] 关键数据点: {', '.join(f'{c}={v(c)}' for c in key_codes)}")

    pages: List[Dict[str, Any]] = [
        build_page_1(student),
        build_page_2(),
        build_page_3(),
        build_page_4(),
        build_page_5(),
        build_page_6(),
        build_page_7(),
        build_page_8(),
        build_page_9(),
        build_page_10(),
        build_page_11(),
        build_page_12(),
        build_page_13(),
        build_page_14(),
        build_page_15(),
        build_page_16(),
        build_page_17(),
        build_page_18(),
    ]
    
    for page in pages:
        layout = page.get("layout", "")
        
        if layout in ("emotional_stability", "self_concept"):
            if "gauge" not in page or not isinstance(page["gauge"], dict):
                print(f"  [警告] {layout} 页面缺少 gauge，补全默认值")
                page["gauge"] = gauge_svg(50.0, 100.0)
        
        if layout == "inner_drive":
            if "mindset_gauge" not in page or not isinstance(page["mindset_gauge"], dict):
                print(f"  [警告] inner_drive 页面缺少 mindset_gauge，补全默认值")
                page["mindset_gauge"] = mindset_gauge_svg(50.0)
            core_items = page.get("core_items", [])
            if isinstance(core_items, list):
                for idx, item in enumerate(core_items):
                    if isinstance(item, dict) and ("gauge" not in item or not isinstance(item["gauge"], dict)):
                        print(f"  [警告] inner_drive core_items[{idx}] 缺少 gauge，补全默认值")
                        item["gauge"] = circular_gauge_svg(5.0, 10.0)
        
        if layout == "cognitive":
            cognitive_items = page.get("cognitive_items", [])
            if isinstance(cognitive_items, list):
                for idx, item in enumerate(cognitive_items):
                    if isinstance(item, dict) and ("gauge" not in item or not isinstance(item["gauge"], dict)):
                        print(f"  [警告] cognitive cognitive_items[{idx}] 缺少 gauge，补全默认值")
                        p = to_float(item.get("value", "50"), 50)
                        cx_small, cy_small, radius_small = 70, 50, 38
                        ratio = max(0.0, min(1.0, p / 100.0)) if p > 0 else 0.0
                        start_x = cx_small - radius_small
                        start_y = cy_small
                        angle = math.pi - ratio * math.pi
                        end_x = cx_small + radius_small * math.cos(angle)
                        end_y = cy_small - radius_small * math.sin(angle)
                        arc_path = (f"M {start_x:.1f} {start_y:.1f} "
                                    f"A {radius_small} {radius_small} 0 0 1 {end_x:.1f} {end_y:.1f}")
                        full_path = f"M {start_x:.1f} {start_y:.1f} A {radius_small} {radius_small} 0 0 1 {cx_small + radius_small:.1f} {cy_small:.1f}"
                        item["gauge"] = {
                            "cx": cx_small, "cy": cy_small, "radius": radius_small,
                            "arc_path": arc_path, "full_path": full_path,
                            "needle_x": end_x, "needle_y": end_y,
                            "value": fmt(p), "max": "100",
                        }

    view_student = {
        "name": student.get("name", "") or "",
        "test_date": student.get("test_date", "") or "",
        "grade": student.get("grade", "") or "",
        "school": student.get("school", "") or "",
    }

    return {
        "student": view_student,
        "pages": pages,
    }


# ======================================================================
# HTML 渲染
# ======================================================================

def render_html(view_data: Dict[str, Any], output_path: Path) -> None:
    template_dir = Path(__file__).resolve().parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report.html")
    try:
        html = template.render(**view_data)
    except Exception as exc:
        pages = view_data.get("pages", [])
        print(f"  [错误] 模板渲染失败: {exc}")
        print(f"  [调试] 共 {len(pages)} 页，各页 layout:")
        for i, p in enumerate(pages, 1):
            layout = p.get("layout", "?")
            has_gauge = "gauge" in p
            core_items = p.get("core_items")
            cog_items = p.get("cognitive_items")
            extra = []
            if has_gauge:
                extra.append("has gauge")
            if isinstance(core_items, list):
                for j, item in enumerate(core_items):
                    if "gauge" not in item:
                        extra.append(f"core_items[{j}] no gauge")
            if isinstance(cog_items, list):
                for j, item in enumerate(cog_items):
                    if "gauge" not in item:
                        extra.append(f"cognitive_items[{j}] no gauge")
            extra_str = f" ({', '.join(extra)})" if extra else ""
            print(f"    P{i:02d} [{layout}]{extra_str}")
        raise
    output_path.write_text(html, encoding="utf-8")
    print(f"  HTML 已渲染 → {output_path} ({len(html)} chars, "
          f"{len(view_data.get('pages', []))} 页)")


# ======================================================================
# PDF 生成（Chrome headless）
# ======================================================================

def generate_pdf_with_chrome(html_path: Path, pdf_path: Path) -> None:
    chrome_candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    chrome_path: Optional[str] = None
    for p in chrome_candidates:
        if os.path.exists(p):
            chrome_path = p
            break
    if chrome_path is None:
        for cmd in ["google-chrome", "chromium-browser", "chromium",
                    "google-chrome-stable"]:
            try:
                result = subprocess.run(["which", cmd], capture_output=True,
                                         text=True)
                if result.returncode == 0 and result.stdout.strip():
                    chrome_path = result.stdout.strip()
                    break
            except (FileNotFoundError, OSError):
                pass
    if chrome_path is None:
        raise RuntimeError(
            "未能找到 Chrome/Chromium。请安装后重试，或在 PATH 中包含。"
        )

    abs_html = str(html_path.resolve())
    file_url = f"file://{abs_html}"

    args = [
        chrome_path,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--virtual-time-budget=5000",
        "--run-all-compositor-stages-before-draw",
        f"--print-to-pdf={str(pdf_path.resolve())}",
        "--print-to-pdf-no-header",
        file_url,
    ]

    print(f"  Chrome 打印 PDF (using {chrome_path}) ...")
    result = subprocess.run(args, capture_output=True, text=True, timeout=180)
    if result.stderr:
        last = result.stderr.strip().splitlines()[-3:]
        print("    stderr (last 3):", " | ".join(last))

    if not pdf_path.exists():
        raise RuntimeError(
            f"Chrome PDF 生成失败。stderr={result.stderr[:500]}"
        )
    size_kb = pdf_path.stat().st_size / 1024
    print(f"  PDF 已生成 → {pdf_path} ({size_kb:.0f} KB)")


# ======================================================================
# 主入口
# ======================================================================

def main() -> None:
    print("=" * 60)
    print("综合测评报告 PDF 生成（18 页 · 严格匹配 reference.pdf 结构）")
    print("=" * 60)

    project_dir = Path(__file__).resolve().parent
    output_dir = project_dir / "output"
    output_dir.mkdir(exist_ok=True)
    html_path = output_dir / "report.html"
    pdf_path = output_dir / "report.pdf"

    print("\n[1/3] 构建 18 页视图数据 ...")
    view_data = build_view_data()
    pages = view_data.get("pages", [])
    print(f"  OK ({len(pages)} 页)")
    for i, p in enumerate(pages, 1):
        print(f"    P{i:02d} [{p.get('layout', '?'):18s}] {p.get('page_title', '')}")

    print("\n[2/3] 渲染 HTML ...")
    render_html(view_data, html_path)

    print("\n[3/3] 生成 PDF ...")
    try:
        generate_pdf_with_chrome(html_path, pdf_path)
    except Exception as exc:
        print(f"  [警告] PDF 生成失败: {exc}")
        print("  可手动用 Chrome 打开 output/report.html 并打印为 PDF。")

    print("\n" + "=" * 60)
    print(f"完成！输出: {html_path}, {pdf_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
