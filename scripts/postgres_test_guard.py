"""Fail-closed target checks shared by destructive PostgreSQL test setup."""
import os


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
    """Allow destructive setup only for an explicitly opted-in loopback CI DB."""
    env = os.environ if environ is None else environ
    if env.get("RETAILOPS_ALLOW_DESTRUCTIVE_TEST_DATABASE") != "1":
        raise RuntimeError("Destructive PostgreSQL tests require explicit disposable-database opt-in.")

    overrides = [name for name in LIBPQ_CONNECTION_OVERRIDE_ENV if env.get(name)]
    if overrides:
        raise RuntimeError(
            "Destructive PostgreSQL tests reject libpq connection environment overrides: "
            + ", ".join(overrides)
        )

    options = conninfo_to_dict(dsn)
    if options.get("dbname") != "retailops_test":
        raise RuntimeError("Destructive PostgreSQL tests require the exact database name retailops_test.")

    if options.get("host") not in {"127.0.0.1", "::1"}:
        raise RuntimeError("Destructive PostgreSQL tests require an explicit loopback host.")

    # Explicit libpq routing overrides defeat the checked host or load another
    # connection profile, so reject them even when a loopback host is present.
    if "hostaddr" in options or "service" in options:
        raise RuntimeError("Destructive PostgreSQL tests reject hostaddr/service overrides.")

    return options
