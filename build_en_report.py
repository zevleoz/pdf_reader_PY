# -*- coding: utf-8 -*-
"""build_en_report.py —— 生成 Y4 评测报告的英文版（版式与中文版一致）。

做法：
  1. 读取 templates/report.html，仅替换其中写死的中文界面文案（CSS 与版式完全不动），
     输出 templates/report_en.html；
  2. 用与学生数据等价的值构造英文 pages 视图数据（复用 generate.py 的 SVG 计算函数）；
  3. Jinja2 渲染 HTML，再用 Chrome 打印为 PDF。

输出：
  - output/Y4_Assessment_Report_Jeslyn.html
  - output/Y4_Assessment_Report_Jeslyn.pdf
"""
from __future__ import annotations

import math
import shutil
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader, select_autoescape

import generate as G
from generate import (
    _page_dict,
    circular_gauge_svg,
    gauge_svg,
    generate_pdf_with_chrome,
    mindset_gauge_svg,
    normal_dist_svg,
    radar_svg,
)

ROOT = Path(__file__).resolve().parent
TEMPLATE_DIR = ROOT / "templates"
OUTPUT_DIR = ROOT / "output"

# ---------------------------------------------------------------- 界面文案替换
# 仅替换模板中写死的中文（版式/CSS 不动）
CHROME_REPLACEMENTS = [
    ("<title>Y4 评测报告</title>", "<title>Y4 Assessment Report</title>"),
    ('content:"同龄"', 'content:"PEER"'),
    ('<span class="label">姓　名：</span>', '<span class="label">Name:</span>'),
    ('<span class="label">年　级：</span>', '<span class="label">Grade:</span>'),
    ('<span class="label">学　校：</span>', '<span class="label">School:</span>'),
    ('<span class="label">测评日期：</span>', '<span class="label">Test Date:</span>'),
    ('<div class="emotion-r-label">同龄平均</div>',
     '<div class="emotion-r-label">Peer Average</div>'),
    ('<div class="zh">偏低</div>', '<div class="zh">Low</div>'),
    ('<div class="zh">正常</div>', '<div class="zh">Normal</div>'),
    ('<div class="zh">偏高</div>', '<div class="zh">High</div>'),
    ('                <div class="en">Low</div>\n', ''),
    ('                <div class="en">Normal</div>\n', ''),
    ('                <div class="en">High</div>\n', ''),
    ('                    <div class="cog-score-label-en">Total Score</div>\n', ''),
    ('                    <div class="cog-score-label-en">Percentile</div>\n', ''),
    ('<div class="details-title">测评结果详情 丨 RESULTS DETAILS</div>',
     '<div class="details-title">Results Details</div>'),
    ('<div class="details-desc">个体的自我概念是对众多方面自我认知的整体感知，本测评选取了影响儿童自我概念的六大重要方面，包括行为表现、能力与学校表现、躯体外貌、情绪焦虑、合群、幸福与满意。下面是你在这六大方面得分的具体情况：</div>',
     '<div class="details-desc">Self-concept is an overall perception built from many aspects of self-awareness. This assessment covers six key areas that shape a child\'s self-concept: behavioral adjustment, intellectual and school status, physical appearance and attributes, freedom from anxiety, popularity, and happiness and satisfaction. Scores in each area are shown below.</div>'),
    ('依恋模式测评详情</div>', 'Attachment Assessment Details</div>'),
    ('        <span class="mindset-title">思维模式</span>\n'
     '        <span class="mindset-title-en">MODE OF THINKING</span>',
     '        <span class="mindset-title">Mode of Thinking</span>'),
    ('            <div style="font-size:9.5pt; font-weight:700; color:#2A9D8F;">固定型思维模式</div>\n'
     '            <div style="font-size:7pt; color:#2A9D8F; margin-top:0.5mm;">FIXED MINDSET</div>',
     '            <div style="font-size:9.5pt; font-weight:700; color:#2A9D8F;">Fixed Mindset</div>'),
    ('            <div style="font-size:9.5pt; font-weight:700; color:#E76F51;">成长型思维模式</div>\n'
     '            <div style="font-size:7pt; color:#E76F51; margin-top:0.5mm;">GROWTH MINDSET</div>',
     '            <div style="font-size:9.5pt; font-weight:700; color:#E76F51;">Growth Mindset</div>'),
    ('    <span class="core-dim-title">三个核心维度</span>\n'
     '    <span class="core-dim-en">THREE CORE DIMENSIONS</span>',
     '    <span class="core-dim-title">Three Core Dimensions</span>'),
    ('<div class="cd-mean">同龄平均: ', '<div class="cd-mean">Peer Average: '),
    ('<div class="title">体质健康测评结果</div>',
     '<div class="title">Physical Health Assessment Result</div>'),
    ('<div class="bmi-section-title">身体形态等级图</div>',
     '<div class="bmi-section-title">Body Composition Scale</div>'),
    ('· 身高：', '· HEIGHT: '),
    ('CM　· 体重：', ' CM  · WEIGHT: '),
    ('KG　· BMI：', ' KG  · BMI: '),
    ('<span class="current-tag">当前</span>', '<span class="current-tag">Current</span>'),
    ('影响体质健康的生活习惯</div>',
     'Lifestyle Habits Affecting Physical Health</div>'),
    (' 小时/天</small>', ' hours / day</small>'),
    (' 小时/周</small>', ' hours / week</small>'),
    ('<div class="cog-score-header">认知能力测评结果</div>',
     '<div class="cog-score-header">Cognitive Ability Result</div>'),
    ('<div class="cog-score-label">总得分</div>',
     '<div class="cog-score-label">Total Score</div>'),
    ('<div class="cog-score-label">百分位</div>',
     '<div class="cog-score-label">Percentile</div>'),
    ('<div class="cog-title">{{ page.page_title }}</div>',
     '<div class="cog-title">About Cognitive Ability</div>'),
    ('<div class="cog-chart-title">正态分布图 | TOTAL SCORE</div>',
     '<div class="cog-chart-title">Normal Distribution | TOTAL SCORE</div>'),
    ('以下为您在同龄群体分数分布上的位置，您在认知能力上的总分超过了 ',
     'The chart shows where {{ student.name }} falls within the same-age distribution. {{ student.name }}\'s total cognitive score is higher than '),
    ('% 的同龄人</div>', '% of same-age peers.</div>'),
    ('<div class="cog-section-title">六项子指标百分位</div>',
     '<div class="cog-section-title">Six Sub-Indicator Percentiles</div>'),
    ('学习动机　LEARNING MOTIVATION</div>', 'Learning Motivation</div>'),
    ('学习方法与策略　LEARNING METHODS</div>',
     'Learning Methods and Strategies</div>'),
    ('<div class="backcover-brand">凭远教育 · APP ARK</div>',
     '<div class="backcover-brand">APP ARK EDUCATION</div>'),
]


