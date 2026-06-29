"""测试 dashscope 视觉 API 对 B6 第 12 页的提取能力。"""
import base64
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

import fitz

API_KEY = os.environ.get("DASHSCOPE_API_KEY", "").strip()
if not API_KEY:
    print("未设置 DASHSCOPE_API_KEY，跳过")
    sys.exit(0)

pdf_path = Path(__file__).resolve().parent / "input" / "report_B6.pdf"
if not pdf_path.exists():
    print(f"找不到 PDF: {pdf_path}")
    sys.exit(1)

doc = fitz.open(str(pdf_path))
page = doc[11]  # 第 12 页
mat = fitz.Matrix(2.5, 2.5)
pix = page.get_pixmap(matrix=mat, alpha=False)
doc.close()

DATA_DIR = Path(__file__).resolve().parent / "data"
img_path = DATA_DIR / "_tmp_b6_p12.png"
pix.save(str(img_path))

with open(img_path, "rb") as f:
    b64 = base64.b64encode(f.read()).decode("utf-8")

print("图片大小:", len(b64), "base64 chars")

TARGET_LABELS = ["创造发明", "独立自主", "美的追求", "智力激发", "利他助人",
                 "成就感", "管理权力", "工作环境", "同事关系", "上司关系",
                 "多样变化", "经济报酬", "安全稳定", "声望地位", "生活方式"]

user_prompt = f"""请读取这张 PDF 页面中"我的职业价值观"部分的 15 个项目的得分。
每个项目有一根横向柱状条，顶端附近会显示一个小数（如 9.39、3.29 等）。
请按以下格式严格输出 JSON，只包含 label 和 score：
{{
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
}}
"""

url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
payload = json.dumps({
    "model": "qwen2.5-vl-72b-instruct",
    "input": {
        "messages": [
            {"role": "system", "content": [{"text": "你是一个严格的 PDF 数据提取助手，只输出 JSON。"}]},
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
}).encode("utf-8")

req = urllib.request.Request(
    url, data=payload,
    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    out_json_path = DATA_DIR / "_tmp_dashscope_b6_values.json"
    with open(out_json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    content = data.get("output", {}).get("choices", [{}])[0].get("message", {}).get("content", [])
    print("API 返回 content:", content)
    # 尝试解析 JSON
    for c in content:
        if isinstance(c, dict):
            text = c.get("text", "")
        else:
            text = str(c)
        if text:
            print("\n提取到的文本:")
            print(text)
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode('utf-8')}")
except Exception as e:
    print(f"错误: {type(e).__name__}: {e}")
