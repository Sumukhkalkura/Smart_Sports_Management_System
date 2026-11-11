"""
Schema metadata read live from PostgreSQL's information_schema and pg_catalog.
All SQL here is fixed text with bound parameters; table names are checked against
APP_RELATIONS before use.
"""
from django.db import connection
from psycopg import sql as psql

from .executor import run_readonly

APP_TABLES = ["users", "facilities", "sports", "courts", "bookings", "payments", "reviews", "maintenance"]
APP_VIEWS = ["v_booking_details", "v_facility_revenue"]
APP_RELATIONS = APP_TABLES + APP_VIEWS

ER_NOTES = {
    "users": "Entity USER. Strong entity, PK user_id. Passwords are stored only as salted hashes.",
    "facilities": "Entity FACILITY. Strong entity, PK facility_id.",
    "sports": "Entity SPORT. Strong entity, PK sport_id.",
    "courts": "Entity COURT. FK facility_id (FACILITY contains COURT, 1:N) and FK sport_id (COURT played_on SPORT, N:1).",
    "bookings": "Entity BOOKING. FK user_id (USER places BOOKING, 1:N) and FK court_id (BOOKING booked_for COURT, N:1).",
    "payments": "Weak entity PAYMENT, identified by BOOKING via settled_by (1:1). PK = FK = booking_id.",
    "reviews": "Weak entity REVIEW, identified by BOOKING via reviewed_via (1:1). PK = FK = booking_id.",
    "maintenance": "Weak entity MAINTENANCE, owned by COURT via undergoes (1:N). Composite PK (court_id, start_time).",
    "v_booking_details": "View: one row per booking joined with user, court, facility, sport, payment and review.",
    "v_facility_revenue": "View: per-facility booking counts, collected/pending/refunded money and average rating.",
}


def _fetch(query, params=None):
    with connection.cursor() as cur:
        cur.execute(query, params or [])
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def database_overview():
    info = _fetch("""
        SELECT current_database() AS database, version() AS version,
               pg_size_pretty(pg_database_size(current_database())) AS size,
               current_setting('server_encoding') AS encoding,
               current_setting('TimeZone') AS timezone,
               current_setting('default_transaction_isolation') AS isolation
    """)[0]
    return info


def relation_summaries():
    rows = _fetch("""
        SELECT c.relname AS name,
               CASE c.relkind WHEN 'r' THEN 'table' WHEN 'v' THEN 'view' END AS kind,
               (SELECT COUNT(*) FROM information_schema.columns ic
                 WHERE ic.table_schema = 'public' AND ic.table_name = c.relname) AS columns,
               pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
               (SELECT COUNT(*) FROM pg_index i WHERE i.indrelid = c.oid) AS indexes,
               (SELECT COUNT(*) FROM pg_constraint k WHERE k.conrelid = c.oid) AS constraints
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = ANY(%s)
        ORDER BY array_position(%s, c.relname::text)
    """, [APP_RELATIONS, APP_RELATIONS])
    with connection.cursor() as cur:
        for r in rows:
            cur.execute(psql.SQL("SELECT COUNT(*) FROM {}").format(psql.Identifier(r["name"])))
            r["row_count"] = cur.fetchone()[0]
            r["note"] = ER_NOTES.get(r["name"], "")
    return rows


def columns(table):
    return _fetch("""
        SELECT c.ordinal_position AS position, c.column_name, c.data_type,
               CASE WHEN c.character_maximum_length IS NOT NULL
                    THEN c.data_type || '(' || c.character_maximum_length || ')'
                    WHEN c.data_type = 'numeric'
                    THEN 'numeric(' || c.numeric_precision || ',' || c.numeric_scale || ')'
                    ELSE c.data_type END AS full_type,
               c.is_nullable = 'YES' AS nullable,
               c.column_default, c.is_identity = 'YES' AS identity,
               EXISTS (SELECT 1 FROM information_schema.key_column_usage k
                       JOIN information_schema.table_constraints t
                         ON t.constraint_name = k.constraint_name AND t.table_name = k.table_name
                       WHERE t.constraint_type = 'PRIMARY KEY' AND k.table_name = c.table_name
                         AND k.column_name = c.column_name) AS is_pk,
               EXISTS (SELECT 1 FROM information_schema.key_column_usage k
                       JOIN information_schema.table_constraints t
                         ON t.constraint_name = k.constraint_name AND t.table_name = k.table_name
                       WHERE t.constraint_type = 'FOREIGN KEY' AND k.table_name = c.table_name
                         AND k.column_name = c.column_name) AS is_fk
        FROM information_schema.columns c
        WHERE c.table_schema = 'public' AND c.table_name = %s
        ORDER BY c.ordinal_position
    """, [table])


