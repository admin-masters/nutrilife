from __future__ import annotations

from django.db import models, transaction
from django.utils import timezone

from accounts.models import Organization, User


class ProductionOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SENT = "SENT", "Sent to manufacturer"
        IN_PRODUCTION = "IN_PRODUCTION", "In production"
        SHIPPED = "SHIPPED", "Shipped to warehouse"
        RECEIVED = "RECEIVED", "Received at warehouse"

    manufacturer = models.ForeignKey(
        Organization,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="production_orders",
    )
    month = models.DateField(help_text="Use the 1st day of the month (e.g. 2025-01-01)")
    total_packs = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_production_orders")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["status", "month"])]

    def __str__(self) -> str:
        return f"PO {self.id} – {self.month:%Y-%m} ({self.total_packs} packs)"


class SchoolShipment(models.Model):
    class Status(models.TextChoices):
        PLANNED = "PLANNED", "Planned"
        DISPATCHED = "DISPATCHED", "Dispatched"
        DELIVERED = "DELIVERED", "Delivered"

    school = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="shipments")
    logistics_partner = models.ForeignKey(
        Organization,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logistics_shipments",
    )

    month_index = models.PositiveSmallIntegerField(help_text="Program month index (1..6)")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PLANNED, db_index=True)

    tracking_number = models.CharField(max_length=128, blank=True)

    dispatched_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_shipments")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Shipment {self.id} – {self.school.name} – M{self.month_index} – {self.status}"


class ShipmentItem(models.Model):
    shipment = models.ForeignKey(SchoolShipment, on_delete=models.CASCADE, related_name="items")
    monthly_supply = models.OneToOneField(
        "program.MonthlySupply",
        on_delete=models.CASCADE,
        related_name="shipment_item",
    )
    pack_qty = models.PositiveIntegerField(default=1)

    class Meta:
        indexes = [models.Index(fields=["shipment"])]

    def __str__(self) -> str:
        return f"ShipmentItem {self.id} – supply {self.monthly_supply_id}"
