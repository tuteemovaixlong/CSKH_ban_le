"""PostgreSQL transactions for the shared, parameterized repository statements."""
from contextlib import contextmanager
import re
from urllib.parse import parse_qs, unquote, urlsplit

from retailops.core import ApiError

IDENTITY_SCHEMA = 'retailops_identity'
IDENTITY_SCHEMA_CURRENT = 5
IDENTITY_SCHEMA_COMPATIBLE = (1, 2, 3, 4, 5)
BUSINESS_SCHEMA_CURRENT = 4
BUSINESS_SCHEMA_COMPATIBLE = (2, 3, 4)  # v2/v3 remain readable during migrations.

_LIBPQ_CONNINFO_KEYWORDS = frozenset({
    'authtype', 'service', 'user', 'password', 'passfile', 'channel_binding',
    'connect_timeout', 'client_encoding', 'options', 'application_name',
    'fallback_application_name', 'keepalives', 'keepalives_idle',
    'keepalives_interval', 'keepalives_count', 'tcp_user_timeout', 'tty',
    'replication', 'gssencmode', 'host', 'hostaddr', 'port', 'dbname',
    'sslmode', 'requiressl', 'sslcompression', 'sslcert', 'sslkey',
    'sslpassword', 'sslcertmode', 'sslrootcert', 'sslcrl', 'sslcrldir',
    'sslsni', 'requirepeer', 'ssl_min_protocol_version',
    'ssl_max_protocol_version', 'krbsrvname', 'gsslib', 'gssdelegation',
    'target_session_attrs', 'load_balance_hosts', 'require_auth',
})


def driver():
    try:
        import psycopg
    except ImportError:
        raise ValueError('PostgreSQL requires the packages in requirements-postgres.txt.') from None
    return psycopg


def _parse_dsn_options(dsn: str) -> dict[str, str]:
    if any(ch in dsn for ch in ('\x00', '\r', '\n')):
        raise ValueError()
    text = dsn.strip()
    if text.startswith(('postgresql://', 'postgres://')):
        if any(ch.isspace() or ord(ch) < 32 for ch in text):
            raise ValueError()
        parsed = urlsplit(text)
        if parsed.fragment or parsed.netloc.count('@') > 1:
            raise ValueError()
        if parsed.port is not None and not (1 <= parsed.port <= 65535):
            raise ValueError()
        query = parse_qs(parsed.query, keep_blank_values=True)
        for key in query:
            if key not in _LIBPQ_CONNINFO_KEYWORDS:
                raise ValueError()
        if 'port' in query and query['port'][-1]:
            for part in query['port'][-1].split(','):
                if not (1 <= int(part) <= 65535):
                    raise ValueError()
        raw_path = unquote(parsed.path or '')
        if raw_path and not raw_path.startswith('/'):
            raise ValueError()
        path_db = raw_path[1:] if raw_path.startswith('/') else ''
        if '/' in path_db:
            raise ValueError()
        dbname = path_db or query.get('dbname', [''])[-1].strip()
        user = unquote(parsed.username or '') or query.get('user', [''])[-1].strip()
        return {'dbname': dbname, 'user': user}
    if '://' in text:
        raise ValueError()
    options: dict[str, str] = {}
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        key_start = i
        while i < n and (text[i].isalnum() or text[i] == '_'):
            i += 1
        key = text[key_start:i]
        if not key or key not in _LIBPQ_CONNINFO_KEYWORDS:
            raise ValueError()
        while i < n and text[i].isspace():
            i += 1
        if i >= n or text[i] != '=':
            raise ValueError()
        i += 1
        while i < n and text[i].isspace():
            i += 1
        if i < n and text[i] == "'":
            i += 1
            buf = []
            closed = False
            while i < n:
                ch = text[i]
                if ch == '\\':
                    i += 1
                    if i >= n:
                        raise ValueError()
                    buf.append(text[i])
                    i += 1
                elif ch == "'":
                    closed = True
                    i += 1
                    break
                else:
                    buf.append(ch)
                    i += 1
            if not closed or (i < n and not text[i].isspace()):
                raise ValueError()
            options[key] = ''.join(buf)
        else:
            buf = []
            while i < n and not text[i].isspace():
                ch = text[i]
                if ch == "'":
                    raise ValueError()
                if ch == '\\':
                    i += 1
                    if i >= n:
                        raise ValueError()
                    buf.append(text[i])
                    i += 1
                else:
                    buf.append(ch)
                    i += 1
            options[key] = ''.join(buf)
    if 'port' in options and options['port']:
        for part in options['port'].split(','):
            if not (1 <= int(part) <= 65535):
                raise ValueError()
    return options


def validate_dsn(dsn):
    if not isinstance(dsn, str) or not dsn.strip():
        raise ValueError('PostgreSQL requires RETAILOPS_DATABASE_URL or RETAILOPS_DATABASE_URL_FILE.')
    try:
        options = _parse_dsn_options(dsn)
        if not options.get('dbname') or not options.get('user'):
            raise ValueError()
        try:
            import psycopg
        except ImportError:
            psycopg = None
        if psycopg is not None:
            pg_options = psycopg.conninfo.conninfo_to_dict(dsn)
            if not pg_options.get('dbname') or not pg_options.get('user'):
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
def transaction(dsn, schema=IDENTITY_SCHEMA, *, write=False, read_only=False):
    valid_schema(schema)
    if write and read_only:
        raise ValueError('A PostgreSQL transaction cannot be both read-only and writable.')
    pg = driver()
    from psycopg import sql
    from psycopg.rows import dict_row
    try:
        with pg.connect(dsn, connect_timeout=5, row_factory=dict_row) as connection:
            if read_only:
                connection.execute('SET TRANSACTION READ ONLY')
            connection.execute("SET LOCAL statement_timeout='15s'")
            connection.execute("SET LOCAL lock_timeout='5s'")
            connection.execute(sql.SQL('SET LOCAL search_path TO {}, pg_catalog').format(sql.Identifier(schema)))
            if write:
                connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (schema,))
            yield Queries(connection)
    except pg.Error as exc:
        if getattr(exc, 'sqlstate', None) == '25006':
            raise ApiError(409, 'read_only_store', 'Kho dữ liệu PostgreSQL đang ở chế độ chỉ đọc.') from None
        raise ApiError(
            503,
            'database_unavailable',
            f'Kho dữ liệu chưa sẵn sàng ({exc.__class__.__name__}). Vui lòng thử lại hoặc liên hệ quản trị viên.',
        ) from None


def assert_schema(db, schema, component):
    from psycopg import sql
    exists = db.raw.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s', (schema,)).fetchone()
    if not exists:
        raise ValueError('PostgreSQL schema is missing. Run the explicit database initialization/import command.')
    rows = db.raw.execute(sql.SQL('SELECT component,version FROM {}.retailops_schema').format(sql.Identifier(schema))).fetchall()
    if len(rows) != 1 or rows[0].get('component') != component:
        raise ValueError('Unsupported PostgreSQL schema version or component.')
    version = rows[0].get('version')
    supported = IDENTITY_SCHEMA_COMPATIBLE if component == 'identity' else BUSINESS_SCHEMA_COMPATIBLE
    if version not in supported:
        raise ValueError('Unsupported PostgreSQL schema version or component.')


def check_schema(dsn, schema, component, *, read_only=False):
    with transaction(dsn, schema, read_only=read_only) as db:
        assert_schema(db, schema, component)
