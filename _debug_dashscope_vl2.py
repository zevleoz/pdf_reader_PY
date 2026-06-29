"""测试 dashscope 视觉 API（v2 简化版）。"""
import base64
import json
import os
import sys
from pathlib import Path

import requests  # 需要 requests 或下面用 httpx
import fitz

API_KEY = os.environ.get("DASHSCOPE_API_KEY", "").strip()
if not API_KEY:
    print("未设置 DASHSCOPE_API_KEY")
    sys.exit(0)

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
doc = fitz.open(str(pdf_path))
page = doc[11]  # 第 12 页
mat = fitz.Matrix(2.5, 2.5)
pix = page.get_pixmap(matrix=mat, alpha=False)
doc.close()

img_path = Path(__file__).resolve().parent / "data" / "_tmp_b6_p12.png"
pix.save(str(img_path))

with open(img_path, "rb") as f:
    b64 = base64.b64encode(f.read()).decode("utf-8")

print("图片大小:", len(b64), "base64 chars")

user_prompt = """请读取这张 PDF 页面中"我的职业价值观"部分的 15 个项目的得分。
每个项目有一根横向柱状条，顶端或其旁会显示一个数字（如 9.39、3.29 等）。
请按以下格式严格输出 JSON（只输出 JSON）：
{
  "创造发明": 数字,
  "独立自主": 数字,
  "美的追求": 数字,
  "智力激发": 数字,
  "利他助人": 数字,
  "成就感": 数字,
  "管理权力": 数字,
  "工作环境": 数字,
  "同事关系": 数字,
  "上司关系": 数字,
  "多样变化": 数字,
  "经济报酬": 数字,
  "安全稳定": 数字,
  "声望地位": 数字,
  "生活方式": 数字
}"""

# 用 dashscope 的原生格式（不是 openai 兼容格式）
url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}
payload = {
    "model": "qwen2.5-vl-72b-instruct",
    "input": {
        "messages": [
            {"role": "system", "content": [{"text": "你是一个严格的 PDF 数据提取助手。只输出 JSON。"}]},
            {
                "role": "user",
                "content": [
                    {"image": f"data:image/png;base64,{b64}"},
                    {"text": user_prompt},
                ],
            },
        ]
    },
    "parameters": {"temperature": 0.1, "top_p": 0.9},
}

try:
    r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=180)
    print("status:", r.status_code)
    data = r.json()
    print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