def build_english_template() -> Path:
    src = (TEMPLATE_DIR / "report.html").read_text(encoding="utf-8")
    for old, new in CHROME_REPLACEMENTS:
        if old not in src:
            raise RuntimeError(f"模板中未找到待替换文案: {old[:40]!r}")
        src = src.replace(old, new)
    out = TEMPLATE_DIR / "report_en.html"
    out.write_text(src, encoding="utf-8")
    return out


# ---------------------------------------------------------------- 小工具
def _cog_gauge(p: float) -> Dict[str, Any]:
    """认知子指标的半圆小仪表盘（与 generate.build_page_12 一致）。"""
    cx, cy, radius = 70, 50, 38
    ratio = max(0.0, min(1.0, p / 100.0)) if p > 0 else 0.0
    start_x, start_y = cx - radius, cy
    angle = math.pi - ratio * math.pi
    end_x = cx + radius * math.cos(angle)
    end_y = cy - radius * math.sin(angle)
    arc_path = (f"M {start_x:.1f} {start_y:.1f} "
                f"A {radius} {radius} 0 0 1 {end_x:.1f} {end_y:.1f}")
    full_path = (f"M {start_x:.1f} {start_y:.1f} "
                 f"A {radius} {radius} 0 0 1 {cx + radius:.1f} {cy:.1f}")
    return {
        "cx": cx, "cy": cy, "radius": radius,
        "arc_path": arc_path, "full_path": full_path,
        "needle_x": end_x, "needle_y": end_y,
        "value": f"{p:g}", "max": "100",
    }


STUDENT = {
    "name": "Jeslyn",
    "grade": "Grade 7",
    "school": "SHSID",
    "test_date": "2026-10-07",
}


