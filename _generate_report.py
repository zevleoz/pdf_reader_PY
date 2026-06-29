"""综合测评报告生成器。

使用 data/clean_report_data.json 的真实数据生成：
  output/report.html —— 浏览器直接打开
  output/综合评估报告.pdf —— 使用 weasyprint 转换

依赖：PyMuPDF（fitz）仅用于验证 PDF 文本；生成用 weasyprint。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ACCENT = "#e2542c"
GRAY = "#1f2430"
MUTED = "#9aa4b2"
BLUE = "#2b6cb0"
GREEN = "#2aa67a"
GOLD = "#c08a2a"
PURPLE = "#805ad5"

# ---------- 读取数据 ----------
with open(DATA_DIR / "clean_report_data.json", "r", encoding="utf-8") as f:
    raw = json.load(f)

student = raw["student"]
# 用字典索引以便精确取值（label 可能重复；保留第一个）
items = {}
for it in raw["items"]:
    if it["label"] not in items:
        items[it["label"]] = it


def val(label: str, default: float | None = None) -> float | None:
    it = items.get(label)
    if it is None or it.get("value") is None:
        return default
    try:
        return float(it["value"])
    except (TypeError, ValueError):
        return default


def mean(label: str, default: float | None = None) -> float | None:
    it = items.get(label)
    if it is None or it.get("mean") is None:
        return default
    try:
        return float(it["mean"])
    except (TypeError, ValueError):
        return default


def fmt_num(v: float | int | None) -> str:
    """格式化数字为字符串；整数不显示 .0。"""
    if v is None:
        return "—"
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    # 保留最多 2 位小数去掉尾部 0
    if isinstance(v, float):
        s = f"{v:.2f}".rstrip("0").rstrip(".")
        return s
    return str(v)


# ---------- SVG 组件 ----------
def ring_svg(percent: float, center_text: str, color: str, size: int = 52) -> str:
    r = (size - 8) / 2
    circumference = 2 * math.pi * r
    pct = max(0.0, min(1.0, percent))
    filled = circumference * pct
    cx = cy = size / 2
    text_size = size * 0.36
    return (
        f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#eef0f4" stroke-width="6"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="6" '
        f'stroke-dasharray="{filled} {circumference - filled}" '
        f'transform="rotate(-90 {cx} {cy})" stroke-linecap="round"/>'
        f'<text x="{cx}" y="{cy + text_size/3}" text-anchor="middle" '
        f'font-size="{text_size}" font-weight="700" fill="{GRAY}">{center_text}</text>'
        f'</svg>'
    )


def radar_svg(labels: list[str], scores: list[float], means: list[float]) -> str:
    cx, cy = 100, 100
    radius = 80
    n = len(labels)

    grid = []
    for ring_i in range(1, 6):
        r = radius * ring_i / 5
        pts = []
        for i in range(n):
            angle = -90 + i * (360 / n)
            rad = angle * math.pi / 180
            pts.append(f"{cx + r * math.cos(rad):.1f},{cy + r * math.sin(rad):.1f}")
        grid.append(f'<polygon points="{" ".join(pts)}" fill="none" stroke="#e6e8ef" stroke-width="1"/>')

    axes = []
    for i in range(n):
        angle = -90 + i * (360 / n)
        rad = angle * math.pi / 180
        axes.append(
            f'<line x1="{cx}" y1="{cy}" '
            f'x2="{cx + radius * math.cos(rad):.1f}" y2="{cy + radius * math.sin(rad):.1f}" '
            f'stroke="#e6e8ef" stroke-width="1"/>'
        )

    def poly(values: list[float]) -> str:
        pts = []
        for i in range(n):
            angle = -90 + i * (360 / n)
            rad = angle * math.pi / 180
            r = radius * (values[i] / 5.0)
            pts.append(f"{cx + r * math.cos(rad):.1f},{cy + r * math.sin(rad):.1f}")
        return " ".join(pts)

    label_texts = []
    for i, lab in enumerate(labels):
        angle = -90 + i * (360 / n)
        rad = angle * math.pi / 180
        tx = cx + (radius + 15) * math.cos(rad)
        ty = cy + (radius + 15) * math.sin(rad)
        label_texts.append(
            f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="middle" '
            f'font-size="10" font-weight="700" fill="{GRAY}">{lab}</text>'
        )

    return (
        '<svg viewBox="0 0 200 200" width="170" height="170">'
        + "".join(grid)
        + "".join(axes)
        + f'<polygon points="{poly(means)}" fill="#c9d2e0" fill-opacity="0.45" stroke="#9aa4b2" stroke-width="1.5"/>'
        + f'<polygon points="{poly(scores)}" fill="{ACCENT}" fill-opacity="0.18" stroke="{ACCENT}" stroke-width="2"/>'
        + "".join(label_texts)
        + "</svg>"
    )


def bar_row(name: str, en: str, score: float, max_val: float = 10,
            color: str = ACCENT) -> str:
    pct = max(0, min(100, (score / max_val) * 100))
    return (
        f'<div class="bar-row">'
        f'<div class="name">{name}<small>{en}</small></div>'
        f'<div class="track"><div style="height:100%;width:{pct}%;'
        f'background:linear-gradient(90deg,{color},#f58220);border-radius:4px"></div></div>'
        f'<div class="score">{fmt_num(score)}<small>/{int(max_val)}</small></div>'
        f'</div>'
    )


# ---------- 内容卡片 ----------
def metric_card(label: str, en: str, center_text: str, detail: str,
                color: str = ACCENT, ring_pct: float = 0.5, size: int = 52) -> str:
    return (
        f'<div class="metric-card">'
        f'<div class="ring">{ring_svg(ring_pct, center_text, color, size)}</div>'
        f'<div class="info">'
        f'<div class="label">{label}</div>'
        f'<div class="en">{en}</div>'
        f'<div class="values">{detail}</div>'
        f'</div>'
        f'</div>'
    )


def mini_card(label: str, en: str, center_text: str, color: str = BLUE,
              ring_pct: float = 0.5, size: int = 52) -> str:
    return (
        f'<div class="mini-card">'
        f'{ring_svg(ring_pct, center_text, color, size)}'
        f'<div class="label">{label}</div>'
        f'<div class="en">{en}</div>'
        f'</div>'
    )


def group_header(name: str, en: str, summary: str = "") -> str:
    return (
        f'<div class="group-header">'
        f'<div class="group-title-bar"></div>'
        f'<div class="group-title-row">'
        f'<div class="group-title-name">{name}</div>'
        f'<div class="group-title-en">{en}</div>'
        f'</div>'
        f'<div class="group-summary">{summary}</div>'
        f'</div>'
    )


def section_header(num: str, title: str, en: str, desc: str) -> str:
    return (
        f'<section class="section">'
        f'<div class="section-header">'
        f'<div class="sec-num">{num}</div>'
        f'<div class="sec-body">'
        f'<div class="sec-en">{en}</div>'
        f'<h2 class="sec-title">{title}</h2>'
        f'<div class="sec-desc">{desc}</div>'
        f'</div>'
        f'</div>'
    )


# ========================================================================
# 章节内容
# ========================================================================

def section_01_core_literacy() -> str:
    """核心素养：情绪稳定性 + 依恋关系 + 思维模式&内驱力 + 大五人格 + 体质健康"""
    html = section_header(
        "01", "核心素养", "CORE LITERACY",
        "情绪稳定性、依恋关系、思维模式、大五人格与体质健康的综合画像。",
    )

    # --- 情绪稳定性 ---
    emo_total = val("情绪稳定性总分", 0) or 0
    emo_mean_val = mean("情绪稳定性总分")

    html += group_header("情绪稳定性", "EMOTIONAL STABILITY", "总分与子维度 · 满分 60")
    html += '<div class="cards-3">'
    mean_line = f'同龄人平均 <strong style="color:{ACCENT}">{fmt_num(emo_mean_val)}</strong>' if emo_mean_val is not None else ""
    html += metric_card(
        "情绪稳定性总分", "TOTAL SCORE",
        fmt_num(emo_total),
        f'{mean_line}<span class="out-of"> / 60</span>',
        ACCENT, emo_total / 60, 52,
    )
    # 自卑/自尊，抑郁/愉快，焦虑/安详，无力感/掌控感（若有则显示）
    sub_pairs = [
        ("自卑/自尊", "SELF-ESTEEM vs INFERIORITY",
         (val("自卑", 0) or 0) + (val("自尊", 0) or 0), 15, BLUE),
        ("抑郁/愉快", "DEPRESSION vs CHEERFULNESS",
         (val("抑郁", 0) or 0) + (val("愉快", 0) or 0), 15, BLUE),
        ("焦虑/安详", "ANXIETY vs SERENITY",
         (val("焦虑", 0) or 0) + (val("安详", 0) or 0), 15, BLUE),
        ("无力感/掌控感", "HELPLESSNESS vs CONTROL",
         (val("无力感", 0) or 0) + (val("掌控感", 0) or 0), 15, BLUE),
    ]
    for name, en, sc, mx, color in sub_pairs:
        if sc <= 0:
            continue
        html += metric_card(
            f"情绪稳定性-{name}", en, fmt_num(sc),
            f'<span class="out-of"> / {mx}</span>',
            color, sc / mx, 52,
        )
    html += "</div>"

    # --- 依恋关系（九宫格） ---
    html += group_header(
        "依恋关系", "SOCIAL ATTACHMENT",
        "信任 / 沟通 / 亲近 × 母亲 / 父亲 / 同伴",
    )
    attach = [
        ("依恋-信任-母亲", "TRUST · MOTHER", val("信任-母亲", 0) or 0, 50, GOLD),
        ("依恋-信任-父亲", "TRUST · FATHER", val("信任-父亲", 0) or 0, 50, GOLD),
        ("依恋-信任-同伴", "TRUST · PEERS", val("信任-同伴", 0) or 0, 50, GOLD),
        ("依恋-沟通-母亲", "COMM · MOTHER", val("沟通-母亲", 0) or 0, 50, BLUE),
        ("依恋-沟通-父亲", "COMM · FATHER", val("沟通-父亲", 0) or 0, 50, BLUE),
        ("依恋-沟通-同伴", "COMM · PEERS", val("沟通-同伴", 0) or 0, 50, BLUE),
        ("依恋-亲近-母亲", "INTIMACY · MOTHER", val("亲近-母亲", 0) or 0, 50, PURPLE),
        ("依恋-亲近-父亲", "INTIMACY · FATHER", val("亲近-父亲", 0) or 0, 50, PURPLE),
        ("依恋-亲近-同伴", "INTIMACY · PEERS", val("亲近-同伴", 0) or 0, 50, PURPLE),
    ]
    html += '<div class="mini-grid">'
    for name, en, sc, mx, color in attach:
        if sc <= 0:
            continue
        html += mini_card(name, en, fmt_num(sc), color, sc / mx, 52)
    html += "</div>"

    # --- 思维模式 & 内驱力 ---
    html += group_header(
        "思维模式 & 内驱力", "MINDSET & SELF-DRIVING FORCE",
        "思维模式结果 · 深层动机 · 自我效能感",
    )
    html += '<div class="cards-3">'
    html += metric_card(
        "思维模式结果", "MINDSET RESULT", "成长型",
        f'<span class="out-of">Growth Mindset</span>',
        ACCENT, 0.9, 52,
    )
    deep_mot = val("深层动机", 0) or 0
    if deep_mot > 0:
        m = mean("深层动机")
        mean_line = f'同龄人平均 <strong style="color:{ACCENT}">{fmt_num(m)}</strong>' if m is not None else ""
        html += metric_card(
            "自驱力-自主性", "AUTONOMY", fmt_num(deep_mot),
            f'{mean_line}<span class="out-of"> / 10</span>',
            PURPLE, deep_mot / 10, 52,
        )
    self_eff = val("自我效能感", 0) or 0
    if self_eff > 0:
        m = mean("自我效能感")
        mean_line = f'同龄人平均 <strong style="color:{ACCENT}">{fmt_num(m)}</strong>' if m is not None else ""
        html += metric_card(
            "自驱力-胜任感", "COMPETENCE", fmt_num(self_eff),
            f'{mean_line}<span class="out-of"> / 10</span>',
            PURPLE, self_eff / 10, 52,
        )
    html += "</div>"

    # --- 大五人格（雷达图） ---
    big5_labels = ["开放性", "宜人性", "责任心", "外倾性", "神经质"]
    big5_scores = [val(lab, 0) or 0 for lab in big5_labels]
    big5_means = [mean(lab) or 3.0 for lab in big5_labels]
    bullets = "".join(
        f'<li><strong style="color:{ACCENT}">{fmt_num(s)}</strong> 分 · 平均 {fmt_num(m)} 分</li>'
        for s, m in zip(big5_scores, big5_means)
    )
    html += group_header("大五人格", "BIG FIVE PERSONALITY",
                         "开放性 · 宜人性 · 责任心 · 外倾性 · 神经质")
    html += (
        f'<div class="radar-panel">'
        f'<div class="chart-box">{radar_svg(big5_labels, big5_scores, big5_means)}</div>'
        f'<div class="text">'
        f'<h3>人格画像概览</h3>'
        f'<ul>{bullets}</ul>'
        f'<div class="legend-row">'
        f'<span><span class="swatch" style="background:{ACCENT}"></span>我的得分</span>'
        f'<span><span class="swatch" style="background:#9aa4b2"></span>同龄人平均</span>'
        f'</div>'
        f'</div>'
        f'</div>'
    )

    # --- 体质健康 ---
    html += group_header("体质健康", "PHYSICAL HEALTH",
                         "BMI · 身高 · 体重 · 睡眠 · 运动")
    body = [
        ("BMI", "BMI SCORE", val("BMI", 0) or 0, 40, GOLD, "KG/M²"),
        ("身高", "HEIGHT", val("身高", 0) or 0, 220, BLUE, "CM"),
        ("体重", "WEIGHT", val("体重", 0) or 0, 120, GREEN, "KG"),
        ("睡眠习惯", "SLEEP HOURS", val("每日睡眠时长", 0) or 0, 12, PURPLE, "小时/天"),
        ("运动习惯", "EXERCISE HOURS", val("每周运动时长", 0) or 0, 20, ACCENT, "小时/周"),
    ]
    html += '<div class="cards-3">'
    for name, en, sc, mx, color, extra in body:
        if sc <= 0:
            continue
        html += metric_card(
            f"体质健康-{name}", en, fmt_num(sc),
            f'<span class="out-of"> · {extra}</span>',
            color, sc / mx, 52,
        )
    html += "</div>"

    html += "</section>"
    return html


def section_02_learning() -> str:
    html = section_header(
        "02", "核心学习能力", "CORE LEARNING ABILITY",
        "认知资源、执行功能、学习动机与学习方法的综合表现。",
    )

    total_score = val("认知能力总得分", 0) or 0
    total_pct = val("认知能力百分位", 0) or 0

    html += (
        f'<div class="hero-card">'
        f'{ring_svg(total_pct / 100, fmt_num(total_pct), ACCENT, 100)}'
        f'<div>'
        f'<div class="label">核心学习能力 · 综合表现</div>'
        f'<div class="en">CORE LEARNING PROFILE</div>'
        f'<div class="desc">'
        f'综合认知总得分 <strong style="color:{ACCENT}">{fmt_num(total_score)}</strong>，'
        f'百分位 <strong style="color:{ACCENT}">{fmt_num(total_pct)}%</strong>。'
        f'以下依次呈现认知资源、执行功能、学习动机与学习方法。'
        f'</div>'
        f'</div>'
        f'</div>'
    )

    # 认知资源（六项）
    html += group_header("认知资源", "COGNITIVE RESOURCES", "六项认知维度百分位")
    cog = [
        ("认知能力-感知觉", "PERCEPTION", val("感知觉", 0) or 0, BLUE),
        ("认知能力-注意力", "ATTENTION", val("注意力", 0) or 0, BLUE),
        ("认知能力-记忆力", "MEMORY", val("记忆力", 0) or 0, BLUE),
        ("认知能力-推理能力", "REASONING", val("推理能力", 0) or 0, BLUE),
        ("认知能力-空间能力", "SPATIAL", val("空间能力", 0) or 0, BLUE),
        ("认知能力-加工速度", "PROCESSING SPEED", val("加工速度", 0) or 0, BLUE),
    ]
    html += '<div class="mini-grid">'
    for name, en, sc, color in cog:
        if sc <= 0:
            continue
        html += mini_card(name, en, fmt_num(sc), color, sc / 100, 52)
    html += "</div>"

    # 执行功能
    html += group_header("执行功能", "EXECUTIVE FUNCTIONS",
                         "抑制控制 · 工作记忆 · 认知灵活性")
    exec_list = [
        ("抑制控制", "INHIBITORY CONTROL", val("抑制控制", 0) or 0),
        ("工作记忆", "WORKING MEMORY", val("工作记忆", 0) or 0),
        ("认知灵活性", "COGNITIVE FLEXIBILITY", val("认知灵活性", 0) or 0),
    ]
    html += '<div class="cards-3">'
    for name, en, sc in exec_list:
        if sc <= 0:
            continue
        html += metric_card(
            f"执行功能-{name}", en, fmt_num(sc),
            f'<span class="out-of"> / 100</span>',
            BLUE, sc / 100, 52,
        )
    html += "</div>"

    # 学习动机
    html += group_header("学习动机", "LEARNING MOTIVATION",
                         "深层动机 · 表面动机 · 自我效能感")
    mot_list = [
        ("学习动机-深层动机", "DEEP MOTIVATION",
         val("深层动机", 0) or 0, mean("深层动机")),
        ("学习动机-表面动机", "SURFACE MOTIVATION",
         val("表面动机", 0) or 0, mean("表面动机")),
        ("学习动机-自我效能感", "SELF-EFFICACY",
         val("自我效能感", 0) or 0, mean("自我效能感")),
    ]
    html += '<div class="cards-3">'
    for name, en, sc, m in mot_list:
        if sc <= 0:
            continue
        mean_line = f'同龄人平均 <strong style="color:{ACCENT}">{fmt_num(m)}</strong>' if m is not None else ""
        html += metric_card(
            name, en, fmt_num(sc),
            f'{mean_line}<span class="out-of"> / 10</span>',
            ACCENT, sc / 10, 52,
        )
    html += "</div>"

    # 学习方法
    html += group_header("学习方法与策略", "LEARNING METHODS & STRATEGIES",
                         "深层方法 · 表面方法 · 自我调节")
    strat_list = [
        ("学习-深层方法", "DEEP APPROACH",
         val("学习深层方法与策略", 0) or 0, mean("学习深层方法与策略")),
        ("学习-表面方法", "SURFACE APPROACH",
         val("学习表面方法与策略", 0) or 0, mean("学习表面方法与策略")),
        ("学习-自我调节", "SELF-REGULATION",
         val("学习自我调节", 0) or 0, mean("学习自我调节")),
    ]
    html += '<div class="cards-3">'
    for name, en, sc, m in strat_list:
        if sc <= 0:
            continue
        mean_line = f'同龄人平均 <strong style="color:{ACCENT}">{fmt_num(m)}</strong>' if m is not None else ""
        html += metric_card(
            name, en, fmt_num(sc),
            f'{mean_line}<span class="out-of"> / 10</span>',
            PURPLE, sc / 10, 52,
        )
    html += "</div>"

    html += "</section>"
    return html


def section_03_cognitive_mindset() -> str:
    html = section_header(
        "03", "核心认知 & 成长型思维",
        "COGNITIVE ABILITY & GROWTH MINDSET",
        "六项认知子指标的综合表现及成长性思维倾向。",
    )

    total_score = val("认知能力总得分", 0) or 0
    total_pct = val("认知能力百分位", 0) or 0

    html += (
        f'<div class="hero-card">'
        f'{ring_svg(total_pct / 100, fmt_num(total_score), BLUE, 100)}'
        f'<div>'
        f'<div class="label">核心认知能力 · 总得分 {fmt_num(total_score)}</div>'
        f'<div class="en">COGNITIVE ABILITY TOTAL · PERCENTILE {fmt_num(total_pct)}%</div>'
        f'<div class="desc">'
        f'综合六项认知子指标，学生整体处于同龄人 '
        f'<strong style="color:{ACCENT}">{fmt_num(total_pct)}%</strong> 百分位。'
        f'以下为各项子指标的详细表现。'
        f'</div>'
        f'</div>'
        f'</div>'
    )

    html += group_header("认知能力六项子指标", "COGNITIVE SUBSCALES",
                         "百分位（满分 100）")
    cog = [
        ("感知觉", "PERCEPTION", val("感知觉", 0) or 0, mean("感知觉"), BLUE),
        ("注意力", "ATTENTION", val("注意力", 0) or 0, mean("注意力"), BLUE),
        ("记忆力", "MEMORY", val("记忆力", 0) or 0, mean("记忆力"), BLUE),
        ("推理能力", "REASONING", val("推理能力", 0) or 0, mean("推理能力"), BLUE),
        ("空间能力", "SPATIAL", val("空间能力", 0) or 0, mean("空间能力"), BLUE),
        ("加工速度", "PROCESSING SPEED", val("加工速度", 0) or 0, mean("加工速度"), BLUE),
    ]
    html += '<div class="cards-3">'
    for name, en, sc, m, color in cog:
        if sc <= 0:
            continue
        mean_line = f'同龄人平均 <strong style="color:{ACCENT}">{fmt_num(m)}</strong>' if m is not None else ""
        html += metric_card(
            f"认知能力-{name}", en, fmt_num(sc),
            f'{mean_line}<span class="out-of"> / 100</span>',
            color, sc / 100, 52,
        )
    html += "</div>"

    html += "</section>"
    return html


def section_04_career() -> str:
    html = section_header(
        "04", "职业发展", "CAREER DEVELOPMENT",
        "Holland 职业兴趣、多元智能优势与职业价值观的综合画像。",
    )

    html += group_header(
        "职业兴趣 (Holland)", "HOLLAND OCCUPATIONAL INTERESTS",
        "现实型 · 研究型 · 艺术型 · 社会型 · 事业型 · 常规型",
    )
    holland = [
        ("现实型", "REALISTIC", val("现实型", 0) or 0, ACCENT),
        ("研究型", "INVESTIGATIVE", val("研究型", 0) or 0, BLUE),
        ("艺术型", "ARTISTIC", val("艺术型", 0) or 0, PURPLE),
        ("社会型", "SOCIAL", val("社会型", 0) or 0, GREEN),
        ("事业型", "ENTERPRISING", val("事业型", 0) or 0, ACCENT),
        ("常规型", "CONVENTIONAL", val("常规型", 0) or 0, GOLD),
    ]
    html += "".join(bar_row(n, en, s, 10, c) for n, en, s, c in holland if s > 0)

    html += group_header(
        "能力优势（多元智能）", "MULTIPLE INTELLIGENCES",
        "语言 · 逻辑数学 · 空间 · 身体运动 · 音乐 · 人际 · 内省 · 自然",
    )
    mi = [
        ("语言能力", "LINGUISTIC", val("语言能力", 0) or 0, BLUE),
        ("逻辑数学能力", "LOGICAL-MATHEMATICAL", val("逻辑数学能力", 0) or 0, PURPLE),
        ("空间能力", "SPATIAL", val("空间能力", 0) or 0, GOLD),
        ("身体运动能力", "BODILY-KINESTHETIC", val("身体运动能力", 0) or 0, ACCENT),
        ("音乐能力", "MUSICAL", val("音乐能力", 0) or 0, PURPLE),
        ("人际关系能力", "INTERPERSONAL", val("人际关系能力", 0) or 0, GREEN),
        ("内省能力", "INTRAPERSONAL", val("内省能力", 0) or 0, BLUE),
        ("自然能力", "NATURALISTIC", val("自然能力", 0) or 0, GREEN),
    ]
    mi.sort(key=lambda x: -x[2])
    html += "".join(bar_row(n, en, s, 10, c) for n, en, s, c in mi if s > 0)

    html += group_header("职业价值观", "WORK VALUES", "生活方式 · 美的追求")
    values = [
        ("生活方式", "LIFESTYLE", val("生活方式", 0) or 0, ACCENT),
        ("美的追求", "AESTHETIC PURSUIT", val("美的追求", 0) or 0, PURPLE),
    ]
    html += "".join(bar_row(n, en, s, 10, c) for n, en, s, c in values if s > 0)

    html += "</section>"
    return html


# ========================================================================
# CSS 样式
# ========================================================================
CSS = f"""
@page {{
  size: A4;
  margin: 1.8cm 1.6cm 2.0cm 1.6cm;
  @bottom-left {{
    content: "APP-ARK  凭远教育";
    font-size: 8pt;
    color: {MUTED};
    letter-spacing: 2px;
  }}
  @bottom-center {{
    content: counter(page) " / " counter(pages);
    font-size: 9pt;
    color: {MUTED};
  }}
  @bottom-right {{
    content: "{student.get('name', '同学')} · {student.get('test_date', '')}";
    font-size: 8pt;
    color: {MUTED};
  }}
}}

