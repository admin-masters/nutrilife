import os
from datetime import timedelta
from django.utils import timezone
from celery import shared_task
from .models import MonthlySupply
from messaging.models import MessageLog
from messaging.services import send_compliance_reminder
from .services import compute_overdue_milestones, evaluate_enforcement_for_all_orgs
from accounts.models import Organization
@shared_task
def send_compliance_due_reminders():
    """
    Every 15 min:
    - Find supplies with delivered_on set
    - due at/earlier than now
    - compliance not yet submitted (NOT_SUBMITTED)
    - no reminder sent today for this supply
    Then queue a WhatsApp reminder.
    """
    now = timezone.now()
    since = now - timedelta(hours=24)

    qs = (MonthlySupply.objects
          .select_related("enrollment__student__primary_guardian", "enrollment__organization")
          .filter(delivered_on__isnull=False, compliance_due_at__lte=now,
                  compliance__status="NOT_SUBMITTED"))

    for s in qs:
        # Skip if no guardian phone
        g = getattr(s.enrollment.student, "primary_guardian", None)
        if not g or not g.phone_e164:
            continue
        # Skip if already reminded in last 24h
        already = MessageLog.objects.filter(
            related_supply=s, template_code="COMPLIANCE_REMINDER_V1",
            created_at__gte=since
        ).exists()
        if already:
            continue
        send_compliance_reminder(s)

@shared_task
def update_milestones_and_enforcement():
    compute_overdue_milestones()
    evaluate_enforcement_for_all_orgs()