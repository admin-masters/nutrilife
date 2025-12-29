from django.db import models
from django.utils import timezone
from accounts.models import Organization, User
from roster.models import Student

class Screening(models.Model):
    class RiskLevel(models.TextChoices):
        GREEN = "GREEN", "Green"
        YELLOW = "YELLOW", "Yellow"
        RED = "RED", "Red"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="screenings")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="screenings")
    teacher = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="screenings")
    screened_at = models.DateTimeField(default=timezone.now, db_index=True)

    gender = models.CharField(max_length=1, choices=Student.Gender.choices)
    age_years = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    age_months = models.PositiveIntegerField(null=True, blank=True)

    height_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    muac_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    bmi = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    baz = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    # Stores ALL Section A–F answers (raw) per screening
    answers = models.JSONField(default=dict, blank=True)

    risk_level = models.CharField(max_length=8, choices=RiskLevel.choices, default=RiskLevel.GREEN)
    red_flags = models.JSONField(default=list, blank=True)  # now holds all triggering reasons
    is_low_income_at_screen = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["student", "-screened_at"]),
            models.Index(fields=["organization", "risk_level"]),
        ]

    def __str__(self):
        return f"{self.student.full_name} @ {self.screened_at:%Y-%m-%d} ({self.risk_level})"
