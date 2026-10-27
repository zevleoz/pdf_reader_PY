# -*- coding: utf-8 -*-
"""Task 8：6AM v2 迁移脚本测试（unittest 风格）。

覆盖（实施计划 Task 8 Step 1）：
- dry-run 不写库
- 备份失败即中止（不写任何档案）
- apply 后无 score / predicted_effectiveness 残留
- 行数与 id/version 保持不变
- 模拟中途失败会 rollback

运行：python3.11 -m unittest test_migrate_six_am_v2 -v
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock  # noqa: F401  (test_midway_failure_rolls_back 使用)
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from sqlalchemy import create_engine  # noqa: E402

import db  # noqa: E402
import migrate_six_am_v2 as mig  # noqa: E402


def _v1_profile(report_id: int, name: str = "迁移学生") -> dict:
    """构造带旧 Score 字段的 v1 档案。"""
    return {
        "schema": "six-am-profile-v1",
        "student": {"name": name, "grade": "高二"},
        "report_id": report_id,
        "dimensions": {
            "A1": {"state": "Blocked", "confidence": "Hypothesis",
                   "score": {"total": 12.3, "base": 3.0},
                   "triggered_rules": [], "cross_mods": [], "flags": [], "notes": []},
            "A3": {"state": "At-Risk", "confidence": "Hypothesis",
                   "score": {"total": 1.4},
                   "triggered_rules": [], "cross_mods": [], "flags": [], "notes": []},
            "A6": {"state": None,
                   "support_ranking": {"ranked": [
                       {"direction": "家长陪同", "sub_mechanisms": ["陪跑"],
                        "predicted_effectiveness": "高", "score": 3.0,
                        "basis_rules": ["R6.8"], "cautions": ""}]}},
        },
        "obstacles": [{"dim": "A1", "score": 12.3, "high_priority": True,
                       "sequence": 1, "sequence_note": ""}],
        "sequence_note": "X.3 命中：A4/A5 分数 ×0.7（让位于 A3）。",
    }


def _rebuild_v04(report_id: int, source_profile: dict):
    """迁移测试固定用 v0.4 引擎重算（v2 档案结构），v0.5 为现行默认引擎。"""
    from six_am import build_profile
    return build_profile(int(report_id), source_profile=source_profile,
                         params={"engine": "v0.4"})


class MigrationBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_url = db.DATABASE_URL
        cls._orig_engine = db.engine
        cls._tmpdir = tempfile.mkdtemp(prefix="sixam_v2_")
        cls._db_path = Path(cls._tmpdir) / "test_sixam_v2.db"
        cls._engine = create_engine("sqlite:///%s" % cls._db_path)
        db.engine = cls._engine
        db.DATABASE_URL = "sqlite:///%s" % cls._db_path
        db.Base.metadata.create_all(cls._engine)

    @classmethod
    def tearDownClass(cls):
        db.engine = cls._orig_engine
        db.DATABASE_URL = cls._orig_url
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def setUp(self):
        db.Base.metadata.drop_all(self._engine)
        db.Base.metadata.create_all(self._engine)
        self.student_id = db.add_student(name="迁移学生", gender="", birthday="",
                                         grade="高二")
        self.report_id = db.add_report(self.student_id, date(2026, 1, 1), "x.pdf",
                                       json.dumps({"schema_124": []}))
        self.profile_ids = []

    def _add_profile(self, report_id=None, version=1, name="迁移学生"):
        rid = self.report_id if report_id is None else report_id
        pid = db.add_six_am_profile(self.student_id, rid,
                                    json.dumps(_v1_profile(rid, name), ensure_ascii=False),
                                    version)
        self.profile_ids.append(pid)
        return pid

    def _snapshot(self):
        out = {}
        for pid in self.profile_ids:
            row = db.get_six_am_profile(pid)
            out[pid] = (row["version"], row["profile_json"])
        return out

    def _backup_path(self, name="backup.db"):
        return str(Path(self._tmpdir) / name)


class DryRun(MigrationBase):
    def test_dry_run_does_not_write(self):
        pid = self._add_profile()
        before = db.get_six_am_profile(pid)["profile_json"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            items = mig.run_dry_run()
        self.assertEqual(len(items), 1)
        self.assertIn("不写数据库", buf.getvalue())
        self.assertEqual(db.get_six_am_profile(pid)["profile_json"], before)
        # v1 仍保留 score（未被改写）
        self.assertIn('"score"', db.get_six_am_profile(pid)["profile_json"])


class BackupFailure(MigrationBase):
    def test_backup_failure_aborts_before_writing(self):
        pid = self._add_profile()
        before = db.get_six_am_profile(pid)["profile_json"]
        # 备份目标是一个已存在目录 → copy2 失败
        with self.assertRaises(Exception):
            mig.run_apply(self._tmpdir)
        self.assertEqual(db.get_six_am_profile(pid)["profile_json"], before)


class ApplyMigration(MigrationBase):
    def test_apply_removes_score_and_keeps_ids_and_versions(self):
        self._add_profile(version=1)
        self._add_profile(version=2)
        before = self._snapshot()
        backup = self._backup_path("bk.db")
        items = mig.run_apply(backup, rebuild=_rebuild_v04)
        self.assertEqual(len(items), 2)
        self.assertTrue(os.path.exists(backup))
        self.assertGreater(os.path.getsize(backup), 0)

        after = self._snapshot()
        # 行数与 id/version 不变
        self.assertEqual(set(after.keys()), set(before.keys()))
        for pid in before:
            self.assertEqual(after[pid][0], before[pid][0])   # version 保留
        # 全部升为 v2 且无数值残留
        stats = mig.verify()
        self.assertEqual(stats["count"], 2)
        self.assertEqual(stats["problems"], [])
        for pid in before:
            prof = json.loads(db.get_six_am_profile(pid)["profile_json"])
            self.assertEqual(prof["schema"], mig.V2_SCHEMA)
            self.assertEqual(mig.residue(prof), [])
            self.assertNotIn('"score"', json.dumps(prof))

    def test_midway_failure_rolls_back(self):
        self._add_profile(version=1)
        self._add_profile(version=2)
        before = self._snapshot()
        backup = self._backup_path("bk_rollback.db")

        real = db.update_six_am_profile_json
        calls = {"n": 0}

        def flaky(profile_id, profile_json, session=None):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom")
            return real(profile_id, profile_json, session=session)

        with unittest.mock.patch.object(db, "update_six_am_profile_json", flaky):
            with self.assertRaises(RuntimeError):
                mig.run_apply(backup)

        # 第一条的写入必须被回滚
        after = self._snapshot()
        for pid in before:
            self.assertEqual(after[pid], before[pid], pid)


if __name__ == "__main__":
    import unittest.mock  # noqa: F401
    unittest.main(verbosity=2)
