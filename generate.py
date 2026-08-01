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

import json
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
        return f"{val:.1f}"
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
    full_circle_path = f"M {cx + radius} {cy} A {radius} {radius} 0 1 1 {cx - radius} {cy} A {radius} {radius} 0 1 1 {cx + radius} {cy}"
    if ratio >= 1.0:
        arc_path = full_circle_path
    else:
        arc_path = (f"M {start_x:.1f} {start_y:.1f} "
                    f"A {radius} {radius} 0 {large_arc} 1 {end_x:.1f} {end_y:.1f}")
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
              label_padding: int = 40,
              avg_points: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """生成雷达图（N 边形）SVG 数据。在 Python 中预计算所有坐标。
    
    确保雷达图中心在 viewBox 正中间，方便水平居中显示。
    """
    num = len(items)
    
    # 先计算 viewBox 大小，确保中心在正中间
    margin = 20
    content_w = (radius + label_padding + margin) * 2
    content_h = (radius + label_padding + 30) * 2
    
    viewBox_w = max(content_w, 400)
    viewBox_h = max(content_h, 400)
    
    # 雷达图中心在 viewBox 正中间
    center_x = viewBox_w / 2
    center_y = viewBox_h / 2
    
    rings = []
    for r in range(1, ring_count + 1):
        rr = radius * r / ring_count
        pts = []
        for i in range(num):
            ang = math.pi / 2 - (2 * math.pi / num) * i
            px = center_x + rr * math.cos(ang)
            py = center_y - rr * math.sin(ang)
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
        px = center_x + rr * math.cos(ang)
        py = center_y - rr * math.sin(ang)
        val_pts.append(f"{px:.1f},{py:.1f}")
        dots.append({"x": f"{px:.1f}", "y": f"{py:.1f}"})
        lx = center_x + (radius + label_padding) * math.cos(ang)
        ly = center_y - (radius + label_padding) * math.sin(ang)
        labels.append({
            "x": f"{lx:.1f}", "y": f"{ly:.1f}",
            "label": it.get("label", ""),
            "en": it.get("en", ""),
            "letter": it.get("letter", ""),
            "value": fmt(val),
        })
    
    avg_polygon_points = ""
    if avg_points:
        avg_val_pts = []
        for i, it in enumerate(avg_points):
            val = to_float(it.get("value", 0), 0)
            ratio = max(0.0, min(1.0, val / max_value)) if max_value > 0 else 0.0
            rr = radius * ratio
            ang = math.pi / 2 - (2 * math.pi / num) * i
            px = center_x + rr * math.cos(ang)
            py = center_y - rr * math.sin(ang)
            avg_val_pts.append(f"{px:.1f},{py:.1f}")
        avg_polygon_points = " ".join(avg_val_pts)
    
    axes = []
    for i in range(num):
        ang = math.pi / 2 - (2 * math.pi / num) * i
        ax = center_x + radius * math.cos(ang)
        ay = center_y - radius * math.sin(ang)
        axes.append({"x1": center_x, "y1": center_y, "x2": f"{ax:.1f}", "y2": f"{ay:.1f}"})
    
    return {
        "cx": center_x, "cy": center_y, "radius": radius,
        "rings": rings, "axes": axes,
        "polygon_points": " ".join(val_pts),
        "avg_polygon_points": avg_polygon_points,
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


# ---------------- 辅助函数 ----------------
def has_page_data(page_key_codes: List[str]) -> bool:
    """检查某个页面是否有有效数据"""
    for code in page_key_codes:
        val = v(code)
        if val is not None and val != "" and str(val).strip() != "0":
            return True
    return False


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
                      page_title="凭远教育",
                      subtitle="Y4评测报告",
                      subtitle_en="Y4 Assessment Report",
                      rows=info_items)


