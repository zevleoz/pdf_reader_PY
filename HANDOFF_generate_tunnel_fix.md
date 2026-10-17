# Handoff / QC 文档：Cloudflare Tunnel 下 `/generate` 失败修复

> 作者：Trae Agent
> 日期：2026-10-09
> 状态：**代码已修改、已部署到生产（report.p4learning-ark.app / 8.153.154.174）**，本地工作树亦为同一版本。
> 目的：交给另一个 agent 做 code QC / 风险评估。**请重点看第 8 节「QC 关注点」。**

---

## 1. 一句话摘要

把原本「一次性上传 4 份 PDF（~19MB）+ 同步生成（2–3 分钟）」的 `POST /api/generate`
拆成 **分片上传 → 异步子进程作业 → 轮询进度 → 取回结果** 四个短请求，
以绕开 Cloudflare 免费版代理的 ~100 秒源站响应超时（HTTP 524）。

---

## 2. 背景与根因

### 现象
- `http://8.153.154.174/generate`（直连 IP）能正常生成 PDF。
- `https://report.p4learning-ark.app/generate`（走 Cloudflare Tunnel）其他功能都正常，**只有生成功能失败**。

### 根因（已确证，非推测）
`POST /api/generate` 是**同步**接口，单次请求内同时承担：
1. 接收 ~19MB multipart 上传；
2. 跑 extract（含视觉 OCR API 调用）→ validate → generate（Chrome 打印 PDF）→ 入库 → 返回 PDF，耗时 2–3 分钟。

Cloudflare 免费版代理对「源站响应」有约 100 秒超时，于是隧道返回 **HTTP 524** 并中断。

### 关键证据
- 隧道下完整 generate：HTTP **524**，`time_total≈126.9s`，body `error code: 524`。
- 同一请求走直连 IP：HTTP 200，2MB PDF。
- 上传 1MB：隧道 53KB/s vs 直连 12MB/s。
- nginx `access.log` 里隧道侧的历史 `POST /api/generate` 记录为 `400 0`（Cloudflare 中断时 nginx 的特征日志）。
- 本次复现同样产生 `"POST /api/generate" 400 0 "curl/8.7.1"`。

### 被排除的方案（重要，勿重试）
「改回直连 A 记录 + Let's Encrypt」不可行：该域名在阿里云大陆 ECS 上被 ICP 拦截（403 Beaver 页），
且任何 SNI 含 `p4learning-ark.app` 的 TLS 在多端口都被 DPI 重置。
**Cloudflare Tunnel 必须保留，修复只能是应用层的。** 相关结论已记录在项目 memory 中。

---

## 3. 改动文件总览

| 文件 | 变更量 | 说明 |
|---|---|---|
| `app.py` | +~370 / -~155 | 新增任务基础设施与 3 个接口；抽取 2 个 helper；`/api/progress` 扩展 |
| `templates/index.html` | +~150 / -~45 | `generate()` 重写为分片上传 + 轮询 + 取结果 |

> 注意：本地 git 工作树里另有**与本任务无关的既有改动**（`templates/students.html`、`.DS_Store`、`__pycache__` 等），
> 不是本次引入，QC 时请只看上面两个文件。

---

## 4. `app.py` 改动清单（含行号）

### 4.1 新增常量（约 L35–48）
```
UPLOAD_DIR    = DATA_DIR / "_uploads"     # 分片暂存目录
JOB_FILE      = DATA_DIR / "_job.json"    # 任务状态（原子写）
JOB_LOG_FILE  = DATA_DIR / "_job.log"     # 子进程 stdout/stderr
```

### 4.2 新增任务基础设施（L263–493，含注释说明）
| 函数 | 行号 | 职责 |
|---|---|---|
| `_write_job(**fields)` | L280 | 读改写 `_job.json`，写临时文件后 `os.replace` 原子落盘 |
| `_read_job()` | L298 | 读 `_job.json` |
| `_job_running()` | L307 | 是否运行中；**updated_at 超 20 分钟视为卡死**，不阻塞新任务 |
| `_apply_mindset_override(score)` | L316 | 从 `api_generate` 内联逻辑**原样抽出**（思维模式 059 覆盖） |
| `_clean_y4(v)` | L348 | 从内联抽出 |
| `_save_report_to_db(pdf_path, sid, name)` | L353 | 从 `api_generate` 内联逻辑**原样抽出**（入库归档） |
| `_find_generated_pdf()` | L414 | 定位 `output/` 下刚生成的 PDF（优先 `凭远Y4评测报告_*`） |
| `_run_pipeline_job(job)` | L424 | 无 Flask 上下文执行 extract→validate→mindset→generate→入库；写 `_job.json` |

