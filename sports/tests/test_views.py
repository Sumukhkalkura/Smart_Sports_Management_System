"""HTTP-level tests: authentication, authorisation and the end-to-end booking workflow."""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sports.models import Booking, Court, Facility, Maintenance, Payment, User
from sports.services import local_slot

from .helpers import future_slot, make_world


class AuthTests(TestCase):
    def test_register_hashes_password_and_logs_in(self):
        resp = self.client.post(reverse("register"), {"name": "Neha", "email": "Neha@Example.com",
                                                      "password1": "Str0ng!Pass99", "password2": "Str0ng!Pass99"})
        self.assertRedirects(resp, reverse("dashboard"))
        user = User.objects.get(email="neha@example.com")  # normalised to lower case
        self.assertEqual(user.role, "customer")
        self.assertNotEqual(user.password, "Str0ng!Pass99")
        self.assertTrue(user.check_password("Str0ng!Pass99"))

    def test_register_rejects_duplicate_email_case_insensitively(self):
        make_world()
        resp = self.client.post(reverse("register"), {"name": "A", "email": "ALICE@example.com",
                                                      "password1": "Str0ng!Pass99", "password2": "Str0ng!Pass99"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "already exists")

    def test_login_with_email(self):
        make_world()
        resp = self.client.post(reverse("login"), {"username": "alice@example.com", "password": "Secret#12345"})
        self.assertRedirects(resp, reverse("dashboard"))
        self.client.logout()
        bad = self.client.post(reverse("login"), {"username": "alice@example.com", "password": "wrong"})
        self.assertEqual(bad.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)


class AuthorizationTests(TestCase):
    def setUp(self):
        self.w = make_world()

    def test_admin_pages_forbidden_for_customers(self):
        self.client.force_login(self.w["alice"])
        for name in ["manage_home", "manage_facilities", "manage_courts", "manage_bookings", "manage_payments",
                     "manage_maintenance", "reports", "lab_home", "lab_editor", "lab_queries"]:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)
        resp = self.client.post(reverse("manage_court_toggle", args=[self.w["court"].pk]))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Court.objects.get(pk=self.w["court"].pk).is_active)
        resp = self.client.post(reverse("lab_editor"), {"sql": "select 1", "mode": "run"})
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_redirected_to_login(self):
        for name in ["dashboard", "booking_list", "manage_home", "lab_home"]:
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 302)
            self.assertIn(reverse("login"), resp["Location"])

    def test_admin_can_access(self):
        self.client.force_login(self.w["admin"])
        for name in ["manage_home", "manage_bookings", "reports", "lab_home", "lab_editor"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_cannot_view_or_act_on_another_users_booking(self):
        start, end = future_slot()
        b = Booking.objects.create(user=self.w["alice"], court=self.w["court"], start_time=start, end_time=end,
                                   total_amount=400, status="pending")
        self.client.force_login(self.w["bob"])
        self.assertEqual(self.client.get(reverse("booking_detail", args=[b.pk])).status_code, 404)
        self.client.post(reverse("booking_cancel", args=[b.pk]))
        self.client.post(reverse("booking_pay", args=[b.pk]), {"payment_method": "upi"})
        b.refresh_from_db()
        self.assertEqual(b.status, "pending")
        self.assertFalse(Payment.objects.filter(pk=b.pk).exists())


class BookingWorkflowTests(TestCase):
    def setUp(self):
        self.w = make_world()
        self.client.force_login(self.w["alice"])

    def test_full_booking_flow_through_http(self):
        start, _ = future_slot(days=2, hour=17)
        resp = self.client.post(reverse("court_detail", args=[self.w["court"].pk]),
                                {"date": start.date().isoformat(), "start_hour": 17, "hours": 2,
                                 "total_amount": "1"})  # a forged price is ignored
        booking = Booking.objects.get(user=self.w["alice"])
        self.assertRedirects(resp, reverse("booking_detail", args=[booking.pk]))
        self.assertEqual(booking.total_amount, 800)
        self.assertEqual(booking.status, "pending")

        self.client.post(reverse("booking_pay", args=[booking.pk]), {"payment_method": "upi"})
        booking.refresh_from_db()
        self.assertEqual(booking.status, "confirmed")

        listing = self.client.get(reverse("booking_list"))
        self.assertContains(listing, f">{booking.pk}</a>")

        self.client.post(reverse("booking_cancel", args=[booking.pk]))
        booking.refresh_from_db()
        self.assertEqual((booking.status, booking.payment.payment_status), ("cancelled", "refunded"))

    def test_double_booking_shows_error(self):
        day = future_slot(days=2)[0].date()
        Booking.objects.create(user=self.w["bob"], court=self.w["court"], start_time=local_slot(day, 10)[0],
                               end_time=local_slot(day, 11)[0], total_amount=400, status="confirmed")
        resp = self.client.post(reverse("court_detail", args=[self.w["court"].pk]),
                                {"date": day.isoformat(), "start_hour": 10, "hours": 1}, follow=True)
        self.assertContains(resp, "already booked")
        self.assertFalse(Booking.objects.filter(user=self.w["alice"]).exists())

    def test_availability_grid_reflects_database(self):
        day = future_slot(days=2)[0].date()
        Booking.objects.create(user=self.w["bob"], court=self.w["court"], start_time=local_slot(day, 10)[0],
                               end_time=local_slot(day, 12)[0], total_amount=800, status="confirmed")
        Maintenance.objects.create(court=self.w["court"], start_time=local_slot(day, 14)[0],
                                   end_time=local_slot(day, 15)[0], reason="x")
        resp = self.client.get(reverse("court_detail", args=[self.w["court"].pk]) + f"?date={day.isoformat()}")
        states = {s["hour"]: s["state"] for s in resp.context["slots"]}
        self.assertEqual((states[10], states[11], states[12], states[14], states[16]),
                         ("booked", "booked", "free", "maintenance", "free"))


class AdminManagementTests(TestCase):
    def setUp(self):
        self.w = make_world()
        self.client.force_login(self.w["admin"])

    def test_create_facility_and_court(self):
        self.client.post(reverse("manage_facility_new"), {"name": "New Place", "city": "Pune", "phone": "1",
                                                          "address": "Road 1"})
        fac = Facility.objects.get(name="New Place")
        self.client.post(reverse("manage_court_new"), {"facility": fac.pk, "sport": self.w["sport"].pk,
                                                       "court_name": "C1", "hourly_rate": "250.00",
                                                       "is_active": "on"})
        self.assertTrue(Court.objects.filter(facility=fac, court_name="C1", hourly_rate=250).exists())

    def test_duplicate_court_name_in_facility_shows_validation_error(self):
        resp = self.client.post(reverse("manage_court_new"), {"facility": self.w["facility"].pk,
                                                              "sport": self.w["sport"].pk,
                                                              "court_name": "Court 1", "hourly_rate": "100"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Court.objects.filter(court_name="Court 1").count(), 1)

    def test_toggle_court(self):
        self.client.post(reverse("manage_court_toggle", args=[self.w["court"].pk]))
        self.assertFalse(Court.objects.get(pk=self.w["court"].pk).is_active)

    def test_facility_with_courts_not_deleted(self):
        self.client.post(reverse("manage_facility_delete", args=[self.w["facility"].pk]))
        self.assertTrue(Facility.objects.filter(pk=self.w["facility"].pk).exists())

    def test_schedule_and_delete_maintenance_by_composite_key(self):
        start, end = future_slot(days=5)
        fmt = "%Y-%m-%dT%H:%M"
        self.client.post(reverse("manage_maintenance"), {
            "court": self.w["court"].pk, "start_time": timezone.localtime(start).strftime(fmt),
            "end_time": timezone.localtime(end).strftime(fmt), "reason": "Paint"})
        window = Maintenance.objects.get(court=self.w["court"])
        self.client.post(reverse("manage_maintenance_delete"),
                         {"court_id": window.court_id, "start_time": window.start_time.isoformat()})
        self.assertFalse(Maintenance.objects.exists())

    def test_reports_page_runs_sql(self):
        resp = self.client.get(reverse("reports"))
        self.assertContains(resp, "Revenue by facility")
        self.assertContains(resp, "Test Arena")
