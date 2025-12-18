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
            name="Grantor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("contact_email", models.EmailField(blank=True, max_length=254)),
                ("contact_phone_e164", models.CharField(blank=True, max_length=32)),
                ("created_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="grantor_profile",
                        to="accounts.organization",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Grant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("currency", models.CharField(default="INR", max_length=8)),
                ("amount_committed", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("amount_received", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("DRAFT", "Draft"),
                            ("PGC_APPROVED", "PGC approved"),
                            ("ACTIVE", "Active"),
                            ("CLOSED", "Closed"),
                        ],
                        db_index=True,
                        default="DRAFT",
                        max_length=16,
                    ),
                ),
                ("start_date", models.DateField(blank=True, null=True)),
                ("end_date", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "grantor",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="grants", to="grants.grantor"),
                ),
            ],
            options={
                "indexes": [models.Index(fields=["status", "created_at"], name="grants_gran_status_6df4d7_idx")],
            },
        ),
        migrations.CreateModel(
            name="GrantAllocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("allocated_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                (
                    "allocated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="grant_allocations",
                        to="accounts.user",
                    ),
                ),
                (
                    "enrollment",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="grant_allocations", to="program.enrollment"),
                ),
                (
                    "grant",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="allocations", to="grants.grant"),
                ),
            ],
            options={
                "unique_together": {("grant", "enrollment")},
                "indexes": [
                    models.Index(fields=["allocated_at"], name="grants_gran_allocat_0fe7b7_idx"),
                    models.Index(fields=["grant", "enrollment"], name="grants_gran_grant_i_4f9db2_idx"),
                ],
            },
        ),
    ]
