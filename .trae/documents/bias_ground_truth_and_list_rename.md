# Plan: Bias 语义修正 + 逐问题名单改语 + AI 判断加深

## Context

用户反馈两个问题：
1. **AI 判断太短、不够 nuanced**；且 bias 语义当前是反的——用户要求：偏高(bias=高估) → 真实更好 → 后端自动上移一档（PND→不低），AI 以修正后档位为准绳。
2. **名单用语问题**：四象限是 弱干扰/强干扰/弱潜能/强潜能，不是"干预"；不说学生"有问题"。

当前 bias 定义（app.py L2827）写的是"低估→真实值更高"——这与用户意图相反。需翻转为 severity-based 语义。

## Change 1: Bias 语义翻转 + 档位修正 + 判断加深

### 1a. evaluation_rules.py — `normalize_bias` 映射修正 (L1667-1668)

旧偏高/偏低是 score-based（偏高=分数高估=真实更差）。新高估/低估是 severity-based（高估=严重度高估=真实更好）。两者方向相反：

```python
_BIAS_CANONICAL = {"正常": "正常",
                   "偏高": "低估",   # 旧：分数高估→真实更差 = 新：严重度低估→真实更差
                   "低估": "低估",
                   "偏低": "高估",   # 旧：分数低估→真实更好 = 新：严重度高估→真实更好
                   "高估": "高估"}
```

### 1b. evaluation_rules.py — 新增 `adjust_eval_for_bias()` (L1665 附近)

```python
_BIAS_SLOT_ORDER = ["严重偏低", "明显偏低", "偏低", "不低", "较好", "高"]

def adjust_eval_for_bias(eval_value, bias):
    """高估→上移一档（真实更好）；低估→下移一档（真实更差）。
    档位不在 _BIAS_SLOT_ORDER 中（需关注/需特殊关注/相对健康/正常）→ 不修正。
    边界 clamp。"""
    ev = (eval_value or "").strip()
    b = (bias or "正常").strip()
    if b == "正常" or ev not in _BIAS_SLOT_ORDER:
        return ev
    idx = _BIAS_SLOT_ORDER.index(ev)
    if b == "高估":
        return _BIAS_SLOT_ORDER[min(idx + 1, len(_BIAS_SLOT_ORDER) - 1)]
    if b == "低估":
        return _BIAS_SLOT_ORDER[max(idx - 1, 0)]
    return ev
```

### 1c. evaluation_rules.py — 新增 `verdict_label_cn()` (L789 附近)

PROBLEM 态动态标签：severe items → "需介入"；非 severe → "需支持"。其他态走静态 `VERDICT_LABELS_CN`。

```python
def verdict_label_cn(state, items=None):
    if state == VERDICT_PROBLEM:
        if items and any((r.get("eval") or "") in _QUESTION_SEVERE_EVALS for r in items):
            return "需介入"
        return "需支持"
    return VERDICT_LABELS_CN.get(state, state)
```

`VERDICT_LABELS_CN[VERDICT_PROBLEM]` 改为 `"需支持"`（兜底默认值）。

### 1d. app.py — 三个格式化函数应用 bias 修正

**`_format_e4_line` (L2670-2671)**：
- 调 `adjust_eval_for_bias(eval_v, bias)` 得 adjusted_eval
- 替换 parts 中的 eval_v 为 adjusted_eval
- 追加 `bias修正:{eval_v}→{adjusted_eval}`
- 若档位不在槽位（无法修正）：仍显示 `bias:{bias}`

**`_build_y4_interpret_context` (L2453-2455)**：
- 同上逻辑：替换 `（{eval_v}）` 为 `（{adjusted_eval}）`，追加 `〔bias修正：{eval_v}→{adjusted_eval}〕`
- 若无法修正：保留 `〔专家确认：{bias}〕`

**`_y4_report_line` (L2494-2495)**：同上逻辑。

**不动的**：`_base_point`（Y4 JSON，L3315-3329）保留原始 eval + confirmed_direction，不修正。verdict 计算（`evaluate_question_verdicts`）用原始 eval，不修正。

### 1e. app.py — 翻转 bias 语义 + 加深判断

**L2827 硬规则 #3** 改为：
```
3. bias 修正档位：数据行中已根据 bias 自动修正档位（标注〔bias修正：原→新〕），
修正后的档位即真实水平，直接据此展开判断。高估=严重度高估（真实更好、档位上移）；
低估=严重度低估（真实更差、档位下移）。不再单独标注 bias 字段。
```

**L2843 跟进线索**：删除 bias 特例句（"但若已标 bias:低估则视为确认低估…"），统一由规则 3 处理。

