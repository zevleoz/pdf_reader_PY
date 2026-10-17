# Agent E 指令包：安全收尾 · 数据迁移 · 全量回归 · 上线

> 包编号：05（最后执行）
> 日期：2026-10-14
> 单一事实来源：`docs/superpowers/specs/2026-10-14-y4-platform-2.0-design.md`（下称 **spec**）。本文档所有行号与代码形状均于 2026-10-14 对照真实代码核对；A/B/C/D 包会改动 `app.py` 与模板，执行时若行号漂移，**以符号搜索（grep）为准**，行号仅作定位参考。
> 执行者假设：零上下文。所有需要知道的事实都在本文档与 spec 中。

---

## 1. 背景与目标

Y4 平台 2.0 把 1.0 的"报告转换工具"升级为多角色学生 profiling 平台（三角色账号体系 + 学生 360° 档案 + 问卷子系统 + 新导航 UI）。A–D 四个包完成结构与功能后，**E 包负责安全收尾与上线把关**：

1. ~~移除硬编码 DashScope key~~ **已取消（需求方 2026-10-15 决定）**：`extract.py` / `_vision_values_bar.py` 中的硬编码 key 是**当前生产在用**的正确 key，保留不动；E 包对这两个文件**零改动**；
2. 环境变量规范：`.env.production` 加载链路核对与文档化，确认 git 排除；
3. 登录限流复核（在 A 包实现基础上补漏）；
4. 为所有 session 认证下的 mutating 表单/接口补 CSRF token（最小实现）；
5. 汇总 A、C 两包的数据迁移脚本为一份可执行的总迁移流程（含备份与回滚）；
6. 最终删除 `templates/app_shell.js` 及旧导航残留；
7. 执行全站回归（部署前一轮、生产部署后一轮）；
8. 产出并执行上线操作单。

**完成定义**：第 6 节「验收标准」全部打勾，第 7 节回归清单两轮全绿。

---

## 2. 前置依赖（开工前逐条确认，缺一不可）

E 包在 A→(B∥C)→D 之后执行（spec 第 11 节）。开工前确认：

- [ ] **A 包完成**：`users` 表 + 初始 admin 迁移脚本、`students.student_code` 回填、`app.py` 拆分为 `blueprints/`（auth/workspace/students/reports/questionnaires/insights/tools/system/api_v1）、`@login_required` / `@role_required` 装饰器、登录限流初版、旧 `ADMIN_PASSWORD` 回退拒绝逻辑。
- [ ] **B 包完成**：`templates/layouts/admin.html`（Tailwind/Alpine CDN）、工作台 `/workspace`、Toast 组件；登录页已改为账号+密码表单。
- [ ] **C 包完成**：问卷 6 张新表（questionnaires / questionnaire_rules / assignments / assignment_tokens / student_accounts / responses + response_drafts）迁移脚本、`questionnaires_seed/` seed 导入、规则引擎、学生端 `/q/<token>` 与 `/student/login`、问卷中心管理页。
- [ ] **D 包完成**：学生 360° 档案页 `/students/<code>` 全部 6 个 tab、全部旧管理页面迁入新 layout、旧路由 302/双注册保留。
- [ ] 本地能启动：`cd PDF_converter && python3 app.py run`（或 A 包约定的新启动方式）无报错，且 A–D 各自的冒烟已通过。
- [ ] 你拥有：生产服务器 SSH 权限（`root@8.153.154.174`，密钥见 `.trae/access/y4_deploy_key`，仅部署阶段使用）。

如有任何前置项缺失，**停下来向需求方报告**，不要替 A–D 补做。

---

## 3. 现状文件地图（2026-10-14 实测核对）

### 3.1 安全问题点

| 位置 | 实测事实 | 说明 |
|---|---|---|
| `extract.py:86` | `DEFAULT_DASHSCOPE_KEY = "sk-ws-…"`（真实 key 硬编码，本文档不抄录） | **需求方已确认：该 key 为生产在用，保留不动（2026-10-15）**。E 包不得改动这一行 |
| `extract.py:88` | `DASHSCOPE_KEY = os.environ.get("DASHSCOPE_API_KEY", DEFAULT_DASHSCOPE_KEY).strip()` | env 优先、硬编码兜底的现状保留 |
| `extract.py:134` | `_refresh_vision_env()` 内同样的 `os.environ.get(..., DEFAULT_DASHSCOPE_KEY)` | 保留不动 |
| `_vision_values_bar.py:39` | 同一个 key 的第二份硬编码拷贝 | 同样**保留不动**（需求方确认） |
| `_vision_values_bar.py:43` | `os.environ.get("OPENAI_API_KEY", "") or os.environ.get("DASHSCOPE_API_KEY", DEFAULT_DASHSCOPE_KEY).strip()` | 保留不动 |
| `app.py` 及蓝图多处 | `os.environ.get("DASHSCOPE_API_KEY", extract.DEFAULT_DASHSCOPE_KEY)` 的引用（1.0 基线在 app.py:898/1098/2243/2551/2911/2989/3607；A 包拆分后位置以 grep 为准） | 保留不动；**这些引用依赖 `extract.DEFAULT_DASHSCOPE_KEY` 常量存在，删常量会导致 AttributeError——这是"不许动 key"的技术原因之一** |
| git 历史 | `git log -S 'sk-ws-'` 命中 `0183026 first commit` 与 `15cfaf9 v1.0` | 事实记录：key 在 git 历史中可见。需求方已知悉并接受该暴露面（私有仓库 + 内部使用）；**不再安排轮换** |
| `app.py:58` | `app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')` | 生产必须显式设置 `SECRET_KEY`（加入 env 清单） |
| `app.py:64` | `ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'y4admin2026')` | spec 3.3：迁移期保留读取但**不自动放行**；A 包应已实现拒绝逻辑，E 复核 |

