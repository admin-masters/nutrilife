from django.core.management.base import BaseCommand
from program.models import Enrollment, ScreeningMilestone

class Command(BaseCommand):
    help = "Create 3- and 6-month milestones for enrollments missing them."

    def handle(self, *args, **kwargs):
        created = 0
        for e in Enrollment.objects.all().iterator():
            before = e.milestones.count()
            ScreeningMilestone.bootstrap_for_enrollment(e)
            created += (e.milestones.count() - before)
        self.stdout.write(self.style.SUCCESS(f"Created {created} milestones."))
