"""高精度 PDF 数据提取 - 最终版"""
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


def get_pdf_text(pdf_path: Path) -> str:
    """返回整份 PDF 的文本（去掉多余的换行和空格）"""
    doc = fitz.open(str(pdf_path))
    text_parts = []
    for page in doc:
        text_parts.append(page.get_text())
    doc.close()
    full_text = "\n".join(text_parts)
    # 将 "信任\n方 面" 这类被换行打断的词合并 - 处理换行后出现的 "方 面"
    # 更通用做法：对跨换行的词组，去掉换行符进行正则匹配
    return full_text


def clean(text: str) -> str:
    """将多空格/换行合并为单个空格，用于长句匹配"""
    return re.sub(r"\s+", " ", text).strip()


def parse_student_info(text: str) -> Dict[str, str]:
    info = {}
    for key, pattern in [
        ("name", r"姓\s*名[：:]\s*([A-Za-z\u4e00-\u9fff]+)"),
        ("grade", r"年\s*级[：:]\s*([^\n]+)"),
        ("test_date", r"测试时间[：:]\s*(\d{4}-\d{2}-\d{2})"),
        ("birth_date", r"出生日期[：:]\s*(\d{4}-\d{2}-\d{1,2})"),
        ("school", r"学\s*校[：:]\s*([^\n]+)"),
    ]:
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
    ALL_ITEMS.append(item)
    mean_str = " (同龄人 {}{})".format(mean, unit if unit else "") if mean is not None else ""
    print("  [{}] {} / {} = {}{}{}".format(
        source_pdf, category, label, value, unit if unit else "", mean_str
    ))


# ============================================================
# A2: 认知能力 (page 3) - 标签 + 下一行的 X%
# ============================================================
def parse_a2_cognitive(source_pdf: str, text: str) -> None:
    labels = ["感知觉", "记忆力", "注意力"]
    lines = [l.strip() for l in text.split("\n")]
    found = set()
    for i, line in enumerate(lines):
        if line in labels and i + 1 < len(lines):
            m = re.match(r"^(\d+)\s*%$", lines[i + 1])
            if m and line not in found:
                found.add(line)
                add_item(source_pdf, "认知能力", line, int(m.group(1)), "%")


# ============================================================
# A2: 情绪稳定性 (page 5) - 总分 + 同龄人平均分
# ============================================================
def parse_a2_emotional(source_pdf: str, text: str) -> None:
    # 在多页 PDF 中，只搜索包含 "情绪稳定性" 的那部分文本
    # 通过切片：找到 "情绪稳定性" 第一次出现后 500 字符范围
    idx = text.find("情绪稳定性")
    if idx == -1:
        return
    section = text[idx:idx + 800]
    m = re.search(
        r"(\d+)\s*个分测验中的总得分是\s*(\d+(?:\.\d+)?)\s*分[^\n]{0,100}同龄人[^\d]*?(\d+(?:\.\d+)?)\s*分",
        clean(section),
    )
    if m:
        add_item(source_pdf, "情绪稳定性", "情绪稳定性总分", float(m.group(2)), "分", float(m.group(3)))


# ============================================================
# A2: 大五人格 (page 7) - "标签" 的得分是 X 分，同龄人平均分 Y 分
# ============================================================
def parse_a2_personality(source_pdf: str, text: str) -> None:
    labels = ["开放性", "宜人性", "责任心", "外倾性", "神经质"]
    idx = text.find("大五人格")
    if idx == -1:
        return
    section = text[idx:idx + 1500]
    for lbl in labels:
        patterns = [
            r"[\"'\u201c\u201d\u2018\u2019]{}[\"'\u201c\u201d\u2018\u2019]上的得分是\s*(\d+(?:\.\d+)?)\s*分[^\d]{{0,20}}同龄人[^\d]*?(\d+(?:\.\d+)?)\s*分".format(lbl),
            r"[\"'\u201c\u201d\u2018\u2019]{}[\"'\u201c\u201d\u2018\u2019]的得分是\s*(\d+(?:\.\d+)?)\s*分[^\d]{{0,20}}同龄人[^\d]*?(\d+(?:\.\d+)?)\s*分".format(lbl),
        ]
        for p in patterns:
            m = re.search(p, clean(section))
            if m:
                add_item(source_pdf, "大五人格", lbl, float(m.group(1)), "分", float(m.group(2)))
                break


