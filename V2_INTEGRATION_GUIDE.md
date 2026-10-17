# v2 新版报告并行接入 · 实施说明书（给 Trae）

> **状态：已上线（2026-10）。** 其中第 5 节「档案页重生成下载」当时未部署，后拆为独立说明书 `REGENERATE_PDF_GUIDE.md`，以那份为准。

> 作者：Kimi Code Agent
> 日期：2026-10-09
> 前置：本仓库本地工作树中已存在一套**完成并验证过的参考实现**（未部署），见第 3 节。你可以直接审阅采用，或按第 4 节规格自行实施——两者必须一致。
> 硬约束：**v1 生成流程（extract/OCR API → validate → apply_report_data → generate.main() 主体）一行都不能动**；v2 任何失败不得影响 v1。

---

## 1. 目标

每次现有流程产出 `output/凭远Y4评测报告_<姓名>.pdf`（下称 v1）后，**并行**产出一份新版设计
`output/凭远Y4评测报告_v2_<姓名>.pdf`（下称 v2），前端在生成完成后出现一个**带 Beta 徽章**的独立下载按钮。

- v2 使用独立模版与渲染器（`new_iteration/`，20 页，与 v1 模版无关）
- v2 失败只打警告，主任务照常完成
- DB 入库只存 v1；v2 是文件系统并行产物
- 用户不选择下载 v2 时，体验与现状完全一致

## 2. v2 渲染器（已存在，无需重写）

`new_iteration/` 目录（本地工作树已有，需一并部署到服务器 `/opt/y4_report/new_iteration/`）：

| 文件 | 作用 |
|---|---|
| `report_v2.html` | Jinja2 模版（20 页 A4，全部 SVG 图标内联，无外部依赖） |
| `render_v2.py` | `build_context(student, d)` + `render_html_to(data_path, out_html)`；独立运行 `python3 render_v2.py` 可出样稿+preview 截图 |
| `branding/` | logo 资源（模版以相对路径 `branding/...` 引用，**渲染出的 HTML 必须放在含 branding/ 的目录**——管线里放 `output/`，v1 的 render_html 已把 branding 拷到那里） |
| `stress_test/` | 异常态验证工具（可选部署） |

数据源：与 v1 相同的 `data/report_data.json`（schema_124，extract 产物）。v2 只读它，不写。

## 3. 本地工作树已有的参考实现（未部署）

以下改动已在本地完成并通过验证（CLI 双产出、接口断言、真实 HTTP 登录下载）：

- `generate.py`：`main()` 末尾追加 `[4/4]` v2 步骤
- `app.py`：三处小改
- `templates/index.html`：v2 下载按钮（**缺 Beta 徽章，见 4.4**）
- `new_iteration/`：整个目录是新增

`git status` 中与本任务相关的变更即这些。`templates/students.html` 等其他改动与本次无关。

## 4. 实施规格

### 4.1 `generate.py` — main() 末尾追加（v1 逻辑一行不动）

在重命名块之后、收尾打印之前：

```python
    # --- [4/4] v2 新版设计（并行输出，失败不影响 v1）---
    try:
        import sys as _sys
        _ni = str(project_dir / "new_iteration")
        if _ni not in _sys.path:
            _sys.path.insert(0, _ni)
        import render_v2

        v2_html = output_dir / "report_v2.html"
        render_v2.render_html_to(report_data_path, v2_html)
        v2_base = f"凭远Y4评测报告_v2_{safe_name}" if student_name else "凭远Y4评测报告_v2"
        v2_pdf = output_dir / f"{v2_base}.pdf"
        if v2_pdf.exists():
            v2_pdf.unlink()
        generate_pdf_with_chrome(v2_html, v2_pdf)
        print(f"\n[4/4] v2 新版已生成: {v2_pdf.name}")
    except Exception as exc:
        print(f"\n  [警告] v2 新版生成失败（不影响主报告）: {exc}")
```

要点：
- 整段必须在 `try/except Exception` 里，只打印警告，**不得 raise**
- Chrome 打印复用现有 `generate_pdf_with_chrome()`（含服务器 chromium 查找），不要新写
- 位置在重命名块之后，`student_name` / `safe_name` / `report_data_path` 均已就位
- 子进程（genjob）和旧同步入口 `POST /api/generate` 都调 `generate.main()`，两条路自动都产 v2

### 4.2 `app.py` — 三处小改

**(a) `_find_generated_pdf()`——必须改，否则出生产事故：**
`凭远Y4评测报告_v2_X.pdf` 中 `'v'` 的 Unicode 码位小于任何中文姓氏，sorted() 后会排在 v1 前面，被误当主报告返回给用户。

