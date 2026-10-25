#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
new_iteration/render_v2.py — Y4 评测报告 v2 (new iteration) 独立渲染脚本

与现有生成流程完全隔离：
  - 读取 ../data/report_data.json 作为样例数据（同生产数据源）
  - 渲染 report_v2.html (Jinja2)
  - 用 Chrome headless 打印为 PDF（与生产 generate.py 相同的渲染方式）
  - 输出 preview/ 页面截图，便于逐页校对设计

用法: python3 render_v2.py
"""

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
DATA_PATH = PROJECT / "data" / "report_data.json"

TEMPLATE_NAME = "report_v2.html"
OUT_HTML = HERE / "report_v2_rendered.html"


def load_data():
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    d = {}
    for item in raw["schema_124"]:
        d[item["code"]] = item["value"]
    return raw["student"], d


def fnum(x):
    """格式化数字: 整数去小数点, 否则保留一位；空值/非数字占位为 -（同 v1 fmt）"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "-"
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:g}"


def to_float(val, default=0.0):
    """把任意值转成 float，失败返回 default（同 generate.py 约定）。"""
    try:
        if val is None or val == "":
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


SLOTS = ("A2", "B3", "B4", "B6")


def code_slot(code):
    """数据项编号 → 来源输入 PDF 槽位。每个输出页只用一个槽位的数据。"""
    try:
        n = int(str(code)[:3])
    except ValueError:
        return ""
    if 9 <= n <= 50:
        return "A2"   # 情绪稳定性 / 人格 / 依恋 / 体质健康
    if 63 <= n <= 71 or 128 <= n <= 133:
        return "B3"   # 执行功能 / 学习动机与策略
    if 72 <= n <= 124:
        return "B6"   # 职业兴趣 / 能力优势 / 职业价值观
    return "B4"       # 认知资源 001-008 / 自我概念 051-058 / 内驱力 059-062, 125-127


def present_slots(raw, d):
    """本次实际上传的输入槽位。优先用 extract 记录的 pdf_titles；
    旧快照没有该字段时，按槽位是否有任一非空值推断（059 可被手填思维模式覆盖，不计入）。"""
    titles = raw.get("pdf_titles")
    if titles:
        return {s for s in titles if s in SLOTS}
    return {code_slot(c) for c, v in d.items()
            if c != "059" and str(v if v is not None else "").strip()} & set(SLOTS)


