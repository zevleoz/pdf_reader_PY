"""家庭版显示规则（M1R-P6）：打印、预览和质量检查都用这一份。

存库的文档不改，显示时：
- 不生成“另见：……”来源行；导师手改过的其他线索照旧显示。
- Y4 行最多 3 条。
- AI 写的栏目超过上限时，只保留前面的整句；导师改过的栏目不动。
- 被删掉的句子上的事实核对标记一并去掉。
"""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional

from m1 import report_checks

_SPLIT_RE = re.compile(r"(?<=[。！？!?])")
# 与 report_pipeline.NO_CLUES 相同的固定说明；没有资料来源时保留它，避免误报“栏目为空”。
_NO_CLUES = "暂无直接相关资料。"


def cap_text(text: str, limit: int) -> str:
    """超过上限时保留前面的整句；第一句本身超长时保留第一句。"""
    if len(text) <= limit:
        return text
    pieces = [p for p in _SPLIT_RE.split(text) if p.strip()]
    keep: List[str] = []
    total = 0
    for piece in pieces:
        if keep and total + len(piece) > limit:
            break
        keep.append(piece)
        total += len(piece)
    return "".join(keep)


def sources_line(evidence, code: str) -> str:
    """其他资料来源行已下线；新报告和已有 AI 草稿都不显示。"""
    return ""


def get_path(doc: Any, path: Optional[list]) -> Any:
    node = doc
    for step in path or []:
        if isinstance(node, dict):
            node = node.get(step)
        elif isinstance(node, list) and isinstance(step, int) and 0 <= step < len(node):
            node = node[step]
        else:
            return None
    return node


def display_doc(doc: Optional[Dict[str, Any]], evidence) -> Dict[str, Any]:
    """返回按显示规则处理后的副本；``doc`` 本身不变。"""
    out = copy.deepcopy(doc) if isinstance(doc, dict) else {}
    for _dim_id, dim in (out.get("dims") or {}).items():
        for code, row in ((dim or {}).get("abilities") or {}).items():
            if not isinstance(row, dict):
                continue
            clues = row.get("other_clues") if isinstance(row.get("other_clues"), dict) else {}
            if clues.get("src") != "edited":
                line = sources_line(evidence, code)
                if line or (clues.get("text") or "").strip() != _NO_CLUES:
                    row["other_clues"] = {"text": line, "src": "code"}
            row["y4_selected"] = list(row.get("y4_selected") or [])[:report_checks.Y4_MAX]
    for path, _name, text, limit in report_checks.family_fields_with_limits(out):
        field = get_path(out, path)
        if not isinstance(field, dict) or field.get("src") == "edited":
            continue
        shown = cap_text(text, limit)
        if shown == text:
            continue
        field["text"] = shown
        if isinstance(field.get("sentences"), list):
            field["sentences"] = [row for row in field["sentences"]
                                  if isinstance(row, dict) and (row.get("text") or "") in shown]
    guard = out.get("guard")
    if isinstance(guard, dict) and isinstance(guard.get("flags"), list):
        kept = []
        for flag in guard["flags"]:
            if isinstance(flag, dict):
                sentence = str(flag.get("sentence") or "").strip()
                field = get_path(out, flag.get("path"))
                if sentence and isinstance(field, dict) and \
                        report_checks.normalize(sentence) not in \
                        report_checks.normalize(field.get("text") or ""):
                    continue
            kept.append(flag)
        guard["flags"] = kept
    return out


def display_version(version: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    version = dict(version or {})
    version["doc"] = display_doc(version.get("doc"), version.get("evidence"))
    return version
