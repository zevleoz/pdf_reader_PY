"""使用 SiliconFlow Vision API 从 B6 PDF 第 14 页（职业价值观条形图）提取所有 15 个子项的精确得分。

特别关注：创造发明、独立自主、美的追求、智力激发、利他助人、成就感、管理权力、工作环境、同事关系、上司关系、多样变化、经济报酬、安全稳定、声望地位、生活方式。

请特别确认"声望地位"的得分。"""
from __future__ import annotations
import fitz
from pathlib import Path
import requests
import base64

API_KEY = "sk-eefqofgkmjohvjlbjevxeomtcoahqigghfwrjrhfyfxcpbaf"
API_URL = "https://api.siliconflow.com/v1/chat/completions"

pdf_path = Path("input/B6 职业发展_Samson_2026031417271196372(1).pdf")

# 渲染 B6 第 14 页（职业价值观条形图）
doc = fitz.open(str(pdf_path))
page = doc[13]  # 第 14 页索引 13
zoom = 3.0
mat = fitz.Matrix(zoom, zoom)
pix = page.get_pixmap(matrix=mat)
output_path = Path("output/b6_page14_hires.png")
pix.save(str(output_path))
doc.close()

print(f"已渲染高清图像: {output_path}")

# 编码图像
with open(output_path, "rb") as f:
    base64_image = base64.b64encode(f.read()).decode("utf-8")

prompt = """请仔细阅读这张职业价值观测评报告的图像。

请从中提取 15 个职业价值观子项的得分，每个子项的得分在条形图末端都有一个数值标签（可能是X.XX格式）。

15个子项是：创造发明、独立自主、美的追求、智力激发、利他助人、成就感、管理权力、工作环境、同事关系、上司关系、多样变化、经济报酬、安全稳定、声望地位、生活方式

请按以下格式输出，一行一个：
创造发明：X.XX
独立自主：X.XX
美的追求：X.XX
智力激发：X.XX
利他助人：X.XX
成就感：X.XX
管理权力：X.XX
工作环境：X.XX
同事关系：X.XX
上司关系：X.XX
多样变化：X.XX
经济报酬：X.XX
安全稳定：X.XX
声望地位：X.XX
生活方式：X.XX

注意：请仔细查看每个条形图末端的数值标签，确保提取精确。特别注意"声望地位"这一项。"""

messages = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{base64_image}"
                }
            }
        ]
    }
]

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

payload = {
    "model": "Qwen/Qwen3-VL-32B-Instruct",
    "messages": messages,
    "max_tokens": 1024,
    "temperature": 0.0,
    "stream": False
}

print("\n正在调用 SiliconFlow Vision API...")
try:
    response = requests.post(API_URL, headers=headers, json=payload, timeout=120)
    print(f"状态码: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        print("\n=== API 返回结果 ===")
        print(result["choices"][0]["message"]["content"])
    else:
        print(f"错误响应: {response.text[:500]}")
except Exception as e:
    print(f"调用失败: {e}")
