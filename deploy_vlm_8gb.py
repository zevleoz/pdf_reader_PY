"""
视觉模型部署 - 针对 8GB M2 Mac 优化
======================================

更新: 你的机器实际只有 8GB 内存，所以推荐轻量视觉模型。
推荐方案: qwen2.5vl:3b (2GB) -> 用于补充图表数据提取
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz

INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
DATA_DIR = Path("data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 针对 8GB M2 优化的模型清单
# ============================================================
MODELS = {
    # 🌟 首选 - 8GB M2 最平衡的选择
    "qwen2.5vl:3b-instruct-q4_0": {
        "name": "Qwen2.5-VL 3B (INT4)",
        "size_gb": 2.0,
        "mem_hint": "~4GB 内存",
        "speed_hint": "30-50 tokens/秒",
        "recommended": True,
    },
    # 备选 - 需要关闭其他应用
    "qwen2.5vl:7b-instruct-q4_0": {
        "name": "Qwen2.5-VL 7B (INT4)",
        "size_gb": 4.7,
        "mem_hint": "~6-7GB 内存（需关闭其他应用）",
        "speed_hint": "15-25 tokens/秒",
        "recommended": False,
    },
    # 轻量选择 - 如果上面的还是太慢
    "qwen2.5vl:3b-instruct-q2_K": {
        "name": "Qwen2.5-VL 3B (INT2)",
        "size_gb": 1.2,
        "mem_hint": "~2.5GB 内存",
        "speed_hint": "50-70 tokens/秒",
        "recommended": False,
    },
}

VLM_PROMPT = """你是一个数据提取助手。请分析这张 PDF 页面截图，提取其中所有数字数据。

重点关注:
1. 百分比数据 (%)
2. 分数/得分
3. 平均值/同龄人均值
4. 图表中的柱状图数值
5. BMI、身高、体重

只返回 JSON 格式:
{"items": [{"label": "指标名称", "value": 数值, "unit": "%/分/kg/cm/h 等", "mean": 平均值或 null}]}

