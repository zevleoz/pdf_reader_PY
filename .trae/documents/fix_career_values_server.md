# 修复：服务器端职业价值观识别失败

## 问题根因

[\_ision\_values\_bar.py#L326](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/_vision_values_bar.py#L326) 有一个**硬编码的本地 Mac 路径**：

```python
cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_full_page_for_api.png', ...)
```

* **本地（Mac）**：路径存在，写入成功，职业价值观条形图解析正常

* **服务器（Linux）**：`/Users/jefflau/` 不存在，`cv2.imwrite()` 抛异常 → 异常传播到 [extract.py#L1784-L1822](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/extract.py#L1784-L1822) 的 try/except → 打印"模块加载失败" → 职业价值观 095-124 回退到视觉 API 通用提取（可能拿不到准确值）→ 最终只填默认值

## 本地版本不受影响的安全保证

改动在数学上等价于原代码，原因如下：

1. `base_dir` 已在 [第 309 行](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/_vision_values_bar.py#L309) 定义为 `Path(__file__).resolve().parent`
2. 在本地 Mac 上，`__file__` = `/Users/jefflau/projects/pdf_report_converter/PDF_converter/_vision_values_bar.py`
3. 因此 `base_dir` = `/Users/jefflau/projects/pdf_report_converter/PDF_converter`
4. `str(base_dir / "_full_page_for_api.png")` = `/Users/jefflau/projects/pdf_report_converter/PDF_converter/_full_page_for_api.png`
5. **这与原硬编码路径完全相同** → 本地写入行为 100% 不变
6. `try/except` 只在写入失败时触发；本地写入成功时，except 块不会执行 → 本地后续逻辑 100% 不变
7. 函数其余部分（视觉 API 调用、JSON 解析、结果返回）**完全不改动**

## 修改方案

### 改动 1（唯一改动）：[\_vision\_values\_bar.py#L326](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/_vision_values_bar.py#L326)

把硬编码路径改为动态路径，并包裹 try/except 使其变为可选的调试输出（即使写入失败也不影响提取流程）：

```python
# 旧代码（第 326 行）
cv2.imwrite('/Users/jefflau/projects/pdf_report_converter/PDF_converter/_full_page_for_api.png', cv2.cvtColor(full_page, cv2.COLOR_RGB2BGR))

# 新代码
try:
    cv2.imwrite(str(base_dir / "_full_page_for_api.png"), cv2.cvtColor(full_page, cv2.COLOR_RGB2BGR))
except Exception:
    pass
```

* 本地 Mac：`base_dir` 解析为原硬编码路径 → 行为完全相同

* 服务器 Linux：`base_dir` 解析为 `/opt/y4_report/_full_page_for_api.png` → 写入成功或静默跳过 → 不再崩溃

### 不需要改动的部分

* `data/_vision_b6_values_mapping.json`：此文件由 `_vision_values_bar.py` 运行时动态生成，首次运行时不存在 → [extract.py#L1801-L1818](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/extract.py#L1801-L1818) 已有 fallback 逻辑

* 其他 `_debug_*.py` / `start_server*.py` 中的硬编码路径：这些是本地调试脚本，不在主提取流程中，不影响服务器运行

* `_vision_values_bar.py.bak`：备份文件，不被 import

* `extract.py`、`generate.py`、`app.py`、`data_points.py`：核心管道文件均不改动

## 验证步骤

1. **本地回归验证**：修改后运行 `python app.py run`，确认职业价值观 095-124 仍能正确提取（与修改前结果一致）
2. **服务器验证**：推送到服务器，重新部署后上传 B6 PDF，检查 `data/report_data.json` 中 095-124 是否有实际数值（非默认值）
3. **日志验证**：检查服务器日志 `/var/log/y4_report/error.log`，确认不再出现"职业价值观条形图] 模块加载失败"

