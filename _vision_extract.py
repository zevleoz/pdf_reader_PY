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

重要提示：图片中有15个卡片，每个卡片左上角有一个大的粗体数字编号（1-15）。请按照卡片左上角的数字编号顺序来识别每个卡片对应的价值观名称。

请从中提取每位学生的15个职业价值观子项的得分，以及15个排序编号。严格按照格式输出：

对于每个子项，格式是：<标签>：<数值>
其中标签必须是以下15项之一，按卡片编号顺序（1-15）列出：
- 安全稳定（编号1）
- 生活方式（编号2）
- 利他助人（编号3）
- 工作环境（编号4）
- 经济报酬（编号5）
- 上司关系（编号6）
- 同事关系（编号7）
- 成就感（编号8）
- 管理权力（编号9）
- 声望地位（编号10）
- 独立自主（编号11）
- 创造发明（编号12）
- 智力激发（编号13）
- 美的追求（编号14）
- 多样变化（编号15）

以及每个排序结果，格式是：职业价值观排序<编号>：<标签>

请只输出数据点，不要解释、不要对话，不要多余文字。数值尽量精确到两位小数，若图片上是整数则直接输出整数。

如果无法从图片中读取某个数值，请标注为 "无法识别" 而不要猜测。"""

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
