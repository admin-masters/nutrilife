from django.db import models
from django.utils import timezone
from accounts.models import Organization, User

class AuditLog(models.Model):
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="audit_logs")
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="audit_logs")
    action = models.CharField(max_length=64)  # e.g., SCREENING_CREATED, CSV_EXPORTED
    target_app = models.CharField(max_length=64, blank=True)
    target_model = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "action", "created_at"])]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"
