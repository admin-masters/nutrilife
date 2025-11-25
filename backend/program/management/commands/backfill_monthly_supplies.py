from django.core.management.base import BaseCommand
from program.models import Enrollment, MonthlySupply

class Command(BaseCommand):
    help = "Generate 6 monthly supplies (with QR tokens) for enrollments missing them."

    def handle(self, *args, **opts):
        created_total = 0
        for e in Enrollment.objects.all().iterator():
            before = e.supplies.count()
            MonthlySupply.bootstrap_for_enrollment(e)
            after = e.supplies.count()
            if after > before:
                self.stdout.write(self.style.SUCCESS(f"Enrollment {e.id}: created {after-before} supplies"))
                created_total += (after - before)
        self.stdout.write(self.style.SUCCESS(f"Done. Created {created_total} supplies."))
