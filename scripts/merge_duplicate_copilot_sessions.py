#!/usr/bin/env python3
"""合并重复的 First Touch 会谈（每名学生只保留一条非归档 session）。

**运行前先备份数据库**（绝不要直接对 data/y4_students.db 执行）：

    sqlite3 data/y4_students.db ".backup '/tmp/ft-sessions/audit.db'"

用法：

    # 干跑：只打印每名学生将保留 / 归档哪一条，不改数据
    /Users/jefflau/anaconda3/bin/python scripts/merge_duplicate_copilot_sessions.py \
        --db /tmp/ft-sessions/audit.db

    # 实际执行：归档重复会话 + 创建部分唯一索引
    /Users/jefflau/anaconda3/bin/python scripts/merge_duplicate_copilot_sessions.py \
        --db /tmp/ft-sessions/audit.db --apply

保留规则（依次比较）：
  (a) run_id 关联到已确认报告（CONFIRMED）的会话；
  (b) phase 最高；
  (c) updated_at 最新。
其余会话置为 ``status='ARCHIVED'``（从不删除），并为每条归档写一条
``copilot_session_archived_duplicate`` 审计。最后创建
``uq_copilot_session_student_active`` 部分唯一索引（仅约束非归档行）。

幂等：重复执行只会归档同一批行一次，索引已存在时跳过。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import db as _db  # noqa: E402
import growth_talk_store as store  # noqa: E402

_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_copilot_session_student_active "
    "ON copilot_sessions(student_id) WHERE status != 'ARCHIVED'"
)


def _confirmed_run_ids(sess: Session, run_ids: list[int]) -> set[int]:
    if not run_ids:
        return set()
    rows = sess.execute(
        select(store.GtReport.run_id).where(
            store.GtReport.run_id.in_(run_ids),
            store.GtReport.status == "CONFIRMED",
        )
    ).scalars().all()
    return {int(run_id) for run_id in rows if run_id is not None}


def _keep_key(row: store.CopilotSession, confirmed: set[int]):
    return (
        1 if row.run_id is not None and int(row.run_id) in confirmed else 0,
        int(row.phase or 0),
        row.updated_at or datetime.min,
        int(row.id),
    )


def merge_duplicates(engine, apply: bool = False, out=print) -> dict:
    """按保留规则归档重复会话；``apply=False`` 只打印不写入。"""
    kept: list[dict] = []
    archived: list[dict] = []
    with Session(engine) as sess:
        student_ids = sess.execute(
            select(store.CopilotSession.student_id)
            .where(store.CopilotSession.status != "ARCHIVED")
            .group_by(store.CopilotSession.student_id)
            .having(func.count(store.CopilotSession.id) > 1)
            .order_by(store.CopilotSession.student_id.asc())
        ).scalars().all()

        for student_id in student_ids:
            rows = sess.execute(
                select(store.CopilotSession).where(
                    store.CopilotSession.student_id == student_id,
                    store.CopilotSession.status != "ARCHIVED",
                ).order_by(store.CopilotSession.id.asc())
            ).scalars().all()
            confirmed = _confirmed_run_ids(
                sess, [row.run_id for row in rows if row.run_id is not None])
            winner = max(rows, key=lambda row: _keep_key(row, confirmed))
            losers = [row for row in rows if row.id != winner.id]
            reason = ("confirmed_report" if _keep_key(winner, confirmed)[0]
                      else "phase" if any(int(r.phase or 0) for r in losers)
                      else "updated_at")
            out(
                f"学生 {student_id}：保留 session {winner.id}"
                f"（phase {winner.phase}，{winner.updated_at}），"
                f"归档 {', '.join(str(row.id) for row in losers)}"
            )
            kept.append({
                "studentId": int(student_id),
                "sessionId": int(winner.id),
                "reason": reason,
            })
            if not apply:
                continue
            archived_changes = []
            for row in losers:
                row.status = "ARCHIVED"
                archived.append({
                    "studentId": int(student_id),
                    "sessionId": int(row.id),
                    "keptSessionId": int(winner.id),
                    "reason": reason,
                })
                archived_changes.append({
                    "keptSessionId": int(winner.id),
                    "archivedSessionId": int(row.id),
                    "reason": reason,
                })
            sess.commit()
            for change in archived_changes:
                store.write_audit(
                    None, int(student_id),
                    "copilot_session_archived_duplicate",
                    json.dumps(change, ensure_ascii=False))

    if apply:
        with engine.begin() as conn:
            conn.exec_driver_sql(_INDEX_SQL)
        out("已创建部分唯一索引 uq_copilot_session_student_active。")
    else:
        out("干跑完成，未写入任何数据（加 --apply 才会归档并建索引）。")
    return {"students": len(kept), "kept": kept, "archived": archived,
            "applied": bool(apply)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="合并重复的 First Touch 会谈（每名学生一条非归档 session）")
    parser.add_argument("--db", required=True,
                        help="目标 SQLite 数据库文件（请使用备份副本）")
    parser.add_argument("--apply", action="store_true",
                        help="实际归档重复会话并创建唯一索引（默认干跑）")
    args = parser.parse_args(argv)

    path = Path(args.db).expanduser().resolve()
    if not path.exists():
        print(f"数据库不存在：{path}", file=sys.stderr)
        return 2
    if path == Path(_db.DEFAULT_DB).resolve():
        print("拒绝在真实学生库 data/y4_students.db 上运行；请先备份到副本。",
              file=sys.stderr)
        return 2

    engine = create_engine(f"sqlite:///{path}",
                           connect_args={"check_same_thread": False})
    _db.engine = engine
    summary = merge_duplicates(engine, apply=args.apply)
    if not summary["students"]:
        print("没有重复的非归档会话。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
