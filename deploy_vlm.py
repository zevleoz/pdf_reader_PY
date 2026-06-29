"""
Qwen2.5-VL 7B / GOT-OCR 2.0 本地部署脚本
=============================================
使用 Ollama (GGUF 4-bit 量化) 在 Apple Silicon Mac 上运行视觉模型。

用法:
    # 步骤 1: 安装 Ollama
    bash install_ollama.sh          # 或手动安装: https://ollama.com/download
    
    # 步骤 2: 拉取并测试视觉模型
    python deploy_vlm.py           # 部署模型 + 运行示例推理
    
    # 步骤 3: 提取 PDF 图表数据
    python extract_with_vlm.py     # 使用视觉模型解析图表
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF

INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
DATA_DIR = Path("data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 模型配置（可用的视觉模型 GGUF）
# ============================================================
MODELS = {
    "qwen2.5vl:7b-instruct-q4_0": {
        "name": "Qwen2.5-VL 7B (INT4)",
        "size_gb": 4.7,
        "description": "阿里通义千问视觉模型，综合能力强，推荐首选",
        "prompt_template": (
            "这是一张 PDF 页面的截图。请从图中提取结构化数据。\n"
            "要求:\n"
            "1. 只返回 JSON 格式\n"
            "2. 提取所有数字值（百分比、得分、平均值）\n"
            "3. 每个指标包含 label、value、unit 三个字段\n"
            "4. 如果有平均值/同龄人比较，额外加 mean 字段\n\n"
            "返回格式示例：\n"
            "{{\"items\": [{{\"label\": \"感知觉\", \"value\": 92, \"unit\": \"%\", \"mean\": 50}}]}}\n\n"
        ),
    },
    "llama3.2-vision:11b": {
        "name": "Llama 3.2 Vision 11B (INT4)",
        "size_gb": 7.5,
        "description": "Meta 官方视觉模型，推理质量高但更慢",
        "prompt_template": "",
    },
    "mini-chart-s理解:latest": {
        "name": "Mini-Chart (专门处理图表)",
        "size_gb": 4.5,
        "description": "专门用于解析图表、柱状图、饼图",
        "prompt_template": "",
    },
}

# GOT-OCR 2.0 目前 Ollama 上没有直接模型，但 Qwen2.5-VL 是它的基础模型
# 如果需要 GOT-OCR 2.0，可以通过 transformers 原生部署


# ============================================================
# 步骤 1: 检查环境
# ============================================================
def check_environment() -> Dict[str, Any]:
    print("🔍 环境检查...")
    info: Dict[str, Any] = {}

    # Ollama
    try:
        r = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=10)
        info["ollama"] = r.stdout.strip()
        print(f"  ✅ Ollama: {info['ollama']}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("  ❌ Ollama 未安装 - 请运行: brew install --cask ollama")
        info["ollama"] = None

    # 模型
    if info["ollama"]:
        try:
            r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=15)
            installed = []
            for line in r.stdout.strip().split("\n")[1:]:  # 跳过表头
                parts = re.split(r"\s{2,}", line)
                if parts and parts[0]:
                    installed.append(parts[0])
            info["installed_models"] = installed
            if installed:
                print(f"  📦 已安装模型: {', '.join(installed[:5])}")
            else:
                print("  (暂无模型)")
        except Exception as e:
            print(f"  ⚠️ 无法获取模型列表: {e}")

    # PyMuPDF
    try:
        import fitz
        print(f"  ✅ PyMuPDF: OK")
        info["pymupdf"] = fitz.version[0]
    except ImportError:
        print("  ❌ PyMuPDF 未安装")
        info["pymupdf"] = None

    return info


# ============================================================
# 步骤 2: 启动模型（如果尚未拉取）
# ============================================================
def pull_model(model_id: str) -> bool:
    print(f"\n📥 拉取模型: {model_id}")
    print("  (首次下载约 4-8GB，需要 2-10 分钟)")
    try:
        result = subprocess.run(
            ["ollama", "pull", model_id],
            capture_output=False,
            timeout=600,
        )
        if result.returncode == 0:
            print(f"  ✅ {model_id} 拉取完成")
            return True
        else:
            print(f"  ❌ 拉取失败，返回码: {result.returncode}")
            return False
    except subprocess.TimeoutExpired:
        print("  ⏰ 超时，可手动运行: ollama pull " + model_id)
        return False


# ============================================================
# 步骤 3: 将 PDF 页面转换为图片（供视觉模型分析）
# ============================================================
def pdf_page_to_image(pdf_path: Path, page_num: int, dpi: int = 200) -> Path:
    doc = fitz.open(str(pdf_path))
    page = doc[page_num - 1]  # 1-based
    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    out_dir = OUTPUT_DIR / "images"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{pdf_path.stem}_page{page_num:02d}.png"
    pix.save(str(out_path))
    doc.close()
    return out_path


# ============================================================
# 步骤 4: 通过 Ollama API 调用视觉模型
# ============================================================
def analyze_with_vlm(
    image_path: Path,
    model_id: str = "qwen2.5vl:7b-instruct-q4_0",
    prompt: Optional[str] = None,
) -> str:
    """通过 Ollama API 发送图片 + 提示词，获取结构化回答"""
    if prompt is None:
        prompt = MODELS.get(model_id, {}).get("prompt_template", "请描述图中内容。")

    # Ollama generate API (支持 images)
    payload = json.dumps({
        "model": model_id,
        "prompt": prompt,
        "images": [str(image_path)],
        "stream": False,
        "format": "json",  # 强制 JSON 输出
    })

    try:
        result = subprocess.run(
            ["curl", "-s", "http://localhost:11434/api/generate", "-d", payload],
            capture_output=True,
            text=True,
            timeout=300,
        )
        data = json.loads(result.stdout)
        return data.get("response", "")
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"  ⚠️ 推理失败: {e}")
        return ""


# ============================================================
# 步骤 5: 解析 VLM 返回的 JSON
# ============================================================
def parse_vlm_response(response: str) -> List[Dict[str, Any]]:
    """尝试从 VLM 响应中提取结构化 JSON"""
    # 清理 Markdown 代码块
    cleaned = re.sub(r"```(?:json)?|```", "", response, flags=re.IGNORECASE).strip()

    # 尝试多种格式解析
    for try_text in [cleaned, "{" + cleaned + "}", cleaned[cleaned.find("{"):cleaned.rfind("}")+1]]:
        try:
            data = json.loads(try_text)
            if isinstance(data, dict) and "items" in data:
                return data["items"]
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return [data]
        except json.JSONDecodeError:
            continue

    # 回退：正则提取数字
    items = []
    for m in re.finditer(r'["\']?([\u4e00-\u9fff][\u4e00-\u9fff\s\-]{1,20})["\']?\s*[:：]\s*(\d+(?:\.\d+)?)', response):
        items.append({"label": m.group(1).strip(), "value": float(m.group(2))})
    return items


# ============================================================
# 主流程：将视觉模型集成到 PDF 提取
# ============================================================
def main() -> None:
    print("=" * 70)
    print("🤖 PDF 视觉模型部署工具")
    print("=" * 70)

    # 1. 环境检查
    env = check_environment()
    if not env["ollama"]:
        print("\n💡 请先安装 Ollama:")
        print("   方式 1 (推荐): brew install --cask ollama")
        print("   方式 2: 下载 https://ollama.com/download/mac")
        print("\n   安装完成后重新运行本脚本")
        sys.exit(1)

    # 2. 选择模型
    print("\n📋 可用模型:")
    for i, (mid, info) in enumerate(MODELS.items(), 1):
        print(f"  [{i}] {mid}")
        print(f"      {info['name']} ({info['size_gb']}GB)")
        print(f"      {info['description']}")

    # 默认使用 qwen2.5vl:7b-instruct-q4_0
    model_id = "qwen2.5vl:7b-instruct-q4_0"

    # 3. 检查/拉取模型
    if model_id not in env.get("installed_models", []):
        print(f"\n⚠️ 模型 {model_id} 尚未下载，是否现在拉取？(y/n)")
        # 自动拉取
        pull_model(model_id)

    # 4. 将 PDF 页面转图片（针对图表密集页）
    print("\n📄 准备 PDF 页面（用于图表分析）...")
    pdf_files = sorted(INPUT_DIR.glob("A2*.pdf")) + sorted(INPUT_DIR.glob("B4*.pdf"))
    target_pages = {
        "A2*.pdf": [5, 9, 11],  # 情绪稳定性, 依恋, 体质健康（图表多）
        "B4*.pdf": [4, 11],      # 认知子指标, 自我概念（图表多）
    }

    image_files: List[Path] = []
    for pdf_path in pdf_files[:2]:  # 先处理有图表的 2 份
        pages = []
        for pat, pgs in target_pages.items():
            if pat.replace("*.pdf", "") in pdf_path.stem:
                pages = pgs
        for p in pages[:3]:
            try:
                img = pdf_page_to_image(pdf_path, p)
                image_files.append(img)
                print(f"  ✅ {pdf_path.name} page {p} -> {img.name}")
            except Exception as e:
                print(f"  ⚠️ 跳过: {e}")

    # 5. 调用视觉模型分析（先测试 1 张）
    if image_files:
        print(f"\n🤖 调用视觉模型分析图表数据 (共 {len(image_files)} 张图)...")
        print("  (每张图约 10-30 秒，M2 上 qwen2.5-vl 7B 速度约 20 tokens/秒)")

        all_items: List[Dict[str, Any]] = []
        for img in image_files[:2]:  # 先试 2 张
            print(f"\n  分析: {img.name}")
            response = analyze_with_vlm(img, model_id)
            if response:
                items = parse_vlm_response(response)
                all_items.extend(items)
                print(f"    提取到 {len(items)} 项数据")
                if items:
                    print(f"    示例: {items[0]}")

        # 6. 保存结果
        if all_items:
            output = {
                "model": model_id,
                "items": all_items,
                "total_items": len(all_items),
                "source_images": [p.name for p in image_files[:2]],
            }
            out_path = DATA_DIR / "vlm_extracted_data.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
            print(f"\n✅ 视觉模型提取完成: {len(all_items)} 项")
            print(f"   保存到: {out_path}")

    # 7. 速度/质量建议
    print("\n" + "=" * 70)
    print("📊 在 M2 Mac 上的预期性能:")
    print("  • Qwen2.5-VL 7B INT4: ~15-25 tokens/秒")
    print("  • 每页图表分析: ~10-30 秒")
    print("  • 内存占用: ~5-7GB（可与其他应用共存）")
    print("\n💡 推荐模型组合:")
    print("  - 主要文字提取: PyMuPDF（本项目已实现，0 成本）")
    print("  - 图表补充: Qwen2.5-VL 7B INT4（仅处理 5-10 页有图表的页面）")
    print("=" * 70)


if __name__ == "__main__":
    main()
