"""DP12 legacy SQLite rebuild, failure atomicity and actual entry points."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event

from m1.plan_migration import migrate


@pytest.fixture(params=['plain', 'quoted', 'backtick', 'bracket'])
def legacy(tmp_path, request):
    engine = create_engine('sqlite:///' + str(tmp_path / 'legacy.db'))
    @event.listens_for(engine, 'connect')
    def enable_fk(conn, _):
        conn.execute('PRAGMA foreign_keys=ON')
    delimiters = {'plain': ('', ''), 'quoted': ('"', '"'), 'backtick': ('`', '`'), 'bracket': ('[', ']')}
    left, right = delimiters[request.param]
    def q(name):
        return left + name + right
    with engine.begin() as c:
        for name in ('students', 'users', 'm1_preps', 'm1_reports'):
            c.exec_driver_sql(f'CREATE TABLE {name} (id INTEGER PRIMARY KEY)')
            c.exec_driver_sql(f'INSERT INTO {name} VALUES (1)')
        c.exec_driver_sql(f'''CREATE TABLE {q('m1_plans')} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES students(id),
            {q('prep_id')} INTEGER NOT NULL REFERENCES m1_preps(id),
            {q('report_id')} INTEGER NOT NULL REFERENCES m1_reports(id),
            block_no INTEGER NOT NULL, current_version_id INTEGER,
            status TEXT NOT NULL DEFAULT 'approved', approved_by INTEGER,
            parent_status TEXT DEFAULT 'confirmed', parent_version_id INTEGER,
            UNIQUE (student_id, block_no))''')
        c.exec_driver_sql('CREATE TABLE m1_plan_versions (id INTEGER PRIMARY KEY, plan_id INTEGER REFERENCES m1_plans(id), doc TEXT)')
        c.exec_driver_sql('CREATE TABLE m1_plan_files (id INTEGER PRIMARY KEY, plan_id INTEGER REFERENCES m1_plans(id), stored_path TEXT)')
        c.exec_driver_sql('CREATE TABLE change_log (plan_id INTEGER)')
        c.exec_driver_sql('CREATE INDEX custom_plan_index ON m1_plans(status)')
        c.exec_driver_sql('CREATE TRIGGER custom_plan_trigger AFTER UPDATE ON m1_plans BEGIN INSERT INTO change_log VALUES (new.id); END')
        c.exec_driver_sql("INSERT INTO m1_plans VALUES (5,1,1,1,1,7,'approved',1,'confirmed',8)")
        c.exec_driver_sql("INSERT INTO m1_plans VALUES (99,1,1,1,2,NULL,'inputs',NULL,'none',NULL)")
        c.exec_driver_sql('DELETE FROM m1_plans WHERE id=99')
        c.exec_driver_sql("INSERT INTO m1_plan_versions VALUES (7,5,'internal'),(8,5,'parent')")
        c.exec_driver_sql("INSERT INTO m1_plan_files VALUES (4,5,'/private/fixture.txt')")
    yield engine
    engine.dispose()


def snapshot(engine):
    with engine.connect() as c:
        return {table: c.exec_driver_sql('SELECT * FROM ' + table).fetchall()
                for table in ('m1_plans', 'm1_plan_versions', 'm1_plan_files', 'sqlite_sequence')}


def test_rebuild_preserves_children_indexes_triggers_sequence_and_repeats(legacy):
    before = snapshot(legacy)
    migrate(legacy)
    migrated = snapshot(legacy)
    migrate(legacy)
    assert snapshot(legacy) == migrated
    assert migrated['m1_plans'][0][:10] == before['m1_plans'][0]
    assert migrated['m1_plans'][0][10:] == ('report', '{}', 0, None, None, '[60,60,60]')
    assert migrated['m1_plan_versions'] == before['m1_plan_versions']
    assert migrated['m1_plan_files'] == before['m1_plan_files']
    with legacy.begin() as c:
        assert c.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
        assert c.exec_driver_sql('PRAGMA foreign_key_check').fetchall() == []
        assert all(row[2] == 'm1_plans' for row in c.exec_driver_sql('PRAGMA foreign_key_list(m1_plan_versions)'))
        assert any(row[1] == 'custom_plan_index' for row in c.exec_driver_sql('PRAGMA index_list(m1_plans)'))
        c.exec_driver_sql("INSERT INTO m1_plans (student_id,block_no,source_mode) VALUES (1,2,'mentor_inputs')")
        assert c.exec_driver_sql('SELECT max(id) FROM m1_plans').scalar() == 100
        c.exec_driver_sql("UPDATE m1_plans SET status='review' WHERE id=5")
        assert c.exec_driver_sql('SELECT plan_id FROM change_log').scalar() == 5
    with pytest.raises(Exception, match='UNIQUE'):
        with legacy.begin() as c:
            c.exec_driver_sql('INSERT INTO m1_plans (student_id,block_no) VALUES (1,2)')
    with pytest.raises(Exception, match='FOREIGN KEY'):
        with legacy.begin() as c:
            c.exec_driver_sql('INSERT INTO m1_plan_files VALUES (6,999,\'bad\')')


@pytest.mark.parametrize('stage', ['after_drop', 'before_commit'])
def test_rebuild_failure_rolls_back_everything(legacy, stage):
    before = snapshot(legacy)
    with legacy.connect() as c:
        ddl = c.exec_driver_sql("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
    def fail(at):
        if at == stage:
            raise RuntimeError('injected')
    with pytest.raises(RuntimeError, match='injected'):
        migrate(legacy, checkpoint=fail)
    assert snapshot(legacy) == before
    with legacy.connect() as c:
        assert c.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
        assert c.exec_driver_sql("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall() == ddl
    migrate(legacy)


def test_invalid_fk_fails_before_commit(legacy):
    raw = legacy.raw_connection()
    raw.execute('PRAGMA foreign_keys=OFF')
    raw.execute("INSERT INTO m1_plan_files VALUES (9,999,'missing')")
    raw.commit()
    raw.execute('PRAGMA foreign_keys=ON')
    raw.close()
    before = snapshot(legacy)
    with pytest.raises(RuntimeError, match='foreign key check'):
        migrate(legacy)
    assert snapshot(legacy) == before


def test_real_app_boot_migrates_legacy_and_subprocess_ensure(tmp_path):
    """A fresh process detects the legacy shape through the production startup path."""
    import db
    import m1.plan_store as plans
    from sqlalchemy.schema import CreateTable
    engine = create_engine('sqlite:///' + str(tmp_path / 'boot.db'))
    # Populate the genuine prior shape, with all other tables created by real init_db.
    code = 'import db; db.init_db()'
    env = dict(os.environ, DATABASE_URL=str(engine.url), SECRET_KEY='fixture')
    root = Path(__file__).resolve().parent
    first = subprocess.run([sys.executable, '-c', code], cwd=root, env=env, capture_output=True, text=True, timeout=60)
    assert first.returncode == 0, first.stderr
    with engine.begin() as c:
        c.exec_driver_sql('DROP TABLE m1_plans')
        ddl = str(CreateTable(plans.M1Plan.__table__).compile(engine))
        for name in ('prep_id', 'report_id'):
            ddl = ddl.replace(name + ' INTEGER,', name + ' INTEGER NOT NULL,')
        from m1.plan_migration import NEW_COLUMNS
        ddl = '\n'.join(line for line in ddl.splitlines() if not any(line.strip().startswith(n + ' ') for n in NEW_COLUMNS))
        c.exec_driver_sql(ddl)
    for code in ('import app', 'from m1 import plan_store; plan_store.ensure_tables()'):
        result = subprocess.run([sys.executable, '-c', code], cwd=root, env=env, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        with engine.connect() as c:
            info = {row[1]: row for row in c.exec_driver_sql('PRAGMA table_info(m1_plans)')}
            assert info['prep_id'][3] == info['report_id'][3] == 0
            assert 'source_mode' in info
    engine.dispose()
