"""高精度 PDF 数据提取 - 最终版 v3"""
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
    doc = fitz.open(str(pdf_path))
    text_parts = [p.get_text() for p in doc]
    doc.close()
    return "\n".join(text_parts)


def clean(text: str) -> str:
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
    source_pdf: str, category: str, label: str,
    value: Any, unit: Optional[str] = None, mean: Optional[Any] = None,
) -> None:
    item: Dict[str, Any] = {
        "source_pdf": source_pdf, "category": category,
        "label": label, "value": value,
    }
    if unit:
        item["unit"] = unit
    if mean is not None:
        item["mean"] = mean
    ALL_ITEMS.append(item)
    mean_str = " (同龄人 {}{})".format(mean, unit if unit else "") if mean is not None else ""
    print("  [{}] {} / {} = {}{}{}".format(
        source_pdf, category, label, value, unit if unit else "", mean_str))


def find_section(text: str, keywords: List[str], max_len: int = 2000) -> Optional[str]:
    for kw in keywords:
        idx = text.find(kw)
        if idx != -1:
            return text[idx:idx + max_len]
    return None


# ========== A2 ==========

def parse_a2_cognitive(source_pdf: str, text: str) -> None:
    section = find_section(text, ["认知能力测评报告", "认知能力\n"])
    if not section:
        return
    for lbl in ["感知觉", "记忆力", "注意力"]:
        lines = [l.strip() for l in section.split("\n")]
        for i, line in enumerate(lines):
            if line == lbl and i + 1 < len(lines):
                m = re.match(r"^(\d+)\s*%$", lines[i + 1])
                if m:
                    add_item(source_pdf, "认知能力", lbl, int(m.group(1)), "%")
                    break


def parse_a2_emotional(source_pdf: str, text: str) -> None:
    section = find_section(text, ["情绪稳定性测评报告", "情绪稳定性\n"])
    if not section:
        return
    cleaned = clean(section)
    # 用 "同[^\d]*?龄[^\d]*?人" 匹配 "同龄 人" 中间可能有空格
    m = re.search(
        r"(\d+)\s*个分测验中的总得分是\s*(\d+(?:\.\d+)?)\s*分[^\d]*?同[^\d]*?龄[^\d]*?人[^\d]*?(\d+(?:\.\d+)?)\s*分",
        cleaned,
    )
    if m:
        add_item(source_pdf, "情绪稳定性", "情绪稳定性总分", float(m.group(2)), "分", float(m.group(3)))
    else:
        # 调试：显示 section 的一部分
        print("  [DEBUG] emotional stability pattern not found in:")
        print("    " + cleaned[:300])


def parse_a2_personality(source_pdf: str, text: str) -> None:
    section = find_section(text, ["人格测评报告", "大五人格"])
    if not section:
        return
    for lbl in ["开放性", "宜人性", "责任心", "外倾性", "神经质"]:
        for p in [
            r"[\"'\u201c\u201d\u2018\u2019]{}[\"'\u201c\u201d\u2018\u2019]上的得分是\s*(\d+(?:\.\d+)?)\s*分[^\d]{{0,30}}同龄人[^\d]*?(\d+(?:\.\d+)?)\s*分".format(lbl),
            r"[\"'\u201c\u201d\u2018\u2019]{}[\"'\u201c\u201d\u2018\u2019]的得分是\s*(\d+(?:\.\d+)?)\s*分[^\d]{{0,30}}同龄人[^\d]*?(\d+(?:\.\d+)?)\s*分".format(lbl),
        ]:
            m = re.search(p, clean(section))
            if m:
                add_item(source_pdf, "大五人格", lbl, float(m.group(1)), "分", float(m.group(2)))
                break


def parse_a2_attachment(source_pdf: str, text: str) -> None:
    section = find_section(text, ["依恋类型", "母亲/父亲/同伴依恋"])
    if not section:
        return
    persons = ["母亲", "父亲", "同伴"]
    for dim in ["信任", "沟通", "亲近"]:
        # "信任方面的得分分别 是47分、32分、22分"
        m = re.search(
            r"{}[方面上的\s]*得分[分别\s]*是\s*(\d+)\s*分[、,，\s]*(\d+)\s*分[、,，\s]*(\d+)\s*分".format(dim),
            clean(section),
        )
        if m:
            for j, p in enumerate(persons):
                add_item(source_pdf, "依恋关系", "{}-{}".format(dim, p), int(m.group(j + 1)), "分")


