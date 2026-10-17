"""存量学校回填：school 空/「—」的学生，用其最新报告 data_json 中的 student.school 回填。

默认 dry-run（只打印将改动的行），加 --apply 才落库。
纯读已有 JSON，不碰 OCR、不改其他字段。

用法：
    python scripts/backfill_school.py           # 预览
    python scripts/backfill_school.py --apply   # 落库
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

import db as _db  # noqa: E402
from db import Report, Student, Session, engine  # noqa: E402

_EMPTY = ("", "—", "-")


def _clean(v: str) -> str:
    v = (v or "").strip()
    return "" if v in _EMPTY else v


def main() -> int:
    apply = "--apply" in sys.argv

    with Session(engine) as sess:
        students = sess.execute(select(Student)).scalars().all()
        pending = []
        for st in students:
            if _clean(st.school):
                continue  # 已有有效学校
            # 取最新报告（report_date desc, id desc）
            rep = sess.execute(
                select(Report)
                .where(Report.student_id == st.id)
                .order_by(Report.report_date.desc(), Report.id.desc())
                .limit(1)
            ).scalars().first()
            if not rep or not rep.data_json:
                continue
            try:
                data = json.loads(rep.data_json)
            except Exception:
                continue
            school = _clean((data.get("student") or {}).get("school", ""))
            if not school:
                continue
            pending.append((st.id, st.name, st.student_code or "", st.school or "", school))

        if not pending:
            print("无需回填：没有 school 为空且报告里有学校值的学生。")
            return 0

        print(f"{'[APPLY] 将写入' if apply else '[DRY-RUN] 将写入'} {len(pending)} 行：")
        for sid, name, code, old, new in pending:
            print(f"  id={sid} {name}({code})  {old!r} -> {new!r}")

        if not apply:
            print("\n未落库。确认无误后加 --apply 执行。")
            return 0

        for sid, *_rest, new in pending:
            sess.execute(
                Student.__table__.update()
                .where(Student.id == sid)
                .values(school=new)
            )
        sess.commit()
        print(f"\n已完成 {len(pending)} 行学校回填。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
