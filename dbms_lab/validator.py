"""
Validation of SQL typed into the DBMS Lab editor.

Layer 1 of 3 (defence in depth):
  1. THIS MODULE parses the text with PostgreSQL's own parser (libpg_query via
     pglast) and walks the whole syntax tree. Only a single SELECT (optionally
     wrapped in EXPLAIN) is accepted; data-modifying CTEs, SELECT INTO, row
     locks and dangerous functions are rejected anywhere in the tree.
  2. The query runs as a role that only has SELECT privileges (dbms_lab/roles.py).
  3. The transaction is READ ONLY with a statement_timeout, and is always rolled back.
"""
from pglast import ast, parse_sql
from pglast.parser import ParseError

MAX_SQL_LENGTH = 10_000

# Functions that could sleep, touch files, signal backends, change settings,
# execute dynamic SQL strings or produce side effects.
BLOCKED_FUNCTION_PREFIXES = (
    "pg_sleep", "pg_read_", "pg_ls_", "pg_stat_file", "lo_", "dblink", "pg_terminate_backend",
    "pg_cancel_backend", "pg_reload_conf", "pg_rotate_logfile", "pg_advisory", "pg_try_advisory",
    "pg_notify", "pg_create_", "pg_drop_", "pg_logical_", "pg_replication_", "pg_switch_wal",
    "pg_backup_", "pg_promote", "pg_file_", "set_config", "nextval", "setval", "currval", "lastval",
    "query_to_xml", "table_to_xml", "cursor_to_xml", "schema_to_xml", "database_to_xml",
    "query_to_xmlschema", "txid_current", "pg_current_xact_id", "pg_import_system_collations",
)

WRITE_NODES = (ast.InsertStmt, ast.UpdateStmt, ast.DeleteStmt, ast.MergeStmt)


class SQLRejected(ValueError):
    """The submitted SQL is not allowed in the read-only editor."""


def _walk(obj):
    if isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _walk(item)
    elif isinstance(obj, ast.Node):
        yield obj
        for attr in obj:
            yield from _walk(getattr(obj, attr))


def _function_name(node: ast.FuncCall) -> str:
    return ".".join(part.sval for part in node.funcname if isinstance(part, ast.String)).lower()


def validate_readonly_sql(text: str) -> dict:
    """Return {'sql': cleaned_sql, 'explain': bool, 'analyze': bool} or raise SQLRejected."""
    if not text or not text.strip():
        raise SQLRejected("Please enter a query.")
    if len(text) > MAX_SQL_LENGTH:
        raise SQLRejected(f"Query is too long (max {MAX_SQL_LENGTH} characters).")
    try:
        statements = parse_sql(text)
    except ParseError as exc:
        raise SQLRejected(f"Syntax error: {exc}") from None

    if len(statements) != 1:
        raise SQLRejected("Exactly one SQL statement is allowed per submission (found %d)." % len(statements))

    root = statements[0].stmt
    explain = analyze = False
    if isinstance(root, ast.ExplainStmt):
        explain = True
        analyze = any(opt.defname == "analyze" for opt in (root.options or ()))
        target = root.query
    else:
        target = root

    if not isinstance(target, ast.SelectStmt):
        kind = type(target).__name__.replace("Stmt", "").upper()
        raise SQLRejected(f"Only SELECT queries are allowed in the editor ({kind} statement rejected). "
                          "Write operations are demonstrated in the rolled-back sandbox examples.")

    for node in _walk(target):
        if isinstance(node, WRITE_NODES):
            raise SQLRejected("Data-modifying statements (e.g. inside a WITH clause) are not allowed.")
        if isinstance(node, ast.SelectStmt):
            if node.intoClause is not None:
                raise SQLRejected("SELECT ... INTO creates a table and is not allowed.")
            if node.lockingClause:
                raise SQLRejected("Row-locking clauses (FOR UPDATE / FOR SHARE) are not allowed.")
        if isinstance(node, ast.FuncCall):
            name = _function_name(node)
            short = name.rsplit(".", 1)[-1]
            if short.startswith(BLOCKED_FUNCTION_PREFIXES):
                raise SQLRejected(f"Function '{name}' is not allowed in the lab editor.")
        if type(node).__name__.endswith("Stmt") and not isinstance(node, ast.SelectStmt):
            raise SQLRejected(f"{type(node).__name__} is not allowed inside a query.")

    return {"sql": text.strip().rstrip(";").strip(), "explain": explain, "analyze": analyze}