# ============================================================
# A2: 依恋关系 (page 9) - 信任/沟通/亲近 + 母亲/父亲/同伴
# ============================================================
def parse_a2_attachment(source_pdf: str, text: str) -> None:
    persons = ["母亲", "父亲", "同伴"]
    idx = text.find("依恋类型")
    if idx == -1:
        idx = text.find("母亲/父亲/同伴依恋")
    if idx == -1:
        return
    section = text[idx:idx + 1500]
    for dim in ["信任", "沟通", "亲近"]:
        m = re.search(
            r"{}[方面上的\s]*得分分别是\s*(\d+)\s*分[、,，\s]*(\d+)\s*分[、,，\s]*(\d+)\s*分".format(dim),
            clean(section),
        )
        if m:
            for j, p in enumerate(persons):
                add_item(source_pdf, "依恋关系", "{}-{}".format(dim, p), int(m.group(j + 1)), "分")


# ============================================================
# A2: 体质健康 (page 11) - 睡眠/运动/饮食习惯
# ============================================================
def parse_a2_physical(source_pdf: str, text: str) -> None:
    # 睡眠时长
    m = re.search(r"(\d+(?:\.\d+)?)\s*小时\s*/\s*每天", clean(text))
    if m:
        add_item(source_pdf, "体质健康", "每日睡眠时长", float(m.group(1)), "小时/天")
    # 运动时长
    m = re.search(r"(\d+(?:\.\d+)?)\s*小时\s*/\s*每周", clean(text))
    if m:
        add_item(source_pdf, "体质健康", "每周运动时长", float(m.group(1)), "小时/周")


# ============================================================
# B3: 执行功能 (page 3) - 标签 + 下一行的 X%
# ============================================================
def parse_b3_executive(source_pdf: str, text: str) -> None:
    labels = ["抑制控制", "工作记忆", "认知灵活性"]
    lines = [l.strip() for l in text.split("\n")]
    for i, line in enumerate(lines):
        if line in labels and i + 1 < len(lines):
            m = re.match(r"^(\d+)\s*%$", lines[i + 1])
            if m:
                add_item(source_pdf, "执行功能", line, int(m.group(1)), "%")


# ============================================================
# B3: 学习动机 (page 9) - 标签 X分 + 我的得分/平均得分
# ============================================================
def parse_b3_motivation(source_pdf: str, text: str) -> None:
    labels = ["深层动机", "表面动机", "自我效能感"]
    lines = [l.strip() for l in text.split("\n")]

    # 第一阶段：从 "标签 4.8分" 模式提取
    scores = {}
    for i, line in enumerate(lines):
        for lbl in labels:
            if lbl in line:
                m = re.search(r"(\d+(?:\.\d+)?)\s*分", line)
                if m:
                    scores[lbl] = float(m.group(1))

    # 第二阶段：从 "我的得分：X分 平均得分：Y分" 提取
    means = {}
    for i, line in enumerate(lines):
        if "我的得分" in line and "平均得分" in line:
            my_m = re.search(r"我的得分[：:]\s*(\d+(?:\.\d+)?)\s*分", line)
            avg_m = re.search(r"平均得分[：:]\s*(\d+(?:\.\d+)?)\s*分", line)
            if my_m:
                # 找到对应的标签（向前搜索 10 行）
                for back in range(max(0, i - 10), i):
                    cand = lines[back]
                    for lbl in labels:
                        if lbl in cand and lbl not in means:
                            if avg_m:
                                means[lbl] = float(avg_m.group(1))
                            if lbl not in scores:
                                scores[lbl] = float(my_m.group(1))
                            break

    # 输出
    for lbl in labels:
        if lbl in scores:
            add_item(source_pdf, "学习动机", lbl, scores[lbl], "分", means.get(lbl))


# ============================================================
# B3: 学习方法与策略 (page 11)
# ============================================================
def parse_b3_methods(source_pdf: str, text: str) -> None:
    labels_map = {
        "学习深层方法与策略": "深层",
        "学习表面方法与策略": "表面",
        "学习自我调节": "自我调节",
    }
    lines = [l.strip() for l in text.split("\n")]
    scores = {}
    for i, line in enumerate(lines):
        for lbl in labels_map:
            if lbl in line:
                m = re.search(r"(\d+(?:\.\d+)?)\s*分", line)
                if not m and i + 1 < len(lines):
                    m = re.search(r"(\d+(?:\.\d+)?)\s*分", lines[i + 1])
                if m and lbl not in scores:
                    scores[lbl] = float(m.group(1))

    for lbl in labels_map:
        if lbl in scores:
            add_item(source_pdf, "学习方法与策略", lbl, scores[lbl], "分")


