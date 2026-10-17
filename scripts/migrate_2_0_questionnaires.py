#!/usr/bin/env python3
"""Y4 平台 2.0 —— C 包问卷子系统迁移脚本。

职责：
  1. 建问卷子系统 7 张表（questionnaires / questionnaire_rules / assignments /
     assignment_tokens / student_accounts / responses / response_drafts）
  2. 建活动任务部分唯一索引（ux_assignments_active）
  3. 导入固定题库（questionnaires_seed/*.json，按 code upsert）
  4. 首次运行时导入并发布初始识别规则（questionnaires_seed/_rules_v1.json）

执行前请先备份数据库文件（SQLite）：
    cp data/y4_students.db data/y4_students.db.bak_$(date +%Y%m%d_%H%M%S)

用法：
    python scripts/migrate_2_0_questionnaires.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import db  # noqa: E402
import questionnaire_store as qs  # noqa: E402


def _backup_hint() -> str:
    if db.DATABASE_URL.startswith("sqlite"):
        return db.DATABASE_URL.split("sqlite:///", 1)[-1] or str(db.DEFAULT_DB)
    return db.DATABASE_URL


def main() -> None:
    print("=" * 60)
    print("Y4 平台 2.0 · C 包问卷子系统迁移")
    print(f"数据库：{_backup_hint()}")
    print("提示：执行前请先备份数据库文件！")
    print("=" * 60)

    db.init_db()                       # 建表 + ensure_indexes
    qs.create_tables(db.engine)
    qs.ensure_indexes(db.engine)
    print("[tables] 问卷子系统 7 张表 + 活动任务部分唯一索引已就绪")

    report = qs.load_seed_files()
    print("[bank] 题库导入：" + json.dumps(report, ensure_ascii=False))

    rules = qs.load_rules_seed()
    print("[rules] 识别规则种子：" + json.dumps(rules, ensure_ascii=False))

    banks = qs.list_questionnaires()
    print("=" * 60)
    print(f"完成。题库共 {len(banks)} 份问卷：")
    for q in banks:
        print(f"  - {q['code']}  {q['title']}  active={q['is_active']}")
    versions = qs.list_rule_versions()
    pub = [v for v in versions if v["status"] == "published"]
    print(f"规则版本 {len(versions)} 个，其中 published {len(pub)} 个")
    print("=" * 60)


if __name__ == "__main__":
    main()