### 3.2 认证 / 限流 / CSRF 现状（1.0 基线，A 包会改）

- 登录：`GET /login` 渲染 `templates/login.html`（单密码输入框）→ `POST /api/admin/login`（`app.py:2013`）比对 `ADMIN_PASSWORD`，成功写 `session['is_admin']`。**无任何限流**。
- 装饰器：`admin_required`（`app.py:74`，JSON 403）、`page_login_required`（`app.py:84`，302 跳 `/login?next=…`）。A 包重写为 `@login_required` / `@role_required`。
- 现有限流工具：`_v1_rate_check(limit, scope)`（`app.py:107`）——**每 IP+scope 滑动窗口**（`deque` 存时间戳，60 秒窗口，超限返回 False → 429 `RATE_LIMITED`），仅用于 `/api/v1/*`（默认 60 次/分，E4 端点 8 次/分）。spec 3.3 要求登录限流"沿用此模式"：同 IP 5 次/分钟、按失败计数、超限 429。
- **CSRF：全代码库零实现**（已 grep 确认无 csrf 相关代码、无 Flask-WTF）。所有管理端 mutating 接口靠 session cookie + `admin_required`，无 token 校验。
- `app.py:62` 已有 `ProxyFix(x_for=1, ...)`，`request.remote_addr` 在 nginx/CF Tunnel 后是真实客户端 IP，限流按 IP 计数可用。

### 3.3 部署链路（已逐文件核对，行为只读）

| 文件 | 关键事实 |
|---|---|
| `deploy/cloud-init.sh` | 阿里云 ECS 2核2G 一键初始化；clone → venv → `sed` 把 gunicorn workers 改 1 → 装 systemd unit + nginx。**脚本不启动服务**，提示人工写 `/opt/y4_report/.env.production`（`chmod 600`、`chown y4report:y4report`）后 `systemctl start y4_report` |
| `y4_report.service` | `Type=notify`；`User=Group=y4report`；`WorkingDirectory=/opt/y4_report`；**`EnvironmentFile=/opt/y4_report/.env.production`** —— 这是 .env.production 唯一被读取的地方（systemd 注入进程环境）；`ExecStart=venv/bin/gunicorn -c gunicorn_config.py app:app`；`ExecReload=kill -HUP` |
| `gunicorn_config.py` | `workers = 2`（cloud-init 改成 1）；`sync` worker；`timeout = 600`；`max_requests = 10` + jitter 2（**worker 频繁回收，异步生成必须用独立子进程**，spec 红线）；`preload_app = True`；`bind = unix:/tmp/y4_report.sock` |
| `nginx_y4.conf` | 80 → 301 HTTPS；443 主站 `proxy_pass http://unix:/tmp/y4_report.sock`；注入 `X-Real-IP` / `X-Forwarded-For` / `X-Forwarded-Proto`；`client_max_body_size 50M`；`proxy_read_timeout 600s` |
| `.gitignore:23-24` | `.env` 与 `.env.production` **已在排除清单**（`git check-ignore` 实测命中）；`data/`（第 18 行）也已排除，SQLite 库文件不会入库 |
| 代码内 dotenv | **不存在**。全仓库无 `load_dotenv` / dotenv 引用；本地开发靠 shell `export`，生产靠 systemd EnvironmentFile |
| `HANDOFF_generate_tunnel_fix.md`（仓库根目录，非 deploy/） | CF Tunnel 524 修复交接文档，结论见第 8 节引用 |

### 3.4 待删除物

- `templates/app_shell.js`（295 行，vanilla JS 侧边导航注入器，含 `data-app-shell` 挂载点约定）。
- `templates/app_shell.css`（配套样式）。
- `app.py` 中 `serve_app_shell_css` / `serve_app_shell_js` 两个路由（拆分前在 `app.py:200-209`；A 包拆分后可能在 tools/system 蓝图里，grep 定位）。
- 当前引用 app_shell 的模板共 11 个：`admin_bookings / booking / dashboard / index / internal / prompt_lab / six_am / six_am_rules / students / transcript / y4_signals`（`.html`）。**D 包迁完后这些引用应全部消失；E 包先验证再删。**

---

## 4. 禁止事项（红线）

spec 第 2 节红线**全量适用**于 E 包，无白名单例外。

