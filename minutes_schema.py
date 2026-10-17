"""会议纪要结构化 Schema（minutes-v1）。

数据流：LLM 输出固定结构 JSON → 本模块校验/归一 → DB 存 minutes_json（内部中间层）
→ minutes_docx.build_minutes_docx 确定性渲染 DOCX。旧自由文本路径仍保留作为回退。

对外导出的固定契约：
  - SCHEMA_VERSION
  - FIXED_SECTION_TITLES   DOCX H1 锚点文本，逐字固定，下游解析依赖
  - validate_minutes(data)  归一化，输入非 dict 时抛 ValueError
  - minutes_to_markdown(d)  渲染页面预览 Markdown（沿用 v1 标题层级）
"""
from __future__ import annotations

from typing import Any, Dict, List

SCHEMA_VERSION = "minutes-v1"

# DOCX H1 锚点：不得随会议内容变化，下游按此文本定位章节
FIXED_SECTION_TITLES: List[str] = [
    "执行摘要",
    "心力",
    "精力",
    "学习力",
    "生涯力",
    "后续行动项",
    "会议总体判断",
]

_META_FIELDS = ["student_name", "grade", "gender", "meeting_date", "advisor", "attendees"]
_XINLI_FIELDS = ["emotion", "peers", "family", "motivation", "personality"]
_JINGLI_FIELDS = ["overview"]
_XUEXILI_FIELDS = ["cognitive", "executive", "motivation", "methods", "overall"]
_SHENGYALI_FIELDS = ["interests", "direction", "values", "overall"]
_ACTION_FIELDS = ["what", "why", "how", "timeline"]
MAX_ACTION_ITEMS = 5

_CN_NUM = ["一", "二", "三", "四", "五"]


def _as_str(value: Any) -> str:
    """把任意值矫正为去空白的字符串。list 以换行拼接，dict/None 视为空。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return "\n".join(s for s in (_as_str(v) for v in value) if s)
    if isinstance(value, dict):
        return ""
    return str(value).strip()


def _as_str_list(value: Any) -> List[str]:
    """把任意值矫正为非空字符串列表。"""
    if value is None:
        return []
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else []
    if isinstance(value, (list, tuple)):
        out: List[str] = []
        for v in value:
            s = _as_str(v)
            if s:
                out.append(s)
        return out
    return []


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def validate_minutes(data: dict) -> dict:
    """缺键补默认值、类型矫正、行动项裁剪到 5 条并按优先级连续编号。

    输入完全不可用（非 dict）时抛 ValueError。
    """
    if not isinstance(data, dict):
        raise ValueError("minutes data must be a dict")

    meta_raw = data.get("meeting_meta")
    if not isinstance(meta_raw, dict):
        meta_raw = {}
    meeting_meta = {f: _as_str(meta_raw.get(f)) for f in _META_FIELDS}

    def _group(key: str, fields: List[str]) -> Dict[str, str]:
        raw = data.get(key)
        if not isinstance(raw, dict):
            raw = {}
        return {f: _as_str(raw.get(f)) for f in fields}

    action_raw = data.get("action_items")
    action_items: List[Dict[str, Any]] = []
    if isinstance(action_raw, list):
        for item in action_raw[:MAX_ACTION_ITEMS]:
            if not isinstance(item, dict):
                continue
            entry = {f: _as_str(item.get(f)) for f in _ACTION_FIELDS}
            entry["priority"] = _as_int(item.get("priority"), len(action_items) + 1)
            action_items.append(entry)
        # 按优先级排序后重新连续编号，保证 1..N
        action_items.sort(key=lambda x: x["priority"])
        for i, it in enumerate(action_items, 1):
            it["priority"] = i

    return {
        "schema_version": SCHEMA_VERSION,
        "meeting_meta": meeting_meta,
        "executive_summary": _as_str_list(data.get("executive_summary")),
        "xinli": _group("xinli", _XINLI_FIELDS),
        "jingli": _group("jingli", _JINGLI_FIELDS),
        "xuexili": _group("xuexili", _XUEXILI_FIELDS),
        "shengyali": _group("shengyali", _SHENGYALI_FIELDS),
        "action_items": action_items,
        "overall_judgment": _as_str(data.get("overall_judgment")),
    }


def minutes_to_markdown(d: dict) -> str:
    """从结构化数据渲染预览 Markdown，标题层级与 v1 保持一致，供页面显示。"""
    meta = d.get("meeting_meta") or {}
    name = meta.get("student_name") or "【学生姓名】"

    lines: List[str] = [f"# Y4测评解读会议记录｜{name}", ""]

    # 一、核心结论
    lines.append("## 一、核心结论")
    for i, s in enumerate(d.get("executive_summary") or [], 1):
        lines.append(f"{i}. {s}")
    lines.append("")

    # 二、心力
    lines.append("## 二、心力")
    xinli = d.get("xinli") or {}
    for title, key in (
        ("情绪与自我概念", "emotion"),
        ("同伴关系", "peers"),
        ("家庭与依恋关系", "family"),
        ("内驱力", "motivation"),
        ("人格", "personality"),
    ):
        val = xinli.get(key, "")
        if val:
            lines.append(f"### {title}")
            lines.append(val)
    lines.append("")

    # 三、精力
    lines.append("## 三、精力")
    jingli = d.get("jingli") or {}
    if jingli.get("overview"):
        lines.append(jingli["overview"])
    lines.append("")

    # 四、学习力
    lines.append("## 四、学习力")
    xue = d.get("xuexili") or {}
    for title, key in (
        ("认知资源优势", "cognitive"),
        ("执行能力与认知灵活性", "executive"),
        ("学习动机", "motivation"),
        ("学习方法与策略", "methods"),
        ("学习力整体判断", "overall"),
    ):
        val = xue.get(key, "")
        if val:
            lines.append(f"### {title}")
            lines.append(val)
    lines.append("")

    # 五、生涯力
    lines.append("## 五、生涯力")
    sy = d.get("shengyali") or {}
    for title, key in (
        ("职业兴趣", "interests"),
        ("能力优势与专业方向", "direction"),
        ("职业价值观", "values"),
        ("生涯力整体判断", "overall"),
    ):
        val = sy.get(key, "")
        if val:
            lines.append(f"### {title}")
            lines.append(val)
    lines.append("")

    # 六、后续成长重点
    lines.append("## 六、后续成长重点")
    items = d.get("action_items") or []
    if items:
        for idx, it in enumerate(items):
            cn = _CN_NUM[idx] if idx < len(_CN_NUM) else str(idx + 1)
            what = it.get("what", "")
            lines.append(f"### 第{cn}优先级：{what}")
            if it.get("why"):
                lines.append(f"- **为什么：** {it['why']}")
            if it.get("how"):
                lines.append(f"- **怎么做：** {it['how']}")
            if it.get("timeline"):
                lines.append(f"- **时间：** {it['timeline']}")
            lines.append("")
    else:
        lines.append("- 本次会议未形成明确行动项。")
        lines.append("")

    # 七、会议形成的总体判断
    lines.append("## 七、会议形成的总体判断")
    if d.get("overall_judgment"):
        lines.append(d["overall_judgment"])

    return "\n".join(lines)