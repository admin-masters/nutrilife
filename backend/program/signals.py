# backend/program/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from screening.models import Screening
from .models import Enrollment, ScreeningMilestone
from .services import evaluate_org_enforcement
from .models import MonthlySupply, ComplianceSubmission

@receiver(post_save, sender=MonthlySupply)
def ensure_compliance_row(sender, instance: MonthlySupply, created, **kwargs):
    """
    Ensure every MonthlySupply has a ComplianceSubmission row.
    Use get_or_create for idempotency (safe on bulk/backfills).
    """
    if created:
        ComplianceSubmission.objects.get_or_create(monthly_supply=instance)

@receiver(post_save, sender=Screening)
def _complete_milestone_on_screening(sender, instance: Screening, created, **kwargs):
    if not created:
        return
    student = instance.student
    org = instance.organization
    # For the student's ACTIVE enrollments, complete any due/overdue milestones whose due_on has passed.
    # NOTE: without this, an OVERDUE milestone can never be completed and a school will remain suspended.
    enrollments = Enrollment.objects.filter(student=student, organization=org, status=Enrollment.Status.ACTIVE)
    for e in enrollments:
        for m in e.milestones.filter(
            status__in=[ScreeningMilestone.Status.DUE, ScreeningMilestone.Status.OVERDUE],
            due_on__lte=instance.screened_at.date(),
        ):
            m.mark_completed(instance)
    # Re-evaluate enforcement (may unsuspend)
    evaluate_org_enforcement(org)