**明确禁止**：
- **不得改动 `extract.py` / `_vision_values_bar.py` 一个字符**——包括其中的 DashScope key 硬编码（需求方 2026-10-15 确认：该 key 为生产在用，保留）；`extract.py` 在本次 2.0 全周期（A–E）应为**零 diff**；
- 不得改动 `generate.py` / `data_points.py` / `validate.py` / `gauge_reader.py` / `gauge_processor.py` / `new_iteration/render_v2.py` / `new_iteration/report_v2.html` / `new_iteration/branding/`；
- 不得改动 schema_124 数据契约、`data/report_data.json` 读写协议、分片上传协议（`/api/upload/chunk`）、`_run_pipeline_job` 子进程模型；
- 不得修改 `deploy/cloud-init.sh` / `y4_report.service` / `gunicorn_config.py` / `nginx_y4.conf` 的**行为**（只允许在本文档/部署文档层面记录注意事项）；
- 不得改动 `/api/v1/*` 既有契约（路径、Bearer 鉴权、响应结构、CORS 头）——**CSRF 方案对 `/api/v1/*` 豁免**；
- 不得在文档、代码、日志、提交信息中抄录真实 key 值（本文档按此执行）；
- 不得删除 `minutes_schema.py` / `minutes_docx.py`（`app.py:34-35` 顶层 import，删了应用起不来——引自 HANDOFF 文档约束提醒）；
- 不得"顺手"清理服务器上 `data/_job.json`、`data/_uploads/`、`reports` 表行等真实运行数据（HANDOFF 第 10 节明确警告）。

---

## 5. 任务分解 checklist

按顺序执行。每一步做完打勾并做该步的自验证。

### 5.1 ~~移除硬编码 DashScope key~~（已取消，保留章节号以维持交叉引用）

**需求方 2026-10-15 决定**：`extract.py` 与 `_vision_values_bar.py` 中硬编码的 DashScope key 是当前生产在用的正确 key，**保留不动，不轮换、不作废**。E 包对这两个文件零改动。

本节唯一保留动作（纯验证，不改代码）：
- [ ] 生产部署回归时，完整跑一次报告生成（4 PDF → 提取成功），确认 OCR 使用的 key 链路工作正常——这是对"现状未被破坏"的验证，不是变更。

> 备忘（不执行）：若未来重启 key 轮换，注意 `app.py` 及蓝图里多处 `os.environ.get("DASHSCOPE_API_KEY", extract.DEFAULT_DASHSCOPE_KEY)` 引用该常量，删常量会导致 AttributeError；轮换必须先改这些引用、先部署新 key 验证、再作废旧 key。

### 5.2 环境变量规范核对与文档化

已核对的事实（写进项目部署文档，不要改代码）：
- 生产 env 注入唯一通道：`y4_report.service` 的 `EnvironmentFile=/opt/y4_report/.env.production`（systemd 在**启动进程时**读取该文件注入环境）；
- 代码内无 dotenv，应用只读 `os.environ`；
- `.gitignore` 第 23-24 行已排除 `.env` / `.env.production`（`git check-ignore` 实测命中）；`data/` 已排除，SQLite 库不入库；
- 生产权限基线：`chmod 600` + `chown y4report:y4report /opt/y4_report/.env.production`（cloud-init.sh 指引）。

E 包要做的：
- [ ] 确认工作树中不存在 `.env.production`（实测：仓库内没有该文件，正常）；
- [ ] 确认 `.env` / `.env.production` / `data/` 三行仍在 `.gitignore`（如被前面包改动，恢复）；
- [ ] 在 `docs/`（或 A 包约定的位置）补齐 `.env.production` 模板说明，字段清单见第 9.2 节（**只写字段名与说明，不写真实值**）；
- [ ] 核对生产服务器上现有 `.env.production` 的 key 清单（SSH 上机 `sudo cat /opt/y4_report/.env.production | cut -d= -f1`），与 9.2 清单比对，补齐缺失项——**新 env 加完后必须 `systemctl restart y4_report`，`reload`（HUP）不会让 systemd 重读 EnvironmentFile**（见第 8 节坑 1）。

### 5.3 登录限流复核（A 包实现之上补漏）

spec 3.3 要求：登录接口同一 IP 5 次/分钟，**失败计数**超限返回 429，沿用 `_v1_rate_check` 的滑动窗口模式。

复核清单（A 包拆分后代码在 `blueprints/auth.py`，以 grep 为准）：
- [ ] 限流作用在**登录提交端点**（新表单 POST `/login` 或 A 包约定的处理路由）；旧 `POST /api/admin/login` 若仍挂载也必须同样限流或按 spec 3.3 返回"系统已升级"拒绝。
- [ ] 计数口径：**只计失败尝试**（成功登录应清空该 IP 的失败窗口或至少不计入）；窗口 60 秒、阈值 5 次、超限返回 **429**。
- [ ] 限流 key 用 `request.remote_addr`（`ProxyFix` 已在，`app.py:62`），不要误用 `X-Forwarded-For` 原始字符串自己解析。
- [ ] 429 响应在登录页有友好文案（不是白屏/堆栈）。
- [ ] **学生端登录** `/student/login` 同样限流（同一工具，独立 scope，如 `student-login`）——spec 未明文但同一威胁面，属于"补漏"。
- [ ] 若 A 包把 `_v1_rate_check` 挪到了 `app_utils.py`，确认蓝图导入路径正确、且 `_V1_RATE_BUCKETS` 仍是进程级单例（gunicorn 多 worker 下各进程独立计数是可接受的近似，不要为此引入 Redis——2G 内存小机器，spec 未要求）。

**可执行验证**：
```bash
# 本地起服务后，对登录端点连发 6 次错误密码
for i in 1 2 3 4 5 6; do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:5000/login \
    -H 'Content-Type: application/x-www-form-urlencoded' --data 'username=admin&password=wrong'
done
# 期望：前 5 次 401/200带错误文案，第 6 次 429
```

### 5.4 CSRF 最小实现（session 认证面）

