# 档案页「查看 PDF」→「生成 PDF」实施说明书（给 Trae）

> 作者：Kimi Code Agent
> 日期：2026-10-13
> 范围：**只含档案页重生成下载功能**。v2 并行产出已上线，本文不涉及。
> 本地工作树已有完成并验证过的参考实现（`app.py`、`templates/students.html` 的当前版本），可直接审阅采用或按本文规格实施。

## 1. 背景与根因

档案页（/students）每条历史报告的「查看 PDF」链接指向 `/output/<文件名>`，但生成任务每次运行都会清空 `output/` 下所有 `凭远Y4评测报告_*.pdf`——所以**除最新一份外，历史报告的 PDF 文件全部不存在了**，点击全 404。

修复方式不是找回文件，而是把按钮改成「生成 PDF」：**从 DB 的 `reports.data_json` 完整数据快照重新渲染**。不调 extract、不调任何 OCR/外部 API，零成本，服务器上约 10–30 秒同步完成（远低于 Cloudflare 100s 限制）。

## 2. `app.py`：新增一个接口

放在 `api_student_reports` 附近（reports API 区）：

```python
@app.route("/api/reports/<int:report_id>/regenerate", methods=["POST"])
@admin_required
def api_report_regenerate(report_id):
    """从 DB 数据快照重生成报告 PDF（不调 extract/OCR，零 API 成本）。

    注意：会覆盖 data/report_data.json（全局"当前数据"）；下一次真实生成的
    extract 会重写它，不影响正确性。
    """
    if _job_running():
        return jsonify({"ok": False, "error": "已有生成任务正在运行，请稍候"}), 409

    info = _db.get_report_raw(report_id)
    if not info:
        return jsonify({"ok": False, "error": "报告记录不存在"}), 404
    raw = info.get("raw") or {}
    if not raw.get("schema_124"):
        return jsonify({"ok": False, "error": "该记录没有完整数据快照，无法重生成"}), 400

    try:
        (DATA_DIR / "report_data.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        apply_report_data()
        try:
            _generate_module.main()
        except SystemExit as exc:
            if exc.code not in (None, 0):
                raise RuntimeError(f"生成 PDF 失败: SystemExit({exc.code})")
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"重生成失败: {exc}"}), 500

    student_name = ((raw.get("student") or {}).get("name")
                    or info.get("student_name") or "").strip()
    safe_name = student_name.replace("/", "_").replace("\\", "_").replace(" ", "")
    pdf_path = OUTPUT_DIR / f"凭远Y4评测报告_{safe_name}.pdf"
    if not safe_name or not pdf_path.exists():
        return jsonify({"ok": False, "error": "生成流程完成，但未找到 PDF 文件"}), 500

    v2_path = OUTPUT_DIR / f"凭远Y4评测报告_v2_{safe_name}.pdf"
    resp = send_from_directory(
        str(OUTPUT_DIR), pdf_path.name,
        as_attachment=True, download_name=pdf_path.name,
        mimetype="application/pdf",
    )
    from urllib.parse import quote
    resp.headers["Content-Disposition"] = \
        f"attachment; filename*=UTF-8''{quote(pdf_path.name)}"
    if v2_path.exists():
        resp.headers["X-V2-Filename"] = v2_path.name
    return resp
```

要点：

- 所有依赖（`_job_running`、`_db.get_report_raw`、`apply_report_data`、`_generate_module`、`DATA_DIR`、`OUTPUT_DIR`、`send_from_directory`、`traceback`）在 app.py 里都已存在，无需新增 import
- v2 由 `generate.main()` 末尾的 [4/4] 步骤自动顺带产出（线上已部署）；`X-V2-Filename` 只在文件真的存在时带
- 不碰 `_job.json` 任务系统、不碰 output/ 清理 glob、不动 extract/validate

## 3. `templates/students.html`：按钮替换 + JS + 一个小样式

**(a) 报告行的「PDF 文件」列**，把：

```
<td><a href="/output/${r.pdf_path.split('/').pop()}" target="_blank">查看 PDF</a></td>
```

换成：

```
<td>
  <button class="btn btn-sm btn-primary" onclick="regeneratePdf(${r.id}, this)">生成 PDF</button>
  <a class="btn btn-sm btn-secondary" id="v2link-${r.id}" style="display:none" href="#" target="_blank">新版 <span class="beta-badge">Beta</span></a>
</td>
```

**(b) JS**（放在 `showRawData` 之前即可）：

```js
async function regeneratePdf(reportId, btn) {
  // 从 DB 数据快照重生成（不调 OCR），成功后自动下载；有 v2 时显示 Beta 链接
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = '生成中…';
  try {
    const resp = await fetch(`/api/reports/${reportId}/regenerate`, { method: 'POST' });
    if (!resp.ok) {
      let msg = '生成失败 (HTTP ' + resp.status + ')';
      try { const e = await resp.json(); if (e && e.error) msg = e.error; } catch (_) {}
      throw new Error(msg);
    }
    const blob = await resp.blob();
    let filename = '凭远Y4评测报告.pdf';
    const disposition = resp.headers.get('Content-Disposition') || '';
    const starMatch = disposition.match(/filename\*=UTF-8''([^;\n]+)/i);
    if (starMatch) filename = decodeURIComponent(starMatch[1]);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    const v2name = resp.headers.get('X-V2-Filename');
    const v2link = document.getElementById('v2link-' + reportId);
    if (v2name && v2link) {
      v2link.href = '/output/' + encodeURIComponent(v2name);
      v2link.style.display = '';
    }
  } catch (err) {
    alert(err.message || ('网络错误: ' + err));
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
}
```

**(c) CSS**（样式区任意位置，比如 `.btn-danger` 前）：

```css
.beta-badge {
  display: inline-block; margin-left: 4px; padding: 1px 6px;
  font-size: 10px; font-weight: 700; line-height: 1.4;
  color: #fff; background: #f59e0b; border-radius: 999px;
  vertical-align: 2px; letter-spacing: 0.5px;
}
```

「新版 Beta」链接指向 `/output/<v2文件名>`——v2 文件在重生成那一刻刚产出，直接读即可，不重复生成。

## 4. 部署

只动两个文件，按现有惯例：

```bash
cp /opt/y4_report/app.py /opt/y4_report/app.py.bak_<timestamp>
cp /opt/y4_report/templates/students.html /opt/y4_report/templates/students.html.bak_<timestamp>
# 上传新文件后：
chown y4report:y4report /opt/y4_report/app.py /opt/y4_report/templates/students.html
find /opt/y4_report -name __pycache__ -type d -prune -exec rm -rf {} +
systemctl restart y4_report && systemctl is-active y4_report
```

回滚就是把两个 .bak 拷回去重启。

## 5. 上线后验证

1. 隧道入口打开 /students → 任一学生 → 历史报告行点「生成 PDF」→ 按钮变「生成中…」→ 10–30 秒后自动下载 `凭远Y4评测报告_<姓名>.pdf`，内容与该报告一致
2. 同一行出现「新版 Beta」链接，点开是 v2 新版 PDF
3. 对最早的一条历史记录（文件早已被清掉的）操作——这正是本次修复的场景，必须成功
4. `_job.log` / journalctl 无新增报错

## 6. 参考实现已通过的验证（本地，2026-10-13）

- test_client：POST 本地现存报告（id=1）→ 200、2650KB PDF、文件名正确、`X-V2-Filename` 正确；不存在的 id → 404
- `/students` 页面渲染正常，按钮与 Beta 样式就位
- 实测两次 Chrome 打印共 ~25 秒完成
- 测试后 `data/report_data.json` 已还原