**L2866 可能失真段**：删除"bias 标注的高估/低估不属于此列"句（bias 已体现在档位中）。

**判断深度（L2804-2810）**：
- 健康/中性：2-4 句（原 1-3）
- 关注：4-6 句（原 3-5）
- 需支持/需介入：5-8 句（原 4-6）

**L2794 状态列举**：`（需介入/需支持/关注/观察/健康/中性）`

**L2863 核心问题段**：`（需介入/需支持/关注级）`

### 1f. app.py — VERDICT 标签调用改用 `verdict_label_cn`

三处调用点（L1629、L3180、L3574）：
```python
cn = _eval_rules.verdict_label_cn(v.get("state"), v.get("items") or [])
```

## Change 2: 名单标签 干预→干扰 + 去"问题"语

### 2a. evaluation_rules.py — 逐问题名单常量 (L798-801)

```python
LIST_STRONG_INTERVENTION = "强干扰"   # was 强干预
LIST_WEAK_INTERVENTION = "弱干扰"      # was 弱干预
LIST_STRONG_POTENTIAL = "强潜能"       # unchanged
LIST_WEAK_POTENTIAL = "弱潜能"         # unchanged
```

更新 L795 注释、L807 docstring 中的措辞。

### 2b. app.py — 结论级名单格式 (L3443, L3509)

```python
placement = "干扰" if is_interference else "潜能"          # was 干预名单/潜能名单
result["category"] = f"{'强' if result['strength'] == '强' else '弱'}{placement}"  # was 干预名单·强特质
```

输出：强干扰 / 弱干扰 / 强潜能 / 弱潜能。

### 2c. app.py — Step3 prompt (L3058-3062)

```
- 强干扰：E1/E2 存在严重判定（重度档位或多个问题同时成立）
- 弱干扰：E1/E2 有需介入/需支持判定但程度较轻（单一问题、程度有限）
- 强潜能：E1/E2 均无问题，且认知能力百分位总≥95、执行功能平均≥90
- 弱潜能：E1/E2 均无问题，但学习力潜力或动力不充分
```

### 2d. app.py — E4 协议 META 段 (L3686-3705)

- L3686: `if placement.startswith("干扰")`
- L3687: `归入干扰：E1 情绪或 E2 精力存在需介入/需支持级判定。`
- L3690: `强度判定：强（多个问题或严重偏低）`
- L3692: `强度判定：弱（单一问题、程度有限）`
- L3695: `需关注指标：`（was 问题指标）
- L3700: `归入潜能：E1 情绪和 E2 精力均无问题级判定。`
- L3705: `{'强' if strength == '强' else '弱'}依据：`（was 强特质/弱特质）

### 2e. evaluation_rules.py — E4_JUDGMENT_GUIDES 文本 (L1531, L1560, L1593)

- L1531: `本题不写「需介入/需支持」`（was 有问题）
- L1560: `这是「需支持但需确认」的判断姿态`（was 有问题但需确认）
- L1593: `才写整体方法系统薄弱（需支持）`（was 有问题）

### 2f. 模板 tooltip 更新

**internal.html L1036-1037 + prompt_lab.html L989-990**：
```javascript
data-tip="严重度高估：真实水平更好（档位上移）"  // 高估
data-tip="严重度低估：真实水平更差（档位下移）"  // 低估
```

CSS 类名 `bias-high`/`bias-low` 不改。

## 修改文件清单

1. `evaluation_rules.py` — normalize_bias 修正、adjust_eval_for_bias、verdict_label_cn、LIST 常量、E4_JUDGMENT_GUIDES 文本
2. `app.py` — _format_e4_line、_build_y4_interpret_context、_y4_report_line、_e4_step2_system、_e4_step3_system、_determine_list_placement、E4 META 段、3 处 VERDICT_LABELS_CN 调用
3. `templates/internal.html` — tooltip
4. `templates/prompt_lab.html` — tooltip

## 验证

1. `python3 -m py_compile app.py evaluation_rules.py`
2. 单元测试：`adjust_eval_for_bias`（6 档位 × 3 bias + 边界 clamp + 非槽位档位）
3. 单元测试：`verdict_label_cn`（PROBLEM+severe→需介入、PROBLEM→需支持、其他态→静态标签）
4. 单元测试：`normalize_bias`（偏高→低估、偏低→高估、高估→高估、低估→低估）
5. grep `有问题` app.py evaluation_rules.py — 仅剩 eval 档位/注释语境，verdict 语境清零
6. grep `干预名单|强特质|弱特质` — 清零
7. IrisLu 数据跑 E4：数据行出现 `bias修正:偏低→不低`、VERDICT 行出现 `需介入/需支持`、名单归属出现 `强干扰/弱干扰`