def build_context(student, d, slots=SLOTS):
    # 缺失的输入 PDF 对应的整页不出（见模版 has.*）；下方兜底只针对已上传 PDF 中
    # 个别字段抽取失败：缺失键按空值处理、数值占位为 -，不让单个空值导致整份 v2 失败。
    d = defaultdict(str, d)
    ctx = {}
    ctx["student"] = student
    ctx["has"] = {s: s in slots for s in SLOTS}

    # ---- Jinja helpers for cover geometry ----
    ctx["cos"] = lambda deg: math.cos(math.radians(deg))
    ctx["sin"] = lambda deg: math.sin(math.radians(deg))

    # ---- P4 情绪稳定性 ----
    em_dims = [
        ("自卑", "Inferiority", "自尊", "Self-Esteem", "011", "ic-down", "ic-star", "#FEF3D8"),
        ("抑郁", "Depression", "愉快", "Pleasure", "012", "ic-cloud", "ic-happy", "#FEF3D8"),
        ("焦虑", "Anxiety", "安详", "Serenity", "013", "ic-dizzy", "ic-calm", "#EFF7E9"),
        ("无力感", "Helplessness", "掌控感", "Controllability", "014", "ic-battlow", "ic-target", "#FDEAE0"),
    ]
    ctx["emotion"] = {
        "total": fnum(d["009"]),
        "level": d["010"],
        "peer": "40",
        "dims": [
            {
                "l_zh": l_zh, "l_en": l_en, "r_zh": r_zh, "r_en": r_en,
                "pct": round(to_float(d[code]) / 15.0 * 100, 1),
                "val_pct": round(min(max(to_float(d[code]) / 15.0 * 100, 8), 92), 1),
                "val": fnum(d[code]),
                "lic": lic, "ric": ric, "ric_bg": ric_bg,
            }
            for (l_zh, l_en, r_zh, r_en, code, lic, ric, ric_bg) in em_dims
        ],
    }

    # ---- P5 自我概念 ----
    sc_items = [
        ("行为表现", "Behavioral Adjustment", "053"),
        ("能力与学校表现", "Intellectual and School Status", "054"),
        ("躯体外貌", "Physical Appearance and Attributes", "055"),
        ("情绪状态", "Freedom from Anxiety", "056"),
        ("合群", "Popularity", "057"),
        ("幸福与满足", "Happiness and Satisfaction", "058"),
    ]
    ctx["self_concept"] = {
        "total": fnum(d["051"]),
        "level": d["052"],
        "band_pct": round(max(5, min(95, to_float(d["051"], 80))), 1),
        "rows": [
            {"zh": zh, "en": en, "val": fnum(d[code]),
             "pct": round(to_float(d[code]) / 10.0 * 100, 1)}
            for (zh, en, code) in sc_items
        ],
    }

    # ---- P6 依恋关系 ----
    type_style = {
        "安全型": {"bg": "#F0F9FD", "border": "#42B6E9", "color": "#42B6E9", "warn": False},
        "回避型": {"bg": "#FAECEC", "border": "#C00000", "color": "#C00000", "warn": True},
        "焦虑型": {"bg": "#ECF9F2", "border": "#00AF50", "color": "#00AF50", "warn": True},
        "焦虑-矛盾型": {"bg": "#ECF9F2", "border": "#00AF50", "color": "#00AF50", "warn": True},
    }
    cards = []
    for who, code in [("母亲", "020"), ("父亲", "021"), ("同伴", "022")]:
        t = d[code]
        st = type_style.get(t, type_style["安全型"])
        cards.append({"who": who, "type": t, **st})

    def lv_text(lv):
        return {"高": "高", "中": "不低", "低": "低"}.get(lv, lv)

    at_dims = []
    for zh, en, maxv, base_s, base_l in [
        ("信任", "Trust", 50, "023", "032"),
        ("沟通", "Communication", 45, "026", "035"),
        ("亲近", "Closeness", 30, "029", "038"),
    ]:
        rows = []
        for i, who in enumerate(["母亲", "父亲", "同伴"]):
            sc_raw = d[str(int(base_s) + i).zfill(3)]
            sc = to_float(sc_raw)
            lv = d[str(int(base_l) + i).zfill(3)]
            rows.append({
                "who": who, "pct": round(sc / maxv * 100, 1),
                "sc": fnum(sc_raw), "max": fnum(maxv),
                "lv": lv, "lv_text": lv_text(lv),
            })
        at_dims.append({"zh": zh, "en": en, "rows": rows})
    ctx["attachment"] = {"cards": cards, "dims": at_dims}

    # ---- P7 内驱力 ----
    drive_dims = [
        ("自主性", "Autonomy", "060", "125"),
        ("胜任感", "Competence", "061", "126"),
        ("归属感", "Relatedness", "062", "127"),
    ]
    ctx["drive"] = {
        "mindset": fnum(d["059"]),
        "mindset_pct": round(to_float(d["059"]), 1),
        "dims": [
            {"zh": zh, "en": en, "val": fnum(d[vc]), "avg": fnum(d[ac]),
             "pct": round(to_float(d[vc]) / 10 * 100, 1),
             "avg_pct": round(to_float(d[ac]) / 10 * 100, 1)}
            for (zh, en, vc, ac) in drive_dims
        ],
    }

    # ---- P8 人格 (雷达图) ----
    pers_items = [
        ("开放性", "Openness", "015"),
        ("宜人性", "Agreeableness", "016"),
        ("责任心", "Conscientiousness", "017"),
        ("外倾性", "Extraversion", "018"),
        ("神经质", "Neuroticism", "019"),
    ]
    cx, cy, R = 200.0, 170.0, 105.0
    # 五轴角度: 开放性在顶部, 顺时针
    angles = [-90, -18, 54, 126, 198]
    vals = [to_float(d[code]) for (_, _, code) in pers_items]

    def pt(angle, r):
        a = math.radians(angle)
        return (cx + r * math.cos(a), cy + r * math.sin(a))

    grid = []
    for k in range(1, 6):
        r = R * k / 5
        grid.append(" ".join(f"{x:.1f},{y:.1f}" for x, y in [pt(a, r) for a in angles]))
    axes = [{"x": f"{pt(a, R)[0]:.1f}", "y": f"{pt(a, R)[1]:.1f}"} for a in angles]
    poly_pts = [pt(a, R * v / 5.0) for a, v in zip(angles, vals)]
    polygon = " ".join(f"{x:.1f},{y:.1f}" for x, y in poly_pts)
    points = [{"x": f"{x:.1f}", "y": f"{y:.1f}"} for x, y in poly_pts]
    # 标签位置: 沿轴外推
    label_pos = []
    for a in angles:
        x, y = pt(a, R + 34)
        anchor = "middle"
        if -80 < a < 80 and a != -90:
            anchor = "start"
        elif 100 < a < 260 and a != -90:
            anchor = "end"
        if a == -90:
            anchor = "middle"
            x, y = pt(a, R + 38)
        label_pos.append({"x": round(x, 1), "y": round(y, 1), "anchor": anchor})
    labels = []
    for (zh, en, code), v, lp in zip(pers_items, vals, label_pos):
        labels.append({"zh": zh, "en": en, "val": fnum(v), **lp})
    ctx["personality"] = {
        "grid": grid, "axes": axes, "polygon": polygon, "points": points,
        "labels": labels,
        "rows": [{"zh": zh, "en": en, "val": fnum(d[code])} for (zh, en, code) in pers_items],
    }

    # ---- P10 体质健康 ----
    level = d["042"]
    shapes = [
        {"zh": "偏瘦", "en": "LOW", "scale": 0.88, "active": level == "偏瘦"},
        {"zh": "正常", "en": "NORMAL", "scale": 1.0, "active": level == "正常"},
        {"zh": "超重", "en": "OVERWEIGHT", "scale": 1.14, "active": level == "超重"},
        {"zh": "肥胖", "en": "OBESITY", "scale": 1.3, "active": level == "肥胖"},
    ]
    habit_color = {"优": "#F8B01E", "良好": "#FBCF6B", "中等": "#9E9E9E", "差": "#D93025"}
    habits = [
        {"zh": "饮食习惯", "en": "Diet", "level": d["046"],
         "color": habit_color.get(d["046"], "#9E9E9E"), "val": None, "unit": ""},
        {"zh": "睡眠习惯", "en": "Sleep", "level": d["048"],
         "color": habit_color.get(d["048"], "#9E9E9E"),
         "val": fnum(d["047"]), "unit": " 小时/天"},
        {"zh": "运动习惯", "en": "Exercise", "level": d["050"],
         "color": habit_color.get(d["050"], "#9E9E9E"),
         "val": fnum(d["049"]), "unit": " 小时/周"},
    ]
    ctx["physical"] = {
        "bmi": fnum(d["041"]), "level": level,
        "height": fnum(d["043"]), "weight": fnum(d["044"]),
        "shapes": shapes, "habits": habits,
    }

    # ---- P12 认知资源 / P13 六项子指标 ----
    pct_val = to_float(d["002"])
    ctx["cognition"] = {
        "total": fnum(d["001"]),
        "percentile": fnum(d["002"]),
        "marker_pct": round(min(max(pct_val, 6), 92), 1),
        "subs": [
            {"zh": "感知觉", "en": "Perception", "val": fnum(d["003"]),
             "desc": "感知是认知、理解的基础。感知觉是大脑对作用于大脑的外部信息的整体看法和理解，整个加工过程包括获取信息、理解信息、选择信息和组织信息。"},
            {"zh": "注意力", "en": "Attention", "val": fnum(d["004"]),
             "desc": "心理活动对一定对象的指向和集中。一般理解为对客观事物持续注意的能力，如做事专注，还是易分心。神经生理因素、兴趣/动机、精神状态等均会影响一个人的注意力水平。"},
            {"zh": "记忆力", "en": "Memory", "val": fnum(d["005"]),
             "desc": "记忆力是神经系统存储过往经验的能力，是学习的基础，一般包括识记、保持、再认和重现。记忆力的个体差异影响学习效率，如有的同学看3遍就记住了一个单词，而有的同学可能要7-8遍。"},
            {"zh": "推理能力", "en": "Reasoning", "val": fnum(d["006"]),
             "desc": "推理能力是智力的核心成分，是一个人通过已有知识和经验，通过综合分析做出新判断的过程。推理能力的差异往往反应一个人洞悉事物本质，事物联系能力的高低。"},
            {"zh": "空间能力", "en": "Spatial Ability", "val": fnum(d["007"]),
             "desc": "空间能力是大脑通过观察、触摸及想象对物体形状、位置判断的能力。它是大脑对外部信息的抽象表征和推理，是数学、自然科学、工程等重要学科领域用到的重要心理能力。"},
            {"zh": "加工速度", "en": "Processing Speed", "val": fnum(d["008"]),
             "desc": "加工速度是大脑处理内部或外部信息的速度，和网速、手机使用流畅性一样，大脑的信息加工速度直接影响学习、思考和人际沟通的效率。"},
        ],
    }

    # ---- P14 执行功能 ----
    ctx["exec"] = {"list": [
        {"zh": "抑制控制", "en": "Inhibitory Control", "val": fnum(d["063"]),
         "desc": "抑制控制是指个体在行动之前控制冲动、理性思考、排除干扰完成任务的能力。即抑制住自己的本能、欲望，使自己做出符合预期目标的行为。它和孩子的专注力、情绪调节和冲动控制等有关。"},
        {"zh": "工作记忆", "en": "Working Memory", "val": fnum(d["064"]),
         "desc": "工作记忆是有意识地在头脑中保存和操纵信息的能力。我们依靠记忆信息预测未来，信息是周全还是片面直接影响预测的准确性。我们依靠记忆制定目标、安排计划、执行任务，而目标是否清晰，计划是否详细，执行是否到位均与记忆力有关。"},
        {"zh": "认知灵活性", "en": "Cognitive Flexibility", "val": fnum(d["065"]),
         "desc": "认知灵活性是指个体大脑适应新的、变化的或计划以外事件的能力。比如当情况有变，原计划被打破或最初的方案行不通时，认知灵活性高的人能根据变化从不同角度看问题，及时调整心态，改变思路，快速找到解决问题的新方案。认知灵活性影响孩子的自我调节能力和心理韧性。"},
    ]}

    # ---- P15 学习动机与策略 ----
    ctx["motivation"] = {"groups": [
        {"zh": "学习动机", "en": "Learning Motivation", "rows": [
            {"zh": "深层动机", "en": "Deep Motivation",
             "val": fnum(d["066"]), "avg": fnum(d["128"]),
             "pct": round(to_float(d["066"]) / 10 * 100, 1),
             "avg_pct": round(to_float(d["128"]) / 10 * 100, 1),
             "desc": "深层动机是对学习本身感兴趣，学习本身使个体感到满足和兴奋的内部动机。深层动机得分高的个体一般学习动力足，主动学习、不需要外部监督和督促。"},
            {"zh": "表面动机", "en": "Surface Motivation",
             "val": fnum(d["067"]), "avg": fnum(d["129"]),
             "pct": round(to_float(d["067"]) / 10 * 100, 1),
             "avg_pct": round(to_float(d["129"]) / 10 * 100, 1),
             "desc": "表面动机是对学习不感兴趣，为了通过考试、得到奖励或避免惩罚而学习的外部动机。表面动机难以维持长期学习，一旦外部奖励或惩罚退去，个体可能不再学习。"},
            {"zh": "自我效能感", "en": "Self-Efficacy",
             "val": fnum(d["068"]), "avg": fnum(d["130"]),
             "pct": round(to_float(d["068"]) / 10 * 100, 1),
             "avg_pct": round(to_float(d["130"]) / 10 * 100, 1),
             "desc": "自我效能感是个体对自己能否成功完成某事的主观判断。个体的自我效能感源于过往的成功经验以及对自己的准确的评估。"},
        ]},
        {"zh": "学习方法与策略", "en": "Learning Methods", "rows": [
            {"zh": "学习深层方法与策略", "en": "Deep Methods and Strategies",
             "val": fnum(d["069"]), "avg": fnum(d["131"]),
             "pct": round(to_float(d["069"]) / 10 * 100, 1),
             "avg_pct": round(to_float(d["131"]) / 10 * 100, 1),
             "desc": "学习深层方法与策略是为了深入理解知识本身而采取的学习方法和策略，是一种建立在理解和应用基础之上的深度学习。这种学习方法使学习记忆更牢、理解更深刻。"},
            {"zh": "学习表面方法与策略", "en": "Surface Methods and Strategies",
             "val": fnum(d["070"]), "avg": fnum(d["132"]),
             "pct": round(to_float(d["070"]) / 10 * 100, 1),
             "avg_pct": round(to_float(d["132"]) / 10 * 100, 1),
             "desc": "学习表面方法与策略是为了记住某具体内容或为了某次考试通过而学习的方法与策略，这种方法策略可以在短期内看到效果，对长期发展非常不利。因为这种不求甚解的学习方法记得快，忘得也快。"},
            {"zh": "学习自我调节", "en": "Self-Regulation",
             "val": fnum(d["071"]), "avg": fnum(d["133"]),
             "pct": round(to_float(d["071"]) / 10 * 100, 1),
             "avg_pct": round(to_float(d["133"]) / 10 * 100, 1),
             "desc": "学习自我调节是学习过程中遇到困难或挫折时采取的自我调节的方法。比如即使遇到了自己不喜欢的老师或科目，但为了取得好成绩也会进行自我调节、努力学习。"},
        ]},
    ]}

    # ---- P17 职业兴趣 ----
    code = d["072"]
    holland_items = [
        {"letter": "R", "zh": "现实型", "en": "Realistic", "val": fnum(d["073"]),
         "desc": "喜欢具体的、可操作性的工作，比如修理、组装或建造东西；喜欢动手操作、操作设备、工具或机器；偏好具体任务，而不是抽象思考，或与人讨论；不善言辞，更喜欢独立工作。"},
        {"letter": "I", "zh": "研究型", "en": "Investigative", "val": fnum(d["074"]),
         "desc": "喜欢研究抽象问题，善于逻辑分析，喜欢探索未知；喜欢观察、学习、思考、调查和实验研究；善于提出问题和解决问题；个性独立，为人谨慎。"},
        {"letter": "A", "zh": "艺术型", "en": "Artistic", "val": fnum(d["075"]),
         "desc": "文艺青年；用文字、艺术、音乐或戏剧来交流、表演或表达自己，创造和设计事物；想象力丰富，喜欢创造与表达；喜欢无拘无束的自由生活，喜欢新鲜刺激的生活，讨厌一成不变的生活。"},
        {"letter": "S", "zh": "社会型", "en": "Social", "val": fnum(d["076"]),
         "desc": "温暖、和善；乐于帮助他人；关心社会问题，喜欢与人一起帮助和服务他人；关心他人的幸福和福利。"},
        {"letter": "E", "zh": "事业型", "en": "Enterprising", "val": fnum(d["077"]),
         "desc": "追求权利、利益；喜欢竞争，有野心和抱负；喜欢影响他人、领导他人完成目标；精力充沛，掌控大局。"},
        {"letter": "C", "zh": "常规型", "en": "Conventional", "val": fnum(d["078"]),
         "desc": "遵循规章制度办事；喜欢重复的事务性工作，不喜欢变动；个性谨慎，工作认真，注重细节；喜欢配合和服从，不喜欢领导他人。"},
    ]
    top_letters = set(code[:3])
    for it in holland_items:
        it["top"] = it["letter"] in top_letters
    ctx["holland"] = {"code": code, "rows": holland_items}

    # ---- P18 能力优势 ----
    # 以固定 8 项（079-086）为准、按分数从高到低排序，与 v1 口径一致。
    # 不再依赖 087-094 排序字段：该字段由文本抽取生成，偶发抽错（如把
    # “空间能力”抽成“事业型”）或为空，直接查表会 KeyError 导致整份 v2 失败。
    mi_defs = [
        ("语言能力", "079", "Linguistic"),
        ("逻辑数学能力", "080", "Logical-Mathematical"),
        ("音乐能力", "081", "Musical"),
        ("空间能力", "082", "Spatial"),
        ("身体运动能力", "083", "Bodily-Kinesthetic"),
        ("人际关系能力", "084", "Interpersonal"),
        ("内省能力", "085", "Intrapersonal"),
        ("自然能力", "086", "Naturalist"),
    ]
    ranked = []
    for zh, code, en in mi_defs:
        try:
            num = float(d.get(code))
        except (TypeError, ValueError):
            num = 5.0
        ranked.append({"zh": zh, "en": en, "val": fnum(num),
                       "pct": round(num / 10 * 100, 1)})
    ranked.sort(key=lambda x: float(x["val"]), reverse=True)
    for i, it in enumerate(ranked):
        it["top"] = i < 3
    ctx["intelligences"] = ranked

    # ---- P19 职业价值观 ----
    val_map = {
        "上司关系": ("Supervisor Relations", "有一个开明的、民主的、公正的好领导", "有一个好领导"),
        "成就感": ("Achievement", "不断取得新的成就，得到认可或实现自己想做的事", "能给我带来成就感"),
        "生活方式": ("Lifestyle", "可以选择过自己想过的生活，安逸、简单、快乐或充实", "有选择生活方式的权利"),
        "同事关系": ("Colleague Relations", "一起工作的大多数同事，人品较好，相处愉快", "与喜欢的人共事"),
        "安全稳定": ("Security", "工作稳定，收入有保障，不会失业", "安稳，不会失业"),
        "工作环境": ("Work Environment", "追求比较舒适、轻松、自由的工作环境", "工作环境舒适，轻松自由"),
        "声望地位": ("Social Status", "所从事的工作在人们的心目中有较高的社会地位", "社会地位高，受人敬仰"),
        "经济报酬": ("Economic Reward", "较高的报酬，生活过得较为富足", "薪酬高，福利好"),
        "美的追求": ("Aesthetic Pursuit", "不断地追求美的东西，得到美的享受", "能体验和感受美"),
        "独立自主": ("Independence", "可以按自己的方式或想法工作，不受他人的影响", "能按自己想法和节奏做事"),
        "管理权力": ("Management Power", "管理和指挥他人做事", "影响和领导别人一起"),
        "创造发明": ("Creativity", "发明创造新的事物，可能是新产品，也可能是新观念或新方法", "发明创造新的事物"),
        "利他助人": ("Altruism", "为他人的幸福、利益尽一份力", "能帮助到他人"),
        "多样变化": ("Variety", "讨厌简单重复的工作，喜欢有挑战、丰富多彩的工作", "尝试不同的工作"),
        "智力激发": ("Intellectual Stimulation", "必须动脑筋思考、学习和探索新事物，解决新问题", "有挑战性"),
    }
    vlist = []
    for i in range(1, 16):
        name = d[str(109 + i).zfill(3)]  # 110..124
        if name not in val_map:  # 未抽到/抽错的排序项跳过，不让整份 v2 失败
            continue
        en, desc, quote = val_map[name]
        vlist.append({"zh": name, "en": en, "desc": desc, "quote": quote,
                      "top": i <= 5})
    ctx["values"] = vlist

    return ctx


