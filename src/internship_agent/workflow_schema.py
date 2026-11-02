"""Additive application workflow schema; discovery layout/history stay intact."""
VERSION = 1
DDL = (
    '''CREATE TABLE preparation_operations (
        operation_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
        request_key TEXT NOT NULL, input_sha TEXT NOT NULL, job_sha TEXT NOT NULL,
        profile_sha TEXT, profile_path TEXT, options_json TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('pending','committed','failed')),
        packet_json TEXT, created_at TEXT NOT NULL, completed_at TEXT,
        UNIQUE(job_id,request_key))''',
    "CREATE UNIQUE INDEX idx_preparation_pending ON preparation_operations(job_id) WHERE state='pending'",
    '''CREATE TABLE application_bindings (
        job_id TEXT PRIMARY KEY REFERENCES applications(job_id),
        operation_id TEXT NOT NULL REFERENCES preparation_operations(operation_id),
        input_sha TEXT NOT NULL, job_sha TEXT NOT NULL,
        profile_sha TEXT NOT NULL, profile_path TEXT NOT NULL, packet_sha TEXT NOT NULL,
        packet_json TEXT NOT NULL, review_token TEXT NOT NULL, approved_token TEXT)''',
    '''CREATE TABLE submission_records (
        job_id TEXT PRIMARY KEY REFERENCES applications(job_id), evidence TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind='user_supplied'),
        verification TEXT NOT NULL CHECK(verification='unverified'),
        approval_token TEXT NOT NULL, recorded_at TEXT NOT NULL)''',
)


def migrate(connection):
    owned = not connection.in_transaction
    if owned:
        connection.execute('BEGIN IMMEDIATE')
    else:
        connection.execute('UPDATE jobs SET id=id WHERE 0')
    connection.execute('SAVEPOINT workflow_migration')
    try:
        if connection.execute('PRAGMA user_version').fetchone()[0] not in (2, 3):
            raise ValueError('Initialize the supported discovery schema before workflow migration')
        connection.execute('''CREATE TABLE IF NOT EXISTS workflow_schema (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL)''')
        row = connection.execute('SELECT version FROM workflow_schema WHERE singleton=1').fetchone()
        version = row[0] if row else 0
        if version > VERSION:
            raise ValueError('Unsupported application workflow schema')
        if version == 0:
            for statement in DDL:
                connection.execute(statement)
            connection.execute('INSERT INTO workflow_schema VALUES(1,?)', (VERSION,))
        # Old binaries reject >2 before permitting their unbound approval writes.
        connection.execute('PRAGMA user_version=3')
        connection.execute('RELEASE SAVEPOINT workflow_migration')
        if owned:
            connection.commit()
    except BaseException:
        connection.execute('ROLLBACK TO SAVEPOINT workflow_migration')
        connection.execute('RELEASE SAVEPOINT workflow_migration')
        if owned:
            connection.rollback()
        raise
