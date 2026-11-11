"""Administrator pages (/manage/...). Every view is protected by @admin_required on the server."""
from datetime import datetime
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services
from .forms import CourtForm, FacilityForm, MaintenanceForm, SportForm
from .models import Booking, Court, Facility, Maintenance, Payment, Review, Sport
from .reports import REPORTS, dashboard_stats, run_report


def admin_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_admin:
            raise PermissionDenied("Administrators only.")
        return view(request, *args, **kwargs)
    return wrapper


@admin_required
def manage_home(request):
    recent = Booking.objects.select_related("user", "court__facility").order_by("-created_at")[:8]
    return render(request, "manage/home.html", {"stats": dashboard_stats(), "recent": recent})


# ---------------------------------------------------------------- facilities
@admin_required
def facilities(request):
    rows = Facility.objects.annotate(courts_n=Count("courts", distinct=True)).order_by("name")
    return render(request, "manage/facilities.html", {"facilities": rows})


@admin_required
def facility_edit(request, facility_id=None):
    facility = get_object_or_404(Facility, pk=facility_id) if facility_id else None
    form = FacilityForm(request.POST or None, instance=facility)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        messages.success(request, f"Facility '{obj.name}' saved (facility_id={obj.pk}).")
        return redirect("manage_facilities")
    return render(request, "manage/form.html", {"form": form, "title": "Edit facility" if facility else "New facility",
                                                "back": "manage_facilities"})


@admin_required
@require_POST
def facility_delete(request, facility_id):
    facility = get_object_or_404(Facility, pk=facility_id)
    if facility.courts.exists():
        messages.error(request, "This facility still has courts. The foreign key courts.facility_id "
                                "(ON DELETE NO ACTION) prevents deleting it; deactivate its courts instead.")
    else:
        facility.delete()
        messages.success(request, "Facility deleted.")
    return redirect("manage_facilities")


# -------------------------------------------------------------------- courts
@admin_required
def courts(request):
    rows = (Court.objects.select_related("facility", "sport")
            .annotate(bookings_n=Count("bookings", filter=~Q(bookings__status="cancelled")))
            .order_by("facility__name", "court_name"))
    return render(request, "manage/courts.html", {"courts": rows})


@admin_required
def court_edit(request, court_id=None):
    court = get_object_or_404(Court, pk=court_id) if court_id else None
    form = CourtForm(request.POST or None, instance=court)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        messages.success(request, f"Court '{obj.court_name}' saved (court_id={obj.pk}).")
        return redirect("manage_courts")
    return render(request, "manage/form.html", {"form": form, "title": "Edit court" if court else "New court",
                                                "back": "manage_courts"})


@admin_required
@require_POST
def court_toggle(request, court_id):
    court = get_object_or_404(Court, pk=court_id)
    court.is_active = not court.is_active
    court.save(update_fields=["is_active"])
    messages.success(request, f"{court.court_name} is now {'active' if court.is_active else 'inactive'}.")
    return redirect("manage_courts")


# -------------------------------------------------------------------- sports
@admin_required
def sports(request):
    form = SportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Sport added.")
        return redirect("manage_sports")
    rows = Sport.objects.annotate(courts_n=Count("courts")).order_by("name")
    return render(request, "manage/sports.html", {"sports": rows, "form": form})


# ------------------------------------------------------------------ bookings
@admin_required
def bookings(request):
    qs = Booking.objects.select_related("user", "court__facility", "court__sport", "payment").order_by("-start_time")
    status = request.GET.get("status", "")
    facility = request.GET.get("facility", "")
    if status in Booking.Status.values:
        qs = qs.filter(status=status)
    if facility.isdigit():
        qs = qs.filter(court__facility_id=int(facility))
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "manage/bookings.html", {
        "page": page, "statuses": Booking.Status.choices, "facilities": Facility.objects.all(),
        "selected_status": status, "selected_facility": facility, "now": timezone.now()})


@admin_required
@require_POST
def booking_action(request, booking_id):
    action = request.POST.get("action")
    try:
        if action == "cancel":
            services.cancel_booking(request.user, booking_id)
            messages.success(request, f"Booking #{booking_id} cancelled (paid payments refunded).")
        elif action == "complete":
            services.mark_completed(booking_id)
            messages.success(request, f"Booking #{booking_id} marked completed.")
        elif action == "complete_all":
            n = services.complete_past_bookings()
            messages.success(request, f"{n} past confirmed booking(s) marked completed.")
        else:
            messages.error(request, "Unknown action.")
    except services.BookingError as e:
        messages.error(request, str(e))
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/manage/") else "manage_bookings")  # no open redirects


# ---------------------------------------------------------------- payments
@admin_required
def payments(request):
    qs = Payment.objects.select_related("booking__user", "booking__court__facility").order_by("-booking_id")
    status = request.GET.get("status", "")
    if status in Payment.Status.values:
        qs = qs.filter(payment_status=status)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "manage/payments.html", {"page": page, "statuses": Payment.Status.choices,
                                                    "selected_status": status})


@admin_required
@require_POST
def payment_received(request, booking_id):
    try:
        services.mark_cash_received(booking_id)
        messages.success(request, f"Cash payment for booking #{booking_id} recorded.")
    except (services.BookingError, Payment.DoesNotExist) as e:
        messages.error(request, str(e))
    return redirect("manage_payments")


# ---------------------------------------------------------------- reviews
@admin_required
def reviews(request):
    qs = Review.objects.select_related("booking__user", "booking__court__facility").order_by("-created_at")
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "manage/reviews.html", {"page": page})


# ------------------------------------------------------------ maintenance
@admin_required
def maintenance(request):
    form = MaintenanceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            window, cancelled = services.schedule_maintenance(d["court"].pk, d["start_time"], d["end_time"],
                                                              d["reason"], d["cancel_conflicts"])
        except services.BookingError as e:
            messages.error(request, str(e))
        else:
            extra = f" {len(cancelled)} conflicting booking(s) were cancelled." if cancelled else ""
            messages.success(request, f"Maintenance scheduled for {window.court.court_name}.{extra}")
            return redirect("manage_maintenance")
    rows = Maintenance.objects.select_related("court__facility").order_by("-start_time")
    return render(request, "manage/maintenance.html", {"form": form, "windows": rows, "now": timezone.now()})


@admin_required
@require_POST
def maintenance_delete(request):
    # Weak entity: identified by its composite key (court_id, start_time).
    try:
        court_id = int(request.POST["court_id"])
        start = datetime.fromisoformat(request.POST["start_time"])
    except (KeyError, ValueError):
        messages.error(request, "Invalid maintenance key.")
        return redirect("manage_maintenance")
    deleted, _ = Maintenance.objects.filter(court_id=court_id, start_time=start).delete()
    messages.success(request, "Maintenance window removed." if deleted else "Nothing deleted.")
    return redirect("manage_maintenance")


# ---------------------------------------------------------------- reports
@admin_required
def reports(request):
    results = [run_report(k) for k in REPORTS]
    return render(request, "manage/reports.html", {"reports": results})
