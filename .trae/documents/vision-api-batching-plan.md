# 方案 C：124 视觉 API 拆批次调用

## Context

当前 `extract_124_points_with_vision()`（extract.py L1688-1764）将 4 份 PDF 的约 38 张高清 PNG 在一次 API 调用中发给 qwen3-vl-plus。API 间歇性返回空响应（0 字符 / ~32s），导致整个生成流程崩溃，`_vision_values_bar` 也没有机会运行。

**目标**：将单次 38 图调用拆为 4 次 slot 批次调用（A2/B3/B4/B6，每批 8-11 张图），加入重试+指数退避，批次失败时继续其他批次（部分降级），仅当全部 4 个批次失败时才 raise RuntimeError（保持现有错误契约不变）。

## 改动范围

**仅改 `extract.py` 一个文件**。`_vision_values_bar.py`、`app.py`、`generate.py` 一行不动。

## 实施步骤

### Step 1：新增 slot 拆分逻辑（extract.py L1467 之后插入）

用正则从 `_SCHEMA_PROMPT_USER_124` 中按 slot tag（`（A2）`/`（B3）`/`（B4）`/`（B6）`）程序化拆分 133 项。

```python
_SCHEMA_ITEM_LINE_RE = re.compile(
    r"^(\d{3})\s+(.+?)\s+(number|string)（([AB]\d)[^）]*）\s*$"
)

def _parse_slot_items() -> Dict[str, List[Tuple[str, str]]]:
    out: Dict[str, List[Tuple[str, str]]] = {"A2": [], "B3": [], "B4": [], "B6": []}
    for raw in _SCHEMA_PROMPT_USER_124.splitlines():
        line = raw.rstrip()
        m = _SCHEMA_ITEM_LINE_RE.match(line)
        if not m:
            continue
        code, _desc, _type, slot = m.groups()
        out.setdefault(slot, []).append((code, line))
    return out

_SLOT_ITEMS = _parse_slot_items()
assert sum(len(v) for v in _SLOT_ITEMS.values()) == 133
```

### Step 2：新增 per-slot prompt 构造器（紧接 Step 1）

```python
_PER_SLOT_HEADER = """你是一个严格按编号从 PDF 报告中抽取数据的助手。
以下是我需要你严格输出的 {n} 项数据点的编号和取值口径。
输出形式固定为一个 JSON：顶层只有一个 key "data"，对应一个长度 {n} 的数组。
数组里每一项为 {{"code": "NNN", "value": <你的结果>}}。
必须按下面定义的编号顺序输出，一个都不能少。编号不能跳。
每个 value 都必须按照我给的"类型约束"来输出：
  - number —— 纯数字。如果读不到写 ""。
  - string —— 文字值。
不要写其他文字解释。不要用 null。
数据点定义（按编号顺序）：
"""

def _build_slot_prompt(slot: str) -> str:
    items = _SLOT_ITEMS.get(slot, [])
    return _PER_SLOT_HEADER.format(n=len(items)) + "\n".join(l for _, l in items) + "\n"
```

### Step 3：修改 `_call_dashscope_native_multi`（L1489-1543）

- L1489 签名加 `prompt: str = _SCHEMA_PROMPT_USER_124` 参数
- L1506 `{"text": _SCHEMA_PROMPT_USER_124}` → `{"text": prompt}`

### Step 4：新增重试+指数退避包装函数（L1543 之后插入）

```python
_VISION_RETRY_DELAYS = (5, 10, 20)

def _call_vision_with_retry(slot, b64_images, prompt, max_retries=3, timeout=300):
    last_reason = "unknown"
    for attempt in range(max_retries + 1):
        if attempt > 0:
            time.sleep(_VISION_RETRY_DELAYS[attempt - 1])
            print(f"  [slot {slot}] 重试 {attempt}/{max_retries}")
        resp = _call_dashscope_native_multi(b64_images, timeout=timeout, prompt=prompt)
        if resp is None:
            last_reason = "API None"; continue
        content = (resp.get("content") or "").strip()
        if not content:
            last_reason = "空内容"; continue
        parsed = _extract_json_from_response(content)
        if parsed is None or "data" not in parsed:
            last_reason = "JSON 解析失败"
            (DATA_DIR / f"vision_raw_{slot}_a{attempt}.txt").write_text(content, encoding="utf-8")
            continue
        return parsed
    print(f"  [slot {slot}] {max_retries+1} 次全部失败 ({last_reason})")
    return None
```

