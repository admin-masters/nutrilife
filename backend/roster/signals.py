"""Roster signals.

Goal:
  When a new SCHOOL organization is created, automatically seed default
  Classroom rows (grades Nursery..12 + Other; sections A..Z + Other) so that
  teachers can immediately select grade/division in the "Add student" flow.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import Organization
from .services import ensure_default_classrooms_for_school


@receiver(post_save, sender=Organization)
def seed_default_classrooms_on_new_school(sender, instance: Organization, created: bool, **kwargs):
    if kwargs.get("raw"):
        # Skip fixture loading scenarios.
        return

    # Only seed once at creation time and only for SCHOOL orgs.
    if not created:
        return
    if instance.org_type != Organization.OrgType.SCHOOL:
        return

    # If org creation rolls back, we should not leave behind classrooms.
    transaction.on_commit(lambda: ensure_default_classrooms_for_school(instance))
