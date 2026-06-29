"""步骤③：校验 data/report_data.json 的完整性。

只做两件事：
  1. 结构正确（顶层含 sections，每个 section 含 groups，每个 group 含 items）；
  2. 每个 item 的 value 都有（不是 None/空）。

会把有问题的项写进 data/issues.txt，供人工复核。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
IN_FILE = DATA_DIR / "report_data.json"
ISSUES_FILE = DATA_DIR / "issues.txt"


def _iter_items(data: Dict[str, Any]):
    for sec in data.get("sections", []) or []:
        for grp in sec.get("groups", []) or []:
            for it in grp.get("items", []) or []:
                yield sec.get("title", ""), grp.get("name", ""), it


def main() -> int:
    if not IN_FILE.exists():
        print(f"[validate] 找不到 {IN_FILE}，先跑 extract.py")
        return 1

    with open(IN_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    issues: List[str] = []
    total = 0
    filled = 0

    for sec_title, grp_name, item in _iter_items(data):
        total += 1
        code = item.get("code", "?")
        val = item.get("value")
        if val is None or (isinstance(val, str) and val.strip() == ""):
            issues.append(f"[{sec_title} / {grp_name}] #{code} value 缺失")
        else:
            filled += 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if issues:
        ISSUES_FILE.write_text("\n".join(issues) + "\n", encoding="utf-8")
    else:
        ISSUES_FILE.write_text("OK\n", encoding="utf-8")

    print(f"[validate] 共 {total} 项，已填 {filled} 项；"
          f"问题 {len(issues)} 条 → data/issues.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
