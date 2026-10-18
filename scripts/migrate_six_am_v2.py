#!/usr/bin/env python3
"""6AM 档案 v2 迁移：备份 + 重算 + 覆盖历史 six_am_profiles。

背景（Task 8）：Task 1 起 6AM 档案升级为 ``six-am-profile-v2``，旧 v1 档案仍带
ObstacleScore / 数值权重字段。本脚本把每行现有 profile 作为 ``source_profile``
重算，就地覆盖 ``profile_json``，保留原 ``id / version / created_at``。

安全约束：
- ``--dry-run`` 只读预演，不写数据库；
- ``--apply`` 必须先二进制备份 SQLite 文件，备份失败即退出，不写任何档案；
- 全部覆盖在单个事务内完成，任一失败 ``rollback``。

用法：
    python3.11 scripts/migrate_six_am_v2.py --dry-run
    python3.11 scripts/migrate_six_am_v2.py --apply \\
        --backup data/backups/y4_students_before_sixam_v2_<timestamp>.db
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import db  # noqa: E402
import six_am  # noqa: E402

V2_SCHEMA = "six-am-profile-v2"


# ── 备份 ──────────────────────────────────────────────────────
def sqlite_path() -> Optional[str]:
    """当前 DATABASE_URL 对应的 SQLite 文件路径；非 SQLite 返回 None。"""
    url = db.DATABASE_URL or ""
    if not url.startswith("sqlite"):
        return None
    return url.split("sqlite:///", 1)[-1] or str(db.DEFAULT_DB)


def backup_db(backup_path: str) -> Path:
    """二进制备份 SQLite 数据库；失败抛异常（调用方据此中止，不写任何档案）。"""
    db_path = sqlite_path()
    if not db_path:
        raise RuntimeError("DATABASE_URL 非 SQLite，无法二进制备份：%s" % db.DATABASE_URL)
    src = Path(db_path)
    if not src.exists():
        raise RuntimeError("数据库文件不存在：%s" % src)
    dst = Path(backup_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if not dst.exists() or dst.stat().st_size == 0:
        raise RuntimeError("备份未生成或为空：%s" % dst)
    return dst


# ── 枚举与重算（只读）──────────────────────────────────────────
def _load_rows(session) -> List[Any]:
    from sqlalchemy import select
    from db import SixAmProfile
    stmt = select(SixAmProfile).order_by(SixAmProfile.id.asc())
    return list(session.execute(stmt).scalars().all())


def _rebuild(report_id: int, source_profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """用旧档案作为 source_profile 重算 v2 档案；报告不存在返回 None。"""
    if not report_id:
        return None
    return six_am.build_profile(int(report_id), source_profile=source_profile)


def plan(session, rebuild: Optional[Callable] = None) -> List[Dict[str, Any]]:
    """枚举所有 six_am_profiles 并逐行重算（不写库）。"""
    rebuild = rebuild or _rebuild
    items: List[Dict[str, Any]] = []
    for row in _load_rows(session):
        try:
            src = json.loads(row.profile_json or "{}")
        except Exception:
            src = {}
        items.append({
            "profile_id": row.id,
            "report_id": row.report_id,
            "version": row.version,
            "source": src,
            "new": rebuild(int(row.report_id or 0), src),
        })
    return items


# ── 数值残留检测 ───────────────────────────────────────────────
def residue(profile: Any) -> List[str]:
    """返回仍带数值权重字段的路径（迁移后应为空）。"""
    if not isinstance(profile, dict):
        return ["<not-a-profile>"]
    problems: List[str] = []
    for dim, rec in (profile.get("dimensions") or {}).items():
        if not isinstance(rec, dict):
            continue
        if "score" in rec:
            problems.append("dimensions.%s.score" % dim)
        sr = rec.get("support_ranking")
        if isinstance(sr, dict):
            for i, r in enumerate(sr.get("ranked") or []):
                if isinstance(r, dict) and ("score" in r or "predicted_effectiveness" in r):
                    problems.append("dimensions.%s.support_ranking.ranked[%d]" % (dim, i))
    for i, ob in enumerate(profile.get("obstacles") or []):
        if isinstance(ob, dict) and "score" in ob:
            problems.append("obstacles[%d].score" % i)
    sp = profile.get("support_plan") or {}
    for i, r in enumerate(sp.get("ranked") or []):
        if isinstance(r, dict) and ("score" in r or "predicted_effectiveness" in r):
            problems.append("support_plan.ranked[%d]" % i)
    return problems


def _primary_dim(profile: Any) -> str:
    obstacles = (profile or {}).get("obstacles") or []
    if obstacles and isinstance(obstacles[0], dict):
        return str(obstacles[0].get("dim") or "—")
    return "—"


# ── dry-run 输出 ───────────────────────────────────────────────
def print_dry_run(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    print("报告编号  档案ID  版本   可迁移  主要障碍(前 → 后)")
    migratable = 0
    for it in items:
        ok = it["new"] is not None
        migratable += 1 if ok else 0
        before = _primary_dim(it["source"])
        after = _primary_dim(it["new"]) if ok else "—"
        print("%8s  %6s  %4s   %s    %s → %s" % (
            it["report_id"], it["profile_id"], it["version"],
            "是" if ok else "否", before, after))
    print("-" * 56)
    print("合计 %d 条，可迁移 %d 条，不可迁移 %d 条（不写数据库）。"
          % (len(items), migratable, len(items) - migratable))
    return items


# ── 覆盖（单事务）──────────────────────────────────────────────
def apply_items(session, items: List[Dict[str, Any]]) -> int:
    """逐行覆盖 profile_json；不提交，由调用方统一 commit / rollback。"""
    migrated = 0
    for it in items:
        if it["new"] is None:
            raise RuntimeError("profile_id=%s（report_id=%s）无法重算，迁移中止"
                               % (it["profile_id"], it["report_id"]))
        payload = json.dumps(it["new"], ensure_ascii=False)
        ok = db.update_six_am_profile_json(it["profile_id"], payload, session=session)
        if not ok:
            raise RuntimeError("profile_id=%s 更新未命中" % it["profile_id"])
        migrated += 1
    session.commit()
    return migrated


def run_dry_run() -> List[Dict[str, Any]]:
    from sqlalchemy.orm import Session
    with Session(db.engine) as session:
        items = plan(session)
    return print_dry_run(items)


def run_apply(backup_path: str, rebuild: Optional[Callable] = None) -> List[Dict[str, Any]]:
    """备份后单事务覆盖。备份失败即抛，尚未写任何档案。"""
    from sqlalchemy.orm import Session
    backup_db(backup_path)
    session = Session(db.engine)
    try:
        items = plan(session, rebuild=rebuild)
        apply_items(session, items)
    except Exception:
        session.rollback()
        session.close()
        raise
    session.close()
    return items


def verify() -> Dict[str, Any]:
    """迁移后校验：schema 均为 v2，且无 score / predicted_effectiveness 残留。"""
    from sqlalchemy.orm import Session
    with Session(db.engine) as session:
        rows = _load_rows(session)
    problems: List[str] = []
    for row in rows:
        try:
            prof = json.loads(row.profile_json or "{}")
        except Exception:
            problems.append("profile_id=%s profile_json 解析失败" % row.id)
            continue
        if prof.get("schema") != V2_SCHEMA:
            problems.append("profile_id=%s schema=%s" % (row.id, prof.get("schema")))
        res = residue(prof)
        if res:
            problems.append("profile_id=%s 残留：%s" % (row.id, ", ".join(res)))
    return {"count": len(rows), "problems": problems}


# ── CLI ───────────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="6AM 档案 v2 迁移（备份 + 重算 + 覆盖）")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="只读预演，不写数据库")
    group.add_argument("--apply", action="store_true", help="备份后覆盖旧档案")
    ap.add_argument("--backup", help="apply 时的二进制备份路径")
    args = ap.parse_args(argv)

    db.init_db()

    if args.dry_run:
        run_dry_run()
        return 0

    if not args.backup:
        print("[错误] --apply 必须提供 --backup <路径>", file=sys.stderr)
        return 2

    try:
        items = run_apply(args.backup)
    except Exception as exc:
        print("[错误] 迁移中止并回滚：%s" % exc, file=sys.stderr)
        return 1

    print("已覆盖 %d 条档案；备份：%s" % (len(items), args.backup))
    stats = verify()
    print("校验：%d 条档案，问题 %d 项" % (stats["count"], len(stats["problems"])))
    for p in stats["problems"]:
        print("  · " + p, file=sys.stderr)
    return 0 if not stats["problems"] else 1


if __name__ == "__main__":
    sys.exit(main())
