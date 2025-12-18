# Generated manually for Phase 2

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0002_organization_assistance_suspended_and_more"),
        ("program", "0004_screeningmilestone"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProductionOrder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("month", models.DateField(help_text="Use the 1st day of the month (e.g. 2025-01-01)")),
                ("total_packs", models.PositiveIntegerField(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("DRAFT", "Draft"),
                            ("SENT", "Sent to manufacturer"),
                            ("IN_PRODUCTION", "In production"),
                            ("SHIPPED", "Shipped to warehouse"),
                            ("RECEIVED", "Received at warehouse"),
                        ],
                        db_index=True,
                        default="DRAFT",
                        max_length=16,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                (
                    "created_at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_production_orders",
                        to="accounts.user",
                    ),
                ),
                (
                    "manufacturer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="production_orders",
                        to="accounts.organization",
                    ),
                ),
            ],
            options={
                "indexes": [models.Index(fields=["status", "month"], name="fulfillment__status_f8c2bb_idx")],
            },
        ),
        migrations.CreateModel(
            name="SchoolShipment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("month_index", models.PositiveSmallIntegerField(help_text="Program month index (1..6)")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PLANNED", "Planned"),
                            ("DISPATCHED", "Dispatched"),
                            ("DELIVERED", "Delivered"),
                        ],
                        db_index=True,
                        default="PLANNED",
                        max_length=16,
                    ),
                ),
                ("tracking_number", models.CharField(blank=True, max_length=128)),
                ("dispatched_at", models.DateTimeField(blank=True, null=True)),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_shipments",
                        to="accounts.user",
                    ),
                ),
                (
                    "logistics_partner",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="logistics_shipments",
                        to="accounts.organization",
                    ),
                ),
                (
                    "school",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="shipments", to="accounts.organization"),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["school", "status"], name="fulfillment__school_7c4fcf_idx"),
                    models.Index(fields=["status", "created_at"], name="fulfillment__status_9e05be_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="ShipmentItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("pack_qty", models.PositiveIntegerField(default=1)),
                (
                    "monthly_supply",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="shipment_item",
                        to="program.monthlysupply",
                    ),
                ),
                (
                    "shipment",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="fulfillment.schoolshipment"),
                ),
            ],
            options={
                "indexes": [models.Index(fields=["shipment"], name="fulfillment__shipment_0d1b40_idx")],
            },
        ),
    ]
