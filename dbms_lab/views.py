"""DBMS Demonstration Lab views. Administrators only (checked server-side)."""
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_POST

from sports.manage_views import admin_required

from . import catalogue, introspection
from .executor import explain, run_readonly, run_sandbox
from .validator import SQLRejected, validate_readonly_sql

INDEX_OFF = {"enable_indexscan": "off", "enable_bitmapscan": "off", "enable_indexonlyscan": "off"}


@admin_required
def lab_home(request):
    return render(request, "dbms_lab/home.html", {
        "db": introspection.database_overview(),
        "relations": introspection.relation_summaries(),
        "fks": introspection.foreign_keys(),
        "categories": catalogue.grouped(),
    })


@admin_required
def table_detail(request, table):
    if table not in introspection.APP_RELATIONS:
        raise Http404
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1
    page_size = 25
    result, total, hidden = introspection.browse(table, page, page_size)
    pages = max(1, -(-total // page_size))
    is_view = table in introspection.APP_VIEWS
    return render(request, "dbms_lab/table.html", {
        "table": table, "is_view": is_view, "note": introspection.ER_NOTES.get(table, ""),
        "columns": introspection.columns(table),
        "constraints": [] if is_view else introspection.constraints(table),
        "indexes": [] if is_view else introspection.indexes(table),
        "triggers": [] if is_view else introspection.triggers(table),
        "references": [fk for fk in introspection.foreign_keys() if fk["from_table"] == table],
        "referenced_by": introspection.referenced_by(table),
        "view_sql": introspection.view_definition(table) if is_view else "",
        "result": result, "total": total, "hidden": hidden,
        "page": page, "pages": pages, "has_prev": page > 1, "has_next": page < pages,
        "relations": introspection.APP_RELATIONS,
    })


@admin_required
def query_list(request):
    return render(request, "dbms_lab/queries.html", {"categories": catalogue.grouped()})


def _run_select(sql_text, mode="run"):
    """Validate, then run normally / EXPLAIN / EXPLAIN ANALYZE via the read-only role."""
    checked = validate_readonly_sql(sql_text)
    if checked["explain"]:
        return run_readonly(checked["sql"], is_explain=True)
    if mode == "explain":
        return explain(checked["sql"])
    if mode == "analyze":
        return explain(checked["sql"], analyze=True)
    return run_readonly(checked["sql"], is_explain=False)


@admin_required
def query_detail(request, slug):
    item = catalogue.BY_SLUG.get(slug)
    if not item:
        raise Http404
    ctx = {"item": item, "category": dict(catalogue.CATEGORIES)[item["category"]]}
    if item["kind"] == "select":
        mode = request.GET.get("mode", "run")
        ctx["mode"] = mode
        try:
            ctx["result"] = _run_select(item["sql"], mode)
        except SQLRejected as e:  # should never happen for catalogue SQL
            ctx["rejected"] = str(e)
    elif item["kind"] == "compare":
        ctx["plan_default"] = explain(item["sql"], analyze=True)
        sql = f"EXPLAIN (ANALYZE, BUFFERS, COSTS, FORMAT TEXT) {item['sql']}"
        ctx["plan_noindex"] = run_readonly(sql, local_settings=INDEX_OFF, is_explain=True)
        for key in ("plan_default", "plan_noindex"):
            res = ctx[key]
            res.exec_time = next((line.split(":", 1)[1].strip() for line in res.plan_lines
                                  if line.startswith("Execution Time")), "")
    return render(request, "dbms_lab/query_detail.html", ctx)


@admin_required
@require_POST
def sandbox_run(request, slug):
    item = catalogue.BY_SLUG.get(slug)
    if not item or item["kind"] != "sandbox":
        raise Http404
    # Only the catalogue's fixed statements are executed -- nothing from the request body.
    steps, verify = run_sandbox(item["steps"], item.get("verify_sql"))
    return render(request, "dbms_lab/query_detail.html", {
        "item": item, "category": dict(catalogue.CATEGORIES)[item["category"]],
        "steps": steps, "verify": verify, "ran": True})


@admin_required
def editor(request):
    sql_text = request.POST.get("sql") if request.method == "POST" else request.GET.get("sql", "")
    if not sql_text and request.GET.get("from") in catalogue.BY_SLUG:
        sql_text = catalogue.BY_SLUG[request.GET["from"]]["sql"]
    ctx = {"sql": sql_text or "SELECT f.name, COUNT(c.court_id) AS courts\nFROM facilities f\n"
                              "LEFT JOIN courts c ON c.facility_id = f.facility_id\nGROUP BY f.name\nORDER BY courts DESC;",
           "relations": introspection.APP_RELATIONS}
    if request.method == "POST":
        mode = request.POST.get("mode", "run")
        ctx["mode"] = mode
        try:
            ctx["result"] = _run_select(sql_text, mode)
        except SQLRejected as e:
            ctx["rejected"] = str(e)
    return render(request, "dbms_lab/editor.html", ctx)