def parse_a2_physical(source_pdf: str, text: str) -> None:
    section = find_section(text, ["体质健康测评报告", "体质健康\n"])
    if not section:
        return
    cleaned = clean(section)

    m = re.search(r"(\d+(?:\.\d+)?)\s*小时\s*/\s*每天", cleaned)
    if m:
        add_item(source_pdf, "体质健康", "每日睡眠时长", float(m.group(1)), "小时/天")

    m = re.search(r"(\d+(?:\.\d+)?)\s*小时\s*/\s*周", cleaned)
    if m:
        add_item(source_pdf, "体质健康", "每周运动时长", float(m.group(1)), "小时/周")

    m = re.search(r"身高[：:]\s*(\d+)\s*(?:CM|cm)", cleaned)
    if m:
        add_item(source_pdf, "体质健康", "身高", int(m.group(1)), "CM")

    m = re.search(r"体重[：:]\s*(\d+)\s*(?:KG|kg)", cleaned)
    if m:
        add_item(source_pdf, "体质健康", "体重", int(m.group(1)), "KG")

    m = re.search(r"BMI[：:]\s*(\d+(?:\.\d+)?)\s*(?:KG/M²|kg/m²|KG/M)", cleaned)
    if m:
        add_item(source_pdf, "体质健康", "BMI", float(m.group(1)), "KG/M²")


# ========== B3 ==========

def parse_b3_executive(source_pdf: str, text: str) -> None:
    section = find_section(text, ["执行功能测评报告", "执行功能\n"])
    if not section:
        return
    lines = [l.strip() for l in section.split("\n")]
    for lbl in ["抑制控制", "工作记忆", "认知灵活性"]:
        for i, line in enumerate(lines):
            if line == lbl and i + 1 < len(lines):
                m = re.match(r"^(\d+)\s*%$", lines[i + 1])
                if m:
                    add_item(source_pdf, "执行功能", lbl, int(m.group(1)), "%")
                    break


def parse_b3_motivation(source_pdf: str, text: str) -> None:
    section = find_section(text, ["学习动机测评报告", "学习动机\n"])
    if not section:
        return
    labels = ["深层动机", "表面动机", "自我效能感"]

    for lbl in labels:
        # 模式: "深层动机 Deep Motivation 我的得分：4.8分 平均得分：7.4分"
        # 用正则在 clean 后的 section 中找
        m = re.search(
            r"{}\s*(?:[A-Za-z\- ]+)?\s*我的得分[：:]\s*(\d+(?:\.\d+)?)\s*分[^\d]*?平均得分[：:]\s*(\d+(?:\.\d+)?)\s*分".format(lbl),
            clean(section),
        )
        if m:
            add_item(source_pdf, "学习动机", lbl, float(m.group(1)), "分", float(m.group(2)))
        else:
            # fallback: "深层动机 4.8分"
            m = re.search(r"{}\s*(\d+(?:\.\d+)?)\s*分".format(lbl), clean(section))
            if m:
                add_item(source_pdf, "学习动机", lbl, float(m.group(1)), "分")


def parse_b3_methods(source_pdf: str, text: str) -> None:
    section = find_section(text, ["学习方法与策略测评报告", "学习方法与策略\n"])
    if not section:
        return
    labels = ["学习深层方法与策略", "学习表面方法与策略", "学习自我调节"]
    for lbl in labels:
        m = re.search(
            r"{}\s*(?:[A-Za-z\- ]+)?\s*我的得分[：:]\s*(\d+(?:\.\d+)?)\s*分[^\d]*?平均得分[：:]\s*(\d+(?:\.\d+)?)\s*分".format(lbl),
            clean(section),
        )
        if m:
            add_item(source_pdf, "学习方法与策略", lbl, float(m.group(1)), "分", float(m.group(2)))
        else:
            m = re.search(r"{}\s*(\d+(?:\.\d+)?)\s*分".format(lbl), clean(section))
            if m:
                add_item(source_pdf, "学习方法与策略", lbl, float(m.group(1)), "分")


# ========== B4 ==========

def parse_b4_overall(source_pdf: str, text: str) -> None:
    lines = [l.strip() for l in text.split("\n")]
    for i, line in enumerate(lines):
        if "总得分" in line and "Total Score" in " ".join(lines[max(0, i-2):i+2]):
            # 上一行是数字
            for back in range(1, 4):
                if i - back >= 0 and re.match(r"^\d+$", lines[i - back]):
                    add_item(source_pdf, "认知能力", "认知能力总得分", int(lines[i - back]), "分")
                    break
        if "百分位" in line and "认知能力" in " ".join(lines[max(0, i-20):i+5]):
            for back in range(1, 4):
                if i - back >= 0 and re.match(r"^\d+$", lines[i - back]):
                    if lines[i - back] != "115":  # 不是总得分
                        add_item(source_pdf, "认知能力", "认知能力百分位", int(lines[i - back]), "%")
                        break


