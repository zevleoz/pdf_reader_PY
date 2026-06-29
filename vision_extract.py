"""用 GPT-4o Vision 从 PDF 图片中提取结构化数据。"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent
PAGES_DIR = BASE_DIR / "pages"
DATA_DIR = BASE_DIR / "data"
VISION_DIR = BASE_DIR / "vision_results"
for d in (DATA_DIR, VISION_DIR):
    d.mkdir(exist_ok=True)

SYS_PROMPT = """你是一个严谨的评估报告数据提取助手。

从测评报告的图片中提取所有数值型数据。输出严格 JSON 格式:

{
  "student": {"name": "...", "grade": "...", "school": "..."},
  "metrics": [
    {"label": "情绪稳定性总分", "value": 43.5, "mean": 40, "unit": "分", "grade": "", "notes": "核心素养"},
    {"label": "感知觉", "value": 92, "mean": null, "unit": "%", "grade": "", "notes": ""}
  ]
}

规则:
- value = 学生本人的得分(必须是数字)
- mean = 同龄人/平均/参考分(有则填数字,没有则 null)
- unit = 单位("分", "%", "cm", "kg", "小时")
- grade = 文本性档位(如 "偏高", "良好", "4", etc.,没有则留 "")
- notes = 该指标所在的分组/章节名称
- 只提取数值型数据(雷达图、柱状图、得分数字),不要提取描述性文字
- 严格 JSON 格式,不要 Markdown 代码块符号,不要解释性文字
- label 要简短准确
"""


def encode_image(image_path: Path) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def call_gpt4o(pdf_title: str, batch: List[Path]) -> Dict[str, Any]:
    from openai import OpenAI
    client = OpenAI()
    img_msgs = []
    for p in batch:
        img_msgs.append({
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64," + encode_image(p)},
        })
    page_names = ", ".join(p.name for p in batch)
    messages = [
        {"role": "system", "content": SYS_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "PDF: " + pdf_title + "，pages: " + page_names + "。请从这些页面提取所有数值型数据。"},
                *img_msgs,
            ],
        },
    ]
    r = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.0,
        response_format={"type": "json_object"},
        max_tokens=4096,
    )
    content = r.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        content = content.strip().strip("`")
        if content.startswith("json"):
            content = content[4:]
        return json.loads(content.strip())


def extract_from_pdf(pdf_title: str, pages_dir: Path) -> Dict[str, Any]:
    page_paths = sorted(pages_dir.glob("page_*.png"))
    if not page_paths:
        return {"student": {}, "metrics": []}

    metrics: List[Dict[str, Any]] = []
    student: Dict[str, str] = {}
    batch_size = 3
    for start in range(0, len(page_paths), batch_size):
        batch = page_paths[start:start + batch_size]
        names = [p.name for p in batch]
        print("  batch {}: {}".format(start // batch_size + 1, names))
        try:
            data = call_gpt4o(pdf_title, batch)
        except Exception as e:
            print("  [ERROR] {}".format(e))
            continue
        if isinstance(data.get("student"), dict):
            for k, v in data["student"].items():
                if v and v != "—":
                    student[k] = v
        if isinstance(data.get("metrics"), list):
            for m in data["metrics"]:
                if m.get("label"):
                    m["_pdf"] = pdf_title
                    metrics.append(m)
    return {"student": student, "metrics": metrics}


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: 请设置环境变量 OPENAI_API_KEY")
        print("       export OPENAI_API_KEY=sk-...")
        print("       然后重新运行: python vision_extract.py")
        return 1

    all_pages_dirs = sorted(PAGES_DIR.iterdir())
    all_pages_dirs = [d for d in all_pages_dirs if d.is_dir()]
    if not all_pages_dirs:
        print("ERROR: pages/ 目录下没有子目录。请先运行 python _convert_images.py")
        return 1

    print("Found {} PDFs (images already generated)".format(len(all_pages_dirs)))

    all_student: Dict[str, str] = {}
    all_metrics: List[Dict[str, Any]] = []

    for pages_dir in all_pages_dirs:
        stem = pages_dir.name
        print("\n=== {} ===".format(stem))
        result = extract_from_pdf(stem, pages_dir)
        if result.get("student"):
            all_student.update(result["student"])
        for m in result.get("metrics", []):
            all_metrics.append(m)
        print("  extracted: {} metrics".format(len(result.get("metrics", []))))
        (VISION_DIR / (stem + ".json")).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print("\n=== Summary ===")
    print("Student info: {}".format(all_student))
    print("Total raw metrics: {}".format(len(all_metrics)))

    # Dedupe by label
    seen: Dict[str, Dict[str, Any]] = {}
    for m in all_metrics:
        key = str(m.get("label", "")).strip()
        if not key:
            continue
        if key not in seen:
            seen[key] = dict(m)
        else:
            if seen[key].get("value") is None and m.get("value") is not None:
                seen[key]["value"] = m["value"]
            if seen[key].get("mean") is None and m.get("mean") is not None:
                seen[key]["mean"] = m["mean"]

    unique = list(seen.values())
    unique.sort(key=lambda x: x.get("label", ""))
    print("Unique metrics: {}".format(len(unique)))

    print("\n[Data Preview]")
    for m in unique[:50]:
        print("  {:<30s} {:>8s} {:<4s} (avg: {:>8s}) [{:s}]".format(
            str(m.get("label", "?"))[:28],
            str(m.get("value")) if m.get("value") is not None else "-",
            str(m.get("unit", "")),
            str(m.get("mean")) if m.get("mean") is not None else "-",
            str(m.get("_pdf", ""))[:20],
        ))

    summary = {
        "student": all_student,
        "metrics": unique,
        "by_pdf_count": len(all_pages_dirs),
    }
    out_path = DATA_DIR / "vision_report_data.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n[DONE] {}".format(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
