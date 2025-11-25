import random, string
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from roster.models import Student, Guardian

def _rand_name():
    return "User" + "".join(random.choices(string.ascii_uppercase+string.digits, k=6))

class Command(BaseCommand):
    help = "Scramble PII (use ONLY on staging/dev)."

    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("Refusing to anonymize in non-DEBUG environment.")
        for s in Student.objects.all().iterator():
            s.first_name = _rand_name(); s.last_name = ""
            s.save(update_fields=["first_name","last_name"])
        for g in Guardian.objects.all().iterator():
            if g.phone_e164:
                g.phone_e164 = "+91" + "".join(random.choices("0123456789", k=8))
            g.full_name = _rand_name()
            g.save(update_fields=["full_name","phone_e164"])
        self.stdout.write(self.style.SUCCESS("Anonymized students & guardians."))
