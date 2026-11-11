"""
Business logic. Every operation that changes more than one row runs inside a
single transaction (transaction.atomic) so it either fully commits or fully
rolls back.

Concurrency strategy for schedule changes on a court:
  1. SELECT ... FOR UPDATE on the court row  -> serialises bookings/maintenance per court.
  2. A friendly application-level overlap check (gives a clear error message).
  3. The database is the final authority: the EXCLUDE constraint
     `bookings_no_overlap` and the maintenance triggers reject anything that slips through
     (e.g. a raw SQL insert that bypasses this module).
"""
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Booking, Court, Maintenance, Payment, Review

OPEN_HOUR = 6      # facilities accept bookings from 06:00 ...
CLOSE_HOUR = 23    # ... until 23:00 (local time)
MAX_HOURS = 4      # longest booking a customer may make through the UI


class BookingError(Exception):
    """A business-rule violation that should be shown to the user."""


CONSTRAINT_MESSAGES = {
    "bookings_no_overlap": "That court is already booked for an overlapping time.",
    "bookings_not_during_maintenance": "The court is under maintenance during that time.",
    "bookings_time_order": "End time must be after start time.",
    "maintenance_no_overlap": "This overlaps another maintenance window for the court.",
    "maintenance_not_during_booking": "The court has active bookings in that window.",
    "maintenance_pkey": "A maintenance window already starts at that time for this court.",
    "maintenance_time_order": "End time must be after start time.",
    "reviews_pkey": "This booking has already been reviewed.",
    "reviews_rating_1_to_5": "Rating must be between 1 and 5.",
}


def constraint_name(exc: IntegrityError):
    diag = getattr(exc.__cause__, "diag", None)
    return getattr(diag, "constraint_name", None)


def friendly_integrity_error(exc: IntegrityError) -> BookingError:
    name = constraint_name(exc)
    return BookingError(CONSTRAINT_MESSAGES.get(name, f"Database rejected the change ({name or 'integrity error'})."))


# ------------------------------------------------------------------ helpers
def local_slot(day, hour, hours=1):
    """Convert (date, start hour, duration) in local time to aware datetimes."""
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time(hour=hour)), tz)
    return start, start + timedelta(hours=hours)


def compute_amount(hourly_rate: Decimal, start, end) -> Decimal:
    hours = Decimal((end - start).total_seconds()) / Decimal(3600)
    return (hourly_rate * hours).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _overlapping_bookings(court_id, start, end):
    return Booking.objects.filter(court_id=court_id, start_time__lt=end, end_time__gt=start).exclude(
        status=Booking.Status.CANCELLED)


def _overlapping_maintenance(court_id, start, end):
    return Maintenance.objects.filter(court_id=court_id, start_time__lt=end, end_time__gt=start)


def _validate_customer_window(start, end):
    if end <= start:
        raise BookingError("End time must be after start time.")
    if start <= timezone.now():
        raise BookingError("Bookings must start in the future.")
    if end - start > timedelta(hours=MAX_HOURS):
        raise BookingError(f"A booking can be at most {MAX_HOURS} hours long.")
    local_start, local_end = timezone.localtime(start), timezone.localtime(end)
    if (local_start.hour < OPEN_HOUR or local_end.date() != local_start.date()
            or (local_end.hour, local_end.minute) > (CLOSE_HOUR, 0)):
        raise BookingError(f"Bookings must be between {OPEN_HOUR:02d}:00 and {CLOSE_HOUR:02d}:00 on one day.")


# ----------------------------------------------------------------- bookings
def create_booking(user, court_id, start, end) -> Booking:
    """Create a pending booking. Price is always computed here, never taken from the client."""
    _validate_customer_window(start, end)
    with transaction.atomic():
        try:
            court = Court.objects.select_for_update().get(pk=court_id)  # row lock on the court
        except Court.DoesNotExist:
            raise BookingError("That court does not exist.")
        if not court.is_active:
            raise BookingError("This court is currently not accepting bookings.")
        if _overlapping_maintenance(court.pk, start, end).exists():
            raise BookingError(CONSTRAINT_MESSAGES["bookings_not_during_maintenance"])
        if _overlapping_bookings(court.pk, start, end).exists():
            raise BookingError(CONSTRAINT_MESSAGES["bookings_no_overlap"])
        booking = Booking(user=user, court=court, start_time=start, end_time=end,
                          total_amount=compute_amount(court.hourly_rate, start, end),
                          status=Booking.Status.PENDING)
        try:
            with transaction.atomic():  # savepoint, so the outer transaction stays usable
                booking.save()
        except IntegrityError as exc:
            raise friendly_integrity_error(exc)
    return booking


def pay_booking(user, booking_id, method, simulate_failure=False) -> Payment:
    """Simulated payment. Booking and payment rows change together atomically."""
    if method not in Payment.Method.values:
        raise BookingError("Unknown payment method.")
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking_id)
        if booking.user_id != user.pk:
            raise BookingError("You can only pay for your own bookings.")
        if booking.status != Booking.Status.PENDING:
            raise BookingError("Only bookings awaiting payment can be paid.")
        payment = Payment.objects.filter(booking=booking).first() or Payment(booking=booking)
        payment.amount = booking.total_amount
        payment.payment_method = method
        payment.paid_at = None
        if method == Payment.Method.CASH:
            payment.payment_status = Payment.Status.PENDING      # collected at the venue later
            booking.status = Booking.Status.CONFIRMED
        elif simulate_failure:
            payment.payment_status = Payment.Status.FAILED        # booking stays pending; may retry
        else:
            payment.payment_status = Payment.Status.PAID
            payment.paid_at = timezone.now()
            booking.status = Booking.Status.CONFIRMED
        payment.save()
        booking.save(update_fields=["status"])
    return payment


