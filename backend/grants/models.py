from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.db.models import Sum
from django.utils import timezone

from accounts.models import Organization, User


class Grantor(models.Model):
    """An entity that funds supplementation.

    Optionally linked to an Organization so the grantor can log in and see dashboards.
    """

    organization = models.ForeignKey(
        Organization,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grantor_profile",
    )
    name = models.CharField(max_length=255)
    contact_email = models.EmailField(blank=True)
    contact_phone_e164 = models.CharField(max_length=32, blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name


class Grant(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PGC_APPROVED = "PGC_APPROVED", "PGC approved"
        ACTIVE = "ACTIVE", "Active"
        CLOSED = "CLOSED", "Closed"

    grantor = models.ForeignKey(Grantor, on_delete=models.CASCADE, related_name="grants")
    title = models.CharField(max_length=255)

    currency = models.CharField(max_length=8, default="INR")
    amount_committed = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_received = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.currency})"

    def allocated_total(self) -> Decimal:
        agg = self.allocations.aggregate(total=Sum("amount"))
        return agg["total"] or Decimal("0")

    def available_amount(self) -> Decimal:
        return (self.amount_received or Decimal("0")) - self.allocated_total()


class GrantAllocation(models.Model):
    """Tracks how a grant funded an enrollment."""

    grant = models.ForeignKey(Grant, on_delete=models.CASCADE, related_name="allocations")
    enrollment = models.ForeignKey("program.Enrollment", on_delete=models.CASCADE, related_name="grant_allocations")
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    allocated_at = models.DateTimeField(default=timezone.now, db_index=True)
    allocated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="grant_allocations")

    class Meta:
        unique_together = (("grant", "enrollment"),)
        indexes = [
            models.Index(fields=["allocated_at"]),
            models.Index(fields=["grant", "enrollment"]),
        ]

    def __str__(self) -> str:
        return f"{self.grant_id} -> enrollment {self.enrollment_id} ({self.amount})"
