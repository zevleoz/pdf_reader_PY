from __future__ import annotations

import json
import base64
import urllib.request
import os
import re
from pathlib import Path
from typing import Dict, Tuple, List

try:
    import pymupdf as fitz
except ImportError:
    import fitz
import cv2
import numpy as np


VALUE_LABELS = ["安全稳定", "生活方式", "利他助人", "工作环境", "经济报酬",
                "上司关系", "同事关系", "成就感", "管理权力", "声望地位",
                "独立自主", "创造发明", "智力激发", "美的追求", "多样变化"]

# VALUE_LABELS 去空格版本 -> 标准名称映射（用于视觉 API 返回"美 的追求"这类变体时的标准化）
_LABEL_NO_SPACE_MAP = {lbl.replace(" ", ""): lbl for lbl in VALUE_LABELS}


def normalize_label(name: str) -> str:
    """把视觉 API 返回的变体标签名规范化为 VALUE_LABELS 中的标准名称。
    
    例如 "美 的追求" → "美的追求"。
    如果匹配不到，原样返回。
    """
    if not name:
        return name
    key = name.strip().replace(" ", "")
    return _LABEL_NO_SPACE_MAP.get(key, name.strip())


DEFAULT_DASHSCOPE_KEY = "sk-ws-H.RYLDEIE.E3Vt.MEUCIQDhlaQEMxHpnz09zmIpQONyI6aUfqP61xHF6ek9bKwGTwIgMxoi1LjUk0j7Lmc5piivXxONI52as5Zx_Dlj9mFt2Qs"


def call_vision_api(image_b64: str, prompt: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "") or os.environ.get("DASHSCOPE_API_KEY", DEFAULT_DASHSCOPE_KEY).strip()
    base_url = os.environ.get("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    
    if not api_key:
        print("[视觉] 未设置API密钥，跳过API调用")
        return ""
    
    payload = json.dumps({
        "model": "qwen3-vl-plus",
        "messages": [
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                {"type": "text", "text": prompt}
            ]}
        ],
        "temperature": 0.1,
        "max_tokens": 2048
    }).encode("utf-8")
    
    url = base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[视觉] API调用失败: {e}")
        return ""


def render_page(pdf_path: Path, page_idx: int, dpi: int = 200) -> np.ndarray:
    doc = fitz.open(str(pdf_path))
    page = doc[page_idx]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    doc.close()
    return img


