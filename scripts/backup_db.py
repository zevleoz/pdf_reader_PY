#!/usr/bin/env python3
"""SQLite 数据库备份脚本。

用 SQLite 自身的 backup API 在服务运行时安全复制数据库，并做完整性校验、
按保留份数清理旧备份。不打印数据库内容。
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO / "data" / "y4_students.db"
DEFAULT_OUT = REPO / "backups"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="备份 SQLite 数据库")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="源数据库文件")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="备份输出目录")
    parser.add_argument("--keep", type=int, default=14, help="保留的备份份数")
    args = parser.parse_args(argv)

    # 在打开数据库或创建输出目录之前拒绝非正数，避免把已有备份全部清空。
    if args.keep < 1:
        parser.error("--keep 必须是 1 或更大的整数")

    url = os.environ.get("DATABASE_URL")
    if url and not url.startswith("sqlite"):
        print("只支持 SQLite 数据库")
        return 2

    db = Path(args.db)
    if not db.exists():
        print("找不到数据库文件")
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # 同一秒内已有备份时改用 _001 起的序号，独占创建保证不会覆盖旧备份；
    # 下划线排在 "." 之后，按文件名排序仍保持时间先后。
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # Continue above surviving suffixes; a pruned base name must not be reused
    # and then immediately removed as the lexically oldest backup.
    prefix = "y4_students-%s" % stamp
    used = []
    for existing in out.glob(prefix + "*.db"):
        stem = existing.stem
        suffix = stem[len(prefix):]
        if not suffix:
            used.append(0)
        elif suffix.startswith("_") and suffix[1:].isdigit():
            used.append(int(suffix[1:]))
    first_seq = max(used, default=-1) + 1
    target = None
    for seq in range(first_seq, 1000):
        suffix = "" if seq == 0 else "_%03d" % seq
        candidate = out / ("y4_students-%s%s.db" % (stamp, suffix))
        try:
            fd = os.open(str(candidate), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            continue
        os.close(fd)
        target = candidate
        break
    if target is None:
        print("同一秒内的备份文件名已用尽")
        return 1

    try:
        source_conn = sqlite3.connect(str(db))
        target_conn = sqlite3.connect(str(target))
        try:
            source_conn.backup(target_conn)
        finally:
            target_conn.close()
            source_conn.close()

        check_conn = sqlite3.connect(str(target))
        try:
            result = check_conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            check_conn.close()
    except Exception:
        # 只删除本次独占创建的文件，已有的备份不受影响。
        target.unlink(missing_ok=True)
        raise

    if not result or result[0] != "ok":
        target.unlink()
        print("备份校验失败")
        return 1

    size_kb = target.stat().st_size / 1024

    files = sorted(out.glob("y4_students-*.db"), key=lambda p: p.name)
    for old in files[:max(0, len(files) - args.keep)]:
        old.unlink()
    remaining = len(list(out.glob("y4_students-*.db")))

    print("备份完成：%s，%.1f KB，保留 %d 份" % (target.name, size_kb, remaining))
    return 0


if __name__ == "__main__":
    sys.exit(main())
