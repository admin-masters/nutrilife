# Generated manually for Phase 2

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_organization_assistance_suspended_and_more"),
        ("assist", "0002_approvalbatch_application_sapa_reviewed_at_and_more"),
        ("screening", "0001_initial"),
        ("grants", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="trigger_screening",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assistance_applications",
                to="screening.screening",
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="low_income_declared",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="application",
            name="income_verification_status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pending school verification"),
                    ("VERIFIED", "Verified"),
                    ("REJECTED", "Rejected"),
                ],
                db_index=True,
                default="PENDING",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="income_verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="application",
            name="income_verified_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="income_verified_applications",
                to="accounts.user",
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="income_verification_notes",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="approvalbatch",
            name="grant",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="approval_batches",
                to="grants.grant",
            ),
        ),
    ]
