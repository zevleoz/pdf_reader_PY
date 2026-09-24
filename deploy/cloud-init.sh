#!/bin/bash
# Y4 报告系统一键部署脚本（阿里云 ECS 2核2G）
# 用法：买 ECS 时粘贴到「自定义数据」(cloud-init) 中
# 注意：脚本不会自动启动服务，需要你手动写 .env.production 后再启动

set -e

echo "=== [1/8] 更新系统并安装基础依赖 ==="
apt-get update -y
apt-get install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git

echo "=== [2/8] 创建应用用户和目录 ==="
useradd -m -s /bin/bash y4report 2>/dev/null || true
mkdir -p /opt/y4_report
chown y4report:y4report /opt/y4_report

echo "=== [3/8] 添加 2G swap（2G 内存机器防 OOM）==="
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "=== [4/8] 克隆代码 ==="
cd /opt/y4_report
if [ ! -d .git ]; then
    sudo -u y4report git clone https://github.com/zevleoz/pdf_reader_PY.git .
fi

echo "=== [5/8] 创建虚拟环境并安装依赖 ==="
cd /opt/y4_report
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

echo "=== [6/8] 调整 gunicorn 配置（2G 内存用 1 个 worker）==="
sed -i 's/^workers = .*/workers = 1/' /opt/y4_report/gunicorn_config.py

echo "=== [7/8] 配置 systemd 服务 ==="
cp /opt/y4_report/y4_report.service /etc/systemd/system/y4_report.service
systemctl daemon-reload
systemctl enable y4_report

echo "=== [8/8] 配置 Nginx ==="
cp /opt/y4_report/nginx_y4.conf /etc/nginx/sites-available/y4_report
ln -sf /etc/nginx/sites-available/y4_report /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo ""
echo "=============================================="
echo "✅ 环境部署完成！"
echo ""
echo "接下来你需要手动完成 3 件事："
echo ""
echo "1. 写入密钥配置："
echo "   sudo nano /opt/y4_report/.env.production"
echo "   （内容见下方模板）"
echo ""
echo "2. 设置权限并启动服务："
echo "   sudo chmod 600 /opt/y4_report/.env.production"
echo "   sudo chown y4report:y4report /opt/y4_report/.env.production"
echo "   sudo systemctl start y4_report"
echo "   sudo systemctl status y4_report"
echo ""
echo "3. 签 SSL 证书（先把 DNS 指向新 IP）："
echo "   sudo certbot --nginx -d report.p4learning-ark.app"
echo "=============================================="
