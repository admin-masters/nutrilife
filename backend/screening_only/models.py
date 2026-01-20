from django.conf import settings
from django.db import models
from django.utils import timezone


class ScreeningSchoolProfile(models.Model):
    """
    Marks an Organization as enrolled in the Screening-only program and stores
    registration + authorization metadata required by the Screening Program flow.
    """
    organization = models.OneToOneField(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="screening_only_profile",
    )

    # Registration metadata (from the PDF's School Registration screen)
    district = models.CharField(max_length=128, blank=True, default="")
    address = models.CharField(max_length=255, blank=True, default="")

    principal_name = models.CharField(max_length=255, blank=True, default="")
    principal_email = models.EmailField()

    operator_name = models.CharField(max_length=255, blank=True, default="")
    operator_email = models.EmailField(blank=True, default="")

    # "Local language" used as the 3rd language in WhatsApp messages and video page.
    # Keep it flexible: you can store "mr", "te", etc. If not configured, fallback happens in code.
    local_language_code = models.CharField(max_length=12, blank=True, default="")

    onboarding_completed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    def is_authorized_admin_email(self, email: str) -> bool:
        if not email:
            return False
        e = email.strip().lower()
        pe = (self.principal_email or "").strip().lower()
        oe = (self.operator_email or "").strip().lower()
        return e == pe or (oe and e == oe)

    def __str__(self) -> str:
        return f"ScreeningSchoolProfile({self.organization_id})"


class ScreeningTermsAcceptance(models.Model):
    """
    Records one-time (versioned) acceptance of Screening Program terms/conditions
    per user, per organization, and per actor role (ORG_ADMIN / TEACHER).
    """
    class ActorRole(models.TextChoices):
        ORG_ADMIN = "ORG_ADMIN", "School Admin"
        TEACHER = "TEACHER", "Teacher"

    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="screening_only_terms_acceptances",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="screening_only_terms_acceptances",
    )
    actor_role = models.CharField(max_length=16, choices=ActorRole.choices)
    version = models.CharField(max_length=32, default="v1")
    accepted_at = models.DateTimeField(default=timezone.now)

    # Optional audit metadata
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        unique_together = ("organization", "user", "actor_role", "version")

    def __str__(self) -> str:
        return f"TermsAcceptance({self.organization_id},{self.user_id},{self.actor_role},{self.version})"