**适用范围**：所有**管理端 session 认证**下的 mutating 请求（POST/PUT/DELETE 等），无论服务端渲染表单还是 `fetch()` JSON 调用。
**豁免**：`/api/v1/*`（Bearer token，无 cookie，spec 第 8 节明确不受影响）；公开面一次性 token 端点（`/q/<token>` 提交——靠不可枚举 token 本身防 CSRF）；`/api/booking` 公开预约（无 session 可劫持，不强制，可选加 Origin 检查）。

**最小实现（三件套）**：

1. **token 生成与注入**（放 A 包划出的共享模块，如 `app_utils.py` 或 `blueprints/auth.py` 顶部）：
```python
import secrets
from flask import session

def get_csrf_token() -> str:
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_urlsafe(32)
    return session["_csrf_token"]

# 注册一次（create_app 内）：
app.context_processor(lambda: {"csrf_token": get_csrf_token})
```

2. **校验**：before_request 全局校验比逐路由装饰器更难漏，推荐：
```python
from flask import request, abort, jsonify
import hmac

CSRF_EXEMPT_PREFIXES = ("/api/v1/",)          # Bearer 豁免
CSRF_EXEMPT_PATHS = {"/q/submit"}             # 以 C 包实际公开提交路由为准，用 grep 核对后填实

@app.before_request
def _csrf_protect():
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    path = request.path
    if any(path.startswith(p) for p in CSRF_EXEMPT_PREFIXES) or path in CSRF_EXEMPT_PATHS:
        return
    if not session.get("user_id"):            # 未登录的公开端点（如 /api/booking）不走 CSRF
        return
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    if not sent or not hmac.compare_digest(sent, session.get("_csrf_token", "")):
        if path.startswith("/api/"):
            return jsonify({"ok": False, "error": "CSRF 校验失败，请刷新页面重试"}), 403
        abort(403)
```
注意：`/login` 与学生端 `/student/login` 提交时还没有 `user_id`，按上面逻辑天然豁免（登录接口已由 5.3 的限流保护）。学生端已登录后的草稿保存/提交如果写管理 session 之外的独立 session key（spec 6.6 要求分离），可在豁免路径中按 C 包实际路由补入，或用同一机制给学生 session 也发 token——以 C 包实现为准，**原则：有 session cookie 的 mutating 请求就要有 token**。

3. **模板/前端接入**：
   - 服务端渲染表单：`<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`；
   - `fetch()` JSON 调用：在 `templates/layouts/admin.html` `<head>` 加 `<meta name="csrf-token" content="{{ csrf_token() }}">`，并放一个公共 JS helper：
     ```js
     const CSRF = document.querySelector('meta[name="csrf-token"]').content;
     // 所有管理端 fetch 统一加：headers: { 'X-CSRF-Token': CSRF, ... }
     ```
   - **排查存量调用**：`grep -rn "fetch(" templates/ | grep -i "post\|put\|delete"`（以及表单 `method="post"`），逐个确认带上 token。B/D 包若已封装统一 request helper，只改 helper 一处。

**可执行验证**：
```bash
# 登录拿到 cookie 后：
curl -s -o /dev/null -w "%{http_code}\n" -b cookies.txt -X POST http://127.0.0.1:5000/api/students/1 \
  -H 'Content-Type: application/json' -d '{"name":"x"}'
# 期望：403（无 token）
# 带正确 token 重放期望 200/400（业务校验），不是 403
# /api/v1/* 不带 token 但带错误 Bearer → 401（不是 403），证明豁免生效
```

### 5.5 数据迁移总脚本与执行流程

汇总 A、C 两包迁移为一次可执行、可回滚的操作。**原则：先备份，再迁移，可回滚**（spec 第 9 节）。

**执行顺序**（生产与本地一致）：
```bash
# 0) 停机（生产）
sudo systemctl stop y4_report

# 1) 备份 SQLite（生产路径 /opt/y4_report/data/y4_students.db；本地 PDF_converter/data/y4_students.db）
TS=$(date +%Y%m%d_%H%M%S)
cp /opt/y4_report/data/y4_students.db /opt/y4_report/data/y4_students.db.bak_$TS
# 同时备份 A/C 包迁移脚本要求的其他产物（若有），并把备份文件名记录下来

# 2) A 包迁移：users 表 + 初始 admin + students.student_code 回填
cd /opt/y4_report && sudo -u y4report venv/bin/python -m <A包迁移入口>   # 以 A 包指令文档给出的实际入口为准
#    预期输出：users 表创建、初始 admin 创建（用户名/密码读 Y4_INITIAL_ADMIN_USER /
#    Y4_INITIAL_ADMIN_PASSWORD，绝不硬编码）、现有学生按 id 升序补发 Y4-0001…

# 3) C 包迁移：问卷 6+1 张新表 + questionnaires_seed/ 题库 upsert
sudo -u y4report venv/bin/python -m <C包迁移入口>

# 4) 迁移后只读校验
sudo -u y4report venv/bin/python - <<'EOF'
import sqlite3
c = sqlite3.connect('/opt/y4_report/data/y4_students.db')
print('users:', c.execute('select count(*) from users').fetchone())
print('student_code 空值:', c.execute("select count(*) from students where student_code is null or student_code=''").fetchone())
print('questionnaires:', c.execute('select count(*) from questionnaires').fetchone())
print('rules published:', c.execute("select count(*) from questionnaire_rules where status='published'").fetchone())
EOF

# 5) 起服务 + 第 7 节回归
sudo systemctl start y4_report && systemctl is-active y4_report
```

