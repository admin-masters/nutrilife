from django.db import models
from django.contrib.auth.models import AbstractUser
from .managers import UserManager

class Role(models.TextChoices):
    ORG_ADMIN = "ORG_ADMIN", "School Admin"
    TEACHER   = "TEACHER", "Teacher"
    SAPA_ADMIN = "SAPA_ADMIN", "SAPA Admin"
    INDITECH  = "INDITECH", "Inditech"
    SAPA_PGC = "SAPA_PGC", "SAPA Governing Committee"
    MANUFACTURER = "MANUFACTURER", "Manufacturer"
    LOGISTICS = "LOGISTICS", "Logistics Partner"

class User(AbstractUser):
    """
    Email-first auth; username removed. Users can belong to multiple orgs via OrgMembership.
    """
    username = None
    email = models.EmailField(unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email

class Organization(models.Model):
    class OrgType(models.TextChoices):
        SCHOOL = "SCHOOL", "School"
        NGO = "NGO", "NGO"
        SAPA = "SAPA", "SAPA"
        INDITECH = "INDITECH", "Inditech"
        
        MANUFACTURER = "MANUFACTURER", "Manufacturer"
        LOGISTICS = "LOGISTICS", "Logistics Partner"

    name = models.CharField(max_length=255)
    org_type = models.CharField(max_length=16, choices=OrgType.choices, default=OrgType.SCHOOL)
    city = models.CharField(max_length=128, blank=True)
    state = models.CharField(max_length=128, blank=True)
    country = models.CharField(max_length=64, blank=True)
    timezone = models.CharField(max_length=64, default="Asia/Kolkata")
    screening_link_token = models.SlugField(max_length=64, unique=True)  # used later for the teacher link
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    assistance_suspended = models.BooleanField(default=False)
    assistance_suspended_at = models.DateTimeField(null=True, blank=True)
    assistance_suspension_reason = models.CharField(max_length=255, blank=True)
    def __str__(self):
        return self.name

class OrgMembership(models.Model):
    """
    Many-to-many link: a user can have different roles in different organizations.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (("user", "organization", "role"),)
        indexes = [
            models.Index(fields=["organization", "role"]),
            models.Index(fields=["user", "organization"]),
        ]

    def __str__(self):
        return f"{self.user.email} @ {self.organization.name} ({self.role})"
