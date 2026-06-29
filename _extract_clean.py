"""高精度提取：简化版 - 使用更稳健的正则表达式。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

import fitz

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_PATH = BASE_DIR / "data" / "clean_report_data.json"


def extract_numbers_from_text(text: str, labels: List[str], default_unit: str = "分") -> List[Dict[str, Any]]:
    """从文本中提取 '标签 + 数字 + 单位' 格式的数据。

    支持格式:
    - "您在'标签'上的得分是 X 分，同龄人平均分是 Y 分"
    - "标签" 后单独一行有数字
    - "标签 X 分" 或 "标签 X%"
    """
    items: List[Dict[str, Any]] = []

    for label in labels:
        val = None
        mean = None
        unit = default_unit
        grade = ""

        # 1. 找 "得分是 X 分" 且前面某处有标签
        # 例如: "您在"开放性"上的得分是 3.3 分，同龄人的平均分是3分"
        pat1 = label + r"[\s\S]{0,80}?(\d+(?:\.\d+)?)\s*分[\s\S]{0,100}?同龄人[^\d]{0,15}(\d+(?:\.\d+)?)\s*分"
        m = re.search(pat1, text)
        if m:
            val = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
            mean = float(m.group(2)) if "." in m.group(2) else int(m.group(2))
            unit = "分"
        else:
            # 2. 在标签附近找数字
            pat2 = label + r"[\s\S]{0,50}?(\d+(?:\.\d+)?)\s*(分|%)"
            m = re.search(pat2, text)
            if m:
                val = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
                unit = m.group(2) or default_unit

        # 3. 单独一行的 "标签" + 后几行的数字（像雷达图/柱状图数据）
        if val is None:
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            for i, line in enumerate(lines):
                if label in line:
                    for j in range(1, min(5, len(lines) - i)):
                        num_line = lines[i + j]
                        m3 = re.match(r"^(\d+(?:\.\d+)?)\s*(分|%)?\s*$", num_line)
                        if m3:
                            val = float(m3.group(1)) if "." in m3.group(1) else int(m3.group(1))
                            unit = m3.group(2) or default_unit
                            break

        if val is not None:
            items.append({
                "label": label,
                "value": val,
                "mean": mean,
                "unit": unit,
                "grade": grade,
            })

    return items


def parse_a2_cognitive(text: str) -> List[Dict[str, Any]]:
    """认知能力: 感知觉 注意力 记忆力 推理能力 空间能力 信息加工速度"""
    items = extract_numbers_from_text(text,
        ["感知觉", "注意力", "记忆力", "推理能力", "空间能力", "信息加工速度"],
        "%")

    # 总得分
    m = re.search(r"总得分[^\d]*(\d+(?:\.\d+)?)", text)
    if m:
        val = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
        items.append({"label": "认知能力总得分", "value": val, "mean": None, "unit": "分", "grade": ""})

    # 同龄人百分位
    m = re.search(r"超过了\s*(\d+(?:\.\d+)?)\s*%", text)
    if m:
        val = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
        items.append({"label": "认知能力百分位", "value": val, "mean": None, "unit": "%", "grade": ""})

    for item in items:
        item["group"] = "认知能力"
    return items


def parse_a2_emotional(text: str) -> List[Dict[str, Any]]:
    """情绪稳定性: 自卑-自尊 抑郁-愉快 焦虑-安详 依赖-自主"""
    items = []

    # 总分: "X个分测验中的总得分是32.5分，同龄人的平均分是40分"
    m = re.search(r"(\d+)\s*个分测验中的总得分是\s*(\d+(?:\.\d+)?)\s*分[^\n]*同龄人[^\d]*(\d+(?:\.\d+)?)\s*分", text)
    if m:
        val = float(m.group(2)) if "." in m.group(2) else int(m.group(2))
        mean = float(m.group(3)) if "." in m.group(3) else int(m.group(3))
        items.append({"label": "情绪稳定性总分", "value": val, "mean": mean, "unit": "分", "grade": "", "group": "情绪稳定性"})

    # 子项: "您在自卑-自尊上的得分是 X 分"
    subitems = extract_numbers_from_text(text,
        ["自卑", "抑郁", "焦虑", "依赖", "自卑-自尊", "抑郁-愉快", "焦虑-安详", "依赖-自主",
         "情绪稳定", "情绪不稳定"], "分")
    for item in subitems:
        item["group"] = "情绪稳定性"
    items.extend(subitems)

    return items


def parse_a2_personality(text: str) -> List[Dict[str, Any]]:
    """大五人格: 开放性 宜人性 责任心 外倾性 神经质"""
    items = extract_numbers_from_text(text,
        ["开放性", "宜人性", "责任心", "外倾性", "神经质"], "分")
    for item in items:
        item["group"] = "大五人格"
    return items


def parse_a2_social(text: str) -> List[Dict[str, Any]]:
    """依恋关系: 信任/沟通/亲近 × 母亲/父亲/同伴"""
    items = []

    # 信任: "信任方面的得分分别是47分、32分、22分"
    m = re.search(r"信任[方面上的]{0,5}得分分别是\s*(\d+)\s*分[、，,]\s*(\d+)\s*分[、，,]\s*(\d+)\s*分", text)
    if m:
        for idx, person in enumerate(["母亲", "父亲", "同伴"]):
            items.append({
                "label": "信任-{}".format(person),
                "value": int(m.group(idx + 1)),
                "mean": None, "unit": "分", "grade": "", "group": "依恋关系"
            })

    # 沟通: "沟通上的得分分别是41分、29分、19分"
    m = re.search(r"沟通[方面上的]{0,5}得分分别是\s*(\d+)\s*分[、，,]\s*(\d+)\s*分[、，,]\s*(\d+)\s*分", text)
    if m:
        for idx, person in enumerate(["母亲", "父亲", "同伴"]):
            items.append({
                "label": "沟通-{}".format(person),
                "value": int(m.group(idx + 1)),
                "mean": None, "unit": "分", "grade": "", "group": "依恋关系"
            })

    # 亲近: "亲近上的得分分别是19分、12分、14分"
    m = re.search(r"亲近[方面上的]{0,5}得分分别是\s*(\d+)\s*分[、，,]\s*(\d+)\s*分[、，,]\s*(\d+)\s*分", text)
    if m:
        for idx, person in enumerate(["母亲", "父亲", "同伴"]):
            items.append({
                "label": "亲近-{}".format(person),
                "value": int(m.group(idx + 1)),
                "mean": None, "unit": "分", "grade": "", "group": "依恋关系"
            })

    return items


def parse_a2_health(text: str) -> List[Dict[str, Any]]:
    """体质健康: 身高 体重 运动习惯 睡眠习惯 BMI"""
    items = []

    m = re.search(r"身高[：:是为]{0,3}\s*(\d+(?:\.\d+)?)\s*(cm|CM)", text, re.IGNORECASE)
    if m:
        items.append({"label": "身高", "value": int(m.group(1)), "mean": None, "unit": "cm", "grade": "", "group": "体质健康"})

    m = re.search(r"体重[：:是为]{0,3}\s*(\d+(?:\.\d+)?)\s*(kg|KG)", text, re.IGNORECASE)
    if m:
        items.append({"label": "体重", "value": int(m.group(1)), "mean": None, "unit": "kg", "grade": "", "group": "体质健康"})

    # BMI
    m = re.search(r"BMI[^\d]{0,10}(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if m:
        val = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
        items.append({"label": "BMI", "value": val, "mean": None, "unit": "", "grade": "", "group": "体质健康"})

    # 睡眠: "7.1小时/每天"
    m = re.search(r"(\d+(?:\.\d+)?)\s*小时\s*/\s*每?天", text)
    if m:
        val = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
        items.append({"label": "睡眠（每天）", "value": val, "mean": None, "unit": "小时", "grade": "", "group": "体质健康"})

    # 运动: "11小时/周"
    m = re.search(r"(\d+(?:\.\d+)?)\s*小时\s*/\s*每?周", text)
    if m:
        val = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
        items.append({"label": "运动（每周）", "value": val, "mean": None, "unit": "小时", "grade": "", "group": "体质健康"})

    return items


def parse_b3_executive(text: str) -> List[Dict[str, Any]]:
    """执行功能: 抑制控制 工作记忆 认知灵活性"""
    items = extract_numbers_from_text(text, ["抑制控制", "工作记忆", "认知灵活性"], "%")
    for item in items:
        item["group"] = "执行功能"
    return items


def parse_b3_motivation(text: str) -> List[Dict[str, Any]]:
    """学习动机: 深层动机 表面动机 自我效能感"""
    items = extract_numbers_from_text(text, ["深层动机", "表面动机", "自我效能感"], "分")
    for item in items:
        item["group"] = "学习动机"
    return items


def parse_b3_methods(text: str) -> List[Dict[str, Any]]:
    """学习方法与策略: 学习深层方法与策略 学习表面方法与策略 学习自我调节"""
    items = extract_numbers_from_text(text,
        ["学习深层方法与策略", "学习表面方法与策略", "学习自我调节"], "分")
    for item in items:
        item["group"] = "学习方法与策略"
    return items


def parse_b4_cognitive(text: str) -> List[Dict[str, Any]]:
    """认知能力六项子指标"""
    items = extract_numbers_from_text(text,
        ["感知觉", "记忆力", "注意力", "推理能力", "空间能力", "信息加工速度",
         "反应时", "正确率"], "%")
    for item in items:
        item["group"] = "认知能力六项子指标"
    return items


def parse_b4_selfconcept(text: str) -> List[Dict[str, Any]]:
    """自我概念: 行为表现 能力与学校表现 躯体外貌 情绪状态 合群 幸福与满足"""
    items = extract_numbers_from_text(text,
        ["行为表现", "能力与学校表现", "躯体外貌", "情绪状态", "合群", "幸福与满足"], "分")
    for item in items:
        item["group"] = "自我概念"

    # 整体评价
    m = re.search(r"整体评价[：:是为]{0,3}\s*([\u4e00-\u9fff]{2,4})", text)
    if m:
        items.append({
            "label": "自我概念整体评价",
            "value": None, "mean": None, "unit": "",
            "grade": m.group(1), "group": "自我概念"
        })
    return items


def parse_b4_motivation(text: str) -> List[Dict[str, Any]]:
    """自驱力: 自主性 胜任感 归属感 思维模式 成长型思维"""
    items = extract_numbers_from_text(text,
        ["自主性", "胜任感", "归属感", "思维模式", "成长型思维"], "分")
    for item in items:
        item["group"] = "自驱力（内在动机）"
    return items


def parse_b6_interest(text: str) -> List[Dict[str, Any]]:
    """职业兴趣 Holland 六型"""
    items = extract_numbers_from_text(text,
        ["事业型", "社会型", "研究型", "常规型", "艺术型", "现实型"], "分")

    # NO.1: XX型 X分
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in lines:
        m = re.match(r"^NO\.?\s*\d+[：:]\s*([\u4e00-\u9fff]{2,4}(?:型|者)?)\s+(\d+(?:\.\d+)?)\s*分", line)
        if m:
            label = m.group(1)
            val = float(m.group(2)) if "." in m.group(2) else int(m.group(2))
            if not any(it["label"] == label for it in items):
                items.append({"label": label, "value": val, "mean": None, "unit": "分", "grade": "",
                              "group": "职业兴趣（Holland）"})

    for item in items:
        if "group" not in item:
            item["group"] = "职业兴趣（Holland）"
    return items


def parse_b6_ability(text: str) -> List[Dict[str, Any]]:
    """能力优势多元智能"""
    items = extract_numbers_from_text(text,
        ["语言能力", "人际关系能力", "内省能力", "身体运动能力",
         "逻辑数学能力", "空间能力", "音乐能力", "自然能力"], "分")
    for item in items:
        item["group"] = "能力优势（多元智能）"
    return items


def parse_b6_values(text: str) -> List[Dict[str, Any]]:
    """职业价值观"""
    items = extract_numbers_from_text(text,
        ["成就感", "经济报酬", "工作环境", "人际关系", "独立性",
         "稳定性", "智性刺激", "利他主义", "管理权力", "生活方式",
         "创造力", "审美追求", "多样性"], "分")
    for item in items:
        item["group"] = "职业价值观"
    return items


def main() -> int:
    pdfs = sorted(INPUT_DIR.glob("*.pdf"))
    if not pdfs:
        print("ERROR: no PDFs")
        return 1

    print("Found {} PDFs".format(len(pdfs)))

    all_texts: List[str] = []
    all_metrics: List[Dict[str, Any]] = []
    pdf_titles: List[str] = []

    for pdf in pdfs:
        stem = pdf.stem
        print("\n=== {} ===".format(stem))

        title_match = re.match(r"([A-Z]\d*[\u4e00-\u9fff]+?)[_（(]", stem)
        pdf_title = title_match.group(1) if title_match else stem
        pdf_titles.append(pdf_title)

        doc = fitz.open(str(pdf))
        pdf_metrics: List[Dict[str, Any]] = []

        for page_idx in range(len(doc)):
            page_text = doc[page_idx].get_text()
            all_texts.append(page_text)

            if "A2" in stem:
                if page_idx == 2:
                    pdf_metrics.extend(parse_a2_cognitive(page_text))
                elif page_idx == 4:
                    pdf_metrics.extend(parse_a2_emotional(page_text))
                elif page_idx == 6:
                    pdf_metrics.extend(parse_a2_personality(page_text))
                elif page_idx == 8:
                    pdf_metrics.extend(parse_a2_social(page_text))
                elif page_idx == 10:
                    pdf_metrics.extend(parse_a2_health(page_text))
            elif "B3" in stem:
                if 2 <= page_idx <= 5:
                    pdf_metrics.extend(parse_b3_executive(page_text))
                elif 6 <= page_idx <= 9:
                    pdf_metrics.extend(parse_b3_motivation(page_text))
                elif page_idx >= 10:
                    pdf_metrics.extend(parse_b3_methods(page_text))
            elif "B4" in stem:
                if page_idx <= 5:
                    pdf_metrics.extend(parse_b4_cognitive(page_text))
                elif 9 <= page_idx <= 12:
                    pdf_metrics.extend(parse_b4_selfconcept(page_text))
                elif page_idx >= 13:
                    pdf_metrics.extend(parse_b4_motivation(page_text))
            elif "B6" in stem:
                if page_idx <= 5:
                    pdf_metrics.extend(parse_b6_interest(page_text))
                elif 6 <= page_idx <= 10:
                    pdf_metrics.extend(parse_b6_ability(page_text))
                elif page_idx >= 12:
                    pdf_metrics.extend(parse_b6_values(page_text))

        doc.close()

        for m in pdf_metrics:
            m["source_pdf"] = pdf_title

        all_metrics.extend(pdf_metrics)
        print("  extracted: {} metrics".format(len(pdf_metrics)))
        for m in pdf_metrics:
            val = str(m["value"]) if m["value"] is not None else "-"
            mean = str(m["mean"]) if m["mean"] is not None else "-"
            print("    {:<25s} {:>8s} {:<4s} (avg: {:>8s} grade: {}) [{}]".format(
                m["label"][:23], val, m["unit"], mean, m.get("grade", ""), m.get("group", "")
            ))

    # Student info
    combined = "\n".join(all_texts)

    def grab(pat: str) -> str:
        m = re.search(pat, combined)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

    student = {
        "name": grab(r"姓\s*名[：:]\s*([^\n]+)"),
        "gender": grab(r"性\s*别[：:]\s*([^\n]+)"),
        "birthday": grab(r"出生日期[：:]\s*([^\n]+)"),
        "test_date": grab(r"测试(?:日期|时间)[：:]\s*([^\n]+)"),
        "grade": grab(r"年\s*级[：:]\s*([^\n]+)"),
        "school": grab(r"学\s*校[：:]\s*([^\n]+)"),
        "teacher": grab(r"(?:测评老师|指导师)[：:]\s*([^\n]+)"),
        "archive_id": grab(r"档案ID[：:]\s*([^\n]+)"),
        "report_code": grab(r"报告编码[：:]\s*([^\n]+)"),
    }

    print("\n=== Student Info ===")
    for k, v in sorted(student.items()):
        print("  {:<15s} {}".format(k, v))

    # 去重
    seen: set = set()
    clean_metrics: List[Dict[str, Any]] = []
    for m in all_metrics:
        key = "{}|{}".format(m["label"], m.get("source_pdf", ""))
        if key in seen:
            continue
        seen.add(key)
        clean_metrics.append(m)

    print("\n=== Summary ===")
    print("Total: {} unique metrics from {} PDFs".format(len(clean_metrics), len(pdf_titles)))

    # 组织成 sections
    by_pdf: Dict[str, List[Dict[str, Any]]] = {}
    for m in clean_metrics:
        pdf = m.get("source_pdf", "")
        if pdf not in by_pdf:
            by_pdf[pdf] = []
        by_pdf[pdf].append(m)

    sections: List[Dict[str, Any]] = []
    for title in pdf_titles:
        metrics = by_pdf.get(title, [])
        by_group: Dict[str, List[Dict[str, Any]]] = {}
        for m in metrics:
            g = m.get("group", "其他")
            if g not in by_group:
                by_group[g] = []
            by_group[g].append(m)
        groups = [{"name": name, "items": items} for name, items in by_group.items()]
        sections.append({"title": title, "subtitle": title.upper(), "groups": groups})

    report = {
        "student": student,
        "pdf_titles": pdf_titles,
        "total_metrics": len(clean_metrics),
        "sections": sections,
        "flat_metrics": clean_metrics,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n[DONE] Saved to {}".format(OUTPUT_PATH))
    return 0


if __name__ == "__main__":
    main()
