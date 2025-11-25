from django.core.management.base import BaseCommand
from program.models import MonthlySupply
from program.services import apply_gating_after_submission

class Command(BaseCommand):
    help = "Recompute ok_to_ship_next for all supplies based on compliance."

    def handle(self, *args, **opts):
        n = 0
        for ms in MonthlySupply.objects.select_related("compliance","enrollment").all().iterator():
            if hasattr(ms, "compliance"):
                apply_gating_after_submission(ms)
                n += 1
        self.stdout.write(self.style.SUCCESS(f"Recomputed gating for {n} supplies."))