html {{ counter-reset: page; }}
body {{
  font-family: "PingFang SC", "Hiragino Sans GB", "STHeiti",
               "Microsoft YaHei", "SimSun", sans-serif;
  color: {GRAY};
  font-size: 10pt;
  line-height: 1.55;
  margin: 0;
}}

/* ============ 封面 ============ */
.cover {{
  padding: 0.5cm 0 0.5cm 0;
  page-break-after: always;
}}
.cover .brand-line {{
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  border-bottom: 1px solid #e6e8ef;
  padding-bottom: 8px;
  margin-bottom: 2.2cm;
}}
.cover .brand {{
  font-size: 12pt;
  font-weight: 700;
  color: {GRAY};
  letter-spacing: 2px;
}}
.cover .brand .dot {{
  display: inline-block;
  width: 8px;
  height: 8px;
  background: {ACCENT};
  border-radius: 2px;
  margin-right: 6px;
  vertical-align: middle;
}}
.cover .report-type {{
  font-size: 8pt;
  color: {MUTED};
  letter-spacing: 3px;
  text-transform: uppercase;
}}
.cover .title-block .ch {{
  font-size: 36pt;
  font-weight: 800;
  letter-spacing: 6px;
  color: {GRAY};
  line-height: 1.1;
  margin: 0;
}}
.cover .title-block .ch em {{
  color: {ACCENT};
  font-style: normal;
}}
.cover .title-block .en {{
  font-size: 10pt;
  color: {MUTED};
  letter-spacing: 6px;
  text-transform: uppercase;
  margin-top: 10px;
  font-weight: 500;
}}
.cover .accent-bar {{
  width: 48px;
  height: 4px;
  background: {ACCENT};
  margin: 24px 0;
  border-radius: 2px;
}}
.cover .summary {{
  font-size: 10pt;
  color: #5c6371;
  max-width: 14cm;
  line-height: 1.75;
}}
.student-grid {{
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin: 2.0cm 0 1.5cm 0;
}}
.student-grid .cell {{
  padding: 10px 12px;
  background: #f7f8fb;
  border-left: 3px solid {ACCENT};
  border-radius: 0 6px 6px 0;
}}
.student-grid .cell .k {{
  font-size: 7.5pt;
  color: {MUTED};
  letter-spacing: 1.5px;
  text-transform: uppercase;
}}
.student-grid .cell .v {{
  font-size: 12pt;
  font-weight: 700;
  color: {GRAY};
  margin-top: 3px;
}}
.toc-title {{
  font-size: 9pt;
  color: {MUTED};
  letter-spacing: 3px;
  text-transform: uppercase;
  margin-bottom: 12px;
  margin-top: 0.5cm;
}}
.toc-list {{
  display: grid;
  gap: 8px;
}}
.toc-list .row {{
  display: grid;
  grid-template-columns: 48px 1fr;
  align-items: start;
  padding: 10px 14px;
  background: #f7f8fb;
  border-radius: 8px;
}}
.toc-list .row .num {{
  font-size: 20pt;
  font-weight: 800;
  color: {ACCENT};
  letter-spacing: 0;
  line-height: 1;
}}
.toc-list .row .t {{
  font-size: 11.5pt;
  font-weight: 700;
  color: {GRAY};
  margin-top: 1px;
}}
.toc-list .row .s {{
  font-size: 8.5pt;
  color: {MUTED};
  margin-top: 4px;
}}