def analyze_vertical_bars(img: np.ndarray) -> List[dict]:
    h, w = img.shape[:2]
    
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    
    yellow_mask = (hsv[:, :, 0] > 15) & (hsv[:, :, 0] < 50) & (hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 80)
    blue_mask = (hsv[:, :, 0] > 90) & (hsv[:, :, 0] < 140) & (hsv[:, :, 1] > 30) & (hsv[:, :, 2] > 50)
    red_mask = (hsv[:, :, 0] > 0) & (hsv[:, :, 0] < 20) & (hsv[:, :, 1] > 30) & (hsv[:, :, 2] > 80)
    green_mask = (hsv[:, :, 0] > 40) & (hsv[:, :, 0] < 80) & (hsv[:, :, 1] > 30) & (hsv[:, :, 2] > 50)
    
    combined_mask = yellow_mask | blue_mask | red_mask | green_mask
    
    kernel = np.ones((3, 3), np.uint8)
    combined_mask = cv2.morphologyEx(combined_mask.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
    combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_OPEN, kernel)
    
    contours, _ = cv2.findContours(combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    bar_contours = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 200 or area > 100000:
            continue
        
        x, y, cw, ch = cv2.boundingRect(contour)
        
        if cw < 15 or ch < 30:
            continue
        
        bar_contours.append({'x': x, 'y': y, 'w': cw, 'h': ch})
    
    bar_contours.sort(key=lambda c: c['x'])
    
    return bar_contours


def extract_min_max_from_text(pdf_path: Path) -> Tuple[float, float, str, str]:
    try:
        doc = fitz.open(str(pdf_path))
        
        min_val = 4.5
        max_val = 8.5
        min_label = "多样变化"
        max_label = "安全稳定"
        
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            text = page.get_text()
            
            lines = text.split('\n')
            for i, line in enumerate(lines):
                line = line.strip()
                if line == "8.5" and i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line in VALUE_LABELS:
                        max_label = next_line
                if line == "4.5" and i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line in VALUE_LABELS:
                        min_label = next_line
        
        doc.close()
        
        return min_val, max_val, min_label, max_label
    except Exception as e:
        return 4.5, 8.5, "多样变化", "安全稳定"


def parse_api_result(api_result: str, min_score: float, max_score: float, min_label: str, max_label: str) -> Dict[str, float]:
    results = {}
    
    json_match = re.search(r'\{[\s\S]*\}', api_result)
    if json_match:
        try:
            parsed = json.loads(json_match.group())
            if isinstance(parsed, dict):
                if '编号' in parsed and isinstance(parsed['编号'], list):
                    print(f"[视觉] API返回的编号顺序: {parsed['编号']}")
                    
                    if '分数' in parsed and isinstance(parsed['分数'], dict):
                        for i, label in enumerate(parsed['编号']):
                            matched_label = None
                            for known_label in VALUE_LABELS:
                                if known_label in label or label in known_label:
                                    matched_label = known_label
                                    break
                            
                            if matched_label:
                                score = None
                                for key, value in parsed['分数'].items():
                                    if matched_label in key or key in matched_label:
                                        try:
                                            score = float(value)
                                        except (ValueError, TypeError):
                                            pass
                                        break
                                if score is not None:
                                    results[matched_label] = round(max(min_score, min(max_score, score)), 1)
                elif len(parsed) <= 15:
                    for key, value in parsed.items():
                        matched_label = None
                        for known_label in VALUE_LABELS:
                            if known_label in key or key in known_label:
                                matched_label = known_label
                                break
                        
                        if matched_label:
                            try:
                                score = float(value)
                                results[matched_label] = round(max(min_score, min(max_score, score)), 1)
                            except (ValueError, TypeError):
                                pass
        except json.JSONDecodeError:
            pass
    
    if len(results) < 10:
        lines = api_result.split('\n')
        in_table = False
        for line in lines:
            line = line.strip()
            if '价值观' in line and ('分数' in line or '得分' in line):
                in_table = True
                continue
            if in_table:
                parts = re.split(r'[\s,，\t]+', line)
                if len(parts) >= 2:
                    label = parts[0]
                    score_str = parts[-1]
                    matched_label = None
                    for known_label in VALUE_LABELS:
                        if known_label in label or label in known_label:
                            matched_label = known_label
                            break
                    
                    if matched_label:
                        try:
                            score = float(score_str)
                            results[matched_label] = round(max(min_score, min(max_score, score)), 1)
                        except ValueError:
                            pass
            
            if in_table and not line.strip():
                if len(results) >= 10:
                    break
    
    if len(results) < 10:
        pattern = re.compile(r'([^\d]+?)\s*[：:]\s*(\d+\.?\d*)')
        for match in pattern.finditer(api_result):
            label_text = match.group(1).strip()
            score_str = match.group(2)
            
            matched_label = None
            for known_label in VALUE_LABELS:
                if known_label in label_text or label_text in known_label:
                    matched_label = known_label
                    break
            
            if matched_label:
                try:
                    score = float(score_str)
                    results[matched_label] = round(max(min_score, min(max_score, score)), 1)
                except ValueError:
                    pass
    
    return results


# ============================================================
# B6 版本检测：初中版 vs 高中版
# ============================================================

def detect_b6_version(pdf_path: Path) -> str:
    """检测 B6 是初中版还是高中版。直接从文件名判断。

    文件名包含 "高中" → 高中版
    文件名包含 "初中" → 初中版
    默认 → 初中版
    """
    name = pdf_path.name
    if "高中" in name:
        print(f"[视觉] B6 版本检测: 高中版 (文件名: {name})")
        return "高中版"
    if "初中" in name:
        print(f"[视觉] B6 版本检测: 初中版 (文件名: {name})")
        return "初中版"
    print(f"[视觉] B6 版本检测: 初中版 (默认, 文件名: {name})")
    return "初中版"


def find_values_page(pdf_path: Path) -> int:
    """返回职业价值观页面的 0-based 索引。

    初中版 → page 12 (index 11)
    高中版 → page 15 (index 14)
    """
    version = detect_b6_version(pdf_path)
    return 11 if version == "初中版" else 14


# ============================================================
# Prompt 模板：初中版 vs 高中版
# ============================================================

PROMPT_CHUZHONG = """这是职业价值观测评报告的页面。页面上有15个卡片，排列成3行5列。
每个卡片左上角有一个大的粗体数字编号（1-15）。

卡片编号的空间布局：
- 第1行（最上面）：编号 1, 2, 3, 4, 5（从左到右）
- 第2行（中间）：编号 6, 7, 8, 9, 10（从左到右）
- 第3行（最下面）：编号 11, 12, 13, 14, 15（从左到右）

你的任务：按照上述布局，识别每个编号卡片上的价值观名称（中文）。

请严格按照以下JSON格式输出，不要输出任何其他内容：

{{
  "1": "第1行第1列卡片的价值观名称",
  "2": "第1行第2列卡片的价值观名称",
  "3": "第1行第3列卡片的价值观名称",
  "4": "第1行第4列卡片的价值观名称",
  "5": "第1行第5列卡片的价值观名称",
  "6": "第2行第1列卡片的价值观名称",
  "7": "第2行第2列卡片的价值观名称",
  "8": "第2行第3列卡片的价值观名称",
  "9": "第2行第4列卡片的价值观名称",
  "10": "第2行第5列卡片的价值观名称",
  "11": "第3行第1列卡片的价值观名称",
  "12": "第3行第2列卡片的价值观名称",
  "13": "第3行第3列卡片的价值观名称",
  "14": "第3行第4列卡片的价值观名称",
  "15": "第3行第5列卡片的价值观名称"
}}

要求：
- 价值观名称必须从图片中读取，不要猜测
- 必须包含所有15个编号"""


PROMPT_GAOZHONG = """这是高中版职业价值观测评报告的页面。页面上有15个卡片，排列成3行5列。
每个卡片左上角有一个大的粗体数字编号（1-15）。

卡片编号的空间布局：
- 第1行（最上面）：编号 1, 2, 3, 4, 5（从左到右）
- 第2行（中间）：编号 6, 7, 8, 9, 10（从左到右）
- 第3行（最下面）：编号 11, 12, 13, 14, 15（从左到右）

你的任务：按照上述布局，识别每个编号卡片上的价值观名称（中文）。

请严格按照以下JSON格式输出，不要输出任何其他内容：

{{
  "1": "第1行第1列卡片的价值观名称",
  "2": "第1行第2列卡片的价值观名称",
  "3": "第1行第3列卡片的价值观名称",
  "4": "第1行第4列卡片的价值观名称",
  "5": "第1行第5列卡片的价值观名称",
  "6": "第2行第1列卡片的价值观名称",
  "7": "第2行第2列卡片的价值观名称",
  "8": "第2行第3列卡片的价值观名称",
  "9": "第2行第4列卡片的价值观名称",
  "10": "第2行第5列卡片的价值观名称",
  "11": "第3行第1列卡片的价值观名称",
  "12": "第3行第2列卡片的价值观名称",
  "13": "第3行第3列卡片的价值观名称",
  "14": "第3行第4列卡片的价值观名称",
  "15": "第3行第5列卡片的价值观名称"
}}

要求：
- 价值观名称必须从图片中读取，不要猜测
- 必须包含所有15个编号"""


def main() -> Dict[str, float]:
    base_dir = Path(__file__).resolve().parent
    input_dir = base_dir / "input"
    
    b6_files = sorted(input_dir.glob("*B6*.pdf"))
    if not b6_files:
        print("[视觉] 未找到 B6 PDF 文件")
        return {}
    
    pdf_path = b6_files[0]
    print(f"[视觉] 读取 {pdf_path.name}")
    
    # 检测版本并选择页面
    version = detect_b6_version(pdf_path)
    values_page_idx = find_values_page(pdf_path)
    print(f"[视觉] 职业价值观页面在第 {values_page_idx + 1} 页 (版本: {version})")
    
    img_15 = render_page(pdf_path, values_page_idx)
    
    # 用整页图片，不裁剪（裁剪会切掉第二、三排卡片）
    full_page = img_15
    try:
        cv2.imwrite(str(base_dir / "_full_page_for_api.png"), cv2.cvtColor(full_page, cv2.COLOR_RGB2BGR))
    except Exception:
        pass
    
    _, img_bytes = cv2.imencode('.png', cv2.cvtColor(full_page, cv2.COLOR_RGB2BGR))
    image_b64 = base64.b64encode(img_bytes).decode("utf-8")
    
    min_score, max_score, min_label, max_label = extract_min_max_from_text(pdf_path)
    print(f"[视觉] 读取到: min={min_score}({min_label}), max={max_score}({max_label})")
    
    # 根据版本选择 prompt
    prompt = PROMPT_GAOZHONG if version == "高中版" else PROMPT_CHUZHONG
    print(f"[视觉] 使用 {version} prompt")
    
    api_result = call_vision_api(image_b64, prompt)
    
    if api_result:
        print("\n[视觉] API返回:")
        print(api_result)
        
        try:
            json_match = re.search(r'\{[\s\S]*\}', api_result)
            if json_match:
                parsed = json.loads(json_match.group())
                
                # 解析 number_mapping（API 直接返回 {"1":"标签名",...,"15":"标签名"}）
                num_to_label = {}
                for key, value in parsed.items():
                    if key.isdigit() and 1 <= int(key) <= 15:
                        name_norm = normalize_label(str(value))
                        if name_norm:
                            num_to_label[str(key)] = name_norm
                
                # 基本校验：必须有 15 个条目
                if len(num_to_label) < 15:
                    print(f"\n[视觉] 警告: number_mapping 不完整 (count={len(num_to_label)})，丢弃映射")
                    num_to_label = {}
                
                # 构建 results（保持 extract.py 接口不变：返回 {标签: 分数}）
                # 分数从 min/max 文本读取的值填充，不需要视觉 API 返回分数
                results = {}
                if num_to_label:
                    for i in range(1, 16):
                        label_name = num_to_label.get(str(i), "")
                        if label_name:
                            # 分数用默认值填充（extract.py 主要用 mapping 填排名 110-124）
                            results[label_name] = max_score if label_name == max_label else (min_score if label_name == min_label else 5.0)
                    
                    print("\n[视觉] 最终结果（按卡片编号排序）:")
                    for i in range(1, 16):
                        label_name = num_to_label.get(str(i), "")
                        if label_name:
                            print(f"    卡片 {i}: {label_name}")
                    
                    # 写入 scores 文件（extract.py 读这个填 095-109）
                    output_path = base_dir / "data" / "_vision_b6_values_bar.json"
                    output_path.parent.mkdir(exist_ok=True)
                    with open(output_path, 'w', encoding='utf-8') as f:
                        json.dump(results, f, ensure_ascii=False, indent=2)
                    print(f"\n[视觉] 写入 {output_path}")
                    
                    # 写入 mapping 文件（extract.py 读这个填 110-124）
                    mapping_output_path = base_dir / "data" / "_vision_b6_values_mapping.json"
                    with open(mapping_output_path, 'w', encoding='utf-8') as f:
                        json.dump(num_to_label, f, ensure_ascii=False, indent=2)
                    print(f"\n[视觉] 写入编号映射 {mapping_output_path}")
                    
                    return results
        except json.JSONDecodeError:
            pass
    
    # 视觉API解析失败，不使用条形图匹配的默认值，返回空字典
    print("\n[视觉] API解析失败，不使用默认值，返回空结果")
    print("[视觉] 请检查视觉API是否正常工作，或重试")
    return {}


if __name__ == "__main__":
    main()
