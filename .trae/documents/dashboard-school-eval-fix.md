# Dashboard 学校归一化 + 精力有效评价 + AI 洞察夯实

## Context

Dashboard 数据仪表盘存在三个问题：

1. **学校数据缺失**：`get_student_makeup.by_school` 只查 `Student.school` 字段，但老师预约时基本不填学校。OCR 解析出的学校信息存在 `report.data_json.student.school`，未被 makeup 聚合使用。25 个学生不可能只有 3 所学校。
2. **学校/顾问名字未归一化**：SHSID 大小写、Angela/angela 被当成不同条目。用户要求含子串匹配（"世外" in "上海世外中学" → 同一所）。
3. **精力维度漏掉有效评价**：`get_indicator_aggregates` / `get_indicator_trends` / `get_student_profiles` 只调 `derive_evaluation`（规则推导），没走档位 fallback。导致体质健康（睡眠/饮食/运动/BMI）自带的有效评价被漏掉，精力维度数据点偏少。
4. **AI 洞察有"捏造感"**：部分 insights 像凭空抽象的维度而非基于具体指标。

## 改动文件

### 1. db.py — 学校数据源 + 归一化

**新增 `_normalize_school` 和 `_cluster_names` 函数**（放在 `get_dashboard_stats` 前）：

```python
import re

_SCHOOL_SUFFIXES = ("国际学校", "国际", "实验学校", "实验", "中学", "学校", "分校", "校区", "外国语学校", "外国语")

def _normalize_school(name: str) -> str:
    """学校名归一化：小写 + 去空格 + 去常见后缀。"""
    s = (name or "").strip().lower().replace(" ", "")
    for suf in _SCHOOL_SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf):
            s = s[: -len(suf)]
    return s

def _cluster_by_substring(raw_names: list) -> dict:
    """按子串关系聚类：短名是长名的子串 → 合并到短名。
    
    返回 {raw_name: cluster_representative} 映射。
    """
    # 先按 normalize 后的值分组
    norm_map = {}  # normalized → [raw_names]
    for name in raw_names:
        if not name:
            continue
        key = _normalize_school(name)
        norm_map.setdefault(key, []).append(name)
    
    # 在 normalized key 之间做子串聚类
    keys = sorted(norm_map.keys(), key=len)  # 短的优先
    key_to_canon = {}
    used = set()
    for k in keys:
        if k in used:
            continue
        key_to_canon[k] = k
        for other in keys:
            if other == k or other in used:
                continue
            if k in other:  # 短的是长的子串 → 合并
                key_to_canon[other] = k
                used.add(other)
        used.add(k)
    
    # raw_name → canon normalized key
    result = {}
    for key, names in norm_map.items():
        canon = key_to_canon.get(key, key)
        for name in names:
            result[name] = canon
    return result
```

**改 `get_student_makeup` 的 `by_school`（L968-973）**：

不再只查 `Student.school`，改为从 `report.data_json.student.school` 取学校（和 `get_student_profiles` 一致），再用归一化聚类：

```python
# 从 report.data_json 提取每个学生的学校
with Session(engine) as sess:
    report_rows = sess.execute(
        select(Report.data_json, Student.school).join(Student, Report.student_id == Student.id)
    ).all()
    raw_schools = []
    for dj, stu_school in report_rows:
        try:
            data = json.loads(dj) if dj else {}
        except:
            data = {}
        sch = (data.get("student") or {}).get("school") or stu_school or ""
        raw_schools.append(sch)
    
    # 归一化聚类
    cluster_map = _cluster_by_substring(raw_schools)
    # canon → count
    from collections import Counter
    school_counts = Counter()
    canon_to_display = {}  # 保留一个原始名做展示
    for raw in raw_schools:
        if not raw:
            continue
        canon = cluster_map.get(raw, _normalize_school(raw))
        school_counts[canon] += 1
        if canon not in canon_to_display:
            canon_to_display[canon] = raw
    
    by_school = [{"label": canon_to_display.get(c, c), "count": n} 
                 for c, n in school_counts.most_common()]
```

