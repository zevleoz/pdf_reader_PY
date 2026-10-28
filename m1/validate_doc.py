"""M1 文档校验：占位符扫描、优先能力覆盖、Y4 原始分值泄漏。

三个检查函数都返回问题列表；``validate_doc`` 汇总后抛
:class:`DocValidationError`。生成流程在落库前调用一次。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

PLACEHOLDER_TOKENS = ("〔", "〕", "AI 填写", "待分析", "TODO")

# 数字前是这些字符时，属于编号（R4、第 4 环节、日期分隔符）
_CODE_PREFIXES = ("第", "R", "r")
_DATE_JOINERS = "-/:."

_SKIP_KEYS = {"id", "origin", "code"}


class DocValidationError(ValueError):
    """文档未通过校验。``problems`` 为逐条可读信息。"""

    def __init__(self, problems: Iterable[str]):
        self.problems = list(problems)
        super().__init__("；".join(self.problems))


def _is_skipped_key(key) -> bool:
    return isinstance(key, str) and (key in _SKIP_KEYS or key.endswith("id"))


def _iter_strings(value: Any, key: str = "") -> Iterable[str]:
    """遍历文档里的文本值（跳过 id/code/origin 之类的标识字段）。"""
    if isinstance(value, str):
        if not _is_skipped_key(key):
            yield value
        return
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _iter_strings(child, str(child_key))
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            yield from _iter_strings(child, key)


def scan_placeholders(doc: Dict[str, Any]) -> List[str]:
    """返回文档中出现的占位符标记（去重）。空列表表示通过。"""
    found: List[str] = []
    for text in _iter_strings(doc):
        for token in PLACEHOLDER_TOKENS:
            if token in text and token not in found:
                found.append(token)
    return found


def check_priority_coverage(doc: Dict[str, Any]) -> List[str]:
    """返回未在 3.2 事件或 3.3 备用问题中安排的优先能力编号。"""
    covered = set()
    for event in doc.get("events") or []:
        if isinstance(event, dict):
            for code in event.get("abilities") or []:
                if isinstance(code, str):
                    covered.add(code.strip())
    for backup in doc.get("backups") or []:
        if isinstance(backup, dict) and isinstance(backup.get("code"), str):
            covered.add(backup["code"].strip())

    missing: List[str] = []
    for row in doc.get("priority") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        if code and code not in covered and code not in missing:
            missing.append(code)
    return missing


def _raw_specs(evidence) -> List[tuple]:
    """(raw value, indicator name) for every Y4 item with a numeric raw score."""
    specs = []
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        raw = item.get("raw")
        if raw is None or isinstance(raw, bool):
            continue
        try:
            value = float(str(raw).strip())
        except (TypeError, ValueError):
            continue
        label = str(item.get("text") or "").split("：")[0]
        name = re.split(r"[—\-]", label)[-1].strip()
        specs.append((value, name))
    return specs


def _iter_block_texts(value: Any) -> Iterable[str]:
    """只遍历会被渲染的文本：block.text 与 3.2 的 clue。"""
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ("text", "clue") and isinstance(child, str):
                yield child
            else:
                yield from _iter_block_texts(child)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            yield from _iter_block_texts(child)


# 指标名后多少个字符内出现的数字算作该指标的分值
_NEAR_NAME = 16


def _leak_spans(text: str, specs: List[tuple]) -> List[tuple]:
    """返回泄漏的原始分值 (start, end, token)。

    只有两种情况算泄漏：数字紧跟「分」，或数字出现在对应指标名之后
    _NEAR_NAME 个字符以内。孤立的小数字（R4、60 分钟、日期）不算。
    """
    spans = []
    for match in re.finditer(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])", text):
        start, end = match.span()
        before = text[:start]
        if before.endswith(_CODE_PREFIXES) or (before and before[-1] in _DATE_JOINERS):
            continue
        number = float(match.group(0))
        hits = [name for value, name in specs if abs(number - value) < 1e-9]
        if not hits:
            continue
        after = text[end:].lstrip()
        window = before[-_NEAR_NAME:]
        if after.startswith("分") and not after.startswith("分钟"):
            spans.append((start, end, match.group(0)))
        elif any(name and name in window for name in hits):
            spans.append((start, end, match.group(0)))
    return spans


def check_no_raw_numbers(doc: Dict[str, Any], evidence) -> List[str]:
    """返回文档文本里出现的 Y4 原始分值（去重，字符串形式）。"""
    specs = _raw_specs(evidence)
    if not specs:
        return []
    leaked: List[str] = []
    for text in _iter_block_texts(doc):
        for _start, _end, token in _leak_spans(text, specs):
            token = str(int(float(token))) if float(token).is_integer() else token
            if token not in leaked:
                leaked.append(token)
    return leaked


def redact_raw_numbers(doc: Any, evidence, _specs=None) -> int:
    """就地删除泄漏的原始分值（连同紧跟的「分」），返回删除处数。"""
    specs = _raw_specs(evidence) if _specs is None else _specs
    if not specs:
        return 0
    count = 0
    if isinstance(doc, dict):
        for key, child in doc.items():
            if key in ("text", "clue") and isinstance(child, str):
                spans = _leak_spans(child, specs)
                for start, end, _token in reversed(spans):
                    tail = child[end:]
                    if tail.lstrip().startswith("分"):
                        end += len(tail) - len(tail.lstrip()) + 1
                    child = (child[:start].rstrip() + child[end:]).strip()
                    count += 1
                doc[key] = child
            else:
                count += redact_raw_numbers(child, evidence, specs)
    elif isinstance(doc, list):
        for child in doc:
            count += redact_raw_numbers(child, evidence, specs)
    return count


def validate_doc(doc: Dict[str, Any], evidence=None) -> None:
    """运行全部检查；有问题时抛 :class:`DocValidationError`。"""
    problems: List[str] = []

    placeholders = scan_placeholders(doc)
    if placeholders:
        problems.append("文档含占位符：%s" % "、".join(placeholders))

    uncovered = check_priority_coverage(doc)
    if uncovered:
        problems.append("优先能力未安排到 3.2/3.3：%s" % "、".join(uncovered))

    leaked = check_no_raw_numbers(doc, evidence)
    if leaked:
        problems.append("文档出现 Y4 原始分值：%s" % "、".join(leaked))

    if problems:
        raise DocValidationError(problems)