def find_chrome():
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    raise RuntimeError("未找到 Chrome/Chromium")


def render_html_to(data_path, out_html):
    """读数据 → build_context → Jinja 渲染 → 写出 HTML。供 generate.py 管线复用。

    模版以相对路径引用 branding/，因此输出 HTML 同目录下必须存在所需资源。
    管线中 out_html 位于 output/，v1 的 render_html 会把 branding/ 拷到那里，
    但那份是 v1 品牌资源（不含 v2 封面用的 logo_crest_white.png）。这里补一份
    缺失的资源，保证 v2 封面等用图在任何环境下都能正确渲染。
    """
    out = Path(out_html)
    branding_dst = out.parent / "branding"
    branding_dst.mkdir(parents=True, exist_ok=True)
    for asset in (HERE / "branding").iterdir():
        target = branding_dst / asset.name
        if asset.is_file() and not target.exists():
            shutil.copy2(str(asset), str(target))

    raw = json.loads(Path(data_path).read_text(encoding="utf-8"))
    d = {}
    for item in raw["schema_124"]:
        d[item["code"]] = item["value"]
    ctx = build_context(raw["student"], d, present_slots(raw, d))

    env = Environment(
        loader=FileSystemLoader(str(HERE)),
        autoescape=select_autoescape(default=True, default_for_string=True),
    )
    template = env.get_template(TEMPLATE_NAME)
    html = template.render(**ctx)
    out.write_text(html, encoding="utf-8")
    return html


