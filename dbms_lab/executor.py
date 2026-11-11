"""
Query execution for the DBMS Lab.

* run_readonly(): opens a NEW connection as the SELECT-only role, starts a
  READ ONLY transaction with a statement_timeout, runs the query through a
  server-side cursor (so at most max_rows+1 rows ever leave the server), then
  ROLLS BACK. User-typed SQL is only ever executed through this function.

* run_sandbox(): runs a fixed, catalogue-defined list of write statements on the
  application connection inside one transaction that is ALWAYS rolled back. The
  SQL comes from dbms_lab/catalogue.py and cannot be edited by the browser.
"""
import re
import time
from dataclasses import dataclass, field

import psycopg
from django.conf import settings
from django.db import connections
from psycopg import sql as psql


@dataclass
class QueryResult:
    sql: str
    ok: bool = True
    columns: list = field(default_factory=list)   # [{"name":..., "type":...}]
    rows: list = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    duration_ms: float = 0.0
    error: str = ""
    error_code: str = ""
    status: str = ""          # command tag, e.g. "INSERT 0 1"
    note: str = ""
    expect_error: bool = False
    plan_lines: list = field(default_factory=list)
    plan_nodes: list = field(default_factory=list)

    @property
    def is_plan(self):
        return bool(self.plan_lines)


def _conn_kwargs(user, password):
    db = connections["default"].settings_dict  # NAME is the test DB during tests
    kwargs = {"dbname": db["NAME"], "user": user, "host": db.get("HOST") or None,
              "port": db.get("PORT") or None, "connect_timeout": 5,
              "application_name": "dbms_lab"}
    if password:
        kwargs["password"] = password
    return kwargs


def _readonly_connection():
    return psycopg.connect(**_conn_kwargs(settings.READONLY_DB_USER, settings.READONLY_DB_PASSWORD),
                           autocommit=False)


def _owner_connection():
    db = connections["default"].settings_dict
    return psycopg.connect(**_conn_kwargs(db["USER"], db.get("PASSWORD")), autocommit=False)


def _clean_error(exc):
    diag = getattr(exc, "diag", None)
    msg = (getattr(diag, "message_primary", None) or str(exc)).strip()
    detail = getattr(diag, "message_detail", None)
    hint = getattr(diag, "message_hint", None)
    constraint = getattr(diag, "constraint_name", None)
    parts = [msg]
    if detail:
        parts.append(f"DETAIL: {detail}")
    if constraint:
        parts.append(f"CONSTRAINT: {constraint}")
    if hint:
        parts.append(f"HINT: {hint}")
    return "\n".join(parts), getattr(diag, "sqlstate", "") or ""


def _type_names(cur, description):
    oids = sorted({d.type_code for d in description})
    names = {}
    for oid in oids:
        info = cur.connection.adapters.types.get(oid)
        if info:
            names[oid] = info.name
    missing = [o for o in oids if o not in names]
    if missing:
        cur.execute("SELECT oid::int, format_type(oid, NULL) FROM pg_type WHERE oid = ANY(%s)", [missing])
        names.update(dict(cur.fetchall()))
    return [{"name": d.name, "type": names.get(d.type_code, str(d.type_code))} for d in description]


PLAN_NODE_RE = re.compile(
    r"(Seq Scan|Parallel Seq Scan|Index Only Scan|Index Scan|Bitmap Heap Scan|Bitmap Index Scan|"
    r"Nested Loop|Hash Join|Merge Join|Hash|Sort|Incremental Sort|HashAggregate|GroupAggregate|Aggregate|"
    r"Limit|Unique|WindowAgg|Subquery Scan|CTE Scan|Materialize|Memoize|Append|Result|Gather)")


def _plan_payload(result, lines):
    result.plan_lines = lines
    nodes = []
    for line in lines:
        m = PLAN_NODE_RE.search(line.split("(")[0])
        if m and m.group(1) not in nodes:
            nodes.append(m.group(1))
    result.plan_nodes = nodes


