"""Business logic, transactions and concurrency."""
import threading
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.db import IntegrityError, connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from sports import services
from sports.models import Booking, Maintenance, Payment, Review
from sports.services import BookingError

from .helpers import future_slot, make_world


class BookingServiceTests(TestCase):
    def setUp(self):
        self.w = make_world()

    def test_create_booking_computes_amount_server_side(self):
        start, end = future_slot(hours=2)
        b = services.create_booking(self.w["alice"], self.w["court"].pk, start, end)
        b.refresh_from_db()
        self.assertEqual(b.total_amount, Decimal("800.00"))  # 2 h x 400
        self.assertEqual(b.status, "pending")
        self.assertEqual(b.user_id, self.w["alice"].pk)

    def test_rejects_inactive_court(self):
        self.w["court"].is_active = False
        self.w["court"].save()
        with self.assertRaisesMessage(BookingError, "not accepting"):
            services.create_booking(self.w["alice"], self.w["court"].pk, *future_slot())

    def test_rejects_unknown_court(self):
        with self.assertRaisesMessage(BookingError, "does not exist"):
            services.create_booking(self.w["alice"], 987654, *future_slot())

    def test_rejects_past_and_reversed_intervals(self):
        start, end = future_slot(days=-1)
        with self.assertRaises(BookingError):
            services.create_booking(self.w["alice"], self.w["court"].pk, start, end)
        start, end = future_slot()
        with self.assertRaises(BookingError):
            services.create_booking(self.w["alice"], self.w["court"].pk, end, start)

    def test_rejects_outside_opening_hours_and_too_long(self):
        with self.assertRaises(BookingError):
            services.create_booking(self.w["alice"], self.w["court"].pk, *future_slot(hour=3))
        with self.assertRaises(BookingError):
            services.create_booking(self.w["alice"], self.w["court"].pk, *future_slot(hour=8, hours=6))

    def test_rejects_overlap(self):
        start, end = future_slot(hours=2)
        services.create_booking(self.w["alice"], self.w["court"].pk, start, end)
        with self.assertRaisesMessage(BookingError, "already booked"):
            services.create_booking(self.w["bob"], self.w["court"].pk, start + timedelta(hours=1),
                                    end + timedelta(hours=1))

    def test_rejects_maintenance_conflict(self):
        start, end = future_slot(hours=3)
        Maintenance.objects.create(court=self.w["court"], start_time=start, end_time=end, reason="repair")
        with self.assertRaisesMessage(BookingError, "maintenance"):
            services.create_booking(self.w["alice"], self.w["court"].pk, start, start + timedelta(hours=1))

    def test_cancelled_slot_can_be_rebooked(self):
        start, end = future_slot()
        b = services.create_booking(self.w["alice"], self.w["court"].pk, start, end)
        services.cancel_booking(self.w["alice"], b.pk)
        services.create_booking(self.w["bob"], self.w["court"].pk, start, end)

    def test_payment_success_confirms_booking(self):
        b = services.create_booking(self.w["alice"], self.w["court"].pk, *future_slot())
        p = services.pay_booking(self.w["alice"], b.pk, "upi")
        b.refresh_from_db()
        self.assertEqual((b.status, p.payment_status), ("confirmed", "paid"))
        self.assertEqual(p.amount, b.total_amount)
        self.assertIsNotNone(p.paid_at)

    def test_failed_payment_keeps_booking_pending_and_retry_updates_same_row(self):
        b = services.create_booking(self.w["alice"], self.w["court"].pk, *future_slot())
        services.pay_booking(self.w["alice"], b.pk, "card", simulate_failure=True)
        b.refresh_from_db()
        self.assertEqual(b.status, "pending")
        self.assertEqual(Payment.objects.get(pk=b.pk).payment_status, "failed")
        services.pay_booking(self.w["alice"], b.pk, "upi")
        self.assertEqual(Payment.objects.filter(pk=b.pk).count(), 1)  # still exactly one row (1:1)
        self.assertEqual(Payment.objects.get(pk=b.pk).payment_status, "paid")

    def test_cash_payment_confirms_with_pending_payment(self):
        b = services.create_booking(self.w["alice"], self.w["court"].pk, *future_slot())
        services.pay_booking(self.w["alice"], b.pk, "cash")
        b.refresh_from_db()
        self.assertEqual((b.status, b.payment.payment_status), ("confirmed", "pending"))
        services.mark_cash_received(b.pk)
        self.assertEqual(Payment.objects.get(pk=b.pk).payment_status, "paid")

    def test_cannot_pay_for_someone_elses_booking(self):
        b = services.create_booking(self.w["alice"], self.w["court"].pk, *future_slot())
        with self.assertRaises(BookingError):
            services.pay_booking(self.w["bob"], b.pk, "upi")

    def test_cancel_refunds_paid_payment(self):
        b = services.create_booking(self.w["alice"], self.w["court"].pk, *future_slot())
        services.pay_booking(self.w["alice"], b.pk, "upi")
        services.cancel_booking(self.w["alice"], b.pk)
        b.refresh_from_db()
        self.assertEqual((b.status, b.payment.payment_status), ("cancelled", "refunded"))

    def test_cannot_cancel_someone_elses_booking(self):
        b = services.create_booking(self.w["alice"], self.w["court"].pk, *future_slot())
        with self.assertRaises(BookingError):
            services.cancel_booking(self.w["bob"], b.pk)
        services.cancel_booking(self.w["admin"], b.pk)  # administrators may

    def _played_booking(self, user=None):
        start, end = future_slot(days=-2)
        return Booking.objects.create(user=user or self.w["alice"], court=self.w["court"], start_time=start,
                                      end_time=end, total_amount=Decimal("400"), status="completed")

    def test_review_rules(self):
        b = self._played_booking()
        with self.assertRaises(BookingError):
            services.submit_review(self.w["bob"], b.pk, 5)  # not Bob's booking
        services.submit_review(self.w["alice"], b.pk, 4, "nice")
        with self.assertRaisesMessage(BookingError, "already been reviewed"):
            services.submit_review(self.w["alice"], b.pk, 5)
        self.assertEqual(Review.objects.get(pk=b.pk).rating, 4)

    def test_cannot_review_future_booking(self):
        b = services.create_booking(self.w["alice"], self.w["court"].pk, *future_slot())
        services.pay_booking(self.w["alice"], b.pk, "upi")
        with self.assertRaises(BookingError):
            services.submit_review(self.w["alice"], b.pk, 5)

    def test_invalid_rating_rejected_by_database(self):
        b = self._played_booking()
        with self.assertRaisesMessage(BookingError, "between 1 and 5"):
            services.submit_review(self.w["alice"], b.pk, 9)

    def test_maintenance_policy(self):
        start, end = future_slot(hours=2)
        b = services.create_booking(self.w["alice"], self.w["court"].pk, start, end)
        services.pay_booking(self.w["alice"], b.pk, "upi")
        with self.assertRaisesMessage(BookingError, "Active bookings overlap"):
            services.schedule_maintenance(self.w["court"].pk, start, end, "repair")
        window, cancelled = services.schedule_maintenance(self.w["court"].pk, start, end, "repair",
                                                          cancel_conflicts=True)
        b.refresh_from_db()
        self.assertEqual([c.pk for c in cancelled], [b.pk])
        self.assertEqual((b.status, b.payment.payment_status), ("cancelled", "refunded"))

    def test_complete_past_bookings_bulk_update(self):
        start, end = future_slot(days=-1)
        Booking.objects.create(user=self.w["alice"], court=self.w["court"], start_time=start, end_time=end,
                               total_amount=400, status="confirmed")
        self.assertEqual(services.complete_past_bookings(), 1)


