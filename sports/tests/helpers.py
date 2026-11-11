from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from sports.models import Court, Facility, Sport, User
from sports.services import local_slot


def make_world():
    """A minimal consistent dataset: 1 facility, 1 sport, 2 courts, 2 customers, 1 admin."""
    facility = Facility.objects.create(name="Test Arena", city="Testville", phone="123", address="1 Test St")
    sport = Sport.objects.create(name="Badminton")
    court = Court.objects.create(facility=facility, sport=sport, court_name="Court 1", hourly_rate=Decimal("400.00"))
    court2 = Court.objects.create(facility=facility, sport=sport, court_name="Court 2", hourly_rate=Decimal("350.00"))
    alice = User.objects.create_user(email="alice@example.com", name="Alice", password="Secret#12345")
    bob = User.objects.create_user(email="bob@example.com", name="Bob", password="Secret#12345")
    admin = User.objects.create_superuser(email="admin@example.com", name="Admin", password="Secret#12345")
    return {"facility": facility, "sport": sport, "court": court, "court2": court2,
            "alice": alice, "bob": bob, "admin": admin}


def future_slot(days=3, hour=10, hours=1):
    return local_slot(timezone.localdate() + timedelta(days=days), hour, hours)
