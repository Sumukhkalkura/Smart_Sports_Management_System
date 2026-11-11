"""
Deterministic sample data.

    python manage.py seed_data                 # only on an empty database
    python manage.py seed_data --reset         # TRUNCATE domain tables, then seed (asks to confirm)
    python manage.py seed_data --bulk 20000    # also add 20,000 historical bookings (for EXPLAIN demos)

All randomness comes from random.Random(SEED), so the same command produces the
same rows (dates are relative to the day the command is run, so that upcoming
bookings always exist for a demo).
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from sports.models import Booking, Court, Facility, Maintenance, Payment, Review, Sport, User
from sports.services import CLOSE_HOUR, OPEN_HOUR, compute_amount, local_slot

SEED = 2026
DEMO_ADMIN = ("admin@sportsms.local", "Asha Admin", "Admin@12345")
DEMO_CUSTOMER_PASSWORD = "Player@12345"

SPORTS = ["Badminton", "Tennis", "Football", "Basketball", "Table Tennis", "Squash", "Volleyball"]

FACILITIES = [
    # name, city, phone, address, [(court_name, sport, rate, active)]
    ("Smash Arena", "Bengaluru", "+91 80 4110 2201", "12 Outer Ring Rd, HSR Layout",
     [("Badminton Court 1", "Badminton", 400, True), ("Badminton Court 2", "Badminton", 400, True),
      ("Badminton Court 3", "Badminton", 450, True), ("Squash Court A", "Squash", 600, True)]),
    ("Greenfield Sports Club", "Bengaluru", "+91 80 4220 3302", "88 Bannerghatta Main Rd",
     [("Tennis Court 1", "Tennis", 800, True), ("Tennis Court 2", "Tennis", 750, True),
      ("5-a-side Turf", "Football", 1800, True), ("Basketball Half Court", "Basketball", 700, False)]),
    ("Royal Mysore Gymkhana", "Mysuru", "+91 821 255 4403", "3 Lalitha Mahal Rd, Nazarbad",
     [("Centre Court", "Tennis", 650, True), ("TT Table 1", "Table Tennis", 200, True),
      ("TT Table 2", "Table Tennis", 200, True), ("Indoor Basketball", "Basketball", 900, True)]),
    ("Coastal Turf Park", "Mangaluru", "+91 824 242 5504", "21 Lighthouse Hill Rd, Hampankatta",
     [("Main Turf", "Football", 2000, True), ("Practice Turf", "Football", 1500, True),
      ("Shuttle Court 1", "Badminton", 350, True)]),
    # A brand-new facility with courts but no bookings yet (useful for LEFT JOIN demos).
    ("Hubli Racquet Centre", "Hubballi", "+91 836 236 6605", "5 Vidyanagar Main Rd",
     [("Court East", "Badminton", 300, True), ("Court West", "Squash", 500, True)]),
]

CUSTOMERS = [
    "Aarav Sharma", "Diya Rao", "Kabir Menon", "Meera Iyer", "Rohan Gupta", "Sneha Kulkarni",
    "Vikram Hegde", "Ananya Shetty", "Arjun Nair", "Ishita Bhat", "Karthik Reddy", "Pooja Desai",
    # The last three never book anything (users without bookings).
    "Nikhil Joshi", "Tara Pillai", "Zoya Khan",
]

REVIEW_COMMENTS = {
    5: ["Excellent court, well maintained!", "Perfect lighting and surface.", "Best place in town."],
    4: ["Good experience overall.", "Nice court, slightly crowded parking.", "Would book again."],
    3: ["Average. Changing rooms need work.", "Okay for the price.", ""],
    2: ["Surface was uneven.", "Lights flickered during the game."],
    1: ["Court was double-booked at the desk, very poor.", "Dirty and poorly maintained."],
}


class Command(BaseCommand):
    help = "Populate the database with deterministic sample data."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="TRUNCATE all application tables first (destructive, asks for confirmation).")
        parser.add_argument("--noinput", action="store_true", help="Do not prompt for confirmation with --reset.")
        parser.add_argument("--bulk", type=int, default=0,
                            help="Additionally generate N historical bookings (for EXPLAIN/index demos).")

    def handle(self, *args, **opts):
        if opts["reset"]:
            if not opts["noinput"]:
                answer = input(f"This will DELETE all data in database "
                               f"'{connection.settings_dict['NAME']}'. Type 'yes' to continue: ")
                if answer.strip().lower() != "yes":
                    raise CommandError("Aborted.")
            with connection.cursor() as cur:
                cur.execute("TRUNCATE reviews, payments, maintenance, bookings, courts, sports, facilities, "
                            "users, django_admin_log, django_session RESTART IDENTITY CASCADE")
            self.stdout.write(self.style.WARNING("Application tables truncated."))
        elif Facility.objects.exists() or User.objects.exists():
            raise CommandError("Database already contains data. Use --reset to wipe and re-seed explicitly.")

        rng = random.Random(SEED)
        with transaction.atomic():
            counts = self._seed(rng)
            if opts["bulk"]:
                counts["bulk bookings"] = self._bulk(rng, opts["bulk"])
        with connection.cursor() as cur:
            cur.execute("ANALYZE")  # refresh planner statistics for EXPLAIN demos
        for k, v in counts.items():
            self.stdout.write(f"  {k:<16} {v}")
        self.stdout.write(self.style.SUCCESS("Seed complete."))
        self.stdout.write(f"  admin login:    {DEMO_ADMIN[0]} / {DEMO_ADMIN[2]}")
        self.stdout.write(f"  customer login: aarav.sharma@example.com / {DEMO_CUSTOMER_PASSWORD}")

    # ------------------------------------------------------------------
    def _seed(self, rng):
        now = timezone.now()
        today = timezone.localdate()

        User.objects.create_superuser(email=DEMO_ADMIN[0], name=DEMO_ADMIN[1], password=DEMO_ADMIN[2],
                                      created_at=now - timedelta(days=120))
        # Hash once (PBKDF2 is deliberately slow) and reuse for all demo customers.
        customer_hash = make_password(DEMO_CUSTOMER_PASSWORD)
        customers = []
        for i, full_name in enumerate(CUSTOMERS):
            email = full_name.lower().replace(" ", ".") + "@example.com"
            customers.append(User(name=full_name, email=email, password=customer_hash,
                                  role=User.Role.CUSTOMER, created_at=now - timedelta(days=100 - i * 5)))
        customers = User.objects.bulk_create(customers)
        bookers = customers[:12]

        sports = {name: Sport.objects.create(name=name) for name in SPORTS}

        courts = []
        for fname, city, phone, address, court_specs in FACILITIES:
            facility = Facility.objects.create(name=fname, city=city, phone=phone, address=address)
            for cname, sport, rate, active in court_specs:
                courts.append(Court.objects.create(facility=facility, sport=sports[sport], court_name=cname,
                                                   hourly_rate=Decimal(rate), is_active=active))
        bookable = [c for c in courts if c.facility.name != "Hubli Racquet Centre"]

        taken = set()  # (court_id, date, hour) already used by a booking or maintenance

        def reserve(court, day, hour, hours):
            cells = {(court.pk, day, h) for h in range(hour, hour + hours)}
            if cells & taken:
                return False
            taken.update(cells)
            return True

        # Maintenance windows: some past, some upcoming.
        maint_specs = [
            (-15, 6, 4, "Resurfacing of court floor"), (-9, 14, 3, "Net and post replacement"),
            (-4, 6, 2, "Floodlight repair"), (-2, 18, 4, "Deep cleaning"),
            (1, 6, 3, "Line re-painting"), (3, 12, 4, "Turf grooming"),
            (6, 6, 6, "Annual safety inspection"), (9, 15, 2, "Air-conditioning service"),
        ]
        maintenance_count = 0
        for i, (offset, hour, hours, reason) in enumerate(maint_specs):
            court = bookable[(i * 5) % len(bookable)]
            day = today + timedelta(days=offset)
            if reserve(court, day, hour, hours):
                start, end = local_slot(day, hour, hours)
                Maintenance.objects.create(court=court, start_time=start, end_time=end, reason=reason)
                maintenance_count += 1

        bookings = payments = reviews = 0
        online_methods = ["upi", "upi", "card", "netbanking"]
        target = 90
        attempts = 0
        while bookings < target and attempts < 5000:
            attempts += 1
            court = rng.choice([c for c in bookable if c.is_active] + bookable[:3])  # popular courts weighted
            if not court.is_active:
                continue
            day = today + timedelta(days=rng.randint(-25, 12))
            hours = rng.choice([1, 1, 1, 2, 2, 3])
            hour = rng.randint(OPEN_HOUR, CLOSE_HOUR - hours)
            start, end = local_slot(day, hour, hours)
            user = rng.choice(bookers)
            if start <= now < end:
                continue  # keep the demo simple: no booking in progress right now
            if not reserve(court, day, hour, hours):
                continue
            past = end <= now
            r = rng.random()
            if past:
                status = "completed" if r < 0.72 else ("cancelled" if r < 0.87 else "confirmed")
            else:
                status = "confirmed" if r < 0.6 else ("pending" if r < 0.85 else "cancelled")
            created = start - timedelta(days=rng.randint(1, 10), hours=rng.randint(0, 12))
            if created > now:
                created = now - timedelta(hours=rng.randint(1, 48))
            booking = Booking.objects.create(user=user, court=court, start_time=start, end_time=end,
                                             total_amount=compute_amount(court.hourly_rate, start, end),
                                             status=status, created_at=created)
            bookings += 1

            payment = self._payment_for(rng, booking, created, online_methods)
            if payment:
                payment.save(force_insert=True)
                payments += 1
            if status == "completed" and rng.random() < 0.6:
                rating = rng.choices([5, 4, 3, 2, 1], weights=[35, 35, 15, 10, 5])[0]
                Review.objects.create(booking=booking, rating=rating,
                                      comment=rng.choice(REVIEW_COMMENTS[rating]),
                                      created_at=end + timedelta(hours=rng.randint(1, 30)))
                reviews += 1

        return {"users": User.objects.count(), "sports": len(sports), "facilities": len(FACILITIES),
                "courts": len(courts), "bookings": bookings, "payments": payments, "reviews": reviews,
                "maintenance": maintenance_count}

    @staticmethod
    def _payment_for(rng, booking, created, online_methods):
        """Payment row consistent with the booking status (or None = never paid)."""
        amt = booking.total_amount
        paid_at = created + timedelta(minutes=rng.randint(1, 30))
        s = booking.status
        if s in ("completed", "confirmed"):
            if rng.random() < 0.15:  # paid in cash at the venue
                if booking.end_time <= timezone.now():
                    return Payment(booking=booking, amount=amt, payment_method="cash", payment_status="paid",
                                   paid_at=booking.start_time)
                return Payment(booking=booking, amount=amt, payment_method="cash", payment_status="pending")
            return Payment(booking=booking, amount=amt, payment_method=rng.choice(online_methods),
                           payment_status="paid", paid_at=paid_at)
        if s == "pending":
            if rng.random() < 0.4:  # a failed online attempt; user may retry
                return Payment(booking=booking, amount=amt, payment_method=rng.choice(online_methods),
                               payment_status="failed")
            return None
        # cancelled
        r = rng.random()
        if r < 0.5:
            return Payment(booking=booking, amount=amt, payment_method=rng.choice(online_methods),
                           payment_status="refunded", paid_at=paid_at)
        if r < 0.7:
            return Payment(booking=booking, amount=amt, payment_method="cash", payment_status="cancelled")
        return None

    def _bulk(self, rng, n):
        """Historical completed bookings on distinct (court, day, hour) cells far in the past."""
        today = timezone.localdate()
        courts = list(Court.objects.filter(is_active=True))
        users = list(User.objects.filter(role="customer").order_by("user_id")[:12])
        rows, made = [], 0
        day_offset = 30
        while made < n:
            day = today - timedelta(days=day_offset)
            for court in courts:
                for hour in range(OPEN_HOUR, CLOSE_HOUR):
                    if made >= n:
                        break
                    if rng.random() < 0.55:
                        continue
                    start, end = local_slot(day, hour, 1)
                    status = "completed" if rng.random() < 0.9 else "cancelled"
                    rows.append(Booking(user=rng.choice(users), court=court, start_time=start, end_time=end,
                                        total_amount=court.hourly_rate, status=status,
                                        created_at=start - timedelta(days=2)))
                    made += 1
            day_offset += 1
        created = Booking.objects.bulk_create(rows, batch_size=2000)
        pays = [Payment(booking=b, amount=b.total_amount, payment_method=rng.choice(["upi", "card", "cash"]),
                        payment_status="paid" if b.status == "completed" else "refunded",
                        paid_at=b.created_at) for b in created]
        Payment.objects.bulk_create(pays, batch_size=2000)
        return made