CONSTRAINT_TYPES = {"p": "PRIMARY KEY", "f": "FOREIGN KEY", "u": "UNIQUE", "c": "CHECK", "x": "EXCLUSION"}


def constraints(table):
    rows = _fetch("""
        SELECT k.conname AS name, k.contype AS code, pg_get_constraintdef(k.oid, true) AS definition,
               k.condeferrable AS deferrable, k.condeferred AS deferred
        FROM pg_constraint k
        WHERE k.conrelid = %s::regclass
        ORDER BY array_position(ARRAY['p','f','u','x','c']::"char"[], k.contype), k.conname
    """, [table])
    for r in rows:
        r["type"] = CONSTRAINT_TYPES.get(r["code"], r["code"])
    return rows


def foreign_keys():
    """Every FK in the application schema: the edges of the relational model."""
    return _fetch("""
        SELECT src.relname AS from_table,
               string_agg(sa.attname, ', ' ORDER BY u.ord) AS from_columns,
               dst.relname AS to_table,
               string_agg(da.attname, ', ' ORDER BY u.ord) AS to_columns,
               CASE k.confdeltype WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT' WHEN 'c' THEN 'CASCADE'
                                  WHEN 'n' THEN 'SET NULL' WHEN 'd' THEN 'SET DEFAULT' END AS on_delete,
               k.conname AS name
        FROM pg_constraint k
        JOIN pg_class src ON src.oid = k.conrelid
        JOIN pg_class dst ON dst.oid = k.confrelid
        CROSS JOIN LATERAL unnest(k.conkey, k.confkey) WITH ORDINALITY AS u(src_att, dst_att, ord)
        JOIN pg_attribute sa ON sa.attrelid = k.conrelid  AND sa.attnum = u.src_att
        JOIN pg_attribute da ON da.attrelid = k.confrelid AND da.attnum = u.dst_att
        WHERE k.contype = 'f' AND src.relname = ANY(%s)
        GROUP BY src.relname, dst.relname, k.confdeltype, k.conname
        ORDER BY src.relname, k.conname
    """, [APP_TABLES])


def referenced_by(table):
    return [fk for fk in foreign_keys() if fk["to_table"] == table]


def indexes(table):
    return _fetch("""
        SELECT i.indexname AS name, i.indexdef AS definition,
               pg_size_pretty(pg_relation_size(format('%%I', i.indexname)::regclass)) AS size,
               COALESCE(s.idx_scan, 0) AS scans
        FROM pg_indexes i
        LEFT JOIN pg_stat_user_indexes s ON s.indexrelname = i.indexname
        WHERE i.schemaname = 'public' AND i.tablename = %s
        ORDER BY i.indexname
    """, [table])


def triggers(table):
    return _fetch("""
        SELECT t.tgname AS name, pg_get_triggerdef(t.oid, true) AS definition,
               p.proname AS function, pg_get_functiondef(p.oid) AS function_source
        FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
        WHERE t.tgrelid = %s::regclass AND NOT t.tgisinternal
        ORDER BY t.tgname
    """, [table])


def view_definition(view):
    rows = _fetch("SELECT pg_get_viewdef(%s::regclass, true) AS d", [view])
    return rows[0]["d"] if rows else ""


def browse(table, page=1, page_size=25):
    """Read rows through the SELECT-only role, using only the columns that role may read."""
    if table not in APP_RELATIONS:
        raise ValueError("Unknown table")
    readable = run_readonly(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s "
        "AND has_column_privilege(current_user, format('%%I', table_name), column_name, 'SELECT') "
        "ORDER BY ordinal_position", [table], max_rows=200)
    if not readable.ok:
        return readable, 0, []
    cols = [r[0] for r in readable.rows]
    hidden = [c["column_name"] for c in columns(table) if c["column_name"] not in cols]
    pk_cols = [c["column_name"] for c in columns(table) if c["is_pk"]] or cols[:1]
    count = run_readonly(psql.SQL("SELECT COUNT(*) FROM {}").format(psql.Identifier(table)))
    total = count.rows[0][0] if count.ok else 0
    query = psql.SQL("SELECT {cols} FROM {table} ORDER BY {order} LIMIT %s OFFSET %s").format(
        cols=psql.SQL(", ").join(psql.Identifier(c) for c in cols),
        table=psql.Identifier(table),
        order=psql.SQL(", ").join(psql.Identifier(c) for c in pk_cols if c in cols) or psql.SQL("1"),
    )
    result = run_readonly(query, [page_size, (page - 1) * page_size], max_rows=page_size)
    return result, total, hidden