### Step 5：修改 `_render_pages_for_vision`（L1597-1685）

返回类型从 `List[Path]` 改为 `Dict[str, List[Path]]`：
- L1598 签名改为 `-> Dict[str, List[Path]]`
- L1628 `paths: List[Path] = []` → `paths_by_slot: Dict[str, List[Path]] = {}`
- L1680 `paths.append(out)` → `paths_by_slot.setdefault(slot, []).append(out)`
- L1685 `return paths` → `return paths_by_slot`

其余逻辑（关键词定位、B6 `find_values_page`、B4 `max_per_pdf=11`）不变。

### Step 6：重写 `extract_124_points_with_vision`（L1707-1763）

替换从渲染到返回的核心逻辑：

```python
slot_paths = _render_pages_for_vision(max_per_pdf=8)

# API key 检查（保持原有 RuntimeError）
if not VISION_ACTIVE_KEY:
    raise RuntimeError("未设置视觉 API Key...")

# 按 slot 分批调用
all_results: Dict[str, Any] = {}
failed_slots: List[str] = []

for slot in ("A2", "B3", "B4", "B6"):
    paths = slot_paths.get(slot, [])
    if not paths:
        failed_slots.append(slot); continue
    b64_images = [base64.b64encode(open(p, "rb").read()).decode("utf-8") for p in paths]
    prompt = _build_slot_prompt(slot)
    parsed = _call_vision_with_retry(slot, b64_images, prompt)
    if parsed is None:
        failed_slots.append(slot); continue
    # 安全过滤：只接受属于该 slot 的 code
    expected_codes = {c for c, _ in _SLOT_ITEMS[slot]}
    for item in parsed.get("data", []):
        code = str(item.get("code", "")).strip()
        if code in expected_codes:
            all_results[code] = item.get("value") or ""

# 全部失败 → raise（保持现有错误契约）
if not all_results:
    raise RuntimeError("视觉 API 全部 4 个 slot 批次调用失败...")

print(f"  视觉 API: 成功 {len(all_results)}/133 项; 失败={failed_slots}")
return all_results
```

**关键设计决策**：
- B6 批次仍询问 095-124 项（_vision_values_bar 后续会覆盖，但作为 fallback）
- 每个 slot 只接受属于该 slot 的 code（防止幻觉污染）
- 部分 slot 失败 → 返回部分结果，让文本兜底和 _vision_values_bar 补充
- 全部失败 → raise RuntimeError（app.py Flask 错误处理不变）

## 不变的部分

- `_SCHEMA_PROMPT_USER_124` 常量（L1320-1467）— 仍是唯一 schema 源
- `_build_schema_payload`（L1470-1483）— 不在主路径，不受影响
- `_extract_json_from_response`（L1569）— 被 Step 4 复用
- `main()`（L1770+）— 签名和调用方式不变
- `_vision_values_bar.py` / `app.py` / `generate.py` — 一行不改

## 验证步骤

1. **正则验证**：`assert sum(len(v) for v in _SLOT_ITEMS.values()) == 133`
2. **Happy path**：本地跑一组已知 input，确认 `len(result) ≈ 133`，所有 code 001-133 都存在
3. **部分失败模拟**：monkey-patch `_call_dashscope_native_multi` 对 B6 返回 None，确认函数返回部分结果而非崩溃，`main()` 继续走文本兜底
4. **全失败**：确认全部 slot 失败时 raise RuntimeError，app.py 返回 500 错误
5. **生产验证**：push 到生产后用之前失败的那组 input 测试，看终端日志是否有 `[slot A2] OK` / `[slot B6] 重试` 等行
