#!/usr/bin/env bash
# ============================================================
# 在 macOS (Apple Silicon M1/M2/M3) 上一键部署视觉模型
# 支持: Qwen2.5-VL 7B, Llama 3.2 Vision 11B, 和类似模型
# ============================================================

set -e

echo ""
echo "🚀 ==== 视觉模型一键部署 (macOS Apple Silicon) ===="
echo ""

# 1. 安装 Ollama
if ! command -v ollama &> /dev/null; then
    echo "[1/3] 安装 Ollama..."
    if command -v brew &> /dev/null; then
        brew install --cask ollama
    else
        echo "  未检测到 Homebrew，使用官网安装包..."
        echo "  请手动访问: https://ollama.com/download"
        echo "  或安装 Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        exit 1
    fi
    echo "  ✅ Ollama 安装完成"
else
    echo "[1/3] ✅ Ollama 已安装 ($(ollama --version))"
fi

# 2. 启动 Ollama 服务
echo ""
echo "[2/3] 启动 Ollama 服务..."
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "  正在启动 Ollama..."
    open -a "Ollama" || true
    sleep 3
    # 等待服务就绪
    for i in {1..20}; do
        if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
            break
        fi
        sleep 2
    done
fi
echo "  ✅ Ollama 服务运行中 (http://localhost:11434)"

# 3. 拉取视觉模型
echo ""
echo "[3/3] 拉取视觉模型..."
echo ""
echo "  选择要部署的模型:"
echo "  [1] Qwen2.5-VL 7B (INT4)  - 4.7GB 推荐⭐"
echo "  [2] Llama 3.2 Vision 11B (INT4) - 7.5GB"
echo "  [3] 两个都要"
echo "  [0] 跳过下载"
echo ""
read -p "请输入选择 [默认 1]: " choice
choice=${choice:-1}

pull_model() {
    local model=$1
    echo ""
    echo "📥 下载 $model (需要 2-10 分钟)..."
    ollama pull "$model"
    echo "  ✅ $model 就绪"
}

case $choice in
    1) pull_model "qwen2.5vl:7b-instruct-q4_0" ;;
    2) pull_model "llama3.2-vision:11b" ;;
    3) pull_model "qwen2.5vl:7b-instruct-q4_0"; pull_model "llama3.2-vision:11b" ;;
    0) echo "  ⏭ 跳过模型下载" ;;
    *) echo "  ⚠️ 无效选择，使用默认"; pull_model "qwen2.5vl:7b-instruct-q4_0" ;;
esac

echo ""
echo "========================================"
echo "🎉 部署完成!"
echo ""
echo "验证方法:"
echo "  ollama list                        # 查看已安装模型"
echo "  ollama run qwen2.5vl:7b-instruct-q4_0  # 交互式测试"
echo ""
echo "测试图片识别:"
echo "  python deploy_vlm.py              # 运行集成脚本"
echo "========================================"