/* ============ 章节 ============ */
.section {{
  page-break-before: always;
}}
.section-header {{
  display: grid;
  grid-template-columns: 80px 1fr;
  align-items: center;
  padding: 16px 0;
  margin-bottom: 18px;
  border-bottom: 1px solid #e6e8ef;
}}
.section-header .sec-num {{
  font-size: 40pt;
  font-weight: 800;
  color: {ACCENT};
  line-height: 1;
  text-align: left;
}}
.section-header h2 {{
  font-size: 18pt;
  font-weight: 700;
  color: {GRAY};
  margin: 0 0 4px 0;
  letter-spacing: 1px;
}}
.section-header .sec-en {{
  font-size: 9pt;
  color: {MUTED};
  letter-spacing: 3px;
  text-transform: uppercase;
  margin-bottom: 6px;
}}
.section-header .sec-desc {{
  font-size: 9.5pt;
  color: #5c6371;
  line-height: 1.55;
}}

/* ============ 小组标题 ============ */
.group-header {{
  margin: 18px 0 12px 0;
  padding-left: 12px;
  border-left: 3px solid {ACCENT};
  page-break-inside: avoid;
}}
.group-header .group-title-row {{
  display: flex;
  align-items: baseline;
  gap: 12px;
}}
.group-header .group-title-name {{
  font-size: 12pt;
  font-weight: 700;
  color: {GRAY};
}}
.group-header .group-title-en {{
  font-size: 7.5pt;
  color: {MUTED};
  letter-spacing: 2px;
  text-transform: uppercase;
}}
.group-header .group-summary {{
  font-size: 8.5pt;
  color: {MUTED};
  margin-top: 4px;
}}