# ============================================================
# B4: 认知能力总览 (page 3) - 115 总得分 + 84 百分位
# ============================================================
def parse_b4_overall(source_pdf: str, text: str) -> None:
    lines = [l.strip() for l in text.split("\n")]
    for i, line in enumerate(lines):
        if line == "总得分" and i > 0:
            m = re.match(r"^(\d+)$", lines[i - 1])
            if m:
                add_item(source_pdf, "认知能力", "认知能力总得分", int(m.group(1)), "分")
        if "百分位" in line and "认知能力" in " ".join(lines[max(0, i - 5):i + 1]):
            m = re.match(r"^(\d+(?:\.\d+)?)$", lines[i - 1]) if i > 0 else None
            if m and lines[i - 1].isdigit():
                add_item(source_pdf, "认知能力", "认知能力百分位", int(m.group(1)), "%")


# ============================================================
# B4: 认知能力六项子指标 (page 4)
# ============================================================
def parse_b4_cognitive_subitems(source_pdf: str, text: str) -> None:
    labels = ["感知觉", "注意力", "记忆力", "推理能力", "空间能力", "加工速度"]
    lines = [l.strip() for l in text.split("\n")]

    # 在 page 4 中：标签 -> 描述 -> "百分位（%）" -> 数字
    # 我们找到所有 "百分位（%）" 后一行的数字，向前找最近的标签
    for i, line in enumerate(lines):
        if "百分位（%）" in line:
            for j in range(i + 1, min(i + 5, len(lines))):
                m = re.match(r"^(\d+)$", lines[j])
                if m:
                    # 向前找标签
                    nearest = None
                    for k in range(i - 1, max(0, i - 20), -1):
                        for lbl in labels:
                            if lbl in lines[k]:
                                nearest = lbl
                                break
                        if nearest:
                            break
                    if nearest:
                        already = any(
                            it["label"] == nearest and it["category"] == "认知能力-子指标"
                            for it in ALL_ITEMS
                        )
                        if not already:
                            add_item(source_pdf, "认知能力-子指标", nearest, int(m.group(1)), "%")
                    break


# ============================================================
# B4: 自我概念 (page 11+) - 标签 + 数字行
# ============================================================
def parse_b4_self_concept(source_pdf: str, text: str) -> None:
    """自我概念六大项：行为表现、能力与学校表现、躯体外貌、情绪焦虑、合群、幸福与满意"""
    labels = [
        "行为表现", "能力与学校表现", "躯体外貌",
        "情绪焦虑", "合群", "幸福与满意",
    ]
    lines = [l.strip() for l in text.split("\n")]

    # 在 page 11 中：格式是 "数字" -> "标签" -> "英文"
    # 所以从标签向前找数字
    for i, line in enumerate(lines):
        for lbl in labels:
            if lbl in line:
                # 向前找数字（在 1-5 行内）
                for back in range(1, 6):
                    if i - back >= 0:
                        m = re.match(r"^(\d+)$", lines[i - back])
                        if m:
                            already = any(
                                it["label"] == lbl and it["category"] == "自我概念"
                                for it in ALL_ITEMS
                            )
                            if not already:
                                add_item(source_pdf, "自我概念", lbl, int(m.group(1)), "分")
                            break


# ============================================================
# B6: 职业兴趣 (page 3-7)
# ============================================================
def parse_b6_interest(source_pdf: str, text: str) -> None:
    """职业兴趣：现实型 2, 研究型 4, 艺术型 4, 社会型 7, 事业型 9, 常规型 4"""
    labels = ["现实型", "研究型", "艺术型", "社会型", "事业型", "常规型"]
    lines = [l.strip() for l in text.split("\n")]

    # page 4-7 中："现实型（实干家）" -> 下一行 "Realistic" -> 下一行 "2"
    # 简化做法：找 "现实型" 后下一个数字行
    for i, line in enumerate(lines):
        for lbl in labels:
            if lbl in line:
                for forward in range(1, 10):
                    if i + forward < len(lines):
                        m = re.match(r"^(\d+(?:\.\d+)?)$", lines[i + forward])
                        if m and lines[i + forward] not in labels:
                            already = any(
                                it["label"] == lbl and it["category"] == "职业兴趣"
                                for it in ALL_ITEMS
                            )
                            if not already:
                                add_item(source_pdf, "职业兴趣", lbl, int(m.group(1)), "分")
                            break


