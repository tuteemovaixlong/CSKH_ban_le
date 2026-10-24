import unittest

from scripts.postgres_test_guard import (
    LIBPQ_CONNECTION_OVERRIDE_ENV,
    require_disposable_postgres_test_target,
)


class PostgresTestGuardTests(unittest.TestCase):
    def clean_env(self, **extra):
        env = {"RETAILOPS_ALLOW_DESTRUCTIVE_TEST_DATABASE": "1"}
        env.update(extra)
        return env

    def valid_options(self, **overrides):
        options = {
            "dbname": "retailops_test",
            "user": "retailops_test",
            "host": "127.0.0.1",
            "port": "5432",
        }
        options.update(overrides)
        return options

    def check(self, options, environ=None):
        return require_disposable_postgres_test_target(
            "redacted", lambda _dsn: options, environ=environ
        )

    def test_accepts_explicit_workflow_disposable_ci_endpoint(self):
        for extra in ({}, {"password": "ci-only-disposable-password"}):
            with self.subTest(extra_keys=sorted(extra)):
                expected = self.valid_options(**extra)
                self.assertEqual(
                    self.check(expected, environ=self.clean_env()),
                    expected,
                )

    def test_requires_explicit_destructive_database_opt_in(self):
        for env in ({}, {"RETAILOPS_ALLOW_DESTRUCTIVE_TEST_DATABASE": "0"}, {"RETAILOPS_ALLOW_DESTRUCTIVE_TEST_DATABASE": "true"}):
            with self.subTest(env=env):
                with self.assertRaisesRegex(RuntimeError, "explicit disposable-database opt-in"):
                    self.check(self.valid_options(), environ=env)

    def test_rejects_prefix_similar_or_missing_database(self):
        for bad_db in ("retailops_test_prod", "retailops", ""):
            with self.subTest(dbname=bad_db):
                with self.assertRaisesRegex(RuntimeError, "exact database name"):
                    self.check(
                        self.valid_options(dbname=bad_db),
                        environ=self.clean_env(),
                    )
        opts_no_db = self.valid_options()
        opts_no_db.pop("dbname")
        with self.assertRaisesRegex(RuntimeError, "exact database name"):
            self.check(opts_no_db, environ=self.clean_env())

    def test_rejects_missing_or_unexpected_service_user(self):
        for bad_user in ("retailops", "postgres", ""):
            with self.subTest(user=bad_user):
                with self.assertRaisesRegex(RuntimeError, "exact database user"):
                    self.check(
                        self.valid_options(user=bad_user),
                        environ=self.clean_env(),
                    )
        opts_no_user = self.valid_options()
        opts_no_user.pop("user")
        with self.assertRaisesRegex(RuntimeError, "exact database user"):
            self.check(opts_no_user, environ=self.clean_env())

    def test_rejects_default_omitted_port(self):
        opts_omitted_port = self.valid_options()
        opts_omitted_port.pop("port")
        with self.assertRaisesRegex(RuntimeError, "explicit disposable database port 5432"):
            self.check(opts_omitted_port, environ=self.clean_env())

        for empty_port in ("", None):
            with self.subTest(port=empty_port):
                with self.assertRaisesRegex(RuntimeError, "explicit disposable database port 5432"):
                    self.check(
                        self.valid_options(port=empty_port),
                        environ=self.clean_env(),
                    )

    def test_rejects_wrong_port_and_port_forwards(self):
        for bad_port in ("15432", "5433", "6543", "5432,15432", "05432", " 5432 ", 5432):
            with self.subTest(port=bad_port):
                with self.assertRaisesRegex(RuntimeError, "explicit disposable database port 5432"):
                    self.check(
                        self.valid_options(port=bad_port),
                        environ=self.clean_env(),
                    )

        try:
            import psycopg
        except ImportError:
            psycopg = None
        if psycopg is not None:
            parse = psycopg.conninfo.conninfo_to_dict
            accepted = require_disposable_postgres_test_target(
                "postgresql://retailops_test:disposable@127.0.0.1:5432/retailops_test",
                parse,
                environ=self.clean_env(),
            )
            self.assertEqual(accepted.get("port"), "5432")
            for bad_dsn, expected_msg in (
                (
                    "postgresql://retailops_test:disposable@127.0.0.1/retailops_test",
                    "explicit disposable database port 5432",
                ),
                (
                    "postgresql://retailops_test:disposable@127.0.0.1:15432/retailops_test",
                    "explicit disposable database port 5432",
                ),
                (
                    "postgresql://retailops_test:disposable@[::1]:5432/retailops_test",
                    "exact workflow loopback host 127.0.0.1",
                ),
                (
                    "postgresql://retailops:disposable@127.0.0.1:5432/retailops_test",
                    "exact database user",
                ),
                (
                    "postgresql://retailops_test:disposable@127.0.0.1:5432/retailops_test?passfile=/tmp/pgpass",
                    "unexpected conninfo parameters: passfile",
                ),
            ):
                with self.subTest(real_conninfo=bad_dsn):
                    with self.assertRaisesRegex(RuntimeError, expected_msg):
                        require_disposable_postgres_test_target(
                            bad_dsn, parse, environ=self.clean_env()
                        )

    def test_rejects_non_workflow_hosts_and_conninfo_overrides(self):
        for bad_host in ("db.example.com", "localhost", "::1", "127.0.0.1,db.example.com", ""):
            with self.subTest(host=bad_host):
                with self.assertRaisesRegex(RuntimeError, "exact workflow loopback host 127.0.0.1"):
                    self.check(
                        self.valid_options(host=bad_host),
                        environ=self.clean_env(),
                    )
        for key in ("hostaddr", "service"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(RuntimeError, "hostaddr/service overrides"):
                    self.check(
                        self.valid_options(**{key: "redirect"}),
                        environ=self.clean_env(),
                    )
        secret_param_value = "must-not-echo-param-value"
        for key in ("passfile", "options", "target_session_attrs"):
            with self.subTest(unexpected_key=key):
                with self.assertRaisesRegex(RuntimeError, key) as caught:
                    self.check(
                        self.valid_options(**{key: secret_param_value}),
                        environ=self.clean_env(),
                    )
                self.assertNotIn(secret_param_value, str(caught.exception))

    def test_rejects_ambient_libpq_connection_overrides_without_echoing_values(self):
        for key in LIBPQ_CONNECTION_OVERRIDE_ENV:
            secret_value = "must-not-appear-in-errors"
            with self.subTest(key=key):
                with self.assertRaisesRegex(RuntimeError, key) as caught:
                    self.check(
                        self.valid_options(),
                        environ=self.clean_env(**{key: secret_value}),
                    )
                self.assertNotIn(secret_value, str(caught.exception))

    def test_redacts_conninfo_parser_failures(self):
        secret_canary = "canary-secret-dsn-fragment"

        def broken_parser(_dsn):
            raise ValueError(f"invalid conninfo containing {secret_canary}")

        with self.assertRaisesRegex(RuntimeError, "valid connection string") as caught:
            require_disposable_postgres_test_target(
                f"postgresql://retailops_test:{secret_canary}@127.0.0.1:5432/retailops_test",
                broken_parser,
                environ=self.clean_env(),
            )
        self.assertNotIn(secret_canary, str(caught.exception))

        for bad_dsn in ("", "   ", None):
            with self.subTest(bad_dsn=bad_dsn):
                with self.assertRaisesRegex(RuntimeError, "valid connection string"):
                    require_disposable_postgres_test_target(
                        bad_dsn,
                        lambda _dsn: self.valid_options(),
                        environ=self.clean_env(),
                    )
        with self.assertRaisesRegex(RuntimeError, "valid connection string"):
            require_disposable_postgres_test_target(
                "redacted",
                lambda _dsn: [],
                environ=self.clean_env(),
            )


if __name__ == "__main__":
    unittest.main()