# ---------------- P02 Y4 Intro ----------------
def build_page_2() -> Dict[str, Any]:
    paragraphs = [
        "Y4 是凭远从四个相互关联的成长系统出发，对青少年当前状态、发展资源和潜在困难形成的综合画像。",
        "Y 代表 Youth，也呼应 Why。Y4 不只描述一个学生“是什么样”，也试图进一步回答：",
        "● TA为什么会产生这样的情绪和行为；",
        "● TA为什么在某些环境中充满动力，在另一些环境中难以行动；",
        "● TA为什么在某些学习任务中表现突出，却在另一些任务中频繁受阻；",
        "● TA为什么被某些方向吸引；",
        "● 什么样的成长支持，能够真正帮助TA把潜能转化为未来。",
        "Y4 <strong>不</strong>以单一分数<strong>定义</strong>学生，也<strong>不</strong>把学生简单<strong>归类</strong>为某一种类型。它通过四个系统之间的联系，<strong>理解</strong>一个真实、复杂并且仍在<strong>发展</strong>中的青少年。",
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
                          "● TA是否能够在压力、失败和变化中保持基本稳定；",
                          "● TA如何评价自己、理解自己；",
                          "● TA是否相信自己有能力面对挑战；",
                          "● TA是否拥有值得信任和依靠的关系；",
                          "● TA能否表达需要，并在困难时寻求帮助；",
                          "● TA行动的动力来自哪里；",
                          "● TA如何与环境、他人和任务建立关系。",
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
    return _page_dict("self_concept",
                      page_title="自我概念",
                      subtitle="SELF CONCEPT",
                      page_en="Self-Concept Dimensions",
                      intro="自我概念是个体对自己认识的集合，个体认为的“我是谁，我是一个怎样的人”。也可以理解为个人心中对自己的印象，包括对身体、能力、性格、态度等。比如“我是聪明的”、“我是漂亮的”、“我学习好”。自我概念的发展过程是一个人个性形成和社会化发展的关键。",
                      overall_value=fmt(overall),
                      overall_pct=max(0, min(100, int(overall))),
                      sub_items=sub_items)


# ---------------- P06 依恋关系（020-040） ----------------
def _attachment_level(dim_name: str, score: float) -> str:
    if dim_name == "信任":
        if score >= 35:
            return "高"
        elif score >= 18:
            return "不低"
        else:
            return "偏低"
    elif dim_name == "沟通":
        if score >= 31:
            return "高"
        elif score >= 16:
            return "不低"
        else:
            return "偏低"
    elif dim_name == "亲近":
        if score >= 21:
            return "高"
        elif score >= 11:
            return "不低"
        else:
            return "偏低"
    return ""

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
            "max": 50,
            "dim_items": [
                {"label": "信任", "who": "母亲", "value": fmt(v("023")), "code": "023"},
                {"label": "信任", "who": "父亲", "value": fmt(v("024")), "code": "024"},
                {"label": "信任", "who": "同伴", "value": fmt(v("025")), "code": "025"},
            ]
        },
        {
            "name": "沟通",
            "en": "Communication",
            "max": 45,
            "dim_items": [
                {"label": "沟通", "who": "母亲", "value": fmt(v("026")), "code": "026"},
                {"label": "沟通", "who": "父亲", "value": fmt(v("027")), "code": "027"},
                {"label": "沟通", "who": "同伴", "value": fmt(v("028")), "code": "028"},
            ]
        },
        {
            "name": "亲近",
            "en": "Closeness",
            "max": 30,
            "dim_items": [
                {"label": "亲近", "who": "母亲", "value": fmt(v("029")), "code": "029"},
                {"label": "亲近", "who": "父亲", "value": fmt(v("030")), "code": "030"},
                {"label": "亲近", "who": "同伴", "value": fmt(v("031")), "code": "031"},
            ]
        },
    ]
    for dim in dimensions:
        max_val = dim.get("max", 50)
        dim_name = dim.get("name", "")
        for item in dim["dim_items"]:
            s = to_float(item["value"], 5)
            item["pct"] = max(0, min(100, int(s / max_val * 100)))
            item["level"] = _attachment_level(dim_name, s)
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
    # 思维模式值必须来自视觉API读取，不使用默认值
    # 如果值为空或无法转换，明确报错而不是使用默认值
    try:
        mindset_val = float(mindset_raw)
        mindset_pct = max(0, min(100, int(mindset_val)))
    except (ValueError, TypeError):
        print(f"  [错误] 思维模式(059)值无效: '{mindset_raw}'，视觉API可能未成功读取")
        print(f"  [错误] 不使用默认值，请检查视觉API是否正常工作")
        # 使用0作为标记值，表示读取失败（不使用50.0默认值掩盖问题）
        mindset_val = 0.0
        mindset_pct = 0
    
    # 判断思维模式类型（根据数值判断，不再强制修改数值）
    text_lower = str(mindset_raw).lower()
    if "成长" in str(mindset_raw) or "growth" in text_lower:
        mindset_type = "成长型思维模式"
        mindset_type_en = "Growth Mindset"
    elif "固定" in str(mindset_raw) or "fixed" in text_lower:
        mindset_type = "固定型思维模式"
        mindset_type_en = "Fixed Mindset"
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
        {"label": "自主性", "en": "Autonomy", "code": "060", "mean_label": "自主性", "norm_code": "125"},
        {"label": "胜任感", "en": "Competence", "code": "061", "mean_label": "胜任感", "norm_code": "126"},
        {"label": "归属感", "en": "Relatedness", "code": "062", "mean_label": "归属感", "norm_code": "127"},
    ]
    core_items = []
    for it in core_items_raw:
        val = to_float(v(it["code"]), 5)
        mean_val = m(it["mean_label"], 6.0)
        norm_val = to_float(v(it["norm_code"]), mean_val)
        pct = max(0, min(100, int(val / 10.0 * 100)))
        norm_pct = max(0, min(100, int(norm_val / 10.0 * 100)))
        try:
            gauge = circular_gauge_svg(val, 10.0)
        except Exception:
            gauge = circular_gauge_svg(5.0, 10.0)
        core_items.append({
            "label": it["label"], "en": it["en"],
            "value": fmt(val), "max": 10.0,
            "pct": pct, "mean": mean_val,
            "norm_value": fmt(norm_val),
            "norm_pct": norm_pct,
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
    avg_items = [
        {"label": "开放性", "value": 3.0},
        {"label": "宜人性", "value": 3.0},
        {"label": "责任心", "value": 3.0},
        {"label": "外倾性", "value": 3.0},
        {"label": "神经质", "value": 3.0},
    ]
    radar = radar_svg(big_five_items, 5.0,
                      radius=120, cy=180, color="#2A9D8F",
                      label_padding=45, avg_points=avg_items)
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
                          "一个学生可能拥有很强的认知能力和明确的目标，但如果长期睡眠不足、运动不足、饮食失衡或身体状态欠佳，TA所拥有的能力就可能无法稳定表现出来。",
                          "精力系统的核心问题：",
                          "● 这个学生是否拥有持续前进所需要的身体能量和生活节律；",
                          "● TA的饮食、睡眠和运动习惯，是否在支撑而不是消耗TA；",
                          "● TA是否具备基本的身体管理意识和能力。",
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
                      health_desc_eat=v("050a"))


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
                          "● TA在学习过程中能否有效地管理自己的注意力、记忆和思维方式；",
                          "● TA学习的动力来自哪里，是出于兴趣还是外部压力；",
                          "● TA是否掌握了有效和可迁移的学习策略。",
                      ])


