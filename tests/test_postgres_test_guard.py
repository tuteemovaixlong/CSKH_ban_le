import os
import unittest
from unittest.mock import patch

from scripts.postgres_test_guard import (
    LIBPQ_CONNECTION_OVERRIDE_ENV,
    require_disposable_postgres_test_target,
)


class PostgresTestGuardTests(unittest.TestCase):
    def clean_env(self, **extra):
        env = {"RETAILOPS_ALLOW_DESTRUCTIVE_TEST_DATABASE": "1"}
        env.update(extra)
        return env

    def check(self, options, environ=None):
        return require_disposable_postgres_test_target(
            "redacted", lambda _dsn: options, environ=environ
        )

    def test_accepts_explicit_loopback_ci_database(self):
        self.assertEqual(
            self.check(
                {"dbname": "retailops_test", "host": "127.0.0.1"},
                environ=self.clean_env(),
            ),
            {"dbname": "retailops_test", "host": "127.0.0.1"},
        )

    def test_requires_explicit_destructive_database_opt_in(self):
        with self.assertRaisesRegex(RuntimeError, "explicit disposable-database opt-in"):
            self.check(
                {"dbname": "retailops_test", "host": "127.0.0.1"},
                environ={},
            )

    def test_rejects_prefix_similar_database(self):
        with self.assertRaisesRegex(RuntimeError, "exact database name"):
            self.check(
                {"dbname": "retailops_test_prod", "host": "127.0.0.1"},
                environ=self.clean_env(),
            )

    def test_rejects_non_loopback_and_conninfo_redirects(self):
        with self.assertRaisesRegex(RuntimeError, "loopback host"):
            self.check(
                {"dbname": "retailops_test", "host": "db.example.com"},
                environ=self.clean_env(),
            )
        for key in ("hostaddr", "service"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(RuntimeError, "hostaddr/service overrides"):
                    self.check(
                        {"dbname": "retailops_test", "host": "127.0.0.1", key: "redirect"},
                        environ=self.clean_env(),
                    )

    def test_rejects_ambient_libpq_connection_overrides_without_echoing_values(self):
        for key in LIBPQ_CONNECTION_OVERRIDE_ENV:
            secret_value = "must-not-appear-in-errors"
            with self.subTest(key=key):
                with self.assertRaisesRegex(RuntimeError, key) as caught:
                    self.check(
                        {"dbname": "retailops_test", "host": "127.0.0.1"},
                        environ=self.clean_env(**{key: secret_value}),
                    )
                self.assertNotIn(secret_value, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