class TransactionRollbackTests(TestCase):
    """A failure in the last step of a multi-step operation must undo the earlier steps."""

    def setUp(self):
        self.w = make_world()

    def test_maintenance_cancellations_rolled_back_when_insert_fails(self):
        start, end = future_slot(hours=2)
        b = services.create_booking(self.w["alice"], self.w["court"].pk, start, end)
        services.pay_booking(self.w["alice"], b.pk, "upi")
        boom = IntegrityError("simulated failure")
        with mock.patch.object(Maintenance, "save", side_effect=boom), self.assertRaises(BookingError):
            services.schedule_maintenance(self.w["court"].pk, start, end, "x", cancel_conflicts=True)
        b.refresh_from_db()
        self.assertEqual(b.status, "confirmed")  # cancellation was rolled back
        self.assertEqual(b.payment.payment_status, "paid")  # refund was rolled back

    def test_payment_rolled_back_when_booking_update_fails(self):
        b = services.create_booking(self.w["alice"], self.w["court"].pk, *future_slot())
        original_save = Booking.save

        def failing_save(self_, *args, **kwargs):
            if kwargs.get("update_fields") == ["status"]:
                raise RuntimeError("crash after payment insert")
            return original_save(self_, *args, **kwargs)

        with mock.patch.object(Booking, "save", failing_save), self.assertRaises(RuntimeError):
            services.pay_booking(self.w["alice"], b.pk, "upi")
        self.assertFalse(Payment.objects.filter(pk=b.pk).exists())
        b.refresh_from_db()
        self.assertEqual(b.status, "pending")


