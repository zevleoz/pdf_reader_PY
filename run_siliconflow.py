"""
SiliconFlow API - Qwen3-VL-32B 数据提取
===========================================
Endpoint: https://api.siliconflow.com/v1
Model:    Qwen/Qwen3-VL-32B-Instruct
"""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List

import fitz

INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
DATA_DIR = Path("data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

API_KEY = "sk-eefqofgkmjohvjlbjevxeomtcoahqigghfwrjrhfyfxcpbaf"
ENDPOINT = "https://api.siliconflow.com/v1/chat/completions"
MODEL = "Qwen/Qwen3-VL-32B-Instruct"

SYSTEM_PROMPT = """你是一个专业的 PDF 报告数据提取助手。你需要从图片中精确提取结构化数据。

分析规则:
1. 仔细阅读图表中的所有中文标签和数值
2. 区分"我的得分"和"同龄人平均分"或"平均值"
3. 柱状图的数值通常在柱形顶部或横轴
4. 百分比（%）和分数要明确区分
5. 提取 BMI、身高、体重等体检数据
6. 如果不确定数值，标注 "uncertain": true
7. 忽略纯装饰性文字"""

USER_PROMPT = """请分析这张 PDF 页面，提取所有数字数据。

输出格式要求 —— 严格只输出 JSON，不要任何 Markdown 标记或解释:

{
  "items": [
    {"label": "指标名称", "value": 数值, "unit": "%/分/kg/cm/h", "mean": 平均值或 null}
  ]
}"""


def call_api(image_path: Path) -> str:
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                    {"type": "text", "text": USER_PROMPT},
                ],
            },
        ],
        "temperature": 0.1,
        "max_tokens": 2048,
    }).encode("utf-8")

    req = urllib.request.Request(
        ENDPOINT,
        data=payload,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("choices", [{}])[0].get("message", {}).get("content", "")
    except urllib.error.HTTPError as e:
        return f"ERROR: HTTP {e.code} - {e.read().decode('utf-8', errors='replace')}"
    except Exception as e:
        return f"ERROR: {e}"


def pdf_pages_to_images(pdf_path: Path, page_nums: List[int], dpi: int = 200) -> List[Path]:
    doc = fitz.open(str(pdf_path))
    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    out_dir = OUTPUT_DIR / "images"
    out_dir.mkdir(exist_ok=True)
    paths = []
    for p in page_nums:
        if 1 <= p <= len(doc):
            pix = doc[p - 1].get_pixmap(matrix=mat, alpha=False)
            out_path = out_dir / f"{pdf_path.stem}_page{p:02d}.png"
            pix.save(str(out_path))
            paths.append(out_path)
    doc.close()
    return paths


def parse_response(response: str) -> List[Dict[str, Any]]:
    cleaned = re.sub(r"```(?:json)?\s*|```\s*", "", response, flags=re.IGNORECASE).strip()

    # 策略 1: 完整 JSON
    for candidate in _gen_candidates(cleaned):
        try:
            data = json.loads(candidate)
            items = _extract_items(data)
            if items:
                return items
        except json.JSONDecodeError:
            continue

    # 策略 2: 正则 fallback
    return _fallback_regex(response)


def _gen_candidates(text: str) -> List[str]:
    cands = [text]
    if "{" in text and "}" in text:
        # 找最外层花括号
        depth = 0
        start = text.find("{")
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    cands.append(text[start:i + 1])
                    break
    if "[" in text and "]" in text:
        start = text.find("[")
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    cands.append(text[start:i + 1])
                    break
    return cands


def _extract_items(data: Any) -> List[Dict[str, Any]]:
    items = []
    if isinstance(data, dict):
        if "items" in data and isinstance(data["items"], list):
            items.extend(data["items"])
        elif "label" in data and "value" in data:
            items.append(data)
        else:
            for v in data.values():
                if isinstance(v, (dict, list)):
                    items.extend(_extract_items(v))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "label" in item and "value" in item:
                items.append(item)
            elif isinstance(item, (dict, list)):
                items.extend(_extract_items(item))
    return items


def _fallback_regex(text: str) -> List[Dict[str, Any]]:
    items = []
    seen = set()
    for m in re.finditer(r'"([\u4e00-\u9fff][\u4e00-\u9fff\-]{0,30})"\s*[:：]\s*(\d+(?:\.\d+)?)', text):
        label = m.group(1).strip()
        if label not in seen:
            seen.add(label)
            items.append({"label": label, "value": float(m.group(2)), "unit": ""})
    if not items:
        for m in re.finditer(r"([\u4e00-\u9fff]{2,10})\s*[:：]\s*(\d+(?:\.\d+)?)", text):
            val = float(m.group(2))
            if 0 <= val <= 500:
                label = m.group(1).strip()
                if label not in seen and len(label) >= 2:
                    seen.add(label)
                    items.append({"label": label, "value": val, "unit": ""})
    return items


def merge_with_existing(api_items: List[Dict[str, Any]]) -> None:
    existing_path = DATA_DIR / "clean_report_data.json"
    if not existing_path.exists():
        return
    try:
        with open(existing_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        existing_labels = {item["label"] for item in existing.get("items", [])}
        new_items = [
            it for it in api_items
            if it.get("label") and it["label"] not in existing_labels
        ]
        merged = {
            "student": existing.get("student", {}),
            "text_items": existing.get("items", []),
            "vision_items": new_items,
            "total_items": len(existing.get("items", [])) + len(new_items),
            "summary": f"文本 {len(existing.get('items',[]))} 项 + 视觉 {len(new_items)} 项",
        }
        out = DATA_DIR / "final_merged_report.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        print(f"\n📊 合并: {out}")
        print(f"   文本: {len(existing.get('items',[]))} 项")
        print(f"   视觉新增: {len(new_items)} 项")
        print(f"   总计: {merged['total_items']} 项")
    except Exception as e:
        print(f"\n⚠️ 合并失败: {e}")


def main() -> None:
    print("=" * 70)
    print(f"🤖 SiliconFlow API - {MODEL}")
    print(f"   Endpoint: {ENDPOINT}")
    print("=" * 70)

    # 准备图表密集页
    target_pages = {
        "A2*.pdf": [5, 9, 11],
        "B4*.pdf": [4, 11],
    }

    print("\n📄 准备 PDF 页面:")
    all_images: List[Path] = []
    for glob_pat, pages in target_pages.items():
        pdfs = sorted(INPUT_DIR.glob(glob_pat))
        if pdfs:
            imgs = pdf_pages_to_images(pdfs[0], pages)
            all_images.extend(imgs)
            for img in imgs:
                print(f"  ✅ {pdfs[0].name} -> {img.name}")

    if not all_images:
        print("  ❌ 未找到 PDF 文件")
        return

    print(f"\n🤖 分析 {len(all_images)} 张图表页面...")

    all_items: List[Dict[str, Any]] = []
    start_time = time.time()

    for idx, img in enumerate(all_images, 1):
        print(f"\n  [{idx}/{len(all_images)}] {img.name}")
        print("       请求 API... ", end="", flush=True)
        response = call_api(img)

        if response.startswith("ERROR"):
            print(f"❌ {response[:100]}")
            continue

        items = parse_response(response)
        if items:
            all_items.extend(items)
            print(f"✅ {len(items)} 项")
            preview = ", ".join(f"{it.get('label','?')}:{it.get('value','?')}" for it in items[:3])
            if len(items) > 3:
                preview += "..."
            print(f"       [{preview}]")
        else:
            print("⚠️ 未解析到结构化数据")
            preview = response.replace("\n", " ")[:120]
            print(f"       [{preview}]")

        time.sleep(1.5)  # 速率限制

    elapsed = time.time() - start_time

    # 保存
    output = {
        "provider": "SiliconFlow",
        "model": MODEL,
        "items": all_items,
        "total_items": len(all_items),
        "elapsed_seconds": round(elapsed, 1),
        "source_images": [p.name for p in all_images],
    }
    out_path = DATA_DIR / "api_extracted_data.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 70}")
    print(f"✅ 完成! 提取 {len(all_items)} 项，用时 {elapsed:.1f}s")
    print(f"   保存: {out_path}")

    merge_with_existing(all_items)
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
