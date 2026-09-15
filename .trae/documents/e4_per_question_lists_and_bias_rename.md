# Plan: E4 逐问题名单 + Bias 术语重命名

## Context

两个问题驱动此改动：

1. **E4 的干预/潜能名单只在结论级生成**（`_determine_list_placement` 只看 E1/E2 是否有 PROBLEM），缺少逐问题粒度。用户要求每个 E4 问题都出一份名单归属（强干预/弱干预/强潜能/弱潜能），与结论级名单并存。

2. **data_bias 的偏高/偏低与 eval_value 的偏低混淆**：依恋亲近的 eval 可以是"偏低"，bias 也可以是"偏低"，无法区分"实测值低于真实水平"还是"评价确实低"。用户要求改为高估/低估（overestimate/underestimate 的直译）。

## Change 1: 逐问题名单归属

### 规则引擎 — evaluation_rules.py

在 `evaluate_question_verdicts()` 的 verdict 循环末尾（L1624 之前），为每个 group 的 verdict 添加 `list_assignment` 字段。

**新增常量与函数**（放在 L793 `_VERDICT_RANK` 之后）：

```python
_QUESTION_SEVERE_EVALS = {"需特殊关注", "明显偏低", "严重偏低"}
_STRONG_POTENTIAL_EVALS = {"高", "较好"}
LIST_STRONG_INTERVENTION = "强干预"
LIST_WEAK_INTERVENTION = "弱干预"
LIST_STRONG_POTENTIAL = "强潜能"
LIST_WEAK_POTENTIAL = "弱潜能"

def _question_list_assignment(verdict):
    state = verdict.get("state")
    items = verdict.get("items") or []
    severe = any((r.get("eval") or "") in _QUESTION_SEVERE_EVALS for r in items)
    if state == VERDICT_PROBLEM:
        return LIST_STRONG_INTERVENTION if severe else LIST_WEAK_INTERVENTION
    if state == VERDICT_WATCH:
        return LIST_WEAK_INTERVENTION
    if state == VERDICT_OBSERVED:
        return LIST_WEAK_POTENTIAL
    if state == VERDICT_HEALTHY:
        strong = [r for r in items
                  if r.get("state") == VERDICT_HEALTHY
                  and (r.get("eval") or "") in _STRONG_POTENTIAL_EVALS]
        if len(strong) >= 2 or (len(items) == 1 and items[0].get("eval") == "高"):
            return LIST_STRONG_POTENTIAL
        return LIST_WEAK_POTENTIAL
    return LIST_WEAK_POTENTIAL  # NEUTRAL
```

**在 verdict 循末追加**（L1617-1624 for 循环体内，return 之前）：
```python
if g.get("verdict"):
    g["verdict"]["list_assignment"] = _question_list_assignment(g["verdict"])
```

非破坏性：现有代码只读 `state`/`summary`/`items`，新增 key 透明。

### E4 协议 MD — app.py `_assemble_e4_protocol` L3570

VERDICT 行改为：
```python
parts = [f"[VERDICT] {state_cn}"]
la = v.get("list_assignment")
if la:
    parts.append(f"[LIST] {la}")
parts.append(v['summary'])
md.append(" | ".join(parts))
```

输出样例：`[VERDICT] 有问题 | [LIST] 强干预 | 学习自信不足`

### Step2 用户 prompt — app.py L1627/L3176

问题判定行追加名单：
```python
la = v.get("list_assignment") or ""
la_seg = f" | 名单: {la}" if la else ""
all_lines.append(f"问题判定（Python 规则）：{cn}{la_seg} | {v.get('summary', '')}")
```

### 结论级名单不变

`_determine_list_placement` 不改动。逐问题名单与结论级名单可以不一致（逐问题更细），结论级仍是 META 中的权威归属。

## Change 2: Bias 术语 偏高/偏低 → 高估/低估

### evaluation_rules.py

**L1628** — 改选项：
```python
DATA_BIAS_OPTIONS = ["正常", "高估", "低估"]
```

**L1628 之后** — 加向后兼容归一化器：
```python
_BIAS_CANONICAL = {"正常": "正常", "偏高": "高估", "高估": "高估",
                    "偏低": "低估", "低估": "低估"}

def normalize_bias(bias):
    return _BIAS_CANONICAL.get((bias or "").strip(), "正常")
```

**L755** — order-pos 合成处加归一化：
```python
"data_bias": normalize_bias(src.get("data_bias", "正常")),
```

