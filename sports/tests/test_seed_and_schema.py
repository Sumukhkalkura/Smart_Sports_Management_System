"""Seed-data consistency and migration/schema checks."""
from io import StringIO

from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase

from sports.models import Booking, Facility, Maintenance, Payment, Review, Sport, User


def scalar(sql):
    with connection.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


class SeedDataTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        call_command("seed_data", stdout=StringIO())

    def test_volumes(self):
        self.assertGreaterEqual(User.objects.count(), 10)
        self.assertGreaterEqual(Facility.objects.count(), 3)
        self.assertGreaterEqual(Sport.objects.count(), 4)
        self.assertGreaterEqual(Booking.objects.count(), 40)
        self.assertGreater(Review.objects.count(), 0)
        self.assertGreater(Maintenance.objects.count(), 0)
        self.assertEqual(set(Booking.objects.values_list("status", flat=True).distinct()),
                         {"pending", "confirmed", "completed", "cancelled"})
        self.assertTrue({"paid", "pending", "failed", "refunded"}
                        <= set(Payment.objects.values_list("payment_status", flat=True)))

    def test_no_overlapping_active_bookings(self):
        self.assertEqual(scalar("""
            SELECT COUNT(*) FROM bookings a JOIN bookings b
              ON a.court_id = b.court_id AND a.booking_id < b.booking_id
             AND tstzrange(a.start_time, a.end_time) && tstzrange(b.start_time, b.end_time)
            WHERE a.status <> 'cancelled' AND b.status <> 'cancelled'"""), 0)

    def test_payments_consistent_with_bookings(self):
        self.assertEqual(scalar("SELECT COUNT(*) FROM payments p JOIN bookings b USING (booking_id) "
                                "WHERE p.amount <> b.total_amount"), 0)
        # A paid (not refunded) payment never belongs to a cancelled booking; refunds only for cancelled ones.
        self.assertEqual(scalar("SELECT COUNT(*) FROM payments p JOIN bookings b USING (booking_id) "
                                "WHERE (p.payment_status = 'paid' AND b.status = 'cancelled') "
                                "   OR (p.payment_status = 'refunded' AND b.status <> 'cancelled')"), 0)
        # Confirmed/completed bookings always have a payment row.
        self.assertEqual(scalar("SELECT COUNT(*) FROM bookings b WHERE b.status IN ('confirmed','completed') "
                                "AND NOT EXISTS (SELECT 1 FROM payments p WHERE p.booking_id = b.booking_id)"), 0)

    def test_reviews_only_for_played_bookings(self):
        self.assertEqual(scalar("SELECT COUNT(*) FROM reviews r JOIN bookings b USING (booking_id) "
                                "WHERE b.status <> 'completed' OR b.end_time > r.created_at"), 0)

    def test_amounts_match_rate_times_hours(self):
        self.assertEqual(scalar("""SELECT COUNT(*) FROM bookings b JOIN courts c USING (court_id)
            WHERE b.total_amount <> ROUND(c.hourly_rate * EXTRACT(EPOCH FROM b.end_time - b.start_time) / 3600, 2)"""), 0)

    def test_no_booking_overlaps_maintenance(self):
        self.assertEqual(scalar("""SELECT COUNT(*) FROM bookings b JOIN maintenance m USING (court_id)
            WHERE b.status <> 'cancelled'
              AND tstzrange(b.start_time, b.end_time) && tstzrange(m.start_time, m.end_time)"""), 0)

    def test_users_without_bookings_exist(self):
        self.assertGreater(scalar("SELECT COUNT(*) FROM users u WHERE u.role = 'customer' AND NOT EXISTS "
                                  "(SELECT 1 FROM bookings b WHERE b.user_id = u.user_id)"), 0)

    def test_refuses_to_reseed_without_reset(self):
        with self.assertRaises(CommandError):
            call_command("seed_data", stdout=StringIO())

    def test_reset_is_deterministic(self):
        def fingerprint():
            return list(Booking.objects.order_by("booking_id").values_list("court_id", "user_id", "status",
                                                                           "total_amount"))
        first = fingerprint()
        call_command("seed_data", reset=True, noinput=True, stdout=StringIO())
        self.assertEqual(fingerprint(), first)


class SchemaTests(TestCase):
    def test_no_missing_migrations(self):
        call_command("makemigrations", "--check", "--dry-run", stdout=StringIO())  # raises SystemExit if drift

    def test_database_objects_created_by_migrations(self):
        self.assertEqual(scalar("SELECT COUNT(*) FROM pg_extension WHERE extname = 'btree_gist'"), 1)
        self.assertEqual(scalar("SELECT COUNT(*) FROM pg_views WHERE schemaname = 'public' "
                                "AND viewname IN ('v_booking_details', 'v_facility_revenue')"), 2)
        self.assertEqual(scalar("SELECT COUNT(*) FROM pg_trigger WHERE NOT tgisinternal AND tgname IN "
                                "('trg_bookings_not_during_maintenance', 'trg_maintenance_not_during_booking')"), 2)

    def test_column_types(self):
        with connection.cursor() as cur:
            cur.execute("""SELECT table_name || '.' || column_name, data_type FROM information_schema.columns
                           WHERE table_schema = 'public' AND table_name IN ('bookings', 'payments', 'users')""")
            types = dict(cur.fetchall())
        self.assertEqual(types["bookings.booking_id"], "bigint")
        self.assertEqual(types["bookings.start_time"], "timestamp with time zone")
        self.assertEqual(types["bookings.total_amount"], "numeric")
        self.assertEqual(types["payments.amount"], "numeric")
        self.assertEqual(types["users.password_hash"], "character varying")
        self.assertNotIn("users.password", types)


class MigrationRoundTripTests(TransactionTestCase):
    """Unapply the app's migrations and re-apply them on the test database."""

    def test_migrate_down_and_up(self):
        call_command("migrate", "sports", "0001", stdout=StringIO())
        self.assertEqual(scalar("SELECT COUNT(*) FROM pg_views WHERE viewname = 'v_booking_details'"), 0)
        call_command("migrate", "sports", stdout=StringIO())
        self.assertEqual(scalar("SELECT COUNT(*) FROM pg_views WHERE viewname = 'v_booking_details'"), 1)
        from dbms_lab.roles import ensure_readonly_role
        ensure_readonly_role(connection)  # views were re-created: grant SELECT again
