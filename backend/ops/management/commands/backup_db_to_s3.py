from django.core.management.base import BaseCommand
from ops.tasks import nightly_backup
class Command(BaseCommand):
    help = "Run a DB backup now and upload to S3."
    def handle(self, *args, **opts):
        res = nightly_backup()
        self.stdout.write(self.style.SUCCESS(str(res)))
