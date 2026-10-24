#!/usr/bin/env python3
"""把 copilot_sessions.meeting_at 规整为 UTC ISO 字符串 ``YYYY-MM-DDTHH:MM:SSZ``。

**运行前先备份数据库，绝不要直接对 data/y4_students.db 执行：**

    sqlite3 data/y4_students.db ".backup '/tmp/ft-meeting/audit.db'"

用法（默认干跑，只打印将要改写的行，不写库）：

    /Users/jefflau/anaconda3/bin/python scripts/normalize_meeting_at.py \
        --db /tmp/ft-meeting/audit.db

    # 确认无误后实际写入
    /Users/jefflau/anaconda3/bin/python scripts/normalize_meeting_at.py \
        --db /tmp/ft-meeting/audit.db --apply

规则：
  * 带时区偏移或 ``Z`` 的存量值：换算到 UTC。
  * 无时区的存量值：旧代码用 ``datetime.utcnow()`` 写入，按 UTC 理解
    （与 API 入参把无时区时间当作上海本地时间不同）。
  * 已是目标格式的值保持不变，可重复执行（幂等）。
  * 无法解析的值保持原样并给出警告。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REAL_DB = (ROOT / "data" / "y4_students.db").resolve()
TARGET_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def normalize(value: str | None) -> str | None:
    """把存量 meeting_at 规整为目标格式；无效输入返回 None。"""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # 存量无时区值来自 datetime.utcnow()，按 UTC 理解。
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime(TARGET_FORMAT)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="规整 First Touch 会谈时间（copilot_sessions.meeting_at）")
    parser.add_argument("--db", required=True, help="SQLite 数据库路径（请用备份副本）")
    parser.add_argument("--apply", action="store_true",
                        help="实际写库；缺省为干跑")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    if db_path == REAL_DB:
        print("拒绝直接改写生产库 data/y4_students.db；请先备份到临时路径。",
              file=sys.stderr)
        return 1
    if not db_path.exists():
        print(f"数据库不存在：{db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    try:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "copilot_sessions" not in tables:
            print("未找到 copilot_sessions 表。", file=sys.stderr)
            return 1

        rows = conn.execute(
            "SELECT id, meeting_at FROM copilot_sessions ORDER BY id").fetchall()
        changes: list[tuple[int, str, str]] = []
        warnings: list[tuple[int, str]] = []
        for row_id, old_value in rows:
            if old_value is None or not str(old_value).strip():
                continue
            new_value = normalize(str(old_value))
            if new_value is None:
                warnings.append((row_id, str(old_value)))
            elif new_value != str(old_value):
                changes.append((row_id, str(old_value), new_value))

        for row_id, old_value in warnings:
            print(f"[跳过] id={row_id} 无法解析：{old_value}")
        for row_id, old_value, new_value in changes:
            print(f"id={row_id}: {old_value} -> {new_value}")

        if not changes:
            print(f"无需改写（扫描 {len(rows)} 行）。")
            return 0
        if not args.apply:
            print(f"干跑：将改写 {len(changes)} 行；加 --apply 实际写入。")
            return 0

        with conn:
            conn.executemany(
                "UPDATE copilot_sessions SET meeting_at = ? WHERE id = ?",
                [(new_value, row_id) for row_id, _, new_value in changes])
        print(f"已改写 {len(changes)} 行。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
