from django.core.management.base import BaseCommand
from django.utils.crypto import get_random_string
from accounts.models import User, Organization, OrgMembership, Role

class Command(BaseCommand):
    help = "Create superuser and a demo organization + admin membership."

    def add_arguments(self, parser):
        parser.add_argument("--superuser-email", default="admin@nutrilift.local")
        parser.add_argument("--superuser-password", default=None)
        parser.add_argument("--org-name", default="Demo School")
        parser.add_argument("--org-type", default="SCHOOL")

    def handle(self, *args, **opts):
        email = opts["superuser_email"]
        password = opts["superuser_password"] or get_random_string(16)
        org_name = opts["org_name"]
        org_type = opts["org_type"]

        # Superuser
        su, created = User.objects.get_or_create(email=email, defaults={"is_staff": True, "is_superuser": True})
        if created:
            su.set_password(password)
            su.save()
            self.stdout.write(self.style.SUCCESS(f"Created superuser {email} / {password}"))
        else:
            self.stdout.write(self.style.WARNING(f"Superuser {email} already exists"))

        # Demo org
        from django.utils.text import slugify
        token = slugify(org_name) + "-" + get_random_string(8)
        org, _ = Organization.objects.get_or_create(name=org_name, defaults={
            "org_type": org_type, "screening_link_token": token
        })
        self.stdout.write(self.style.SUCCESS(f"Organization ready: {org.name} (token={org.screening_link_token})"))

        # Membership for superuser (as School Admin)
        OrgMembership.objects.get_or_create(user=su, organization=org, role=Role.ORG_ADMIN)
        self.stdout.write(self.style.SUCCESS("Membership added (ORG_ADMIN)."))

        self.stdout.write(self.style.SUCCESS("Foundations bootstrap complete."))
