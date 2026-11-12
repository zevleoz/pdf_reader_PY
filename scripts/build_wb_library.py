"""一次性构建 World Bank SEL 参考资料（数据不入库）。

用法（仓库根目录）::

    python -I scripts/build_wb_library.py --xlsx <path> --pdf-dir <dir> --out m1/kb/private

读取 ``M1_WorldBank_Reference.xlsx`` 的 01/03/04 三张表与 G5–G9 教师手册，
写出 ``wb_index.json`` 与 ``wb_lessons.json``，并在 stdout 打印构建报告。
匹配不上的行不会被猜测，只进入 ``problems``。

依赖 ``openpyxl`` 与 ``PyMuPDF``，只在开发机运行，不进服务端依赖。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

VERSION = "V1.1"
HEADER_ROW = 4

R4_KB_PATH = BASE_DIR / "m1" / "kb" / "r4_abilities.json"

SHEET_PREFIX = {
    "r4": "01_R4能力映射",
    "lessons": "03_WB课程索引",
    "by_age": "04_R4分龄参考",
}

_SECTION_START = {
    "REFERENCES", "BIBLIOGRAPHY", "ANNEX", "APPENDIX", "GLOSSARY",
    "INDEX", "ACKNOWLEDGEMENTS", "ACKNOWLEDGMENTS", "ABOUT",
}


# ---------------------------------------------------------------- 文本工具

def _text(value) -> str:
    return str(value if value is not None else "").strip()


def _fold(value) -> str:
    """课名比较：统一引号、压缩空白、忽略大小写。"""
    text = _text(value)
    for source, target in (
        ("\u2018", "'"), ("\u2019", "'"), ("\u201b", "'"),
        ("\u201c", '"'), ("\u201d", '"'),
    ):
        text = text.replace(source, target)
    return re.sub(r"\s+", " ", text).strip().casefold()


def names_match(left, right) -> bool:
    """课名是否一致（去空白、忽略大小写与引号形态）。"""
    folded = _fold(left)
    return bool(folded) and folded == _fold(right)


def _norm_header(value) -> str:
    return re.sub(r"\s+", "", _text(value)).lower()


def parse_int(value):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number


def parse_grade_cell(value):
    """年级单元格 → 数字（``G5``、``5``、``5年级``、``五年级``）。"""
    text = _text(value)
    if not text:
        return None
    match = re.match(r"^g\s*(\d{1,2})$", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    if re.fullmatch(r"\d{1,2}", text):
        return int(text)
    from m1 import wb  # 复用 lookup 模块的中文年级解析

    return wb.grade_from_text(text)


def parse_source_ref(value):
    """``G5.pdf · PDF p.39 · 书内 p.41`` → ``{pdf, pdf_page, book_page}``。"""
    text = _text(value)
    pdf_match = re.search(r"([^\s·/]+\.pdf)", text, re.IGNORECASE)
    page_match = re.search(r"PDF\s*p\.?\s*(\d+)", text, re.IGNORECASE)
    if not pdf_match or not page_match:
        return None
    book_match = re.search(r"书内\s*p\.?\s*(\d+)", text)
    return {
        "pdf": pdf_match.group(1),
        "pdf_page": int(page_match.group(1)),
        "book_page": int(book_match.group(1)) if book_match else None,
    }


# ---------------------------------------------------------------- 表格读取

def sheet_by_prefix(workbook, prefix: str):
    for name in workbook.sheetnames:
        if name.startswith(prefix):
            return workbook[name]
    return None


def require_sheet(workbook, prefix: str):
    worksheet = sheet_by_prefix(workbook, prefix)
    if worksheet is None:
        raise SystemExit("找不到工作表 %s" % prefix)
    return worksheet


def header_columns(worksheet, row: int = HEADER_ROW):
    """表头（第 4 行）→ ``{规范化表头: 列号}``。"""
    columns = {}
    for cell in worksheet[row]:
        key = _norm_header(cell.value)
        if key:
            columns[key] = cell.column
    return columns


def find_column(columns, exact=(), contains=(), exclude=()):
    for name in exact:
        key = _norm_header(name)
        if key in columns:
            return columns[key]
    for name in contains:
        key = _norm_header(name)
        for header, index in columns.items():
            if key in header and not any(_norm_header(term) in header for term in exclude):
                return index
    return None


def _cell(row, column):
    if not column:
        return None
    return row[column - 1] if column - 1 < len(row) else None


def read_lesson_rows(worksheet):
    """sheet 03 → 课程行（带行号）。"""
    columns = header_columns(worksheet)
    layout = {
        "id": find_column(columns, ("Lesson ID",), ("lessonid",)),
        "grade": find_column(columns, ("Grade",), ("grade",), exclude=("SEL",)),
        "skill": find_column(columns, ("SEL Specific Skill",), ("sel",)),
        "no": find_column(columns, ("Lesson No.",), ("lessonno",)),
        "name": find_column(columns, ("原始课名（英文）",), ("原始课名",)),
        "objective": find_column(columns, ("原始学习目标（英文）",), ("原始学习目标",)),
        "pdf": find_column(columns, ("来源 PDF", "来源PDF"), ("来源pdf",)),
        "pdf_page": find_column(columns, ("PDF页码",), ("pdf页码",)),
        "book_page": find_column(columns, ("书内页码",), ("书内页码",)),
    }
    missing = [key for key, column in layout.items() if not column]
    if missing:
        raise ValueError("sheet 03 缺少列：%s" % ", ".join(missing))
    rows = []
    for offset, row in enumerate(worksheet.iter_rows(min_row=HEADER_ROW + 1, values_only=True)):
        wb_id = _text(_cell(row, layout["id"]))
        if not wb_id:
            continue
        rows.append({
            "row": HEADER_ROW + 1 + offset,
            "id": wb_id,
            "grade": parse_grade_cell(_cell(row, layout["grade"])),
            "skill": _text(_cell(row, layout["skill"])),
            "no": parse_int(_cell(row, layout["no"])),
            "name": _text(_cell(row, layout["name"])),
            "objective": _text(_cell(row, layout["objective"])),
            "pdf": _text(_cell(row, layout["pdf"])),
            "pdf_page": parse_int(_cell(row, layout["pdf_page"])),
            "book_page": parse_int(_cell(row, layout["book_page"])),
        })
    return rows


def read_r4_rows(worksheet):
    """sheet 01 → ``{code: {name, focus, boundary}}`` 与按行问题。"""
    columns = header_columns(worksheet)
    layout = {
        "code": find_column(columns, ("R4编号",), ("r4编号",)),
        "name": find_column(columns, ("R4能力",), ("r4能力",), exclude=("说明",)),
        "focus": find_column(columns, ("R4教学关注点",), ("教学关注点",)),
        "boundary": find_column(columns, ("参考边界 / 个性化延伸",), ("参考边界",)),
    }
    missing = [key for key, column in layout.items() if not column]
    if missing:
        raise ValueError("sheet 01 缺少列：%s" % ", ".join(missing))
    out, problems = {}, []
    for offset, row in enumerate(worksheet.iter_rows(min_row=HEADER_ROW + 1, values_only=True)):
        code = _text(_cell(row, layout["code"]))
        name = _text(_cell(row, layout["name"]))
        if not code and not name:
            continue
        if not code:
            problems.append("01 第%d行 缺少 R4编号，跳过" % (HEADER_ROW + 1 + offset))
            continue
        out[code] = {
            "name": name,
            "focus": _text(_cell(row, layout["focus"])),
            "boundary": _text(_cell(row, layout["boundary"])),
            "by_grade": {},
        }
    return out, problems


def read_by_age_rows(worksheet):
    """sheet 04 → 分龄参考行（带行号）。"""
    columns = header_columns(worksheet)
    layout = {
        "code": find_column(columns, ("R4编号",), ("r4编号",)),
        "grade": find_column(columns, ("年级",), ("年级",)),
        "skill": find_column(columns, ("关联 WB 技能", "关联WB技能"), ("关联wb",)),
        "name": find_column(columns, ("参考课程名称",), ("参考课程名称",)),
        "objective": find_column(columns, ("原教材学习目标（英文）",), ("原教材学习目标",)),
        "source": find_column(columns, ("来源及页码",), ("来源及页码",)),
        "match": find_column(columns, ("参考匹配程度 / 限制",), ("参考匹配程度",)),
        "limit": find_column(columns, ("教材适用边界 / 可延伸点",), ("教材适用边界",)),
    }
    missing = [key for key, column in layout.items() if not column]
    if missing:
        raise ValueError("sheet 04 缺少列：%s" % ", ".join(missing))
    rows = []
    for offset, row in enumerate(worksheet.iter_rows(min_row=HEADER_ROW + 1, values_only=True)):
        code = _text(_cell(row, layout["code"]))
        if not code:
            continue
        rows.append({
            "row": HEADER_ROW + 1 + offset,
            "code": code,
            "grade": parse_grade_cell(_cell(row, layout["grade"])),
            "skill": _text(_cell(row, layout["skill"])),
            "name": _text(_cell(row, layout["name"])),
            "objective": _text(_cell(row, layout["objective"])),
            "source": _text(_cell(row, layout["source"])),
            "match": _text(_cell(row, layout["match"])),
            "limit": _text(_cell(row, layout["limit"])),
        })
    return rows


def join_lesson(row, lessons):
    """把 sheet 04 行关联到课程：``(wb_id, None)`` 或 ``(None, 问题说明)``。

    ``lessons`` 为 ``{wb_id: {grade, pdf, pdf_page, name, …}}``。
    """
    grade = row.get("grade")
    if grade is None:
        return None, "年级无法解析"
    ref = parse_source_ref(row.get("source"))
    if ref is None:
        return None, "来源及页码无法解析"
    same_page = [
        wb_id for wb_id, entry in lessons.items()
        if entry.get("grade") == grade
        and _text(entry.get("pdf")).lower() == ref["pdf"].lower()
        and entry.get("pdf_page") == ref["pdf_page"]
    ]
    if not same_page:
        return None, "没有同年级同页课程（%s p.%d）" % (ref["pdf"], ref["pdf_page"])
    for wb_id in same_page:
        if names_match(row.get("name"), lessons[wb_id].get("name")):
            return wb_id, None
    return None, "课名不符：%s ≠ %s" % (
        row.get("name"), " / ".join(lessons[wb_id].get("name") or "" for wb_id in same_page))


# ---------------------------------------------------------------- PDF 读取

def normalise_whitespace(text: str) -> str:
    lines = [line.replace("\u00a0", " ").rstrip() for line in str(text or "").splitlines()]
    joined = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", joined).strip()


def first_line(page) -> str:
    for line in (page.get_text("text") or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def looks_like_section_start(line: str) -> bool:
    words = re.findall(r"[A-Za-z]+", str(line or "").upper())
    return bool(words) and words[0] in _SECTION_START


def _has_content(page) -> bool:
    """页面有正文（排除空白页和只有页码的页脚页）。"""
    lines = [line.strip() for line in (page.get_text("text") or "").splitlines() if line.strip()]
    if not lines:
        return False
    return not (len(lines) == 1 and re.fullmatch(r"page\s+\d+", lines[0], re.IGNORECASE))


def last_lesson_end(document, start_page: int):
    """最后一课的结束页与依据。"""
    total = document.page_count
    for page_no in range(start_page + 1, total + 1):
        line = first_line(document[page_no - 1])
        if looks_like_section_start(line):
            return page_no - 1, "p.%d 首行为非课文小节：%s" % (page_no, line[:60])
    try:
        toc_pages = sorted({
            page for _level, _title, page in document.get_toc(simple=True)
            if isinstance(page, int) and start_page < page <= total
        })
    except Exception:  # 目录损坏时退回 PDF 末页
        toc_pages = []
    if toc_pages:
        return min(toc_pages) - 1, "目录下一节始于 p.%d" % min(toc_pages)
    end = total
    while end > start_page and not _has_content(document[end - 1]):
        end -= 1
    if end == total:
        return total, "到 PDF 末页"
    return end, "PDF 末页为空白/页码页（p.%d–p.%d），止于 p.%d" % (end + 1, total, end)


def page_text(document, start: int, end: int) -> str:
    parts = [document[page - 1].get_text("text") for page in range(start, end + 1)]
    return normalise_whitespace("\n\n".join(parts))


# ---------------------------------------------------------------- 构建

def _assign_end_pages(lessons):
    """非最后一课：下一课起始页 − 1。"""
    grouped = {}
    for wb_id, entry in lessons.items():
        if entry.get("pdf") and entry.get("pdf_page"):
            grouped.setdefault(entry["pdf"].lower(), []).append((entry["pdf_page"], wb_id))
    for entries in grouped.values():
        entries.sort()
        for (page, wb_id), (next_page, _) in zip(entries, entries[1:]):
            lessons[wb_id]["end_page"] = next_page - 1
        lessons[entries[-1][1]]["end_page"] = None


def build(xlsx_path, pdf_dir, out_dir):
    from openpyxl import load_workbook

    problems = []
    workbook = load_workbook(xlsx_path, data_only=True)
    kb = json.loads(R4_KB_PATH.read_text(encoding="utf-8"))
    kb_names = {item["code"]: item["name"] for item in kb.get("abilities") or []}

    sheet_lessons = require_sheet(workbook, SHEET_PREFIX["lessons"])
    sheet_r4 = require_sheet(workbook, SHEET_PREFIX["r4"])
    sheet_by_age = require_sheet(workbook, SHEET_PREFIX["by_age"])

    # 课程索引
    lessons = {}
    for row in read_lesson_rows(sheet_lessons):
        if row["id"] in lessons:
            problems.append("03 第%d行 课程编号重复：%s" % (row["row"], row["id"]))
            continue
        if not row["grade"] or not row["pdf_page"] or not row["name"]:
            problems.append("03 第%d行 缺少年级/页码/课名：%s" % (row["row"], row["id"]))
            continue
        lessons[row["id"]] = {
            "grade": row["grade"],
            "skill": row["skill"],
            "no": row["no"],
            "name": row["name"],
            "objective": row["objective"],
            "pdf": row["pdf"],
            "pdf_page": row["pdf_page"],
            "book_page": row["book_page"],
            "end_page": None,
            "has_text": False,
        }
    _assign_end_pages(lessons)

    # R4 映射
    r4, r4_problems = read_r4_rows(sheet_r4)
    problems.extend(r4_problems)
    for code, entry in r4.items():
        if code not in kb_names:
            raise SystemExit("sheet 01 的 %s 不在 m1/kb/r4_abilities.json 中" % code)
        if entry["name"] != kb_names[code]:
            raise SystemExit(
                "R4 能力名不一致：%s 表中为「%s」，知识库为「%s」" % (code, entry["name"], kb_names[code]))
    missing_codes = [code for code in kb_names if code not in r4]
    if missing_codes:
        problems.append("sheet 01 未覆盖：%s" % "、".join(missing_codes))

    # 分龄参考 → 关联课程
    by_age = read_by_age_rows(sheet_by_age)
    joined = 0
    for row in by_age:
        wb_id, reason = join_lesson(row, lessons)
        if wb_id is None:
            problems.append("04 第%d行 %s：%s" % (row["row"], reason, row["source"] or row["name"]))
            continue
        entry = r4.get(row["code"])
        if entry is None:
            problems.append("04 第%d行 的 R4 编号 %s 不在 sheet 01" % (row["row"], row["code"]))
            continue
        entry["by_grade"].setdefault(str(row["grade"]), []).append({
            "lesson": wb_id,
            "match": row["match"],
            "limit": row["limit"],
        })
        joined += 1

    # 课文原文
    try:
        import fitz
    except ImportError:
        raise SystemExit("缺少 PyMuPDF（fitz），请在装有该库的开发机运行")
    texts = {}
    cuts = []
    documents = {}
    for entry in lessons.values():
        name = entry["pdf"]
        if not name:
            problems.append("%s 缺少来源 PDF" % entry.get("name"))
            continue
        if name not in documents:
            path = Path(pdf_dir) / name
            if not path.exists():
                problems.append("找不到 PDF：%s" % path)
                documents[name] = None
            else:
                documents[name] = fitz.open(str(path))
        document = documents[name]
        if document is None:
            continue
        if entry["end_page"] is None:
            end_page, reason = last_lesson_end(document, entry["pdf_page"])
            entry["end_page"] = end_page
            cuts.append((name, entry["pdf_page"], end_page, reason))

    for wb_id, entry in lessons.items():
        document = documents.get(entry["pdf"])
        if document is None or not entry["end_page"]:
            continue
        start, end = entry["pdf_page"], entry["end_page"]
        if end < start or start > document.page_count:
            problems.append("%s 页码越界：p.%d–p.%d" % (wb_id, start, end))
            continue
        text = page_text(document, start, end)
        texts[wb_id] = {"text": text, "pages": [start, end], "chars": len(text)}
        head = page_text(document, start, start)
        if not _fold(entry["name"]) or _fold(entry["name"]) not in _fold(head):
            problems.append("%s 首页未见课名「%s」" % (wb_id, entry["name"]))
        elif len(text) < 500:
            problems.append("%s 课文字符数不足 500（%d）" % (wb_id, len(text)))
        else:
            entry["has_text"] = True

    for document in documents.values():
        if document is not None:
            document.close()

    index = {
        "version": VERSION,
        "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "lessons": lessons,
        "r4": r4,
        "problems": problems,
    }

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "wb_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "wb_lessons.json").write_text(
        json.dumps(texts, ensure_ascii=False, indent=2), encoding="utf-8")

    return index, texts, cuts


def report(index, cuts, xlsx_path, out_dir):
    lessons = index["lessons"]
    with_text = [wb_id for wb_id, entry in lessons.items() if entry.get("has_text")]
    per_grade = {}
    for entry in lessons.values():
        per_grade[entry["grade"]] = per_grade.get(entry["grade"], 0) + 1
    grade_line = "、".join("G%d %d 条" % (grade, count) for grade, count in sorted(per_grade.items()))
    lines = [
        "World Bank SEL 参考资料构建报告",
        "版本：%s" % index["version"],
        "生成时间：%s" % index["built_at"],
        "输入：%s" % xlsx_path,
        "输出：%s" % (Path(out_dir) / "wb_index.json"),
        "",
        "课程索引：%d 条（%s），有文本 %d，无文本 %d" % (
            len(lessons), grade_line, len(with_text), len(lessons) - len(with_text)),
        "R4 能力：%d 项" % len(index["r4"]),
    ]
    by_age_joined = sum(
        len(rows) for entry in index["r4"].values() for rows in entry["by_grade"].values())
    lines.append("sheet 04：已关联课程 %d 条" % by_age_joined)
    lines.append("")
    lines.append("每个 PDF 最后一课的截断：")
    for name, start, end, reason in cuts:
        lines.append("  %s：p.%d → p.%d（%s）" % (name, start, end, reason))
    lines.append("")
    lines.append("问题（%d）：" % len(index["problems"]))
    if index["problems"]:
        lines.extend("  - %s" % item for item in index["problems"])
    else:
        lines.append("  （无）")
    lines.append("")
    lines.append("注意：说明页提到的 05_教研待确认 工作表不在文件中，已忽略。")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="构建 World Bank SEL 参考资料")
    parser.add_argument("--xlsx", required=True, help="M1_WorldBank_Reference.xlsx")
    parser.add_argument("--pdf-dir", required=True, help="G5.pdf–G9.pdf 所在目录")
    parser.add_argument("--out", required=True, help="输出目录（m1/kb/private）")
    args = parser.parse_args(argv)
    index, texts, cuts = build(args.xlsx, args.pdf_dir, args.out)
    print(report(index, cuts, args.xlsx, args.out))


if __name__ == "__main__":
    main()
