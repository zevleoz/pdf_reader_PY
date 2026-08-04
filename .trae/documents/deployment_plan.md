# Y4 Report Generator — Deployment Plan

## Goal

Migrate the existing localhost Flask application to an online production server while preserving **100% of existing functionality**. The same upload → extract → generate → download pipeline must produce identical outputs. No new features. No redesign. The localhost version will be kept as a backup.

---

## Part 1: Architecture Report (How It Works Now)

### 1.1 Current State (Localhost)

```
┌─────────────────────────────────────────────────────┐
│  macOS: python app.py                                 │
│  Flask dev server listening on http://localhost:8000 │
│                                                      │
│  User opens http://localhost:8000                    │
│  → Uploads 4 PDFs (A2, B3, B4, B6)                   │
│  → Clicks "生成并下载综合报告 PDF"                    │
│  → POST /api/generate                                │
│                                                      │
│  app.py api_generate():                              │
│    1. Save PDFs to input/                            │
│    2. extract.main() → vision OCR → data/report_data.json│
│    3. validate.main() → check completeness            │
│    4. apply_report_data() → fill USER_DATA dict      │
│    5. generate.main() → build_view_data → render_html │
│       → generate_pdf_with_chrome() → output/report.pdf│
│    6. Return report.pdf as download                   │
│                                                      │
│  User receives: 综合测评报告.pdf                      │
└─────────────────────────────────────────────────────┘
```

**Current code that runs this:**
- `app.py` — Flask routes, runs via `app.run(host="0.0.0.0", port=8000, debug=False, threaded=True)`
- `extract.py` — PDF → JSON extraction with vision OCR
- `generate.py` — JSON → HTML → PDF (Chrome headless)
- `data_points.py` — 133-point data schema
- `validate.py` — data completeness check
- `templates/index.html` — upload form (vanilla HTML+JS, no framework)
- `templates/report.html` — Jinja2 PDF report template
- `templates/style.css` — PDF CSS (A4, @page rules)
- `branding/` — logo images
- `static/css/fontawesome.min.css` — Font Awesome CSS + fonts

**Key technical details:**
- The Flask app's WSGI application object is `app` (in `app.py`). This is the standard Python interface between web servers and Python web applications.
- When you run `python app.py`, it calls `app.run()` which starts Flask's built-in development HTTP server. This server is NOT production-grade (single-threaded, not secure, limited).
- The app uses `threaded=True` to handle concurrent requests, but Flask dev server is not designed for production.

### 1.2 What Must NOT Change

| Component | Why |
|-----------|-----|
| `extract.py` internal logic | Already produces correct `report_data.json` |
| `generate.py` internal logic | Already produces correct PDF via Chrome headless |
| `data_points.py` schema | 133-point schema is the authoritative data model |
| `validate.py` logic | Correct data completeness check |
| `templates/report.html` | Already renders correct report layout |
| `templates/style.css` | Already has correct PDF styling |
| `branding/` assets | Already has correct brand assets |
| Flask routes (`/`, `/api/generate`, `/output/<path>`) | Already handle the full workflow correctly |

### 1.3 What WILL Change (Minimal)

| Component | Change | Why |
|-----------|--------|-----|
| **How the Flask app is served** | Replace `app.run()` (Flask dev server) with Gunicorn (production WSGI server) | Flask dev server is not production-grade |
| **Reverse proxy** | Add Nginx in front of Gunicorn | Security, SSL, static file serving |
| **`app.py` imports** | Add `import os` (missing, bug fix) | Line 251 uses `os.environ.get()` without import |
| **`app.py` config** | Add `MAX_CONTENT_LENGTH` | Flask needs this for large uploads (>16MB) |
| **`app.py` error handler** | Add 413 handler for oversized uploads | User-friendly error message |
| **`requirements.txt`** | Add gunicorn, matplotlib, opencv-python-headless | Production server + missing deps |
| **`.gitignore`** | Remove `branding/` from ignore | Brand assets must be deployed |
| **Deployment scripts** | Create gunicorn config, nginx config, systemd service | Production infrastructure |

**Total code changes to existing Python files: 4 lines in `app.py` (1 import + 3 config lines).**