# ---------------------------------------------------------------- 各页数据
def pages() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    # P01 封面
    out.append(_page_dict(
        "cover",
        page_title="凭远教育",
        subtitle="Y4 Assessment Report",
        page_en="Youth Profile in Four Dimensions",
    ))

    # P02 Y4 介绍
    out.append(_page_dict(
        "y4_intro",
        page_title="Y4 | Youth Profile in Four Dimensions",
        subtitle="APP ARK Education · An integrated profile of four growth systems",
        paragraphs=[
            "Y4 is APP ARK's integrated profile of a young person's current state, developmental resources and potential difficulties, built on four interrelated growth systems.",
            "Y stands for Youth, and also echoes Why. Y4 does not only describe what a student is like. It also seeks to answer:",
            "● Why they experience these emotions and behaviors;",
            "● Why they feel driven in some environments and struggle to act in others;",
            "● Why they excel at some learning tasks yet are repeatedly blocked by others;",
            "● Why they are drawn to certain directions;",
            "● What kind of support can genuinely help turn their potential into a future.",
            "Y4 does <strong>not</strong> define a student by a single score, nor does it <strong>sort</strong> students into one type. By examining the connections among the four systems, it seeks to <strong>understand</strong> a real, complex young person who is still <strong>developing</strong>.",
        ],
    ))

    # P03 心力
    out.append(_page_dict(
        "section_intro",
        page_title="Mental Strength ｜ Emotions & Motivation",
        subtitle="EMOTIONAL & MOTIVATIONAL SYSTEM",
        section_num="1.",
        paragraphs=[
            "Mental strength is the inner foundation that lets a young person understand themselves, steady themselves, connect with others and take action.",
            "This system is not concerned with whether a student is \u201cin a good mood\u201d or has a \u201cgood personality.\u201d It looks at:",
            "● Whether they can stay fundamentally steady under pressure, failure and change;",
            "● How they evaluate and understand themselves;",
            "● Whether they believe they can meet challenges;",
            "● Whether they have relationships they can trust and rely on;",
            "● Whether they can express needs and ask for help when things are hard;",
            "● Where their drive to act comes from;",
            "● How they relate to their environment, to others and to tasks.",
        ],
    ))

    # P04 情绪稳定性
    polarity = [
        ("Inferiority", "Self-Esteem", "12"),
        ("Depression", "Pleasure", "11.5"),
        ("Anxiety", "Serenity", "9"),
        ("Helplessness", "Controllability", "10"),
    ]
    polarity_items = []
    for left, right, value in polarity:
        s = float(value)
        polarity_items.append({
            "left": left, "left_en": "",
            "right": right, "right_en": "",
            "value": value, "max": 15,
            "pct": max(0, min(100, int(s / 15 * 100))),
        })
    out.append(_page_dict(
        "emotional_stability",
        page_title="Emotional Stability",
        subtitle="EMOTIONAL STABILITY",
        page_en="Emotional Stability Assessment",
        intro=("Emotional stability describes how strongly and how widely a person's emotions fluctuate in response to external events or internal psychological change. This assessment is based on the Eysenck emotional stability test, one of the most widely used measures in this area. Eysenck held that people who are marked by low self-esteem, depression, anxiety and dependence on others tend to be more sensitive and fragile emotionally, and more easily affected by their surroundings. By contrast, people who show self-esteem, cheerfulness, serenity and autonomy are more stable, and recover their calm more easily even when they do experience strong emotions."),
        total_score="42.5",
        total_max=60,
        level="Emotionally Stable",
        gauge=gauge_svg(42.5, 60.0),
        peer_avg=40,
        polarity_items=polarity_items,
    ))

    # P05 自我概念
    sub_raw = [
        ("Behavioral Adjustment", 9),
        ("Intellectual and School Status", 6),
        ("Physical Appearance and Attributes", 10),
        ("Freedom from Anxiety", 8),
        ("Popularity", 10),
        ("Happiness and Satisfaction", 9),
    ]
    sub_items = []
    for name, val in sub_raw:
        sub_items.append({
            "label": name, "en": "",
            "value": f"{val:g}", "max": 10,
            "pct": int(val / 10 * 100),
        })
    out.append(_page_dict(
        "self_concept",
        page_title="Self-Concept",
        subtitle="SELF CONCEPT",
        page_en="Self-Concept Dimensions",
        intro=("Self-concept is the sum of what a person believes about themselves: \u201cwho I am and what kind of person I am.\u201d It can also be understood as the impression a person holds of themselves, including their body, abilities, character and attitudes, for example \u201cI am smart,\u201d \u201cI am attractive\u201d or \u201cI do well in school.\u201d The development of self-concept is central to personality formation and socialization."),
        overall_value="96",
        overall_pct=96,
        sub_items=sub_items,
    ))

    # P06 依恋关系
    types = [
        {"role": "Mother", "type": "Secure"},
        {"role": "Father", "type": "Secure"},
        {"role": "Peers", "type": "Secure"},
    ]
    dimensions = [
        {
            "name": "Trust", "en": "", "max": 50,
            "dim_items": [
                {"label": "Trust", "who": "Mother", "value": "47", "pct": 94, "level": "High"},
                {"label": "Trust", "who": "Father", "value": "48", "pct": 96, "level": "High"},
                {"label": "Trust", "who": "Peers", "value": "37", "pct": 74, "level": "High"},
            ],
        },
        {
            "name": "Communication", "en": "", "max": 45,
            "dim_items": [
                {"label": "Communication", "who": "Mother", "value": "33", "pct": 73, "level": "High"},
                {"label": "Communication", "who": "Father", "value": "38", "pct": 84, "level": "High"},
                {"label": "Communication", "who": "Peers", "value": "30", "pct": 67, "level": "Not Low"},
            ],
        },
        {
            "name": "Closeness", "en": "", "max": 30,
            "dim_items": [
                {"label": "Closeness", "who": "Mother", "value": "18", "pct": 60, "level": "Not Low"},
                {"label": "Closeness", "who": "Father", "value": "19", "pct": 63, "level": "Not Low"},
                {"label": "Closeness", "who": "Peers", "value": "17", "pct": 57, "level": "Not Low"},
            ],
        },
    ]
    out.append(_page_dict(
        "attachment",
        page_title="Attachment",
        subtitle="SOCIAL ATTACHMENT",
        page_en="Social Attachment Dimensions",
        intro=("Attachment style is the earliest social bond formed between an individual and their primary caregivers, and reflects a person's tendency to maintain close relationships with significant others. Attachment is classified as secure, avoidant, or anxious-ambivalent. Securely attached individuals form close relationships easily and show trust in and reliance on others. Avoidant individuals avoid closeness. Anxious-ambivalent individuals want closeness but also fear it, and are prone to inner conflict and ambivalence."),
        types=types,
        dimensions=dimensions,
    ))

    # P07 内驱力
    core_raw = [
        ("Autonomy", "Autonomy", 7.1, 6.1),
        ("Competence", "Competence", 8.3, 6.6),
        ("Relatedness", "Relatedness", 9.2, 7.6),
    ]
    core_items = []
    for label, en, val, norm in core_raw:
        core_items.append({
            "label": label, "en": "",
            "value": f"{val:g}", "max": 10.0,
            "pct": int(val / 10.0 * 100),
            "mean": norm,
            "norm_value": f"{norm:g}",
            "norm_pct": int(norm / 10.0 * 100),
            "gauge": circular_gauge_svg(val, 10.0),
        })
    out.append(_page_dict(
        "inner_drive",
        page_title="Inner Drive",
        subtitle="INNER DRIVE",
        page_en="Inner Drive Dimensions",
        mindset_value="69",
        mindset_max=100,
        mindset_pct=69,
        mindset_type="Growth Mindset",
        mindset_type_en="Growth Mindset",
        mindset_gauge=mindset_gauge_svg(69),
        core_items=core_items,
        core_range="/ 10.0",
    ))

    # P08 人格
    big_five_items = [
        {"label": "Openness", "en": "", "value": "4"},
        {"label": "Agreeableness", "en": "", "value": "3.1"},
        {"label": "Conscientiousness", "en": "", "value": "3"},
        {"label": "Extraversion", "en": "", "value": "4"},
        {"label": "Neuroticism", "en": "", "value": "3.1"},
    ]
    avg_items = [{"label": it["label"], "value": 3.0} for it in big_five_items]
    out.append(_page_dict(
        "big_five",
        page_title="Personality",
        subtitle="PERSONALITY",
        page_en="Big Five Personality Dimensions",
        intro=("Personality refers to a person's relatively stable attitudes, ways of thinking and behavioral tendencies toward themselves, other people and the world, for example being introverted or extraverted, open or conservative. Personality is shaped by heredity and is closely tied to ability, interests, ideals and values. It relates not only to physical and mental health but also to academic adjustment and career development. This assessment is based on the Big Five model and covers five areas: extraversion, interpersonal style (agreeableness), rule awareness and self-management (conscientiousness), emotional stability (neuroticism) and openness to new knowledge and experience (openness)."),
        big_five_items=big_five_items,
        radar=radar_svg(big_five_items, 5.0, radius=120, cy=180,
                        color="#2A9D8F", label_padding=45, avg_points=avg_items),
        range_text="/ 5.0",
    ))

    # P09 精力
    out.append(_page_dict(
        "section_intro",
        page_title="Vitality ｜ Energy Management & Physical Health",
        subtitle="VITALITY & PHYSICAL WELLBEING SYSTEM",
        section_num="2.",
        paragraphs=[
            "Growth does not happen only at the psychological and cognitive level. It also rests on the energy the body provides.",
            "A student may have strong cognitive ability and clear goals, but if they are chronically short on sleep, not getting enough exercise, eating poorly or in poor physical condition, those abilities may not show up consistently.",
            "The core questions of the vitality system:",
            "● Does this student have the physical energy and daily rhythm needed to keep moving forward;",
            "● Are their eating, sleep and exercise habits supporting them rather than draining them;",
            "● Do they have the basic awareness and ability to manage their own health.",
        ],
    ))

    # P10 体质健康
    level_map = [
        ("Underweight", "", "#F4A261", 0.9),
        ("Normal", "", "#2A9D8F", 1.0),
        ("Overweight", "", "#E76F51", 1.05),
        ("Obese", "", "#B33A3A", 1.1),
    ]
    figures = [{
        "level": lvl, "level_en": lvl_en, "color": color,
        "active": (lvl == "Overweight"), "scale": scale,
    } for lvl, lvl_en, color, scale in level_map]
    out.append(_page_dict(
        "physical_health",
        page_title="Physical Health",
        subtitle="PHYSICAL HEALTH",
        page_en="Physical Health Assessment",
        intro="",
        bmi_score="22",
        bmi_level="Overweight",
        height_cm="180",
        weight_kg="70",
        figures=figures,
        health_items=[
            {"label": "Diet", "en": "", "score": "", "level": "Poor"},
            {"label": "Sleep", "en": "", "score": "8.6", "level": "Excellent"},
            {"label": "Exercise", "en": "", "score": "24", "level": "Excellent"},
        ],
        health_desc_eat="",
    ))

    # P11 学习力
    out.append(_page_dict(
        "section_intro",
        page_title="Learning Power ｜ Learning System",
        subtitle="LEARNING POWER SYSTEM",
        section_num="3.",
        paragraphs=[
            "Learning power is not the same as exam results, and it is not the same as how smart a student is.",
            "It is the ability to integrate cognitive resources, executive function, learning motivation and learning strategies in order to understand, complete and transfer learning tasks over time.",
            "The core questions of the learning power system:",
            "● Does the student have stable and varied information-processing ability at the cognitive level;",
            "● Can they effectively manage their own attention, memory and thinking while learning;",
            "● Where does their motivation to learn come from: interest, or external pressure;",
            "● Have they mastered effective, transferable learning strategies.",
        ],
    ))

    # P12 认知资源
    out.append(_page_dict(
        "cognitive",
        page_title="Cognitive Resources",
        subtitle="COGNITIVE ABILITY",
        page_en="Cognitive Resource Overview",
        intro=("Cognitive ability is the brain's capacity to process information, understand the internal logic of objective things, and apply knowledge and experience to solve problems. Cognition includes perception, memory, imagination, thinking and judgment. It matters because every kind of human learning depends on cognitive ability."),
        total_score="129",
        percentile="97",
        dist_svg=normal_dist_svg(97),
    ))

    # P12b 六项子指标
    cog_raw = [
        ("Perception", 90,
         "Perception is the foundation of cognition and understanding. It is the brain's overall view and interpretation of external information, and the process includes acquiring, interpreting, selecting and organizing that information."),
        ("Attention", 98,
         "Attention is the direction and concentration of mental activity on a particular object. It is commonly understood as the ability to stay focused on something over time: whether a person concentrates well or is easily distracted. Neurophysiological factors, interest and motivation, and mental state all affect attention."),
        ("Memory", 96,
         "Memory is the nervous system's capacity to store past experience and the basis of learning. It generally involves encoding, retention, recognition and recall. Individual differences in memory affect learning efficiency: some students remember a new word after three exposures, while others may need seven or eight."),
        ("Reasoning", 85,
         "Reasoning is a core component of intelligence: the process of reaching new judgments from existing knowledge and experience through integrated analysis. Differences in reasoning often reflect how well a person grasps the essence of things and the connections between them."),
        ("Spatial Ability", 88,
         "Spatial ability is the brain's capacity to judge the shape and position of objects through observation, touch and imagination. It is the brain's abstract representation of, and reasoning about, external information, and an important mental ability in mathematics, the natural sciences and engineering."),
        ("Processing Speed", 93,
         "Processing speed is how fast the brain handles internal or external information. Like internet speed or the responsiveness of a phone, it directly affects the efficiency of learning, thinking and interpersonal communication."),
    ]
    cognitive_items = [{
        "label": label, "en": "",
        "value": f"{val:g}", "pct": val,
        "desc": desc, "gauge": _cog_gauge(val),
    } for label, val, desc in cog_raw]
    out.append(_page_dict(
        "cognitive_details",
        page_title="", subtitle="", page_en="",
        cognitive_items=cognitive_items,
    ))

    # P13 执行功能
    exec_items = [
        {"label": "Inhibitory Control", "en": "", "value": "60", "pct": 60, "color": "teal",
         "desc": "Inhibitory control is the ability to restrain impulses before acting, think rationally and screen out distractions to complete a task: holding back instincts and desires so that behavior matches the intended goal. It is related to focus, emotion regulation and impulse control."},
        {"label": "Working Memory", "en": "", "value": "89", "pct": 89, "color": "red",
         "desc": "Working memory is the ability to hold and manipulate information in mind consciously. We rely on remembered information to predict the future, and whether that information is complete or partial directly affects how accurate the predictions are. We rely on memory to set goals, plan and carry out tasks, and whether goals are clear, plans are detailed and execution is on track all depend on memory."},
        {"label": "Cognitive Flexibility", "en": "", "value": "83", "pct": 83, "color": "amber",
         "desc": "Cognitive flexibility is the brain's ability to adapt to new, changing or unplanned events. When circumstances change and the original plan is disrupted, or the first approach does not work, people with high cognitive flexibility can view the problem from another angle, adjust their mindset, change course and quickly find a new solution. It affects a child's self-regulation and psychological resilience."},
    ]
    out.append(_page_dict(
        "executive",
        page_title="Executive Function",
        subtitle="EXECUTIVE FUNCTIONS",
        page_en="Executive Functions Overview",
        intro="",
        exec_items=exec_items,
        radar=radar_svg(exec_items, 100.0, radius=100, cx=170, cy=140,
                        color="#2A9D8F", label_padding=45),
        unit="%",
    ))

    # P14 学习动机与策略
    motivation_items = [
        ("Deep Motivation", "6", "7.0",
         "Deep motivation is intrinsic: a genuine interest in learning itself, where learning brings satisfaction and excitement. Students with high deep motivation are generally driven, learn on their own initiative and need no outside supervision or prompting."),
        ("Surface Motivation", "6.4", "5.7",
         "Surface motivation is extrinsic: a lack of interest in learning itself, with study driven by passing exams, earning rewards or avoiding punishment. It is hard to sustain over the long term; once external rewards or penalties disappear, the student may stop learning."),
        ("Self-Efficacy", "8.7", "7.6",
         "Self-efficacy is a person's subjective judgment of whether they can successfully complete a given task. It is built on past experiences of success and an accurate assessment of one's own abilities."),
    ]
    strategy_items = [
        ("Deep Methods and Strategies", "7.2", "6.8",
         "Deep methods and strategies are approaches adopted to understand knowledge thoroughly, a form of deep learning built on comprehension and application. They make what is learned stick better and be understood more fully."),
        ("Surface Methods and Strategies", "7.6", "5.8",
         "Surface methods and strategies are approaches used to memorize specific content or to pass a particular exam. They can show results in the short term but are very unfavorable to long-term development, because learning without real understanding is quick to memorize and quick to forget."),
        ("Self-Regulation", "6.2", "6.6",
         "Self-regulation in learning refers to the adjustments a student makes when they meet difficulty or setbacks, for example still regulating themselves and working hard for good results despite having a teacher or subject they dislike."),
    ]

    def _mk(items_raw):
        res = []
        for label, val, norm, desc in items_raw:
            fval, fnorm = float(val), float(norm)
            res.append({
                "label": label, "en": "",
                "value": val, "unit": "/10.0",
                "pct": int(fval / 10.0 * 100),
                "norm_value": norm,
                "norm_pct": int(fnorm / 10.0 * 100),
                "desc": desc,
            })
        return res

    out.append(_page_dict(
        "learning_motivation",
        page_title="Learning Motivation and Strategies",
        subtitle="LEARNING MOTIVATION & STRATEGIES",
        page_en="Learning Motivation and Strategies",
        motivation_items=_mk(motivation_items),
        strategy_items=_mk(strategy_items),
    ))

    # P15 生涯力
    out.append(_page_dict(
        "section_intro",
        page_title="Career Capacity ｜ Major & Career Development",
        subtitle="MAJOR & CAREER DEVELOPMENT SYSTEM",
        section_num="4.",
        paragraphs=[
            "Career capacity does not mean asking young people to settle early on a single, lifelong career. It helps students gradually come to understand:",
            "● What problems draw me in;",
            "● What I am good at;",
            "● What I hope to gain from future study and work;",
            "● Which directions can carry my interests, abilities and values at the same time.",
            "The core question of the career capacity system:",
            "Where do this student's interests, abilities and values intersect, and how can they gradually develop into a major and career direction that suits them?",
        ],
    ))

    # P16 职业兴趣
    holland_raw = [
        ("R", "Realistic", "7",
         "Prefers concrete, hands-on work such as repairing, assembling or building things; likes operating equipment, tools or machines; prefers specific tasks to abstract thinking or discussion with others; not given to speech-making and prefers to work independently."),
        ("I", "Investigative", "6",
         "Likes to study abstract problems, is good at logical analysis and enjoys exploring the unknown; likes observing, learning, thinking, investigating and experimenting; good at posing and solving problems; independent and careful by nature."),
        ("A", "Artistic", "6",
         "Creative and expressive; uses writing, art, music or drama to communicate, perform or express themselves, and to create and design things; imaginative; likes an unconstrained, free life and fresh, stimulating experiences; dislikes a life that never changes."),
        ("S", "Social", "8",
         "Warm and kind; enjoys helping others; cares about social issues; likes to help and serve people alongside others; cares about the happiness and welfare of others."),
        ("E", "Enterprising", "8",
         "Pursues power and profit; likes competition, and is ambitious and aspiring; likes to influence others and lead them toward goals; energetic and able to take charge of the big picture."),
        ("C", "Conventional", "6",
         "Follows rules and procedures; likes repetitive, routine work and dislikes change; careful by nature, conscientious and attentive to detail; prefers to cooperate and comply, and does not like to lead others."),
    ]
    holland_items = [{
        "letter": letter, "label": label, "en": "",
        "value": val, "pct": int(float(val) / 10.0 * 100),
        "desc": desc,
    } for letter, label, val, desc in holland_raw]
    out.append(_page_dict(
        "holland",
        page_title="Vocational Interests",
        subtitle="VOCATIONAL INTEREST",
        page_en="Holland Vocational Interest Types",
        intro=("Vocational interest is how interest shows up in career choice, and reflects an aspect of personality. It can be understood as an explicit or implicit preference for, and wish to do, a certain kind of work. The Holland Code is formed by ranking the results of the vocational interest assessment from highest to lowest score. The three highest-scoring codes make up the student's Holland Code."),
        code="ESR",
        holland_items=holland_items,
    ))

    # P17 能力优势
    intell_raw = [
        ("Interpersonal", 10), ("Bodily-Kinesthetic", 8), ("Intrapersonal", 8),
        ("Linguistic", 7), ("Logical-Mathematical", 7), ("Spatial", 7),
        ("Naturalist", 5), ("Musical", 3),
    ]
    intell_items = [{
        "label": name, "en": "", "value": f"{val:g}",
        "pct": int(val / 10.0 * 100),
    } for name, val in intell_raw]
    intell_items[0]["is_max"] = True
    intell_items[-1]["is_min"] = True
    out.append(_page_dict(
        "intelligences",
        page_title="Strengths and Abilities",
        subtitle="MULTIPLE INTELLIGENCES",
        page_en="Gardner's Multiple Intelligences",
        intro=("Everyone has their own gifts and strengths. When people use their strengths to learn or work, they tend to be more efficient and focused, and find it easier to feel a sense of achievement and enjoyment. Psychologist Howard Gardner proposed that human ability can be divided into eight types."),
        intelligence_items=intell_items,
        max_score=intell_items[0]["value"],
        min_score=intell_items[-1]["value"],
    ))

    # P18 职业价值观
    values_raw = [
        ("Supervisor Relations", "An open-minded, democratic and fair supervisor", "Having a good boss"),
        ("Social Status", "Work that holds a high place in people's minds", "High standing, respected by others"),
        ("Achievement", "Continually achieving new things, earning recognition or accomplishing what one wants to do", "Work that gives me a sense of achievement"),
        ("Management Power", "Managing and directing others", "Influencing and leading others"),
        ("Colleague Relations", "Most colleagues are of good character and pleasant to work with", "Working with people I like"),
        ("Intellectual Stimulation", "Requires thinking, learning, exploring new things and solving new problems", "Challenging"),
        ("Lifestyle", "Being able to choose the life one wants: comfortable, simple, happy or fulfilling", "The right to choose my way of life"),
        ("Creativity", "Inventing new things, whether a new product, idea or method", "Inventing and creating new things"),
        ("Work Environment", "Seeks a comfortable, relaxed and free work environment", "A comfortable, relaxed, free workplace"),
        ("Independence", "Working in one's own way or by one's own ideas, free from others' influence", "Working by my own ideas and pace"),
        ("Economic Reward", "High pay and a comfortable standard of living", "High salary and good benefits"),
        ("Aesthetic Pursuit", "Continually seeking beautiful things and enjoying beauty", "Experiencing and appreciating beauty"),
        ("Security", "Stable work with a guaranteed income and no risk of unemployment", "Stable, no risk of job loss"),
        ("Altruism", "Contributing to the happiness and welfare of others", "Being able to help others"),
        ("Variety", "Dislikes simple, repetitive work; prefers challenging, varied work", "Trying different kinds of work"),
    ]
    values_items = [{
        "label": name, "en": "", "num": i, "rank": i,
        "value": "5", "pct": 50,
        "feature": feature, "monologue": monologue,
    } for i, (name, feature, monologue) in enumerate(values_raw, start=1)]
    out.append(_page_dict(
        "values_grid",
        page_title="Career Values",
        subtitle="CAREER VALUES",
        page_en="Top Work Values & Priorities",
        intro="",
        values_items=values_items,
    ))

    # P19 封底
    out.append(_page_dict(
        "backcover",
        page_title="Y4 Assessment Report · Reading Notes",
        paragraphs=[
            {"title": "Assessment does not define or classify",
             "content": "This report is intended to show characteristics, not to attach fixed \u201clabels\u201d to a student or confine them to a single model."},
            {"title": "Results reflect a point in time",
             "content": "The report records the test taker's state at the time of testing, which is shaped by environment, mood and a range of underlying factors."},
            {"title": "Interpret in context",
             "content": "The data must be read in light of the student's specific background and professional context. Do not draw conclusions from isolated figures."},
            {"title": "Consult a professional assessor",
             "content": "To make sure the report is understood correctly, please consult an APP ARK assessor when reading it, for an objective and comprehensive interpretation."},
        ],
        copyright="This report is confidential material of APP ARK, which holds all rights to it. Forwarding or disclosing it in any form without the dual authorization of an APP ARK assessor and the family concerned is strictly prohibited.",
    ))

    return out


