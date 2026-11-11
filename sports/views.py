"""Public and customer-facing views. Business rules live in services.py."""
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, F, Min, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services
from .forms import BookingForm, PaymentForm, RegisterForm, ReviewForm
from .models import Booking, Court, Facility, Payment, Review, Sport
from .reports import dashboard_stats


def home(request):
    facilities = (Facility.objects.annotate(court_count=Count("courts", filter=Q(courts__is_active=True), distinct=True),
                                            min_rate=Min("courts__hourly_rate", filter=Q(courts__is_active=True)))
                  .order_by("facility_id"))
    return render(request, "sports/home.html", {"facilities": facilities, "stats": dashboard_stats(),
                                                "sports": Sport.objects.all()})


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, f"Welcome, {user.name}! Your account was created.")
        return redirect("dashboard")
    return render(request, "registration/register.html", {"form": form})


def facility_list(request):
    city = request.GET.get("city", "")
    sport_id = request.GET.get("sport", "")
    qs = Facility.objects.annotate(
        court_count=Count("courts", filter=Q(courts__is_active=True), distinct=True),
        min_rate=Min("courts__hourly_rate", filter=Q(courts__is_active=True)),
    )
    if city:
        qs = qs.filter(city=city)
    if sport_id.isdigit():
        qs = qs.filter(courts__sport_id=int(sport_id), courts__is_active=True).distinct()
    ratings = {row["fid"]: row["avg"] for row in
               Review.objects.values(fid=F("booking__court__facility_id")).annotate(avg=Avg("rating"))}
    facilities = list(qs.order_by("name"))
    for f in facilities:
        f.avg_rating = ratings.get(f.pk)
    return render(request, "sports/facility_list.html", {
        "facilities": facilities, "cities": Facility.objects.values_list("city", flat=True).distinct().order_by("city"),
        "sports": Sport.objects.all(), "selected_city": city, "selected_sport": sport_id,
    })


def facility_detail(request, facility_id):
    facility = get_object_or_404(Facility, pk=facility_id)
    courts = (facility.courts.select_related("sport")
              .annotate(avg_rating=Avg("bookings__review__rating"), reviews=Count("bookings__review"))
              .order_by("court_name"))
    recent_reviews = (Review.objects.filter(booking__court__facility=facility)
                      .select_related("booking__user", "booking__court")[:5])
    return render(request, "sports/facility_detail.html",
                  {"facility": facility, "courts": courts, "recent_reviews": recent_reviews})


def court_detail(request, court_id):
    court = get_object_or_404(Court.objects.select_related("facility", "sport"), pk=court_id)
    try:
        day = date.fromisoformat(request.GET["date"]) if request.GET.get("date") else None
    except ValueError:
        day = None
    day = day or timezone.localdate()
    form = BookingForm(request.POST or None, initial={"date": day})
    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect(f"/accounts/login/?next={request.path}")
        if form.is_valid():
            start, end = services.local_slot(form.cleaned_data["date"], form.cleaned_data["start_hour"],
                                             form.cleaned_data["hours"])
            try:
                booking = services.create_booking(request.user, court.pk, start, end)
            except services.BookingError as e:
                messages.error(request, str(e))
                day = form.cleaned_data["date"]
            else:
                messages.success(request, f"Booking #{booking.pk} created for ₹{booking.total_amount}. "
                                          "Complete the payment to confirm it.")
                return redirect("booking_detail", booking_id=booking.pk)
    upcoming_maintenance = court.maintenance_windows.filter(end_time__gt=timezone.now())[:5]
    return render(request, "sports/court_detail.html", {
        "court": court, "form": form, "day": day, "slots": services.court_availability(court, day),
        "prev_day": day - timedelta(days=1), "next_day": day + timedelta(days=1),
        "today": timezone.localdate(), "maintenance": upcoming_maintenance,
    })


@login_required
def dashboard(request):
    if request.user.is_admin:
        return redirect("manage_home")
    mine = Booking.objects.filter(user=request.user).select_related("court__facility", "court__sport", "payment")
    now = timezone.now()
    upcoming = mine.filter(start_time__gt=now).exclude(status="cancelled").order_by("start_time")
    to_review = [b for b in mine.filter(end_time__lte=now, status__in=["confirmed", "completed"], review__isnull=True)[:5]]
    summary = mine.aggregate(total=Count("booking_id"), cancelled=Count("booking_id", filter=Q(status="cancelled")))
    return render(request, "sports/dashboard.html",
                  {"upcoming": upcoming, "to_review": to_review, "summary": summary})


@login_required
def booking_list(request):
    status = request.GET.get("status", "")
    qs = (Booking.objects.filter(user=request.user)
          .select_related("court__facility", "court__sport", "payment", "review").order_by("-start_time"))
    if status in Booking.Status.values:
        qs = qs.filter(status=status)
    return render(request, "sports/booking_list.html",
                  {"bookings": qs, "statuses": Booking.Status.choices, "selected_status": status})


def _own_booking(request, booking_id):
    booking = get_object_or_404(Booking.objects.select_related("court__facility", "court__sport", "user"),
                                pk=booking_id)
    if booking.user_id != request.user.pk and not request.user.is_admin:
        raise Http404  # do not reveal that someone else's booking exists
    return booking


@login_required
def booking_detail(request, booking_id):
    booking = _own_booking(request, booking_id)
    payment = Payment.objects.filter(pk=booking.pk).first()
    review = Review.objects.filter(pk=booking.pk).first()
    return render(request, "sports/booking_detail.html", {
        "booking": booking, "payment": payment, "review": review,
        "pay_form": PaymentForm(), "review_form": ReviewForm(),
        "can_pay": booking.user_id == request.user.pk and booking.status == "pending",
        "can_cancel": booking.status in ("pending", "confirmed") and booking.start_time > timezone.now()
                      and booking.user_id == request.user.pk,
        "can_review": services.can_review(request.user, booking),
    })


@login_required
@require_POST
def booking_pay(request, booking_id):
    _own_booking(request, booking_id)
    form = PaymentForm(request.POST)
    if form.is_valid():
        try:
            payment = services.pay_booking(request.user, booking_id, form.cleaned_data["payment_method"],
                                           form.cleaned_data["simulate_failure"])
        except services.BookingError as e:
            messages.error(request, str(e))
        else:
            if payment.payment_status == "failed":
                messages.error(request, "Payment was declined (simulated). The booking is still pending; try again.")
            elif payment.payment_status == "pending":
                messages.success(request, "Booking confirmed. Please pay in cash at the venue.")
            else:
                messages.success(request, "Payment successful. Your booking is confirmed!")
    return redirect("booking_detail", booking_id=booking_id)


@login_required
@require_POST
def booking_cancel(request, booking_id):
    _own_booking(request, booking_id)
    try:
        services.cancel_booking(request.user, booking_id)
    except services.BookingError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "Booking cancelled. Any payment made has been marked as refunded.")
    return redirect("booking_detail", booking_id=booking_id)


@login_required
@require_POST
def booking_review(request, booking_id):
    _own_booking(request, booking_id)
    form = ReviewForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please choose a rating between 1 and 5.")
    else:
        try:
            services.submit_review(request.user, booking_id, form.cleaned_data["rating"], form.cleaned_data["comment"])
        except services.BookingError as e:
            messages.error(request, str(e))
        else:
            messages.success(request, "Thanks for your review!")
    return redirect("booking_detail", booking_id=booking_id)