/* ============ 卡片网格 ============ */
.cards-3 {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}}
.metric-card {{
  background: #fff;
  border: 1px solid #e6e8ef;
  border-radius: 10px;
  padding: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  page-break-inside: avoid;
}}
.metric-card .ring {{
  flex: 0 0 auto;
  width: 52px;
  height: 52px;
}}
.metric-card .ring svg {{
  width: 100%;
  height: 100%;
  display: block;
}}
.metric-card .info {{
  flex: 1 1 auto;
  min-width: 0;
}}
.metric-card .info .label {{
  font-size: 10pt;
  font-weight: 700;
  color: {GRAY};
  line-height: 1.3;
}}
.metric-card .info .en {{
  font-size: 7pt;
  color: {MUTED};
  letter-spacing: 1.2px;
  text-transform: uppercase;
  margin-top: 2px;
}}
.metric-card .info .values {{
  margin-top: 6px;
  font-size: 8.5pt;
  color: #5c6371;
}}
.metric-card .info .values strong {{
  color: {ACCENT};
  font-size: 10pt;
  font-weight: 700;
  margin-right: 2px;
}}
.metric-card .info .values .out-of {{
  color: {MUTED};
}}

.mini-grid {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}}
.mini-card {{
  background: #fff;
  border: 1px solid #e6e8ef;
  border-radius: 10px;
  padding: 12px 10px;
  text-align: center;
  page-break-inside: avoid;
}}
.mini-card svg {{
  width: 52px;
  height: 52px;
  margin: 0 auto;
  display: block;
}}
.mini-card .label {{
  font-size: 9pt;
  font-weight: 700;
  margin-top: 6px;
  color: {GRAY};
}}
.mini-card .en {{
  font-size: 6.5pt;
  color: {MUTED};
  letter-spacing: 1.2px;
  text-transform: uppercase;
}}

