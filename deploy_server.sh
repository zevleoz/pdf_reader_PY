#!/bin/bash
# ====================================================================
# Y4 报告生成器 — 阿里云 ECS 一键部署脚本
# ECS IP: 120.55.0.127
# 用法：SSH 登录 ECS 后，以 root 身份执行：
#   bash deploy_server.sh
# ====================================================================
set -e

APP_DIR="/opt/y4_report"
APP_USER="y4report"
LOG_DIR="/var/log/y4_report"

echo "============================================"
echo "  Y4 报告生成器 — 部署开始"
echo "  ECS: 120.55.0.127"
echo "============================================"

# ------------------------------------------
# 1. 安装系统依赖
# ------------------------------------------
echo ""
echo "[1/8] 安装系统依赖..."
apt update -y
apt install -y python3 python3-venv python3-pip
apt install -y chromium-browser || apt install -y chromium
apt install -y fonts-noto-cjk fonts-wqy-zenhei
apt install -y nginx libffi-dev libssl-dev

# 验证 Chrome 安装
echo "  Chrome 路径检查:"
for p in /usr/bin/chromium-browser /usr/bin/chromium /usr/bin/google-chrome; do
  if [ -f "$p" ]; then
    echo "    ✅ 找到: $p"
    CHROME_PATH="$p"
    break
  fi
done
if [ -z "$CHROME_PATH" ]; then
  echo "    ⚠️  未找到 Chrome，请手动安装: apt install chromium-browser"
fi

# ------------------------------------------
# 2. 创建应用用户
# ------------------------------------------
echo ""
echo "[2/8] 创建应用用户..."
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd -r -s /bin/false "$APP_USER"
  echo "  ✅ 用户 $APP_USER 已创建"
else
  echo "  ℹ️  用户 $APP_USER 已存在"
fi

# ------------------------------------------
# 3. 部署代码
# ------------------------------------------
echo ""
echo "[3/8] 部署代码..."
echo "  ⚠️  请确保你的代码已推送到 Git 仓库。"
echo "  如果还没有推送，请在本地执行："
echo "    cd /Users/jefflau/projects/pdf_report_converter/PDF_converter"
echo "    git add . && git commit -m 'deploy' && git push"
echo ""
echo "  请输入你的 Git 仓库地址 (例如 git@github.com:xxx/xxx.git)："
read -r GIT_URL

if [ -z "$GIT_URL" ]; then
  echo "  ❌ 未输入 Git 地址，请手动 clone 后重新运行"
  exit 1
fi

mkdir -p "$APP_DIR"
chown "$APP_USER":"$APP_USER" "$APP_DIR"

if [ -d "$APP_DIR/.git" ]; then
  echo "  ℹ️  代码已存在，执行 git pull..."
  sudo -u "$APP_USER" git -C "$APP_DIR" pull origin main || sudo -u "$APP_USER" git -C "$APP_DIR" pull
else
  echo "  📦 克隆代码..."
  sudo -u "$APP_USER" git clone "$GIT_URL" "$APP_DIR"
fi

# ------------------------------------------
# 4. 创建虚拟环境 + 安装依赖
# ------------------------------------------
echo ""
echo "[4/8] 创建 Python 虚拟环境..."
if [ ! -d "$APP_DIR/venv" ]; then
  sudo -u "$APP_USER" python3 -m venv "$APP_DIR/venv"
fi
echo "  安装 Python 依赖..."
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"
echo "  ✅ Python 依赖安装完成"

# ------------------------------------------
# 5. 目录权限
# ------------------------------------------
echo ""
echo "[5/8] 设置目录权限..."
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
for d in input output data pages; do
  mkdir -p "$APP_DIR/$d"
  chown "$APP_USER":"$APP_USER" "$APP_DIR/$d"
done

# ------------------------------------------
# 6. 日志目录
# ------------------------------------------
echo ""
echo "[6/8] 设置日志目录..."
mkdir -p "$LOG_DIR"
chown "$APP_USER":"$APP_USER" "$LOG_DIR"

# ------------------------------------------
# 7. 环境变量
# ------------------------------------------
echo ""
echo "[7/8] 配置环境变量..."
echo "  请输入 DashScope API Key（直接回车则使用代码中的默认 key）："
read -r DASHSCOPE_KEY
echo "  请输入一个随机字符串作为 SECRET_KEY（直接回车则自动生成）："
read -r SECRET_INPUT

if [ -z "$SECRET_INPUT" ]; then
  SECRET_INPUT=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 32)
fi

cat > "$APP_DIR/.env.production" <<EOF
FLASK_ENV=production
DASHSCOPE_API_KEY=${DASHSCOPE_KEY:-}
SECRET_KEY=${SECRET_INPUT}
EOF
chown "$APP_USER":"$APP_USER" "$APP_DIR/.env.production"
chmod 600 "$APP_DIR/.env.production"
echo "  ✅ .env.production 已创建"

# ------------------------------------------
# 8. 配置 Systemd + Nginx
# ------------------------------------------
echo ""
echo "[8/8] 配置 Systemd + Nginx..."

# Systemd
cp "$APP_DIR/y4_report.service" /etc/systemd/system/y4_report.service
systemctl daemon-reload
systemctl enable y4_report

# Nginx
cp "$APP_DIR/nginx_y4.conf" /etc/nginx/sites-available/y4_report
ln -sf /etc/nginx/sites-available/y4_report /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# 测试 Nginx 配置
if nginx -t; then
  echo "  ✅ Nginx 配置测试通过"
else
  echo "  ❌ Nginx 配置测试失败，请检查 /etc/nginx/sites-available/y4_report"
  exit 1
fi

# 启动/重启服务
systemctl restart y4_report
systemctl reload nginx

# ------------------------------------------
# 验证
# ------------------------------------------
echo ""
echo "============================================"
echo "  ✅ 部署完成！"
echo "============================================"
echo ""
echo "  服务状态:"
systemctl is-active y4_report && echo "  ✅ Gunicorn: running" || echo "  ❌ Gunicorn: failed"
systemctl is-active nginx && echo "  ✅ Nginx: running" || echo "  ❌ Nginx: failed"
echo ""
echo "  访问地址: http://120.55.0.127"
echo ""
echo "  查看日志:"
echo "    sudo tail -f /var/log/y4_report/error.log"
echo "    sudo tail -f /var/log/y4_report/access.log"
echo "    sudo journalctl -u y4_report -f"
echo ""
echo "  重启服务:"
echo "    sudo systemctl restart y4_report"
echo ""
echo "  后续加域名+SSL:"
echo "    sudo certbot --nginx -d report.你的域名.com"
echo "============================================"