def cancel_booking(actor, booking_id) -> Booking:
    """Cancel a booking; a paid payment becomes refunded, a pending one is cancelled."""
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking_id)
        if not actor.is_admin and booking.user_id != actor.pk:
            raise BookingError("You can only cancel your own bookings.")
        if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED):
            raise BookingError("Only pending or confirmed bookings can be cancelled.")
        if not actor.is_admin and booking.start_time <= timezone.now():
            raise BookingError("Bookings can only be cancelled before they start.")
        _cancel_locked(booking)
    return booking


def _cancel_locked(booking):
    booking.status = Booking.Status.CANCELLED
    booking.save(update_fields=["status"])
    payment = Payment.objects.select_for_update().filter(booking=booking).first()
    if payment:
        if payment.payment_status == Payment.Status.PAID:
            payment.payment_status = Payment.Status.REFUNDED  # paid_at stays: money was received
        elif payment.payment_status == Payment.Status.PENDING:
            payment.payment_status = Payment.Status.CANCELLED
        payment.save(update_fields=["payment_status"])


def mark_cash_received(booking_id) -> Payment:
    with transaction.atomic():
        payment = Payment.objects.select_for_update().select_related("booking").get(pk=booking_id)
        if payment.payment_status != Payment.Status.PENDING:
            raise BookingError("Only pending payments can be marked as received.")
        payment.payment_status = Payment.Status.PAID
        payment.paid_at = timezone.now()
        payment.save(update_fields=["payment_status", "paid_at"])
    return payment


def mark_completed(booking_id) -> Booking:
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking_id)
        if booking.status != Booking.Status.CONFIRMED or not booking.has_ended:
            raise BookingError("Only confirmed bookings that have ended can be completed.")
        booking.status = Booking.Status.COMPLETED
        booking.save(update_fields=["status"])
    return booking


def complete_past_bookings() -> int:
    """Bulk UPDATE: confirmed bookings whose end_time has passed become completed."""
    return Booking.objects.filter(status=Booking.Status.CONFIRMED, end_time__lte=timezone.now()).update(
        status=Booking.Status.COMPLETED)


# ------------------------------------------------------------------ reviews
def can_review(user, booking) -> bool:
    return (booking.user_id == user.pk
            and booking.status in (Booking.Status.CONFIRMED, Booking.Status.COMPLETED)
            and booking.has_ended
            and not Review.objects.filter(pk=booking.pk).exists())


def submit_review(user, booking_id, rating, comment="") -> Review:
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking_id)
        if booking.user_id != user.pk:
            raise BookingError("You can only review your own bookings.")
        if booking.status not in (Booking.Status.CONFIRMED, Booking.Status.COMPLETED) or not booking.has_ended:
            raise BookingError("You can review a booking only after it has been played.")
        review = Review(booking=booking, rating=rating, comment=comment.strip())
        try:
            with transaction.atomic():
                review.save(force_insert=True)  # INSERT only: never overwrite an existing review
        except IntegrityError as exc:
            raise friendly_integrity_error(exc)
    return review


# -------------------------------------------------------------- maintenance
def schedule_maintenance(court_id, start, end, reason, cancel_conflicts=False):
    """Insert a maintenance window. Policy: conflicting active bookings block it,
    unless the admin explicitly asks to cancel (and refund) them in the same transaction."""
    if end <= start:
        raise BookingError("End time must be after start time.")
    with transaction.atomic():
        court = Court.objects.select_for_update().get(pk=court_id)
        if _overlapping_maintenance(court.pk, start, end).exists():
            raise BookingError(CONSTRAINT_MESSAGES["maintenance_no_overlap"])
        conflicts = list(_overlapping_bookings(court.pk, start, end).select_for_update())
        if conflicts and not cancel_conflicts:
            ids = ", ".join(f"#{b.pk}" for b in conflicts)
            raise BookingError(f"Active bookings overlap this window ({ids}). "
                               "Tick 'cancel conflicting bookings' to cancel and refund them.")
        for booking in conflicts:
            _cancel_locked(booking)
        window = Maintenance(court=court, start_time=start, end_time=end, reason=reason)
        try:
            with transaction.atomic():
                window.save(force_insert=True)
        except IntegrityError as exc:
            raise friendly_integrity_error(exc)
    return window, conflicts


# ------------------------------------------------------------- availability
def court_availability(court, day):
    """Hourly slots for one local day: free / booked / maintenance / past."""
    day_start, _ = local_slot(day, 0)
    day_end = day_start + timedelta(days=1)
    bookings = list(_overlapping_bookings(court.pk, day_start, day_end).values_list("start_time", "end_time"))
    windows = list(_overlapping_maintenance(court.pk, day_start, day_end).values_list("start_time", "end_time"))
    now = timezone.now()
    slots = []
    for hour in range(OPEN_HOUR, CLOSE_HOUR):
        s, e = local_slot(day, hour)
        if any(ms < e and me > s for ms, me in windows):
            state = "maintenance"
        elif any(bs < e and be > s for bs, be in bookings):
            state = "booked"
        elif s <= now:
            state = "past"
        else:
            state = "free"
        slots.append({"hour": hour, "label": f"{hour:02d}:00", "state": state})
    return slots