/* ============ Hero 卡片 ============ */
.hero-card {{
  background: #fff;
  border: 1px solid #e6e8ef;
  border-radius: 12px;
  padding: 16px 18px;
  display: grid;
  grid-template-columns: 100px 1fr;
  align-items: center;
  gap: 14px;
  margin-bottom: 10px;
  page-break-inside: avoid;
}}
.hero-card svg {{
  width: 100px;
  height: 100px;
}}
.hero-card .label {{
  font-size: 11pt;
  font-weight: 700;
  color: {GRAY};
}}
.hero-card .en {{
  font-size: 7.5pt;
  color: {MUTED};
  letter-spacing: 2px;
  text-transform: uppercase;
  margin-bottom: 4px;
}}
.hero-card .desc {{
  font-size: 9pt;
  color: #5c6371;
  line-height: 1.55;
  margin-top: 4px;
}}
.hero-card .desc strong {{
  color: {ACCENT};
}}

/* ============ 雷达图面板 ============ */
.radar-panel {{
  display: grid;
  grid-template-columns: 1fr 1.1fr;
  gap: 14px;
  background: #f7f8fb;
  border-radius: 12px;
  padding: 14px 16px;
  align-items: center;
  page-break-inside: avoid;
}}
.radar-panel .chart-box {{
  display: flex;
  align-items: center;
  justify-content: center;
}}
.radar-panel svg {{
  width: 170px;
  height: 170px;
}}
.radar-panel .text h3 {{
  margin: 0 0 6px 0;
  font-size: 11pt;
  font-weight: 700;
  color: {GRAY};
}}
.radar-panel .text ul {{
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: 8.5pt;
  color: #5c6371;
  line-height: 1.8;
}}
.radar-panel .text ul li::before {{
  content: "· ";
  color: {ACCENT};
  font-weight: 700;
}}
.legend-row {{
  display: flex;
  gap: 14px;
  font-size: 8pt;
  color: #5c6371;
  margin-top: 8px;
  align-items: center;
}}
.legend-row .swatch {{
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  margin-right: 4px;
  vertical-align: middle;
  background: {ACCENT};
}}

