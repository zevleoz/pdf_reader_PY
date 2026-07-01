import cv2
import numpy as np
import json
import os
import urllib.request


def extract_ranking_region(img_path: str) -> np.ndarray:
    img = cv2.imread(img_path)
    h, w = img.shape[:2]
    
    ranking_region = img[int(h*0.35):int(h*0.75), :]
    return ranking_region


def call_vision_api(image_data: bytes) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    
    if not api_key:
        print("请设置 OPENAI_API_KEY 环境变量")
        return ""
    
    import base64
    image_b64 = base64.b64encode(image_data).decode("utf-8")
    
    payload = json.dumps({
        "model": "qwen3-vl-plus",
        "messages": [
            {"role": "system", "content": "你是一个专业的OCR助手。请识别图像中的文本内容。"},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                {"type": "text", "text": "请识别这个表格中的所有文本，按行输出。每行格式为：排名编号 价值观名称"}
            ]}
        ],
        "temperature": 0.1,
        "max_tokens": 512
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
            content = result["choices"][0]["message"]["content"]
            return content
    except Exception as e:
        print(f"API调用失败: {e}")
        return ""


def parse_ranking(text: str) -> dict:
    import re
    
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    ranking = {}
    for line in lines:
        match = re.match(r'(\d+)\s+(.+)', line)
        if match:
            rank = int(match.group(1))
            label = match.group(2).strip()
            if 1 <= rank <= 15:
                ranking[label] = rank
    
    return ranking


def main():
    img_path = "data/page15.png"
    
    ranking_region = extract_ranking_region(img_path)
    
    cv2.imwrite("data/ranking_for_api.png", cv2.cvtColor(ranking_region, cv2.COLOR_RGB2BGR))
    print("已保存排序区域图像")
    
    _, buffer = cv2.imencode('.png', cv2.cvtColor(ranking_region, cv2.COLOR_RGB2BGR))
    image_data = buffer.tobytes()
    
    print("正在调用视觉API...")
    api_result = call_vision_api(image_data)
    
    if api_result:
        print("\nAPI返回结果:")
        print(api_result)
        
        ranking = parse_ranking(api_result)
        print("\n解析后的排序:")
        for label, rank in sorted(ranking.items(), key=lambda x: x[1]):
            print(f"  排名 {rank}: {label}")
        
        output_path = "data/_vision_b6_ranking.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(ranking, f, ensure_ascii=False, indent=2)
        print(f"\n排序结果已保存到 {output_path}")


if __name__ == "__main__":
    main()
