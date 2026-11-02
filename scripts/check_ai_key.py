"""检查当前环境的 DashScope key 能否调用模型。只输出结果，从不输出 key。

用法（服务器上）：
    cd /opt/y4_report && sudo -u y4report bash -c 'set -a; . ./.env.production; set +a; venv/bin/python scripts/check_ai_key.py'
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    key = (os.environ.get("FT_LLM_API_KEY") or os.environ.get("DASHSCOPE_API_KEY") or "").strip()
    if not key:
        print("未设置 DASHSCOPE_API_KEY")
        return 1
    model = os.environ.get("FT_LLM_MODEL") or "qwen-plus"
    base = (os.environ.get("FT_LLM_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")
    body = {"model": model, "temperature": 0.1, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": '只输出 JSON：{"ok": true}'}]}
    request = urllib.request.Request(
        base + "/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            json.loads(response.read().decode("utf-8"))
        print("OK：key 可用，模型 %s" % model)
        return 0
    except urllib.error.HTTPError as exc:
        try:
            error = json.loads(exc.read().decode("utf-8", errors="replace")).get("error") or {}
        except ValueError:
            error = {}
        print("失败：HTTP %s %s %s" % (exc.code, error.get("code", ""), error.get("message", "")))
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print("失败：连接错误 %s" % exc.__class__.__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