### 4.3 新增接口
| 路由 | 行号 | 鉴权 |
|---|---|---|
| `POST /api/upload/chunk` | L496 | `@admin_required` |
| `POST /api/generate/start` | L525 | `@admin_required` |
| `GET  /api/generate/result` | L620 | `@admin_required` |

### 4.4 修改接口
- `GET /api/progress`（L657）：**向后兼容扩展**。原返回值 `{stage,percent,message}`，
  新增 `{status, filename, error}`。`percent` 取 `_job.json` 与 `_progress.json` 的较大值，
  但**仅当 `_progress.json` 的 mtime ≥ `job.started_at`** 才采信（避免上一次运行的残留进度污染）。

### 4.5 `api_generate()`（L696，**保留，未被删除**）
同步管道**完整保留**，仅两处替换为等价 helper 调用（纯代码搬移，行为一致）：
- 内联 mindset 块 → `_apply_mindset_override(request.form.get('mindset_score'))`
- 内联入库块 → `_save_report_to_db(pdf_path, ...)`

### 4.6 子进程入口（`__main__`，L4457 起）
```
python app.py genjob <args.json>   → sys.exit(_run_pipeline_job(json.load(args.json)))
python app.py run                  → 原有独立跑管道模式（未改动）
```

---

## 5. `templates/index.html` 改动清单（含行号）

| 内容 | 行号 |
|---|---|
| `const CHUNK_SIZE = 1 * 1024 * 1024;` | L938 |
| `sleep(ms)` | L940 |
| `uploadFileChunked(key, file, uploadId, onBytes)` | L945 |
| `pollGenerateProgress(progFill, progText)` | L968 |
| `async function generate()` 重写 | L990 |

流程：上传阶段映射进度条 0→30%，生成阶段映射 30→100%；完成后 `fetch('/api/generate/result')` 取 blob，
沿用原有的 `saveReportToSession` / 下载按钮 / `autoStartAIInterpretation()`。
删除了原来的 `AbortController` 15 分钟超时，改为轮询内 20 分钟上限。

---

## 6. 接口契约

### `POST /api/upload/chunk`（admin）
- multipart：`key` ∈ {A2,B3,B4,B6}，`upload_id`（`[A-Za-z0-9_-]{1,64}`），`chunk_index`(int)，
  `total_chunks`(int，服务端暂未使用)，`chunk`(file)
- 行为：写入 `data/_uploads/<upload_id>/<KEY>.part`；`chunk_index==0` 截断重写，否则追加
- 返回：`{"ok":true,"received":<chunk_index>}` / 400 / 403

### `POST /api/generate/start`（admin）
- multipart：`upload_id`，`manifest`(JSON `{"A2":{"filename":"xxx.pdf"},...}`)，
  可选 `mindset_score` / `student_id` / `manual_student_name`
- 行为：校验 `upload_id` → 清空 `input/*.pdf` → 每个 `<KEY>.part` 移到 `input/report_<KEY>.pdf`
  （B6 依据 manifest 文件名里的「高中/初中」加后缀）→ 删除分片目录 → 若有**存活**任务则 409 →
  写 `_job_args.json` → `_job.json` 置 running（带 `started_at`）→
  `Popen([sys.executable, "app.py", "genjob", args], cwd=BASE_DIR, start_new_session=True, stdout/stderr→_job.log)`
  → **sleep 0.3s 后 `poll()`**，若子进程已退出则返回 500 并附日志尾部
- 返回：`{"ok":true,"keys":[...]}`