/* ============ 条形图行 ============ */
.bar-row {{
  display: grid;
  grid-template-columns: 130px 1fr 60px;
  align-items: center;
  padding: 8px 12px;
  background: #fff;
  border: 1px solid #e6e8ef;
  border-radius: 8px;
  margin-bottom: 6px;
  page-break-inside: avoid;
}}
.bar-row .name {{
  font-weight: 700;
  font-size: 9.5pt;
  color: {GRAY};
}}
.bar-row .name small {{
  display: block;
  font-weight: 400;
  color: {MUTED};
  font-size: 7pt;
  letter-spacing: 1.2px;
  text-transform: uppercase;
  margin-top: 1px;
}}
.bar-row .track {{
  height: 8px;
  background: #f0f2f7;
  border-radius: 4px;
  overflow: hidden;
}}
.bar-row .score {{
  text-align: right;
  font-size: 11pt;
  font-weight: 700;
  color: {GRAY};
}}
.bar-row .score small {{
  font-size: 7pt;
  color: {MUTED};
  font-weight: 400;
}}
"""


# ========================================================================
# 组装完整 HTML
# ========================================================================
def build_html() -> str:
    name = student.get("name", "同学")
    grade = student.get("grade", "")
    school = student.get("school", "")
    test_date = student.get("test_date", "")

    cover_html = f'''<section class="cover">
      <div class="brand-line">
        <div class="brand"><span class="dot"></span>凭远教育 APP-ARK</div>
        <div class="report-type">Comprehensive Assessment Report</div>
      </div>

      <div class="title-block">
        <div class="ch">综合<em>测评</em>报告</div>
        <div class="en">Student Comprehensive Profile</div>
      </div>

      <div class="accent-bar"></div>
      <div class="summary">
        本报告整合四份原始测评数据——核心素养、核心学习能力、核心认知能力与成长型思维、
        职业发展——对学生的各项能力指标进行归纳与可视化呈现，
        便于快速把握整体画像与重点发展方向。
      </div>

      <div class="student-grid">
        <div class="cell"><div class="k">Name</div><div class="v">{name}</div></div>
        <div class="cell"><div class="k">Grade</div><div class="v">{grade}</div></div>
        <div class="cell"><div class="k">School</div><div class="v">{school}</div></div>
        <div class="cell"><div class="k">Date</div><div class="v">{test_date}</div></div>
      </div>

      <div class="toc-title">报告目录 · Sections</div>
      <div class="toc-list">
        <div class="row">
          <div class="num">01</div>
          <div>
            <div class="t">核心素养 · Core Literacy</div>
            <div class="s">情绪稳定性 · 依恋关系 · 大五人格 · 体质健康</div>
          </div>
        </div>
        <div class="row">
          <div class="num">02</div>
          <div>
            <div class="t">核心学习能力 · Core Learning Ability</div>
            <div class="s">认知资源 · 执行功能 · 学习动机 · 学习方法与策略</div>
          </div>
        </div>
        <div class="row">
          <div class="num">03</div>
          <div>
            <div class="t">核心认知 &amp; 成长型思维 · Cognitive &amp; Mindset</div>
            <div class="s">总览 · 六项认知子指标</div>
          </div>
        </div>
        <div class="row">
          <div class="num">04</div>
          <div>
            <div class="t">职业发展 · Career Development</div>
            <div class="s">Holland 职业兴趣 · 多元智能优势 · 职业价值观</div>
          </div>
        </div>
      </div>
    </section>'''

    body = (
        cover_html + "\n"
        + section_01_core_literacy() + "\n"
        + section_02_learning() + "\n"
        + section_03_cognitive_mindset() + "\n"
        + section_04_career()
    )

    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>综合测评报告 - {name}</title>\n"
        f"<style>{CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f"{body}\n"
        "</body>\n"
        "</html>\n"
    )


# ========================================================================
# 主流程
# ========================================================================
def main() -> int:
    html = build_html()
    html_path = OUTPUT_DIR / "report.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"✅ HTML 报告: {html_path}")

    pdf_path = OUTPUT_DIR / "综合评估报告.pdf"
    import os as _os
    import subprocess as _sp

    # ---- 方案 1：Chrome headless（首选，中文字体嵌入最可靠）----
    CHROME_CANDIDATES = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    chrome = next((c for c in CHROME_CANDIDATES if _os.path.exists(c)), None)
    if chrome:
        try:
            cmd = [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                f"--print-to-pdf={pdf_path}",
                "--no-pdf-header-footer",
                f"file://{html_path.resolve()}",
            ]
            print(f"[1/2] 用 Chrome headless 生成 PDF ...")
            r = _sp.run(cmd, capture_output=True, text=True, timeout=120)
            if pdf_path.exists() and pdf_path.stat().st_size > 10_000:
                size_kb = pdf_path.stat().st_size / 1024
                print(f"✅ PDF 报告 (Chrome): {pdf_path}  ({size_kb:.0f} KB)")
            else:
                raise RuntimeError(f"Chrome 未产出有效 PDF (stderr={r.stderr[:200]})")
        except Exception as e:
            print(f"⚠️  Chrome 失败，回退到 WeasyPrint: {e}")
            chrome = None

    # ---- 方案 2：WeasyPrint（回退，可能中文字体需依赖系统字体）----
    if not chrome:
        try:
            _os.environ.setdefault("DYLD_LIBRARY_PATH", "/opt/homebrew/lib")
            from weasyprint import HTML
            HTML(filename=str(html_path)).write_pdf(str(pdf_path))
            size_kb = pdf_path.stat().st_size / 1024
            print(f"✅ PDF 报告 (WeasyPrint): {pdf_path}  ({size_kb:.0f} KB)")
        except Exception as e:
            print(f"⚠️  WeasyPrint 失败: {e}")
            try:
                result = _sp.run(
                    [
                        "/Users/jefflau/anaconda3/bin/python3",
                        "-c",
                        "import os, sys; "
                        "os.environ['DYLD_LIBRARY_PATH']='/opt/homebrew/lib'; "
                        f"from weasyprint import HTML; "
                        f"HTML(filename='{html_path}').write_pdf('{pdf_path}'); "
                        "print('ok')",
                    ],
                    capture_output=True,
                    timeout=180,
                )
                if result.returncode == 0 and pdf_path.exists():
                    size_kb = pdf_path.stat().st_size / 1024
                    print(f"✅ PDF 报告 (WeasyPrint 子进程): {pdf_path}  ({size_kb:.0f} KB)")
                else:
                    stderr = result.stderr.decode("utf-8", errors="ignore")[:500]
                    print(f"⚠️  WeasyPrint 子进程失败: {stderr}")
            except Exception as e2:
                print(f"⚠️  PDF 生成全部失败: {e2}")
                print("   浏览器打开 HTML 即可查看报告。")

    # 数据概览
    print(f"\n📊 使用数据:")
    print(f"   student = {student}")
    print(f"   metrics = {len(items)} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