def parse_b4_cognitive_subitems(source_pdf: str, text: str) -> None:
    section = find_section(text, ["认知能力模型", "DAN测评根据儿童青少年"])
    if not section:
        return
    labels = ["感知觉", "注意力", "记忆力", "推理能力", "空间能力", "加工速度"]
    lines = [l.strip() for l in section.split("\n")]
    for i, line in enumerate(lines):
        if "百分位" in line:
            # 找下一行的数字
            for j in range(i + 1, min(i + 5, len(lines))):
                if re.match(r"^\d+$", lines[j]):
                    nearest_label = None
                    for k in range(i - 1, max(0, i - 20), -1):
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
                            add_item(source_pdf, "认知能力-子指标", nearest_label, int(lines[j]), "%")
                    break


def parse_b4_self_concept(source_pdf: str, text: str) -> None:
    section = find_section(text, ["自我概念测评报告", "自我概念\n"])
    if not section:
        return
    labels = ["行为表现", "能力与学校表现", "躯体外貌", "情绪焦虑", "合群", "幸福与满意"]
    lines = [l.strip() for l in section.split("\n")]
    for i, line in enumerate(lines):
        for lbl in labels:
            if lbl in line:
                # 向前找第一个数字（可能是前 1-3 行）
                for back in range(1, 8):
                    if i - back >= 0:
                        m = re.match(r"^(\d+)$", lines[i - back])
                        if m and not any(
                            l2 in lines[i - back] for l2 in labels
                        ):
                            already = any(
                                it["label"] == lbl and it["category"] == "自我概念"
                                for it in ALL_ITEMS
                            )
                            if not already:
                                add_item(source_pdf, "自我概念", lbl, int(m.group(1)), "分")
                            break


# ========== B6 ==========

def parse_b6_interest(source_pdf: str, text: str) -> None:
    section = find_section(text, ["职业兴趣测评结果", "职业兴趣测评报告"])
    if not section:
        return
    # 只匹配以 "X型（YY）" 开头的独立行
    pattern = r"^(现实型|研究型|艺术型|社会型|事业型|常规型)[（\(][\u4e00-\u9fffA-Z]+[）\)]$"
    lines = [l.strip() for l in section.split("\n")]
    for i, line in enumerate(lines):
        m = re.match(pattern, line)
        if m:
            lbl = m.group(1)
            for j in range(i + 1, min(i + 4, len(lines))):
                if re.match(r"^[A-Za-z\-\s]+$", lines[j]):
                    continue
                m2 = re.match(r"^(\d+)$", lines[j])
                if m2:
                    already = any(
                        it["label"] == lbl and it["category"] == "职业兴趣"
                        for it in ALL_ITEMS
                    )
                    if not already:
                        add_item(source_pdf, "职业兴趣", lbl, int(m2.group(1)), "分")
                    break


def parse_b6_ability(source_pdf: str, text: str) -> None:
    section = find_section(text, ["能力优势测评报告", "能力优势\n"])
    if not section:
        return
    labels = ["语言能力", "逻辑数学能力", "音乐能力", "空间能力", "身体运动能力", "人际关系能力", "内省能力", "自然能力"]
    lines = [l.strip() for l in section.split("\n")]
    for i, line in enumerate(lines):
        for lbl in labels:
            if lbl in line:
                # 在本行或接下来 3 行内找 "X分"
                text_chunk = " ".join(lines[i:i + 4])
                m = re.search(r"(\d+(?:\.\d+)?)\s*分", text_chunk)
                if m:
                    already = any(
                        it["label"] == lbl and it["category"] == "能力优势"
                        for it in ALL_ITEMS
                    )
                    if not already:
                        add_item(source_pdf, "能力优势", lbl, int(m.group(1)), "分")


def parse_b6_values(source_pdf: str, text: str) -> None:
    section = find_section(text, ["职业价值观", "我的职业价值观"])
    if not section:
        return
    labels = ["生活方式", "美的追求", "创造发明", "独立自主", "智力激发",
              "利他助人", "成就感", "管理权力", "工作环境", "同事关系",
              "上司关系", "多样变化", "经济报酬", "安全稳定", "声望地位"]
    lines = [l.strip() for l in section.split("\n")]
    for i, line in enumerate(lines):
        for lbl in labels:
            if line == lbl:
                # 向前找数字
                for back in range(1, 8):
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


# ========== 主流程 ==========

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
            parse_b4_overall, parse_b4_cognitive_subitems,
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
        text = get_pdf_text(pdfs[0])
        print("\n--- {} ({}) ---".format(source_pdf, pdfs[0].name))
        if not all_student_info:
            all_student_info = parse_student_info(text)
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
