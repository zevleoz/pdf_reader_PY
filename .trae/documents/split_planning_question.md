# 计划拆分「计划性」问题为「计划性」+「确定性需求」

## Context
当前 E4 框架中「计划性」一题（evaluation_rules.py L656-658）包含 4 个指标：人格-责任心、自驱力-自主性（判定项）、职业兴趣-常规型、ORDER:安全稳定（确定性需求上下文）。常规型和安全稳定当前只作上下文展示（VERDICT_NEUTRAL），不参与判定。

用户要求拆成两个独立问题：
- **计划性**：只保留 人格-责任心 + 自驱力-自主性
- **确定性需求**（新增）：职业兴趣-常规型 + ORDER:安全稳定

## 修改清单

### 1. E4_FRAMEWORK（evaluation_rules.py L656-658）
拆成两个 group：
```python
{"q": "计划性",
 "indicators": [{"label": "人格-责任心"}, {"label": "自驱力-自主性"}]},
{"q": "确定性需求",
 "indicators": [{"label": "职业兴趣-常规型"}, {"order_value": "安全稳定"}]},
```

### 2. `_v_e4_planning`（L1431-1463）— 简化
删除常规型/安全稳定上下文逻辑（demand 列表、VERDICT_NEUTRAL context rows、合并 summary）。只判 责任心+自主性，summary 只写计划性本身。

### 3. 新增 `_v_e4_certainty_demand` 函数
判定逻辑（二元判断：有/无确定性需求）：
- 常规型 高/不低 **或** 安全稳定排前五（至少一项命中）→ HEALTHY，summary "有确定性需求（{命中项}）"
- 两项都未命中 → NEUTRAL，summary "无明显确定性需求"
- 永远不会是 PROBLEM/WATCH（确定性需求是特质不是问题）

### 4. `_QUESTION_VERDICTS`（L1505）
- 保留 `"计划性": _v_e4_planning`
- 新增 `"确定性需求": _v_e4_certainty_demand`

### 5. `E4_JUDGMENT_GUIDES`（L1609-1614）
- **计划性**：删掉确定性需求上下文段落，只写责任心/自主性的判断指南
- **确定性需求**（新增）：写常规型+安全稳定如何判断高低，点明这是偏好不是问题，高确定性需求+计划性不足时结构化工具是对路切入点

### 6. app.py L2854 跟进线索
当前：`高确定性需求（...）+ 计划性不足 + 学习策略使用少 → 一表人才`
改为引用「确定性需求」问题结论 + 计划性不足的组合线索。

### 7. evaluation_rules.py L1128
docstring 更新：「已移至 E4 确定性需求」。

## 验证
- `python3 -m py_compile evaluation_rules.py app.py`
- 确认 E4_FRAMEWORK 输出含两个独立 group
- 确认 `_QUESTION_VERDICTS` 有 "确定性需求" key
- 确认 `E4_JUDGMENT_GUIDES` 有 "确定性需求" key
