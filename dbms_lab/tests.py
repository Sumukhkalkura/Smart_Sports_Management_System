"""
DBMS Lab tests. TransactionTestCase is used because the lab reads through a
*separate* PostgreSQL connection (the SELECT-only role), which can only see
committed data.
"""
from io import StringIO

import psycopg
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.urls import reverse

from dbms_lab import catalogue, introspection
from dbms_lab.executor import _readonly_connection, run_readonly, run_sandbox
from dbms_lab.validator import SQLRejected, validate_readonly_sql
from sports.models import Booking, Court, Facility, Payment, Review, User


class ValidatorTests(SimpleTestCase):
    ALLOWED = [
        "SELECT 1",
        "select * from bookings;",
        "WITH x AS (SELECT * FROM courts) SELECT count(*) FROM x",
        "VALUES (1), (2)",
        "EXPLAIN ANALYZE SELECT * FROM bookings",
        "SELECT 'a; DROP TABLE users'",                    # semicolon inside a string literal
        "SELECT $$; DELETE FROM users$$",                   # dollar-quoted string
        "SELECT 1 /* ; DELETE FROM users */",               # comment
        "SELECT name FROM users WHERE email = 'x'' OR ''1''=''1'",
    ]
    REJECTED = [
        "",
        "SELECT 1; SELECT 2",
        "SELECT 1; DROP TABLE users",
        "DROP TABLE users",
        "DELETE FROM reviews",
        "UPDATE courts SET is_active = false",
        "INSERT INTO sports(name) VALUES ('x')",
        "TRUNCATE bookings",
        "CREATE TABLE t (a int)",
        "ALTER TABLE users ADD COLUMN x int",
        "GRANT ALL ON users TO public",
        "BEGIN",
        "COMMIT",
        "SET ROLE postgres",
        "SET transaction_read_only = off",
        "COPY users TO STDOUT",
        "DO $$ BEGIN DELETE FROM reviews; END $$",
        "CALL some_proc()",
        "WITH d AS (DELETE FROM reviews RETURNING *) SELECT * FROM d",
        "WITH u AS (UPDATE courts SET is_active=false RETURNING *) SELECT 1",
        "SELECT * INTO copy_users FROM users",
        "SELECT * FROM courts FOR UPDATE",
        "SELECT pg_sleep(10)",
        "SELECT pg_catalog.pg_sleep(10)",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT set_config('transaction_read_only', 'off', true)",
        "SELECT nextval('bookings_booking_id_seq')",
        "SELECT query_to_xml('DELETE FROM reviews', true, true, '')",
        "SELECT pg_terminate_backend(1)",
        "SELECT * FROM (SELECT lo_import('/etc/passwd')) x",
        "EXPLAIN ANALYZE DELETE FROM reviews",
        "SELECT 1 FROM",  # syntax error
        "x" * 20000,
    ]

    def test_allowed(self):
        for sql in self.ALLOWED:
            with self.subTest(sql=sql):
                validate_readonly_sql(sql)

    def test_rejected(self):
        for sql in self.REJECTED:
            with self.subTest(sql=sql[:60]), self.assertRaises(SQLRejected):
                validate_readonly_sql(sql)


class SeededLabTestCase(TransactionTestCase):
    reset_sequences = True  # deterministic IDs (catalogue examples refer to e.g. user_id = 2)

    def setUp(self):
        call_command("seed_data", stdout=StringIO())