**回滚步骤**：
```bash
sudo systemctl stop y4_report
cp /opt/y4_report/data/y4_students.db.bak_$TS /opt/y4_report/data/y4_students.db
git checkout <迁移前的 commit>        # 或按 HANDOFF 的 .bak 文件恢复 app.py 等
find /opt/y4_report -name __pycache__ -type d -prune -exec rm -rf {} +
sudo systemctl start y4_report
```

E 包的迁移责任边界：
- [ ] 核对 A/C 迁移脚本入口真实存在且**幂等**（重复执行不报错、不重复发 code）；
- [ ] 核对 `db.py._migrate_schema` 现状：该函数**仅对 SQLite 生效**（`db.py:145-153`，非 sqlite 直接 return）；PostgreSQL 走 `Base.metadata.create_all`。若生产是 SQLite（默认 `data/y4_students.db`），student_code 回填必须覆盖 SQLite 路径；如需求方实际使用 Postgres，提醒其新表由 create_all 创建、回填脚本需兼容——**执行前先 SSH 上机确认生产 `DATABASE_URL` 实际值**；
- [ ] 把上述命令中的 `<A包迁移入口>` / `<C包迁移入口>` 替换为真实命令后，写入最终部署 runbook。

### 5.6 删除 app_shell.js 与旧导航残留（D 包验证后执行）

- [ ] **前置验证**：`grep -rln "app_shell" templates/` 与 `grep -rn "data-app-shell" templates/` **必须零命中**（D 包应已迁完 11 个引用模板，清单见 3.4）；有命中则退回 D 包，不要删。
- [ ] 删除 `templates/app_shell.js`、`templates/app_shell.css`。
- [ ] 删除路由 `serve_app_shell_css` / `serve_app_shell_js`（1.0 基线在 `app.py:200-209`，拆分后 grep `app_shell` 定位到具体蓝图）。
- [ ] 删完后 `python3 -m py_compile` 相关模块，启动冒烟：登录 → 工作台 → 学生列表 → 档案页 → 报告生成页，每个页面 200 且无 404 静态资源（浏览器 devtools Network 面板全绿）。
- [ ] `grep -rn "app_shell" --include="*.py" --include="*.html" --include="*.js"` 全仓库零命中。

### 5.7 全站回归

执行第 7 节清单，**两轮**：部署前本地一轮、生产部署后一轮。任何一项失败：修复（或退回对应包）→ 重跑**整个**清单，不允许只重跑失败项（安全改动与迁移的影响面是全站的）。

### 5.8 部署与上线

按第 9、10 节执行。

---

## 6. 验收标准（每条都必须可执行验证）

| # | 标准 | 验证方法 | 通过判据 |
|---|---|---|---|
| 1 | ~~硬编码 key 移除~~ **已取消**：key 保留在用，OCR 链路未被破坏 | 生产/本地完整跑一次报告生成（4 PDF → 提取成功）；`git diff <A包前基线>..HEAD -- extract.py _vision_values_bar.py` | 生成成功；两个文件零 diff |
| 5 | `.env.production` 被 git 排除 | `git check-ignore -v .env.production` | 命中 `.gitignore:24` |
| 6 | 登录限流触发 429 | 5.3 的 6 连发 curl | 第 6 次 429；管理端与学生端登录都覆盖 |
| 7 | 无 CSRF token 的 session POST 被拒 | 5.4 的 curl | 403；带正确 token 放行；`/api/v1/*` 无 token + 错 Bearer 仍 401 |
| 8 | 迁移可执行可回滚 | 在备份副本上完整跑一遍 5.5 流程 + 回滚流程 | 校验 SQL 输出符合预期；回滚后旧代码能正常服务 |
| 9 | app_shell 零残留 | 5.6 的 grep | 零命中，冒烟全绿 |
| 10 | 回归全绿 | 第 7 节清单两轮 | 两轮全部通过 |
| 11 | spec 红线未被触碰 | `git diff <A包前基线>..HEAD -- extract.py generate.py data_points.py validate.py gauge_reader.py gauge_processor.py new_iteration/ deploy/cloud-init.sh y4_report.service gunicorn_config.py nginx_y4.conf` | **全部文件零 diff**（extract.py 含硬编码 key，保持原样） |

---

## 7. 全站回归 checklist（部署前 / 部署后两轮，逐项打勾）

执行方式：能用 curl 的用 curl，页面类用真实浏览器。**每条记录实际结果**，失败即中止修复。

### 7.0 冒烟

- [ ] 服务启动无异常；`GET /login` 200；`GET /api/v1/health` 返回 `{"ok": true, "status": "healthy"}`

### 7.1 1.0 功能全量回归（spec 第 10 节第 2 条）

生成主链路（用真实 4 份 PDF，A2/B3/B4/B6）：
- [ ] 分片上传：`POST /api/upload/chunk` 全部分片 200
- [ ] `POST /api/generate/start` → `{"ok":true,"keys":[...]}`；任务运行中重复 start 返回 409
- [ ] `GET /api/progress` 轮询：percent 递增至 100，status 流转 running→done
- [ ] `GET /api/generate/result` → 200，PDF 可打开，`X-Applied-Items` / `X-Total-Items` 头存在；`?v=2` 可取 v2
- [ ] 报告落库：学生列表出现该学生，报告记录存在
- [ ] 旧同步入口 `POST /api/generate` 仍挂载（无文件时 400 且文案正确，不 404）
- [ ] 报告重生成：`POST /api/reports/<id>/regenerate` → 200 PDF（不调 OCR）
- [ ] `GET /preview` 200