### `GET /api/generate/result`（admin）
- 读 `_job.json`：非 done → 409；文件不存在 → 404
- 返回 PDF 附件，`Content-Disposition: filename*=UTF-8''...`（RFC5987），
  以及 `X-Applied-Items` / `X-Total-Items`

### `GET /api/progress`（admin）
- 返回 `{stage,percent,message,status,filename,error}`；`status` ∈ idle/running/done/error

### `_job.json` 字段
`status, percent, message, error, filename, pdf_path, applied, total, started_at, updated_at, trace`

---

## 7. 设计取舍与理由

1. **子进程而非线程**：`gunicorn_config.py` 有 `max_requests=10`，worker 回收时会连带杀掉派生线程；
   `start_new_session=True` 的独立进程不受影响。这是硬约束，不能改成线程。
2. **分片大小 1MB**：目标「每个请求 < 100s」。实测最慢单片的场景是**冷启动 TLS + 无连接复用**（curl，67s/1.5MB）；
   浏览器有 keep-alive 会更快。为留余量，从 1.5MB 降到 1MB。
3. **文件式任务状态**：gunicorn 多 worker（workers=2）共享文件状态，无需引入队列/Redis。
4. **`started_at` 门控 `_progress.json`**：避免上一次运行的残留进度把新任务的进度条顶到 95%。
5. **20 分钟卡死阈值**：防止子进程异常死亡后 `_job.json` 永远 running、后续任务全被 409 拒绝。

---

## 8. QC 关注点（请重点审这些）

### 高优先级
1. **子进程环境继承**：`sys.executable` 在 gunicorn（`preload_app=True`，venv 启动）下是否为 venv python？
   `DASHSCOPE_API_KEY` 等是否通过 systemd `EnvironmentFile` 进入 gunicorn 并被 `Popen` 继承？
   （本次实测隧道/直连均成功，说明当前环境 OK，但请确认这是**结构性**而非巧合。）
2. **并发 / 多租户**：任务状态 `_job.json` 与 `input/`、`output/` 都是**全局单例**。
   任意时刻只能有一个生成任务；两个用户同时点生成，后者会被 409 拒绝。
   请判断这是否可接受，或需要按 session/upload_id 隔离。
3. **卡死阈值可被绕过导致并发**：`_job_running()` 在「20 分钟无更新」时返回 False，
   若某个合法任务恰好长时间无进度写入（例如某个慢 API 调用），可能被允许启动第二个任务，
   二者共用 `input/`、`output/` → 存在竞态（进度、PDF 文件名可能互相覆盖）。
   请评估阈值/机制是否够稳。
4. **`/api/generate/result` 的文件名信任链**：`filename` 来自 `_job.json`，其值源自在 `output/` 内 glob 到的
   `pdf_path.name`，理论上不含路径分隔符。请确认不存在路径穿越或读到非预期 PDF 的可能。
5. **分片上传失败无重试**：`uploadFileChunked` 遇非 200 直接抛错中断；已上传的分片残留在
   `data/_uploads/<upload_id>/`。目前**只有**在 `start` 成功时才会删除该目录，
   失败/放弃的上传会**残留孤儿目录**。请确认是否需要清理策略（janitor / TTL / 前端重试）。

### 中优先级
6. **前端 20 分钟轮询上限**与后端 20 分钟卡死阈值是否一致合理。
7. **旧入口 `POST /api/generate` 保留但 UI 不再调用**：属于有意保留（向后兼容脚本/集成）。
   请判断是否希望移除以避免逻辑漂移，或反过来在 UI 保留直连时走旧入口。
8. **`total_chunks` 服务端未校验**：仅前端用于切片循环；未校验分片完整性（是否丢片/乱序）。
   当前依赖「顺序上传 + 索引 0 截断」这一隐含约定。请评估是否需要显式校验（如 md5/分片计数）。
9. **进度条映射**为前端硬编码（上传 0–30%，生成 30–100%），非后端返回。
10. **`_run_pipeline_job` 与 `api_generate` 仍是两段相似编排**（共享 helper，但控制流各自一份）。
    是否进一步统一为单一实现、让 `api_generate` 变成薄封装？

