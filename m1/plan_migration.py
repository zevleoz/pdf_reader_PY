"""Transactional SQLite DP12 migration. Called explicitly at boot, never at import."""
import re

NEW_COLUMNS = {
    'source_mode': "VARCHAR(20) NOT NULL DEFAULT 'report'",
    'teaching_brief': "TEXT NOT NULL DEFAULT '{}'",
    'brief_revision': 'INTEGER NOT NULL DEFAULT 0',
    'brief_confirmed_revision': 'INTEGER',
    'brief_confirmed_by': 'INTEGER',
    'session_durations': "TEXT NOT NULL DEFAULT '[60,60,60]'",
}


def migrate(engine, *, checkpoint=None):
    if engine.dialect.name != 'sqlite':
        return
    connection = engine.raw_connection()
    cursor = connection.cursor()
    fk = cursor.execute('PRAGMA foreign_keys').fetchone()[0]
    try:
        # PRAGMA foreign_keys cannot change inside a transaction.
        connection.commit()
        cursor.execute('PRAGMA foreign_keys=OFF')
        cursor.execute('BEGIN IMMEDIATE')
        columns = cursor.execute('PRAGMA table_info(m1_plans)').fetchall()
        if not columns:
            connection.commit()
            return
        names = {c[1] for c in columns}
        rebuild = any(c[1] in ('prep_id', 'report_id') and c[3] for c in columns)
        if rebuild:
            sql = cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='m1_plans'").fetchone()[0]
            sequence = None
            if 'AUTOINCREMENT' in sql.upper():
                sequence = cursor.execute("SELECT seq FROM sqlite_sequence WHERE name='m1_plans'").fetchone()
            objects = cursor.execute("SELECT sql FROM sqlite_master WHERE tbl_name='m1_plans' AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
            sql = re.sub(r'CREATE TABLE\s+(?:"m1_plans"|`m1_plans`|\[m1_plans\]|m1_plans)', 'CREATE TABLE m1_plans_dp12_new', sql, count=1, flags=re.I)
            for name in ('prep_id', 'report_id'):
                sql = re.sub(r'((?:"' + name + r'"|`' + name + r'`|\[' + name + r'\]|\b' + name + r'\b)\s+[^,\n]*?)\s+NOT NULL', r'\1', sql, count=1, flags=re.I)
            cursor.execute(sql)
            quoted = ','.join('"%s"' % c[1] for c in columns)
            cursor.execute(f'INSERT INTO m1_plans_dp12_new ({quoted}) SELECT {quoted} FROM m1_plans')
            cursor.execute('DROP TABLE m1_plans')
            if checkpoint:
                checkpoint('after_drop')
            cursor.execute('ALTER TABLE m1_plans_dp12_new RENAME TO m1_plans')
            if sequence is not None:
                cursor.execute("UPDATE sqlite_sequence SET seq=? WHERE name='m1_plans'", sequence)
            for (sql,) in objects:
                cursor.execute(sql)
        for name, ddl in NEW_COLUMNS.items():
            if name not in names:
                cursor.execute(f'ALTER TABLE m1_plans ADD COLUMN {name} {ddl}')
        violations = cursor.execute('PRAGMA foreign_key_check').fetchall()
        if violations:
            raise RuntimeError('DP12 migration foreign key check failed')
        if checkpoint:
            checkpoint('before_commit')
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        cursor.execute(f'PRAGMA foreign_keys={int(fk)}')
        cursor.close()
        connection.close()
