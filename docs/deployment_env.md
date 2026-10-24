# .env.production 环境变量规范

> 适用范围：生产服务器 `/opt/y4_report/.env.production`。
> 本文档只列字段名与说明，**不写真实值**。

## 加载链路

- 生产 env 注入唯一通道：`y4_report.service` 的 `EnvironmentFile=/opt/y4_report/.env.production`
  （systemd 在**启动进程时**读取该文件注入进程环境）。
- 代码内无 dotenv 依赖，应用只读 `os.environ`；本地开发靠 shell `export`。
- **env 更改后必须 `systemctl restart y4_report`**：`reload`（HUP）只让 gunicorn 用旧环境重新 exec，
  systemd 不会重读 `EnvironmentFile`。
- **生产标识（必须设置）**：`Y4_ENV=production` 需写入 `/opt/y4_report/.env.production`（systemd
  `EnvironmentFile`）。`y4_report.service` / `gunicorn_config.py` 本身不设置任何环境变量；旧版
  `deploy_server.sh` 生成的文件写的是 `FLASK_ENV=production`，代码同样识别（`Y4_ENV` 优先）——
  **建议新部署统一补 `Y4_ENV=production`**，不要依赖已过时的部署脚本。
- 生产站点经 Cloudflare Tunnel 以 HTTPS 对外，因此生产默认给会话 Cookie 加 `Secure`；
  本地 `http://localhost` 开发默认不加，登录不受影响。
- 权限基线：`chmod 600` + `chown y4report:y4report /opt/y4_report/.env.production`。
- git 排除：`.env` / `.env.production` 在 `.gitignore`（第 23-24 行），`data/`（第 18 行）同样排除。

## 字段清单

| 变量 | 必/选 | 说明 |
|---|---|---|
| `DASHSCOPE_API_KEY` | 选（现状保留） | 阿里云百炼（DashScope）API key，视觉 OCR 使用。未设置时代码回退到 `extract.py` 内置 key（**生产在用，需求方 2026-10-15 确认保留，不删不轮换**）；设置则覆盖。本期不需要为它做任何变更 |
| `SECRET_KEY` | 生产必 | Flask session / CSRF 签名密钥，强随机值，缺省开发值 `dev-key-change-in-production`。**生产（`Y4_ENV=production`）缺失或等于开发默认值 → 启动时抛 `RuntimeError` 拒绝启动**；非生产环境回退默认值并打一条 warning |
| `Y4_ENV` | 生产必 | 生产环境标识，唯一有效值 `production`，缺省未设置（视为非生产）。未设置且 `SECRET_KEY` 缺失时应用会以开发默认 key 启动，**生产务必设置**（写入 `.env.production`）。也兼容读取 `FLASK_ENV=production`，但 `Y4_ENV` 优先 |
| `Y4_COOKIE_SECURE` | 选 | 会话 Cookie 的 `Secure` 标记，取值 `1/0/true/false/yes/no/on/off`；缺省生产 `true`、非生产 `false`。生产经 Cloudflare Tunnel 走 HTTPS，默认开启；若 HTTPS 未就绪需临时登录可设 `false` |
| `Y4_INITIAL_ADMIN_USER` | 迁移期必 | 2.0 初始 admin 用户名（`scripts/migrate_2_0_foundation.py` 读取） |
| `Y4_INITIAL_ADMIN_PASSWORD` | 迁移期必 | 2.0 初始 admin 密码；迁移完成且 admin 改密后可从 env 移除 |
| `Y4_INITIAL_ADMIN_DISPLAY_NAME` | 选 | 初始 admin 显示名，缺省同用户名 |
| `Y4_API_KEY` | 必（现有） | `/api/v1/*` Bearer token（既有契约，不动） |
| `Y4_API_CORS_ORIGINS` | 选（现有） | 外部 API CORS 允许来源，缺省 `*` |
| `Y4_API_RATE_LIMIT` | 选（现有） | `/api/v1/*` 每 IP 每分钟限流次数，缺省 60 |
| `Y4_API_E4_RATE_LIMIT` | 选（现有） | E4 端点独立限流（每分钟），缺省 8 |
| `Y4_E4_CACHE_TTL` | 选（现有） | E4 结果缓存 TTL |
| `DATABASE_URL` | 选 | 缺省 SQLite `data/y4_students.db`；迁移执行前先确认生产实际值 |
| `VISION_MODEL_NAME` | 选 | 视觉 OCR 模型名，缺省 `qwen3-vl-plus` |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | 选 | 视觉 OCR 备选 provider（优先级 DASHSCOPE > OPENAI > SILICONFLOW） |
| `SILICONFLOW_API_KEY` | 选 | 视觉 OCR 备选 provider |
| `AI_TEXT_MODEL` | 选 | 文本 AI 模型，缺省 `qwen-plus` |
| `AI_TEMPERATURE` | 选 | AI 采样温度，缺省 `0.5` |
| `ITERATION_MODEL` | 选 | 迭代模型（速度优先，缺省 `qwen-turbo`） |
| `DASHBOARD_AI_MODEL` / `DASHBOARD_AI_TIMEOUT` | 选 | Dashboard AI 分析模型与超时 |
| `Y4_LOGIN_RATE_LIMIT` | 选 | 登录限流阈值（每 IP 每分钟失败次数），缺省 5 |
| `DEEPSEEK_API_KEY` | Growth Talk 必 | 画像分析（Growth Talk）使用的 DeepSeek API key。未设置时分析作业报「未配置画像分析服务，请联系管理员」；不配置则 Growth Talk 分析不可用 |
| `DEEPSEEK_BASE_URL` | 选 | DeepSeek OpenAI 兼容端点，缺省 `https://api.deepseek.com`；调用路径为 `{BASE_URL}/chat/completions` |
| `DEEPSEEK_MODEL` | 选 | 画像分析模型，缺省 `deepseek-chat` |
| `YUGUO_BASE_URL` | Yuguo 集成必 | Yuguo 服务根地址（如 `https://yuguo.example.com`），不带末尾斜杠。未设置时导师目录同步/学生导入返回「尚未配置」类 503 |
| `YUGUO_STUDENT_READ_TOKEN` | Yuguo 集成必 | 调用 Yuguo 学生导入接口的 Bearer token，需与 Yuguo 侧配置一致；本平台只校验非空，建议同样使用至少 32 字符的独立强随机值 |
| `FIRST_TOUCH_DIRECTORY_TOKEN` | Yuguo 集成必 | Yuguo / First Touch 调用本平台导师目录（`GET/POST /api/integrations/teachers`）的 Bearer token，**至少 32 字符**（代码强制，不足即按未配置返回 503） |
| `CRM_INTEGRATION_TOKEN` | CRM 集成必 | CRM 投递预约/学生交付到 `POST /api/integrations/crm/deliveries` 的 Bearer token，**至少 32 字符**（代码强制，不足按未授权返回 401）；必须与导师目录 token 分开 |

> 已移除：旧 `ADMIN_PASSWORD` 不再被任何代码读取（登录走 users 表），常量已删除；
> 若 `.env.production` 仍保留该值可安全清除。
