"""
Relational schema for the Smart Sports Management System.

Every class below maps one entity of the ER diagram to one PostgreSQL table.
Table and column names are fixed explicitly (db_table / db_column) so that the
SQL you see in the DBMS Lab matches this file one-to-one.

    ER entity     -> table          primary key
    USER          -> users          user_id
    FACILITY      -> facilities     facility_id
    SPORT         -> sports         sport_id
    COURT         -> courts         court_id
    BOOKING       -> bookings       booking_id
    PAYMENT  (weak, 1:1 with BOOKING) -> payments    booking_id            (PK + FK)
    REVIEW   (weak, 1:1 with BOOKING) -> reviews     booking_id            (PK + FK)
    MAINTENANCE (weak, N:1 with COURT)-> maintenance (court_id, start_time) (composite PK)
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeBoundary, RangeOperators
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Func, Q
from django.db.models.functions import Lower
from django.utils import timezone


class TsTzRange(Func):
    """SQL: tstzrange(start_time, end_time, '[)') -- half-open time interval."""

    function = "TSTZRANGE"
    output_field = models.DateTimeField()  # only used inside constraint expressions


# --------------------------------------------------------------------------- USER
class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, name, password, role, **extra):
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email).lower(), name=name, role=role, **extra)
        user.set_password(password)  # Django PBKDF2 hashing -> stored in password_hash
        user.save(using=self._db)
        return user

    def create_user(self, email, name, password=None, **extra):
        return self._create(email, name, password, User.Role.CUSTOMER, **extra)

    def create_superuser(self, email, name, password=None, **extra):
        return self._create(email, name, password, User.Role.ADMIN, **extra)

    def get_by_natural_key(self, email):
        return self.get(email__iexact=email)


class User(AbstractBaseUser):
    """ER entity USER. Django's auth framework works on top of this table."""

    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        ADMIN = "admin", "Administrator"

    user_id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=100)
    email = models.EmailField(max_length=254, unique=True)
    # AbstractBaseUser calls this field "password"; we store it in a column named
    # password_hash to match the ER diagram. It always holds a salted hash.
    password = models.CharField("password hash", max_length=128, db_column="password_hash")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CUSTOMER)
    created_at = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True)  # implementation attribute (account lock)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        db_table = "users"
        ordering = ["user_id"]
        constraints = [
            # Emails are stored in canonical lower-case form, so the UNIQUE index on
            # email is effectively case-insensitive ('A@x.com' cannot sneak in).
            models.CheckConstraint(condition=Q(email=Lower("email")), name="users_email_lowercase"),
            models.CheckConstraint(condition=Q(role__in=["customer", "admin"]), name="users_role_valid"),
        ]

    def __str__(self):
        return f"{self.name} <{self.email}>"

    # Authorization is derived from the single `role` attribute.
    @property
    def is_admin(self):
        return self.is_active and self.role == self.Role.ADMIN

    @property
    def is_staff(self):  # used by django.contrib.admin
        return self.is_admin

    @property
    def is_superuser(self):
        return self.is_admin

    def has_perm(self, perm, obj=None):
        return self.is_admin

    def has_perms(self, perm_list, obj=None):
        return self.is_admin

    def has_module_perms(self, app_label):
        return self.is_admin


# ------------------------------------------------------------------------ FACILITY
class Facility(models.Model):
    facility_id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20)
    city = models.CharField(max_length=60)
    address = models.CharField(max_length=255)

    class Meta:
        db_table = "facilities"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["name", "city"], name="facilities_name_city_uniq"),
        ]
        verbose_name_plural = "facilities"

    def __str__(self):
        return f"{self.name} ({self.city})"


# --------------------------------------------------------------------------- SPORT
class Sport(models.Model):
    sport_id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=60)

    class Meta:
        db_table = "sports"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(Lower("name"), name="sports_name_lower_uniq")]

    def __str__(self):
        return self.name