**改 advisor 名字归一化**：对 `advisor_name` 做小写+trim 归一化（不做子串匹配，人名太短容易误合并）：

```python
def _normalize_advisor(name: str) -> str:
    return (name or "").strip().lower()
```

在 advisor 聚合处（L977-1000），用 `_normalize_advisor` 归一化后再 group by，展示时保留原始大小写。

### 2. db.py — 精力维度档位 fallback

**问题**：`get_indicator_aggregates`（L1192）、`get_indicator_trends`（L1487）、`get_student_profiles`（L1342）三处都只调 `derive_evaluation`，漏掉档位 fallback。

**方案**：每处改成先调 `evaluation_rules.build_evaluation_view(items)` 拿到带 `eval_value` 的列表（含规则推导 + 档位 fallback），建 `code → eval_value` map，再在迭代里用这个 map 替代直接调 `derive_evaluation`。

以 `get_indicator_aggregates` 为例（其余两处同理）：

```python
from evaluation_rules import (
    dimension_of, derive_evaluation, _find_norm,
    _to_number, _code_int, build_evaluation_view,
)

# ... 在 report 循环里，items 拿到后：
eval_items, _ = build_evaluation_view(items)
eval_map = {}
for ei in eval_items:
    code = str(ei.get("code", ""))
    if code and ei.get("eval_value"):
        eval_map[code] = ei["eval_value"]

# 迭代 items 时：
for item in items:
    code = str(item.get("code", ""))
    ...
    ev = eval_map.get(code)  # 替代 derive_evaluation 调用
    # ev 现在包含规则推导 + 档位 fallback 的结果
```

**不改动** `evaluation_rules.py` 本身（它已有 `build_evaluation_view` 包含 fallback 逻辑）。

### 3. db.py — `get_student_profiles` 的 school 也用归一化

L1399 的 `"school": student_obj.get("school") or student.school` 保持不变（profiles 展示原始名），但 makeup 聚合时用归一化。

### 4. app.py — AI 洞察夯实

**系统 prompt（L1141-1172）加强约束**：在硬规则里追加：

```
9. 每条 insight 的 detail 必须至少引用一个数据中出现过的具体指标中文名称（如"睡眠习惯""焦虑安详""执行功能-工作记忆"），禁止只用维度名概括。
10. 禁止将多个指标打包成数据中不存在的组合名（如"情绪耗竭""认知负荷"等），只能用"XX 维度的 XX 指标"这种指代方式。
```

**data_summary 补充**：在【维度指标分布】段落里，为精力维度额外列出有档位评价的指标及其 eval 值（因为精力维度的有效评价来自档位 fallback，需要让 AI 看到具体值）。

## 验证

1. **本地验证学校归一化**：
```bash
python3 -c "
from db import get_dashboard_stats
s = get_dashboard_stats()
print('学校数:', len(s['student_makeup']['by_school']))
for sc in s['student_makeup']['by_school']:
    print(f'  [{sc[\"count\"]}] {sc[\"label\"]}')
"
```
预期：学校数从 3 增加到合理数量，SHSID 大小写合并，"世外"/"上海世外"合并。

2. **本地验证精力维度有效评价**：
```bash
python3 -c "
from db import get_indicator_aggregates
agg = get_indicator_aggregates()
dim = agg.get('by_dimension', {}).get('精力', [])
print('精力维度指标数:', len(dim))
for ind in dim:
    print(f'  {ind[\"label\"]}: most_common_eval={ind[\"most_common_eval\"]}, weak_pct={ind[\"weak_pct\"]}')
"
```
预期：体质健康（睡眠/饮食/运动/BMI）的 `most_common_eval` 不再为 None。

3. **Dashboard 页面**：访问 `/dashboard`，检查 07 学生构成的学校分布图、06 学生侧写的学校字段、AI 洞察是否引用具体指标名。
