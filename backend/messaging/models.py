from django.db import models
from django.utils import timezone
from accounts.models import Organization
import uuid

class MessageLog(models.Model):
    idempotency_key = models.CharField(
        max_length=36,
        unique=True,
        default=uuid.uuid4,   # Django will str() the UUID
        editable=False,
    )

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        SENT = "SENT", "Sent"
        DELIVERED = "DELIVERED", "Delivered"
        READ = "READ", "Read"
        FAILED = "FAILED", "Failed"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="messages")

    # NEW: store the student's PID for linkage/auditing
    pid = models.CharField(max_length=64, blank=True, default="", db_index=True, editable=False)

    # PII fields: must NOT be stored going forward
    to_phone_e164 = models.CharField(max_length=20, db_index=True, blank=True, default="", editable=False)
    payload = models.JSONField(blank=True, default=dict, editable=False)

    channel = models.CharField(max_length=16, default="whatsapp")
    template_code = models.CharField(max_length=64, blank=True)   # e.g., RED_EDU_V1 / RED_ASSIST_V1
    language = models.CharField(max_length=16, default="en")      # 'en' | 'hi' | 'local' (or ISO)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    provider_msg_id = models.CharField(max_length=128, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_title = models.CharField(max_length=255, blank=True)

    # linkage to operational event
    related_screening = models.ForeignKey("screening.Screening", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    related_supply = models.ForeignKey("program.MonthlySupply", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["scheduled_at", "status"]),
            models.Index(fields=["organization", "pid", "created_at"]),  # useful for audit lookups
        ]

    def __str__(self):
        pid_short = (self.pid or "")[:8]
        return f"{pid_short} {self.template_code} {self.status}"

    def save(self, *args, **kwargs):
        """
        Enforce that we NEVER persist phone or payload.
        Even if some code mistakenly sets these, we blank them here.
        """
        self.to_phone_e164 = ""
        self.payload = {}

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = list(set(update_fields) | {"to_phone_e164", "payload"})

        super().save(*args, **kwargs)