class ConcurrentBookingTests(TransactionTestCase):
    """Real concurrency: each thread has its own PostgreSQL connection and transaction."""

    def setUp(self):
        self.w = make_world()

    def _race(self, n, slot_for):
        barrier = threading.Barrier(n)
        outcomes = []

        def worker(i):
            try:
                barrier.wait()
                user = self.w["alice"] if i % 2 == 0 else self.w["bob"]
                services.create_booking(user, self.w["court"].pk, *slot_for(i))
                outcomes.append("ok")
            except BookingError:
                outcomes.append("rejected")
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return outcomes

    def test_only_one_of_many_simultaneous_requests_wins(self):
        start, end = future_slot(days=4)
        outcomes = self._race(8, lambda i: (start, end))
        self.assertEqual(outcomes.count("ok"), 1, outcomes)
        self.assertEqual(outcomes.count("rejected"), 7, outcomes)
        self.assertEqual(Booking.objects.exclude(status="cancelled").filter(court=self.w["court"]).count(), 1)

    def test_partially_overlapping_simultaneous_requests(self):
        base, _ = future_slot(days=4, hour=8)
        # i=0: 08-10, i=1: 09-11, i=2: 10-12, i=3: 11-13 -> at most 2 can coexist
        outcomes = self._race(4, lambda i: (base + timedelta(hours=i), base + timedelta(hours=i + 2)))
        rows = list(Booking.objects.filter(court=self.w["court"]).order_by("start_time"))
        for a, b in zip(rows, rows[1:]):
            self.assertLessEqual(a.end_time, b.start_time)  # no overlaps persisted
        self.assertEqual(outcomes.count("ok"), len(rows))

    def test_concurrent_booking_and_maintenance(self):
        start, end = future_slot(days=4)
        barrier = threading.Barrier(2)
        results = {}

        def book():
            try:
                barrier.wait()
                services.create_booking(self.w["alice"], self.w["court"].pk, start, end)
                results["booking"] = "ok"
            except BookingError:
                results["booking"] = "rejected"
            finally:
                connection.close()

        def maintain():
            try:
                barrier.wait()
                services.schedule_maintenance(self.w["court"].pk, start, end, "urgent")
                results["maintenance"] = "ok"
            except BookingError:
                results["maintenance"] = "rejected"
            finally:
                connection.close()

        threads = [threading.Thread(target=book), threading.Thread(target=maintain)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results.values()), ["ok", "rejected"], results)
        with connection.cursor() as cur:
            cur.execute("""SELECT COUNT(*) FROM bookings b JOIN maintenance m ON m.court_id = b.court_id
                           WHERE b.status <> 'cancelled'
                             AND tstzrange(b.start_time, b.end_time) && tstzrange(m.start_time, m.end_time)""")
            self.assertEqual(cur.fetchone()[0], 0)
