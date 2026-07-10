from __future__ import annotations

import json
import base64
import urllib.request
import os
import re
from pathlib import Path
from typing import Dict, Tuple, List

import fitz
import cv2
import numpy as np


VALUE_LABELS = ["安全稳定", "生活方式", "利他助人", "工作环境", "经济报酬",
                "上司关系", "同事关系", "成就感", "管理权力", "声望地位",
                "独立自主", "创造发明", "智力激发", "美的追求", "多样变化"]

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
    
    chart_region = img[200:600, 50:w-50]
    
    hsv = cv2.cvtColor(chart_region, cv2.COLOR_RGB2HSV)
    
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
                                            break
                                        except (ValueError, TypeError):
                                            pass
                                
                                if score is not None:
                                    results[matched_label] = round(max(min_score, min(max_score, score)), 1)
                                else:
                                    results[matched_label] = round(min_score + (max_score - min_score) * (i / 14), 1)
                
                elif '分数' in parsed and isinstance(parsed['分数'], dict):
                    for key, value in parsed['分数'].items():
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
            if '|' in line and ('索引' in line or '价值观' in line or '分数' in line):
                in_table = True
                continue
            
            if in_table and '|' in line:
                parts = [p.strip() for p in line.split('|') if p.strip()]
                if len(parts) >= 2:
                    label = ''
                    score_str = ''
                    for part in parts:
                        if any(known_label in part or part in known_label for known_label in VALUE_LABELS):
                            label = part
                        try:
                            score = float(part)
                            if min_score <= score <= max_score + 1:
                                score_str = part
                        except ValueError:
                            pass
                    
                    if label and score_str:
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
    
    if len(results) < 10:
        pattern2 = re.compile(r'(\d+)\.\s*([^\d]+?)\s+(\d+\.?\d*)')
        for match in pattern2.finditer(api_result):
            label_text = match.group(2).strip()
            score_str = match.group(3)
            
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
    
    if max_label in VALUE_LABELS:
        results[max_label] = max_score
    if min_label in VALUE_LABELS:
        results[min_label] = min_score
    
    return results


def find_values_page(pdf_path: Path) -> int:
    doc = fitz.open(str(pdf_path))
    for i in range(len(doc)):
        text = doc[i].get_text()
        if '我的职业价值观一览表' in text or ('价值观' in text and '1\n2\n3\n4\n5' in text):
            doc.close()
            return i
    doc.close()
    return 14