### app.py — 系统提示词中的 bias 引用

以下行将 `偏高`→`高估`、`偏低`→`低估`（仅 bias 语境，eval 档位词汇不动）：

| 行号 | 当前 | 改为 |
|------|------|------|
| L2825 | `bias=偏高/偏低：用户在 UI 中标注的偏高/偏低是专家判定...例如标注偏低意味着该值确实偏低` | `bias=高估/低估：用户在 UI 中标注的高估/低估是专家判定...例如标注低估意味着该实测值低估了真实水平（真实值更高）` |
| L2841 | `若已标 bias:偏低则视为确认偏低` | `若已标 bias:低估则视为确认低估（实测值低于真实水平）` |
| L2864 | `bias 标注的偏高/偏低不属于此列` | `bias 标注的高估/低估不属于此列` |
| L1436 (注释) | `偏高偏低确认` | `高估低估确认` |
| L2451 (注释) | `专家确认的偏高/偏低` | `专家确认的高估/低估` |

**不动的行**（L2835-2836 学习自我调节偏低/依恋亲近偏低 = eval 档位；L1156-1157 精力偏低 = eval 档位；L3404 _SEVERE_EVALS；L3412/L3681 注释中的 eval 档位）。

### prompts/ai_interpreter.md — bias 引用

| 行号 | 改动 |
|------|------|
| L44 | `〔专家确认：偏高〕`→`〔专家确认：高估〕`、`〔专家确认：偏低〕`→`〔专家确认：低估〕` |
| L80 | `〔专家确认：偏低〕`→`〔专家确认：低估〕`（首个"偏低可能受疲劳影响"是 eval 档位，不动） |
| L190 | `专家已确认偏低的按事实写`→`专家已确认低估的按事实写` |

### 模板 — internal.html & prompt_lab.html（两文件平行改动）

**按钮**（internal L1035-1037; prompt_lab L988-990）：
```javascript
// 偏高→高估，偏低→低估，tooltip 更新
html += `... onclick="setBias('${it.code}','高估',this)">高估</button>`;
html += `... onclick="setBias('${it.code}','低估',this)">低估</button>`;
```

**renderEvalCard 卡片类**（internal L1012; prompt_lab L965）：
```javascript
it.data_bias === '高估' ? 'bias-high' : (it.data_bias === '低估' ? 'bias-low' : ''),
```

**setBias**（internal L1077-1088; prompt_lab L1030-1041）：
```javascript
if (bias === '高估') card.classList.add('bias-high');
if (bias === '低估') card.classList.add('bias-low');
```

**CSS 类名保持 `bias-high`/`bias-low` 不改**——是内部标识符，颜色语义仍对（amber=高估/overestimate, indigo=低估/underestimate）。

### 数据流自动传播

以下读取 `data_bias` 的代码只比较 `!= "正常"`，不需改逻辑，新值自动透传：
- `_format_e4_line` L2647 → 输出 `bias:高估`/`bias:低估`
- `_build_y4_payload` L3317 → `confirmed_direction: "高估"`/`"低估"`
- `_build_y4_interpret_context` L2451 → `〔专家确认：高估〕`/`〔专家确认：低估〕`
- `_y4_report_line` L2372 → 同上

## 修改文件清单

1. `evaluation_rules.py` — DATA_BIAS_OPTIONS、normalize_bias、_question_list_assignment、evaluate_question_verdicts 钩子
2. `app.py` — _assemble_e4_protocol VERDICT 行、Step2 prompt bias 字符串、注释
3. `prompts/ai_interpreter.md` — L44/L80/L190 bias 引用
4. `templates/internal.html` — 按钮文案/tooltip、renderEvalCard、setBias
5. `templates/prompt_lab.html` — 同上

## 验证

1. `python3 -m py_compile app.py evaluation_rules.py`
2. 用 IrisLu 数据调 `evaluate_question_verdicts`，检查每个 group 的 `verdict["list_assignment"]`：E1 PROBLEM+severe → "强干预"；E3 HEALTHY+多高 → "强潜能"
3. E4 协议 MD 检查 `[LIST]` 标注出现
4. UI 打开 prompt-lab，点"高估"/"低估"按钮，检查卡片颜色和 active 状态
5. grep `偏高` app.py evaluation_rules.py prompts/ai_interpreter.md — 仅剩 eval 档位语境的命中，bias 语境清零
6. 生成 E4 协议下载，确认 `bias:高估`/`bias:低估` 出现在数据行
