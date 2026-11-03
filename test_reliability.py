# -*- coding: utf-8 -*-
"""F5：健康检查、版本、数据库备份与恢复。

所有数据库都在 tmp_path 临时目录，绝不触碰 data/y4_students.db。
"""
from __future__ import annotations

import importlib.util
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event

import app_utils
import db as _db
import questionnaire_store as qs

REPO_ROOT = Path(__file__).resolve().parent
PASSWORD = "pw-123456"


def _load(name):
    spec = importlib.util.spec_from_file_location(
        "f5_" + name, REPO_ROOT / "scripts" / ("%s.py" % name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_db(path, rows):
    with sqlite3.connect(str(path)) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.executemany("INSERT INTO t (x) VALUES (?)", [(i,) for i in range(rows)])
    return path


def _rows(path):
    with sqlite3.connect(str(path)) as conn:
        return conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]


def _backup(tmp_path):
    backup_db = _load("backup_db")
    src = _make_db(tmp_path / "src.db", 3)
    out = tmp_path / "out"
    assert backup_db.main(["--db", str(src), "--out", str(out)]) == 0
    files = sorted(out.glob("y4_students-*.db"))
    assert len(files) == 1
    return files[0]


@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/login_platforms.db")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    _db.Base.metadata.create_all(engine)
    qs.ensure_indexes(bind=engine)
    monkeypatch.setattr(_db, "engine", engine)
    monkeypatch.setattr(qs, "engine", engine)
    monkeypatch.delenv("E4_URL", raising=False)
    app_utils._SESSION_USER_CACHE.clear()
    app_utils._RATE_BUCKETS.clear()

    w = SimpleNamespace(
        admin_id=_db.create_user("t-admin", PASSWORD, "admin"),
        advisor_id=_db.create_user("t-adv", PASSWORD, "advisor", advisor_name="Mine"),
        no_m1_id=_db.create_user("t-adv-nom1", PASSWORD, "advisor",
                                 advisor_name="Mine", m1_access=0),
        viewer_id=_db.create_user("t-view", PASSWORD, "viewer"),
    )
    yield w
    app_utils._SESSION_USER_CACHE.clear()
    app_utils._RATE_BUCKETS.clear()
    engine.dispose()


@pytest.fixture()
def app(world):
    import app as app_module
    application = app_module.create_app()
    application.config["TESTING"] = True
    application.secret_key = "test"
    return application


def _client(app, user_id, role, advisor_name=""):
    """旧 session 形态：只有 user_id / role / advisor_name，其余由账号同步。"""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role
        sess["advisor_name"] = advisor_name
    return client


# ── 1. 备份 ────────────────────────────────────────────────────
def test_backup_copies_database(tmp_path):
    backup_db = _load("backup_db")
    src = _make_db(tmp_path / "src.db", 3)
    out = tmp_path / "backups"

    assert backup_db.main(["--db", str(src), "--out", str(out)]) == 0

    files = list(out.glob("y4_students-*.db"))
    assert len(files) == 1
    assert _rows(files[0]) == 3


# ── 2. 清理旧备份 ──────────────────────────────────────────────
def test_backup_prunes_to_keep(tmp_path):
    backup_db = _load("backup_db")
    src = _make_db(tmp_path / "src.db", 3)
    out = tmp_path / "backups"

    for i in range(3):
        assert backup_db.main(["--db", str(src), "--out", str(out), "--keep", "2"]) == 0
        if i < 2:
            time.sleep(1.1)

    files = list(out.glob("y4_students-*.db"))
    assert len(files) == 2


# ── 3. 非 SQLite 拒绝备份 ───────────────────────────────────────
def test_backup_refuses_non_sqlite(tmp_path, monkeypatch):
    backup_db = _load("backup_db")
    src = _make_db(tmp_path / "src.db", 3)
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")

    assert backup_db.main(["--db", str(src), "--out", str(tmp_path / "backups")]) == 2


# ── 4. 恢复必须显式确认 ────────────────────────────────────────
def test_restore_requires_yes(tmp_path):
    restore_db = _load("restore_db")
    backup = _backup(tmp_path)
    target = _make_db(tmp_path / "target.db", 1)

    assert restore_db.main([str(backup), "--db", str(target)]) == 1
    assert _rows(target) == 1


# ── 5. 恢复 ────────────────────────────────────────────────────
def test_restore_replaces_database(tmp_path):
    restore_db = _load("restore_db")
    backup = _backup(tmp_path)
    target = _make_db(tmp_path / "target.db", 1)

    assert restore_db.main([str(backup), "--db", str(target), "--yes"]) == 0

    assert _rows(target) == 3
    saved = list(tmp_path.glob("target.db.before-restore-*"))
    assert len(saved) == 1
    assert _rows(saved[0]) == 1


# ── 6. 坏备份被拒绝 ────────────────────────────────────────────
def test_restore_rejects_bad_backup(tmp_path):
    restore_db = _load("restore_db")
    bad = tmp_path / "bad.db"
    bad.write_text("not a database", encoding="utf-8")
    target = _make_db(tmp_path / "target.db", 1)

    assert restore_db.main([str(bad), "--db", str(target), "--yes"]) == 1
    assert _rows(target) == 1


# ── 7. 健康检查 ────────────────────────────────────────────────
def test_healthz_is_public(app):
    resp = app.test_client().get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


# ── 8. 版本 ────────────────────────────────────────────────────
def test_admin_version(app, world):
    resp = _client(app, world.admin_id, "admin").get("/api/admin/version")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["commit"]

    resp = _client(app, world.viewer_id, "viewer").get("/api/admin/version")
    assert resp.status_code != 200

    resp = app.test_client().get("/api/admin/version")
    assert resp.status_code != 200
