"""用 SiliconFlow Vision API 读取职业价值观 PDF 页面的数值数据。"""
from __future__ import annotations
import base64
import json
from pathlib import Path
import urllib.request
import urllib.error

API_KEY = "sk-eefqofgkmjohvjlbjevxeomtcoahqigghfwrjrhfyfxcpbaf"
API_URL = "https://api.siliconflow.cn/v1/chat/completions"

IMAGE_DIR = Path("output")
images = [
    ("B6 第14页（职业价值观 条形图）", "output/b6_page_14.png"),
    ("B6 第15页（职业价值观 排序表）", "output/b6_page_15.png"),
]

# 将图片转为 base64
image_messages = []
for title, img_path in images:
    data = Path(img_path).read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    image_messages.append({
        "type": "text",
        "text": f"=== {title} (file: {img_path}) ==="
    })
    image_messages.append({
        "type": "image_url",
        "image_url": {
            "url": f"data:image/png;base64,{b64}"
        }
    })

prompt = """请仔细阅读这两张职业价值观测评的图片。

图片中有15个卡片，每个卡片左上角有一个大的粗体数字编号（1-15）。

你的任务是：
1. 识别每个卡片左上角的编号（1-15）
2. 识别每个卡片上的价值观名称（中文）
3. 识别每个价值观的得分
4. 识别排序结果

请严格按照以下JSON格式输出，不要输出任何其他内容：

{
    "number_mapping": {
        "1": "<编号1对应的价值观名称>",
        "2": "<编号2对应的价值观名称>",
        ...
        "15": "<编号15对应的价值观名称>"
    },
    "scores": {
        "<价值观名称>": "<得分数值>",
        ...
    },
    "ranking": {
        "1": "<排名第1的价值观名称>",
        "2": "<排名第2的价值观名称>",
        ...
        "15": "<排名第15的价值观名称>"
    }
}

注意：
- number_mapping中的键是卡片左上角的数字编号，值是该卡片上的价值观名称
- scores中的键是价值观名称，值是该价值观的得分
- ranking中的键是排名（1-15），值是该排名对应的价值观名称
- 价值观名称必须从图片中读取，不要使用预设的名称
- 如果无法识别某个值，请留空字符串"""

message = {
    "role": "user",
    "content": image_messages + [{"type": "text", "text": prompt}]
}

payload = json.dumps({
    "model": "Qwen/Qwen3-VL-32B-Instruct",
    "messages": [message],
    "max_tokens": 2048,
    "temperature": 0.1,
}).encode("utf-8")

req = urllib.request.Request(
    API_URL,
    data=payload,
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    },
)

print("调用 SiliconFlow Vision API ...")
try:
    with urllib.request.urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"]
        print("\n=== Vision API 返回结果 ===")
        print(content)
        # 同时保存到文件
        Path("output/vision_work_values.json").write_text(
            json.dumps({"content": content, "raw": result}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print("\n✅ 已保存到 output/vision_work_values.json")
except urllib.error.URLError as e:
    print(f"❌ 网络错误: {e}")
except Exception as e:
    print(f"❌ 错误: {e}")
    import traceback; traceback.print_exc()