---

## Part 2: How the Migration Works (Before vs After)

### 2.1 Before: Localhost (Current)

```
User Browser
    │
    ▼
Flask Dev Server (app.py → app.run())
    │  localhost:8000
    │
    ├── GET / → render index.html (upload form)
    ├── POST /api/generate → run pipeline → return PDF
    └── GET /output/<path> → download generated file
```

### 2.2 After: Online (Production)

```
User Browser (anywhere on the internet)
    │
    ▼
Nginx (port 80, SSL on port 443)
    │  Handles: SSL, rate limiting, static files, request routing
    │
    ▼  Unix socket (not HTTP, for security)
    │
Gunicorn (production WSGI server)
    │  Runs: app:app (imports Flask app from app.py)
    │  Workers: 2 sync workers
    │  Timeout: 600s
    │
    ├── GET / → render index.html (upload form)     ← SAME ROUTE
    ├── POST /api/generate → run pipeline → PDF     ← SAME ROUTE, SAME CODE
    └── GET /output/<path> → download generated file ← SAME ROUTE
    │
    ▼
SAME PIPELINE (extract.py → validate → generate.py)
    │
    ▼
SAME OUTPUT (output/report.pdf → identical to localhost)
```

**The critical insight: Gunicorn imports your Flask application object and serves it. The Flask code itself does not change. All routes, templates, extraction logic, PDF generation — everything runs the same way.**

### 2.3 Technical Explanation: Why This Works

Flask applications follow the WSGI (Web Server Gateway Interface) standard. Your `app.py` creates an application object:

```python
app = Flask(__name__)
```

This `app` object is a WSGI application — it's a callable that accepts `(environ, start_response)` and returns an iterable of response bytes. Any WSGI-compatible server can run it.

**Currently**, you start it with Flask's built-in server:
```python
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
```

**In production**, Gunicorn starts it instead:
```bash
gunicorn app:app
# This means: import 'app' module, get the 'app' variable (the Flask WSGI application)
```

**The Flask routes, templates, and business logic are 100% identical.** Only the HTTP server that wraps the Flask app changes.

### 2.4 What Gunicorn Provides vs Flask Dev Server

| Feature | Flask Dev Server | Gunicorn |
|---------|-----------------|----------|
| Production-ready | ❌ | ✅ |
| Handles concurrent requests | Single-threaded / threaded | Multi-worker |
| Static file serving | Built-in | Nginx (more efficient) |
| Logging | Basic | Structured access/error logs |
| Process management | Manual | Systemd (auto-restart on crash) |
| Security | Debug mode, reloader | No debug, hardened |
| Timeout handling | None | 600s configurable |

### 2.5 Why Nginx + Gunicorn (Not Just Gunicorn)

- **Nginx** handles: SSL termination, static file serving (CSS, images), request routing, security headers, rate limiting
- **Gunicorn** handles: running the Python Flask application
- **Together**: Industry standard for deploying Flask/Python web apps
- **Why not just Gunicorn?** No SSL, less efficient for static files, no request queuing

---

## Part 3: Production Configuration Details

### 3.1 Files to Create (5 files, all config/infra)

#### File 1: `gunicorn_config.py`
```python
"""Gunicorn production configuration.

This file is imported by gunicorn. It tells gunicorn how to serve
the Flask application. The Flask code itself (app.py) is NOT modified.
"""

# Worker processes — each loads the full Flask app + extract + generate modules
workers = 2

# Use synchronous workers (matches Flask dev server behavior)
worker_class = 'sync'

# Max time a request can take before being killed (seconds)
# Vision OCR takes 30-120s, Chrome PDF takes 5-15s
# Total pipeline: up to ~180s. 600s gives safety margin.
timeout = 600

# Time to keep connection alive between requests
keepalive = 5

# Recycle workers after N requests (prevents memory leaks)
max_requests = 10
max_requests_jitter = 2

# Load app before forking workers (saves memory)
preload_app = True

# Unix socket — more secure than TCP, only accessible locally
bind = 'unix:/tmp/y4_report.sock'

# Logging
accesslog = '/var/log/y4_report/access.log'
errorlog = '/var/log/y4_report/error.log'
loglevel = 'info'
```