### 低优先级
11. `_job.log` 无轮转，长期会增长。
12. `data/_job.json` 无 TTL，页面刷新时会回放上一次任务的 done 状态（前端只在生成时轮询，影响有限）。

---

## 9. 验证证据

### 9.1 隧道端到端（从源站经 Cloudflare Tunnel，真实 4 份 PDF，~17MB）
- 登录 200；分片上传**全部 200**，最慢单片刻 **67s**（冷 TLS；均 < 100s）
- `POST /api/generate/start` 立即返回 `{"ok":true,"keys":["A2","B3","B4","B6"]}`
- 进度：5→20→60→75→95→100，`status:"done"`
- `GET /api/generate/result` → **HTTP 200**，`size=2032103`，`time≈9s`，有效 PDF（8 页），`X-Applied-Items: 134/134`
- **无 524**

### 9.2 直连 IP 端到端（同一套前端新流程，真实 4 份 PDF）
- 分片上传每片 **1–4s**，全部 200
- 进度 5→20→75→95→100，done
- `result` → **HTTP 200**，`size=2032067`，有效 PDF（8 页），`134/134`

### 9.3 真实浏览器验证（直连 IP，最有价值的一条）
2026-10-09 16:37:59–16:42:31，**真实浏览器（Safari）**从 `http://8.153.154.174/generate`
走**新流程**完成了一次真实生成（nginx access.log 可查，客户端 IP `120.204.219.231`）：
- 一串 `POST /api/upload/chunk` 全部 **200**
- `POST /api/generate/start` → **200**
- 产出 `output/凭远Y4评测报告_Eason.pdf`，`_job.json` 落为 `status=done, applied=134, total=134`
- DB `reports` id=47（学生 Eason）

### 9.4 旧入口存活
- `POST /api/generate`（无文件）→ `400 {"ok":false,"error":"请至少上传一份PDF文件"}`，路由正常挂载

### 9.5 静态检查
- `python3 -m py_compile app.py` 通过
- 内联 JS 用 `new Function()` 语法校验通过
- 服务器 `venv/bin/python -m py_compile app.py` 通过，`systemctl is-active y4_report` = active，`curl /login` = 200

---

## 10. 服务器当前状态与清理情况（**QC 请勿误删**）

### 只清理了「我自己的测试产物」
- **DB**：我测试产生的 `reports` 行已删除；用户/他人真实生成的记录**一律保留**：
  - `id=46` Sean，2026-10-08（用户直连生成，保留）
  - `id=47` Eason，2026-10-09 16:42（**真实浏览器直连、走新流程生成，保留**）
  - 当前 `reports` max id = **47**
- **服务器 /tmp**：我创建的 `/tmp/y4test`、`/tmp/direct_test.sh`、`/tmp/y4direct` 已删除。

### 目前仍存在的运行时文件（属于真实使用，**不要删**）
- `data/_job.json`：当前是 Eason 那次真实生成的 `status=done` 状态。
- `data/_uploads/`：空目录。
- `data/_job.log`、`input/`、`output/` 下的真实产物。

> ⚠️ 结论：我在验证结束后曾把 `_job.json`/`_uploads` 清空；随后用户真实使用又重新生成了这些文件。
> **不要**为了"恢复干净状态"再删 `_job.json` 或 `reports` 行——那会破坏真实数据。

### 未处理（既有遗留，不在本次范围）
- `output/` 下的历史非正式 PDF（`demo_elegant_report.pdf`、`reference.pdf`、`report copy.pdf` 等），
  memory 里曾要求清理，本次未动。

---

## 11. 部署与回滚

### 已部署内容
- 服务器 `/opt/y4_report/app.py`、`/opt/y4_report/templates/index.html` 已更新（已 `chown y4report:y4report`、清 `__pycache__`、重启 `y4_report`）。
- **备份**（回滚用）：
  - `/opt/y4_report/app.py.bak_20261008_145058`
  - `/opt/y4_report/templates/index.html.bak_20261008_145058`