学生与档案：
- [ ] `GET /students` 列表正常；学生显示 `student_code`（Y4-XXXX）
- [ ] 同名不同生日学生不被合并（spec 第 4 节 find_or_create_student 微调）
- [ ] `GET /students/<code>` 档案页 6 个 tab 全部渲染：画像 / 报告 / 问卷 / 预约 / 纪要 / 6AM
- [ ] `GET /api/students`、`/api/students/<id>/reports`、`PUT/DELETE /api/students/<id>`、`DELETE /api/reports/<id>` 行为正确

洞察：
- [ ] `/dashboard` 页面 + `/api/dashboard/stats` 200；`/api/dashboard/ai-analysis` 返回 analysis JSON
- [ ] `/y4-signals` 页面 + `/api/reports/<id>/y4-signals` 200
- [ ] `/six-am` 与 `/six-am/rules` 页面 200；`/api/reports/<id>/six-am` 及 generate/answers/docx/json 端点正常；`/api/six-am/rule-versions`（GET/POST）+ publish + sandbox 正常

工具：
- [ ] `/booking`（公开）可提交预约：`POST /api/booking` 成功；满员时段 409、关闭时段 409
- [ ] `/admin/bookings` + `/api/bookings` + complete/cancel/delete 正常
- [ ] `/api/availability`（GET/POST）+ `/api/availability/month` 正常
- [ ] `/transcript` 提交逐字稿生成纪要；`/api/transcript/docx` 下载 .docx 可打开；纪要 CRUD（GET 列表/详情、PUT、DELETE）正常
- [ ] `/prompt-lab` 页面 + run/iterate/save/prompt/evaluation/e4-mapping/e4 step1-3/y4-export 端点正常
- [ ] `/internal` 内部下载页正常；`/api/export` 正常
- [ ] `/api/chat` AI 对话返回 reply
- [ ] `/api/reports/<id>/raw`、`/qualification`、`/interpret`、`/protocol-md`、`/y4-json`、`/e4-protocol`、`/evaluation` 全部正常
- [ ] `/output/<filename>` 下载需要登录（未登录 302/403）

公开面（无需登录，spec 3.3）：
- [ ] `/` 落地页 200
- [ ] `/booking` 200 且可提交
- [ ] `/api/docs` 200
- [ ] `/api/v1/*`：无 Bearer → 401；正确 Bearer → 200；覆盖 students / student reports / report meta / y4-json / y4-md / pdf / e4-protocol（e4 限流 8 次/分，连发验证 429）/ health（免 key）
- [ ] `/q/<token>`：有效 token 渲染问卷；已用/过期/伪造 token 显示对应友好文案（**不泄露管理端任何内容**）
- [ ] `/student/login` + `/student/home`：学生账号登录、待办列表、草稿保存、提交

### 7.2 2.0 新功能回归

- [ ] 三角色登录：admin / advisor / viewer 各自登录成功；停用账号（is_active=0）不可登录
- [ ] 登录后 admin/advisor 落地 `/workspace`，viewer 落地 `/students`
- [ ] 工作台 4 区块渲染：待确认问卷任务、进行中的生成作业、最近活跃学生、快捷入口
- [ ] 旧 `ADMIN_PASSWORD` 回退：users 表非空后旧密码登录被拒并提示"系统已升级，请使用账号登录"
- [ ] 问卷端到端：新报告落库 → published 规则命中 → 问卷中心出现 pending 任务 → 确认（选 link/account/both）→ status=sent → 一次性链接 `/q/<token>` 作答提交 → token 作废、assignment=submitted、responses 落库（原始 JSON）→ 档案页「问卷」tab 可见
- [ ] 临时账号路径：创建 student_account → `/student/login` 登录 → 待办列表 → 草稿保存（response_drafts）→ 提交
- [ ] token 7 天过期 → status=expired → 重新生成链接复活为 sent
- [ ] 每生每问卷活动任务去重（UNIQUE 约束生效，重复推荐不产生第二条）
- [ ] 驳回 → rejected；可再次推荐
- [ ] 题库页：列表/题目预览/启停；规则页：版本列表、新建 draft（JSON 校验 + 试算预览）、发布自动归档旧 published
- [ ] 用户管理 `/system/users` 仅 admin 可见可用
- [ ] 初始 admin 登录后工作台顶部有"修改初始密码"持续提醒
- [ ] 旧路由（如 `/students`、`/dashboard` 等 1.0 路径）按 spec 5.1 重定向或双注册可用，外链/书签不断裂

### 7.3 三角色权限矩阵（逐格验证）

| 操作 | Admin | Advisor | Viewer |
|---|---|---|---|
| 登录后落地页 | /workspace | /workspace | /students（只读） |
| 学生列表/档案 | 全部学生 | **仅自己名下**（advisor_name 匹配） | 全部只读 |
| 报告生成 /generate | ✔ | ✔（自己学生） | ✘（导航不可见 + 直接访问被拒） |
| 问卷任务确认/分发 | ✔ | ✔（自己学生） | ✘（仅只读任务列表可见，无操作） |
| 题库查看 | ✔ | ✔ | ✔（只读） |
| 规则管理 | ✔ | ✘ | ✘ |
| 用户管理 /system/users | ✔ | ✘（导航隐藏 + 403） | ✘ |
| 预约/纪要/工具写操作 | ✔ | ✔ | ✘ |
| Dashboard / y4-signals / 6AM 查看 | ✔ | ✔ | ✔（只读） |

