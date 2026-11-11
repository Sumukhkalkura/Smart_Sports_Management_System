"""Database-level integrity: these tests bypass services.py and hit PostgreSQL constraints directly."""
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from sports.models import Booking, Facility, Maintenance, Payment, Review, Sport, User
from sports.services import constraint_name

from .helpers import future_slot, make_world


class ConstraintTestBase(TestCase):
    def setUp(self):
        self.w = make_world()

    def booking(self, start=None, end=None, status="confirmed", court=None, user=None, amount="400.00"):
        if start is None:
            start, end = future_slot()
        return Booking.objects.create(user=user or self.w["alice"], court=court or self.w["court"],
                                      start_time=start, end_time=end, total_amount=Decimal(amount), status=status)

    def assertViolates(self, name, func):
        with self.assertRaises(IntegrityError) as ctx, transaction.atomic():
            func()
        self.assertEqual(constraint_name(ctx.exception), name)


class CheckConstraintTests(ConstraintTestBase):
    def test_end_must_be_after_start(self):
        start, _ = future_slot()
        self.assertViolates("bookings_time_order", lambda: self.booking(start, start))

    def test_booking_status_domain(self):
        self.assertViolates("bookings_status_valid", lambda: self.booking(status="reserved"))

    def test_booking_amount_non_negative(self):
        self.assertViolates("bookings_amount_non_negative", lambda: self.booking(amount="-1"))

    def test_rating_between_1_and_5(self):
        b = self.booking()
        self.assertViolates("reviews_rating_1_to_5", lambda: Review.objects.create(booking=b, rating=6))
        self.assertViolates("reviews_rating_1_to_5", lambda: Review.objects.create(booking=b, rating=0))

    def test_payment_amount_non_negative(self):
        b = self.booking()
        self.assertViolates("payments_amount_non_negative", lambda: Payment.objects.create(
            booking=b, amount=Decimal("-10"), payment_method="upi", payment_status="pending"))

    def test_paid_payment_requires_paid_at(self):
        b = self.booking()
        self.assertViolates("payments_paid_at_consistent", lambda: Payment.objects.create(
            booking=b, amount=b.total_amount, payment_method="upi", payment_status="paid", paid_at=None))

    def test_court_rate_positive(self):
        self.w["court"].hourly_rate = Decimal("0")
        self.assertViolates("courts_hourly_rate_positive", lambda: self.w["court"].save())

    def test_email_unique_and_lowercase(self):
        self.assertViolates("users_email_key", lambda: User.objects.create(
            name="Dup", email="alice@example.com", password="x"))
        self.assertViolates("users_email_lowercase", lambda: User.objects.create(
            name="Upper", email="ALICE2@EXAMPLE.COM", password="x"))

    def test_role_domain(self):
        self.assertViolates("users_role_valid", lambda: User.objects.create(
            name="X", email="x@example.com", password="x", role="superhero"))