class ReadOnlyExecutionTests(SeededLabTestCase):
    """Layers 2 and 3: even SQL that skipped the validator cannot write."""

    WRITES = ["DELETE FROM reviews", "UPDATE courts SET is_active = false",
              "INSERT INTO sports (name) VALUES ('hack')", "DROP TABLE reviews", "TRUNCATE payments",
              "WITH d AS (DELETE FROM reviews RETURNING *) SELECT * FROM d"]

    def test_role_cannot_write_even_without_validator(self):
        before = (Review.objects.count(), Court.objects.filter(is_active=True).count(), Payment.objects.count())
        conn = _readonly_connection()
        conn.autocommit = True
        try:
            # Layer 3: the role's default_transaction_read_only = on
            for sql in self.WRITES:
                with self.subTest(layer="read-only", sql=sql), self.assertRaises(psycopg.Error) as ctx:
                    conn.execute(sql)
                self.assertEqual(ctx.exception.sqlstate, "25006")  # read_only_sql_transaction
            # Layer 2: even if a session switches read-only off, the role has no write privileges
            conn.execute("SET default_transaction_read_only = off")
            for sql in self.WRITES:
                with self.subTest(layer="privileges", sql=sql), self.assertRaises(psycopg.Error) as ctx:
                    conn.execute(sql)
                self.assertEqual(ctx.exception.sqlstate, "42501")  # insufficient_privilege
        finally:
            conn.close()
        after = (Review.objects.count(), Court.objects.filter(is_active=True).count(), Payment.objects.count())
        self.assertEqual(after, before)

    def test_executor_blocks_writes_without_validator(self):
        for sql in self.WRITES:
            with self.subTest(sql=sql):
                self.assertFalse(run_readonly(sql).ok)

    def test_password_hash_not_readable(self):
        res = run_readonly("SELECT password_hash FROM users")
        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "42501")  # insufficient_privilege
        self.assertTrue(run_readonly("SELECT user_id, name, email FROM users").ok)

    @override_settings(LAB_STATEMENT_TIMEOUT_MS=200)
    def test_statement_timeout(self):
        res = run_readonly("SELECT pg_sleep(2)")  # validator bypassed on purpose
        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "57014")  # query_canceled

    @override_settings(LAB_MAX_ROWS=10)
    def test_row_limit(self):
        res = run_readonly("SELECT * FROM generate_series(1, 1000)")
        self.assertTrue(res.ok)
        self.assertEqual(res.row_count, 10)
        self.assertTrue(res.truncated)

    def test_result_columns_types_and_rows_match_orm(self):
        res = run_readonly("SELECT booking_id, total_amount, start_time, status FROM bookings ORDER BY booking_id")
        self.assertTrue(res.ok, res.error)
        self.assertEqual([c["name"] for c in res.columns], ["booking_id", "total_amount", "start_time", "status"])
        self.assertEqual([c["type"] for c in res.columns], ["int8", "numeric", "timestamptz", "varchar"])
        self.assertEqual(res.row_count, Booking.objects.count())
        first = Booking.objects.order_by("booking_id").first()
        self.assertEqual(res.rows[0][:2], [first.booking_id, first.total_amount])

    def test_aggregate_result_matches_orm(self):
        res = run_readonly("SELECT COUNT(*) FROM payments WHERE payment_status = 'paid'")
        self.assertEqual(res.rows[0][0], Payment.objects.filter(payment_status="paid").count())


class CatalogueTests(SeededLabTestCase):
    def test_every_select_query_validates_and_returns_rows(self):
        for item in catalogue.Q:
            if item["kind"] != "select":
                continue
            with self.subTest(slug=item["slug"]):
                checked = validate_readonly_sql(item["sql"])
                res = run_readonly(checked["sql"], is_explain=checked["explain"])
                self.assertTrue(res.ok, f"{item['slug']}: {res.error}")
                self.assertGreater(res.row_count, 0, item["slug"])

    def test_sandboxes_behave_as_documented_and_leave_no_trace(self):
        def snapshot():
            with connection.cursor() as cur:
                cur.execute("SELECT (SELECT COUNT(*) FROM bookings), (SELECT COUNT(*) FROM payments), "
                            "(SELECT COUNT(*) FROM reviews), (SELECT COUNT(*) FROM sports), "
                            "(SELECT SUM(hourly_rate) FROM courts), (SELECT COUNT(*) FROM users)")
                return cur.fetchone()

        before = snapshot()
        for item in catalogue.Q:
            if item["kind"] != "sandbox":
                continue
            with self.subTest(slug=item["slug"]):
                steps, verify = run_sandbox(item["steps"], item.get("verify_sql"))
                self.assertEqual(len(steps), len(item["steps"]), item["slug"])
                for step, spec in zip(steps, item["steps"]):
                    self.assertEqual(step.ok, not spec.get("expect_error", False), f"{item['slug']}: {step.error}")
                    if not step.ok:
                        self.assertTrue(step.error_code.startswith(("23", "22")), step.error_code)
                if verify:
                    self.assertTrue(verify.ok)
        self.assertEqual(snapshot(), before)


