#!/usr/bin/env python3
import dashscope
from dashscope import MultiModalConversation
import os
import sys

# 使用环境变量中的 key
DASHSCOPE_KEY = os.environ.get('DASHSCOPE_API_KEY', 'sk-ws-H.RYLDEIE.E3Vt.MEUCIQDhlaQEMxHpnz09zmIpQONyI6aUfqP61xHF6ek9bKwGTwIgMxoi1LjUk0j7Lmc5piivXxONI52as5Zx_Dlj9mFt2Qs')
dashscope.api_key = DASHSCOPE_KEY

print(f'API Key: {DASHSCOPE_KEY[:20]}...', file=sys.stderr)
print(f'Using model: qwen3-vl-plus', file=sys.stderr)

# 简单的测试调用
messages = [
    {
        'role': 'user',
        'content': [
            {'text': '你好，请回复JSON格式：{"status":"ok"}'}
        ]
    }
]

try:
    response = MultiModalConversation.call(
        model='qwen3-vl-plus',
        messages=messages,
        timeout=60,
    )
    print(f'Status code: {response.status_code}', file=sys.stderr)
    print(f'Response: {response}', file=sys.stderr)
    if hasattr(response, 'output'):
        print(f'Output: {response.output}', file=sys.stderr)
except Exception as e:
    print(f'Error: {type(e).__name__}: {e}', file=sys.stderr)
    import traceback
    traceback.print_exc()
