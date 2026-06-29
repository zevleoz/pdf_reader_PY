"""高精度 PDF 数据提取 - 基于验证后的真实页面文本"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz

INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
DATA_DIR = Path("data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

ALL_ITEMS: List[Dict[str, Any]] = []


def get_pdf_pages(pdf_path: Path) -> List[Tuple[int, str]]:
    """返回 [(page_number, text), ...] 只含非空文本的页面"""
    doc = fitz.open(str(pdf_path))
    result = []
    for i, page in enumerate(doc):
        text = page.get_text()
        if text.strip():
            result.append((i + 1, text))
    doc.close()
    return result


def parse_student_info(texts: List[Tuple[int, str]]) -> Dict[str, str]:
    """提取学生基本信息"""
    info = {}
    for _, text in texts:
        for key, pattern in [
            ("name", r"姓\s*名[：:]\s*([A-Za-z\u4e00-\u9fff]+)"),
            ("grade", r"年\s*级[：:]\s*([^\n]+)"),
            ("test_date", r"测试时间[：:]\s*(\d{4}-\d{2}-\d{2})"),
            ("birth_date", r"出生日期[：:]\s*(\d{4}-\d{2}-\d{1,2})"),
            ("school", r"学\s*校[：:]\s*([^\n]+)"),
        ]:
            if key not in info:
                m = re.search(pattern, text)
                if m:
                    info[key] = m.group(1).strip()
    return info


def add_item(
    source_pdf: str,
    category: str,
    label: str,
    value: Any,
    unit: Optional[str] = None,
    mean: Optional[Any] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    item: Dict[str, Any] = {
        "source_pdf": source_pdf,
        "category": category,
        "label": label,
        "value": value,
    }
    if unit:
        item["unit"] = unit
    if mean is not None:
        item["mean"] = mean
    if extra:
        item.update(extra)
    ALL_ITEMS.append(item)
    print("  [{}] {} / {} = {}{}{}".format(
        source_pdf, category, label, value,
        unit if unit else "",
        " (同龄人 {}{})".format(mean, unit if unit else "") if mean is not None else "",
    ))


# ============================================================
# A2 核心素养: 认知能力 (page 3)
# ============================================================
def parse_a2_cognitive(source_pdf: str, texts: List[Tuple[int, str]]) -> None:
    """
    认知能力 - 每页提取标签+下一行的 X% 数值
    模式: "感知觉" → 下一行 "92%"
    """
    labels = ["感知觉", "记忆力", "注意力"]
    found = {}

    for page_num, text in texts:
        lines = [l.strip() for l in text.split("\n")]
        for i, line in enumerate(lines):
            for lbl in labels:
                if lbl == line and i + 1 < len(lines):
                    m = re.match(r"^(\d+(?:\.\d+)?)\s*%$", lines[i + 1])
                    if m and lbl not in found:
                        found[lbl] = True
                        add_item(source_pdf, "认知能力", lbl, int(m.group(1)), "%")


# ============================================================
# A2 核心素养: 情绪稳定性 (page 5)
# ============================================================
def parse_a2_emotional(source_pdf: str, texts: List[Tuple[int, str]]) -> None:
    """
    情绪稳定性 - 从长句中提取总分和同龄人平均分
    模式: "X个分测验中的总得分是Y分，...同龄人...平均分是Z分"
    """
    for _, text in texts:
        if "情绪稳定性" not in text:
            continue
        m = re.search(
            r"(\d+)\s*个分测验中的总得分是\s*(\d+(?:\.\d+)?)\s*分[^\n]*同龄人[^\d]*(\d+(?:\.\d+)?)\s*分",
            text,
        )
        if m:
            add_item(
                source_pdf, "情绪稳定性",
                "情绪稳定性总分", float(m.group(2)), "分", float(m.group(3)),
            )
            # 标记：子项（自卑、抑郁、焦虑、依赖）的具体分数只在图表中，文本不可提取


# ============================================================
# A2 核心素养: 大五人格 (page 7)
# ============================================================
def parse_a2_personality(source_pdf: str, texts: List[Tuple[int, str]]) -> None:
    """
    大五人格 - 从单个长句中提取 5 个标签的得分和平均分
    模式: "您在'开放性'上的得分是 3.3 分，同龄人的平均分是3分；..."
    """
    for _, text in texts:
        if "大五人格" not in text and "人格测评报告" not in text:
            continue
        # 匹配引号变体: 英文引号 "..." 或中文引号 ""..."" 或 ''...''
        # 实际 PDF 中格式为: "您在"开放性"上的得分是 3.3 分，同龄人的平均分是3分"
        pattern = (
            r"[\"\u201c\u201d\u2018\u2019]"              # 左引号
            r"([\u4e00-\u9fff]{2,4})"                      # 标签
            r"[\"\u201c\u201d\u2018\u2019]"              # 右引号
            r"(?:上|的)"                                   # "上"或"的"
            r"的得分是\s*(\d+(?:\.\d+)?)\s*分"             # 得分
            r"[^\d]*?同龄人[^\d]*?(\d+(?:\.\d+)?)\s*分"   # 同龄人平均分
        )
        for m in re.finditer(pattern, text):
            add_item(
                source_pdf, "大五人格",
                m.group(1), float(m.group(2)), "分", float(m.group(3)),
            )


# ============================================================
# A2 核心素养: 依恋关系 (page 9)
# ============================================================
def parse_a2_attachment(source_pdf: str, texts: List[Tuple[int, str]]) -> None:
    """
    依恋关系 - 从长句中提取 信任/沟通/亲近 的三类得分
    模式: "母亲、父亲和同伴在信任方面的得分分别是47分、32分、22分"
    """
    persons = ["母亲", "父亲", "同伴"]

    for _, text in texts:
        if "依恋" not in text:
            continue
        # trust 信任: "信任方面的得分分别是47分、32分、22分"
        # communication 沟通: "沟通上的得分分别是41分、29分、19分"
        # closeness 亲近: "亲近上的得分分别是19分、12分、14分"
        for dim, dim_label in [("信任", "信任-依恋"), ("沟通", "沟通-依恋"), ("亲近", "亲近-依恋")]:
            # 变体: "信任方面的得分分别是" 或 "信任上的得分分别是"
            m = re.search(
                r"{}[方面上的]*\s*得分分别是\s*(\d+)\s*分[、,，]\s*(\d+)\s*分[、,，]\s*(\d+)\s*分".format(dim),
                text,
            )
            if m:
                for j, p in enumerate(persons):
                    add_item(
                        source_pdf, "依恋关系",
                        "{}-{}".format(dim, p), int(m.group(j + 1)), "分",
                    )


# ============================================================
# A2 核心素养: 体质健康 (page 11)
# ============================================================
def parse_a2_physical(source_pdf: str, texts: List[Tuple[int, str]]) -> None:
    """
    体质健康 - 提取睡眠时长、运动时长、饮食习惯评价
    """
    for page_num, text in texts:
        if "体质健康" not in text:
            continue
        # 睡眠 "7.1小时/每天"
        m = re.search(r"(\d+(?:\.\d+)?)\s*小时\s*/\s*每天", text)
        if m:
            add_item(source_pdf, "体质健康", "每日睡眠时长", float(m.group(1)), "小时/天")
        # 运动 "X小时/每周"
        m = re.search(r"(\d+(?:\.\d+)?)\s*小时\s*/\s*每周", text)
        if m:
            add_item(source_pdf, "体质健康", "每周运动时长", float(m.group(1)), "小时/周")
        # 饮食习惯评价 ("优"/"中等" 等)
        m = re.search(r"饮食习惯[^\n]*均衡饮食[^\n]*([优良中差高]|优秀|良好|中等|较差)", text)
        if m:
            add_item(source_pdf, "体质健康", "饮食习惯评级", m.group(1))


# ============================================================
# B3 核心学习能力: 执行功能 (page 3)
# ============================================================
def parse_b3_executive(source_pdf: str, texts: List[Tuple[int, str]]) -> None:
    """
    执行功能 - 标签 + 下一行 X% 数值
    模式: "抑制控制" → 下一行 "50%"
    """
    labels = ["抑制控制", "工作记忆", "认知灵活性"]
    for page_num, text in texts:
        if "执行功能" not in text and "EXECUTIVE FUNCTIONS" not in text:
            continue
        lines = [l.strip() for l in text.split("\n")]
        for i, line in enumerate(lines):
            for lbl in labels:
                if lbl == line and i + 1 < len(lines):
                    m = re.match(r"^(\d+(?:\.\d+)?)\s*%$", lines[i + 1])
                    if m:
                        # 检查是否已经提取
                        key = "执行功能-" + lbl
                        already = any(it["label"] == lbl and it["category"] == "执行功能" for it in ALL_ITEMS)
                        if not already:
                            add_item(source_pdf, "执行功能", lbl, int(m.group(1)), "%")


# ============================================================
# B3: 学习动机 (page 9)
# ============================================================
def parse_b3_motivation(source_pdf: str, texts: List[Tuple[int, str]]) -> None:
    """
    学习动机 - "标签 X.Y分" + "我的得分：X.Y分 平均得分：Y.Z分"
    模式 1: "深层动机 4.8分"
    模式 2: "我的得分：4.8分 平均得分：7.4分"
    """
    labels = ["深层动机", "表面动机", "自我效能感"]
    label_to_key = {
        "深层动机": "学习动机-深层动机",
        "表面动机": "学习动机-表面动机",
        "自我效能感": "学习动机-自我效能感",
    }

    for page_num, text in texts:
        if "学习动机" not in text:
            continue
        lines = [l.strip() for l in text.split("\n")]

        # 模式 1: "深层动机" + 下一行 "4.8分"
        # 模式 2: "深层动机 4.8分" 同一行
        for i, line in enumerate(lines):
            for lbl in labels:
                key = label_to_key[lbl]
                if lbl in line:
                    # 同行 "深层动机 4.8分"
                    m = re.search(r"{}[^\d]*(\d+(?:\.\d+)?)\s*分".format(lbl), line)
                    if m and not any(it["label"] == lbl and it["category"] == "学习动机" for it in ALL_ITEMS):
                        add_item(source_pdf, "学习动机", lbl, float(m.group(1)), "分")
                    # 下一行模式
                    if i + 1 < len(lines):
                        m2 = re.search(r"(\d+(?:\.\d+)?)\s*分", lines[i + 1])
                        if m2:
                            pass  # 已由同行模式处理

        # 模式 3: "我的得分：X.Y分 平均得分：Y.Z分" - 从文本中找到所有这样的配对
        # 标签在 "我的得分" 上一行
        my_score_lines = [i for i, l in enumerate(lines) if "我的得分" in l]
        for idx in my_score_lines:
            my_match = re.search(r"我的得分[：:]\s*(\d+(?:\.\d+)?)\s*分", lines[idx])
            avg_match = re.search(r"平均得分[：:]\s*(\d+(?:\.\d+)?)\s*分", lines[idx])
            # 标签可能在 idx-2 行
            label = None
            for back in range(1, 6):
                if idx - back >= 0:
                    cand = lines[idx - back]
                    if cand in labels:
                        label = cand
                        break
                    elif any(l in cand for l in labels):
                        for l in labels:
                            if l in cand:
                                label = l
                                break
                        if label:
                            break
            if my_match and label:
                # 检查是否已存在这个标签（值相同跳过，不同则更新 mean）
                existing = [
                    it for it in ALL_ITEMS
                    if it["label"] == label and it["category"] == "学习动机"
                ]
                if existing:
                    if avg_match and "mean" not in existing[0]:
                        existing[0]["mean"] = float(avg_match.group(1))
                        print("  [update] {} / {} mean = {}".format(source_pdf, label, avg_match.group(1)))
                else:
                    mean_val = float(avg_match.group(1)) if avg_match else None
                    add_item(source_pdf, "学习动机", label, float(my_match.group(1)), "分", mean_val)


# ============================================================
# B3: 学习方法与策略 (page 11)
# ============================================================
def parse_b3_methods(source_pdf: str, texts: List[Tuple[int, str]]) -> None:
    """
    学习方法与策略 - 类似学习动机的模式
    标签: "学习深层方法与策略", "学习表面方法与策略", "学习自我调节"
    """
    labels_map = {
        "学习深层方法与策略": "学习方法-深层",
        "学习表面方法与策略": "学习方法-表面",
        "学习自我调节": "学习方法-自我调节",
    }
    labels = list(labels_map.keys())

    for page_num, text in texts:
        if "学习方法与策略" not in text:
            continue
        lines = [l.strip() for l in text.split("\n")]

        for i, line in enumerate(lines):
            for lbl in labels:
                if lbl in line:
                    m = re.search(r"(\d+(?:\.\d+)?)\s*分", line)
                    if not m and i + 1 < len(lines):
                        m = re.search(r"(\d+(?:\.\d+)?)\s*分", lines[i + 1])
                    if m:
                        # 检查是否已经存在
                        already = any(
                            it["label"] == lbl and it["category"] == "学习方法与策略"
                            for it in ALL_ITEMS
                        )
                        if not already:
                            add_item(source_pdf, "学习方法与策略", lbl, float(m.group(1)), "分")

        # 提取 my_score / avg_score 模式（如果有）
        my_score_lines = [i for i, l in enumerate(lines) if "我的得分" in l and "学习方法" in " ".join(lines[max(0, i-5):i+1])]
        for idx in my_score_lines:
            my_match = re.search(r"我的得分[：:]\s*(\d+(?:\.\d+)?)\s*分", lines[idx])
            avg_match = re.search(r"平均得分[：:]\s*(\d+(?:\.\d+)?)\s*分", lines[idx])
            if my_match:
                # 找到对应的标签
                for lbl in labels:
                    if lbl in " ".join(lines[max(0, idx-10):idx+1]):
                        existing = [
                            it for it in ALL_ITEMS
                            if it["label"] == lbl and it["category"] == "学习方法与策略"
                        ]
                        if existing and avg_match and "mean" not in existing[0]:
                            existing[0]["mean"] = float(avg_match.group(1))
                            print("  [update] {} / {} mean = {}".format(source_pdf, lbl, avg_match.group(1)))
                        break


# ============================================================
# B4 核心认知能力: page 3 (总得分/百分位)
# ============================================================
def parse_b4_overall(source_pdf: str, texts: List[Tuple[int, str]]) -> None:
    """
    B4 - 认知能力总览 (page 3): "115 总得分" 和 "84 百分位"
    格式:
      115
      总得分
      Total Score
      84
      百分位（%）
      Percentile
    """
    for page_num, text in texts:
        if "认知能力" not in text:
            continue
        lines = [l.strip() for l in text.split("\n")]
        for i, line in enumerate(lines):
            # 找 "总得分" 行 → 上一行是数字
            if line == "总得分" and i > 0:
                m = re.match(r"^(\d+)$", lines[i - 1])
                if m and not any(it["label"] == "认知能力总得分" for it in ALL_ITEMS):
                    add_item(source_pdf, "认知能力", "认知能力总得分", int(m.group(1)), "分")
            if "百分位" in line and i > 0:
                m = re.match(r"^(\d+(?:\.\d+)?)$", lines[i - 1])
                if m and not any(it["label"] == "认知能力百分位" for it in ALL_ITEMS):
                    add_item(source_pdf, "认知能力", "认知能力百分位", int(m.group(1)), "%")


# ============================================================
# B4: 认知能力六项子指标 (page 4)
# ============================================================
def parse_b4_cognitive_subitems(source_pdf: str, texts: List[Tuple[int, str]]) -> None:
    """
    B4 - page 4: 六项子指标（感知觉、注意力、记忆力、推理能力、空间能力、信息加工速度）
    格式: "空间能力 | Spatial Ability" 等，后面某行 "百分位（%） 92"
    """
    labels = ["感知觉", "注意力", "记忆力", "推理能力", "空间能力", "信息加工速度"]

    for page_num, text in texts:
        if "认知能力模型" not in text and "DAN测评" not in text:
            continue
        lines = [l.strip() for l in text.split("\n")]

        # 在本页中找到所有 "百分位（%）"，取其下一行数字
        for i, line in enumerate(lines):
            if "百分位（%）" in line:
                # 下一行可能是数字 (92, 66, 72, 83, 52, 86)
                for j in range(i + 1, min(i + 5, len(lines))):
                    m = re.match(r"^(\d+(?:\.\d+)?)$", lines[j])
                    if m:
                        # 找到这个百分位数字之前最近的标签
                        nearest_label = None
                        for k in range(i - 1, max(0, i - 15), -1):
                            for lbl in labels:
                                if lbl in lines[k]:
                                    nearest_label = lbl
                                    break
                            if nearest_label:
                                break
                        if nearest_label:
                            already = any(
                                it["label"] == nearest_label and it["category"] == "认知能力-子指标"
                                for it in ALL_ITEMS
                            )
                            if not already:
                                add_item(source_pdf, "认知能力-子指标", nearest_label, int(m.group(1)), "%")
                        break


# ============================================================
# B4: 成长型思维 (page 8-10)
# ============================================================
def parse_b4_mindset(source_pdf: str, texts: List[Tuple[int, str]]) -> None:
    """
    B4 - 成长型思维: 从 "成长型思维测评报告" 相关页面提取
    """
    for page_num, text in texts:
        if "成长型思维" not in text and "Growth Mindset" not in text and "MINDSET" not in text:
            continue
        lines = [l.strip() for l in text.split("\n")]

        # 类似认知能力，找 "X" 标签行 + 下一行 "Y%"
        for i, line in enumerate(lines):
            # 直接找 "Y%" 模式的行，并向前查找中文标签
            m = re.match(r"^(\d+(?:\.\d+)?)\s*%$", line)
            if m and i > 0:
                # 向前找到最近的非空中文标签
                for j in range(i - 1, max(0, i - 10), -1):
                    if lines[j] and re.match(r"^[\u4e00-\u9fff]{2,10}$", lines[j]):
                        lbl = lines[j]
                        already = any(
                            it["label"] == lbl and it["category"] == "成长型思维"
                            for it in ALL_ITEMS
                        )
                        if not already and lbl not in ["我的得分", "大家的平均分", "百分位", "成长建议"]:
                            add_item(source_pdf, "成长型思维", lbl, int(m.group(1)), "%")
                        break

        # "我的得分 X 分 同龄人平均分 Y 分" 模式
        for i, line in enumerate(lines):
            m = re.search(
                r"([\u4e00-\u9fff]{2,6})[^\n]*?我的得分[：:\s]*(\d+(?:\.\d+)?)\s*分[^\d]*?同龄人[^\d]*?(\d+(?:\.\d+)?)\s*分",
                line,
            )
            if m:
                already = any(
                    it["label"] == m.group(1) and it["category"] == "成长型思维"
                    for it in ALL_ITEMS
                )
                if not already:
                    add_item(
                        source_pdf, "成长型思维",
                        m.group(1), float(m.group(2)), "分", float(m.group(3)),
                    )


# ============================================================
# B6: 职业价值观
# ============================================================
def parse_b6_career(source_pdf: str, texts: List[Tuple[int, str]]) -> None:
    """
    B6 - 职业价值观: 从页面中提取 "标签 + 数值" 模式
    """
    for page_num, text in texts:
        if "职业" not in text and "价值观" not in text and "Career" not in text and "VALUE" not in text:
            continue
        lines = [l.strip() for l in text.split("\n")]

        # 模式 A: "标签" 行 + 下一行 "X%"
        for i, line in enumerate(lines):
            m = re.match(r"^(\d+(?:\.\d+)?)\s*%$", line)
            if m and i > 0:
                for j in range(i - 1, max(0, i - 10), -1):
                    if lines[j] and re.match(r"^[\u4e00-\u9fff]{2,12}$", lines[j]):
                        lbl = lines[j]
                        already = any(
                            it["label"] == lbl and it["category"] == "职业价值观"
                            for it in ALL_ITEMS
                        )
                        if not already and lbl not in ["我的得分", "大家的平均分", "百分位", "成长建议"]:
                            add_item(source_pdf, "职业价值观", lbl, int(m.group(1)), "%")
                        break

        # 模式 B: "我的得分 X 分 同龄人平均分 Y 分"
        for line in lines:
            m = re.search(
                r"([\u4e00-\u9fff]{2,6})[^\n]*?我的得分[：:\s]*(\d+(?:\.\d+)?)\s*分[^\d]*?同龄人[^\d]*?(\d+(?:\.\d+)?)\s*分",
                line,
            )
            if m:
                already = any(
                    it["label"] == m.group(1) and it["category"] == "职业价值观"
                    for it in ALL_ITEMS
                )
                if not already:
                    add_item(
                        source_pdf, "职业价值观",
                        m.group(1), float(m.group(2)), "分", float(m.group(3)),
                    )


# ============================================================
# 主流程
# ============================================================
def main() -> None:
    pdfs = {
        "A2-核心素养": sorted(INPUT_DIR.glob("A2*.pdf")),
        "B3-核心学习能力": sorted(INPUT_DIR.glob("B3*.pdf")),
        "B4-核心认知能力": sorted(INPUT_DIR.glob("B4*.pdf")),
        "B6-职业价值观": sorted(INPUT_DIR.glob("B6*.pdf")),
    }

    print("=" * 70)
    print("PDF 提取 - 高精度模式")
    print("=" * 70)

    all_student_info: Dict[str, str] = {}

    for source_pdf, paths in pdfs.items():
        if not paths:
            continue
        pdf_path = paths[0]
        print("\n--- {} ({}) ---".format(source_pdf, pdf_path.name))
        texts = get_pdf_pages(pdf_path)
        print("  {} 个含文本页面".format(len(texts)))

        # 学生信息
        info = parse_student_info(texts)
        if not all_student_info:
            all_student_info = info
        print("  学生信息: {}".format(info))

        # 根据 PDF 类型应用解析器
        if "A2" in source_pdf:
            parse_a2_cognitive(source_pdf, texts)
            parse_a2_emotional(source_pdf, texts)
            parse_a2_personality(source_pdf, texts)
            parse_a2_attachment(source_pdf, texts)
            parse_a2_physical(source_pdf, texts)
        elif "B3" in source_pdf:
            parse_b3_executive(source_pdf, texts)
            parse_b3_motivation(source_pdf, texts)
            parse_b3_methods(source_pdf, texts)
        elif "B4" in source_pdf:
            parse_b4_overall(source_pdf, texts)
            parse_b4_cognitive_subitems(source_pdf, texts)
            parse_b4_mindset(source_pdf, texts)
        elif "B6" in source_pdf:
            parse_b6_career(source_pdf, texts)

    # 输出 JSON
    output = {
        "student": all_student_info,
        "items": ALL_ITEMS,
        "total_items": len(ALL_ITEMS),
    }
    with open(DATA_DIR / "clean_report_data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 70)
    print("共提取 {} 项数据".format(len(ALL_ITEMS)))
    print("JSON 保存到 data/clean_report_data.json")
    print("=" * 70)


if __name__ == "__main__":
    main()