def main():
    student, d = load_data()
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    ctx = build_context(student, d, present_slots(raw, d))

    env = Environment(
        loader=FileSystemLoader(str(HERE)),
        autoescape=select_autoescape(default=True, default_for_string=True),
    )
    template = env.get_template(TEMPLATE_NAME)
    html = template.render(**ctx)
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"[1/3] HTML 渲染完成 -> {OUT_HTML.name} ({len(html)} chars)")

    safe_name = student["name"].replace("/", "_").replace(" ", "")
    pdf_path = HERE / f"凭远Y4评测报告_v2_{safe_name}.pdf"

    chrome = find_chrome()
    args = [
        chrome, "--headless=new", "--disable-gpu",
        f"--print-to-pdf={pdf_path}",
        "--no-pdf-header-footer",
        f"file://{OUT_HTML}",
    ]
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if not pdf_path.exists():
        raise RuntimeError(f"Chrome PDF 生成失败: {result.stderr[:500]}")
    print(f"[2/3] PDF 生成完成 -> {pdf_path.name} ({pdf_path.stat().st_size/1024:.0f} KB)")

    # 预览图
    import pymupdf
    preview = HERE / "preview"
    preview.mkdir(exist_ok=True)
    doc = pymupdf.open(str(pdf_path))
    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=100)
        pix.save(str(preview / f"page_{i+1:02d}.png"))
    print(f"[3/3] 预览图 -> preview/ ({len(doc)} 页)")


if __name__ == "__main__":
    main()