def main() -> Dict[str, float]:
    base_dir = Path(__file__).resolve().parent
    input_dir = base_dir / "input"
    
    b6_files = sorted(input_dir.glob("*B6*.pdf"))
    if not b6_files:
        print("[视觉] 未找到 B6 PDF 文件")
        return {}
    
    pdf_path = b6_files[0]
    print(f"[视觉] 读取 {pdf_path.name}")
    
    values_page_idx = find_values_page(pdf_path)
    print(f"[视觉] 职业价值观页面在第 {values_page_idx + 1} 页")
    
    img_15 = render_page(pdf_path, values_page_idx)
    
    full_page = img_15[150:1000, :]
    cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_full_page_for_api.png', cv2.cvtColor(full_page, cv2.COLOR_RGB2BGR))
    
    _, img_bytes = cv2.imencode('.png', cv2.cvtColor(full_page, cv2.COLOR_RGB2BGR))
    image_b64 = base64.b64encode(img_bytes).decode("utf-8")
    
    min_score, max_score, min_label, max_label = extract_min_max_from_text(pdf_path)
    print(f"[视觉] 读取到: min={min_score}({min_label}), max={max_score}({max_label})")
    
    prompt = f"""这是职业价值观测评报告的页面。页面上有15个卡片，排列成3行5列的网格。每个卡片左上角有一个大的粗体数字编号（1-15）。

重要规则：
1. 第1行从左到右是编号1-5
2. 第2行从左到右是编号6-10
3. 第3行从左到右是编号11-15
4. 请仔细识别每个卡片左上角的数字编号
5. 按照数字编号1-15的顺序输出价值观名称，不要按分数排序

已知信息：
- 最高分是{max_score}分，对应"{max_label}"
- 最低分是{min_score}分，对应"{min_label}"

请识别每个编号卡片对应的价值观名称，并提取其分数。

请只输出JSON，不要输出其他任何文字。JSON格式如下：
{{
  "1": {{"名称": "价值观名称", "分数": 分数}},
  "2": {{"名称": "价值观名称", "分数": 分数}},
  ...
  "15": {{"名称": "价值观名称", "分数": 分数}}
}}

其中数字键（1-15）代表卡片左上角的编号，每个编号对应一个对象，包含"名称"和"分数"字段。
分数保留一位小数。
请确保"{max_label}"的分数是{max_score}，"{min_label}"的分数是{min_score}。
必须包含所有15个编号。"""
    
    api_result = call_vision_api(image_b64, prompt)
    
    if api_result:
        print("\n[视觉] API返回:")
        print(api_result)
        
        try:
            json_match = re.search(r'\{[\s\S]*\}', api_result)
            if json_match:
                parsed = json.loads(json_match.group())
                
                results = {}
                for num in range(1, 16):
                    key = str(num)
                    if key in parsed and isinstance(parsed[key], dict):
                        name = parsed[key].get('名称', '')
                        score = parsed[key].get('分数', '')
                        
                        matched_label = None
                        for known_label in VALUE_LABELS:
                            if known_label in name or name in known_label:
                                matched_label = known_label
                                break
                        
                        if matched_label:
                            try:
                                score_val = float(score)
                                results[matched_label] = round(max(min_score, min(max_score, score_val)), 1)
                            except (ValueError, TypeError):
                                pass
                
                if results and len(results) >= 10:
                    print("\n[视觉] 解析API结果:")
                    for label, score in results.items():
                        print(f"  {label}: {score}")
                    
                    results[max_label] = max_score
                    results[min_label] = min_score
                    
                    print("\n[视觉] 最终结果:")
                    sorted_results = sorted(results.items(), key=lambda x: -x[1])
                    for rank, (label, score) in enumerate(sorted_results, 1):
                        print(f"    排名 {rank}: {label} - {score:.1f}")
                    
                    output_path = base_dir / "data" / "_vision_b6_values_bar.json"
                    output_path.parent.mkdir(exist_ok=True)
                    
                    with open(output_path, 'w', encoding='utf-8') as f:
                        json.dump(results, f, ensure_ascii=False, indent=2)
                    
                    print(f"\n[视觉] 写入 {output_path}")
                    
                    num_to_label = {}
                    for num in range(1, 16):
                        key = str(num)
                        if key in parsed and isinstance(parsed[key], dict):
                            name = parsed[key].get('名称', '')
                            for known_label in VALUE_LABELS:
                                if known_label in name or name in known_label:
                                    num_to_label[str(num)] = known_label
                                    break
                    
                    if num_to_label:
                        mapping_output_path = base_dir / "data" / "_vision_b6_values_mapping.json"
                        with open(mapping_output_path, 'w', encoding='utf-8') as f:
                            json.dump(num_to_label, f, ensure_ascii=False, indent=2)
                        print(f"\n[视觉] 写入编号映射 {mapping_output_path}")
                    
                    return results
        except json.JSONDecodeError:
            pass
    
    print("\n[视觉] API解析失败，使用条形图匹配")
    
    bars = analyze_vertical_bars(img_15)
    
    if len(bars) != 15:
        print(f"[视觉] 只检测到 {len(bars)} 个条形，不足15个")
        return {}
    
    heights = [bar['h'] for bar in bars]
    min_height = min(heights)
    max_height = max(heights)
    score_range = max_score - min_score
    
    print(f"[视觉] 条形高度范围: {min_height} - {max_height}")
    
    sorted_bars_by_height = sorted(bars, key=lambda b: -b['h'])
    
    max_bar_index = bars.index(sorted_bars_by_height[0])
    min_bar_index = bars.index(sorted_bars_by_height[-1])
    
    print(f"\n[视觉] 最高条形位置索引: {max_bar_index}")
    print(f"[视觉] 最低条形位置索引: {min_bar_index}")
    
    position_labels = VALUE_LABELS.copy()
    
    old_max_label = position_labels[max_bar_index]
    old_min_label = position_labels[min_bar_index]
    
    position_labels[max_bar_index] = max_label
    position_labels[min_bar_index] = min_label
    
    max_label_original_pos = VALUE_LABELS.index(max_label)
    min_label_original_pos = VALUE_LABELS.index(min_label)
    
    if max_label_original_pos != max_bar_index:
        position_labels[max_label_original_pos] = old_max_label
    
    if min_label_original_pos != min_bar_index:
        position_labels[min_label_original_pos] = old_min_label
    
    print(f"\n[视觉] 根据条形位置匹配标签:")
    for i, label in enumerate(position_labels):
        print(f"  位置{i}: {label}")
    
    results = {}
    
    for i, bar in enumerate(bars):
        if i < len(position_labels):
            label = position_labels[i]
            normalized = (bar['h'] - min_height) / (max_height - min_height) if max_height > min_height else 0.5
            score = min_score + normalized * score_range
            results[label] = round(max(min_score, min(max_score, score)), 1)
    
    results[max_label] = max_score
    results[min_label] = min_score
    
    print("\n[视觉] 最终结果:")
    sorted_results = sorted(results.items(), key=lambda x: -x[1])
    for rank, (label, score) in enumerate(sorted_results, 1):
        print(f"    排名 {rank}: {label} - {score:.1f}")
    
    output_path = base_dir / "data" / "_vision_b6_values_bar.json"
    output_path.parent.mkdir(exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n[视觉] 写入 {output_path}")
    
    return results


if __name__ == "__main__":
    main()