#### File 2: `nginx_y4.conf`
```nginx
server {
    listen 80;
    server_name your-domain.com;

    # Max upload size (4 PDFs can be large)
    client_max_body_size 50M;

    # Timeout for long-running requests (must match gunicorn timeout)
    proxy_read_timeout 600s;
    proxy_connect_timeout 600s;

    # Main location — proxy everything to Gunicorn via Unix socket
    location / {
        proxy_pass http://unix:/tmp/y4_report.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### File 3: `y4_report.service`
```
[Unit]
Description=Y4 Report Generator (Gunicorn)
After=network.target

[Service]
Type=notify
User=y4report
Group=y4report
WorkingDirectory=/opt/y4_report
ExecStart=/opt/y4_report/venv/bin/gunicorn -c gunicorn_config.py app:app
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=30s

[Install]
WantedBy=multi-user.target
```

#### File 4: `.env.production`
```
FLASK_ENV=production
DASHSCOPE_API_KEY=your_production_key_here
SECRET_KEY=change_this_to_a_random_string
```

#### File 5: `deploy.sh`
```bash
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
```

### 3.2 Files to Modify (4 files, minimal changes)

#### File 6: `app.py` — 4 minimal additions
```python
# ADD: import os (line ~13, after 'import traceback')
import os

# ADD: after app creation (~line 25)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')

# ADD: error handler (~line 35, after imports)
@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({"ok": False, "error": "文件太大，单文件不超过 50MB"}), 413
```

#### File 7: `requirements.txt` — add missing deps
```
# (existing)
PyMuPDF>=1.23
openai>=1.30
Jinja2>=3.1
WeasyPrint>=60.0
Flask>=3.0
# (added for production)
gunicorn>=21.2
dashscope>=1.19
opencv-python-headless>=4.8
numpy>=1.24
matplotlib>=3.7
```

#### File 8: `.gitignore` — remove branding/ exclusion
```
# Remove this line (brand images must be deployed):
# branding/     ← REMOVED

# Add this line:
.env.production
```

#### File 9: `templates/index.html` — add timeout hint
- Increase `fetch()` timeout from default to 300s
- Add progress message after upload starts: "正在处理，约需 1-3 分钟，请耐心等待..."

---

## Part 4: Server Deployment (Alibaba Cloud ECS)

### 4.1 One-Time Server Setup

```bash
# 1. Install system dependencies
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
sudo apt install -y chromium-browser
sudo apt install -y fonts-noto-cjk fonts-wqy-zenhei
sudo apt install -y nginx libffi-dev libssl-dev

# 2. Create app user
sudo useradd -r -s /bin/false y4report
sudo mkdir -p /opt/y4_report
sudo chown y4report:y4report /opt/y4_report

# 3. Deploy code
sudo -u y4report git clone <repo-url> /opt/y4_report
cd /opt/y4_report
sudo -u y4report python3 -m venv venv
sudo -u y4report venv/bin/pip install -r requirements.txt

# 4. Set permissions
sudo chown -R y4report:y4report /opt/y4_report
for dir in input output data pages; do
    mkdir -p /opt/y4_report/$dir
    sudo chown y4report:y4report /opt/y4_report/$dir
done

# 5. Set up logging
sudo mkdir -p /var/log/y4_report
sudo chown y4report:y4report /var/log/y4_report

# 6. Set environment
sudo -u y4report bash -c 'cat > /opt/y4_report/.env.production << EOF
FLASK_ENV=production
DASHSCOPE_API_KEY=<your-production-api-key>
SECRET_KEY=<random-string>
EOF'

# 7. Load env into systemd service
# (We'll create a wrapper or use EnvironmentFile)
```

### 4.2 Configure Systemd Service

```bash
sudo cp y4_report.service /etc/systemd/system/
# Edit y4_report.service to include:
# EnvironmentFile=/opt/y4_report/.env.production
sudo systemctl daemon-reload
sudo systemctl enable y4_report
sudo systemctl start y4_report
sudo systemctl status y4_report
```

### 4.3 Configure Nginx

```bash
sudo cp nginx_y4.conf /etc/nginx/sites-available/y4_report
sudo ln -s /etc/nginx/sites-available/y4_report /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