# ---------------- P12 认知能力（001-008） ----------------
def build_page_12() -> Dict[str, Any]:
    cognitive_items = [
        {"label": "感知觉", "en": "Perception", "value": fmt(v("003")),
         "desc": "感知是认知、理解的基础。感知觉是大脑对作用于大脑的外部信息的整体看法和理解，整个加工过程包括获取信息、理解信息、选择信息和组织信息。"},
        {"label": "注意力", "en": "Attention", "value": fmt(v("004")),
         "desc": "心理活动对一定对象的指向和集中。一般理解为对客观事物持续注意的能力，如做事专注，还是易分心。神经生理因素、兴趣/动机、精神状态等均会影响一个人的注意力水平。"},
        {"label": "记忆力", "en": "Memory", "value": fmt(v("005")),
         "desc": "记忆力是神经系统存储过往经验的能力，是学习的基础，一般包括识记、保持、再认和重现。记忆力的个体差异影响学习效率，如有的同学看3遍就记住了一个单词，而有的同学可能要7-8遍。"},
        {"label": "推理能力", "en": "Reasoning", "value": fmt(v("006")),
         "desc": "推理能力是智力的核心成分，是一个人通过已有知识和经验，通过综合分析做出新判断的过程。推理能力的差异往往反应一个人洞悉事物本质，事物联系能力的高低。"},
        {"label": "空间能力", "en": "Spatial Ability", "value": fmt(v("007")),
         "desc": "空间能力是大脑通过观察、触摸及想象对物体形状、位置判断的能力。它是大脑对外部信息的抽象表征和推理，是数学、自然科学、工程等重要学科领域用到的重要心理能力。"},
        {"label": "加工速度", "en": "Processing Speed", "value": fmt(v("008")),
         "desc": "加工速度是大脑处理内部或外部信息的速度，和网速、手机使用流畅性一样，大脑的信息加工速度直接影响学习、思考和人际沟通的效率。"},
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
                      intro="认知能力是大脑加工、处理信息，认知客观事物内部逻辑，并运用知识、经验等解决问题的能力。认知的过程包括感知、记忆、想象、思考、判断等。它被重视的原因是人类所有的学习活动都离不开认知能力的运用。",
                      total_score=fmt(v("001")),
                      percentile=fmt(percentile),
                      dist_svg=dist_svg), _page_dict("cognitive_details",
                      page_title="",
                      subtitle="",
                      page_en="",
                      cognitive_items=cognitive_items)


