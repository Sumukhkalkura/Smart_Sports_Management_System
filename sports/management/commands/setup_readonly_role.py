from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from dbms_lab.roles import READABLE_RELATIONS, USERS_READABLE_COLUMNS, ensure_readonly_role


class Command(BaseCommand):
    help = "Create/refresh the SELECT-only PostgreSQL role used by the DBMS Lab query editor."

    def handle(self, *args, **options):
        role = ensure_readonly_role(connection)
        self.stdout.write(self.style.SUCCESS(
            f"Role '{role}' ready on database '{settings.DATABASES['default']['NAME']}'."))
        self.stdout.write(f"  SELECT on: {', '.join(READABLE_RELATIONS)}")
        self.stdout.write(f"  SELECT on users({', '.join(USERS_READABLE_COLUMNS)})  -- no password_hash")
        self.stdout.write(f"  default_transaction_read_only=on, statement_timeout={settings.LAB_STATEMENT_TIMEOUT_MS}ms")