- [ ] 矩阵逐格实测通过，特别注意 **Advisor 越权测试**：advisor A 直接访问 advisor B 学生的档案 URL / API，必须被拒或空结果（查询层隔离生效，spec 3.3）
- [ ] Viewer 所有 mutating 请求（手工构造 curl）一律 403
- [ ] 学生端 session 访问任何管理端路由被拒（session 分离，spec 6.6）

### 7.4 安全验收项（第 6 节表格逐条在目标环境重跑）

- [ ] 429 / CSRF 403 / `.env` 排除 / OCR 生成链路，部署后环境下同样通过

### 7.5 部署后追加项（仅第二轮）

- [ ] 走 CF Tunnel 域名 `https://report.p4learning-ark.app` 完整跑一遍生成主链路（真实 4 PDF），**无 524**，分片全部 < 100s
- [ ] nginx access.log 无异常 400/502 爆发；`systemctl is-active y4_report` = active
- [ ] `/var/log/y4_report/error.log` 无新增 traceback

---

## 8. 常见坑（执行前通读）

1. **env 更改后必须 restart 而非 reload**。`.env.production` 由 systemd `EnvironmentFile` 在**进程启动时**读取注入。`systemctl reload y4_report` 只是给 gunicorn 发 HUP，gunicorn 用**旧环境**重新 exec 自己，新 env 不生效。改任何 env（SECRET_KEY、Y4_INITIAL_ADMIN_* 等）后：`sudo systemctl restart y4_report`。
2. **gunicorn `preload_app = True` 的 env 读取时机**。master 启动时 import 应用模块，模块级 `os.environ.get(...)` 只读一次；`extract.py` 的 `_refresh_vision_env()` 是有意设计——每次调用前重读 env（解决"服务启动后才 export"的场景）。**不要**因为"重复读 env 不规范"而删掉它；也**不要**动 `DEFAULT_DASHSCOPE_KEY` 常量及其全部引用（key 保留在用，见 5.1）。
3. **unix socket 权限**。gunicorn 以 `y4report` 用户创建 `/tmp/y4_report.sock`，nginx worker（通常 `www-data`）需要读写它。若重启后出现 502 Bad Gateway 且 error.log 报 `connect() to unix:/tmp/y4_report.sock failed (13: Permission denied)`：检查 socket 属主与 nginx 用户，必要时 `chmod 666 /tmp/y4_report.sock` 或调整 gunicorn `umask`（改配置属部署变更，需需求方确认）；另外 `/tmp` 被 systemd PrivateTmp 隔离也会导致 nginx 看不见 socket——当前 unit 未开 PrivateTmp，**不要手痒加上**。
4. **`max_requests = 10`（+jitter 2）**：worker 每处理约 10 个请求就被回收。任何"挂在请求里的后台线程"都会被杀——异步生成作业必须是 `start_new_session=True` 的独立子进程（现状如此，HANDOFF 第 7.1 节，硬约束）。E 包不得引入任何请求内后台线程。
5. **CF Tunnel 524 与长请求**（结论引自仓库根目录 `HANDOFF_generate_tunnel_fix.md`，已核对）：Cloudflare 免费版对源站响应约 **100 秒**超时；所有耗时操作必须作业化（分片上传 + 异步子进程 + 轮询）。已知**仍为同步**的长请求：`POST /api/chat`、`POST /api/transcript`、`/api/dashboard/ai-analysis` 等 AI 调用端点，模型慢时在隧道下可能 524——**本期不修**（HANDOFF 第 12.1 节列为已知遗留），回归时若偶发 524 先区分是这些端点的既有问题还是新引入的回归，不要把既有问题当 E 包失败，也不要顺手改这些端点。另外注意：该域名直连 A 记录 + Let's Encrypt 方案已被阿里云 ICP/DPI 拦截判死，**CF Tunnel 必须保留**，任何"换回直连"的提议都是错的（HANDOFF 第 2 节）。
6. **单例作业与全局目录**：`_job.json` / `input/` / `output/` 是全局单例，同时只允许一个生成任务（第二个被 409）。回归"生成主链路"时确保上一轮任务已结束；`_job_running()` 有 20 分钟卡死阈值，不要用"删 `_job.json`"来解锁生产环境（HANDOFF 第 10 节明确禁止删真实运行数据）。
7. **`git checkout` 回滚粒度**：本地工作树混有历史 WIP（HANDOFF 附录约束：不要把 `app.py`/`db.py` 整个 checkout 回 HEAD 以外的某个旧版本而不加分辨）。回滚只用 5.5 给出的"备份文件恢复"路径。
8. **DashScope key 保留在用（2026-10-15 需求方决定）**：硬编码 key 不删不轮换。执行中若任何步骤"顺手"动了 `extract.py` / `_vision_values_bar.py` 的 key 相关行，立即回退——`app.py`/蓝图中多处 `extract.DEFAULT_DASHSCOPE_KEY` 引用依赖该常量存在，误删 = 生产 OCR 全面中断。
9. **`SECRET_KEY` 默认值**：`app.py:58` 缺省 `'dev-key-change-in-production'`。生产 `.env.production` 必须显式设置强随机 `SECRET_KEY`，否则 session 签名可预测，CSRF 与登录态全部白做。加入 env 清单（9.2）并上线前核对。
10. **worker 数与限流**：gunicorn 多 worker 下 `_V1_RATE_BUCKETS` 是进程内字典，限流计数按 worker 分裂（cloud-init 把 workers 改为 1，影响消失；若需求方未来改回 2，知道这一现象即可，不要为此加依赖）。