# ============================================================
# B6: 能力优势 (page 8-13)
# ============================================================
def parse_b6_ability(source_pdf: str, text: str) -> None:
    """能力优势八大类：语言能力 8, 逻辑数学 5, 音乐 3, 空间 4, 身体运动 5, 人际关系 7, 内省 6, 自然 2"""
    labels = [
        ("语言能力", "语言能力"),
        ("逻辑数学能力", "逻辑数学能力"),
        ("音乐能力", "音乐能力"),
        ("空间能力", "空间能力"),
        ("身体运动能力", "身体运动能力"),
        ("人际关系能力", "人际关系能力"),
        ("内省能力", "内省能力"),
        ("自然能力", "自然能力"),
    ]
    lines = [l.strip() for l in text.split("\n")]

    # page 8: "语言能力" -> ... -> "8分"
    for i, line in enumerate(lines):
        for search_lbl, out_lbl in labels:
            if search_lbl in line and "| Perception" not in line:
                # 在本行或下几行找 "X分"
                text_chunk = " ".join(lines[i:i + 5])
                m = re.search(r"(\d+(?:\.\d+)?)\s*分", text_chunk)
                if m:
                    already = any(
                        it["label"] == out_lbl and it["category"] == "能力优势"
                        for it in ALL_ITEMS
                    )
                    if not already:
                        add_item(source_pdf, "能力优势", out_lbl, int(m.group(1)), "分")


# ============================================================
# B6: 职业价值观 (page 14+)
# ============================================================
def parse_b6_values(source_pdf: str, text: str) -> None:
    """职业价值观：生活方式 9.39, 美的追求 3.29, ..."""
    # page 14: "9.39" -> "生活方式" -> "3.29" -> "美的追求"
    lines = [l.strip() for l in text.split("\n")]

    for i, line in enumerate(lines):
        # 如果是 "生活方式" 或 "美的追求" 等职业价值观关键词
        for lbl in ["生活方式", "美的追求", "创造发明", "独立自主", "智力激发",
                     "利他助人", "成就感", "管理权力", "工作环境", "同事关系",
                     "上司关系", "多样变化", "经济报酬", "安全稳定", "声望地位"]:
            if line == lbl:
                # 向前找数字（可能前 1-5 行）
                for back in range(1, 6):
                    if i - back >= 0:
                        m = re.match(r"^(\d+(?:\.\d+)?)$", lines[i - back])
                        if m:
                            already = any(
                                it["label"] == lbl and it["category"] == "职业价值观"
                                for it in ALL_ITEMS
                            )
                            if not already:
                                add_item(source_pdf, "职业价值观", lbl, float(m.group(1)), "分")
                            break


# ============================================================
# 主流程
# ============================================================
def main() -> None:
    pdf_configs = [
        ("A2-核心素养", "A2*.pdf", [
            parse_a2_cognitive, parse_a2_emotional, parse_a2_personality,
            parse_a2_attachment, parse_a2_physical,
        ]),
        ("B3-核心学习能力", "B3*.pdf", [
            parse_b3_executive, parse_b3_motivation, parse_b3_methods,
        ]),
        ("B4-核心认知能力", "B4*.pdf", [
            parse_b4_overall, parse_b4_cognitive_subitems, parse_b4_self_concept,
        ]),
        ("B6-职业发展", "B6*.pdf", [
            parse_b6_interest, parse_b6_ability, parse_b6_values,
        ]),
    ]

    all_student_info: Dict[str, str] = {}

    for source_pdf, glob_pat, parsers in pdf_configs:
        pdfs = sorted(INPUT_DIR.glob(glob_pat))
        if not pdfs:
            continue
        pdf_path = pdfs[0]
        text = get_pdf_text(pdf_path)

        print("\n--- {} ({}) ---".format(source_pdf, pdf_path.name))
        info = parse_student_info(text)
        if not all_student_info:
            all_student_info = info

        for parser in parsers:
            parser(source_pdf, text)

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