class IntrospectionTests(SeededLabTestCase):
    def test_primary_keys_reflect_er_mapping(self):
        def pk(table):
            return [c["column_name"] for c in introspection.columns(table) if c["is_pk"]]

        self.assertEqual(pk("bookings"), ["booking_id"])
        self.assertEqual(pk("payments"), ["booking_id"])          # weak entity, 1:1
        self.assertEqual(pk("reviews"), ["booking_id"])           # weak entity, 1:1
        self.assertEqual(sorted(pk("maintenance")), ["court_id", "start_time"])  # weak entity, partial key

    def test_foreign_keys_and_delete_rules(self):
        fks = {(fk["from_table"], fk["from_columns"], fk["to_table"]): fk["on_delete"]
               for fk in introspection.foreign_keys()}
        self.assertEqual(fks[("bookings", "user_id", "users")], "NO ACTION")
        self.assertEqual(fks[("bookings", "court_id", "courts")], "NO ACTION")
        self.assertEqual(fks[("courts", "facility_id", "facilities")], "NO ACTION")
        self.assertEqual(fks[("courts", "sport_id", "sports")], "NO ACTION")
        self.assertEqual(fks[("payments", "booking_id", "bookings")], "CASCADE")
        self.assertEqual(fks[("reviews", "booking_id", "bookings")], "CASCADE")
        self.assertEqual(fks[("maintenance", "court_id", "courts")], "CASCADE")
        self.assertEqual(len(fks), 7)

    def test_constraints_indexes_triggers_present(self):
        names = {k["name"] for k in introspection.constraints("bookings")}
        self.assertTrue({"bookings_no_overlap", "bookings_time_order", "bookings_status_valid"} <= names)
        idx = {i["name"] for i in introspection.indexes("bookings")}
        self.assertTrue({"bookings_pkey", "bookings_no_overlap", "bookings_user_start_idx"} <= idx)
        self.assertEqual([t["name"] for t in introspection.triggers("bookings")],
                         ["trg_bookings_not_during_maintenance"])

    def test_row_counts_are_exact(self):
        counts = {r["name"]: r["row_count"] for r in introspection.relation_summaries()}
        self.assertEqual(counts["bookings"], Booking.objects.count())
        self.assertEqual(counts["users"], User.objects.count())
        self.assertEqual(counts["v_booking_details"], Booking.objects.count())

    def test_browse_hides_password_column_and_paginates(self):
        result, total, hidden = introspection.browse("users", page=1, page_size=5)
        self.assertTrue(result.ok, result.error)
        self.assertNotIn("password_hash", [c["name"] for c in result.columns])
        self.assertIn("password_hash", hidden)
        self.assertEqual((result.row_count, total), (5, User.objects.count()))


class LabHttpTests(SeededLabTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(User.objects.get(role="admin"))

    def test_editor_runs_select_and_shows_tuples(self):
        resp = self.client.post(reverse("lab_editor"), {"sql": "SELECT name, city FROM facilities ORDER BY name",
                                                        "mode": "run"})
        self.assertEqual(resp.context["result"].row_count, Facility.objects.count())
        self.assertContains(resp, "Coastal Turf Park")

    def test_editor_rejects_injection_and_writes(self):
        for sql in ["SELECT 1; DELETE FROM reviews", "DELETE FROM reviews",
                    "WITH d AS (DELETE FROM reviews RETURNING *) SELECT * FROM d"]:
            resp = self.client.post(reverse("lab_editor"), {"sql": sql, "mode": "run"})
            self.assertIn("rejected", resp.context)
        self.assertGreater(Review.objects.count(), 0)

    def test_explain_and_analyze(self):
        resp = self.client.post(reverse("lab_editor"), {"sql": "SELECT * FROM bookings WHERE user_id = 2",
                                                        "mode": "analyze"})
        res = resp.context["result"]
        self.assertTrue(res.ok, res.error)
        self.assertTrue(any(line.startswith("Execution Time") for line in res.plan_lines))

    def test_catalogue_pages_and_sandbox(self):
        for item in catalogue.Q:
            self.assertEqual(self.client.get(reverse("lab_query", args=[item["slug"]])).status_code, 200)
        resp = self.client.post(reverse("lab_sandbox", args=["atomic-booking"]))
        self.assertContains(resp, "ROLLBACK")
        self.assertEqual(resp.context["verify"].rows, [[0]])

    def test_table_pages(self):
        for table in introspection.APP_RELATIONS:
            self.assertEqual(self.client.get(reverse("lab_table", args=[table])).status_code, 200)
        self.assertEqual(self.client.get(reverse("lab_table", args=["django_session"])).status_code, 404)
