"""Fail-closed target checks shared by destructive PostgreSQL test setup."""
import os


DISPOSABLE_TEST_DB_NAME = "retailops_test"
DISPOSABLE_TEST_DB_USER = "retailops_test"
DISPOSABLE_TEST_DB_HOST = "127.0.0.1"
DISPOSABLE_TEST_DB_PORT = "5432"
ALLOWED_DISPOSABLE_CONNINFO_KEYS = frozenset(
    {"dbname", "user", "password", "host", "port"}
)

# libpq reads these variables when corresponding connection parameters are absent.
# Reject them for destructive tests so an ambient shell/runner configuration cannot
# redirect a DSN that otherwise appears to target the disposable loopback database.
LIBPQ_CONNECTION_OVERRIDE_ENV = (
    "PGHOST",
    "PGHOSTADDR",
    "PGPORT",
    "PGDATABASE",
    "PGUSER",
    "PGPASSWORD",
    "PGPASSFILE",
    "PGSERVICE",
    "PGSERVICEFILE",
    "PGSYSCONFDIR",
)


def require_disposable_postgres_test_target(dsn, conninfo_to_dict, environ=None):
    """Allow destructive setup only for the explicitly configured loopback CI DB endpoint."""
    env = os.environ if environ is None else environ
    if env.get("RETAILOPS_ALLOW_DESTRUCTIVE_TEST_DATABASE") != "1":
        raise RuntimeError("Destructive PostgreSQL tests require explicit disposable-database opt-in.")

    overrides = [name for name in LIBPQ_CONNECTION_OVERRIDE_ENV if env.get(name)]
    if overrides:
        raise RuntimeError(
            "Destructive PostgreSQL tests reject libpq connection environment overrides: "
            + ", ".join(overrides)
        )

    if not isinstance(dsn, str) or not dsn.strip():
        raise RuntimeError("Destructive PostgreSQL tests require a valid connection string.")

    try:
        options = conninfo_to_dict(dsn)
    except Exception:
        raise RuntimeError(
            "Destructive PostgreSQL tests require a valid connection string."
        ) from None

    if not isinstance(options, dict):
        raise RuntimeError("Destructive PostgreSQL tests require a valid connection string.")

    if options.get("dbname") != DISPOSABLE_TEST_DB_NAME:
        raise RuntimeError("Destructive PostgreSQL tests require the exact database name retailops_test.")

    if options.get("user") != DISPOSABLE_TEST_DB_USER:
        raise RuntimeError("Destructive PostgreSQL tests require the exact database user retailops_test.")

    if options.get("host") != DISPOSABLE_TEST_DB_HOST:
        raise RuntimeError("Destructive PostgreSQL tests require the exact workflow loopback host 127.0.0.1.")

    if options.get("port") != DISPOSABLE_TEST_DB_PORT:
        raise RuntimeError("Destructive PostgreSQL tests require the explicit disposable database port 5432.")

    # Explicit libpq routing/profile/credential overrides defeat the checked endpoint,
    # so allow only the connection keys present on the workflow disposable DSN.
    if "hostaddr" in options or "service" in options:
        raise RuntimeError("Destructive PostgreSQL tests reject hostaddr/service overrides.")

    unexpected_keys = sorted(set(options) - ALLOWED_DISPOSABLE_CONNINFO_KEYS)
    if unexpected_keys:
        raise RuntimeError(
            "Destructive PostgreSQL tests reject unexpected conninfo parameters: "
            + ", ".join(unexpected_keys)
        )

    return options