# ---------------------------------------------------------------- 渲染
def render(view_data: Dict[str, Any], template_path: Path, output_path: Path) -> None:
    branding_src = ROOT / "branding"
    branding_dst = output_path.parent / "branding"
    if not branding_dst.exists():
        shutil.copytree(str(branding_src), str(branding_dst))
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template(template_path.name)
    html = template.render(**view_data)
    output_path.write_text(html, encoding="utf-8")
    print(f"  HTML 已渲染 → {output_path} ({len(html)} chars)")


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    print("[1/3] 生成英文模板 ...")
    template_path = build_english_template()
    print(f"  → {template_path}")

    print("[2/3] 渲染 HTML ...")
    view_data = {"student": STUDENT, "pages": pages()}
    html_path = OUTPUT_DIR / "Y4_Assessment_Report_Jeslyn.html"
    render(view_data, template_path, html_path)

    print("[3/3] 生成 PDF ...")
    pdf_path = OUTPUT_DIR / "Y4_Assessment_Report_Jeslyn.pdf"
    if pdf_path.exists():
        pdf_path.unlink()
    try:
        generate_pdf_with_chrome(html_path, pdf_path)
    except TimeoutExpired:
        # Chrome 打印完成后偶尔不会自行退出；只要 PDF 已写出即视为成功。
        if not pdf_path.exists():
            raise
        print("  Chrome 未在超时内退出，但 PDF 已生成。")
    print("完成。")


if __name__ == "__main__":
    main()