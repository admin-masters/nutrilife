from django.db import models
from django.utils import timezone
from accounts.models import Organization, User
from roster.models import Student, Guardian


class Application(models.Model):
    class Source(models.TextChoices):
        TEACHER = "TEACHER", "Teacher"
        PARENT  = "PARENT", "Parent"

    class Status(models.TextChoices):
        APPLIED   = "APPLIED", "Applied"
        FORWARDED = "FORWARDED", "Forwarded to SAPA"
        APPROVED  = "APPROVED", "Approved"
        REJECTED  = "REJECTED", "Rejected"
        CLOSED    = "CLOSED", "Closed"   # optional future use

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="applications")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="applications")
    guardian = models.ForeignKey(Guardian, on_delete=models.SET_NULL, null=True, blank=True, related_name="applications")

    source = models.CharField(max_length=16, choices=Source.choices, default=Source.PARENT)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.APPLIED)

    form_lang = models.CharField(max_length=12, default="en")
    form_data = models.JSONField(default=dict, blank=True)

    applied_at = models.DateTimeField(default=timezone.now)
    sapa_reviewed_at = models.DateTimeField(null=True, blank=True)  # NEW
    forwarded_at = models.DateTimeField(null=True, blank=True)
    forwarded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="forwarded_applications")

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["student", "status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.student.full_name} – {self.status}"

# from accounts.models import User

class ApprovalBatch(models.Model):
    class Method(models.TextChoices):
        ALL_PENDING = "ALL_PENDING", "All pending"
        TOP_N_ALPHA = "TOP_N_ALPHA", "Top-N alphabetic"

    organization = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE, related_name="approval_batches")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="approval_batches")
    method = models.CharField(max_length=16, choices=Method.choices)
    n_selected = models.PositiveIntegerField(null=True, blank=True)
    executed_at = models.DateTimeField(default=timezone.now)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "-executed_at"])]

    def __str__(self):
        return f"{self.organization.name} – {self.method} – {self.executed_at:%Y-%m-%d %H:%M}"


class BatchItem(models.Model):
    class Outcome(models.TextChoices):
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        SKIPPED  = "SKIPPED",  "Skipped"   # e.g., not in the Top-N

    approval_batch = models.ForeignKey(ApprovalBatch, on_delete=models.CASCADE, related_name="items")
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="batch_items")
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    note = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["outcome","created_at"])]
