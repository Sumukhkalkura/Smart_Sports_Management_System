"""Test runner: PostgreSQL test database + the SELECT-only lab role granted inside it."""
from django.conf import settings
from django.db import connection
from django.test.runner import DiscoverRunner


class PostgresTestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        # PBKDF2 is intentionally slow; tests don't need that.
        settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

    def setup_databases(self, **kwargs):
        old_config = super().setup_databases(**kwargs)
        from dbms_lab.roles import ensure_readonly_role

        ensure_readonly_role(connection)
        return old_config
