from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone

from .models import Court, Facility, Payment, Sport, User
from .services import CLOSE_HOUR, MAX_HOURS, OPEN_HOUR


class RegisterForm(forms.ModelForm):
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ["name", "email"]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Passwords do not match.")
        if p1:
            candidate = User(name=data.get("name", ""), email=data.get("email", ""))
            try:
                validate_password(p1, candidate)
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return data

    def save(self, commit=True):
        return User.objects.create_user(email=self.cleaned_data["email"], name=self.cleaned_data["name"],
                                        password=self.cleaned_data["password1"])


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autofocus": True}))


HOUR_CHOICES = [(h, f"{h:02d}:00") for h in range(OPEN_HOUR, CLOSE_HOUR)]


class BookingForm(forms.Form):
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    start_hour = forms.TypedChoiceField(choices=HOUR_CHOICES, coerce=int, label="Start time")
    hours = forms.TypedChoiceField(choices=[(h, f"{h} hour{'s' if h > 1 else ''}") for h in range(1, MAX_HOURS + 1)],
                                   coerce=int, label="Duration")

    def clean(self):
        data = super().clean()
        if data.get("date") and data["date"] < timezone.localdate():
            self.add_error("date", "Pick today or a future date.")
        if data.get("start_hour") is not None and data.get("hours"):
            if data["start_hour"] + data["hours"] > CLOSE_HOUR:
                self.add_error("hours", f"The booking must end by {CLOSE_HOUR:02d}:00.")
        return data


class PaymentForm(forms.Form):
    payment_method = forms.ChoiceField(choices=Payment.Method.choices)
    simulate_failure = forms.BooleanField(required=False, label="Simulate a declined payment (demo)")


class ReviewForm(forms.Form):
    rating = forms.TypedChoiceField(choices=[(i, f"{i} ★") for i in range(5, 0, -1)], coerce=int)
    comment = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False, max_length=1000)


# ------------------------------------------------------------- admin forms
class FacilityForm(forms.ModelForm):
    class Meta:
        model = Facility
        fields = ["name", "city", "phone", "address"]


class CourtForm(forms.ModelForm):
    class Meta:
        model = Court
        fields = ["facility", "sport", "court_name", "hourly_rate", "is_active"]


class SportForm(forms.ModelForm):
    class Meta:
        model = Sport
        fields = ["name"]


class MaintenanceForm(forms.Form):
    court = forms.ModelChoiceField(queryset=Court.objects.select_related("facility").order_by("facility__name", "court_name"))
    start_time = forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))
    end_time = forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))
    reason = forms.CharField(max_length=255)
    cancel_conflicts = forms.BooleanField(required=False, label="Cancel (and refund) conflicting bookings")

    def clean(self):
        data = super().clean()
        if data.get("start_time") and data.get("end_time") and data["end_time"] <= data["start_time"]:
            self.add_error("end_time", "End time must be after start time.")
        return data
