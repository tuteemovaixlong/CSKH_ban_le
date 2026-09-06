"""PostgreSQL transactions for the shared, parameterized repository statements."""
from contextlib import contextmanager
import re

from retailops.core import ApiError

IDENTITY_SCHEMA = 'retailops_identity'


def driver():
    try:
        import psycopg
    except ImportError:
        raise ValueError('PostgreSQL requires the packages in requirements-postgres.txt.') from None
    return psycopg


def validate_dsn(dsn):
    if not isinstance(dsn, str) or not dsn.strip():
        raise ValueError('PostgreSQL requires RETAILOPS_DATABASE_URL or RETAILOPS_DATABASE_URL_FILE.')
    try:
        options = driver().conninfo.conninfo_to_dict(dsn)
        if not options.get('dbname') or not options.get('user'):
            raise ValueError()
    except Exception:
        raise ValueError('Invalid PostgreSQL connection settings; connection details are not logged.') from None


def tenant_schema(storage_key):
    if not isinstance(storage_key, str) or not re.fullmatch(r'[a-f0-9]{32}', storage_key):
        raise ValueError('Invalid tenant storage key.')
    return 'tenant_' + storage_key


def valid_schema(schema):
    if schema != IDENTITY_SCHEMA and not re.fullmatch(r'tenant_[a-f0-9]{32}', schema):
        raise ValueError('Invalid database schema.')


class Queries:
    """Repository SQL uses qmark placeholders and dict-like rows on both engines.

    Statements are static, owned by the repository (no literal question marks).
    User values remain separate driver parameters; this is not a SQLite SQL translator.
    """
    def __init__(self, connection):
        self.raw = connection

    def execute(self, statement, parameters=()):
        return self.raw.execute(statement.replace('?', '%s'), parameters)

    def executemany(self, statement, parameters):
        cursor = self.raw.cursor()
        cursor.executemany(statement.replace('?', '%s'), parameters)
        return cursor


@contextmanager
def transaction(dsn, schema=IDENTITY_SCHEMA, *, write=False):
    valid_schema(schema)
    pg = driver()
    from psycopg import sql
    from psycopg.rows import dict_row
    try:
        with pg.connect(dsn, connect_timeout=5, row_factory=dict_row) as connection:
            connection.execute("SET LOCAL statement_timeout='15s'")
            connection.execute("SET LOCAL lock_timeout='5s'")
            # Only the server-selected schema is searched. Never fall back to public.
            connection.execute(sql.SQL('SET LOCAL search_path TO {}, pg_catalog').format(sql.Identifier(schema)))
            if write:
                # Preserve the existing SQLite serialized-write contract across processes.
                connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (schema,))
            yield Queries(connection)
    except pg.Error:
        # Database errors can include SQL values/DSNs; do not expose them to HTTP or logs.
        raise ApiError(503, 'database_unavailable', 'Kho dữ liệu chưa sẵn sàng. Vui lòng thử lại hoặc liên hệ quản trị viên.') from None


def assert_schema(db, schema, component):
    from psycopg import sql
    exists = db.raw.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s', (schema,)).fetchone()
    if not exists:
        raise ValueError('PostgreSQL schema is missing. Run the explicit database initialization/import command.')
    rows = db.raw.execute(sql.SQL('SELECT component,version FROM {}.retailops_schema').format(sql.Identifier(schema))).fetchall()
    if len(rows) != 1 or rows[0] != {'component': component, 'version': 2 if component == 'business' else 1}:
        raise ValueError('Unsupported PostgreSQL schema version or component.')


def check_schema(dsn, schema, component):
    with transaction(dsn, schema) as db:
        assert_schema(db, schema, component)
