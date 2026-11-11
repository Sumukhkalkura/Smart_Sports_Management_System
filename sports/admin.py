"""Django admin for quick CRUD. (MAINTENANCE has a composite primary key, which the
Django admin does not support, so it is managed at /manage/maintenance/ instead.)"""
from django.contrib import admin

from .models import Booking, Court, Facility, Payment, Review, Sport, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("user_id", "name", "email", "role", "is_active", "created_at")
    list_filter = ("role", "is_active")
    search_fields = ("name", "email")
    exclude = ("password",)
    readonly_fields = ("last_login",)

    def has_delete_permission(self, request, obj=None):
        return obj is None or not obj.bookings.exists()


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ("facility_id", "name", "city", "phone")
    search_fields = ("name", "city")

    def has_delete_permission(self, request, obj=None):
        return obj is None or not obj.courts.exists()


@admin.register(Sport)
class SportAdmin(admin.ModelAdmin):
    list_display = ("sport_id", "name")


@admin.register(Court)
class CourtAdmin(admin.ModelAdmin):
    list_display = ("court_id", "court_name", "facility", "sport", "hourly_rate", "is_active")
    list_filter = ("is_active", "sport", "facility")

    def has_delete_permission(self, request, obj=None):
        return obj is None or not obj.bookings.exists()


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("booking_id", "user", "court", "start_time", "end_time", "total_amount", "status")
    list_filter = ("status", "court__facility")
    raw_id_fields = ("user", "court")
    date_hierarchy = "start_time"


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("booking", "amount", "payment_method", "payment_status", "paid_at")
    list_filter = ("payment_status", "payment_method")
    raw_id_fields = ("booking",)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("booking", "rating", "created_at")
    list_filter = ("rating",)
    raw_id_fields = ("booking",)