def run_readonly(query, params=None, max_rows=None, local_settings=None, is_explain=None):
    """Run one read-only statement. `query` is a str or psycopg.sql.Composed (trusted internal SQL)."""
    max_rows = max_rows or settings.LAB_MAX_ROWS
    text = query if isinstance(query, str) else None
    result = QueryResult(sql=text or "")
    try:
        conn = _readonly_connection()
    except psycopg.OperationalError as exc:
        result.ok = False
        result.error = ("Could not connect as the read-only role "
                        f"'{settings.READONLY_DB_USER}'. Run: python manage.py setup_readonly_role\n"
                        f"({_clean_error(exc)[0].splitlines()[0]})")
        return result
    try:
        with conn:
            with conn.cursor() as cur:
                if not result.sql:
                    result.sql = query.as_string(conn)
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute("SELECT set_config('statement_timeout', %s, true)",
                            [f"{settings.LAB_STATEMENT_TIMEOUT_MS}ms"])
                for name, value in (local_settings or {}).items():
                    cur.execute("SELECT set_config(%s, %s, true)", [name, value])
                if is_explain is None:
                    is_explain = result.sql.lstrip().lower().startswith("explain")
                started = time.perf_counter()
                if is_explain:
                    cur.execute(query, params)
                    lines = [r[0] for r in cur.fetchall()]
                    result.duration_ms = (time.perf_counter() - started) * 1000
                    result.columns = [{"name": "QUERY PLAN", "type": "text"}]
                    result.rows = [[line] for line in lines]
                    result.row_count = len(lines)
                    _plan_payload(result, lines)
                else:
                    # Server-side cursor: rows are streamed, never all loaded into memory.
                    with conn.cursor(name="lab_cursor") as scur:
                        scur.execute(query, params)
                        rows = scur.fetchmany(max_rows + 1)
                        result.duration_ms = (time.perf_counter() - started) * 1000
                        description = scur.description
                    result.truncated = len(rows) > max_rows
                    result.rows = [list(r) for r in rows[:max_rows]]
                    result.row_count = len(result.rows)
                    if description:
                        result.columns = _type_names(cur, description)
                conn.rollback()  # nothing to keep: always roll back
    except psycopg.Error as exc:
        result.ok = False
        result.error, result.error_code = _clean_error(exc)
    finally:
        conn.close()
    return result


def explain(sql_text, analyze=False):
    opts = "ANALYZE, BUFFERS, " if analyze else ""
    return run_readonly(f"EXPLAIN ({opts}COSTS, VERBOSE OFF, FORMAT TEXT) {sql_text}", is_explain=True)


# ----------------------------------------------------------------------------- sandbox
def run_sandbox(steps, verify_sql=None):
    """Execute catalogue-defined steps in ONE transaction, then ROLLBACK.

    Each step: {"sql": str, "note": str, "expect_error": bool}. A step that is
    expected to fail is wrapped in a SAVEPOINT so the transaction can continue.
    """
    results, verify = [], None
    conn = _owner_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('statement_timeout', '5s', true), set_config('lock_timeout', '2s', true)")
            for i, step in enumerate(steps):
                res = QueryResult(sql=step["sql"].strip(), note=step.get("note", ""),
                                  expect_error=step.get("expect_error", False))
                sp = psql.Identifier(f"lab_step_{i}")
                if res.expect_error:
                    cur.execute(psql.SQL("SAVEPOINT {}").format(sp))
                started = time.perf_counter()
                try:
                    cur.execute(res.sql)
                    res.duration_ms = (time.perf_counter() - started) * 1000
                    res.status = cur.statusmessage or ""
                    if cur.description:
                        rows = cur.fetchmany(settings.LAB_MAX_ROWS + 1)
                        res.truncated = len(rows) > settings.LAB_MAX_ROWS
                        res.rows = [list(r) for r in rows[:settings.LAB_MAX_ROWS]]
                        res.columns = _type_names(cur, cur.description)
                    res.row_count = len(res.rows) if cur.description else max(cur.rowcount, 0)
                    if res.expect_error:
                        cur.execute(psql.SQL("RELEASE SAVEPOINT {}").format(sp))
                except psycopg.Error as exc:
                    res.ok = False
                    res.duration_ms = (time.perf_counter() - started) * 1000
                    res.error, res.error_code = _clean_error(exc)
                    if res.expect_error:
                        cur.execute(psql.SQL("ROLLBACK TO SAVEPOINT {}").format(sp))
                        res.note = (res.note + " " if res.note else "") + "(rolled back to savepoint)"
                    else:
                        results.append(res)
                        break  # transaction is now aborted; stop executing
                results.append(res)
    finally:
        conn.rollback()  # <-- the whole sandbox is ALWAYS undone
        conn.close()
    if verify_sql:
        verify = run_readonly(verify_sql)
    return results, verify