```python
    # 排除并行产出的 v2 新版，主报告永远是 v1
    named = [f for f in pdf_files if "凭远Y4评测报告" in f.name and "_v2_" not in f.name]
```

**(b) `_run_pipeline_job()`——v1 定位后、写 done 状态前，探测 v2：**

```python
        # 并行产出的 v2 新版（可选，不存在不阻塞）
        filename_v2 = ""
        m = re.match(r"^凭远Y4评测报告_(.+)\.pdf$", pdf_path.name)
        if m:
            v2_candidate = OUTPUT_DIR / f"凭远Y4评测报告_v2_{m.group(1)}.pdf"
            if v2_candidate.exists():
                filename_v2 = v2_candidate.name
```

然后 done 状态的 `_write_job(...)` 里加 `filename_v2=filename_v2`。
（`_write_job` 支持任意字段；`_job.json` 契约新增字段，向后兼容。）

**(c) `/api/generate/result`——支持 `?v=2`：**

```python
    name = job.get("filename") or ""
    if request.args.get("v") == "2":
        name = job.get("filename_v2") or ""
        if not name:
            return jsonify({"ok": False, "error": "本次生成没有 v2 新版报告"}), 404
```

响应头追加 `resp.headers["X-V2-Available"] = "1" if job.get("filename_v2") else "0"`。
路径安全：`send_from_directory` 自带 `safe_join`，`filename_v2` 由 OUTPUT_DIR 内文件名推导，无穿越风险。

### 4.3 `_run_pipeline_job` 的 output/ 清理 glob

现有 `["report.pdf", "report.html", "凭远Y4评测报告_*.pdf", "凭远Y4评测报告_*.html"]` **已覆盖 v2 旧产物**，不用改。旧同步入口 `api_generate` 里的同款清理也一样，不用改。

### 4.4 `templates/index.html` — v2 按钮 + **Beta 徽章**（用户明确要求）

工具栏"下载报告"按钮后加：

```html
<button class="btn btn-secondary" id="downloadV2Btn" style="display:none" onclick="downloadV2Pdf()">
  下载新版报告 <span class="beta-badge">Beta</span>
</button>
```

CSS（小样式，放页面 style 里）：

```css
.beta-badge {
    display: inline-block; margin-left: 4px; padding: 1px 6px;
    font-size: 10px; font-weight: 700; line-height: 1.4;
    color: #fff; background: #f59e0b; border-radius: 999px;
    vertical-align: 2px; letter-spacing: 0.5px;
}
```

JS 三处：
1. 生成完成取回 v1 后（`fetch('/api/generate/result')` 成功处）：
   ```js
   document.getElementById('downloadV2Btn').style.display =
     resp.headers.get('X-V2-Available') === '1' ? '' : 'none';
   ```
2. 新增下载函数（v2 不进 sessionStorage，浏览器原生下载）：
   ```js
   function downloadV2Pdf() { window.location.href = '/api/generate/result?v=2'; }
   ```
3. `restoreFromSession()` 恢复上次报告的分支里探测：
   ```js
   fetch('/api/generate/result?v=2', { method: 'HEAD' })
     .then(r => { document.getElementById('downloadV2Btn').style.display = r.ok ? '' : 'none'; })
     .catch(() => {});
   ```

行为约定：v2 按钮**只在**「本次生成了 v2」或「上次任务有 v2 且文件还在」时出现；平时页面与现状完全一致。

## 5. 档案页「查看 PDF」→「生成 PDF」（同一批部署，本地已实现并验证）

背景：「查看 PDF」链接指向 `/output/<文件>`，但每次新生成都会清空 `output/` 下历史报告 PDF → 旧记录全 404。改成**从 DB 数据快照重生成**（不调 OCR，零 API 成本，~10-30s 同步请求，低于 Cloudflare 100s 限制）。

本地工作树已实现：

- `app.py` 新增 `POST /api/reports/<id>/regenerate`（admin）：`_job_running()` → 409；`_db.get_report_raw(id)` 取快照（缺 schema_124 → 400）；快照写入 `data/report_data.json` → `apply_report_data()` → `generate.main()`（v2 由 [4/4] 步骤顺带产出）→ 返回 v1 附件 + `X-V2-Filename` 头
- `templates/students.html`：「查看 PDF」换成「生成 PDF」按钮（生成中禁用 → blob 自动下载），响应有 v2 时同行出现「新版 Beta」链接（指 `/output/<v2文件名>`）

