"""Write docs/SQL_QUERIES.md from dbms_lab/catalogue.py (single source of truth)."""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from dbms_lab import catalogue


class Command(BaseCommand):
    help = "Export the DBMS Lab SQL catalogue as Markdown (docs/SQL_QUERIES.md)."

    def handle(self, *args, **options):
        out = ["# SQL query catalogue", "",
               "Generated from `dbms_lab/catalogue.py` by `python manage.py export_sql_catalogue`. "
               "Every query can be run live at `/dbms-lab/queries/<slug>/`.", "",
               "* **select** – runs live as the SELECT-only role in a READ ONLY transaction",
               "* **sandbox** – fixed write statements executed in one transaction that is always rolled back",
               "* **compare** – the same query EXPLAIN ANALYZEd with and without index scans", ""]
        for code, name, items in catalogue.grouped():
            out += [f"## {code}. {name}", ""]
            for q in items:
                out += [f"### {q['title']}", "", f"`{q['slug']}` · *{q['kind']}* · **Concept:** {q['concept']}", "",
                        f"**Objective:** {q['objective']}", ""]
                if q["tables"]:
                    out.append(f"**Tables:** {', '.join(q['tables'])}  ")
                if q["joins"]:
                    out.append(f"**Joins:** `{q['joins']}`  ")
                if q["filters"]:
                    out.append(f"**Filters:** `{q['filters']}`  ")
                if q["tuple"]:
                    out.append(f"**One result tuple:** {q['tuple']}")
                out.append("")
                if q["columns"]:
                    out += [f"- `{k}` — {v}" for k, v in q["columns"].items()] + [""]
                if q["kind"] == "sandbox":
                    sql = "BEGIN;\n" + "\n".join(
                        s["sql"].rstrip() + (f"   -- {s['note']}" if s.get("note") else "") for s in q["steps"]
                    ) + "\nROLLBACK;"
                else:
                    sql = q["sql"]
                out += ["```sql", sql.strip(), "```", ""]
                if q.get("verify_sql"):
                    out += ["Verification after rollback:", "```sql", q["verify_sql"], "```", ""]
                if q["notes"]:
                    out += [f"> {q['notes']}", ""]
        path = Path(settings.BASE_DIR) / "docs" / "SQL_QUERIES.md"
        path.write_text("\n".join(out))
        self.stdout.write(self.style.SUCCESS(f"Wrote {path} ({len(catalogue.Q)} queries)"))