### 回滚步骤
```bash
ssh -i .trae/access/y4_deploy_key root@8.153.154.174
cp /opt/y4_report/app.py.bak_20261008_145058 /opt/y4_report/app.py
cp /opt/y4_report/templates/index.html.bak_20261008_145058 /opt/y4_report/templates/index.html
chown y4report:y4report /opt/y4_report/app.py /opt/y4_report/templates/index.html
find /opt/y4_report -name __pycache__ -type d -prune -exec rm -rf {} +
systemctl restart y4_report && systemctl is-active y4_report
```
（本地工作树的回滚：`git checkout -- app.py templates/index.html`，会丢失本次改动。）

---

## 12. 未做 / 可选后续方向（想改但**没有**改）

1. **AI 解读异步化**：`POST /api/chat` 也是同步请求，若模型耗时 >100s，走隧道同样会 524。
   用户反馈「其他功能正常」，故未动。若后续出现，同样需要作业化。
2. **分片上传增强**：失败重试 + 自适应分片（慢链路自动调小，如 512KB）+ 断点续传。
3. **孤儿分片清理**：`data/_uploads/` 的 TTL janitor。
4. **任务按用户隔离**：若需要支持多人并发生成，改为 per-upload_id / per-session 的作业状态与目录。
5. **统一编排实现**：让 `api_generate` 成为 `_run_pipeline_job` 的薄封装，消除两段相似控制流。
6. **清理 `output/` 历史非正式 PDF**（既有遗留项）。
7. **把 E2E 测试脚本纳入仓库**（本次为临时脚本，已删除）。
8. 若确有必要：按 Host 判断，让直连走旧的一次性请求、隧道走新流程（**不推荐**，收益低、复杂度高）。

---

## 13. 附：本次临时验证脚本的等价形态（已删除，供复现）

思路：`split -b 1000000` 切片 → 逐片 `curl -F key=/upload_id=/chunk_index=/chunk=@片` 打
`/api/upload/chunk` → `curl -F upload_id/manifest` 打 `/api/generate/start` → 循环打 `/api/progress`
→ `curl /api/generate/result -o result.pdf`。隧道与直连分别把 `BASE` 设为域名/IP 即可。

---

# 附：会议纪要 v2（结构化管线）已关闭，仅留档

> 追加于 2026-10-12。与上文的 524 修复**无关**，仅记录本次"会议纪要翻新"期间对本地 v2 处理的留痕。

## 背景

本地工作区曾存在一套会议纪要"结构化管线"（未 commit、未部署），与线上 v1 链路并存：

| 文件 | 作用 |
|---|---|
| `prompts/transcript_summary_v2.md` | v2 Prompt，要求 LLM 输出固定结构 JSON（schema `minutes-v1`） |
| `minutes_schema.py` | Schema 校验/归一 + 预览 Markdown 渲染（`validate_minutes` / `minutes_to_markdown`） |
| `minutes_docx.py` | 结构化数据 → McKinsey 风格 DOCX 渲染（`build_minutes_docx`） |
| `docs/minutes_docx_spec.md` | 面向下游系统的机器解析规范 |

`app.py`（本地未提交版本）L1049 的判断为：**无自定义 Prompt 且 `prompts/transcript_summary_v2.md` 存在 → 走 v2 结构化管线**；否则回退 v1（`transcript_summary.md` + `_build_docx`）。

## 本次处理（关闭方式）

把 `prompts/transcript_summary_v2.md` **改名为 `prompts/transcript_summary_v2.md.disabled`**。改名后 `app.py` 的"文件存在"判断不再成立，本地立即回退 v1 链路（与生产一致）。v2 代码/模块**原样保留**，未删除、未提交。

## 恢复方法

将文件名改回 `prompts/transcript_summary_v2.md` 即可重新启用 v2 结构化管线（届时 `app.py` 会自动优先走 JSON 路径）。

## 状态

未 commit。重启"机器可读会议纪要"需求时再启用。当前线上与本地均以 v1（`prompts/transcript_summary.md` → `_build_docx`）为准。

## 约束提醒（勿踩）

* 不得删除 `minutes_schema.py`、`minutes_docx.py`：`app.py:34-35` 顶层 import 它们，删除会导致应用无法启动。
* 不得把 `app.py`、`db.py` `git checkout` 回 HEAD：其中混有与本次无关的 WIP（分片上传/异步生成任务）。