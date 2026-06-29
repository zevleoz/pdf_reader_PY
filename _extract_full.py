"""从 4 个 PDF 中提取所有结构化数据。
策略：用 PyMuPDF 提取文本，用正则解析所有数字数据点。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_PATH = BASE_DIR / "data" / "full_report_data.json"


def extract_student_info(texts: List[str]) -> Dict[str, str]:
    """从所有页面文本中提取学生信息。"""
    combined = "\n".join(texts)

    def grab(pat: str) -> str:
        m = re.search(pat, combined)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

    return {
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


def parse_page_text(text: str, page_num: int, pdf_title: str,
                    sub_title: str) -> List[Dict[str, Any]]:
    """从一页文本中解析出所有数值数据点。"""
    items: List[Dict[str, Any]] = []
    lines = [re.sub(r"\s+", " ", l).strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return items

    # 模式 1: "标签\nX%" 或 "标签\nX分" （前后可能有英文）
    i = 0
    while i < len(lines):
        line = lines[i]

        # 过滤掉页眉/页脚/导航文字
        skip_patterns = [
            "第.*页", "姓.*名", "档案ID", "测试时间", "出生日期",
            "指导师", "报告编码", "电子报告", "成长建议",
            "COGNITIVE", "EXECUTIVE", "EMOTIONAL", "PERSONALITY",
            "VOCATIONAL", "ACADEMIC", "WORKING", "PERCEPTION",
            "ATTENTION", "SPATIAL", "SELF", "LIST", "REPORT",
            "RESULTS", "DETAILS", "SUMMARY", "HOLLAND", "CODE",
            "ADVANTAGE", "MY", "WORK", "VALUES", "TOTAL", "SCORE",
            "测评报告", "测评结果", "关注.*公众号", "双培强基",
        ]
        if any(re.search(p, line) for p in skip_patterns):
            i += 1
            continue

        # 检查行本身是否就是数字
        m_num = re.match(r"^(\d+(?:\.\d+)?)\s*(分|%|cm|kg|小时|CM|KG|岁)?$", line)
        if m_num and i > 0:
            # 往回找标签（最近的非数字行）
            val = float(m_num.group(1)) if "." in m_num.group(1) else int(m_num.group(1))
            unit = m_num.group(2) or ""

            # 向上找标签（跳过英文副标签）
            label = ""
            for j in range(i - 1, max(0, i - 5), -1):
                candidate = lines[j].strip()
                if not candidate or len(candidate) < 2:
                    continue
                if re.match(r"^[\d\s%分CMKGcmkg小时岁\.,/-]+$", candidate):
                    continue
                # 纯英文（副标签）也跳过，但记录为英文
                if re.match(r"^[A-Za-z\s\(\)\-']+$", candidate):
                    continue
                # 含有中文字符，且长度合适
                if re.search(r"[\u4e00-\u9fff]", candidate) and len(candidate) <= 30:
                    label = candidate
                    break

            if label:
                items.append({
                    "label": label,
                    "value": val,
                    "mean": None,
                    "unit": unit,
                    "grade": "",
                    "notes": sub_title,
                    "page": page_num,
                    "pdf": pdf_title,
                    "source": "pattern1",
                })

        # 模式 2: 整句描述 "...您的得分是 X 分，同龄人平均分是 Y 分"
        sent = line
        for m in re.finditer(
            r"([\u4e00-\u9fff]{2,20}).*?(?:得分|分)[^\d]{0,10}(\d+(?:\.\d+)?)\s*(分|%)?"
            r"(?:[^\d]{0,20}(?:同龄人|大家的|平均)[^\d]{0,10}(\d+(?:\.\d+)?))?",
            sent,
        ):
            label = m.group(1)
            val = float(m.group(2)) if "." in m.group(2) else int(m.group(2))
            mean = None
            if m.group(4):
                mean = float(m.group(4)) if "." in m.group(4) else int(m.group(4))
            unit = m.group(3) or "分"

            # 验证：label 不应包含通用词汇
            if any(w in label for w in ("总得分", "总分", "测评", "报告", "结果")):
                continue
            items.append({
                "label": label,
                "value": val,
                "mean": mean,
                "unit": unit,
                "grade": "",
                "notes": sub_title,
                "page": page_num,
                "pdf": pdf_title,
                "source": "pattern2",
            })

        # 模式 3: "NO.1: XX型 X分" （Holland 职业兴趣）
        m3 = re.match(r"^NO\.?\s*\d+[：:]\s*([\u4e00-\u9fffA-Za-z]{2,20})\s+(\d+(?:\.\d+)?)\s*(分)?$", line)
        if m3:
            val = float(m3.group(2)) if "." in m3.group(2) else int(m3.group(2))
            items.append({
                "label": m3.group(1),
                "value": val,
                "mean": None,
                "unit": "分",
                "grade": "",
                "notes": sub_title,
                "page": page_num,
                "pdf": pdf_title,
                "source": "pattern3",
            })

        # 模式 4: 总分描述
        m4 = re.search(
            r"([\u4e00-\u9fff]{2,10}).*?总得分[：:是为]{0,3}\s*(\d+(?:\.\d+)?)\s*分"
            r"(?:[^\n]{0,100}同龄人.*?平均分[：:是为]{0,3}\s*(\d+(?:\.\d+)?))?",
            sent,
        )
        if m4:
            label = m4.group(1) + "总分"
            val = float(m4.group(2)) if "." in m4.group(2) else int(m4.group(2))
            mean = None
            if m4.group(3):
                mean = float(m4.group(3)) if "." in m4.group(3) else int(m4.group(3))
            items.append({
                "label": label,
                "value": val,
                "mean": mean,
                "unit": "分",
                "grade": "",
                "notes": sub_title,
                "page": page_num,
                "pdf": pdf_title,
                "source": "pattern4",
            })

        i += 1

    # 模式 5: 段落级 "身高"、"体重" 等特殊指标
    full_text = " ".join(lines)

    patterns_5 = [
        (r"身高[^\d]*(\d+(?:\.\d+)?)\s*(cm|CM)", "身高"),
        (r"体重[^\d]*(\d+(?:\.\d+)?)\s*(kg|KG)", "体重"),
        (r"BMI[^\d]*(\d+(?:\.\d+)?)", "BMI"),
        (r"运动习惯.*?(\d+(?:\.\d+)?)\s*小时", "运动习惯（每周小时）"),
        (r"睡眠习惯.*?(\d+(?:\.\d+)?)\s*小时", "睡眠习惯（每天小时）"),
    ]
    for pat, label in patterns_5:
        m = re.search(pat, full_text, re.IGNORECASE)
        if m:
            val = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
            unit = m.group(2) if m.lastindex > 1 else ""
            if not unit:
                if "身高" in label:
                    unit = "cm"
                elif "体重" in label:
                    unit = "kg"
                elif "小时" in label:
                    unit = "小时"
            items.append({
                "label": label,
                "value": val,
                "mean": None,
                "unit": unit,
                "grade": "",
                "notes": sub_title,
                "page": page_num,
                "pdf": pdf_title,
                "source": "pattern5",
            })

    return items


def process_pdf(pdf_path: Path) -> Tuple[str, str, List[str], List[Dict[str, Any]]]:
    """处理单个 PDF，返回 (标题, 副标题, 所有页面文本, 所有数据项)。"""
    print("  · {}".format(pdf_path.name))
    doc = fitz.open(str(pdf_path))
    pdf_title = pdf_path.stem

    # 从文件名提取标题（如果有）
    m = re.match(r"([A-Z]\d*[\u4e00-\u9fff]+?)(?:[_（(]|$)", pdf_path.stem)
    if m:
        pdf_title = m.group(1).strip()

    all_text: List[str] = []
    all_items: List[Dict[str, Any]] = []
    sub_titles_seen: List[str] = []

    current_sub = pdf_title
    for i, page in enumerate(doc, 1):
        text = page.get_text()
        all_text.append(text)

        # 识别子报告标题
        for line in [l.strip() for l in text.splitlines() if l.strip()][:5]:
            if re.match(r"^[\u4e00-\u9fff]{2,20}(?:测评)?报告\s*$", line):
                current_sub = line.replace("测评报告", "报告")
                if current_sub not in sub_titles_seen:
                    sub_titles_seen.append(current_sub)
                break

        items = parse_page_text(text, i, pdf_title, current_sub)
        all_items.extend(items)

    fallback = sub_titles_seen[0] if sub_titles_seen else pdf_title
    print("    → 主标题: {}".format(pdf_title))
    print("    → 子报告: {}".format(sub_titles_seen))
    print("    → 数据项: {}".format(len(all_items)))
    doc.close()
    return pdf_title, fallback, all_text, all_items


def merge_and_clean(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """合并同一 label 的多个数据点，去除噪音。"""
    by_label: Dict[str, Dict[str, Any]] = {}

    for it in items:
        label = str(it.get("label", "")).strip()
        if not label or len(label) < 2:
            continue
        # 过滤明显的噪音
        if any(w in label for w in ("报告", "测评", "第", "姓名", "学校", "测试", "档案", "编码")):
            continue

        if label not in by_label:
            by_label[label] = {
                "label": label,
                "value": it.get("value"),
                "mean": it.get("mean"),
                "unit": it.get("unit", ""),
                "grade": it.get("grade", ""),
                "notes": it.get("notes", ""),
                "page": it.get("page"),
                "pdf": it.get("pdf", ""),
                "sources": [it.get("source", "")],
            }
        else:
            # 合并：如果已有 value 但新的有 mean，补充 mean
            existing = by_label[label]
            if existing.get("value") is None and it.get("value") is not None:
                existing["value"] = it["value"]
            if existing.get("mean") is None and it.get("mean") is not None:
                existing["mean"] = it["mean"]
            if not existing.get("unit") and it.get("unit"):
                existing["unit"] = it["unit"]
            existing["sources"].append(it.get("source", ""))
            if existing.get("pdf") and it.get("pdf") and existing["pdf"] != it["pdf"]:
                existing["pdf"] = existing["pdf"] + " | " + it["pdf"]

    # 最终过滤：value 必须是数字
    result = []
    for label, item in by_label.items():
        if item.get("value") is None:
            continue
        # 去掉只提取了 sources 字段的辅助条目
        if "sources" in item:
            del item["sources"]
        result.append(item)

    # 按 PDF 分组排序
    result.sort(key=lambda x: (str(x.get("pdf", "")), str(x.get("label", ""))))
    return result


def main() -> int:
    pdfs = sorted(INPUT_DIR.glob("*.pdf"))
    if not pdfs:
        print("ERROR: no PDFs in", INPUT_DIR)
        return 1

    print("Found {} PDFs\n".format(len(pdfs)))

    all_text_blobs: List[str] = []
    all_items: List[Dict[str, Any]] = []
    pdf_titles: List[str] = []

    for pdf in pdfs:
        title, fallback, texts, items = process_pdf(pdf)
        all_text_blobs.extend(texts)
        if title not in pdf_titles:
            pdf_titles.append(title)
        all_items.extend(items)

    # 学生信息
    student = extract_student_info(all_text_blobs)
    print("\n[学生信息]")
    for k, v in student.items():
        print("  {:<15s} {}".format(k, v))

    # 按 PDF 分组并合并去重
    print("\n[数据合并]")
    print("  原始数据项: {}".format(len(all_items)))
    merged = merge_and_clean(all_items)
    print("  合并后: {}".format(len(merged)))

    # 按 PDF 分组输出
    print("\n[最终结果]")
    by_pdf: Dict[str, List[Dict[str, Any]]] = {}
    for item in merged:
        pdf = item.get("pdf", "")
        if pdf not in by_pdf:
            by_pdf[pdf] = []
        by_pdf[pdf].append(item)

    for pdf, items in sorted(by_pdf.items()):
        print("\n  [{}] - {} 项".format(pdf, len(items)))
        for it in items:
            val = str(it.get("value")) if it.get("value") is not None else "-"
            mean = str(it.get("mean")) if it.get("mean") is not None else "-"
            print("    {:<30s} {:>10s} {:<4s} (avg: {:>10s}) [{}]".format(
                str(it.get("label", "?"))[:28],
                val,
                str(it.get("unit", "")),
                mean,
                str(it.get("notes", ""))[:20],
            ))

    # 组织成 sections
    sections = []
    for pdf_title in pdf_titles:
        sec_items = [it for it in merged if it.get("pdf") and pdf_title in str(it.get("pdf", ""))]
        if sec_items:
            sections.append({
                "title": pdf_title,
                "subtitle": pdf_title.upper() if pdf_title else "",
                "groups": [{
                    "name": "主要指标",
                    "items": sec_items,
                }],
            })

    # 保存 JSON
    report = {
        "student": student,
        "pdf_titles": pdf_titles,
        "total_metrics": len(merged),
        "sections": sections,
        "flat_metrics": merged,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n[DONE] Saved to {}".format(OUTPUT_PATH))
    return 0


if __name__ == "__main__":
    main()
