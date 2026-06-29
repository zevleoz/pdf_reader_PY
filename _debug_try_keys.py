"""测试多个可能的 API key。"""
import base64
import json
import os
import sys
from pathlib import Path

import requests
import fitz

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))
page = doc[11]  # 第 12 页
mat = fitz.Matrix(2.0, 2.0)
pix = page.get_pixmap(matrix=mat, alpha=False)
doc.close()
img_path = Path(__file__).resolve().parent / "data" / "_tmp_b6_p12.png"
pix.save(str(img_path))
with open(img_path, "rb") as f:
    b64 = base64.b64encode(f.read()).decode("utf-8")
print("图片大小:", len(b64), "chars")

user_prompt = """只输出JSON。读取PDF中"我的职业价值观"部分的15个项目的得分，格式：{"创造发明": 数字, "独立自主": 数字, "美的追求": 数字, "智力激发": 数字, "利他助人": 数字, "成就感": 数字, "管理权力": 数字, "工作环境": 数字, "同事关系": 数字, "上司关系": 数字, "多样变化": 数字, "经济报酬": 数字, "安全稳定": 数字, "声望地位": 数字, "生活方式": 数字}"""

candidates = [
    "sk-48392f71-66b2-4738-ba4b-51f259204d44",
    "sk-eeb2e473-cb57-4a5d-a174-32a5fe7cb7a3",
    "sk-tlewsksaclvrslvcggviiipolrhcyenaqtvkoiwragjtxd",
]

url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
for key in candidates:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": "qwen2.5-vl-72b-instruct",
        "input": {
            "messages": [
                {"role": "user", "content": [
                    {"image": f"data:image/png;base64,{b64}"},
                    {"text": user_prompt},
                ]},
            ]
        },
        "parameters": {"temperature": 0.1},
    }
    try:
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=180)
        print(f"key={key[:20]}... status={r.status_code} body[:400]={r.text[:400]}")
    except Exception as e:
        print(f"key={key[:20]}... err={e}")
    print()
