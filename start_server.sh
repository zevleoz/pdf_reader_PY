#!/bin/bash
# PDF 报告生成器 Web 服务器启动脚本
# API key 已 hard code 在 extract.py 中，无需手动设置

cd "$(dirname "$0")"

# 清理可能占用端口 8000 的旧进程
lsof -ti:8000 | xargs kill -9 2>/dev/null

echo "========================================"
echo "PDF 报告生成器 Web 服务器"
echo "========================================"
echo ""
echo "API Key: 已内置（阿里云 DashScope）"
echo "视觉模型: qwen-vl-plus"
echo ""
echo "启动服务器..."
echo "访问地址: http://localhost:8000"
echo ""
echo "按 Ctrl+C 停止服务器"
echo "========================================"

# 启动 Flask 服务器
python app.py