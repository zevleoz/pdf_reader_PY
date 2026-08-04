#!/bin/bash
set -e
cd /opt/y4_report
echo "Pulling latest code..."
git pull origin main
echo "Installing dependencies..."
/opt/y4_report/venv/bin/pip install -r requirements.txt
echo "Restarting service..."
sudo systemctl restart y4_report
echo "Done!"
