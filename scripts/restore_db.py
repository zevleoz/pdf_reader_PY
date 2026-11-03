#!/usr/bin/env python3
"""从备份恢复 SQLite 数据库。

恢复前先校验备份文件，并把当前数据库另存一份。脚本不停止或启动服务，
由使用者在按提示操作。
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO / "data" / "y4_students.db"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="从备份恢复 SQLite 数据库")
    parser.add_argument("backup", help="备份文件")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="目标数据库文件")
    parser.add_argument("--yes", action="store_true", help="确认覆盖当前数据库")
    args = parser.parse_args(argv)

    if not args.yes:
        print("恢复会覆盖当前数据库。请先停止服务（sudo systemctl stop y4_report），"
              "确认后加 --yes 重新运行。")
        return 1

    backup = Path(args.backup)
    if not backup.exists():
        print("找不到备份文件")
        return 1

    try:
        check_conn = sqlite3.connect(str(backup))
        try:
            result = check_conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            check_conn.close()
        ok = bool(result) and result[0] == "ok"
    except sqlite3.DatabaseError:
        ok = False
    if not ok:
        print("备份文件校验失败，未做任何改动")
        return 1

    db = Path(args.db)
    saved = None
    if db.exists():
        saved = db.with_name(db.name + ".before-restore-"
                             + datetime.now().strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(db, saved)

    backup_conn = sqlite3.connect(str(backup))
    db_conn = sqlite3.connect(str(db))
    try:
        backup_conn.backup(db_conn)
    finally:
        db_conn.close()
        backup_conn.close()

    print("已恢复：%s。原数据库已另存为 %s。请启动服务：sudo systemctl start y4_report"
          % (backup.name, saved.name if saved else "无"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
