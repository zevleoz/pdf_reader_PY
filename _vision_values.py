"""使用 SiliconFlow Vision API 从 B6 PDF 第 14-15 页的图像中提取职业价值观数据。"""
from __future__ import annotations
import fitz
from pathlib import Path
import requests
import base64
import json

API_KEY = "sk-eefqofgkmjohvjlbjevxeomtcoahqigghfwrjrhfyfxcpbaf"
API_URL = "https://api.siliconflow.com/v1/chat/completions"

pdf_path = Path("input/B6 职业发展_Samson_2026031417271196372(1).pdf")

# 1. 渲染 B6 第 14 页和第 15 页为图像
doc = fitz.open(str(pdf_path))
image_paths = []

for page_idx in [13, 14]:  # 14 页和 15 页
    page = doc[page_idx]
    zoom = 2.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    output_path = Path(f"output/b6_page{page_idx+1}_full.png")
    pix.save(str(output_path))
    image_paths.append(output_path)
    print(f"已渲染: {output_path}")

doc.close()

# 2. 调用 SiliconFlow Vision API 读取图像
def encode_image(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

prompt = """请仔细阅读这两张职业价值观测评报告的图像。

请从中提取：

1) 15个职业价值观子项的得分（保留2位小数），包括：创造发明、独立自主、美的追求、智力激发、利他助人、成就感、管理权力、工作环境、同事关系、上司关系、多样变化、经济报酬、安全稳定、生活方式

2) 15个排序编号及其对应的职业价值观子项，从排序1到排序15

请严格按以下格式输出，一行一个数据：
得分数据：
创造发明：X.XX
独立自主：X.XX
...

排序数据：
职业价值观排序1：XXX
职业价值观排序2：XXX
...

注意：请仔细查看条形图旁边的数值标签，以及排序表格中的排序编号和对应子项。

请只输出数值和子项名，不要其他分析文字。"""

# 准备图像内容
image_contents = []
for img_path in image_paths:
    base64_image = encode_image(img_path)
    image_contents.append({
        "type": "image_url",
        "image_url": {
            "url": f"data:image/png;base64,{base64_image}"
        }
    })

# 准备消息
messages = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            *image_contents
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
    "max_tokens": 2048,
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
        print(f"错误响应: {response.text}")
except Exception as e:
    print(f"调用失败: {e}")
    import traceback
    traceback.print_exc()
