#!/usr/bin/env python3
"""Y4 平台 2.0 —— A 包地基迁移脚本。

职责：
  1. 建 users 表（若不存在），并在 users 为空时用环境变量创建初始 admin
  2. 为 students 回填 student_code（Y4-0001 起，按 id 升序），并加唯一索引

执行前请先备份数据库文件（SQLite）：
    cp data/y4_students.db data/y4_students.db.bak_$(date +%Y%m%d_%H%M%S)

用法：
    Y4_INITIAL_ADMIN_USER=xxx Y4_INITIAL_ADMIN_PASSWORD=yyy \
        python scripts/migrate_2_0_foundation.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 允许从项目根目录直接运行（scripts/ 的上一级）
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import db  # noqa: E402


def _backup_hint() -> str:
    if db.DATABASE_URL.startswith("sqlite"):
        # sqlite:////abs/path 或 sqlite:///rel/path
        return db.DATABASE_URL.split("sqlite:///", 1)[-1] or str(db.DEFAULT_DB)
    return db.DATABASE_URL


def create_initial_admin() -> None:
    """users 为空时，用环境变量创建初始 admin；缺省报错退出。"""
    existing = db.list_users()
    if existing:
        print(f"[users] 已存在 {len(existing)} 个用户，跳过初始 admin 创建")
        return
    username = (os.environ.get("Y4_INITIAL_ADMIN_USER") or "").strip()
    password = os.environ.get("Y4_INITIAL_ADMIN_PASSWORD") or ""
    if not username or not password:
        print("[错误] users 表为空，但未提供 Y4_INITIAL_ADMIN_USER / "
              "Y4_INITIAL_ADMIN_PASSWORD 环境变量，无法创建初始管理员。",
              file=sys.stderr)
        sys.exit(1)
    uid = db.create_user(
        username=username, password=password, role="admin",
        display_name=(os.environ.get("Y4_INITIAL_ADMIN_DISPLAY_NAME") or username),
    )
    print(f"[users] 已创建初始 admin: id={uid} username={username}")


def backfill_student_code() -> None:
    """为 students 回填 student_code（若列已存在）。按 id 升序从 Y4-0001 起。"""
    import sqlite3
    if not db.DATABASE_URL.startswith("sqlite"):
        print("[student_code] 非 SQLite 后端，跳过回填（由 ORM/后续迁移处理）")
        return
    db_path = db.DATABASE_URL.split("sqlite:///", 1)[-1]
    if not Path(db_path).exists():
        print("[student_code] 数据库文件不存在，跳过")
        return
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(students)")
    cols = {row[1] for row in cur.fetchall()}
    if "student_code" not in cols:
        print("[student_code] students.student_code 列不存在，跳过回填"
              "（请先执行 5.4 的列迁移）")
        conn.close()
        return
    cur.execute("SELECT id FROM students WHERE student_code IS NULL OR student_code = '' ORDER BY id ASC")
    pending = [r[0] for r in cur.fetchall()]
    if not pending:
        print("[student_code] 无需回填")
        conn.close()
        return
    cur.execute("SELECT MAX(student_code) FROM students WHERE student_code LIKE 'Y4-%'")
    row = cur.fetchone()
    next_no = 1
    if row and row[0]:
        try:
            next_no = int(str(row[0]).split("-")[1]) + 1
        except (IndexError, ValueError):
            next_no = 1
    for sid in pending:
        code = f"Y4-{next_no:04d}"
        cur.execute("UPDATE students SET student_code = ? WHERE id = ?", (code, sid))
        next_no += 1
    conn.commit()
    # 唯一性问题兜底：加唯一索引
    try:
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_students_student_code ON students (student_code)")
        conn.commit()
    except sqlite3.IntegrityError as exc:
        print(f"[student_code][错误] 存在重复 student_code：{exc}", file=sys.stderr)
        conn.close()
        sys.exit(1)
    print(f"[student_code] 已回填 {len(pending)} 条，起始 Y4-0001")
    conn.close()


def main() -> None:
    print("=" * 60)
    print("Y4 平台 2.0 · A 包地基迁移")
    print(f"数据库：{_backup_hint()}")
    print("提示：执行前请先备份数据库文件！")
    print("=" * 60)
    db.init_db()
    create_initial_admin()
    backfill_student_code()
    print("=" * 60)
    print(f"完成。当前用户数：{len(db.list_users())}")
    print("=" * 60)


if __name__ == "__main__":
    main()
