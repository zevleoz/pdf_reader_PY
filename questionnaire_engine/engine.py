"""问卷识别规则引擎 —— 纯函数求值，零 Flask import、零 DB 访问。

模块纪律参照 ``six_am/``：输入「指标列表 + rules_json」，输出命中列表
``[{"questionnaire_code": ..., "reason": ...}]``。

DSL（spec 6.4）：

    {
      "version": 1,
      "rules": [
        {"questionnaire_code": "Q-XXX-01",
         "when": {"all": [{"code": "013", "op": "<", "value": 5}]},
         "reason": "命中原因（写进 assignment.reason）"}
      ]
    }

- 条件对象：``{code, op, value}``；op ∈ =, !=, <, <=, >, >=, in, contains
- ``all``（且）/ ``any``（或）二选一，不支持嵌套；空条件视为不命中
- ``code`` 引用指标 code；引用不存在的 code 视为不命中（不报错）
- 数值比较前尝试 float 转换，失败回退字符串比较
- 同一 ``questionnaire_code`` 可写多条规则，命中任意一条即推荐该问卷
  （等价于 OR，用来表达「(A 且 B) 或 C」而无需嵌套）

一期扩展（在 spec 6.4 之上的两点，向需求方说明后落地）：

1. 条件可带可选字段 ``"source"``，取值 ``"value"``（默认）或 ``"eval"``。
   ``source="eval"`` 时比较的是该指标的**有效评价档位**（由调用方用
   ``evaluation_rules`` 的既有口径算出，挂到条目的 ``eval_value`` 上）。
   例：``{"code": "068", "op": "=", "value": "偏低", "source": "eval"}``
   表达「学习动机-自我效能感（相对常模 130）评价为偏低」。
2. ``value`` 允许为 ``null``（表示与空值比较），但仍遵循等值语义。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

OPS = ("=", "!=", "<", "<=", ">", ">=", "in", "contains")
_NUM_OPS = ("<", "<=", ">", ">=")


def _to_number(value: Any) -> Optional[float]:
    """尽力转 float；失败返回 None（bool 不参与数值比较）。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        s = str(value).strip()
    except Exception:
        return None
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def norm_code(code: Any) -> str:
    """code 归一：纯数字 code 同时接受 "013" / "13" 两种写法。"""
    s = str(code if code is not None else "").strip()
    return s