### 4.4 Open Firewall

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
# OR Alibaba Cloud security group: add rules for ports 80, 443
```

### 4.5 SSL (Optional)

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

---

## Part 5: Verification (Before & After)

### 5.1 Local Pre-deployment Check

Run on your Mac before deployment to verify nothing changed:
```bash
cd /Users/jefflau/projects/pdf_report_converter/PDF_converter

# Start Flask (local)
python app.py

# Test with sample PDFs
curl -X POST http://localhost:8000/api/generate \
  -F "A2=@test_A2.pdf" -F "B3=@test_B3.pdf" \
  -F "B4=@test_B4.pdf" -F "B6=@test_B6.pdf" \
  --output local_test.pdf

# Save hash for comparison
shasum local_test.pdf
```

### 5.2 Server Verification

```bash
# 1. Check service status
sudo systemctl status y4_report

# 2. Check Nginx is listening
curl -I http://localhost/

# 3. Upload test
curl -X POST http://your-domain.com/api/generate \
  -F "A2=@test_A2.pdf" -F "B3=@test_B3.pdf" \
  -F "B4=@test_B4.pdf" -F "B6=@test_B6.pdf" \
  --output server_test.pdf

# 4. Compare with local
shasum server_test.pdf
# Should match local_test.pdf hash

# 5. Check logs
sudo tail -20 /var/log/y4_report/error.log
sudo tail -20 /var/log/y4_report/access.log
```

### 5.3 Rollback Plan

If online version fails:
```bash
# Restore local version — just run python app.py on Mac
# Online version can be left running or stopped
sudo systemctl stop y4_report

# Fix online version later
cd /opt/y4_report && git pull && sudo systemctl restart y4_report
```

### 5.4 Keep Local as Backup

The local version on your Mac stays exactly as is. If the online version has issues:
1. Users can continue using the localhost version
2. Debug the online version remotely
3. Restart the online version when fixed

---

## Part 6: Risks & Mitigations

| Risk | Probability | Mitigation |
|------|-------------|------------|
| Chrome headless fails on Linux | Medium | `generate.py` already has Linux Chrome paths + `--no-sandbox`. Install `chromium-browser` via apt. Test with `chromium --headless --no-sandbox --print-to-pdf=/tmp/test.pdf` |
| Chinese fonts garbled in PDF | Medium | Install `fonts-noto-cjk` + `fonts-wqy-zenhei` on server |
| Vision OCR API timeout | Low | Already configured 600s timeout in both Nginx and Gunicorn |
| File write permissions | Low | Set via `chown -R y4report:y4report` |
| API key exposed in git | Low | `.env.production` is gitignored; production key only on server |
| Worker starvation (2 workers both busy) | Low | Acceptable for single-user internal app |
| `import os` bug in app.py | **Critical** | Already identified; part of Phase 2 code changes |

---

## Summary: What Actually Changes

**Infrastructure (new files):**
- `gunicorn_config.py` — Tells Gunicorn how to serve the Flask app
- `nginx_y4.conf` — Tells Nginx to proxy to Gunicorn
- `y4_report.service` — Tells systemd to auto-start on boot
- `.env.production` — Production secrets (not committed to git)
- `deploy.sh` — One-command deployment script

**Code (existing files, minimal changes):**
- `app.py` — +4 lines (1 import + 3 config)
- `requirements.txt` — +5 dependencies
- `.gitignore` — Remove `branding/`, add `.env.production`
- `templates/index.html` — +2 lines (timeout + progress message)

**NOT changed:**
- `extract.py` — zero changes
- `generate.py` — zero changes
- `data_points.py` — zero changes
- `validate.py` — zero changes
- `templates/report.html` — zero changes
- `templates/style.css` — zero changes
- `gauge_reader.py` — zero changes
- `gauge_processor.py` — zero changes
- `_vision_values_bar.py` — zero changes

**Total: 4 existing files modified (13 lines added). 5 new config/infrastructure files created.**
