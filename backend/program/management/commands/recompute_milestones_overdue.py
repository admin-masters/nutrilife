from django.core.management.base import BaseCommand
from program.services import compute_overdue_milestones, evaluate_enforcement_for_all_orgs

class Command(BaseCommand):
    help = "Mark overdue milestones and recompute enforcement for all orgs."

    def handle(self, *args, **kwargs):
        n = compute_overdue_milestones()
        evaluate_enforcement_for_all_orgs()
        self.stdout.write(self.style.SUCCESS(f"Marked {n} milestones overdue and evaluated enforcement."))