注意：该接口会覆盖 `data/report_data.json`（全局当前数据），下一次真实生成的 extract 会重写——已知且可接受。

## 6. 部署清单

```bash
# 本地/服务器均按你现有惯例；参考步骤：
scp new_iteration 整个目录 + generate.py + app.py + templates/index.html 到服务器 /opt/y4_report/
# 服务器上：
cp /opt/y4_report/generate.py /opt/y4_report/generate.py.bak_<timestamp>     # 备份（generate.py 上次没动过，没有旧备份）
cp /opt/y4_report/app.py /opt/y4_report/app.py.bak_<timestamp>
cp /opt/y4_report/templates/index.html /opt/y4_report/templates/index.html.bak_<timestamp>
# 部署新文件后：
chown -R y4report:y4report /opt/y4_report
find /opt/y4_report -name __pycache__ -type d -prune -exec rm -rf {} +
# 字体确认（v2 用 Noto Sans CJK SC 兜底）：
fc-list | grep -i "noto sans cjk" || apt install -y fonts-noto-cjk
systemctl restart y4_report && systemctl is-active y4_report
curl -s http://127.0.0.1:8000/login -o /dev/null -w '%{http_code}\n'
```

## 7. 上线后验证 checklist

1. 隧道（report.p4learning-ark.app）跑一次真实生成（4 份 PDF）：
   - 分片上传 / start / 进度 / result 全链路正常（与上一版一致，无 524）
   - v1 下载内容与接入前一致
   - 生成完成后出现「下载新版报告 Beta」按钮，点击下到 `凭远Y4评测报告_v2_<姓名>.pdf`，20 页
2. 直连 IP 同样跑一遍。
3. 故障抽查（可选但推荐）：临时把 `new_iteration/report_v2.html` 改名 → 跑一次生成 → v1 正常产出、任务状态 done、界面无 v2 按钮、`_job.log` 里只有一行警告 → 改回。
4. `systemctl status y4_report` 无异常；`_job.log` 无新增报错。

## 8. 回滚

```bash
cp /opt/y4_report/app.py.bak_<timestamp> /opt/y4_report/app.py
cp /opt/y4_report/generate.py.bak_<timestamp> /opt/y4_report/generate.py
cp /opt/y4_report/templates/index.html.bak_<timestamp> /opt/y4_report/templates/index.html
chown y4report:y4report /opt/y4_report/app.py /opt/y4_report/generate.py /opt/y4_report/templates/index.html
find /opt/y4_report -name __pycache__ -type d -prune -exec rm -rf {} +
systemctl restart y4_report
```
（`new_iteration/` 目录留在服务器上无害——generate.py 回滚后没有任何东西引用它。）

## 9. 附：QC 建议项（可选，本次不实施）

来自对异步化重构（分片上传+子进程作业）的评审，**仅记录，不做**：

1. `_job_running()` 存活判断可补看 `data/_progress.json` 的 mtime（extract 运行时会写它），避免 OCR 极端慢（>20min 无 `_job.json` 写入）时误判卡死放行第二个任务。两行代码，暂不急。
2. `data/_uploads/` 孤儿分片目录无清理：可在 `api_generate_start` 开头删 mtime>1h 的目录，或部署层 cron。
3. 分片完整性：manifest 可带 filesize，start 时校验合并后字节数。当前丢片会在 extract 显性失败，可接受。
4. `_job.log` 无轮转：部署层加 logrotate 即可。
5. 旧入口 `POST /api/generate` 与新异步路径是两段相似编排：暂缓统一，下次大改（如多人并发）时一起做。

---

## 10. 参考实现已通过的验证（本地，2026-10-09）

- `python3 generate.py`：output/ 同时产出 v1（旧设计）+ v2（新设计 20 页）
- v2 的 Chrome 打印真实失败过一次（本地旧旗标超时），主流程仅打印警告照常完成——故障隔离实证
- `_find_generated_pdf()` 在 v1/v2 同存时返回 v1
- Flask test_client：v1 200 且文件名无 `_v2_`、`?v=2` 200 且文件名为 v2、无 v2 时 `?v=2` 404、`X-V2-Available` 头正确
- 真实 HTTP：起服 → 登录 → `/generate` 200 含按钮 → 两个接口各下到正确 PDF
- 注意：本机 Chrome 对旧 `--headless` 旗标会"写完文件但不退出"，每次打印吃满 180s 超时（文件完整）——**本地现象，服务器无此问题**，不要为此改旗标（用户已决定不动）。
