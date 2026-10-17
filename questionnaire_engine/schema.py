"""问卷 schema 工具 —— 题目分组与服务端答案校验（纯函数、零 Flask、零 DB）。

schema 结构（spec 6.3，外加两处向后兼容的可选扩展）：

    {
      "version": 1,
      "sections": [ {"id", "title", "intro"} ],          # 可选：分段（问卷 2 用）
      "questions": [
        {"id", "type": "single|multi|scale|text", "title", "required",
         "options": [{"value", "label"}],
         "scale": {"min", "max", "min_label", "max_label"},
         "max_length": 500,
         "dimension": "焦虑",           # 可选：来源维度（供后续计分对齐）
         "section": "erq"}              # 可选：所属分段 id
      ]
    }
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

TYPES = ("single", "multi", "scale", "text")


def questions_of(schema: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [q for q in ((schema or {}).get("questions") or []) if isinstance(q, dict)]


def sections_of(schema: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [s for s in ((schema or {}).get("sections") or []) if isinstance(s, dict)]


def group_by_section(schema: Optional[Dict[str, Any]]) -> List[Tuple[Optional[Dict[str, Any]],
                                                                     List[Dict[str, Any]]]]:
    """按 sections 顺序分组题目；无 sections 时返回单组 (None, 全部题目)。"""
    qs = questions_of(schema)
    sections = sections_of(schema)
    if not sections:
        return [(None, qs)]
    buckets: List[Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]] = []
    by_id: Dict[str, List[Dict[str, Any]]] = {}
    for s in sections:
        sid = str(s.get("id") or "")
        by_id[sid] = []
        buckets.append((s, by_id[sid]))
    orphans: List[Dict[str, Any]] = []
    for q in qs:
        sid = str(q.get("section") or "")
        if sid in by_id:
            by_id[sid].append(q)
        else:
            orphans.append(q)
    out = [(s, qlist) for s, qlist in buckets if qlist]
    if orphans:
        out.append((None, orphans))
    return out


def _to_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_answers(schema: Optional[Dict[str, Any]],
                     answers: Optional[Dict[str, Any]]) -> List[str]:
    """服务端校验：必填 / 类型 / 选项值合法 / scale 区间 / max_length。

    返回错误信息列表（空列表 = 通过）。答案 key 一律按题目 id 字符串匹配。

    错误文案引用**题号**（按 ``questions_of`` 的枚举顺序，1 起）而非整段题干，
    以便学生在作答页一眼定位到漏答的题；前端据此把「第 N 题」渲染为可点击跳转。
    """
    answers = answers if isinstance(answers, dict) else {}
    errors: List[str] = []
    for idx, q in enumerate(questions_of(schema), start=1):
        qid = str(q.get("id") or "")
        ref = f"第 {idx} 题"
        required = bool(q.get("required"))
        qtype = q.get("type") or "single"
        val = answers.get(qid)

        if qtype == "text":
            text = "" if val is None else str(val)
            if required and not text.strip():
                errors.append(f"{ref}：需要作答")
            max_len = q.get("max_length")
            if max_len and len(text) > int(max_len):
                errors.append(f"{ref}：超过字数上限")
            continue

        if qtype == "multi":
            values = val if isinstance(val, list) else []
            if required and not values:
                errors.append(f"{ref}：至少选择一项")
            allowed = {str(o.get("value")) for o in (q.get("options") or [])}
            for v in values:
                if str(v) not in allowed:
                    errors.append(f"{ref}：选项 {v} 非法")
            continue

        if qtype == "scale":
            num = _to_number(val)
            sc = q.get("scale") or {}
            if num is None:
                if required:
                    errors.append(f"{ref}：需要作答")
                continue
            lo = _to_number(sc.get("min"))
            hi = _to_number(sc.get("max"))
            if (lo is not None and num < lo) or (hi is not None and num > hi):
                errors.append(f"{ref}：取值需在 {sc.get('min')} 到 {sc.get('max')} 之间")
            continue

        # single
        if val is None or (isinstance(val, str) and not val.strip()):
            if required:
                errors.append(f"{ref}：需要作答")
            continue
        allowed = {str(o.get("value")) for o in (q.get("options") or [])}
        if str(val) not in allowed:
            errors.append(f"{ref}：选项 {val} 非法")
    return errors
