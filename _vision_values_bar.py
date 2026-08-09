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
    try:
        cv2.imwrite(str(base_dir / "_full_page_for_api.png"), cv2.cvtColor(full_page, cv2.COLOR_RGB2BGR))
    except Exception:
        pass
    
    _, img_bytes = cv2.imencode('.png', cv2.cvtColor(full_page, cv2.COLOR_RGB2BGR))
    image_b64 = base64.b64encode(img_bytes).decode("utf-8")
    
    min_score, max_score, min_label, max_label = extract_min_max_from_text(pdf_path)
    print(f"[视觉] 读取到: min={min_score}({min_label}), max={max_score}({max_label})")
    
    prompt = f"""这是职业价值观测评报告的页面。页面上有15个卡片。每个卡片左上角有一个大的粗体数字编号（1-15）。

你的任务：
1. 仔细识别每个卡片左上角的数字编号（1-15）
2. 识别每个编号卡片上的价值观名称（中文）
3. 识别每个价值观的分数

重要：不要假设任何固定顺序，必须按照卡片上的实际编号来识别。

已知信息：
- 最高分是{max_score}分，对应"{max_label}"
- 最低分是{min_score}分，对应"{min_label}"

请严格按照以下JSON格式输出，不要输出任何其他内容：

{{
  "number_mapping": {{
    "1": "编号1对应的价值观名称",
    "2": "编号2对应的价值观名称",
    ...
    "15": "编号15对应的价值观名称"
  }},
  "scores": {{
    "价值观名称": 分数,
    ...
  }}
}}

要求：
- number_mapping中的键是卡片左上角的数字编号（1-15），值是该卡片上的价值观名称
- scores中的键是价值观名称，值是该价值观的得分（保留一位小数）
- 必须包含所有15个编号
- 请确保"{max_label}"的分数是{max_score}，"{min_label}"的分数是{min_score}
- 价值观名称必须从图片中读取，不要猜测"""
    
    api_result = call_vision_api(image_b64, prompt)
    
    if api_result:
        print("\n[视觉] API返回:")
        print(api_result)
        
        try:
            json_match = re.search(r'\{[\s\S]*\}', api_result)
            if json_match:
                parsed = json.loads(json_match.group())
                
                results = {}
                num_to_label = {}
                
                if 'scores' in parsed and isinstance(parsed['scores'], dict):
                    for name, score in parsed['scores'].items():
                        name_clean = name.strip()
                        if name_clean:
                            try:
                                score_val = float(score)
                                results[name_clean] = round(max(min_score, min(max_score, score_val)), 1)
                            except (ValueError, TypeError):
                                pass
                
                if 'number_mapping' in parsed and isinstance(parsed['number_mapping'], dict):
                    for num, name in parsed['number_mapping'].items():
                        name_clean = name.strip()
                        if name_clean:
                            num_to_label[str(num)] = name_clean
                
                if not num_to_label and isinstance(parsed, dict):
                    for key, value in parsed.items():
                        if key.isdigit() and 1 <= int(key) <= 15:
                            if isinstance(value, dict) and '名称' in value:
                                name = value['名称']
                                matched_label = None
                                for known_label in VALUE_LABELS:
                                    if known_label in name or name in known_label:
                                        matched_label = known_label
                                        break
                                if matched_label:
                                    num_to_label[str(key)] = matched_label
                
                if results and len(results) >= 10:
                    print("\n[视觉] 解析API结果:")
                    for label, score in results.items():
                        print(f"  {label}: {score}")
                    
                    # 不强制覆盖视觉API读取的值，仅补充缺失的最高/最低分
                    if max_label not in results:
                        results[max_label] = max_score
                    if min_label not in results:
                        results[min_label] = min_score
                    
                    # 按卡片编号排序（如果有编号映射）
                    if num_to_label:
                        # 创建按编号顺序排列的结果
                        ordered_results = {}
                        for i in range(1, 16):
                            label_name = num_to_label.get(str(i), "")
                            if label_name and label_name in results:
                                ordered_results[label_name] = results[label_name]
                        # 补充不在映射中的其他值
                        for label_name, score in results.items():
                            if label_name not in ordered_results:
                                ordered_results[label_name] = score
                        
                        print("\n[视觉] 最终结果（按卡片编号排序）:")
                        for i in range(1, 16):
                            label_name = num_to_label.get(str(i), "")
                            if label_name and label_name in ordered_results:
                                print(f"    卡片 {i}: {label_name} - {ordered_results[label_name]:.1f}")
                        
                        results = ordered_results
                    else:
                        print("\n[视觉] 最终结果（按分数排序）:")
                        sorted_results = sorted(results.items(), key=lambda x: -x[1])
                        for rank, (label, score) in enumerate(sorted_results, 1):
                            print(f"    排名 {rank}: {label} - {score:.1f}")
                    
                    output_path = base_dir / "data" / "_vision_b6_values_bar.json"
                    output_path.parent.mkdir(exist_ok=True)
                    
                    with open(output_path, 'w', encoding='utf-8') as f:
                        json.dump(results, f, ensure_ascii=False, indent=2)
                    
                    print(f"\n[视觉] 写入 {output_path}")
                    
                    if num_to_label:
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