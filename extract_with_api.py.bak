"""
线上视觉 API 集成工具
=======================

支持的提供商:
  [1] 阿里云 DashScope (qwen2.5-vl-72b) — 推荐⭐
  [2] 硅基流动 SiliconFlow (Qwen2.5-VL-72B)
  [3] 智谱 GLM (glm-4v-flash)
  [4] OpenAI (gpt-4o-mini)

使用方式:
  export DASHSCOPE_API_KEY=sk-your-key
  python extract_with_api.py

  或者在运行时输入 API Key
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF

INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
DATA_DIR = Path("data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 数据提取提示词 - 针对 PDF 报告
# ============================================================
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


# ============================================================
# Provider 1: 阿里云 DashScope
# ============================================================
class DashScopeClient:
    def __init__(self, api_key: str, model: str = "qwen2.5-vl-72b-instruct"):
        self.api_key = api_key
        self.model = model
        self.endpoint = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"

    def analyze(self, image_path: Path) -> str:
        import urllib.request

        # 将图片编码为 base64
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        payload = json.dumps({
            "model": self.model,
            "input": {
                "messages": [
                    {"role": "system", "content": [{"text": SYSTEM_PROMPT}]},
                    {
                        "role": "user",
                        "content": [
                            {"image": f"data:image/png;base64,{image_b64}"},
                            {"text": USER_PROMPT},
                        ],
                    },
                ]
            },
            "parameters": {
                "temperature": 0.1,
                "top_p": 0.9,
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                # DashScope 返回格式解析
                content = result.get("output", {}).get("choices", [{}])[0].get("message", {}).get("content", [])
                if isinstance(content, list):
                    text_parts = [c.get("text", "") if isinstance(c, dict) else str(c) for c in content]
                    return "".join(text_parts)
                return str(content)
        except Exception as e:
            return f"ERROR: {e}"


# ============================================================
# Provider 2: 硅基流动 SiliconFlow
# ============================================================
class SiliconFlowClient:
    def __init__(self, api_key: str, model: str = "Qwen/Qwen2.5-VL-72B-Instruct"):
        self.api_key = api_key
        self.model = model
        self.endpoint = "https://api.siliconflow.cn/v1/chat/completions"

    def analyze(self, image_path: Path) -> str:
        import urllib.request

        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        payload = json.dumps({
            "model": self.model,
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
            "max_tokens": 1024,
        }).encode("utf-8")

        req = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as e:
            return f"ERROR: {e}"


# ============================================================
# Provider 3: OpenAI 兼容格式（支持多种提供商）
# ============================================================
class OpenAICompatClient:
    def __init__(self, api_key: str, model: str, endpoint: str):
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint

    def analyze(self, image_path: Path) -> str:
        import urllib.request

        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        payload = json.dumps({
            "model": self.model,
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
            "max_tokens": 1024,
        }).encode("utf-8")

        req = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as e:
            return f"ERROR: {e}"


# ============================================================
# PDF 转图片
# ============================================================
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


# ============================================================
# JSON 解析
# ============================================================
def parse_response(response: str) -> List[Dict[str, Any]]:
    # 清理 Markdown 标记
    cleaned = re.sub(r"```(?:json)?\s*|```\s*", "", response, flags=re.IGNORECASE).strip()

    # 尝试多种解析策略
    for candidate in _generate_candidates(cleaned):
        try:
            data = json.loads(candidate)
            items = _extract_items(data)
            if items:
                return items
        except json.JSONDecodeError:
            continue

    # 回退: 从文本中正则提取 "标签": 数值
    return _fallback_regex(response)


def _generate_candidates(cleaned: str) -> List[str]:
    candidates = [cleaned]
    if "{" in cleaned:
        candidates.append(cleaned[cleaned.find("{"):cleaned.rfind("}") + 1])
    if "[" in cleaned:
        candidates.append(cleaned[cleaned.find("["):cleaned.rfind("]") + 1])
    # 尝试在花括号内查找
    if cleaned.count("{") > 1:
        depth = 0
        start = cleaned.find("{")
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(cleaned[start:i + 1])
                    break
    return candidates


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
    # 匹配 "label": value 形式
    for m in re.finditer(r'"([\u4e00-\u9fff][\u4e00-\u9fff\-]{0,30})"\s*[:：]\s*(\d+(?:\.\d+)?)', text):
        label = m.group(1).strip()
        if label not in seen:
            seen.add(label)
            items.append({"label": label, "value": float(m.group(2)), "unit": ""})
    # 如果上面没找到，尝试 "label ... value" 形式
    if not items:
        for m in re.finditer(r"([\u4e00-\u9fff]{2,10})\s*[:：]\s*(\d+(?:\.\d+)?)", text):
            val = float(m.group(2))
            if 0 <= val <= 500:
                label = m.group(1).strip()
                if label not in seen and len(label) >= 2:
                    seen.add(label)
                    items.append({"label": label, "value": val, "unit": ""})
    return items


# ============================================================
# 主流程
# ============================================================
def get_client(choice: str) -> Optional[Any]:
    """根据用户选择创建 API 客户端"""
    if choice == "1":
        key = os.environ.get("DASHSCOPE_API_KEY") or input("请输入 DashScope API Key: ").strip()
        if not key:
            print("❌ 需要 API Key")
            return None
        return DashScopeClient(key)

    if choice == "2":
        key = os.environ.get("SILICONFLOW_API_KEY") or input("请输入 SiliconFlow API Key: ").strip()
        if not key:
            print("❌ 需要 API Key")
            return None
        return SiliconFlowClient(key)

    if choice == "3":
        key = os.environ.get("ZHIPU_API_KEY") or input("请输入智谱 API Key: ").strip()
        if not key:
            print("❌ 需要 API Key")
            return None
        return OpenAICompatClient(key, "glm-4v-flash", "https://open.bigmodel.cn/api/paas/v4/chat/completions")

    if choice == "4":
        key = os.environ.get("OPENAI_API_KEY") or input("请输入 OpenAI API Key: ").strip()
        if not key:
            print("❌ 需要 API Key")
            return None
        return OpenAICompatClient(key, "gpt-4o-mini", "https://api.openai.com/v1/chat/completions")

    return None


def main() -> None:
    print("=" * 70)
    print("🌐 线上视觉 API 数据提取")
    print("=" * 70)

    # 选择提供商
    print("\n📋 可用 API:")
    print("  [1] 阿里云 DashScope - qwen2.5-vl-72b")
    print("  [2] 硅基流动 SiliconFlow - Qwen2.5-VL-72B")
    print("  [3] 智谱 GLM - glm-4v-flash")
    print("  [4] OpenAI - gpt-4o-mini")

    # 默认自动选择（优先环境变量）
    choice = None
    for i, env_var in enumerate(["DASHSCOPE_API_KEY", "SILICONFLOW_API_KEY", "ZHIPU_API_KEY", "OPENAI_API_KEY"], 1):
        if os.environ.get(env_var):
            choice = str(i)
            print(f"\n  ✅ 自动选择: [{i}] (检测到 {env_var})")
            break

    if not choice:
        choice = input("\n请输入选择 [默认 1]: ").strip() or "1"

    client = get_client(choice)
    if not client:
        print("\n💡 获取 API Key:")
        print("  DashScope: https://dashscope.console.aliyun.com/")
        print("  SiliconFlow: https://cloud.siliconflow.cn/")
        print("  智谱 GLM: https://open.bigmodel.cn/")
        return

    # 选择要分析的页面（只分析含图表的页面）
    print("\n📄 准备 PDF 页面（仅含图表的页面）:")
    target_pages = {
        "A2*.pdf": [5, 9, 11],  # 情绪稳定性, 依恋, 体质健康（含图表）
        "B4*.pdf": [4, 11],     # 认知子指标, 自我概念（含图表）
    }

    all_images: List[Path] = []
    for glob_pat, pages in target_pages.items():
        pdfs = sorted(INPUT_DIR.glob(glob_pat))
        if pdfs:
            imgs = pdf_pages_to_images(pdfs[0], pages, dpi=200)
            all_images.extend(imgs)
            for img in imgs:
                print(f"  ✅ {pdfs[0].name} -> {img.name}")

    if not all_images:
        print("  ❌ 未找到 PDF 文件")
        return

    print(f"\n🤖 调用 API 分析 {len(all_images)} 张图片...")
    print("  (每张约 3-10 秒)\n")

    all_items: List[Dict[str, Any]] = []
    total_cost_estimate = 0.0
    start_time = time.time()

    for idx, img in enumerate(all_images, 1):
        print(f"  [{idx}/{len(all_images)}] {img.name}")
        print("       API 请求中... ", end="", flush=True)
        response = client.analyze(img)

        if response.startswith("ERROR"):
            print(f"❌ {response}")
            continue

        items = parse_response(response)
        if items:
            all_items.extend(items)
            print(f"✅ 提取 {len(items)} 项")
            preview = ", ".join(f"{it.get('label','?')}:{it.get('value','?')}" for it in items[:3])
            if len(items) > 3:
                preview += "..."
            print(f"       [{preview}]")
        else:
            print("⚠️ 未解析到结构化数据")
            print(f"       原始响应片段: {response[:100]}")

        # 节流: 防止触发速率限制
        time.sleep(1)

    elapsed = time.time() - start_time

    # 保存结果
    output = {
        "provider": type(client).__name__,
        "model": getattr(client, "model", "unknown"),
        "items": all_items,
        "total_items": len(all_items),
        "elapsed_seconds": round(elapsed, 1),
        "source_images": [p.name for p in all_images],
        "note": "视觉 API 补充提取的数据（用于图表数据）",
    }
    out_path = DATA_DIR / "api_extracted_data.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 70}")
    print(f"✅ 完成!")
    print(f"   共提取 {len(all_items)} 项数据")
    print(f"   耗时 {elapsed:.1f} 秒")
    print(f"   保存: {out_path}")

    # 合并到现有数据
    _merge_results(out_path)
    print(f"{'=' * 70}")


def _merge_results(api_path: Path) -> None:
    existing_path = DATA_DIR / "clean_report_data.json"
    if not existing_path.exists():
        print("\n⚠️ 找不到纯文本提取数据，跳过合并")
        return

    try:
        with open(existing_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        with open(api_path, "r", encoding="utf-8") as f:
            api_data = json.load(f)

        existing_labels = {item["label"] for item in existing.get("items", [])}
        new_items = [
            it for it in api_data.get("items", [])
            if it.get("label") and it["label"] not in existing_labels
        ]

        merged = {
            "student": existing.get("student", {}),
            "text_items": existing.get("items", []),
            "vision_items": new_items,
            "total_items": len(existing.get("items", [])) + len(new_items),
            "summary": f"文本提取 {len(existing.get('items',[]))} 项 + 视觉 API 提取 {len(new_items)} 项",
        }
        merged_path = DATA_DIR / "final_merged_report.json"
        with open(merged_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        print(f"\n📊 合并数据: {merged_path}")
        print(f"   文本: {len(existing.get('items',[]))} 项")
        print(f"   视觉: {len(new_items)} 项 (新增)")
        print(f"   总计: {merged['total_items']} 项")
    except Exception as e:
        print(f"\n⚠️ 合并失败: {e}")


if __name__ == "__main__":
    main()
