# -*- coding: utf-8 -*-
"""根 conftest：pytest 全程不得连接/修改真实库 data/y4_students.db。

四道防线：
1. 收集测试模块之前（本文件 import 时）把 DATABASE_URL 指向本次运行的临时 SQLite；
   若外部已把 DATABASE_URL 指向真实库则直接退出。子进程继承该环境变量。
2. 全局 SQLAlchemy do_connect 钩子：任何 engine 试图打开真实库文件即抛错（在打开文件之前）。
3. 每个测试前后检查 db.engine / questionnaire_store.engine 未被重绑到真实库。
4. 会话结束时比对真实库 mtime/size，有变化则判本次运行失败（兜底 sqlite3 直连/子进程）。
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine, make_url

_BASE_DIR = Path(__file__).resolve().parent
_REAL_DB = (_BASE_DIR / "data" / "y4_students.db").resolve()


def _points_at_real_db(url) -> bool:
    try:
        u = make_url(str(url))
    except Exception:
        return False
    if not u.drivername.startswith("sqlite") or not u.database:
        return False
    if u.database == ":memory:":
        return False
    return Path(u.database).resolve() == _REAL_DB


def _real_db_stamp():
    try:
        st = _REAL_DB.stat()
    except FileNotFoundError:
        return None
    return (st.st_mtime_ns, st.st_size)


_env_url = os.environ.get("DATABASE_URL")
if _env_url and _points_at_real_db(_env_url):
    pytest.exit("DATABASE_URL 指向真实库 %s，拒绝运行测试" % _REAL_DB, returncode=2)

_TMP_DIR = None
if not _env_url:
    _TMP_DIR = tempfile.mkdtemp(prefix="y4_pytest_")
    os.environ["DATABASE_URL"] = "sqlite:///%s" % os.path.join(_TMP_DIR, "pytest.db")

_REAL_DB_STAMP = _real_db_stamp()


@event.listens_for(Engine, "do_connect")
def _refuse_real_db(dialect, conn_rec, cargs, cparams):
    if dialect.name != "sqlite":
        return
    target = cparams.get("database") or (cargs[0] if cargs else "")
    if target and target != ":memory:" and Path(str(target)).resolve() == _REAL_DB:
        raise RuntimeError("测试禁止连接真实库 %s" % _REAL_DB)


def _real_db_binding():
    """返回指向真实库的绑定描述（无则 None）。"""
    for mod_name in ("db", "questionnaire_store"):
        mod = sys.modules.get(mod_name)
        engine = getattr(mod, "engine", None) if mod else None
        if engine is not None and _points_at_real_db(engine.url):
            return "%s.engine" % mod_name
    db_mod = sys.modules.get("db")
    if db_mod is not None and _points_at_real_db(getattr(db_mod, "DATABASE_URL", "")):
        return "db.DATABASE_URL"
    return None


def pytest_configure(config):
    import db  # noqa: F401  —— 让 db 在任何测试模块之前以临时库初始化
    bad = _real_db_binding()
    if bad:
        pytest.exit("%s 指向真实库 %s，拒绝运行测试" % (bad, _REAL_DB), returncode=2)


@pytest.fixture(autouse=True)
def _guard_real_db():
    bad = _real_db_binding()
    if bad:
        pytest.fail("%s 指向真实库 %s" % (bad, _REAL_DB), pytrace=False)
    yield
    bad = _real_db_binding()
    if bad:
        pytest.fail("测试结束后 %s 指向真实库 %s" % (bad, _REAL_DB), pytrace=False)


def pytest_sessionfinish(session, exitstatus):
    if _real_db_stamp() != _REAL_DB_STAMP:
        session.exitstatus = 1
        tr = session.config.pluginmanager.get_plugin("terminalreporter")
        msg = "真实库 %s 在本次测试运行中被修改！" % _REAL_DB
        if tr is not None:
            tr.write_line(msg, red=True, bold=True)
        else:
            print(msg, file=sys.stderr)
    if _TMP_DIR:
        shutil.rmtree(_TMP_DIR, ignore_errors=True)