---

## 9. 部署注意事项

### 9.1 部署/重启顺序（生产，`/opt/y4_report`）

```bash
# 1) 上线代码
cd /opt/y4_report && sudo -u y4report git pull        # 或按既定发布方式
sudo -u y4report venv/bin/pip install -r requirements.txt   # 若 A–E 有新增依赖（应保持零新增，核对）
# 2) 更新 env（如有新变量），注意 600 权限与属主
sudo nano /opt/y4_report/.env.production && sudo chmod 600 /opt/y4_report/.env.production
# 3) 清字节码缓存（避免旧 .pyc 干扰，沿用 HANDOFF 惯例）
sudo find /opt/y4_report -name __pycache__ -type d -prune -exec rm -rf {} +
# 4) 迁移（见 5.5：先 stop → 备份 → 迁移 → start）
# 5) 重启（env 变更必须 restart，不是 reload）
sudo systemctl restart y4_report && systemctl is-active y4_report
sudo nginx -t && sudo systemctl reload nginx           # 仅在 nginx 配置有变时；本期不应有变
# 6) 回归第 7 节第二轮
```

CF Tunnel 侧：无需操作（隧道配置不变）；部署后用隧道域名跑 7.5 验证 524 不复发。

### 9.2 环境变量清单（`.env.production` 应有字段；只列名，不写值）

| 变量 | 必/选 | 说明 |
|---|---|---|
| `DASHSCOPE_API_KEY` | 选（现状保留） | 未设置时代码回退到 `extract.py:86` 内置 key（**生产在用，需求方确认保留**）；设置则覆盖。本期不需要为它做任何变更 |
| `SECRET_KEY` | 必 | Flask session 签名，强随机（坑 9） |
| `Y4_INITIAL_ADMIN_USER` / `Y4_INITIAL_ADMIN_PASSWORD` | 迁移期必 | A 包初始 admin 迁移用；迁移完成、admin 改密后可从 env 移除 |
| `Y4_API_KEY` | 必（现有） | `/api/v1/*` Bearer token（既有，不动） |
| `Y4_API_CORS_ORIGINS` / `Y4_API_RATE_LIMIT` / `Y4_API_E4_RATE_LIMIT` / `Y4_E4_CACHE_TTL` | 选（现有） | 既有默认值可用 |
| `ADMIN_PASSWORD` | 迁移期保留 | 仅作"已升级"拒绝提示的判断（spec 3.3）；不用于放行 |
| `DATABASE_URL` | 选 | 缺省 SQLite `data/y4_students.db`；**执行迁移前先上机确认生产实际值** |
| `VISION_MODEL_NAME` / `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `SILICONFLOW_API_KEY` | 选 | 视觉 OCR 备选 provider（extract.py 优先级 DASHSCOPE > OPENAI > SILICONFLOW） |
| `AI_TEXT_MODEL` / `AI_TEMPERATURE` / `ITERATION_MODEL` / `DASHBOARD_AI_MODEL` / `DASHBOARD_AI_TIMEOUT` | 选 | 既有默认值可用 |

---

## 10. 上线操作单（严格按顺序执行，每步确认后再进行下一步）

1. **预检**：A–D 前置依赖（第 2 节）全部打勾；本地回归（第 7 节第一轮）全绿；`git status` 干净、已提交。
2. **备份**（生产）：
   ```bash
   ssh -i .trae/access/y4_deploy_key root@8.153.154.174
   systemctl stop y4_report
   TS=$(date +%Y%m%d_%H%M%S)
   cp /opt/y4_report/data/y4_students.db /opt/y4_report/data/y4_students.db.bak_$TS
   cp /opt/y4_report/.env.production /root/.env.production.bak_$TS   # 备份到 root 家目录，不进仓库
   ```
3. **更新 env**：确认/补 `SECRET_KEY`（强随机，坑 9）、写入 `Y4_INITIAL_ADMIN_USER` / `Y4_INITIAL_ADMIN_PASSWORD`；`chmod 600`。**不需要动 `DASHSCOPE_API_KEY`**（key 保留在用，5.1）。
4. **部署代码**：9.1 第 1、3 步。
5. **迁移**：5.5 第 2–4 步（A 迁移 → C 迁移 → 只读校验 SQL 输出符合预期）。
6. **启动**：`systemctl start y4_report` → `is-active` = active → `curl -s localhost 路径` 冒烟（经 nginx 或 unix socket）。
7. **生产回归**：第 7 节第二轮 + 7.5 追加项，全绿（其中必须含一次完整报告生成，确认 OCR key 链路正常）。
8. **收尾**：移除 `Y4_INITIAL_ADMIN_PASSWORD`（admin 已改密后）；记录迁移备份文件名与位置；更新部署 runbook；通知需求方验收 spec 第 10 节整体验收清单。
9. **回滚预案**（任何一步失败时）：按 5.5「回滚步骤」恢复 DB 备份 + 代码备份 + 旧 env 备份，重启服务，再排查。

---

*文档结束。执行中发现本文档与代码现状不一致（行号漂移除外），停下来向需求方确认，不要自行决断。*
