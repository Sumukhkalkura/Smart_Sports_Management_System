from django.contrib.auth import views as auth_views
from django.urls import path

from . import manage_views as m
from . import views
from .forms import EmailAuthenticationForm

urlpatterns = [
    path("", views.home, name="home"),
    path("accounts/register/", views.register, name="register"),
    path("accounts/login/", auth_views.LoginView.as_view(authentication_form=EmailAuthenticationForm,
                                                         redirect_authenticated_user=True), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("facilities/", views.facility_list, name="facility_list"),
    path("facilities/<int:facility_id>/", views.facility_detail, name="facility_detail"),
    path("courts/<int:court_id>/", views.court_detail, name="court_detail"),
    path("bookings/", views.booking_list, name="booking_list"),
    path("bookings/<int:booking_id>/", views.booking_detail, name="booking_detail"),
    path("bookings/<int:booking_id>/pay/", views.booking_pay, name="booking_pay"),
    path("bookings/<int:booking_id>/cancel/", views.booking_cancel, name="booking_cancel"),
    path("bookings/<int:booking_id>/review/", views.booking_review, name="booking_review"),
    # administrator area
    path("manage/", m.manage_home, name="manage_home"),
    path("manage/facilities/", m.facilities, name="manage_facilities"),
    path("manage/facilities/new/", m.facility_edit, name="manage_facility_new"),
    path("manage/facilities/<int:facility_id>/edit/", m.facility_edit, name="manage_facility_edit"),
    path("manage/facilities/<int:facility_id>/delete/", m.facility_delete, name="manage_facility_delete"),
    path("manage/courts/", m.courts, name="manage_courts"),
    path("manage/courts/new/", m.court_edit, name="manage_court_new"),
    path("manage/courts/<int:court_id>/edit/", m.court_edit, name="manage_court_edit"),
    path("manage/courts/<int:court_id>/toggle/", m.court_toggle, name="manage_court_toggle"),
    path("manage/sports/", m.sports, name="manage_sports"),
    path("manage/bookings/", m.bookings, name="manage_bookings"),
    path("manage/bookings/<int:booking_id>/action/", m.booking_action, name="manage_booking_action"),
    path("manage/bookings/action/", m.booking_action, {"booking_id": None}, name="manage_bookings_bulk"),
    path("manage/payments/", m.payments, name="manage_payments"),
    path("manage/payments/<int:booking_id>/received/", m.payment_received, name="manage_payment_received"),
    path("manage/reviews/", m.reviews, name="manage_reviews"),
    path("manage/maintenance/", m.maintenance, name="manage_maintenance"),
    path("manage/maintenance/delete/", m.maintenance_delete, name="manage_maintenance_delete"),
    path("manage/reports/", m.reports, name="reports"),
]