# --------------------------------------------------------------------------- COURT
class Court(models.Model):
    court_id = models.BigAutoField(primary_key=True)
    # FACILITY contains COURT (1:N, total participation of COURT) -> NOT NULL FK.
    # DO_NOTHING in Django = plain FK in PostgreSQL (ON DELETE NO ACTION): the
    # database itself refuses to delete a facility that still has courts.
    facility = models.ForeignKey(Facility, on_delete=models.DO_NOTHING, related_name="courts",
                                 db_column="facility_id",
                                 db_index=False)  # covered by courts_facility_name_uniq (facility_id, court_name)
    # COURT played_on SPORT (N:1, total participation of COURT) -> NOT NULL FK.
    sport = models.ForeignKey(Sport, on_delete=models.DO_NOTHING, related_name="courts", db_column="sport_id")
    court_name = models.CharField(max_length=60)
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2)
    is_active = models.BooleanField(default=True)  # soft-deactivation keeps booking history intact

    class Meta:
        db_table = "courts"
        ordering = ["facility_id", "court_name"]
        constraints = [
            models.UniqueConstraint(fields=["facility", "court_name"], name="courts_facility_name_uniq"),
            models.CheckConstraint(condition=Q(hourly_rate__gt=0), name="courts_hourly_rate_positive"),
        ]

    def __str__(self):
        return f"{self.court_name} @ {self.facility.name}"


# ------------------------------------------------------------------------- BOOKING
class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending payment"
        CONFIRMED = "confirmed", "Confirmed"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    # Statuses that occupy the court (everything except cancelled).
    BLOCKING_STATUSES = (Status.PENDING, Status.CONFIRMED, Status.COMPLETED)

    booking_id = models.BigAutoField(primary_key=True)
    # USER places BOOKING (1:N). NO ACTION at DB level preserves booking history.
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING, related_name="bookings", db_column="user_id",
                             db_index=False)  # covered by bookings_user_start_idx (user_id, start_time)
    # BOOKING booked_for COURT (N:1).
    court = models.ForeignKey(Court, on_delete=models.DO_NOTHING, related_name="bookings", db_column="court_id")
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    # Snapshot of hourly_rate x duration at booking time (rates may change later).
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)

    class Meta:
        db_table = "bookings"
        ordering = ["-start_time"]
        constraints = [
            models.CheckConstraint(condition=Q(end_time__gt=F("start_time")), name="bookings_time_order"),
            models.CheckConstraint(
                condition=Q(end_time__lte=F("start_time") + timedelta(hours=12)),
                name="bookings_max_12_hours",
            ),
            models.CheckConstraint(condition=Q(total_amount__gte=0), name="bookings_amount_non_negative"),
            models.CheckConstraint(
                condition=Q(status__in=["pending", "confirmed", "completed", "cancelled"]),
                name="bookings_status_valid",
            ),
            # No two non-cancelled bookings of the same court may overlap in time.
            # EXCLUDE USING gist (court_id WITH =, tstzrange(start_time,end_time,'[)') WITH &&)
            #   WHERE (status <> 'cancelled')
            ExclusionConstraint(
                name="bookings_no_overlap",
                expressions=[
                    ("court", RangeOperators.EQUAL),
                    (TsTzRange("start_time", "end_time", RangeBoundary()), RangeOperators.OVERLAPS),
                ],
                condition=~Q(status="cancelled"),
            ),
        ]
        indexes = [
            # "My bookings" page: WHERE user_id = ? ORDER BY start_time DESC
            models.Index(fields=["user", "-start_time"], name="bookings_user_start_idx"),
            # Reports filtered by date range (revenue per month, upcoming bookings)
            models.Index(fields=["start_time"], name="bookings_start_idx"),
        ]

    def __str__(self):
        return f"Booking #{self.booking_id}"

    @property
    def duration_hours(self):
        return Decimal((self.end_time - self.start_time).total_seconds()) / Decimal(3600)

    @property
    def is_upcoming(self):
        return self.start_time > timezone.now()

    @property
    def has_ended(self):
        return self.end_time <= timezone.now()


