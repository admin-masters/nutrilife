from django.db import migrations, models

def amber_to_yellow(apps, schema_editor):
    Screening = apps.get_model("screening", "Screening")
    Screening.objects.filter(risk_level="AMBER").update(risk_level="YELLOW")

class Migration(migrations.Migration):

    dependencies = [
        ("screening", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="screening",
            name="age_months",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="screening",
            name="muac_cm",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name="screening",
            name="bmi",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True),
        ),
        migrations.AddField(
            model_name="screening",
            name="baz",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True),
        ),
        migrations.AlterField(
            model_name="screening",
            name="risk_level",
            field=models.CharField(
                choices=[("GREEN", "Green"), ("YELLOW", "Yellow"), ("RED", "Red")],
                default="GREEN",
                max_length=8,
            ),
        ),
        migrations.RunPython(amber_to_yellow, reverse_code=migrations.RunPython.noop),
    ]
