from django.db import models
from django.utils import timezone
from accounts.models import Organization

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True

class Classroom(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="classrooms")
    grade = models.CharField(max_length=64)
    division = models.CharField(max_length=64, blank=True)

    class Meta:
        unique_together = (("organization", "grade", "division"),)
        indexes = [models.Index(fields=["organization", "grade", "division"])]

    def __str__(self):
        return f"{self.grade}{('-' + self.division) if self.division else ''}"

class Guardian(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="guardians")
    pid = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    full_name = models.CharField(max_length=255, null=True, blank=True, editable=False)
    phone_e164 = models.CharField(max_length=20, null=True, blank=True, editable=False)
    whatsapp_opt_in = models.BooleanField(default=True)
    preferred_language = models.CharField(max_length=8, default="en")

    class Meta:
        unique_together = (
            ("organization", "phone_e164"),  # legacy (phone will be NULL going forward)
            ("organization", "pid"),         # new linkage
        )
        indexes = [
            models.Index(fields=["organization", "pid"]),
            models.Index(fields=["organization", "full_name"]),
            models.Index(fields=["organization", "phone_e164"]),
        ]

    def __str__(self):
        if self.full_name:
            return self.full_name
        if self.pid:
            return f"Guardian {self.pid[:8]}"
        return f"Guardian {self.pk}"

class Student(TimeStampedModel):
    class Gender(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"
        OTHER = "O", "Other"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="students")
    classroom = models.ForeignKey(Classroom, on_delete=models.SET_NULL, null=True, blank=True, related_name="students")
    pid = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    first_name = models.CharField(max_length=128, null=True, blank=True, editable=False)
    last_name  = models.CharField(max_length=128, null=True, blank=True, editable=False)
    gender = models.CharField(max_length=1, choices=Gender.choices)
    dob = models.DateField(null=True, blank=True)
    student_code = models.CharField(max_length=64, blank=True)  # optional school id
    is_low_income = models.BooleanField(default=False)
    primary_guardian = models.ForeignKey("Guardian", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = (
            ("organization", "student_code"),
            ("organization", "pid"),
        )
        indexes = [
            models.Index(fields=["organization", "pid"]),
            models.Index(fields=["organization", "last_name", "first_name"]),
        ]

    @property
    def full_name(self) -> str:
        # Backwards-compatible display string WITHOUT storing real PII.
        if self.first_name or self.last_name:
            return f"{self.first_name or ''} {self.last_name or ''}".strip()
        if self.student_code:
            return f"Student {self.student_code}"
        if self.pid:
            return f"Student {self.pid[:8]}"
        return "Student"


class StudentGuardian(TimeStampedModel):
    class Relationship(models.TextChoices):
        MOTHER = "MOTHER", "Mother"
        FATHER = "FATHER", "Father"
        GUARDIAN = "GUARDIAN", "Guardian"

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="guardian_links")
    guardian = models.ForeignKey(Guardian, on_delete=models.CASCADE, related_name="student_links")
    relationship = models.CharField(max_length=16, choices=Relationship.choices, default=Relationship.GUARDIAN)

    class Meta:
        unique_together = (("student", "guardian"),)
