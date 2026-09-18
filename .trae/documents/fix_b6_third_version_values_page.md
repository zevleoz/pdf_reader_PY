# 修复 B6 第三版本（非初中/非高中）职业价值观页码读取

## Summary

B6 职业价值观页面在不同版本出现在不同页码：初中版第 12 页、高中版第 15 页、第三版本（既不是初中也不是高中、文件名无版本关键词）第 13 页。当前代码对"文件名不含 高中/初中 关键词"的 B6 默认当初中版处理（读第 12 页），导致第三版本读错页、视觉 API 取不到 15 个价值观卡片。

本方案做**最小增量改动**：仅改 `_vision_values_bar.py` 一个文件、两处函数，把"既不是初中也不是高中"的默认分支从「初中版→页12」翻成「通用版→页13」。初中版与高中版分支一行不动，现有 process 不受影响。

## Current State Analysis（基于实际代码）

### 版本检测 — `detect_b6_version()`
[_vision_values_bar.py:262-277](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/_vision_values_bar.py#L262-L277)

```python
def detect_b6_version(pdf_path: Path) -> str:
    name = pdf_path.name
    if "高中" in name: return "高中版"
    if "初中" in name: return "初中版"
    return "初中版"   # ← BUG：第三版本（无关键词）被误判为初中版
```

文件名判断方式由 [app.py:184-194](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/app.py#L184-L194) 上传保存逻辑决定：
- 文件名含"高中"/"初中" → 存为 `report_B6_高中.pdf` / `report_B6_初中.pdf`
- 否则 → 存为 `report_B6.pdf`（无版本后缀）→ 命中默认分支

### 页码定位 — `find_values_page()`
[_vision_values_bar.py:280-287](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/_vision_values_bar.py#L280-L287)

```python
def find_values_page(pdf_path: Path) -> int:
    version = detect_b6_version(pdf_path)
    return 11 if version == "初中版" else 14   # 初中→index11(页12), 其余→index14(页15)
```

### 调用方（全部路由到 `find_values_page`，无独立硬编码）
- [_vision_values_bar.py:378](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/_vision_values_bar.py#L378) — 视觉 API 主路径
- [extract.py:1648](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/extract.py#L1648) — must_pages 拼装价值观页+排名页
- [extract.py:2514](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/extract.py#L2514) — OCR 兜底路径
- [extract.py:2576](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/extract.py#L2576) — 图像处理兜底路径

> 结论：`find_values_page()` 是唯一真相源。改它一处，四条路径全部自动修正。`extract.py` 无需改动。

### Prompt 选择 — 复用现有，无需新增
[_vision_values_bar.py:397](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/_vision_values_bar.py#L397)
```python
prompt = PROMPT_GAOZHONG if version == "高中版" else PROMPT_CHUZHONG
```
用户确认第三版本卡片布局与初中/高中版完全一致（15 卡片，3×5，编号 1-15）。第三版本命中 `else` 分支用 `PROMPT_CHUZHONG`，布局一致可正常工作。**不改。**

## Proposed Changes

### 改动 1：`detect_b6_version()` — 默认分支翻成"通用版"
**文件**：[_vision_values_bar.py:262-277](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/_vision_values_bar.py#L262-L277)
**为什么**：第三版本文件名无 高中/初中 关键词，当前落默认分支被误判为初中版。
**怎么改**：仅改默认分支返回值与打印，高中/初中两个 `if` 分支保持原样。

```python
def detect_b6_version(pdf_path: Path) -> str:
    """检测 B6 版本。直接从文件名判断。

    文件名包含 "高中" → 高中版（价值观在第15页）
    文件名包含 "初中" → 初中版（价值观在第12页）
    都不包含       → 通用版（价值观在第13页，即既不是初中也不是高中的 B6）
    """
    name = pdf_path.name
    if "高中" in name:
        print(f"[视觉] B6 版本检测: 高中版 (文件名: {name})")
        return "高中版"
    if "初中" in name:
        print(f"[视觉] B6 版本检测: 初中版 (文件名: {name})")
        return "初中版"
    print(f"[视觉] B6 版本检测: 通用版 (非初中/非高中, 文件名: {name})")
    return "通用版"
```

### 改动 2：`find_values_page()` — 通用版映射到 index 12（第13页）
**文件**：[_vision_values_bar.py:280-287](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/_vision_values_bar.py#L280-L287)
**为什么**：当前 `return 11 if version == "初中版" else 14` 把通用版错配到页15；需显式三分支。
**怎么改**：改成显式 if/elif/else，初中/高中映射不变，新增通用版→12。

```python
def find_values_page(pdf_path: Path) -> int:
    """返回职业价值观页面的 0-based 索引。

    初中版 → page 12 (index 11)
    高中版 → page 15 (index 14)
    通用版 → page 13 (index 12)   # 既不是初中也不是高中
    """
    version = detect_b6_version(pdf_path)
    if version == "初中版":
        return 11
    if version == "高中版":
        return 14
    return 12  # 通用版
```

## Local Testing & Production Safety（先本地测，不影响线上）

### 环境隔离（本地 ≠ 生产）
- **本地**：`/Users/jefflau/projects/pdf_report_converter/PDF_converter`，跑 Flask dev server（`python app.py`，[app.py:3799](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/app.py#L3799) `app.run(host="0.0.0.0", port=8000, debug=False, threaded=True)`），访问 http://localhost:8000
- **生产**：远程阿里云 ECS `/opt/y4_report`，Gunicorn + systemd（`y4_report.service`），靠服务器端 `git pull` 部署（见 [deploy.sh](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/deploy.sh)）
- **隔离结论**：我仅在本地工作目录改 `_vision_values_bar.py`，**不跑任何 deploy 脚本（deploy.sh / deploy_server.sh）、不 git push、不 git commit、不碰 /opt/y4_report**。本地改动物理上碰不到生产；生产只有在你在服务器上手动 `git pull` 后才会更新。

### 本地测试流程
1. 改完 `_vision_values_bar.py` 后，**重启本地服务**（`debug=False` 无自动重载，.py 改动需重启）：
   - 在跑 `./start_server.sh` / `python app.py` 的终端按 `Ctrl+C` 停止
   - 重新执行 `./start_server.sh`（会自动清理 8000 端口旧进程再启 Flask）
2. 浏览器访问 http://localhost:8000，按下方 Verification 三种场景上传 B6 测试
3. 观察终端日志里的 `[视觉] B6 版本检测:` 和 `职业价值观页面在第 N 页` 输出
4. **全部本地验证通过后，再由你决定何时部署到生产**（你的常规 git 工作流，不在我本次任务范围）

## Assumptions & Decisions

1. **检测策略 = 文件名关键词**：沿用现有方式，不引入 PDF 内容扫描/页数统计（用户明确要求不改 process；现有方式对初中/高中已稳定）。第三版本"无关键词"天然落入默认分支。
2. **内部标签"通用版"**：纯内部路由用，不出现在 UI/报告里。代表"既不是初中也不是高中的 B6"。用户无命名偏好，可后续按需重命名（只影响日志打印）。
3. **Prompt 复用 `PROMPT_CHUZHONG`**：用户确认布局完全一致，无需新增 prompt。命中 `else` 分支即可。
4. **不改 `app.py` 上传逻辑**：第三版本已存为 `report_B6.pdf`（无后缀），正好被新默认分支识别为通用版。
5. **不改 `extract.py`**：三处调用已全部路由到 `find_values_page()`，自动获益。
6. **行为变化范围**：唯一变化是"文件名不含 高中/初中 关键词"的 B6 从读第12页变为读第13页。初中版（含"初中"关键词）和高中版（含"高中"关键词）行为完全不变。
7. **风险点**：若有人上传初中版 B6 但文件名漏写"初中"关键词，会被当通用版读第13页（而非第12页）。但这是用户工作流的既定约定（第三版本就是靠"无关键词"区分），与当前默认读第12页同属猜测，无新增风险。

## Files to Modify

仅 1 个文件、2 处函数，均位于 [_vision_values_bar.py](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/_vision_values_bar.py)：
- `detect_b6_version()` (L262-277)
- `find_values_page()` (L280-287)

**不改动**：app.py、extract.py、generate.py、data_points.py、任何 prompt 模板、任何 UI/模板文件。

## Verification

1. **初中版回归**：上传文件名含"初中"的 B6 → 服务日志显示 `B6 版本检测: 初中版`、`职业价值观页面在第 12 页`；生成的 Y4 PDF 第18页 15 个价值观正常。行为应与改前完全一致。
2. **高中版回归**：上传文件名含"高中"的 B6 → 日志显示 `高中版`、`第 15 页`；价值观正常。
3. **第三版本修复**：上传文件名不含 高中/初中 的 B6 → 日志显示 `通用版 (非初中/非高中)`、`第 13 页`；视觉 API 应返回 15 个价值观卡片，Y4 PDF 第18页正常填充。
4. **兜底路径**：第三版本下 OCR 兜底（extract.py L2514）与图像处理兜底（L2576）也应读取第13页（因均路由到 `find_values_page`）。
5. **mapping 文件**：检查 `data/_vision_b6_values_mapping.json` 对第三版本写入 15 个编号→名称映射。
