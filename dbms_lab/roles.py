"""
Creation of the SELECT-only PostgreSQL role used by the DBMS Lab.

The lab never runs user-typed SQL on the application's (schema-owner) connection.
It opens a separate connection as this role, which:
  * can only SELECT from the application tables and views listed below,
  * cannot see users.password_hash (column-level privilege),
  * has default_transaction_read_only = on and a statement_timeout.
"""
from django.conf import settings
from psycopg import sql

# Tables/views the lab may read in full.
READABLE_RELATIONS = [
    "facilities", "sports", "courts", "bookings", "payments", "reviews", "maintenance",
    "v_booking_details", "v_facility_revenue",
]
# users is readable column-by-column: password_hash and last_login are excluded.
USERS_READABLE_COLUMNS = ["user_id", "name", "email", "role", "created_at", "is_active"]


def ensure_readonly_role(connection, password=None):
    """Create/refresh the role and grant privileges in the connection's current database.

    `connection` is a Django DatabaseWrapper whose user may create roles (dev setup).
    """
    role = settings.READONLY_DB_USER
    password = password if password is not None else settings.READONLY_DB_PASSWORD
    if not password:
        raise RuntimeError("DB_READONLY_PASSWORD is empty; set it in .env first.")

    with connection.cursor() as cur:
        raw = cur.connection  # psycopg connection, needed for sql.Composed rendering
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
        verb = "ALTER" if cur.fetchone() else "CREATE"
        cur.execute(
            sql.SQL("{} ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
                    "CONNECTION LIMIT 20 PASSWORD {}")
            .format(sql.SQL(verb), sql.Identifier(role), sql.Literal(password)).as_string(raw)
        )
        ident = sql.Identifier(role)
        statements = [
            sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(ident),
            sql.SQL("ALTER ROLE {} SET statement_timeout = {}").format(
                ident, sql.Literal(f"{settings.LAB_STATEMENT_TIMEOUT_MS}ms")),
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(connection.settings_dict["NAME"]), ident),
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(ident),
            # Start from a clean slate inside this database, then grant precisely.
            sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(ident),
            sql.SQL("GRANT SELECT ON {} TO {}").format(
                sql.SQL(", ").join(sql.Identifier(t) for t in READABLE_RELATIONS), ident),
            sql.SQL("GRANT SELECT ({}) ON users TO {}").format(
                sql.SQL(", ").join(sql.Identifier(c) for c in USERS_READABLE_COLUMNS), ident),
        ]
        for stmt in statements:
            cur.execute(stmt.as_string(raw))
    return role