def _index_items(items: Optional[List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """code → item 索引；纯数字 code 同时登记去前导零别名。"""
    index: Dict[str, Dict[str, Any]] = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        code = norm_code(it.get("code"))
        if not code:
            continue
        index.setdefault(code, it)
        if code.isdigit():
            index.setdefault(str(int(code)), it)
    return index


def _lookup(index: Dict[str, Dict[str, Any]], code: Any) -> Optional[Dict[str, Any]]:
    if code is None:
        return None
    s = norm_code(code)
    if not s:
        return None
    item = index.get(s)
    if item is None and s.isdigit():
        item = index.get(str(int(s)))
    return item


def _pick(item: Dict[str, Any], source: str) -> Any:
    """按 source 取被比较值：value（原始值，默认）/ eval（有效评价档位）。"""
    if source == "eval":
        return item.get("eval_value")
    return item.get("value")


def _eq(left: Any, right: Any) -> bool:
    ln, rn = _to_number(left), _to_number(right)
    if ln is not None and rn is not None:
        return ln == rn
    return str(left if left is not None else "").strip() == \
        str(right if right is not None else "").strip()


def _compare(left: Any, op: str, right: Any) -> bool:
    if left is None:
        return op == "=" and right is None
    if op == "=":
        return _eq(left, right)
    if op == "!=":
        return not _eq(left, right)
    if op == "in":
        if not isinstance(right, (list, tuple, set)):
            return False
        return any(_eq(left, cand) for cand in right)
    if op == "contains":
        if right is None:
            return False
        if isinstance(left, (list, tuple, set)):
            return any(_eq(cand, right) for cand in left)
        return str(right) in str(left)
    if op in _NUM_OPS:
        ln, rn = _to_number(left), _to_number(right)
        if ln is not None and rn is not None:
            if op == "<":
                return ln < rn
            if op == "<=":
                return ln <= rn
            if op == ">":
                return ln > rn
            return ln >= rn
        # float 转换失败 → 回退字符串比较（要求两侧都是字符串）
        if isinstance(left, str) and isinstance(right, str):
            if op == "<":
                return left < right
            if op == "<=":
                return left <= right
            if op == ">":
                return left > right
            return left >= right
        return False
    return False


def eval_condition(cond: Any, index: Dict[str, Dict[str, Any]]) -> bool:
    """单条件求值；结构非法或 code 不存在 → False。"""
    if not isinstance(cond, dict):
        return False
    op = cond.get("op")
    if op not in OPS:
        return False
    item = _lookup(index, cond.get("code"))
    if item is None:
        return False
    source = cond.get("source") or "value"
    return _compare(_pick(item, source), op, cond.get("value"))


def eval_when(when: Any, index: Dict[str, Dict[str, Any]]) -> bool:
    """条件组求值：all / any 二选一；空组 / 非法结构 → False（不命中）。"""
    if not isinstance(when, dict):
        return False
    if isinstance(when.get("all"), list):
        conds = when["all"]
        return bool(conds) and all(eval_condition(c, index) for c in conds)
    if isinstance(when.get("any"), list):
        conds = when["any"]
        return bool(conds) and any(eval_condition(c, index) for c in conds)
    return False


def evaluate(items: Optional[List[Dict[str, Any]]],
             rules_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """求值规则集，返回命中列表（按 rules 顺序、questionnaire_code 去重）。"""
    rules = (rules_json or {}).get("rules") if isinstance(rules_json, dict) else None
    if not isinstance(rules, list):
        return []
    index = _index_items(items)
    hits: List[Dict[str, Any]] = []
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        code = norm_code(rule.get("questionnaire_code"))
        if not code or code in seen:
            continue
        if eval_when(rule.get("when"), index):
            seen.add(code)
            hits.append({
                "questionnaire_code": code,
                "reason": str(rule.get("reason") or "").strip(),
            })
    return hits


def validate_rules(rules_json: Any, known_codes: Optional[set] = None) -> List[str]:
    """服务端结构校验；返回错误信息列表（空列表 = 通过）。

    ``known_codes`` 给定时，额外返回「引用了不存在 code」的**警告**（不阻断发布），
    由调用方决定是 error 还是 warning —— 这里统一返回带前缀的字符串。
    """
    errors: List[str] = []
    if not isinstance(rules_json, dict):
        return ["rules_json 必须是 JSON 对象"]
    rules = rules_json.get("rules")
    if not isinstance(rules, list) or not rules:
        return ["rules 必须是非空数组"]
    for i, rule in enumerate(rules):
        tag = f"第 {i + 1} 条规则"
        if not isinstance(rule, dict):
            errors.append(f"{tag}：必须是对象")
            continue
        if not norm_code(rule.get("questionnaire_code")):
            errors.append(f"{tag}：缺少 questionnaire_code")
        when = rule.get("when")
        if not isinstance(when, dict):
            errors.append(f"{tag}：缺少 when")
            continue
        groups = [k for k in ("all", "any") if isinstance(when.get(k), list)]
        if len(groups) != 1:
            errors.append(f"{tag}：when 必须且只能包含 all 或 any 之一")
            continue
        for j, cond in enumerate(when[groups[0]]):
            ctag = f"{tag} 条件 {j + 1}"
            if not isinstance(cond, dict):
                errors.append(f"{ctag}：必须是对象")
                continue
            if not norm_code(cond.get("code")):
                errors.append(f"{ctag}：缺少 code")
            if cond.get("op") not in OPS:
                errors.append(f"{ctag}：op 必须是 {', '.join(OPS)} 之一")
            if cond.get("source") not in (None, "value", "eval"):
                errors.append(f"{ctag}：source 只能是 value 或 eval")
            if known_codes is not None and norm_code(cond.get("code")):
                if _lookup({c: {} for c in known_codes}, cond.get("code")) is None:
                    errors.append(f"警告 {ctag}：code {cond.get('code')} 不在已知指标集合中")
    return errors
