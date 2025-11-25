from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from reporting.services import build_rollups_for_day

class Command(BaseCommand):
    help = "Build daily rollups for a date range (default last 180 days)."

    def add_arguments(self, parser):
        parser.add_argument("--start", type=str, help="YYYY-MM-DD")
        parser.add_argument("--end", type=str, help="YYYY-MM-DD")

    def handle(self, *args, **opts):
        def _parse(s):
            try: return date.fromisoformat(s) if s else None
            except Exception: return None

        end = _parse(opts.get("end")) or timezone.now().date()
        start = _parse(opts.get("start")) or (end - timedelta(days=180))

        d = start
        n = 0
        while d <= end:
            build_rollups_for_day(d)
            self.stdout.write(f"Rolled up {d}")
            d += timedelta(days=1); n += 1
        self.stdout.write(self.style.SUCCESS(f"Completed {n} days."))