不要输出任何额外文字、解释或 Markdown 代码块标记。"""


# ============================================================
# 环境检查
# ============================================================
def check_environment() -> Dict[str, Any]:
    print("🔍 环境检查...")
    info: Dict[str, Any] = {}

    import os
    mem_bytes = int(os.popen("sysctl -n hw.memsize").read().strip())
    mem_gb = mem_bytes / (1024 ** 3)
    info["mem_gb"] = round(mem_gb, 0)
    print(f"  💾 内存: {info['mem_gb']:.0f}GB")

    try:
        r = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=10)
        info["ollama"] = r.stdout.strip()
        print(f"  ✅ Ollama: {info['ollama']}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        info["ollama"] = None
        print("  ❌ Ollama 未安装 - 运行: bash install_ollama.sh")

    if info["ollama"]:
        try:
            r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=15)
            installed = []
            for line in r.stdout.strip().split("\n")[1:]:
                parts = re.split(r"\s{2,}", line)
                if parts and parts[0]:
                    installed.append(parts[0])
            info["installed_models"] = installed
            if installed:
                print(f"  📦 已安装: {', '.join(installed[:5])}")
        except Exception:
            info["installed_models"] = []

    return info


# ============================================================
# 核心: Ollama 推理 API
# ============================================================
def ollama_chat(model_id: str, image_path: Path, prompt: str) -> str:
    """通过 Ollama API 发送图片 + 提示词（使用 messages 格式，更稳定）"""
    payload = json.dumps({
        "model": model_id,
        "messages": [{
            "role": "user",
            "content": prompt,
            "images": [str(image_path)],
        }],
        "stream": False,
        "options": {
            "temperature": 0.1,
        },
    })
    try:
        result = subprocess.run(
            ["curl", "-s", "http://localhost:11434/api/chat", "-d", payload],
            capture_output=True, text=True, timeout=300,
        )
        data = json.loads(result.stdout)
        return data.get("message", {}).get("content", "")
    except Exception as e:
        print(f"  ⚠️ 推理失败: {e}")
        return ""


def pdf_pages_to_images(pdf_path: Path, page_nums: List[int], dpi: int = 150) -> List[Path]:
    """将特定 PDF 页面转为图片（DPI 150, 对 8GB 内存更友好）"""
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
# 解析 VLM 返回的 JSON
# ============================================================
def parse_vlm_response(response: str) -> List[Dict[str, Any]]:
    cleaned = re.sub(r"```(?:json)?\s*|```\s*", "", response, flags=re.IGNORECASE).strip()
    cleaned = cleaned.strip()

    for candidate in [
        cleaned,
        cleaned[cleaned.find("{"):cleaned.rfind("}") + 1] if "{" in cleaned else "",
        cleaned[cleaned.find("["):cleaned.rfind("]") + 1] if "[" in cleaned else "",
    ]:
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
                return data["items"]
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "label" in data:
                return [data]
        except json.JSONDecodeError:
            continue

    # 回退: 正则提取 "标签": 数值 对
    items = []
    for m in re.finditer(r'"([\u4e00-\u9fff][\u4e00-\u9fff\-]{0,30})"\s*[:：]\s*\{[^}]*"value"\s*[:：]\s*(\d+(?:\.\d+)?)', response):
        items.append({"label": m.group(1), "value": float(m.group(2))})
    if items:
        return items

    # 简单回退: "标签 数值" 形式
    for m in re.finditer(r'([\u4e00-\u9fff]{2,10})\s*[:：]\s*(\d+(?:\.\d+)?)', response):
        val = float(m.group(2))
        if val <= 200 and val >= 0:  # 过滤不合理值
            items.append({"label": m.group(1), "value": val})
    # 去重
    seen = set()
    unique = []
    for it in items:
        key = it.get("label", "")
        if key and key not in seen:
            seen.add(key)
            unique.append(it)
    return unique[:10]  # 只取前 10 项


# ============================================================
# 主流程
# ============================================================
def main() -> None:
    print("=" * 70)
    print("🤖 视觉模型部署工具 (8GB M2 优化)")
    print("=" * 70)

    env = check_environment()
    if not env["ollama"]:
        print("\n💡 请先执行: bash install_ollama.sh")
        return

    # 模型选择
    print("\n📋 模型选择 (针对你的 8GB M2):")
    keys = list(MODELS.keys())
    for i, (mid, info) in enumerate(MODELS.items(), 1):
        star = " ⭐推荐" if info.get("recommended") else ""
        print(f"  [{i}] {mid}{star}")
        print(f"      {info['name']} ({info['size_gb']}GB) - {info['mem_hint']}, {info['speed_hint']}")
    print(f"  [0] 使用已有模型")

    # 默认选第一个（推荐）
    model_id = keys[0]
    if model_id not in env.get("installed_models", []):
        print(f"\n📥 模型 {model_id} 尚未下载，开始拉取...")
        subprocess.run(["ollama", "pull", model_id])
    else:
        print(f"\n✅ 模型 {model_id} 已就绪")

    # 确定要分析的 PDF 页面（图表密集页）
    print("\n📄 准备 PDF 页面用于视觉分析...")
    pages_to_analyze: List[Path] = []

    for pdf_name, pages in [
        ("A2*.pdf", [5, 7, 9, 11]),  # 情绪稳定性, 大五, 依恋, 体质健康
        ("B4*.pdf", [4, 11]),        # 认知子指标, 自我概念
    ]:
        pdfs = sorted(INPUT_DIR.glob(pdf_name))
        if pdfs:
            imgs = pdf_pages_to_images(pdfs[0], pages)
            pages_to_analyze.extend(imgs)
            for img in imgs:
                print(f"  ✅ {pdfs[0].name} page {pages[imgs.index(img)] if pages[imgs.index(img)] else '?'} -> {img.name}")

    # 调用视觉模型
    if not pages_to_analyze:
        print("  ⚠️ 没有找到 PDF 文件")
        return

    print(f"\n🤖 使用 {model_id} 分析 {len(pages_to_analyze)} 张图片...")
    print("  (每张约 10-30 秒, 请耐心等待)\n")

    all_items: List[Dict[str, Any]] = []
    for idx, img in enumerate(pages_to_analyze, 1):
        print(f"  [{idx}/{len(pages_to_analyze)}] {img.name}")
        print("       推理中... ", end="", flush=True)
        response = ollama_chat(model_id, img, VLM_PROMPT)
        if response:
            items = parse_vlm_response(response)
            all_items.extend(items)
            print(f"✅ 提取 {len(items)} 项")
            if items:
                preview = ", ".join(f"{it.get('label','?')}:{it.get('value','?')}" for it in items[:3])
                print(f"       [{preview}...]")
        else:
            print("❌ 无响应")

    # 保存结果
    if all_items:
        output = {
            "model": model_id,
            "items": all_items,
            "total_items": len(all_items),
            "note": "视觉模型补充提取的数据（用于图表数据）",
        }
        out_path = DATA_DIR / "vlm_extracted_data.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 完成! 共提取 {len(all_items)} 项数据")
        print(f"   保存: {out_path}")

        # 与之前的纯文本提取合并（简单去重）
        merge_with_existing(out_path)


def merge_with_existing(vlm_path: Path) -> None:
    """将 VLM 提取的数据与已有的文本提取数据合并"""
    existing_path = DATA_DIR / "clean_report_data.json"
    if not existing_path.exists():
        return
    try:
        with open(existing_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        with open(vlm_path, "r", encoding="utf-8") as f:
            vlm = json.load(f)

        existing_labels = {item["label"] for item in existing.get("items", [])}
        new_items = [
            it for it in vlm.get("items", [])
            if it.get("label") and it["label"] not in existing_labels
        ]
        if new_items:
            merged = {
                "student": existing.get("student", {}),
                "text_items": existing.get("items", []),
                "vlm_items": new_items,
                "total_items": len(existing.get("items", [])) + len(new_items),
                "note": f"文本提取 {len(existing.get('items',[]))} 项 + 视觉提取 {len(new_items)} 项",
            }
            merged_path = DATA_DIR / "merged_report_data.json"
            with open(merged_path, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            print(f"   📊 合并数据: {merged_path}")
            print(f"   (文本 {len(existing.get('items',[]))} + 视觉 {len(new_items)} = {merged['total_items']} 项)")
    except Exception as e:
        print(f"   ⚠️ 合并失败: {e}")


if __name__ == "__main__":
    main()