# ---------------- P13 执行功能（063-065） ----------------
def build_page_13() -> Dict[str, Any]:
    executive_items = [
        {"label": "抑制控制", "en": "Inhibitory Control", "value": fmt(v("063")), "color": "teal",
         "desc": "抑制控制是指个体在行动之前控制冲动、理性思考、排除干扰完成任务的能力。即抑制住自己的本能、欲望，使自己做出符合预期目标的行为。它和孩子的专注力、情绪调节和冲动控制等有关。"},
        {"label": "工作记忆", "en": "Working Memory", "value": fmt(v("064")), "color": "red",
         "desc": "工作记忆是有意识地在头脑中保存和操纵信息的能力。我们依靠记忆信息预测未来，信息是周全还是片面直接影响预测的准确性。我们依靠记忆制定目标、安排计划、执行任务，而目标是否清晰，计划是否详细，执行是否到位均与记忆力有关。"},
        {"label": "认知灵活性", "en": "Cognitive Flexibility", "value": fmt(v("065")), "color": "amber",
         "desc": "认知灵活性是指个体大脑适应新的、变化的或计划以外事件的能力。比如当情况有变，原有计划被打破或最初的方案行不通时，认知灵活性高的人能根据变化从不同角度看问题，及时调整心态，改变思路，快速找到解决问题的新方案。认知灵活性影响孩子的自我调节能力和心理韧性。"},
    ]
    for item in executive_items:
        p = to_float(item["value"], 50)
        item["pct"] = max(0, min(100, int(p)))
    radar = radar_svg(executive_items, 100.0,
                      radius=100, cx=170, cy=140,
                      color="#2A9D8F",
                      label_padding=45)
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
        ("深层动机", "Deep Motivation", "066", "128",
         "深层动机是对学习本身感兴趣，学习本身使个体感到满足和兴奋的内部动机。深层动机得分高的个体一般学习动力足，主动学习、不需要外部监督和督促。"),
        ("表面动机", "Surface Motivation", "067", "129",
         "表面动机是对学习不感兴趣，为了通过考试、得到奖励或避免惩罚而学习的外部动机。表面动机难以维持长期学习，一旦外部奖励或惩罚退去，个体可能不再学习。"),
        ("自我效能感", "Self-Efficacy", "068", "130",
         "自我效能感是个体对自己能否成功完成某事的主观判断。个体的自我效能感源于过往的成功经验以及对自己的准确的评估。"),
    ]
    str_raw = [
        ("学习深层方法与策略", "Deep Methods and Strategies", "069", "131",
         "学习深层方法与策略是为了深入理解知识本身而采取的学习方法和策略，是一种建立在理解和应用基础之上的深度学习。这种学习方法使学习记忆更牢、理解更深刻。"),
        ("学习表面方法与策略", "Surface Methods and Strategies", "070", "132",
         "学习表面方法与策略是为了记住某具体内容或为了某次考试通过而学习的方法与策略，这种方法策略可以在短期内看到效果，对长期发展非常不利。因为这种不求甚解的学习方法记得快，忘得也快。"),
        ("学习自我调节", "Self-Regulation", "071", "133",
         "学习自我调节是学习过程中遇到困难或挫折时采取的自我调节的方法。比如即使遇到了自己不喜欢的老师或科目，但为了取得好成绩也会进行自我调节、努力学习。"),
    ]

    def _mk(items_raw):
        out = []
        for label_cn, label_en, code, norm_code, desc in items_raw:
            val = to_float(v(code), 5)
            norm_val = to_float(v(norm_code), 6.0)
            out.append({
                "label": label_cn, "en": label_en,
                "value": fmt(val), "unit": "/10.0",
                "pct": max(0, min(100, int(val / 10.0 * 100))),
                "norm_value": fmt(norm_val),
                "norm_pct": max(0, min(100, int(norm_val / 10.0 * 100))),
                "desc": desc,
            })
        return out

    motivation_items = _mk(mot_raw)
    strategy_items = _mk(str_raw)
    return _page_dict("learning_motivation",
                      page_title="学习动机与策略",
                      subtitle="LEARNING MOTIVATION & STRATEGIES",
                      page_en="Learning Motivation and Strategies",
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
        {"letter": "R", "label": "现实型", "en": "Realistic", "value": fmt(v("073")),
         "desc": "喜欢具体的、可操作性的工作，比如修理、组装或建造东西；喜欢动手操作、操作设备、工具或机器；偏好具体任务，而不是抽象思考，或与人讨论；不善言辞，更喜欢独立工作。"},
        {"letter": "I", "label": "研究型", "en": "Investigative", "value": fmt(v("074")),
         "desc": "喜欢研究抽象问题，善于逻辑分析，喜欢探索未知；喜欢观察、学习、思考、调查和实验研究；善于提出问题和解决问题；个性独立，为人谨慎。"},
        {"letter": "A", "label": "艺术型", "en": "Artistic", "value": fmt(v("075")),
         "desc": "文艺青年；用文字、艺术、音乐或戏剧来交流、表演或表达自己，创造和设计事物；想象力丰富，喜欢创造与表达；喜欢无拘无束的自由生活，喜欢新鲜刺激的生活，讨厌一成不变的生活。"},
        {"letter": "S", "label": "社会型", "en": "Social", "value": fmt(v("076")),
         "desc": "温暖、和善；乐于帮助他人；关心社会问题，喜欢与人一起帮助和服务他人；关心他人的幸福和福利。"},
        {"letter": "E", "label": "事业型", "en": "Enterprising", "value": fmt(v("077")),
         "desc": "追求权利、利益；喜欢竞争，有野心和抱负；喜欢影响他人、领导他人完成目标；精力充沛，掌控大局。"},
        {"letter": "C", "label": "常规型", "en": "Conventional", "value": fmt(v("078")),
         "desc": "遵循规章制度办事；喜欢重复的事务性工作，不喜欢变动；个性谨慎，工作认真，注重细节；喜欢配合和服从，不喜欢领导他人。"},
    ]
    for item in holland_items:
        s = to_float(item["value"], 5)
        item["pct"] = max(0, min(100, int(s / 10.0 * 100)))
    radar = radar_svg(holland_items, 10.0,
                      radius=100, color="#2A9D8F")
    intro = "职业兴趣（Vocational Interest）是兴趣在职业选择方面的表现，背后是人格的一种体现。你可以理解为显性的或隐性的从事某种工作的偏好和愿望。职业兴趣代码（Holland Code）是将你职业兴趣的测评结果按得分从高到低的顺序依次排序，得分最高的三个代码即为你的职业兴趣代码。"
    return _page_dict("holland",
                      page_title="职业兴趣",
                      subtitle="VOCATIONAL INTEREST",
                      page_en="HOLLAND VOCATIONAL INTEREST TYPES",
                      intro=intro,
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
    values_def_default = [
        ("经济报酬", "Economic Reward", "106", 1,
         "较高的报酬，生活过得较为富足", "薪酬高，福利好"),
        ("工作环境", "Work Environment", "102", 2,
         "追求比较舒适、轻松、自由的工作环境", "工作环境舒适，轻松自由"),
        ("生活方式", "Lifestyle", "109", 3,
         "可以选择过自己想过的生活，安逸、简单、快乐或充实", "有选择生活方式的权利"),
        ("上司关系", "Supervisor Relations", "104", 4,
         "有一个开明的、民主的、公正的好领导", "有一个好领导"),
        ("同事关系", "Colleague Relations", "103", 5,
         "一起工作的大多数同事，人品较好，相处愉快", "与喜欢的人共事"),
        ("成就感", "Achievement", "100", 6,
         "不断取得新的成就，得到认可或实现自己想做的事", "能给我带来成就感"),
        ("独立自主", "Independence", "096", 7,
         "可以按自己的方式或想法工作，不受他人的影响", "能按自己想法和节奏做事"),
        ("管理权力", "Management Power", "101", 8,
         "管理和指挥他人做事", "影响和领导别人一起"),
        ("创造发明", "Creativity", "095", 9,
         "发明创造新的事物，可能是新产品，也可能是新观念或新方法", "发明创造新的事物"),
        ("安全稳定", "Security", "107", 10,
         "工作稳定，收入有保障，不会失业", "安稳，不会失业"),
        ("智力激发", "Intellectual Stimulation", "098", 11,
         "必须动脑筋思考、学习和探索新事物，解决新问题", "有挑战性"),
        ("利他助人", "Altruism", "099", 12,
         "为他人的幸福、利益尽一份力", "能帮助到他人"),
        ("声望地位", "Social Status", "108", 13,
         "所从事的工作在人们的心目中有较高的社会地位", "社会地位高，受人敬仰"),
        ("美的追求", "Aesthetic Pursuit", "097", 14,
         "不断地追求美的东西，得到美的享受", "能体验和感受美"),
        ("多样变化", "Variety", "105", 15,
         "讨厌简单重复的工作，喜欢有挑战、丰富多彩的工作", "尝试不同的工作"),
    ]

    mapping_path = Path(__file__).resolve().parent / "data" / "_vision_b6_values_mapping.json"
    num_to_label = {}
    if mapping_path.exists():
        try:
            with open(mapping_path, 'r', encoding='utf-8') as f:
                num_to_label = json.load(f)
            print(f"  [P18] 加载编号映射: {num_to_label}")
        except Exception as e:
            print(f"  [P18] 加载编号映射失败: {e}")

    label_to_def = {cn: (cn, en, score_code, feature, monologue)
                    for cn, en, score_code, num, feature, monologue in values_def_default}

    values_def = []
    if num_to_label and len(num_to_label) == 15:
        for num in range(1, 16):
            label = num_to_label.get(str(num))
            if label and label in label_to_def:
                cn, en, score_code, feature, monologue = label_to_def[label]
                values_def.append((cn, en, score_code, num, feature, monologue))
            else:
                print(f"  [P18] 警告: 编号{num}的标签{label}未找到，使用默认值")
                values_def.append(values_def_default[num-1])
    else:
        values_def = values_def_default
        print("  [P18] 未找到编号映射，使用默认顺序")

    items_with_scores = []
    for cn, en, score_code, num, feature, monologue in values_def:
        val = to_float(v(score_code), 5)
        items_with_scores.append({
            "label": cn, "en": en,
            "num": num,
            "score": val,
            "feature": feature,
            "monologue": monologue,
        })

    # 按卡片编号排序（编号1-15即为正确排名），不按分数排序
    items_with_scores.sort(key=lambda x: x["num"])

    items = []
    for item in items_with_scores:
        items.append({
            "label": item["label"],
            "en": item["en"],
            "num": item["num"],
            "rank": item["num"],  # 卡片编号即为排名
            "value": fmt(item["score"]),
            "pct": max(0, min(100, int(item["score"] / 10.0 * 100))),
            "feature": item["feature"],
            "monologue": item["monologue"],
        })

    return _page_dict("values_grid",
                      page_title="职业价值观",
                      subtitle="WORK VALUES",
                      page_en="TOP WORK VALUES & PRIORITIES",
                      intro="",
                      values_items=items)


# ---------------- P19 封底页 ----------------
def build_page_backcover() -> Dict[str, Any]:
    return _page_dict("backcover",
                      page_title="Y4 测评报告 · 阅读与说明",
                      paragraphs=[
                          {"title": "测评不定义，亦不归类", "content": "本报告旨在呈现特质，而非给学生贴上固定的“标签”或将其局限于某一类模型中。"},
                          {"title": "状态具有时效性", "content": "报告所记录的是测试人在当下的即时状态，该状态会受到环境、情绪及多种潜在因素的综合影响。"},
                          {"title": "理解需结合情境 (Context)", "content": "对报告数据的理解与解读，绝不能脱离具体的成长背景与专业情境，切忌断章取义。"},
                          {"title": "请务必咨询专业测评师", "content": "为了确保您准确理解报告内涵，请在阅读时务必咨询凭远专业老师的意见，以获得客观、全面的深度解析。"},
                      ],
                      copyright="本报告为凭远内部资料，所有权归凭远所有。未经凭远测评师及相关家庭的双重授权，严禁任何形式的转发或公开。")


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
    ]
    
    # 心力系统：按页面逐个判断
    mind_pages = []
    if has_page_data(["009"]):
        mind_pages.append(build_page_4())
    if has_page_data(["051"]):
        mind_pages.append(build_page_5())
    if has_page_data(["020", "021", "022"]):
        mind_pages.append(build_page_6())
    if has_page_data(["059", "060"]):
        mind_pages.append(build_page_7())
    if has_page_data(["015", "016", "017", "018", "019"]):
        mind_pages.append(build_page_8())
    
    # 如果有心力系统页面，添加心力介绍页
    if mind_pages:
        pages.append(build_page_3())
        pages.extend(mind_pages)
    
    # 精力系统：按页面逐个判断
    energy_pages = []
    if has_page_data(["041", "042"]):
        energy_pages.append(build_page_10())
    
    # 如果有精力系统页面，添加精力介绍页
    if energy_pages:
        pages.append(build_page_9())
        pages.extend(energy_pages)
    
    # 学习力系统：按页面逐个判断
    learning_pages = []
    if has_page_data(["001", "002"]):
        pages_12 = build_page_12()
        learning_pages.extend(pages_12)
    if has_page_data(["073", "074", "075", "076", "077", "078", "079", "080", "081", "082"]):
        learning_pages.append(build_page_13())
    if has_page_data(["083", "084", "085", "086", "087", "088", "089", "090"]):
        learning_pages.append(build_page_14())
    
    # 如果有学习力系统页面，添加学习力介绍页
    if learning_pages:
        pages.append(build_page_11())
        pages.extend(learning_pages)
    
    # 生涯力系统：按页面逐个判断
    career_pages = []
    if has_page_data(["091", "092", "093", "094", "095", "096"]):
        career_pages.append(build_page_16())
    if has_page_data(["097", "098", "099", "100", "101", "102", "103"]):
        career_pages.append(build_page_17())
    if has_page_data(["095", "096", "097", "098", "099", "100"]):
        career_pages.append(build_page_18())
    
    # 如果有生涯力系统页面，添加生涯力介绍页
    if career_pages:
        pages.append(build_page_15())
        pages.extend(career_pages)
    
    # 添加封底页
    pages.append(build_page_backcover())
    
    for page in pages:
        layout = page.get("layout", "")
        
        if layout in ("emotional_stability", "self_concept"):
            if "gauge" not in page or not isinstance(page["gauge"], dict):
                print(f"  [警告] {layout} 页面缺少 gauge，补全默认值")
                page["gauge"] = gauge_svg(50.0, 100.0)
        
        if layout == "inner_drive":
            if "mindset_gauge" not in page or not isinstance(page["mindset_gauge"], dict):
                print(f"  [错误] inner_drive 页面缺少 mindset_gauge，视觉API可能未读取思维模式值")
                print(f"  [错误] 不使用默认值，请检查视觉API是否正常工作")
                # 不使用50.0默认值，使用0.0标记读取失败
                page["mindset_gauge"] = mindset_gauge_svg(0.0)
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
    branding_src = Path(__file__).resolve().parent / "branding"
    branding_dst = output_path.parent / "branding"
    if not branding_dst.exists():
        import shutil
        shutil.copytree(str(branding_src), str(branding_dst))
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
    return 0


if __name__ == "__main__":
    main()