class KeyAndForeignKeyTests(ConstraintTestBase):
    def test_one_review_per_booking(self):
        b = self.booking()
        Review.objects.create(booking=b, rating=5)
        self.assertViolates("reviews_pkey", lambda: Review(booking=b, rating=4).save(force_insert=True))

    def test_one_payment_per_booking(self):
        b = self.booking()
        Payment.objects.create(booking=b, amount=b.total_amount, payment_method="cash", payment_status="pending")
        self.assertViolates("payments_pkey", lambda: Payment(
            booking=b, amount=1, payment_method="upi", payment_status="pending").save(force_insert=True))

    def test_maintenance_composite_primary_key(self):
        start, end = future_slot(days=5)
        Maintenance.objects.create(court=self.w["court"], start_time=start, end_time=end, reason="a")
        # same court + same start_time = same key (the exclusion constraint would also object)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Maintenance(court=self.w["court"], start_time=start, end_time=end + timedelta(hours=1),
                        reason="b").save(force_insert=True)
        # same start_time on a DIFFERENT court is a different key -> allowed
        Maintenance.objects.create(court=self.w["court2"], start_time=start, end_time=end, reason="c")

    def test_invalid_foreign_key_rejected(self):
        start, end = future_slot()
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cur:
                cur.execute("SET CONSTRAINTS ALL IMMEDIATE")  # Django FKs are DEFERRABLE INITIALLY DEFERRED
                cur.execute("INSERT INTO bookings (user_id, court_id, start_time, end_time, total_amount, status, "
                            "created_at) VALUES (%s, 999999, %s, %s, 100, 'pending', now())",
                            [self.w["alice"].pk, start, end])

    def test_cannot_delete_parent_with_history(self):
        self.booking()
        for sql, params in [("DELETE FROM courts WHERE court_id = %s", [self.w["court"].pk]),
                            ("DELETE FROM facilities WHERE facility_id = %s", [self.w["facility"].pk]),
                            ("DELETE FROM users WHERE user_id = %s", [self.w["alice"].pk])]:
            with self.subTest(sql=sql), self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cur:
                    cur.execute("SET CONSTRAINTS ALL IMMEDIATE")
                    cur.execute(sql, params)

    def test_weak_entities_cascade_with_owner(self):
        start, end = future_slot(days=2)
        b = self.booking(start, end)
        Payment.objects.create(booking=b, amount=b.total_amount, payment_method="upi", payment_status="paid",
                               paid_at=timezone.now())
        Review.objects.create(booking=b, rating=4)
        with connection.cursor() as cur:  # raw SQL: proves the CASCADE is in PostgreSQL, not in Django
            cur.execute("DELETE FROM bookings WHERE booking_id = %s", [b.pk])
        self.assertFalse(Payment.objects.filter(pk=b.pk).exists())
        self.assertFalse(Review.objects.filter(pk=b.pk).exists())

    def test_maintenance_cascades_with_court(self):
        start, end = future_slot(days=6)
        Maintenance.objects.create(court=self.w["court2"], start_time=start, end_time=end, reason="x")
        with connection.cursor() as cur:
            cur.execute("DELETE FROM courts WHERE court_id = %s", [self.w["court2"].pk])
        self.assertFalse(Maintenance.objects.filter(court_id=self.w["court2"].pk).exists())

    def test_sport_name_unique_case_insensitive(self):
        self.assertViolates("sports_name_lower_uniq", lambda: Sport.objects.create(name="BADMINTON"))

    def test_facility_name_unique_per_city(self):
        self.assertViolates("facilities_name_city_uniq", lambda: Facility.objects.create(
            name="Test Arena", city="Testville", phone="1", address="x"))
        Facility.objects.create(name="Test Arena", city="Othertown", phone="1", address="x")


class OverlapTests(ConstraintTestBase):
    def test_overlapping_active_bookings_rejected(self):
        start, end = future_slot(hours=2)
        self.booking(start, end)
        self.assertViolates("bookings_no_overlap", lambda: self.booking(
            start + timedelta(hours=1), end + timedelta(hours=1), user=self.w["bob"], status="pending"))

    def test_adjacent_bookings_allowed_half_open_interval(self):
        start, end = future_slot()
        self.booking(start, end)
        self.booking(end, end + timedelta(hours=1), user=self.w["bob"])  # [10,11) and [11,12) don't overlap

    def test_cancelled_booking_does_not_block(self):
        start, end = future_slot()
        self.booking(start, end, status="cancelled")
        self.booking(start, end, user=self.w["bob"])

    def test_same_time_different_court_allowed(self):
        start, end = future_slot()
        self.booking(start, end)
        self.booking(start, end, court=self.w["court2"], user=self.w["bob"])

    def test_booking_during_maintenance_rejected_by_trigger(self):
        start, end = future_slot(hours=3)
        Maintenance.objects.create(court=self.w["court"], start_time=start, end_time=end, reason="repair")
        self.assertViolates("bookings_not_during_maintenance",
                            lambda: self.booking(start + timedelta(hours=1), start + timedelta(hours=2)))

    def test_maintenance_over_active_booking_rejected_by_trigger(self):
        start, end = future_slot()
        self.booking(start, end)
        self.assertViolates("maintenance_not_during_booking", lambda: Maintenance.objects.create(
            court=self.w["court"], start_time=start - timedelta(hours=1), end_time=end, reason="x"))

    def test_maintenance_windows_cannot_overlap(self):
        start, end = future_slot(hours=2)
        Maintenance.objects.create(court=self.w["court"], start_time=start, end_time=end, reason="a")
        self.assertViolates("maintenance_no_overlap", lambda: Maintenance.objects.create(
            court=self.w["court"], start_time=start + timedelta(hours=1), end_time=end + timedelta(hours=1),
            reason="b"))