# ------------------------------------------------------------------------- PAYMENT
class Payment(models.Model):
    """Weak entity identified by its owner BOOKING (identifying relationship settled_by, 1:1).

    The PK *is* the FK booking_id, so a booking can have at most one payment row.
    DB_CASCADE: the payment cannot exist without its booking (existence dependency).
    """

    class Method(models.TextChoices):
        UPI = "upi", "UPI"
        CARD = "card", "Card"
        NETBANKING = "netbanking", "Net banking"
        CASH = "cash", "Cash at venue"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"
        CANCELLED = "cancelled", "Cancelled"

    booking = models.OneToOneField(Booking, on_delete=models.DB_CASCADE, primary_key=True,
                                   related_name="payment", db_column="booking_id")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_at = models.DateTimeField(null=True, blank=True)
    payment_method = models.CharField(max_length=12, choices=Method.choices)
    payment_status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)

    class Meta:
        db_table = "payments"
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0), name="payments_amount_non_negative"),
            models.CheckConstraint(
                condition=Q(payment_method__in=["upi", "card", "netbanking", "cash"]),
                name="payments_method_valid",
            ),
            models.CheckConstraint(
                condition=Q(payment_status__in=["pending", "paid", "failed", "refunded", "cancelled"]),
                name="payments_status_valid",
            ),
            # paid_at is recorded exactly when money was received (paid or later refunded).
            models.CheckConstraint(
                condition=(Q(payment_status__in=["paid", "refunded"], paid_at__isnull=False)
                           | Q(~Q(payment_status__in=["paid", "refunded"]), paid_at__isnull=True)),
                name="payments_paid_at_consistent",
            ),
        ]

    def __str__(self):
        return f"Payment for booking #{self.booking_id}"


# -------------------------------------------------------------------------- REVIEW
class Review(models.Model):
    """Weak entity identified by BOOKING (reviewed_via, 1:1): one review per booking.

    The reviewer is not stored separately -- it is bookings.user_id. This avoids
    a redundant column and makes "reviewing someone else's booking" impossible to store.
    """

    booking = models.OneToOneField(Booking, on_delete=models.DB_CASCADE, primary_key=True,
                                   related_name="review", db_column="booking_id")
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "reviews"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(rating__gte=1, rating__lte=5), name="reviews_rating_1_to_5"),
        ]

    def __str__(self):
        return f"Review of booking #{self.booking_id} ({self.rating}/5)"


# --------------------------------------------------------------------- MAINTENANCE
class Maintenance(models.Model):
    """Weak entity owned by COURT (undergoes, 1:N). Partial key: start_time.

    Primary key = (court_id, start_time): the owner's key + the discriminator.
    """

    pk = models.CompositePrimaryKey("court_id", "start_time")
    court = models.ForeignKey(Court, on_delete=models.DB_CASCADE, related_name="maintenance_windows",
                              db_column="court_id", db_index=False)  # PK (court_id, start_time) covers it
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    reason = models.CharField(max_length=255)

    class Meta:
        db_table = "maintenance"
        ordering = ["start_time"]
        constraints = [
            models.CheckConstraint(condition=Q(end_time__gt=F("start_time")), name="maintenance_time_order"),
            ExclusionConstraint(
                name="maintenance_no_overlap",
                expressions=[
                    ("court", RangeOperators.EQUAL),
                    (TsTzRange("start_time", "end_time", RangeBoundary()), RangeOperators.OVERLAPS),
                ],
            ),
        ]
        verbose_name_plural = "maintenance"

    def __str__(self):
        return f"Maintenance on court {self.court_id} from {self.start_time:%Y-%m-%d %H:%M}"
