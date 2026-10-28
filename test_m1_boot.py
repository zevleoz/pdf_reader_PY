"""App boot on a brand-new database must create the M1 tables.

Runs in a clean subprocess: inside pytest, other tests import m1.store
first, which would hide a missing registration in db.init_db.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def test_fresh_boot_creates_m1_tables(tmp_path):
    env = dict(os.environ, DATABASE_URL="sqlite:///%s" % (tmp_path / "fresh.db"),
               SECRET_KEY="boot-test")
    env.pop("Y4_ENV", None)
    env.pop("FLASK_ENV", None)
    code = ("import app, db, sqlalchemy as sa; "
            "print(sorted(t for t in sa.inspect(db.engine).get_table_names() "
            "if t.startswith('m1_')))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert "['m1_preps', 'm1_sources', 'm1_versions']" in out.stdout
